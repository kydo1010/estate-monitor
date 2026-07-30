"""
src/collectors/busan_unsold.py
부산광역시 공동주택 미분양 현황 수집기

실행:
    python -m src.collectors.busan_unsold
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date

import requests

from src.config import BUSAN_UNSOLD_API_KEY, UNSOLD_SPIKE_THRESHOLD_PCT
from src.db import UnsoldHousing, get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT   = "http://apis.data.go.kr/6260000/UnSellStusService/UnSellStusInfo"
PAGE_SIZE  = 1000


def fetch_all() -> list[dict]:
    params = {
        "serviceKey": BUSAN_UNSOLD_API_KEY,
        "pageNo":     1,
        "numOfRows":  PAGE_SIZE,
    }
    resp = requests.get(ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()

    root  = ET.fromstring(resp.text)
    items = root.findall(".//item")
    log.info(f"전체 {len(items)}건 수신")

    records = []
    for el in items:
        def t(tag): 
            node = el.find(tag)
            return node.text.strip() if node is not None and node.text else ""

        records.append({
            "sigungu":            t("sigungu"),
            "eupmundong":         t("eupmundong"),
            "addr":               t("addr"),
            "contractor":         t("contractor"),
            "developer":          t("developer"),
            "scale":              t("scale"),
            "tot_sell_household": t("tot_sell_nm_household"),
            "unsell_household":   t("unsell_nm_household"),
            "completion_at":      t("completion_at"),
            "reference_date":     t("reference_date"),
            "lat":                t("lat"),
            "lng":                t("lng"),
        })
    return records


def aggregate_by_district(records: list[dict]) -> dict[str, dict]:
    """구별로 집계: 총분양가구수, 미분양가구수 합산"""
    result = {}
    for r in records:
        gu = r["sigungu"]
        if not gu:
            continue
        if gu not in result:
            result[gu] = {"tot": 0, "unsold": 0}
        try:
            result[gu]["tot"]    += int(r["tot_sell_household"] or 0)
            result[gu]["unsold"] += int(r["unsell_household"]   or 0)
        except ValueError:
            pass
    return result


def save(session, agg: dict[str, dict]) -> int:
    today     = date.today()
    base_month = today.strftime("%Y-%m")
    saved = 0

    for district, v in agg.items():
        # 전월 데이터 조회 (증감률 계산)
        from dateutil.relativedelta import relativedelta
        prev_month = (today - relativedelta(months=1)).strftime("%Y-%m")
        prev_row = session.query(UnsoldHousing).filter_by(
            region="부산", district=district, base_month=prev_month
        ).first()
        prev_count  = prev_row.unsold_count if prev_row else None
        change_rate = (
            round((v["unsold"] - prev_count) / prev_count * 100, 1)
            if prev_count else None
        )

        # 이번 달 이미 있으면 업데이트
        existing = session.query(UnsoldHousing).filter_by(
            region="부산", district=district, base_month=base_month
        ).first()
        if existing:
            existing.region           = "부산"
            existing.unsold_count     = v["unsold"]
            existing.prev_month_count = prev_count
            existing.change_rate      = change_rate
        else:
            session.add(UnsoldHousing(
                region="부산",
                district=district,
                base_month=base_month,
                unsold_count=v["unsold"],
                prev_month_count=prev_count,
                change_rate=change_rate,
            ))
            saved += 1

    return saved


def run() -> None:
    init_db()
    records = fetch_all()
    agg     = aggregate_by_district(records)
    with get_session() as session:
        saved = save(session, agg)
        session.commit()
    log.info(f"미분양 현황 저장 완료: {len(agg)}개 구·군 (신규 {saved}건)")

    # 급증 알림 출력
    for district, v in sorted(agg.items(), key=lambda x: -x[1]["unsold"]):
        log.info(f"  {district}: 미분양 {v['unsold']}세대 / 총 {v['tot']}세대")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run()
