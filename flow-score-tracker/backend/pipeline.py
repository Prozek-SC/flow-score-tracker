"""
Flow Score Pipeline
Orchestrates weekly Flow Score + daily price updates
"""
import os
import json
import requests
import numpy as np
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from supabase import create_client

from alphavantage_client import AlphaVantageClient
from data_clients import FinvizClient, TradierOptionsClient
from scoring_engine import (
    score_capital_flow_level1, score_capital_flow_level2,
    score_capital_flow_level3, score_capital_flow_pillar,
    score_trend_pillar, score_momentum_pillar,
    calculate_flow_score, detect_burst_trade,
    calculate_sector_flow_score, SECTOR_ETFS
)

load_dotenv()


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def get_watchlist(sb) -> list:
    result = sb.table("watchlist").select("ticker,sector").eq("active", True).execute()
    return result.data or []


# ============================================================
# ICI FUND FLOW DATA (Level 1)
# Source: ICI.org weekly report — scraped or manually entered
# ============================================================

def get_ici_fund_flows() -> dict:
    """
    Fetch ICI fund flow data.
    ICI publishes weekly at ici.org/research/stats/weekly
    We use the most recent available figures.
    Falls back to cached Supabase data if fetch fails.
    """
    try:
        # ICI data endpoint (requires account — fallback to manual entry)
        # For now we use the fund flow data from the manual panel in the dashboard
        sb = get_supabase()
        result = sb.table("fund_flows").select("*").order("week_ending", desc=True).limit(5).execute()
        rows = result.data or []
        if rows:
            latest = rows[0]
            history = [{"week": r["week_ending"], "equity": r["equity_total"],
                        "bond": r["bond_total"], "commodity": r["commodity"]} for r in rows]
            avg_4wk = np.mean([r["equity_total"] for r in rows[:4]]) if len(rows) >= 4 else rows[0]["equity_total"]
            return {
                "equity_weekly": latest["equity_total"],
                "equity_domestic": latest.get("equity_domestic", 0),
                "equity_world": latest.get("equity_world", 0),
                "bond_weekly": latest.get("bond_total", 0),
                "commodity_weekly": latest.get("commodity", 0),
                "equity_4wk_avg": avg_4wk,
                "week_ending": latest["week_ending"],
                "history": history,
            }
    except Exception as e:
        print(f"  ICI fund flow fetch error: {e}")

    # Default neutral values if no data
    return {
        "equity_weekly": 0, "equity_domestic": 0, "equity_world": 0,
        "bond_weekly": 0, "commodity_weekly": 0, "equity_4wk_avg": 0,
        "week_ending": date.today().isoformat(), "history": []
    }


# ============================================================
# SECTOR SCORING
# ============================================================

def score_all_sectors(finviz: FinvizClient, ts_client: AlphaVantageClient,
                       equity_flow: float, equity_avg: float) -> list:
    """Score all 11 sector ETFs and return ranked list"""
    etf_tickers = list(SECTOR_ETFS.values())

    try:
        fv_data = finviz.get_ticker_data(etf_tickers)
    except Exception as e:
        print(f"  Finviz sector data error: {e}")
        fv_data = {}

    sector_scores = []
    for sector_name, etf in SECTOR_ETFS.items():
        fv = fv_data.get(etf, {})
        etf_data = {
            "price": fv.get("price", 0),
            "sma50": fv.get("sma50", 0),
            "sma200": fv.get("sma200", 0),
            "sma20": fv.get("price", 0),  # approximate
            "perf_ytd": fv.get("rs_rating", 0),  # Finviz Perf Year as proxy
            "perf_week": fv.get("perf_week", 0),
            "weekly_flow": fv.get("relative_volume", 1) * fv.get("avg_volume", 0) * fv.get("price", 0) / 1e6,
        }
        result = calculate_sector_flow_score(sector_name, etf_data, equity_flow, equity_avg)
        sector_scores.append(result)

    # Sort by flow score descending and assign rank
    sector_scores.sort(key=lambda x: x["flow_score"], reverse=True)
    for i, s in enumerate(sector_scores):
        s["rank"] = i + 1

    return sector_scores


def get_sector_rank_for_ticker(ticker_sector: str, sector_scores: list) -> int:
    """Find rank of a ticker's sector in the sector rankings"""
    for s in sector_scores:
        if ticker_sector.lower() in s["sector"].lower() or s["sector"].lower() in ticker_sector.lower():
            return s["rank"]
    return 6  # default neutral rank


