# TTI Alignment Plan — Making the Flow Score Compute What TTI Actually Computes

Derived from the TTI ("The Trading Initiative") source material: the 7-part webinar series,
the 10-day "Capital Flow Mastery" course (Days 1–6), Masterclass #006 (Institutional Flows &
Liquidity), the Options Checklist, and the published Hit List report (`config/hit-list-2026-04-29.pdf`).

The current engine is a competent *reverse-engineering* of TTI's published numbers, but it
substitutes **price-performance proxies** for the **capital-flow data** that is the whole point
of the system. TTI's own words: *"Capital flow is the biggest piece by design. Trend and momentum
are downstream. Flow comes first... Capital flow is the wind. The chart is the leaf."*

This plan replaces every proxy with the real rule, pillar by pillar.

---

## 0. Foundational dependencies (do these first — everything else needs them)

### 0.1 Price-history (OHLCV) bars
The pipeline currently runs with `bars = []` everywhere. The following all require daily bars:
key levels / support-resistance (#10), swing structure HH/HL (#12), 20-day-high momentum,
consolidation detection, ADR, Fibonacci targets, VWAP. **Wire a bar source** (TradingView
history, Tradier `/markets/history`, or a cheap EOD feed). Cache to Supabase `daily_bars`.

### 0.2 Full universe for percentile ranking
TTI scores ~3,723 stocks; momentum ROC is a **percentile across that whole universe**. The code
ranks across ~200–400 scanner names, which compresses the distribution. Either score the full
optionable universe in batches, or build the percentile distribution from the full market even
when only a subset is reported.

---

## 1. The funnel — add the two missing rungs

TTI decision tree is **asset class / market cap → sector → industry → stock**. The code jumps
straight to sector → stock. Add:

### 1.1 Market-cap / style tier ranking (funnel step 1)  — *gap #6*
Rank size/style tranches by relative strength and trade only the leaders:
- Large growth `IWF`, large value `IWD`, mid `IWH/IJH`, small `IWM`/Russell 2K, small value `IWN`.
- Method: same RS + 5d/1mo/3mo progression used for sectors. Avoid lagging tranches
  ("how much small-cap value do we own? Not one — it's not working").

### 1.2 Industry layer (funnel step 3)  — *gap #7*
TTI ranks and tags at the **industry** level — the Hit List "sector" column is actually industry
(Semiconductors, Semi Equipment, Managed Health Care, Casinos, Net-lease REIT). Finviz already
returns an `Industry` field (see `data_clients.py` COLUMNS). Within each top sector, rank
industries by RS, then rank stocks within the top industries.

### 1.3 Multi-timeframe rotation  — *gap #26*
Rank sectors/industries by progression across **5d → 1mo → 3mo**, not just `perf_3m`. A group
going lagging→leading on the 5-day is the early signal; it "bleeds into" 1mo then 3mo. This is
the engine behind the Hit List "movers" and the early-rotation edge.

---

## 2. PILLAR 1 — Capital Flow (40 pts): replace proxies with real flow

TTI reads flow from three sources and outputs one CF number per sector and per name. The current
code derives all three from price performance — exactly backwards (flow must lead price).

### 2.1 Level 1 — Asset-class / market regime  *(currently: flat 7/10 SPY-above-200MA)*
Replace the constant with a **risk-on/off composite** built from:
- **Intermarket ratios** (free, from ETF prices): `SPY/TLT`, `GLD/TIPS`, `DXY/EEM`,
  `XLY/XLP`, `SMH/XLU`, `HYG/IEI`. Each above/below its own 50-day MA and rising/falling → score.
- **COT report** (CFTC, free, weekly): asset-manager (institutional) vs leveraged-fund
  (speculator) net positioning on S&P / NASDAQ / Russell / treasuries / VIX. Trade the
  institutional side. Parse the Financial Futures report; an LLM summary step is acceptable.
- **DIX** (SqueezeMetrics dark-pool, low weight — Hamilton is "not so keen" but "has a place").
- **Liquidity regime** (macro context): rising liquidity → reward cyclicals/growth; falling →
  reward defensives. Use this to *weight which sectors' flow counts as bullish*.

### 2.2 Level 2 — Sector flow  *(currently: `perf_week * 200` mislabeled as "$M inflows")*
Replace with **real ETF creation/redemption dollar flow**: `Δ(shares_outstanding) × NAV`.
Shares-outstanding is published by issuers / available via market-data APIs — **free, highest-
impact fix.** "$500M into XLE = ~$500M of buys in energy names that week — settlement mechanics,
not a forecast."

### 2.3 Level 3 — Stock-level flow  *(currently: price outperformance vs SPY/sector)*
This is the one piece that needs a **paid per-ticker feed**. Sources, in order:
- **Options flow** — unusual call/put sweeps; "elephant prints" = absolute volume far above the
  contract's normal (500 vs a usual 5–15). The Tradier client already exists; upgrade
  `get_unusual_options` to flag absolute spikes and **feed the score** (today it's sidebar only).
- **Dark-pool / block prints** per ticker (Unusual Whales–type API).
- **Institutional ownership change** — Finviz already returns `Inst Trans` (a free, lagged proxy).
Until a per-ticker flow feed is wired, L3 stays a proxy — document it as such and cap CF (the
code already caps at 32 without real flow data, which is honest).

### 2.4 Smoothing & exit use  — *gap #24*
Flow is **noisy at one-week resolution** — smooth over 2–3 weeks; the real signal is flow
weakening **2–3 weeks in a row**. CF's best use is the **early exit**: sector flow turns before
price, so weakening flow under a still-rising chart = trim.

---

## 3. PILLAR 2 — Trend (30 pts): add MA slope and price structure

Current code scores only **price vs MA** (20/50/200). TTI's classifier (Day 2) is:
1. **Is the 200-day MA rising or falling?**  ← code ignores slope entirely
2. **Is price above or below it?**
- Price above a **rising** 200 = uptrend (full credit).
- Price above a **falling** 200 = NOT a clean uptrend (reduced/zero).
- Price chopping the 200 / flat MA = **sideways → stand aside** (real neutral state, not partial).

Add:
- **200MA slope** (today vs N days ago) as a gating condition on trend points.
- **Swing structure** HH/HL = uptrend, LH/LL = downtrend (needs bars) — *gap #12*.
- Keep golden-cross as a minor confirm, not the slope substitute.

---

## 4. PILLAR 3 — Momentum (30 pts): rebuild around TTI's three reads

TTI momentum (Day 4) is **price-structure events**, not return-rate math. Current code scores
ROC-percentile + RS + Acceleration; rebuild to:
1. **New 20-day highs** — the primary signal (needs bars).
2. **Break from consolidation** — range compression resolving up on volume; longer base → bigger
   move (needs bars + range/volatility contraction).
3. **Volume expansion** — move on ≥ 2× average volume confirms real money.

Plus:
- **RSI as a regime filter, not mean-reversion**: bullish regime = RSI rangebound 40–100
  (pullbacks hold 40); bearish = 0–60. Only trust reads 1–3 in a bullish RSI regime.
- Keep percentile-ROC as a secondary input (report confirms momentum is percentile-capped at 28).
- **Exhaustion filter** — *gap #21*: skip/penalize names extended > 20% above the prior week
  (report's IV rule; "already up 60% in 4 weeks = a completed move, not a fresh one").

---

## 5. Relative Strength — fix the definition and add persistence

- TTI RS = **ratio** (stock ÷ benchmark) tracked over time, vs **both** sector ETF and SPX. Code
  uses a single-window return **difference**. Add the ratio's **slope** (rising RS / the RRG
  RS-momentum axis) — *gap #17*.
- **Persistence**: "leaders keep leading" — add a consecutive-weeks-leading bonus using the
  existing `weekly_scores` history — *gap #18*.
- **RS placement** — *gap #22*: Day 3 frames RS as "where institutions concentrate" (a flow
  concept). Canonically place RS in **Capital Flow**, leaving Momentum to measure *speed*. This
  also de-correlates the pillars (today `perf_quarter` drives CF-L3, Momentum-ROC, and
  Momentum-RS simultaneously, inflating the composite).

---

## 6. The Flow Score composite & delivery

- The exact integer rubric is **proprietary / unpublished** — reconstruct from §2–5 and tune
  against the 42 benchmark rows in `validate_scores.py` (extend with more Hit List reports).
- **Score velocity ≥ score level** for fresh setups — already implemented correctly via
  `prev_score`/`score_jump`. Keep it.
- Read the score **relative to the field**, not absolute (a 92 in a weak regime ≠ a 92 in a hot one).
- Deliverables to mirror: **Saturday Flow Map** (asset→sector→industry→leaders ranked) and the
  **Wednesday Hit List** (biggest weekly score movers → Burst Trades).
- **Surface, don't score**: earnings-proximity flag (`earnings_release_date` already fetched),
  portfolio overlap, liquidity-for-size — *gap #23*.

---

## 7. Options layer — model TWO trade templates (the original question)

The code conflates two distinct TTI trade types. Model them separately:

### 7.1 Swing / Flow Trade (the Options Checklist)
| Rule | Threshold |
|------|-----------|
| Contract liquidity | day volume **≥ 10**, **OI ≥ 1,000** |
| IV branch | **> 50 IV → debit spread** (limit IV crush); **< 50 IV → naked call/put** (capture IV spike) |
| Expiration | **45 DTE min, 60–90 sweet spot**; close by **20 DTE** (theta) |
| Strike | nearest the **price target (1.618 Fib extension)**; **~0.25 delta** baseline |
| Risk:Reward | **≥ 3:1** (target 4:1) — breakeven at a 25% win rate |

### 7.2 Burst Trade (Hit List report + Day 9)
- Trigger: weekly **score jump ≥ 15**, current score ≥ 70, **ADV ≥ $5M**.
- **30–45 DTE**, **0.40–0.50 delta** (0.60–0.70 on IV > 60% for more intrinsic).
- **Sell half at the double (2x)**, trim at 3x, close at 5x, **never roll, no stops**.

### 7.3 Implementation
- Use the Tradier chain to **select the actual contract** (strike at target/delta), read the
  **mid**, compute 2x/3x/5x and the R:R — replacing today's static strings ("120 DTE .25 delta",
  which matches neither template).
