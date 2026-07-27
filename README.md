# 부산 분양·거래시장 통합 모니터 (estate-monitor)

## 1. 프로젝트 개요

본 프로젝트는 부산 부동산 분양 시장의 지역별 공급·수요 불균형을 정량 지표로 모니터링하기
위한 데이터 파이프라인 및 대시보드입니다. 부산 16개 구·군을 분석 대상으로 하며, 다음 두
지표를 핵심 분석 축으로 삼습니다.

- **공급 지표**: 건축 인허가·분양 동향
- **수요 지표**: 미분양 현황

두 지표를 교차 분석하여 인허가·분양 물량은 증가하는 반면 미분양 세대수도 함께 증가하는
구역을 조기에 식별함으로써, 시공사 교체 또는 분양 전략 변경이 필요한 시점을 사전에 파악하고
해당 시점에 선제적으로 영업 접촉을 시도하는 것을 목표로 합니다.

## 2. 주요 기능

| 기능 | 설명 | 상태 |
|---|---|---|
| 미분양 현황 자동 감지 | 부산 16개 구·군별 미분양 세대수 현황 및 전월 대비 증감률 산출, 임계값(30%↑) 초과 시 급증 지역으로 분류 | 구현 완료 |
| 실거래가 시각화 | 아파트·분양권전매·오피스텔 실거래가의 지역별 평균 및 월별 추이 시각화 | 구현 완료 |
| 신규 분양공고 현황 | 청약홈 기준 아파트·오피스텔(도시형)·잔여세대 분양공고 현황(시행사·시공사·공급세대수 포함) | 구현 완료 |
| 분양가격 추이 | 주택도시보증공사(HUG) 기준 지역별 ㎡당 분양가격 추이 | 구현 완료 |
| 지도 기반 복합 시각화 | V-World 기반 부산 행정구역 지도에서 구·군 클릭 시 미분양·실거래가·인허가 상세 정보 표시 | 구현 완료 |
| 정기 자동 데이터 갱신 | 매주 월요일 오전 7시 기준 자동 데이터 수집·갱신 | 구현 완료 |
| 건축HUB 주택인허가 연동 | 국토교통부 건축HUB 주택인허가 기본개요 API 연동 시도 | 미사용 (동 단위 순회 조회 구조로 인해 현재 비활성) |

## 3. 사용 API 및 데이터 출처

[`src/config.py`](src/config.py)에 정의된 API 키를 기준으로 다음 공공 API 및 공공기관 제공
API를 사용합니다. 모두 무료로 이용 가능한 공공데이터입니다.

| 환경 변수명 | 데이터 출처 | 비고 |
|---|---|---|
| `MOLIT_APARTMENT_API_KEY` | 국토교통부 아파트 매매 실거래가 API | 공공데이터포털 |
| `MOLIT_APT_RIGHTS_API_KEY` | 국토교통부 아파트 분양권전매 실거래가 API | 공공데이터포털 |
| `MOLIT_OFFICETEL_API_KEY` | 국토교통부 오피스텔 매매 실거래가 API | 공공데이터포털 |
| `BUILDING_PERMIT_API_KEY` | 국토교통부 건축HUB 주택인허가 기본개요 API | 필지(법정동) 단위 순회 조회 구조로 인해 현재 미사용 |
| `BUSAN_UNSOLD_API_KEY` | 부산광역시 공동주택 미분양 현황 API | 공공데이터포털 |
| `CHEONGYAK_API_KEY` | 한국부동산원 청약홈 분양정보 API | 공공데이터포털 |
| `HUG_PRICE_API_KEY` | 주택도시보증공사(HUG) 지역별 분양가격 API | HUG 제공 |
| `VWORLD_API_KEY` | V-World 지도 API | 국토교통부 국토정보플랫폼 |

건축HUB 주택인허가 API는 시군구 코드와 법정동 코드를 동 단위로 순회하여 조회해야 하는 구조로,
현재 데이터 수집 파이프라인에는 포함되어 있지 않습니다.

## 4. 기술 스택

[`requirements.txt`](requirements.txt) 기준, 역할별 구성은 다음과 같습니다.

| 구분 | 라이브러리 | 용도 |
|---|---|---|
| 데이터 수집 | `requests` | 공공 API 호출 |
| 데이터 처리 | `pandas` | 수집 데이터 가공 및 집계 |
| 데이터베이스 | `sqlalchemy` | ORM 기반 스키마 정의 및 SQLite 연동 |
| 시각화 | `plotly`, `dash` | 대시보드 UI 및 차트 렌더링 |
| 지도 처리 | `shapely` | 행정구역 GeoJSON 병합 및 지도 시각화 보조 |
| 환경 설정 | `python-dotenv` | `.env` 환경 변수 로드 |
| 스케줄링 | `schedule` | 정기 데이터 갱신 |

## 5. 프로젝트 구조

