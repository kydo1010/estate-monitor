"""
dashboards/app.py
부산 분양·거래시장 통합 모니터 (다크모드 기본 + V-World 지도)

실행: python -m dashboards.app → http://127.0.0.1:8050
"""

import json
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import requests
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, State, clientside_callback

from src.config import (
    UNSOLD_SPIKE_THRESHOLD_PCT, VWORLD_API_KEY,
    BUSAN_DISTRICT_CODES, BUSAN_DONG_CODES,
)
from src.db import (
    get_avg_price_by_district, get_session,
    UnsoldHousing, BuildingPermit, Trade,
)

# ---------------------------------------------------------------------------
# 색상 토큰 (다크모드 / 라이트모드)
# ---------------------------------------------------------------------------
DARK_COLORS = {
    "bg":       "#0d1117",
    "surface":  "#161b27",
    "surface2": "#1e2636",
    "border":   "#2a3347",
    "accent":   "#4f8ef7",
    "accent2":  "#0ea5e9",
    "danger":   "#e05c5c",
    "ok":       "#4caf82",
    "warning":  "#d97706",
    "text":     "#e8eaf0",
    "muted":    "#7a8499",
    "chart_bg": "#161b27",
}

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

DEFAULT_THEME = "dark"


def get_colors(theme: str) -> dict:
    return DARK_COLORS if theme == "dark" else LIGHT_COLORS


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
            "fontSize": "13px",
            "fontFamily": "Malgun Gothic, Apple SD Gothic Neo, sans-serif",
        },
        "style_header": {
            "backgroundColor": colors["surface2"],
            "color": colors["muted"],
            "fontWeight": "600",
            "border": f"1px solid {colors['border']}",
            "fontSize": "12px",
            "letterSpacing": "0.05em",
        },
        "style_data_conditional": [
            {"if": {"row_index": "odd"}, "backgroundColor": colors["surface2"]},
        ],
    }


def kpi(colors, label, value, color=None, sub=None):
    return html.Div(style=get_kpi_card_style(colors), children=[
        html.P(label, style={"color": colors["muted"], "fontSize": "11px",
                              "letterSpacing": "0.1em", "margin": "0 0 8px",
                              "textTransform": "uppercase"}),
        html.P(str(value), style={"color": color or colors["text"], "fontSize": "34px",
                                   "fontWeight": "700", "margin": "0", "lineHeight": "1"}),
        html.P(sub or "", style={"color": colors["muted"], "fontSize": "11px", "margin": "6px 0 0"}),
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

# ---------------------------------------------------------------------------
# 탭별 레이아웃
# ---------------------------------------------------------------------------

def build_tab_map(colors):
    CARD = get_card_style(colors)
    html_path = Path(__file__).parent / "assets" / "vworld_map.html"
    html_content = html_path.read_text(encoding="utf-8")
    html_content = html_content.replace("__VWORLD_API_KEY__", VWORLD_API_KEY or "")

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"16px","flexWrap":"wrap"},
                 children=[
                     kpi(colors, "부산 평균 거래가",
                         f"{int(price_df['평균거래가'].mean()):,}만원" if not price_df.empty else "-",
                         colors["accent"]),
                     kpi(colors, "급증 구·군", n_spike, colors["danger"], "미분양 30%↑"),
                     kpi(colors, "미분양 최다",
                         unsold_df.iloc[0]["지역구"] if not unsold_df.empty else "-",
                         colors["warning"],
                         f"{int(unsold_df.iloc[0]['미분양세대수']):,}세대" if not unsold_df.empty else ""),
                 ]),
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 360px","gap":"16px",
                        "alignItems":"start"}, children=[
            html.Div(style=CARD, children=[
                html.P("구·군을 클릭하면 상세 정보를 확인할 수 있습니다.",
                       style={"color":colors["muted"],"fontSize":"12px","margin":"0 0 10px"}),
                html.Iframe(
                    id="vworld-iframe",
                    srcDoc=html_content,
                    style={"width":"100%","height":"560px","border":"none","borderRadius":"8px"},
                ),
            ]),
            html.Div(id="map-side-panel", style={**CARD, "minHeight":"560px"}, children=[
                html.P("← 지도에서 구·군을 클릭하세요",
                       style={"color":colors["muted"],"fontSize":"13px",
                              "marginTop":"60px","textAlign":"center"}),
            ]),
        ]),
        dcc.Store(id="clicked-gu-store"),
        html.Script(f"""
            window.addEventListener('message', function(evt) {{
                if (evt.data && evt.data.type === 'gu_click') {{
                    var event = new CustomEvent('dash-store-update', {{
                        detail: {{ storeId: 'clicked-gu-store', value: evt.data.name }}
                    }});
                    document.dispatchEvent(event);
                }}
            }});
        """),
    ])


