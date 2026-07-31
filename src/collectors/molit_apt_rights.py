"""
src/collectors/molit_apt_rights.py
국토교통부 아파트 분양권전매 실거래가 수집기
"""

import argparse
import logging
from datetime import date

from src.collectors.base import MolitBaseCollector
from src.config import MOLIT_APT_RIGHTS_API_KEY, MOLIT_ENDPOINTS, ALL_CODE_TO_NAME
from src.db import Trade

log = logging.getLogger(__name__)


class AptRightsTradeCollector(MolitBaseCollector):

    endpoint = MOLIT_ENDPOINTS["apt_rights"]
    api_key  = MOLIT_APT_RIGHTS_API_KEY

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

        sgg_cd   = self._text(el, "sggCd")
        district = ALL_CODE_TO_NAME.get(sgg_cd, self._text(el, "estateAgentSggNm"))

        return {
            "district":      district,
            "dong":          self._text(el, "umdNm"),
            "complex_name":  self._text(el, "aptNm"),
            "property_type": "분양권",
            "deal_amount":   amount,
            "area_m2":       self._float(el, "excluUseAr"),
            "floor":         self._int(el, "floor"),
            "build_year":    None,
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
                region=r["region"],
            ).first()
            if not exists:
                session.add(Trade(**r))
                saved += 1
        return saved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="아파트 분양권전매 실거래가 수집")
    parser.add_argument("--months", nargs="+")
    args = parser.parse_args()
    AptRightsTradeCollector().run(months=args.months)