def get_sector_perf(ticker_sector: str, sector_scores: list) -> float:
    for s in sector_scores:
        if ticker_sector.lower() in s["sector"].lower():
            return s.get("ytd_perf", 0)
    return 0


# ============================================================
# WEEKLY FLOW SCORE
# ============================================================

def score_tickers(ticker_sector_list: list) -> list:
    """
    Score an arbitrary list of [{"ticker": ..., "sector": ...}] dicts.
    Used by scanner to score top results without requiring watchlist membership.
    """
    print(f"[{datetime.now()}] Scoring {len(ticker_sector_list)} tickers...")
    sb = get_supabase()
    ts_client = AlphaVantageClient()
    finviz = FinvizClient()
    uw = TradierOptionsClient()

    tickers = [t["ticker"] for t in ticker_sector_list]

    fund_flows = get_ici_fund_flows()
    equity_weekly = fund_flows["equity_weekly"]
    equity_avg = fund_flows["equity_4wk_avg"]

    sector_scores = score_all_sectors(finviz, ts_client, equity_weekly, equity_avg)

    try:
        fv_batch = finviz.get_ticker_data(tickers)
    except Exception as e:
        print(f"  Finviz error: {e}")
        fv_batch = {}

    spy_perf_63d = 0
    try:
        spy_bars = ts_client.get_bars("SPY", bars_back=70)
        if spy_bars and len(spy_bars) >= 63:
            spy_now = float(spy_bars[-1].get("Close", 0))
            spy_63 = float(spy_bars[-63].get("Close", 0))
            spy_perf_63d = (spy_now - spy_63) / spy_63 * 100
    except:
        pass

    results = []
    for item in ticker_sector_list:
        ticker = item["ticker"]
        sector = item.get("sector", "")
        print(f"  Scoring {ticker}...")
        try:
            bars = []
            try:
                bars = ts_client.get_bars(ticker, bars_back=200)
            except Exception as e:
                print(f"    AlphaVantage error: {e}")

            fv = fv_batch.get(ticker, {})
            price = fv.get("price", 0)
            ma50 = fv.get("sma50", 0)
            ma200 = fv.get("sma200", 0)
            ma20 = price

            try:
                uw_flow = uw.get_flow_for_ticker(ticker)
                uw_unusual = uw.get_unusual_activity(ticker)
                merged_flow = {**uw_flow, **uw_unusual}
            except:
                merged_flow = {}

            sector_rank = get_sector_rank_for_ticker(sector, sector_scores)
            sector_ytd = get_sector_perf(sector, sector_scores)
            sector_etf_flow = 0
            for s in sector_scores:
                if sector.lower() in s["sector"].lower():
                    sector_etf_flow = s.get("etf_flow_m", 0)
                    break

            l1 = score_capital_flow_level1(equity_weekly, equity_avg)
            l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
            l3 = score_capital_flow_level3(bars, fv, merged_flow)
            capital_flow = score_capital_flow_pillar(l1, l2, l3)
            trend = score_trend_pillar(price, ma20, ma50, ma200, bars)
            momentum = score_momentum_pillar(bars, fv, spy_perf_63d, sector_ytd)

            result = calculate_flow_score(capital_flow, trend, momentum)
            result["ticker"] = ticker
            result["price"] = price
            result["sector"] = sector
            result["date"] = date.today().isoformat()

            prev = get_previous_score(sb, ticker)
            result["burst"] = detect_burst_trade(result["flow_score"], prev)

            results.append(result)
            save_weekly_score(sb, ticker, result)

        except Exception as e:
            print(f"  ERROR scoring {ticker}: {e}")

    print(f"[{datetime.now()}] Scored {len(results)} tickers.")
    return results


