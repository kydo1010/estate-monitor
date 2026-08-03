"""
dashboards/app.py
부산·울산·경남 분양·거래시장 통합 모니터 (라이트모드 고정 + V-World 지도)

실행: python -m dashboards.app → http://127.0.0.1:8050
"""

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import requests
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, State, clientside_callback

from src.config import (
    UNSOLD_SPIKE_THRESHOLD_PCT, VWORLD_API_KEY, VWORLD_DOMAIN,
    BUSAN_DISTRICT_CODES, BUSAN_DONG_CODES,
    ULSAN_DISTRICT_CODES, ULSAN_DONG_CODES,
    GYEONGNAM_DISTRICT_CODES, GYEONGNAM_DONG_CODES,
    ALL_DISTRICT_CODES,
)
from src.db import (
    get_avg_price_by_district, get_session,
    UnsoldHousing, BuildingPermit, Trade,
)

# 핸들러는 main.py의 basicConfig(data/app.log + stdout)를 그대로 탄다.
# 이 모듈을 단독 임포트하면 핸들러가 없어 로그가 보이지 않는 것이 정상이다.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 색상 토큰 (라이트모드 고정)
# ---------------------------------------------------------------------------
LIGHT_COLORS = {
    "bg":       "#f5f7fa",
    "surface":  "#ffffff",
    "surface2": "#f0f3f8",
    "border":   "#dde3ed",
    "accent":   "#2563eb",
    "accent2":  "#0ea5e9",
    "danger":   "#dc2626",
    "ok":       "#16a34a",
    "warning":  "#d97706",
    "text":     "#1a2234",
    "muted":    "#64748b",
    "chart_bg": "#ffffff",
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def get_plotly_template(colors: dict) -> dict:
    return dict(
        paper_bgcolor=colors["chart_bg"],
        plot_bgcolor=colors["chart_bg"],
        font=dict(color=colors["text"], family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
        margin=dict(l=16, r=16, t=48, b=16),
    )


def get_card_style(colors: dict) -> dict:
    return {
        "background": colors["surface"],
        "border": f"1px solid {colors['border']}",
        "borderRadius": "12px",
        "padding": "20px 24px",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.06)",
    }


def get_kpi_card_style(colors: dict) -> dict:
    return {**get_card_style(colors), "textAlign": "center", "flex": "1", "minWidth": "140px"}


def get_table_style(colors: dict) -> dict:
    return {
        "style_table": {"overflowX": "auto"},
        "style_cell": {
            "backgroundColor": colors["surface"],
            "color": colors["text"],
            "border": f"1px solid {colors['border']}",
            "padding": "10px 14px",
            "fontSize": "18px",
            "fontFamily": "Malgun Gothic, Apple SD Gothic Neo, sans-serif",
        },
        "style_header": {
            "backgroundColor": colors["surface2"],
            "color": colors["muted"],
            "fontWeight": "600",
            "border": f"1px solid {colors['border']}",
            "fontSize": "17px",
            "letterSpacing": "0.05em",
        },
        "style_data_conditional": [
            {"if": {"row_index": "odd"}, "backgroundColor": colors["surface2"]},
        ],
    }


def kpi(colors, label, value, color=None, sub=None):
    return html.Div(style=get_kpi_card_style(colors), children=[
        html.P(label, style={"color": colors["muted"], "fontSize": "15px",
                              "letterSpacing": "0.1em", "margin": "0 0 8px",
                              "textTransform": "uppercase"}),
        html.P(str(value), style={"color": color or colors["text"], "fontSize": "24px",
                                   "fontWeight": "700", "margin": "0", "lineHeight": "1"}),
        html.P(sub or "", style={"color": colors["muted"], "fontSize": "15px", "margin": "6px 0 0"}),
    ])


def fmt_date(value) -> str:
    """DataFrame의 min()/max() 결과를 YYYY-MM-DD로. 비었거나 파싱 불가면 '-'."""
    if value is None or pd.isna(value):
        return "-"
    ts = pd.to_datetime(value, errors="coerce")
    return "-" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def fmt_period(series) -> str:
    """`YYYY-MM-DD ~ YYYY-MM-DD`. 시리즈가 비었으면 '-'."""
    if series is None or len(series) == 0:
        return "-"
    return f"{fmt_date(series.min())} ~ {fmt_date(series.max())}"


def fmt_won(value_manwon) -> str:
    """
    DB/DataFrame에 만원 단위로 저장된 금액(Trade.deal_amount 등)을 원 단위
    콤마 표기로 바꾼다. 예: 233 → "2,330,000원". None/NaN이면 '-'.
    """
    if value_manwon is None or (isinstance(value_manwon, float) and pd.isna(value_manwon)):
        return "-"
    return f"{round(value_manwon * 10000):,.0f}원"


def data_banner(colors, title, *lines):
    """
    탭 콘텐츠 최상단의 데이터 출처·기간 배너.

    기간·건수는 전부 호출부에서 DataFrame으로 계산해 넘긴다. 여기에 날짜나
    건수를 하드코딩하면 DB가 갱신돼도 화면만 과거에 머무른다.
    """
    return html.Div(style={
        "background": colors["surface2"],
        "border": f"1px solid {colors['border']}",
        "borderLeft": f"3px solid {colors['accent2']}",
        "borderRadius": "8px",
        "padding": "12px 16px",
        "marginBottom": "16px",
    }, children=[
        html.P(title, style={"color": colors["text"], "fontSize": "18px",
                             "fontWeight": "700", "margin": "0 0 4px"}),
        *[html.P(line, style={"color": colors["muted"], "fontSize": "15px",
                              "margin": "0"})
          for line in lines if line],
    ])

# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

UNSOLD_DF_COLUMNS = ["region", "지역구", "기준월", "미분양세대수", "전월세대수", "증감률", "급증여부"]


def load_unsold_df():
    with get_session() as s:
        rows = s.query(UnsoldHousing).order_by(UnsoldHousing.change_rate.desc()).all()
        df = pd.DataFrame([{
            "region": r.region, "지역구": r.district, "기준월": r.base_month,
            "미분양세대수": r.unsold_count, "전월세대수": r.prev_month_count,
            "증감률": r.change_rate,
            "급증여부": (r.change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT,
        } for r in rows])
        # rows가 비면 pd.DataFrame([])는 컬럼이 아예 없는 0x0 프레임이 되어
        # 아래 unsold_df["지역구"] 같은 참조가 KeyError로 죽는다 (map_side_panel,
        # build_tab_unsold에서 실제로 재현됨). 컬럼을 명시해 빈 데이터도 정상
        # "데이터 없음"으로 처리되게 한다.
        if df.empty:
            return pd.DataFrame(columns=UNSOLD_DF_COLUMNS)

        # region 컬럼이 nullable=False로 선언되기 전에 적재된 레거시 행은 region=None으로
        # 남아 있다 (load_price_df의 legacy Trade 케이스와 동일). None인 채로 두면
        # _filter_by_selection의 df["region"] == "부산" 비교가 항상 False가 되어
        # 미분양 알림 섹션이 어떤 지역을 선택해도 계속 빈 상태로 보인다.
        missing = df["region"].isna()
        n_missing = int(missing.sum())
        if n_missing:
            df.loc[missing, "region"] = df.loc[missing, "지역구"].map(DISTRICT_TO_REGION)
            n_unresolved = int(df["region"].isna().sum())
            df.loc[df["region"].isna(), "region"] = "미상"
            logger.info(
                "load_unsold_df: region 없는 %d행 중 %d행 역보정, %d행 '미상' 처리",
                n_missing, n_missing - n_unresolved, n_unresolved,
            )
        return df

def load_price_df():
    end, start = date.today(), date.today() - timedelta(days=90)
    rows = get_avg_price_by_district(start, end)
    df = pd.DataFrame(rows, columns=["region", "지역구", "평균거래가", "거래건수"])
    if df.empty:
        return df

    # region이 nullable이던 확장 이전에 수집된 레거시 거래는 region=None으로
    # 묶여 나온다. district명으로 역보정하고, 그래도 못 구하면 조용히 사라지지
    # 않도록 "미상"으로 명시해 둔다 (지역 선택 필터에서 존재가 드러나야 한다).
    missing = df["region"].isna()
    n_missing = int(missing.sum())
    if n_missing:
        df.loc[missing, "region"] = df.loc[missing, "지역구"].map(DISTRICT_TO_REGION)
        n_unresolved = int(df["region"].isna().sum())
        df.loc[df["region"].isna(), "region"] = "미상"
        logger.info(
            "load_price_df: region 없는 %d행 중 %d행 역보정, %d행 '미상' 처리",
            n_missing, n_missing - n_unresolved, n_unresolved,
        )
    return df

# permit_df 정제 규칙.
#
# building_permits 테이블은 성격이 다른 두 수집기가 공유한다 (CLAUDE.md 참고).
# building_permit.py(건축HUB)는 developer←platPlc(주소), contractor←bldNm(건물명)을
# 넣으므로 "시행사"에 주소가, "시공사"에 단지명이 들어온 행이 섞인다.
# 시행사 값의 주소 흔적으로 그런 행을 골라내 두 컬럼을 "-"로 비운다.
# (행 자체는 남긴다 — 지역구·인허가일·세대수는 그대로 쓸 수 있는 값이다.)
PERMIT_ADDRESS_MARKERS = ("부산광역시", "경상남도", "블록")

# 2020년 이전 인허가 건은 극소수인데 x축을 20년으로 늘려 최근 추세를 눌러버린다.
PERMIT_MIN_DATE = pd.Timestamp("2020-01-01")

# 부산·울산·경남 전체 시·군·구명. 지도가 이제 세 지역을 모두 다루므로 클릭 검증도
# 부산만으로 좁혀 두면 안 된다 (_as_district 참고).
ALL_DISTRICT_NAMES = set(ALL_DISTRICT_CODES.values())

# 지역구명 → region 추정 맵. trend_df는 load_trend_df()가 Trade.region을 아예
# select하지 않아(집계용 df라 원본에 region이 있어도 컬럼을 안 가져옴) 상단 지역
# 선택 바로 필터링하려면 지역구명에서 역으로 추정하는 수밖에 없다. unsold_df는 DB의
# UnsoldHousing.region 컬럼을, price_df는 get_avg_price_by_district가 Trade.region까지
# group by에 포함하므로, permit_df는 BuildingPermit.region 컬럼을 그대로 쓴다
# (_filter_by_selection 참고) — 다만 price_df는 레거시 데이터의 None 보정에 이 맵을
# 재사용한다. 부산·울산 사이에 이름이 겹치는 구가 있다(중구·남구·동구·북구) — 울산
# 데이터가 아직 trend_df에 전혀 없으므로, 겹치는 이름은 마지막에 덮어쓰는 부산이 이긴다.
DISTRICT_TO_REGION = {
    **{name: "경남" for name in GYEONGNAM_DISTRICT_CODES.values()},
    **{name: "울산" for name in ULSAN_DISTRICT_CODES.values()},
    **{name: "부산" for name in BUSAN_DISTRICT_CODES.values()},
}

PERMIT_DF_COLUMNS = ["region", "지역구", "인허가일", "세대수", "시행사", "시공사"]


def load_permit_df():
    with get_session() as s:
        rows = s.query(BuildingPermit).all()
        df = pd.DataFrame([{"region": r.region, "지역구": r.district, "인허가일": r.permit_date,
                            "세대수": r.household_count, "시행사": r.developer,
                            "시공사": r.contractor} for r in rows])
    if df.empty:
        return pd.DataFrame(columns=PERMIT_DF_COLUMNS)

    n_raw = len(df)

    # (1) 부산·울산·경남이 아닌 region 제거. BuildingPermit.region은 이제 수집기가
    # 항상 채우는 NOT NULL 컬럼이라(트레이드/미분양과 동일 패턴) 이 값을 그대로 쓴다
    # — 지역구명(district)으로 걸렀다면 창원시 하위구가 "성산구"처럼 config.py 표기와
    # 다르게 들어온 행이나 "OO지구" 같은 오인식 값이 전부 걸러져 버렸을 것이다.
    df = df[df["region"].isin(("부산", "울산", "경남"))]
    n_bad_district = n_raw - len(df)

    # (2) 2020-01-01 이전 인허가일 제거.
    #     인허가일 컬럼은 원래 dtype(date)을 유지해야 한다 — Timestamp로 바꾸면
    #     사이드패널의 astype(str)이 "2026-07-24 00:00:00"으로 늘어진다.
    #     그래서 비교용 시리즈만 따로 파싱하고 원본은 건드리지 않는다.
    #     파싱 불가/결측(NaT)은 "2020년 이전"이라 단정할 수 없으므로 남긴다.
    parsed = pd.to_datetime(df["인허가일"], errors="coerce")
    n_before = len(df)
    df = df[~(parsed < PERMIT_MIN_DATE)].copy()
    n_too_old = n_before - len(df)

    # (3) 시행사에 주소가 들어온 행의 시행사·시공사를 "-"로 치환
    polluted = pd.Series(False, index=df.index)
    developer = df["시행사"].fillna("")
    for marker in PERMIT_ADDRESS_MARKERS:
        polluted |= developer.str.contains(marker, regex=False)
    df.loc[polluted, ["시행사", "시공사"]] = "-"

    logger.info(
        "permit_df 정제: %d행 → %d행 "
        "(region 없음/부산·울산·경남 외 %d행 제거, %s 이전 %d행 제거, 시행사·시공사 오염 %d행 '-' 치환)",
        n_raw, len(df), n_bad_district, PERMIT_MIN_DATE.date(), n_too_old,
        int(polluted.sum()),
    )
    return df

# 지도 GeoJSON은 **행정동**(adm_nm)이고 Trade.dong은 **법정동**이라 이름이
# 일대일로 맞지 않는다. 이름 그대로 비교하면 부산 전체 거래의 14%밖에 안 붙는다.
#   행정동 보수동  ← 법정동 보수동1가·2가·3가   ('N가' 꼬리)
#   행정동 영주1동·영주2동 ← 법정동 영주동        (행정동 쪽 숫자)
#   행정동 일광읍  ← 법정동 '일광읍 삼성리'       (기장군 읍·면은 '읍 + 리')
# 아래 두 규칙으로 정규화하면 97.7%가 붙고, 나머지(예: 동래구 낙민동 →
# 행정동 복산동)는 이름 자체가 달라 문자열로는 맞출 수 없다. 그때는 호출부가
# 구 평균으로 fallback 한다.
_DONG_GA_RE   = re.compile(r"\d+가$")
_DONG_NUM_RE  = re.compile(r"(\d+)(동|가)$")


def normalize_dong(name: str) -> str:
    """'보수동2가'→'보수동', '영주1동'→'영주동'. 비교 전용 키."""
    if not name:
        return ""
    n = _DONG_GA_RE.sub("", str(name).strip())
    return _DONG_NUM_RE.sub(r"\2", n)


def dong_match_keys(beopjeong_dong: str) -> set:
    """법정동 이름 하나가 매칭될 수 있는 행정동 키들."""
    if not beopjeong_dong:
        return set()
    keys = {normalize_dong(beopjeong_dong)}
    if " " in str(beopjeong_dong):          # '일광읍 삼성리' → '일광읍'
        keys.add(normalize_dong(str(beopjeong_dong).split()[0]))
    return keys


def load_dong_trades(gu: str, dong: str, days: int = 90) -> pd.DataFrame:
    """
    클릭한 행정동에 해당하는 최근 실거래를 Trade에서 직접 조회한다.

    구 단위로 좁혀 DB에서 가져온 뒤(수백 행) 동 매칭은 파이썬에서 한다 —
    정규화 규칙을 SQL로 옮기면 읽기도 어렵고 DB별로 깨진다.
    """
    end, start = date.today(), date.today() - timedelta(days=days)
    with get_session() as s:
        rows = s.query(Trade.dong, Trade.complex_name, Trade.deal_amount,
                       Trade.area_m2, Trade.deal_date).filter(
            Trade.district == gu,
            Trade.deal_date >= start, Trade.deal_date <= end,
        ).all()

    df = pd.DataFrame(rows, columns=["법정동", "단지명", "거래금액", "전용면적", "거래일"])
    if df.empty or not dong:
        return df.iloc[0:0]

    target = normalize_dong(dong)
    return df[df["법정동"].map(lambda d: target in dong_match_keys(d))].copy()


def load_trend_df():
    with get_session() as s:
        rows = s.query(Trade).all()
        df = pd.DataFrame([{"지역구": r.district, "거래금액": r.deal_amount,
                             "거래일": r.deal_date} for r in rows])
        if df.empty:
            return df
        df["월"] = pd.to_datetime(df["거래일"]).dt.to_period("M").astype(str)
        return df

unsold_df  = load_unsold_df()
price_df   = load_price_df()
permit_df  = load_permit_df()
trend_df   = load_trend_df()

updated_at = date.today().strftime("%Y-%m-%d")

# 지도(iframe)의 구·군 색상용 {"region_구·군명": 미분양세대수} 딕셔너리.
# 부산·울산 사이에 이름이 겹치는 구(중구·남구·동구·북구)가 있어 지역구명만으로는
# 키가 충돌한다 — region을 접두어로 붙여 구분한다.
# - 한 구에 여러 기준월 행이 있을 수 있어 drop_duplicates로 첫 행만 남긴다.
#   unsold_df는 증감률 내림차순이므로 map_side_panel의 `.values[0]`과 같은 행을 고른다.
# - numpy 정수/NaN은 그대로 두면 JSON 직렬화나 iframe 쪽 비교에서 걸리므로
#   파이썬 int로 정규화한다.
unsold_dict = (
    {f"{region}_{district}": int(count) for (region, district), count in
     unsold_df.drop_duplicates(["region", "지역구"])
              .set_index(["region", "지역구"])["미분양세대수"].fillna(0).items()}
    if not unsold_df.empty else {}
)

# 지도 색상 모드(실거래가 기준)용 {"region_구·군명": 평균거래가(만원)} 딕셔너리.
# unsold_dict와 동일한 키 규칙(region 접두어)을 쓴다. 구간 판정(분위수 계산)은
# unsold와 마찬가지로 서버가 아니라 iframe(JS)이 currentSelection.region 기준으로
# 한다 — 여기서는 원본 평균가만 넘긴다.
price_dict = (
    {f"{region}_{district}": float(avg) for (region, district), avg in
     price_df.drop_duplicates(["region", "지역구"])
             .set_index(["region", "지역구"])["평균거래가"].items()}
    if not price_df.empty else {}
)

# 섹션 제목/구분선 스타일. build_shell()과 render_*_section 콜백들이 함께 쓰므로
# 셸 안 지역 변수 대신 모듈 레벨 상수로 둔다 (라이트모드 고정이라 재계산 불필요).
SECTION_WRAP_STYLE = {"marginTop":"48px","paddingTop":"32px",
                       "borderTop":f"1px solid {LIGHT_COLORS['border']}"}
SECTION_TITLE_STYLE = {"color":LIGHT_COLORS["text"],"fontSize":"22px","fontWeight":"700",
                        "margin":"0 0 20px"}


def _filter_by_selection(df, sel, district_col="지역구"):
    """
    상단 지역 선택 바(selected-region-store)의 {"region","district"}에 맞춰 df를 좁힌다.

    df에 'region' 컬럼이 있으면(unsold_df, price_df, permit_df) 그대로 쓰고, 없으면
    (trend_df — load_trend_df()가 Trade.region을 select하지 않음) DISTRICT_TO_REGION으로
    지역구명에서 역추정한다.
    """
    if df.empty:
        return df
    region, district = sel.get("region"), sel.get("district")
    region_series = df["region"] if "region" in df.columns else df[district_col].map(DISTRICT_TO_REGION)
    out = df[region_series == region]
    if district:
        out = out[out[district_col] == district]
    return out

# ---------------------------------------------------------------------------
# 탭별 레이아웃
# ---------------------------------------------------------------------------

def build_map_kpi_row(colors, unsold_df, price_df):
    """
    지도 탭 상단 KPI 3개(전체 평균 거래가/급증 구·군/미분양 최다).
    render_map_kpi_section 콜백이 selected-region-store가 바뀔 때마다
    _filter_by_selection으로 좁힌 unsold_df/price_df를 넘겨 다시 계산한다.
    unsold_df가 비어 있으면(예: 미분양 수집기가 없는 울산 전체 선택) "-"로 표시한다.
    """
    n_spike_local = int(unsold_df["급증여부"].sum()) if not unsold_df.empty else 0
    return html.Div(style={"display":"flex","gap":"16px","marginBottom":"16px","flexWrap":"wrap"},
             children=[
                 kpi(colors, "전체 평균 거래가",
                     fmt_won(price_df['평균거래가'].mean()) if not price_df.empty else "-",
                     colors["accent"]),
                 kpi(colors, "급증 구·군", n_spike_local, colors["danger"], "미분양 30%↑"),
                 kpi(colors, "미분양 최다",
                     unsold_df.iloc[0]["지역구"] if not unsold_df.empty else "-",
                     colors["warning"],
                     f"{int(unsold_df.iloc[0]['미분양세대수']):,}세대" if not unsold_df.empty else ""),
             ])


def build_tab_map(colors):
    CARD = get_card_style(colors)

    base_month = unsold_df["기준월"].max() if not unsold_df.empty else "-"

    return html.Div([
        data_banner(
            colors,
            f"미분양 현황 기준월 {base_month}",
            "출처: 부산광역시 공동주택 미분양 현황 API · 경상남도 미분양현황 API",
            "매주 월요일 07:00 자동 갱신",
        ),
        html.Div(id="map-kpi-row"),
        html.Div([
            html.Div(style=CARD, children=[
                html.P("구·군을 클릭하면 상세 정보를 확인할 수 있습니다.",
                       style={"color":colors["muted"],"fontSize":"17px","margin":"0 0 10px"}),
                html.Iframe(
                    id="vworld-iframe",
                    src="/vworld-map.html",
                    style={"width":"100%","height":"560px","border":"none","borderRadius":"8px"},
                ),
                # 지도 색상 기준 토글 — 기본은 미분양(기존과 동일 동작),
                # 실거래가로 바꾸면 iframe이 현재 선택된 지역 내 5분위로 재계산해 칠한다.
                # 세그먼트(pill) 토글처럼 보이게 하는 실제 배경색 전환은
                # assets/custom.css의 #map-color-mode 규칙(:has(input:checked))이
                # 담당한다 — labelStyle/inputStyle은 옵션별로 다르게 줄 수 없어
                # "선택된 것만 다른 배경색"은 인라인 style만으로는 표현이 안 된다.
                # inputStyle로 라디오 원(circle) 자체만 시각적으로 숨긴다.
                dcc.RadioItems(
                    id="map-color-mode",
                    options=[
                        {"label": "실거래가 기준", "value": "price"},
                        {"label": "미분양 기준", "value": "unsold"},
                    ],
                    value="price",
                    inline=True,
                    inputStyle={"position": "absolute", "opacity": 0, "width": 0, "height": 0},
                    style={"marginTop": "12px"},
                ),
            ]),
            html.Div(id="map-side-panel", style={**CARD, "marginTop":"16px", "minHeight":"160px"}, children=[
                html.P("← 지도에서 구·군을 클릭하세요",
                       style={"color":colors["muted"],"fontSize":"18px",
                              "marginTop":"20px","textAlign":"center"}),
            ]),
        ]),
        dcc.Store(id="clicked-gu-store"),
        # 지도(iframe) → Dash 브리지.
        # iframe의 onDongClick이 window.parent.__lastGuClick에
        # '{"gu":"중구","dong":"보수동"}' JSON 문자열을 써 두면 이 Interval이
        # 폴링해서 clicked-gu-store로 옮긴다 (아래 clientside_callback).
        # store 이름은 구 단위 시절 그대로다 — 바꾸면 콜백 id가 전부 따라 바뀐다.
        # 예전의 html.Script + CustomEvent 방식은 두 가지 이유로 동작하지 않았다:
        #   (1) React가 렌더한 <script>는 브라우저가 실행하지 않는다
        #   (2) 'dash-store-update'라는 이벤트를 Dash가 듣지 않는다
        dcc.Interval(id="gu-click-interval", interval=500, n_intervals=0),

        # Dash → 지도(iframe) 브리지. 미분양 세대수를 postMessage로 넘겨야
        # iframe이 구별 색을 칠한다 (넘기지 않으면 전 구역이 #1a6b3c로 남는다).
        dcc.Store(id="unsold-data-store", data=unsold_dict),
        # iframe은 외부(GitHub)에서 행정동 GeoJSON을 받아 레이어를 만들기까지
        # 수 초가 걸리고, 그 전에는 message 리스너조차 등록돼 있지 않을 수 있다.
        # 그래서 1초에 한 번 재전송하고, 레이어가 실제로 생긴 것을 확인하면
        # 아래 clientside_callback이 disabled=True를 돌려 스스로 멈춘다
        # (최대 20초. 그 안에 지도가 못 뜨면 어차피 칠할 대상이 없다).
        dcc.Interval(id="unsold-inject-interval", interval=1000,
                     n_intervals=0, max_intervals=20),

        # 실거래가 색상 모드용 데이터. unsold-data-store와 별개 채널로 둔다.
        # 최초 진입 시 주입은 unsold-inject-interval이 이 스토어도 함께 읽어
        # 처리하고(map-color-mode 기본값이 "price"라 필수), 이후 토글 시
        # 재전송은 map-color-mode의 clientside_callback이 담당한다.
        dcc.Store(id="price-data-store", data=price_dict),
    ])


def build_tab_unsold(colors, df):
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)
    PT = get_plotly_template(colors)

    spike_df = df[df["급증여부"]].copy()
    n_spike_local = len(spike_df)
    n_total = len(df)
    region_label = df["region"].iloc[0] if not df.empty else ""

    bar_df = df.sort_values("미분양세대수", ascending=True)
    fig = go.Figure(go.Bar(
        x=bar_df["미분양세대수"], y=bar_df["지역구"], orientation="h",
        marker_color=[colors["danger"] if v else colors["accent"] for v in bar_df["급증여부"]],
        text=bar_df["증감률"].apply(lambda x: f"{x:+.1f}%" if x else ""),
        textposition="outside", textfont=dict(color=colors["text"], size=15),
    ))
    fig.update_layout(**PT, title="구·군별 미분양 세대수  ·  빨간색 = 전월 대비 30%↑",
                      height=560, xaxis=dict(gridcolor=colors["border"]),
                      yaxis=dict(gridcolor=colors["border"]))

    spike_rows = spike_df[["지역구","기준월","미분양세대수","전월세대수","증감률"]].copy()
    spike_rows["증감률"] = spike_rows["증감률"].apply(lambda x: f"{x:+.1f}%")

    base_month = df["기준월"].max() if not df.empty else "-"
    # 급증이 0건인 이유는 대개 "급증이 없어서"가 아니라 "전월 행이 없어 증감률을
    # 계산하지 못해서"다 (base_month가 API 기준일이 아닌 실행일이라 소급이 안 된다).
    # 빈 표를 보고 안심하지 않도록 그 사정을 배너에 적어 둔다.
    spike_note = ("※ 현재 전월 비교 데이터 미수집 — 증감률을 계산할 수 없어 급증 판정이 비어 있습니다"
                  if n_spike_local == 0 else None)

    return html.Div([
        data_banner(
            colors,
            f"미분양 현황 기준월 {base_month}",
            "출처: 부산광역시 공동주택 미분양 현황 API · 경상남도 미분양현황 API",
            "매주 월요일 07:00 자동 갱신",
            spike_note,
        ),
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi(colors, "모니터링 지역", n_total,
                                sub=f"{region_label} {n_total}개 구·군" if region_label else "데이터 없음"),
                            kpi(colors, "급증 타깃", n_spike_local, colors["danger"],
                                f"전월 대비 {UNSOLD_SPIKE_THRESHOLD_PCT:.0f}%↑"),
                            kpi(colors, "정상 지역", n_total - n_spike_local, colors["ok"])]),
        html.Div(style={**CARD,"marginBottom":"24px","borderLeft":f"3px solid {colors['danger']}"}, children=[
            html.P("⚠  영업 우선 타깃 — 시공사 교체 또는 분양 전략 변경 가능성 높음",
                   style={"color":colors["danger"],"fontWeight":"600","margin":"0 0 16px","fontSize":"18px"}),
            dash_table.DataTable(data=spike_rows.to_dict("records"),
                columns=[{"name":c,"id":c} for c in spike_rows.columns], **TABLE_STYLE)
            if not spike_rows.empty else html.P("현재 급증 지역 없음", style={"color":colors["muted"]}),
        ]),
        dcc.Graph(figure=fig),
    ])


