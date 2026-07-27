"""
dashboards/app.py
분양·거래시장 통합 모니터 대시보드

실행:
    python -m dashboards.app
    브라우저에서 http://127.0.0.1:8050 접속
"""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, dash_table

from src.config import UNSOLD_SPIKE_THRESHOLD_PCT
from src.db import (
    get_avg_price_by_district,
    get_unsold_spike_districts,
    get_session,
    BuildingPermit,
    PriceCapZone,
)

app = Dash(__name__, title="분양·거래시장 통합 모니터")


# ---------------------------------------------------------------------------
# 데이터 로드 함수 (콜백 없이 최초 로드 시 1회 — 나중에 dcc.Interval로 자동갱신 추가 가능)
# ---------------------------------------------------------------------------

def load_price_heatmap_df() -> pd.DataFrame:
    end = date.today()
    start = end - timedelta(days=180)
    rows = get_avg_price_by_district(start, end)
    return pd.DataFrame(rows, columns=["district", "avg_price", "deal_count"])


def load_unsold_spike_df() -> pd.DataFrame:
    rows = get_unsold_spike_districts(threshold_pct=UNSOLD_SPIKE_THRESHOLD_PCT)
    return pd.DataFrame(
        [
            {
                "지역구": r.district,
                "기준월": r.base_month,
                "미분양세대수": r.unsold_count,
                "전월대비": f"{r.change_rate:+.1f}%",
            }
            for r in rows
        ]
    )


def load_permit_df() -> pd.DataFrame:
    with get_session() as session:
        rows = session.query(BuildingPermit).all()
        return pd.DataFrame(
            [
                {
                    "지역구": r.district,
                    "인허가일": r.permit_date,
                    "세대수": r.household_count,
                    "시행사": r.developer,
                    "시공사": r.contractor,
                }
                for r in rows
            ]
        )


def load_price_cap_df() -> pd.DataFrame:
    with get_session() as session:
        rows = session.query(PriceCapZone).all()
        return pd.DataFrame(
            [
                {
                    "지역구": r.district,
                    "지정일": r.designated_date,
                    "해제일": r.released_date or "-",
                    "상태": r.status,
                }
                for r in rows
            ]
        )


# ---------------------------------------------------------------------------
# 차트 빌더
# ---------------------------------------------------------------------------

def build_price_heatmap(df: pd.DataFrame):
    if df.empty:
        return px.bar(title="데이터 없음 (더미 데이터를 먼저 삽입하세요)")
    df = df.sort_values("avg_price", ascending=True)
    fig = px.bar(
        df,
        x="avg_price",
        y="district",
        orientation="h",
        title="지역구별 평균 거래가 (최근 6개월, 만원)",
        labels={"avg_price": "평균 거래가(만원)", "district": "지역구"},
        color="avg_price",
        color_continuous_scale="Blues",
    )
    fig.update_layout(height=700)
    return fig


def build_permit_chart(df: pd.DataFrame):
    if df.empty:
        return px.bar(title="데이터 없음")
    summary = df.groupby("지역구")["세대수"].sum().reset_index()
    fig = px.bar(
        summary.sort_values("세대수", ascending=True),
        x="세대수",
        y="지역구",
        orientation="h",
        title="구별 신규 착공·인허가 세대수",
    )
    fig.update_layout(height=700)
    return fig


# ---------------------------------------------------------------------------
# 레이아웃
# ---------------------------------------------------------------------------

price_df = load_price_heatmap_df()
spike_df = load_unsold_spike_df()
permit_df = load_permit_df()
cap_df = load_price_cap_df()

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "margin": "24px"},
    children=[
        html.H1("분양·거래시장 통합 모니터"),
        html.P("시장을 보는 게 목적이 아닙니다. 미분양이 쌓이는 지역을 먼저 포착합니다."),

        html.Hr(),

        # 1. 미분양 급증 알림 (가장 중요한 정보이므로 최상단)
        html.H2(f"🔔 미분양 급증 알림 (전월 대비 {UNSOLD_SPIKE_THRESHOLD_PCT:.0f}%↑)"),
        dash_table.DataTable(
            data=spike_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in spike_df.columns],
            style_table={"marginBottom": "40px"},
            style_cell={"textAlign": "center", "padding": "8px"},
            style_header={"fontWeight": "bold", "backgroundColor": "#fdecea"},
        ) if not spike_df.empty else html.P("현재 급증 지역이 없습니다."),

        html.Hr(),

        # 2. 지역별 평균 거래가 히트맵
        html.H2("📊 지역별 평균 거래가"),
        dcc.Graph(figure=build_price_heatmap(price_df)),

        html.Hr(),

        # 3. 착공·허가 동향
        html.H2("🏗 착공·허가 동향"),
        dcc.Graph(figure=build_permit_chart(permit_df)),

        html.Hr(),

        # 4. 규제 모니터 (분양가상한제)
        html.H2("🚧 분양가상한제 지정·해제 현황"),
        dash_table.DataTable(
            data=cap_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in cap_df.columns],
            style_cell={"textAlign": "center", "padding": "8px"},
            style_header={"fontWeight": "bold", "backgroundColor": "#e8f0fe"},
        ) if not cap_df.empty else html.P("지정된 지역이 없습니다."),

        html.Hr(),
        html.P("매주 월요일 오전 7시 자동 갱신", style={"color": "gray", "fontSize": "12px"}),
    ],
)


if __name__ == "__main__":
    app.run(debug=True)