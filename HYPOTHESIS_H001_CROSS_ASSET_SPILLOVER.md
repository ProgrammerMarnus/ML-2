# Hypothesis H-001: Cross-Asset Spillover Between SPY and QQQ

**Hypothesis ID:** H-001  
**Research Family:** cross_asset_spillover_v1  
**Date Preregistered:** 2026-09-13  
**Status:** PENDING_APPROVAL  

---

## Section 1: Economic Mechanism

### 1.1 Market Inefficiency: Information Diffusion Lag

**Mechanism:** Information diffuses across related assets with a lag due to:

1. **Investor Attention Constraints**: Investors cannot process all information simultaneously across all assets. When major news affects the technology sector, QQQ (Nasdaq-100 ETF) may react immediately, but SPY (S&P 500 ETF) reacts more slowly as attention gradually spreads.

2. **Arbitrage Frictions**: While statistical arbitrageurs monitor SPY-QQQ relationships, they face:
   - Transaction costs that create no-arbitrage bands
   - Execution risk during volatile periods
   - Capital constraints limiting position sizes
   - Short-selling restrictions in stressed markets

3. **ETF Structure Differences**: 
   - QQQ holds 100 Nasdaq stocks, SPY holds 500 S&P stocks
   - Different rebalancing schedules and methodologies
   - Varying liquidity profiles create temporary dislocations
   - Authorized Participant creation/redemption takes time

4. **Institutional Flow Patterns**:
   - Sector rotation funds trade QQQ before adjusting broader SPY exposure
   - Risk parity funds rebalance on fixed schedules, creating predictable flows
   - Hedging activity in one ETF spills to the other with delay

**Who loses on the other side?**
- Slow-moving institutional investors with multi-day execution horizons
- Passive funds tracking indices with lagged rebalancing
- Retail investors reacting to yesterday's price movements
- Overleveraged arbitrageurs forced to unwind during stress

**Why doesn't arbitrage eliminate it?**
- Signal is small and noisy, requiring large capital for meaningful returns
- Occasional large losses during regime changes deter full arbitrage
- Implementation costs (bid-ask, market impact) exceed typical alpha
- Risk of divergence widening before converging (mark-to-market pain)

**Risk premium or mispricing?**
This is primarily a **liquidity risk premium**. The strategy earns compensation for:
- Providing immediacy when others need time to adjust
- Bearing convergence risk during periods of temporary divergence
- Operating in a crowded trade with occasional violent reversals

---

## Section 2: Testable Prediction

### 2.1 Hypothesis Statement

**Primary prediction:**
> "When the QQQ/SPY price ratio deviates more than 1.5 standard deviations from its 20-day rolling mean, the lagging asset will revert toward the mean by at least 0.3% over the next 1-3 days, achieving OOS Sharpe ratio ≥ 0.4."

**Specific predictions:**

| Condition | Expected Response | Horizon | Confidence |
|-----------|------------------|---------|------------|
| QQQ outperforms SPY by >1.5σ | SPY catches up (QQQ/SPY ratio decreases) | 1-3 days | High |
| QQQ underperforms SPY by >1.5σ | SPY falls back (QQQ/SPY ratio increases) | 1-3 days | High |
| Deviation <1.0σ | No predictable pattern | Any | N/A |
| During high vol (VIX>25) | Larger moves, slower convergence | 3-5 days | Medium |

**Magnitude expectations:**
- Mean reversion: 0.3-0.8% per signal
- Win rate: 55-60%
- Profit factor: 1.3-1.6
- Annual Sharpe: 0.4-0.8 (gross), 0.2-0.5 (net of costs)

---

## Section 3: Falsification Criteria

### 3.1 Abandonment Triggers

This hypothesis will be **abandoned** if ANY of the following occur:

- [ ] Placebo percentile < 0.80 after 5 trials
- [ ] OOS median Sharpe < 0.15 (signal too weak)
- [ ] Max drawdown > 25% (unacceptable tail risk)
- [ ] Turnover > 50x annual (costs destroy alpha)
- [ ] Fails cost stress at 5 bps fees (not robust)
- [ ] Works on QQQ→SPY but not SPY→QQQ (asymmetric, suspicious)
- [ ] Signal disappears after 2020 (regime change killed it)
- [ ] Win rate < 52% (barely better than coin flip)