def build_tab_price(colors, df, tdf, region_label="전체"):
    PT = get_plotly_template(colors)

    # 기간·건수는 집계본(df)이 아니라 거래 원본(tdf)에서 뽑는다.
    # df는 구·군 16행짜리 평균 집계라 거래일 자체가 들어 있지 않다.
    banner = data_banner(
        colors,
        f"실거래 {len(tdf):,}건  ·  {fmt_period(tdf['거래일'] if not tdf.empty else None)}",
        "출처: 국토교통부 실거래가 API (아파트·분양권 전매·오피스텔 3종)",
        "최근 3개월 · 매주 월요일 07:00 자동 갱신",
    )

    if df.empty:
        return html.Div([banner, html.P("데이터 없음", style={"color":colors["muted"]})])

    avg_all = int(df["평균거래가"].mean())
    top_gu  = df.loc[df["평균거래가"].idxmax(), "지역구"]
    total_d = int(df["거래건수"].sum())

    bar_df = df.sort_values("평균거래가", ascending=True)
    fig_bar = go.Figure(go.Bar(
        x=bar_df["평균거래가"], y=bar_df["지역구"], orientation="h",
        marker=dict(color=bar_df["평균거래가"],
                    colorscale=[[0,colors["accent2"]],[1,colors["accent"]]]),
        text=bar_df["평균거래가"].apply(fmt_won),
        textposition="outside", textfont=dict(color=colors["text"], size=14),
    ))
    fig_bar.update_layout(**PT, title="구·군별 평균 거래가 (최근 3개월)", height=560,
                          xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

    fig_t = go.Figure()
    months = []
    if not tdf.empty:
        m = tdf.groupby("월")["거래금액"].mean().reset_index()
        # "2026-05" 같은 문자열 정렬은 지금 데이터에선 우연히 시간순과 같지만
        # 연도가 넘어가면 깨진다. Period로 바꿔 정렬한 뒤 문자열로 되돌린다.
        m = m.assign(_p=pd.PeriodIndex(m["월"], freq="M")).sort_values("_p")
        months = m["월"].tolist()
        # hovertemplate은 파이썬 함수를 직접 호출할 수 없어, fmt_won으로 미리
        # 만들어 둔 표시용 문자열을 customdata로 실어 보낸다.
        m = m.assign(거래금액_표시=m["거래금액"].apply(fmt_won))
        fig_t.add_trace(go.Scatter(
            x=m["월"], y=m["거래금액"], mode="lines+markers",
            line=dict(color=colors["accent"], width=2),
            marker=dict(size=12, color=colors["accent"]),
            fill="tozeroy", fillcolor=_hex_to_rgba(colors["accent"], 0.08),
            customdata=m["거래금액_표시"],
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
        ))
    fig_t.update_layout(
        **PT, title=f"{region_label} 월별 평균 거래가 추이", height=260,
        # type="category"가 핵심이다. 축 타입을 자동에 맡기면 Plotly가 "2026-07"을
        # 날짜로 파싱해 날짜축으로 바꾸고, 그러면 눈금을 스스로 고르기 때문에
        # 마지막 달(예: 7월)의 라벨이 잘려 데이터는 그려졌는데 없는 것처럼 보인다.
        # 카테고리축이면 집계된 달마다 눈금 하나가 categoryarray 순서로 찍힌다.
        xaxis=dict(gridcolor=colors["border"], type="category",
                   categoryorder="array", categoryarray=months),
        yaxis=dict(gridcolor=colors["border"]))

    return html.Div([
        banner,
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi(colors, f"{region_label} 평균", fmt_won(avg_all), colors["accent"]),
                            kpi(colors, "최고가 지역구", top_gu),
                            kpi(colors, "총 거래건수", f"{total_d:,}건", colors["accent2"], "최근 3개월")]),
        dcc.Graph(figure=fig_t),
        dcc.Graph(figure=fig_bar),
        # LAWD 48121이 창원시 전체가 아니라 의창구만 가리켜 "창원시 의창구"로
        # 저장돼 있다(config.py 참고) — 값 자체는 안 건드리고 각주로만 안내.
        html.P("※ 창원시는 API 제약으로 의창구 지역만 반영됨",
               style={"color":colors["muted"],"fontSize":"14px","margin":"8px 0 0"})
        if region_label == "경남" else None,
    ])


