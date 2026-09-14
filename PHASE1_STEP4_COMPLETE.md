> **Historical milestone.** Framework integration is complete, but the
> execution instructions below are superseded. H-001 was validly confirmed and
> rejected; H-002/H-003 require unavailable preregistered data contracts. Use
> [PHASE1_PROGRESS.md](PHASE1_PROGRESS.md) for current actions.

# Phase 1 Step 4 - Strategy Framework Implementation

## Status: COMPLETE ✅

Successfully integrated all three preregistered hypotheses into the research framework.

### Feature Registry Integration

**Total Features Registered:** 72

| Category | Count | Features |
|----------|-------|----------|
| **Base Price/Volume** | 21 | momentum, trend, vol, volume, regime features |
| **Information (FinBERT)** | 8 | sentiment, attention, novelty, disagreement |
| **H-001 Cross-Asset Spillover** | 9 | qqq/spy lags, interaction terms, acceleration |
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
✅ All 72 features registered in central registry
✅ Feature specs accessible with metadata (source, history, normalization)
```

### Next Steps (Step 5)

The original execution plan below is preserved as historical context and must
not be run as a proxy campaign:

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

### Current Scientific Outcome

- H-001: corrected confirmation completed and rejected.
- H-002: blocked before trial on its cross-sectional liquidity contract.
- H-003: blocked before trial on its multi-asset/VIX contract.
- Promotion remains `RESEARCH_ONLY`.