def run_weekly_flow_score():
    """
    Full Flow Score calculation. Run weekly (Fridays after close).
    """
    print(f"[{datetime.now()}] Running WEEKLY Flow Score...")
    sb = get_supabase()
    ts_client = AlphaVantageClient()
    finviz = FinvizClient()
    uw = TradierOptionsClient()

    watchlist = get_watchlist(sb)
    if not watchlist:
        print("  No tickers in watchlist.")
        return []

    tickers = [w["ticker"] for w in watchlist]

    # --- Level 1: ICI Fund Flows ---
    fund_flows = get_ici_fund_flows()
    equity_weekly = fund_flows["equity_weekly"]
    equity_avg = fund_flows["equity_4wk_avg"]
    print(f"  Equity flow: ${equity_weekly/1000:.1f}B (4wk avg: ${equity_avg/1000:.1f}B)")

    # --- Level 2: Sector Scores ---
    sector_scores = score_all_sectors(finviz, ts_client, equity_weekly, equity_avg)
    save_sector_scores(sb, sector_scores)
    print(f"  Sectors scored. Top: {sector_scores[0]['sector']} ({sector_scores[0]['flow_score']})")

    # --- Finviz batch fetch ---
    try:
        fv_batch = finviz.get_ticker_data(tickers)
    except Exception as e:
        print(f"  Finviz error: {e}")
        fv_batch = {}

    # --- SPY performance for RS calculation ---
    spy_perf_63d = 0
    try:
        spy_bars = ts_client.get_bars("SPY", bars_back=70)
        if spy_bars and len(spy_bars) >= 63:
            spy_now = float(spy_bars[-1].get("Close", 0))
            spy_63 = float(spy_bars[-63].get("Close", 0))
            spy_perf_63d = (spy_now - spy_63) / spy_63 * 100
    except:
        pass

    results = []
    for w in watchlist:
        ticker = w["ticker"]
        sector = w.get("sector", "")
        print(f"  Scoring {ticker}...")

        try:
            # Fetch bars
            bars = []
            try:
                bars = ts_client.get_bars(ticker, bars_back=200)
            except Exception as e:
                print(f"    AlphaVantage error: {e}")

            fv = fv_batch.get(ticker, {})
            price = fv.get("price", 0)
            ma50 = fv.get("sma50", 0)
            ma200 = fv.get("sma200", 0)
            ma20 = price  # approximate from price

            # Options flow
            uw_flow = {}
            uw_unusual = {}
            try:
                uw_flow = uw.get_flow_for_ticker(ticker)
                uw_unusual = uw.get_unusual_activity(ticker)
                merged_flow = {**uw_flow, **uw_unusual}
            except:
                merged_flow = {}

            # Sector context
            sector_rank = get_sector_rank_for_ticker(sector, sector_scores)
            sector_ytd = get_sector_perf(sector, sector_scores)
            sector_etf_flow = 0
            for s in sector_scores:
                if sector.lower() in s["sector"].lower():
                    sector_etf_flow = s.get("etf_flow_m", 0)
                    break

            # PILLAR 1: Capital Flow
            l1 = score_capital_flow_level1(equity_weekly, equity_avg)
            l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
            l3 = score_capital_flow_level3(bars, fv, merged_flow)
            capital_flow = score_capital_flow_pillar(l1, l2, l3)

            # PILLAR 2: Trend
            trend = score_trend_pillar(price, ma20, ma50, ma200, bars)

            # PILLAR 3: Momentum
            momentum = score_momentum_pillar(bars, fv, spy_perf_63d, sector_ytd)

            # COMPOSITE
            result = calculate_flow_score(capital_flow, trend, momentum)
            result["ticker"] = ticker
            result["price"] = price
            result["sector"] = sector
            result["date"] = date.today().isoformat()

            # Get previous score for burst detection
            prev = get_previous_score(sb, ticker)
            burst = detect_burst_trade(result["flow_score"], prev)
            result["burst"] = burst

            results.append(result)
            save_weekly_score(sb, ticker, result)

        except Exception as e:
            print(f"  ERROR scoring {ticker}: {e}")

    # Capital Flow Leaders & Exits
    save_flow_leaders_exits(sb, results)

    print(f"[{datetime.now()}] Weekly Flow Score complete. {len(results)} tickers.")
    return results


# ============================================================
# DAILY PRICE UPDATE (lightweight — no full rescore)
# ============================================================

