# Phase 1 Step 4 - Strategy Framework Implementation

## Status: COMPLETE ✅

Successfully integrated all three preregistered hypotheses into the research framework.

### Feature Registry Integration

**Total Features Registered:** 73

| Category | Count | Features |
|----------|-------|----------|
| **Base Price/Volume** | 21 | momentum, trend, vol, volume, regime features |
| **Information (FinBERT)** | 8 | sentiment, attention, novelty, disagreement |
| **H-001 Cross-Asset Spillover** | 10 | qqq/spy lags, interaction terms, acceleration |
| **H-002 Liquidity Reversal** | 13 | amihud, volume imbalance, pressure, Kyle's lambda |
| **H-003 Volatility Risk Premium** | 21 | VRP, term structure, skewness, kurtosis, jumps |

### Files Modified

1. `src/quant_research/features/registry.py` - Added hypothesis feature specs to registry
2. `configs/phase1_hypotheses.yaml` - Created experiment configuration

### Verification Tests Passed

```python
✅ H-001 features module imports correctly
✅ H-002 features module imports correctly  
✅ H-003 features module imports correctly
✅ All 73 features registered in central registry
✅ Feature specs accessible with metadata (source, history, normalization)
```

### Next Steps (Step 5)

Ready to execute research campaign:

1. Run Trial 1 for H-001 (Cross-Asset Spillover)
2. Run Trial 1 for H-002 (Liquidity Reversal)
3. Run Trial 1 for H-003 (Volatility Risk Premium)
4. Evaluate against 14 research gates
5. Iterate up to 10 trials per hypothesis OR until ROBUST_OOS achieved

### Command to Execute First Trials

```bash
# H-001 Trial 1
python -m quant_research.experiments.automation \
  --config configs/phase1_hypotheses.yaml \
  --output artifacts/h001_trial1 \
  --max-experiments 1 \
  --run

# Or use discovery runner for systematic search
python discover-runner.py --hypothesis H001 --trial 1
```

### Success Criteria

A hypothesis achieves **ROBUST_OOS** status when ALL 14 gates pass:
- ✅ full_oos_net_sharpe ≥ 0.0
- ✅ cost_stress_survives (fee drag ≤ 30%)
- ✅ delay_stress_survives 
- ✅ bootstrap_positive_prob ≥ 80%
- ✅ placebo_separates ≥ 95th percentile ← CRITICAL (pv-2.2.0 failed here)
- ✅ no_single_fold_dominance
- ✅ turnover within limits
- ✅ max drawdown ≤ 50%
- + 6 additional gates

### Timeline

- **Week 2 (Current):** Framework ready, begin trials
- **Week 3-4:** Complete trial campaigns (up to 10 per hypothesis)
- **Week 5:** Go/No-Go decision on promotion to paper trading
