"""多檔股票驗證買點評分：逐日用「當天以前」的資料重算評分，統計之後的實際報酬。

執行：python validate.py [股票數量，預設 60]
結果存到 cache/validation.pkl，網頁的「評分可信度」會讀取它。
約需 FinMind 查詢 2 次／檔，60 檔約 120 次（免費額度每小時 300 次）。
"""
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import analysis as A
import data

N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
OUT = data.CACHE_DIR / "validation.pkl"


def main():
    uni = data.universe().head(N)
    mkt = A.market_score_series(data.market_index())
    frames = []
    for i, r in enumerate(uni.itertuples(), 1):
        try:
            p = data.price_history(r.stock_id)
        except data.DataError as e:
            print(f"[{i}/{N}] {r.stock_id} 略過：{e}")
            continue
        if len(p) < 1000:
            print(f"[{i}/{N}] {r.stock_id} {r.name} 歷史太短，略過")
            continue
        t = time.time()
        h = A.historical_ratings(A.add_indicators(p), mkt)
        h["stock_id"] = r.stock_id
        frames.append(h)
        print(f"[{i}/{N}] {r.stock_id} {r.name}：{len(h)} 筆（{time.time() - t:.1f}s）", flush=True)
    allh = pd.concat(frames)
    pd.to_pickle({"hist": allh, "stocks": sorted(allh["stock_id"].unique()), "created": datetime.now()}, OUT)
    print(f"\n完成：{allh['stock_id'].nunique()} 檔、{len(allh):,} 筆，已存到 {OUT}")


if __name__ == "__main__":
    main()
