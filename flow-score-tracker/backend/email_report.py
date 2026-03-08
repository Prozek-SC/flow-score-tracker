"""
Email Report Generator
Sends HTML emails via Gmail SMTP (or SendGrid if configured)
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from dotenv import load_dotenv

load_dotenv()


def _send_email(subject: str, html: str):
    """Send email via Gmail SMTP."""
    to_email = os.getenv("REPORT_EMAIL_TO")
    from_email = os.getenv("REPORT_EMAIL_FROM") or os.getenv("GMAIL_USER")
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not all([to_email, from_email, gmail_user, gmail_pass]):
        print("Email credentials missing — skipping email")
        print(f"  REPORT_EMAIL_TO: {to_email}")
        print(f"  GMAIL_USER: {gmail_user}")
        print(f"  GMAIL_APP_PASSWORD: {'set' if gmail_pass else 'MISSING'}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(from_email, to_email, msg.as_string())
        print(f"  Email sent: {subject}")
    except Exception as e:
        print(f"  Email error: {e}")


def _score_color(score):
    if score is None:
        return "#888"
    if score >= 80: return "#00d4aa"
    if score >= 65: return "#7fff7f"
    if score >= 50: return "#ffd700"
    if score >= 35: return "#ff9944"
    return "#ff4444"


def _perf_color(val):
    if val is None: return "#888"
    if val > 5: return "#00d4aa"
    if val > 0: return "#7fff7f"
    if val > -5: return "#ff9944"
    return "#ff4444"


def _email_wrapper(title: str, subtitle: str, body_html: str) -> str:
    today = date.today().strftime("%A, %B %d, %Y")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0d0d1a;font-family:'Courier New',monospace;">
<div style="max-width:900px;margin:0 auto;padding:32px 16px;">
  <div style="border-bottom:2px solid #00d4aa;padding-bottom:20px;margin-bottom:28px;">
    <div style="font-size:10px;color:#00d4aa;letter-spacing:4px;text-transform:uppercase;">Flow Score Tracker</div>
    <div style="font-size:26px;font-weight:900;color:#fff;margin-top:6px;">{title}</div>
    <div style="color:#888;font-size:12px;margin-top:4px;">{today} · {subtitle}</div>
  </div>
  {body_html}
  <div style="text-align:center;color:#444;font-size:10px;letter-spacing:1px;margin-top:32px;padding-top:16px;border-top:1px solid #1a1a2e;">
    FLOW SCORE TRACKER · AUTOMATED REPORT · NOT FINANCIAL ADVICE
  </div>
</div>
</body>
</html>"""


# ============================================================
# SCANNER REPORT
# ============================================================