def build_tab_unsold(colors, df):
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)
    PT = get_plotly_template(colors)

    spike_df = df[df["급증여부"]].copy()
    n_spike_local = len(spike_df)
    n_total = len(df)

    bar_df = df.sort_values("미분양세대수", ascending=True)
    fig = go.Figure(go.Bar(
        x=bar_df["미분양세대수"], y=bar_df["지역구"], orientation="h",
        marker_color=[colors["danger"] if v else colors["accent"] for v in bar_df["급증여부"]],
        text=bar_df["증감률"].apply(lambda x: f"{x:+.1f}%" if x else ""),
        textposition="outside", textfont=dict(color=colors["text"], size=11),
    ))
    fig.update_layout(**PT, title="구·군별 미분양 세대수  ·  빨간색 = 전월 대비 30%↑",
                      height=560, xaxis=dict(gridcolor=colors["border"]),
                      yaxis=dict(gridcolor=colors["border"]))

    spike_rows = spike_df[["지역구","기준월","미분양세대수","전월세대수","증감률"]].copy()
    spike_rows["증감률"] = spike_rows["증감률"].apply(lambda x: f"{x:+.1f}%")

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi(colors, "모니터링 지역", n_total, sub="부산 16개 구·군"),
                            kpi(colors, "급증 타깃", n_spike_local, colors["danger"],
                                f"전월 대비 {UNSOLD_SPIKE_THRESHOLD_PCT:.0f}%↑"),
                            kpi(colors, "정상 지역", n_total - n_spike_local, colors["ok"])]),
        html.Div(style={**CARD,"marginBottom":"24px","borderLeft":f"3px solid {colors['danger']}"}, children=[
            html.P("⚠  영업 우선 타깃 — 시공사 교체 또는 분양 전략 변경 가능성 높음",
                   style={"color":colors["danger"],"fontWeight":"600","margin":"0 0 16px","fontSize":"13px"}),
            dash_table.DataTable(data=spike_rows.to_dict("records"),
                columns=[{"name":c,"id":c} for c in spike_rows.columns], **TABLE_STYLE)
            if not spike_rows.empty else html.P("현재 급증 지역 없음", style={"color":colors["muted"]}),
        ]),
        dcc.Graph(figure=fig),
    ])


def build_tab_price(colors, df, tdf):
    PT = get_plotly_template(colors)
    if df.empty:
        return html.P("데이터 없음", style={"color":colors["muted"]})

    avg_all = int(df["평균거래가"].mean())
    top_gu  = df.loc[df["평균거래가"].idxmax(), "지역구"]
    total_d = int(df["거래건수"].sum())

    bar_df = df.sort_values("평균거래가", ascending=True)
    fig_bar = go.Figure(go.Bar(
        x=bar_df["평균거래가"], y=bar_df["지역구"], orientation="h",
        marker=dict(color=bar_df["평균거래가"],
                    colorscale=[[0,colors["accent2"]],[1,colors["accent"]]]),
        text=bar_df["평균거래가"].apply(lambda x: f"{x:,.0f}만"),
        textposition="outside", textfont=dict(color=colors["text"], size=10),
    ))
    fig_bar.update_layout(**PT, title="구·군별 평균 거래가 (최근 3개월)", height=560,
                          xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

    fig_t = go.Figure()
    if not tdf.empty:
        m = tdf.groupby("월")["거래금액"].mean().reset_index()
        fig_t.add_trace(go.Scatter(
            x=m["월"], y=m["거래금액"], mode="lines+markers",
            line=dict(color=colors["accent"], width=2),
            marker=dict(size=6, color=colors["accent"]),
            fill="tozeroy", fillcolor=_hex_to_rgba(colors["accent"], 0.08),
        ))
    fig_t.update_layout(**PT, title="부산 전체 월별 평균 거래가 추이", height=260,
                        xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi(colors, "부산 평균", f"{avg_all:,}만원", colors["accent"]),
                            kpi(colors, "최고가 지역구", top_gu),
                            kpi(colors, "총 거래건수", f"{total_d:,}건", colors["accent2"], "최근 3개월")]),
        dcc.Graph(figure=fig_t),
        dcc.Graph(figure=fig_bar),
    ])


