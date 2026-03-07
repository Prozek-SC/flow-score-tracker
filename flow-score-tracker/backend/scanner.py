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
                'option_volume', '52WeekHigh'
            )
            .set_markets('america')
            .where(
                col('sector').isin(tv_sectors),
                col('market_cap_basic') > 1e9,          # $1B+ (o1000 = optionable large enough)
                col('exchange').isin(['NASDAQ', 'NYSE']),
                col('is_primary') == True,
                col('close') > col('SMA50'),             # above 50MA (nos50)
                col('option_volume') > 1000,             # options volume > 1000 (o1000)
                col('short_ratio') > 1,                  # short interest ratio > 1 (optionshort o1)
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
        high_52w = safe_float(row.get('52WeekHigh'))

        # b0to3h: price within 0-3% below 52w high
        if high_52w > 0:
            pct_from_high = (high_52w - price) / high_52w * 100
            if pct_from_high > 3.0:
                continue  # skip — too far from 52w high

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
    Big Blue Sky Scanner:
    - Mid-cap and under (market cap < $10B)
    - Price < $500
    - New 52-week high (price within 1% of 52w high)
    - Above SMA50
    - Optionable (options volume > 1)
    - Short interest > 1%
    """
    print("  Running Big Blue Sky Scanner...")
    try:
        _, df = (Query()
            .select(
                'name', 'description', 'close', 'SMA200', 'SMA50',
                'Perf.3M', 'Perf.1M', 'Perf.W',
                'relative_volume_10d_calc', 'market_cap_basic', 'sector',
                'short_ratio', 'option_volume', '52WeekHigh'
            )
            .set_markets('america')
            .where(
                col('market_cap_basic') < 10e9,          # mid-cap and under
                col('market_cap_basic') > 3e8,           # at least $300M
                col('close') < 500,                      # under $500
                col('exchange').isin(['NASDAQ', 'NYSE']),
                col('is_primary') == True,
                col('close') > col('SMA50'),             # above 50MA
                col('option_volume') > 1,                # optionable
                col('short_ratio') > 1,                  # short interest > 1
            )
            .order_by('Perf.3M', ascending=False)
            .limit(300)
            .get_scanner_data()
        )
    except Exception as e:
        print(f"    Big Blue Sky screener error: {e}")
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
        high_52w = safe_float(row.get('52WeekHigh'))

        # nh: new 52-week high — price within 1% of 52w high
        if high_52w > 0:
            pct_from_high = (high_52w - price) / high_52w * 100
            if pct_from_high > 1.0:
                continue  # not at new high

        stocks.append({
            "ticker": str(row['name']),
            "name": str(row.get('description') or row['name']),
            "price": round(price, 2),
            "ma200": round(ma200, 2),
            "ma50": round(ma50, 2),
            "above_200ma": bool(price > ma200) if ma200 else None,
            "above_50ma": True,
            "perf_3m": round(perf_3m, 2),
            "perf_1m": round(perf_1m, 2),
            "rs_vs_etf": round(perf_3m, 2),  # no sector ETF baseline; use abs 3M perf
            "rel_vol": round(rel_vol, 2),
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

    print(f"  Top sectors: {[s['sector'] for s in top_sectors]}")

    sector_stocks = {}
    all_top_tickers = []

    for sector_data in top_sectors:
        sector = sector_data["sector"]
        etf_perf = sector_data.get("perf_3m", 0)
        print(f"  Scanning {sector} (ETF 3M: {etf_perf}%)...")
        try:
            stocks = get_top_stocks_for_sector(sector, etf_perf)
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

    output = {
        "run_date": date.today().isoformat(),
        "run_at": datetime.now().isoformat(),
        "top_sectors": top_sectors,
        "all_sectors": all_sectors,
        "sector_stocks": sector_stocks,
        "big_blue_sky": big_blue_sky,
        "unusual_activity": unusual,
    }

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
