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

python main.py                # 대시보드 + 스케줄러 동시 실행 (운영, 0.0.0.0:9090)
python main.py --dashboard    # 대시보드만 (개발)
python main.py --scheduler    # 스케줄러만 (매주 월요일 07:00 자동 갱신)
python main.py --update       # 데이터 1회 즉시 갱신 후 종료
python main.py --dashboard --debug   # Dash 디버그 모드

# 개별 수집기 단독 실행 (디버깅용)
python -m src.collectors.molit_apartment --months 202606 202605
python -m src.collectors.molit_apt_rights
python -m src.collectors.molit_officetel
python -m src.collectors.busan_unsold
python -m src.collectors.gyeongnam_unsold
python -m src.collectors.cheongyak
python -m src.collectors.hug_price --start 202401 --end 202506
# 건축HUB(building_permit.py)는 배치 수집기가 폐지돼 단독 실행 커맨드가 없다 —
# 대시보드 "🏗 착공·허가" 섹션 하단의 실시간 검색으로만 조회한다.

# 스케줄러 단독 (즉시 1회 또는 상시)
python -m src.scheduler --once
python -m src.scheduler
```

`python -m dashboards.app`로 직접 띄우면 모듈 하단 `__main__` 블록이 `debug=True`로 고정해
실행합니다 (호스트·포트는 `main.py`와 동일하게 `0.0.0.0:9090`). `python main.py --dashboard`는
기본이 `debug=False`이며 `--debug`를 붙여야 디버그 모드가 됩니다 — 차이는 포트가 아니라
디버그 플래그 기본값입니다.

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
- **`src/collectors/{busan_unsold,gyeongnam_unsold,cheongyak,hug_price}.py`** — 응답 포맷이 국토부
  실거래가 API와 달라 베이스를 쓰지 않는 독립 수집기 (모듈 레벨 `run()` 함수 패턴). 건축HUB
  배치 수집기(`building_permit.py`)는 폐지·삭제됨 — 아래 "청약홈/건축HUB" 항목 참고.
- **`src/scheduler.py`** — `schedule` 라이브러리로 매주 월요일 07:00에 `run_weekly_update()` 실행.
  개별 수집기 실패는 다른 수집기를 막지 않고 로그만 남긴다(`data/scheduler.log`).
- **`main.py`** — 4가지 실행 모드 분기. 기본 모드는 스케줄러를 데몬 스레드로 백그라운드 실행하면서
  대시보드를 메인 스레드에서 블로킹 실행한다. 전체 로그는 `data/app.log`.
- **`dashboards/app.py`** — 단일 파일 Dash 앱(~1250줄). 4개 탭: 지도 / 미분양 알림 / 거래가 분석 /
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
- **지도 ↔ Dash 양방향 브리지는 폴링 방식으로 구현되어 있다** (이전에는 미완성이었으나 수정됨).
  iframe → Dash: `onDongClick`이 `window.parent.__lastGuClick`에 `{"gu":...,"dong":...}` JSON
  문자열을 써 두면, `gu-click-interval`(500ms) + `clientside_callback`이 값이 바뀐 경우에만
  읽어 `clicked-gu-store`에 쓴다(`dashboards/app.py` 약 968행). 값 파싱은 `parse_map_click()` —
  구 이름만 오던 옛 형식도 허용하되, 미확인 값은 절대 구 이름으로 흘려보내지 않는다
  (`_as_district()`가 `BUSAN_DISTRICT_NAMES`로 검증). Dash → iframe: `unsold-inject-interval`
  (1초 간격, 최대 20회)이 `unsold-data-store`를 `postMessage({type:'unsold_data'})`로 반복
  전송하고, iframe에 `layerList`가 생긴 게 확인되면 스스로 `disabled=True`로 멈춘다
  (GeoJSON 레이어 생성에 수 초 걸려 초기 메시지를 놓칠 수 있어 재전송하는 구조).
  store 이름(`clicked-gu-store`)은 구 단위이던 시절 이름 그대로이며, 바꾸면 관련 콜백 id가
  모두 따라 바뀐다.
- **V-World 인증은 `domain` 파라미터 + 브라우저 Referer 오리진 + 키 등록 도메인, 이 셋이 모두
  정확히 일치해야 통과한다.** `vworld_map.html`은 `domain`을 `window.location.protocol + '//' +
  window.location.host`로 만든다(`host` — **포트 포함**, `hostname`으로 바꾸지 말 것).
  브라우저는 비표준 포트에서 Referer에 포트를 붙이므로 `domain`도 포트를 포함해야 하고,
  **V-World 사이트의 등록 도메인에도 포트가 들어가 있어야 한다**(`http://localhost:9090`).
  실측으로 확인된 동작: Referer가 없으면(=서버 사이드 호출) 통과, Referer가
  `http://localhost/`면 통과, `http://localhost:9090/`이면 등록값에 포트가 없는 한 거부.
  즉 **접속 호스트명·포트를 바꾸면 V-World 등록 도메인도 같이 바꿔야 한다.** 서버는 `0.0.0.0`에
  바인딩되지만 공인IP로 접속하면 그 오리진이 등록돼 있지 않아 지도만 조용히 빈다 — SSH 터널로
  `localhost:9090`을 유지하거나 실도메인을 추가 등록할 것.
