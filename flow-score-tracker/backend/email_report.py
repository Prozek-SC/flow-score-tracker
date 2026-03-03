"""
Flow Score Email Reports
Weekly full report + Daily price alert
Sends via Gmail SMTP using an App Password.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from dotenv import load_dotenv

load_dotenv()

RATING_COLORS = {
    "ELITE": "#00ff88",
    "STRONG": "#7fff7f",
    "NEUTRAL": "#ffd700",
    "WEAK": "#ff9944",
    "TOXIC": "#ff3333",
}


def build_weekly_html(results: list) -> str:
    today = date.today().strftime("%A, %B %d, %Y")
    sorted_r = sorted(results, key=lambda x: x.get("flow_score", 0), reverse=True)

    burst_trades = [r for r in sorted_r if r.get("burst", {}).get("is_burst")]
    flow_trades = [r for r in sorted_r if r.get("flow_score", 0) >= 80 and not r.get("burst", {}).get("is_burst")]
    watch_list = [r for r in sorted_r if 50 <= r.get("flow_score", 0) < 80]
    avoid = [r for r in sorted_r if r.get("flow_score", 0) < 50]

    def score_bar(score, max_score=100):
        pct = score / max_score * 100
        color = "#00ff88" if pct >= 80 else "#7fff7f" if pct >= 65 else "#ffd700" if pct >= 50 else "#ff4444"
        return f"""<div style="background:#1a1a2e;border-radius:3px;height:8px;width:120px;display:inline-block;vertical-align:middle;">
            <div style="background:{color};width:{pct}%;height:8px;border-radius:3px;"></div></div>"""

    def ticker_rows(items, section_label, section_color):
        if not items:
            return ""
        rows = f"""<tr><td colspan="7" style="padding:16px 16px 8px;background:#0a0a18;">
            <span style="font-size:11px;color:{section_color};letter-spacing:3px;font-weight:700;">{section_label}</span></td></tr>"""
        for r in items:
            pillars = r.get("pillars", {})
            cf = pillars.get("capital_flow", {}).get("score", 0)
            tr = pillars.get("trend", {}).get("score", 0)
            mo = pillars.get("momentum", {}).get("score", 0)
            rating = r.get("rating", "")
            color = RATING_COLORS.get(rating, "#888")
            burst = r.get("burst", {})
            burst_tag = f'<span style="background:#ff6600;color:#000;font-size:9px;padding:2px 6px;border-radius:3px;font-weight:700;margin-left:8px;">⚡ BURST +{burst.get("score_jump",0):.0f}pts</span>' if burst.get("is_burst") else ""

            rows += f"""<tr style="border-bottom:1px solid #0d0d1a;">
                <td style="padding:12px 16px;font-weight:700;color:#fff;font-size:14px;white-space:nowrap;">{r.get("ticker","")} {burst_tag}</td>
                <td style="padding:12px 8px;text-align:center;font-size:20px;font-weight:900;color:{color};">{r.get("flow_score",0):.0f}</td>
                <td style="padding:12px 8px;"><span style="color:{color};font-weight:700;font-size:11px;">{rating}</span></td>
                <td style="padding:12px 8px;color:#888;font-size:11px;">{score_bar(cf,40)} {cf}/40</td>
                <td style="padding:12px 8px;color:#888;font-size:11px;">{score_bar(tr,30)} {tr}/30</td>
                <td style="padding:12px 8px;color:#888;font-size:11px;">{score_bar(mo,30)} {mo}/30</td>
                <td style="padding:12px 16px;color:#555;font-size:10px;max-width:200px;">{r.get("action","")}</td>
            </tr>"""
        return rows

    all_rows = ""
    if burst_trades:
        all_rows += ticker_rows(burst_trades, "⚡ BURST TRADE ALERTS", "#ff6600")
    if flow_trades:
        all_rows += ticker_rows(flow_trades, "▲ FLOW TRADES (80+ Score)", "#00ff88")
    if watch_list:
        all_rows += ticker_rows(watch_list, "◎ WATCHLIST (50-79 Score)", "#ffd700")
    if avoid:
        all_rows += ticker_rows(avoid, "✕ AVOID / EXITS", "#ff4444")

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0d0d1a;font-family:'Courier New',monospace;color:#fff;">
<div style="max-width:900px;margin:0 auto;padding:32px 16px;">

  <div style="border-bottom:2px solid #00ff88;padding-bottom:24px;margin-bottom:32px;">
    <div style="font-size:10px;color:#00ff88;letter-spacing:4px;text-transform:uppercase;">Weekly Intelligence Report</div>
    <div style="font-size:28px;font-weight:900;color:#fff;margin-top:8px;">The Flow Score</div>
    <div style="color:#888;font-size:12px;margin-top:4px;">{today} · Follow the money.</div>
  </div>

  {'<div style="background:#1a0a00;border:1px solid #ff6600;border-radius:8px;padding:16px 20px;margin-bottom:24px;"><div style="color:#ff6600;font-weight:700;font-size:13px;margin-bottom:8px;">⚡ ' + str(len(burst_trades)) + ' BURST TRADE SIGNAL' + ('S' if len(burst_trades)>1 else '') + ' THIS WEEK</div><div style="color:#aaa;font-size:11px;">Score jumped 15+ points. Entry: 30-45 DTE · .40-.50 Delta · Never roll · Sell the double.</div></div>' if burst_trades else ""}

  <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;margin-bottom:32px;">
    <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;display:flex;justify-content:space-between;">
      <span style="color:#00ff88;font-size:11px;letter-spacing:2px;">FLOW SCORE RANKINGS · {len(sorted_r)} TICKERS</span>
      <span style="color:#444;font-size:10px;">Capital Flow /40 · Trend /30 · Momentum /30</span>
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:#111128;">
        <th style="padding:10px 16px;text-align:left;color:#555;font-size:10px;font-weight:400;">TICKER</th>
        <th style="padding:10px 8px;text-align:center;color:#555;font-size:10px;font-weight:400;">SCORE</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-size:10px;font-weight:400;">RATING</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-size:10px;font-weight:400;">CAPITAL FLOW</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-size:10px;font-weight:400;">TREND</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-size:10px;font-weight:400;">MOMENTUM</th>
        <th style="padding:10px 16px;text-align:left;color:#555;font-size:10px;font-weight:400;">ACTION</th>
      </tr></thead>
      <tbody>{all_rows}</tbody>
    </table>
  </div>

  <div style="text-align:center;color:#333;font-size:10px;letter-spacing:1px;">
    THE FLOW SCORE · WEEKLY REPORT · NOT FINANCIAL ADVICE
  </div>
</div></body></html>"""


