# H-003-R1 Baseline Results

**Executed:** 2026-09-15  
**Decision:** REJECTED; remaining trial budget retired  
**Evidence scope:** H-003-R1 only; original H-003 remains unexecuted

## Frozen identity

- Config: `configs/h003_r1_daily_volatility.yaml`
- Config fingerprint: `b28f26e136fd6dd1`
- Protocol: `artifacts/h003_r1/h003_r1_protocol.json`
- Protocol digest: `0b32c50c955d3f8d`
- Experiment: `20260915T103928Z_e309df031a658f12`
- Snapshot: `3bffff03c4d02f20` (18 symbols, 4,027 complete XNYS sessions)
- OOS: five non-overlapping 504-session folds, 2012-03-30 through 2023-01-31

## Outcome

| Metric | Result | Gate |
|---|---:|---:|
| Full OOS gross Sharpe | 0.375 | diagnostic |
| Full OOS net Sharpe | -0.074 | fail (required 0.8) |
| Mean / median fold Sharpe | -0.100 / -0.080 | fail |
| Positive folds | 2 / 5 | fail concentration gate |
| Full OOS net return | -0.92% | fail economic alpha |
| Full OOS max drawdown | -3.28% | pass |
| Annual turnover | 7.42x | fail (cap 2x) |
| 2x-cost Sharpe | -0.516 | fail |
| Three-session-delay Sharpe | -0.199 | fail |
| Bootstrap P(Sharpe > 0) | 0.414 | fail (required 0.80) |
| Placebo percentile / adjusted p | 1.00 / 0.0476 | pass; null itself was strongly negative |
| Capacity estimate | $6.76m | fail (required $500m) |
| Correlation to SPY | -0.103 | pass |
| 2020 / top-five-VIX-day return | +0.88% / +0.10% | pass |
| Positive VIX-quartile regimes | 2 / 4 | fail |

Ten of the fourteen H-003-R1 mandate gates failed, exceeding the prospective
stop threshold of six failures. The family is therefore rejected after its
baseline and its remaining budget is retired. The gross result is mildly
positive, but the weekly signal changes enough names that 7 bps all-in costs
erase it. This is not a candidate for paper or live trading.

## Accounting attribution correction

The executed net-return series correctly charged the full 7 bps all-in cost.
The original experiment record assigned the combined cost sum (0.051927) to
the `fee_cost` field and zero to `slippage_cost`; this was an attribution-only
defect and did not affect returns, Sharpe, drawdown, turnover, stresses, or the
decision. The correct arithmetic split is fee cost 0.037091 and slippage cost
0.014836. `portfolio_returns` and both portfolio pipelines now expose and use
separate fee/slippage series, with a reconciliation regression test. The
original immutable run artifacts are retained unchanged; this document is the
explicit correction notice.

## Interpretation

The strategy separated from the placebo because row-shuffled signals produced
especially poor high-turnover books, not because the observed strategy met an
absolute performance bar. This is why placebo separation is necessary but not
sufficient. H-003-R1 also supplied the desired crisis/diversification behavior,
but without positive net OOS returns, stability, capacity, or cost tolerance.

The result says nothing decisive about original H-003's VIX-futures curve
mechanism. Testing that distinct mechanism still requires the original data and
continuous-contract methodology.
