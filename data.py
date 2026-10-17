"""從 FinMind 免費 API 抓取台股資料，並快取在本機 cache 資料夾。

使用 Python 內建的 ssl 預設設定（會讀取 Windows 憑證庫），
所以在有防毒軟體做 HTTPS 掃描的電腦上也能正常連線，不需關閉驗證。
"""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

API_URL = "https://api.finmindtrade.com/api/v4/data"
CACHE_DIR = Path(__file__).parent / "cache"
PRICE_START = "2008-01-01"
_SSL_CTX = ssl.create_default_context()


class DataError(Exception):
    pass


def _fetch(dataset: str, data_id: str = "", start_date: str = "") -> pd.DataFrame:
    params = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    url = API_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, context=_SSL_CTX, timeout=60) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("msg", "")
        except Exception:
            msg = ""
        if e.code == 402 or "upper limit" in msg:
            raise DataError("FinMind 免費查詢次數已達上限（每小時約 300 次），請稍後再試。") from e
        raise DataError(f"資料來源回應錯誤（HTTP {e.code}）：{msg}") from e
    except urllib.error.URLError as e:
        raise DataError(f"無法連線到資料來源，請確認網路：{e.reason}") from e
    if payload.get("status") != 200:
        raise DataError(f"資料來源回應錯誤：{payload.get('msg')}")
    return pd.DataFrame(payload.get("data", []))


def _last_close_time(now: datetime) -> datetime:
    """最近一次「收盤資料應已更新」的時間點（交易日 15:00 之後）。"""
    t = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if now < t:
        t -= timedelta(days=1)
    while t.weekday() >= 5:
        t -= timedelta(days=1)
    return t


RETRY_INCOMPLETE = timedelta(minutes=30)


def _latest_date(df: pd.DataFrame):
    if df.empty:
        return None
    idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.get("date"), errors="coerce")
    return None if idx is None or len(idx) == 0 else pd.Timestamp(idx.max()).date()


def _cached(name: str, loader, max_age: timedelta | None = None, daily: bool = False) -> pd.DataFrame:
    """讀取快取，過期才重新下載。

    - max_age：固定時間後過期（新聞、股票清單）。
    - daily：每日收盤資料。快取在最近一次收盤更新（交易日 15:00）前產生就過期；
      若下載到的資料還沒有當天日期（資料源尚未更新），只保留 30 分鐘就再試一次。
    下載失敗時，若有舊快取就先用舊的，避免整個頁面無法使用。
    """
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{name}.pkl"
    now = datetime.now()
    entry = None
    if path.exists():
        try:
            entry = pd.read_pickle(path)
        except Exception:
            entry = None
        if not isinstance(entry, dict):  # 舊版快取格式，直接重抓
            entry = None
    if entry is not None:
        fetched = entry["fetched"]
        if max_age:
            fresh = now - fetched < max_age
        elif entry.get("complete", True):
            fresh = fetched >= _last_close_time(now)
        else:
            fresh = now - fetched < RETRY_INCOMPLETE
        if fresh:
            return entry["df"]
    try:
        df = loader()
    except DataError:
        if entry is not None:
            return entry["df"]
        raise
    complete = True
    if daily:
        latest = _latest_date(df)
        complete = latest is not None and latest >= _last_close_time(now).date()
    pd.to_pickle({"df": df, "fetched": now, "complete": complete}, path)
    return df


def stock_list() -> pd.DataFrame:
    """所有上市櫃股票代號、名稱、產業。"""
    def load():
        df = _fetch("TaiwanStockInfo")
        # 同一檔股票可能有多個產業分類，優先用具體的（例如「半導體業」而非「電子工業」）
        generic = {"電子工業", "所有證券", "其他", "Index", "大盤"}
        df["_generic"] = df["industry_category"].isin(generic)
        df = df.sort_values(["_generic", "date"], ascending=[False, True]).drop_duplicates("stock_id", keep="last")
        return df[["stock_id", "stock_name", "industry_category", "type"]].reset_index(drop=True)
    return _cached("stock_list2", load, max_age=timedelta(days=7))


