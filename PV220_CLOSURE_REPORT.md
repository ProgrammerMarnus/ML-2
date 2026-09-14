# Strategy pv-2.2.0 Closure Report

> **Closed historical strategy record.** The closure remains valid. Subsequent
> research produced no promotable replacement: H-001 is rejected and H-002/
> H-003 are blocked before valid trials. Current status is recorded in
> [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md).

**Date:** 2026-09-13  
**Status:** CLOSED_FAILED  
**Research Family:** 27c49d858beb9a36 (seed44), related families from seed45, seed46  

---

## Executive Summary

The pv-2.2.0 strategy line has been **terminated** after consistent failure to pass the `placebo_separates` research gate across multiple independent runs with different random seeds and parameter configurations. The strategy is statistically indistinguishable from noise and shows no evidence of a durable predictive signal.

**Recommendation:** Do not pursue further variations of this approach. Any future research must begin with a preregistered hypothesis grounded in economic theory, not data mining.

---

## Evidence Summary

### Experimental Runs

| Run ID | Timestamp | Decision | Failed Gates | Placebo % | Bootstrap P(SR>0) | Notes |
|--------|-----------|----------|--------------|-----------|-------------------|-------|
| seed44_run1 | 20260913T075742Z | RESEARCH_ONLY | placebo_separates | 0.85 | 0.916 | Best performer but fails separation |
| seed44_run2 | 20260913T085249Z | RESEARCH_ONLY | placebo_separates | - | - | Consistent failure |
| seed44_run3 | 20260913T092609Z | RESEARCH_ONLY | placebo_separates | - | - | Third confirmation |
| seed45 | 20260912T231914Z | RESEARCH_ONLY | cost_stress, placebo_separates | 0.50 | 0.644 | Also fails cost stress |
| seed46 | 20260912T233445Z | RESEARCH_ONLY | placebo_separates | 0.90 | 0.858 | Closest but still fails |
| seed44_30min | 20260913T100810Z | RESEARCH_ONLY | placebo_separates | 0.85 | 0.916 | Different frequency, same result |

**Total Trials:** 42+ per run × 6+ runs = 250+ trials  
**Success Rate:** 0% ROBUST_OOS promotions  
**Search Budget Used:** Multiple families at cap (1/1 each)

---

## Gate Performance Analysis

### Passing Gates (Consistent)

These gates passed in most runs, indicating basic strategy soundness:

- ✅ **median_oos_sharpe_positive**: Median Sharpe 0.24-0.50 > 0.0
- ✅ **mean_oos_sharpe_positive**: Mean Sharpe 0.23-0.57 > 0.0  
- ✅ **worst_dd_within_limit**: Max drawdown -7.9% to -10.8% > -50% limit
- ✅ **delay_stress_survives**: Maintains positive Sharpe with 1-bar delay
- ✅ **bootstrap_positive_prob**: 64%-92% probability Sharpe > 0 (variable)
- ✅ **placebo_sample_adequate**: 20 valid null runs completed
- ✅ **not_single_fold**: No single fold dominates (max share 43-60%)
- ✅ **turnover_plausible**: 8.9-11.2x annual turnover < 60x limit
- ✅ **data_integrity**: No lookahead or data quality issues detected
- ✅ **trial_accounting_consistent**: Proper trial counting maintained
- ✅ **family_search_within_cap**: Within search budget limits

### Failing Gates (Critical)

#### 1. placebo_separates ❌

**Requirement:** Placebo percentile ≥ 0.95 AND adjusted p-value ≤ 0.10  
**Best Result:** 0.90 percentile (seed46), p = 0.14  
**Typical Result:** 0.50-0.85 percentile, p = 0.19-0.52

**Interpretation:** When we randomly permute the target variable (destroying any real signal), the resulting "strategies" achieve similar or better Sharpe ratios 50-85% of the time. This means the observed performance is **statistically indistinguishable from random chance**.

**Why This Matters:** The placebo test is the gold standard for detecting overfitting. A strategy that cannot separate from its own permutations has no genuine predictive power—it has simply memorized historical noise patterns.

#### 2. cost_stress_survives ❌ (seed45 only)

**Requirement:** Positive Sharpe after applying ≥10 bps transaction fees  
**Result:** seed45 failed with fee stress (Sharpe turned negative)  
**Interpretation:** Marginal strategies with low gross returns cannot survive realistic trading costs.

---

## Root Cause Analysis

### Why pv-2.2.0 Failed

1. **No Economic Mechanism**
   - Strategy uses technical indicators (RSI, Bollinger bands, 52-week position) without theoretical justification
   - No explanation for why these patterns should persist in efficient markets
   - Features are widely known and likely arbitraged away if they ever existed

2. **Overfitting to Historical Noise**
   - Gradient boosting can fit arbitrary patterns in training data
   - Walk-forward validation helps but doesn't eliminate look-ahead bias in feature selection
   - Feature engineering process itself may have been optimized on the same data

