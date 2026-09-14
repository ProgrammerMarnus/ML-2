# Preregistration: H-003 Short-Term Volatility Risk Premium

**Current status (2026-09-14):** `BLOCKED_BEFORE_TRIAL`. The repository lacks
the VIX-futures M1–M3 curve, complete 17-ETF correlation panel, weekly
risk-parity evaluator, and crisis/diversification gates this preregistration
requires. The scalar daily-OHLCV runtime refuses proxy H-003 execution.

## 1. Economic Mechanism

**Hypothesis:** Assets experiencing elevated realized volatility relative to their historical norm command a risk premium as volatility-averse investors reduce exposure, creating return opportunities for volatility sellers.

**Theoretical Foundation:**
- Investors exhibit loss aversion and volatility aversion (prospect theory)
- High volatility periods trigger forced deleveraging and risk reduction
- This creates systematic selling pressure unrelated to fundamentals
- Risk-tolerant capital can earn premium by absorbing this flow
- Effect is mean-reverting: high vol → subsequent lower vol + positive returns

**Key Predictions:**
1. Negative relationship between current vol shock and future returns (for long vol positions)
2. Stronger effect in assets with limited arbitrage capacity
3. Premium concentrated in first 5-10 days post-vol-shock
4. Asymmetric: stronger during vol spikes than gradual increases

---

## 2. Signal Construction

### 2.1 Volatility Shock Metric (VShock)

```
RV_t = sqrt(252 * mean(r_{t-20:t}^2))           # 20-day realized vol
RV_z = (RV_t - mean(RV_{t-252:t-21})) / std(RV_{t-252:t-21})  # Z-score vs prior year
VShock_t = max(0, RV_z)                          # One-sided: only upward shocks
```

### 2.2 Primary Features (Pre-specified)

| Feature ID | Formula | Expected Sign | Rationale |
|------------|---------|---------------|-----------|
| VShock_1d | Yesterday's volatility shock | Negative | High vol shock → sell → reversal |
| VShock_5d | 5-day MA of VShock | Negative | Sustained vol → larger premium |
| Vol_mean_rev | RV_t / RV_252d_avg | Negative | Mean reversion signal |
| Vol_skew_20d | Skewness of daily returns (20d) | Positive | Negative skew → higher premium |
| Correlation_spike | Avg pairwise corr increase | Negative | Flight to quality → opportunity |
| VIX_term_slope | VIX futures M1-M3 slope | Positive | Contango → favorable for vol sellers |
| Asset_class | Equity/Bond/Currency dummy | Mixed | Different dynamics by class |

### 2.3 Composite Signal

```
Signal_t = w1·z(VShock_1d) + w2·z(VShock_5d) + w3·z(Vol_mean_rev)
         + w4·z(Vol_skew_20d) + w5·z(Correlation_spike) 
         + w6·z(VIX_term_slope)
```

**Weights:** Equal-weighted (w_i = 1/6). No optimization.

**Direction:** 
- For equities: SHORT high signal (sell volatility exposure)
- For bonds/currencies: LONG high signal (buy volatility protection)

**Note:** This is a tactical asset allocation signal, not stock selection.

---

## 3. Universe & Data

### 3.1 Investment Universe

**Asset Classes:**
1. **Equity Indices:** SPY, QQQ, IWM, EFA, EEM (5 ETFs)
2. **Fixed Income:** TLT, IEF, SHY, LQD, HYG (5 ETFs)
3. **Currencies:** UUP, FXE, FXY, FXB (4 ETFs)
4. **Commodities:** GLD, DBC, USO (3 ETFs)

**Total:** 17 liquid ETFs representing major asset classes

### 3.2 Data Requirements
- Daily OHLCV for all ETFs
- VIX futures term structure (CBOE data)
- Realized volatility calculations (20-day rolling)
- Pairwise correlation matrix (20-day rolling)

### 3.3 Sample Period
- **Validation Period:** 2008-01-01 to 2023-12-31 (includes GFC, multiple vol regimes)
- **Walk-forward folds:** 6 folds, 2 years each, 1-year gaps (to capture full cycles)

---

## 4. Validation Protocol

