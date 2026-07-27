"""
dashboards/app.py  —  분양·거래시장 통합 모니터 (부산)
실행: python -m dashboards.app  →  http://127.0.0.1:8050
"""

import json, requests
from datetime import date, timedelta
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update

from src.config import BUSAN_DISTRICT_CODES, UNSOLD_SPIKE_THRESHOLD_PCT
from src.db import (
    get_avg_price_by_district, get_session,
    UnsoldHousing, BuildingPermit, PriceCapZone, Trade,
)

# ---------------------------------------------------------------------------
# GeoJSON (부산 16개 구·군) — 앱 시작 시 1회 로드·병합
# ---------------------------------------------------------------------------

def _load_busan_geojson():
    url = ('https://raw.githubusercontent.com/vuski/admdongkor/master/'
           'ver20230701/HangJeongDong_ver20230701.geojson')
    data = requests.get(url, timeout=60).json()
    gu_dict: dict = {}
    for f in data['features']:
        p = f['properties']
        if p.get('sido') != '26':
            continue
        sgg = p['sgg']
        if sgg not in gu_dict:
            gu_dict[sgg] = {'name': p['sggnm'], 'geoms': []}
        try:
            gu_dict[sgg]['geoms'].append(shape(f['geometry']))
        except Exception:
            pass
    features_out = []
    for sgg, v in sorted(gu_dict.items()):
        merged = unary_union(v['geoms'])
        features_out.append({
            'type': 'Feature',
            'properties': {'code': sgg, 'name': v['name']},
            'geometry': mapping(merged),
        })
    return {'type': 'FeatureCollection', 'features': features_out}

print("GeoJSON 로드 중...")
BUSAN_GEO = _load_busan_geojson()
print(f"GeoJSON 로드 완료: {len(BUSAN_GEO['features'])}개 구·군")

# ---------------------------------------------------------------------------
# 색상 토큰
# ---------------------------------------------------------------------------
C = {
    "bg": "#0d1117", "surface": "#161b27", "surface2": "#1e2636",
    "border": "#2a3347", "accent": "#e8845a", "accent2": "#4f8ef7",
    "danger": "#e05c5c", "ok": "#4caf82", "text": "#e8eaf0",
    "muted": "#7a8499", "chart_bg": "#161b27",
}
PT = dict(
    paper_bgcolor=C["chart_bg"], plot_bgcolor=C["chart_bg"],
    font=dict(color=C["text"], family="Pretendard, Malgun Gothic, sans-serif"),
    margin=dict(l=16, r=16, t=48, b=16),
)
CARD = {"background": C["surface"], "border": f"1px solid {C['border']}",
        "borderRadius": "12px", "padding": "20px 24px"}
