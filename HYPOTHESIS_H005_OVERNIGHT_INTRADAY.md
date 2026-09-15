# Hypothesis H-005: Overnight-Intraday Return Decomposition

**Hypothesis ID:** H-005  
**Research Family:** overnight_intraday_v1  
**Date Preregistered:** 2026-09-15  
**Status:** `PREREGISTERED` — awaiting execution  

---

## Section 1: Economic Mechanism

### 1.1 Market Inefficiency: Overnight Risk Premium and Intraday Mean Reversion

**Mechanism:** Equity returns decompose into overnight (close-to-open) and intraday (open-to-close) components with systematically different properties:

1. **Overnight Risk Premium**: 
   - Most long-term equity compensation accrues during overnight hours
   - Investors demand compensation for bearing unhedgeable overnight risk (earnings, macro news, geopolitical events)
   - Institutional investors cannot rebalance during market close, creating persistent exposure
   - Retail investors underweight overnight risk due to salience bias

2. **Intraday Mean Reversion**:
   - Intraday returns exhibit negative autocorrelation due to:
     - Liquidity provision by market makers
     - Overreaction to opening auction information
     - Intraday profit-taking by swing traders
     - Algorithmic mean-reversion strategies crowding the same signals
   - Opening prices overreact to overnight news, then revert during continuous trading

3. **Structural Frictions**:
   - ETF creation/redemption only at close, not open
   - Margin requirements differ for overnight vs intraday positions
   - Short-sale restrictions bind more tightly overnight
   - Information asymmetry between institutional and retail participants

**Who loses on the other side?**
- Retail investors holding through night without compensation awareness
- Overleveraged day traders forced to flatten before close
- Institutions with rigid intraday rebalancing mandates
- Market makers providing liquidity at open after large gaps

**Why doesn't arbitrage eliminate it?**
- Overnight exposure requires full capital commitment with no ability to exit
- Intraday mean reversion has high turnover, eroding profits via costs
- Regulatory constraints (pattern day trader rules, margin requirements)
- Capacity limits: overnight signal requires broad diversification to manage idiosyncratic gap risk

**Risk premium or mispricing?**
This is primarily a **risk premium** for overnight exposure and a **liquidity premium** for intraday mean reversion provision. The strategy earns compensation for:
- Bearing uncompensated overnight tail risk
- Providing immediacy during volatile opening auctions
- Operating high-turnover intraday strategies with significant transaction costs

---

## Section 2: Testable Prediction

### 2.1 Hypothesis Statement

**Primary prediction:**
> "A portfolio that goes long assets with high recent overnight return persistence and short assets with low/negative overnight persistence, combined with an intraday mean-reversion overlay, will achieve OOS Sharpe ratio ≥ 1.0 net of costs."

**Specific predictions:**

| Condition | Expected Response | Horizon | Confidence |
|-----------|------------------|---------|------------|
| High overnight momentum (top quintile) | Continue positive overnight drift | Next 1-5 sessions | High |
| Low overnight momentum (bottom quintile) | Continue weak/negative overnight | Next 1-5 sessions | High |
| Large intraday move (>2σ) | Mean revert next session intraday | 1 session | Medium |
| Overnight gap > 3% | Partial intraday fill/reversal | Same session | Medium |
| High VIX regime | Stronger overnight premium, weaker intraday reversal | 1-5 sessions | Medium |

**Magnitude expectations:**
- Overnight component: 60-70% of total return, Sharpe 0.6-0.9
- Intraday component: Negative Sharpe (-0.2 to -0.4) if held long-only
- Combined strategy (long overnight, short intraday): Net Sharpe 1.0-1.5
- Win rate: 58-62%
- Annual turnover: 12-24x (intraday overlay increases churn)

---

## Section 3: Falsification Criteria

### 3.1 Abandonment Triggers

This hypothesis will be **abandoned** if ANY of the following occur:

- [ ] Placebo percentile < 0.85 after 5 trials
- [ ] OOS median Sharpe < 0.5 (signal too weak after costs)
- [ ] Max drawdown > 20% (unacceptable tail risk)
- [ ] Turnover > 36x annual (costs destroy alpha)
- [ ] Fails cost stress at 8 bps fees (not robust to realistic costs)
- [ ] Overnight component Sharpe < 0.3 (no risk premium)
- [ ] Intraday component not mean-reverting (mechanism broken)
- [ ] Signal works only pre-2015 (regime change killed it)
- [ ] Bootstrap P(SR>0) < 0.75 (insufficient confidence)

### 3.2 Regime Dependencies

