# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

부산 16개 구·군의 분양·거래시장을 모니터링하는 데이터 파이프라인 + Dash 대시보드입니다.
국토교통부/부산시/청약홈/HUG 등 공공데이터 API에서 실거래가·미분양·건축인허가·분양정보를 수집해
SQLite에 적재하고, Plotly Dash로 시각화합니다. 핵심 분석 목표는 건축 인허가(공급)는 느는데
미분양(수요 부진)도 함께 느는 지역을 조기에 식별해, 시공사 교체·분양 전략 변경 타이밍에
선제적으로 영업 접촉하는 것입니다 (README.md 참고).

## Commands

개발은 Windows(PowerShell), 배포는 Linux 서버입니다. 저장소에 두 레이아웃의 venv가 섞여 있을 수
있으니 실행 전 확인하세요 (`venv/bin/python` = Linux, `venv/Scripts/python.exe` = Windows).

```bash
source venv/bin/activate        # Linux.  Windows: venv\Scripts\activate
pip install -r requirements.txt

python main.py                # 대시보드 + 스케줄러 동시 실행 (운영, 0.0.0.0:8050)
python main.py --dashboard    # 대시보드만 (개발)
python main.py --scheduler    # 스케줄러만 (매주 월요일 07:00 자동 갱신)
python main.py --update       # 데이터 1회 즉시 갱신 후 종료
python main.py --dashboard --debug   # Dash 디버그 모드

# 개별 수집기 단독 실행 (디버깅용)
python -m src.collectors.molit_apartment --months 202606 202605
python -m src.collectors.molit_apt_rights
python -m src.collectors.molit_officetel
python -m src.collectors.busan_unsold
python -m src.collectors.building_permit --sigungu 26350   # 미입력 시 부산 전체
python -m src.collectors.cheongyak
python -m src.collectors.hug_price --start 202401 --end 202506

# 스케줄러 단독 (즉시 1회 또는 상시)
python -m src.scheduler --once
python -m src.scheduler
```

`python -m dashboards.app`로 직접 띄우면 `main.py`와 달리 **debug=True, port=1111**로 뜹니다
(모듈 하단 `__main__` 블록). 운영과 동일한 조건으로 확인하려면 `python main.py --dashboard`를 쓰세요.

아직 테스트 스위트, 린터, 빌드 도구가 구성되어 있지 않습니다. `requirements.txt`에 먼저 추가되지
않은 이상 `pytest`, `ruff` 등이 설치되어 있다고 가정하지 마세요. 검증은 보통
`python -c "import dashboards.app"`(임포트 성공 = 레이아웃 구성 OK) + 실제 기동 후 curl로 합니다.

## Architecture

```
공공데이터포털 API群 ──▶ src/collectors/*.py ──▶ SQLAlchemy (src/db.py) ──▶ data/estate_monitor.db
                                                                                   │
                                                                                   ▼
                                                                        dashboards/app.py (Dash)
```

- **`src/config.py`** — `.env` 로드, API 키 상수, `BUSAN_DISTRICT_CODES`(법정동 코드 5자리 ↔
  구·군명), `BUSAN_DONG_CODES`(건축HUB용 시군구코드 → 법정동코드 → 동명 2단계 맵, 부산 약 205개 동),
  `MOLIT_ENDPOINTS`, `UNSOLD_SPIKE_THRESHOLD_PCT=30.0`, `validate_api_keys()`.
- **`src/db.py`** — SQLAlchemy 엔진/세션(`get_session()` 컨텍스트매니저)과 3개 테이블 모델:
  `Trade`(실거래가), `UnsoldHousing`(미분양), `BuildingPermit`(인허가/분양공고). 각 모델에
  `UniqueConstraint` 기반 dedup 키가 있지만 실제 방어는 수집기가 저장 전 `filter_by(...).first()`로
  existing row를 조회하는 코드에 의존한다 (예: `molit_apartment.py`의 `save()`). 조회 헬퍼
  `get_unsold_spike_districts()`, `get_avg_price_by_district()`도 여기 있음.
