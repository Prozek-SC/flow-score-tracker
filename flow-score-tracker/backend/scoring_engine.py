"""
Flow Score Scoring Engine
Three Pillars: Capital Flow (40pts) | Trend (30pts) | Momentum (30pts)
Total: 0-100
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
    sector_etf_perf_ytd: YTD performance of sector ETF (%)
    sector_etf_flow_weekly: weekly ETF flow ($M)
    sector_rank: rank among 11 sectors (1=best)
    """
    score = 0
    details = []

    # Rank-based scoring
    if sector_rank <= 2:
        score += 8
        details.append(f"Sector rank #{sector_rank}/11 (elite)")
    elif sector_rank <= 4:
        score += 6
        details.append(f"Sector rank #{sector_rank}/11 (strong)")
    elif sector_rank <= 6:
        score += 3
        details.append(f"Sector rank #{sector_rank}/11 (neutral)")
    else:
        details.append(f"Sector rank #{sector_rank}/11 (weak)")

    # YTD performance
    if sector_etf_perf_ytd > 10:
        score += 4
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    elif sector_etf_perf_ytd > 5:
        score += 3
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    elif sector_etf_perf_ytd > 0:
        score += 1
        details.append(f"ETF +{sector_etf_perf_ytd:.1f}% YTD")
    else:
        details.append(f"ETF {sector_etf_perf_ytd:.1f}% YTD")

    # Flow direction
    if sector_etf_flow_weekly > 500:
        score += 3
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows")
    elif sector_etf_flow_weekly > 0:
        score += 1
        details.append(f"+${sector_etf_flow_weekly:.0f}M inflows")
    else:
        details.append(f"${sector_etf_flow_weekly:.0f}M outflows")

    return {
        "score": min(15, score),
        "detail": " · ".join(details),
        "raw": {"ytd": sector_etf_perf_ytd, "flow": sector_etf_flow_weekly, "rank": sector_rank}
    }


