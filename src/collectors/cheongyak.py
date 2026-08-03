"""
src/collectors/cheongyak.py
한국부동산원 청약홈 APT 분양정보 수집기 (부산·울산·경남 3개 지역)

SUBSCRPT_AREA_CODE는 법정동 시도코드(26/31/48)가 아니라 청약홈 자체 지역코드다.
실제 API 응답을 지역 필터 없이 조회해 확인한 값: 부산 600, 울산 680, 경남 621
(REGION_CODES 참고).

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
REGION_CODES = {"부산": "600", "울산": "680", "경남": "621"}

ENDPOINTS = [
    ("getAPTLttotPblancDetail", "아파트", "APT 분양정보"),
    ("getUrbtyOfctlLttotPblancDetail", "오피스텔", "오피스텔/도시형 분양정보"),
    ("getRemndrLttotPblancDetail", "잔여세대", "APT 잔여세대"),
]

# 창원시 5개 하위구 → "창원시" 통일 저장 대상 (save() 참고)
CHANGWON_SUB_DISTRICTS = {"의창구", "성산구", "마산합포구", "마산회원구", "진해구", "창원시 의창구"}

# "OO지구" 오염값 → 실제 소속 시·군. developer/contractor 원문과 config.py의
# GYEONGNAM_DONG_CODES(정부 법정동 코드) 대조로 확인된, 지명 자체가 고유한
# 것만 등록한다. "공공주택지구"·"공급촉진지구"처럼 LH 사업유형을 가리키는
# 일반 명칭은 특정 지역명이 아니라 전국 어디서나 나올 수 있어 여기 넣지
# 않는다(과거 사례 하나만 보고 일반화하면 다른 지역 데이터를 잘못 덮어씀) —
# area_nm("경남" 등) 폴백으로 남겨 두고 필요하면 건별로 수동 확인한다.
DISTRICT_OVERRIDE = {
    "양산사송택지개발지구": "양산시",
    "사송지구": "양산시",
    "신문1지구": "김해시",
    "장유신문지구": "김해시",
    "내덕지구": "김해시",
    "부북지구": "밀양시",
}


def fetch_page(endpoint: str, area_code: str, page: int, per_page: int = 100) -> dict:
    # cond 파라미터는 requests가 이중 인코딩하므로 URL을 직접 조합
    url = (
        f"{BASE_URL}/{endpoint}"
        f"?serviceKey={CHEONGYAK_API_KEY}"
        f"&page={page}"
        f"&perPage={per_page}"
        f"&cond%5BSUBSCRPT_AREA_CODE%3A%3AEQ%5D={area_code}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all(endpoint: str, area_code: str) -> list[dict]:
    first = fetch_page(endpoint, area_code, page=1)
    total = first.get("totalCount", 0)
    items = first.get("data", [])
    log.info(f"{endpoint} (area={area_code}): 전체 {total}건 중 {len(items)}건 수신")

    page = 2
    while len(items) < total:
        batch = fetch_page(endpoint, area_code, page=page).get("data", [])
        if not batch:
            break
        items.extend(batch)
        page += 1

    return items


def save(session, items: list[dict], region: str, property_type: str = "아파트") -> int:
    saved = 0
    for r in items:
        # 공급지역명에서 구명 추출 (예: "부산 해운대구" → "해운대구")
        area_nm  = r.get("SUBSCRPT_AREA_CODE_NM", "")
        address  = r.get("HSSPLY_ADRES", "")
        tokens = (address.replace("부산광역시", "")
                         .replace("울산광역시", "")
                         .replace("경상남도", "")
                         .split())
        district = ""
        for part in tokens:
            # "OO지구"(택지개발지구 등)도 "구"로 끝나 구·군으로 오인식되므로 제외.
            # 실제 자치구·자치군 이름은 "~지구"로 끝나지 않는다.
            if part.endswith("지구"):
                continue
            if part.endswith("구") or part.endswith("군"):
                district = part
                break
        if not district:
            # 위에서 스킵한 "OO지구" 토큰 중 실제 소속 시·군이 확인된 것만 그
            # 시·군명으로 대체한다(developer/contractor 원문 및 config.py 법정동
            # 코드 대조로 확인된 매핑 — CLAUDE.md 참고). 매핑에 없는 지구명은
            # 아래에서 area_nm("경남" 등) 폴백으로 남는다.
            for part in tokens:
                if part in DISTRICT_OVERRIDE:
                    district = DISTRICT_OVERRIDE[part]
                    break
        if not district:
            district = area_nm

        # 경남 창원시는 주소가 "경상남도 창원시 의창구 ..."처럼 하위구 단위로 와서
        # 5개 하위구(의창구/성산구/마산합포구/마산회원구/진해구)가 따로따로 잡힌다.
        # config.py는 LAWD 코드 48121이 실제로 의창구만 가리킨다는 이유로
        # "창원시 의창구"로 정확히 등록해 뒀지만(scripts/migrate_changwon_district.py
        # 참고), 여기 cheongyak.py는 코드가 아니라 주소 파싱이라 5개 하위구 데이터가
        # 실제로 다 들어오므로 저장 시엔 "창원시" 하나로 통일한다.
        if district in CHANGWON_SUB_DISTRICTS:
            district = "창원시"

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
            region=region,
            district=district,
            permit_date=permit_date,
            developer=developer,
            household_count=household_count,
        ).first()

        if not exists:
            session.add(BuildingPermit(
                region=region,
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

    for region, area_code in REGION_CODES.items():
        for endpoint, property_type, label in ENDPOINTS:
            items = fetch_all(endpoint, area_code)
            if items:
                with get_session() as session:
                    saved = save(session, items, region, property_type)
                    session.commit()
                total_saved += saved
                log.info(f"[{region}] {label}: {saved}건 저장")

    log.info(f"청약홈 분양정보 저장 완료: 총 {total_saved}건")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run()