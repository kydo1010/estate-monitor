"""
dashboards/app.py
부산 분양·거래시장 통합 모니터 (화이트모드 + V-World 지도)

실행: python -m dashboards.app → http://127.0.0.1:8050
"""

import json
from datetime import date, timedelta
from pathlib import Path
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

import requests
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, clientside_callback

from src.config import UNSOLD_SPIKE_THRESHOLD_PCT, VWORLD_API_KEY
from src.db import (
    get_avg_price_by_district, get_session,
    UnsoldHousing, BuildingPermit, Trade,
)

# ---------------------------------------------------------------------------
# 색상 토큰 (화이트모드)
# ---------------------------------------------------------------------------
C = {
    "bg":       "#f5f7fa",
    "surface":  "#ffffff",
    "surface2": "#f0f3f8",
    "border":   "#dde3ed",
    "accent":   "#2563eb",   # 블루 계열
    "accent2":  "#0ea5e9",
    "danger":   "#dc2626",
    "ok":       "#16a34a",
    "warning":  "#d97706",
    "text":     "#1a2234",
    "muted":    "#64748b",
    "chart_bg": "#ffffff",
}

PT = dict(
    paper_bgcolor=C["chart_bg"],
    plot_bgcolor=C["chart_bg"],
    font=dict(color=C["text"], family="Pretendard, Malgun Gothic, sans-serif"),
    margin=dict(l=16, r=16, t=48, b=16),
)

CARD = {
    "background": C["surface"],
    "border": f"1px solid {C['border']}",
    "borderRadius": "12px",
    "padding": "20px 24px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.06)",
}
KPI_CARD = {**CARD, "textAlign": "center", "flex": "1", "minWidth": "140px"}

TABLE_STYLE = {
    "style_table": {"overflowX": "auto"},
    "style_cell": {
        "backgroundColor": C["surface"],
        "color": C["text"],
        "border": f"1px solid {C['border']}",
        "padding": "10px 14px",
        "fontSize": "13px",
        "fontFamily": "Pretendard, Malgun Gothic, sans-serif",
    },
    "style_header": {
        "backgroundColor": C["surface2"],
        "color": C["muted"],
        "fontWeight": "600",
        "border": f"1px solid {C['border']}",
        "fontSize": "12px",
        "letterSpacing": "0.05em",
    },
    "style_data_conditional": [
        {"if": {"row_index": "odd"}, "backgroundColor": C["surface2"]},
    ],
}

def kpi(label, value, color=None, sub=None):
    return html.Div(style=KPI_CARD, children=[
        html.P(label, style={"color": C["muted"], "fontSize": "11px",
                              "letterSpacing": "0.1em", "margin": "0 0 8px",
                              "textTransform": "uppercase"}),
        html.P(str(value), style={"color": color or C["text"], "fontSize": "34px",
                                   "fontWeight": "700", "margin": "0", "lineHeight": "1"}),
        html.P(sub or "", style={"color": C["muted"], "fontSize": "11px", "margin": "6px 0 0"}),
    ])

# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