```
estate-monitor/
├── main.py                          # 진입점 — 실행 모드에 따라 대시보드·스케줄러 기동
├── requirements.txt                 # 파이썬 의존성 목록
├── .env                              # API 키 등 환경 변수 (미커밋 대상)
├── .gitignore
├── data/
│   ├── estate_monitor.db            # SQLite 데이터베이스 파일 (미커밋 대상)
│   ├── app.log                      # main.py 실행 로그
│   └── scheduler.log                # 스케줄러 실행 로그
├── src/
│   ├── __init__.py
│   ├── config.py                    # .env 로드, 부산 16개 구·군 코드, API 엔드포인트, 알림 임계값 정의
│   ├── db.py                        # SQLAlchemy 엔진·세션 및 모델(Trade, UnsoldHousing, BuildingPermit) 정의
│   ├── scheduler.py                 # 매주 월요일 07:00 자동 갱신 스케줄러
│   └── collectors/
│       ├── base.py                  # 국토부 실거래가 계열 수집기 공통 베이스 클래스
│       ├── molit_apartment.py       # 아파트 매매 실거래가 수집기
│       ├── molit_apt_rights.py      # 아파트 분양권전매 실거래가 수집기
│       ├── molit_officetel.py       # 오피스텔 매매 실거래가 수집기
│       ├── busan_unsold.py          # 부산광역시 공동주택 미분양 현황 수집기
│       ├── cheongyak.py             # 청약홈 분양정보(아파트·오피스텔·잔여세대) 수집기
│       ├── hug_price.py             # HUG 지역별 ㎡당 분양가격 수집기
│       └── building_permit.py       # 건축HUB 연동 시도 — 현재 미사용
└── dashboards/
    ├── __init__.py
    ├── app.py                        # Dash 기반 통합 모니터링 대시보드
    └── assets/
        └── vworld_map.html          # V-World 지도 렌더링용 HTML
```

## 6. 설치 및 실행 방법

Windows/PowerShell 환경을 기준으로 합니다.

```powershell
# 1. 가상환경 활성화
venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. .env 파일에 API 키 설정 (7. 환경 변수 설정 참고)

# 4. 대시보드 실행 (개발 모드)
python main.py --dashboard
```

`main.py`는 목적에 따라 아래 4가지 실행 모드를 지원합니다.

| 인수 | 설명 |
|---|---|
| `python main.py` | 대시보드와 스케줄러를 동시에 실행 (운영 모드) |
| `python main.py --dashboard` | 대시보드만 실행 (개발용) |
| `python main.py --scheduler` | 스케줄러만 실행 (백그라운드 서버) |
| `python main.py --update` | 데이터를 1회 즉시 갱신 후 종료 |

대시보드 실행 후 브라우저에서 `http://127.0.0.1:8050`으로 접속하여 확인합니다.

## 7. 환경 변수 설정 (.env)

프로젝트 루트에 `.env` 파일을 생성하고 아래 키를 설정합니다. 각 키는 발급처를 통해 사전에
신청하여 발급받아야 합니다. `.env` 파일은 `.gitignore`에 등록되어 있으며, 실제 키 값은 어떠한
경우에도 저장소에 커밋하지 않습니다.

```
MOLIT_APARTMENT_API_KEY=<국토교통부 아파트 매매 실거래가 API 키>
MOLIT_APT_RIGHTS_API_KEY=<국토교통부 아파트 분양권전매 실거래가 API 키>
MOLIT_OFFICETEL_API_KEY=<국토교통부 오피스텔 매매 실거래가 API 키>
BUILDING_PERMIT_API_KEY=<국토교통부 건축HUB 주택인허가 API 키>
BUSAN_UNSOLD_API_KEY=<부산광역시 공동주택 미분양 현황 API 키>
CHEONGYAK_API_KEY=<한국부동산원 청약홈 분양정보 API 키>
HUG_PRICE_API_KEY=<주택도시보증공사(HUG) 지역별 분양가격 API 키>
```

발급처는 다음과 같습니다.

- 국토교통부 실거래가 3종, 건축HUB 주택인허가, 청약홈 분양정보: 공공데이터포털(data.go.kr)
- 부산광역시 공동주택 미분양 현황: 공공데이터포털(data.go.kr)
- HUG 지역별 분양가격: 주택도시보증공사(khug.or.kr)

지도 시각화에는 별도로 V-World API 키(`VWORLD_API_KEY`)가 필요하며, 국토교통부 국토정보
플랫폼(vworld.kr)에서 발급받습니다.

## 8. 데이터 수집 방법

각 수집기는 단독으로도 실행할 수 있습니다. 최초 수집 시에는 최근 3개월 치 데이터를 대상으로
수집하는 것을 권장합니다.

```powershell
# 실거래가 (아파트 / 분양권전매 / 오피스텔) — 최근 3개월 권장
python -m src.collectors.molit_apartment --months 202606 202605 202604
python -m src.collectors.molit_apt_rights --months 202606 202605 202604
python -m src.collectors.molit_officetel --months 202606 202605 202604

# 미분양 현황 (전체 조회, 별도 기간 지정 불필요)
python -m src.collectors.busan_unsold

# 청약홈 분양정보 (전체 조회, 별도 기간 지정 불필요)
python -m src.collectors.cheongyak

# HUG 지역별 분양가격 (기본값: 최근 12개월)
python -m src.collectors.hug_price --start 202401 --end 202506
```

위 개별 명령을 순차 실행하는 대신, 다음 명령으로 전체 수집기를 일괄 실행할 수 있습니다.

```powershell
python main.py --update
```

## 9. 갱신 주기 및 데이터 흐름

전체 데이터 흐름은 다음과 같이 구성됩니다.

```
[공공데이터포털 등 API 제공처]                [수집·저장]                    [시각화]
 국토부 실거래가 API (3종)   ─┐
 부산시 미분양현황 API      ─┤
 청약홈 분양정보 API        ─┼─▶  수집기(src/collectors)  ─▶  SQLite DB  ─▶  Dash 대시보드
 HUG 분양가격 API           ─┤        (SQLAlchemy 저장)     (data/estate_monitor.db)  (dashboards/app.py)
 V-World 지도 API           ─┘
```

데이터 갱신 주기는 매주 월요일 오전 7시를 기준으로 자동 수집·갱신하도록 구성되어 있으며,
`src/scheduler.py`가 이를 담당합니다. 갱신 순서는 실거래가(최근 3개월) → 미분양 현황 →
청약홈 분양정보 순이며, 개별 수집기 실행이 실패하더라도 나머지 수집기는 계속 실행되고 실패
내역은 로그(`data/scheduler.log`)에 기록됩니다.
