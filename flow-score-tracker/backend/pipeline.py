# Last updated: 2026-03-18 12:20 ET
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

def score_all_sectors(finviz: FinvizClient, _ts_client,
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
            "perf_ytd": fv.get("perf_year", 0),  # 1-year perf as YTD proxy
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
    finviz = FinvizClient()
    uw = TradierOptionsClient()

    tickers = [t["ticker"] for t in ticker_sector_list]

    fund_flows = get_ici_fund_flows()
    equity_weekly = fund_flows["equity_weekly"]
    equity_avg = fund_flows["equity_4wk_avg"]

    sector_scores = score_all_sectors(finviz, None, equity_weekly, equity_avg)

    # Fetch all tickers + SPY in one Finviz batch call
    try:
        fv_batch = finviz.get_ticker_data(tickers + ["SPY"])
    except Exception as e:
        print(f"  Finviz error: {e}")
        fv_batch = {}

    # Fetch SMA data separately via TradingView (Finviz API has no SMA columns)
    try:
        from tradingview_screener import Query, col as tv_col
        import time
        time.sleep(1.5)  # pause after Finviz HTTP requests
        equity_tickers = [t for t in tickers if len(t) <= 5]
        if equity_tickers:
            _, df_sma = (Query()
                .select("name", "close", "SMA20", "SMA50", "SMA200", "RSI", "High.52W", "Low.52W")
                .set_markets("america")
                .where(tv_col("name").isin(equity_tickers))
                .limit(len(equity_tickers) + 10)
                .get_scanner_data()
            )
            sma_hit = 0
            for _, row in df_sma.iterrows():
                t = str(row["name"]).strip()
                if t in fv_batch:
                    fv_batch[t].update({
                        "sma20":  round(float(row["SMA20"] or 0), 2),
                        "sma50":  round(float(row["SMA50"] or 0), 2),
                        "sma200": round(float(row["SMA200"] or 0), 2),
                        "rsi":    float(row["RSI"] or 50),
                    })
                    sma_hit += 1
            print(f"  Pipeline SMA: {sma_hit}/{len(equity_tickers)} tickers")
    except Exception as e:
        print(f"  Pipeline SMA error: {e}")

    # SPY 63-day perf from Finviz perf_quarter field
    spy_fv = fv_batch.get("SPY", {})
    spy_perf_63d = spy_fv.get("perf_quarter", 0)
    spy_price = spy_fv.get("price", 0)
    spy_ma200 = spy_fv.get("sma200", 0)
    spy_above_200ma = bool(spy_price > spy_ma200) if spy_ma200 else True

    results = []
    for item in ticker_sector_list:
        ticker = item["ticker"]
        sector = item.get("sector", "")
        print(f"  Scoring {ticker}...")
        try:
            bars = []  # No bar data — all signals use Finviz

            fv = fv_batch.get(ticker, {})
            price = fv.get("price", 0)
            ma50 = fv.get("sma50", 0)
            ma200 = fv.get("sma200", 0)
            ma20 = fv.get("sma20", price)  # use actual 20MA if available

            try:
                uw_flow = uw.get_flow_for_ticker(ticker)
                uw_unusual = uw.get_unusual_activity(ticker)
                merged_flow = {**uw_flow, **uw_unusual}
            except:
                merged_flow = {}

            sector_rank = get_sector_rank_for_ticker(sector, sector_scores)
            sector_ytd = get_sector_perf(sector, sector_scores)
            sector_etf_flow = 0
            sector_perf_63d = 0
            for s in sector_scores:
                if sector.lower() in s["sector"].lower():
                    etf_perf_3m = s.get("ytd_perf", 0)
                    sector_etf_flow = etf_perf_3m * 50  # scale: 10% → $500M proxy
                    sector_perf_63d = etf_perf_3m
                    break

            l1 = score_capital_flow_level1(equity_weekly, equity_avg, spy_above_200ma)
            l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
            l3 = score_capital_flow_level3(bars, fv, merged_flow,
                                            spy_perf_63d=spy_perf_63d,
                                            sector_perf_63d=sector_perf_63d)
            capital_flow = score_capital_flow_pillar(l1, l2, l3)
            trend = score_trend_pillar(price, ma20, ma50, ma200, bars)
            momentum = score_momentum_pillar(bars, fv, spy_perf_63d, sector_perf_63d)

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
    sector_scores = score_all_sectors(finviz, None, equity_weekly, equity_avg)
    save_sector_scores(sb, sector_scores)
    print(f"  Sectors scored. Top: {sector_scores[0]['sector']} ({sector_scores[0]['flow_score']})")

    # --- Finviz batch fetch (tickers + SPY for RS baseline) ---
    try:
        fv_batch = finviz.get_ticker_data(tickers + ["SPY"])
    except Exception as e:
        print(f"  Finviz error: {e}")
        fv_batch = {}

    # Fetch SMA data separately via TradingView
    try:
        from tradingview_screener import Query, col as tv_col
        import time
        time.sleep(1.5)
        equity_tickers_w = [t for t in tickers if len(t) <= 5]
        if equity_tickers_w:
            _, df_sma_w = (Query()
                .select("name", "close", "SMA20", "SMA50", "SMA200", "RSI")
                .set_markets("america")
                .where(tv_col("name").isin(equity_tickers_w))
                .limit(len(equity_tickers_w) + 10)
                .get_scanner_data()
            )
            for _, row in df_sma_w.iterrows():
                t = str(row["name"]).strip()
                if t in fv_batch:
                    fv_batch[t].update({
                        "sma20":  round(float(row["SMA20"] or 0), 2),
                        "sma50":  round(float(row["SMA50"] or 0), 2),
                        "sma200": round(float(row["SMA200"] or 0), 2),
                        "rsi":    float(row["RSI"] or 50),
                    })
            print(f"  Weekly SMA: fetched for {len(df_sma_w)} tickers")
    except Exception as e:
        print(f"  Weekly SMA error: {e}")

    # --- SPY 63-day perf from Finviz perf_quarter ---
    spy_fv2 = fv_batch.get("SPY", {})
    spy_perf_63d = spy_fv2.get("perf_quarter", 0)
    spy_price2 = spy_fv2.get("price", 0)
    spy_ma200_2 = spy_fv2.get("sma200", 0)
    spy_above_200ma = bool(spy_price2 > spy_ma200_2) if spy_ma200_2 else True

    results = []
    for w in watchlist:
        ticker = w["ticker"]
        sector = w.get("sector", "")
        print(f"  Scoring {ticker}...")

        try:
            bars = []  # No bar data — all signals use Finviz

            fv = fv_batch.get(ticker, {})
            price = fv.get("price", 0)
            ma50 = fv.get("sma50", 0)
            ma200 = fv.get("sma200", 0)
            ma20 = fv.get("sma20", price)  # use actual 20MA if available

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
            sector_perf_63d = 0
            for s in sector_scores:
                if sector.lower() in s["sector"].lower():
                    etf_perf_3m = s.get("ytd_perf", 0)
                    sector_etf_flow = etf_perf_3m * 50  # scale: 10% perf → $500M proxy
                    sector_perf_63d = etf_perf_3m
                    break

            # PILLAR 1: Capital Flow
            l1 = score_capital_flow_level1(equity_weekly, equity_avg, spy_above_200ma)
            l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
            l3 = score_capital_flow_level3(bars, fv, merged_flow,
                                            spy_perf_63d=spy_perf_63d,
                                            sector_perf_63d=sector_perf_63d)
            capital_flow = score_capital_flow_pillar(l1, l2, l3)

            # PILLAR 2: Trend
            trend = score_trend_pillar(price, ma20, ma50, ma200, bars)

            # PILLAR 3: Momentum
            momentum = score_momentum_pillar(bars, fv, spy_perf_63d, sector_perf_63d)

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

    # Weekly sector snapshot (for WoW rotation tracking)
    save_sector_snapshot(sb, sector_scores)

    # Score change + sector transition detection (for email alerts)
    score_changes = get_score_changes(sb, results)
    sector_transitions = get_sector_transitions(sb, sector_scores)

    print(f"[{datetime.now()}] Weekly Flow Score complete. {len(results)} tickers.")
    print(f"  Surges: {len(score_changes['surges'])} | Fades: {len(score_changes['fades'])}")
    print(f"  Sector transitions: {len(sector_transitions)}")

    # Attach meta for email report
    results.append({
        "_is_meta": True,
        "score_changes": score_changes,
        "sector_transitions": sector_transitions,
    })
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
            price = fv.get("price", 0)
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


def save_sector_snapshot(sb, sector_scores: list):
    """
    Save weekly sector snapshot every Friday (or on manual weekly run).
    Preserves one row per sector per week for WoW rotation tracking.
    """
    # Use Friday's date as the week_ending anchor
    today = date.today()
    days_since_friday = (today.weekday() - 4) % 7
    week_ending = (today - timedelta(days=days_since_friday)).isoformat()

    for s in sector_scores:
        row = {
            "week_ending": week_ending,
            "sector": s["sector"],
            "etf": s.get("etf", ""),
            "flow_score": s["flow_score"],
            "capital_flow": s["capital_flow"],
            "trend": s["trend"],
            "momentum": s["momentum"],
            "etf_flow_m": s.get("etf_flow_m", 0),
            "ytd_perf": s.get("ytd_perf", 0),
            "status": s["status"],
            "rank": s.get("rank", 0),
        }
        sb.table("sector_snapshots").upsert(row, on_conflict="week_ending,sector").execute()

    print(f"  Sector snapshots saved for week ending {week_ending}")


def get_sector_transitions(sb, current_scores: list) -> list:
    """
    Compare current sector scores against last week's snapshot.
    Returns list of notable transitions:
      - NEUTRAL → LEADING (score crossed 70)
      - LEADING → NEUTRAL (score dropped below 70)
      - Large score jumps (±10 pts)
    """
    try:
        # Get most recent prior snapshot (before this week)
        today = date.today()
        days_since_friday = (today.weekday() - 4) % 7
        this_week = (today - timedelta(days=days_since_friday)).isoformat()

        result = sb.table("sector_snapshots") \
            .select("*") \
            .lt("week_ending", this_week) \
            .order("week_ending", desc=True) \
            .limit(11) \
            .execute()

        prior = {r["sector"]: r for r in (result.data or [])}
        if not prior:
            return []

        transitions = []
        for s in current_scores:
            sector = s["sector"]
            curr_score = s["flow_score"]
            curr_status = s["status"]
            prev = prior.get(sector)
            if not prev:
                continue

            prev_score = prev["flow_score"]
            prev_status = prev["status"]
            delta = curr_score - prev_score

            transition = None

            # Status transitions
            if prev_status != "LEADING" and curr_status == "LEADING":
                transition = {
                    "sector": sector, "etf": s.get("etf", ""),
                    "type": "breakout",
                    "label": "→ LEADING",
                    "delta": delta,
                    "curr_score": curr_score,
                    "prev_score": prev_score,
                    "priority": 1,
                }
            elif prev_status == "LEADING" and curr_status != "LEADING":
                transition = {
                    "sector": sector, "etf": s.get("etf", ""),
                    "type": "breakdown",
                    "label": "LEADING →",
                    "delta": delta,
                    "curr_score": curr_score,
                    "prev_score": prev_score,
                    "priority": 2,
                }
            elif abs(delta) >= 10:
                transition = {
                    "sector": sector, "etf": s.get("etf", ""),
                    "type": "surge" if delta > 0 else "fade",
                    "label": f"{'+' if delta > 0 else ''}{delta:.0f} pts",
                    "delta": delta,
                    "curr_score": curr_score,
                    "prev_score": prev_score,
                    "priority": 3,
                }

            if transition:
                transitions.append(transition)

        transitions.sort(key=lambda x: x["priority"])
        return transitions

    except Exception as e:
        print(f"  Sector transition check error: {e}")
        return []


def get_score_changes(sb, current_results: list) -> dict:
    """
    Compare current weekly scores against prior week.
    Returns: { "surges": [...], "fades": [...] }
    Each item has ticker, curr_score, prev_score, delta, rating.
    """
    surges, fades = [], []
    try:
        tickers = [r["ticker"] for r in current_results]
        cutoff = (date.today() - timedelta(days=14)).isoformat()

        result = sb.table("weekly_scores") \
            .select("ticker,flow_score,date") \
            .in_("ticker", tickers) \
            .gte("date", cutoff) \
            .order("date", desc=True) \
            .execute()

        # Group by ticker, take two most recent
        from collections import defaultdict
        by_ticker = defaultdict(list)
        for row in (result.data or []):
            by_ticker[row["ticker"]].append(row)

        curr_map = {r["ticker"]: r for r in current_results}

        for ticker, rows in by_ticker.items():
            if len(rows) < 2:
                continue
            curr_score = curr_map.get(ticker, {}).get("flow_score", rows[0]["flow_score"])
            prev_score = rows[1]["flow_score"]  # second most recent
            delta = curr_score - prev_score

            item = {
                "ticker": ticker,
                "curr_score": curr_score,
                "prev_score": prev_score,
                "delta": delta,
                "rating": curr_map.get(ticker, {}).get("rating", ""),
                "sector": curr_map.get(ticker, {}).get("sector", ""),
            }

            if delta >= 15:
                surges.append(item)
            elif delta <= -15:
                fades.append(item)

        surges.sort(key=lambda x: x["delta"], reverse=True)
        fades.sort(key=lambda x: x["delta"])

    except Exception as e:
        print(f"  Score change check error: {e}")

    return {"surges": surges, "fades": fades}


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