def load_unsold_df():
    with get_session() as s:
        rows = s.query(UnsoldHousing).order_by(UnsoldHousing.change_rate.desc()).all()
        return pd.DataFrame([{
            "지역구": r.district, "기준월": r.base_month,
            "미분양세대수": r.unsold_count, "전월세대수": r.prev_month_count,
            "증감률": r.change_rate,
            "급증여부": (r.change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT,
        } for r in rows])

def load_price_df():
    end, start = date.today(), date.today() - timedelta(days=90)
    rows = get_avg_price_by_district(start, end)
    return pd.DataFrame(rows, columns=["지역구", "평균거래가", "거래건수"])

def load_permit_df():
    with get_session() as s:
        rows = s.query(BuildingPermit).all()
        return pd.DataFrame([{"지역구": r.district, "인허가일": r.permit_date,
                               "세대수": r.household_count, "시행사": r.developer,
                               "시공사": r.contractor} for r in rows])

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

n_spike    = int(unsold_df["급증여부"].sum()) if not unsold_df.empty else 0
updated_at = date.today().strftime("%Y-%m-%d")

# V-World 지도에 넘길 미분양 데이터 (JSON)
unsold_map_data = (
    unsold_df.set_index("지역구")["미분양세대수"].to_dict()
    if not unsold_df.empty else {}
)

# ---------------------------------------------------------------------------
# 탭별 레이아웃
# ---------------------------------------------------------------------------

def build_tab_map():
    # V-World API 키를 HTML에 주입
    html_path = Path(__file__).parent / "assets" / "vworld_map.html"
    html_content = html_path.read_text(encoding="utf-8")
    html_content = html_content.replace("__VWORLD_API_KEY__", VWORLD_API_KEY or "")

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"16px","flexWrap":"wrap"},
                 children=[
                     kpi("부산 평균 거래가",
                         f"{int(price_df['평균거래가'].mean()):,}만원" if not price_df.empty else "-",
                         C["accent"]),
                     kpi("급증 구·군", n_spike, C["danger"], "미분양 30%↑"),
                     kpi("미분양 최다",
                         unsold_df.iloc[0]["지역구"] if not unsold_df.empty else "-",
                         C["warning"],
                         f"{int(unsold_df.iloc[0]['미분양세대수']):,}세대" if not unsold_df.empty else ""),
                 ]),

        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 360px","gap":"16px",
                        "alignItems":"start"}, children=[
            # V-World 지도 iframe
            html.Div(style=CARD, children=[
                html.P("구·군을 클릭하면 상세 정보를 확인할 수 있습니다.",
                       style={"color":C["muted"],"fontSize":"12px","margin":"0 0 10px"}),
                html.Iframe(
                    id="vworld-iframe",
                    srcDoc=html_content,
                    style={"width":"100%","height":"560px","border":"none","borderRadius":"8px"},
                ),
            ]),

            # 사이드 패널
            html.Div(id="map-side-panel", style={**CARD, "minHeight":"560px"}, children=[
                html.P("← 지도에서 구·군을 클릭하세요",
                       style={"color":C["muted"],"fontSize":"13px",
                              "marginTop":"60px","textAlign":"center"}),
            ]),
        ]),

        # iframe → Dash 메시지 수신용 Store
        dcc.Store(id="clicked-gu-store"),

        # postMessage 수신 스크립트
        html.Script(f"""
            window.addEventListener('message', function(evt) {{
                if (evt.data && evt.data.type === 'gu_click') {{
                    var store = document.getElementById('clicked-gu-store');
                    if (store) {{
                        window.dash_clientside = window.dash_clientside || {{}};
                    }}
                    // Dash store 업데이트
                    var event = new CustomEvent('dash-store-update', {{
                        detail: {{ storeId: 'clicked-gu-store', value: evt.data.name }}
                    }});
                    document.dispatchEvent(event);
                }}
            }});
        """),
    ])


def build_tab_unsold(df):
    spike_df = df[df["급증여부"]].copy()
    n_spike  = len(spike_df)
    n_total  = len(df)

    bar_df = df.sort_values("미분양세대수", ascending=True)
    fig = go.Figure(go.Bar(
        x=bar_df["미분양세대수"], y=bar_df["지역구"], orientation="h",
        marker_color=[C["danger"] if v else C["accent"] for v in bar_df["급증여부"]],
        text=bar_df["증감률"].apply(lambda x: f"{x:+.1f}%" if x else ""),
        textposition="outside", textfont=dict(color=C["text"], size=11),
    ))
    fig.update_layout(**PT, title="구·군별 미분양 세대수  ·  빨간색 = 전월 대비 30%↑",
                      height=560, xaxis=dict(gridcolor=C["border"]),
                      yaxis=dict(gridcolor=C["border"]))

    spike_rows = spike_df[["지역구","기준월","미분양세대수","전월세대수","증감률"]].copy()
    spike_rows["증감률"] = spike_rows["증감률"].apply(lambda x: f"{x:+.1f}%")

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("모니터링 지역", n_total, sub="부산 16개 구·군"),
                            kpi("급증 타깃", n_spike, C["danger"], f"전월 대비 {UNSOLD_SPIKE_THRESHOLD_PCT:.0f}%↑"),
                            kpi("정상 지역", n_total-n_spike, C["ok"])]),
        html.Div(style={**CARD,"marginBottom":"24px","borderLeft":f"3px solid {C['danger']}"}, children=[
            html.P("⚠  영업 우선 타깃 — 시공사 교체 또는 분양 전략 변경 가능성 높음",
                   style={"color":C["danger"],"fontWeight":"600","margin":"0 0 16px","fontSize":"13px"}),
            dash_table.DataTable(data=spike_rows.to_dict("records"),
                columns=[{"name":c,"id":c} for c in spike_rows.columns], **TABLE_STYLE)
            if not spike_rows.empty else html.P("현재 급증 지역 없음", style={"color":C["muted"]}),
        ]),
        dcc.Graph(figure=fig),
    ])