def build_tab_permit(colors, df):
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)
    PT = get_plotly_template(colors)

    if df.empty:
        return html.P("데이터 없음", style={"color":colors["muted"]})

    total_u = int(df["세대수"].sum())
    top_c   = df.groupby("시공사")["세대수"].sum().idxmax()
    sm = df.groupby("지역구")["세대수"].sum().reset_index().sort_values("세대수", ascending=True)

    fig = go.Figure(go.Bar(
        x=sm["세대수"], y=sm["지역구"], orientation="h",
        marker_color=colors["accent"],
        text=sm["세대수"].apply(lambda x: f"{x:,}세대"),
        textposition="outside", textfont=dict(color=colors["text"], size=10),
    ))
    fig.update_layout(**PT, title="구·군별 신규 착공·인허가 세대수", height=560,
                      xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

    cd = df.groupby("시공사")["세대수"].sum().reset_index()
    fig_pie = go.Figure(go.Pie(
        labels=cd["시공사"], values=cd["세대수"], hole=0.45,
        marker=dict(colors=[colors["accent"],colors["accent2"],colors["ok"],
                             colors["danger"],colors["muted"]]),
        textfont=dict(color=colors["text"]),
        textposition="inside", textinfo="percent",
    ))
    fig_pie.update_layout(
        **{**PT, "margin": dict(l=0, r=0, t=40, b=0)},
        title="시공사별 세대수 점유율", height=360,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
    )

    tdf = df.sort_values("인허가일", ascending=False).head(20).copy()
    tdf["인허가일"] = tdf["인허가일"].astype(str)

    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi(colors, "총 인허가 세대수", f"{total_u:,}세대", colors["accent"]),
                            kpi(colors, "최다 시공사", top_c),
                            kpi(colors, "모니터링 건수", f"{len(df)}건", colors["muted"])]),
        html.Div(style={"display":"grid","gridTemplateColumns":"2fr 1fr","gap":"16px"},
                 children=[dcc.Graph(figure=fig), dcc.Graph(figure=fig_pie)]),
        html.Div(style={**CARD,"marginTop":"24px"}, children=[
            html.P("최근 인허가 내역 (상위 20건)",
                   style={"color":colors["muted"],"fontSize":"12px","margin":"0 0 12px"}),
            dash_table.DataTable(data=tdf.to_dict("records"),
                columns=[{"name":c,"id":c} for c in tdf.columns], **TABLE_STYLE),
        ]),

        # 건축HUB 단지 검색
        html.Div(style={**CARD,"marginTop":"24px"}, children=[
            html.P("건축HUB 주택인허가 검색",
                   style={"color":colors["text"],"fontSize":"15px","fontWeight":"700",
                          "margin":"0 0 4px"}),
            html.P("구·군과 동을 선택하면 해당 지역의 주택인허가 정보를 실시간 조회합니다.",
                   style={"color":colors["muted"],"fontSize":"12px","margin":"0 0 16px"}),
            html.Div(style={"display":"flex","gap":"12px","flexWrap":"wrap","alignItems":"center"},
                     children=[
                dcc.Dropdown(
                    id="permit-search-gu",
                    options=[{"label": v, "value": k} for k, v in BUSAN_DISTRICT_CODES.items()],
                    placeholder="구·군 선택",
                    style={"width":"160px","fontSize":"13px"},
                    clearable=False,
                ),
                dcc.Dropdown(
                    id="permit-search-dong",
                    options=[],
                    placeholder="동 선택",
                    style={"width":"180px","fontSize":"13px"},
                    clearable=False,
                ),
                html.Button("검색", id="permit-search-btn", n_clicks=0,
                    style={
                        "backgroundColor": colors["accent"],
                        "color": "#ffffff",
                        "border": "none",
                        "borderRadius": "8px",
                        "padding": "8px 20px",
                        "fontSize": "13px",
                        "fontWeight": "600",
                        "cursor": "pointer",
                    }),
            ]),
            html.Div(id="permit-search-result", style={"marginTop":"20px"}),
        ]),
    ])


