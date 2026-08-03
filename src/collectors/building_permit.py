"""
src/collectors/building_permit.py
국토교통부 건축HUB 주택인허가 기본개요 수집기
(sigunguCd + bjdongCd 동 단위 순회 — 부산·울산·경남 39개 시·군·구)

실행:
    python -m src.collectors.building_permit
    python -m src.collectors.building_permit --sigungu 26350  ← 해운대구만
"""

import argparse
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

from src.config import (
    BUILDING_PERMIT_API_KEY,
    BUSAN_DISTRICT_CODES, BUSAN_DONG_CODES,
    ULSAN_DISTRICT_CODES, ULSAN_DONG_CODES,
    GYEONGNAM_DISTRICT_CODES, GYEONGNAM_DONG_CODES,
    ALL_DISTRICT_CODES,
)
from src.db import BuildingPermit, get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT      = "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo"
REQUEST_DELAY = 0.3   # 동별 호출 간격


def fetch(sigungu_cd: str, bjdong_cd: str) -> list[dict]:
    params = {
        "serviceKey": BUILDING_PERMIT_API_KEY,
        "sigunguCd":  sigungu_cd,
        "bjdongCd":   bjdong_cd,
        "numOfRows":  100,
        "pageNo":     1,
    }
    resp = requests.get(ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()

    root  = ET.fromstring(resp.text)
    items = root.findall(".//item")

    def t(el, tag):
        node = el.find(tag)
        return node.text.strip() if node is not None and node.text else ""

    records = []
    for el in items:
        approv_day = t(el, "apprvDay")
        try:
            permit_date = date(
                int(approv_day[:4]),
                int(approv_day[4:6]),
                int(approv_day[6:8]),
            )
        except (ValueError, IndexError):
            permit_date = None

        tot_hhld = t(el, "totHhldCnt")
        try:
            tot_hhld = int(tot_hhld) if tot_hhld else None
        except ValueError:
            tot_hhld = None

        records.append({
            "bld_nm":      t(el, "bldNm"),
            "plat_plc":    t(el, "platPlc"),
            "tot_hhld":    tot_hhld,
            "permit_date": permit_date,
            "stcns_day":   t(el, "stcnsDay"),
        })
    return records


def save(session, records: list[dict], region: str, district: str) -> int:
    saved = 0
    for r in records:
        if not r.get("permit_date"):
            continue
        # uq_permit_dedup(region, district, permit_date, developer, household_count)와
        # 정확히 같은 컬럼 조합으로 필터링해야 한다 — 예전엔 contractor로 필터링해서
        # DB 제약(developer 기준)과 어긋나 IntegrityError로 동 배치 전체가 롤백되는
        # 사고가 있었다(dedup 체크와 실제 제약이 서로 다른 컬럼을 봤기 때문).
        exists = session.query(BuildingPermit).filter_by(
            region=region,
            district=district,
            permit_date=r["permit_date"],
            developer=r["plat_plc"],
            household_count=r["tot_hhld"],
        ).first()
        if not exists:
            session.add(BuildingPermit(
                region=region,
                district=district,
                permit_date=r["permit_date"],
                household_count=r["tot_hhld"],
                developer=r["plat_plc"],
                contractor=r["bld_nm"],
            ))
            saved += 1
    return saved


def _region_lookup(sgg_cd: str) -> tuple[str, str, dict]:
    """시군구코드 접두어(26/31/48)로 (지역, 구·군명, 법정동코드맵)을 판별."""
    if sgg_cd.startswith("26"):
        return "부산", BUSAN_DISTRICT_CODES.get(sgg_cd, sgg_cd), BUSAN_DONG_CODES.get(sgg_cd, {})
    if sgg_cd.startswith("31"):
        return "울산", ULSAN_DISTRICT_CODES.get(sgg_cd, sgg_cd), ULSAN_DONG_CODES.get(sgg_cd, {})
    if sgg_cd.startswith("48"):
        district = GYEONGNAM_DISTRICT_CODES.get(sgg_cd, sgg_cd)
        # 주의: 48121(창원시 의창구)은 config.py에 실제 커버리지 그대로
        # "창원시 의창구"로 정확히 등록돼 있다 — 이 LAWD 코드는 창원시 전체가
        # 아니라 의창구만 가리킨다(scripts/migrate_changwon_district.py 참고).
        # 이 컬렉터가 실제로 수집하는 데이터도 여전히 의창구뿐이지만, 저장 시
        # district만 "창원시"로 합친다 — cheongyak.py가 주소 파싱으로 별도
        # 수집하는 창원시 나머지 4개 하위구(성산구·마산합포구·마산회원구·진해구)
        # 데이터와 표시를 통일하기 위함이다. 즉 "창원시"라는 라벨이 이 컬렉터의
        # 실제 커버리지(의창구뿐)보다 넓어 보일 수 있으니, 이 컬렉터를 창원시
        # 전역 커버리지가 필요한 곳에 재사용할 때는 반드시 이 사실을 확인할 것.
        if district == "창원시 의창구":
            district = "창원시"
        return "경남", district, GYEONGNAM_DONG_CODES.get(sgg_cd, {})
    return "", sgg_cd, {}


def run(sigungu_cds: list[str] | None = None) -> None:
    init_db()
    targets = sigungu_cds or list(ALL_DISTRICT_CODES.keys())
    total_saved = 0

    for sgg_cd in targets:
        region, district, dong_codes = _region_lookup(sgg_cd)
        gu_saved   = 0

        for bjdong_cd, dong_nm in dong_codes.items():
            try:
                records = fetch(sgg_cd, bjdong_cd)
                if records:
                    with get_session() as session:
                        saved = save(session, records, region, district)
                        session.commit()
                    gu_saved   += saved
                    total_saved += saved
            except Exception as e:
                log.warning(f"[{region}] {district} {dong_nm} 실패: {e}")
            time.sleep(REQUEST_DELAY)

        log.info(f"[{region}] {district}: {gu_saved}건 저장 ({len(dong_codes)}개 동 순회)")

    log.info(f"인허가 수집 완료 — 총 {total_saved}건 저장")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="건축HUB 주택인허가 수집")
    parser.add_argument("--sigungu", nargs="+",
                        help="수집할 시군구 코드 (예: 26350 26230). 미입력 시 부산·울산·경남 전체")
    args = parser.parse_args()
    run(sigungu_cds=args.sigungu)