KPI_CARD = {**CARD, "textAlign": "center", "flex": "1", "minWidth": "140px"}
TABLE_STYLE = {
    "style_table": {"overflowX": "auto"},
    "style_cell": {"backgroundColor": C["surface2"], "color": C["text"],
                   "border": f"1px solid {C['border']}", "padding": "10px 14px",
                   "fontSize": "13px"},
    "style_header": {"backgroundColor": C["surface"], "color": C["muted"],
                     "fontWeight": "600", "border": f"1px solid {C['border']}",
                     "fontSize": "12px", "letterSpacing": "0.05em"},
    "style_data_conditional": [{"if": {"row_index": "odd"}, "backgroundColor": C["bg"]}],
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
    end, start = date.today(), date.today() - timedelta(days=180)
    rows = get_avg_price_by_district(start, end)
    return pd.DataFrame(rows, columns=["지역구", "평균거래가", "거래건수"])

def load_permit_df():
    with get_session() as s:
        rows = s.query(BuildingPermit).all()
        return pd.DataFrame([{"지역구": r.district, "인허가일": r.permit_date,
                               "세대수": r.household_count, "시행사": r.developer,
                               "시공사": r.contractor} for r in rows])

def load_cap_df():
    with get_session() as s:
        rows = s.query(PriceCapZone).all()
        return pd.DataFrame([{"지역구": r.district, "지정일": r.designated_date,
                               "해제일": r.released_date or "-", "상태": r.status}
                              for r in rows])

def load_trend_df():
    with get_session() as s:
        rows = s.query(Trade).all()
        df = pd.DataFrame([{"지역구": r.district, "거래금액": r.deal_amount,
                             "거래일": r.deal_date} for r in rows])
        if df.empty:
            return df
        df["월"] = pd.to_datetime(df["거래일"]).dt.to_period("M").astype(str)
        return df

unsold_df = load_unsold_df()
price_df  = load_price_df()
permit_df = load_permit_df()
cap_df    = load_cap_df()
trend_df  = load_trend_df()

n_spike    = int(unsold_df["급증여부"].sum()) if not unsold_df.empty else 0
updated_at = date.today().strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# 지도 choropleth 빌드
# ---------------------------------------------------------------------------

def build_map_figure(unsold_df, price_df):
    """미분양 증감률 기준 choropleth. 급증=빨강, 양호=초록"""
    names = [f['properties']['name'] for f in BUSAN_GEO['features']]

    # 구별 증감률 매핑
    rate_map = dict(zip(unsold_df["지역구"], unsold_df["증감률"])) if not unsold_df.empty else {}
    price_map = dict(zip(price_df["지역구"], price_df["평균거래가"])) if not price_df.empty else {}

    rates  = [rate_map.get(n, 0) for n in names]
    prices = [price_map.get(n, 0) for n in names]

    hover = [
        f"<b>{n}</b><br>"
        f"미분양 증감: {r:+.1f}%<br>"
        f"평균 거래가: {p:,.0f}만원"
        for n, r, p in zip(names, rates, prices)
    ]

    fig = go.Figure(go.Choropleth(
        geojson=BUSAN_GEO,
        locations=names,
        z=rates,
        featureidkey="properties.name",
        colorscale=[
            [0.0,  "#1a6b3c"],   # 감소 → 진한 녹색
            [0.35, "#4caf82"],   # 소폭 증가 → 연녹색
            [0.55, "#f5c842"],   # 중간 → 노랑
            [0.75, "#e8845a"],   # 증가 → 오렌지
            [1.0,  "#e05c5c"],   # 급증 → 빨강
        ],
        zmin=-20, zmax=80,
        colorbar=dict(
            title=dict(text="미분양 증감률(%)", font=dict(color=C["text"], size=11)),
            tickfont=dict(color=C["text"]),
            bgcolor=C["surface"],
            bordercolor=C["border"],
            thickness=14,
        ),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover,
    ))

    fig.update_geos(
        fitbounds="locations",
        visible=False,
    )
    # 지도용 PT — margin을 0으로 덮어씀 (PT에 margin이 이미 있어서 별도 처리)
    map_layout = {k: v for k, v in PT.items() if k != "margin"}
    fig.update_layout(
        **map_layout,
        height=580,
        margin=dict(l=0, r=0, t=0, b=0),
        geo=dict(bgcolor=C["bg"]),
        clickmode="event+select",
    )
    return fig


# ---------------------------------------------------------------------------
# 탭 빌더
# ---------------------------------------------------------------------------

def build_tab_unsold(df):
    spike_df = df[df["급증여부"]].copy()
    n_spike = len(spike_df); n_total = len(df)
    bar_df = df.sort_values("미분양세대수", ascending=True)
    fig = go.Figure(go.Bar(
        x=bar_df["미분양세대수"], y=bar_df["지역구"], orientation="h",
        marker_color=[C["danger"] if v else C["accent2"] for v in bar_df["급증여부"]],
        text=bar_df["증감률"].apply(lambda x: f"{x:+.1f}%"),
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
    if df.empty: return html.P("데이터 없음", style={"color":C["muted"]})
    avg_all = int(df["평균거래가"].mean())
    top_gu  = df.loc[df["평균거래가"].idxmax(), "지역구"]
    total_d = int(df["거래건수"].sum())
    bar_df  = df.sort_values("평균거래가", ascending=True)
    fig_bar = go.Figure(go.Bar(
        x=bar_df["평균거래가"], y=bar_df["지역구"], orientation="h",
        marker=dict(color=bar_df["평균거래가"],
                    colorscale=[[0,C["accent2"]],[1,C["accent"]]]),
        text=bar_df["평균거래가"].apply(lambda x: f"{x:,.0f}만"),
        textposition="outside", textfont=dict(color=C["text"], size=10),
    ))
    fig_bar.update_layout(**PT, title="구·군별 평균 거래가 (최근 6개월)", height=560,
                          xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))
    fig_t = go.Figure()
    if not tdf.empty:
        m = tdf.groupby("월")["거래금액"].mean().reset_index()
        fig_t.add_trace(go.Scatter(x=m["월"], y=m["거래금액"], mode="lines+markers",
            line=dict(color=C["accent"],width=2), marker=dict(size=6,color=C["accent"]),
            fill="tozeroy", fillcolor="rgba(232,132,90,0.1)"))
    fig_t.update_layout(**PT, title="부산 전체 월별 평균 거래가 추이", height=260,
                        xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))
    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("부산 평균", f"{avg_all:,}만원", C["accent"]),
                            kpi("최고가 지역구", top_gu),
                            kpi("총 거래건수", f"{total_d:,}건", C["accent2"], "최근 6개월")]),
        dcc.Graph(figure=fig_t),
        dcc.Graph(figure=fig_bar),
    ])


