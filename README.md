# 부산 분양·거래시장 통합 모니터 (estate-monitor)

사내 전용 모니터링 도구. 부산 16개 구·군 아파트 분양시장에서 미분양 급증 지역을
조기 포착해, 시공사 교체·분양 전략 변경 타이밍에 선제적으로 영업 접촉하기 위해
사용합니다.

## 판단 기준

인허가(공급) 동향과 미분양(수요 부진) 동향을 교차 분석해 지역을 세 그룹으로 분류합니다.

| 인허가 | 미분양 | 판단 |
|---|---|---|
| 증가 | 낮음 | 개발 기회 지역 |
| 증가 | 급증 | 공급 과잉 경보 |
| 감소 | 높음 | 위험 지역 |

## 기술 스택

Python 3.12 · Dash · Plotly · SQLite · SQLAlchemy · schedule(APScheduler 유사 스케줄러)

## 설치 및 실행

```powershell
# 가상환경 활성화 (Windows/PowerShell)
venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

`.env` 파일에 아래 API 키를 설정합니다.

```
MOLIT_APARTMENT_API_KEY=      # 국토부 아파트 매매 실거래가
MOLIT_APT_RIGHTS_API_KEY=     # 국토부 분양권전매 실거래가
MOLIT_OFFICETEL_API_KEY=      # 국토부 오피스텔 매매 실거래가
VWORLD_API_KEY=               # V-World 지도
BUILDING_PERMIT_API_KEY=      # 건축HUB 주택인허가 (대시보드 내 검색용)
BUSAN_UNSOLD_API_KEY=         # 부산광역시 공동주택 미분양 현황
CHEONGYAK_API_KEY=            # 청약홈 분양정보
HUG_PRICE_API_KEY=            # HUG 지역별 ㎡당 분양가격
```

실행은 목적에 따라 4가지 모드를 지원합니다.

| 명령 | 동작 |
|---|---|
| `python main.py` | 대시보드 + 스케줄러 동시 실행 (기본) |
| `python main.py --dashboard` | 대시보드만 실행 |
| `python main.py --scheduler` | 스케줄러만 실행 |
| `python main.py --update` | 데이터 즉시 1회 수집 후 종료 |

대시보드 접속: http://127.0.0.1:8050

## 데이터 수집 API

| API | 용도 | 수집 방식 |
|---|---|---|
| 국토부 실거래가 (아파트·분양권·오피스텔) | 3종 | 배치 수집 (스케줄러) |
| 부산광역시 공동주택 미분양 현황 | 미분양 세대수 | 배치 수집 (스케줄러) |
| 청약홈 분양정보 | 부산 코드 600 기준 분양공고 | 배치 수집 (스케줄러) |
| HUG 지역별 ㎡당 분양가격 | 분양가 추이 | 배치 수집 (스케줄러) |
| 국토부 건축HUB 주택인허가 | 단지별 인허가 상세 | 배치 수집 없음 — 대시보드 내 실시간 검색(구·군 → 동 선택)으로만 사용 |

## 대시보드 탭 구성

- **🗺 지도** — V-World iframe 기반 부산 행정구역 지도. 구·군 클릭 시 사이드패널에 상세 정보 표시. (현재 V-World 도메인 등록 필요, 아래 알려진 이슈 참고)
- **🔔 미분양 알림** — 전월 대비 30% 이상 급증한 지역 자동 감지
- **📊 거래가 분석** — 구·군별 평균 거래가와 월별 추이
- **🏗 착공·허가** — 청약홈 기반 분양공고 통계 + 건축HUB 실시간 검색(구·군/동 선택 후 조회)

## 자동 갱신

매주 월요일 오전 7시 자동 갱신. 수집 대상은 실거래가(최근 3개월), 미분양 현황,
청약홈 분양정보, HUG 분양가격입니다. 건축HUB는 배치 대상에서 제외됩니다.

## 폴더 구조

```
estate-monitor/
├── main.py                          # 진입점 — 실행 모드에 따라 대시보드·스케줄러 기동
├── requirements.txt                 # 파이썬 의존성 목록
├── .env                              # API 키 (미커밋)
├── .gitignore
├── data/
│   ├── estate_monitor.db            # SQLite DB (미커밋)
│   ├── app.log                      # main.py 실행 로그
│   └── scheduler.log                # 스케줄러 실행 로그
├── src/
│   ├── config.py                    # .env 로드, 구·군/동 코드, API 엔드포인트, 임계값
│   ├── db.py                        # SQLAlchemy 모델(Trade, UnsoldHousing, BuildingPermit)
│   ├── scheduler.py                 # 매주 월요일 07:00 자동 갱신
│   └── collectors/
│       ├── base.py                  # 국토부 실거래가 계열 공통 베이스
│       ├── molit_apartment.py       # 아파트 매매 실거래가
│       ├── molit_apt_rights.py      # 아파트 분양권전매 실거래가
│       ├── molit_officetel.py       # 오피스텔 매매 실거래가
│       ├── busan_unsold.py          # 부산 미분양 현황
│       ├── cheongyak.py             # 청약홈 분양정보
│       ├── hug_price.py             # HUG 분양가격
│       └── building_permit.py       # 건축HUB — 배치 미사용, 대시보드 검색 로직 참고용
└── dashboards/
    ├── app.py                        # Dash 대시보드 (다크/라이트 테마 지원)
    └── assets/
        └── vworld_map.html          # V-World 지도 렌더링 HTML
```

## 알려진 이슈

- **V-World 지도**: `http://127.0.0.1:8050` 도메인을 V-World에 등록해야 지도가 정상 표시됨. 미등록 시 지도 미출력. 대안으로 Mapbox 전환 검토 중.
- **건축HUB 배치 수집 불가**: 시군구 코드 + 법정동 코드(필지 단위)가 필수 파라미터인 구조라 전체 배치 수집이 비효율적 — 대시보드 내 구·군/동 선택 검색 전용으로만 사용.
