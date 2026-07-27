"""
src/collectors/building_permit.py
국토교통부 건축HUB 주택인허가 기본개요 수집기

실행:
    python -m src.collectors.building_permit
    python -m src.collectors.building_permit --sigungu 26350  ← 해운대구만
"""

import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import date

import requests

from src.config import BUILDING_PERMIT_API_KEY, BUSAN_DISTRICT_CODES
from src.db import BuildingPermit, get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT = "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo"


def fetch(sigungu_cd: str, page: int = 1, num: int = 100) -> list[dict]:
    params = {
        "serviceKey": BUILDING_PERMIT_API_KEY,
        "sigunguCd":  sigungu_cd,
        "pageNo":     page,
        "numOfRows":  num,
    }
    resp = requests.get(ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()

    root  = ET.fromstring(resp.text)
    items = root.findall(".//item")

    def t(el, tag):
        node = el.find(tag)
        return node.text.strip() if node is not None and node.text else ""

    records = []
    for el in items:
        # apprvDay: 인허가일 (YYYYMMDD)
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
            "sigungu_cd":       t(el, "sigunguCd"),
            "bld_nm":           t(el, "bldNm"),
            "plat_plc":         t(el, "platPlc"),
            "tot_hhld_cnt":     tot_hhld,
            "permit_date":      permit_date,
            "stcns_day":        t(el, "stcnsDay"),   # 착공일
            "use_inspt_day":    t(el, "useInsptDay"), # 사용검사일
        })
    return records


def save(session, records: list[dict], district: str) -> int:
    saved = 0
    for r in records:
        if not r.get("permit_date"):
            continue
        exists = session.query(BuildingPermit).filter_by(
            district=district,
            permit_date=r["permit_date"],
            household_count=r["tot_hhld_cnt"],
            contractor=r["bld_nm"],
        ).first()
        if not exists:
            session.add(BuildingPermit(
                district=district,
                permit_date=r["permit_date"],
                household_count=r["tot_hhld_cnt"],
                developer=r["plat_plc"],   # 주소를 시행사 컬럼에 임시 저장
                contractor=r["bld_nm"],    # 건물명
            ))
            saved += 1
    return saved


def run(sigungu_cds: list[str] | None = None) -> None:
    init_db()
    targets = sigungu_cds or list(BUSAN_DISTRICT_CODES.keys())
    total_saved = 0

    for cd in targets:
        district = BUSAN_DISTRICT_CODES.get(cd, cd)
        try:
            records = fetch(cd)
            if records:
                with get_session() as session:
                    saved = save(session, records, district)
                    session.commit()
                total_saved += saved
                log.info(f"{district}: {saved}건 저장 (수신 {len(records)}건)")
            else:
                log.info(f"{district}: 데이터 없음")
        except Exception as e:
            log.error(f"{district} 수집 실패: {e}")

    log.info(f"인허가 수집 완료 — 총 {total_saved}건 저장")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="건축HUB 주택인허가 수집")
    parser.add_argument("--sigungu", nargs="+",
                        help="수집할 시군구 코드 (예: 26350 26230). 미입력 시 부산 전체")
    args = parser.parse_args()
    run(sigungu_cds=args.sigungu)
