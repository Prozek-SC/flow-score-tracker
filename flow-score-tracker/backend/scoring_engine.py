""" 
Flow Score Scoring Engine
Three Pillars: Capital Flow (40pts) | Trend (30pts) | Momentum (30pts)
Total: 0-100

REBUILD (2026-03-17):
- L1: Falls back to SPY/market context when ICI fund_flows table is empty
- L2: Sector ETF flow uses perf_3m proxy; rank and YTD confirmed
- L3: Rebuilt to measure stock outperformance vs sector ETF + SPY over 63 days
       (matches document: "CVX outperforming XLE, SPY over last 63 days = +13/15")
- Momentum: Rebuilt to 3-component structure matching document exactly:
       Rate of Change (0-10) | Relative Strength (0-10) | Acceleration (0-10)
"""
import numpy as np
from datetime import datetime


# ============================================================
# PILLAR 1: CAPITAL FLOW (40 points total)
# Level 1 - Asset Class (0-10)
# Level 2 - Sector      (0-15)
# Level 3 - Stock       (0-15)
# ============================================================

def score_capital_flow_level1(equity_flow_weekly: float, equity_flow_4wk_avg: float,
                               spy_above_200ma: bool = True) -> dict:
    """
    Level 1: Is money flowing into equities overall?

    Primary: ICI weekly fund flow data (from fund_flows table).
    Fallback: When no ICI data available, use SPY trend as market context proxy.
      - SPY above 200MA = positive equity environment = 7/10
      - SPY below 200MA = risk-off environment = 3/10
    Document benchmark: $14.6B into equities = +8/10
    """
    score = 0
    details = []

    if equity_flow_weekly != 0:
        # Real ICI data available
        if equity_flow_weekly > 0:
            score += 5
            details.append(f"Equity inflows +${equity_flow_weekly/1000:.1f}B")
        else:
            details.append(f"Equity outflows ${equity_flow_weekly/1000:.1f}B")

        if equity_flow_weekly > equity_flow_4wk_avg * 1.5:
            score += 5
            details.append("Flows accelerating strongly")
        elif equity_flow_weekly > equity_flow_4wk_avg:
            score += 3
            details.append("Flows above avg")
        elif equity_flow_weekly > 0:
            score += 1
            details.append("Flows positive but slowing")
    else:
        # Fallback: use SPY 200MA as market regime proxy
        # SPY above 200MA historically correlates with net equity inflows
        if spy_above_200ma:
            score = 7
            details.append("Market regime: bull (SPY above 200MA)")
        else:
            score = 3
            details.append("Market regime: risk-off (SPY below 200MA)")

    return {
        "score": min(10, score),
        "detail": " · ".join(details),
        "raw": {"weekly": equity_flow_weekly, "avg": equity_flow_4wk_avg,
                "spy_above_200ma": spy_above_200ma}
    }


def score_capital_flow_level2(sector_etf_perf_ytd: float, sector_etf_flow_weekly: float,
                               sector_rank: int, total_sectors: int = 11) -> dict:
    """
    Level 2: Is the sector receiving institutional inflows?

    ETF dollar flow (0-9): primary signal
    Sector rank    (0-4): relative leadership
    YTD perf       (0-2): trend confirmation
    Document benchmark: Energy strong inflows + #1 rank = +14/15
    """
    score = 0
    details = []

    # --- ETF Dollar Flow (0-9) ---
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
    elif sector_etf_flow_weekly >= -100:
        score += 1
        details.append(f"${sector_etf_flow_weekly:.0f}M outflows (slight)")
    else:
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

    # --- YTD Performance (0-2) ---
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