- V-World 에러 코드 두 개를 구분할 것: `INCORRECT_KEY`("인증키 정보가 올바르지 않습니다")는
  **키는 존재하나 등록 도메인 불일치**, `INVALID_KEY`("등록되지 않은 인증키입니다")는
  **키 자체가 없음**이다. 전자면 접속 호스트를, 후자면 `.env` 키 값을 의심해야 한다.
- **V-World 키를 `.env`에서 갱신해도 프로세스를 재시작해야 반영된다.** `VWORLD_API_KEY`는
  `src/config.py` 모듈 레벨 상수로 임포트 시점에 1회만 읽히고, `dashboards/app.py`의
  `/vworld-map.html` 라우트가 그 값을 치환해 내보낸다.

## 데이터 출처 매핑

대시보드 각 섹션이 실제로 어느 DB 테이블/API를 쓰는지 정리한 표. `dashboards/app.py`의
`load_*_df()` 함수들은 모듈 임포트 시점에 전역 df(`unsold_df`/`price_df`/`permit_df`/`trend_df`)를
1회만 만들고(위 "데이터는 모듈 임포트 시점에 1회만 로드된다" 항목 참고), 이후 콜백은 그 df를
`_filter_by_selection`으로 좁혀 재사용할 뿐 DB를 다시 쿼리하지 않는다 — 아래 표에서 "직접
쿼리"라고 명시한 것만 예외(클릭·검색 시점에 실제로 DB나 외부 API를 다시 호출).

| 화면 섹션 | 데이터 출처 | 비고 |
|---|---|---|
| 지도 위 KPI 3개(평균거래가·급증구·군·미분양최다) | `price_df`(`get_avg_price_by_district`→`Trade`) + `unsold_df`(`UnsoldHousing`) | `build_map_kpi_row`. 전역 df 필터링만, 실시간 호출 없음 |
| 🔔 미분양 알림 | `UnsoldHousing` 테이블(`unsold_df`) | 부산만 실질 지원 — 경남은 정부 API 백엔드 장애로 데이터 없음, 울산은 수집기 자체가 없음(위 항목 참고) |
| 📊 거래가 분석 | `Trade` 테이블 — 구·군별 평균은 `price_df`(`get_avg_price_by_district`), 월별 추이 라인차트는 `trend_df`(`load_trend_df`, 원본 거래 전체) | 국토부 실거래가 3종(아파트/분양권전매/오피스텔) 배치 수집 결과 |
| 🏗 착공·허가 (상단 KPI·막대그래프·"최근 인허가 내역" 표) | `BuildingPermit` 테이블(`permit_df`) — **청약홈(`cheongyak.py`) 단일 출처** | 건축HUB 배치 수집기(`building_permit.py`)는 폐지·삭제되고 그 기원 데이터도 테이블에서 전량 삭제됨(아래 참고) — 더 이상 출처 혼재 없음 |
| 건축HUB 주택인허가 검색(하단 실시간 검색 위젯) | DB 미사용 — `search_building_permit` 콜백이 건축HUB API(`HsPmsHubService`)를 클릭 시점에 직접 `requests.get()` | `permit_df`/`BuildingPermit`과 완전히 무관. 건축HUB를 쓰는 유일한 경로(배치 수집 폐지) |
| 지도 클릭 사이드패널 — 실거래가 | 동 선택 시 `Trade`를 **직접 쿼리**(`load_dong_trades`, 클릭마다 실행), 동 실거래 없으면 `price_df`(구 평균)로 대체 | 유일하게 클릭 시점에 DB를 다시 쿼리하는 실거래가 경로 |
| 지도 클릭 사이드패널 — 미분양 | `unsold_df`(`UnsoldHousing`) | 구 단위만 존재(동 정보 없음) |
| 지도 클릭 사이드패널 — 최근 인허가 | `permit_df`(`BuildingPermit`, 청약홈 단일 출처) | 착공·허가 섹션과 동일 |