- **`src/collectors/base.py`의 `MolitBaseCollector`** — 국토부 실거래가 계열 3종(아파트/분양권전매/
  오피스텔)의 공통 베이스. 하위 클래스는 `endpoint`, `api_key`, `parse_item()`, `save()`만 구현.
  `run(months=[...])`이 부산 16개 구·군 × 지정 월을 순회하며 XML을 파싱·저장한다
  (호출 간 `REQUEST_DELAY_SEC=1.0`초, 실패 시 지수 백오프 `MAX_RETRIES=3`).
  새 국토부 실거래가 API를 추가할 때는 이 베이스를 상속.
- **`src/collectors/{busan_unsold,building_permit,cheongyak,hug_price}.py`** — 응답 포맷이 국토부
  실거래가 API와 달라 베이스를 쓰지 않는 독립 수집기 (모듈 레벨 `run()` 함수 패턴).
- **`src/scheduler.py`** — `schedule` 라이브러리로 매주 월요일 07:00에 `run_weekly_update()` 실행.
  개별 수집기 실패는 다른 수집기를 막지 않고 로그만 남긴다(`data/scheduler.log`).
- **`main.py`** — 4가지 실행 모드 분기. 기본 모드는 스케줄러를 데몬 스레드로 백그라운드 실행하면서
  대시보드를 메인 스레드에서 블로킹 실행한다. 전체 로그는 `data/app.log`.
- **`dashboards/app.py`** — 단일 파일 Dash 앱(~840줄). 4개 탭: 지도 / 미분양 알림 / 거래가 분석 /
  착공·허가. 다크·라이트 테마는 `DARK_COLORS`/`LIGHT_COLORS` 딕셔너리 + `get_*_style()` 헬퍼로
  런타임 생성하며, CSS 파일이 아니라 인라인 style dict로 전부 처리된다.
- **`dashboards/assets/vworld_map.html`** — V-World OpenLayers 지도. Dash가 이 파일을 읽어
  `__VWORLD_API_KEY__`를 치환한 뒤 `html.Iframe(srcDoc=...)`으로 주입한다 (assets 자동 서빙 아님).
  행정동 GeoJSON은 외부(GitHub vuski/admdongkor)에서 iframe이 직접 fetch하고, `sido === '26'`으로
  부산만 필터해 구 단위로 집계한다.

## 대시보드 구조 gotchas

- **데이터는 모듈 임포트 시점에 1회만 로드된다.** `unsold_df`/`price_df`/`permit_df`/`trend_df`가
  `dashboards/app.py` 모듈 레벨(약 220행)에서 만들어지고 콜백은 이 전역 DataFrame을 읽기만 한다.
  수집기를 돌려 DB를 갱신해도 **대시보드 프로세스를 재시작해야 반영**된다.
- **테마 토글 버그가 반복 재발한 이력이 있다.** `app.py` 최상단 docstring에 5차례의 재발·수정
  경위가 상세히 기록되어 있으니 테마/레이아웃을 건드리기 전에 반드시 읽을 것. 핵심 불변조건 두 가지:
  (1) `theme-toggle-btn`은 `app.layout` 최상위에 `position: fixed`로만 존재하고 `build_shell()`은
  이 id를 **절대 생성하지 않는다** (재생성되면 `n_clicks`가 리셋돼 토글이 죽음).
  (2) 셸(`page-content`)은 `theme-store` 변경에만, 탭 본문(`tab-content`)은 `active-tab-store`
  변경에만 갱신한다 — 한 콜백이 둘 다 담당하면 탭 전환이 테마를 흔든다.
- **지도 ↔ Dash 양방향 브리지는 현재 미완성이다.** iframe은 `postMessage({type:'gu_click'})`를
  보내지만 Dash 쪽에서 `clicked-gu-store`에 값을 **쓰는 콜백이 없다** (`build_tab_map()`의
  `html.Script`는 존재하지 않는 `dash-store-update` 이벤트를 쓰고, `clientside_callback`은
  import만 되어 있고 미사용). 반대로 미분양 색상용 `unsold_data` 메시지도 Dash가 iframe으로
  보내지 않아 지도는 항상 전 구역 `#1a6b3c`(미분양 없음)로 칠해진다. 사이드패널
  `map_side_panel` 콜백 자체는 정상이므로, 고치려면 `clientside_callback`으로 window message를
  받아 store에 쓰는 다리만 놓으면 된다.
- V-World는 API 키에 등록된 도메인에서만 동작한다. 현재 `vworld_map.html`은
  `domain=https://kyungdong.cloud`로 하드코딩되어 있어 다른 호스트에서는 지도가 안 뜬다.

