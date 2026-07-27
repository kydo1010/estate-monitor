"""
seed_dummy_data.py
실제 API 승인 전 DB 스키마·대시보드 검증용 더미 데이터 (부산 16개 구·군 기준)

실행:
    python -m src.collectors.seed_dummy_data
"""

import random
from datetime import date, timedelta

from src.config import BUSAN_DISTRICT_CODES
from src.db import (
    Base, Trade, UnsoldHousing, BuildingPermit, PriceCapZone,
    engine, get_session, init_db,
)

random.seed(42)

DEVELOPERS  = ["해운대개발", "부산주택산업", "동래시티", "남항시행", "기장개발"]
CONTRACTORS = ["현대건설", "GS건설", "대우건설", "롯데건설", "HDC현산"]

# 구별 실제 시세 반영 (만원/평 기준)
BASE_PRICES = {
    "해운대구": 230000, "수영구": 200000, "동래구": 160000, "연제구": 155000,
    "부산진구": 145000, "남구":   140000, "북구":   120000, "사하구": 110000,
    "금정구":   115000, "강서구": 105000, "사상구": 100000, "기장군":  95000,
    "서구":     120000, "동구":   115000, "영도구": 108000, "중구":   130000,
}


def clear_all_tables() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_trades(session, n_per_district: int = 30) -> None:
    today = date.today()
    for district in BUSAN_DISTRICT_CODES.values():
        base = BASE_PRICES.get(district, 120000)
        for _ in range(n_per_district):
            deal_date = today - timedelta(days=random.randint(0, 180))
            area = round(random.uniform(39.0, 114.0), 2)
            price = int(base * (area / 84.0) * random.uniform(0.88, 1.15))
            session.add(Trade(
                district=district,
                dong=f"{district}동",
                complex_name=f"{district[:2]}더샵 {random.randint(1,4)}단지",
                property_type=random.choice(["아파트", "아파트", "오피스텔"]),
                deal_amount=price,
                area_m2=area,
                floor=random.randint(1, 30),
                build_year=random.randint(2008, 2024),
                deal_date=deal_date,
            ))


def seed_unsold_housing(session) -> None:
    """3개 구를 의도적으로 30%↑ 급증 → 알림 로직 테스트"""
    spike_districts = random.sample(list(BUSAN_DISTRICT_CODES.values()), 3)
    for district in BUSAN_DISTRICT_CODES.values():
        prev = random.randint(15, 180)
        if district in spike_districts:
            current = int(prev * random.uniform(1.35, 1.9))
        else:
            current = int(prev * random.uniform(0.8, 1.25))
        change_rate = round((current - prev) / prev * 100, 1) if prev else 0.0
        session.add(UnsoldHousing(
            district=district,
            base_month=date.today().strftime("%Y-%m"),
            unsold_count=current,
            prev_month_count=prev,
            change_rate=change_rate,
        ))


def seed_building_permits(session, n_per_district: int = 3) -> None:
    today = date.today()
    for district in BUSAN_DISTRICT_CODES.values():
        for _ in range(n_per_district):
            permit_date = today - timedelta(days=random.randint(0, 365))
            session.add(BuildingPermit(
                district=district,
                permit_date=permit_date,
                household_count=random.randint(50, 600),
                developer=random.choice(DEVELOPERS),
                contractor=random.choice(CONTRACTORS),
            ))


def seed_price_cap_zones(session) -> None:
    designated = random.sample(list(BUSAN_DISTRICT_CODES.values()), 4)
    today = date.today()
    for district in designated:
        d_date = today - timedelta(days=random.randint(30, 500))
        released = random.random() < 0.3
        session.add(PriceCapZone(
            district=district,
            dong=f"{district}동",
            designated_date=d_date,
            released_date=today - timedelta(days=random.randint(1, 30)) if released else None,
            status="해제" if released else "지정",
        ))


def run() -> None:
    init_db()
    clear_all_tables()
    n = len(BUSAN_DISTRICT_CODES)
    with get_session() as session:
        seed_trades(session)
        seed_unsold_housing(session)
        seed_building_permits(session)
        seed_price_cap_zones(session)
        session.commit()
    print("더미 데이터 삽입 완료 (부산 기준):")
    print(f"  trades:           {n * 30}건")
    print(f"  unsold_housing:   {n}건")
    print(f"  building_permits: {n * 3}건")
    print(f"  price_cap_zones:  4개구")


if __name__ == "__main__":
    run()