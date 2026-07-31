"""
db.py
DB 연결, 스키마 정의, 데이터 저장/조회 헬퍼 함수

사용 예:
    from src.db import init_db, get_session, Trade

    init_db()  # 최초 1회, 테이블 생성
    with get_session() as session:
        session.add(Trade(...))
        session.commit()
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ---------------------------------------------------------------------------
# DB 연결 설정
# ---------------------------------------------------------------------------

DB_PATH = "data/estate_monitor.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()


# ---------------------------------------------------------------------------
# 테이블 정의
# ---------------------------------------------------------------------------

class Trade(Base):
    """실거래가 (아파트·오피스텔 매매)"""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(10), index=True)                     # '부산'/'울산'/'경남', 기존 데이터 호환 위해 nullable
    district = Column(String(20), nullable=False, index=True)   # 예: 강남구
    dong = Column(String(30))                                   # 법정동
    complex_name = Column(String(100))                          # 단지명
    property_type = Column(String(10))                          # 아파트 / 오피스텔
    deal_amount = Column(Integer, nullable=False)                # 거래금액 (만원)
    area_m2 = Column(Float)                                      # 전용면적(㎡)
    floor = Column(Integer)
    build_year = Column(Integer)
    deal_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "district", "complex_name", "deal_date", "deal_amount", "area_m2",
            name="uq_trade_dedup",
        ),
    )


class UnsoldHousing(Base):
    """미분양 현황 (지역구 x 기준월 단위)"""

    __tablename__ = "unsold_housing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(10), nullable=False, index=True)     # '부산'/'울산'/'경남'
    district = Column(String(20), nullable=False, index=True)
    base_month = Column(String(7), nullable=False, index=True)  # 'YYYY-MM'
    unsold_count = Column(Integer, nullable=False)
    prev_month_count = Column(Integer)                          # 전월 값 (알림 계산용)
    change_rate = Column(Float)                                 # 전월 대비 증감률(%)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("region", "district", "base_month", name="uq_unsold_dedup"),
    )


class BuildingPermit(Base):
    """착공·인허가 동향"""

    __tablename__ = "building_permits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    district = Column(String(20), nullable=False, index=True)
    permit_date = Column(Date, nullable=False, index=True)
    household_count = Column(Integer)                            # 인허가 세대수
    developer = Column(String(100))                              # 시행사
    contractor = Column(String(100))                             # 시공사
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "district", "permit_date", "developer", "household_count",
            name="uq_permit_dedup",
        ),
    )


# ---------------------------------------------------------------------------
# 초기화 / 세션 헬퍼
# ---------------------------------------------------------------------------

def init_db() -> None:
    """테이블이 없으면 생성. main.py나 최초 실행 시 1회 호출."""
    Base.metadata.create_all(bind=engine)

    # region 컬럼 없는 기존 DB 대응 — ALTER TABLE로 추가
    inspector = inspect(engine)
    for table, col in [("unsold_housing", "region"), ("trades", "region")]:
        existing = [c["name"] for c in inspector.get_columns(table)]
        if col not in existing:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR(10)"))
                conn.commit()


@contextmanager
def get_session():
    """
    with get_session() as session:
        session.add(...)
        session.commit()
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 조회 헬퍼 (대시보드 / 알림 로직에서 사용)
# ---------------------------------------------------------------------------

def get_unsold_spike_districts(threshold_pct: float = 30.0) -> list[UnsoldHousing]:
    """전월 대비 미분양 증가율이 threshold_pct 이상인 지역 목록 반환"""
    with get_session() as session:
        return (
            session.query(UnsoldHousing)
            .filter(UnsoldHousing.change_rate >= threshold_pct)
            .order_by(UnsoldHousing.change_rate.desc())
            .all()
        )


def get_avg_price_by_district(start_date: date, end_date: date) -> list[tuple]:
    """기간 내 지역(region)·지역구별 평균 거래가 (히트맵/추이 차트용).

    부산·울산 사이에 동명 구(중구·남구·동구·북구)가 있어 district만으로 group by
    하면 두 지역 데이터가 섞인다 — region을 함께 묶어야 한다.
    """
    from sqlalchemy import func

    with get_session() as session:
        return (
            session.query(
                Trade.region,
                Trade.district,
                func.avg(Trade.deal_amount).label("avg_price"),
                func.count(Trade.id).label("deal_count"),
            )
            .filter(Trade.deal_date.between(start_date, end_date))
            .group_by(Trade.region, Trade.district)
            .all()
        )


if __name__ == "__main__":
    # 단독 실행 시 테이블 생성 테스트
    init_db()
    print(f"DB initialized at {DB_PATH}")