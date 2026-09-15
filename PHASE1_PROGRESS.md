# Phase 1: Strategy Research Reset — Current Progress

**Started:** 2026-09-13  
**Updated:** 2026-09-15 (late evening, after valid H-006 Trial 1)
**Status:** ACTIVE — both H-005 engine executions are `CANDIDATE` (all frozen
gates passed; 10/10 selection budget spent); H-001/H-002-R1/H-003-R1 rejected;
H-006 rejected after valid panel execution; H-004/H-007/H-008 remain ledger-only
**Promotion state:** `RESEARCH_ONLY` overall — H-005 `CANDIDATE` pending an
untouched confirmation window

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
- Implemented the H-006 panel evaluator and constrained weekly portfolio,
  corrected undefined self-benchmark standardization, froze exact-snapshot
  replay after provider drift, executed valid Trial 1, and rejected the family
  under its prospective stop rule.
- Merged the parallel AI Studio branches (PRs #4/#5): the H-005 and H-006
  feature modules, configs, and tests are on main, and the full-stack research
  dashboard (Express backend + 8 panels) was imported from the AI Studio
  export.
- Preregistered five newer families in
  `data/research_ledgers/preregistrations.jsonl`: H-005 and H-006 (with
  feature modules and frozen configs) and ledger-only H-004, H-007, H-008.

## Scientific Results

| Hypothesis | Valid status | Result / blocker |
|---|---|---|
| H-001 Cross-Asset Spillover | **REJECTED** | Net Sharpe 0.787318; placebo percentile 0.35; adjusted p-value 0.6667. The preregistered separation gate failed. |
| H-002 Liquidity Reversal (original) | **BLOCKED BEFORE TRIAL** | Requires the preregistered cross-sectional small/mid-cap universe, PIT market cap, VIX, and midpoint-classified trade inputs; the runner cannot provide them. |
| H-002-R1 Liquidity Reversal (amended) | **REJECTED** | Valid single run on real 2010-2023 daily data (285 names). Gross Sharpe −0.342 (no edge before costs); 0/10 positive OOS folds; net Sharpe −2.656; annual turnover 72× vs 6× cap. Trial budget retired. |
| H-003 Volatility Risk Premium | **BLOCKED BEFORE TRIAL** | Requires the preregistered multi-asset and VIX/term-structure inputs; the scalar runner cannot provide them. |
| H-003-R1 Daily Volatility-Shock Allocation | **REJECTED** | One frozen 2008–2023 baseline: net Sharpe −0.074; 10/14 mandate gates failed; budget retired. |
| H-005 Overnight-Intraday Decomposition | **CANDIDATE (two protocol-bound engine executions)** | Both REAL_DATA runs passed all 14 gates. Execution 1 `20260915T160008Z_283db198b22dc6aa`: net Sharpe 0.997, placebo 1.0 / p 0.0476. Execution 2 `20260915T171435Z_8ab87aaf928a91ec`: net Sharpe 1.116, placebo 0.95 / p 0.0952. Both bootstrap P(SR>0) 0.994; cost/delay, leakage, and integrity gates pass. Not `ROBUST_OOS`: both use the previously inspected 2010–2021 window and mean AUC is 0.505/0.501. Budget 10/10 spent. |
| H-006 Factor Exposure Mean Reversion | **REJECTED** | Valid experiment `20260915T183149Z_ce1050bcacf83541`: net Sharpe -0.073, 2/5 positive folds, turnover 15.21x, capacity $19.99m, 13 failed gates. Remaining budget retired. Earlier self-benchmark-noise record invalidated. |
| H-004 Macro Yield Curve & Credit Spread Momentum | **PREREGISTERED (LEDGER ONLY)** | No module/config/engine path; needs macro yield-curve/credit-spread data. |
| H-007 Cross-Sectional Quality-Minus-Junk Low-Turnover Core | **PREREGISTERED (LEDGER ONLY)** | Needs fundamentals data plus the cross-sectional evaluator. |
| H-008 Microstructure Order Flow Imbalance | **PREREGISTERED (LEDGER ONLY)** | Needs intraday order-flow/microstructure data. |

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

H-005 cleared every gate it froze twice, but its budget was exhausted on the
already-inspected window. It must not be run again under this campaign. H-006
is also closed after its valid Trial 1 failure. The next authorized research
step is to implement the data contracts for ledger-only H-004/H-007/H-008 or
formally close them. The panel infrastructure needed by H-007-style families
now exists, but no fundamentals contract does.

A genuinely unseen 2022–2026 H-005 confirmation now requires explicit approval
and a separately frozen confirmation family/protocol with its own budget.

Substituting generic price/volume features under the current hypothesis IDs is
forbidden. H-001 remains rejected; its observed confirmation period must not be
used for post-hoc tuning. H-002's observed 2010-2023 window is now spent and must
not be reused to search for a variant of H-002-R1 that works. H-005's inspected
2010–2021 window must likewise not be re-cut to improve its `CANDIDATE` result.

## Phase 1 Exit Condition

Phase 1 is complete only when every open hypothesis is validly executed or
formally closed and the portfolio decision is recorded. No strategy currently
qualifies for `ROBUST_OOS`, paper promotion, or live trading.

See [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) and
[LIVE_TRADING_READINESS_CHECKLIST.txt](LIVE_TRADING_READINESS_CHECKLIST.txt).