def score_capital_flow_level3(bars: list, finviz_data: dict, uw_flow: dict) -> dict:
    """
    Level 3: Is THIS stock receiving direct institutional flow?
    Combines: volume accumulation, institutional ownership change, options flow
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

    # Volume accumulation on up days
    if bars and len(bars) >= 20:
        up_vols, down_vols = [], []
        for i in range(1, min(21, len(bars))):
            try:
                close = float(bars[i].get("Close", 0))
                prev = float(bars[i-1].get("Close", 0))
                vol = float(bars[i].get("TotalVolume", 0))
                if close > prev:
                    up_vols.append(vol)
                elif close < prev:
                    down_vols.append(vol)
            except:
                continue

        if up_vols and down_vols:
            ratio = np.mean(up_vols) / np.mean(down_vols)
            if ratio >= 1.5:
                score += 5
                details.append(f"Vol ratio {ratio:.1f}x (accumulation)")
            elif ratio >= 1.2:
                score += 3
                details.append(f"Vol ratio {ratio:.1f}x (slight accum)")
            elif ratio < 0.8:
                details.append(f"Vol ratio {ratio:.1f}x (distribution)")

    # Options flow (Unusual Whales)
    pc_ratio = uw_flow.get("put_call_ratio", 1.0)
    sweeps = uw_flow.get("sweep_count", 0)
    if pc_ratio < 0.5 and sweeps >= 5:
        score += 4
        details.append(f"Bullish flow + {sweeps} sweeps")
    elif pc_ratio < 0.7:
        score += 2
        details.append(f"Call-heavy flow P/C {pc_ratio}")

    return {
        "score": min(15, score),
        "detail": " · ".join(details) or "No accumulation signal",
        "raw": {"inst_trans": inst_trans, "pc_ratio": pc_ratio, "sweeps": sweeps}
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
    Each MA worth 10 points. Score also considers distance and slope.
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

    # Higher highs / higher lows check
    if bars and len(bars) >= 40:
        try:
            first_half = bars[-40:-20]
            second_half = bars[-20:]
            h1_high = max(float(b.get("High", 0)) for b in first_half)
            h2_high = max(float(b.get("High", 0)) for b in second_half)
            h1_low = min(float(b.get("Low", 0)) for b in first_half)
            h2_low = min(float(b.get("Low", 0)) for b in second_half)
            if h2_high > h1_high and h2_low > h1_low:
                score = min(30, score + 2)
                details.append("HH/HL confirmed")
        except:
            pass

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
# 5 components, each worth up to 6pts → max 30
#
# Rate of Change    (0-6)  — 63-day price momentum magnitude
# Relative Strength (0-6)  — outperformance vs SPY + sector
# Acceleration      (0-6)  — short-term momentum > prior period
# MACD              (0-6)  — trend direction + histogram expansion
# ADX               (0-6)  — trend strength (does it have legs?)
# ============================================================

def _ema(data: list, period: int) -> np.ndarray:
    """Exponential moving average"""
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return np.array(result)


def score_momentum_pillar(bars: list, finviz_data: dict,
                           spy_perf_63d: float, sector_perf_63d: float) -> dict:
    """
    Momentum: ROC + RS + Acceleration + MACD + ADX
    Each component scored 0-6. Total max = 30.
    """
    scores = {}
    details = []

    closes = highs = lows = np.array([])
    if bars and len(bars) >= 30:
        try:
            closes = np.array([float(b.get("Close", 0)) for b in bars])
            highs  = np.array([float(b.get("High",  0)) for b in bars])
            lows   = np.array([float(b.get("Low",   0)) for b in bars])
        except:
            pass

    # -------------------------------------------------------
    # 1. RATE OF CHANGE (0-6)
    # -------------------------------------------------------
    roc_score = 0
    if len(closes) >= 63:
        try:
            roc_63 = (closes[-1] - closes[-63]) / closes[-63] * 100
            roc_21 = (closes[-1] - closes[-21]) / closes[-21] * 100
            if roc_63 > 30:   roc_score = 6
            elif roc_63 > 20: roc_score = 5
            elif roc_63 > 10: roc_score = 4
            elif roc_63 > 5:  roc_score = 3
            elif roc_63 > 0:  roc_score = 1
            details.append(f"ROC 63d:{roc_63:.1f}% 21d:{roc_21:.1f}%")
        except:
            details.append("ROC: calc error")
    else:
        details.append("ROC: insufficient data")
    scores["roc"] = roc_score

    # -------------------------------------------------------
    # 2. RELATIVE STRENGTH vs SPY + Sector (0-6)
    # -------------------------------------------------------
    rs_score = 0
    perf_63d = finviz_data.get("perf_quarter", 0)
    if perf_63d and spy_perf_63d is not None:
        try:
            outperf_spy    = perf_63d - spy_perf_63d
            outperf_sector = perf_63d - (sector_perf_63d or 0)
            if outperf_spy > 10 and outperf_sector > 5:
                rs_score = 6
                details.append(f"RS: +{outperf_spy:.1f}% SPY +{outperf_sector:.1f}% sector (elite)")
            elif outperf_spy > 5:
                rs_score = 4
                details.append(f"RS: +{outperf_spy:.1f}% vs SPY (strong)")
            elif outperf_spy > 0:
                rs_score = 2
                details.append(f"RS: +{outperf_spy:.1f}% vs SPY (positive)")
            elif outperf_spy > -5:
                rs_score = 1
                details.append(f"RS: {outperf_spy:.1f}% vs SPY (lagging)")
            else:
                details.append(f"RS: {outperf_spy:.1f}% vs SPY (weak)")
        except:
            details.append("RS: calc error")
    else:
        details.append("RS: no data")
    scores["rs"] = rs_score

    # -------------------------------------------------------
    # 3. ACCELERATION — short-term vs prior period (0-6)
    # -------------------------------------------------------
    accel_score = 0
    if len(closes) >= 63:
        try:
            mom_recent = (closes[-1]  - closes[-21]) / closes[-21] * 100
            mom_prior  = (closes[-42] - closes[-63]) / closes[-63] * 100
            accel = mom_recent - mom_prior
            if accel > 10:   accel_score = 6
            elif accel > 5:  accel_score = 4
            elif accel > 0:  accel_score = 2
            elif accel > -5: accel_score = 1
            details.append(f"Accel: {'+' if accel >= 0 else ''}{accel:.1f}pts")
        except:
            details.append("Accel: calc error")
    else:
        details.append("Accel: insufficient data")
    scores["accel"] = accel_score

    # -------------------------------------------------------
    # 4. MACD (12, 26, 9) — trend direction + histogram (0-6)
    # -------------------------------------------------------
    macd_score = 0
    if len(closes) >= 35:
        try:
            ema12 = _ema(closes.tolist(), 12)
            ema26 = _ema(closes.tolist(), 26)
            macd_line   = ema12 - ema26
            signal_line = _ema(macd_line.tolist(), 9)
            histogram   = macd_line - signal_line

            macd_val  = float(macd_line[-1])
            hist_val  = float(histogram[-1])
            hist_prev = float(histogram[-2]) if len(histogram) > 1 else 0
            hist_expanding = hist_val > hist_prev

            if macd_val > 0 and hist_val > 0 and hist_expanding:
                macd_score = 6   # bullish + expanding histogram
                details.append(f"MACD: bullish+expanding (hist {hist_val:.3f})")
            elif macd_val > 0 and hist_val > 0:
                macd_score = 4   # bullish but slowing
                details.append(f"MACD: bullish (hist {hist_val:.3f})")
            elif macd_val > 0:
                macd_score = 2   # above signal but histogram negative
                details.append(f"MACD: above zero, fading")
            elif hist_val > hist_prev:
                macd_score = 1   # below zero but improving
                details.append(f"MACD: bearish, improving")
            else:
                details.append(f"MACD: bearish (hist {hist_val:.3f})")
        except Exception as e:
            details.append(f"MACD: calc error")
    else:
        details.append("MACD: insufficient data")
    scores["macd"] = macd_score

    # -------------------------------------------------------
    # 5. ADX (14) — trend strength (0-6)
    # -------------------------------------------------------
    adx_score = 0
    if len(closes) >= 20 and len(highs) >= 20 and len(lows) >= 20:
        try:
            period = 14
            tr_list, plus_dm_list, minus_dm_list = [], [], []
            for i in range(1, len(closes)):
                tr = max(highs[i] - lows[i],
                         abs(highs[i] - closes[i-1]),
                         abs(lows[i]  - closes[i-1]))
                tr_list.append(tr)
                h_diff = highs[i] - highs[i-1]
                l_diff = lows[i-1] - lows[i]
                plus_dm_list.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
                minus_dm_list.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)

            atr       = _ema(tr_list, period)
            plus_di   = 100 * _ema(plus_dm_list, period)  / (atr + 1e-9)
            minus_di  = 100 * _ema(minus_dm_list, period) / (atr + 1e-9)
            dx        = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
            adx       = _ema(dx.tolist(), period)

            adx_val      = float(adx[-1])
            plus_di_val  = float(plus_di[-1])
            minus_di_val = float(minus_di[-1])
            bullish_di   = plus_di_val > minus_di_val

            if adx_val >= 30 and bullish_di:
                adx_score = 6
                details.append(f"ADX: {adx_val:.1f} strong+bullish")
            elif adx_val >= 25 and bullish_di:
                adx_score = 4
                details.append(f"ADX: {adx_val:.1f} trending+bullish")
            elif adx_val >= 20:
                adx_score = 2
                details.append(f"ADX: {adx_val:.1f} developing")
            elif adx_val >= 15:
                adx_score = 1
                details.append(f"ADX: {adx_val:.1f} weak trend")
            else:
                details.append(f"ADX: {adx_val:.1f} no trend")
        except Exception as e:
            details.append("ADX: calc error")
    else:
        details.append("ADX: insufficient data")
    scores["adx"] = adx_score

    total = sum(scores.values())

    return {
        "score": min(30, total),
        "detail": " · ".join(details),
        "raw": {
            "roc_score":   scores["roc"],
            "rs_score":    scores["rs"],
            "accel_score": scores["accel"],
            "macd_score":  scores["macd"],
            "adx_score":   scores["adx"],
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
    """Calculate Flow Score for an entire sector ETF"""
    ytd_perf = etf_data.get("perf_ytd", 0)
    weekly_flow = etf_data.get("weekly_flow", 0)
    price = etf_data.get("price", 0)
    ma50 = etf_data.get("sma50", 0)
    ma200 = etf_data.get("sma200", 0)
    ma20 = etf_data.get("sma20", price)  # fallback

    # Simplified sector scoring
    capital_score = min(40, max(0,
        (10 if equity_flow > 0 else 0) +
        (15 if ytd_perf > 10 else 10 if ytd_perf > 5 else 5 if ytd_perf > 0 else 0) +
        (15 if weekly_flow > 500 else 10 if weekly_flow > 0 else 0)
    ))

    trend_score = min(30,
        (10 if price > ma20 else 0) +
        (10 if price > ma50 else 0) +
        (10 if price > ma200 else 0)
    )

    momentum_score = min(30, max(0,
        (15 if ytd_perf > 15 else 10 if ytd_perf > 8 else 5 if ytd_perf > 0 else 0) +
        (15 if weekly_flow > 1000 else 10 if weekly_flow > 0 else 0)
    ))

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
