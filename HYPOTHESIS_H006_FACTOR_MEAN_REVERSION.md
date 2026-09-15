# Preregistration: H-006 Factor Exposure Mean Reversion

**Family:** H-006 (new hypothesis family)  
**Frozen before evaluation data retrieval:** 2026-09-15  
**Status:** PENDING EXECUTION

## Economic mechanism

Factor exposures exhibit mean-reverting behavior over short-to-medium horizons due to:
1. **Crowding unwinds**: When factor trades become overcrowded, subsequent rebalancing or deleveraging causes temporary price distortions that revert
2. **Style rotation**: Institutional flows rotate between value/growth, large/small, and other style factors, creating predictable reversals
3. **Risk parity adjustments**: Volatility-targeting portfolios mechanically rebalance away from outperforming factors, inducing mean reversion

This hypothesis tests whether extreme factor exposure deviations from rolling norms predict opposite-signed returns over the following week.

## Immutable data contract

- Evaluation window: 2010-01-01 through 2023-12-30 inclusive (`end` is the exclusive 2023-12-31 boundary).
- Investable universe: SPY, QQQ, IWM, DIA, EFA, EEM, VEA, VWO, TLT, IEF, SHY, LQD, HYG, GLD, DBC, USO, VNQ (17 ETFs spanning equity style, geography, fixed income, commodities, and real estate).
- Provider/basis: yfinance daily `auto_adjust=True` OHLCV. No forward filling of input market data is permitted.
- Calendar: XNYS. All 17 investables must be present or execution fails.
- Risk-free proxy: SHY close (used only for excess return calculation; not as a trading signal input).

## Immutable signal contract

For every investable ETF, using data available through close `t`:

### Primary signals (all required):

1. **`h006_beta_zscore`**: Rolling 60-session beta to SPY (for equity ETFs) or to aggregate bond index (LQD for credit, GLD for commodities) z-scored over trailing 252 sessions. Expected-return sign: negative (extreme positive beta predicts underperformance, extreme negative beta predicts outperformance).

2. **`h006_momentum_deviation`**: 20-session return minus 252-session rolling median return, cross-sectionally z-scored across the universe. Expected-return sign: negative (recent outperformance relative to norm predicts reversal).

3. **`h006_volatility_percentile`**: Current 20-session realized volatility ranked within trailing 252-session distribution (0-1 scale), then transformed to z-score. Expected-return sign: negative (high volatility percentile predicts mean reversion).

4. **`h006_correlation_extreme`**: Rolling 60-session correlation to SPY minus 252-session rolling mean correlation, cross-sectionally standardized. Expected-return sign: negative (extreme correlation deviations revert).

5. **`h006_drawdown_recovery`**: Current drawdown from 252-session high divided by 252-session realized volatility (z-score of drawdown depth). Expected-return sign: positive (deep drawdowns predict recovery).

### Signal processing:

- Each term is cross-sectionally z-scored across all 17 ETFs at each rebalance date.
- All five signed terms must be present; the composite is their unweighted equal-weight mean.
- Signal magnitude determines position size (capped); sign determines long/short direction.
- Minimum 12 complete signals required; otherwise stand down to cash.

## Immutable portfolio and execution contract

- **Rebalance frequency**: Weekly, every Wednesday close. If Wednesday is not an observed session, hold the prior book until the next Wednesday; do not substitute another day.
- **Execution/return attribution**: Begins one session after the decision close.
- **Position sizing**: Signed composite signal scaled by inverse 60-session volatility, targeting 8% annualized volatility per position before portfolio constraints.
- **Gross leverage cap**: 1.0 (100% gross exposure maximum).
- **Net exposure cap**: ±40% (net long or short equity/factor exposure).
- **Single-asset weight cap**: ±12% per ETF.
- **Asset-class gross caps**: 
  - US Equity (SPY, QQQ, IWM, DIA, VNQ): 50%
  - International Equity (EFA, EEM, VEA, VWO): 30%
  - Fixed Income (TLT, IEF, SHY, LQD, HYG): 40%
  - Commodities (GLD, DBC, USO): 20%
- **Turnover constraint**: If predicted one-way turnover exceeds 8x annualized, scale all signals by 0.7.
- **Volatility target**: Scale portfolio to 10% predicted annualized volatility; never scale up above gross cap.
- **Stand-down conditions**:
  - VIX spot > 75: reduce gross leverage to 0.3
  - Fewer than 12 valid signals: stand down to cash
  - Any ETF missing > 5 sessions in prior 20 sessions: exclude from universe
- **Costs**: 5 bps fees plus 3 bps slippage per unit of one-sided turnover (total 8 bps round-trip assumption).

## Walk-forward and statistical contract

