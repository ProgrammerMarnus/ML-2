# Phase 1, Step 5: Research Campaign Execution — Current Record

**Updated:** 2026-09-14  
**Status:** H-001 complete and rejected; H-002/H-003 blocked before valid trial

## Valid Evidence

| Hypothesis | State | Trials with valid hypothesis contract | Outcome |
|---|---:|---:|---|
| H-001 Cross-Asset Spillover | Rejected | 1 corrected confirmation | Net Sharpe 0.787318; placebo percentile 0.35; adjusted p-value 0.6667; fails preregistered separation gate |
| H-002 Liquidity Reversal | Blocked | 0 | Missing cross-sectional small/mid-cap and liquidity contract |
| H-003 Volatility Risk Premium | Blocked | 0 | Missing multi-asset and VIX/term-structure contract |

## Invalid Early Executions

The earlier H-001/H-002 runs that all returned approximately -0.41 Sharpe used
the generic price/volume automation template rather than the preregistered
hypothesis feature families. They are retained as framework-defect evidence,
not hypothesis results. Later generic proxy attempts for H-002/H-003 are also
ineligible; the runtime now refuses them before a trial is recorded.

## Next Action

- Preserve H-001 as a rejecting confirmation; do not tune it on the observed
  data.
- Implement the exact H-002/H-003 data contracts, or formally close those
  hypotheses.
- If a scalar-compatible idea is desired, preregister it as a new family rather
  than relabelling a proxy as H-002 or H-003.

The project remains `RESEARCH_ONLY`.
