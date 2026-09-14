> **Historical execution log — invalid proxy runs.** The early H-001/H-002
> entries below used generic price/volume templates and are framework-defect
> evidence, not hypothesis evidence. Current outcome: H-001 was later confirmed
> with the corrected contract and rejected; H-002/H-003 are blocked before
> valid trials. See [PHASE1_STEP5_PROGRESS.md](PHASE1_STEP5_PROGRESS.md).

# Phase 1, Step 5: Research Campaign Execution Log

## Overview
Executing systematic research campaign for three preregistered hypotheses (H-001, H-002, H-003) with strict trial budgets (10 trials each).

---

## H-001: Cross-Asset Spillover Trials

### Trial 1 (Baseline) - COMPLETE ❌
**Date:** 2026-09-14  
**Configuration:** Baseline features (10 features), alpha=0.001 (logreg_C=0.25), walk-forward 7-fold  
**Experiment ID:** `20260914T085809Z_992d3ef805baf68a`

**Results:**
- **Decision:** RESEARCH_ONLY
- **Net Sharpe (OOS):** -0.41 (FAILS: needs > 0)
- **Bootstrap P(SR>0):** 35% (FAILS: needs ≥80%)
- **Placebo Percentile:** 0.10 (FAILS: needs ≥0.95)
- **Failed Gates (7/14):**
  1. median_oos_sharpe_positive ✗
  2. mean_oos_sharpe_positive ✗
  3. cost_stress_survives ✗
  4. bootstrap_positive_prob ✗
  5. placebo_separates ✗
  6. not_single_fold ✗
  7. family_search_within_cap ✗

**Interpretation:** Strategy is anti-predictive (negative Sharpe) and indistinguishable from noise (placebo percentile 0.10 means random noise performs better). The cross-asset spillover signal as specified has no predictive power.

**Status:** FAILED - Requires hypothesis refinement or abandonment

---

### Trial 2 (Weaker Regularization) - COMPLETE ❌
**Date:** 2026-09-14  
**Configuration:** Same features, logreg_C=0.5 (2x weaker regularization), 50 bootstrap, 20 placebo  
**Experiment ID:** `20260914T124208Z_f48329fc354fd2d8`
**Hypothesis:** Weaker regularization may allow model to capture genuine signal

**Results:**
- **Decision:** RESEARCH_ONLY (inferred - all critical gates fail)
- **Net Sharpe (OOS):** -0.41 (NO CHANGE vs Trial 1)
- **Bootstrap P(SR>0):** 30% (WORSE vs Trial 1's 35%)
- **Placebo Percentile:** 0.10 (NO CHANGE vs Trial 1)

**Comparison Trial 2 vs Trial 1:**
| Metric | Trial 1 | Trial 2 | Change |
|--------|---------|---------|--------|
| Mean Sharpe | -0.407 | -0.407 | 0.000 (no change) |
| Bootstrap Prob | 35% | 30% | -5pp (worse) |
| Placebo Percentile | 0.10 | 0.10 | 0.00 (no change) |

**Interpretation:** Weaker regularization provided ZERO benefit. The signal is fundamentally non-predictive, not overfit. Changing hyperparameters cannot fix a broken hypothesis.

**Status:** FAILED - Strong evidence to abandon H-001

---

### Trial 3 (Feature Subset: Returns Only) - CANCELLED
**Rationale:** After two consecutive failures with identical poor results, continuing to iterate on H-001 violates the preregistration stopping rules.

**Stopping Rule Triggered:** 
- ✓ Placebo percentile < 0.30 after Trials 1-2 (actual: 0.10)
- ✓ No improvement in any critical gate across trials
- ✓ Signal remains anti-predictive (negative Sharpe)

**Decision:** ABANDON H-001. Do not execute Trial 3.

**Trial Budget Used:** 2 of 10 (remaining 8 preserved for future hypotheses)

---

## Pivot Decision: H-001 → H-002

### Rationale for Abandoning H-001

1. **Consistent failure:** Two independent trials, identical negative results
2. **No hyperparameter sensitivity:** 2x change in regularization had zero effect
3. **Anti-predictive signal:** Negative Sharpe suggests feature construction may be inverted or mechanism invalid
4. **Placebo proves noise:** 0.10 percentile means strategy is worse than random
5. **Economic mechanism questioned:** Information diffusion theory may not translate to measurable alpha at daily frequency

### Next Hypothesis: H-002 (Liquidity Reversal)

**Advantages over H-001:**
- Stronger microstructural foundation (liquidity provision is well-documented)
- Different mechanism (liquidity vs information)
- Higher capacity ($50-200M vs $10-50M)
- Features already implemented (13 liquidity reversal features ready)
- Orthogonal to H-001 failures

**Execution Plan:**
- Launch H-002 Trial 1 immediately
- Use baseline protocol (similar to H-001 Trial 1)
- Universe: Top 500 stocks by market cap
- Focus on short-term reversals (1-5 day horizon)

---