**Expected to work BEST during:**
- Moderate volatility regimes (VIX 15-25)
- Earnings seasons with frequent overnight gaps
- Periods with clear macro dispersion (Fed uncertainty, economic data)
- Normal market functioning (no sustained halts or circuit breakers)

**Expected to work WORST (or fail) during:**
- Market crashes — overnight gaps become directional, not mean-reverting
- Low volatility complacency (VIX < 12) — insufficient overnight compensation
- Flash crash periods — technical dislocations dominate fundamentals
- Extended bull markets — overnight premium compresses as risk perception falls
- Trading halts/suspensions — inability to exit intraday positions

**If the signal works equally in ALL regimes, the mechanism is suspect.** A genuine overnight-risk story predicts stronger premiums during elevated uncertainty.

---

## Section 4: Analysis Plan

### 4.1 Data Requirements

| Field | Source | Start Date | End Date | Frequency | Notes |
|-------|--------|------------|----------|-----------|-------|
| SPY OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Open required for overnight/intraday split |
| QQQ OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Open required |
| IWM OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Small-cap exposure |
| EFA OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Developed ex-US |
| EEM OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Emerging markets |
| TLT OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Long-duration treasuries |
| GLD OHLC | yfinance (adjusted) | 2010-01-01 | 2026-01-01 | daily | Gold |
| VIX | yfinance (^VIX) | 2010-01-01 | 2026-01-01 | daily | Volatility regime |
| Risk-free rate | FRED (DGS1) | 2010-01-01 | 2026-01-01 | daily | For Sharpe calculation |

**Critical requirement:** Must have OPEN prices, not just OHLCV. Many datasets omit opens; yfinance provides adjusted opens.

**Data quality checks:**
- [ ] No survivorship bias (all ETFs still exist)
- [ ] Corporate actions adjusted (yfinance auto_adjust=True)
- [ ] Trading hours aligned (all US-listed ETFs)
- [ ] Open price present and non-zero
- [ ] Overnight return computable: (Open_t - Close_{t-1}) / Close_{t-1}
- [ ] Intraday return computable: (Close_t - Open_t) / Open_t

### 4.2 Feature Construction

**Core signal features (pre-specified, no additions allowed):**

| Feature ID | Formula | Rationale | Expected Sign |
|------------|---------|-----------|---------------|
| overnight_ret_1d | `(open_t - close_{t-1}) / close_{t-1}` | Single-day overnight return | Persistent |
| overnight_ret_5d | `rolling(overnight_ret_1d, 5).mean()` | 5-day overnight momentum | Predictive |
| overnight_ret_20d | `rolling(overnight_ret_1d, 20).mean()` | 20-day overnight trend | Predictive |
| intraday_ret_1d | `(close_t - open_t) / open_t` | Single-day intraday return | Mean-reverting |
| intraday_ret_5d | `rolling(intraday_ret_1d, 5).mean()` | 5-day intraday momentum | Mean-reverting |
| overnight_momentum_rank | Cross-sectional rank of overnight_ret_20d | Relative overnight strength | Long top, short bottom |
| overnight_vol_ratio | `std(overnight_ret, 20) / std(total_ret, 20)` | Fraction of vol from overnight | Modulates position size |
| gap_size | `abs(overnight_ret_1d)` | Magnitude of overnight gap | Larger gaps → more intraday reversal |
| vix_regime | `rolling(vix, 20).mean()` | Volatility environment | Higher VIX → stronger overnight premium |
| overnight_skew | `rolling(overnight_ret, 60).skew()` | Asymmetry of overnight moves | Negative skew → higher premium demanded |

**Target variables:**

```python
# Overnight target: next N days' overnight returns
target_overnight_1d = overnight_ret_1d.shift(-1)  # Next session's overnight
target_overnight_5d = rolling(overnight_ret_1d.shift(-1), 5).sum()

# Intraday target: next session's intraday return (expected negative autocorrelation)
target_intraday_1d = intraday_ret_1d.shift(-1)

# Combined target: long overnight, short intraday
# Position: +1 * sign(overnight_signal) for overnight, -0.5 * sign(intraday_signal) for intraday
target_combined = target_overnight_1d - 0.5 * target_intraday_1d
```

**Prohibited features:**
- Future returns or forward-looking ratios
- Optimized lookback periods (must use 5, 20, 60 as specified)
- Additional assets beyond the 7 ETFs listed
- Alternative target definitions mid-experiment
- Using close-to-close returns without decomposition

### 4.3 Model Specification

**Model class:** Linear Regression with Elastic Net regularization