- Wire **IV** (and IV-rank) and **GEX** (volatility regime) into selection — `iv_pct` is currently
  dead code (`pipeline.py` never passes it).
- Add the **per-contract liquidity gate** (vol/OI) — today only stock ADV is checked.

---

## 8. Entry & exit mechanics (the "TTI setup")

**Entry** (key-level breakout, pullback): mark the resistance level → measure breakout volume →
**buy the pullback if RVOL > 1**, else hold. Needs key-level detection (S/R, pivots, VRVP).

**Exit ladder**: sell half at +100% (2x) OR move stop to entry after a **1.5× ADR** move → 25%
at the **1.618 Fib extension** → final 25% on market-structure breakdown / trend reversal / inside
the expiration window. (Burst variant: 2x / 3x / 5x, no stops.)

**Volume philosophy** — *gap #14*: treat RVOL as an **input, not a hard filter** (the scanner's
`rel_vol > 1` exclusion drops valid low-volume breakouts — "strong trends happen on declining
volume"). Add VWAP and VRVP liquidity zones for key levels.

---

## 9. Data sources & cost summary

| Layer | Source | Cost |
|-------|--------|------|
| OHLCV bars | TradingView / Tradier history / EOD feed | free–cheap |
| CF L1 intermarket ratios | ETF prices (already available) | free |
| CF L1 COT | CFTC Financial Futures report | free |
| CF L1 DIX / GEX | SqueezeMetrics | free–cheap |
| CF L2 sector flow | ETF shares-outstanding × NAV | free |
| CF L3 per-stock flow | options-flow / dark-pool API (Unusual Whales etc.) | **paid** |
| Inst ownership (L3 proxy) | Finviz `Inst Trans` | already have |
| Options chain / IV / greeks | Tradier (already wired) | already have |