def score_capital_flow_level3(bars: list, finviz_data: dict, uw_flow: dict,
                               spy_perf_63d: float = 0,
                               sector_perf_63d: float = 0) -> dict:
    """
    Level 3: Is THIS stock receiving direct institutional flow?

    REBUILT to match document definition:
    "CVX outperforming XLE, SPY over last 63 days = +13/15"

    The document measures L3 as RELATIVE OUTPERFORMANCE vs sector ETF and SPY,
    not institutional ownership percentage. We have this data already.

    Structure (0-15):
      Outperformance vs SPY 63d  (0-7): primary — beating the market
      Outperformance vs Sector   (0-5): secondary — beating the sector
      Relative Volume            (0-3): confirms active accumulation
    """
    score = 0
    details = []

    perf_quarter = finviz_data.get("perf_quarter", 0) or 0

    # --- Outperformance vs SPY (0-7) ---
    # Document: CVX outperforming SPY over 63 days is key L3 signal
    vs_spy_score = 0
    if spy_perf_63d is not None and perf_quarter:
        vs_spy = perf_quarter - spy_perf_63d
        if vs_spy > 20:       vs_spy_score = 7
        elif vs_spy > 12:     vs_spy_score = 6
        elif vs_spy > 7:      vs_spy_score = 5
        elif vs_spy > 3:      vs_spy_score = 3
        elif vs_spy > 0:      vs_spy_score = 1
        details.append(f"vs SPY:{vs_spy:+.1f}% ({vs_spy_score}pts)")
    else:
        details.append("vs SPY: no data")
    score += vs_spy_score

    # --- Outperformance vs Sector ETF (0-5) ---
    # Document: CVX outperforming XLE over 63 days
    vs_sector_score = 0
    if sector_perf_63d is not None and perf_quarter:
        vs_sector = perf_quarter - sector_perf_63d
        if vs_sector > 15:    vs_sector_score = 5
        elif vs_sector > 8:   vs_sector_score = 4
        elif vs_sector > 3:   vs_sector_score = 3
        elif vs_sector > 0:   vs_sector_score = 1
        details.append(f"vs Sector:{vs_sector:+.1f}% ({vs_sector_score}pts)")
    else:
        details.append("vs Sector: no data")
    score += vs_sector_score

    # --- Relative Volume (0-3): confirms accumulation ---
    rel_vol = finviz_data.get("relative_volume", 1.0) or 1.0
    if rel_vol >= 2.0:
        score += 3
        details.append(f"RelVol {rel_vol:.1f}x")
    elif rel_vol >= 1.5:
        score += 2
        details.append(f"RelVol {rel_vol:.1f}x")
    elif rel_vol >= 1.2:
        score += 1
        details.append(f"RelVol {rel_vol:.1f}x")

    return {
        "score": min(15, score),
        "detail": " · ".join(details) or "No outperformance signal",
        "raw": {
            "perf_quarter": perf_quarter,
            "spy_perf_63d": spy_perf_63d,
            "sector_perf_63d": sector_perf_63d,
            "vs_spy": round(perf_quarter - (spy_perf_63d or 0), 2),
            "vs_sector": round(perf_quarter - (sector_perf_63d or 0), 2),
            "rel_vol": rel_vol
        }
    }


def score_capital_flow_pillar(l1: dict, l2: dict, l3: dict) -> dict:
    """
    Capital Flow composite. Max 40 with full ICI data, 32 without.

    CALIBRATION — confirmed against two TTI Hit List reports:
      4/22/2026 (42 benchmarks) and 4/29/2026 (100 benchmarks):
      - Observed CF ceiling = 32 in both reports (MXL at top both weeks)
      - 0% of benchmarks hit 40 → the 8pt gap = missing ICI fund flow data
      - Without ICI, L1 uses SPY 200MA fallback (max 7) + L2 (15) + L3 (15) = 37
      - Cap at 32 when no ICI so scores align with how TTI publishes them
      - CF range observed: 15 (HP, energy driller) to 32 (MXL, sustained leader)
    """
    total = l1["score"] + l2["score"] + l3["score"]

    # Detect fallback mode: L1 used SPY proxy instead of real ICI flow data
    has_ici_data = l1.get("raw", {}).get("weekly", 0) != 0
    effective_max = 40 if has_ici_data else 32

    return {
        "score": min(effective_max, total),
        "level1": l1,
        "level2": l2,
        "level3": l3,
        "has_ici_data": has_ici_data,
        "detail": f"L1:{l1['score']}/10 · L2:{l2['score']}/15 · L3:{l3['score']}/15"
                  + ("" if has_ici_data else " · capped@32 (no ICI)")
    }