### 4.1 Backtest Configuration (LOCKED)

```yaml
folds: 6
fold_length_years: 2
gap_between_folds_days: 252  # 1 year to capture different regimes
rebalance_frequency: weekly  # Lower turnover than equity signals
transaction_costs_bps: 5  # ETF trading is cheap
slippage_bps: 2
min_history_days: 504  # 2 years for vol calculations
weighting: risk_parity  # Equal risk contribution
leverage: 0.5  # Conservative given tail risks
```

### 4.2 Success Criteria (All Must Pass)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| sharpe_ratio_annual | ≥ 0.8 | Lower bar due to diversification play |
| sortino_ratio | ≥ 1.2 | Downside focus critical for vol strategies |
| max_drawdown | ≤ -20% | Higher tolerance for vol strategies |
| turnover_annual | ≤ 200% | Weekly rebalance should be low |
| capacity_millions | ≥ $500 | Very high (ETF liquidity) |
| cost_stress_survives | Sharpe ≥ 0.4 at 2x costs | Robust to fee changes |
| delay_stress_survives | Sharpe ≥ 0.4 at 3-day delay | Execution flexibility |
| bootstrap_positive_prob | ≥ 80% | Statistical confidence |
| placebo_separates | Placebo percentile ≥ 0.85 | Slightly lower bar for macro |
| crisis_alpha | Positive return in top 5 vol days | Tail protection value |
| regime_consistent | Positive Sharpe in 3/4 regimes | Works across environments |
| subperiod_stable | Positive Sharpe in both halves | Not period-specific |
| transaction_cost_alpha | Net alpha after 10 bps all-in | Economically meaningful |
| correlation_diversification | Portfolio corr < 0.5 to SPY | True diversification |

### 4.3 Falsification Conditions

Hypothesis is **REJECTED** if ANY of the following occur:
1. Placebo percentile < 0.65 (macro signals noisier, but still need separation)
2. Bootstrap probability < 55%
3. Max drawdown > -35% (unacceptable even for vol strategy)
4. Negative returns during 2008 or 2020 crises (failed mandate)
5. Correlation to SPY > 0.7 (not diversifying)
6. Results flip sign in second half of sample

---

## 5. Trial Budget & Decision Rules

### 5.1 Allowed Experiments

| Trial | Purpose | Modification Allowed |
|-------|---------|---------------------|
| 1 | Baseline run | None - pure preregistered spec |
| 2 | Robustness check | Change fold structure (4 folds, 3 years each) |
| 3 | Alternative vol measure | Parkinson range-based estimator |
| 4 | Cost sensitivity | 2x and 3x transaction costs |
| 5 | Crisis period only | 2008-2009 and 2020 subsamples |
| 6 | Non-crisis only | Exclude 2008-2009, 2020 |
| 7 | Asset class analysis | Equities only vs multi-asset |
| 8 | Rebalance frequency | Daily vs weekly vs monthly |
| 9 | Leverage sensitivity | 0.25x, 0.5x, 0.75x |
| 10 | Final validation | Full spec, fresh random seed |

### 5.2 Stopping Rules

**STOP and REJECT hypothesis if:**
- Trial 1 fails > 6 gates
- Crisis alpha negative (fails core mandate)
- Max drawdown > -35% in any trial
- Placebo percentile < 0.65 in Trials 1-3 average

**STOP and PROMOTE to next phase if:**
- Trials 1 AND 10 pass ALL 14 gates
- Positive returns in both 2008 and 2020 crisis periods
- Correlation to SPY < 0.5

**CONTINUE experimenting if:**
- Trial 1 passes 9-13 gates
- Crisis alpha positive but other gates borderline
- Theoretically consistent results

### 5.3 Forbidden Actions

❌ NO parameter optimization
❌ NO asset selection based on results
❌ NO changing weights post-hoc
❌ NO excluding crisis periods to improve Sharpe
❌ NO adding features after seeing Trial 1 results
❌ NO "just one more trial" after budget exhausted

---

## 6. Risk Controls

### 6.1 Position Limits
- Max single ETF weight: 15% (at rebalance)
- Max asset class exposure: 40% gross
- Net equity exposure: -20% to +20% (market neutral bias)

