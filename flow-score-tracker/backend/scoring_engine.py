"""
Flow Score Scoring Engine
Three Pillars: Capital Flow (40pts) | Trend (30pts) | Momentum (30pts)
Total: 0-100

CHANGELOG (2026-03-08):
- Momentum pillar rebuilt to use Finviz perf fields (perf_week/month/quarter/half/year)
  since bars=[] always. ROC, RS, Accel, MACD-proxy, and multi-period trend now all
  derive from Finviz data. ADX removed (requires bars).
- L2 sector scoring rebalanced: ETF dollar flows now primary signal (0-9pts),
  sector rank secondary (0-4pts), YTD perf tertiary (0-2pts). Max still 15.
- calculate_sector_flow_score: weekly_flow threshold bumped to match real ETF flow
  magnitudes ($500M-$1B range for leading sectors per Flow Map reports).
"""
import numpy as np
from datetime import datetime


# ============================================================
# PILLAR 1: CAPITAL FLOW (40 points total)
# Level 1 - Asset Class (0-10)
# Level 2 - Sector      (0-15)
# Level 3 - Stock       (0-15)
# ============================================================

def score_capital_flow_level1(equity_flow_weekly: float, equity_flow_4wk_avg: float) -> dict:
    """
    Level 1: Is money flowing into equities overall?
    Uses ICI weekly fund flow data.
    equity_flow_weekly: most recent week's equity inflow ($M)
    equity_flow_4wk_avg: 4-week rolling average
    """
    score = 0
    details = []

    if equity_flow_weekly > 0:
        score += 5
        details.append(f"Equity inflows +${equity_flow_weekly/1000:.1f}B")
    else:
        details.append(f"Equity outflows ${equity_flow_weekly/1000:.1f}B")

    # Accelerating vs decelerating
    if equity_flow_weekly > equity_flow_4wk_avg * 1.5:
        score += 5
        details.append("Flows accelerating strongly")
    elif equity_flow_weekly > equity_flow_4wk_avg:
        score += 3
        details.append("Flows above avg")
    elif equity_flow_weekly > 0:
        score += 1
        details.append("Flows positive but slowing")

    return {
        "score": min(10, score),
        "detail": " · ".join(details),
        "raw": {"weekly": equity_flow_weekly, "avg": equity_flow_4wk_avg}
    }


def score_capital_flow_level2(sector_etf_perf_ytd: float, sector_etf_flow_weekly: float,
                               sector_rank: int, total_sectors: int = 11) -> dict:
    """
    Level 2: Is the sector receiving institutional inflows?

    Rebalanced scoring (max 15):
      ETF dollar flow (0-9): primary signal — actual institutional buying
      Sector rank    (0-4): confirms relative sector leadership
      YTD perf       (0-2): long-term trend confirmation
    """
    score = 0
    details = []

    # --- ETF Dollar Flow: primary signal (0-9) ---
    # Thresholds calibrated to real Flow Map data:
    # XLE $934M = elite | XLU $650M = strong | XLB $30M = modest
    if sector_etf_flow_weekly >= 800:
        score += 9
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows (elite)")
    elif sector_etf_flow_weekly >= 400:
        score += 7
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows (strong)")
    elif sector_etf_flow_weekly >= 100:
        score += 5
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows (moderate)")
    elif sector_etf_flow_weekly > 0:
        score += 2
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows (light)")
    elif sector_etf_flow_weekly >= -200:
        score += 0
        details.append(f"${sector_etf_flow_weekly:.0f}M outflows (slight)")
    else:
        score += 0
        details.append(f"${sector_etf_flow_weekly:.0f}M outflows (heavy)")

    # --- Sector Rank (0-4) ---
    if sector_rank <= 2:
        score += 4
        details.append(f"Sector rank #{sector_rank}/11 (elite)")
    elif sector_rank <= 4:
        score += 3
        details.append(f"Sector rank #{sector_rank}/11 (strong)")
    elif sector_rank <= 6:
        score += 1
        details.append(f"Sector rank #{sector_rank}/11 (neutral)")
    else:
        details.append(f"Sector rank #{sector_rank}/11 (weak)")

    # --- YTD Performance (0-2): long-term trend confirmation ---
    if sector_etf_perf_ytd > 10:
        score += 2
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    elif sector_etf_perf_ytd > 5:
        score += 1
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    elif sector_etf_perf_ytd > 0:
        score += 0
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    else:
        details.append(f"ETF {sector_etf_perf_ytd:.1f}% YTD")

    return {
        "score": min(15, score),
        "detail": " · ".join(details),
        "raw": {"ytd": sector_etf_perf_ytd, "flow": sector_etf_flow_weekly, "rank": sector_rank}
    }


