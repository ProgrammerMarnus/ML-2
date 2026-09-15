# Phase 1, Step 5: Research Campaign Execution — Current Record

**Updated:** 2026-09-15 (evening)
**Status:** H-001/H-002-R1/H-003-R1 rejected; original H-002/H-003 blocked;
H-005/H-006/H-004/H-007/H-008 preregistered without valid engine evidence

## Valid Evidence

| Hypothesis | State | Trials with valid hypothesis contract | Outcome |
|---|---:|---:|---|
| H-001 Cross-Asset Spillover | Rejected | 1 corrected confirmation | Net Sharpe 0.787318; placebo percentile 0.35; adjusted p-value 0.6667; fails preregistered separation gate |
| H-002 Liquidity Reversal | Blocked | 0 | Missing cross-sectional small/mid-cap and liquidity contract |
| H-003 Volatility Risk Premium | Blocked | 0 | Missing multi-asset and VIX/term-structure contract |
| H-002-R1 Liquidity Reversal | Rejected | 1 frozen baseline | Gross Sharpe −0.342; 0/10 positive folds; budget retired |
| H-003-R1 Daily Volatility-Shock Allocation | Rejected | 1 frozen baseline | Net Sharpe −0.074; 10/14 mandate gates failed; budget retired |
| H-005 Overnight-Intraday Decomposition | Preregistered, not engine-executed | 0 | 13 features registered and wired into the engine panel; Trials 1–4 were standalone-script runs (PRELIMINARY only) |
| H-006 Factor Exposure Mean Reversion | Preregistered, execution blocked | 0 | 5 features registered; needs a cross-sectional (panel, weekly rank/rebalance) evaluator |
| H-004 Macro Yield Curve & Credit Spread Momentum | Preregistered (ledger only) | 0 | Needs macro yield-curve/credit-spread data |
| H-007 Cross-Sectional Quality-Minus-Junk Low-Turnover Core | Preregistered (ledger only) | 0 | Needs fundamentals data plus the cross-sectional evaluator |
| H-008 Microstructure Order Flow Imbalance | Preregistered (ledger only) | 0 | Needs intraday order-flow/microstructure data |

## Invalid Early Executions

The earlier H-001/H-002 runs that all returned approximately -0.41 Sharpe used
the generic price/volume automation template rather than the preregistered
hypothesis feature families. They are retained as framework-defect evidence,
not hypothesis results. Later generic proxy attempts for H-002/H-003 are also
ineligible; the runtime now refuses them before a trial is recorded.

## Next Action

- Preserve H-001 as a rejecting confirmation; do not tune it on the observed
  data.
- Implement the exact original H-002/H-003 data contracts, formally close those
  hypotheses, or preregister a genuinely new mechanism on untouched data.
- If a scalar-compatible idea is desired, preregister it as a new family rather
  than relabelling a proxy as H-002 or H-003.
- Run H-005 trials 5–10 through the engine protocol (add ^VIX to the h005
  configs first; Trials 1–4 are standalone-script PRELIMINARY runs).
- Implement the cross-sectional (panel) evaluator to unblock H-006, and decide
  the data contracts for ledger-only H-004/H-007/H-008.

The project remains `RESEARCH_ONLY`.
