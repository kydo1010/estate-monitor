"""
src/collectors/molit_officetel.py
국토교통부 오피스텔 매매 실거래가 수집기
"""

import argparse
import logging
from datetime import date

from src.collectors.base import MolitBaseCollector
from src.config import MOLIT_OFFICETEL_API_KEY, MOLIT_ENDPOINTS, BUSAN_CODE_TO_NAME
from src.db import Trade, get_session

log = logging.getLogger(__name__)


class OfficetelTradeCollector(MolitBaseCollector):

    endpoint = MOLIT_ENDPOINTS["officetel"]
    api_key  = MOLIT_OFFICETEL_API_KEY

    def parse_item(self, el) -> dict:
        amount_str = self._text(el, "dealAmount").replace(",", "").strip()
        amount = int(amount_str) if amount_str.lstrip("-").isdigit() else None

        try:
            deal_date = date(
                int(self._text(el, "dealYear")),
                int(self._text(el, "dealMonth")),
                int(self._text(el, "dealDay")),
            )
        except (ValueError, TypeError):
            deal_date = None

        # sggNm 직접 사용 (예: "해운대구"), 없으면 코드로 변환
        sgg_nm   = self._text(el, "sggNm").strip()
        sgg_cd   = self._text(el, "sggCd")
        district = sgg_nm or BUSAN_CODE_TO_NAME.get(sgg_cd, "")

        return {
            "district":      district,
            "dong":          self._text(el, "umdNm"),
            "complex_name":  self._text(el, "offiNm"),
            "property_type": "오피스텔",
            "deal_amount":   amount,
            "area_m2":       self._float(el, "excluUseAr"),
            "floor":         self._int(el, "floor"),
            "build_year":    self._int(el, "buildYear"),
            "deal_date":     deal_date,
        }

    def save(self, session, records: list[dict]) -> int:
        saved = 0
        for r in records:
            if not r.get("deal_amount") or not r.get("deal_date"):
                continue
            exists = session.query(Trade).filter_by(
                district=r["district"],
                complex_name=r["complex_name"],
                deal_date=r["deal_date"],
                deal_amount=r["deal_amount"],
                area_m2=r["area_m2"],
            ).first()
            if not exists:
                session.add(Trade(**r))
                saved += 1
        return saved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="오피스텔 매매 실거래가 수집")
    parser.add_argument("--months", nargs="+",
                        help="수집할 계약년월 (예: 202606 202605). 미입력 시 당월")
    args = parser.parse_args()
    OfficetelTradeCollector().run(months=args.months)