# Preregistration: H-002 Liquidity-Driven Reversal

**Current status (2026-09-14):** `BLOCKED_BEFORE_TRIAL`. The repository lacks
the point-in-time Russell 3000, market-cap, classified intraday trade, VIX,
cross-sectional dollar-neutral portfolio, sector, and capacity contracts this
preregistration requires. Existing synthetic single-target runs are invalid
proxy diagnostics. The runtime refuses them as H-002 evidence.

## 1. Economic Mechanism

**Hypothesis:** Short-term liquidity imbalances create temporary price pressure that reverses within 1-3 days as liquidity providers step in.

**Theoretical Foundation:**
- Market makers and liquidity providers face inventory constraints
- Large trades cause temporary price impact beyond fundamental value
- Reversal occurs as: (a) informed trading completes, (b) liquidity providers rebalance, (c) arbitrageurs exploit mispricing
- Effect strongest in small/mid-cap stocks with lower baseline liquidity

**Key Predictions:**
1. Reversal magnitude increases with trade size relative to ADV
2. Reversal speed decreases with stock liquidity
3. Effect concentrated in first 1-3 days post-imbalance
4. Stronger during high volatility periods (risk premium component)

---

## 2. Signal Construction

### 2.1 Liquidity Imbalance Metric (LIM)

```
LIM_{i,t} = (BuyVol_{i,t} - SellVol_{i,t}) / TotalVol_{i,t}
```

Where:
- BuyVol = volume from trades at or above midpoint
- SellVol = volume from trades below midpoint
- Normalized by total volume to control for activity level

### 2.2 Primary Features (Pre-specified)

| Feature ID | Formula | Expected Sign | Rationale |
|------------|---------|---------------|-----------|
| LIM_1d | LIM from previous day | Negative | High buying → reversal down |
| LIM_5d | 5-day rolling mean LIM | Negative | Sustained imbalance → stronger reversal |
| LIM_std_20d | 20-day std of LIM | Positive | High variability → more opportunity |
| Volume_ratio | Today's vol / 20-day avg vol | Positive | Unusual volume → larger imbalance |
| Amihud_illiq | |Return| / DollarVol (20-day avg) | Positive | Illiquid stocks → larger reversals |
| Size_decile | Log market cap decile | Negative | Small caps → larger effect |
| Vol_regime | VIX 20-day MA vs 1-year median | Positive | High vol → larger risk premium |

### 2.3 Composite Signal

```
Signal_i,t = w1·z(LIM_1d) + w2·z(LIM_5d) + w3·z(LIM_std_20d) 
           + w4·z(Volume_ratio) + w5·z(Amihud_illiq) 
           + w6·z(Size_decile) + w7·z(Vol_regime)
```

Where z() denotes cross-sectional z-score normalization.

**Weights:** Equal-weighted initially (w_i = 1/7). No optimization allowed.

**Direction:** Short high signal stocks, long low signal stocks (negative relationship expected).

---

## 3. Universe & Data

### 3.1 Investment Universe
- **Coverage:** Russell 3000 constituents
- **Exclusions:** 
  - Stocks < $100M market cap
  - Stocks < $1M daily ADV
  - REITs, MLPs, closed-end funds
  - Stocks with < 252 trading days history
- **Rebalancing:** Monthly constituency updates

### 3.2 Data Requirements
- Daily OHLCV data (adjusted for splits/dividends)
- Intraday trade data for buy/sell classification (or use Lee-Ready algorithm on daily)
- Market cap data from CRSP/Compustat equivalent
- VIX index for volatility regime

### 3.3 Sample Period
- **Training/Development:** NOT ALLOWED
- **Validation Period:** 2010-01-01 to 2023-12-31
- **Walk-forward folds:** 7 folds, 2 years each, 6-month gaps

---

## 4. Validation Protocol

### 4.1 Backtest Configuration (LOCKED)

```yaml
folds: 7
fold_length_years: 2
gap_between_folds_days: 126  # ~6 months
rebalance_frequency: daily
transaction_costs_bps: 15  # conservative for small caps
slippage_bps: 5
min_history_days: 252
weighting: equal_weight_long_short
leverage: 1.0  # dollar neutral
```

