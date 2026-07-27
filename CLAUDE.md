# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

부산 16개 구·군의 분양·거래시장을 모니터링하는 데이터 파이프라인 + Dash 대시보드입니다.
국토교통부/부산시/청약홈 등 공공데이터 API에서 실거래가·미분양·건축인허가·분양정보를 수집해
SQLite에 적재하고, Plotly Dash로 시각화합니다. 핵심 분석 목표는 건축 인허가(공급)는 느는데
미분양(수요 부진)도 함께 느는 지역을 조기에 식별하는 것입니다 (README.md 참고).

실 API 수집기가 이미 구현되어 있습니다 — `src/collectors/seed_dummy_data.py`는 실 API 호출 없이
스키마·대시보드를 검증하기 위한 더미 데이터 생성용으로만 남아 있습니다.

## Commands

```powershell
venv\Scripts\activate
pip install -r requirements.txt

python main.py                # 대시보드 + 스케줄러 동시 실행 (운영)
python main.py --dashboard    # 대시보드만 (개발, http://127.0.0.1:8050)
python main.py --scheduler    # 스케줄러만 (매주 월요일 07:00 자동 갱신)
python main.py --update       # 데이터 1회 즉시 갱신 후 종료

# 개별 수집기 단독 실행 (디버깅용)
python -m src.collectors.molit_apartment --months 202606 202605
python -m src.collectors.molit_apt_rights
python -m src.collectors.molit_officetel
python -m src.collectors.busan_unsold
python -m src.collectors.building_permit
python -m src.collectors.cheongyak
python -m src.collectors.hug_price

# 스키마/대시보드 검증용 더미 데이터 (실 API 호출 없음)
python -m src.collectors.seed_dummy_data

# 스케줄러 단독 (즉시 1회 또는 상시)
python -m src.scheduler --once
python -m src.scheduler
```

아직 테스트 스위트, 린터, 빌드 도구가 구성되어 있지 않습니다. `requirements.txt`에 먼저 추가되지
않은 이상 `pytest`, `ruff` 등이 설치되어 있다고 가정하지 마세요.

## Architecture

```
공공데이터포털 API群 ──▶ src/collectors/*.py ──▶ SQLAlchemy (src/db.py) ──▶ data/estate_monitor.db
                                                                                   │
                                                                                   ▼
                                                                        dashboards/app.py (Dash)
```

- **`src/config.py`** — `.env` 로드, API 키 상수, `BUSAN_DISTRICT_CODES`(법정동 코드 5자리 ↔
  구·군명 매핑), `MOLIT_ENDPOINTS`, `validate_api_keys()`. `.env`에 실키가 없거나 `여기에_`
  플레이스홀더면 미설정으로 간주된다.
- **`src/db.py`** — SQLAlchemy 엔진/세션(`get_session()` 컨텍스트매니저)과 3개 테이블 모델:
  `Trade`(실거래가), `UnsoldHousing`(미분양), `BuildingPermit`(건축인허가). 각 모델에
  `UniqueConstraint` 기반 dedup 키가 있음 — 수집기는 저장 전 항상 existing row를 조회해 중복
  삽입을 막는다 (예: `molit_apartment.py`의 `save()`). `PriceCapZone`(분양가상한제) 모델은
  최근 커밋에서 제거됨.
- **`src/collectors/base.py`의 `MolitBaseCollector`** — 국토부 실거래가 계열 수집기(아파트/
  분양권전매/오피스텔)의 공통 베이스. 하위 클래스는 `endpoint`, `api_key`, `parse_item()`,
  `save()`만 구현하면 됨. `run(months=[...])`이 부산 16개 구·군 × 지정 월 전체를 순회하며 XML
  응답을 파싱·저장한다 (구별 호출 간 `REQUEST_DELAY_SEC=1.0`초 딜레이, 실패 시 지수 백오프
  재시도 `MAX_RETRIES=3`). 새 국토부 실거래가 API를 추가할 때는 이 베이스를 상속.
- **`src/collectors/{busan_unsold,building_permit,cheongyak,hug_price}.py`** — `MolitBaseCollector`를
  쓰지 않는 독립 수집기 (모듈 레벨 `run()` 함수 패턴). API 응답 포맷이 국토부 실거래가 API와
  다르기 때문.
- **`src/scheduler.py`** — `schedule` 라이브러리로 매주 월요일 07:00에 `run_weekly_update()`
  실행. 이 함수가 실거래가(최근 3개월) → 미분양 → 건축인허가 → 청약홈 순으로 모든 수집기를
  순차 실행하며, 개별 수집기 실패는 다른 수집기를 막지 않고 로그만 남긴다(`data/scheduler.log`).
- **`main.py`** — 4가지 실행 모드(`--dashboard`/`--scheduler`/`--update`/기본) 분기. 기본 모드는
  스케줄러를 데몬 스레드로 백그라운드 실행하면서 대시보드를 메인 스레드에서 블로킹 실행한다.
  전체 로그는 `data/app.log`에 남는다.
- **`dashboards/app.py`** — Dash 대시보드. 지역별 인허가 추이, 미분양 증감(임계값
  `UNSOLD_SPIKE_THRESHOLD_PCT=30%` 초과 시 급증 지역 분류), 실거래가 추이, 지도 기반(choropleth)
  복합 시각화 탭으로 구성 (`shapely`로 부산 행정구역 GeoJSON 처리).

## Data flow gotchas

- 지역 매핑은 항상 `src/config.py`의 `BUSAN_DISTRICT_CODES`/`BUSAN_CODE_TO_NAME`/
  `BUSAN_NAME_TO_CODE`를 통해야 함 — 구·군명을 하드코딩하지 말 것.
- 국토부 API 응답은 XML이며 필드가 비어있거나 숫자가 아닐 수 있음 — `MolitBaseCollector._int`/
  `_float`/`_text`가 안전 파싱을 처리하므로 새 파서를 만들 때도 이 헬퍼를 재사용.
- `src/db.py`의 `DB_PATH`는 상대경로(`data/estate_monitor.db`) 기준이라, 저장소 루트가 아닌
  다른 cwd에서 실행하면 DB 위치가 달라진다. `src/config.py`에도 `BASE_DIR` 기준 별도 `DB_PATH`
  상수가 있으니 둘이 어긋나지 않는지 주의.

## 보안(Secrets)

`.env`에는 실제 API 키 8종(`MOLIT_APARTMENT_API_KEY`, `MOLIT_APT_RIGHTS_API_KEY`,
`MOLIT_OFFICETEL_API_KEY`, `VWORLD_API_KEY`, `BUILDING_PERMIT_API_KEY`, `BUSAN_UNSOLD_API_KEY`,
`CHEONGYAK_API_KEY`, `HUG_PRICE_API_KEY`)가 들어 있으며 gitignore 처리되어 있습니다 — 절대
커밋하거나 다른 곳에 하드코딩하지 마세요.
