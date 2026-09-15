# Phase 1, Step 5: Research Campaign Status

**Updated:** 2026-09-15 (evening)
**Promotion state:** `RESEARCH_ONLY`

## Resolution of the Original Framework Blocker

The original automation defect was confirmed: early executions silently used
generic price/volume templates rather than the declared hypothesis feature
families. The execution path has since been hardened with hypothesis-specific
feature selection, execution-eligibility checks, and stable dataset-family
contract validation. Ineligible proxy runs now fail before consuming a valid
hypothesis trial.

## Current Outcome

- **H-001:** corrected independent confirmation completed and **rejected**.
  Net Sharpe 0.787318, placebo percentile 0.35, adjusted p-value 0.6667.
- **H-002:** **blocked before trial** because its cross-sectional liquidity data
  contract is unavailable to the scalar runner.
- **H-003:** **blocked before trial** because its multi-asset/VIX data contract
  is unavailable to the scalar runner.
- **H-002-R1:** amended daily-data family executed once and **rejected**; gross
  Sharpe −0.342, 0/10 positive folds, and 72× turnover. Budget retired.
- **H-003-R1:** amended daily-data family executed once and **rejected**; net
  Sharpe −0.074, 7.42× turnover, and 10/14 mandate gates failed. Budget retired.

## New Preregistered Families (2026-09-15)

Five newer families are preregistered in
`data/research_ledgers/preregistrations.jsonl` but none has valid engine
evidence yet:

- **H-005 Overnight-Intraday Decomposition:** 13 features registered and wired
  into the engine feature panel; configs are executable. Trials 1–4 were
  produced by a standalone script outside the protocol (PRELIMINARY only).
- **H-006 Factor Exposure Mean Reversion:** 5 features registered, config
  frozen; blocked on a cross-sectional (17-ETF panel, weekly rank/rebalance)
  evaluator.
- **H-004 / H-007 / H-008:** ledger-only preregistrations (macro yield curve,
  quality-minus-junk, microstructure order flow); no module, config, or engine
  path exists yet.

The identical early -0.41 results remain invalid framework diagnostics and
must not be cited as evidence against the three economic hypotheses.

## Decision Boundary

Do not bypass the blocker with generic proxies. Supply each exact preregistered
contract, close the blocked hypothesis, or create a new preregistered family.
No current result supports promotion to `ROBUST_OOS`, paper trading, or live
trading.

See [PHASE1_PROGRESS.md](PHASE1_PROGRESS.md) for the phase ledger and
[CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) for canonical status.
