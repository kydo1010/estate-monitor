"""
src/collectors/base.py
국토부 실거래가 API 공통 베이스 — 모든 수집기가 상속
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

log = logging.getLogger(__name__)

# 국토부 API 공통 파라미터
DEFAULT_NUM_OF_ROWS = 1000
REQUEST_DELAY_SEC   = 1.0   # 구별 순회 시 호출 간격 (과부하 방지)
MAX_RETRIES         = 3
TIMEOUT_SEC         = 30    # 타임아웃 (기존 15 → 30)

# (구·군,월) 조합이 이 횟수만큼 연속으로 "응답 자체를 못 받음"이면 run()을
# 조기 종료한다 — API 백엔드가 통째로 막힌 상황(2026-08 MOLIT 포트80 장애 등)에서
# 351개 조합 전부를 조합당 약 59초(재시도 3회 타임아웃+백오프)씩 순회하며
# 몇 시간을 낭비하는 걸 막기 위함. 진짜 "데이터 없음"(정상 응답, 빈 목록)은
# 여기 포함되지 않는다 — fetch_one_month가 그 경우 예외 없이 빈 리스트를
# 반환하므로 카운터가 리셋된다.
CIRCUIT_BREAKER_THRESHOLD = 10


class MolitConnectionFailure(Exception):
    """fetch_one_month이 MAX_RETRIES를 전부 소진하도록 응답을 한 번도 못 받았을 때.

    API가 정상 응답했는데 데이터가 없는 경우([])와 구분하기 위한 신호다 —
    이 예외가 나야만 run()의 연속 실패 카운터가 올라간다.
    """


class MolitBaseCollector:
    """
    국토부 실거래가 API 공통 수집기 베이스.

    하위 클래스에서 반드시 구현:
        - endpoint (str): API URL
        - api_key  (str): 서비스키
        - parse_item(item_el) -> dict: XML item 파싱
        - save(session, records): DB 저장
    """

    endpoint: str = ""
    api_key:  str = ""

    def fetch_one_month(self, lawd_cd: str, deal_ymd: str) -> list[dict]:
        """
        특정 지역·월 데이터 1회 조회.
        lawd_cd  : 법정동 코드 앞 5자리 (예: '26350')
        deal_ymd : 계약년월 6자리      (예: '202606')

        MAX_RETRIES를 전부 소진하도록 응답을 한 번도 못 받으면 빈 리스트가 아니라
        MolitConnectionFailure를 던진다 — run()의 회로차단기가 "데이터 없음"(정상
        응답)과 "연결 자체가 안 됨"을 구분해야 하기 때문이다.
        """
        params = {
            "serviceKey": self.api_key,
            "LAWD_CD":    lawd_cd,
            "DEAL_YMD":   deal_ymd,
            "numOfRows":  DEFAULT_NUM_OF_ROWS,
            "pageNo":     1,
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(self.endpoint, params=params, timeout=15)
                resp.raise_for_status()
                return self._parse_xml(resp.text)
            except requests.RequestException as e:
                log.warning(f"[{attempt}/{MAX_RETRIES}] 요청 실패 {lawd_cd}/{deal_ymd}: {e}")
                time.sleep(2 ** attempt)
        log.error(f"최대 재시도 초과: {lawd_cd}/{deal_ymd}")
        raise MolitConnectionFailure(f"{lawd_cd}/{deal_ymd}: {MAX_RETRIES}회 재시도 모두 실패")

    def _parse_xml(self, xml_text: str) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
            items = root.findall(".//item")
            return [self.parse_item(item) for item in items]
        except ET.ParseError as e:
            log.error(f"XML 파싱 오류: {e}")
            return []

    def parse_item(self, item_el) -> dict:
        raise NotImplementedError

    def save(self, session, records: list[dict]) -> int:
        raise NotImplementedError

    def _text(self, el, tag: str, default: str = "") -> str:
        node = el.find(tag)
        return node.text.strip() if node is not None and node.text else default

    def _int(self, el, tag: str) -> int | None:
        val = self._text(el, tag).replace(",", "")
        return int(val) if val.lstrip("-").isdigit() else None

    def _float(self, el, tag: str) -> float | None:
        val = self._text(el, tag).replace(",", "")
        try:
            return float(val)
        except ValueError:
            return None

    def run(self, months: list[str] | None = None) -> None:
        """
        부산·울산·경남 전체 시·군·구 × 지정 월 전체 수집 → DB 저장.
        months: ['202606', '202605', ...] 형태. None이면 당월만.
        """
        from src.config import (
            ALL_DISTRICT_CODES, BUSAN_DISTRICT_CODES,
            ULSAN_DISTRICT_CODES, GYEONGNAM_DISTRICT_CODES,
        )
        from src.db import get_session, init_db

        init_db()

        region_map = {
            **{k: "부산" for k in BUSAN_DISTRICT_CODES},
            **{k: "울산" for k in ULSAN_DISTRICT_CODES},
            **{k: "경남" for k in GYEONGNAM_DISTRICT_CODES},
        }

        if months is None:
            today = date.today()
            months = [today.strftime("%Y%m")]

        # district-major, month-minor 순회 순서는 기존 중첩 for문과 동일 —
        # 회로차단기가 "남은 조합 수"를 계산하려면 인덱스가 필요해 미리 펼쳐 둔다.
        combos = [(lawd_cd, ym) for lawd_cd in ALL_DISTRICT_CODES for ym in months]
        total_combos = len(combos)

        total_saved = 0
        consecutive_failures = 0
        circuit_broken = False

        for idx, (lawd_cd, ym) in enumerate(combos):
            district = ALL_DISTRICT_CODES.get(lawd_cd, lawd_cd)
            try:
                records = self.fetch_one_month(lawd_cd, ym)
            except MolitConnectionFailure:
                consecutive_failures += 1
                if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                    remaining = total_combos - idx - 1
                    log.error(
                        f"MOLIT API 응답 없음 — {CIRCUIT_BREAKER_THRESHOLD}회 연속 실패로 "
                        f"조기 종료, 남은 {remaining}개 조합 스킵"
                    )
                    circuit_broken = True
                    break
                time.sleep(REQUEST_DELAY_SEC)
                continue

            consecutive_failures = 0
            if records:
                for record in records:
                    record["region"] = region_map.get(lawd_cd, "")
                with get_session() as session:
                    saved = self.save(session, records)
                    session.commit()
                total_saved += saved
                log.info(f"{district} {ym}: {saved}건 저장")
            else:
                log.info(f"{district} {ym}: 데이터 없음")
            time.sleep(REQUEST_DELAY_SEC)

        if circuit_broken:
            log.info(f"수집 중단(회로차단) — 총 {total_saved}건 저장")
        else:
            log.info(f"수집 완료 — 총 {total_saved}건 저장")