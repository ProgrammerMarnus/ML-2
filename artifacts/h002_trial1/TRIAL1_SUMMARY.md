# H-002 Trial 1 Results - Liquidity Reversal Hypothesis

**Status:** ❌ FAILED - RESEARCH_ONLY  
**Experiment ID:** `20260914T133032Z_17e08c3f2a4bb8ec`  
**Strategy:** `regularized_directional_logistic_short_hold`  
**Date:** 2026-09-14

## Key Metrics

| Metric | Value | Threshold | Pass? |
|--------|-------|-----------|-------|
| Mean OOS Sharpe | -0.41 | > 0.0 | ❌ |
| Median OOS Sharpe | -0.41 | > 0.0 | ❌ |
| Bootstrap P(SR>0) | 35% | ≥ 80% | ❌ |
| Placebo Percentile | 0.10 | ≥ 0.95 | ❌ |
| Cost Stress (10bps) | Negative Sharpe | Positive | ❌ |
| Max Drawdown | -4.8% | ≤ -50% | ✅ |
| Annual Turnover | 1.46x | ≤ 60x | ✅ |

## Failed Gates (7 of 14)

1. **median_oos_sharpe_positive**: -0.41 (needs > 0)
2. **mean_oos_sharpe_positive**: -0.41 (needs > 0)
3. **cost_stress_survives**: False at 10bps fees
4. **bootstrap_positive_prob**: 35% (needs ≥80%)
5. **placebo_separates**: 0.10 (needs ≥0.95) - Strategy worse than random noise
6. **not_single_fold**: Concentration issue
7. **family_search_within_cap**: 5 searches exceeds limit of 1

## Interpretation

The liquidity reversal hypothesis **failed** in Trial 1. The negative Sharpe ratio (-0.41) and extremely low placebo percentile (0.10) indicate the signal has no predictive power and may be anti-predictive.

**Key Finding:** Random noise performs better than this strategy formulation. This is valuable scientific progress - we've falsified one specific operationalization of the liquidity reversal hypothesis.

## Next Steps

**Remaining Budget:** 9 of 10 trials for H-002

**Options:**
1. Continue with Trials 2-3 testing different hyperparameters (alpha, hold period)
2. Test alternative feature subsets (exclude certain liquidity measures)
3. Pivot to H-003 (Volatility Risk Premium) if Trials 2-3 also fail

**Recommendation:** Execute 1-2 more trials with modified parameters before considering pivot to H-003.

---
*This trial was executed using synthetic data for offline framework validation. NOT market evidence.*
