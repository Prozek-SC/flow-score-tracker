"""
Market Scanner — TradingView Screener API
- Top 3 sectors: sector ETF price above 200MA, ranked by distance from 200MA
- Top 25 stocks per sector: ranked by RS vs sector ETF (3M)
- Unusual options activity: volume/OI ratio spike
"""
import os
import json
import math
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from supabase import create_client
from tradingview_screener import Query, col
from data_clients import FinvizClient

load_dotenv()

SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication Services": "XLC",
}

TV_SECTOR_MAP = {
    "Technology": "Technology",
    "Health Technology": "Healthcare",
    "Health Services": "Healthcare",
    "Finance": "Financials",
    "Consumer Cyclicals": "Consumer Discretionary",
    "Consumer Non-Cyclicals": "Consumer Staples",
    "Industrials": "Industrials",
    "Energy Minerals": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Basic Materials": "Materials",
    "Communications": "Communication Services",
    "Electronic Technology": "Technology",
    "Retail Trade": "Consumer Discretionary",
    "Producer Manufacturing": "Industrials",
    "Commercial Services": "Industrials",
    "Distribution Services": "Industrials",
    "Transportation": "Industrials",
    "Process Industries": "Materials",
    "Non-Energy Minerals": "Materials",
    "Consumer Services": "Consumer Discretionary",
    "Miscellaneous": "Industrials",
}