def generate_scanner_html(results: dict) -> str:
    top_sectors = results.get("top_sectors", [])
    sector_stocks = results.get("sector_stocks", {})
    unusual = results.get("unusual_activity", [])

    body = ""

    # --- Sector Summary ---
    if top_sectors:
        sector_rows = ""
        for s in top_sectors:
            color = _perf_color(s.get("pct_from_200ma", 0))
            sector_rows += f"""
            <tr style="border-bottom:1px solid #1a1a2e;">
              <td style="padding:12px 16px;font-weight:900;color:#fff;font-size:15px;">{s['sector']}</td>
              <td style="padding:12px 16px;color:#888;font-size:12px;">{s['etf']}</td>
              <td style="padding:12px 16px;text-align:right;font-family:monospace;color:#fff;">${s.get('price',0):.2f}</td>
              <td style="padding:12px 16px;text-align:right;font-family:monospace;color:{color};font-weight:700;">
                {'+' if s.get('pct_from_200ma',0) > 0 else ''}{s.get('pct_from_200ma',0):.1f}% vs 200MA
              </td>
              <td style="padding:12px 16px;text-align:right;font-family:monospace;color:{_perf_color(s.get('perf_3m',0))};">
                {'+' if s.get('perf_3m',0) > 0 else ''}{s.get('perf_3m',0):.1f}% (3M)
              </td>
            </tr>"""

        body += f"""
        <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;margin-bottom:24px;">
          <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
            <span style="color:#00d4aa;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
              ▲ Top Sectors — Above 200MA
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#111128;">
                <th style="padding:10px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">SECTOR</th>
                <th style="padding:10px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">ETF</th>
                <th style="padding:10px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">PRICE</th>
                <th style="padding:10px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">vs 200MA</th>
                <th style="padding:10px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">3M PERF</th>
              </tr>
            </thead>
            <tbody>{sector_rows}</tbody>
          </table>
        </div>"""

    # --- Top Stocks per Sector ---
    for sector in top_sectors:
        sname = sector["sector"]
        stocks = sector_stocks.get(sname, [])[:15]  # top 15 in email
        if not stocks:
            continue

        stock_rows = ""
        for i, s in enumerate(stocks):
            rs_color = _perf_color(s.get("rs_vs_etf", 0))
            score = s.get("flow_score")
            score_html = (
                f'<span style="color:{_score_color(score)};font-weight:700;">{score:.0f}</span>'
                if score is not None else
                '<span style="color:#555;">—</span>'
            )
            ma_color = "#00d4aa" if s.get("above_200ma") else "#ff4444"
            stock_rows += f"""
            <tr style="border-bottom:1px solid #0f0f1e;">
              <td style="padding:10px 16px;color:#888;font-family:monospace;font-size:11px;">{i+1}</td>
              <td style="padding:10px 16px;">
                <a href="https://www.tradingview.com/chart/?symbol={s['ticker']}"
                   style="color:#00d4aa;font-weight:900;font-family:monospace;font-size:13px;text-decoration:none;">
                  {s['ticker']}
                </a>
                <div style="color:#666;font-size:10px;">${s.get('price',0):.2f}</div>
              </td>
              <td style="padding:10px 16px;color:#aaa;font-size:11px;">{s.get('name','')[:28]}</td>
              <td style="padding:10px 16px;text-align:right;font-family:monospace;color:{rs_color};font-weight:700;">
                {'+' if s.get('rs_vs_etf',0) > 0 else ''}{s.get('rs_vs_etf',0):.1f}%
              </td>
              <td style="padding:10px 16px;text-align:right;font-family:monospace;color:{_perf_color(s.get('perf_3m',0))};">
                {'+' if s.get('perf_3m',0) > 0 else ''}{s.get('perf_3m',0):.1f}%
              </td>
              <td style="padding:10px 16px;text-align:center;">
                <span style="color:{ma_color};font-size:10px;font-weight:700;">
                  {'▲' if s.get('above_200ma') else '▼'}200
                </span>
              </td>
              <td style="padding:10px 16px;text-align:right;">{score_html}</td>
            </tr>"""

        body += f"""
        <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;margin-bottom:24px;">
          <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
            <span style="color:#00d4aa;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
              {sname} — Top 15 by RS vs ETF
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#111128;">
                <th style="padding:8px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;">#</th>
                <th style="padding:8px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;">TICKER</th>
                <th style="padding:8px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;">NAME</th>
                <th style="padding:8px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;">RS vs ETF</th>
                <th style="padding:8px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;">3M</th>
                <th style="padding:8px 16px;text-align:center;color:#888;font-size:10px;font-weight:400;">MA</th>
                <th style="padding:8px 16px;text-align:right;color:#888;font-size:10px;font-weight:400;">SCORE</th>
              </tr>
            </thead>
            <tbody>{stock_rows}</tbody>
          </table>
        </div>"""

    # --- Unusual Options ---
    if unusual:
        unusual_rows = ""
        for u in unusual:
            color = "#00d4aa" if u.get("bias") == "bullish" else "#ff4444"
            unusual_rows += f"""
            <tr style="border-bottom:1px solid #1a1a2e;">
              <td style="padding:10px 16px;font-weight:900;color:#fff;font-family:monospace;">{u['ticker']}</td>
              <td style="padding:10px 16px;text-align:right;color:{color};font-weight:700;font-family:monospace;">
                {u.get('vol_oi_ratio',0):.1f}x Vol/OI
              </td>
              <td style="padding:10px 16px;text-align:right;color:#aaa;font-size:11px;">
                Vol: {u.get('total_volume',0):,} · OI: {u.get('total_oi',0):,}
              </td>
              <td style="padding:10px 16px;text-align:center;">
                <span style="color:{color};font-size:10px;font-weight:700;letter-spacing:1px;">
                  {u.get('bias','').upper()}
                </span>
              </td>
            </tr>"""

        body += f"""
        <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;margin-bottom:24px;">
          <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
            <span style="color:#ffd700;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
              ⚡ Unusual Options Activity
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <tbody>{unusual_rows}</tbody>
          </table>
        </div>"""

    return _email_wrapper("Morning Market Scanner", "Pre-Market Analysis", body)