def score_capital_flow_level3(bars: list, finviz_data: dict, uw_flow: dict) -> dict:
    """
    Level 3: Is THIS stock receiving direct institutional flow?
    Combines: institutional ownership change, relative volume, options flow.
    (bars unused — kept for API compatibility)
    """
    score = 0
    details = []

    # Institutional ownership change (Finviz)
    inst_trans = finviz_data.get("institutional_trans_pct", 0)
    if inst_trans > 5:
        score += 6
        details.append(f"Inst. buying +{inst_trans:.1f}%")
    elif inst_trans > 2:
        score += 4
        details.append(f"Inst. accumulating +{inst_trans:.1f}%")
    elif inst_trans > 0:
        score += 2
        details.append(f"Slight inst. buying +{inst_trans:.1f}%")
    elif inst_trans < -3:
        details.append(f"Inst. selling {inst_trans:.1f}%")

    # Relative volume (Finviz) — elevated vol = institutional activity
    rel_vol = finviz_data.get("relative_volume", 1.0)
    if rel_vol >= 2.0:
        score += 5
        details.append(f"RelVol {rel_vol:.1f}x (heavy buying)")
    elif rel_vol >= 1.5:
        score += 3
        details.append(f"RelVol {rel_vol:.1f}x (above avg)")
    elif rel_vol >= 1.2:
        score += 1
        details.append(f"RelVol {rel_vol:.1f}x (slight pickup)")

    # Options flow (Tradier/Unusual Whales)
    pc_ratio = uw_flow.get("put_call_ratio", 1.0)
    sweeps = uw_flow.get("sweep_count", 0)
    if pc_ratio < 0.5 and sweeps >= 5:
        score += 4
        details.append(f"Bullish flow + {sweeps} sweeps")
    elif pc_ratio < 0.7:
        score += 2
        details.append(f"Call-heavy flow P/C {pc_ratio:.2f}")

    return {
        "score": min(15, score),
        "detail": " · ".join(details) or "No accumulation signal",
        "raw": {"inst_trans": inst_trans, "pc_ratio": pc_ratio, "sweeps": sweeps,
                "rel_vol": rel_vol}
    }


def score_capital_flow_pillar(l1: dict, l2: dict, l3: dict) -> dict:
    total = l1["score"] + l2["score"] + l3["score"]
    return {
        "score": min(40, total),
        "level1": l1,
        "level2": l2,
        "level3": l3,
        "detail": f"L1:{l1['score']}/10 · L2:{l2['score']}/15 · L3:{l3['score']}/15"
    }


# ============================================================
# PILLAR 2: TREND (30 points total)
# 20-day MA (0-10) | 50-day MA (0-10) | 200-day MA (0-10)
# ============================================================

def score_trend_pillar(price: float, ma20: float, ma50: float, ma200: float, bars: list) -> dict:
    """
    Trend scoring across three timeframes.
    Each MA worth 10 points. Score also considers distance above MA.
    """
    score = 0
    details = []

    def ma_score(price, ma, label, max_pts=10):
        if not ma or ma == 0:
            return 0, f"{label}: no data"
        pct_above = (price - ma) / ma * 100
        if price > ma:
            pts = min(max_pts, 5 + min(5, pct_above))
            return pts, f"Above {label} (+{pct_above:.1f}%)"
        else:
            return 0, f"Below {label} ({pct_above:.1f}%)"

    s20, d20 = ma_score(price, ma20, "20MA")
    s50, d50 = ma_score(price, ma50, "50MA")
    s200, d200 = ma_score(price, ma200, "200MA")

    score = s20 + s50 + s200
    details = [d20, d50, d200]

    # Golden cross bonus: 50MA > 200MA
    if ma50 and ma200 and ma50 > ma200:
        score = min(30, score + 2)
        details.append("Golden cross")

    return {
        "score": min(30, score),
        "detail": " · ".join(details),
        "raw": {
            "price": price, "ma20": ma20, "ma50": ma50, "ma200": ma200,
            "s20": round(s20, 1), "s50": round(s50, 1), "s200": round(s200, 1)
        }
    }


# ============================================================
# PILLAR 3: MOMENTUM (30 points total)
#
# All 5 components use Finviz perf fields since bars=[]:
#  1. Rate of Change    (0-6)  — perf_quarter magnitude
#  2. Relative Strength (0-6)  — outperformance vs SPY
#  3. Acceleration      (0-6)  — short vs long-term perf
#  4. Multi-period trend(0-6)  — perf_week/month/quarter all positive
#  5. Sector alpha      (0-6)  — outperformance vs sector ETF
# ============================================================