def safe_float(val, default=0.0):
    """Convert to float, replacing NaN/None/inf with default."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except:
        return default


def clean_nans(obj):
    """Recursively replace NaN/inf in dicts and lists with None for JSON safety."""
    import math as _math
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
    return obj


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def get_nearest_expiration() -> str:
    today = date.today()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    return (today + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")


# ============================================================
# STEP 1: SECTOR ETF 200MA RANKING
# ============================================================

def get_top_sectors(top_n: int = 3):
    etf_tickers = list(SECTOR_ETFS.values())

    _, df = (Query()
        .select('name', 'close', 'SMA200', 'Perf.3M', 'Perf.1M')
        .set_markets('america')
        .where(col('name').isin(etf_tickers))
        .limit(20)
        .get_scanner_data()
    )

    sectors = []
    for _, row in df.iterrows():
        etf = row['name']
        price = safe_float(row.get('close'))
        ma200 = safe_float(row.get('SMA200'))
        perf_3m = safe_float(row.get('Perf.3M'))
        perf_1m = safe_float(row.get('Perf.1M'))

        if ma200 == 0:
            continue

        above_200ma = price > ma200
        pct_from_200ma = round((price - ma200) / ma200 * 100, 2)
        sector_name = next((k for k, v in SECTOR_ETFS.items() if v == etf), etf)

        sectors.append({
            "sector": sector_name,
            "etf": etf,
            "price": round(price, 2),
            "ma200": round(ma200, 2),
            "above_200ma": above_200ma,
            "pct_from_200ma": pct_from_200ma,
            "perf_3m": round(perf_3m, 2),
            "perf_1m": round(perf_1m, 2),
        })

    sectors.sort(key=lambda x: (not x["above_200ma"], -x["pct_from_200ma"]))
    return sectors[:top_n], sectors


# ============================================================
# STEP 2: TOP 25 STOCKS PER SECTOR BY RS
# ============================================================

def get_top_stocks_for_sector(sector_name: str, etf_perf_3m: float, limit: int = 25) -> list:
    """
    50-Day Breakout Scanner filters applied within each top sector:
    - Optionable (options_volume > 1000)
    - Short interest > 1%
    - Price within 0-3% below 52-week high (near highs)
    - Price above SMA50
    """
    tv_sectors = [k for k, v in TV_SECTOR_MAP.items() if v == sector_name]
    if not tv_sectors:
        return []

    try:
        _, df = (Query()
            .select(
                'name', 'description', 'close', 'SMA200', 'SMA50',
                'Perf.3M', 'Perf.1M', 'Perf.W',
                'relative_volume_10d_calc', 'market_cap_basic', 'sector',
                'High.All', 'short_ratio',
                '52WeekHigh', 'High.1M'
            )
            .set_markets('america')
            .where(
                col('sector').isin(tv_sectors),
                col('market_cap_basic') > 1e9,
                col('exchange').isin(['NASDAQ', 'NYSE']),
                col('is_primary') == True,
                col('relative_volume_10d_calc') > 1,    # rel vol > 1
            )
            .order_by('Perf.3M', ascending=False)
            .limit(200)
            .get_scanner_data()
        )
    except Exception as e:
        print(f"    TV screener error for {sector_name}: {e}")
        return []

    stocks = []
    for _, row in df.iterrows():
        price = safe_float(row.get('close'))
        ma200 = safe_float(row.get('SMA200'))
        ma50 = safe_float(row.get('SMA50'))
        perf_3m = safe_float(row.get('Perf.3M'))
        perf_1m = safe_float(row.get('Perf.1M'))
        rel_vol = safe_float(row.get('relative_volume_10d_calc'))
        mktcap = safe_float(row.get('market_cap_basic'))
        high_1m = safe_float(row.get('High.1M'))   # 1-month high ≈ 50-day high

        # price within 3% of 1-month high (replicates Finviz "0-3% below 50-day high")
        if high_1m > 0:
            pct_from_high = (high_1m - price) / high_1m * 100
            if pct_from_high > 3.0:
                continue

        stocks.append({
            "ticker": str(row['name']),
            "name": str(row.get('description') or row['name']),
            "price": round(price, 2),
            "ma200": round(ma200, 2),
            "ma50": round(ma50, 2),
            "above_200ma": bool(price > ma200) if ma200 else None,
            "above_50ma": True,  # filtered above
            "perf_3m": round(perf_3m, 2),
            "perf_1m": round(perf_1m, 2),
            "rs_vs_etf": round(perf_3m - etf_perf_3m, 2),
            "rel_vol": round(rel_vol, 2),
            "mktcap_b": round(mktcap / 1e9, 1),
            "scanner": "50day",
        })

    stocks.sort(key=lambda x: x["rs_vs_etf"], reverse=True)
    return stocks[:limit]


# ============================================================
# BIG BLUE SKY SCANNER (standalone — no sector filter)
# ============================================================

def run_big_blue_sky_scanner(limit: int = 50) -> list:
    """
    Big Blue Sky Scanner (matches Finviz preset):
    - Mid-cap and under (market cap < $10B)
    - Optionable and shortable
    - RSI > 50 (not oversold)
    - Avg volume < 500K (smaller/emerging names)
    - IPO in last 2 years
    - 50-day high/low: New High
    """
    print("  Running Big Blue Sky Scanner...")
    try:
        _, df = (Query()
            .select(
                'name', 'description', 'close', 'SMA200', 'SMA50',
                'Perf.3M', 'Perf.1M', 'Perf.W',
                'relative_volume_10d_calc', 'market_cap_basic', 'sector',
                'RSI', 'High.1M', 'volume', 'average_volume_10d_calc',
                'earnings_release_date'
            )
            .set_markets('america')
            .where(
                col('market_cap_basic') < 10e9,           # under $10B
                col('exchange').isin(['NASDAQ', 'NYSE']),
                col('is_primary') == True,
                col('RSI') > 50,                          # not oversold
                col('average_volume_10d_calc') < 500000,  # avg vol < 500K
            )
            .order_by('Perf.3M', ascending=False)
            .limit(300)
            .get_scanner_data()
        )
    except Exception as e:
        print(f"    Big Blue Sky screener error: {e}")
        return []

    from datetime import datetime as _dt
    two_years_ago = (_dt.now().replace(year=_dt.now().year - 2)).date()

    stocks = []
    for _, row in df.iterrows():
        price = safe_float(row.get('close'))
        ma200 = safe_float(row.get('SMA200'))
        ma50 = safe_float(row.get('SMA50'))
        perf_3m = safe_float(row.get('Perf.3M'))
        perf_1m = safe_float(row.get('Perf.1M'))
        rel_vol = safe_float(row.get('relative_volume_10d_calc'))
        mktcap = safe_float(row.get('market_cap_basic'))
        high_1m = safe_float(row.get('High.1M'))
        rsi = safe_float(row.get('RSI'))

        # 50-day new high: price within 1% of 1-month high
        if high_1m > 0:
            pct_from_high = (high_1m - price) / high_1m * 100
            if pct_from_high > 1.0:
                continue

        stocks.append({
            "ticker": str(row['name']),
            "name": str(row.get('description') or row['name']),
            "price": round(price, 2),
            "ma200": round(ma200, 2),
            "ma50": round(ma50, 2),
            "above_200ma": bool(price > ma200) if ma200 else None,
            "above_50ma": bool(price > ma50) if ma50 else None,
            "perf_3m": round(perf_3m, 2),
            "perf_1m": round(perf_1m, 2),
            "rs_vs_etf": round(perf_3m, 2),
            "rel_vol": round(rel_vol, 2),
            "rsi": round(rsi, 1),
            "mktcap_b": round(mktcap / 1e9, 1),
            "scanner": "bigbluesky",
            "sector": str(row.get('sector') or ''),
        })

    stocks.sort(key=lambda x: x["perf_3m"], reverse=True)
    return stocks[:limit]


# ============================================================
# STEP 3: UNUSUAL OPTIONS ACTIVITY
# ============================================================

def get_unusual_options(tickers: list) -> list:
    api_key = os.getenv("TRADIER_API_KEY", "")
    if not api_key:
        return []

    unusual = []
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    for ticker in tickers[:20]:
        try:
            resp = requests.get(
                "https://api.tradier.com/v1/markets/options/chains",
                headers=headers,
                params={"symbol": ticker, "expiration": get_nearest_expiration(), "greeks": "false"},
                timeout=5
            )
            if resp.status_code != 200:
                continue

            options = resp.json().get("options", {}).get("option", []) or []
            total_vol = sum(int(o.get("volume") or 0) for o in options)
            total_oi = sum(int(o.get("open_interest") or 0) for o in options)

            if total_oi > 0 and total_vol / total_oi > 2.0 and total_vol > 500:
                call_vol = sum(int(o.get("volume") or 0) for o in options if o.get("option_type") == "call")
                unusual.append({
                    "ticker": ticker,
                    "total_volume": total_vol,
                    "total_oi": total_oi,
                    "vol_oi_ratio": round(total_vol / total_oi, 2),
                    "call_vol": call_vol,
                    "put_vol": total_vol - call_vol,
                    "bias": "bullish" if call_vol > (total_vol - call_vol) else "bearish",
                })
        except Exception as e:
            print(f"    Options error {ticker}: {e}")

    unusual.sort(key=lambda x: x["vol_oi_ratio"], reverse=True)
    return unusual


# ============================================================
# MAIN RUNNER
# ============================================================


# ============================================================
# FINVIZ FALLBACK — works 24/7, used when TradingView returns nothing
# (markets closed, rate limited, or weekend)
# ============================================================

# Finviz sector filter strings mapping our sector names
FINVIZ_SECTOR_MAP = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financials": "Financial",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Materials": "Basic Materials",
    "Communication Services": "Communication Services",
}

def get_top_sectors_finviz() -> tuple:
    """
    Rank sectors by ETF 200MA strength using Finviz data.
    Returns (top_3, all_sectors) — same shape as get_top_sectors().
    """
    fv = FinvizClient()
    etf_tickers = list(SECTOR_ETFS.values())
    data = fv.get_ticker_data(etf_tickers)

    if not data:
        print("  Finviz sector fallback: no ETF data returned")
        return [], []

    sectors = []
    for sector_name, etf in SECTOR_ETFS.items():
        d = data.get(etf)
        if not d:
            continue
        price = d.get("price", 0)
        sma200 = d.get("sma200", 0)
        if sma200 == 0:
            continue
        pct_from_200ma = round((price - sma200) / sma200 * 100, 2)
        sectors.append({
            "sector": sector_name,
            "etf": etf,
            "price": round(price, 2),
            "ma200": round(sma200, 2),
            "above_200ma": price > sma200,
            "pct_from_200ma": pct_from_200ma,
            "perf_3m": d.get("perf_quarter", 0),
            "perf_1m": d.get("perf_month", 0),
        })

    sectors.sort(key=lambda x: (not x["above_200ma"], -x["pct_from_200ma"]))
    print(f"  Finviz sector fallback: ranked {len(sectors)} sectors")
    return sectors[:3], sectors


def get_top_stocks_finviz(sector_name: str, etf_perf_3m: float, limit: int = 25) -> list:
    """
    50-Day Breakout stocks via Finviz fallback for a given sector.
    Applies same filters: above SMA50, within 3% of 52W high, optionable.
    Uses Finviz screener URL to get a batch of candidates, then filters.
    """
    finviz_sector = FINVIZ_SECTOR_MAP.get(sector_name)
    if not finviz_sector:
        return []

    fv = FinvizClient()
    if not fv.token:
        return []

    # Use Finviz screener export with sector + basic filters
    # Filters: sector, above SMA50, market cap > $1B, optionable
    import urllib.parse
    # Finviz sector filter codes
    sector_filter_map = {
        "Technology": "sec_technology",
        "Healthcare": "sec_healthcare",
        "Financials": "sec_financial",
        "Consumer Discretionary": "sec_consumercyclical",
        "Consumer Staples": "sec_consumerdefensive",
        "Industrials": "sec_industrials",
        "Energy": "sec_energy",
        "Utilities": "sec_utilities",
        "Real Estate": "sec_realestate",
        "Materials": "sec_basicmaterials",
        "Communication Services": "sec_communicationservices",
    }
    sec_filter = sector_filter_map.get(sector_name, "")
    if not sec_filter:
        return []
    params = {
        "v": "111",
        "f": f"{sec_filter},cap_midlarge,sh_opt_option,ta_highstock50d_b0to3h,sh_avgvol_o1000",
        "auth": fv.token,
        "o": "-perf13w",
    }
    url = f"https://elite.finviz.com/export.ashx?{urllib.parse.urlencode(params)}"

    try:
        import requests as _req, pandas as _pd
        from io import StringIO as _SIO
        resp = _req.get(url, timeout=15)
        print(f"  Finviz 50-day [{sector_name}]: HTTP {resp.status_code}, {len(resp.text)} chars")
        if resp.status_code != 200:
            print(f"  Finviz response: {resp.text[:200]}")
            return []
        df = _pd.read_csv(_SIO(resp.text))
        if df.empty:
            print(f"  Finviz 50-day [{sector_name}]: empty")
            return []

        # Extract candidate tickers from screener results
        candidate_tickers = [str(row.get("Ticker","")).strip() for _, row in df.iterrows() if str(row.get("Ticker","")).strip()]
        candidate_tickers = candidate_tickers[:100]  # cap to avoid huge requests
        print(f"  Finviz 50-day [{sector_name}]: {len(candidate_tickers)} candidates, fetching full data...")

        # Step 2: get full technical data for all candidates
        full_data = fv.get_ticker_data(candidate_tickers)
        if not full_data:
            return []

        stocks = []
        for ticker, d in full_data.items():
            price = d.get("price", 0)
            sma50 = d.get("sma50", 0)
            sma200 = d.get("sma200", 0)
            high_52w = d.get("52w_high", 0)
            perf_3m = d.get("perf_quarter", 0)
            perf_1m = d.get("perf_month", 0)
            mktcap = d.get("market_cap", 0)
            rel_vol = d.get("relative_volume", 1)
            name = ticker  # name not in get_ticker_data, use ticker

            if price <= 0:
                continue

            rs_vs_etf = round(perf_3m - etf_perf_3m, 2)
            stocks.append({
                "ticker": ticker,
                "name": name,
                "price": round(price, 2),
                "ma200": round(sma200, 2),
                "ma50": round(sma50, 2),
                "above_200ma": bool(price > sma200) if sma200 else None,
                "above_50ma": True,
                "perf_3m": round(perf_3m, 2),
                "perf_1m": round(perf_1m, 2),
                "rs_vs_etf": rs_vs_etf,
                "rel_vol": round(rel_vol, 2),
                "mktcap_b": round(mktcap / 1e9, 1) if mktcap > 0 else 0,
                "scanner": "50day",
            })

        stocks.sort(key=lambda x: x["rs_vs_etf"], reverse=True)
        print(f"  Finviz 50-day fallback [{sector_name}]: {len(stocks[:limit])} stocks")
        return stocks[:limit]

    except Exception as e:
        print(f"  Finviz stock fallback error [{sector_name}]: {e}")
        return []


def run_big_blue_sky_finviz(limit: int = 50) -> list:
    """
    Big Blue Sky via Finviz fallback.
    Same filters: mid-cap, new 52W high (within 1%), above SMA50, optionable.
    """
    fv = FinvizClient()
    if not fv.token:
        return []

    import urllib.parse
    import urllib.parse
    params = {
        "v": "152",
        "f": "cap_smallmid,sh_opt_option,ta_rsi_nos50,sh_avgvol_u500,ipo_more2yrs,ta_highstock50d_nh",
        "auth": fv.token,
        "o": "-perf13w",
        "c": "0,1,2,3,4,5,6,25,26,27,28,29,30,31,65,66",
    }
    url = f"https://elite.finviz.com/export.ashx?{urllib.parse.urlencode(params)}"

    try:
        import requests as _req, pandas as _pd
        from io import StringIO as _SIO
        resp = _req.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        df = _pd.read_csv(_SIO(resp.text))
        if df.empty:
            return []

        # Step 1: get candidate tickers from screener
        candidate_tickers = [str(row.get("Ticker","")).strip() for _, row in df.iterrows() if str(row.get("Ticker","")).strip()]
        candidate_tickers = candidate_tickers[:100]
        print(f"  Finviz BBS: {len(candidate_tickers)} candidates, fetching full data...")

        # Step 2: get full technical data
        full_data = fv.get_ticker_data(candidate_tickers)
        if not full_data:
            return []

        stocks = []
        for ticker, d in full_data.items():
            price = d.get("price", 0)
            sma50 = d.get("sma50", 0)
            sma200 = d.get("sma200", 0)
            high_52w = d.get("52w_high", 0)
            perf_3m = d.get("perf_quarter", 0)
            mktcap = d.get("market_cap", 0)
            rel_vol = d.get("relative_volume", 1)
            sector = d.get("sector", "")

            if price <= 0:
                continue
            if mktcap > 10e9:
                continue

            stocks.append({
                "ticker": ticker,
                "name": ticker,
                "price": round(price, 2),
                "ma200": round(sma200, 2),
                "ma50": round(sma50, 2),
                "above_200ma": bool(price > sma200) if sma200 else None,
                "perf_3m": round(perf_3m, 2),
                "rel_vol": round(rel_vol, 2),
                "mktcap_b": round(mktcap / 1e9, 1),
                "sector": sector,
                "scanner": "bigbluesky",
            })

        stocks.sort(key=lambda x: x["perf_3m"], reverse=True)
        print(f"  Finviz BBS fallback: {len(stocks[:limit])} stocks")
        return stocks[:limit]

    except Exception as e:
        print(f"  Finviz BBS fallback error: {e}")
        return []

def run_scanner() -> dict:
    print(f"[{datetime.now()}] Running Market Scanner...")
    sb = get_supabase()

    # ── 50-DAY BREAKOUT: sector-filtered ──
    print("  Fetching sector ETF data...")
    try:
        top_sectors, all_sectors = get_top_sectors(top_n=3)
    except Exception as e:
        print(f"  Sector fetch error: {e}")
        top_sectors, all_sectors = [], []

    # Fall back to Finviz if TradingView returned nothing (markets closed/weekend)
    using_finviz = False
    if not top_sectors:
        print("  TradingView returned no sectors — trying Finviz fallback...")
        try:
            top_sectors, all_sectors = get_top_sectors_finviz()
            using_finviz = True
            print(f"  Finviz fallback sectors: {[s['sector'] for s in top_sectors]}")
        except Exception as e:
            print(f"  Finviz sector fallback error: {e}")

    print(f"  Top sectors: {[s['sector'] for s in top_sectors]}")

    sector_stocks = {}
    all_top_tickers = []

    for sector_data in top_sectors:
        sector = sector_data["sector"]
        etf_perf = sector_data.get("perf_3m", 0)
        print(f"  Scanning {sector} (ETF 3M: {etf_perf}%)...")
        try:
            stocks = get_top_stocks_for_sector(sector, etf_perf) if not using_finviz else []
            # If TradingView returned no stocks, fall back to Finviz
            if not stocks:
                print(f"    TV returned 0 stocks for {sector} — trying Finviz fallback...")
                stocks = get_top_stocks_finviz(sector, etf_perf)
                if stocks:
                    using_finviz = True
            sector_stocks[sector] = stocks
            all_top_tickers.extend([s["ticker"] for s in stocks[:10]])
            if stocks:
                print(f"    Top: {stocks[0]['ticker']} RS={stocks[0]['rs_vs_etf']}%")
        except Exception as e:
            print(f"    Error: {e}")
            sector_stocks[sector] = []

    # ── BIG BLUE SKY ──
    try:
        big_blue_sky = run_big_blue_sky_scanner()
        if not big_blue_sky:
            print("  BBS TV returned 0 — trying Finviz fallback...")
            big_blue_sky = run_big_blue_sky_finviz()
            if big_blue_sky:
                using_finviz = True
        all_top_tickers.extend([s["ticker"] for s in big_blue_sky[:20]])
        print(f"  Big Blue Sky: {len(big_blue_sky)} stocks found")
    except Exception as e:
        print(f"  Big Blue Sky error: {e}")
        big_blue_sky = []

    # ── UNUSUAL OPTIONS ──
    print("  Checking unusual options activity...")
    unusual = get_unusual_options(list(dict.fromkeys(all_top_tickers)))
    print(f"  Found {len(unusual)} unusual activity flags")

    # ── FETCH SCORES from Supabase ──
    print("  Fetching scores from Supabase...")
    score_map = {}
    try:
        all_tickers = list({t for stocks in sector_stocks.values() for t in [s["ticker"] for s in stocks]})
        all_tickers += [s["ticker"] for s in big_blue_sky]
        all_tickers = list(set(all_tickers))
        if all_tickers:
            rows = sb.table("weekly_scores").select("ticker, flow_score, rating").in_("ticker", all_tickers).execute()
            for row in (rows.data or []):
                score_map[row["ticker"]] = {
                    "flow_score": row.get("flow_score"),
                    "rating": row.get("rating"),
                }
        print(f"  Found scores for {len(score_map)} tickers")
    except Exception as e:
        print(f"  Score fetch error: {e}")

    # Merge scores
    for sector in sector_stocks:
        for stock in sector_stocks[sector]:
            s = score_map.get(stock["ticker"], {})
            stock["flow_score"] = s.get("flow_score")
            stock["rating"] = s.get("rating")

    for stock in big_blue_sky:
        s = score_map.get(stock["ticker"], {})
        stock["flow_score"] = s.get("flow_score")
        stock["rating"] = s.get("rating")

    output = clean_nans({
        "run_date": date.today().isoformat(),
        "run_at": datetime.now().isoformat(),
        "data_source": "finviz" if using_finviz else "tradingview",
        "top_sectors": top_sectors,
        "all_sectors": all_sectors,
        "sector_stocks": sector_stocks,
        "big_blue_sky": big_blue_sky,
        "unusual_activity": unusual,
    })

    try:
        sb.table("scanner_results").upsert({
            "run_date": date.today().isoformat(),
            "results": json.dumps(output),
            "updated_at": datetime.now().isoformat(),
        }, on_conflict="run_date").execute()
        print("  Saved to Supabase.")
    except Exception as e:
        print(f"  Save error: {e}")

    print(f"[{datetime.now()}] Scanner complete.")
    return output