def build_tab_permit(df):
    if df.empty: return html.P("데이터 없음", style={"color":C["muted"]})
    total_u = int(df["세대수"].sum())
    top_c   = df.groupby("시공사")["세대수"].sum().idxmax()
    sm = df.groupby("지역구")["세대수"].sum().reset_index().sort_values("세대수", ascending=True)
    fig = go.Figure(go.Bar(x=sm["세대수"], y=sm["지역구"], orientation="h",
        marker_color=C["accent2"],
        text=sm["세대수"].apply(lambda x: f"{x:,}세대"),
        textposition="outside", textfont=dict(color=C["text"], size=10)))
    fig.update_layout(**PT, title="구·군별 신규 착공·인허가 세대수", height=560,
                      xaxis=dict(gridcolor=C["border"]), yaxis=dict(gridcolor=C["border"]))
    cd = df.groupby("시공사")["세대수"].sum().reset_index()
    fig_pie = go.Figure(go.Pie(labels=cd["시공사"], values=cd["세대수"], hole=0.45,
        marker=dict(colors=[C["accent"],C["accent2"],C["ok"],C["danger"],C["muted"]]),
        textfont=dict(color=C["text"])))
    fig_pie.update_layout(**PT, title="시공사별 점유율", height=300)
    tdf = df.sort_values("인허가일", ascending=False).head(20).copy()
    tdf["인허가일"] = tdf["인허가일"].astype(str)
    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("총 세대수", f"{total_u:,}세대", C["accent2"]),
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


def build_tab_cap(df):
    n_a = len(df[df["상태"]=="지정"]) if not df.empty else 0
    n_r = len(df[df["상태"]=="해제"]) if not df.empty else 0
    dd  = df.copy()
    dd["지정일"] = dd["지정일"].astype(str); dd["해제일"] = dd["해제일"].astype(str)
    cond = [*TABLE_STYLE["style_data_conditional"],
            {"if":{"filter_query":'{상태} = "지정"',"column_id":"상태"},"color":C["danger"],"fontWeight":"700"},
            {"if":{"filter_query":'{상태} = "해제"',"column_id":"상태"},"color":C["ok"],"fontWeight":"700"}]
    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                 children=[kpi("현재 지정", n_a, C["danger"], "분양가상한제 적용 중"),
                            kpi("해제 완료", n_r, C["ok"])]),
        html.Div(style=CARD, children=[
            html.P("분양가상한제 지정·해제 이력",
                   style={"color":C["muted"],"fontSize":"12px","margin":"0 0 16px"}),
            dash_table.DataTable(data=dd.to_dict("records"),
                columns=[{"name":c,"id":c} for c in dd.columns],
                style_data_conditional=cond,
                **{k:v for k,v in TABLE_STYLE.items() if k!="style_data_conditional"})
            if not dd.empty else html.P("데이터 없음", style={"color":C["muted"]}),
        ]),
    ])