# ============================================================
# PILLAR 2: TREND (30 points total)
# 20-day MA (0-10) | 50-day MA (0-10) | 200-day MA (0-10)
# Document: "Capital flow gives direction. Trend confirms it."
# ============================================================

def score_trend_pillar(price: float, ma20: float, ma50: float, ma200: float, bars: list) -> dict:
    """
    Trend scoring across three timeframes.
    Each MA worth 10 points. Partial credit for distance above MA.
    Document benchmark: all top stocks score 30/30 (above all 3 MAs).
    """
    score = 0
    details = []

    def ma_score(price, ma, label, max_pts=10):
        if not ma or ma == 0:
            return 0, f"{label}: no data"
        pct_above = (price - ma) / ma * 100
        if price > ma:
            # Full 10 if well above, partial if just above
            pts = min(max_pts, 5 + min(5, pct_above))
            return round(pts, 1), f"Above {label} (+{pct_above:.1f}%)"
        else:
            return 0, f"Below {label} ({pct_above:.1f}%)"

    s20, d20 = ma_score(price, ma20, "20MA")
    s50, d50 = ma_score(price, ma50, "50MA")
    s200, d200 = ma_score(price, ma200, "200MA")

    score = s20 + s50 + s200

    # Golden cross bonus: 50MA > 200MA (2pt bonus, capped at 30)
    if ma50 and ma200 and ma50 > ma200:
        score = min(30, score + 2)
        details = [d20, d50, d200, "Golden cross +2"]
    else:
        details = [d20, d50, d200]

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
# Document structure (page 14):
#   Rate of Change    (0-10): percentile ranked across universe
#   Relative Strength (0-10): outperforming SPY? Sector?
#   Acceleration      (0-10): short-term momentum > medium-term?
# ============================================================

def score_roc_percentile(perf_quarter: float, universe_perfs: list) -> int:
    """
    Percentile-rank perf_quarter within the scored universe (0-10 pts).

    TTI scores ROC as a universe percentile across 3,723 stocks.
    Our universe is smaller (~200-400 scanner candidates) but filtering
    already removed weak stocks, so the distribution is comparable.

    Returns None when the universe is too small to rank meaningfully
    (< 20 stocks) so callers can fall back to absolute thresholds.
    """
    valid = [p for p in universe_perfs if p is not None]
    if len(valid) < 20:
        return None

    rank = sum(1 for p in valid if p <= perf_quarter)
    pct  = rank / len(valid) * 100

    if pct >= 90:   return 10
    elif pct >= 75: return 8
    elif pct >= 60: return 6
    elif pct >= 45: return 4
    elif pct >= 30: return 2
    elif pct >= 15: return 1
    else:           return 0


