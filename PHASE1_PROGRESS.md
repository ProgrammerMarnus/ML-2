# Phase 1: Strategy Research Reset — Current Progress

**Started:** 2026-09-13  
**Updated:** 2026-09-14  
**Status:** ACTIVE, BLOCKED ON H-002/H-003 DATA CONTRACT DECISION  
**Promotion state:** `RESEARCH_ONLY`

## Completed

- Closed the legacy pv-2.2.0 strategy family as failed and preserved its evidence.
- Created the preregistration template and H-001/H-002/H-003 specifications.
- Implemented and registered the hypothesis feature modules.
- Fixed the experiment execution path so hypothesis identity and feature-family
  selection are enforced instead of silently falling back to generic templates.
- Added execution-eligibility and stable dataset-family contract checks.
- Completed the corrected H-001 confirmation run.

## Scientific Results

| Hypothesis | Valid status | Result / blocker |
|---|---|---|
| H-001 Cross-Asset Spillover | **REJECTED** | Net Sharpe 0.787318; placebo percentile 0.35; adjusted p-value 0.6667. The preregistered separation gate failed. |
| H-002 Liquidity Reversal | **BLOCKED BEFORE TRIAL** | Requires the preregistered cross-sectional small/mid-cap universe and liquidity inputs; the scalar runner cannot provide them. |
| H-003 Volatility Risk Premium | **BLOCKED BEFORE TRIAL** | Requires the preregistered multi-asset and VIX/term-structure inputs; the scalar runner cannot provide them. |

Earlier runs that produced identical generic price/volume results were invalid
proxy executions. They consume audit history but are not scientific evidence
for H-001, H-002, or H-003.

## Required Decision

For H-002 and H-003, either:

1. implement and freeze each exact preregistered data contract, then execute;
2. close the hypothesis without a valid trial; or
3. preregister a new scalar-compatible family under a new identity.

Substituting generic price/volume features under the current hypothesis IDs is
forbidden. H-001 remains rejected; its observed confirmation period must not be
used for post-hoc tuning.

## Phase 1 Exit Condition

Phase 1 is complete only when every open hypothesis is validly executed or
formally closed and the portfolio decision is recorded. No strategy currently
qualifies for `ROBUST_OOS`, paper promotion, or live trading.

See [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) and
[LIVE_TRADING_READINESS_CHECKLIST.txt](LIVE_TRADING_READINESS_CHECKLIST.txt).
