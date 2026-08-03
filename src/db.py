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

import re
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
            "district", "complex_name", "deal_date", "deal_amount", "area_m2", "region",
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
    region = Column(String(10), nullable=False, index=True)      # '부산'/'울산'/'경남'
    district = Column(String(20), nullable=False, index=True)
    permit_date = Column(Date, nullable=False, index=True)
    household_count = Column(Integer)                            # 인허가 세대수
    developer = Column(String(100))                              # 시행사
    contractor = Column(String(100))                             # 시공사
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "region", "district", "permit_date", "developer", "household_count",
            name="uq_permit_dedup",
        ),
    )


# ---------------------------------------------------------------------------
# 초기화 / 세션 헬퍼
# ---------------------------------------------------------------------------

TRADES_LEGACY_TABLE = "trades_pre_region_uq"


def _trades_unique_constraint_has_region() -> bool | None:
    """
    trades 테이블의 uq_trade_dedup UNIQUE 제약에 region이 포함돼 있는지 확인.
    테이블이 아직 없으면 None(마이그레이션 불필요 — 아래 create_all이 최신
    모델 그대로 새로 만든다).
    """
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
        )).fetchone()
    if row is None or row[0] is None:
        return None
    match = re.search(r"uq_trade_dedup\s+UNIQUE\s*\(([^)]*)\)", row[0], re.IGNORECASE)
    if not match:
        return False
    columns = [c.strip() for c in match.group(1).split(",")]
    return "region" in columns


def _migrate_trades_add_region_to_constraint() -> None:
    """
    SQLite는 ALTER TABLE로 기존 UNIQUE 제약을 바꿀 수 없어, rename → 현재
    모델대로 재생성 → 데이터 복사 → 옛 테이블 drop 순서로 우회한다.

    기존 행은 region이 전부 NULL인 채로 그대로 복사되는데, SQLite UNIQUE
    비교에서 NULL은 서로 다른 값으로 취급되어(NULL != NULL) 복사 도중
    제약 위반이 나지 않는다 — 실제로 이 함수 호출 전 데이터에 이미
    (district, complex_name, deal_date, deal_amount, area_m2) 기준 중복이
    없었으므로(region을 더한 새 제약은 그 초과집합이라) 위반이 생길 수 없다.
    """
    with engine.begin() as conn:
        # ALTER TABLE RENAME은 named index(ix_trades_district 등)의 이름을
        # 새 테이블로 넘겨주지 않고 옛 테이블에 그대로 남긴다 — 이 상태로
        # Trade.__table__.create()를 부르면 새 trades에 같은 이름의 인덱스를
        # 또 만들려다 "index already exists"로 충돌한다. rename 전에 지워
        # 두면 새 trades에서 Trade.__table__.create()가 다시 만들어 준다.
        idx_rows = conn.execute(text("PRAGMA index_list('trades')")).fetchall()
        for idx in idx_rows:
            idx_name = idx[1]
            if not idx_name.startswith("sqlite_autoindex_"):
                conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        conn.execute(text(f"ALTER TABLE trades RENAME TO {TRADES_LEGACY_TABLE}"))

    Trade.__table__.create(bind=engine, checkfirst=True)

    cols = ("id, region, district, dong, complex_name, property_type, "
            "deal_amount, area_m2, floor, build_year, deal_date, created_at")
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO trades ({cols}) SELECT {cols} FROM {TRADES_LEGACY_TABLE}"))
        conn.execute(text(f"DROP TABLE {TRADES_LEGACY_TABLE}"))


UNSOLD_LEGACY_TABLE = "unsold_housing_pre_region_uq"


def _unsold_unique_constraint_has_region() -> bool | None:
    """
    unsold_housing 테이블의 uq_unsold_dedup UNIQUE 제약에 region이 포함돼
    있는지 확인. 테이블이 아직 없으면 None(마이그레이션 불필요 — 아래
    create_all이 최신 모델 그대로 새로 만든다).
    """
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='unsold_housing'"
        )).fetchone()
    if row is None or row[0] is None:
        return None
    match = re.search(r"uq_unsold_dedup\s+UNIQUE\s*\(([^)]*)\)", row[0], re.IGNORECASE)
    if not match:
        return False
    columns = [c.strip() for c in match.group(1).split(",")]
    return "region" in columns