## Data flow gotchas

- 지역 매핑은 항상 `src/config.py`의 `BUSAN_DISTRICT_CODES`/`BUSAN_CODE_TO_NAME`/
  `BUSAN_NAME_TO_CODE`를 통해야 함 — 구·군명을 하드코딩하지 말 것.
- **`building_permits` 테이블은 성격이 다른 두 수집기가 공유한다.** `building_permit.py`(건축HUB)는
  `developer←platPlc(주소)`, `contractor←bldNm(건물명)`으로 넣고, `cheongyak.py`(청약홈 분양공고)는
  `developer←BSNS_MBY_NM(시행사)`, `contractor←CNSTRCT_ENTRPS_NM 또는 HOUSE_NM`으로 넣는다.
  즉 대시보드 "시공사" 컬럼과 시공사별 도넛차트에는 실제 시공사명과 단지명·주소가 섞여 있다.
  이 테이블을 다루는 코드를 쓸 때 두 출처가 섞여 있음을 전제할 것.
- **스케줄러는 HUG 분양가격을 수집하지 않는다.** `run_weekly_update()`의 대상은 실거래가(최근
  3개월) → 미분양 → 건축인허가 → 청약홈 4종뿐이다 (README 표는 HUG도 배치라고 적혀 있으나 코드와
  불일치). `hug_price`는 수동 실행 전용.
- **`HugPrice` 모델은 `db.py`가 아니라 `hug_price.py` 안에 정의되어 있다.** `init_db()`로는
  `hug_prices` 테이블이 생기지 않고, 같은 모듈의 `ensure_table()`을 호출해야 한다. 다만 `Base`를
  공유하므로 이 모듈을 임포트한 뒤 `init_db()`를 부르면 생성되는 임포트 순서 의존성이 있다.
- **미분양 `base_month`는 API의 `reference_date`가 아니라 실행 시점의 `date.today()`다.**
  증감률은 "직전 달에 이 수집기가 실행됐고 그 행이 DB에 있을 때"만 계산되며, 없으면 `None`이라
  급증 알림에서 조용히 빠진다. 과거 데이터를 소급 적재할 수 없는 구조.
- 국토부 API 응답은 XML이며 필드가 비어있거나 숫자가 아닐 수 있음 — `MolitBaseCollector._int`/
  `_float`/`_text`가 안전 파싱을 처리하므로 새 파서를 만들 때도 이 헬퍼를 재사용.
- `src/db.py`의 `DB_PATH`는 상대경로(`data/estate_monitor.db`)라 저장소 루트가 아닌 cwd에서
  실행하면 DB 위치가 달라진다. `src/config.py`에는 `BASE_DIR` 기준 절대경로 `DB_PATH`가 따로 있어
  두 상수가 어긋날 수 있다 — 실제로 쓰이는 쪽은 `db.py`의 상대경로다.
- `validate_api_keys()`의 내부 딕셔너리에 `HUG_PRICE_API_KEY`가 빠져 있다. 인자로 이 이름을
  넘기면 `KeyError`가 난다.
- 청약홈 API는 `cond[...]` 파라미터를 `requests`가 이중 인코딩하므로 `cheongyak.py`는 URL 문자열을
  직접 조합한다 — `params=`로 리팩터링하지 말 것.

## requirements.txt 불일치

- `python-dateutil`이 목록에 없지만 `scheduler.py`와 `busan_unsold.py`가 `relativedelta`를 쓴다
  (현재는 pandas 의존성으로 우연히 설치됨). 명시적으로 추가하는 편이 안전하다.
- `shapely`는 목록에 있으나 코드 어디서도 쓰지 않는다 (choropleth → V-World iframe 전환 잔재).

## 보안(Secrets)

`.env`에는 실제 API 키 8종(`MOLIT_APARTMENT_API_KEY`, `MOLIT_APT_RIGHTS_API_KEY`,
`MOLIT_OFFICETEL_API_KEY`, `VWORLD_API_KEY`, `BUILDING_PERMIT_API_KEY`, `BUSAN_UNSOLD_API_KEY`,
`CHEONGYAK_API_KEY`, `HUG_PRICE_API_KEY`)가 들어 있으며 gitignore 처리되어 있습니다 — 절대
커밋하거나 다른 곳에 하드코딩하지 마세요. `.env.example`은 없고 키 목록은 README.md에 있습니다.