- **Initial training history**: 504 sessions (~2 years)
- **Validation span**: 126 sessions (~6 months) for any parameter sensitivity checks (not used for threshold optimization since this is an unoptimized signal combination)
- **Purge**: 5 sessions between validation and test
- **Embargo**: 5 sessions before each OOS test
- **OOS test size**: 504 sessions (~2 years)
- **Step size**: 504 sessions (non-overlapping folds)
- **Expected folds**: Six 2-year OOS folds (2010-2011, 2012-2013, 2014-2015, 2016-2017, 2018-2019, 2020-2021, 2022-2023)

The strategy has no fitted model parameters or threshold search. Train/validation spans establish chronological information boundaries only. All signal parameters are fixed ex-ante.

## Success criteria (ROBUST_OOS gates)

All gates must pass on untouched OOS evidence:

### Critical gates (must all pass):
- [ ] `median_oos_sharpe_positive`: Median OOS fold net Sharpe > 0
- [ ] `mean_oos_sharpe_positive`: Mean OOS fold net Sharpe > 0
- [ ] `oos_drawdown_within_limit`: Max OOS drawdown > -20%
- [ ] `oos_turnover_within_limit`: Annual turnover < 12x
- [ ] `cost_stress_survives`: Net Sharpe remains positive under 10 bps fees + 5 bps slippage
- [ ] `delay_stress_survives`: Net Sharpe > 0.5 with 1-day execution delay
- [ ] `slippage_stress_survives`: Net Sharpe > 0.5 with 2x assumed slippage
- [ ] `parameter_robustness`: Net Sharpe > 0.5 under ±20% parameter perturbation
- [ ] `missing_data_robustness`: Net Sharpe > 0.5 with 5% random data gaps
- [ ] `bootstrap_positive_prob`: ≥80% bootstrap probability that Sharpe > 0
- [ ] `placebo_separates`: Strategy ranks ≥0.95 percentile vs 100 noise placebos
- [ ] `not_single_fold`: No single OOS fold contributes >50% of total OOS Sharpe
- [ ] `capacity_sufficient`: Capacity estimate ≥ $50M (10x target $5M AUM)
- [ ] `family_search_within_cap`: Total trials ≤ 10 (within trial budget)

### Target metrics (aspirational):
- [ ] Net Sharpe ≥ 1.2 (OOS, untouched evidence)
- [ ] Max Drawdown ≤ -12%
- [ ] Annual Turnover ≤ 5x
- [ ] Capacity ≥ $100M

## Deviations from prior hypotheses

H-006 differs from H-001/H-002-R1/H-003-R1 in the following ways:

1. **Signal focus**: Unlike H-001 (cross-asset spillover timing), H-002-R1 (liquidity reversals), or H-003-R1 (volatility shocks), H-006 targets factor exposure mean reversion across a multi-asset ETF universe.

2. **Universe construction**: Uses 17 ETFs explicitly chosen to span orthogonal factor exposures (style, geography, asset class) rather than SPY/QQQ only (H-001) or liquidity-focused small-caps (H-002-R1) or vol-targeting assets (H-003-R1).

3. **Sizing methodology**: Uses signal-magnitude-dependent sizing (capped) rather than pure sign-based positioning (H-003-R1) or threshold-gated binary signals (H-002-R1).

4. **No machine learning**: Purely rules-based signal combination without any ML fitting, distinguishing it from any prior hypothesis that used gradient boosting or other estimators.

## Trial plan

- **Trial 1**: Execute on full 2010-2023 window with base parameters as specified above.
- **Trials 2-10** (contingent on Trial 1 success): Parameter sensitivity analysis varying:
  - Lookback windows (40/60/80 for beta, 15/20/25 for momentum)
  - Volatility targeting levels (6%/8%/10%)
  - Gross leverage caps (0.8/1.0/1.2)
  
If Trial 1 fails to meet ROBUST_OOS criteria, the trial budget is retired and H-006 is rejected. Evidence from H-006 is evidence for H-006 only; it does not rehabilitate any prior rejected hypothesis.

## Implementation checklist

Before Trial 1 execution:
- [ ] Feature module `factor_mean_reversion.py` created with all 5 signals
- [ ] All features registered in central registry
- [ ] Configuration file `h006_factor_mean_reversion.yaml` created
- [ ] Unit tests for feature calculations
- [ ] Integration test for full pipeline
- [ ] Preregistration document locked (this file)

---

**Preregistration lock statement**: This document defines the complete H-006 hypothesis family. Any deviation in data, signals, portfolio construction, or evaluation protocol creates a new family (H-006-R1, etc.) and does not constitute evidence for H-006. This preregistration was frozen before any evaluation data was retrieved or analyzed.

**Freeze timestamp**: 2026-09-15T00:00:00Z  
**Next action**: Implement feature module and execute Trial 1
