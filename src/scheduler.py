"""
src/scheduler.py
매주 월요일 오전 7시 데이터 자동 갱신 스케줄러

실행:
    python -m src.scheduler          # 상시 실행
    python -m src.scheduler --once   # 즉시 1회 실행 후 종료
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime

import schedule

from src.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/scheduler.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _recent_months(n: int = 3) -> list[str]:
    from dateutil.relativedelta import relativedelta
    today = date.today()
    return [(today - relativedelta(months=i)).strftime("%Y%m") for i in range(n)]


def collect_trades() -> None:
    months = _recent_months(3)
    log.info(f"실거래가 수집 시작 — 대상 월: {', '.join(months)}")
    from src.collectors.molit_apartment import ApartmentTradeCollector
    ApartmentTradeCollector().run(months=months)
    from src.collectors.molit_apt_rights import AptRightsTradeCollector
    AptRightsTradeCollector().run(months=months)
    from src.collectors.molit_officetel import OfficetelTradeCollector
    OfficetelTradeCollector().run(months=months)
    log.info("실거래가 수집 완료")


def collect_unsold() -> None:
    log.info("미분양 현황 수집 시작")
    from src.collectors.busan_unsold import run
    run()
    log.info("미분양 현황 수집 완료")


def collect_building_permits() -> None:
    log.info("건축인허가 수집 시작")
    from src.collectors.building_permit import run
    run()
    log.info("건축인허가 수집 완료")


def collect_cheongyak() -> None:
    log.info("청약홈 분양정보 수집 시작")
    from src.collectors.cheongyak import run
    run()
    log.info("청약홈 분양정보 수집 완료")


def run_weekly_update() -> None:
    start = datetime.now()
    log.info("=" * 60)
    log.info(f"주간 갱신 시작: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    tasks = [
        ("실거래가",        collect_trades),
        ("미분양 현황",     collect_unsold),
        ("건축인허가",      collect_building_permits),
        ("청약홈 분양정보", collect_cheongyak),
    ]

    success, failed = [], []
    for name, task in tasks:
        try:
            task()
            success.append(name)
        except Exception as e:
            log.error(f"{name} 수집 실패: {e}", exc_info=True)
            failed.append(name)

    elapsed = (datetime.now() - start).seconds
    log.info("-" * 60)
    log.info(f"갱신 완료 — 소요시간: {elapsed}초")
    log.info(f"성공: {', '.join(success) if success else '없음'}")
    if failed:
        log.warning(f"실패: {', '.join(failed)}")
    log.info("=" * 60)


def start_scheduler() -> None:
    init_db()
    schedule.every().monday.at("07:00").do(run_weekly_update)
    log.info("스케줄러 시작 — 매주 월요일 오전 07:00 갱신")
    log.info(f"다음 갱신 예정: {schedule.next_run().strftime('%Y-%m-%d %H:%M:%S')}")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="즉시 1회 갱신 후 종료")
    args = parser.parse_args()
    if args.once:
        log.info("수동 1회 갱신 모드")
        init_db()
        run_weekly_update()
    else:
        start_scheduler()