def build_tab_permit(colors, df):
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)
    PT = get_plotly_template(colors)

    if df.empty:
        summary_block = html.P("데이터 없음", style={"color":colors["muted"]})
    else:
        total_u = int(df["세대수"].sum())
        top_c   = df.groupby("시공사")["세대수"].sum().idxmax()
        sm = df.groupby("지역구")["세대수"].sum().reset_index().sort_values("세대수", ascending=True)

        fig = go.Figure(go.Bar(
            x=sm["세대수"], y=sm["지역구"], orientation="h",
            marker_color=colors["accent"],
            text=sm["세대수"].apply(lambda x: f"{x:,}세대"),
            textposition="outside", textfont=dict(color=colors["text"], size=14),
        ))
        fig.update_layout(**PT, title="구·군별 신규 착공·인허가 세대수", height=560,
                          xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

        tdf = df.sort_values("인허가일", ascending=False).head(20).copy()
        tdf["인허가일"] = tdf["인허가일"].astype(str)

        summary_block = html.Div([
            html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                     children=[kpi(colors, "총 인허가 세대수", f"{total_u:,}세대", colors["accent"]),
                                kpi(colors, "최다 시공사", top_c),
                                kpi(colors, "모니터링 건수", f"{len(df)}건", colors["muted"])]),
            dcc.Graph(figure=fig),
            html.Div(style={**CARD,"marginTop":"24px"}, children=[
                html.P("최근 인허가 내역 (상위 20건)",
                       style={"color":colors["muted"],"fontSize":"17px","margin":"0 0 12px"}),
                dash_table.DataTable(data=tdf.to_dict("records"),
                    columns=[{"name":c,"id":c} for c in tdf.columns], **TABLE_STYLE),
            ]),
        ])

    return html.Div([
        data_banner(
            colors,
            f"인허가 {len(df):,}건  ·  {fmt_period(df['인허가일'] if not df.empty else None)}",
            "출처: 청약홈 분양정보 API (배치 수집) + 건축HUB 주택인허가 API (실시간 검색)",
            "매주 월요일 07:00 자동 갱신",
        ),
        summary_block,

        # 건축HUB 단지 검색 — 국토교통부 건축HUB 주택인허가정보 서비스는
        # 이제 이 실시간 검색 조회 방식만으로 사용함 (배치 수집은 폐지).
        html.Div(style={**CARD,"marginTop":"24px"}, children=[
            html.P("건축HUB 주택인허가 검색",
                   style={"color":colors["text"],"fontSize":"21px","fontWeight":"700",
                          "margin":"0 0 4px"}),
            html.P("구·군과 동을 선택하면 해당 지역의 주택인허가 정보를 실시간 조회합니다.",
                   style={"color":colors["muted"],"fontSize":"17px","margin":"0 0 16px"}),
            html.Div(style={"display":"flex","gap":"12px","flexWrap":"wrap","alignItems":"center"},
                     children=[
                dcc.Dropdown(
                    id="permit-search-gu",
                    # 부산·울산 사이에 이름이 겹치는 구(중구·남구·동구·북구)가 있어
                    # region을 라벨에 붙여 구분한다. DISTRICT_TO_REGION은 이름 기준이라
                    # 겹치는 이름은 마지막에 덮어쓴 부산이 이겨버려 여기엔 못 쓴다 —
                    # sigunguCd 자체는 겹치지 않으므로 코드 소속으로 직접 판별한다.
                    options=[
                        {
                            "label": f"{'부산' if k in BUSAN_DISTRICT_CODES else '울산' if k in ULSAN_DISTRICT_CODES else '경남'} {v}",
                            "value": k,
                        }
                        for k, v in ALL_DISTRICT_CODES.items()
                    ],
                    placeholder="구·군 선택",
                    style={"width":"160px","fontSize":"18px", "color": "#000000"},
                    clearable=False,
                ),
                dcc.Dropdown(
                    id="permit-search-dong",
                    options=[],
                    placeholder="동 선택",
                    style={"width":"180px","fontSize":"18px", "color": "#000000"},
                    clearable=False,
                ),
                html.Button("검색", id="permit-search-btn", n_clicks=0,
                    style={
                        "backgroundColor": colors["accent"],
                        "color": "#ffffff",
                        "border": "none",
                        "borderRadius": "8px",
                        "padding": "8px 20px",
                        "fontSize": "18px",
                        "fontWeight": "600",
                        "cursor": "pointer",
                    }),
            ]),
            dcc.Loading(
                id="permit-search-loading",
                type="default",
                children=html.Div(id="permit-search-result", style={"marginTop":"20px"}),
            ),
        ]),
    ])