def build_tab_map(unsold_df, price_df, permit_df, cap_df):
    fig = build_map_figure(unsold_df, price_df)
    return html.Div([
        html.Div(style={"display":"flex","gap":"16px","marginBottom":"16px","flexWrap":"wrap"},
                 children=[kpi("부산 평균 거래가",
                               f"{int(price_df['평균거래가'].mean()):,}만원" if not price_df.empty else "-",
                               C["accent"]),
                            kpi("급증 구·군", n_spike, C["danger"], "미분양 30%↑"),
                            kpi("분양가상한제 지정",
                                len(cap_df[cap_df["상태"]=="지정"]) if not cap_df.empty else 0,
                                C["ok"])]),
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 380px","gap":"16px",
                        "alignItems":"start"}, children=[
            # 지도
            html.Div(style=CARD, children=[
                html.P("구·군 클릭 시 상세 정보를 확인할 수 있습니다.",
                       style={"color":C["muted"],"fontSize":"12px","margin":"0 0 12px"}),
                dcc.Graph(id="busan-map", figure=fig, config={"displayModeBar": False}),
            ]),
            # 사이드 패널 (클릭 시 채워짐)
            html.Div(id="map-side-panel", style={**CARD, "minHeight":"500px"}, children=[
                html.P("← 지도에서 구·군을 클릭하세요",
                       style={"color":C["muted"],"fontSize":"13px","marginTop":"40px",
                              "textAlign":"center"}),
            ]),
        ]),
    ])


# ---------------------------------------------------------------------------
# 앱 레이아웃
# ---------------------------------------------------------------------------
app = Dash(__name__, title="부산 분양·거래시장 통합 모니터",
           suppress_callback_exceptions=True)

TAB_S = {"backgroundColor":"transparent","color":C["muted"],"border":"none",
          "borderBottom":"2px solid transparent","padding":"12px 20px",
          "fontSize":"13px","fontWeight":"500"}
TAB_A = {**TAB_S, "color":C["text"], "borderBottom":f"2px solid {C['accent']}",
          "backgroundColor":"transparent"}

app.layout = html.Div(
    style={"backgroundColor":C["bg"],"minHeight":"100vh",
           "fontFamily":"Pretendard, Malgun Gothic, sans-serif","color":C["text"]},
    children=[
        # 헤더
        html.Div(style={"backgroundColor":C["surface"],"borderBottom":f"1px solid {C['border']}",
                        "padding":"0 32px","display":"flex","alignItems":"center",
                        "justifyContent":"space-between","height":"64px"}, children=[
            html.Div(style={"display":"flex","alignItems":"center","gap":"12px"}, children=[
                html.Span("●", style={"color":C["accent"],"fontSize":"10px"}),
                html.Span("부산 분양·거래시장 통합 모니터",
                          style={"fontWeight":"800","fontSize":"22px","letterSpacing":"-0.5px"}),
            ]),
            html.Div(style={"display":"flex","alignItems":"center","gap":"20px"}, children=[
                html.Span(f"갱신: {updated_at}", style={"color":C["muted"],"fontSize":"12px"}),
                html.Span(f"⚠ 급증 {n_spike}개구" if n_spike else "✓ 정상",
                    style={"color":C["danger"] if n_spike else C["ok"],
                           "fontSize":"12px","fontWeight":"600",
                           "backgroundColor":"rgba(224,92,92,0.12)" if n_spike else "rgba(76,175,130,0.12)",
                           "padding":"4px 12px","borderRadius":"20px"}),
            ]),
        ]),
        # 서브헤더
        html.Div(style={"padding":"10px 32px","backgroundColor":C["bg"],
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
                dcc.Tab(label="🚧  규제 모니터", value="tab-cap",    style=TAB_S, selected_style=TAB_A),
            ], style={"border":"none","backgroundColor":"transparent"},
               colors={"border":"transparent","primary":C["accent"],"background":C["surface"]}),
        ]),
        html.Div(id="tab-content", style={"padding":"24px 32px"}),
        html.Div(style={"padding":"14px 32px","borderTop":f"1px solid {C['border']}",
                        "marginTop":"24px"}, children=[
            html.P("매주 월요일 오전 7시 자동 갱신  ·  국토부 실거래가 API  ·  건축인허가 API  ·  전국 미분양현황 API",
                   style={"color":C["muted"],"fontSize":"11px","margin":"0"}),
        ]),
    ]
)

