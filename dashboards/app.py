"""
dashboards/app.py
부산 분양·거래시장 통합 모니터 (다크모드 기본 + V-World 지도)

실행: python -m dashboards.app → http://127.0.0.1:8050

[수정 이력]
- 탭 전환 시 테마가 임의로 바뀌던 버그 수정.
  기존에는 theme-store와 active-tab-store 둘 다 하나의 콜백(render_page)에서
  page-content 전체(헤더 + 테마 토글 버튼 포함)를 다시 그렸기 때문에,
  탭만 클릭해도 theme-toggle-btn이 새로 마운트되어 테마 토글 콜백이
  의도치 않게 다시 트리거되는 문제가 있었음.
  → page-content(헤더/탭바 등 '셸')는 theme-store 변경시에만 재생성하고,
    tab-content(탭 본문)만 별도 콜백으로 분리하여 active-tab-store 변경시에만
    갱신하도록 구조 변경. 테마는 오직 테마 토글 버튼 클릭으로만 바뀜.
- 테마 토글이 두 번째 클릭부터 작동하지 않던 버그 수정.
  위 수정 이후에도 theme-toggle-btn 자체가 build_shell() 안에서 만들어졌기 때문에,
  theme-store가 바뀔 때마다 render_shell이 버튼을 n_clicks=0으로 다시 마운트했음.
  Dash는 이 프로퍼티 변화(예: 1 → 0)도 진짜 클릭처럼 감지해 toggle_theme를 재발동시켜
  테마가 즉시 원래대로 되돌아갔음(짝수 번째 클릭마다 고정되는 것처럼 보임).
  → theme-toggle-btn을 app.layout 최상위에 고정 배치해 다시는 재마운트되지 않도록 하고,
    라벨/스타일만 별도 콜백(sync_toggle_button)이 theme-store를 보고 갱신하도록 분리.
    (참고: 이후 요청으로 버튼을 헤더 인라인 배치로 되돌리면서 sync_toggle_button은
    제거됨 — 아래 항목 참고.)
- 헤더 인라인 배치로 되돌린 뒤 페이지가 흰 화면만 뜨던 버그 수정.
  theme-toggle-btn을 다시 build_shell() 안(헤더의 "갱신: 날짜" 옆)으로 옮기면서,
  sync_toggle_button 콜백(Output: theme-toggle-btn.children/style, Input: theme-store)은
  지우지 않고 그대로 남겨뒀음. 그 결과 theme-toggle-btn이라는 같은 id를 놓고 두 콜백이
  동시에 소유권을 다투게 됨 — 하나는 page-content.children을 통해 그 버튼을 "포함하는"
  서브트리 전체를 새로 만들고(render_shell), 다른 하나는 그 버튼의 개별 prop을 직접
  갱신(sync_toggle_button)하려 함. 페이지 최초 로드 시 둘 다 theme-store.data를 Input으로
  가지므로 동시에 발동하는데, 이 시점에는 theme-toggle-btn이 아직 어디에도 렌더링되지
  않은 상태라 sync_toggle_button이 대상 DOM 노드를 찾지 못해 dash-renderer가 처리하지
  못하고 클라이언트에서 렌더링이 통째로 죽어버림 → 흰 화면.
  → sync_toggle_button 콜백을 완전히 제거. build_shell()이 버튼을 (재)생성할 때마다
    get_toggle_button_label()/get_toggle_button_style()로 이미 테마에 맞는 라벨·색을
    직접 채워 넣으므로 별도 콜백 없이도 항상 최신 상태이며, id 소유권 충돌도 사라짐.
    (참고: 이후 요청으로 theme-toggle-btn을 다시 build_shell() 안(헤더 인라인)으로
    옮기게 됨 — 아래 두 항목 참고.)
- (재발) build_shell()이 theme-store 변경마다 버�른을 n_clicks=0으로 재생성해
  두 번째 클릭부터 테마가 고정되는 버그가 다시 발생.
  이를 theme-click-store(dcc.Store)로 클릭 횟수를 별도 집계해 우회하려 시도했으나,
  집계 콜백(record_click)의 Input이 여전히 theme-toggle-btn.n_clicks였기 때문에
  n_clicks가 리셋될 때도 "클릭"으로 오인되어 카운터가 함께 튀는 것은 그대로였음.
  결과적으로 클릭 1번 = toggle_theme 2번 연달아 발동 = 테마가 원래대로 즉시 복귀
  (겉보기엔 "버튼이 아예 안 먹는다"로 증상만 바뀌었을 뿐 근본 원인은 그대로였음).
  → theme-click-store/record_click 제거.
- theme-toggle-btn을 app.layout 최상위에 position: fixed로 다시 고정 배치해
  build_shell()이 이 버튼을 절대 만들지 않도록 함(재생성 자체가 없으니 n_clicks도
  리셋될 일이 없음). toggle_theme는 다시 Input: theme-toggle-btn.n_clicks로 직접
  반응. 라벨/스타일은 update_toggle_button_display 콜백 하나가 Input: theme-store.data
  를 보고 theme-toggle-btn.children/style만 갱신 — page-content 안쪽에는 이 id를 가진
  다른 엘리먼트가 전혀 없으므로(= build_shell이 만들지 않으므로) 예전처럼 두 콜백이
  같은 id를 놓고 충돌해 흰 화면이 뜨는 문제도 재발하지 않음.
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

# theme-toggle-btn은 헤더 우측 상단에 고정 배치되므로, 헤더 콘텐츠가 버튼과
# 겹치지 않도록 헤더 우측 padding으로 이만큼 여백을 확보해둔다.
THEME_BTN_CLEARANCE = "150px"


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
                       style={"color":colors["muted"],"fontSize":"17px","margin":"0 0 10px"}),
                html.Iframe(
                    id="vworld-iframe",
                    srcDoc=html_content,
                    style={"width":"100%","height":"560px","border":"none","borderRadius":"8px"},
                ),
            ]),
            html.Div(id="map-side-panel", style={**CARD, "minHeight":"560px"}, children=[
                html.P("← 지도에서 구·군을 클릭하세요",
                       style={"color":colors["muted"],"fontSize":"18px",
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
        textposition="outside", textfont=dict(color=colors["text"], size=15),
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
                   style={"color":colors["danger"],"fontWeight":"600","margin":"0 0 16px","fontSize":"18px"}),
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
        textposition="outside", textfont=dict(color=colors["text"], size=14),
    ))
    fig_bar.update_layout(**PT, title="구·군별 평균 거래가 (최근 3개월)", height=560,
                          xaxis=dict(gridcolor=colors["border"]), yaxis=dict(gridcolor=colors["border"]))

    fig_t = go.Figure()
    if not tdf.empty:
        m = tdf.groupby("월")["거래금액"].mean().reset_index()
        fig_t.add_trace(go.Scatter(
            x=m["월"], y=m["거래금액"], mode="lines+markers",
            line=dict(color=colors["accent"], width=2),
            marker=dict(size=12, color=colors["accent"]),
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

        cd = df.groupby("시공사")["세대수"].sum().reset_index()
        fig_pie = go.Figure(go.Pie(
            labels=cd["시공사"], values=cd["세대수"], hole=0.45,
            marker=dict(colors=[colors["accent"],colors["accent2"],colors["ok"],
                                 colors["danger"],colors["muted"]]),
            textfont=dict(color=colors["text"]),
            textposition="inside", textinfo="percent",
        ))
        fig_pie.update_layout(
            **{**PT, "margin": dict(l=0, r=220, t=40, b=0)},
            title="시공사별 세대수 점유율", height=480,
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="middle", y=0.5,
                xanchor="left", x=1.02,
                font=dict(size=15),
                traceorder="normal",
            ),
        )

        tdf = df.sort_values("인허가일", ascending=False).head(20).copy()
        tdf["인허가일"] = tdf["인허가일"].astype(str)

        summary_block = html.Div([
            html.Div(style={"display":"flex","gap":"16px","marginBottom":"24px","flexWrap":"wrap"},
                     children=[kpi(colors, "총 인허가 세대수", f"{total_u:,}세대", colors["accent"]),
                                kpi(colors, "최다 시공사", top_c),
                                kpi(colors, "모니터링 건수", f"{len(df)}건", colors["muted"])]),
            # 막대차트(전체 폭) → 도넛차트(전체 폭, 범례는 차트 오른쪽 세로 배치) 순으로 세로 스택.
            # 기존 2단 좌우 배치(2fr/1fr)는 도넛 범례 텍스트가 잘리는 문제가 있어 변경함.
            dcc.Graph(figure=fig),
            html.Div(style={"marginTop":"16px"}, children=[dcc.Graph(figure=fig_pie)]),
            html.Div(style={**CARD,"marginTop":"24px"}, children=[
                html.P("최근 인허가 내역 (상위 20건)",
                       style={"color":colors["muted"],"fontSize":"17px","margin":"0 0 12px"}),
                dash_table.DataTable(data=tdf.to_dict("records"),
                    columns=[{"name":c,"id":c} for c in tdf.columns], **TABLE_STYLE),
            ]),
        ])

    return html.Div([
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
                    options=[{"label": v, "value": k} for k, v in BUSAN_DISTRICT_CODES.items()],
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


def build_tab_content(tab, colors):
    if tab == "tab-map":    return build_tab_map(colors)
    if tab == "tab-unsold": return build_tab_unsold(colors, unsold_df)
    if tab == "tab-price":  return build_tab_price(colors, price_df, trend_df)
    if tab == "tab-permit": return build_tab_permit(colors, permit_df)
    return html.Div()

# ---------------------------------------------------------------------------
# 셸(헤더/탭바) — 테마가 바뀔 때만 재생성됨
# ---------------------------------------------------------------------------

def build_shell(theme, active_tab):
    """
    헤더 + 서브헤더 + 탭바 + tab-content 컨테이너(초기 콘텐츠 포함)를 반환.
    이 함수는 theme-store 변경시에만 호출되어야 함 (탭 전환으로는 호출 금지).

    theme-toggle-btn은 여기서 절대 만들지 않는다 — app.layout 최상위에 고정
    배치되어 있고, 이 함수는 theme-store가 바뀔 때마다(render_shell을 통해)
    반복 호출되므로 버튼을 여기서 만들면 매번 n_clicks가 리셋되어 두 번째
    클릭부터 테마가 고정되는 버그가 재발한다. 라벨/스타일은
    update_toggle_button_display 콜백이 별도로 갱신한다.
    """
    colors = get_colors(theme)

    TAB_S = {"backgroundColor":"transparent","color":colors["muted"],"border":"none",
              "borderBottom":"2px solid transparent","padding":"12px 20px",
              "fontSize":"21px","fontWeight":"500"}
    TAB_A = {**TAB_S,"color":colors["accent"],"borderBottom":f"2px solid {colors['accent']}",
              "backgroundColor":"transparent"}

    return html.Div(
        style={"backgroundColor":colors["bg"],"minHeight":"100vh",
               "fontFamily":"Malgun Gothic, Apple SD Gothic Neo, sans-serif",
               "color":colors["text"]},
        children=[
            # 헤더 — 우측 끝은 theme-toggle-btn(고정 배치, app.layout 최상위)이
            # 겹치지 않도록 여백(THEME_BTN_CLEARANCE)만큼 비워둔다.
            html.Div(style={"backgroundColor":colors["surface"],
                            "borderBottom":f"1px solid {colors['border']}",
                            "padding":f"0 {THEME_BTN_CLEARANCE} 0 32px",
                            "display":"flex","alignItems":"center",
                            "justifyContent":"space-between","height":"64px",
                            "boxShadow":"0 1px 4px rgba(0,0,0,0.06)"}, children=[
                html.Div(style={"display":"flex","alignItems":"center","gap":"12px"}, children=[
                    html.Span("●", style={"color":colors["accent"],"fontSize":"14px"}),
                    html.Span("부산 분양·거래시장 통합 모니터",
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

            # 탭 콘텐츠 — 별도 콜백(render_tab_content)이 이 컨테이너의 children만 갱신함.
            # 초기 렌더링(테마 변경 직후 포함)에는 여기서 바로 콘텐츠를 채워줌.
            html.Div(id="tab-content", style={"padding":"24px 32px"},
                     children=build_tab_content(active_tab, colors)),

            # 푸터
            html.Div(style={"padding":"14px 32px","borderTop":f"1px solid {colors['border']}",
                            "marginTop":"24px","backgroundColor":colors["surface"]}, children=[
                html.P("매주 월요일 오전 7시 자동 갱신  ·  국토부 실거래가 API  ·  청약홈 API  ·  부산광역시 미분양현황 API",
                       style={"color":colors["muted"],"fontSize":"15px","margin":"0"}),
            ]),
        ]
    )

def get_toggle_button_style(colors: dict) -> dict:
    return {
        "position": "fixed",
        "top": "18px",
        "right": "32px",
        "zIndex": 1000,
        "color": colors["text"],
        "fontSize": "17px",
        "fontWeight": "600",
        "backgroundColor": colors["surface2"],
        "border": f"1px solid {colors['border']}",
        "padding": "4px 14px",
        "borderRadius": "20px",
        "cursor": "pointer",
    }


def get_toggle_button_label(theme: str) -> str:
    return "☀️ 라이트" if theme == "dark" else "🌙 다크"


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
app = Dash(__name__, title="부산 분양·거래시장 통합 모니터",
           suppress_callback_exceptions=True)

app.layout = html.Div([
    dcc.Store(id="theme-store", data=DEFAULT_THEME),
    dcc.Store(id="active-tab-store", data="tab-map"),
    # theme-toggle-btn: page-content 바깥, app.layout 최상위에 고정 배치.
    # build_shell()은 이 id를 가진 엘리먼트를 절대 만들지 않으므로, page-content가
    # 다시 그려져도 이 버튼은 재마운트되지 않아 n_clicks가 리셋되지 않는다.
    # 라벨·스타일은 update_toggle_button_display 콜백이 theme-store를 보고 갱신한다.
    html.Button(
        get_toggle_button_label(DEFAULT_THEME),
        id="theme-toggle-btn",
        n_clicks=0,
        style=get_toggle_button_style(get_colors(DEFAULT_THEME)),
    ),
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
    # 테마는 오직 이 버튼 클릭으로만 바뀐다.
    return "light" if current_theme == "dark" else "dark"


@app.callback(
    Output("theme-toggle-btn", "children"),
    Output("theme-toggle-btn", "style"),
    Input("theme-store", "data"),
)
def update_toggle_button_display(theme):
    # 버튼의 라벨·색상만 갱신한다. build_shell()이 이 id를 가진 엘리먼트를
    # 절대 만들지 않으므로 다른 콜백과 소유권이 겹치지 않는다.
    colors = get_colors(theme)
    return get_toggle_button_label(theme), get_toggle_button_style(colors)


@app.callback(Output("active-tab-store", "data"), Input("main-tabs", "value"))
def sync_active_tab(value):
    return value


@app.callback(
    Output("page-content", "children"),
    Input("theme-store", "data"),
    State("active-tab-store", "data"),
)
def render_shell(theme, active_tab):
    """
    theme-store가 바뀔 때만(=테마 토글 버튼을 눌렀을 때만, 그리고 페이지
    최초 로드 시) 헤더/탭바/테마 토글 버튼을 포함한 셸 전체를 재생성한다.
    active_tab은 State로만 받으므로 탭 전환 자체는 이 콜백을 트리거하지 않는다.
    """
    return build_shell(theme, active_tab)


@app.callback(
    Output("tab-content", "children"),
    Input("active-tab-store", "data"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def render_tab_content(active_tab, theme):
    """
    탭 전환시에는 이 콜백만 발동되어 tab-content 영역만 다시 그린다.
    theme은 State로만 받아 현재 색상 테마를 유지하되, 헤더/토글버튼은
    건드리지 않으므로 테마가 바뀌는 부작용이 없다.
    """
    colors = get_colors(theme)
    return build_tab_content(active_tab, colors)


@app.callback(
    Output("map-side-panel", "children"),
    Input("clicked-gu-store", "data"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def map_side_panel(gu_name, theme):
    colors = get_colors(theme)
    CARD = get_card_style(colors)
    TABLE_STYLE = get_table_style(colors)

    if not gu_name:
        return html.P("← 지도에서 구·군을 클릭하세요",
                      style={"color":colors["muted"],"fontSize":"18px",
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
                html.Span(label, style={"color":colors["muted"],"fontSize":"17px"}),
                html.Span(str(value), style={"color":color or colors["text"],
                                              "fontSize":"18px","fontWeight":"600"}),
            ])

    return html.Div([
        html.Div(style={"display":"flex","alignItems":"center",
                        "justifyContent":"space-between","marginBottom":"20px"}, children=[
            html.H3(gu_name, style={"margin":"0","fontSize":"14px",
                                     "fontWeight":"700","color":colors["text"]}),
            html.Span("⚠ 급증" if spike else "✓ 정상",
                style={"color":colors["danger"] if spike else colors["ok"],"fontSize":"15px",
                       "fontWeight":"700",
                       "backgroundColor":_hex_to_rgba(
                           colors["danger"] if spike else colors["ok"], 0.08),
                       "padding":"3px 10px","borderRadius":"12px"}),
        ]),
        html.P("미분양 현황", style={"color":colors["muted"],"fontSize":"15px",
                                    "letterSpacing":"0.1em","margin":"0 0 4px",
                                    "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("미분양 세대수", f"{unsold_count}세대"),
            stat_row("전월 대비",
                     f"{change_rate:+.1f}%" if change_rate is not None else "-",
                     colors["danger"] if spike else colors["ok"]),
        ]),
        html.P("실거래가", style={"color":colors["muted"],"fontSize":"15px",
                                  "letterSpacing":"0.1em","margin":"0 0 4px",
                                  "textTransform":"uppercase"}),
        html.Div(style={**CARD,"marginBottom":"14px","padding":"12px 16px"}, children=[
            stat_row("최근 3개월 평균",
                     f"{avg_price:,}만원" if avg_price else "-", colors["accent"]),
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
    app.run(debug=True, port=1111)