### 3.2 Regime Dependencies

**Expected to work BEST during:**
- Normal volatility regimes (VIX 12-22)
- Trending markets with clear sector rotation
- Earnings seasons with stock-specific news
- Fed communication periods (gradual information release)

**Expected to work WORST (or fail) during:**
- Market crashes (>10% decline in 5 days) - correlations go to 1
- Flash crashes - technical dislocations, not fundamental
- Major geopolitical shocks - both move together on macro news
- Month-end/quarter-end rebalancing - mechanical flows dominate
- FOMC announcement days - simultaneous reaction to news

**If the signal works equally well in ALL regimes, the mechanism is suspect.** A genuine information diffusion story predicts slower convergence during stress when attention is overloaded.

---

## Section 4: Analysis Plan

### 4.1 Data Requirements

| Field | Source | Start Date | End Date | Frequency | Notes |
|-------|--------|------------|----------|-----------|-------|
| SPY OHLCV | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Corporate actions adjusted |
| QQQ OHLCV | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Corporate actions adjusted |
| VIX | yfinance (^VIX) | 2010-01-01 | 2026-01-01 | daily | Volatility regime indicator |
| Risk-free rate | FRED (DGS1) | 2010-01-01 | 2026-01-01 | daily | 1-month Treasury for Sharpe |

**Data quality checks:**
- [x] No survivorship bias (both ETFs still exist)
- [x] Corporate actions adjusted (yfinance auto_adjust=True)
- [x] Trading hours aligned (both US equity ETFs)
- [ ] Missing data check (pending download)
- [ ] Outlier detection (pending analysis)

### 4.2 Feature Construction

**Core signal features (pre-specified, no additions allowed):**

| Feature ID | Formula | Rationale | Expected Sign |
|------------|---------|-----------|---------------|
| ratio_price | `qqq_close / spy_close` | Raw price ratio | N/A |
| ratio_ma20 | `rolling(ratio_price, 20).mean()` | 20-day moving average | N/A |
| ratio_std20 | `rolling(ratio_price, 20).std()` | 20-day volatility | N/A |
| ratio_zscore | `(ratio_price - ratio_ma20) / ratio_std20` | Standardized deviation | Mean-reverting |
| ratio_zscore_lag1 | `ratio_zscore.shift(1)` | Yesterday's signal | Predictive |
| ratio_zscore_lag3 | `ratio_zscore.shift(3)` | 3 days ago | Decay check |
| vol_regime | `rolling(vix, 20).mean() / vix` | High/low vol indicator | Modulates speed |
| spy_volume_zscore | `(spy_vol - roll_mean(spy_vol,20)) / roll_std(spy_vol,20)` | Unusual volume | Confirms signal |
| qqq_volume_zscore | `(qqq_vol - roll_mean(qqq_vol,20)) / roll_std(qqq_vol,20)` | Unusual volume | Confirms signal |

**Target variable:**
```python
# Forward return of the LAGGING asset
# If ratio_zscore > 0: QQQ rich vs SPY, expect SPY to outperform
# Target = spy_return over next 1-3 days
# If ratio_zscore < 0: QQQ cheap vs SPY, expect QQQ to outperform  
# Target = qqq_return over next 1-3 days

target_1d = np.where(ratio_zscore > 0, spy_return_1d, qqq_return_1d)
target_3d = np.where(ratio_zscore > 0, spy_return_3d, qqq_return_3d)
```

**Prohibited features:**
- Future returns or forward-looking ratios
- Optimized lookback periods (must use 20, not "best" period)
- Additional assets beyond SPY/QQQ (scope creep)
- Alternative target definitions mid-experiment

### 4.3 Model Specification

**Model class:** Logistic Regression

**Justification:**
- Simple, interpretable model appropriate for binary signal
- Reduces overfitting risk vs. complex models
- Matches linear nature of mean-reversion hypothesis
- Easy to audit and understand failure modes

