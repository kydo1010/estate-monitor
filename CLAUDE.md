# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 레포지토리에서 작업할 때 참고하는 안내 문서입니다.

## 프로젝트 현황

이 레포지토리는 아직 동작하는 애플리케이션이 아니라 빈 껍데기(scaffold) 상태입니다. `main.py`,
`README.md`, `src/__init__.py`, `src/config.py`, `src/db.py`는 모두 존재하지만 현재 비어 있습니다.
실제 내용이 있는 파일은 `requirements.txt`와 `.env`뿐입니다. 아래에 설명하는 "아키텍처"는 이 두
파일에서 유추한 의도된 방향일 뿐, 이미 구현된 코드가 아닙니다 — 어떤 함수·클래스·모듈이 구현되어
있다고 가정하기 전에 반드시 해당 파일을 직접 읽어서 확인하세요.

## 목적 (`.env`와 의존성 파일로부터 유추)

한국 부동산 시장을 모니터링하는 도구입니다. `.env` 파일에는 한국 정부 공공데이터 API를 가리키는
API 키 3개가 정의되어 있습니다:

- `MOLIT_API_KEY` — 국토교통부(MOLIT) 부동산 실거래가 API
- `BUILDING_PERMIT_API_KEY` — 건축인허가 API
- `UNSOLD_HOUSING_API_KEY` — 미분양현황 API

의존성 목록(`requests`, `pandas`, `sqlalchemy`, `plotly`, `dash`, `python-dotenv`, `schedule`)과
종합해보면, 의도된 구조는 다음과 같습니다: 위 세 API에서 스케줄에 따라 데이터를 수집하고,
SQLAlchemy를 통해 저장하며(`.gitignore`가 `data/*.db`, `data/*.sqlite3`를 제외하는 것으로 보아
SQLite 사용), Plotly/Dash 대시보드로 시각화. `src/config.py`는 아마도 `.env` 값을 로드하는
곳이고, `src/db.py`는 아마도 SQLAlchemy 엔진/모델이 위치할 곳으로 추정되지만 — 실제로 코드가
작성된 뒤 다시 확인해야 합니다.

## 개발 환경

- Python 3.12.4, miniconda 베이스 설치에서 생성한 `venv/` 가상환경 사용
  (`venv/pyvenv.cfg` 참고).  `venv/`는 gitignore 처리되어 있습니다.
- 이 환경의 기본 셸은 Windows/PowerShell입니다.

## 명령어

```powershell
# 기존 가상환경 활성화
venv\Scripts\activate

# 의존성 설치/업데이트
pip install -r requirements.txt

# 진입점 실행 (현재는 no-op — main.py가 비어 있음)
python main.py
```

아직 테스트 스위트, 린터, 빌드 도구가 구성되어 있지 않습니다. `requirements.txt`에 먼저 추가되지
않은 이상 `pytest`, `ruff` 등이 설치되어 있다고 가정하지 마세요.

## 보안(Secrets)

`.env`에는 실제 API 키가 들어 있으며 gitignore 처리되어 있습니다 — 절대 커밋하거나 다른 곳에
하드코딩하지 마세요. 현재 작업 사본의 `.env`에는 실제 키가 아니라 한글 플레이스홀더
(`여기에_..._API_키`, "여기에 ... API 키를 입력하세요")만 들어 있습니다.