def _send_gmail(subject: str, html: str):
    """Send via Gmail SMTP using an App Password."""
    gmail_user = os.getenv("GMAIL_ADDRESS")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    to_email   = os.getenv("REPORT_EMAIL_TO")

    if not gmail_user or not gmail_pass or not to_email:
        print("Skipping email — set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, REPORT_EMAIL_TO in env")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Flow Score <{gmail_user}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Gmail SMTP error: {e}")


def send_weekly_report(results: list):
    if not results:
        print("Skipping email — no results")
        return
    burst_count = sum(1 for r in results if r.get("burst", {}).get("is_burst"))
    subject = f"⚡ BURST ALERT + Flow Score Report — {date.today().strftime('%b %d')}" if burst_count else \
              f"📊 Weekly Flow Score Report — {date.today().strftime('%b %d, %Y')}"
    _send_gmail(subject, build_weekly_html(results))


def send_daily_price_alert():
    today = date.today().strftime("%A, %B %d, %Y")
    html = f"""<!DOCTYPE html><html><body style="background:#0d0d1a;font-family:'Courier New',monospace;color:#fff;padding:24px;">
    <div style="max-width:600px;margin:0 auto;">
      <div style="font-size:10px;color:#00ff88;letter-spacing:3px;">DAILY PRICE UPDATE</div>
      <div style="font-size:22px;font-weight:900;margin:8px 0;">Flow Score · Morning Brief</div>
      <div style="color:#888;font-size:12px;margin-bottom:24px;">{today}</div>
      <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;padding:20px;">
        <p style="color:#888;font-size:12px;">Daily price data has been refreshed. Visit your dashboard for current MA positions and relative volume.</p>
        <p style="color:#00ff88;font-size:12px;">Full Flow Score recalculates each Friday after market close.</p>
      </div>
      <div style="margin-top:24px;text-align:center;color:#333;font-size:10px;">THE FLOW SCORE · NOT FINANCIAL ADVICE</div>
    </div></body></html>"""
    _send_gmail(f"☀ Flow Score Morning Brief — {date.today().strftime('%b %d')}", html)
