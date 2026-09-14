# H-002 Trial 2 Results - Liquidity Reversal Hypothesis

**Status:** ❌ FAILED - RESEARCH_ONLY  
**Experiment ID:** `20260914T133400Z_b53f2b9fb2cafc65`  
**Date:** 2026-09-14

## Key Metrics (Identical to Trial 1)

| Metric | Trial 2 | Trial 1 | Threshold |
|--------|---------|---------|-----------|
| Mean OOS Sharpe | -0.41 | -0.41 | > 0.0 |
| Bootstrap P(SR>0) | 35% | 35% | ≥ 80% |
| Placebo Percentile | 0.10 | 0.10 | ≥ 0.95 |
| Failed Gates | 7 | 7 | 0 |

## Critical Finding

**Trial 2 produced IDENTICAL results to Trial 1** - same Sharpe (-0.41), same bootstrap (35%), same placebo (0.10).

This indicates:
1. Default template parameters not being overridden by hypothesis-specific config
2. Liquidity reversal features not being used in the model
3. Configuration pipeline issue between hypothesis spec and execution

## Root Cause Analysis

The automation module is running default `regularized_directional_logistic_short_hold` template instead of H-002 liquidity reversal features. This is a **framework execution issue**, not a hypothesis failure.

## Required Fix

Need to create proper H-002-specific configuration that:
1. Uses liquidity_reversal features (13 features)
2. Sets appropriate hyperparameters for liquidity signals
3. Properly binds to H-002 hypothesis ID

## Next Actions

1. Create H-002 specific config file with liquidity features
2. Verify feature registry includes liq_rev_* features
3. Re-execute Trial 2 with correct configuration
4. If still fails → pivot to H-003

---
*Framework execution issue identified - not a true hypothesis test result*
