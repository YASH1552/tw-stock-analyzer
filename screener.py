"""選股掃描與同產業比較。只用股價資料（每檔 2 次 FinMind 查詢，之後讀快取）。"""
import pandas as pd

import analysis as A
import data


def quick_rating(stock_id: str, market: A.MarketState | None) -> dict | None:
    """用和個股頁相同的價格面規則算出評分（不含法人、本益比、營收、融資）。"""
    p = data.price_history(stock_id)
    if len(p) < 260:
        return None
    d = A.add_indicators(p)
    trend = A.assess_trend(d)
    levels = A.key_levels(d)
    sim = A.similar_situations(d)
    oks = list(A.price_checklist_series(d).iloc[-1].values)
    comps = A.rating_components(d.iloc[-1], trend, oks, sim, levels, market.score if market else None)
    score = round(A.weighted_score(comps))
    s20 = next((s for s in sim.stats if s.horizon == 20), None) if sim else None
    c = d["close"]
    return {
        "評分": round(score), "評級": A.tier_of(score)[0], "趨勢": trend.label,
        "收盤": c.iloc[-1], "今日漲跌": c.iloc[-1] / c.iloc[-2] - 1,
        "20日漲跌": c.iloc[-1] / c.iloc[-21] - 1, "60日漲跌": c.iloc[-1] / c.iloc[-61] - 1,
        "120日漲跌": c.iloc[-1] / c.iloc[-121] - 1 if len(c) > 121 else float("nan"),
        "20日上漲機率": s20.up_prob if s20 else float("nan"),
        "平常上漲機率": s20.base_up_prob if s20 else float("nan"),
        "距停損": levels.stop / c.iloc[-1] - 1,
        "符合條件": f"{int(sum(bool(o) for o in oks if pd.notna(o)))}/{sum(pd.notna(o) for o in oks)}",
    }


def scan(stock_ids: list, names: dict, market: A.MarketState | None, progress=None) -> pd.DataFrame:
    rows = []
    for i, sid in enumerate(stock_ids, 1):
        if progress:
            progress(i, len(stock_ids), sid)
        try:
            r = quick_rating(sid, market)
        except data.DataError as e:
            if "上限" in str(e):  # 免費額度用完就停止，保留已完成的結果
                break
            continue
        if r:
            rows.append({"代號": sid, "名稱": names.get(sid, ""), **r})
    df = pd.DataFrame(rows)
    return df.sort_values("評分", ascending=False).reset_index(drop=True) if len(df) else df


def peers(stock_id: str, industry: str, market: A.MarketState | None, n: int = 8) -> pd.DataFrame:
    """同產業成交金額最大的 n 檔（含自己），比較漲跌幅與評分。"""
    uni = data.universe()
    same = uni[(uni["industry"] == industry) & (uni["stock_id"] != stock_id)].head(n)
    ids = [stock_id] + same["stock_id"].tolist()
    names = dict(zip(uni["stock_id"], uni["name"]))
    names.setdefault(stock_id, "")
    return scan(ids, names, market)