3. **Data Mining Without Preregistration**
   - No documented hypothesis before experimentation
   - Multiple seeds tried until "good" results appeared (survivorship bias)
   - Search budget fragmented across families instead of concentrated testing

4. **Generic Technical Features**
   - Overnight gap, intraday return: No structural reason for predictability
   - RSI, Bollinger position: Publicly known indicators with no edge
   - Vol-of-vol: May capture something real but not robustly enough

5. **Insufficient Signal Strength**
   - Even when gates pass, Sharpe ratios are marginal (0.2-0.6)
   - Such weak signals are easily destroyed by minor regime changes
   - Not sufficient compensation for model risk and execution uncertainty

---

## What Was Learned

### Positive Findings

1. **Research Infrastructure Works**
   - Walk-forward validation properly implemented
   - Gate system correctly identifies weak strategies
   - Placebo testing catches overfitting
   - Trial accounting prevents unlimited search

2. **Baseline Strategy Is Sound (But Not Profitable)**
   - No lookahead leakage detected
   - Execution replay matches original results
   - Cost accounting is accurate
   - Framework supports rigorous testing

3. **Some Gates Are Too Easy**
   - median_oos_sharpe_positive passes even for noise strategies
   - Need higher bars for promotion (e.g., Sharpe > 0.5 minimum)
   - Consider adding additional gates for robustness

### Negative Findings

1. **Technical Analysis Alone Insufficient**
   - Simple ML on price-derived features cannot beat markets
   - Public indicators provide no sustainable edge
   - Need alternative data or structural advantages

2. **Seed-Chasing Is Unproductive**
   - Trying different random seeds until one "works" is p-hacking
   - All seeds should be treated as equally valid tests
   - Consistency across seeds is more important than best-case performance

3. **Placebo Test Is The Hard Gate**
   - Most other gates can be satisfied with reasonable parameters
   - Placebo separation requires genuine signal, not curve-fitting
   - This is the primary filter for real vs. spurious findings

---

## Recommendations for Future Research

### Immediate Actions

1. **Stop Current Approach**
   - Cease all pv-2.2.0 variant experiments
   - Archive all artifacts with this closure report
   - Mark research families as CLOSED_FAILED in registry

2. **Require Preregistration**
   - Document economic mechanism before any code changes
   - Specify features, models, and validation protocol in advance
   - Define falsification criteria upfront

3. **Raise Standards**
   - Require placebo percentile ≥ 0.95 (current best: 0.90)
   - Require bootstrap P(SR>0) ≥ 0.90 (current best: 0.916)
   - Consider adding minimum Sharpe threshold (e.g., > 0.5)

### New Research Directions

See PHASE1_STRATEGY_RESET.md for detailed proposals:

- **Liquidity-based signals**: Market microstructure frictions
- **Cross-asset spillover**: Information diffusion between SPY/QQQ
- **Volatility risk premium**: Variance risk pricing
- **Seasonal effects**: Calendar anomalies with institutional basis

### Process Improvements

1. **Trial Budget Enforcement**
   - Maximum 10 trials per hypothesis
   - Maximum 3 hypotheses per family
   - Mandatory review after 30 total trials

2. **Blind Validation**
   - Lock test set before any experimentation
   - Use separate validation set for parameter tuning
   - Final evaluation only once per hypothesis

3. **Economic Review Board**
   - External review of mechanisms before coding
   - Challenge sessions to stress-test rationales
   - Kill projects lacking theoretical foundation

---

## Artifacts Archived

All experimental artifacts preserved in:

- `artifacts_seed44/` - 3 runs + metadata
- `artifacts_seed45/` - 1 run + metadata
- `artifacts_seed46/` - 1 run + metadata
- `artifacts_seed44_30min/` - 1 run + metadata
- `strategy-runs.jsonl` - Complete run history
- `experiment_registry.jsonl` - Family tracking

**Total Storage:** ~5 MB of JSON/CSV evidence  
**Retention Policy:** Indefinite (for audit trail and learning)

---

## Conclusion

The pv-2.2.0 strategy line has been conclusively demonstrated to lack genuine predictive power. While the research infrastructure functioned correctly and identified the failure appropriately, the underlying approach—applying machine learning to technical indicators—proved incapable of generating alpha distinguishable from noise.

**This is not a failure of the research process; it is the research process working as designed.** The gates prevented a bad strategy from advancing to paper trading, where it would have lost money and wasted time.

Future efforts must start from first principles: identify a market inefficiency with a structural or behavioral basis, formulate a testable hypothesis, and then—and only then—write code to test it. Data mining without theory is guaranteed to find patterns that don't exist out-of-sample.

---

**Report Prepared By:** Automated Research System  
**Review Status:** Closure recorded 2026-09-14  
**Next Action:** Follow the current decision boundary in PHASE1_PROGRESS.md
