# Preregistration Template for New Strategy Research

**Template Version:** 1.0  
**Date Created:** 2026-09-13  
**Required Before:** Any code changes or experiments

---

## Section 1: Economic Mechanism

### 1.1 What market inefficiency does this exploit?

*Describe the structural, behavioral, or institutional friction that creates predictable returns.*

**Required elements:**
- Why does this pattern exist? (not just that it exists)
- Who is on the other side of the trade and why do they lose?
- Why hasn't arbitrage eliminated this opportunity?
- Is this a risk premium or a mispricing?

**Example (good):**
> "Market makers providing liquidity in ETFs face inventory risk when underlying components trade at different speeds. During periods of high volatility, they widen spreads to compensate for holding risk. This creates predictable return patterns: assets with higher inventory risk earn higher subsequent returns as compensation."

**Example (bad - reject this):**
> "RSI below 30 predicts rebounds because markets overreact." (No mechanism, just observation)

---

## Section 2: Testable Prediction

### 2.1 Specific hypothesis statement

*State the predicted relationship in falsifiable terms.*

**Format:** "When [condition], then [asset/strategy] will [direction] by [magnitude] over [horizon]."

**Required elements:**
- Clear independent variable (the signal)
- Clear dependent variable (the return)
- Predicted sign (positive/negative)
- Expected magnitude (order of magnitude)
- Time horizon (holding period)

**Example:**
> "When the SPY/QQQ price ratio deviates more than 2 standard deviations from its 20-day rolling mean, QQQ will revert toward the mean by at least 0.5% over the next 3 days, with Sharpe ratio > 0.3."

---

## Section 3: Falsification Criteria

### 3.1 What would prove this wrong?

*Define in advance what results would cause you to abandon the hypothesis.*

**Required checkpoints:**
- [ ] Placebo percentile < 0.80 (cannot separate from noise)
- [ ] OOS Sharpe < 0.2 (signal too weak)
- [ ] Max drawdown > 30% (unacceptable risk)
- [ ] Turnover > 40x annual (costs kill it)
- [ ] Fails cost stress at 5 bps (not robust to fees)
- [ ] Works on only 1 of 3+ test assets (not generalizable)
- [ ] Signal decays > 80% after 2020 (regime dependent)

### 3.2 Regime dependencies

*Under what market conditions should this NOT work?*

**Example:**
> "This momentum strategy should fail during: (1) high-volatility regimes (VIX > 30), (2) Fed announcement days, (3) market crashes (>10% in 5 days). If it works equally well in all regimes, the mechanism is suspect."

---

## Section 4: Analysis Plan

### 4.1 Data requirements

| Field | Source | Start Date | End Date | Frequency | Notes |
|-------|--------|------------|----------|-----------|-------|
| OHLCV | yfinance / exchange API | YYYY-MM-DD | YYYY-MM-DD | daily/minute | Which symbols? |
| Additional data | ... | ... | ... | ... | ... |

**Data quality checks:**
- [ ] No survivorship bias (includes delisted assets)
- [ ] Corporate actions adjusted (splits, dividends)
- [ ] Trading hours aligned across assets
- [ ] Missing data < 1% or properly handled

### 4.2 Feature construction

*List EVERY feature you will construct. No post-hoc additions allowed.*

| Feature ID | Formula | Economic rationale | Expected sign |
|------------|---------|-------------------|---------------|
| feat_01 | `(close - open) / (high - low + 1e-8)` | Intraday momentum | + |
| feat_02 | `rolling(vol, 20).mean() / vol` | Vol regime indicator | - |
| ... | ... | ... | ... |

**Prohibited:**
- Features using future data (even accidentally)
- Features optimized on the test set
- "Kitchen sink" approach (must justify each feature)

### 4.3 Model specification

**Model class:** [Logistic Regression / Gradient Boosting / Linear / Other]

**Justification:** *Why this model class matches the hypothesized relationship*

**Hyperparameters to tune:**
```yaml
param_grid:
  learning_rate: [0.01, 0.05, 0.1]
  n_estimators: [50, 100, 200]
  max_depth: [2, 3, 5]
```

