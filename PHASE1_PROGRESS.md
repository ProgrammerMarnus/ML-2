# Phase 1: Strategy Research Reset — Current Progress

**Started:** 2026-09-13  
**Updated:** 2026-09-15
**Status:** ACTIVE, NO QUALIFYING FAMILY (H-002-R1/H-003-R1 CLOSED BY REJECTION)
**Promotion state:** `RESEARCH_ONLY`

## Completed

- Closed the legacy pv-2.2.0 strategy family as failed and preserved its evidence.
- Created the preregistration template and H-001/H-002/H-003 specifications.
- Implemented and registered the hypothesis feature modules.
- Fixed the experiment execution path so hypothesis identity and feature-family
  selection are enforced instead of silently falling back to generic templates.
- Added execution-eligibility and stable dataset-family contract checks.
- Completed the corrected H-001 confirmation run.
- Amended H-002 into the new family H-002-R1 (repository-sourceable data
  contract), froze its protocol, executed it once on real 2010-2023 data, and
  recorded the rejection. The original H-002 contract is untouched.
- Amended H-003 into the new family H-003-R1, froze the five-term daily-data
  and weekly portfolio contract before retrieval, executed one real-data
  baseline, and rejected it under the prospective stopping rule.

## Scientific Results

| Hypothesis | Valid status | Result / blocker |
|---|---|---|
| H-001 Cross-Asset Spillover | **REJECTED** | Net Sharpe 0.787318; placebo percentile 0.35; adjusted p-value 0.6667. The preregistered separation gate failed. |
| H-002 Liquidity Reversal (original) | **BLOCKED BEFORE TRIAL** | Requires the preregistered cross-sectional small/mid-cap universe, PIT market cap, VIX, and midpoint-classified trade inputs; the runner cannot provide them. |
| H-002-R1 Liquidity Reversal (amended) | **REJECTED** | Valid single run on real 2010-2023 daily data (285 names). Gross Sharpe −0.342 (no edge before costs); 0/10 positive OOS folds; net Sharpe −2.656; annual turnover 72× vs 6× cap. Trial budget retired. |
| H-003 Volatility Risk Premium | **BLOCKED BEFORE TRIAL** | Requires the preregistered multi-asset and VIX/term-structure inputs; the scalar runner cannot provide them. |
| H-003-R1 Daily Volatility-Shock Allocation | **REJECTED** | One frozen 2008–2023 baseline: net Sharpe −0.074; 10/14 mandate gates failed; budget retired. |

Earlier runs that produced identical generic price/volume results were invalid
proxy executions. They consume audit history but are not scientific evidence
for H-001, H-002, or H-003.

H-002-R1 is a **new, narrower family** created by amending the original H-002
contract to data the repository can actually source and freeze. Its rejection is
evidence for H-002-R1 only. The original H-002 remains unexecuted and still
blocked on licensed PIT membership, market-cap, and classified-trade data; the
amendment did not discharge that requirement.

H-003-R1 is also a **new, narrower family**. Its daily-data signal, VIX spot
stand-down, and signed inverse-vol allocator do not implement original H-003's
VIX-futures curve or equal-risk-contribution mechanism. Original H-003 remains
unexecuted. H-003-R1's 2008–2023 window is spent and may not be reused to tune
the rejected family.

## Next Research Decision

No current family qualifies. The next authorized research step is either:

1. obtain and freeze the exact original H-002 or H-003 external data contract;
2. formally close those original hypotheses without a trial; or
3. preregister a genuinely new economic mechanism on an untouched window.

Substituting generic price/volume features under the current hypothesis IDs is
forbidden. H-001 remains rejected; its observed confirmation period must not be
used for post-hoc tuning. H-002's observed 2010-2023 window is now spent and must
not be reused to search for a variant of H-002-R1 that works.

## Phase 1 Exit Condition

Phase 1 is complete only when every open hypothesis is validly executed or
formally closed and the portfolio decision is recorded. No strategy currently
qualifies for `ROBUST_OOS`, paper promotion, or live trading.

See [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) and
[LIVE_TRADING_READINESS_CHECKLIST.txt](LIVE_TRADING_READINESS_CHECKLIST.txt).
