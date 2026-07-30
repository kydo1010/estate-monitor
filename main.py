
"""
main.py
부산 분양·거래시장 통합 모니터 — 전체 실행 진입점

실행 모드:
    python main.py               # 대시보드 + 스케줄러 동시 실행 (운영)
    python main.py --dashboard   # 대시보드만 실행 (개발)
    python main.py --scheduler   # 스케줄러만 실행 (백그라운드 서버)
    python main.py --update      # 데이터 1회 즉시 갱신 후 종료
"""

import argparse
import logging
import sys
import threading
from datetime import datetime

from src.config import validate_api_keys
from src.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/app.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 실행 모드별 함수
# ---------------------------------------------------------------------------

def run_dashboard(debug: bool = False) -> None:
    from dashboards.app import app
    # V-World 인증키가 domain=http://localhost:9090으로만 등록되어
    # 있고, vworld_map.html이 domain 파라미터를 window.location.host에서 만들기 때문에
    # 포트가 바뀌면 지도 인증이 INCORRECT_KEY로 깨진다.
    log.info("대시보드 시작: http://0.0.0.0:9090")
    app.run(debug=debug, use_reloader=False, host="0.0.0.0", port=9090)


def run_scheduler() -> None:
    """스케줄러 실행 (블로킹)"""
    from src.scheduler import start_scheduler
    start_scheduler()


def run_update_once() -> None:
    """데이터 1회 즉시 갱신"""
    from src.scheduler import run_weekly_update
    run_weekly_update()


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="부산 분양·거래시장 통합 모니터",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
실행 예시:
  python main.py                # 대시보드 + 스케줄러 동시 실행 (운영)
  python main.py --dashboard    # 대시보드만 (개발)
  python main.py --scheduler    # 스케줄러만 (서버 백그라운드)
  python main.py --update       # 데이터 즉시 1회 갱신
        """,
    )
    parser.add_argument("--dashboard", action="store_true", help="대시보드만 실행")
    parser.add_argument("--scheduler", action="store_true", help="스케줄러만 실행")
    parser.add_argument("--update",    action="store_true", help="데이터 1회 즉시 갱신 후 종료")
    parser.add_argument("--debug",     action="store_true", help="Dash 디버그 모드")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 공통 초기화
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("부산 분양·거래시장 통합 모니터")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # DB 초기화 (테이블 없으면 생성)
    init_db()
    log.info("DB 초기화 완료")

    # API 키 검증 (--update, --scheduler 모드에서만 — 대시보드 단독은 스킵)
    if args.update or args.scheduler:
        try:
            validate_api_keys()
            log.info("API 키 검증 완료")
        except RuntimeError as e:
            log.warning(f"API 키 미설정: {e}")
            log.warning("수집기는 API 키 설정 후 활성화됩니다.")

    # ------------------------------------------------------------------
    # 모드별 분기
    # ------------------------------------------------------------------

    if args.update:
        # 즉시 1회 갱신
        run_update_once()

    elif args.dashboard:
        # 대시보드만
        run_dashboard(debug=args.debug)

    elif args.scheduler:
        # 스케줄러만
        run_scheduler()

    else:
        # 기본: 대시보드 + 스케줄러 동시 실행
        # 스케줄러를 데몬 스레드로 백그라운드 실행
        scheduler_thread = threading.Thread(
            target=run_scheduler,
            name="scheduler",
            daemon=True,   # 메인(대시보드)이 종료되면 같이 종료
        )
        scheduler_thread.start()
        log.info("스케줄러 백그라운드 실행 중 (매주 월요일 07:00 갱신)")

        # 대시보드는 메인 스레드에서 실행 (블로킹)
        run_dashboard(debug=args.debug)


if __name__ == "__main__":
    main()