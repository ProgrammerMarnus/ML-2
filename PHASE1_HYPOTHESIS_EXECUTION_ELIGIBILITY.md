# Phase 1 Hypothesis Execution Eligibility Audit

**Date:** 2026-09-14 (rows for the five newer preregistered families added
2026-09-15; H-005 status updated 2026-09-15 late evening after its first
protocol-bound engine trial)  
**Decision:** `DO_NOT_PROMOTE` — H-001, H-002-R1, and H-003-R1 are rejected;
H-005 is `CANDIDATE` but not yet `ROBUST_OOS` (its evaluated window is not
untouched). Original H-002/H-003 may not consume research budget until their
exact external data contracts are supplied; their amended-family evidence does
not transfer. H-006 is blocked on a cross-sectional evaluator;
H-004/H-007/H-008 are ledger-only and not executable.

## Scope

This review compares the preregistration documents, the currently registered
feature modules, the available pipeline inputs, and the Phase 1 configurations.
It is separate from the now-fixed feature-selection defect: a module can be
selected correctly yet still fail to represent the preregistered hypothesis.

## Findings

| Hypothesis | Preregistered contract | Current executable contract | Decision |
|---|---|---|---|
| H-001 Cross-Asset Spillover | Nine ratio/VIX/volume features; adjusted SPY, QQQ, VIX, and risk-free data from 2010–2026 | The nine feature formulas, selected SPY/QQQ leg, two-sided switching cost, walk-forward replay, and robustness path are implemented. A frozen 2021–2026 independent confirmation was run after correcting its full-strategy feature placebo. It failed placebo separation (percentile 0.35, adjusted p 0.667; 20 nulls). | Rejected — do not rerun or promote |
| H-002 Liquidity Reversal | Seven cross-sectional features over Russell 3000 constituents, with intraday trade classification, market cap, and VIX. 126-session inter-fold gaps and a weekly rebalance contract. | **Amended and executed (H-002-R1 family):** 13-feature cross-sectional panel over a 285-name US small/mid-cap universe; five-term equal-weighted cross-sectional z-score composite (daily LIM proxies, 5d/20d rolling moments, volume ratio, Amihud illiquidity); dollar-neutral top/bottom-decile long/short portfolio; 2010–2023 contiguous weekly rebalance walk-forward with 7 folds and 52-session gaps; full documented deviations (no PIT membership, no market cap, no intraday classification, no VIX, proxies substitute for LIM, weekly rebalance instead of weekly rebalancing path with intraday fills). See `HYPOTHESIS_H002_R1_LIQUIDITY_REVERSAL_AMENDED.md`. | **REJECTED** — H-002-R1 executed under a formally revised family; valid evidence, no edge, trial budget spent |
| H-003 Volatility Risk Premium | Seven-feature tactical allocation across 17 ETFs, with VIX futures M1–M3 term structure, correlations, and risk-parity construction | Twenty-one mostly single-target realized-volatility features; optional VIX/VXN *spot* inputs only. The engine has no VIX-futures, correlation, or multi-asset risk-parity input path. | Do not execute |
| H-003-R1 Daily Volatility-Shock Allocation | Five sign-aligned daily-data terms across the same 17 ETFs; VIX spot stand-down; Wednesday signed inverse-vol allocation; 0.5 gross cap; portfolio-native placebo, cost, delay, crisis, capacity, and diversification gates | Implemented and protocol-frozen as a separate amended family. Baseline experiment `20260915T103928Z_e309df031a658f12` produced net Sharpe −0.074, 7.42x turnover, $6.76m capacity, and failed 10/14 mandate gates. | Rejected; budget retired |
| H-005 Overnight-Intraday Return Decomposition | Daily OHLCV **including opens** for SPY/QQQ/IWM/EFA/EEM/TLT/GLD plus ^VIX, 2010–2021; 13 overnight/intraday features; 7-fold expanding walk-forward (1260/252/252, purge/embargo 5) | The 13-feature contract is implemented and now produces `vix_regime` from the real-data `^VIX` symbol (the previous `VIX`-only check silently dropped it). Protocols frozen at `artifacts/h005_trial{1,2}/h005_protocol.json`; trial `20260915T160008Z_283db198b22dc6aa` passed all 14 frozen gates. | `CANDIDATE` — confirm on an untouched locked window before any `ROBUST_OOS` claim |
| H-006 Factor Exposure Mean Reversion | 17-ETF cross-sectional weekly mean-reversion portfolio: 5 immutable features, Wednesday rebalance, gross ≤ 1.0, net ±40% | 5 features registered and computable (multi-asset feature path exists); no cross-sectional portfolio/walk-forward evaluator — the scalar engine ranks nothing | Do not execute until the panel evaluator exists |
| H-004 Macro Yield Curve & Credit Spread Momentum | Macro yield-curve and credit-spread momentum data (per frozen ledger entry) | Ledger-only: no hypothesis document, feature module, config, or engine path | Not executable |
| H-007 Cross-Sectional Quality-Minus-Junk Low-Turnover Core | Cross-sectional quality/fundamentals factor with low-turnover core allocation | Ledger-only; needs fundamentals data plus the panel evaluator | Not executable |
| H-008 Microstructure Order Flow Imbalance | Intraday order-flow imbalance and liquidity-replenishment microstructure data | Ledger-only; no intraday data or engine path | Not executable |