**건축HUB 배치 수집 폐지 경위**: `building_permit.py`가 쌓은 데이터는 세대수·시공사가 자주
비어 있어 품질이 낮았고, 청약홈 데이터와 화면에서 구분할 방법도 없었다. `developer` 필드가
"시/도명 + 공백 + 구·군·동 + 번지/블록" 형태의 **주소**면 건축HUB 기원, 회사명·조합명이면
청약홈 기원이라는 게 확인돼(`developer←platPlc` vs `developer←BSNS_MBY_NM`, 아래 "Data flow
gotchas" 참고) 이 패턴으로 `building_permits`에서 건축HUB 기원 7,112건을 전량 삭제하고
(청약홈 기원 621건만 남김), `building_permit.py` 파일과 `scheduler.py`의
`collect_building_permits()` 호출을 제거했다. **주의**: 단순 부분일치(`developer`에 "울산광역시"
포함 등)로 판별하면 `"울산광역시도시공사"`/`"경상남도개발공사"`처럼 지역명을 포함한 정당한
청약홈 시행사명(공공기관명)까지 오탐으로 걸러진다 — 실제로 이 문제 때문에 `load_permit_df()`의
옛 `PERMIT_ADDRESS_MARKERS` 기반 시행사·시공사 "-" 치환 로직도 함께 제거했다(건축HUB 데이터가
없으니 청소할 대상 자체가 없어졌고, 남아 있었다면 같은 오탐을 계속 냈을 것). 시/도명 뒤에
**공백이 오는지**를 반드시 확인해서 주소와 기관명을 구분할 것.

## Data flow gotchas

- 지역 매핑은 항상 `src/config.py`의 `BUSAN_DISTRICT_CODES`/`BUSAN_CODE_TO_NAME`/
  `BUSAN_NAME_TO_CODE`를 통해야 함 — 구·군명을 하드코딩하지 말 것.
- **`building_permits` 테이블은 이제 청약홈(`cheongyak.py`) 단일 출처다.** 예전엔
  `building_permit.py`(건축HUB, `developer←platPlc(주소)`, `contractor←bldNm(건물명)`)와
  섞여 있었지만 배치 수집기를 폐지하며 그 기원 데이터를 전량 삭제했다(위 "데이터 출처 매핑"
  참고) — 지금은 `developer←BSNS_MBY_NM(시행사)`, `contractor←CNSTRCT_ENTRPS_NM 또는
  HOUSE_NM`만 들어온다. 건축HUB는 대시보드 실시간 검색으로만 남아 있고 `building_permits`에
  아무것도 안 쓴다.
- **스케줄러는 HUG 분양가격과 건축인허가를 수집하지 않는다.** `run_weekly_update()`의 대상은
  실거래가(최근 1개월) → 미분양 → 청약홈 3종뿐이다 (README 표는 HUG도 배치라고 적혀 있으나
  코드와 불일치). 건축인허가(건축HUB) 배치는 폐지됐고, `hug_price`는 원래부터 수동 실행 전용.
- **`HugPrice` 모델은 `db.py`가 아니라 `hug_price.py` 안에 정의되어 있다.** `init_db()`로는
  `hug_prices` 테이블이 생기지 않고, 같은 모듈의 `ensure_table()`을 호출해야 한다. 다만 `Base`를
  공유하므로 이 모듈을 임포트한 뒤 `init_db()`를 부르면 생성되는 임포트 순서 의존성이 있다.
- **미분양 `base_month`는 API의 `reference_date`가 아니라 실행 시점의 `date.today()`다.**
  증감률은 "직전 달에 이 수집기가 실행됐고 그 행이 DB에 있을 때"만 계산되며, 없으면 `None`이라
  급증 알림에서 조용히 빠진다. 과거 데이터를 소급 적재할 수 없는 구조.
- **미분양은 사실상 부산만 지원된다.** 울산은 수집기 자체가 없고, 경남(`gyeongnam_unsold.py`)은
  스케줄러가 매주 계속 호출은 하지만 정부 API 백엔드가 `SERVICETIMEOUT_ERROR`로 항상 실패해
  실제로 쌓이는 데이터가 없다 — 원인이 이 서버가 아니라 정부 쪽 인프라라 재수집을 더 이상
  추적/시도하지 않기로 했다(코드는 그대로 두되 방치). `dashboards/app.py`의
  `build_tab_unsold()`는 `region_label != "부산"`이면 빈 KPI 대신
  `UNSOLD_UNSUPPORTED_REGION_MSG` 안내 문구를 보여준다 — 이 지역들에서 미분양 데이터가
  안 보이는 건 버그가 아니라 이 상태를 반영한 것이다.
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
