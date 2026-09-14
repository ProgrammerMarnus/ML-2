# Phase 1 Hypothesis Execution Eligibility Audit

**Date:** 2026-09-14  
**Decision:** `DO_NOT_EXECUTE` — H-001 is rejected after independent
confirmation, and H-002/H-003 may not consume research budget until their
discrepancies are resolved in new immutable protocols.

## Scope

This review compares the preregistration documents, the currently registered
feature modules, the available pipeline inputs, and the Phase 1 configurations.
It is separate from the now-fixed feature-selection defect: a module can be
selected correctly yet still fail to represent the preregistered hypothesis.

## Findings

| Hypothesis | Preregistered contract | Current executable contract | Decision |
|---|---|---|---|
| H-001 Cross-Asset Spillover | Nine ratio/VIX/volume features; adjusted SPY, QQQ, VIX, and risk-free data from 2010–2026 | The nine feature formulas, selected SPY/QQQ leg, two-sided switching cost, walk-forward replay, and robustness path are implemented. A frozen 2021–2026 independent confirmation was run after correcting its full-strategy feature placebo. It failed placebo separation (percentile 0.35, adjusted p 0.667; 20 nulls). | Rejected — do not rerun or promote |
| H-002 Liquidity Reversal | Seven cross-sectional features over Russell 3000 constituents, with intraday trade classification, market cap, and VIX | Thirteen single-asset OHLCV proxies. The available trial YAML targets SPY and has neither constituent history, market cap, intraday trade data, nor VIX. | Do not execute |
| H-003 Volatility Risk Premium | Seven-feature tactical allocation across 17 ETFs, with VIX futures M1–M3 term structure, correlations, and risk-parity construction | Twenty-one mostly single-target realized-volatility features; optional VIX/VXN *spot* inputs only. The engine has no VIX-futures, correlation, or multi-asset risk-parity input path. | Do not execute |

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