def run_daily_price_update():
    """
    Daily update: refresh price, MA position, relative volume only.
    Does NOT recalculate full Flow Score (that's weekly).
    """
    print(f"[{datetime.now()}] Running daily price update...")
    sb = get_supabase()
    ts_client = AlphaVantageClient()
    finviz = FinvizClient()

    watchlist = get_watchlist(sb)
    if not watchlist:
        return

    tickers = [w["ticker"] for w in watchlist]

    try:
        fv_data = finviz.get_ticker_data(tickers)
    except:
        fv_data = {}

    updates = []
    for w in watchlist:
        ticker = w["ticker"]
        fv = fv_data.get(ticker, {})

        try:
            quote = ts_client.get_quote(ticker) or {}
            price = fv.get("price", float(quote.get("Last", 0)))
            ma50 = fv.get("sma50", 0)
            ma200 = fv.get("sma200", 0)
            rel_vol = fv.get("relative_volume", 0)

            row = {
                "ticker": ticker,
                "date": date.today().isoformat(),
                "price": price,
                "ma50": ma50,
                "ma200": ma200,
                "relative_volume": rel_vol,
                "above_50ma": price > ma50 if ma50 else None,
                "above_200ma": price > ma200 if ma200 else None,
                "updated_at": datetime.now().isoformat(),
            }
            sb.table("daily_prices").upsert(row, on_conflict="ticker,date").execute()
            updates.append(ticker)
        except Exception as e:
            print(f"  Price update error {ticker}: {e}")

    print(f"  Updated {len(updates)} tickers.")


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_previous_score(sb, ticker: str) -> float:
    try:
        result = sb.table("weekly_scores") \
            .select("flow_score") \
            .eq("ticker", ticker) \
            .order("date", desc=True) \
            .limit(2) \
            .execute()
        rows = result.data or []
        return rows[1]["flow_score"] if len(rows) >= 2 else 0
    except:
        return 0


def save_weekly_score(sb, ticker: str, result: dict):
    row = {
        "ticker": ticker,
        "date": result.get("date", date.today().isoformat()),
        "flow_score": result.get("flow_score", 0),
        "rating": result.get("rating", ""),
        "label": result.get("label", ""),
        "action": result.get("action", ""),
        "price": result.get("price", 0),
        "sector": result.get("sector", ""),
        "pillars": json.dumps(result.get("pillars", {})),
        "burst": json.dumps(result.get("burst", {})),
        "scored_at": result.get("scored_at", datetime.now().isoformat()),
    }
    sb.table("weekly_scores").upsert(row, on_conflict="ticker,date").execute()


def save_sector_scores(sb, sector_scores: list):
    for s in sector_scores:
        row = {
            "date": date.today().isoformat(),
            "sector": s["sector"],
            "etf": s["etf"],
            "flow_score": s["flow_score"],
            "capital_flow": s["capital_flow"],
            "trend": s["trend"],
            "momentum": s["momentum"],
            "etf_flow_m": s.get("etf_flow_m", 0),
            "ytd_perf": s.get("ytd_perf", 0),
            "status": s["status"],
            "rank": s["rank"],
        }
        sb.table("sector_scores").upsert(row, on_conflict="date,sector").execute()


def save_flow_leaders_exits(sb, results: list):
    """Save top 10 leaders and bottom 5 exits for dashboard panels"""
    sorted_results = sorted(results, key=lambda x: x.get("flow_score", 0), reverse=True)
    leaders = sorted_results[:10]
    exits = [r for r in sorted_results if r.get("flow_score", 50) < 40][:5]

    today = date.today().isoformat()
    sb.table("flow_leaders").delete().eq("date", today).execute()
    sb.table("flow_exits").delete().eq("date", today).execute()

    for r in leaders:
        sb.table("flow_leaders").insert({
            "date": today, "ticker": r["ticker"],
            "flow_score": r["flow_score"], "rating": r.get("rating", ""),
            "sector": r.get("sector", ""),
            "capital_flow": r.get("pillars", {}).get("capital_flow", {}).get("score", 0),
            "trend": r.get("pillars", {}).get("trend", {}).get("score", 0),
            "momentum": r.get("pillars", {}).get("momentum", {}).get("score", 0),
        }).execute()

    for r in exits:
        sb.table("flow_exits").insert({
            "date": today, "ticker": r["ticker"],
            "flow_score": r["flow_score"], "rating": r.get("rating", ""),
            "sector": r.get("sector", ""),
            "capital_flow": r.get("pillars", {}).get("capital_flow", {}).get("score", 0),
            "trend": r.get("pillars", {}).get("trend", {}).get("score", 0),
            "momentum": r.get("pillars", {}).get("momentum", {}).get("score", 0),
        }).execute()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "daily":
        run_daily_price_update()
    else:
        run_weekly_flow_score()