**What NOT to tune:**
- Number of features (pre-specify)
- Target definition (pre-specify)
- Validation protocol (pre-specify)

### 4.4 Validation protocol

**Walk-forward specification:**
- Number of folds: [e.g., 7]
- Train length: [e.g., 3 years per fold]
- Test length: [e.g., 6 months per fold]
- Gap between train/test: [e.g., 0 bars]

**Promotion criteria (all must pass):**
```python
gates = {
    'median_oos_sharpe_positive': '> 0.0',
    'mean_oos_sharpe_positive': '> 0.0', 
    'worst_dd_within_limit': '> -0.5',
    'cost_stress_survives': 'Sharpe > 0 at 10bps',
    'delay_stress_survives': 'Sharpe > 0 with 1-bar delay',
    'bootstrap_positive_prob': '>= 0.80',
    'placebo_separates': 'percentile >= 0.95, p <= 0.10',  # CRITICAL
    'placebo_sample_adequate': '>= 20 null runs',
    'not_single_fold': 'max_fold_share <= 0.6',
    'turnover_plausible': '<= 60x annual',
    'data_integrity': 'passed',
    'lookahead_resolved': 'no unresolved risks',
    'trial_accounting_consistent': 'recorded',
    'family_search_within_cap': '<= max_family_searches'
}
```

**Additional gates for this hypothesis:**
- [Add any hypothesis-specific gates here]

---

## Section 5: Trial Budget

### 5.1 Allocated trials

- **Maximum trials for this hypothesis:** 10
- **Maximum hypotheses in this family:** 3
- **Total family budget:** 30 trials
- **Mandatory review after:** 30 trials regardless of results

### 5.2 Trial accounting

Each trial must be recorded with:
- Trial ID (sequential within family)
- Timestamp
- Parameter configuration
- Result (pass/fail/aborted)
- Reason for failure (if applicable)

**NO UNRECORDED EXPERIMENTS ALLOWED.**

---

## Section 6: Decision Rules

### 6.1 Go/No-Go criteria

**Advance to paper trading if ALL of:**
- [ ] All 14 gates pass with margin (not borderline)
- [ ] Placebo percentile ≥ 0.95
- [ ] Bootstrap P(SR>0) ≥ 0.90
- [ ] OOS Sharpe ≥ 0.5
- [ ] Results replicate across 2+ seeds
- [ ] Economic mechanism validated independently

**Continue research if ANY of:**
- [ ] Gates pass but margins thin
- [ ] Mechanism plausible but needs refinement
- [ ] Trial budget not exhausted

**Abandon hypothesis if ANY of:**
- [ ] Placebo percentile < 0.80 after 5 trials
- [ ] Cannot articulate mechanism after review
- [ ] Results contradict prediction direction
- [ ] Trial budget exhausted without promotion

### 6.2 Review milestones

| Milestone | Trigger | Action |
|-----------|---------|--------|
| Mid-point review | Trial 5/10 | Assess progress, pivot or persist |
| Budget exhaustion | Trial 10/10 | Formal go/no-go decision |
| Family review | 3 hypotheses tested | Evaluate entire research direction |
| 30-trial review | Any combination | Mandatory external review |

---

## Section 7: Pre-Analysis Checklist

Before running first experiment, confirm:

- [ ] Economic mechanism documented and reviewed
- [ ] Prediction stated in falsifiable terms
- [ ] All features pre-specified
- [ ] Validation protocol locked
- [ ] Trial budget allocated
- [ ] Success/failure criteria defined
- [ ] No access to test set results yet
- [ ] Registry entry created for this hypothesis

**Researcher signature:** ___________________  
**Date:** _______________  
**Reviewer signature:** ___________________  
**Date:** _______________

---

## Appendix: Example Completed Preregistration

*See HYPOTHESIS_CROSS_ASSET_SPILLOVER.md for a fully completed example.*

---

**Template Notes:**
- This template enforces discipline and prevents data mining
- Deviations require documented justification and reviewer approval
- Violations invalidate all subsequent results
- Keep this document immutable once experiments begin
