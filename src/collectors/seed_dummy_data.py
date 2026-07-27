"""
seed_dummy_data.py
실제 API 승인 전, DB 스키마와 대시보드를 검증하기 위한 더미 데이터 삽입 스크립트.

실행:
    python -m src.collectors.seed_dummy_data

주의: 개발/테스트 전용. 운영 코드에서는 절대 import하지 말 것.
"""

import random
from datetime import date, timedelta

from src.config import SEOUL_DISTRICT_CODES
from src.db import (
    Base,
    Trade,
    UnsoldHousing,
    BuildingPermit,
    PriceCapZone,
    engine,
    get_session,
    init_db,
)

random.seed(42)  # 재현 가능한 더미 데이터

DEVELOPERS = ["한빛개발", "서울주택산업", "그린시티", "미래건설시행"]
CONTRACTORS = ["현대건설", "GS건설", "대우건설", "롯데건설", "DL이앤씨"]


def clear_all_tables() -> None:
    """기존 더미 데이터 초기화 (반복 실행 대비)"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_trades(session, n_per_district: int = 30) -> None:
    today = date.today()
    for district in SEOUL_DISTRICT_CODES:
        base_price = random.randint(80000, 250000)  # 만원 단위, 구별 기본 시세
        for _ in range(n_per_district):
            deal_date = today - timedelta(days=random.randint(0, 180))
            area = round(random.uniform(39.0, 114.0), 2)
            price = int(base_price * (area / 84.0) * random.uniform(0.9, 1.15))
            session.add(
                Trade(
                    district=district,
                    dong=f"{district[:-1]}동",
                    complex_name=f"{district[:2]}자이 {random.randint(1, 5)}단지",
                    property_type=random.choice(["아파트", "아파트", "오피스텔"]),
                    deal_amount=price,
                    area_m2=area,
                    floor=random.randint(1, 25),
                    build_year=random.randint(2005, 2023),
                    deal_date=deal_date,
                )
            )


def seed_unsold_housing(session) -> None:
    """일부 지역은 의도적으로 30% 이상 급증하도록 만들어 알림 로직 테스트"""
    spike_districts = random.sample(list(SEOUL_DISTRICT_CODES), 3)

    for district in SEOUL_DISTRICT_CODES:
        prev = random.randint(20, 200)
        if district in spike_districts:
            current = int(prev * random.uniform(1.35, 1.8))  # 급증 케이스
        else:
            current = int(prev * random.uniform(0.85, 1.2))  # 일반 변동

        change_rate = round((current - prev) / prev * 100, 1) if prev else 0.0

        session.add(
            UnsoldHousing(
                district=district,
                base_month=date.today().strftime("%Y-%m"),
                unsold_count=current,
                prev_month_count=prev,
                change_rate=change_rate,
            )
        )


def seed_building_permits(session, n_per_district: int = 3) -> None:
    today = date.today()
    for district in SEOUL_DISTRICT_CODES:
        for _ in range(n_per_district):
            permit_date = today - timedelta(days=random.randint(0, 365))
            session.add(
                BuildingPermit(
                    district=district,
                    permit_date=permit_date,
                    household_count=random.randint(50, 800),
                    developer=random.choice(DEVELOPERS),
                    contractor=random.choice(CONTRACTORS),
                )
            )


def seed_price_cap_zones(session) -> None:
    """일부 지역만 분양가상한제 지정 상태로 설정"""
    designated = random.sample(list(SEOUL_DISTRICT_CODES), 5)
    today = date.today()

    for district in designated:
        designated_date = today - timedelta(days=random.randint(30, 400))
        released = random.random() < 0.3  # 30% 확률로 이미 해제됨
        session.add(
            PriceCapZone(
                district=district,
                dong=f"{district[:-1]}동",
                designated_date=designated_date,
                released_date=today - timedelta(days=random.randint(1, 20)) if released else None,
                status="해제" if released else "지정",
            )
        )


def run() -> None:
    init_db()
    clear_all_tables()

    with get_session() as session:
        seed_trades(session)
        seed_unsold_housing(session)
        seed_building_permits(session)
        seed_price_cap_zones(session)
        session.commit()

    print("더미 데이터 삽입 완료:")
    print(f"  - trades: {25 * 30}건")
    print(f"  - unsold_housing: {25}건 (25개구 x 1개월)")
    print(f"  - building_permits: {25 * 3}건")
    print("  - price_cap_zones: 5개구")


if __name__ == "__main__":
    run()