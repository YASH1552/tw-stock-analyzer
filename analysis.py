"""技術指標、趨勢判斷、買點檢查表與歷史機率回測。"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HORIZONS = [5, 20, 60]


# ---------- 技術指標 ----------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    for n in [5, 10, 20, 60, 120, 240]:
        d[f"MA{n}"] = c.rolling(n).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    d["RSI"] = d["RSI"].fillna(100)

    # KD（台灣常用 9,3,3）
    low9 = d["low"].rolling(9).min()
    high9 = d["high"].rolling(9).max()
    rsv = ((c - low9) / (high9 - low9).replace(0, np.nan) * 100).fillna(50)
    k = np.full(len(d), 50.0)
    dd = np.full(len(d), 50.0)
    for i in range(1, len(d)):
        k[i] = k[i - 1] * 2 / 3 + rsv.iloc[i] / 3
        dd[i] = dd[i - 1] * 2 / 3 + k[i] / 3
    d["K"], d["D"] = k, dd

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_signal"] = d["MACD"].ewm(span=9, adjust=False).mean()
    d["MACD_hist"] = d["MACD"] - d["MACD_signal"]

    std20 = c.rolling(20).std()
    d["BB_up"] = d["MA20"] + 2 * std20
    d["BB_low"] = d["MA20"] - 2 * std20

    prev = c.shift()
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev).abs(), (d["low"] - prev).abs()], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    d["VOL_MA20"] = d["volume"].rolling(20).mean()
    d["LOW60"] = d["low"].rolling(60).min()
    d["HIGH60"] = d["high"].rolling(60).max()
    d["BIAS20"] = c / d["MA20"] - 1
    return d


# ---------- 趨勢判斷 ----------

def _slope(s: pd.Series, lag: int) -> float:
    if len(s) <= lag or pd.isna(s.iloc[-1]) or pd.isna(s.iloc[-1 - lag]):
        return np.nan
    return s.iloc[-1] / s.iloc[-1 - lag] - 1


@dataclass
class Trend:
    label: str
    score: int
    max_score: int
    parts: list = field(default_factory=list)  # (期間, 狀態, 說明)


def assess_trend(d: pd.DataFrame) -> Trend:
    last = d.iloc[-1]
    c = last["close"]
    score, max_score, parts = 0, 0, []
    for name, ma, lag in [("短期（月線）", "MA20", 5), ("中期（季線）", "MA60", 20), ("長期（年線）", "MA240", 20)]:
        m = last[ma]
        if pd.isna(m):
            parts.append((name, "資料不足", "上市時間太短，無法計算"))
            continue
        sl = _slope(d[ma], lag)
        above = c > m
        rising = sl > 0
        score += (1 if above else -1) + (1 if rising else -1)
        max_score += 2
        if above and rising:
            state = "上升"
        elif not above and not rising:
            state = "下降"
        else:
            state = "整理"
        parts.append((name, state, f"股價在{ma}之{'上' if above else '下'}，{ma}{'上揚' if rising else '下彎'}（{sl:+.1%}）"))
    if not any(pd.isna(last[m]) for m in ["MA20", "MA60", "MA240"]):
        max_score += 1
        if last["MA20"] > last["MA60"] > last["MA240"]:
            score += 1
            parts.append(("均線排列", "多頭排列", "月線 > 季線 > 年線"))
        elif last["MA20"] < last["MA60"] < last["MA240"]:
            score -= 1
            parts.append(("均線排列", "空頭排列", "月線 < 季線 < 年線"))
        else:
            parts.append(("均線排列", "糾結", "均線交錯，方向不明"))
    ratio = score / max_score if max_score else 0
    if ratio >= 0.7:
        label = "強勢多頭"
    elif ratio >= 0.3:
        label = "偏多"
    elif ratio > -0.3:
        label = "盤整"
    elif ratio > -0.7:
        label = "偏空"
    else:
        label = "強勢空頭"
    return Trend(label, score, max_score, parts)


# ---------- 支撐、壓力、停損 ----------

def _pivots(d: pd.DataFrame, lookback: int = 120, w: int = 5):
    x = d.iloc[-lookback:]
    lows = x["low"][(x["low"] == x["low"].rolling(2 * w + 1, center=True).min())]
    highs = x["high"][(x["high"] == x["high"].rolling(2 * w + 1, center=True).max())]
    return lows.tolist(), highs.tolist()


@dataclass
class Levels:
    support: float | None
    support_name: str
    resistance: float | None
    resistance_name: str
    stop: float
    risk_pct: float
    reward_risk: float | None


def key_levels(d: pd.DataFrame) -> Levels:
    last = d.iloc[-1]
    c, atr = last["close"], last["ATR"]
    cands = {"月線": last["MA20"], "季線": last["MA60"], "年線": last["MA240"],
             "近60日低點": last["LOW60"], "近60日高點": last["HIGH60"]}
    lows, highs = _pivots(d)
    for v in lows:
        cands.setdefault(f"前波低點 {v:,.2f}", v)
    for v in highs:
        cands.setdefault(f"前波高點 {v:,.2f}", v)
    below = {k: v for k, v in cands.items() if pd.notna(v) and v < c * 0.995}
    above = {k: v for k, v in cands.items() if pd.notna(v) and v > c * 1.005}
    sup_name, sup = max(below.items(), key=lambda kv: kv[1]) if below else ("無", None)
    res_name, res = min(above.items(), key=lambda kv: kv[1]) if above else ("創新高，上方無壓力", None)
    stop = (sup - 0.5 * atr) if sup else c - 2 * atr
    stop = max(stop, c * 0.85)  # 停損距離最多 15%
    risk = (c - stop) / c
    rr = (res - c) / (c - stop) if res else None
    return Levels(sup, sup_name, res, res_name, stop, risk, rr)


# ---------- 買點檢查表 ----------

PRICE_ITEMS = ["長期趨勢向上", "中期趨勢向上", "沒有過熱", "接近支撐（拉回）", "短線轉強", "量價健康"]


def price_checklist_series(d: pd.DataFrame) -> pd.DataFrame:
    """每一天的價格面檢查項目（布林值），用於當下判斷與歷史回測，兩者標準一致。"""
    c = d["close"]
    out = pd.DataFrame(index=d.index)
    out["長期趨勢向上"] = (c > d["MA240"]) & (d["MA240"] > d["MA240"].shift(20))
    out["中期趨勢向上"] = (c > d["MA60"]) & (d["MA60"] > d["MA60"].shift(20))
    out["沒有過熱"] = (d["RSI"] < 70) & (d["BIAS20"] < 0.10)
    sup = pd.concat([d[m].where(d[m] < c) for m in ["MA20", "MA60", "MA240", "LOW60"]], axis=1).max(axis=1)
    out["接近支撐（拉回）"] = ((c - sup) / d["ATR"]) <= 1.5
    h = d["MACD_hist"]
    out["短線轉強"] = (d["K"] > d["D"]) & (h > h.shift(1))
    up = c > c.shift()
    vol = d["volume"]
    up_vol = vol.where(up).rolling(20, min_periods=5).mean()
    dn_vol = vol.where(~up).rolling(20, min_periods=5).mean()
    out["量價健康"] = up_vol > dn_vol
    out = out.astype(float)
    # 資料不足的日子設為 NaN（例如上市未滿一年就沒有年線）
    out.loc[d["MA240"].shift(20).isna(), "長期趨勢向上"] = np.nan
    out.loc[d["MA60"].shift(20).isna(), "中期趨勢向上"] = np.nan
    out.loc[d["MA60"].isna()] = np.nan
    return out


@dataclass
class CheckItem:
    name: str
    ok: bool | None
    detail: str


def checklist(d: pd.DataFrame, inst: pd.DataFrame, val: pd.DataFrame,
              rev: pd.DataFrame | None = None, mg: pd.DataFrame | None = None) -> list[CheckItem]:
    last = d.iloc[-1]
    s = price_checklist_series(d).iloc[-1]
    c = last["close"]
    items = []

    def ok(name):
        v = s[name]
        return None if pd.isna(v) else bool(v)

    items.append(CheckItem("長期趨勢向上", ok("長期趨勢向上"),
                           f"收盤 {c:,.2f}，年線 {last['MA240']:,.2f}，年線 20 日變化 {_slope(d['MA240'], 20):+.1%}"
                           if ok("長期趨勢向上") is not None else "上市未滿一年，沒有年線"))
    items.append(CheckItem("中期趨勢向上", ok("中期趨勢向上"),
                           f"季線 {last['MA60']:,.2f}，季線 20 日變化 {_slope(d['MA60'], 20):+.1%}"))
    items.append(CheckItem("沒有過熱", ok("沒有過熱"),
                           f"RSI {last['RSI']:.0f}（70 以上算過熱），月線乖離 {last['BIAS20']:+.1%}（10% 以上算過熱）"))
    sup = max([last[m] for m in ["MA20", "MA60", "MA240", "LOW60"] if pd.notna(last[m]) and last[m] < c], default=np.nan)
    dist = (c - sup) / last["ATR"] if pd.notna(sup) else np.nan
    items.append(CheckItem("接近支撐（拉回）", ok("接近支撐（拉回）"),
                           f"距下方最近的均線／60日低點 {sup:,.2f} 約 {dist:.1f} 倍 ATR（1.5 倍以內算接近）" if pd.notna(sup) else "下方沒有支撐（已跌破所有均線）"))
    items.append(CheckItem("短線轉強", ok("短線轉強"),
                           f"K {last['K']:.0f} / D {last['D']:.0f}，MACD 柱狀體{'上升' if d['MACD_hist'].iloc[-1] > d['MACD_hist'].iloc[-2] else '下降'}"))
    items.append(CheckItem("量價健康", ok("量價健康"), "近 20 日上漲日的平均成交量" + ("大於" if ok("量價健康") else "小於") + "下跌日"))

    if inst is not None and not inst.empty:
        recent = inst.iloc[-10:]
        net = recent["外資"].sum() + recent["投信"].sum()
        items.append(CheckItem("法人偏多", bool(net > 0),
                               f"近 10 日外資 {recent['外資'].sum():+,.0f} 張、投信 {recent['投信'].sum():+,.0f} 張"))
    else:
        items.append(CheckItem("法人偏多", None, "沒有法人買賣資料"))

    per = val["PER"] if val is not None and "PER" in val else pd.Series(dtype=float)
    per = per[per > 0]
    if len(per) > 250 and val["PER"].iloc[-1] > 0:
        now = per.iloc[-1]
        hist = per[per.index >= per.index[-1] - pd.Timedelta(days=365 * 5)]
        pct = (hist < now).mean()
        items.append(CheckItem("評價不貴", bool(pct <= 0.5),
                               f"本益比 {now:.1f} 倍，位於近 5 年的 {pct:.0%} 位置（50% 以下算不貴）"))
    else:
        items.append(CheckItem("評價不貴", None, "沒有本益比資料（ETF 或公司虧損）"))

    rv = revenue_summary(rev)
    if rv:
        items.append(CheckItem("營收成長", bool(rv["yoy3"] > 0),
                               f"近 3 個月營收年增 {rv['yoy3']:+.1%}，最新 {rv['month']:%Y/%m} 年增 {rv['yoy']:+.1%}"))
    else:
        items.append(CheckItem("營收成長", None, "沒有月營收資料（ETF 或資料不足）"))

    ms = margin_summary(mg, d)
    if ms:
        good = ms["chg20"] <= 0.10 and (pd.isna(ms["usage"]) or ms["usage"] < 0.30)
        usage = f"，融資使用率 {ms['usage']:.0%}" if pd.notna(ms["usage"]) else ""
        items.append(CheckItem("散戶籌碼安定", bool(good),
                               f"融資餘額近 20 日 {ms['chg20']:+.1%}{usage}（融資暴增或使用率超過 30% 代表散戶追價）"))
    else:
        items.append(CheckItem("散戶籌碼安定", None, "沒有融資融券資料"))
    return items


def revenue_summary(rev: pd.DataFrame | None) -> dict | None:
    """月營收重點：最新年增、近 3 個月累計年增、近 12 個月平均年增。"""
    if rev is None or rev.empty or rev["yoy"].dropna().empty or len(rev) < 15:
        return None
    r = rev.dropna(subset=["yoy"])
    last3 = rev["revenue"].iloc[-3:].sum()
    prev3 = rev["revenue"].iloc[-15:-12].sum()
    return {"month": r.index[-1], "yoy": r["yoy"].iloc[-1], "mom": rev["mom"].iloc[-1],
            "yoy3": last3 / prev3 - 1 if prev3 > 0 else np.nan, "yoy12": r["yoy"].iloc[-12:].mean(),
            "streak": int((r["yoy"][::-1] > 0).cumprod().sum())}


def margin_summary(mg: pd.DataFrame | None, d: pd.DataFrame) -> dict | None:
    if mg is None or mg.empty or len(mg) < 25 or mg["融資餘額"].iloc[-21] <= 0:
        return None
    return {"balance": mg["融資餘額"].iloc[-1], "chg20": mg["融資餘額"].iloc[-1] / mg["融資餘額"].iloc[-21] - 1,
            "usage": mg["融資使用率"].iloc[-1], "short_ratio": mg["券資比"].iloc[-1],
            "price20": d["close"].iloc[-1] / d["close"].iloc[-21] - 1}


# ---------- 大盤 ----------

@dataclass
class MarketState:
    label: str
    score: float          # 0–100
    close: float
    change: float
    ret20: float
    above_ma60: bool
    parts: list


def market_state(mkt: pd.DataFrame | None) -> MarketState | None:
    if mkt is None or len(mkt) < 260:
        return None
    m = add_indicators(mkt)
    tr = assess_trend(m)
    last, prev = m.iloc[-1], m.iloc[-2]
    score = _clip((tr.score / tr.max_score + 1) * 50) if tr.max_score else 50
    return MarketState(tr.label, score, last["close"], last["close"] / prev["close"] - 1,
                       last["close"] / m["close"].iloc[-21] - 1, bool(last["close"] > last["MA60"]), tr.parts)


# ---------- 歷史機率 ----------

def _features(d: pd.DataFrame) -> pd.DataFrame:
    c = d["close"]
    f = pd.DataFrame(index=d.index)
    f["月線乖離"] = c / d["MA20"] - 1
    f["季線乖離"] = c / d["MA60"] - 1
    f["年線乖離"] = c / d["MA240"] - 1
    f["RSI"] = d["RSI"] / 100
    f["20日漲跌"] = c / c.shift(20) - 1
    f["60日漲跌"] = c / c.shift(60) - 1
    rng = (d["HIGH60"] - d["LOW60"]).replace(0, np.nan)
    f["區間位置"] = (c - d["LOW60"]) / rng
    f["季線斜率"] = d["MA60"] / d["MA60"].shift(20) - 1
    f["波動度"] = d["ATR"] / c
    return f


def _forward(d: pd.DataFrame, h: int) -> pd.DataFrame:
    c = d["close"]
    ret = c.shift(-h) / c - 1
    future_low = d["low"][::-1].rolling(h).min()[::-1].shift(-1)
    dd = future_low / c - 1
    return pd.DataFrame({"ret": ret, "dd": dd})


@dataclass
class HorizonStats:
    horizon: int
    n: int
    up_prob: float
    mean: float
    median: float
    p10: float
    p90: float
    avg_drawdown: float
    base_up_prob: float
    base_mean: float
    base_n: int


@dataclass
class SimilarResult:
    stats: list[HorizonStats]
    dates: list  # 最相似的歷史日期（20 日期間）
    features_used: list


def similar_prep(d: pd.DataFrame):
    """預先算好特徵與未來報酬；回測時重複使用，不必每天重算。"""
    fws = {h: (_forward(d, h)["ret"].to_numpy(), _forward(d, h)["dd"].to_numpy()) for h in HORIZONS}
    return _features(d), fws


def similar_situations(d: pd.DataFrame, min_gap: int = 5, pre=None, end: int | None = None) -> SimilarResult | None:
    """找出歷史上和「今天」（或第 end 天）技術狀態最相似的日子，統計之後的漲跌。

    只使用 end 當天以前已經知道結果的日子，回測時不會偷看未來。
    """
    f_all, fws = pre if pre is not None else similar_prep(d)
    n = len(d) if end is None else end + 1
    f = f_all.iloc[:n]
    # 上市不滿兩年就不用年線特徵
    if f["年線乖離"].notna().sum() < 250:
        f = f.drop(columns="年線乖離")
    X = f.to_numpy(dtype=float)
    today = X[-1]
    if np.isnan(today).any():
        return None
    valid = ~np.isnan(X).any(axis=1)
    if valid.sum() < 300:
        return None
    scale = np.nanstd(X[valid], axis=0, ddof=1)
    scale[scale == 0] = 1
    dist = np.sqrt((((X - today) / scale) ** 2).sum(axis=1))

    stats, top_dates = [], []
    for h in HORIZONS:
        ret, dd = fws[h]
        known = np.zeros(n, dtype=bool)
        known[: max(n - h, 0)] = True  # 第 p 天的 h 日後報酬，要到 p+h 天才知道
        cand = np.nonzero(valid & known & ~np.isnan(ret[:n]))[0]
        if len(cand) < 200:
            continue
        k = int(np.clip(len(cand) * 0.04, 30, 120))
        blocked = np.zeros(n + min_gap, dtype=bool)
        chosen = []
        for p in cand[np.argsort(dist[cand], kind="stable")]:
            if not blocked[p]:
                chosen.append(p)
                blocked[max(p - min_gap + 1, 0): p + min_gap] = True
                if len(chosen) >= k:
                    break
        chosen = np.array(chosen)
        r = pd.Series(ret[chosen])
        base = ret[cand]
        stats.append(HorizonStats(
            h, len(r), float((r > 0).mean()), float(r.mean()), float(r.median()), float(r.quantile(0.1)),
            float(r.quantile(0.9)), float(np.nanmean(dd[chosen])), float((base > 0).mean()), float(base.mean()), len(base)))
        if h == 20:
            top_dates = list(d.index[chosen[:10]])
    if not stats:
        return None
    return SimilarResult(stats, top_dates, list(f.columns))


def score_backtest(d: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """把歷史每一天的價格面檢查分數分組，看分數高低和之後報酬的關係。"""
    s = price_checklist_series(d)
    score = s.sum(axis=1, min_count=len(PRICE_ITEMS))
    fw = _forward(d, horizon)["ret"]
    df = pd.DataFrame({"score": score, "ret": fw}).dropna()
    bins = [(0, 2, "0–2 項"), (3, 4, "3–4 項"), (5, 6, "5–6 項")]
    rows = []
    for lo, hi, name in bins:
        x = df[(df.score >= lo) & (df.score <= hi)]["ret"]
        if len(x):
            rows.append({"符合項目": name, "歷史天數": len(x), "上漲機率": (x > 0).mean(),
                         "平均報酬": x.mean(), "中位數報酬": x.median()})
    rows.append({"符合項目": "全部日子（基準）", "歷史天數": len(df), "上漲機率": (df.ret > 0).mean(),
                 "平均報酬": df.ret.mean(), "中位數報酬": df.ret.median()})
    return pd.DataFrame(rows)


# ---------- 買點評分 ----------

@dataclass
class Rating:
    score: int            # 0–100
    tier: str             # 評級文字
    tone: str             # bull / neutral / bear，給 UI 上色
    summary: str          # 一句話結論
    components: list      # (項目, 分數 0–100, 權重)
    pros: list
    cons: list
    watch: list           # 轉強觀察條件


def _clip(x: float) -> float:
    return float(np.clip(x, 0, 100))


# 權重依 validate.py 的 60 檔、約 4.4 萬筆逐日回測結果調整（2026-10）：
# 趨勢結構是唯一在 2019 前後兩段期間都有效的項目；買點條件、風險報酬幾乎沒有預測力，只保留小權重；
# 大盤環境呈現反向關係（大盤弱時之後反而較好），不列入評分，只在畫面上顯示。
WEIGHTS = {"趨勢結構": 0.50, "歷史勝率優勢": 0.30, "買點條件": 0.10, "風險報酬": 0.10, "大盤環境": 0.0}


def rating_components(last: pd.Series, trend: Trend, oks: list, sim: SimilarResult | None,
                      levels: Levels, market_score: float | None = None) -> dict:
    """各評分項目的 0–100 分數。歷史回測也用同一個函式，確保標準一致。"""
    comps = {}
    comps["趨勢結構"] = _clip((trend.score / trend.max_score + 1) * 50) if trend.max_score else 50.0

    applicable = [o for o in oks if o is not None and not pd.isna(o)]
    comps["買點條件"] = _clip(sum(bool(o) for o in applicable) / len(applicable) * 100) if applicable else 50.0

    edges = [s.up_prob - s.base_up_prob for s in sim.stats if s.horizon in (20, 60)] if sim else []
    edge = float(np.mean(edges)) if edges else 0.0
    comps["歷史勝率優勢"] = _clip(50 + edge * 300)  # 比平常高 ~17% 就滿分

    rr = levels.reward_risk
    r_score = 65.0 if rr is None else _clip(20 + rr * 35)  # 創新高無壓力給 65；rr 1 → 55，rr 2 → 90
    if last["RSI"] >= 75 or last["BIAS20"] >= 0.12:
        r_score = min(r_score, 30.0)
    comps["風險報酬"] = r_score

    if market_score is not None:
        comps["大盤環境"] = float(market_score)
    return comps


def tier_of(score: float) -> tuple[str, str]:
    if score >= 70:
        return "買點訊號浮現", "bull"
    if score >= 57:
        return "偏多，可列入觀察", "bull"
    if score >= 43:
        return "中性，等待訊號", "neutral"
    return "訊號偏弱，暫不符合買點", "bear"


def weighted_score(comps: dict, weights: dict | None = None) -> float:
    w = {k: v for k, v in (weights or WEIGHTS).items() if k in comps and v > 0}
    total = sum(w.values())
    return sum(comps[k] * v for k, v in w.items()) / total if total else 50.0


def buy_rating(d: pd.DataFrame, trend: Trend, items: list[CheckItem], sim: SimilarResult | None,
               levels: Levels, market: MarketState | None = None, weights: dict | None = None) -> Rating:
    """把趨勢、檢查表、歷史機率、風險報酬（與大盤）合成 0–100 的買點評分。"""
    last = d.iloc[-1]
    c = last["close"]
    weights = weights or WEIGHTS
    cdict = rating_components(last, trend, [i.ok for i in items], sim, levels,
                              market.score if market else None)
    comps = [(k, v, weights.get(k, 0)) for k, v in cdict.items() if weights.get(k, 0) > 0]
    edges = [s.up_prob - s.base_up_prob for s in sim.stats if s.horizon in (20, 60)] if sim else []
    edge = float(np.mean(edges)) if edges else 0.0
    rr = levels.reward_risk

    score = int(round(weighted_score(cdict, weights)))
    tier, tone = tier_of(score)

    pros, cons = [], []
    if trend.label in ("強勢多頭", "偏多"):
        pros.append(f"趨勢{trend.label}，均線結構支撐股價")
    elif trend.label in ("偏空", "強勢空頭"):
        cons.append(f"趨勢{trend.label}，逆勢承接風險較高")
    # 大盤狀態只在畫面上方顯示：回測顯示它和之後報酬呈反向關係，不適合當成有利／不利因素
    for i in items:
        if i.ok is True:
            pros.append(f"{i.name}：{i.detail}")
        elif i.ok is False:
            cons.append(f"{i.name}：{i.detail}")
    if sim and edges:
        s20 = next((s for s in sim.stats if s.horizon == 20), None)
        if s20:
            txt = f"相似歷史情況 20 日上漲機率 {s20.up_prob:.0%}（平常 {s20.base_up_prob:.0%}）"
            (pros if edge >= 0.02 else cons if edge <= -0.02 else []).append(txt)
    if rr is not None:
        txt = f"報酬風險比 {rr:.1f}（上看 {levels.resistance:,.2f}，停損 {levels.stop:,.2f}）"
        (pros if rr >= 1.5 else cons).append(txt)

    watch = []
    names_failed = {i.name for i in items if i.ok is False}
    if "長期趨勢向上" in names_failed and pd.notna(last["MA240"]):
        watch.append(f"站回年線 {last['MA240']:,.2f} 之上，且年線止跌回升")
    if "中期趨勢向上" in names_failed and pd.notna(last["MA60"]):
        watch.append(f"站穩季線 {last['MA60']:,.2f}，季線轉為上揚")
    if "沒有過熱" in names_failed:
        watch.append(f"漲多過熱，等待拉回月線 {last['MA20']:,.2f} 附近、RSI 降到 70 以下")
    if "接近支撐（拉回）" in names_failed and levels.support and c > levels.support:
        watch.append(f"拉回至支撐 {levels.support:,.2f} 附近不破")
    if "短線轉強" in names_failed:
        watch.append("KD 黃金交叉（K 向上穿越 D）且 MACD 柱狀體翻揚")
    if "量價健康" in names_failed:
        watch.append("上漲時出量、下跌時量縮")
    if "法人偏多" in names_failed:
        watch.append("外資或投信由賣轉買")

    if tone == "bull":
        summary = f"技術面與歷史統計偏有利，綜合評分 {score} 分。" + (f"若跌破 {levels.stop:,.2f} 代表判斷失效。")
    elif tone == "neutral":
        summary = f"多空訊號參半，綜合評分 {score} 分，尚未出現明確買點。"
    else:
        summary = f"多數條件不符合，綜合評分 {score} 分，目前不是統計上有利的進場位置。"
    return Rating(score, tier, tone, summary, comps, pros, cons, watch[:4])


# ---------- 新聞情緒（關鍵字判讀） ----------

_BULL_WORDS = ["大漲", "漲停", "創高", "新高", "買超", "調升", "上修", "看好", "利多", "強勢", "突破", "翻倍",
               "成長", "增長", "優於預期", "加碼", "旺", "攻上", "勁揚", "大單", "獲利創", "營收創", "雙位數成長", "目標價上",
               "飆", "季增", "年增", "再寫新", "噴發", "上攻", "首選"]
_BEAR_WORDS = ["大跌", "重挫", "跌停", "賣超", "調降", "下修", "看壞", "利空", "疲弱", "跌破", "衰退", "虧損",
               "不如預期", "減碼", "警訊", "砍單", "下滑", "失守", "崩", "賣壓", "目標價下", "降評",
               "暴跌", "狂殺", "殺逾", "摔", "提款", "泡沫", "季減", "年減", "腳軟"]


def tag_news(df: pd.DataFrame) -> pd.DataFrame:
    """用關鍵字粗略判斷標題偏多或偏空。"""
    out = df.copy()

    def tag(t: str) -> str:
        b = sum(w in t for w in _BULL_WORDS)
        s = sum(w in t for w in _BEAR_WORDS)
        return "偏多" if b > s else "偏空" if s > b else "中性"
    out["tone"] = out["title"].map(tag) if len(out) else []
    return out


# ---------- 綜合 ----------

def overall_signal(items: list[CheckItem], sim: SimilarResult | None) -> tuple[str, str]:
    """回傳（訊號等級, 說明）。只是統計訊號，不是買賣建議。"""
    applicable = [i for i in items if i.ok is not None]
    ratio = sum(i.ok for i in applicable) / len(applicable) if applicable else 0
    edge = None
    if sim:
        s20 = next((s for s in sim.stats if s.horizon == 20), None)
        if s20:
            edge = s20.up_prob - s20.base_up_prob
    notes = [f"檢查表符合 {sum(i.ok for i in applicable)}/{len(applicable)} 項"]
    if edge is not None:
        notes.append(f"相似情況 20 日上漲機率比平常{'高' if edge >= 0 else '低'} {abs(edge):.0%}")
    if ratio >= 0.65 and (edge is None or edge >= 0.03):
        level = "條件偏有利"
    elif ratio <= 0.35 or (edge is not None and edge <= -0.05):
        level = "條件偏不利"
    else:
        level = "條件中性"
    return level, "，".join(notes)


# ---------- 評分回測（逐日重算，只用當天以前的資料） ----------

def trend_score_series(d: pd.DataFrame) -> pd.DataFrame:
    """和 assess_trend 相同的規則，一次算出每一天的趨勢分數與滿分。"""
    c = d["close"]
    score = pd.Series(0.0, index=d.index)
    max_score = pd.Series(0.0, index=d.index)
    for ma, lag in [("MA20", 5), ("MA60", 20), ("MA240", 20)]:
        m = d[ma]
        ok = m.notna() & m.shift(lag).notna()
        pts = np.where(c > m, 1, -1) + np.where(m > m.shift(lag), 1, -1)
        score += np.where(ok, pts, 0)
        max_score += np.where(ok, 2, 0)
    all_ma = d[["MA20", "MA60", "MA240"]].notna().all(axis=1)
    align = np.where(d["MA20"].gt(d["MA60"]) & d["MA60"].gt(d["MA240"]), 1,
                     np.where(d["MA20"].lt(d["MA60"]) & d["MA60"].lt(d["MA240"]), -1, 0))
    score += np.where(all_ma, align, 0)
    max_score += np.where(all_ma, 1, 0)
    return pd.DataFrame({"score": score, "max": max_score})


def market_score_series(mkt: pd.DataFrame | None) -> pd.Series | None:
    if mkt is None or len(mkt) < 260:
        return None
    t = trend_score_series(add_indicators(mkt))
    return ((t["score"] / t["max"].replace(0, np.nan) + 1) * 50).clip(0, 100)


def historical_ratings(d: pd.DataFrame, mkt_score: pd.Series | None = None, step: int = 5,
                       start: int = 600) -> pd.DataFrame:
    """每隔 step 個交易日，用「當天以前」的資料重算一次評分各項目，並記錄之後的實際報酬。"""
    pc = price_checklist_series(d)
    ts = trend_score_series(d)
    fw20 = _forward(d, 20)["ret"]
    fw60 = _forward(d, 60)["ret"]
    if mkt_score is not None:
        mkt_score = mkt_score.reindex(d.index, method="ffill")
    rows = []
    pre = similar_prep(d)
    for t in range(start, len(d), step):
        sub = d.iloc[: t + 1]
        date = d.index[t]
        trend = Trend("", int(ts["score"].iloc[t]), int(ts["max"].iloc[t]))
        sim = similar_situations(d, pre=pre, end=t)
        lv = key_levels(sub)
        ms = None if mkt_score is None or pd.isna(mkt_score.iloc[t]) else mkt_score.iloc[t]
        comps = rating_components(sub.iloc[-1], trend, list(pc.iloc[t].values), sim, lv, ms)
        rows.append({"date": date, **comps, "fwd20": fw20.iloc[t], "fwd60": fw60.iloc[t]})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


SCORE_BUCKETS = [(0, 43, "42 分以下"), (43, 57, "43–56 分"), (57, 70, "57–69 分"), (70, 101, "70 分以上")]


def score_bucket_table(hist: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """依評分區間統計之後 20／60 個交易日的實際表現。"""
    comp_cols = [k for k in WEIGHTS if k in hist.columns]
    h = hist.dropna(subset=["fwd20"]).copy()
    h["score"] = h[comp_cols].apply(lambda r: weighted_score(r.to_dict(), weights), axis=1)
    rows = []
    for lo, hi, name in SCORE_BUCKETS + [(0, 101, "全部（基準）")]:
        x = h[(h.score >= lo) & (h.score < hi)]
        if len(x):
            x60 = x["fwd60"].dropna()
            rows.append({"評分區間": name, "次數": len(x), "20日上漲機率": (x.fwd20 > 0).mean(),
                         "20日平均報酬": x.fwd20.mean(),
                         "60日上漲機率": (x60 > 0).mean() if len(x60) else np.nan,
                         "60日平均報酬": x60.mean() if len(x60) else np.nan})
    return pd.DataFrame(rows)