# ---------------------------------------------------------------------------
# 콜백
# ---------------------------------------------------------------------------

@app.callback(Output("tab-content", "children"), Input("main-tabs", "value"))
def render_tab(tab):
    if tab == "tab-map":    return build_tab_map(unsold_df, price_df, permit_df, cap_df)
    if tab == "tab-unsold": return build_tab_unsold(unsold_df)
    if tab == "tab-price":  return build_tab_price(price_df, trend_df)
    if tab == "tab-permit": return build_tab_permit(permit_df)
    if tab == "tab-cap":    return build_tab_cap(cap_df)
    return html.Div()


@app.callback(
    Output("map-side-panel", "children"),
    Input("busan-map", "clickData"),
    prevent_initial_call=True,
)
def map_click_panel(click_data):
    """지도 구·군 클릭 시 사이드패널 업데이트"""
    if not click_data:
        return no_update
    try:
        gu_name = click_data["points"][0]["location"]
    except (KeyError, IndexError):
        return no_update

    # 데이터 조회
    u_row = unsold_df[unsold_df["지역구"] == gu_name]
    p_row = price_df[price_df["지역구"] == gu_name]
    pm_rows = permit_df[permit_df["지역구"] == gu_name].sort_values("인허가일", ascending=False).head(5).copy()
    pm_rows["인허가일"] = pm_rows["인허가일"].astype(str)
    c_rows = cap_df[cap_df["지역구"] == gu_name]

    unsold_count  = int(u_row["미분양세대수"].values[0]) if not u_row.empty else "-"
    change_rate   = u_row["증감률"].values[0] if not u_row.empty else None
    avg_price     = int(p_row["평균거래가"].values[0]) if not p_row.empty else None
    cap_status    = c_rows["상태"].values[0] if not c_rows.empty else "해당 없음"

    spike = (change_rate or 0) >= UNSOLD_SPIKE_THRESHOLD_PCT

    def stat_row(label, value, color=None):
        return html.Div(style={"display":"flex","justifyContent":"space-between",
                                "padding":"8px 0","borderBottom":f"1px solid {C['border']}"}, children=[
            html.Span(label, style={"color":C["muted"],"fontSize":"12px"}),
            html.Span(str(value), style={"color": color or C["text"],
                                          "fontSize":"13px","fontWeight":"600"}),
        ])

    return html.Div([
        html.Div(style={"display":"flex","alignItems":"center","justifyContent":"space-between",
                        "marginBottom":"20px"}, children=[
            html.H3(gu_name, style={"margin":"0","fontSize":"20px","fontWeight":"700"}),
            html.Span("⚠ 급증" if spike else "✓ 정상",
                style={"color":C["danger"] if spike else C["ok"],"fontSize":"11px",
                       "fontWeight":"700","backgroundColor":"rgba(224,92,92,0.12)" if spike else "rgba(76,175,130,0.12)",
                       "padding":"3px 10px","borderRadius":"12px"}),
        ]),

        # 미분양
        html.P("미분양 현황", style={"color":C["muted"],"fontSize":"11px",
                                    "letterSpacing":"0.1em","margin":"0 0 4px",
                                    "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"16px","padding":"12px 16px"}, children=[
            stat_row("미분양 세대수", f"{unsold_count}세대"),
            stat_row("전월 대비",
                     f"{change_rate:+.1f}%" if change_rate is not None else "-",
                     C["danger"] if spike else C["ok"]),
        ]),

        # 거래가
        html.P("실거래가", style={"color":C["muted"],"fontSize":"11px",
                                  "letterSpacing":"0.1em","margin":"0 0 4px",
                                  "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"16px","padding":"12px 16px"}, children=[
            stat_row("최근 6개월 평균",
                     f"{avg_price:,}만원" if avg_price else "-", C["accent"]),
        ]),

        # 규제
        html.P("규제 현황", style={"color":C["muted"],"fontSize":"11px",
                                   "letterSpacing":"0.1em","margin":"0 0 4px",
                                   "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"16px","padding":"12px 16px"}, children=[
            stat_row("분양가상한제",
                     cap_status,
                     C["danger"] if cap_status == "지정" else C["ok"]),
        ]),

        # 인허가
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