def build_tab_price(df, tdf):
    if df.empty:
        return html.P("데이터 없음", style={"color":C["muted"]})

    avg_all = int(df["평균거래가"].mean())
    top_gu  = df.loc[df["평균거래가"].idxmax(), "지역구"]
    total_d = int(df["거래건수"].sum())

    bar_df = df.sort_values("평균거래가", ascending=True)
    fig_bar = go.Figure(go.Bar(
        x=bar_df["평균거래가"], y=bar_df["지역구"], orientation="h",
        marker=dict(color=bar_df["평균거래가"],
                    colorscale=[[0,C["accent2"]],[1,C["accent"]]]),
        text=bar_df["평균거래가"].apply(lambda x: f"{x:,.0f}만"),
        textposition="outside", textfont=dict(color=C["text"], size=10),
    ))
    fig_bar.update_layout(**PT, title="구·군별 평균 거래가 (최근 3개월)", height=560,
                          xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))

    fig_t = go.Figure()
    if not tdf.empty:
        m = tdf.groupby("월")["거래금액"].mean().reset_index()
        fig_t.add_trace(go.Scatter(
            x=m["월"], y=m["거래금액"], mode="lines+markers",
            line=dict(color=C["accent"], width=2),
            marker=dict(size=6, color=C["accent"]),
            fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
        ))
    fig_t.update_layout(**PT, title="부산 전체 월별 평균 거래가 추이", height=260,
                        xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("부산 평균", f"{avg_all:,}만원", C["accent"]),
                            kpi("최고가 지역구", top_gu),
                            kpi("총 거래건수", f"{total_d:,}건", C["accent2"], "최근 3개월")]),
        dcc.Graph(figure=fig_t),
        dcc.Graph(figure=fig_bar),
    ])


def build_tab_permit(df):
    if df.empty:
        return html.P("데이터 없음", style={"color":C["muted"]})

    total_u = int(df["세대수"].sum())
    top_c   = df.groupby("시공사")["세대수"].sum().idxmax()
    sm = df.groupby("지역구")["세대수"].sum().reset_index().sort_values("세대수", ascending=True)

    fig = go.Figure(go.Bar(
        x=sm["세대수"], y=sm["지역구"], orientation="h",
        marker_color=C["accent"],
        text=sm["세대수"].apply(lambda x: f"{x:,}세대"),
        textposition="outside", textfont=dict(color=C["text"], size=10),
    ))
    fig.update_layout(**PT, title="구·군별 신규 착공·인허가 세대수", height=560,
                      xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))

    cd = df.groupby("시공사")["세대수"].sum().reset_index()
    fig_pie = go.Figure(go.Pie(
        labels=cd["시공사"], values=cd["세대수"], hole=0.45,
        marker=dict(colors=[C["accent"],C["accent2"],C["ok"],C["danger"],C["muted"]]),
        textfont=dict(color=C["text"]),
    ))
    fig_pie.update_layout(**PT, title="시공사별 세대수 점유율", height=300)

    tdf = df.sort_values("인허가일", ascending=False).head(20).copy()
    tdf["인허가일"] = tdf["인허가일"].astype(str)

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("총 인허가 세대수", f"{total_u:,}세대", C["accent"]),
                            kpi("최다 시공사", top_c),
                            kpi("모니터링 건수", f"{len(df)}건", C["muted"])]),
        html.Div(style={"display":"grid","gridTemplateColumns":"2fr 1fr","gap":"16px"},
                 children=[dcc.Graph(figure=fig), dcc.Graph(figure=fig_pie)]),
        html.Div(style={**CARD,"marginTop":"24px"}, children=[
            html.P("최근 인허가 내역 (상위 20건)",
                   style={"color":C["muted"],"fontSize":"12px","margin":"0 0 12px"}),
            dash_table.DataTable(data=tdf.to_dict("records"),
                columns=[{"name":c,"id":c} for c in tdf.columns], **TABLE_STYLE),
        ]),
    ])

