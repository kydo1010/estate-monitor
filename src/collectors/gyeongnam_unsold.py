"""
src/collectors/gyeongnam_unsold.py
경상남도 미분양 현황 수집기

실행:
    python -m src.collectors.gyeongnam_unsold
"""

import logging
from datetime import date

import requests

from src.config import GYEONGNAM_UNSOLD_API_KEY
from src.db import UnsoldHousing, get_session, init_db

log = logging.getLogger(__name__)

ENDPOINT  = "http://apis.data.go.kr/6480000/gyeongnamunsold/gyeongnamunsoldlist"
PAGE_SIZE = 1000


def fetch_all() -> list[dict]:
    params = {
        "ServiceKey": GYEONGNAM_UNSOLD_API_KEY,
        "pageNo":     1,
        "numOfRows":  PAGE_SIZE,
        "resultType": "json",
    }
    resp = requests.get(ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()

    data  = resp.json()
    items = data["response"]["body"]["items"]
    log.info(f"전체 {len(items)}건 수신")

    records = []
    for r in items:
        records.append({
            "sigungu":     r.get("signgunm", ""),
            "unsold_this": r.get("unsoldcnt_this", ""),
            "unsold_prev": r.get("unsoldcnt_prev", ""),
            "total":       r.get("totalcnt", ""),
        })
    return records


def aggregate_by_district(records: list[dict]) -> dict[str, dict]:
    """시군구별로 집계: 당월 미분양, 전월 미분양, 총분양 합산"""
    result = {}
    for r in records:
        gu = r["sigungu"]
        if not gu:
            continue
        if gu not in result:
            result[gu] = {"unsold": 0, "prev": 0, "tot": 0}
        try:
            result[gu]["unsold"] += int(r["unsold_this"] or 0)
            result[gu]["prev"]   += int(r["unsold_prev"] or 0)
            result[gu]["tot"]    += int(r["total"] or 0)
        except ValueError:
            pass
    return result


def save(session, agg: dict[str, dict]) -> int:
    today      = date.today()
    base_month = today.strftime("%Y-%m")
    saved = 0

    for district, v in agg.items():
        prev_count  = v["prev"] or None
        change_rate = (
            round((v["unsold"] - prev_count) / prev_count * 100, 1)
            if prev_count else None
        )

        # 이번 달 이미 있으면 업데이트
        existing = session.query(UnsoldHousing).filter_by(
            district=district, base_month=base_month
        ).first()
        if existing:
            existing.unsold_count     = v["unsold"]
            existing.prev_month_count = prev_count
            existing.change_rate      = change_rate
        else:
            session.add(UnsoldHousing(
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
    log.info(f"경남 미분양 현황 저장 완료: {len(agg)}개 시군구 (신규 {saved}건)")

    # 급증 알림 출력
    for district, v in sorted(agg.items(), key=lambda x: -x[1]["unsold"]):
        log.info(f"  {district}: 미분양 {v['unsold']}세대 / 총 {v['tot']}세대")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run()