# ---------------------------------------------------------------------------
# 셸(헤더/본문/푸터) — 테마가 바뀔 때만 재생성됨
# ---------------------------------------------------------------------------

def build_region_select_bar(colors):
    """
    페이지 최상단(지도 섹션보다 위) 지역 선택 바. region-select/district-select/
    검색 버튼과 selected-region-store를 담는다. 미분양·거래가·인허가 3개 섹션은
    이 store 변경에 반응해 다시 그려진다 (render_unsold_section 등 참고).
    지도 섹션은 값이 바뀌어도 재요청하지 않고 카메라만 이동한다 (selected-region-store를
    Input으로 받아 iframe에 postMessage하는 clientside_callback, 콜백 섹션 참고).
    """
    CARD = get_card_style(colors)
    return html.Div([
        html.Div(style={**CARD, "display":"flex", "gap":"12px", "alignItems":"center",
                        "marginBottom":"24px"}, children=[
            dcc.Dropdown(
                id="region-select",
                options=[
                    {"label": "부산광역시", "value": "부산"},
                    {"label": "울산광역시", "value": "울산"},
                    {"label": "경상남도",   "value": "경남"},
                ],
                value="부산", clearable=False,
                style={"width":"200px"},
            ),
            dcc.Dropdown(
                id="district-select",
                options=[], value=None,
                placeholder="구·군 선택 (선택 안 하면 전체)",
                style={"width":"200px"},
            ),
            html.Button("검색", id="region-search-btn", n_clicks=0,
                style={
                    "backgroundColor": colors["accent"],
                    "color": "#ffffff",
                    "border": "none",
                    "borderRadius": "8px",
                    "padding": "8px 20px",
                    "fontSize": "18px",
                    "fontWeight": "600",
                    "cursor": "pointer",
                }),
        ]),
        dcc.Store(id="selected-region-store", data={"region": "부산", "district": None}),
    ])