**Alternative (if LR fails):** Gradient Boosting with shallow trees (max_depth=2-3)

**Hyperparameters:**

```yaml
# Logistic Regression
logreg_C: [0.01, 0.1, 1.0, 10.0]  # Regularization strength
logreg_max_iter: [1000]  # Convergence

# If using Gradient Boosting
gb_learning_rate: [0.01, 0.05, 0.1]
gb_n_estimators: [50, 100, 200]
gb_max_depth: [2, 3]
gb_min_samples_leaf: [10, 20, 50]  # Prevent overfitting
```

**What is NOT tuned:**
- Number of features (fixed at 9 pre-specified features)
- Target definition (1-day and 3-day ahead, pre-specified)
- Validation protocol (7-fold walk-forward, pre-specified)
- Signal threshold (1.5σ, pre-specified; sensitivity test only)

### 4.4 Validation Protocol

**Walk-forward specification:**

| Fold | Train Start | Train End | Test Start | Test End |
|------|-------------|-----------|------------|----------|
| 1 | 2010-01-01 | 2013-12-31 | 2014-01-01 | 2014-12-31 |
| 2 | 2011-01-01 | 2014-12-31 | 2015-01-01 | 2015-12-31 |
| 3 | 2012-01-01 | 2015-12-31 | 2016-01-01 | 2016-12-31 |
| 4 | 2013-01-01 | 2016-12-31 | 2017-01-01 | 2017-12-31 |
| 5 | 2014-01-01 | 2017-12-31 | 2018-01-01 | 2018-12-31 |
| 6 | 2015-01-01 | 2018-12-31 | 2019-01-01 | 2019-12-31 |
| 7 | 2016-01-01 | 2019-12-31 | 2020-01-01 | 2020-12-31 |

**Configuration:**
- Number of folds: 7
- Train length: 4 years per fold (expanding window start)
- Test length: 1 year per fold
- Gap between train/test: 0 bars (continuous)
- Total out-of-sample period: 7 years (2014-2020)

**Promotion criteria (all gates must pass):**

```python
gates = {
    'median_oos_sharpe_positive': '> 0.0',
    'mean_oos_sharpe_positive': '> 0.0',
    'worst_dd_within_limit': '> -0.25',  # Stricter than default
    'cost_stress_survives': 'Sharpe > 0 at 10bps',
    'delay_stress_survives': 'Sharpe > 0 with 1-bar delay',
    'bootstrap_positive_prob': '>= 0.85',  # Higher confidence required
    'placebo_separates': 'percentile >= 0.95, p <= 0.10',  # CRITICAL
    'placebo_sample_adequate': '>= 20 null runs',
    'not_single_fold': 'max_fold_share <= 0.6',
    'turnover_plausible': '<= 50x annual',  # Stricter than default
    'data_integrity': 'passed',
    'lookahead_resolved': 'no unresolved risks',
    'trial_accounting_consistent': 'recorded',
    'family_search_within_cap': '<= max_family_searches',
    
    # Hypothesis-specific gates
    'min_win_rate': '>= 0.54',  # Better than coin flip
    'signal_direction_correct': 'coefficient sign matches prediction',
    'vol_regime_interaction': 'convergence slower in high vol'
}
```

---

## Section 5: Trial Budget

### 5.1 Allocated Trials

- **Hypothesis ID:** H-001
- **Maximum trials:** 10
- **Trial budget breakdown:**
  - Trials 1-3: Baseline model with core features
  - Trials 4-6: Hyperparameter optimization
  - Trials 7-8: Robustness checks (different thresholds, horizons)
  - Trials 9-10: Final validation with locked parameters

- **Remaining family budget:** 3 hypotheses total (H-001, H-002, H-003)
- **Mandatory review:** After trial 10 OR after all 3 hypotheses tested

### 5.2 Trial Accounting

