# 부산 분양·거래시장 통합 모니터 (estate-monitor)

## 1. 프로젝트 개요

본 프로젝트는 부동산 분양 시장의 지역별 공급·수요 불균형을 정량 지표로 모니터링하기 위한
데이터 파이프라인 및 대시보드입니다. 부산 16개 구·군을 분석 대상으로 하며, 다음 두 지표를
핵심 분석 축으로 삼습니다.

- **공급 지표**: 건축 인허가(착공) 동향
- **수요 지표**: 미분양 현황

두 지표를 교차 분석하여 인허가 건수는 증가하는 반면 미분양 세대수도 함께 증가하는 구역을
조기에 식별함으로써, 시장 리스크를 사전에 파악하는 것을 목표로 합니다.

## 2. 주요 기능

| 기능 | 설명 | 상태 |
|---|---|---|
| 지역별 인허가 추이 비교 | 부산 16개 구·군의 건축 인허가 건수 추이 및 구간별 비교 시각화 | 구현 완료 (더미 데이터 기준) |
| 미분양 증감 자동 감지 | 구·군별 미분양 세대수 현황 및 전월 대비 증감률 산출, 임계값(30%↑) 초과 시 급증 지역으로 분류 | 구현 완료 (더미 데이터 기준) |
| 실거래가 시각화 | 지역별 평균 실거래가 및 월별 추이 시각화 | 구현 완료 (더미 데이터 기준) |
| 분양가상한제 이력 추적 | 지역별 분양가상한제 지정·해제 이력 조회 | 구현 완료 (더미 데이터 기준) |
| 지도 기반 복합 시각화 | 부산 행정구역 경계 기반 choropleth 지도에 미분양 증감률·실거래가를 결합 표시 | 구현 완료 (더미 데이터 기준) |
| 정기 자동 데이터 갱신 | 매주 월요일 오전 7시 기준 자동 데이터 수집·갱신 | 개발 예정 |
| 공공 API 실데이터 수집 | 국토부 실거래가 / 건축인허가 / 미분양현황 API로부터 실제 데이터 수집 | 개발 예정 (현재는 스키마·대시보드 검증용 더미 데이터로 대체) |

현재 저장소에는 실제 공공 API 연동 수집기가 아직 포함되어 있지 않으며,
[`src/collectors/seed_dummy_data.py`](src/collectors/seed_dummy_data.py)를 통해 생성한 더미
데이터로 DB 스키마와 대시보드 동작을 검증하는 단계입니다.

## 3. 사용 API 및 데이터 출처

[`src/config.py`](src/config.py)에 정의된 API 키를 기준으로 다음 3종의 공공 API를 사용할
예정입니다. 모두 공공데이터포털(data.go.kr)에서 제공하는 무료 공공 API입니다.

| 환경 변수명 | 데이터 출처 |
|---|---|
| `MOLIT_API_KEY` | 국토교통부(MOLIT) 부동산 실거래가 API |
| `BUILDING_PERMIT_API_KEY` | 건축인허가 API |
| `UNSOLD_HOUSING_API_KEY` | 미분양현황 API |

## 4. 기술 스택

[`requirements.txt`](requirements.txt) 기준, 역할별 구성은 다음과 같습니다.

| 구분 | 라이브러리 | 용도 |
|---|---|---|
| 데이터 수집 | `requests` | 공공 API 호출 |
| 데이터 처리 | `pandas` | 수집 데이터 가공 및 집계 |
| 데이터베이스 | `sqlalchemy` | ORM 기반 스키마 정의 및 SQLite 연동 |
| 시각화 | `plotly`, `dash` | 대시보드 UI 및 차트/지도 렌더링 |
| 지리 정보 처리 | `shapely` | 행정구역 GeoJSON 병합 및 지도 시각화 보조 |
| 환경 설정 | `python-dotenv` | `.env` 환경 변수 로드 |
| 스케줄링 | `schedule` | 정기 데이터 갱신 (개발 예정, 현재 미사용) |

## 5. 프로젝트 구조

```
estate-monitor/
├── main.py                        # 진입점 (현재 비어 있음, 구현 예정)
├── requirements.txt                # 파이썬 의존성 목록
├── .env                             # API 키 등 환경 변수 (미커밋 대상)
├── .gitignore
├── data/
│   └── estate_monitor.db          # SQLite 데이터베이스 파일 (미커밋 대상, 실행 시 자동 생성)
├── src/
│   ├── __init__.py
│   ├── config.py                  # .env 로드, 부산 16개 구·군 코드, 알림 임계값 등 전역 설정
│   ├── db.py                      # SQLAlchemy 엔진·모델(Trade, UnsoldHousing, BuildingPermit, PriceCapZone) 및 조회 헬퍼
│   └── collectors/
│       └── seed_dummy_data.py     # 실제 API 연동 전 더미 데이터 생성 스크립트 (스키마·대시보드 검증용)
└── dashboards/
    ├── __init__.py
    └── app.py                      # Dash 기반 통합 모니터링 대시보드
```

공공 API 연동 수집기(국토부 실거래가, 건축인허가, 미분양현황)는 `src/collectors/` 하위에
추가될 예정이며, 현재는 더미 데이터 생성 스크립트만 존재합니다.

## 6. 설치 및 실행 방법

Windows/PowerShell 환경을 기준으로 합니다.

```powershell
# 1. 가상환경 활성화
venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. .env 파일에 API 키 설정 (7. 환경 변수 설정 참고)

# 4. 더미 데이터 생성 (DB 스키마 및 대시보드 동작 검증용)
python -m src.collectors.seed_dummy_data

# 5. 대시보드 실행
python -m dashboards.app
```

대시보드 실행 후 브라우저에서 `http://127.0.0.1:8050` 으로 접속하여 확인합니다.

## 7. 환경 변수 설정 (.env)

프로젝트 루트에 `.env` 파일을 생성하고 아래 3개 키를 설정합니다. 각 키는 공공데이터포털
(data.go.kr)에서 해당 오픈 API를 신청하여 발급받습니다. `.env` 파일은 `.gitignore`에 등록되어
있으며, 실제 키 값은 어떠한 경우에도 저장소에 커밋하지 않습니다.

```
MOLIT_API_KEY=<국토교통부 실거래가 API 키>
BUILDING_PERMIT_API_KEY=<건축인허가 API 키>
UNSOLD_HOUSING_API_KEY=<미분양현황 API 키>
```

## 8. 갱신 주기 및 데이터 흐름

전체 데이터 흐름은 다음과 같이 구성됩니다.

```
[공공데이터포털 API]                [수집/저장]                  [시각화]
 국토부 실거래가 API   ─┐
 건축인허가 API        ─┼─▶  수집기(src/collectors)  ─▶  SQLite DB  ─▶  Dash 대시보드
 미분양현황 API        ─┘        (SQLAlchemy 저장)     (data/estate_monitor.db)  (dashboards/app.py)
```

데이터 갱신 주기는 매주 월요일 오전 7시를 기준으로 자동 수집·갱신하는 것을 목표로 하며,
`schedule` 라이브러리를 이용한 스케줄러 구현은 개발 예정 상태입니다. 현재는 개발자가
`python -m src.collectors.seed_dummy_data` 명령을 수동으로 실행하여 더미 데이터를 갱신하는
방식으로 대시보드를 검증하고 있습니다.