def score_momentum_pillar(bars: list, finviz_data: dict,
                           spy_perf_63d: float, sector_perf_63d: float) -> dict:
    """
    Momentum scored entirely from Finviz perf fields.
    bars parameter kept for API compatibility but not used.
    """
    scores = {}
    details = []

    perf_week    = finviz_data.get("perf_week", 0) or 0
    perf_month   = finviz_data.get("perf_month", 0) or 0
    perf_quarter = finviz_data.get("perf_quarter", 0) or 0
    perf_half    = finviz_data.get("perf_half", 0) or 0
    perf_year    = finviz_data.get("perf_year", 0) or 0

    # -------------------------------------------------------
    # 1. RATE OF CHANGE (0-6) — 63-day (quarter) magnitude
    # -------------------------------------------------------
    roc = perf_quarter
    if roc > 30:      roc_score = 6
    elif roc > 20:    roc_score = 5
    elif roc > 10:    roc_score = 4
    elif roc > 5:     roc_score = 3
    elif roc > 0:     roc_score = 1
    else:             roc_score = 0
    scores["roc"] = roc_score
    details.append(f"ROC 63d:{roc:+.1f}%")

    # -------------------------------------------------------
    # 2. RELATIVE STRENGTH vs SPY (0-6)
    # -------------------------------------------------------
    rs_score = 0
    if spy_perf_63d is not None and perf_quarter:
        outperf = perf_quarter - spy_perf_63d
        if outperf > 15:      rs_score = 6
        elif outperf > 10:    rs_score = 5
        elif outperf > 5:     rs_score = 4
        elif outperf > 0:     rs_score = 2
        elif outperf > -5:    rs_score = 1
        details.append(f"RS vs SPY:{outperf:+.1f}%")
    else:
        details.append("RS: no SPY data")
    scores["rs"] = rs_score

    # -------------------------------------------------------
    # 3. ACCELERATION — short-term vs long-term perf (0-6)
    # perf_month (21d) vs perf_half (126d) as proxy
    # -------------------------------------------------------
    accel_score = 0
    if perf_month and perf_half:
        # annualize to compare apples-to-apples
        monthly_rate = perf_month
        half_monthly_rate = perf_half / 6  # avg monthly over 6 months
        accel = monthly_rate - half_monthly_rate
        if accel > 5:        accel_score = 6
        elif accel > 2:      accel_score = 4
        elif accel > 0:      accel_score = 2
        elif accel > -2:     accel_score = 1
        details.append(f"Accel:{accel:+.1f}pts")
    else:
        details.append("Accel: no data")
    scores["accel"] = accel_score

    # -------------------------------------------------------
    # 4. MULTI-PERIOD TREND — all timeframes pointing up (0-6)
    # -------------------------------------------------------
    trend_score = 0
    positives = sum(1 for p in [perf_week, perf_month, perf_quarter, perf_half, perf_year] if p > 0)
    if positives == 5:        trend_score = 6
    elif positives >= 4:      trend_score = 4
    elif positives >= 3:      trend_score = 2
    elif positives >= 2:      trend_score = 1
    details.append(f"Multi-period:{positives}/5 green")
    scores["multi"] = trend_score

    # -------------------------------------------------------
    # 5. SECTOR ALPHA — outperformance vs sector ETF (0-6)
    # -------------------------------------------------------
    alpha_score = 0
    if sector_perf_63d is not None and perf_quarter:
        sector_alpha = perf_quarter - sector_perf_63d
        if sector_alpha > 15:      alpha_score = 6
        elif sector_alpha > 8:     alpha_score = 5
        elif sector_alpha > 3:     alpha_score = 4
        elif sector_alpha > 0:     alpha_score = 2
        elif sector_alpha > -5:    alpha_score = 1
        details.append(f"Sector alpha:{sector_alpha:+.1f}%")
    else:
        details.append("Sector alpha: no data")
    scores["alpha"] = alpha_score

    total = sum(scores.values())

    return {
        "score": min(30, total),
        "detail": " · ".join(details),
        "raw": {
            "roc_score":   scores["roc"],
            "rs_score":    scores["rs"],
            "accel_score": scores["accel"],
            "multi_score": scores["multi"],
            "alpha_score": scores["alpha"],
            "perf_week":    perf_week,
            "perf_month":   perf_month,
            "perf_quarter": perf_quarter,
            "perf_half":    perf_half,
            "perf_year":    perf_year,
        }
    }


# ============================================================
# COMPOSITE FLOW SCORE
# ============================================================

