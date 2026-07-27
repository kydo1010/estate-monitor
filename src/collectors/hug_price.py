"""
src/collectors/hug_price.py
주택도시보증공사(HUG) 지역별 ㎡당 분양가격 수집기 (부산 = 지역코드 02)

실행:
    python -m src.collectors.hug_price
    python -m src.collectors.hug_price --start 202401 --end 202506
"""

import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import date

import requests

from src.config import HUG_PRICE_API_KEY
from src.db import get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT   = "https://www.khug.or.kr/priceDistributedPrice3dot3.do"
BUSAN_CODE = "02"


# ---------------------------------------------------------------------------
# DB 테이블 — HugPrice (별도 테이블로 관리)
# ---------------------------------------------------------------------------
# db.py에 추가하지 않고 SQLAlchemy core로 직접 처리
from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime

from src.db import engine, Base


class HugPrice(Base):
    """HUG 지역별 ㎡당 분양가격 (월별)"""
    __tablename__ = "hug_prices"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    area_code  = Column(String(10), nullable=False)   # 지역코드 (02 = 부산)
    area_name  = Column(String(50))                   # 지역명
    year_mm    = Column(String(6), nullable=False)     # 연월 (YYYYMM)
    price_m2   = Column(Float)                        # ㎡당 분양가격 (만원)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("area_code", "year_mm", name="uq_hugprice_dedup"),
    )


def ensure_table() -> None:
    HugPrice.__table__.create(bind=engine, checkfirst=True)


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------

def fetch(start_yym: str, end_yym: str, area_dcd: str = BUSAN_CODE) -> list[dict]:
    params = {
        "API_KEY":   HUG_PRICE_API_KEY,
        "START_YYM": start_yym,
        "END_YYM":   end_yym,
        "AREA_DCD":  area_dcd,
    }
    resp = requests.get(ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()

    root  = ET.fromstring(resp.text)
    items = root.findall(".//item")
    log.info(f"HUG 분양가격 {len(items)}건 수신 ({start_yym}~{end_yym})")

    records = []
    for el in items:
        def t(tag):
            node = el.find(tag)
            return node.text.strip() if node is not None and node.text else ""

        price_str = t("YEAR_VAL")
        try:
            price = float(price_str)
        except ValueError:
            price = None

        records.append({
            "area_code": t("AREA_DCD"),
            "area_name": t("AREA_DCD_NM"),
            "year_mm":   t("YEAR_MM"),
            "price_m2":  price,
        })
    return records


def save(session, records: list[dict]) -> int:
    saved = 0
    for r in records:
        exists = session.query(HugPrice).filter_by(
            area_code=r["area_code"],
            year_mm=r["year_mm"],
        ).first()
        if exists:
            exists.price_m2  = r["price_m2"]
            exists.area_name = r["area_name"]
        else:
            session.add(HugPrice(**r))
            saved += 1
    return saved


def run(start_yym: str | None = None, end_yym: str | None = None) -> None:
    init_db()
    ensure_table()

    today = date.today()
    if not start_yym:
        # 기본: 최근 12개월
        start_yym = f"{today.year - 1}{today.month:02d}"
    if not end_yym:
        end_yym = today.strftime("%Y%m")

    records = fetch(start_yym, end_yym)
    with get_session() as session:
        saved = save(session, records)
        session.commit()

    log.info(f"HUG 분양가격 저장 완료: 신규 {saved}건")
    for r in records:
        log.info(f"  {r['area_name']} {r['year_mm']}: {r['price_m2']}만원/㎡")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="HUG 지역별 분양가격 수집")
    parser.add_argument("--start", default=None,
                        help="시작연월 (예: 202401). 미입력 시 최근 12개월")
    parser.add_argument("--end",   default=None,
                        help="종료연월 (예: 202506). 미입력 시 당월")
    args = parser.parse_args()
    run(start_yym=args.start, end_yym=args.end)