### 4.2 Success Criteria (All Must Pass)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| sharpe_ratio_annual | ≥ 1.0 | Minimum viable return/risk |
| sortino_ratio | ≥ 1.3 | Downside protection |
| max_drawdown | ≤ -15% | Capital preservation |
| turnover_annual | ≤ 600% | Implementation feasible |
| capacity_millions | ≥ $50 | Meaningful scale |
| cost_stress_survives | Sharpe ≥ 0.5 at 2x costs | Robust to fee changes |
| delay_stress_survives | Sharpe ≥ 0.5 at 2-day delay | Execution latency tolerance |
| bootstrap_positive_prob | ≥ 85% | Statistical confidence |
| placebo_separates | Placebo percentile ≥ 0.90 | Not noise |
| monotonic_decay | IC decay over 5 days | Mechanism validation |
| sector_neutral | Sector exposure < 5% | Pure alpha, not beta |
| regime_consistent | Positive Sharpe in 4/5 regimes | Robust across environments |
| subperiod_stable | Positive Sharpe in both halves | Not period-specific |
| transaction_cost_alpha | Net alpha after 20 bps all-in | Economically meaningful |

### 4.3 Falsification Conditions

Hypothesis is **REJECTED** if ANY of the following occur:
1. Placebo percentile < 0.70 (inseparable from noise)
2. Bootstrap probability < 60% (likely zero true alpha)
3. Max drawdown > -25% (unacceptable risk)
4. Cost stress fails completely (Sharpe < 0 at 2x costs)
5. Monotonic decay not observed (wrong mechanism)
6. Results flip sign in second half of sample (data mining)

---

## 5. Trial Budget & Decision Rules

### 5.1 Allowed Experiments

| Trial | Purpose | Modification Allowed |
|-------|---------|---------------------|
| 1 | Baseline run | None - pure preregistered spec |
| 2 | Robustness check 1 | Change fold structure only |
| 3 | Robustness check 2 | Alternative liquidity measure |
| 4 | Sensitivity analysis | Cost assumptions ±50% |
| 5 | Subsample test | First half only |
| 6 | Subsample test | Second half only |
| 7 | Sector analysis | Sector-neutral constraint test |
| 8 | Regime analysis | High vs low VIX periods |
| 9 | Turnover analysis | Weekly vs daily rebalance |
| 10 | Final validation | Full spec, fresh random seed |

### 5.2 Stopping Rules

**STOP and REJECT hypothesis if:**
- Trial 1 fails > 5 gates
- Trials 1-3 average placebo percentile < 0.70
- Any trial shows max drawdown > -25%

**STOP and PROMOTE to next phase if:**
- Trials 1 AND 10 pass ALL 14 gates
- Placebo percentile ≥ 0.90 in both trials
- Consistent results across subsamples

**CONTINUE experimenting if:**
- Trial 1 passes 10-13 gates
- Failures are understandable (e.g., borderline on one gate)
- Directionally consistent with theory

### 5.3 Forbidden Actions

❌ NO parameter optimization
❌ NO feature selection based on results
❌ NO changing weights post-hoc
❌ NO extending sample period to improve results
❌ NO adding features after seeing Trial 1 results
❌ NO "just one more trial" after budget exhausted

---

## 6. Risk Controls

### 6.1 Position Limits
- Max single stock weight: 2% (long or short)
- Max sector exposure: 10% net, 20% gross
- Max market cap decile concentration: 30%

### 6.2 Trading Constraints
- No trading first 30 minutes of market open
- No trading last 15 minutes unless rebalance
- Limit order participation rate: ≤ 10% of ADV
- Emergency flatten capability required

### 6.3 Kill Switch Triggers
- Daily P&L loss > -5%
- Drawdown from peak > -10%
- Data feed interruption > 1 hour
- Model signal missing > 1 day

---

## 7. Documentation Requirements

For EACH trial, must record:
1. Exact code commit hash
2. Random seed used
3. All 14 gate results with numeric values
4. Any errors or warnings during execution
5. Runtime and computational resources
6. Deviation from preregistration (if any, with justification)

All artifacts saved to: `artifacts/H002/trial_N/`

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

## Appendix A: Comparison to H-001

| Aspect | H-001 (Cross-Asset Spillover) | H-002 (Liquidity Reversal) |
|--------|-------------------------------|----------------------------|
| Mechanism | Information diffusion | Liquidity provision |
| Horizon | Intraday to 2 days | 1-5 days |
| Universe | Large-cap ETFs | Small/mid-cap stocks |
| Turnover | Very high | Moderate |
| Capacity | Limited by ETF liquidity | Higher (broader universe) |
| Data needs | Minute-level ETF prices | Daily + intraday volume |
| Complexity | Low | Medium |
| Complementarity | Orthogonal | Orthogonal |

**Portfolio note:** H-001 was rejected. Any future diversification claim for
H-002 depends on H-002 first becoming executable and passing untouched OOS
evaluation under a new approved protocol.