# ---------------------------------------------------------------------------
# 앱 레이아웃
# ---------------------------------------------------------------------------
app = Dash(__name__, title="부산 분양·거래시장 통합 모니터",
           suppress_callback_exceptions=True)

TAB_S = {"backgroundColor":"transparent","color":C["muted"],"border":"none",
          "borderBottom":f"2px solid transparent","padding":"12px 20px",
          "fontSize":"13px","fontWeight":"500"}
TAB_A = {**TAB_S,"color":C["accent"],"borderBottom":f"2px solid {C['accent']}",
          "backgroundColor":"transparent"}

app.layout = html.Div(
    style={"backgroundColor":C["bg"],"minHeight":"100vh",
           "fontFamily":"Pretendard, Malgun Gothic, sans-serif","color":C["text"]},
    children=[
        # 헤더
        html.Div(style={"backgroundColor":C["surface"],"borderBottom":f"1px solid {C['border']}",
                        "padding":"0 32px","display":"flex","alignItems":"center",
                        "justifyContent":"space-between","height":"64px",
                        "boxShadow":"0 1px 4px rgba(0,0,0,0.06)"}, children=[
            html.Div(style={"display":"flex","alignItems":"center","gap":"12px"}, children=[
                html.Span("●", style={"color":C["accent"],"fontSize":"10px"}),
                html.Span("부산 분양·거래시장 통합 모니터",
                          style={"fontWeight":"800","fontSize":"22px",
                                 "letterSpacing":"-0.5px","color":C["text"]}),
            ]),
            html.Div(style={"display":"flex","alignItems":"center","gap":"20px"}, children=[
                html.Span(f"갱신: {updated_at}",
                          style={"color":C["muted"],"fontSize":"12px"}),
                html.Span(f"⚠ 급증 {n_spike}개구" if n_spike else "✓ 정상",
                    style={"color":C["danger"] if n_spike else C["ok"],
                           "fontSize":"12px","fontWeight":"600",
                           "backgroundColor":"rgba(220,38,38,0.08)" if n_spike else "rgba(22,163,74,0.08)",
                           "padding":"4px 12px","borderRadius":"20px"}),
            ]),
        ]),

        # 서브헤더
        html.Div(style={"padding":"10px 32px","backgroundColor":C["surface2"],
                        "borderBottom":f"1px solid {C['border']}"}, children=[
            html.P("미분양이 쌓이는 지역의 시행사를 먼저 포착해 시공사 교체·분양 전략 변경 타이밍에 선제적으로 영업합니다.",
                   style={"color":C["muted"],"fontSize":"12px","margin":"0"}),
        ]),

        # 탭 바
        html.Div(style={"padding":"0 24px","backgroundColor":C["surface"],
                        "borderBottom":f"1px solid {C['border']}"}, children=[
            dcc.Tabs(id="main-tabs", value="tab-map", children=[
                dcc.Tab(label="🗺  지도",        value="tab-map",    style=TAB_S, selected_style=TAB_A),
                dcc.Tab(label="🔔  미분양 알림", value="tab-unsold", style=TAB_S, selected_style=TAB_A),
                dcc.Tab(label="📊  거래가 분석", value="tab-price",  style=TAB_S, selected_style=TAB_A),
                dcc.Tab(label="🏗  착공·허가",   value="tab-permit", style=TAB_S, selected_style=TAB_A),
            ], style={"border":"none","backgroundColor":"transparent"},
               colors={"border":"transparent","primary":C["accent"],"background":C["surface"]}),
        ]),

        # 탭 콘텐츠
        html.Div(id="tab-content", style={"padding":"24px 32px"}),

        # 푸터
        html.Div(style={"padding":"14px 32px","borderTop":f"1px solid {C['border']}",
                        "marginTop":"24px","backgroundColor":C["surface"]}, children=[
            html.P("매주 월요일 오전 7시 자동 갱신  ·  국토부 실거래가 API  ·  건축인허가 API  ·  부산광역시 미분양현황 API",
                   style={"color":C["muted"],"fontSize":"11px","margin":"0"}),
        ]),
    ]
)

