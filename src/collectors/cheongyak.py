"""
src/collectors/cheongyak.py
한국부동산원 청약홈 APT 분양정보 수집기 (부산 필터)

실행:
    python -m src.collectors.cheongyak
"""

import logging
from datetime import date, timedelta

import requests

from src.config import CHEONGYAK_API_KEY
from src.db import BuildingPermit, get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"


def fetch_busan(page: int = 1, per_page: int = 100) -> dict:
    params = {
        "serviceKey": CHEONGYAK_API_KEY,
        "page":       page,
        "perPage":    per_page,
        "cond[SIDO_NM::EQ]": "부산광역시",
    }
    resp = requests.get(ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_all_busan() -> list[dict]:
    """전체 페이지 순회"""
    first  = fetch_busan(page=1, per_page=100)
    total  = first.get("totalCount", 0)
    items  = first.get("data", [])

    page = 2
    while len(items) < total:
        data = fetch_busan(page=page, per_page=100)
        batch = data.get("data", [])
        if not batch:
            break
        items.extend(batch)
        page += 1

    log.info(f"청약홈 부산 분양정보 {len(items)}건 수신")
    return items


def save(session, items: list[dict]) -> int:
    saved = 0
    for r in items:
        # 구·군명 추출 (예: "부산광역시 해운대구" → "해운대구")
        region = r.get("SUBSCRPT_AREA_CODE_NM", "")
        district = region.split()[-1] if region else ""

        # 모집공고일 → permit_date
        announce_date = r.get("RCRIT_PBLANC_DE", "")
        try:
            permit_date = date.fromisoformat(announce_date)
        except (ValueError, TypeError):
            permit_date = date.today()

        household_count = r.get("TOT_SUPLY_HSHLDCO")
        try:
            household_count = int(household_count) if household_count else None
        except ValueError:
            household_count = None

        complex_name = r.get("HOUSE_NM", "")

        # 중복 체크
        exists = session.query(BuildingPermit).filter_by(
            district=district,
            permit_date=permit_date,
            developer=r.get("BSNS_MBY_NM", ""),
            household_count=household_count,
        ).first()

        if not exists:
            session.add(BuildingPermit(
                district=district,
                permit_date=permit_date,
                household_count=household_count,
                developer=r.get("BSNS_MBY_NM", ""),    # 사업주체
                contractor=complex_name,                  # 단지명을 시공사 컬럼에 임시 저장
            ))
            saved += 1
    return saved


def run() -> None:
    init_db()
    items = fetch_all_busan()
    with get_session() as session:
        saved = save(session, items)
        session.commit()
    log.info(f"청약홈 분양정보 저장 완료: 신규 {saved}건")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run()