**Justification:**
- Continuous target variable (return magnitude matters)
- Multiple correlated features require regularization
- Interpretable coefficients to validate mechanism
- Prevents overfitting with limited time series observations

**Alternative (if linear fails):** Gradient Boosting with shallow trees (max_depth=2-3)

**Hyperparameters:**

```yaml
# Elastic Net
enet_alpha: [0.001, 0.01, 0.1, 1.0]  # Regularization strength
enet_l1_ratio: [0.1, 0.5, 0.9]  # Elastic net mixing parameter
enet_max_iter: [1000]  # Convergence

# If using Gradient Boosting
gb_learning_rate: [0.01, 0.05, 0.1]
gb_n_estimators: [50, 100, 200]
gb_max_depth: [2, 3]
gb_min_samples_leaf: [20, 50, 100]  # Prevent overfitting
```

**What is NOT tuned:**
- Number of features (fixed at 10 pre-specified features)
- Target definition (overnight, intraday, combined as specified)
- Validation protocol (7-fold walk-forward, pre-specified)
- Asset universe (fixed at 7 ETFs)

### 4.4 Validation Protocol

**Walk-forward specification:**

| Fold | Train Start | Train End | Test Start | Test End |
|------|-------------|-----------|------------|----------|
| 1 | 2010-01-01 | 2014-12-31 | 2015-01-01 | 2015-12-31 |
| 2 | 2011-01-01 | 2015-12-31 | 2016-01-01 | 2016-12-31 |
| 3 | 2012-01-01 | 2016-12-31 | 2017-01-01 | 2017-12-31 |
| 4 | 2013-01-01 | 2017-12-31 | 2018-01-01 | 2018-12-31 |
| 5 | 2014-01-01 | 2018-12-31 | 2019-01-01 | 2019-12-31 |
| 6 | 2015-01-01 | 2019-12-31 | 2020-01-01 | 2020-12-31 |
| 7 | 2016-01-01 | 2020-12-31 | 2021-01-01 | 2021-12-31 |

**Configuration:**
- Number of folds: 7
- Train length: 5 years per fold (expanding window start)
- Test length: 1 year per fold
- Gap between train/test: 0 bars (continuous)
- Total out-of-sample period: 7 years (2015-2021)
- Independent confirmation period: 2022-2026 (held back for final validation)

**Promotion criteria (all gates must pass):**

```python
gates = {
    'median_oos_sharpe_positive': '> 0.0',
    'mean_oos_sharpe_positive': '> 0.0',
    'oos_drawdown_within_limit': '> -0.20',
    'oos_turnover_within_limit': '< 36x annual',
    'cost_stress_survives': 'Sharpe > 0.5 at 8bps fees + 3bps slippage',
    'delay_stress_survives': 'Sharpe > 0 with 1-bar delay',
    'slippage_stress_survives': 'Sharpe > 0 at 2x slippage',
    'parameter_robustness': 'perturbation stable',
    'missing_data_robustness': 'gap tolerance',
    'bootstrap_positive_prob': '>= 0.80',
    'placebo_separates': 'percentile >= 0.85, p <= 0.15',
    'not_single_fold': 'max_fold_share <= 0.6',
    'capacity_sufficient': '> $50M minimum',
    'family_search_within_cap': '<= max_family_searches',
    
    # Hypothesis-specific gates
    'overnight_component_positive': 'standalone overnight Sharpe >= 0.3',
    'intraday_mean_reverting': 'intraday autocorr < 0',
    'vol_regime_interaction': 'overnight premium stronger when VIX > 20',
    'min_win_rate': '>= 0.55',
    'both_components_contribute': 'combined > either alone'
}
```

---

## Section 5: Trial Budget

### 5.1 Allocated Trials

- **Hypothesis ID:** H-005
- **Maximum trials:** 10
- **Trial budget breakdown:**
  - Trials 1-3: Baseline model with core features (overnight + intraday decomposition)
  - Trials 4-6: Hyperparameter optimization and model selection
  - Trials 7-8: Robustness checks (different horizons, regime filters)
  - Trials 9-10: Final validation with locked parameters

- **Remaining family budget:** This is hypothesis 5 of the research program
- **Mandatory review:** After trial 10 OR after achieving ROBUST_OOS status

### 5.2 Trial Accounting

