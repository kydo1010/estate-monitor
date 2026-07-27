"""
src/scheduler.py
매주 월요일 오전 7시 데이터 자동 갱신 스케줄러

실행:
    python -m src.scheduler          # 포그라운드 (개발/테스트)
    python -m src.scheduler --once   # 즉시 1회 실행 후 종료 (수동 갱신)
"""

import argparse
import logging
import sys
from datetime import datetime

import schedule
import time

from src.db import init_db

# ---------------------------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 수집 작업 (API 승인 후 collectors/ 모듈로 교체)
# ---------------------------------------------------------------------------

def collect_trades() -> None:
    """국토부 아파트·오피스텔 실거래가 수집 (구현 예정)"""
    log.info("실거래가 수집 시작")
    # from src.collectors.molit_trade import run
    # run()
    log.info("실거래가 수집 완료 (수집기 구현 전 — 스킵)")


def collect_unsold_housing() -> None:
    """전국 미분양 현황 수집 (구현 예정)"""
    log.info("미분양 현황 수집 시작")
    # from src.collectors.unsold_housing import run
    # run()
    log.info("미분양 현황 수집 완료 (수집기 구현 전 — 스킵)")


def collect_building_permits() -> None:
    """건축인허가 정보 수집 (구현 예정)"""
    log.info("건축인허가 수집 시작")
    # from src.collectors.building_permit import run
    # run()
    log.info("건축인허가 수집 완료 (수집기 구현 전 — 스킵)")


def collect_price_cap_zones() -> None:
    """분양가상한제 지정·해제 현황 수집 (구현 예정)"""
    log.info("분양가상한제 현황 수집 시작")
    # from src.collectors.price_cap_zone import run
    # run()
    log.info("분양가상한제 현황 수집 완료 (수집기 구현 전 — 스킵)")


# ---------------------------------------------------------------------------
# 통합 갱신 작업
# ---------------------------------------------------------------------------

def run_weekly_update() -> None:
    """
    매주 월요일 오전 7시 실행되는 통합 갱신 작업.
    수집기가 구현되는 순서대로 주석을 해제하여 활성화한다.
    """
    start = datetime.now()
    log.info("=" * 60)
    log.info(f"주간 갱신 시작: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    tasks = [
        ("실거래가",        collect_trades),
        ("미분양 현황",     collect_unsold_housing),
        ("건축인허가",      collect_building_permits),
        ("분양가상한제",    collect_price_cap_zones),
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


# ---------------------------------------------------------------------------
# 스케줄 등록 및 실행
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """매주 월요일 07:00 갱신 스케줄 등록 후 대기"""
    init_db()

    schedule.every().monday.at("07:00").do(run_weekly_update)

    log.info("스케줄러 시작")
    log.info("갱신 주기: 매주 월요일 오전 07:00")

    next_run = schedule.next_run()
    log.info(f"다음 갱신 예정: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    while True:
        schedule.run_pending()
        time.sleep(30)  # 30초마다 스케줄 체크


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="부산 분양·거래시장 모니터 스케줄러")
    parser.add_argument(
        "--once",
        action="store_true",
        help="스케줄 대기 없이 즉시 1회 갱신 후 종료 (수동 갱신용)",
    )
    args = parser.parse_args()

    if args.once:
        log.info("수동 1회 갱신 모드")
        init_db()
        run_weekly_update()
    else:
        start_scheduler()