def find_stock(query: str) -> pd.DataFrame:
    """用代號或名稱搜尋股票，回傳符合的列（代號完全相符者優先）。"""
    q = query.strip()
    sl = stock_list()
    exact = sl[sl.stock_id.str.upper() == q.upper()]
    if not exact.empty:
        return exact
    # 只列一般股票（4 碼）和 ETF（00 開頭），排除權證等衍生商品
    sl = sl[sl.stock_id.str.match(r"^(\d{4}|00\d{2,4}[A-Z]?)$")]
    hits = sl[sl.stock_name.str.contains(q, regex=False) | sl.stock_id.str.startswith(q)].copy()
    hits["_rank"] = (hits.stock_name != q).astype(int) * 2 + (~hits.stock_name.str.startswith(q)).astype(int)
    return hits.sort_values(["_rank", "stock_id"]).drop(columns="_rank")


def _adjust(price: pd.DataFrame, divs: pd.DataFrame) -> pd.DataFrame:
    """把除權息、分割造成的價格跳空還原（向前調整），讓回測報酬正確。"""
    p = price.copy()
    factor = pd.Series(1.0, index=p.index)
    div_dates = set()
    if not divs.empty:
        for _, d in divs.iterrows():
            date = pd.Timestamp(d["date"])
            if d["before_price"] > 0 and d["after_price"] > 0 and date in factor.index:
                factor[date] *= d["after_price"] / d["before_price"]
                div_dates.add(date)
    # 股票分割 / 減資：用「參考價 ÷ 前日收盤」偵測大幅跳動
    ref = p["close"] - p["spread"]
    f = ref / p["close"].shift()
    big = f[((f - 1).abs() > 0.15) & (f > 0.05) & (f < 20)]
    for date, v in big.items():
        if date not in div_dates:
            factor[date] *= v
    # 某日的因子要套用到它之前的所有價格
    cum = factor[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    for col in ["open", "high", "low", "close"]:
        p[col] = p[col] * cum
    p["volume"] = p["volume"] / cum
    return p


def price_history(stock_id: str) -> pd.DataFrame:
    """還原後的日 K 資料，index 為日期。"""
    def load():
        df = _fetch("TaiwanStockPrice", stock_id, PRICE_START)
        if df.empty:
            raise DataError(f"找不到 {stock_id} 的股價資料。")
        df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["close"] > 0].set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume", "spread"]].astype(float)
        try:
            time.sleep(0.3)
            divs = _fetch("TaiwanStockDividendResult", stock_id, PRICE_START)
        except DataError:
            divs = pd.DataFrame()
        df = _adjust(df, divs)
        df["volume"] = df["volume"] / 1000  # 股 → 張
        return df.drop(columns="spread")
    return _cached(f"price_{stock_id}", load, daily=True)


def institutional(stock_id: str) -> pd.DataFrame:
    """三大法人每日買賣超（張）：外資、投信、自營商。"""
    def load():
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = _fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start)
        if df.empty:
            return pd.DataFrame(columns=["外資", "投信", "自營商"])
        df["net"] = (df["buy"] - df["sell"]) / 1000
        groups = {
            "Foreign_Investor": "外資", "Foreign_Dealer_Self": "外資",
            "Investment_Trust": "投信",
            "Dealer_self": "自營商", "Dealer_Hedging": "自營商", "Dealer": "自營商",
        }
        df["who"] = df["name"].map(groups)
        out = df.dropna(subset=["who"]).pivot_table(index="date", columns="who", values="net", aggfunc="sum")
        out.index = pd.to_datetime(out.index)
        return out.reindex(columns=["外資", "投信", "自營商"]).fillna(0)
    return _cached(f"inst_{stock_id}", load, daily=True)


def news(stock_id: str, name: str, days: int = 7) -> pd.DataFrame:
    """近期相關新聞（Google 新聞 RSS，個人使用免費），每小時更新一次。"""
    def load():
        q = urllib.parse.quote(f"{name} 股 when:{days}d")
        url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
                root = ET.fromstring(resp.read())
        except (urllib.error.URLError, ET.ParseError) as e:
            raise DataError(f"無法取得新聞：{e}") from e
        rows = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            src = item.find("source")
            source = src.text if src is not None and src.text else ""
            site = urllib.parse.urlparse(src.get("url", "")).netloc.removeprefix("www.") if src is not None else ""
            # 標題以「 - 來源」結尾，去掉避免重複
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            rows.append({"date": item.findtext("pubDate", ""), "title": title.strip(),
                         "source": source, "site": site, "link": item.findtext("link", "")})
        df = pd.DataFrame(rows, columns=["date", "title", "source", "site", "link"])
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
        df = df[~df["source"].isin(["Facebook", "Instagram", "YouTube"])]  # 社群貼文雜訊多
        df = df.dropna(subset=["date"]).drop_duplicates("title").sort_values("date", ascending=False)
        return df.reset_index(drop=True)
    return _cached(f"news2_{stock_id}", load, max_age=timedelta(hours=1))


