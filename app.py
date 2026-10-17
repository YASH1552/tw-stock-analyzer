"""台股分析工具：輸入股票代號，顯示買點評分、趨勢、歷史機率與相關新聞。

啟動方式：點兩下「啟動.bat」，或執行 streamlit run app.py
"""
from datetime import datetime
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import analysis as A
import data

# 台股習慣：紅漲綠跌
UP, DOWN, GOLD = "#ff5a5f", "#22c38e", "#f0b429"
PANEL, GRID, MUTED, TEXT = "#111722", "#1f2836", "#8b97a8", "#e6edf3"
MA_COLORS = {"MA20": "#c98500", "MA60": "#3987e5", "MA240": "#9085e9"}
TONE_COLOR = {"bull": UP, "neutral": GOLD, "bear": DOWN}
HORIZON_LABEL = {5: "約 1 週後", 20: "約 1 個月後", 60: "約 3 個月後"}

st.set_page_config(page_title="台股分析終端", page_icon="📈", layout="wide")


def html(s: str) -> None:
    """輸出 HTML（壓成一行，避免 Markdown 把縮排當成程式碼區塊）。"""
    st.markdown(" ".join(line.strip() for line in s.splitlines()), unsafe_allow_html=True)


html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700;900&display=swap');
html, body, [class*="css"], .stMarkdown, .stTextInput input, button { font-family: 'Noto Sans TC', sans-serif; }
.block-container { padding-top: 1.2rem; max-width: 1400px; }
header[data-testid="stHeader"] { background: transparent; }
.mono { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
.brand { display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1f2836; padding-bottom:10px; margin-bottom:14px; }
.brand .logo { font-weight:900; letter-spacing:.08em; font-size:1.05rem; color:#e6edf3; }
.brand .logo span { color:#f0b429; }
.brand .meta { color:#8b97a8; font-size:.8rem; }
.card { background:#111722; border:1px solid #1f2836; border-radius:12px; padding:18px 20px; height:100%; }
.card h4 { margin:0 0 10px 0; font-size:.78rem; letter-spacing:.12em; color:#8b97a8; font-weight:600; text-transform:uppercase; }
.tag { display:inline-block; padding:2px 9px; border-radius:999px; font-size:.72rem; border:1px solid #2a3547; color:#aab6c6; margin-right:6px; }
.code { background:#f0b429; color:#0b0f17; font-weight:800; padding:2px 10px; border-radius:6px; font-size:.85rem; margin-right:10px; }
.name { font-size:1.7rem; font-weight:900; color:#e6edf3; }
.price { font-size:2.6rem; font-weight:700; line-height:1.1; }
.chg { font-size:1rem; font-weight:600; margin-left:10px; }
.stats { display:grid; grid-template-columns:repeat(4, 1fr); gap:10px 18px; margin-top:14px; }
.stats div { font-size:.75rem; color:#8b97a8; }
.stats b { display:block; font-size:.95rem; color:#e6edf3; font-weight:600; }
.verdict { font-size:1.5rem; font-weight:900; margin:4px 0 6px 0; }
.summary { color:#c9d3df; font-size:.92rem; line-height:1.6; margin-bottom:12px; }
.list { margin:0; padding:0; list-style:none; }
.list li { font-size:.86rem; color:#c9d3df; padding:4px 0; line-height:1.5; border-bottom:1px dashed #1c2533; }
.list li:last-child { border-bottom:none; }
.ic { display:inline-block; width:18px; font-weight:700; }
.comp { display:flex; align-items:center; gap:10px; font-size:.8rem; color:#aab6c6; margin:5px 0; }
.comp .bar { flex:1; height:6px; background:#1f2836; border-radius:3px; overflow:hidden; }
.comp .bar i { display:block; height:100%; border-radius:3px; }
.comp .lbl { width:84px; } .comp .v { width:30px; text-align:right; }
.kpi .label { font-size:.75rem; color:#8b97a8; letter-spacing:.06em; }
.kpi .value { font-size:1.45rem; font-weight:700; margin-top:4px; color:#e6edf3; }
.kpi .sub { font-size:.78rem; color:#8b97a8; margin-top:2px; }
.news { display:block; padding:12px 14px; border:1px solid #1f2836; border-radius:10px; margin-bottom:8px; background:#111722; text-decoration:none !important; }
.news:hover { border-color:#f0b429; }
.news .t { color:#e6edf3; font-size:.95rem; font-weight:500; }
.news .m { color:#8b97a8; font-size:.75rem; margin-top:6px; display:flex; justify-content:space-between; align-items:center; gap:8px; }
.news .open { color:#0b0f17; background:#f0b429; font-weight:700; padding:2px 10px; border-radius:6px; white-space:nowrap; }
.news:hover .open { background:#ffd166; }
.pill { display:inline-block; font-size:.7rem; font-weight:700; padding:1px 8px; border-radius:999px; margin-right:8px; }
.sentbar { display:flex; height:10px; border-radius:5px; overflow:hidden; margin:8px 0 4px 0; gap:2px; }
.disclaimer { color:#6b7789; font-size:.75rem; text-align:center; margin-top:24px; }
div[data-testid="stForm"] { border:1px solid #1f2836; background:#111722; border-radius:12px; }
button[data-baseweb="tab"] { font-size:.9rem; }
</style>
""")

html(f"""
<div class="brand">
  <div class="logo">◆ TW EQUITY <span>TERMINAL</span>　<span style="color:#8b97a8;font-weight:500;letter-spacing:0">台股分析終端</span></div>
  <div class="meta mono">{datetime.now():%Y-%m-%d %H:%M}</div>
</div>
""")

def theme(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(height=height, paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=MUTED, size=12),
                      margin=dict(l=12, r=12, t=36, b=12), hovermode="x unified",
                      hoverlabel=dict(bgcolor="#1a2230", bordercolor="#2a3547", font_color=TEXT),
                      legend=dict(orientation="h", y=1.06, x=0, bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False, side="right")
    return fig


def breaks(view: pd.DataFrame) -> list:
    """隱藏週末與國定假日等沒有交易的日子，讓 K 線連續。"""
    holidays = pd.bdate_range(view.index[0], view.index[-1]).difference(view.index)
    return [dict(bounds=["sat", "mon"]), dict(values=holidays.strftime("%Y-%m-%d").tolist())]


RANK_PCT_COLS = ["今日漲跌", "20日漲跌", "60日漲跌", "120日漲跌", "20日上漲機率", "平常上漲機率", "距停損"]


def rank_table(df: pd.DataFrame):
    """掃描／同業表格：百分比欄位統一顯示一位小數。回傳 (data, column_config=...) 給 st.dataframe。"""
    out = df.copy()
    for c in RANK_PCT_COLS:
        if c in out:
            out[c] = out[c] * 100
    cfg = {"評分": st.column_config.ProgressColumn("評分", min_value=0, max_value=100, format="%d"),
           "收盤": st.column_config.NumberColumn(format="%.2f"),
           **{c: st.column_config.NumberColumn(format="%.1f%%") for c in RANK_PCT_COLS}}
    return out, cfg


def pct_color(v: float) -> str:
    return UP if v > 0 else DOWN if v < 0 else TEXT


# 從選股掃描點選某檔股票時，先切回個股分析（必須在建立元件之前設定）
if st.session_state.get("goto"):
    code = st.session_state.pop("goto")
    st.session_state.update(mode="個股分析", query=code, query_box=code)

# ---------- 大盤 ----------
try:
    market = A.market_state(data.market_index())
except data.DataError:
    market = None
mcol, scol = st.columns([3, 2], vertical_alignment="center")
with mcol:
    if market:
        mc = pct_color(market.change)
        tc = UP if market.label in ("強勢多頭", "偏多") else DOWN if market.label in ("偏空", "強勢空頭") else GOLD
        html(f"""<div class="card" style="padding:10px 16px;display:flex;gap:22px;align-items:center;flex-wrap:wrap">
<span style="color:#8b97a8;font-size:.78rem;letter-spacing:.1em">加權指數 TAIEX</span>
<span class="mono" style="font-size:1.15rem;font-weight:700;color:{mc}">{market.close:,.2f}</span>
<span class="mono" style="color:{mc}">{market.change:+.2%}</span>
<span style="font-size:.85rem">大盤趨勢 <b style="color:{tc}">{market.label}</b></span>
<span class="mono" style="font-size:.8rem;color:#8b97a8">近 20 日 {market.ret20:+.1%}</span></div>""")
with scol:
    st.session_state.setdefault("mode", "個股分析")
    mode = st.segmented_control("模式", ["個股分析", "選股掃描"], key="mode", label_visibility="collapsed")
mode = mode or "個股分析"

if mode == "選股掃描":
    import screener

    html('<div class="card" style="margin-top:12px"><h4>選股掃描 STOCK SCREENER</h4>'
         '<div style="color:#8b97a8;font-size:.85rem">依成交金額挑出最熱門的股票，用和個股分析相同的價格面規則計算買點評分並排序。'
         '只看股價資料（不含法人、本益比、營收、融資），第一次掃描每檔約需 2 次免費查詢，之後當天會讀快取。</div></div>')
    c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
    n = c1.select_slider("掃描範圍（成交金額前幾名）", [20, 40, 60, 80, 100], value=40)
    try:
        uni = data.universe()
    except data.DataError as e:
        st.error(str(e))
        st.stop()
    inds = ["全部產業"] + sorted(uni["industry"].dropna().unique().tolist())
    ind = c2.selectbox("產業", inds)
    run = c3.button("開始掃描", type="primary", width="stretch")
    pool = uni if ind == "全部產業" else uni[uni["industry"] == ind]
    pool = pool.head(n)
    if run:
        bar = st.progress(0.0, text="準備中…")
        names = dict(zip(uni["stock_id"], uni["name"]))
        res = screener.scan(pool["stock_id"].tolist(), names, market,
                            progress=lambda i, t, s: bar.progress(i / t, text=f"掃描中 {i}/{t}：{s} {names.get(s, '')}"))
        bar.empty()
        if len(res) and len(res) < len(pool):
            st.warning(f"只完成 {len(res)} / {len(pool)} 檔，可能是免費查詢額度用完，請一小時後再試。")
        st.session_state["scan_result"] = res
    res = st.session_state.get("scan_result")
    if res is not None and len(res):
        st.caption("點選任一列即可切換到該股票的完整分析。")
        tbl, cfg = rank_table(res)
        ev = st.dataframe(tbl, column_config=cfg, hide_index=True, width="stretch", height=min(38 * len(res) + 40, 760),
                          on_select="rerun", selection_mode="single-row", key="scan_table")
        sel = ev.selection.rows if ev and ev.selection else []
        if sel:
            st.session_state["goto"] = res.iloc[sel[0]]["代號"]
            st.rerun()
    elif res is not None:
        st.info("沒有掃描結果。")
    html('<div class="disclaimer">本工具僅為技術與統計分析，不構成任何投資建議。投資前請自行判斷並承擔風險。</div>')
    st.stop()

with st.form("search_form"):
    col1, col2 = st.columns([5, 1])
    # 用固定的 key 綁定輸入框；不能傳會變動的 value，否則每換一次股票，輸入框就被當成新元件而吃掉輸入內容
    col1.text_input("股票代號或名稱", key="query_box",
                    placeholder="輸入代號或名稱，例如 2330 或 台積電", label_visibility="collapsed")
    submitted = col2.form_submit_button("開始分析", width="stretch", type="primary")
if submitted:
    st.session_state["query"] = st.session_state["query_box"].strip()
query = st.session_state.get("query", "")

if not query:
    html("""<div class="card" style="text-align:center;padding:48px">
    <div style="font-size:1.3rem;font-weight:700;color:#e6edf3">輸入股票代號開始分析</div>
    <div style="color:#8b97a8;margin-top:8px">買點評分 · 趨勢結構 · 歷史機率 · 籌碼評價 · 相關新聞</div></div>""")
    st.stop()

try:
    matches = data.find_stock(query)
except data.DataError as e:
    st.error(str(e))
    st.stop()
if matches.empty:
    st.warning(f"找不到「{query}」，請確認代號或名稱。")
    st.stop()
if len(matches) > 1:
    opts = [f"{r.stock_id} {r.stock_name}" for r in matches.itertuples()]
    pick = st.selectbox(f"找到 {len(matches)} 檔符合的股票，請選擇：", opts)
    info = matches.iloc[opts.index(pick)]
else:
    info = matches.iloc[0]
sid = info.stock_id

try:
    with st.spinner(f"正在分析 {sid} {info.stock_name}…"):
        price = data.price_history(sid)
        inst = data.institutional(sid)
        val = data.valuation(sid)
except data.DataError as e:
    st.error(str(e))
    st.stop()
try:
    news = A.tag_news(data.news(sid, info.stock_name))
except data.DataError:
    news = pd.DataFrame(columns=["date", "title", "source", "link", "tone"])

if len(price) < 80:
    st.warning("這檔股票的交易資料太少（不到 80 天），無法分析。")
    st.stop()

try:
    rev = data.month_revenue(sid)
except data.DataError:
    rev = None
try:
    mg = data.margin(sid)
except data.DataError:
    mg = None

d = A.add_indicators(price)
trend = A.assess_trend(d)
levels = A.key_levels(d)
items = A.checklist(d, inst, val, rev, mg)
sim = A.similar_situations(d)
rating = A.buy_rating(d, trend, items, sim, levels, market)
last, prev = d.iloc[-1], d.iloc[-2]
s20 = next((s for s in sim.stats if s.horizon == 20), None) if sim else None


# ---------- 個股標題 ----------
chg = last.close - prev.close
chg_color = UP if chg > 0 else DOWN if chg < 0 else TEXT
arrow = "▲" if chg > 0 else "▼" if chg < 0 else "■"
market = {"twse": "上市", "tpex": "上櫃"}.get(info.type, info.type)
y1 = d.iloc[-250:]
pe = val["PER"].iloc[-1] if val is not None and not val.empty and val["PER"].iloc[-1] > 0 else None
dy = val["dividend_yield"].iloc[-1] if val is not None and not val.empty else None

left, right = st.columns([1.05, 1], gap="medium")
with left:
    html(f"""
<div class="card">
  <div><span class="code mono">{sid}</span><span class="name">{escape(info.stock_name)}</span></div>
  <div style="margin-top:8px"><span class="tag">{market}</span><span class="tag">{escape(info.industry_category)}</span><span class="tag mono">資料日期 {d.index[-1]:%Y-%m-%d}</span></div>
  <div style="margin-top:16px"><span class="price mono" style="color:{chg_color}">{last.close:,.2f}</span>
  <span class="chg mono" style="color:{chg_color}">{arrow} {abs(chg):,.2f}（{chg / prev.close:+.2%}）</span></div>
  <div class="stats mono">
    <div>開盤<b>{last.open:,.2f}</b></div><div>最高<b>{last.high:,.2f}</b></div>
    <div>最低<b>{last.low:,.2f}</b></div><div>成交量<b>{last.volume:,.0f} 張</b></div>
    <div>52 週高<b>{y1.high.max():,.2f}</b></div><div>52 週低<b>{y1.low.min():,.2f}</b></div>
    <div>本益比<b>{f'{pe:.1f} 倍' if pe else '—'}</b></div><div>殖利率<b>{f'{dy:.2f}%' if dy and dy > 0 else '—'}</b></div>
  </div>
</div>""")

    # 四個重點指標
    k = st.columns(4)
    trend_color = UP if trend.label in ("強勢多頭", "偏多") else DOWN if trend.label in ("偏空", "強勢空頭") else GOLD
    kpis = [
        ("趨勢", f'<span style="color:{trend_color}">{trend.label}</span>', f"趨勢分數 {trend.score:+d} / ±{trend.max_score}"),
        ("20 日上漲機率", f"{s20.up_prob:.0%}" if s20 else "—", f"平常 {s20.base_up_prob:.0%}" if s20 else "歷史資料不足"),
        ("下方支撐", f"{levels.support:,.2f}" if levels.support else "—",
         f"上方壓力 {levels.resistance:,.2f}" if levels.resistance else "上方無壓力（創新高）"),
        ("參考停損", f"{levels.stop:,.2f}", f"風險 -{levels.risk_pct:.1%}" + (f" · 報酬風險比 {levels.reward_risk:.1f}" if levels.reward_risk else "")),
    ]
    for col, (label, value, sub) in zip(k, kpis):
        with col:
            html(f'<div class="card kpi" style="margin-top:12px;padding:14px 14px"><div class="label">{label}</div>'
                 f'<div class="value mono">{value}</div><div class="sub">{sub}</div></div>')

with right:
    tone_c = TONE_COLOR[rating.tone]
    arc = 251.33  # 半圓弧長 π × 80
    gauge = f"""<svg viewBox="0 0 200 118" style="width:100%;max-width:230px">
<path d="M20,100 A80,80 0 0 1 180,100" fill="none" stroke="#1f2836" stroke-width="14" stroke-linecap="round"/>
<path d="M20,100 A80,80 0 0 1 180,100" fill="none" stroke="{tone_c}" stroke-width="14" stroke-linecap="round"
 stroke-dasharray="{arc * rating.score / 100:.1f} 999"/>
<text x="100" y="92" text-anchor="middle" fill="{tone_c}" font-size="44" font-weight="700" font-family="JetBrains Mono">{rating.score}</text>
<text x="100" y="114" text-anchor="middle" fill="{MUTED}" font-size="10" letter-spacing="2">/ 100</text>
<text x="20" y="116" text-anchor="middle" fill="{MUTED}" font-size="9">0</text>
<text x="180" y="116" text-anchor="middle" fill="{MUTED}" font-size="9">100</text></svg>"""
    comps = "".join(
        f'<div class="comp"><span class="lbl">{n}</span><span class="bar"><i style="width:{s:.0f}%;background:{tone_c}"></i></span>'
        f'<span class="v mono">{s:.0f}</span></div>' for n, s, _ in rating.components)
    html(f"""<div class="card"><h4>買點評分 BUY SIGNAL SCORE</h4>
<div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
<div style="flex:0 0 210px;text-align:center">{gauge}</div>
<div style="flex:1;min-width:220px"><div class="verdict" style="color:{tone_c}">{rating.tier}</div>
<div class="summary">{escape(rating.summary)}</div></div></div>
<div style="margin-top:10px">{comps}</div></div>""")

# ---------- 分析師觀點 ----------
c1, c2, c3 = st.columns(3, gap="medium")


def bullet_card(col, title: str, rows: list, icon: str, color: str, empty: str) -> None:
    lis = "".join(f'<li><span class="ic" style="color:{color}">{icon}</span>{escape(r)}</li>' for r in rows[:6]) or \
        f'<li style="color:#6b7789">{empty}</li>'
    with col:
        html(f'<div class="card" style="margin-top:4px"><h4>{title}</h4><ul class="list">{lis}</ul></div>')


bullet_card(c1, "有利因素 BULL CASE", rating.pros, "▲", UP, "目前沒有明顯的有利因素")
bullet_card(c2, "不利因素 BEAR CASE", rating.cons, "▼", DOWN, "目前沒有明顯的不利因素")
bullet_card(c3, "轉強觀察條件 WATCH LIST", rating.watch or ["主要條件皆已符合，留意是否跌破停損價"], "◎", GOLD, "")

# ---------- K 線圖 ----------
def price_chart() -> go.Figure:
    view = d.iloc[-250:]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=view.index, open=view.open, high=view.high, low=view.low, close=view.close,
                                 name="K線", increasing_line_color=UP, increasing_fillcolor=UP,
                                 decreasing_line_color=DOWN, decreasing_fillcolor=DOWN), row=1, col=1)
    for ma, name in [("MA20", "月線"), ("MA60", "季線"), ("MA240", "年線")]:
        fig.add_trace(go.Scatter(x=view.index, y=view[ma], name=name, line=dict(color=MA_COLORS[ma], width=1.6)), row=1, col=1)

    if sim:
        bdays = pd.bdate_range(d.index[-1], periods=max(A.HORIZONS) + 1)
        xs = [d.index[-1]] + [bdays[s.horizon] for s in sim.stats]
        c = last.close
        hi = [c] + [c * (1 + s.p90) for s in sim.stats]
        lo = [c] + [c * (1 + s.p10) for s in sim.stats]
        mid = [c] + [c * (1 + s.median) for s in sim.stats]
        edge = dict(color="rgba(240,180,41,0.55)", width=1, dash="dot")
        fig.add_trace(go.Scatter(x=xs, y=hi, mode="lines", line=edge, showlegend=False, hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=lo, mode="lines", fill="tonexty", fillcolor="rgba(240,180,41,0.16)", line=edge,
                                 name="八成落點範圍", hoverinfo="skip"), row=1, col=1)
        hover = [f"{HORIZON_LABEL[s.horizon]}<br>八成落在 {lo[i + 1]:,.2f} ～ {hi[i + 1]:,.2f}<br>"
                 f"歷史中間值 {mid[i + 1]:,.2f}（一半高於、一半低於）" for i, s in enumerate(sim.stats)]
        fig.add_trace(go.Scatter(x=xs, y=mid, name="歷史中間值", mode="lines+markers",
                                 marker=dict(size=8, color=GOLD), line=dict(color=GOLD, dash="dot", width=2),
                                 hovertext=["今天收盤"] + hover, hoverinfo="text"), row=1, col=1)
        for i, s in enumerate(sim.stats):
            fig.add_annotation(x=xs[i + 1], y=hi[i + 1], yanchor="bottom", showarrow=False, row=1, col=1,
                               text=f"<b>{HORIZON_LABEL[s.horizon]}</b><br>{lo[i + 1]:,.0f} ～ {hi[i + 1]:,.0f}<br>中間值 {mid[i + 1]:,.0f}",
                               font=dict(size=11, color=TEXT), bgcolor="rgba(17,23,34,0.85)",
                               bordercolor="rgba(240,180,41,0.5)", borderwidth=1, borderpad=4)

    for y, text, color, pos in [(levels.resistance, "壓力", UP, "top left"), (levels.support, "支撐", DOWN, "top right"),
                                (levels.stop, "停損", MUTED, "bottom right")]:
        if y:
            fig.add_hline(y=y, line=dict(color=color, dash="dash", width=1), row=1, col=1,
                          annotation_text=f"{text} {y:,.2f}", annotation_position=pos,
                          annotation_font=dict(color=color, size=11))

    colors = [UP if c >= o else DOWN for c, o in zip(view.close, view.open)]
    fig.add_trace(go.Bar(x=view.index, y=view.volume, marker_color=colors, marker_line_width=0, opacity=0.7,
                         name="成交量（張）", showlegend=False), row=2, col=1)
    theme(fig, 600)
    fig.update_layout(xaxis_rangeslider_visible=False)
    fig.update_xaxes(rangebreaks=breaks(view))
    return fig


html('<div class="card" style="margin-top:16px;border:none;background:none;padding:6px 0 0 0"><h4>價格走勢與未來機率區間 PRICE ACTION & PROJECTION</h4>'
     '<div style="color:#8b97a8;font-size:.82rem">右側金色區域：過去和今天狀態相似的情況中，八成的股價最後落在這個範圍；'
     '虛線是歷史中間值（一半高於、一半低於）。這是統計範圍，<b style="color:#c9d3df">不是走勢預測</b>，股價不會沿著虛線走。</div></div>')
st.plotly_chart(price_chart(), width="stretch", config={"displayModeBar": False})

# ---------- 分頁 ----------
n_news = len(news)
tab_cred, tab_check, tab_prob, tab_peer, tab_chip, tab_news, tab_ind, tab_help = st.tabs(
    ["評分可信度", "買點檢查表", "機率分析", "同業比較", "營收與籌碼", f"相關新聞（{n_news}）", "技術指標", "方法說明"])

PCT = {"20日上漲機率": "{:.0%}", "20日平均報酬": "{:+.1%}", "60日上漲機率": "{:.0%}", "60日平均報酬": "{:+.1%}", "次數": "{:,}"}


@st.cache_data(show_spinner=False)
def stock_history_ratings(stock_id: str, last_date) -> pd.DataFrame:
    mkt = data.market_index()
    return A.historical_ratings(A.add_indicators(data.price_history(stock_id)), A.market_score_series(mkt))


@st.cache_data(show_spinner=False)
def validation_tables(mtime: float):
    v = pd.read_pickle(data.CACHE_DIR / "validation.pkl")
    return A.score_bucket_table(v["hist"]), v["hist"]["stock_id"].nunique(), len(v["hist"]), v["created"]


def screener_peers(stock_id: str, industry: str) -> pd.DataFrame:
    import screener
    return screener.peers(stock_id, industry, market)


def bucket_of(score: float) -> str:
    return next(name for lo, hi, name in A.SCORE_BUCKETS if lo <= score < hi)


with tab_cred:
    st.caption("把過去每一週都用「當天以前」的資料重新計算一次評分（不偷看未來），再統計之後實際漲跌。"
               "如果高分區間的上漲機率明顯高於基準，代表評分有參考價值；如果差不多，就只能當作參考。"
               "歷史回測只用價格面的 6 項條件，法人、本益比、營收、融資的歷史資料不夠長，沒有納入。")
    cur_bucket = bucket_of(rating.score)
    vpath = data.CACHE_DIR / "validation.pkl"
    cols = st.columns(2, gap="medium")
    with cols[0]:
        st.markdown(f"##### 這檔股票（{sid}）的歷史")
        with st.spinner("回測中…"):
            hist = stock_history_ratings(sid, d.index[-1])
        if hist.empty or hist["fwd20"].notna().sum() < 50:
            st.info("歷史資料不足，無法回測。")
        else:
            bt = A.score_bucket_table(hist)
            st.dataframe(bt.style.format(PCT, na_rep="—"), hide_index=True, width="stretch")
            row = bt[bt["評分區間"] == cur_bucket]
            base = bt[bt["評分區間"] == "全部（基準）"].iloc[0]
            if len(row):
                r0 = row.iloc[0]
                html(f'<div class="summary">今天評分 <b>{rating.score}</b> 落在「{cur_bucket}」。這檔股票過去在這個區間共 {r0["次數"]} 次，'
                     f'20 日後上漲機率 <b>{r0["20日上漲機率"]:.0%}</b>（平常 {base["20日上漲機率"]:.0%}）。'
                     + ("<span style='color:#8b97a8'>樣本少於 30 次，參考性有限。</span>" if r0["次數"] < 30 else "") + '</div>')
    with cols[1]:
        if vpath.exists():
            vt, nst, nrow, created = validation_tables(vpath.stat().st_mtime)
            st.markdown(f"##### {nst} 檔熱門股合併驗證")
            st.dataframe(vt.style.format(PCT, na_rep="—"), hide_index=True, width="stretch")
            base = vt[vt["評分區間"] == "全部（基準）"].iloc[0]
            hi = vt[vt["評分區間"].isin(["57–69 分", "70 分以上"])]
            if len(hi):
                n_hi = hi["次數"].sum()
                up_hi = (hi["20日上漲機率"] * hi["次數"]).sum() / n_hi
                r_hi = (hi["20日平均報酬"] * hi["次數"]).sum() / n_hi
                html(f'<div class="summary">結論：57 分以上的情況，20 日平均報酬 <b>{r_hi:+.1%}</b>（基準 {base["20日平均報酬"]:+.1%}），'
                     f'上漲機率 <b>{up_hi:.0%}</b>（基準 {base["20日上漲機率"]:.0%}）。'
                     '評分對「平均報酬」有小幅參考價值，但對「會不會漲」幫助很有限，請搭配停損使用。</div>')
            st.caption(f"共 {nrow:,} 筆歷史評分，驗證日期 {created:%Y-%m-%d}。重新驗證：在工具資料夾執行 python validate.py")
        else:
            st.info("尚未執行多檔驗證。在工具資料夾執行 python validate.py 即可產生。")

with tab_check:
    applicable = [i for i in items if i.ok is not None]
    passed = sum(i.ok for i in applicable)
    rows = "".join(
        f'<li><span class="ic" style="color:{UP if i.ok else (MUTED if i.ok is None else DOWN)}">'
        f'{"●" if i.ok else ("○" if i.ok is None else "✕")}</span><b style="color:#e6edf3">{i.name}</b>　'
        f'<span style="color:#8b97a8">{escape(i.detail)}</span></li>' for i in items)
    html(f'<div class="card"><h4>符合 {passed} / {len(applicable)} 項</h4><ul class="list">{rows}</ul></div>')

    st.markdown("##### 這份檢查表在這檔股票上準不準？")
    st.caption("把過去每一天都用同樣的前 6 項（價格面）檢查一次，依符合項數分組，看之後 20 個交易日的表現。"
               "「符合越多、上漲機率越高」代表這套標準對這檔股票有效；沒有差別就別太依賴它。")
    bt = A.score_backtest(d)
    st.dataframe(bt.style.format({"上漲機率": "{:.0%}", "平均報酬": "{:+.1%}", "中位數報酬": "{:+.1%}", "歷史天數": "{:,}"}),
                 hide_index=True, width="stretch")

with tab_prob:
    if not sim:
        st.info("歷史資料不足（需要約一年半以上的交易資料），無法統計相似情況。")
    else:
        st.caption(f"從這檔股票的歷史中，找出 {', '.join(sim.features_used)} 等技術狀態和今天最相似的日子"
                   "（彼此至少間隔 5 個交易日），統計它們之後的漲跌。「平常」是所有日子的基準值，差距越大越有參考價值。")
        cols = st.columns(len(sim.stats))
        c = last.close
        for col, s in zip(cols, sim.stats):
            edge = s.up_prob - s.base_up_prob
            ec = UP if edge > 0.02 else DOWN if edge < -0.02 else GOLD
            with col:
                html(f"""<div class="card kpi"><div class="label">{s.horizon} 個交易日後</div>
<div class="value mono" style="font-size:2rem">{s.up_prob:.0%}</div>
<div class="sub">上漲機率 · 平常 {s.base_up_prob:.0%} · <span style="color:{ec}">{edge:+.0%}</span></div>
<div class="stats mono" style="grid-template-columns:1fr 1fr">
<div>歷史中間值<b>{c * (1 + s.median):,.2f}</b></div><div>平均報酬<b>{s.mean:+.1%}</b></div>
<div>悲觀 10%<b style="color:{DOWN}">{c * (1 + s.p10):,.2f}</b></div><div>樂觀 90%<b style="color:{UP}">{c * (1 + s.p90):,.2f}</b></div>
<div>期間平均最大跌幅<b>{s.avg_drawdown:+.1%}</b></div><div>樣本數<b>{s.n}</b></div></div></div>""")
        if sim.dates:
            st.caption("最相似的歷史日期：" + "、".join(f"{x:%Y-%m-%d}" for x in sim.dates))

with tab_news:
    if news.empty:
        st.info("近 7 天沒有找到相關新聞。")
    else:
        cnt = news["tone"].value_counts()
        b, n0, s_ = cnt.get("偏多", 0), cnt.get("中性", 0), cnt.get("偏空", 0)
        tot = max(b + n0 + s_, 1)
        html(f"""<div class="card" style="margin-bottom:12px"><h4>近 7 日新聞情緒 NEWS SENTIMENT</h4>
<div class="sentbar"><i style="width:{b / tot:.0%};background:{UP}"></i><i style="width:{n0 / tot:.0%};background:#3a4558"></i><i style="width:{s_ / tot:.0%};background:{DOWN}"></i></div>
<div class="mono" style="font-size:.8rem;color:#8b97a8"><span style="color:{UP}">▲ 偏多 {b}</span>　■ 中性 {n0}　<span style="color:{DOWN}">▼ 偏空 {s_}</span>
　·　標題關鍵字粗略判讀，僅供快速瀏覽</div></div>""")
        pill = {"偏多": (UP, "rgba(255,90,95,.15)"), "偏空": (DOWN, "rgba(34,195,142,.15)"), "中性": (MUTED, "rgba(139,151,168,.12)")}
        tone_filter = st.radio("篩選", ["全部", "偏多", "中性", "偏空"], horizontal=True, label_visibility="collapsed")
        shown = news if tone_filter == "全部" else news[news["tone"] == tone_filter]
        out = []
        for r in shown.head(40).itertuples():
            fg, bg = pill[r.tone]
            out.append(f'<a class="news" href="{escape(r.link)}" target="_blank" rel="noopener noreferrer">'
                       f'<div class="t"><span class="pill" style="color:{fg};background:{bg}">{r.tone}</span>{escape(r.title)}</div>'
                       f'<div class="m"><span class="mono">{escape(r.source)}'
                       f'{" · " + escape(r.site) if getattr(r, "site", "") else ""} · {r.date:%m/%d %H:%M}</span>'
                       f'<span class="open">開啟原文 ↗</span></div></a>')
        # 外層用 div 包住，Markdown 才會把整段當成原始 HTML，不去解析標題或網址裡的符號
        html("<div>" + "".join(out) + "</div>" if out else '<div style="color:#8b97a8">沒有符合的新聞</div>')

with tab_ind:
    view = d.iloc[-120:]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07, subplot_titles=["KD（9,3,3）", "RSI（14）", "MACD（12,26,9）"])
    fig.add_trace(go.Scatter(x=view.index, y=view.K, name="K", line=dict(color=MA_COLORS["MA20"], width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=view.index, y=view.D, name="D", line=dict(color=MA_COLORS["MA60"], width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=view.index, y=view.RSI, name="RSI", line=dict(color=MA_COLORS["MA240"], width=2)), row=2, col=1)
    for y in (20, 80):
        fig.add_hline(y=y, line=dict(color="#3a4558", dash="dot", width=1), row=1, col=1)
    for y in (30, 70):
        fig.add_hline(y=y, line=dict(color="#3a4558", dash="dot", width=1), row=2, col=1)
    fig.add_trace(go.Bar(x=view.index, y=view.MACD_hist, name="MACD 柱", marker_line_width=0,
                         marker_color=[UP if v >= 0 else DOWN for v in view.MACD_hist]), row=3, col=1)
    fig.add_trace(go.Scatter(x=view.index, y=view.MACD, name="DIF", line=dict(color=MA_COLORS["MA20"], width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=view.index, y=view.MACD_signal, name="MACD", line=dict(color=MA_COLORS["MA60"], width=1.5)), row=3, col=1)
    theme(fig, 640)
    fig.update_xaxes(rangebreaks=breaks(view))
    fig.update_annotations(font=dict(color=TEXT, size=13))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

with tab_peer:
    st.caption(f"和同產業（{info.industry_category}）成交金額最大的幾檔股票比較近期漲跌與評分。"
               "同業評分只用價格面資料，所以可能和上方的完整評分略有不同。第一次載入每檔約需 2 次免費查詢。")
    key = f"peers_{sid}"
    if key not in st.session_state:
        if st.button("載入同業比較", type="primary"):
            with st.spinner("正在分析同業…"):
                try:
                    st.session_state[key] = screener_peers(sid, info.industry_category)
                except data.DataError as e:
                    st.error(str(e))
    pr = st.session_state.get(key)
    if pr is not None:
        if len(pr) <= 1:
            st.info("找不到同產業的其他股票。")
        else:
            pr = pr.sort_values("60日漲跌", ascending=False).reset_index(drop=True)
            me = pr.index[pr["代號"] == sid]
            if len(me):
                rank = int(me[0]) + 1
                html(f'<div class="summary">近 60 日漲幅在 {len(pr)} 檔同業中排名第 <b>{rank}</b>'
                     f'（{"強於" if rank <= len(pr) / 2 else "弱於"}多數同業）。</div>')
            tbl, cfg = rank_table(pr)
            st.dataframe(tbl, column_config=cfg, hide_index=True, width="stretch")

with tab_chip:
    rv = A.revenue_summary(rev)
    if rv:
        r24 = rev.iloc[-24:]
        fig = make_subplots(specs=[[{"secondary_y": False}]])
        fig.add_trace(go.Bar(x=r24.index, y=r24["revenue"] / 1e8, name="月營收（億元）", marker_line_width=0,
                             marker_color=[UP if y > 0 else DOWN for y in r24["yoy"].fillna(0)],
                             customdata=r24["yoy"], hovertemplate="%{x|%Y/%m}<br>營收 %{y:,.1f} 億<br>年增 %{customdata:+.1%}<extra></extra>"))
        theme(fig, 300)
        fig.update_layout(title=dict(text="月營收（近 24 個月，紅色＝年增、綠色＝年減）", font=dict(color=TEXT, size=14)),
                          showlegend=False, hovermode="closest")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        k = st.columns(4)
        for col, (label, value) in zip(k, [("最新月份", f"{rv['month']:%Y/%m}"), ("年增率", f"{rv['yoy']:+.1%}"),
                                           ("近 3 個月累計年增", f"{rv['yoy3']:+.1%}"), ("連續年增", f"{rv['streak']} 個月")]):
            with col:
                html(f'<div class="card kpi" style="padding:12px 14px"><div class="label">{label}</div>'
                     f'<div class="value mono" style="font-size:1.2rem">{value}</div></div>')
    else:
        st.info("沒有月營收資料（ETF 或資料不足）。")

    ms = A.margin_summary(mg, d)
    if ms:
        mv = mg.iloc[-120:]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                            subplot_titles=["收盤價", "融資餘額（張）"], row_heights=[0.5, 0.5])
        pv = d["close"].reindex(mv.index)
        fig.add_trace(go.Scatter(x=mv.index, y=pv, name="收盤價", line=dict(color=TEXT, width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=mv.index, y=mv["融資餘額"], name="融資餘額", line=dict(color=MA_COLORS["MA20"], width=2)), row=2, col=1)
        theme(fig, 380)
        fig.update_layout(showlegend=False)
        fig.update_xaxes(rangebreaks=breaks(mv))
        fig.update_annotations(font=dict(color=TEXT, size=13))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        usage = f"{ms['usage']:.1%}" if pd.notna(ms["usage"]) else "—"
        st.caption(f"融資餘額 {ms['balance']:,.0f} 張，近 20 日 {ms['chg20']:+.1%}（同期股價 {ms['price20']:+.1%}）· 融資使用率 {usage}"
                   f" · 券資比 {ms['short_ratio']:.1%}。股價跌、融資增，代表散戶逢低承接，籌碼較亂；股價漲、融資減，籌碼較乾淨。")

    if inst is not None and not inst.empty:
        iv = inst.iloc[-60:]
        fig = go.Figure()
        for who, color in [("外資", MA_COLORS["MA60"]), ("投信", MA_COLORS["MA20"]), ("自營商", "#5b6678")]:
            fig.add_trace(go.Bar(x=iv.index, y=iv[who], name=who, marker_color=color, marker_line_width=0))
        theme(fig, 340)
        fig.update_layout(barmode="relative", title=dict(text="三大法人買賣超（近 60 日，張）", font=dict(color=TEXT, size=14)))
        fig.update_xaxes(rangebreaks=breaks(iv))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        sums = pd.DataFrame({f"近 {n} 日": inst.iloc[-n:].sum() for n in (5, 20, 60)})
        st.dataframe(sums.style.format("{:+,.0f}"), width="stretch")
    else:
        st.info("沒有法人買賣超資料。")
    per = val["PER"][val["PER"] > 0] if val is not None and not val.empty else pd.Series(dtype=float)
    if len(per):
        fig = go.Figure(go.Scatter(x=per.index, y=per, name="本益比", line=dict(color=MA_COLORS["MA240"], width=2)))
        fig.add_hline(y=per.iloc[-250 * 5:].median(), line=dict(dash="dot", color=MUTED),
                      annotation_text="近 5 年中位數", annotation_font=dict(color=MUTED))
        theme(fig, 300)
        fig.update_layout(title=dict(text="本益比走勢", font=dict(color=TEXT, size=14)), showlegend=False)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

with tab_help:
    st.markdown("""
**買點評分（0–100）由四個部分加權組成**

| 項目 | 權重 | 看什麼 |
|---|---|---|
| 趨勢結構 | 50% | 股價和月線、季線、年線的位置與方向 |
| 歷史勝率優勢 | 30% | 相似歷史情況的 20／60 日上漲機率，比這檔股票平常高或低多少 |
| 買點條件 | 10% | 檢查表的符合比例 |
| 風險報酬 | 10% | 到壓力的潛在漲幅 ÷ 到停損的潛在跌幅；過熱時會被壓低 |

**權重怎麼來的**：用 60 檔熱門股、約 4.4 萬筆「只用當天以前資料」重算的歷史評分驗證。
趨勢結構是唯一在 2019 年前後兩段期間都有效的項目，所以權重最高；檢查表與風險報酬幾乎沒有預測力，只保留小權重。
大盤環境呈現反向關係（大盤弱勢時，之後的表現反而略好），所以只顯示、不計分。

**評分的實際效果（請務必了解）**：高分（57 分以上）在驗證中的**平均報酬**比低分高，
但**上漲機率**只高約 1 個百分點。也就是說，高分比較常出現大漲的情況，卻不代表比較不容易跌。
詳細數字見「評分可信度」分頁。

**評級**：70 分以上「買點訊號浮現」、57–69「偏多，可列入觀察」、43–56「中性，等待訊號」、42 以下「訊號偏弱」。

**使用時請注意**

- 歷史機率只代表「過去類似情況的統計結果」，市場隨時可能出現過去沒發生過的狀況。
- 檢查表中的法人、本益比、營收、融資項目歷史資料不夠長，無法驗證，僅供參考。
- 新聞情緒是用標題關鍵字粗略判斷，不計入評分，請點進原文自行閱讀。
- 股價已用除權息及分割資料還原，回測報酬包含配息。
- 資料來源：FinMind（證交所、櫃買中心公開資料）、Google 新聞。資料快取在 `cache` 資料夾，收盤後自動更新。
""")

html('<div class="disclaimer">本工具僅為技術與統計分析，不構成任何投資建議。投資前請自行判斷並承擔風險。</div>')