def build_shell():
    """
    헤더 + 서브헤더 + 지역 선택 바 + 4개 섹션(지도/미분양/거래가/인허가)을 세로로
    이어 붙인 단일 페이지 + 푸터를 반환. 앱 시작 시 한 번만 호출되어 page-content의
    초기값으로 쓰인다.

    미분양·거래가·인허가 섹션은 여기서 내용을 직접 채우지 않는다 — id만 가진 빈
    컨테이너를 두고, render_unsold_section/render_price_section/render_permit_section
    콜백이 selected-region-store를 구독해 채운다 (페이지 최초 로드 시에도 Input이
    Store의 초기값으로 한 번 발동하므로 정적 렌더링과 동일하게 즉시 채워진다).
    """
    colors = LIGHT_COLORS

    return html.Div(
        style={"backgroundColor":colors["bg"],"minHeight":"100vh",
               "fontFamily":"Malgun Gothic, Apple SD Gothic Neo, sans-serif",
               "color":colors["text"]},
        children=[
            # 헤더
            html.Div(style={"backgroundColor":colors["surface"],
                            "borderBottom":f"1px solid {colors['border']}",
                            "padding":"0 32px",
                            "display":"flex","alignItems":"center",
                            "justifyContent":"space-between","height":"64px",
                            "boxShadow":"0 1px 4px rgba(0,0,0,0.06)"}, children=[
                html.Div(style={"display":"flex","alignItems":"center","gap":"12px"}, children=[
                    html.Span("●", style={"color":colors["accent"],"fontSize":"14px"}),
                    html.Span("부산·울산·경남 분양·거래시장 통합 모니터",
                              style={"fontWeight":"800","fontSize":"25px",
                                     "letterSpacing":"-0.5px","color":colors["text"]}),
                ]),
                html.Div(style={"display":"flex","alignItems":"center","gap":"20px"}, children=[
                    html.Span(f"갱신: {updated_at}",
                              style={"color":colors["muted"],"fontSize":"17px"}),
                ]),
            ]),

            # 서브헤더
            html.Div(style={"padding":"10px 32px","backgroundColor":colors["surface2"],
                            "borderBottom":f"1px solid {colors['border']}"}, children=[
                html.P("미분양이 쌓이는 지역의 시행사를 먼저 포착해 시공사 교체·분양 전략 변경 타이밍에 선제적으로 영업합니다.",
                       style={"color":colors["muted"],"fontSize":"13px","margin":"0"}),
            ]),

            # 본문 — 지역 선택 바 + 지도 / 미분양 / 거래가 / 인허가 4개 섹션을
            # 세로로 이어 붙인 단일 페이지. 지도 섹션은 제목 없이 바로 시작하고,
            # 나머지는 구분선 + 섹션 제목으로 시작한다.
            html.Div(style={"padding":"24px 32px"}, children=[
                build_region_select_bar(colors),

                build_tab_map(colors),

                html.Div(id="unsold-section", style=SECTION_WRAP_STYLE),
                html.Div(id="price-section",  style=SECTION_WRAP_STYLE),
                html.Div(id="permit-section", style=SECTION_WRAP_STYLE),
            ]),

            # 푸터
            html.Div(style={"padding":"14px 32px","borderTop":f"1px solid {colors['border']}",
                            "marginTop":"24px","backgroundColor":colors["surface"]}, children=[
                html.P("매주 월요일 오전 7시 자동 갱신  ·  국토부 실거래가 API  ·  청약홈 API  ·  부산광역시 미분양현황 API  ·  경상남도 미분양현황 API  ·  건축HUB 주택인허가 API",
                       style={"color":colors["muted"],"fontSize":"15px","margin":"0"}),
            ]),
        ]
    )

# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
app = Dash(__name__, title="부산·울산·경남 분양·거래시장 통합 모니터",
           suppress_callback_exceptions=True)


# vworld_map.html은 assets 정적 서빙(/assets/...)이 아니라 이 라우트로 내보낸다.
# 파일 안의 __VWORLD_API_KEY__ 플레이스홀더를 여기서 치환하기 위함이다.
# (iframe은 srcDoc이 아니라 src=로 이 URL을 가리켜야 한다. srcDoc이면 지도 쪽
#  window.location.host가 비어 V-World domain 파라미터가 깨진다.)
@app.server.route("/vworld-map.html")
def serve_vworld_map():
    html_path = Path(__file__).parent / "assets" / "vworld_map.html"
    content = html_path.read_text(encoding="utf-8")
    content = content.replace("__VWORLD_API_KEY__", VWORLD_API_KEY or "")
    return content, 200, {"Content-Type": "text/html; charset=utf-8"}


