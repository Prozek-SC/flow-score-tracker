# Last updated: 2026-03-26 11:00 ET 
"""
Flow Score — Flask API Server
Weekly scoring at Friday 5pm ET + Daily price update at 7am ET
"""
import os
import json
import pytz
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from supabase import create_client

from pipeline import (run_weekly_flow_score, run_daily_price_update,
                      run_daily_score,
                      get_ici_fund_flows, score_tickers,
                      get_sector_transitions, get_score_changes)
from scanner import run_scanner
from email_report import send_weekly_report, send_daily_price_alert, send_scanner_report

load_dotenv()

app = Flask(__name__)
CORS(app)
ET = pytz.timezone("America/New_York")

US_HOLIDAYS = {
    # Add major market holidays here (expand annually)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}

def is_trading_day(dt=None) -> bool:
    """Returns True if dt (default: today ET) is a market trading day."""
    if dt is None:
        dt = datetime.now(ET).date()
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if dt.isoformat() in US_HOLIDAYS:
        return False
    return True


def get_sb():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


# ============================================================
# SCHEDULER
# ============================================================

def weekly_job():
    print(f"[SCHEDULER] Weekly Flow Score — {datetime.now(ET)}")
    results = run_weekly_flow_score()
    send_weekly_report(results)

def daily_job():
    print(f"[SCHEDULER] Daily price update — {datetime.now(ET)}")
    run_daily_price_update()
    send_daily_price_alert()

def scanner_job():
    print(f"[SCHEDULER] Morning scanner — {datetime.now(ET)}")
    try:
        results = run_scanner()

        # Score top 10 per sector + top 10 Big Blue Sky
        sector_stocks = results.get("sector_stocks", {})
        top_sectors = results.get("top_sectors", [])
        top10 = []
        for sector_data in top_sectors:
            sname = sector_data["sector"]
            stocks = sector_stocks.get(sname, [])
            top_in_sector = sorted(stocks, key=lambda s: s.get("rs_vs_etf", 0), reverse=True)[:25]
            for s in top_in_sector:
                top10.append({"ticker": s["ticker"], "sector": sname, "rs": s.get("rs_vs_etf", 0)})

        bbs = results.get("big_blue_sky", [])
        for s in bbs:
            top10.append({"ticker": s["ticker"], "sector": s.get("sector", ""), "rs": s.get("perf_3m", 0)})

        if top10:
            print(f"  Scoring {len(top10)} stocks (top 25/sector): {[t['ticker'] for t in top10]}")
            scored = score_tickers(top10)
            # Merge scores back into results for the email
            score_map = {r["ticker"]: r for r in scored}
            for sname, stocks in sector_stocks.items():
                for stock in stocks:
                    if stock["ticker"] in score_map:
                        stock["flow_score"] = score_map[stock["ticker"]].get("flow_score")
                        stock["rating"] = score_map[stock["ticker"]].get("rating")

        send_scanner_report(results)
    except Exception as e:
        print(f"  Scanner job error: {e}")

scheduler = BackgroundScheduler(timezone=ET)
# Weekly: Friday at 5:00 PM ET (after market close)
scheduler.add_job(weekly_job, CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=ET))
# Daily: 7:00 AM ET weekdays
scheduler.add_job(daily_job, CronTrigger(day_of_week="mon-fri", hour=7, minute=0, timezone=ET))
# Scanner: 7:05 AM ET weekdays (runs after daily price update)
scheduler.add_job(scanner_job, CronTrigger(day_of_week="mon-fri", hour=7, minute=5, timezone=ET))
# Daily trend score: 4:30 PM ET weekdays (after market close)
scheduler.add_job(
    lambda: run_daily_score(),
    CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
    id="daily_score_job"
)
scheduler.start()


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(ET).isoformat()})