def calculate_flow_score(capital_flow: dict, trend: dict, momentum: dict) -> dict:
    total = capital_flow["score"] + trend["score"] + momentum["score"]
    score = round(total, 1)

    if score >= 85:
        rating = "ELITE"
        label = "Primary Buy"
        color = "#00ff88"
        action = "Flow Trade: 120 DTE, .25 Delta"
    elif score >= 70:
        rating = "STRONG"
        label = "Strong Setup"
        color = "#7fff7f"
        action = "Flow Trade: 120 DTE, .25 Delta"
    elif score >= 50:
        rating = "NEUTRAL"
        label = "Watch Only"
        color = "#ffd700"
        action = "Watchlist only. Wait."
    elif score >= 30:
        rating = "WEAK"
        label = "Avoid"
        color = "#ff9944"
        action = "Avoid completely."
    else:
        rating = "TOXIC"
        label = "Do Not Touch"
        color = "#ff3333"
        action = "Do not touch."

    return {
        "flow_score": score,
        "rating": rating,
        "label": label,
        "color": color,
        "action": action,
        "pillars": {
            "capital_flow": capital_flow,
            "trend": trend,
            "momentum": momentum,
        },
        "scored_at": datetime.now().isoformat(),
    }


def detect_burst_trade(current_score: float, previous_score: float) -> dict:
    """
    Burst Trade = score jumps 15+ points in a single week.
    Uses shorter DTE and higher delta than Flow Trade.
    """
    jump = current_score - previous_score if previous_score else 0
    is_burst = jump >= 15 and current_score >= 65

    return {
        "is_burst": is_burst,
        "score_jump": round(jump, 1),
        "trade_type": "Burst Trade" if is_burst else "Flow Trade" if current_score >= 80 else "None",
        "options_params": "30-45 DTE · .40-.50 Delta · Never roll · Sell the double" if is_burst else
                          "120 DTE · .25 Delta · Roll winners only · Sell the double" if current_score >= 80 else
                          "No trade — score too low"
    }


# ============================================================
# SECTOR FLOW SCORE
# ============================================================

SECTOR_ETFS = {
    "Energy": "XLE",
    "Utilities": "XLU",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Health Care": "XLV",
    "Real Estate": "XLRE",
    "Comm Services": "XLC",
    "Consumer Disc": "XLY",
    "Financials": "XLF",
    "Technology": "XLK",
}


def calculate_sector_flow_score(sector_name: str, etf_data: dict,
                                 equity_flow: float, equity_avg: float) -> dict:
    """
    Sector-level Flow Score.
    Uses actual ETF dollar flows from fund_flows table when available.
    weekly_flow should be in $M (e.g. 934 for XLE's $934M inflow).
    """
    ytd_perf    = etf_data.get("perf_ytd", 0) or 0
    weekly_flow = etf_data.get("weekly_flow", 0) or 0
    price       = etf_data.get("price", 0) or 0
    ma50        = etf_data.get("sma50", 0) or 0
    ma200       = etf_data.get("sma200", 0) or 0
    ma20        = etf_data.get("sma20", price) or price

    # Capital flow: equity environment + ETF flows
    l1_equity = 10 if equity_flow > 0 else 0
    # ETF inflow tiers calibrated to real data ($M)
    if weekly_flow >= 800:      l2_flow = 15
    elif weekly_flow >= 400:    l2_flow = 12
    elif weekly_flow >= 100:    l2_flow = 8
    elif weekly_flow >= 30:     l2_flow = 5
    elif weekly_flow > 0:       l2_flow = 2
    else:                       l2_flow = 0

    capital_score = min(40, l1_equity + l2_flow +
                        (15 if ytd_perf > 10 else 8 if ytd_perf > 5 else 3 if ytd_perf > 0 else 0))

    trend_score = min(30,
        (10 if price > ma20  else 0) +
        (10 if price > ma50  else 0) +
        (10 if price > ma200 else 0)
    )

    # Momentum: YTD perf magnitude + flow size as confirmation
    ytd_mom = (15 if ytd_perf > 15 else 10 if ytd_perf > 8 else 5 if ytd_perf > 0 else 0)
    flow_mom = (15 if weekly_flow >= 500 else 10 if weekly_flow >= 100 else 5 if weekly_flow > 0 else 0)
    momentum_score = min(30, ytd_mom + flow_mom)

    total = capital_score + trend_score + momentum_score

    return {
        "sector": sector_name,
        "etf": SECTOR_ETFS.get(sector_name, ""),
        "flow_score": round(total, 1),
        "capital_flow": capital_score,
        "trend": trend_score,
        "momentum": momentum_score,
        "etf_flow_m": weekly_flow,
        "ytd_perf": ytd_perf,
        "status": "LEADING" if total >= 70 else "NEUTRAL" if total >= 50 else "WEAK"
    }