# ---------------------------------------------------------------------------
# 구·군/읍면동 지오메트리 캐시
#
# 행정구역 경계는 거의 안 바뀌는 데이터인데, vworld_map.html이 예전엔 매
# 페이지 로드(iframe 재로드 포함)마다 V-World 데이터 API를 브라우저에서 직접
# 호출했다. 서버가 최초 1회(또는 캐시 만료 시)만 받아 파일로 저장해 두고,
# 이후 요청은 그 파일을 그대로 돌려준다 — V-World 호출 횟수가 줄고 로딩도
# 즉시 끝난다. 응답 형식은 V-World 원본 featureCollection 래퍼 그대로라
# vworld_map.html의 unwrapFeatureCollection()이 예전과 똑같이 파싱한다.
# ---------------------------------------------------------------------------
GEOMETRY_CACHE_DIR = Path(__file__).parent / "assets" / "geometry_cache"
GEOMETRY_CACHE_DIR.mkdir(exist_ok=True)
CACHE_MAX_AGE_DAYS = 90     # 행정구역 개편(드물지만 읍면동 통폐합 등)에 대비한 만료 정책
GEOMETRY_PAGE_SIZE = 1000   # V-World 데이터 API 1회 최대치 — vworld_map.html의 예전 PAGE_SIZE와 동일
GEOMETRY_MAX_PAGES = 3
GEOMETRY_BBOX = "127.6,34.6,129.5,35.7"     # 부산·울산·경남 — vworld_map.html의 예전 REGION_BBOX와 동일
GEOMETRY_LAYERS = {"sigg": "LT_C_ADSIGG_INFO", "emd": "LT_C_ADEMD_INFO"}


def fetch_geometry_from_vworld(data_layer: str) -> dict:
    """
    V-World 데이터 API를 페이지네이션하며 모두 받아 하나의 featureCollection으로
    합친다 (예전에 vworld_map.html의 fetchAdmin/requestPage가 브라우저에서 하던
    일을 그대로 서버로 옮긴 것 — 꽉 찬 페이지가 오면 다음 페이지를 더 받는다).
    """
    all_features = []
    for page in range(1, GEOMETRY_MAX_PAGES + 1):
        params = {
            "service": "data", "request": "GetFeature", "version": "2.0",
            "key": VWORLD_API_KEY, "domain": VWORLD_DOMAIN,
            "data": data_layer, "format": "json", "errorformat": "json",
            "size": GEOMETRY_PAGE_SIZE, "page": page,
            "geometry": "true", "attribute": "true", "crs": "EPSG:4326",
            "geomFilter": f"BOX({GEOMETRY_BBOX})",
        }
        resp = requests.get("https://api.vworld.kr/req/data", params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        res = payload.get("response") or {}
        if res.get("status") and res["status"] != "OK":
            error = res.get("error") or {}
            raise RuntimeError(
                f"V-World 데이터 API 오류: {error.get('text') or error.get('code') or res['status']}"
            )
        page_features = ((res.get("result") or {}).get("featureCollection") or {}).get("features") or []
        all_features.extend(page_features)
        if len(page_features) < GEOMETRY_PAGE_SIZE:
            break   # 꽉 찬 페이지가 아니면 다음 페이지가 없다

    return {
        "response": {
            "status": "OK",
            "result": {"featureCollection": {"type": "FeatureCollection", "features": all_features}},
        }
    }


@app.server.route("/geometry/<data_type>")
def serve_geometry_cache(data_type):
    """
    data_type: 'sigg'(구·군) 또는 'emd'(읍면동).
    캐시 파일이 있고 CACHE_MAX_AGE_DAYS 이내면 그대로 반환한다. 없거나 만료됐으면
    V-World에서 새로 받아와 캐시한 뒤 반환한다.
    """
    data_layer = GEOMETRY_LAYERS.get(data_type)
    if not data_layer:
        return json.dumps({"error": f"unknown data_type: {data_type}"}), 404, {"Content-Type": "application/json"}

    cache_file = GEOMETRY_CACHE_DIR / f"{data_type}.json"
    if cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            return cache_file.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}

    try:
        payload = fetch_geometry_from_vworld(data_layer)
    except Exception as e:
        if cache_file.exists():
            # 갱신에 실패해도(예: V-World 503·한도초과) 만료된 캐시가 아예 없는
            # 것보다는 낫다 — 행정구역 경계는 거의 안 바뀌므로 낡은 캐시로도 지도는
            # 정상 동작한다.
            logger.warning("geometry cache 갱신 실패(%s) — 만료된 캐시로 대체: %s", data_type, e)
            return cache_file.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
        logger.warning("geometry cache 생성 실패(%s), 캐시 없음: %s", data_type, e)
        return json.dumps({"error": str(e)}), 502, {"Content-Type": "application/json"}

    body = json.dumps(payload, ensure_ascii=False)
    cache_file.write_text(body, encoding="utf-8")
    return body, 200, {"Content-Type": "application/json"}


app.layout = html.Div([
    html.Div(id="page-content", children=build_shell()),
])

# ---------------------------------------------------------------------------
# 콜백
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 지역 선택 바 — region-select/district-select/검색 버튼 → selected-region-store
# ---------------------------------------------------------------------------

@app.callback(
    Output("district-select", "options"),
    Output("district-select", "value"),
    Input("region-select", "value"),
)
def update_district_options(region):
    mapping = {
        "부산": BUSAN_DISTRICT_CODES,
        "울산": ULSAN_DISTRICT_CODES,
        "경남": GYEONGNAM_DISTRICT_CODES,
    }
    codes = mapping.get(region, {})
    # LAWD 48121은 창원시 전체가 아니라 의창구만 가리켜 config.py에 "창원시
    # 의창구"로 정확히 등록돼 있다(scripts/migrate_changwon_district.py 참고) —
    # value는 필터링에 그대로 쓰이므로 안 건드리고 label만 안내 문구를 붙인다.
    return [
        {"label": "창원시 (의창구만 수집됨)" if v == "창원시 의창구" else v, "value": v}
        for v in codes.values()
    ], None


@app.callback(
    Output("selected-region-store", "data"),
    Input("region-search-btn", "n_clicks"),
    State("region-select", "value"),
    State("district-select", "value"),
    prevent_initial_call=True,
)
def update_selected_region(n_clicks, region, district):
    return {"region": region, "district": district}


