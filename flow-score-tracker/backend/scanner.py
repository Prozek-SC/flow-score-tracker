"""
Market Scanner — TradingView Screener API
- Top 3 sectors: sector ETF price above 200MA, ranked by distance from 200MA
- Top 25 stocks per sector: S&P 500 constituents ranked by RS vs sector ETF (63d)
- Unusual options activity: options volume/OI ratio spike
"""
import os
import json
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
        price = float(row.get('close') or 0)
        ma200 = float(row.get('SMA200') or 0)
        perf_3m = float(row.get('Perf.3M') or 0)
        perf_1m = float(row.get('Perf.1M') or 0)

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
    tv_sectors = [k for k, v in TV_SECTOR_MAP.items() if v == sector_name]
    if not tv_sectors:
        return []

    try:
        _, df = (Query()
            .select(
                'name', 'description', 'close', 'SMA200', 'SMA50',
                'Perf.3M', 'Perf.1M', 'Perf.W',
                'relative_volume_10d_calc', 'market_cap_basic', 'sector'
            )
            .set_markets('america')
            .where(
                col('sector').isin(tv_sectors),
                col('market_cap_basic') > 2e9,
                col('exchange').isin(['NASDAQ', 'NYSE']),
                col('is_primary') == True,
            )
            .order_by('market_cap_basic', ascending=False)
            .limit(150)
            .get_scanner_data()
        )
    except Exception as e:
        print(f"    TV screener error for {sector_name}: {e}")
        return []

    stocks = []
    for _, row in df.iterrows():
        price = float(row.get('close') or 0)
        ma200 = float(row.get('SMA200') or 0)
        ma50 = float(row.get('SMA50') or 0)
        perf_3m = float(row.get('Perf.3M') or 0)
        perf_1m = float(row.get('Perf.1M') or 0)
        rel_vol = float(row.get('relative_volume_10d_calc') or 0)
        mktcap = float(row.get('market_cap_basic') or 0)

        stocks.append({
            "ticker": row['name'],
            "name": row.get('description', row['name']),
            "price": round(price, 2),
            "ma200": round(ma200, 2),
            "ma50": round(ma50, 2),
            "above_200ma": price > ma200 if ma200 else None,
            "above_50ma": price > ma50 if ma50 else None,
            "perf_3m": round(perf_3m, 2),
            "perf_1m": round(perf_1m, 2),
            "rs_vs_etf": round(perf_3m - etf_perf_3m, 2),
            "rel_vol": round(rel_vol, 2),
            "mktcap_b": round(mktcap / 1e9, 1),
        })

    stocks.sort(key=lambda x: x["rs_vs_etf"], reverse=True)
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

    print("  Fetching sector ETF data...")
    try:
        top_sectors, all_sectors = get_top_sectors(top_n=3)
    except Exception as e:
        print(f"  Sector fetch error: {e}")
        return {}

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

    print("  Checking unusual options activity...")
    unusual = get_unusual_options(list(dict.fromkeys(all_top_tickers)))
    print(f"  Found {len(unusual)} unusual activity flags")

    output = {
        "run_date": date.today().isoformat(),
        "run_at": datetime.now().isoformat(),
        "top_sectors": top_sectors,
        "all_sectors": all_sectors,
        "sector_stocks": sector_stocks,
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