def score_momentum_pillar(bars: list, finviz_data: dict,
                           spy_perf_63d: float, sector_perf_63d: float,
                           universe_perfs: list = None) -> dict:
    """
    Momentum: 3 components × 10pts = 30pts max.
    Matches document exactly: ROC | RS | Acceleration.

    Document benchmark:
      Energy stocks with +25% 3M perf score 24-28/30
      Tech stocks with -5% 3M perf score 6/30
    """
    scores = {}
    details = []

    perf_week    = finviz_data.get("perf_week", 0) or 0
    perf_month   = finviz_data.get("perf_month", 0) or 0
    perf_quarter = finviz_data.get("perf_quarter", 0) or 0
    perf_half    = finviz_data.get("perf_half", 0) or 0
    perf_year    = finviz_data.get("perf_year", 0) or 0

    # perf_half drives the Acceleration component. If missing (TradingView fallback
    # often returns 0 for Perf.6M), estimate from year / 2. This is conservative
    # vs quarter * 2 and avoids overstating acceleration for recent-only movers.
    if not perf_half and perf_year:
        perf_half = perf_year / 2
    elif not perf_half and perf_quarter:
        perf_half = perf_quarter * 1.5

    # -------------------------------------------------------
    # 1. RATE OF CHANGE (0-10)
    # Document: "Percentile ranked across the entire universe"
    # When universe_perfs is provided (scanner two-pass), use actual
    # percentile rank within the scored batch.  Falls back to absolute
    # thresholds when the universe is too small (< 20 stocks) or absent.
    # -------------------------------------------------------
    roc = perf_quarter
    roc_pct = score_roc_percentile(roc, universe_perfs) if universe_perfs else None
    if roc_pct is not None:
        roc_score = roc_pct
        details.append(f"ROC:{roc:+.1f}% (pct={roc_score}pts)")
    else:
        if roc > 30:      roc_score = 10
        elif roc > 20:    roc_score = 8
        elif roc > 12:    roc_score = 6
        elif roc > 7:     roc_score = 4
        elif roc > 3:     roc_score = 2
        elif roc > 0:     roc_score = 1
        else:             roc_score = 0
        details.append(f"ROC:{roc:+.1f}% (abs={roc_score}pts)")
    scores["roc"] = roc_score

    # -------------------------------------------------------
    # 2. RELATIVE STRENGTH (0-10)
    # Document: "Is this stock outperforming SPY? Sector?"
    # Use the better of vs-SPY or vs-Sector outperformance
    # -------------------------------------------------------
    rs_score = 0
    vs_spy = (perf_quarter - spy_perf_63d) if spy_perf_63d is not None else None
    vs_sector = (perf_quarter - sector_perf_63d) if sector_perf_63d is not None else None

    # Score vs SPY (primary)
    spy_pts = 0
    if vs_spy is not None:
        if vs_spy > 20:       spy_pts = 10
        elif vs_spy > 12:     spy_pts = 8
        elif vs_spy > 7:      spy_pts = 6
        elif vs_spy > 3:      spy_pts = 4
        elif vs_spy > 0:      spy_pts = 2
        elif vs_spy > -5:     spy_pts = 1

    # Score vs Sector (secondary — bonus if outperforming both)
    sector_pts = 0
    if vs_sector is not None:
        if vs_sector > 15:    sector_pts = 3
        elif vs_sector > 8:   sector_pts = 2
        elif vs_sector > 3:   sector_pts = 1

    # Combine: SPY is primary, sector adds bonus up to max 10
    rs_score = min(10, spy_pts + sector_pts)
    scores["rs"] = rs_score

    spy_str = f"vs SPY:{vs_spy:+.1f}%" if vs_spy is not None else "no SPY"
    sec_str = f"vs Sector:{vs_sector:+.1f}%" if vs_sector is not None else "no sector"
    details.append(f"RS: {spy_str} · {sec_str} ({rs_score}pts)")

    # -------------------------------------------------------
    # 3. ACCELERATION (0-10)
    # Document: "Is short-term momentum > medium-term?"
    # perf_month (21d) vs perf_half/6 (avg monthly rate over 6mo)
    # Also checks weekly vs monthly for very short-term acceleration
    # -------------------------------------------------------
    accel_score = 0
    if perf_month and perf_half:
        half_monthly_rate = perf_half / 6
        accel = perf_month - half_monthly_rate
        if accel > 8:         accel_score = 10
        elif accel > 5:       accel_score = 8
        elif accel > 3:       accel_score = 6
        elif accel > 1:       accel_score = 4
        elif accel > 0:       accel_score = 2
        elif accel > -2:      accel_score = 1
        details.append(f"Accel:{accel:+.1f}pts ({accel_score}pts)")
    elif perf_month and perf_quarter:
        # Fallback: monthly vs quarterly rate
        qtr_monthly_rate = perf_quarter / 3
        accel = perf_month - qtr_monthly_rate
        if accel > 5:         accel_score = 8
        elif accel > 2:       accel_score = 5
        elif accel > 0:       accel_score = 3
        elif accel > -2:      accel_score = 1
        details.append(f"Accel(short):{accel:+.1f}pts ({accel_score}pts)")
    else:
        details.append("Accel: no data")
    scores["accel"] = accel_score

    total = scores["roc"] + scores["rs"] + scores["accel"]

    # CALIBRATION — confirmed against 4/22 (42 benchmarks) and 4/29 (100 benchmarks):
    # Zero tickers exceeded 28 in either report; ~50% hit exactly 28 both weeks.
    # 2pt gap vs the 30pt max = universe-percentile rank factor TTI computes internally.
    # Range observed: 17 (SBRA, low-momentum REIT) to 28 (ARM, TXN, MXL, most leaders).
    return {
        "score": min(28, total),
        "detail": " · ".join(details),
        "raw": {
            "roc_score":    scores["roc"],
            "rs_score":     scores["rs"],
            "accel_score":  scores["accel"],
            "perf_week":    perf_week,
            "perf_month":   perf_month,
            "perf_quarter": perf_quarter,
            "perf_half":    perf_half,
            "perf_year":    perf_year,
            "vs_spy":       round(vs_spy, 2) if vs_spy is not None else None,
            "vs_sector":    round(vs_sector, 2) if vs_sector is not None else None,
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


def detect_burst_trade(current_score: float, previous_score: float,
                        adv_m: float = None, iv_pct: float = None) -> dict:
    """
    TTI Hit List tier classification. Confirmed against 4/22 and 4/29 reports.

      Tier 1 — BURST TRIGGER:  jump ≥ 15 AND score ≥ 70 AND ADV ≥ $5M
               → 30-45 DTE, .40-.50 Delta (or .60-.70 on IV > 60%), sell half at 2x,
                 trim at 3x, close at 5x, never roll, no stops
      Tier 2 — NEAR BURST:     10 ≤ jump < 15 AND score ≥ 70
               → watch for acceleration, one more push triggers
      Tier 3 — BIG MOVE:       jump ≥ 15 AND 60 ≤ score < 70
               → flow there, confirmation not yet
      Tier 4 — HIGH CONVICTION: score ≥ 80 AND jump < 10
               → sustained positioning, position hold not burst entry

      adv_m:  Average Daily Dollar Volume in millions. Tier 1 requires ≥ $5M.
              Pass None to skip check (backwards compatible).
      iv_pct: Implied Volatility as a percentage (e.g. 75 for 75% IV).
              High IV (> 60%) → TTI recommends .60-.70 delta for more intrinsic.
    """
    jump = current_score - previous_score if previous_score else 0
    jump = round(jump, 1)

    tier = None
    is_burst = False
    trade_type = "None"
    options_params = "No trade — score too low"

    # ADV check: Tier 1 requires ≥ $5M daily dollar volume (per TTI 4/29 report)
    adv_qualifies = (adv_m is None) or (adv_m >= 5)

    # Delta target: .60-.70 for high IV names (IV > 60%), else standard .40-.50
    if iv_pct is not None and iv_pct > 60:
        delta_target = ".60-.70 Delta (high IV — more intrinsic, less time decay)"
    else:
        delta_target = ".40-.50 Delta"

    if jump >= 15 and current_score >= 70 and adv_qualifies:
        tier = "TIER_1_BURST"
        is_burst = True
        trade_type = "Burst Trade"
        options_params = (f"30-45 DTE · {delta_target} · "
                          "Sell half at 2x · Trim at 3x · Close at 5x · Never roll · No stops")
    elif jump >= 15 and current_score >= 70 and not adv_qualifies:
        tier = "TIER_1_LOW_LIQ"
        trade_type = "Burst (low liquidity)"
        options_params = f"Score/jump qualify but ADV ${adv_m:.1f}M < $5M — too illiquid for standard sizing"
    elif 10 <= jump < 15 and current_score >= 70:
        tier = "TIER_2_NEAR_BURST"
        trade_type = "Near Burst (watch)"
        options_params = "Watch for acceleration — one more push triggers full burst"
    elif jump >= 15 and 60 <= current_score < 70:
        tier = "TIER_3_BIG_MOVE"
        trade_type = "Big Move (unconfirmed)"
        options_params = "Flow is there. Score not yet. Wait for confirmation."
    elif current_score >= 80 and jump < 10:
        tier = "TIER_4_HIGH_CONVICTION"
        trade_type = "High Conviction Hold"
        options_params = "Position hold · 120 DTE · .25 Delta · Sustained positioning"
    elif current_score >= 80:
        tier = "FLOW_TRADE"
        trade_type = "Flow Trade"
        options_params = "120 DTE · .25 Delta · Roll winners only · Sell the double"

    return {
        "is_burst": is_burst,
        "tier": tier,
        "score_jump": jump,
        "trade_type": trade_type,
        "options_params": options_params,
        "adv_m": adv_m,
        "iv_pct": iv_pct,
    }


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


def score_sector_capital_flow(weekly_flow_m: float,
                              monthly_flow_m: float = None,
                              flow_aum_pct: float = None) -> float:
    """
    Sector Capital Flow score (0-40), calibrated against 10 weeks of TTI Flow
    Map reports (see ../TTI_FORMULA_FINDINGS.md).

    Key empirical finding: CF is driven by NORMALIZED flow (Flow/AUM) and flow
    DIRECTION / ACCELERATION (weekly vs the trailing 4-week trend) — NOT raw
    dollar volume. The sector pulling the most dollars can post the LOWEST CF,
    because a big fund's inflow is small relative to its AUM (e.g. XLF took the
    most $ on 2026-02-28 yet scored the lowest CF). This reproduces that.

    Accuracy vs the reports: absolute MAE ~3 pts, but sector RANK agreement —
    what actually picks leaders vs laggards — is ~0.83 Spearman / 83% pairwise.
    Refine the thresholds as more weekly reports are collected.

    weekly_flow_m  : this week's net ETF flow, $M (creation/redemption).
    monthly_flow_m : trailing 4-week net flow, $M (direction/acceleration).
                     Falls back to weekly*4 when unknown.
    flow_aum_pct   : weekly flow as a % of fund AUM (conviction). 0 if unknown.
    """
    wk = weekly_flow_m or 0
    mn = monthly_flow_m if monthly_flow_m is not None else wk * 4
    aum = flow_aum_pct or 0

    # Base: weekly flow direction and magnitude (the strongest single signal).
    if   wk <= -700: cf = 11
    elif wk <= -330: cf = 14
    elif wk <=  -50: cf = 17
    elif wk <=   60: cf = 20
    elif wk <=  366: cf = 22
    else:            cf = 24

    # Acceleration: is the week running with or against the 4-week trend?
    # The monthly trend dominates — a single green week can't rescue a sector
    # whose month is collapsing (e.g. XLE: +$314M week on a -$1.3B month -> CF 9).
    if   wk > 60 and mn > 500:   cf += 3            # sustained multi-week inflow
    elif wk > 0  and mn < -800:  cf = min(cf, 12)   # weekly pop vs a collapsing month
    elif wk > 0  and mn < -13:   cf -= 2            # weekly pop, month still bleeding
    elif wk < 0  and mn < -150:  cf -= 1            # sustained outflow

    # Conviction: Flow/AUM gates the top scores, but only when the month confirms
    # (guards a small fund's high-% one-week blip from scoring too hot).
    if mn > 0:
        if   aum >= 1.6: cf += 3
        elif aum >= 1.0: cf += 2
        elif aum >= 0.4: cf += 1
    if aum <= -0.4:      cf -= 2

    return float(max(0, min(40, cf)))


def calculate_sector_flow_score(sector_name: str, etf_data: dict,
                                 equity_flow: float, equity_avg: float) -> dict:
    """
    Sector-level Flow Score. Max 100.
    Capital Flow now uses Flow/AUM-normalized ETF flow (score_sector_capital_flow),
    calibrated to the TTI Flow Map reports, instead of the old perf_week proxy.
    """
    ytd_perf    = etf_data.get("perf_ytd", 0) or 0
    weekly_flow = etf_data.get("weekly_flow", 0) or 0
    price       = etf_data.get("price", 0) or 0
    ma50        = etf_data.get("sma50", 0) or 0
    ma200       = etf_data.get("sma200", 0) or 0
    ma20        = etf_data.get("sma20", price) or price

    # Capital Flow — Flow/AUM-normalized, calibrated to TTI Flow Maps.
    # Real ETF creation/redemption flow + 4-week flow + Flow/AUM% drive this once
    # the pipeline supplies them; until then weekly_flow may be the legacy proxy
    # and monthly_flow/flow_aum fall back inside score_sector_capital_flow.
    monthly_flow = etf_data.get("monthly_flow")
    flow_aum     = etf_data.get("flow_aum")
    capital_score = score_sector_capital_flow(weekly_flow, monthly_flow, flow_aum)

    trend_score = min(30,
        (10 if price > ma20  else 0) +
        (10 if price > ma50  else 0) +
        (10 if price > ma200 else 0)
    )

    ytd_mom  = 15 if ytd_perf > 15 else 10 if ytd_perf > 8 else 5 if ytd_perf > 0 else 0
    flow_mom = 15 if weekly_flow >= 500 else 10 if weekly_flow >= 100 else 5 if weekly_flow > 0 else 0
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


# ============================================================
# OPTIONS CONTRACT QUALITY
# Grade the actual contract to buy against the TTI options checklist:
# liquidity (OI / volume / spread), delta fit to the trade template, and IV
# regime. Turns "Flow Score 85" into "85, and the $90 call is an A-grade buy."
# (Risk/reward vs a 1.618 Fib price target is a follow-up — needs bar data.)
# ============================================================

OPTION_TEMPLATES = {
    # Fast burst trade off a fresh score jump.
    "burst": {"dte_min": 30, "dte_max": 45, "dte_target": 44,
              "delta_lo": 0.40, "delta_hi": 0.50, "delta_target": 0.45},
    # Slower swing / flow trade on sustained conviction.
    "swing": {"dte_min": 60, "dte_max": 90, "dte_target": 75,
              "delta_lo": 0.20, "delta_hi": 0.30, "delta_target": 0.25},
}


def choose_option_template(flow_score: float, score_jump: float) -> str:
    """Burst when a fresh 15+ jump fires on a 70+ score; else the swing template."""
    if score_jump is not None and score_jump >= 15 and (flow_score or 0) >= 70:
        return "burst"
    return "swing"


def select_contract(chain: list, target_delta: float) -> dict:
    """Pick the call whose |delta| is closest to target_delta."""
    best, best_diff = None, 1e9
    for o in chain:
        if o.get("option_type") != "call":
            continue
        d = (o.get("greeks") or {}).get("delta")
        if d is None:
            continue
        diff = abs(abs(d) - target_delta)
        if diff < best_diff:
            best, best_diff = o, diff
    return best


def grade_option_contract(option: dict, template_key: str = "burst") -> dict:
    """
    Grade one option contract (Tradier-shaped dict) against the TTI options
    checklist. Returns grade A-F, the 0-100 score, per-check detail, the
    contract summary, and an IV-based structure recommendation.
    """
    t = OPTION_TEMPLATES.get(template_key, OPTION_TEMPLATES["burst"])
    g = option.get("greeks") or {}
    bid = float(option.get("bid") or 0)
    ask = float(option.get("ask") or 0)
    mid = round((bid + ask) / 2, 2) if (bid or ask) else float(option.get("last") or 0)
    oi = int(option.get("open_interest") or 0)
    vol = int(option.get("volume") or 0)
    delta = abs(float(g.get("delta") or 0))
    iv_raw = g.get("mid_iv")
    iv = round(float(iv_raw) * 100, 1) if iv_raw not in (None, 0) else None
    spread_pct = round((ask - bid) / mid * 100, 1) if mid else 999.0

    pts = 0
    checks = []
    def chk(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    # Liquidity — open interest (heaviest: an illiquid contract you can't exit).
    if   oi >= 1000: pts += 22; chk("Open interest", True,  f"{oi:,} (deep)")
    elif oi >= 500:  pts += 14; chk("Open interest", True,  f"{oi:,} (ok)")
    elif oi >= 100:  pts += 6;  chk("Open interest", False, f"{oi:,} (thin)")
    else:                       chk("Open interest", False, f"{oi:,} (illiquid — hard to exit)")

    # Day volume.
    if   vol >= 10: pts += 8; chk("Day volume", True,  str(vol))
    elif vol >= 1:  pts += 4; chk("Day volume", True,  f"{vol} (light)")
    else:                     chk("Day volume", False, "0 (no trades today)")

    # Bid/ask spread — wide spreads bleed you on entry and exit.
    if   spread_pct <= 5:  pts += 15; chk("Bid/ask spread", True,  f"{spread_pct}% (tight)")
    elif spread_pct <= 10: pts += 9;  chk("Bid/ask spread", True,  f"{spread_pct}%")
    elif spread_pct <= 20: pts += 4;  chk("Bid/ask spread", False, f"{spread_pct}% (wide)")
    else:                             chk("Bid/ask spread", False, f"{spread_pct}% (very wide — bad fills)")

    # Delta fit to the template band.
    if   t["delta_lo"] <= delta <= t["delta_hi"]: pts += 25; chk("Delta", True,  f"{delta:.2f} (in band)")
    elif abs(delta - t["delta_target"]) <= 0.07:  pts += 15; chk("Delta", True,  f"{delta:.2f} (near band)")
    elif abs(delta - t["delta_target"]) <= 0.12:  pts += 7;  chk("Delta", False, f"{delta:.2f} (off band)")
    else:                                                    chk("Delta", False, f"{delta:.2f} (wrong strike)")

    # IV regime -> structure recommendation (debit spread vs naked call).
    rec = None
    if iv is not None:
        if iv > 50:
            rec = f"IV {iv}% is rich — use a call debit spread to limit IV-crush risk"
            pts += 8; chk("IV regime", True, f"{iv}% (spread)")
        else:
            rec = f"IV {iv}% — buy the call outright to capture an IV pop on the breakout"
            pts += 15; chk("IV regime", True, f"{iv}% (naked)")
    else:
        chk("IV regime", False, "no IV data")

    grade = "A" if pts >= 85 else "B" if pts >= 70 else "C" if pts >= 50 else "D" if pts >= 30 else "F"
    return {
        "grade": grade,
        "score": pts,
        "template": template_key,
        "recommendation": rec,
        "contract": {
            "symbol": option.get("symbol"),
            "strike": option.get("strike"),
            "expiration": option.get("expiration_date"),
            "bid": bid, "ask": ask, "mid": mid, "double": round(mid * 2, 2),
            "delta": round(delta, 2), "iv": iv,
            "open_interest": oi, "volume": vol,
        },
        "checks": checks,
    }