def market_index() -> pd.DataFrame:
    """加權指數（TAIEX）日 K。"""
    def load():
        df = _fetch("TaiwanStockPrice", "TAIEX", PRICE_START)
        if df.empty:
            raise DataError("找不到加權指數資料。")
        df = df.rename(columns={"max": "high", "min": "low", "Trading_money": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["close"] > 0].set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df["volume"] = df["volume"] / 1e8  # 成交金額（億元）
        return df
    return _cached("market_TAIEX", load, daily=True)


def month_revenue(stock_id: str) -> pd.DataFrame:
    """月營收（元），index 為營收月份的第一天；含年增率與月增率。"""
    def load():
        start = (datetime.now() - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
        df = _fetch("TaiwanStockMonthRevenue", stock_id, start)
        if df.empty:
            return pd.DataFrame(columns=["revenue", "yoy", "mom"])
        df["month"] = pd.to_datetime(dict(year=df["revenue_year"], month=df["revenue_month"], day=1))
        df = df.drop_duplicates("month", keep="last").set_index("month").sort_index()[["revenue"]].astype(float)
        df["yoy"] = df["revenue"] / df["revenue"].shift(12) - 1
        df["mom"] = df["revenue"] / df["revenue"].shift(1) - 1
        return df
    return _cached(f"rev_{stock_id}", load, max_age=timedelta(hours=12))


def margin(stock_id: str) -> pd.DataFrame:
    """融資、融券餘額（張）與使用率。"""
    def load():
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = _fetch("TaiwanStockMarginPurchaseShortSale", stock_id, start)
        if df.empty:
            return pd.DataFrame(columns=["融資餘額", "融券餘額", "融資使用率", "券資比"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        out = pd.DataFrame(index=df.index)
        out["融資餘額"] = df["MarginPurchaseTodayBalance"].astype(float)
        out["融券餘額"] = df["ShortSaleTodayBalance"].astype(float)
        limit = df["MarginPurchaseLimit"].astype(float).replace(0, float("nan"))
        out["融資使用率"] = out["融資餘額"] / limit
        out["券資比"] = out["融券餘額"] / out["融資餘額"].replace(0, float("nan"))
        return out
    return _cached(f"margin_{stock_id}", load, daily=True)


def valuation(stock_id: str) -> pd.DataFrame:
    """每日本益比、股價淨值比、殖利率（ETF 通常沒有）。"""
    def load():
        start = (datetime.now() - timedelta(days=365 * 8)).strftime("%Y-%m-%d")
        df = _fetch("TaiwanStockPER", stock_id, start)
        if df.empty:
            return pd.DataFrame(columns=["PER", "PBR", "dividend_yield"])
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()[["PER", "PBR", "dividend_yield"]]
    return _cached(f"val_{stock_id}", load, daily=True)


def _get_json(url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception as e:  # 櫃買中心的大型檔案偶爾會傳到一半中斷，重試即可
            last = e
            time.sleep(1 + i)
    raise DataError(f"無法取得資料：{last}")


def universe() -> pd.DataFrame:
    """上市櫃全部股票最新一日的成交資料，用來挑選掃描範圍（依成交金額排序）。"""
    def load():
        rows = []
        for r in _get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"):
            rows.append({"stock_id": r["Code"], "name": r["Name"], "market": "上市",
                         "close": r["ClosingPrice"], "value": r["TradeValue"]})
        try:
            for r in _get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"):
                rows.append({"stock_id": r["SecuritiesCompanyCode"], "name": r["CompanyName"], "market": "上櫃",
                             "close": r["Close"], "value": r["TransactionAmount"]})
        except DataError:
            pass  # 櫃買中心抓不到時，只用上市股票
        df = pd.DataFrame(rows)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce") / 1e8  # 成交金額（億元）
        df = df[df["stock_id"].str.match(r"^\d{4}$") & df["close"].gt(0)]  # 只取一般股票
        ind = stock_list().drop_duplicates("stock_id").set_index("stock_id")["industry_category"]
        df["industry"] = df["stock_id"].map(ind)
        return df.sort_values("value", ascending=False).reset_index(drop=True)
    return _cached("universe", load, max_age=timedelta(hours=6))
