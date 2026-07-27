"""
src/collectors/cheongyak.py
한국부동산원 청약홈 APT 분양정보 수집기 (부산 코드: 600)

실행:
    python -m src.collectors.cheongyak
"""

import logging
from datetime import date

import requests

from src.config import CHEONGYAK_API_KEY
from src.db import BuildingPermit, get_session, init_db

log = logging.getLogger(__name__)

BASE_URL  = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
BUSAN_CODE = "600"


def fetch_page(endpoint: str, page: int, per_page: int = 100) -> dict:
    # cond 파라미터는 requests가 이중 인코딩하므로 URL을 직접 조합
    url = (
        f"{BASE_URL}/{endpoint}"
        f"?serviceKey={CHEONGYAK_API_KEY}"
        f"&page={page}"
        f"&perPage={per_page}"
        f"&cond%5BSUBSCRPT_AREA_CODE%3A%3AEQ%5D={BUSAN_CODE}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all(endpoint: str) -> list[dict]:
    first = fetch_page(endpoint, page=1)
    total = first.get("totalCount", 0)
    items = first.get("data", [])
    log.info(f"{endpoint}: 전체 {total}건 중 {len(items)}건 수신")

    page = 2
    while len(items) < total:
        batch = fetch_page(endpoint, page=page).get("data", [])
        if not batch:
            break
        items.extend(batch)
        page += 1

    return items


def save(session, items: list[dict], property_type: str = "아파트") -> int:
    saved = 0
    for r in items:
        # 공급지역명에서 구명 추출 (예: "부산 해운대구" → "해운대구")
        area_nm  = r.get("SUBSCRPT_AREA_CODE_NM", "")
        address  = r.get("HSSPLY_ADRES", "")
        district = ""
        for part in address.replace("부산광역시", "").split():
            if part.endswith("구") or part.endswith("군"):
                district = part
                break
        if not district:
            district = area_nm

        # 모집공고일
        announce_date = r.get("RCRIT_PBLANC_DE", "")
        try:
            permit_date = date.fromisoformat(announce_date)
        except (ValueError, TypeError):
            permit_date = date.today()

        household_count = r.get("TOT_SUPLY_HSHLDCO")
        try:
            household_count = int(household_count) if household_count else None
        except (ValueError, TypeError):
            household_count = None

        house_nm     = r.get("HOUSE_NM", "")
        developer    = r.get("BSNS_MBY_NM", "")    # 시행사
        contractor   = r.get("CNSTRCT_ENTRPS_NM", "") # 시공사

        exists = session.query(BuildingPermit).filter_by(
            district=district,
            permit_date=permit_date,
            developer=developer,
            household_count=household_count,
        ).first()

        if not exists:
            session.add(BuildingPermit(
                district=district,
                permit_date=permit_date,
                household_count=household_count,
                developer=developer,
                contractor=contractor or house_nm,
            ))
            saved += 1
    return saved


def run() -> None:
    init_db()
    total_saved = 0

    # APT 분양정보
    apt_items = fetch_all("getAPTLttotPblancDetail")
    if apt_items:
        with get_session() as session:
            saved = save(session, apt_items, "아파트")
            session.commit()
        total_saved += saved
        log.info(f"APT 분양정보: {saved}건 저장")

    # 오피스텔/도시형 분양정보
    offi_items = fetch_all("getUrbtyOfctlLttotPblancDetail")
    if offi_items:
        with get_session() as session:
            saved = save(session, offi_items, "오피스텔")
            session.commit()
        total_saved += saved
        log.info(f"오피스텔/도시형 분양정보: {saved}건 저장")

    # APT 잔여세대
    remndr_items = fetch_all("getRemndrLttotPblancDetail")
    if remndr_items:
        with get_session() as session:
            saved = save(session, remndr_items, "잔여세대")
            session.commit()
        total_saved += saved
        log.info(f"APT 잔여세대: {saved}건 저장")

    log.info(f"청약홈 분양정보 저장 완료: 총 {total_saved}건")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run()