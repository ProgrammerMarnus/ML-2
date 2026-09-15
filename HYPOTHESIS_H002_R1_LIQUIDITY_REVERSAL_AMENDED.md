# H-002-R1: Liquidity Reversal (Amended Family) — Preregistration Amendment and Result

**Family ID:** H-002-R1
**Supersedes (for execution only):** H-002 Liquidity Reversal (original preregistration)
**Status:** **REJECTED** — validly executed, no edge, trial budget retired
**Protocol:** `artifacts/h002_r1/h002_r1_protocol.json` (digest `1ad57615a9619f0f`)
**Config:** `configs/h002_real_universe.yaml` (fingerprint `44d1757bdd9f7a70`)
**Artifacts:** `artifacts/h002_r1/run/`

---

## 1. Why this amendment exists

The original H-002 preregistration could not be executed. Its data contract
requires inputs that are not obtainable in this repository without a licensed
commercial data agreement:

| Original requirement | Availability | Consequence |
|---|---|---|
| Point-in-time monthly Russell 3000 membership | Not available | Universe cannot be reconstructed as preregistered |
| Daily market capitalisation per name | Not available | Size-decile composite term and cap-weighting impossible |
| Intraday buys/sells classified at the midpoint (Lee-Ready or equivalent) | Not available | The LIM itself cannot be computed |
| VIX level series | Not reliably retrievable | Vol-regime composite term impossible |
| 126-session inter-fold gaps | Not supported by the engine | See §4, deliberate B09 guard |

Under the Phase 1 decision recorded in `PHASE1_DATA_CONTRACT_GAP_MATRIX.md`, an
open hypothesis must either be given its exact contract or be **formally revised
into a genuinely new research family**. H-002 was revised. The revised family is
**H-002-R1**, and it is a *different, narrower* hypothesis whose contract is
restricted to data the repository can actually source, freeze, and verify.

**H-002-R1 is not H-002.** Results here are evidence for H-002-R1 only and must
never be presented as evidence for the original H-002 preregistration.

---

## 2. Amended hypothesis

> Cross-sectional liquidity-imbalance reversal: names with unusually high buying
> pressure (proxied by return-signed volume over a 1–5 day window) subsequently
> underperform names with unusually high selling pressure, because transient
> liquidity demand reverses once it is satisfied.

Economic mechanism is unchanged from H-002. What changed is the measurement
contract, and therefore the strength of the claim that can be made.

---

## 3. Amended data contract (frozen)

| Element | Original H-002 | H-002-R1 (amended) |
|---|---|---|
| Universe | PIT monthly Russell 3000 | Static snapshot, `data/universe_russell3000.csv` (285 names) |
| Prices | PIT adjusted daily OHLCV | yfinance daily adjusted OHLCV, 2010-01-01 → 2023-12-31 |
| LIM | Intraday buys/sells classified at midpoint | Return-signed volume imbalance proxy |
| Market cap | Daily per-name | **Omitted** |
| VIX / vol regime | VIX level series | **Omitted** |
| Sectors | PIT GICS | Static map, `src/quant_research/data/h002_sectors.json` |
| Portfolio | Cross-sectional, equal-weight, dollar-neutral, sector-neutral | Same construction, implemented in `portfolio/h002_portfolio.py` |
| Rebalance | 1–5 day signal horizon | 5-session rebalance (`rebalance_bars=5`) |
| Costs | 15 bps fee + 5 bps slippage | 15 bps fee + 5 bps slippage (unchanged) |
| Folds | 2010–2023, 126-session gaps | 2010–2023, **contiguous** non-overlapping 252-session OOS folds |

### Composite signal

The preregistered composite is

```
Signal = w1·z(LIM_1d) + w2·z(LIM_5d) + w3·z(LIM_std_20d) + w4·z(Volume_ratio)
       + w5·z(Amihud_illiq) + w6·z(Size_decile) + w7·z(Vol_regime)
```

with cross-sectional z-scores. H-002-R1 **equal-weights 5 of the 7 terms**; the
`Size_decile` and `Vol_regime` terms are omitted because their inputs (§1) do
not exist here. The five retained terms are implemented in
`h002_pipeline.py::_build_h002_composite_signal`.

---

## 4. Evaluation contract, and the gap deviation

The original H-002 fold schedule specified **126-session gaps** between OOS test
windows. The engine rejects this configuration. The guard is deliberate (B09):
a gapped OOS window would carry open position state across unscored sessions, so
the reported drawdown and turnover would be computed over a path that silently
skips the very returns in which the book was held. Making that valid requires
modelling liquidation at the fold boundary and re-entry after the gap, including
their costs. That is a change to the strategy, not to the plumbing.

H-002-R1 therefore substitutes **contiguous, non-overlapping 252-session test
folds** (`step_bars == test_window == 252`). This is a *weaker* schedule than the
preregistered one — it removes test-window overlap but adds no cooling-off gap —
and the amendment records it as a deviation rather than claiming equivalence.

