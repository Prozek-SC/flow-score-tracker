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

from pipeline import run_weekly_flow_score, run_daily_price_update, get_ici_fund_flows
from email_report import send_weekly_report, send_daily_price_alert

load_dotenv()

app = Flask(__name__)
CORS(app)
ET = pytz.timezone("America/New_York")


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

scheduler = BackgroundScheduler(timezone=ET)
# Weekly: Friday at 5:00 PM ET (after market close)
scheduler.add_job(weekly_job, CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=ET))
# Daily: 7:00 AM ET weekdays
scheduler.add_job(daily_job, CronTrigger(day_of_week="mon-fri", hour=7, minute=0, timezone=ET))
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
    sb.table("watchlist").upsert({"ticker": ticker, "sector": sector, "active": True}).execute()
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
    try:
        results = run_weekly_flow_score()
        send_weekly_report(results)
        return jsonify({"success": True, "tickers": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scan/daily", methods=["POST"])
def trigger_daily():
    try:
        run_daily_price_update()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# CSV EXPORT
# ============================================================

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