**Only CF Level 3 (per-stock hidden flow) truly needs paid data.** Everything else — including a
real dark-pool *regime* signal and real sector flow — is free.

---

## 10. Validation

The current calibration is **circular** (tuned to reproduce TTI's published numbers). After the
rewrite:
1. Keep `validate_scores.py` MAE against Hit List reports (add more reports for more rows).
2. Add a **forward-return backtest**: do high Flow Scores / burst triggers actually precede
   profitable option outcomes? This is the test the system has never had.

---

## Prioritized roadmap

1. **Foundations** — wire OHLCV bars (§0.1) + full-universe percentile (§0.2). Unblocks everything.
2. **CF L2 real ETF flow** (§2.2) — free, highest single-pillar impact, kills the worst proxy.
3. **CF L1 intermarket + COT composite** (§2.1) — free, makes regime real.
4. **Trend slope + structure** (§3) and **Momentum rebuild** (§4) — needs bars from step 1.
5. **RS ratio/slope/persistence + placement** (§5).
6. **Options two-template engine + contract selection + R:R** (§7) — answers the original question.
7. **Industry & market-cap funnel rungs** (§1).
8. **CF L3 paid flow feed** (§2.3) — last, only piece needing spend.
9. **Forward-return backtest** (§10).

> Bottom line: the architecture (3 pillars, weights, tier logic, score velocity) is already right.
> The work is swapping **price-performance proxies for real capital-flow data**, adding the
> **bars-dependent** trend/momentum/level signals, and building a **real options-selection engine**
> with two trade templates. After that, the engine computes what TTI computes — and can finally be
> validated against forward returns instead of against TTI's own numbers.