## Consequences

- The early proxy H-001/H-002 results remain invalid because they used the
  wrong feature panel. H-001's later corrected confirmation is valid rejecting
  evidence.
- The corrected feature-selection path must not be used to relabel an
  implementation mismatch as valid evidence.
- H-001's originally reported 2010–2020 candidate result is superseded: its
  prior placebo held the ratio-selected leg fixed. The corrected independent
  confirmation is the valid decision evidence and rejects H-001.
- Synthetic data can exercise software only. It cannot satisfy any of the
  market-data preregistrations above or produce promotable strategy evidence.
- H-003-R1's valid rejecting evidence is scoped to its daily-data/inverse-vol
  amendment. It does not test original H-003's VIX-futures curve mechanism.

## Required before H-002/H-003 execution or a new research family

1. Choose, for each blocked hypothesis, whether to implement its existing
   preregistration or replace it with a materially revised hypothesis. H-001 is
   closed as rejected and must not be rerun against its observed test window.
2. Freeze a new `ResearchProtocol` that names the exact registered columns,
   universe, target/portfolio construction, dataset versions, walk-forward
   specification, and trial budget. A revision must be assigned a new research
   family; it cannot inherit the invalid trials as evidence.
3. Add the missing point-in-time data contracts and executable evaluation path
   (where applicable), including constituent history for H-002 and VIX-futures
   term structure plus multi-asset allocation for H-003.
4. Obtain the required reviewer approval before unlocking any real-data test
   window. Then generate a fresh protocol-first plan; the runtime feature-panel
   guard will reject a configuration/protocol mismatch.

## Verification performed

- Confirmed that the feature source declared in YAML is now loaded,
  fingerprinted, included in automated protocol creation, and checked against
  the runtime model panel.
- Corrected H-001 from an unrelated ten-column return-lag module to its frozen
  nine-column ratio/VIX/volume contract. Automated plans now reject a missing
  SPY, QQQ, or VIX input before a protocol can be frozen.
- Added and tested an H-001-capable selected-asset execution path. Its
  execution lag shifts both the trade decision and its selected leg together;
  a subsequent leg switch cannot be hidden as zero scalar turnover. Corrected
  Trial 1 completed through the full workflow, but its earlier generic placebo
  is superseded. A locked 2021–2026 confirmation with the corrected
  full-strategy placebo failed and rejects H-001; see
  `H001_CORRECTED_TRIAL_1_RESULTS.md`.
- Confirmed the registered modules expose 9 (H-001), 13 (H-002), and 21
  (H-003) columns, respectively.
- Added a regression guard that recomputes the H-001 conditional leg from a
  permuted feature panel. The focused suite is rerun after this update.