def _migrate_unsold_add_region_to_constraint() -> None:
    """
    _migrate_trades_add_region_to_constraint()와 동일한 이유·동일한 순서
    (rename → 현재 모델대로 재생성 → 데이터 복사 → 옛 테이블 drop)로 우회한다.

    다만 UnsoldHousing.region은 Trade.region과 달리 nullable=False다. region이
    전부 NULL인 레거시 행을 그대로 복사하면 NOT NULL 제약 위반으로 INSERT가
    실패하는데, 그 시점엔 이미 rename·재생성이 끝난 뒤라 옛 테이블은 사라지고
    새 테이블은 비어있는 중간 상태로 남는다. 그래서 스키마를 하나도 건드리기
    전에 먼저 전체 행을 읽어 region을 확정해 두고, district명으로도 역보정 못
    하는 행이 하나라도 있으면 그 자리에서 예외를 던져 스키마 변경 자체를
    시작하지 않는다. district→region 역보정 근거는 dashboards/app.py의
    DISTRICT_TO_REGION과 같다 — 구·군명은 지역 간에 겹치는 이름(중구·남구 등)만
    없으면 유일하게 지역을 특정한다.
    """
    from src.config import BUSAN_DISTRICT_CODES, GYEONGNAM_DISTRICT_CODES, ULSAN_DISTRICT_CODES

    district_to_region = {
        **{name: "경남" for name in GYEONGNAM_DISTRICT_CODES.values()},
        **{name: "울산" for name in ULSAN_DISTRICT_CODES.values()},
        **{name: "부산" for name in BUSAN_DISTRICT_CODES.values()},
    }

    cols = ["id", "region", "district", "base_month", "unsold_count",
            "prev_month_count", "change_rate", "created_at"]

    with engine.connect() as conn:
        legacy_rows = [
            dict(zip(cols, row))
            for row in conn.execute(text(f"SELECT {', '.join(cols)} FROM unsold_housing")).fetchall()
        ]

    unresolved = sorted({
        r["district"] for r in legacy_rows
        if r["region"] is None and r["district"] not in district_to_region
    })
    if unresolved:
        raise RuntimeError(
            "unsold_housing region 마이그레이션 중단 — region이 없고 구·군명으로도 "
            f"지역을 역보정할 수 없는 행 발견: {unresolved}. "
            "config.py의 지역 코드 맵에 해당 구·군을 추가한 뒤 다시 시도할 것."
        )

    for r in legacy_rows:
        if r["region"] is None:
            r["region"] = district_to_region[r["district"]]

    with engine.begin() as conn:
        # ALTER TABLE RENAME이 named index(ix_unsold_housing_district 등)의
        # 이름을 새 테이블로 넘겨주지 않고 옛 테이블에 그대로 남기는 문제는
        # trades 마이그레이션과 동일 — rename 전에 지워 둬야 재생성 시
        # "index already exists" 충돌이 안 난다.
        idx_rows = conn.execute(text("PRAGMA index_list('unsold_housing')")).fetchall()
        for idx in idx_rows:
            idx_name = idx[1]
            if not idx_name.startswith("sqlite_autoindex_"):
                conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        conn.execute(text(f"ALTER TABLE unsold_housing RENAME TO {UNSOLD_LEGACY_TABLE}"))

    UnsoldHousing.__table__.create(bind=engine, checkfirst=True)

    insert_cols = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    with engine.begin() as conn:
        for r in legacy_rows:
            conn.execute(text(f"INSERT INTO unsold_housing ({insert_cols}) VALUES ({placeholders})"), r)
        conn.execute(text(f"DROP TABLE {UNSOLD_LEGACY_TABLE}"))


PERMIT_LEGACY_TABLE = "building_permits_pre_region_uq"


