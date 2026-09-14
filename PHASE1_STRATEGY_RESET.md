> **Historical implementation plan.** Steps 1–4 were completed. Current Step 5
> status is H-001 rejected and H-002/H-003 blocked before valid trial; use
> [PHASE1_PROGRESS.md](PHASE1_PROGRESS.md) rather than the old schedule or
> unchecked deliverables below.

# Phase 1: Strategy Research Reset - Implementation Plan

## Executive Summary

**Current State:** All recent strategy runs (seed44, seed45, seed46, seed44_30min) fail critical research gates, primarily `placebo_separates`. The pv-2.2.0 strategy line is statistically indistinguishable from noise.

**Goal:** Close the failed strategy line and establish a new research direction with defensible economic mechanisms.

---

## Step 1: Document Current Strategy Failures ✓

### Evidence Summary

| Run | Decision | Failed Gates | Placebo Percentile | Notes |
|-----|----------|--------------|-------------------|-------|
| seed44 (20260913T075742Z) | RESEARCH_ONLY | placebo_separates | 0.85 | Need ≥0.95 |
| seed45 (20260912T231914Z) | RESEARCH_ONLY | cost_stress_survives, placebo_separates | 0.50 | Cost drag kills it |
| seed46 (20260912T233445Z) | RESEARCH_ONLY | placebo_separates | 0.90 | Close but fails |
| seed44_30min (20260913T100810Z) | RESEARCH_ONLY | placebo_separates | 0.85 | Same as seed44 |

**Critical Finding:** All strategies fail `placebo_separates` gate requiring percentile ≥0.95 with adjusted p-value ≤0.10. Current best is 0.90 (seed46), but still below threshold.

---

## Step 2: Close pv-2.2.0 Research Line

### Actions Required

1. **Create closure document** for pv-2.2.0 strategy family
2. **Archive all artifacts** with failure documentation
3. **Update experiment registry** to mark line as CLOSED_FAILED
4. **Document lessons learned** about why this approach failed

### Root Cause Analysis

The baseline strategy uses:
- Gradient Boosting / Logistic Regression on technical features
- Walk-forward validation with 7 folds
- Features include: overnight gap, intraday return, RSI, Bollinger position, 52-week position, vol-of-vol

**Why It Fails Placebo Test:**
- Signal has no durable economic mechanism
- Performance likely from overfitting to historical noise
- Placebo permutations achieve similar Sharpe ratios
- No structural reason why signal should persist out-of-sample

---

## Step 3: Develop New Signal Hypothesis

### Preregistration Requirements

Before any new research begins, document:

1. **Economic Mechanism**: Why should this signal exist?
   - Market friction explanation
   - Behavioral bias rationale
   - Risk premium justification
   - Structural constraint argument

2. **Testable Prediction**: What specific pattern do we expect?
   - Direction of effect
   - Expected magnitude
   - Conditions where it strengthens/weakens

3. **Falsification Criteria**: What would prove it wrong?
   - Specific gate failures
   - Regime dependencies
   - Asset class boundaries

4. **Analysis Plan**: 
   - Data requirements
   - Feature construction (pre-registered)
   - Model class justification
   - Validation protocol

### Promising Research Directions

#### Direction A: Liquidity-Based Signals
**Mechanism:** Market makers demand compensation for inventory risk
**Prediction:** Assets with higher liquidity risk should have predictable returns
**Features:** Bid-ask spread proxies, volume volatility, Amihud illiquidity

#### Direction B: Cross-Asset Spillover
**Mechanism:** Information diffusion across related assets
**Prediction:** QQQ movements predict SPY with lag (or vice versa)
**Features:** Cross-correlation, lead-lag measures, ETF flow data

#### Direction C: Volatility Risk Premium
**Mechanism:** Investors overpay for downside protection
**Prediction:** High realized vol → negative future returns
**Features:** Realized vol, VIX-term structure proxies, skewness

#### Direction D: Seasonal/Calendar Effects
**Mechanism:** Institutional flows, tax considerations, window dressing
**Prediction:** Predictable patterns at month-end, quarter-end, holidays
**Features:** Day-of-week, month effects, turn-of-month indicators

---

## Step 4: Implement New Strategy Framework

### Code Changes Needed

```python
# New strategy template with preregistration support
class PreregisteredStrategy:
    def __init__(self, preregistration_doc: dict):
        self.economic_mechanism = preregistration_doc['mechanism']
        self.testable_prediction = preregistration_doc['prediction']
        self.falsification_criteria = preregistration_doc['falsification']
        self.analysis_plan = preregistration_doc['plan']
        
    def validate_mechanism(self, data: pd.DataFrame) -> bool:
        """Test if proposed mechanism exists in data"""
        pass
        
    def construct_features(self) -> List[str]:
        """Only pre-registered features allowed"""
        return self.analysis_plan['features']
```

### Gate Enhancements

Consider adding:
- **economic_mechanism_documented**: Boolean check for preregistration
- **out_of_sample_decay**: Max allowable Sharpe drop from train to OOS
- **cross_asset_robustness**: Must work on multiple related assets
- **regime_stability**: Performance consistency across market regimes

---

## Step 5: Execute New Research Campaign

### Trial Budget

- Maximum 10 trials per hypothesis
- Maximum 3 hypotheses per research family
- Total cap: 30 trials before mandatory review

### Success Criteria

All 14 gates must pass:
1. ✅ median_oos_sharpe_positive (>0.0)
2. ✅ mean_oos_sharpe_positive (>0.0)
3. ✅ worst_dd_within_limit (>-0.5)
4. ✅ cost_stress_survives (positive Sharpe at ≥10bps fees)
5. ✅ delay_stress_survives (positive Sharpe with execution delay)
6. ✅ bootstrap_positive_prob (≥80% probability Sharpe >0)
7. ✅ placebo_separates (percentile ≥0.95, p ≤0.10) ← **CRITICAL**
8. ✅ placebo_sample_adequate (≥20 null runs)
9. ✅ not_single_fold (no single fold dominates)
10. ✅ turnover_plausible (≤60x annual)
11. ✅ data_integrity (no lookahead, clean data)
12. ✅ lookahead_resolved (no unresolved risks)
13. ✅ trial_accounting_consistent (proper trial counting)
14. ✅ family_search_within_cap (within search budget)

### Timeline

- Week 1-2: Literature review, hypothesis development
- Week 3: Preregistration, feature engineering
- Week 4-6: Initial experiments (max 10 trials)
- Week 7: Review and pivot decision
- Week 8-10: Second hypothesis if needed
- Week 11-12: Final validation and documentation

---

## Deliverables

1. [ ] pv-2.2.0 closure document
2. [ ] Archived artifacts with failure analysis
3. [ ] New hypothesis preregistration documents
4. [ ] Updated strategy framework code
5. [ ] Research campaign results (pass/fail)
6. [ ] Recommendation: proceed to paper trading OR continue research

---

## Risk Mitigation

**Risk:** No viable strategy found after 3 months
**Mitigation:** Expand asset universe, consider alternative data sources, partner with external researchers

**Risk:** Strategy passes gates but fails paper trading
**Mitigation:** Extend paper validation to 90 days, add more stress tests

**Risk:** Market regime change invalidates research
**Mitification:** Include regime-switching models, test across multiple market conditions

---

*Created: 2026-09-13*
*Historical status at creation: IN PROGRESS*  
*Current status: superseded by PHASE1_PROGRESS.md*