def send_scanner_report(results: dict):
    if not results:
        print("  No scanner results — skipping email")
        return
    today = date.today().strftime("%B %d, %Y")
    top = [s["sector"] for s in results.get("top_sectors", [])]
    sector_str = " · ".join(top) if top else "No sectors"
    html = generate_scanner_html(results)
    _send_email(f"📊 Morning Scanner — {today} · {sector_str}", html)


# ============================================================
# WEEKLY FLOW SCORE REPORT
# ============================================================

def generate_weekly_html(results: list) -> str:
    # Extract meta block if present
    meta = {}
    clean_results = []
    for r in results:
        if r.get("_is_meta"):
            meta = r
        else:
            clean_results.append(r)

    score_changes = meta.get("score_changes", {"surges": [], "fades": []})
    sector_transitions = meta.get("sector_transitions", [])

    sorted_results = sorted(clean_results, key=lambda x: x.get("flow_score", 0), reverse=True)

    body = ""

    # --- Sector Transition Alerts ---
    if sector_transitions:
        trans_rows = ""
        for t in sector_transitions:
            if t["type"] == "breakout":
                color = "#00d4aa"
                icon = "🚀"
                desc = f"Crossed into LEADING ({t['prev_score']:.0f} → {t['curr_score']:.0f})"
            elif t["type"] == "breakdown":
                color = "#ff4444"
                icon = "⚠️"
                desc = f"Dropped from LEADING ({t['prev_score']:.0f} → {t['curr_score']:.0f})"
            elif t["type"] == "surge":
                color = "#ffd700"
                icon = "📈"
                desc = f"Score surged {t['delta']:+.0f} pts ({t['prev_score']:.0f} → {t['curr_score']:.0f})"
            else:
                color = "#ff9944"
                icon = "📉"
                desc = f"Score faded {t['delta']:+.0f} pts ({t['prev_score']:.0f} → {t['curr_score']:.0f})"

            trans_rows += f"""
            <tr style="border-bottom:1px solid #1a1a2e;">
              <td style="padding:12px 16px;font-size:18px;">{icon}</td>
              <td style="padding:12px 16px;">
                <span style="color:{color};font-weight:900;font-family:monospace;font-size:14px;">{t['sector']}</span>
                <span style="color:#666;font-size:11px;margin-left:8px;">{t['etf']}</span>
              </td>
              <td style="padding:12px 16px;color:#aaa;font-size:12px;">{desc}</td>
              <td style="padding:12px 16px;text-align:right;">
                <span style="color:{color};font-weight:700;font-family:monospace;">{t['label']}</span>
              </td>
            </tr>"""

        body += f"""
        <div style="background:#0a0a18;border:2px solid #ffd700;border-radius:8px;overflow:hidden;margin-bottom:24px;">
          <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
            <span style="color:#ffd700;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
              ⚡ Sector Rotation Signals
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <tbody>{trans_rows}</tbody>
          </table>
        </div>"""

    # --- Score Change Alerts ---
    surges = score_changes.get("surges", [])
    fades = score_changes.get("fades", [])

    if surges or fades:
        change_rows = ""
        for item in surges:
            change_rows += f"""
            <tr style="border-bottom:1px solid #1a1a2e;">
              <td style="padding:10px 16px;font-size:16px;">📈</td>
              <td style="padding:10px 16px;">
                <span style="color:#00d4aa;font-weight:900;font-family:monospace;">{item['ticker']}</span>
                <span style="color:#555;font-size:10px;margin-left:6px;">{item['sector']}</span>
              </td>
              <td style="padding:10px 16px;color:#aaa;font-size:12px;font-family:monospace;">
                {item['prev_score']:.0f} → {item['curr_score']:.0f}
              </td>
              <td style="padding:10px 16px;text-align:right;">
                <span style="color:#00d4aa;font-weight:700;font-family:monospace;">+{item['delta']:.0f} pts</span>
              </td>
            </tr>"""

        for item in fades:
            change_rows += f"""
            <tr style="border-bottom:1px solid #1a1a2e;">
              <td style="padding:10px 16px;font-size:16px;">📉</td>
              <td style="padding:10px 16px;">
                <span style="color:#ff4444;font-weight:900;font-family:monospace;">{item['ticker']}</span>
                <span style="color:#555;font-size:10px;margin-left:6px;">{item['sector']}</span>
              </td>
              <td style="padding:10px 16px;color:#aaa;font-size:12px;font-family:monospace;">
                {item['prev_score']:.0f} → {item['curr_score']:.0f}
              </td>
              <td style="padding:10px 16px;text-align:right;">
                <span style="color:#ff4444;font-weight:700;font-family:monospace;">{item['delta']:.0f} pts</span>
              </td>
            </tr>"""

        body += f"""
        <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;margin-bottom:24px;">
          <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
            <span style="color:#00d4aa;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
              ⚡ Score Changes (±15+ pts WoW)
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <tbody>{change_rows}</tbody>
          </table>
        </div>"""

    # --- Full Score Table ---
    rows = ""
    for r in sorted_results:
        ticker = r.get("ticker", "")
        score = r.get("flow_score", 0) or 0
        rating = r.get("rating", "F")
        label = r.get("label", "")
        price = r.get("price", 0) or 0
        color = _score_color(score)
        pillars = r.get("pillars", {})
        if isinstance(pillars, str):
            import json
            try: pillars = json.loads(pillars)
            except: pillars = {}

        pillar_html = ""
        for key, display in [("capital_flow", "Capital Flow"), ("trend", "Trend"), ("momentum", "Momentum")]:
            p = pillars.get(key, {})
            ps = p.get("score", 0)
            max_pts = 40 if key == "capital_flow" else 30
            bar_pct = (ps / max_pts) * 100
            bar_color = _score_color(ps / max_pts * 100)
            pillar_html += f"""
            <tr>
              <td style="padding:3px 8px;color:#aaa;font-size:11px;width:100px;">{display}</td>
              <td style="padding:3px 8px;">
                <div style="background:#1a1a2e;border-radius:3px;height:6px;width:200px;">
                  <div style="background:{bar_color};width:{bar_pct:.0f}%;height:6px;border-radius:3px;"></div>
                </div>
              </td>
              <td style="padding:3px 8px;color:{bar_color};font-size:11px;font-weight:700;font-family:monospace;">{ps}</td>
            </tr>"""

        rows += f"""
        <tr style="border-bottom:1px solid #1a1a2e;">
          <td style="padding:16px;vertical-align:top;">
            <a href="https://www.tradingview.com/chart/?symbol={ticker}"
               style="font-size:20px;font-weight:900;color:#00d4aa;text-decoration:none;font-family:monospace;">
              {ticker} ↗
            </a>
            <div style="color:#888;font-size:12px;margin-top:4px;">${price:.2f}</div>
          </td>
          <td style="padding:16px;vertical-align:top;text-align:center;min-width:80px;">
            <div style="font-size:36px;font-weight:900;color:{color};font-family:monospace;">{score:.0f}</div>
            <div style="font-size:16px;color:{color};font-weight:700;">{rating}</div>
            <div style="font-size:10px;color:#888;">{label}</div>
          </td>
          <td style="padding:16px;vertical-align:top;">
            <table style="border-collapse:collapse;">{pillar_html}</table>
          </td>
        </tr>"""

    body += f"""
    <div style="background:#0a0a18;border:1px solid #1a1a2e;border-radius:8px;overflow:hidden;">
      <div style="background:#111128;padding:12px 16px;border-bottom:1px solid #1a1a2e;">
        <span style="color:#00d4aa;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
          Flow Scores · {len(sorted_results)} Tickers
        </span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#111128;">
            <th style="padding:10px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">TICKER</th>
            <th style="padding:10px 16px;text-align:center;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">SCORE</th>
            <th style="padding:10px 16px;text-align:left;color:#888;font-size:10px;font-weight:400;letter-spacing:1px;">PILLARS</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    return _email_wrapper("Weekly Flow Score Report", "End of Week Analysis", body)


def send_weekly_report(results: list):
    if not results:
        print("  No results — skipping weekly email")
        return
    today = date.today().strftime("%B %d, %Y")
    html = generate_weekly_html(results)  # handles meta block internally
    _send_email(f"📈 Weekly Flow Scores — {today}", html)


# ============================================================
# DAILY PRICE ALERT (stub — kept for compatibility)
# ============================================================

def send_daily_price_alert():
    pass  # Can be expanded later


if __name__ == "__main__":
    print("Testing scanner email...")
    test_results = {
        "top_sectors": [{"sector": "Energy", "etf": "XLE", "price": 56.19, "ma200": 45.36,
                          "pct_from_200ma": 23.87, "perf_3m": 22.44, "perf_1m": 12.16, "above_200ma": True}],
        "sector_stocks": {"Energy": [
            {"ticker": "CLMT", "name": "Calumet Inc", "price": 29.32, "rs_vs_etf": 26.02,
             "perf_3m": 48.46, "perf_1m": 33.09, "above_200ma": True, "flow_score": 72, "mktcap_b": 2.5}
        ]},
        "unusual_activity": []
    }
    send_scanner_report(test_results)