def _permit_unique_constraint_has_region() -> bool | None:
    """
    building_permits 테이블의 uq_permit_dedup UNIQUE 제약에 region이 포함돼
    있는지 확인. 테이블이 아직 없으면 None(마이그레이션 불필요 — 아래
    create_all이 최신 모델 그대로 새로 만든다).
    """
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='building_permits'"
        )).fetchone()
    if row is None or row[0] is None:
        return None
    match = re.search(r"uq_permit_dedup\s+UNIQUE\s*\(([^)]*)\)", row[0], re.IGNORECASE)
    if not match:
        return False
    columns = [c.strip() for c in match.group(1).split(",")]
    return "region" in columns


def _migrate_permit_add_region_to_constraint() -> None:
    """
    _migrate_unsold_add_region_to_constraint()와 같은 이유·같은 순서로 우회한다.
    다만 building_permits는 region 컬럼 자체가 지금까지 한 번도 없었다(trades/
    unsold_housing과 달리 ALTER TABLE ADD COLUMN 단계 자체가 필요 없음).

    이 테이블은 지금 building_permit.py(건축HUB 배치)·cheongyak.py(청약홈) 두
    수집기만 쓰고 둘 다 부산 전용이라, district명 기반 역추정 대신 전체 행을
    무조건 region='부산'으로 채운다 — district에 실제 구·군명이 아니라 "부산"
    문자열 그대로 들어간 예외적인 행(cheongyak.py가 주소에서 구·군을 못 뽑았을 때의
    fallback)이 있어 구·군명 매핑으로는 오히려 걸러지므로, 이 테이블에 한해서는
    매핑 대신 상수를 쓰는 게 맞다. UnsoldHousing 마이그레이션 사고 교훈대로
    스키마를 하나도 건드리기 전에 먼저 region을 전부 확정해 둔다.
    """
    cols = ["id", "district", "permit_date", "household_count",
            "developer", "contractor", "created_at"]

    with engine.connect() as conn:
        legacy_rows = [
            dict(zip(cols, row))
            for row in conn.execute(text(f"SELECT {', '.join(cols)} FROM building_permits")).fetchall()
        ]
    for r in legacy_rows:
        r["region"] = "부산"

    with engine.begin() as conn:
        # ALTER TABLE RENAME이 named index 이름을 새 테이블로 넘겨주지 않고
        # 옛 테이블에 남기는 문제는 trades/unsold_housing 마이그레이션과 동일.
        idx_rows = conn.execute(text("PRAGMA index_list('building_permits')")).fetchall()
        for idx in idx_rows:
            idx_name = idx[1]
            if not idx_name.startswith("sqlite_autoindex_"):
                conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        conn.execute(text(f"ALTER TABLE building_permits RENAME TO {PERMIT_LEGACY_TABLE}"))

    BuildingPermit.__table__.create(bind=engine, checkfirst=True)

    insert_cols = ["id", "region", "district", "permit_date", "household_count",
                   "developer", "contractor", "created_at"]
    insert_cols_sql = ", ".join(insert_cols)
    placeholders = ", ".join(f":{c}" for c in insert_cols)
    with engine.begin() as conn:
        for r in legacy_rows:
            conn.execute(text(f"INSERT INTO building_permits ({insert_cols_sql}) VALUES ({placeholders})"), r)
        conn.execute(text(f"DROP TABLE {PERMIT_LEGACY_TABLE}"))


def init_db() -> None:
    """테이블이 없으면 생성. main.py나 최초 실행 시 1회 호출."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # region 컬럼 자체가 없던 옛 스키마 대응 — 제약 마이그레이션 전에 먼저
    # 컬럼을 채워 둔다(없으면 아래 데이터 복사 시 "no such column" 오류).
    for table in ("trades", "unsold_housing"):
        if table in existing_tables:
            existing_cols = [c["name"] for c in inspector.get_columns(table)]
            if "region" not in existing_cols:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN region VARCHAR(10)"))
                    conn.commit()

    if _trades_unique_constraint_has_region() is False:
        _migrate_trades_add_region_to_constraint()

    if _unsold_unique_constraint_has_region() is False:
        _migrate_unsold_add_region_to_constraint()

    if _permit_unique_constraint_has_region() is False:
        _migrate_permit_add_region_to_constraint()

    Base.metadata.create_all(bind=engine)


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