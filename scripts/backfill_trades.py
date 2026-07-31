"""
scripts/backfill_trades.py
최근 12개월치 실거래가(아파트·분양권전매·오피스텔)를 부산·울산·경남 39개
시·군·구 전체에 대해 백필한다.

실행:
    python -m scripts.backfill_trades                # 처음부터
    python -m scripts.backfill_trades --start-index 40  # 40번째 작업부터 이어서

새 API 호출 로직은 만들지 않는다 — 각 수집기가 이미 가진
MolitBaseCollector.run(months=[...])을 그대로 재사용한다. run()은 내부에서
config.ALL_DISTRICT_CODES 전체 × months를 순회하므로, 구·군 하나씩 진행
로그를 남기기 위해 호출 직전에 config.ALL_DISTRICT_CODES를 해당 구 하나짜리
dict로 잠깐 바꿔치기한 뒤 run()을 부르고 원래대로 되돌린다(region_map은
BUSAN/ULSAN/GYEONGNAM_DISTRICT_CODES 전체를 그대로 쓰므로 영향 없음).

API 호출 간 지연은 base.py의 MolitBaseCollector.REQUEST_DELAY_SEC(1.0초)가
매 fetch_one_month 호출 뒤에 이미 넣고 있어 여기서 별도로 추가하지 않는다.

재실행 안전성: Trade의 uq_trade_dedup unique constraint와 각 수집기 save()의
dedup 쿼리가 (district, complex_name, deal_date, deal_amount, area_m2, region)
전부를 기준으로 하므로, 스크립트가 중간에 끊겨도 다시 실행하면 이미 저장된
행은 건너뛰고 새 행만 저장된다 — 중복 저장 걱정 없이 그냥 재실행해도 된다.
다만 이미 받은 구간의 API 재호출 자체를 막지는 못한다(저장만 막아줄 뿐 API는
다시 부른다) — 그 낭비를 줄이려면 로그에서 마지막으로 완료된 작업 번호를 보고
--start-index로 이어서 실행하면 된다.
"""

import argparse
import logging
import sys
from datetime import date

from dateutil.relativedelta import relativedelta

import src.config as config
from src.collectors.molit_apartment import ApartmentTradeCollector
from src.collectors.molit_apt_rights import AptRightsTradeCollector
from src.collectors.molit_officetel import OfficetelTradeCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/backfill_trades.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BACKFILL_MONTHS = 12

COLLECTORS = [
    ("아파트", ApartmentTradeCollector),
    ("분양권전매", AptRightsTradeCollector),
    ("오피스텔", OfficetelTradeCollector),
]


def _backfill_month_list(n: int = BACKFILL_MONTHS) -> list[str]:
    """오늘 기준으로 역산한 최근 n개월을 오래된 달 → 최신 달 순으로 반환."""
    today = date.today()
    return sorted((today - relativedelta(months=i)).strftime("%Y%m") for i in range(n))


def main() -> None:
    parser = argparse.ArgumentParser(description="최근 12개월 실거래가 백필")
    parser.add_argument("--start-index", type=int, default=0,
                        help="전체 작업 번호(1부터) 기준, 이 번호 이전까지는 건너뛰고 이어서 실행")
    args = parser.parse_args()

    months = _backfill_month_list()
    districts = list(config.ALL_DISTRICT_CODES.items())  # [(lawd_cd, district_name), ...]

    total_work = len(districts) * len(COLLECTORS)
    total_calls = total_work * len(months)
    log.info(
        f"백필 대상: {len(districts)}개 구·군 × {len(months)}개월({months[0]}~{months[-1]}) "
        f"× {len(COLLECTORS)}종 API = 최대 {total_calls:,}회 API 호출 예상"
    )
    if args.start_index:
        log.info(f"--start-index {args.start_index} — 이전 작업은 건너뛰고 이어서 실행")

    work_idx = 0
    for label, collector_cls in COLLECTORS:
        collector = collector_cls()
        for district_idx, (lawd_cd, district_name) in enumerate(districts, start=1):
            work_idx += 1
            if work_idx <= args.start_index:
                continue

            log.info(
                f"[전체 {work_idx}/{total_work}] [{label}] ({district_idx}/{len(districts)}) "
                f"{district_name} 처리 중, {months[0]}~{months[-1]}"
            )

            original_codes = config.ALL_DISTRICT_CODES
            config.ALL_DISTRICT_CODES = {lawd_cd: district_name}
            try:
                collector.run(months=months)
            except Exception:
                log.exception(
                    f"[전체 {work_idx}/{total_work}] [{label}] {district_name} 처리 실패 — 다음으로 넘어감"
                )
            finally:
                config.ALL_DISTRICT_CODES = original_codes

    log.info("백필 완료")


if __name__ == "__main__":
    main()