def build_tab_content(tab, colors):
    if tab == "tab-map":    return build_tab_map(colors)
    if tab == "tab-unsold": return build_tab_unsold(colors, unsold_df)
    if tab == "tab-price":  return build_tab_price(colors, price_df, trend_df)
    if tab == "tab-permit": return build_tab_permit(colors, permit_df)
    return html.Div()

# ---------------------------------------------------------------------------
# 전체 페이지 레이아웃 (테마별 재구성)
# ---------------------------------------------------------------------------

def build_page(theme, active_tab):
    colors = get_colors(theme)
    is_dark = theme == "dark"
    toggle_label = "☀️ 라이트" if is_dark else "🌙 다크"

    TAB_S = {"backgroundColor":"transparent","color":colors["muted"],"border":"none",
              "borderBottom":"2px solid transparent","padding":"12px 20px",
              "fontSize":"13px","fontWeight":"500"}
    TAB_A = {**TAB_S,"color":colors["accent"],"borderBottom":f"2px solid {colors['accent']}",
              "backgroundColor":"transparent"}

    toggle_style = {
        "color": colors["text"],
        "fontSize": "12px",
        "fontWeight": "600",
        "backgroundColor": colors["surface2"],
        "border": f"1px solid {colors['border']}",
        "padding": "4px 14px",
        "borderRadius": "20px",
        "cursor": "pointer",
    }

    badge_style = {
        "color": colors["danger"] if n_spike else colors["ok"],
        "fontSize": "12px", "fontWeight": "600",
        "backgroundColor": _hex_to_rgba(colors["danger"] if n_spike else colors["ok"], 0.08),
        "padding": "4px 12px", "borderRadius": "20px",
    }

    return html.Div(
        style={"backgroundColor":colors["bg"],"minHeight":"100vh",
               "fontFamily":"Malgun Gothic, Apple SD Gothic Neo, sans-serif",
               "color":colors["text"]},
        children=[
            # 헤더
            html.Div(style={"backgroundColor":colors["surface"],
                            "borderBottom":f"1px solid {colors['border']}",
                            "padding":"0 32px","display":"flex","alignItems":"center",
                            "justifyContent":"space-between","height":"64px",
                            "boxShadow":"0 1px 4px rgba(0,0,0,0.06)"}, children=[
                html.Div(style={"display":"flex","alignItems":"center","gap":"12px"}, children=[
                    html.Span("●", style={"color":colors["accent"],"fontSize":"10px"}),
                    html.Span("부산 분양·거래시장 통합 모니터",
                              style={"fontWeight":"800","fontSize":"22px",
                                     "letterSpacing":"-0.5px","color":colors["text"]}),
                ]),
                html.Div(style={"display":"flex","alignItems":"center","gap":"20px"}, children=[
                    html.Span(f"갱신: {updated_at}",
                              style={"color":colors["muted"],"fontSize":"12px"}),
                    html.Span(f"⚠ 급증 {n_spike}개구" if n_spike else "✓ 정상",
                              style=badge_style),
                    html.Button(toggle_label, id="theme-toggle-btn", n_clicks=0,
                                style=toggle_style),
                ]),
            ]),

            # 서브헤더
            html.Div(style={"padding":"10px 32px","backgroundColor":colors["surface2"],
                            "borderBottom":f"1px solid {colors['border']}"}, children=[
                html.P("미분양이 쌓이는 지역의 시행사를 먼저 포착해 시공사 교체·분양 전략 변경 타이밍에 선제적으로 영업합니다.",
                       style={"color":colors["muted"],"fontSize":"12px","margin":"0"}),
            ]),

            # 탭 바
            html.Div(style={"padding":"0 24px","backgroundColor":colors["surface"],
                            "borderBottom":f"1px solid {colors['border']}"}, children=[
                dcc.Tabs(id="main-tabs", value=active_tab, children=[
                    dcc.Tab(label="🗺  지도",        value="tab-map",    style=TAB_S, selected_style=TAB_A),
                    dcc.Tab(label="🔔  미분양 알림", value="tab-unsold", style=TAB_S, selected_style=TAB_A),
                    dcc.Tab(label="📊  거래가 분석", value="tab-price",  style=TAB_S, selected_style=TAB_A),
                    dcc.Tab(label="🏗  착공·허가",   value="tab-permit", style=TAB_S, selected_style=TAB_A),
                ], style={"border":"none","backgroundColor":"transparent"},
                   colors={"border":"transparent","primary":colors["accent"],
                           "background":colors["surface"]}),
            ]),

            # 탭 콘텐츠
            html.Div(id="tab-content", style={"padding":"24px 32px"},
                     children=build_tab_content(active_tab, colors)),

            # 푸터
            html.Div(style={"padding":"14px 32px","borderTop":f"1px solid {colors['border']}",
                            "marginTop":"24px","backgroundColor":colors["surface"]}, children=[
                html.P("매주 월요일 오전 7시 자동 갱신  ·  국토부 실거래가 API  ·  청약홈 API  ·  부산광역시 미분양현황 API",
                       style={"color":colors["muted"],"fontSize":"11px","margin":"0"}),
            ]),
        ]
    )

# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
app = Dash(__name__, title="부산 분양·거래시장 통합 모니터",
           suppress_callback_exceptions=True)

app.layout = html.Div([
    dcc.Store(id="theme-store", data=DEFAULT_THEME),
    dcc.Store(id="active-tab-store", data="tab-map"),
    html.Div(id="page-content"),
])

# ---------------------------------------------------------------------------
# 콜백
# ---------------------------------------------------------------------------

@app.callback(
    Output("theme-store", "data"),
    Input("theme-toggle-btn", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def toggle_theme(n_clicks, current_theme):
    return "light" if current_theme == "dark" else "dark"


@app.callback(Output("active-tab-store", "data"), Input("main-tabs", "value"))
def sync_active_tab(value):
    return value


@app.callback(
    Output("page-content", "children"),
    Input("theme-store", "data"),
    Input("active-tab-store", "data"),
)
def render_page(theme, active_tab):
    return build_page(theme, active_tab)


@app.callback(
    Output("map-side-panel", "children"),
    Input("clicked-gu-store", "data"),
    Input("theme-store", "data"),
    prevent_initial_call=True,
)
def map_side_panel(gu_name, theme):
    colors = get_colors(theme)
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)

    if not gu_name:
        return html.P("← 지도에서 구·군을 클릭하세요",
                      style={"color":colors["muted"],"fontSize":"13px",
                             "marginTop":"60px","textAlign":"center"})

    u_row   = unsold_df[unsold_df["지역구"] == gu_name]
    p_row   = price_df[price_df["지역구"] == gu_name]
    pm_rows = permit_df[permit_df["지역구"] == gu_name].sort_values(
        "인허가일", ascending=False).head(5).copy()
    pm_rows["인허가일"] = pm_rows["인허가일"].astype(str)

    unsold_count = int(u_row["미분양세대수"].values[0]) if not u_row.empty else "-"
    change_rate  = u_row["증감률"].values[0] if not u_row.empty else None
    avg_price    = int(p_row["평균거래가"].values[0]) if not p_row.empty else None
    spike        = (change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT

    def stat_row(label, value, color=None):
        return html.Div(
            style={"display":"flex","justifyContent":"space-between",
                   "padding":"8px 0","borderBottom":f"1px solid {colors['border']}"},
            children=[
                html.Span(label, style={"color":colors["muted"],"fontSize":"12px"}),
                html.Span(str(value), style={"color":color or colors["text"],
                                              "fontSize":"13px","fontWeight":"600"}),
            ])

    return html.Div([
        html.Div(style={"display":"flex","alignItems":"center",
                        "justifyContent":"space-between","marginBottom":"20px"}, children=[
            html.H3(gu_name, style={"margin":"0","fontSize":"20px",
                                     "fontWeight":"700","color":colors["text"]}),
            html.Span("⚠ 급증" if spike else "✓ 정상",
                style={"color":colors["danger"] if spike else colors["ok"],"fontSize":"11px",
                       "fontWeight":"700",
                       "backgroundColor":_hex_to_rgba(
                           colors["danger"] if spike else colors["ok"], 0.08),
                       "padding":"3px 10px","borderRadius":"12px"}),
        ]),
        html.P("미분양 현황", style={"color":colors["muted"],"fontSize":"11px",
                                    "letterSpacing":"0.1em","margin":"0 0 4px",
                                    "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("미분양 세대수", f"{unsold_count}세대"),
            stat_row("전월 대비",
                     f"{change_rate:+.1f}%" if change_rate is not None else "-",
                     colors["danger"] if spike else colors["ok"]),
        ]),
        html.P("실거래가", style={"color":colors["muted"],"fontSize":"11px",
                                  "letterSpacing":"0.1em","margin":"0 0 4px",
                                  "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("최근 3개월 평균",
                     f"{avg_price:,}만원" if avg_price else "-", colors["accent"]),
        ]),
        html.P("최근 인허가", style={"color":colors["muted"],"fontSize":"11px",
                                     "letterSpacing":"0.1em","margin":"0 0 8px",
                                     "textTransform":"uppercase"}),
        html.Div(style={**CARD,"padding":"0"}, children=[
            dash_table.DataTable(
                data=pm_rows[["인허가일","세대수","시공사"]].to_dict("records"),
                columns=[{"name":c,"id":c} for c in ["인허가일","세대수","시공사"]],
                **TABLE_STYLE,
            ) if not pm_rows.empty else html.P("인허가 내역 없음",
                style={"color":colors["muted"],"padding":"12px","fontSize":"12px"}),
        ]),
    ])


# ---------------------------------------------------------------------------
# 건축HUB 검색 콜백
# ---------------------------------------------------------------------------

@app.callback(
    Output("permit-search-dong", "options"),
    Input("permit-search-gu", "value"),
    prevent_initial_call=True,
)
def update_dong_options(sgg_cd):
    if not sgg_cd:
        return []
    dongs = BUSAN_DONG_CODES.get(sgg_cd, {})
    return [{"label": v, "value": k} for k, v in dongs.items()]


@app.callback(
    Output("permit-search-result", "children"),
    Input("permit-search-btn", "n_clicks"),
    State("permit-search-gu", "value"),
    State("permit-search-dong", "value"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def search_building_permit(n_clicks, sgg_cd, bjdong_cd, theme):
    colors = get_colors(theme)
    TABLE_STYLE = get_table_style(colors)

    if not sgg_cd or not bjdong_cd:
        return html.P("구·군과 동을 모두 선택해주세요.",
                      style={"color": colors["warning"], "fontSize": "13px"})

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
                          style={"color": colors["muted"], "fontSize": "13px"})

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
                   style={"color": colors["muted"], "fontSize": "12px", "margin": "0 0 12px"}),
            dash_table.DataTable(
                data=df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in df.columns],
                **TABLE_STYLE,
                page_size=20,
            ),
        ])

    except requests.exceptions.Timeout:
        return html.P("요청 시간이 초과됐습니다. 다시 시도해주세요.",
                      style={"color": colors["danger"], "fontSize": "13px"})
    except Exception as e:
        return html.P(f"조회 중 오류가 발생했습니다: {str(e)}",
                      style={"color": colors["danger"], "fontSize": "13px"})


if __name__ == "__main__":
    app.run(debug=True)