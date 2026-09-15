# Preregistration Amendment: H-003-R1 Daily Volatility-Shock Allocation

**Family:** H-003-R1 (new family; not a revision-in-place)  
**Frozen before evaluation data retrieval:** 2026-09-15  
**Status:** EXECUTED ONCE AND REJECTED; TRIAL BUDGET RETIRED

## Decision boundary

Original H-003 remains unexecuted. It requires a normalized VIX-futures M1-M3
curve, a specified continuous-contract roll methodology, and a true
equal-risk-contribution evaluator. Those inputs are not present in the
repository. H-003-R1 asks a narrower question using only adjusted daily ETF
OHLCV and VIX spot available through the existing yfinance adapter. Evidence
from H-003-R1 is evidence for H-003-R1 only.

## Economic mechanism

Volatility shocks can induce forced deleveraging and temporarily distorted
multi-asset prices. A fixed, sign-aligned combination of realized-volatility,
skewness, and correlation-shock measures may forecast the next week's relative
returns. The portfolio absorbs those dislocations while limiting gross and
asset-class risk.

## Immutable data contract

- Evaluation window: 2008-01-01 through 2023-12-30 inclusive (`end` is the
  exclusive 2023-12-31 boundary).
- Investable ETFs: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, SHY, LQD, HYG, UUP, FXE,
  FXY, FXB, GLD, DBC, USO.
- Risk indicator: `^VIX` spot close; it is not investable and is not described
  as a futures term-structure substitute.
- Provider/basis: yfinance daily `auto_adjust=True` OHLCV. No forward filling of
  input market data is permitted.
- Calendar: XNYS. All 17 investables and VIX must be present or execution fails.

## Immutable signal contract

For every investable ETF, using data available through close `t`:

1. `h003r1_vshock_1d`: positive part of 20-session realized-volatility z-score
   relative to the prior-year reference ending 21 sessions earlier, shifted by
   one session. Expected-return sign: negative.
2. `h003r1_vshock_5d`: five-session mean of the lagged positive shock.
   Expected-return sign: negative.
3. `h003r1_vol_mean_rev`: current 20-session realized volatility divided by its
   lagged prior-year mean. Expected-return sign: negative.
4. `h003r1_skewness_20d`: trailing 20-session return skewness.
   Expected-return sign: positive.
5. `h003r1_correlation_spike`: the ETF's trailing 20-session average
   correlation to the other 16 ETFs minus its trailing 252-session norm.
   Expected-return sign: negative.

Each term is cross-sectionally z-scored. All five signed terms must be present;
the composite is their unoptimized equal-weight mean. Signal magnitude is not
used for sizing; only its sign determines long or short direction.

## Immutable portfolio and execution contract

- Rebalance only at Wednesday close. If Wednesday is not an observed session,
  hold the prior book until the next Wednesday; do not substitute another day.
- Execution/return attribution begins one session after the decision close.
- Signed inverse trailing-60-session volatility allocation.
- Gross leverage cap 0.50; scale down to 10% predicted annualized volatility,
  never up above 0.50 gross.
- Absolute ETF weight cap 15%; asset-class gross cap 40%; absolute net equity
  exposure cap 20%; at least 12 complete signals required.
- Stand down to cash when observed VIX is above 80.
- Costs: 5 bps fees plus 2 bps slippage per unit of one-sided turnover.

This inverse-volatility budget is intentionally not called equal risk
contribution. That is a documented deviation from original H-003.

## Walk-forward and statistical contract

- Expanding 504-session initial training history, 126-session validation,
  5-session purge, 5-session embargo, and 504-session non-overlapping OOS tests.
- Step size equals test size. This yields up to six two-year OOS folds without
  the unsupported unscored one-year gaps in original H-003.
- The strategy has no fitted model or threshold search. Train/validation spans
  establish chronological information boundaries only.
- 500 stationary/block bootstrap samples using the repository implementation.
- 20 full-strategy placebos: permute complete cross-sectional signal rows,
  rebuild the portfolio, and reprice it. The selected OOS schedule stays fixed.
- Cost stress: 1x, 2x, and 3x both fees and slippage.
- Delay stress: 0, configured 3-session, and frozen 3-session delay.
- Capacity: fifth percentile of `1% * trailing 20-session dollar volume /
  absolute rebalance trade weight`, reported in USD millions.

## Required gates

All original promotion intent that is measurable under the amended contract is
retained: net OOS Sharpe at least 0.8, Sortino at least 1.2, max drawdown no
worse than -20%, annual turnover at most 2x, estimated capacity at least $500m,
2x-cost Sharpe at least 0.4, three-session-delay Sharpe at least 0.4, bootstrap
`P(Sharpe>0)` at least 0.80, placebo percentile at least 0.85, positive 2020 and
top-five-VIX-day returns, positive Sharpe in at least three of four VIX
quartiles, positive Sharpe in both OOS halves, positive net Sharpe at the 2x
all-in cost, and correlation to SPY below 0.5. The repository-wide research
gates also remain mandatory.

The original 2008 crisis-return condition is removed because a 2008 start and
the required volatility warm-up cannot produce an untouched 2008 OOS position.
This inconsistency is resolved prospectively here, not after viewing results.

## Stopping rule and trial budget

One baseline execution is authorized after the protocol is frozen. If it fails
more than six amended gates, has negative crisis alpha, or exceeds a -35%
drawdown, reject H-003-R1 and retire the remaining budget. Otherwise, at most
ten total trials may follow the preregistered purposes in original H-003. No
asset removal, sign change, lookback change, or extra trial is allowed after
the evaluation window is observed.

## Implementation map

- `configs/h003_r1_daily_volatility.yaml`
- `src/quant_research/h003_pipeline.py`
- `src/quant_research/portfolio/h003_portfolio.py`
- `tests/test_h003_pipeline.py`
- Frozen protocol: `artifacts/h003_r1/h003_r1_protocol.json`

## Recorded decision

The single frozen baseline was executed on 2026-09-15 as experiment
`20260915T103928Z_e309df031a658f12`. Ten of fourteen H-003-R1 mandate gates
failed, including net Sharpe, turnover, capacity, cost, delay, bootstrap,
regime, and subperiod gates. Under the prospective stopping rule the family is
rejected and its remaining trial budget is retired. See `H003_R1_RESULTS.md`.