# ---------------------------------------------------------------------------
# 콜백
# ---------------------------------------------------------------------------

@app.callback(Output("tab-content","children"), Input("main-tabs","value"))
def render_tab(tab):
    if tab == "tab-map":    return build_tab_map()
    if tab == "tab-unsold": return build_tab_unsold(unsold_df)
    if tab == "tab-price":  return build_tab_price(price_df, trend_df)
    if tab == "tab-permit": return build_tab_permit(permit_df)
    return html.Div()


@app.callback(
    Output("map-side-panel","children"),
    Input("clicked-gu-store","data"),
    prevent_initial_call=True,
)
def map_side_panel(gu_name):
    if not gu_name:
        return html.P("← 지도에서 구·군을 클릭하세요",
                      style={"color":C["muted"],"fontSize":"13px",
                             "marginTop":"60px","textAlign":"center"})

    u_row  = unsold_df[unsold_df["지역구"] == gu_name]
    p_row  = price_df[price_df["지역구"] == gu_name]
    pm_rows = permit_df[permit_df["지역구"] == gu_name].sort_values("인허가일", ascending=False).head(5).copy()
    pm_rows["인허가일"] = pm_rows["인허가일"].astype(str)

    unsold_count = int(u_row["미분양세대수"].values[0]) if not u_row.empty else "-"
    change_rate  = u_row["증감률"].values[0] if not u_row.empty else None
    avg_price    = int(p_row["평균거래가"].values[0]) if not p_row.empty else None
    spike        = (change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT

    def stat_row(label, value, color=None):
        return html.Div(style={"display":"flex","justifyContent":"space-between",
                                "padding":"8px 0","borderBottom":f"1px solid {C['border']}"}, children=[
            html.Span(label, style={"color":C["muted"],"fontSize":"12px"}),
            html.Span(str(value), style={"color":color or C["text"],
                                          "fontSize":"13px","fontWeight":"600"}),
        ])

    return html.Div([
        html.Div(style={"display":"flex","alignItems":"center",
                        "justifyContent":"space-between","marginBottom":"20px"}, children=[
            html.H3(gu_name, style={"margin":"0","fontSize":"20px",
                                     "fontWeight":"700","color":C["text"]}),
            html.Span("⚠ 급증" if spike else "✓ 정상",
                style={"color":C["danger"] if spike else C["ok"],"fontSize":"11px",
                       "fontWeight":"700",
                       "backgroundColor":"rgba(220,38,38,0.08)" if spike else "rgba(22,163,74,0.08)",
                       "padding":"3px 10px","borderRadius":"12px"}),
        ]),

        html.P("미분양 현황", style={"color":C["muted"],"fontSize":"11px",
                                    "letterSpacing":"0.1em","margin":"0 0 4px",
                                    "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("미분양 세대수", f"{unsold_count}세대"),
            stat_row("전월 대비",
                     f"{change_rate:+.1f}%" if change_rate is not None else "-",
                     C["danger"] if spike else C["ok"]),
        ]),

        html.P("실거래가", style={"color":C["muted"],"fontSize":"11px",
                                  "letterSpacing":"0.1em","margin":"0 0 4px",
                                  "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("최근 3개월 평균",
                     f"{avg_price:,}만원" if avg_price else "-", C["accent"]),
        ]),

        html.P("최근 인허가", style={"color":C["muted"],"fontSize":"11px",
                                     "letterSpacing":"0.1em","margin":"0 0 8px",
                                     "textTransform":"uppercase"}),
        html.Div(style={**CARD,"padding":"0"}, children=[
            dash_table.DataTable(
                data=pm_rows[["인허가일","세대수","시공사"]].to_dict("records"),
                columns=[{"name":c,"id":c} for c in ["인허가일","세대수","시공사"]],
                **TABLE_STYLE,
            ) if not pm_rows.empty else html.P("인허가 내역 없음",
                style={"color":C["muted"],"padding":"12px","fontSize":"12px"}),
        ]),
    ])


if __name__ == "__main__":
    app.run(debug=True)