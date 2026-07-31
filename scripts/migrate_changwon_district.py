"""
scripts/migrate_changwon_district.py
Trade 테이블에서 region="경남", district="창원시"로 저장된 기존 행을
"창원시 의창구"로 정정하는 1회성 마이그레이션.

배경: GYEONGNAM_DISTRICT_CODES["48121"]이 "창원시"로 잘못 등록돼 있었다
(이 LAWD 코드는 실제로는 창원시 전체가 아니라 의창구만 가리킨다). config.py는
이미 "창원시 의창구"로 고쳤지만, 그 전에 이 코드로 수집돼 저장된 기존 행은
여전히 옛 이름 "창원시"로 남아 있어 이 스크립트로 정정한다. 오피스텔 수집기는
API가 주는 sggNm 필드를 그대로 써서 처음부터 "창원시 의창구"로 정확히
저장됐으므로 대상이 아니다(아파트·분양권만 영향받음).

실행:
    python -m scripts.migrate_changwon_district            # 대상 건수만 확인 (dry-run)
    python -m scripts.migrate_changwon_district --execute  # 실제 UPDATE 수행
"""

import argparse
import logging

from src.db import get_session, Trade

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REGION = "경남"
OLD_DISTRICT = "창원시"
NEW_DISTRICT = "창원시 의창구"


def main() -> None:
    parser = argparse.ArgumentParser(description="창원시 district 명칭 정정 마이그레이션")
    parser.add_argument("--execute", action="store_true",
                        help="실제로 UPDATE를 실행. 미지정 시 대상 건수만 보여주고 종료(dry-run)")
    args = parser.parse_args()

    with get_session() as session:
        targets = session.query(Trade).filter_by(region=REGION, district=OLD_DISTRICT).all()
        n = len(targets)
        by_type = {}
        for t in targets:
            by_type[t.property_type] = by_type.get(t.property_type, 0) + 1

        log.info(f"대상: region='{REGION}' district='{OLD_DISTRICT}' -> '{NEW_DISTRICT}'")
        log.info(f"총 {n}건 ({', '.join(f'{k} {v}건' for k, v in by_type.items())})")

        if n == 0:
            log.info("대상 행이 없습니다. 종료.")
            return

        if not args.execute:
            log.info("dry-run입니다 — 실제로 반영하려면 --execute를 붙여 다시 실행하세요.")
            return

        for t in targets:
            t.district = NEW_DISTRICT
        session.commit()
        log.info(f"{n}건 정정 완료.")


if __name__ == "__main__":
    main()
