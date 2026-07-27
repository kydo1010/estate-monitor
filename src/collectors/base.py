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
        return []

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
        부산 16개 구·군 × 지정 월 전체 수집 → DB 저장.
        months: ['202606', '202605', ...] 형태. None이면 당월만.
        """
        from src.config import BUSAN_DISTRICT_CODES
        from src.db import get_session, init_db

        init_db()

        if months is None:
            today = date.today()
            months = [today.strftime("%Y%m")]

        total_saved = 0
        for lawd_cd, district in BUSAN_DISTRICT_CODES.items():
            for ym in months:
                records = self.fetch_one_month(lawd_cd, ym)
                if records:
                    with get_session() as session:
                        saved = self.save(session, records)
                        session.commit()
                    total_saved += saved
                    log.info(f"{district} {ym}: {saved}건 저장")
                else:
                    log.info(f"{district} {ym}: 데이터 없음")
                time.sleep(REQUEST_DELAY_SEC)

        log.info(f"수집 완료 — 총 {total_saved}건 저장")