@app.route("/api/debug")
def debug():
    """
    System health check — tests every data source and returns status.
    Hit this in browser to verify everything is wired up correctly.
    """
    report = {}

    # 1. Supabase
    try:
        sb = get_sb()
        wl = sb.table("watchlist").select("ticker").eq("active", True).execute()
        scores = sb.table("weekly_scores").select("ticker").order("date", desc=True).limit(1).execute()
        flows = sb.table("fund_flows").select("*").order("week_ending", desc=True).limit(1).execute()
        report["supabase"] = {
            "status": "ok",
            "watchlist_count": len(wl.data or []),
            "has_scores": len(scores.data or []) > 0,
            "latest_score_ticker": scores.data[0]["ticker"] if scores.data else None,
            "fund_flows_populated": len(flows.data or []) > 0,
            "latest_fund_flow": flows.data[0] if flows.data else "EMPTY — L1 using SPY fallback",
        }
    except Exception as e:
        report["supabase"] = {"status": "error", "message": str(e)}

    # 2. Finviz
    try:
        from data_clients import FinvizClient
        fv = FinvizClient()
        if fv.token:
            data = fv.get_ticker_data(["SPY", "TRGP"])
            spy = data.get("SPY", {})
            trgp = data.get("TRGP", {})
            report["finviz"] = {
                "status": "ok",
                "token_present": True,
                "parsed_SPY": {k: v for k, v in spy.items() if k in
                        ["price", "sma200", "perf_quarter", "perf_month", "perf_half", "perf_year", "perf_week"]},
                "parsed_TRGP": {k: v for k, v in trgp.items() if k in
                         ["price", "sma20", "sma50", "sma200", "perf_quarter", "perf_month",
                          "perf_half", "perf_year", "perf_week", "relative_volume", "sector"]},
            }
        else:
            report["finviz"] = {"status": "error", "message": "No FINVIZ_API_TOKEN set"}
    except Exception as e:
        report["finviz"] = {"status": "error", "message": str(e)}

    # 3. Scoring engine — simulate TRGP score with live data
    try:
        from data_clients import FinvizClient, TradierOptionsClient
        from pipeline import get_ici_fund_flows, score_all_sectors, get_sector_rank_for_ticker, get_sector_perf
        from scoring_engine import (score_capital_flow_level1, score_capital_flow_level2,
                                     score_capital_flow_level3, score_capital_flow_pillar,
                                     score_trend_pillar, score_momentum_pillar, calculate_flow_score)

        fv = FinvizClient()
        fv_batch = fv.get_ticker_data(["TRGP", "SPY"])
        spy_fv = fv_batch.get("SPY", {})
        trgp_fv = fv_batch.get("TRGP", {})

        spy_perf_63d = spy_fv.get("perf_quarter", 0)
        spy_price = spy_fv.get("price", 0)
        spy_ma200 = spy_fv.get("sma200", 0)
        spy_above_200ma = bool(spy_price > spy_ma200) if spy_ma200 else True

        fund_flows = get_ici_fund_flows()
        equity_weekly = fund_flows["equity_weekly"]
        equity_avg = fund_flows["equity_4wk_avg"]

        sector_scores = score_all_sectors(fv, None, equity_weekly, equity_avg)
        sector_rank = get_sector_rank_for_ticker("Energy", sector_scores)
        sector_ytd = get_sector_perf("Energy", sector_scores)
        sector_perf_63d = sector_ytd
        sector_etf_flow = sector_ytd * 50

        price = trgp_fv.get("price", 0)
        ma20 = trgp_fv.get("sma20", price)
        ma50 = trgp_fv.get("sma50", 0)
        ma200 = trgp_fv.get("sma200", 0)

        l1 = score_capital_flow_level1(equity_weekly, equity_avg, spy_above_200ma)
        l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
        l3 = score_capital_flow_level3([], trgp_fv, {}, spy_perf_63d=spy_perf_63d, sector_perf_63d=sector_perf_63d)
        cf = score_capital_flow_pillar(l1, l2, l3)
        trend = score_trend_pillar(price, ma20, ma50, ma200, [])
        mom = score_momentum_pillar([], trgp_fv, spy_perf_63d, sector_perf_63d)
        result = calculate_flow_score(cf, trend, mom)

        report["scoring_engine"] = {
            "status": "ok",
            "trgp_test": {
                "flow_score": result["flow_score"],
                "rating": result["rating"],
                "expected": "85-95 ELITE",
                "cf": cf["score"],
                "cf_l1": l1["score"],
                "cf_l1_detail": l1["detail"],
                "cf_l2": l2["score"],
                "cf_l2_detail": l2["detail"],
                "cf_l3": l3["score"],
                "cf_l3_detail": l3["detail"],
                "trend": trend["score"],
                "trend_detail": trend["detail"],
                "momentum": mom["score"],
                "momentum_detail": mom["detail"],
                "inputs": {
                    "spy_perf_63d": spy_perf_63d,
                    "spy_above_200ma": spy_above_200ma,
                    "equity_weekly_flow": equity_weekly,
                    "sector_rank": sector_rank,
                    "sector_ytd": sector_ytd,
                    "sector_etf_flow_proxy": sector_etf_flow,
                    "trgp_perf_quarter": trgp_fv.get("perf_quarter"),
                    "trgp_perf_month": trgp_fv.get("perf_month"),
                    "trgp_perf_half": trgp_fv.get("perf_half"),
                    "trgp_rel_vol": trgp_fv.get("relative_volume"),
                    "trgp_price": price,
                    "trgp_ma20": ma20,
                    "trgp_ma50": ma50,
                    "trgp_ma200": ma200,
                }
            }
        }
    except Exception as e:
        import traceback
        report["scoring_engine"] = {"status": "error", "message": str(e), "trace": traceback.format_exc()}

    # 4. Scanner results
    try:
        sb = get_sb()
        result = sb.table("scanner_results").select("run_date, updated_at").order("run_date", desc=True).limit(1).execute()
        report["scanner"] = {
            "status": "ok",
            "last_run": result.data[0] if result.data else "No scans yet"
        }
    except Exception as e:
        report["scanner"] = {"status": "error", "message": str(e)}

    return jsonify(report)

def _tv_sma_test(ticker):
    """Direct TradingView SMA test — returns raw result or error."""
    try:
        from tradingview_screener import Query, col as tv_col
        _, df = (Query()
            .select("name", "close", "SMA20", "SMA50", "SMA200")
            .set_markets("america")
            .where(tv_col("name").isin([ticker]))
            .limit(5)
            .get_scanner_data()
        )
        if len(df) == 0:
            return {"error": "no rows returned", "ticker": ticker}
        row = df.iloc[0]
        return {
            "name": str(row["name"]),
            "SMA20": float(row["SMA20"] if row["SMA20"] is not None else 0),
            "SMA50": float(row["SMA50"] if row["SMA50"] is not None else 0),
            "SMA200": float(row["SMA200"] if row["SMA200"] is not None else 0),
        }
    except Exception as e:
        return {"error": str(e)}