All trials will be recorded in the project artifact registry with:
```json
{
  "hypothesis_id": "H-005",
  "trial_number": 1,
  "timestamp": "2026-09-15T00:00:00Z",
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
- [ ] All 14 standard gates pass
- [ ] All 5 hypothesis-specific gates pass
- [ ] Placebo percentile ≥ 0.85
- [ ] Bootstrap P(SR>0) ≥ 0.80
- [ ] OOS median Sharpe ≥ 0.8
- [ ] Results replicate across seeds 44, 45, 46
- [ ] Mechanism validated: overnight premium and intraday mean reversion both present
- [ ] Cost stress passes at realistic assumptions (8bps + 3bps)

**Continue research if:**
- Gates pass but placebo percentile 0.75-0.84 (needs refinement)
- Sharpe 0.5-0.8 (marginal but promising)
- Mechanism validated but magnitude smaller than expected
- Trial budget remaining

**Abandon hypothesis if:**
- Placebo percentile < 0.75 after 5 trials
- OOS Sharpe < 0.3 consistently
- Overnight component shows no persistence (mechanism broken)
- Intraday returns not mean-reverting (contradicts theory)
- Trial budget exhausted without promotion

### 6.2 Review Milestones

| Milestone | Date | Trigger | Decision |
|-----------|------|---------|----------|
| Initial review | 2026-09-22 | Trials 1-3 complete | Continue/pivot |
| Mid-point review | 2026-09-29 | Trial 5 complete | Deep dive on failures |
| Final decision | 2026-10-06 | Trial 10 complete | Promote/abandon |
| Family review | TBD | Multiple hypotheses tested | Continue direction/new direction |

---

## Section 7: Pre-Analysis Checklist

- [x] Economic mechanism documented
- [x] Prediction stated in falsifiable terms
- [x] Features pre-specified (10 features, no additions)
- [x] Validation protocol locked (7-fold, 2015-2021 OOS)
- [x] Trial budget allocated (10 trials)
- [x] Success/failure criteria defined
- [ ] Test set locked (no peeking at results yet)
- [ ] Registry entry created
- [ ] Feature module implemented and registered

**Researcher signature:** _Automated Research System_  
**Date:** 2026-09-15  

**Reviewer signature:** _Pending preregistration review_  
**Decision date:** _Awaiting initial trial_

---

## Appendix A: Configuration File

```json
{
  "hypothesis_id": "H-005",
  "name": "Overnight-Intraday Return Decomposition",
  "version": "1.0",
  "data": {
    "symbols": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
    "start": "2010-01-01",
    "end": "2021-12-31",
    "frequency": "1d",
    "required_fields": ["open", "high", "low", "close", "volume"]
  },
  "features": [
    "overnight_ret_1d",
    "overnight_ret_5d",
    "overnight_ret_20d",
    "intraday_ret_1d",
    "intraday_ret_5d",
    "overnight_momentum_rank",
    "overnight_vol_ratio",
    "gap_size",
    "vix_regime",
    "overnight_skew"
  ],
  "model": {
    "type": "elastic_net",
    "enet_alpha": 0.01,
    "enet_l1_ratio": 0.5,
    "random_seed": 44
  },
  "validation": {
    "n_folds": 7,
    "train_years": 5,
    "test_years": 1
  },
  "execution": {
    "hold_bars": 1,
    "fee_bps": 8.0,
    "slippage_bps": 3.0,
    "rebalance_time": "close"
  }
}
```

---

## Appendix B: Risk Disclosures

**Known risks:**
1. **Regime change:** Post-2020 market structure may alter overnight/intraday dynamics
2. **Crowding:** Overnight momentum is well-documented in academic literature
3. **Transaction costs:** High turnover from intraday overlay may exceed estimates
4. **Capacity:** Strategy scales with AUM but intraday component has limits
5. **Gap risk:** Overnight positions exposed to unanticipated news with no exit
6. **ETF-specific issues:** Different ETFs have different trading hours, liquidity profiles

**Mitigation:**
- Test on out-of-period data (2022-2026) before paper trading
- Conservative cost assumptions (2-3x estimated)
- Capacity analysis before live deployment
- Diversification across 7 uncorrelated ETFs reduces idiosyncratic gap risk
- Volatility scaling reduces exposure during stressed regimes

**Academic precedent:**
- Barclay, Henderliter, and Smith (2020): "The Overnight Anomaly"
- Bogousslavsky (2016): "Different Information for Different Horizons"
- Lou, Polk, and Skouras (2011): "A Tug of War: Overnight vs Intraday Competition"

These papers document the phenomenon but do not provide tradable protocols. This hypothesis specifies an exact, testable implementation.

---

**Document Control:**
- Version: 1.0
- Created: 2026-09-15
- Status: PREREGISTERED
- Next Review: After trial 1 or 2026-09-22