# selected-region-store가 바뀔 때마다 지도 iframe에 postMessage로 이동을 지시한다.
# 이 콜백은 자기 자신의 Output이 곧 자신의 Input이다(둘 다 selected-region-store.data) —
# allow_duplicate=True로 update_selected_region과의 Output 소유권 충돌을 피하고,
# 항상 no_update를 반환해 store 값 자체는 절대 바꾸지 않으므로 순환 갱신은 일어나지
# 않는다. postMessage는 store에 되돌려 쓸 결과가 없는 순수 부수효과인데, Dash는
# clientside_callback에도 Output이 반드시 있어야 하므로 이 "자기참조 + no_update"
# 패턴으로 우회한다.
clientside_callback(
    """
    function(sel) {
        var iframe = document.getElementById('vworld-iframe');
        if (iframe && iframe.contentWindow && sel) {
            iframe.contentWindow.postMessage(
                { type: 'move_to_region', region: sel.region, district: sel.district }, '*');
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("selected-region-store", "data", allow_duplicate=True),
    Input("selected-region-store", "data"),
    prevent_initial_call=True,
)


def _section_children(title, content):
    return [html.H2(title, style=SECTION_TITLE_STYLE), content]


@app.callback(Output("map-kpi-row", "children"), Input("selected-region-store", "data"))
def render_map_kpi_section(sel):
    udf = _filter_by_selection(unsold_df, sel)
    pdf = _filter_by_selection(price_df, sel)
    return build_map_kpi_row(LIGHT_COLORS, udf, pdf)


@app.callback(Output("unsold-section", "children"), Input("selected-region-store", "data"))
def render_unsold_section(sel):
    df = _filter_by_selection(unsold_df, sel)
    return _section_children("🔔 미분양 알림", build_tab_unsold(LIGHT_COLORS, df))


@app.callback(Output("price-section", "children"), Input("selected-region-store", "data"))
def render_price_section(sel):
    df  = _filter_by_selection(price_df, sel)
    tdf = _filter_by_selection(trend_df, sel)
    return _section_children("📊 거래가 분석",
                              build_tab_price(LIGHT_COLORS, df, tdf, region_label=sel["region"]))


@app.callback(Output("permit-section", "children"), Input("selected-region-store", "data"))
def render_permit_section(sel):
    df = _filter_by_selection(permit_df, sel)
    return _section_children("🏗 착공·허가", build_tab_permit(LIGHT_COLORS, df))


# 지도(iframe) → Dash 브리지의 나머지 절반.
# gu-click-interval이 500ms마다 깨워 주면 window.__lastGuClick을 읽어
# 값이 바뀐 경우에만 clicked-gu-store에 쓴다.
# no_update로 걸러 주지 않으면 0.5초마다 store가 갱신돼 map_side_panel이
# 계속 다시 그려진다.
clientside_callback(
    """
    function(n_intervals, current) {
        var latest = window.__lastGuClick;
        if (!latest || latest === current) {
            return window.dash_clientside.no_update;
        }
        return latest;
    }
    """,
    Output("clicked-gu-store", "data"),
    Input("gu-click-interval", "n_intervals"),
    State("clicked-gu-store", "data"),
    prevent_initial_call=True,
)


# Dash → 지도(iframe) 브리지의 나머지 절반.
# unsold-inject-interval이 깨울 때마다 unsold-data-store·price-data-store
# 양쪽 내용과 현재 map-color-mode 값을 전부 iframe으로 postMessage한다.
# iframe 쪽 리스너는
#   (1) 레이어가 이미 있으면 refreshColors()로 다시 칠하고
#   (2) 아직 없으면 전역 unsoldData/priceData/colorMode만 갱신해 두었다가
#       buildGuLayer가 그 값으로 칠한다
# 어느 쪽이든 한 번 도착하기만 하면 되므로, 도착 여부를 확신할 수 있을 때까지
# 재전송한다. same-origin(/vworld-map.html)이라 iframe 전역 layerList를 직접
# 읽어 레이어 생성 여부로 판정한다.
#
# map-color-mode 기본값이 "price"로 바뀌면서, iframe의 JS 쪽 colorMode
# 하드코딩 기본값("unsold")과 어긋나는 문제가 생겼다 — 별도 price-inject-interval을
# 새로 만드는 대신, 이미 있는 이 interval에 price-data-store·map-color-mode를
# State로 얹어 하나로 처리한다(별도 interval 두 개가 서로 다른 초기 color_mode를
# 주장하며 경합할 여지를 원천적으로 없앤다 — State는 매 tick마다 그 시점의
# 최신 값을 읽으므로, 이 재시도 구간(최대 20초) 동안 사용자가 직접 토글해도
# 다음 tick이 그 값을 그대로 따라간다).
clientside_callback(
    """
    function(n_intervals, unsoldData, priceData, mode) {
        var iframe = document.getElementById('vworld-iframe');
        if (!iframe || !iframe.contentWindow) {
            return window.dash_clientside.no_update;
        }
        iframe.contentWindow.postMessage(
            { type: 'unsold_data', data: unsoldData || {} }, '*');
        iframe.contentWindow.postMessage(
            { type: 'trade_price_data', data: priceData || {} }, '*');
        iframe.contentWindow.postMessage({ type: 'color_mode', mode: mode }, '*');
        try {
            var layers = iframe.contentWindow.layerList;
            if (layers && layers.length > 0) {
                return true;   // 레이어가 이 메시지를 받았다 — Interval 정지
            }
        } catch (e) {
            // cross-origin으로 바뀌면 판정이 불가능하다. 그때는 max_intervals까지
            // 계속 쏘는 편이 안전하다 (postMessage 자체는 여전히 통한다).
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("unsold-inject-interval", "disabled"),
    Input("unsold-inject-interval", "n_intervals"),
    State("unsold-data-store", "data"),
    State("price-data-store", "data"),
    State("map-color-mode", "value"),
    prevent_initial_call=True,
)


# map-color-mode(RadioItems) 변경 → iframe에 색상 모드 전환을 지시.
# move_to_region과 같은 1회성 이벤트라 unsold-inject-interval 같은 재전송
# 루프는 필요 없다.
#
# unsold-inject-interval은 페이지 로드 후 최대 20초 안에 iframe의 layerList
# 존재를 확인하면 스스로 멈추고, 그 이후로는 unsold_data가 다시 전송되지
# 않는다 — 즉 unsoldData가 세션 내내 최초 1회 주입값 그대로라는 암묵적
# 전제에 의존한다. 처음엔 "price" 방향만 매번 데이터를 다시 보내고 "unsold"
# 방향은 color_mode 메시지만 보냈는데, 이 비대칭이 원인 특정이 어려운
# 회귀(반복 토글 후 미분양 색상이 안 뜨는 문제)의 여지를 남겼다 — 그래서
# 어느 방향으로 전환하든 항상 그 모드에 맞는 데이터를 함께 재전송해
# "최초 1회 주입 이후 상태 불변"이라는 전제 자체를 없앤다.
clientside_callback(
    """
    function(mode, priceData, unsoldData) {
        var iframe = document.getElementById('vworld-iframe');
        if (iframe && iframe.contentWindow) {
            if (mode === 'price') {
                iframe.contentWindow.postMessage(
                    { type: 'trade_price_data', data: priceData || {} }, '*');
            } else {
                iframe.contentWindow.postMessage(
                    { type: 'unsold_data', data: unsoldData || {} }, '*');
            }
            iframe.contentWindow.postMessage({ type: 'color_mode', mode: mode }, '*');
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("price-data-store", "data", allow_duplicate=True),
    Input("map-color-mode", "value"),
    State("price-data-store", "data"),
    State("unsold-data-store", "data"),
    prevent_initial_call=True,
)


def parse_map_click(data):
    """
    clicked-gu-store 값 → (구, 동, region).

    지도는 이제 '{"gu":"중구","dong":"보수동","region":"부산"}' JSON 문자열을
    보낸다. region이 없는(구·동만 보내던) 예전 형식과 구 이름 문자열만 오던 더
    예전 형식도 그대로 받아 준다 — 브라우저에 남아 있던 옛 iframe이 캐시에서
    뜨면 그 형식으로 오고, 그때 패널이 죽으면 안 된다. 두 예전 형식 모두 region
    정보가 없으므로 "부산"으로 간주한다 (그 시절 iframe은 부산만 다뤘다).

    다만 파싱에 실패한 값을 구 이름으로 흘려보내지는 않는다. 예전에 이 함수가
    없던 시절, store에 들어온 JSON 문자열이 헤더 H3에 그대로 렌더돼
    `{"gu":"수영구","dong":"광안4동"}`가 화면에 뜬 적이 있다. 알 수 없는 형식은
    (None, None, None)으로 떨어뜨려 안내 문구를 띄우는 편이 낫다.
    """
    if not data:
        return None, None, None
    if isinstance(data, dict):
        return _as_district(data.get("gu")), data.get("dong"), data.get("region", "부산")
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError):
        return _as_district(data), None, "부산"    # 예전 형식: 구 이름 문자열
    if isinstance(parsed, dict):
        return _as_district(parsed.get("gu")), parsed.get("dong"), parsed.get("region", "부산")
    return _as_district(parsed), None, "부산"


def _as_district(value):
    """구·군 이름으로 확인된 값만 통과시킨다 (config 매핑 기준, 부산·울산·경남 전체)."""
    if isinstance(value, str) and value.strip() in ALL_DISTRICT_NAMES:
        return value.strip()
    return None


@app.callback(
    Output("map-side-panel", "children"),
    Input("clicked-gu-store", "data"),
    prevent_initial_call=True,
)
def map_side_panel(click_data):
    colors = LIGHT_COLORS
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)

    gu_name, dong_name, region_name = parse_map_click(click_data)

    if not gu_name:
        return html.P("← 지도에서 구·군을 클릭하세요",
                      style={"color":colors["muted"],"fontSize":"18px",
                             "marginTop":"60px","textAlign":"center"})

    u_row   = unsold_df[(unsold_df["지역구"] == gu_name) & (unsold_df["region"] == region_name)]
    p_row   = price_df[(price_df["지역구"] == gu_name) & (price_df["region"] == region_name)]
    # 인허가는 구 단위 유지 — building_permits에 동 정보가 없다.
    # permit_df에 실제 region 컬럼이 있으므로(건축HUB·청약홈 모두 부산·울산·경남
    # 3개 지역을 수집) 그 값을 그대로 쓴다 — 부산·울산 동명 구(중구·남구 등)를
    # 클릭했을 때 다른 지역 데이터가 잘못 붙는 걸 막는다.
    # building_permits.district는 창원시 5개 하위구를 "창원시" 하나로 통일해
    # 저장하지만(cheongyak.py/building_permit.py 참고), 드롭다운·Trade는 LAWD
    # 48121 표기 그대로 "창원시 의창구"를 쓴다(config.py) — 그 값이 클릭됐을
    # 때만 permit_df 매칭에 "창원시"도 포함시킨다. 다른 구·군은 기존과 동일.
    permit_district_match = (
        permit_df["지역구"].isin(("창원시 의창구", "창원시"))
        if gu_name == "창원시 의창구"
        else permit_df["지역구"] == gu_name
    )
    pm_rows = permit_df[
        permit_district_match &
        (permit_df["region"] == region_name)
    ].sort_values("인허가일", ascending=False).head(5).copy()
    pm_rows["인허가일"] = pm_rows["인허가일"].astype(str)

    unsold_count = int(u_row["미분양세대수"].values[0]) if not u_row.empty else "-"
    change_rate  = u_row["증감률"].values[0] if not u_row.empty else None
    gu_avg_price = int(p_row["평균거래가"].values[0]) if not p_row.empty else None
    spike        = (change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT

    # 실거래가만 동 단위로 내려간다. 동 거래가 하나도 없으면 구 평균으로 돌아가고,
    # 그 사실을 반드시 화면에 적는다 — 안 적으면 구 평균이 동 시세로 읽힌다.
    dong_trades = load_dong_trades(gu_name, dong_name) if dong_name else pd.DataFrame()
    if not dong_trades.empty:
        price_value = fmt_won(dong_trades['거래금액'].mean())
        price_sub   = f"{dong_name} 기준 · {len(dong_trades)}건"
        price_note  = None
    else:
        price_value = fmt_won(gu_avg_price) if gu_avg_price else "-"
        price_sub   = f"{gu_name} 전체 평균"
        price_note  = (f"※ {dong_name} 실거래 없음 — 구 평균으로 대체"
                       if dong_name else None)

    def note(text):
        return html.P(text, style={"color":colors["muted"],"fontSize":"14px",
                                   "margin":"6px 0 0","lineHeight":"1.4"})

    def stat_row(label, value, color=None):
        return html.Div(
            style={"display":"flex","justifyContent":"space-between",
                   "padding":"8px 0","borderBottom":f"1px solid {colors['border']}"},
            children=[
                html.Span(label, style={"color":colors["muted"],"fontSize":"17px"}),
                html.Span(str(value), style={"color":color or colors["text"],
                                              "fontSize":"18px","fontWeight":"600"}),
            ])

    return html.Div([
        html.Div(style={"display":"flex","alignItems":"center",
                        "justifyContent":"space-between","marginBottom":"20px"}, children=[
            html.H3(" ".join(p for p in (gu_name, dong_name) if p),
                    style={"margin":"0","fontSize":"14px",
                           "fontWeight":"700","color":colors["text"]}),
            html.Span("⚠ 급증" if spike else "✓ 정상",
                style={"color":colors["danger"] if spike else colors["ok"],"fontSize":"15px",
                       "fontWeight":"700",
                       "backgroundColor":_hex_to_rgba(
                           colors["danger"] if spike else colors["ok"], 0.08),
                       "padding":"3px 10px","borderRadius":"12px"}),
        ]),
        # 실거래가(왼쪽) · 미분양 현황(오른쪽) 2컬럼. 컬럼 하나당 제목 P + CARD를
        # 통째로 묶어 flex 아이템으로 둔다 — minWidth를 둬서 사이드패널처럼 좁은
        # 폭에서도 두 컬럼이 과도하게 찌그러지지 않게 한다.
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"14px","flexWrap":"wrap"}, children=[
            html.Div(style={"flex":"1","minWidth":"220px"}, children=[
                html.P("실거래가", style={"color":colors["muted"],"fontSize":"15px",
                                          "letterSpacing":"0.1em","margin":"0 0 4px",
                                          "textTransform":"uppercase"}),
                html.Div(style={**CARD,"padding":"12px 16px"}, children=[
                    stat_row("최근 3개월 평균", price_value, colors["accent"]),
                    stat_row("집계 범위", price_sub),
                    *([note(price_note)] if price_note else []),
                ]),
            ]),
            html.Div(style={"flex":"1","minWidth":"220px"}, children=[
                html.P("미분양 현황 (※ 구 전체 기준)", style={"color":colors["muted"],"fontSize":"15px",
                                            "letterSpacing":"0.1em","margin":"0 0 4px",
                                            "textTransform":"uppercase"}),
                html.Div(style={**CARD,"padding":"12px 16px"}, children=[
                    stat_row("미분양 세대수", f"{unsold_count}세대"),
                    stat_row("전월 대비",
                             f"{change_rate:+.1f}%" if change_rate is not None else "-",
                             colors["danger"] if spike else colors["ok"]),
                    # 미분양은 구 단위로만 집계돼 들어온다. 동을 눌러도 이 숫자는
                    # 구 전체 값이므로 그렇게 밝혀 둔다.
                ]),
            ]),
        ]),
        html.P("최근 인허가", style={"color":colors["muted"],"fontSize":"15px",
                                     "letterSpacing":"0.1em","margin":"0 0 8px",
                                     "textTransform":"uppercase"}),
        html.Div(style={**CARD,"padding":"0"}, children=[
            dash_table.DataTable(
                data=pm_rows[["인허가일","세대수","시공사"]].to_dict("records"),
                columns=[{"name":c,"id":c} for c in ["인허가일","세대수","시공사"]],
                **TABLE_STYLE,
            ) if not pm_rows.empty else html.P("인허가 내역 없음",
                style={"color":colors["muted"],"padding":"12px","fontSize":"17px"}),
        ]),
    ])


# ---------------------------------------------------------------------------
# 건축HUB 검색 콜백
# 국토교통부 건축HUB 주택인허가정보 서비스는 이제 이 실시간 검색으로만 사용.
# (구·군 → 동 선택 후 조회, 배치/자동 수집 없음)
# ---------------------------------------------------------------------------

@app.callback(
    Output("permit-search-dong", "options"),
    Input("permit-search-gu", "value"),
    prevent_initial_call=True,
)
def update_dong_options(sgg_cd):
    if not sgg_cd:
        return []
    if sgg_cd.startswith("26"):
        dongs = BUSAN_DONG_CODES.get(sgg_cd, {})
    elif sgg_cd.startswith("31"):
        dongs = ULSAN_DONG_CODES.get(sgg_cd, {})
    elif sgg_cd.startswith("48"):
        dongs = GYEONGNAM_DONG_CODES.get(sgg_cd, {})
    else:
        dongs = {}
    return [{"label": v, "value": k} for k, v in dongs.items()]


@app.callback(
    Output("permit-search-result", "children"),
    Input("permit-search-btn", "n_clicks"),
    State("permit-search-gu", "value"),
    State("permit-search-dong", "value"),
    prevent_initial_call=True,
)
def search_building_permit(n_clicks, sgg_cd, bjdong_cd):
    colors = LIGHT_COLORS
    TABLE_STYLE = get_table_style(colors)

    if not sgg_cd or not bjdong_cd:
        return html.P("구·군과 동을 모두 선택해주세요.",
                      style={"color": colors["warning"], "fontSize": "18px"})

    from src.config import BUILDING_PERMIT_API_KEY
    endpoint = "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo"
    params = {
        "serviceKey": BUILDING_PERMIT_API_KEY,
        "sigunguCd":  sgg_cd,
        "bjdongCd":   bjdong_cd,
        "numOfRows":  100,
        "pageNo":     1,
    }

    try:
        resp = requests.get(endpoint, params=params, timeout=15)
        resp.raise_for_status()
        root  = ET.fromstring(resp.text)
        items = root.findall(".//item")

        if not items:
            return html.P("해당 지역의 주택인허가 데이터가 없습니다.",
                          style={"color": colors["muted"], "fontSize": "18px"})

        def t(el, tag):
            node = el.find(tag)
            return node.text.strip() if node is not None and node.text else "-"

        rows = []
        for el in items:
            approv = t(el, "apprvDay")
            if len(approv) == 8:
                approv = f"{approv[:4]}-{approv[4:6]}-{approv[6:]}"
            rows.append({
                "단지명":    t(el, "bldNm"),
                "주소":      t(el, "platPlc"),
                "세대수":    t(el, "totHhldCnt"),
                "사업승인일": approv,
                "착공일":    t(el, "stcnsDay") or "-",
            })

        total = root.findtext(".//totalCount") or str(len(rows))
        df = pd.DataFrame(rows)

        return html.Div([
            html.P(f"조회 결과: {total}건",
                   style={"color": colors["muted"], "fontSize": "17px", "margin": "0 0 12px"}),
            dash_table.DataTable(
                data=df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in df.columns],
                **TABLE_STYLE,
                page_size=20,
            ),
        ])

    except requests.exceptions.Timeout:
        return html.P("요청 시간이 초과됐습니다. 다시 시도해주세요.",
                      style={"color": colors["danger"], "fontSize": "18px"})
    except Exception as e:
        return html.P(f"조회 중 오류가 발생했습니다: {str(e)}",
                      style={"color": colors["danger"], "fontSize": "18px"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=9090)