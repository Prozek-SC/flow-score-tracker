# TTI Flow Score — Empirical Reverse-Engineering Findings

Derived by parsing the weekly TTI reports in this repo and fitting the published component
scores against the published inputs. Companion to `TTI_ALIGNMENT_PLAN.md` (which is the rebuild
plan); this doc records what the data actually shows.

## Data parsed
- **17 Flow Maps** (`Flow Reports/`, weeks 2026-02-28 → 2026-06-18) — sector-level CF/Trend/Mom
  + weekly/monthly/Flow-AUM flows + COT + asset-class flows.
- **12 Execution Reports** (`Execution Reports/`) — stock-level burst tables + per-stock
  CF/Trend/Mom (featured setups) + options contract details.
- **1 Hit List** (`config/hit-list-2026-04-29.pdf`) — 42 stocks × CF/Trend/Mom across 4 tiers.

Sector dataset extracted: **110 sector-rows / 10 weeks** (99 with full weekly+monthly+AUM columns).

## Finding 1 — The composite is a pure sum
`Flow Score = Capital Flow + Trend + Momentum`, exact, **110/110 rows**. No hidden weighting or
nonlinearity. The problem reduces to three independent sub-functions (CF/40, Trend/30, Mom/30).
Confirmed at the stock level too (Execution Report featured setups, e.g. ONDS 29+26+28=83).

## Finding 2 — Capital Flow is normalized-flow-driven, NOT raw dollars
- Correlation(raw weekly $flow, CF) = **+0.55** (weak).
- In **6 of 10 weeks** the biggest-inflow sector is NOT the highest-CF sector.
- Smoking gun (2026-02-28): XLF most dollars ($149M) → lowest CF (12); XLE fewer ($62M) →
  highest CF (36). 2026-06-13: XLE $314M inflow → CF just 9.
- **Flow/AUM (flow normalized by fund size) is the real driver**, not raw $.
- CF ceiling observed = **36** (not the 32 the current code caps at).

## Finding 3 — CF variance is 81% sector-specific, 19% regime
Variance decomposition of CF (99 rows):
- **Within-week (sector-flow / Level 2): 81%**
- Between-week (regime / Level 1): 19%

CF is overwhelmingly about *which sector* is getting flow, not the broad market regime.

## Finding 4 — The sector-flow leg of CF is largely recoverable
Fitting within-week (sector-demeaned) CF against weekly/monthly/Flow-AUM:
- **R² = 0.724, MAE = 1.67 CF points** (near the parse/rounding noise floor).
- Flow/AUM is the strongest single feature (corr +0.66).
- Decision tree (depth 3) recovers the threshold structure:
  - deep outflow (weekly < −$700M) → CF ≈ 12
  - flat/small flow → CF ≈ 20
  - strong inflow + monthly > $523M + Flow/AUM > 1.65% → CF ≈ 28

## Finding 5 — The regime leg is minor and not explained by COT levels
Weekly-mean CF vs S&P COT positioning: corr **−0.31** (asset mgrs), **−0.41** (lev funds).
COT levels barely move week to week (~1.0M net long throughout), so they can't drive the (small,
19%) baseline. Likely tracks broad-equity flow direction (SPY/QQQ weekly); too small a target to
fit from 9 weeks. **Low priority.**

## Implications for the rebuild (`TTI_ALIGNMENT_PLAN.md`)
- **CF Level 2 = Flow/AUM-normalized sector flow** — confirmed dominant; replace `perf_week×200`.
  The reports prove raw $ is insufficient; normalization by fund AUM is the signal.
- **CF Level 1 = small regime baseline** (~20% weight); don't over-invest in it.
- Composite stays a simple sum; keep the additive design.
- Raise/remove the CF=32 cap (real CF reaches 36).

## Finding 6 — Sector Trend is ~85% recoverable from MA distance
Fit Trend against price-vs-MA features (99 rows, ETF history via yfinance):
- **Tree depth 3: R² = 0.849, MAE = 1.96** (linear R² = 0.785).
- Primary driver: **distance above the 200MA** (split at +3.77%), then 50MA distance, then
  golden cross / 20MA. Confirms the current code's MA-distance Trend approach is essentially right.
- **MA slope effect is real but rare in this sample**: only 2 rows had price above a *falling*
  200MA; they averaged Trend 12.5 vs 22.3 for above-a-*rising*-200. Slope matters (per Day 2) but
  the Feb–Jun 2026 bull market gave few falling-MA cases to weight it.

## Finding 7 — Sector Momentum is ~87% recoverable, driven by 1-month return
Fit Momentum against return / new-high / RSI features:
- **Tree depth 3: R² = 0.868, MAE = 1.28** (linear R² = 0.828).
- Dominant feature: **1-month return (perf21), corr +0.89** — more than the quarter (perf63 +0.68).
  Strong secondaries: RSI (+0.76), relative strength vs SPY 63d (+0.74), distance from 20d high (−0.44).
- Refinement vs current code: the engine's Momentum leans on `perf_quarter`; the data says
  **1-month return is the stronger driver** for sectors.

## Sector Flow Score scorecard (how recoverable the formula is)
| Pillar | Best fit R² | MAE | Dominant driver |
|--------|-------------|-----|-----------------|
| Capital Flow (sector-flow leg, 81% of CF) | 0.72 | ±1.7 | Flow/AUM |
| Trend | 0.85 | ±2.0 | distance above 200MA |
| Momentum | 0.87 | ±1.3 | 1-month return (+RSI, +RS) |
| Composite | = exact sum | — | — |

The **sector-level Flow Score is substantially reverse-engineered** — each pillar recovered to
1.3–2.0 points from observable inputs, near the PDF-parse/rounding noise floor.

## Still open
- **Stock-level** Trend & Momentum should fit similarly (need per-stock price history).
- **Stock-level** CF/Trend/Mom fits — Hit List + Execution Reports give outputs; stock CF
  *inputs* (per-stock hidden flow) are not published → stock CF is the hard residual.
- Fold in the 7 older-format weeks (~180 rows total) to tighten the sector fits.
