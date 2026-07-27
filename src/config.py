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
MOLIT_API_KEY           = os.getenv("MOLIT_API_KEY")
BUILDING_PERMIT_API_KEY = os.getenv("BUILDING_PERMIT_API_KEY")
UNSOLD_HOUSING_API_KEY  = os.getenv("UNSOLD_HOUSING_API_KEY")

def validate_api_keys() -> None:
    keys = {
        "MOLIT_API_KEY": MOLIT_API_KEY,
        "BUILDING_PERMIT_API_KEY": BUILDING_PERMIT_API_KEY,
        "UNSOLD_HOUSING_API_KEY": UNSOLD_HOUSING_API_KEY,
    }
    missing = [n for n, v in keys.items() if not v or "여기에_" in v]
    if missing:
        raise RuntimeError(f".env에 다음 API 키가 설정되지 않았습니다: {', '.join(missing)}")

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
DB_PATH = BASE_DIR / "data" / "estate_monitor.db"

# ---------------------------------------------------------------------------
# 부산 16개 구·군 (법정동 코드 5자리 / 국토부 API LAWD_CD 파라미터)
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

# 역방향 조회용
BUSAN_CODE_TO_NAME = BUSAN_DISTRICT_CODES
BUSAN_NAME_TO_CODE = {v: k for k, v in BUSAN_DISTRICT_CODES.items()}

# ---------------------------------------------------------------------------
# 알림 임계값
# ---------------------------------------------------------------------------
UNSOLD_SPIKE_THRESHOLD_PCT = 30.0  # 전월 대비 미분양 증가율 알림 기준(%)

if __name__ == "__main__":
    validate_api_keys()
    print("모든 API 키가 정상적으로 로드되었습니다.")