### 6.2 Trading Constraints
- Rebalance only on Wednesdays (reduce timing games)
- No trading during first/last 30 minutes
- Limit order only (no market orders)
- Max daily turnover: 25% of portfolio

### 6.3 Kill Switch Triggers
- Daily P&L loss > -8%
- Drawdown from peak > -15%
- VIX > 80 (extreme stress - stand down)
- Data feed interruption > 4 hours
- Model signal missing > 2 days

### 6.4 Tail Risk Management
- Hard stop: Flatten all positions if portfolio down -20% from peak
- Volatility targeting: Scale positions to achieve 10% annualized vol
- Correlation monitoring: Reduce risk if all correlations → 1

---

## 7. Documentation Requirements

For EACH trial, must record:
1. Exact code commit hash
2. Random seed used
3. All 14 gate results with numeric values
4. Crisis period performance (2008, 2020) separately
5. Correlation to SPY over full period and rolling 1-year
6. Any errors or warnings during execution
7. Runtime and computational resources
8. Deviation from preregistration (if any, with justification)

All artifacts saved to: `artifacts/H003/trial_N/`

---

## 8. Timeline

| Milestone | Target Date | Status |
|-----------|-------------|--------|
| Preregistration complete | Week 1 | ✅ Done |
| Trial 1 execution | Unscheduled | Blocked on exact data contract |
| Trials 2-5 | Unscheduled | Blocked; no valid Trial 1 |
| Trials 6-10 | Unscheduled | Blocked; no valid Trial 1 |
| Go/No-Go decision | After valid evidence | Not reached |

---

## 9. Approval & Attestation

**Researcher:** AI Research Assistant  
**Date:** 2026-09-11  
**Commitment:** I will execute this research plan exactly as specified, without modification based on interim results. Any deviations will be documented and justified. Violations of this protocol invalidate all findings.

**Status:** PREREGISTERED BUT BLOCKED — not ready for Trial 1

---

## Appendix A: Comparison to H-001 and H-002

| Aspect | H-001 (Cross-Asset Spillover) | H-002 (Liquidity Reversal) | H-003 (Vol Risk Premium) |
|--------|-------------------------------|----------------------------|--------------------------|
| Mechanism | Information diffusion | Liquidity provision | Volatility risk bearing |
| Horizon | Intraday to 2 days | 1-5 days | 5-20 days |
| Universe | Large-cap ETFs (2-5) | Small/mid stocks (500+) | Multi-asset ETFs (17) |
| Turnover | Very high (daily+) | Moderate (daily) | Low (weekly) |
| Capacity | $10-50M | $50-200M | $500M+ |
| Data needs | Minute ETF prices | Daily + intraday volume | Daily prices, VIX futures |
| Complexity | Low | Medium | Medium-High |
| Crisis alpha | Unknown | Unknown | Core feature |
| Diversification | Equity only | Equity only | Multi-asset |
| Complementarity | Orthogonal | Orthogonal | Orthogonal to both |

**Original portfolio rationale:** The designs targeted orthogonal exposures:
- Different mechanisms (information, liquidity, volatility)
- Different horizons (intraday, days, weeks)
- Different universes (ETFs, stocks, multi-asset)
- Different turnover profiles

No current portfolio benefit may be claimed: H-001 is rejected and H-002/
H-003 have no valid trial evidence. Any diversification claim requires new,
untouched results under their exact contracts.

---

## Appendix B: Relationship to Existing Literature

This hypothesis connects to several well-documented phenomena:

1. **Volatility Risk Premium (VRP):** Documented in index options markets (short straddles earn positive returns)

2. **Low Volatility Anomaly:** Haugen & Heins (1975), Baker et al. (2011) - low vol stocks outperform

3. **Volatility Mean Reversion:** Potentially exploitable for tactical allocation

4. **Flight-to-Quality:** During stress, correlations converge, creating opportunities

5. **VIX Term Structure:** Contango in VIX futures creates headwind for long vol, tailwind for short vol

**Novel Contribution:** Combining these effects into a systematic multi-asset tactical allocation framework with strict preregistration and validation.