@app.route("/api/diagnose/<ticker>")
def diagnose_ticker(ticker):
    """
    Full scoring breakdown for any ticker.
    Usage: /api/diagnose/TRGP?sector=Energy
    Shows every input and every sub-score so you can see exactly why a stock got its score.
    """
    sector = request.args.get("sector", "Energy")
    try:
        from data_clients import FinvizClient, TradierOptionsClient
        from pipeline import get_ici_fund_flows, score_all_sectors, get_sector_rank_for_ticker, get_sector_perf
        from scoring_engine import (score_capital_flow_level1, score_capital_flow_level2,
                                     score_capital_flow_level3, score_capital_flow_pillar,
                                     score_trend_pillar, score_momentum_pillar, calculate_flow_score)

        fv = FinvizClient()
        fv_batch = fv.get_ticker_data([ticker.upper(), "SPY"])
        spy_fv = fv_batch.get("SPY", {})
        stock_fv = fv_batch.get(ticker.upper(), {})

        # Fetch SMA directly via TradingView (bypassing get_ticker_data)
        sma_result = _tv_sma_test(ticker.upper())
        if "SMA50" in sma_result and sma_result["SMA50"]:
            stock_fv["sma20"]  = round(sma_result["SMA20"], 2)
            stock_fv["sma50"]  = round(sma_result["SMA50"], 2)
            stock_fv["sma200"] = round(sma_result["SMA200"], 2)

        spy_perf_63d = spy_fv.get("perf_quarter", 0)
        spy_price = spy_fv.get("price", 0)
        spy_ma200 = spy_fv.get("sma200", 0)
        spy_above_200ma = bool(spy_price > spy_ma200) if spy_ma200 else True

        fund_flows = get_ici_fund_flows()
        equity_weekly = fund_flows["equity_weekly"]
        equity_avg = fund_flows["equity_4wk_avg"]

        sector_scores = score_all_sectors(fv, None, equity_weekly, equity_avg)
        sector_rank = get_sector_rank_for_ticker(sector, sector_scores)
        sector_ytd = get_sector_perf(sector, sector_scores)
        sector_perf_63d = sector_ytd
        sector_etf_flow = sector_ytd * 50

        price = stock_fv.get("price", 0)
        ma20 = stock_fv.get("sma20", price)
        ma50 = stock_fv.get("sma50", 0)
        ma200 = stock_fv.get("sma200", 0)

        l1 = score_capital_flow_level1(equity_weekly, equity_avg, spy_above_200ma)
        l2 = score_capital_flow_level2(sector_ytd, sector_etf_flow, sector_rank)
        l3 = score_capital_flow_level3([], stock_fv, {}, spy_perf_63d=spy_perf_63d, sector_perf_63d=sector_perf_63d)
        cf = score_capital_flow_pillar(l1, l2, l3)
        trend = score_trend_pillar(price, ma20, ma50, ma200, [])
        mom = score_momentum_pillar([], stock_fv, spy_perf_63d, sector_perf_63d)
        result = calculate_flow_score(cf, trend, mom)

        return jsonify({
            "ticker": ticker.upper(),
            "sector": sector,
            "flow_score": result["flow_score"],
            "rating": result["rating"],
            "pillars": {
                "capital_flow": {
                    "score": cf["score"],
                    "max": 40,
                    "l1": {"score": l1["score"], "max": 10, "detail": l1["detail"]},
                    "l2": {"score": l2["score"], "max": 15, "detail": l2["detail"]},
                    "l3": {"score": l3["score"], "max": 15, "detail": l3["detail"]},
                },
                "trend": {
                    "score": trend["score"],
                    "max": 30,
                    "detail": trend["detail"],
                    "raw": trend["raw"],
                },
                "momentum": {
                    "score": mom["score"],
                    "max": 30,
                    "detail": mom["detail"],
                    "raw": mom["raw"],
                },
            },
            "raw_finviz_data": {k: v for k, v in stock_fv.items() if k in [
                "price", "sma20", "sma50", "sma200", "perf_week", "perf_month",
                "perf_quarter", "perf_half", "perf_year", "relative_volume", "sector"
            ]},
            "sma_debug": {
                "sma20": stock_fv.get("sma20"),
                "sma50": stock_fv.get("sma50"),
                "sma200": stock_fv.get("sma200"),
                "all_keys_with_values": {k: v for k, v in stock_fv.items() if v and v != 0},
                "tv_sma_direct_test": _tv_sma_test(ticker.upper()),
            },
            "context": {
                "spy_perf_63d": spy_perf_63d,
                "spy_above_200ma": spy_above_200ma,
                "equity_weekly_flow": equity_weekly,
                "sector_rank": sector_rank,
                "sector_ytd": sector_ytd,
                "sector_etf_flow_proxy": sector_etf_flow,
            }
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/sma-test/<ticker>")
def sma_test(ticker):
    """Test SMA fetching directly — shows raw TradingView output."""
    try:
        from tradingview_screener import Query, col as tv_col
        _, df = (Query()
            .select("name", "close", "SMA20", "SMA50", "SMA200")
            .set_markets("america")
            .where(tv_col("name").isin([ticker.upper()]))
            .limit(5)
            .get_scanner_data()
        )
        rows = df.to_dict(orient="records")
        return jsonify({
            "ticker": ticker.upper(),
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(rows),
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/admin/backfill-scores")
def backfill_scores():
    """
    One-time backfill: populates prev_score and score_jump for all existing
    weekly_scores rows by comparing consecutive scores per ticker.
    Requires prev_score (float8) and score_jump (float8) columns in Supabase.
    """
    try:
        sb = get_sb()
        from collections import defaultdict

        # Fetch all rows ordered by ticker then date ascending
        result = sb.table("weekly_scores") \
            .select("id,ticker,date,flow_score") \
            .order("ticker") \
            .order("date") \
            .execute()
        rows = result.data or []

        # Group by ticker
        by_ticker = defaultdict(list)
        for row in rows:
            by_ticker[row["ticker"]].append(row)

        updated = 0
        skipped = 0
        errors = []
        for ticker, ticker_rows in by_ticker.items():
            for i, row in enumerate(ticker_rows):
                curr_score = row.get("flow_score") or 0
                prev = ticker_rows[i - 1].get("flow_score") if i > 0 else None
                jump = round(curr_score - (prev or 0), 1) if prev is not None else None
                try:
                    sb.table("weekly_scores").update({
                        "prev_score": prev,
                        "score_jump": jump,
                    }).eq("id", row["id"]).execute()
                    updated += 1
                except Exception as e:
                    skipped += 1
                    errors.append(str(e)[:100])

        return jsonify({
            "status": "done",
            "total_rows": len(rows),
            "updated": updated,
            "skipped": skipped,
            "tickers": len(by_ticker),
            "sample_errors": errors[:3],
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/admin/seed-hitlist", methods=["POST"])
def seed_hitlist():
    """
    One-time seed: loads TTI Hit List 2026-04-22 into weekly_scores.
    Inserts April-14 (prev) and April-21 (current) rows for all 42 names,
    and adds each ticker to the watchlist if not already present.
    Safe to re-run (upsert on ticker,date).
    """
    try:
        import traceback as _tb
        from scoring_engine import detect_burst_trade as _dbt

        CURRENT_DATE = "2026-04-21"
        PREV_DATE    = "2026-04-14"

        HIT_LIST = [
            # Tier 1 — Burst Triggers
            {"ticker": "NVTS", "score": 88, "cf": 30, "trend": 30, "mom": 28, "prev": 49, "sector": "Technology",     "price": 16.89,   "tier": 1},
            {"ticker": "VICR", "score": 86, "cf": 28, "trend": 30, "mom": 28, "prev": 67, "sector": "Technology",     "price": 259.67,  "tier": 1},
            {"ticker": "NN",   "score": 84, "cf": 27, "trend": 30, "mom": 27, "prev": 42, "sector": "Industrials",    "price": 22.68,   "tier": 1},
            {"ticker": "UMC",  "score": 83, "cf": 28, "trend": 30, "mom": 25, "prev": 61, "sector": "Technology",     "price": 12.61,   "tier": 1},
            {"ticker": "SMTC", "score": 82, "cf": 24, "trend": 30, "mom": 28, "prev": 62, "sector": "Technology",     "price": 106.06,  "tier": 1},
            {"ticker": "BE",   "score": 81, "cf": 23, "trend": 30, "mom": 28, "prev": 52, "sector": "Energy",         "price": 228.50,  "tier": 1},
            {"ticker": "USAR", "score": 81, "cf": 29, "trend": 26, "mom": 26, "prev": 36, "sector": "Materials",      "price": 24.05,   "tier": 1},
            {"ticker": "TWLO", "score": 80, "cf": 24, "trend": 30, "mom": 26, "prev": 39, "sector": "Technology",     "price": 153.41,  "tier": 1},
            {"ticker": "NVDA", "score": 76, "cf": 22, "trend": 30, "mom": 24, "prev": 56, "sector": "Semiconductors", "price": 201.08,  "tier": 1},
            {"ticker": "RKLB", "score": 73, "cf": 23, "trend": 30, "mom": 20, "prev": 52, "sector": "Industrials",    "price": 89.69,   "tier": 1},
            {"ticker": "ABNB", "score": 70, "cf": 18, "trend": 30, "mom": 22, "prev": 43, "sector": "Consumer Disc",  "price": 146.50,  "tier": 1},
            {"ticker": "AAPL", "score": 70, "cf": 24, "trend": 25, "mom": 21, "prev": 52, "sector": "Tech Hardware",  "price": 267.47,  "tier": 1},
            # Tier 2 — Near Burst
            {"ticker": "MXL",  "score": 90, "cf": 32, "trend": 30, "mom": 28, "prev": 78, "sector": "Technology",     "price": 33.31,   "tier": 2},
            {"ticker": "AMKR", "score": 86, "cf": 28, "trend": 30, "mom": 28, "prev": 76, "sector": "Technology",     "price": 71.47,   "tier": 2},
            {"ticker": "GFS",  "score": 86, "cf": 28, "trend": 30, "mom": 28, "prev": 73, "sector": "Technology",     "price": 59.44,   "tier": 2},
            {"ticker": "ON",   "score": 85, "cf": 27, "trend": 30, "mom": 28, "prev": 72, "sector": "Semiconductors", "price": 85.86,   "tier": 2},
            {"ticker": "PLUG", "score": 83, "cf": 25, "trend": 30, "mom": 28, "prev": 70, "sector": "Energy",         "price": 3.10,    "tier": 2},
            {"ticker": "ICHR", "score": 82, "cf": 24, "trend": 30, "mom": 28, "prev": 70, "sector": "Technology",     "price": 65.10,   "tier": 2},
            {"ticker": "IAC",  "score": 81, "cf": 26, "trend": 30, "mom": 25, "prev": 70, "sector": "Technology",     "price": 45.14,   "tier": 2},
            {"ticker": "SIMO", "score": 81, "cf": 26, "trend": 30, "mom": 25, "prev": 67, "sector": "Technology",     "price": 142.62,  "tier": 2},
            {"ticker": "VFC",  "score": 80, "cf": 25, "trend": 30, "mom": 25, "prev": 68, "sector": "Industrials",    "price": 21.72,   "tier": 2},
            {"ticker": "HG",   "score": 80, "cf": 25, "trend": 30, "mom": 25, "prev": 70, "sector": "Financials",     "price": 32.55,   "tier": 2},
            # Tier 3 — Big Moves, Not There Yet
            {"ticker": "ALGN", "score": 69, "cf": 18, "trend": 26, "mom": 25, "prev": 46, "sector": "Health Care",    "price": 197.28,  "tier": 3},
            {"ticker": "QXO",  "score": 69, "cf": 20, "trend": 29, "mom": 20, "prev": 53, "sector": "Consumer Disc",  "price": 23.31,   "tier": 3},
            {"ticker": "BALL", "score": 69, "cf": 18, "trend": 28, "mom": 23, "prev": 52, "sector": "Materials",      "price": 64.46,   "tier": 3},
            {"ticker": "JOE",  "score": 69, "cf": 19, "trend": 29, "mom": 21, "prev": 47, "sector": "Real Estate",    "price": 69.71,   "tier": 3},
            {"ticker": "IREN", "score": 69, "cf": 24, "trend": 30, "mom": 15, "prev": 41, "sector": "Technology",     "price": 47.01,   "tier": 3},
            {"ticker": "DAVE", "score": 68, "cf": 25, "trend": 15, "mom": 28, "prev": 31, "sector": "Financials",     "price": 274.55,  "tier": 3},
            {"ticker": "AUR",  "score": 68, "cf": 28, "trend": 15, "mom": 25, "prev": 36, "sector": "Technology",     "price": 5.30,    "tier": 3},
            {"ticker": "BEN",  "score": 68, "cf": 18, "trend": 26, "mom": 24, "prev": 48, "sector": "Financials",     "price": 27.63,   "tier": 3},
            {"ticker": "LNTH", "score": 68, "cf": 19, "trend": 30, "mom": 19, "prev": 50, "sector": "Health Care",    "price": 82.96,   "tier": 3},
            {"ticker": "PACS", "score": 67, "cf": 21, "trend": 26, "mom": 20, "prev": 43, "sector": "Health Care",    "price": 36.83,   "tier": 3},
            # Tier 4 — High Conviction
            {"ticker": "VSH",  "score": 86, "cf": 28, "trend": 30, "mom": 28, "prev": 81, "sector": "Technology",     "price": 26.80,   "tier": 4},
            {"ticker": "VECO", "score": 84, "cf": 26, "trend": 30, "mom": 28, "prev": 77, "sector": "Technology",     "price": 48.63,   "tier": 4},
            {"ticker": "UI",   "score": 84, "cf": 26, "trend": 30, "mom": 28, "prev": 76, "sector": "Technology",     "price": 1044.42, "tier": 4},
            {"ticker": "STM",  "score": 84, "cf": 26, "trend": 30, "mom": 28, "prev": 75, "sector": "Technology",     "price": 44.38,   "tier": 4},
            {"ticker": "ACLS", "score": 84, "cf": 26, "trend": 30, "mom": 28, "prev": 77, "sector": "Technology",     "price": 136.15,  "tier": 4},
            {"ticker": "SYRE", "score": 83, "cf": 25, "trend": 30, "mom": 28, "prev": 76, "sector": "Health Care",    "price": 71.68,   "tier": 4},
            {"ticker": "AVT",  "score": 83, "cf": 26, "trend": 30, "mom": 27, "prev": 75, "sector": "Technology",     "price": 75.54,   "tier": 4},
            {"ticker": "NBIS", "score": 82, "cf": 24, "trend": 30, "mom": 28, "prev": 79, "sector": "Technology",     "price": 161.78,  "tier": 4},
            {"ticker": "VIAV", "score": 82, "cf": 24, "trend": 30, "mom": 28, "prev": 77, "sector": "Technology",     "price": 44.34,   "tier": 4},
            {"ticker": "LSCC", "score": 82, "cf": 24, "trend": 30, "mom": 28, "prev": 77, "sector": "Technology",     "price": 117.88,  "tier": 4},
        ]

        def _rating(s):
            if s >= 85: return ("ELITE",   "Primary Buy",  "Flow Trade: 120 DTE, .25 Delta")
            if s >= 70: return ("STRONG",  "Strong Setup", "Flow Trade: 120 DTE, .25 Delta")
            if s >= 50: return ("NEUTRAL", "Watch Only",   "Watchlist only. Wait.")
            if s >= 30: return ("WEAK",    "Avoid",        "Avoid completely.")
            return             ("TOXIC",   "Do Not Touch", "Do not touch.")

        sb2 = get_sb()
        wl_added = prev_rows = curr_rows = 0
        errors = []

        for item in HIT_LIST:
            ticker = item["ticker"]
            sector = item["sector"]
            score  = item["score"]
            prev   = item["prev"]
            price  = item["price"]
            cf, trend, mom = item["cf"], item["trend"], item["mom"]

            # 1. Watchlist
            try:
                sb2.table("watchlist").upsert(
                    {"ticker": ticker, "sector": sector, "active": True},
                    on_conflict="ticker"
                ).execute()
                wl_added += 1
            except Exception as e:
                errors.append(f"wl {ticker}: {str(e)[:200]}")

            burst = _dbt(score, prev)
            rating, label, action = _rating(score)
            prev_rating, prev_label, prev_action = _rating(prev)

            pillars_curr = json.dumps({
                "capital_flow": {"score": cf,    "detail": f"CF {cf}/40 · TTI 2026-04-22"},
                "trend":        {"score": trend, "detail": f"Trend {trend}/30 · TTI 2026-04-22"},
                "momentum":     {"score": mom,   "detail": f"Mom {mom}/30 · TTI 2026-04-22"},
            })

            # 2. April-14 anchor row
            try:
                sb2.table("weekly_scores").upsert({
                    "ticker": ticker, "date": PREV_DATE,
                    "flow_score": prev,
                    "rating": prev_rating, "label": prev_label, "action": prev_action,
                    "price": price, "sector": sector,
                    "pillars": json.dumps({}),
                    "burst": json.dumps({"is_burst": False, "tier": None, "score_jump": 0,
                                         "trade_type": "None", "options_params": "Seeded Apr-14"}),
                    "scored_at": f"{PREV_DATE}T00:00:00",
                }, on_conflict="ticker,date").execute()
                prev_rows += 1
            except Exception as e:
                errors.append(f"prev {ticker}: {str(e)[:200]}")

            # 3. April-21 current row
            try:
                sb2.table("weekly_scores").upsert({
                    "ticker": ticker, "date": CURRENT_DATE,
                    "flow_score": score,
                    "rating": rating, "label": label, "action": action,
                    "price": price, "sector": sector,
                    "pillars": pillars_curr,
                    "burst": json.dumps(burst),
                    "scored_at": f"{CURRENT_DATE}T00:00:00",
                }, on_conflict="ticker,date").execute()
                curr_rows += 1
            except Exception as e:
                errors.append(f"curr {ticker}: {str(e)[:200]}")

        return jsonify({
            "status":    "done",
            "tickers":   len(HIT_LIST),
            "watchlist": wl_added,
            "prev_rows": prev_rows,
            "curr_rows": curr_rows,
            "errors":    errors,
            "source":    "TTI Hit List 2026-04-22 (scores as of Apr 21)",
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/scores/daily-run", methods=["POST"])
def trigger_daily_score():
    """Manually trigger daily trend score."""
    def _run():
        run_daily_score()
    import threading
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/scores/daily-latest")
def daily_scores_latest():
    """
    Latest daily trend scores per ticker.
    Returns today's score + yesterday's for day jump calculation.
    """
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=3)).isoformat()
    result = sb.table("daily_scores") \
        .select("*") \
        .gte("date", cutoff) \
        .order("date", desc=True) \
        .execute()

    rows = result.data or []

    # Group by ticker, keep last 2 dates
    from collections import defaultdict
    by_ticker = defaultdict(list)
    for row in rows:
        by_ticker[row["ticker"]].append(row)

    output = {}
    for ticker, ticker_rows in by_ticker.items():
        latest = ticker_rows[0]
        prev = ticker_rows[1] if len(ticker_rows) > 1 else None
        day_jump = None
        if prev and latest.get("trend_score") is not None and prev.get("trend_score") is not None:
            day_jump = round(latest["trend_score"] - prev["trend_score"], 1)
        output[ticker] = {
            "date": latest["date"],
            "price": latest.get("price"),
            "trend_score": latest.get("trend_score"),
            "rel_vol": latest.get("rel_vol"),
            "above_20": latest.get("above_20"),
            "above_50": latest.get("above_50"),
            "above_200": latest.get("above_200"),
            "day_jump": day_jump,
        }

    return jsonify(output)


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    sb = get_sb()
    result = sb.table("watchlist").select("*").eq("active", True).order("ticker").execute()
    return jsonify(result.data or [])

@app.route("/api/watchlist", methods=["POST"])
def add_ticker():
    data = request.json
    ticker = data.get("ticker", "").upper().strip()
    sector = data.get("sector", "").strip()
    if not ticker:
        return jsonify({"error": "Ticker required"}), 400
    sb = get_sb()
    existing = sb.table("watchlist").select("*").eq("ticker", ticker).execute()
    if existing.data:
        sb.table("watchlist").update({"active": True, "sector": sector}).eq("ticker", ticker).execute()
    else:
        sb.table("watchlist").insert({"ticker": ticker, "sector": sector, "active": True}).execute()

    # Score the new ticker immediately in the background
    import threading
    def _score_new():
        try:
            from pipeline import score_tickers
            results = score_tickers([{"ticker": ticker, "sector": sector}])
            print(f"  Auto-scored {ticker} on watchlist add: {results[0].get('flow_score') if results else 'no result'}")
        except Exception as e:
            print(f"  Auto-score error for {ticker}: {e}")
    threading.Thread(target=_score_new, daemon=True).start()

    return jsonify({"success": True, "ticker": ticker})

@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def remove_ticker(ticker):
    sb = get_sb()
    sb.table("watchlist").update({"active": False}).eq("ticker", ticker.upper()).execute()
    return jsonify({"success": True})


# ============================================================
# FLOW SCORES
# ============================================================

@app.route("/api/scores/latest")
def latest_scores():
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    result = sb.table("weekly_scores") \
        .select("*") \
        .gte("date", cutoff) \
        .order("date", desc=True) \
        .execute()

    # Build full history per ticker to compute day-over-day jump
    ticker_history = {}
    for row in (result.data or []):
        ticker = row.get("ticker")
        if ticker not in ticker_history:
            ticker_history[ticker] = []
        ticker_history[ticker].append(row)

    # Deduplicate — keep latest row per ticker, add day_jump
    seen = {}
    for ticker, rows in ticker_history.items():
        # rows already sorted desc by date
        latest = rows[0]
        try:
            latest["pillars"] = json.loads(latest.get("pillars", "{}"))
            latest["burst"] = json.loads(latest.get("burst", "{}"))
        except:
            pass

        # Day-over-day jump: compare today vs yesterday's score
        curr_score = latest.get("flow_score") or 0
        # Day jump comes from daily_scores table (populated separately)
        latest["day_jump"] = None  # will be merged below

        # Week jump — from burst blob or prev_score column
        burst = latest.get("burst", {}) if isinstance(latest.get("burst"), dict) else {}
        week_jump = burst.get("score_jump") or latest.get("score_jump")
        latest["week_jump"] = week_jump
        latest["prev_score"] = latest.get("prev_score") or burst.get("prev_score")

        seen[ticker] = latest

    # Merge day jump from daily_scores
    try:
        daily_cutoff = (date.today() - timedelta(days=3)).isoformat()
        daily_result = sb.table("daily_scores") \
            .select("ticker,date,trend_score,rel_vol,above_20,above_50,above_200") \
            .gte("date", daily_cutoff) \
            .order("date", desc=True) \
            .execute()
        from collections import defaultdict as _dd
        daily_by_ticker = _dd(list)
        for row in (daily_result.data or []):
            daily_by_ticker[row["ticker"]].append(row)
        for ticker, daily_rows in daily_by_ticker.items():
            if ticker in seen and len(daily_rows) >= 2:
                today_ts = daily_rows[0].get("trend_score")
                prev_ts  = daily_rows[1].get("trend_score")
                if today_ts is not None and prev_ts is not None:
                    seen[ticker]["day_jump"] = round(today_ts - prev_ts, 1)
    except Exception as e:
        print(f"  daily_scores merge error: {e}")

    # Sort by flow_score descending
    scores = sorted(seen.values(), key=lambda x: x.get("flow_score", 0) or 0, reverse=True)
    # Sanitize NaN/Infinity values which break JSON serialization in browsers
    import math
    def sanitize(obj):
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
    scores = sanitize(scores)
    return jsonify(scores)

@app.route("/api/scores/history/<ticker>")
def ticker_history(ticker):
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    result = sb.table("weekly_scores") \
        .select("date,flow_score,rating,label,price") \
        .eq("ticker", ticker.upper()) \
        .gte("date", cutoff) \
        .order("date") \
        .execute()
    return jsonify(result.data or [])

@app.route("/api/scores/daily/<ticker>")
def daily_prices(ticker):
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    result = sb.table("daily_prices") \
        .select("*") \
        .eq("ticker", ticker.upper()) \
        .gte("date", cutoff) \
        .order("date") \
        .execute()
    return jsonify(result.data or [])


# ============================================================
# SECTOR RANKINGS
# ============================================================

@app.route("/api/sectors/latest")
def sector_rankings():
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    result = sb.table("sector_scores") \
        .select("*") \
        .gte("date", cutoff) \
        .order("flow_score", desc=True) \
        .execute()

    # Deduplicate — keep latest per sector
    seen = {}
    for row in (result.data or []):
        sector = row["sector"]
        if sector not in seen:
            seen[sector] = row
    return jsonify(list(seen.values()))


@app.route("/api/sectors/history")
def sector_history():
    """
    Returns weekly sector snapshots for the last N weeks.
    Used for WoW rotation tracking in the dashboard.
    """
    sb = get_sb()
    weeks = int(request.args.get("weeks", 6))
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()

    result = sb.table("sector_snapshots") \
        .select("*") \
        .gte("week_ending", cutoff) \
        .order("week_ending", desc=True) \
        .execute()

    # Group by sector for easy frontend consumption
    by_sector = {}
    for row in (result.data or []):
        s = row["sector"]
        if s not in by_sector:
            by_sector[s] = []
        by_sector[s].append({
            "week_ending": row["week_ending"],
            "flow_score": row["flow_score"],
            "status": row["status"],
            "rank": row["rank"],
            "etf_flow_m": row.get("etf_flow_m", 0),
        })

    return jsonify({"sectors": by_sector, "weeks": weeks})


# ============================================================
# CAPITAL FLOW LEADERS & EXITS
# ============================================================

@app.route("/api/leaders")
def flow_leaders():
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    result = sb.table("flow_leaders").select("*").gte("date", cutoff).order("flow_score", desc=True).execute()
    return jsonify(result.data or [])

@app.route("/api/exits")
def flow_exits():
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    result = sb.table("flow_exits").select("*").gte("date", cutoff).order("flow_score").execute()
    return jsonify(result.data or [])

@app.route("/api/burst-trades")
def burst_trades():
    sb = get_sb()
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    result = sb.table("weekly_scores").select("ticker,flow_score,rating,burst,date,sector,price").gte("date", cutoff).execute()

    bursts = []
    for row in (result.data or []):
        try:
            burst = json.loads(row.get("burst", "{}"))
            if burst.get("is_burst"):
                row["burst"] = burst
                bursts.append(row)
        except:
            pass
    bursts.sort(key=lambda x: x.get("burst", {}).get("score_jump", 0), reverse=True)
    return jsonify(bursts)


# ============================================================
# FUND FLOWS (ICI Data)
# ============================================================

@app.route("/api/fund-flows")
def fund_flows():
    sb = get_sb()
    result = sb.table("fund_flows").select("*").order("week_ending", desc=True).limit(8).execute()
    return jsonify(result.data or [])

@app.route("/api/fund-flows", methods=["POST"])
def add_fund_flow():
    """Manually enter weekly ICI fund flow data from dashboard"""
    data = request.json
    sb = get_sb()
    row = {
        "week_ending": data.get("week_ending"),
        "equity_total": data.get("equity_total", 0),
        "equity_domestic": data.get("equity_domestic", 0),
        "equity_world": data.get("equity_world", 0),
        "bond_total": data.get("bond_total", 0),
        "commodity": data.get("commodity", 0),
    }
    sb.table("fund_flows").upsert(row, on_conflict="week_ending").execute()
    return jsonify({"success": True})


# ============================================================
# MANUAL TRIGGERS
# ============================================================

@app.route("/api/scan/weekly", methods=["POST"])
def trigger_weekly():
    import threading
    def run():
        try:
            run_weekly_flow_score()
            print("Weekly score run complete (no email — manual trigger)")
        except Exception as e:
            print(f"Weekly scan error: {e}")
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "message": "Scoring watchlist in background — check Scores tab in ~1 min"})

@app.route("/api/scan/daily", methods=["POST"])
def trigger_daily():
    import threading
    def run():
        try:
            run_daily_price_update()
        except Exception as e:
            print(f"Daily scan error: {e}")
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "message": "Daily scan started in background"})


# ============================================================
# CSV EXPORT
# ============================================================



# ============================================================
# SCANNER
# ============================================================

@app.route("/api/scanner/run", methods=["POST"])
def trigger_scanner():
    # On non-trading days, skip live scan and return cached results immediately
    if not is_trading_day():
        sb = get_sb()
        try:
            result = sb.table("scanner_results").select("*").order("run_date", desc=True).limit(1).execute()
            if result.data:
                row = result.data[0]
                return jsonify({
                    "success": True,
                    "cached": True,
                    "message": f"Markets closed — showing last scan from {row.get('updated_at', row['run_date'])}",
                    "run_date": row["run_date"],
                })
        except Exception as e:
            print(f"Cache fetch error: {e}")
        return jsonify({"success": False, "message": "Markets closed and no cached results available"})

    import threading
    def _run():
        try:
            results = run_scanner()

            # Score top 10 per sector + top 10 Big Blue Sky
            sector_stocks = results.get("sector_stocks", {})
            top_sectors = results.get("top_sectors", [])
            top10 = []
            for sector_data in top_sectors:
                sname = sector_data["sector"]
                stocks = sector_stocks.get(sname, [])
                top_in_sector = sorted(stocks, key=lambda s: s.get("rs_vs_etf", 0), reverse=True)[:25]
                for s in top_in_sector:
                    top10.append({"ticker": s["ticker"], "sector": sname, "rs": s.get("rs_vs_etf", 0)})

            bbs = results.get("big_blue_sky", [])
            for s in bbs:
                top10.append({"ticker": s["ticker"], "sector": s.get("sector", ""), "rs": s.get("perf_3m", 0)})

            if top10:
                print(f"  Scoring {len(top10)} stocks (top 25/sector + BBS): {[t['ticker'] for t in top10]}")
                scored = score_tickers(top10)
                score_map = {r["ticker"]: r for r in scored}
                for sname, stocks in sector_stocks.items():
                    for stock in stocks:
                        if stock["ticker"] in score_map:
                            stock["flow_score"] = score_map[stock["ticker"]].get("flow_score")
                            stock["rating"] = score_map[stock["ticker"]].get("rating")
                for stock in results.get("big_blue_sky", []):
                    if stock["ticker"] in score_map:
                        stock["flow_score"] = score_map[stock["ticker"]].get("flow_score")
                        stock["rating"] = score_map[stock["ticker"]].get("rating")

                # Re-save to Supabase with scores merged in
                sb = get_sb()
                import json as _json
                from datetime import datetime as _dt, date as _date
                sb.table("scanner_results").upsert({
                    "run_date": _date.today().isoformat(),
                    "results": _json.dumps(results),
                    "updated_at": _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }, on_conflict="run_date").execute()
                print("  Scanner results updated with scores.")

        except Exception as e:
            print(f"Scanner error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Scanner started — scores will appear in ~2 min"})


@app.route("/api/scanner/results")
def get_scanner_results():
    sb = get_sb()
    try:
        result = sb.table("scanner_results").select("*").order("run_date", desc=True).limit(1).execute()
        if result.data:
            row = result.data[0]
            data = json.loads(row["results"]) if isinstance(row["results"], str) else row["results"]
            trading_day = is_trading_day()
            return jsonify({
                "success": True,
                "data": data,
                "run_date": row["run_date"],
                "is_cached": not trading_day,
                "cache_notice": None if trading_day else f"Markets closed — showing last scan from {row.get('updated_at', row['run_date'])}",
            })
        return jsonify({"success": False, "message": "No scanner results yet"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/export/scores")
def export_scores():
    import csv, io
    sb = get_sb()
    result = sb.table("weekly_scores").select("*").order("date", desc=True).execute()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Ticker", "Flow Score", "Rating", "Label", "Price", "Sector", "Action"])
    for r in (result.data or []):
        writer.writerow([r.get("date"), r.get("ticker"), r.get("flow_score"),
                          r.get("rating"), r.get("label"), r.get("price"),
                          r.get("sector"), r.get("action")])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=flow_scores.csv"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Flow Score server on port {port}")
    print("Weekly scan: Fridays 5pm ET | Daily update: 7am ET weekdays")
    app.run(host="0.0.0.0", port=port, debug=False)