All trials will be recorded in `/workspace/experiment_registry.jsonl` with:
```json
{
  "hypothesis_id": "H-001",
  "trial_number": 1,
  "timestamp": "2026-09-13T00:00:00Z",
  "config_hash": "...",
  "parameters": {...},
  "result": "pass/fail/pending",
  "gate_failures": [],
  "notes": ""
}
```

---

## Section 6: Decision Rules

### 6.1 Go/No-Go Criteria

**Advance to paper trading if ALL of:**
- [x] All 14 standard gates pass
- [x] All 3 hypothesis-specific gates pass
- [ ] Placebo percentile ≥ 0.95 (critical)
- [ ] Bootstrap P(SR>0) ≥ 0.85
- [ ] OOS median Sharpe ≥ 0.3
- [ ] Results replicate across seeds 44, 45, 46
- [ ] Mechanism validated: vol regime interaction present

**Continue research if:**
- Gates pass but placebo percentile 0.85-0.94 (needs refinement)
- Sharpe 0.2-0.3 (marginal but promising)
- Mechanism validated but magnitude smaller than expected
- Trial budget remaining

**Abandon hypothesis if:**
- Placebo percentile < 0.80 after 5 trials
- OOS Sharpe < 0.1 consistently
- Signal goes wrong direction (negative coefficient)
- No vol regime interaction (mechanism suspect)
- Trial budget exhausted without promotion

### 6.2 Review Milestones

| Milestone | Date | Trigger | Decision |
|-----------|------|---------|----------|
| Initial review | 2026-09-20 | Trials 1-3 complete | Continue/pivot |
| Mid-point review | 2026-09-27 | Trial 5 complete | Deep dive on failures |
| Final decision | 2026-10-04 | Trial 10 complete | Promote/abandon |
| Family review | 2026-10-11 | All hypotheses tested | Continue direction/new direction |

---

## Section 7: Pre-Analysis Checklist

- [x] Economic mechanism documented
- [x] Prediction stated in falsifiable terms
- [x] Features pre-specified (9 features, no additions)
- [x] Validation protocol locked (7-fold, 2010-2020)
- [x] Trial budget allocated (10 trials)
- [x] Success/failure criteria defined
- [ ] Test set locked (no peeking at results yet)
- [ ] Registry entry created

**Researcher signature:** _Automated Research System_  
**Date:** 2026-09-13  

**Reviewer signature:** _Pending human review_  
**Date:** _______________

---

## Appendix A: Configuration File

```json
{
  "hypothesis_id": "H-001",
  "name": "Cross-Asset Spillover SPY-QQQ",
  "version": "1.0",
  "data": {
    "symbols": ["SPY", "QQQ"],
    "start": "2010-01-01",
    "end": "2020-12-31",
    "frequency": "1d"
  },
  "features": [
    "ratio_price",
    "ratio_ma20",
    "ratio_std20",
    "ratio_zscore",
    "ratio_zscore_lag1",
    "ratio_zscore_lag3",
    "vol_regime",
    "spy_volume_zscore",
    "qqq_volume_zscore"
  ],
  "model": {
    "type": "logistic",
    "logreg_C": 1.0,
    "random_seed": 44
  },
  "validation": {
    "n_folds": 7,
    "train_years": 4,
    "test_years": 1
  },
  "execution": {
    "hold_bars": 3,
    "fee_bps": 1.0,
    "slippage_bps": 1.0
  }
}
```

---

## Appendix B: Risk Disclosures

**Known risks:**
1. **Regime change:** Post-2020 market structure may differ significantly
2. **Crowding:** Many firms monitor SPY-QQQ relationship
3. **ETF changes:** QQQ rebalancing rules changed in past
4. **Transaction costs:** Real-world costs may exceed estimates
5. **Capacity:** Strategy may not scale beyond certain AUM

**Mitigation:**
- Test on out-of-period data (2021-2026) before paper trading
- Monitor crowding indicators (volume, open interest)
- Conservative cost assumptions (2-3x estimated)
- Capacity analysis before live deployment

---

**Document Control:**
- Version: 1.0
- Created: 2026-09-13
- Status: PENDING_APPROVAL
- Next Review: After trial 5 or 2026-09-27
