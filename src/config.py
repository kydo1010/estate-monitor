"""
config.py
.env 값 로드 및 프로젝트 전역 공통 상수 정의
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# API 키
# ---------------------------------------------------------------------------

# 국토교통부 실거래가 (3종)
MOLIT_APARTMENT_API_KEY  = os.getenv("MOLIT_APARTMENT_API_KEY")   # 아파트 매매
MOLIT_APT_RIGHTS_API_KEY = os.getenv("MOLIT_APT_RIGHTS_API_KEY")  # 아파트 분양권전매
MOLIT_OFFICETEL_API_KEY  = os.getenv("MOLIT_OFFICETEL_API_KEY")   # 오피스텔 매매

# V-World (지도·공시지가·토지이용계획 공통 키)
VWORLD_API_KEY           = os.getenv("VWORLD_API_KEY")

# 건축인허가
BUILDING_PERMIT_API_KEY  = os.getenv("BUILDING_PERMIT_API_KEY")

# 미분양
BUSAN_UNSOLD_API_KEY     = os.getenv("BUSAN_UNSOLD_API_KEY")      # 부산광역시 공동주택 미분양

# 청약홈
CHEONGYAK_API_KEY        = os.getenv("CHEONGYAK_API_KEY")         # 청약홈 분양정보

# 주택도시보증공사
HUG_PRICE_API_KEY        = os.getenv("HUG_PRICE_API_KEY")         # 지역별 ㎡당 분양가격


def validate_api_keys(keys: list[str] | None = None) -> None:
    """
    keys: 검증할 키 이름 리스트. None이면 현재 실키 보유 항목만 검증.
    플레이스홀더('여기에_') 또는 None이면 미설정으로 간주.
    """
    all_keys = {
        "MOLIT_APARTMENT_API_KEY":  MOLIT_APARTMENT_API_KEY,
        "MOLIT_APT_RIGHTS_API_KEY": MOLIT_APT_RIGHTS_API_KEY,
        "MOLIT_OFFICETEL_API_KEY":  MOLIT_OFFICETEL_API_KEY,
        "VWORLD_API_KEY":           VWORLD_API_KEY,
        "BUILDING_PERMIT_API_KEY":  BUILDING_PERMIT_API_KEY,
        "BUSAN_UNSOLD_API_KEY":     BUSAN_UNSOLD_API_KEY,
        "CHEONGYAK_API_KEY":        CHEONGYAK_API_KEY,
    }
    target = {k: all_keys[k] for k in keys} if keys else {
        k: v for k, v in all_keys.items()
        if v and "여기에_" not in v  # 실키가 있는 항목만 검증
    }
    missing = [n for n, v in target.items() if not v or "여기에_" in v]
    if missing:
        raise RuntimeError(
            f".env에 다음 API 키가 설정되지 않았습니다: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
DB_PATH = BASE_DIR / "data" / "estate_monitor.db"

# ---------------------------------------------------------------------------
# 부산 16개 구·군 (국토부 API LAWD_CD — 법정동 코드 앞 5자리)
# ---------------------------------------------------------------------------
BUSAN_DISTRICT_CODES = {
    "26110": "중구",
    "26140": "서구",
    "26170": "동구",
    "26200": "영도구",
    "26230": "부산진구",
    "26260": "동래구",
    "26290": "남구",
    "26320": "북구",
    "26350": "해운대구",
    "26380": "사하구",
    "26410": "금정구",
    "26440": "강서구",
    "26470": "연제구",
    "26500": "수영구",
    "26530": "사상구",
    "26710": "기장군",
}

BUSAN_CODE_TO_NAME = BUSAN_DISTRICT_CODES
BUSAN_NAME_TO_CODE = {v: k for k, v in BUSAN_DISTRICT_CODES.items()}

# ---------------------------------------------------------------------------
# 국토부 API 엔드포인트
# ---------------------------------------------------------------------------
MOLIT_BASE_URL = "http://apis.data.go.kr/1613000"

MOLIT_ENDPOINTS = {
    "apartment":  f"{MOLIT_BASE_URL}/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "apt_rights": f"{MOLIT_BASE_URL}/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
    "officetel":  f"{MOLIT_BASE_URL}/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
}

# ---------------------------------------------------------------------------
# 알림 임계값
# ---------------------------------------------------------------------------
UNSOLD_SPIKE_THRESHOLD_PCT = 30.0  # 전월 대비 미분양 증가율 알림 기준(%)

if __name__ == "__main__":
    validate_api_keys()
    print("API 키 검증 완료")