| Evaluation parameter | H-002-R1 |
|---|---|
| Train window | 504 sessions (expanding) |
| Validation window | 252 sessions |
| Test window | 252 sessions |
| Step | 252 sessions (contiguous) |
| Purge / embargo | 5 / 5 sessions |

### Promotion gates (unchanged thresholds)

| Gate | Threshold |
|---|---|
| median OOS Sharpe | > 0 |
| mean OOS Sharpe | > 0 |
| full OOS path drawdown | ≥ −15% |
| cost stress | Sharpe > 0 at ≥ 30 bps |
| delay stress | Sharpe > 0 at ≥ 1 session delay |
| bootstrap P(SR > 0) | ≥ 0.85 |
| placebo percentile | ≥ 0.90 |
| placebo sample | ≥ 20 valid null runs |
| single-fold share | ≤ 0.60 |
| annual turnover | ≤ 6× |

---

## 5. Result — H-002-R1 is REJECTED

Executed once, under the frozen protocol, with the trial budget retired
immediately afterwards. Promotion state: **`RESEARCH_ONLY`**.

| Metric | Value |
|---|---|
| Median OOS Sharpe (net) | **−3.221** |
| Mean OOS Sharpe (net) | **−3.131** |
| Full OOS net Sharpe | −2.656 |
| **Full OOS gross Sharpe** | **−0.342** |
| Full OOS net return | **−81.07%** |
| Full OOS gross return | −19.70% |
| Full OOS path max drawdown | −81.14% |
| Positive OOS folds | **0 of 10** |
| Annual turnover | 72.09× (cap 6×) |
| Total transaction cost sum | 1.978 (fees 1.483; slippage 0.494) |

The immutable baseline artifact assigned the combined 1.978 sum to its
`fee_cost` field and zero to `slippage_cost`. This was attribution-only: the
net return series charged all 20 bps and every decision metric is unchanged.
The shared portfolio accounting now emits separate fee and slippage series,
and a reconciliation regression covers the correction.

All ten performance gates failed; the four process gates passed:

- **Passed:** `data_integrity`, `lookahead_resolved`,
  `trial_accounting_consistent`, `family_search_within_cap`.
- **Failed:** `median_oos_sharpe_positive`, `mean_oos_sharpe_positive`,
  `worst_dd_within_limit`, `cost_stress_survives`, `delay_stress_survives`,
  `bootstrap_positive_prob`, `placebo_separates`, `placebo_sample_adequate`,
  `not_single_fold`, `turnover_plausible`.

### Interpretation

The decisive number is the **gross** Sharpe of **−0.342**. Costs are severe
(72× annual turnover against a 20 bps round-trip, compounding to a complete loss
of capital), but they are not the reason the hypothesis fails. The directional
signal itself — before any trading cost — has no edge: it is marginally negative,
and **zero of ten out-of-sample folds were profitable**.

A proxy-LIM, static-universe, five-term version of liquidity reversal has no
predictive power on liquid US large/mid-caps over 2010–2023. Two readings are
available and the evidence cannot distinguish them:

1. The economic effect does not exist at this horizon and universe; or
2. The effect is real but is destroyed by the proxy — return-signed volume is a
   poor stand-in for a midpoint-classified order imbalance, and it is precisely
   the classification step that the original H-002 preregistration insisted on.

Reading (2) is the more likely of the two, and it is the reason the original
H-002 data requirement existed. It is also why this run **cannot** be used to
dismiss the original H-002: the amendment removed the measurement the hypothesis
actually rested on.

An additional contract defect is visible in the gate table. The inherited
**6× annual turnover cap is not satisfiable by a 1–5 day signal horizon.** A
5-session rebalance replaces roughly 1.4× of the book per rebalance, ~50 times a
year, which is ~72× annual turnover — exactly what was observed. The original
H-002 preregistration specified both "1–5 day horizon" and "≤ 6× annual
turnover"; those two requirements are mutually contradictory, and the amended
protocol inherited both. The `turnover_plausible` gate therefore fails by
construction, independently of whether the signal works.

This defect does **not** rescue the hypothesis. Meeting the 6× cap would require
holding for roughly two months, at which point the 1–5 day reversal signal has
entirely decayed — the result would be a different strategy, and a worse one.
The rejection rests on the negative gross Sharpe, not on the turnover gate.

---

## 6. Decision

**H-002-R1: REJECTED. Trial budget retired. No further tuning.**

The one-run, no-tuning rule applies: the observed 2010–2023 window is now spent
for this family and must not be reused to search for a variant that works.

The original **H-002 remains unexecuted**, and it remains blocked on PIT
Russell 3000 membership, market-cap, and intraday classified-trade data — exactly
as recorded in `PHASE1_DATA_CONTRACT_GAP_MATRIX.md`. Amending one hypothesis into
a new family does not discharge that requirement; it only removes a permanently
blocked item from the Phase 1 queue by closing it on the evidence available.

If H-002's mechanism is to be tested properly, the path is a licensed data
contract for PIT membership, market cap, and midpoint-classified trades, followed
by a new preregistration. That is a procurement decision, not a research one.
