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
            top_in_sector = sorted(stocks, key=lambda s: s.get("rs_vs_etf", 0), reverse=True)[:10]
            for s in top_in_sector:
                top10.append({"ticker": s["ticker"], "sector": sname, "rs": s.get("rs_vs_etf", 0)})

        bbs = results.get("big_blue_sky", [])[:10]
        for s in bbs:
            top10.append({"ticker": s["ticker"], "sector": s.get("sector", ""), "rs": s.get("perf_3m", 0)})

        if top10:
            print(f"  Scoring {len(top10)} stocks (top 10/sector): {[t['ticker'] for t in top10]}")
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
scheduler.start()


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(ET).isoformat()})

@app.route("/api/debug")
def debug():
    try:
        sb = get_sb()
        result = sb.table("watchlist").select("ticker").limit(1).execute()
        return jsonify({"supabase": "ok", "data": result.data})
    except Exception as e:
        return jsonify({"supabase": "error", "message": str(e)}), 500


# ============================================================
# WATCHLIST
# ============================================================

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
        .order("flow_score", desc=True) \
        .execute()

    scores = []
    for row in (result.data or []):
        try:
            row["pillars"] = json.loads(row.get("pillars", "{}"))
            row["burst"] = json.loads(row.get("burst", "{}"))
        except:
            pass
        scores.append(row)
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
            results = run_weekly_flow_score()
            send_weekly_report(results)
        except Exception as e:
            print(f"Weekly scan error: {e}")
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "message": "Weekly scan started in background"})

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
                    "message": f"Markets closed — showing last scan from {row['run_date']}",
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
                top_in_sector = sorted(stocks, key=lambda s: s.get("rs_vs_etf", 0), reverse=True)[:10]
                for s in top_in_sector:
                    top10.append({"ticker": s["ticker"], "sector": sname, "rs": s.get("rs_vs_etf", 0)})

            bbs = results.get("big_blue_sky", [])[:10]
            for s in bbs:
                top10.append({"ticker": s["ticker"], "sector": s.get("sector", ""), "rs": s.get("perf_3m", 0)})

            if top10:
                print(f"  Scoring {len(top10)} stocks (top 10/sector + BBS): {[t['ticker'] for t in top10]}")
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
                    "updated_at": _dt.now().isoformat(),
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
                "cache_notice": None if trading_day else f"Markets closed — showing last scan from {row['run_date']}",
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
