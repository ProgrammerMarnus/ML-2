# H-006 Factor Exposure Mean Reversion — Final Status

**Decision:** REJECTED; remaining valid-trial budget retired

**Valid execution:** `20260915T183149Z_ce1050bcacf83541`

**Evidence:** `REAL_DATA`, `RESEARCH_ONLY`

**Date:** 2026-09-15

## Outcome

The cross-sectional evaluator is implemented and H-006 has now run through the
real engine on the frozen 17-ETF panel plus non-investable `^VIX`. The valid
baseline failed 13 promotion gates. In accordance with the preregistered Trial
1 stop rule, no parameter/sensitivity trials may be used to rescue this family.

| Metric | Valid Trial 1 result |
|---|---:|
| Full OOS net Sharpe | -0.073 |
| Full OOS gross Sharpe | 0.206 |
| Full OOS net return | -4.04% |
| Mean / median fold Sharpe | -0.029 / -0.139 |
| Positive folds | 2 / 5 |
| Full OOS max drawdown | -16.22% |
| Annual turnover | 15.21x |
| Bootstrap P(SR > 0) | 0.472 |
| Placebo percentile / adjusted p | 0.99 / 0.0198 |
| 10 bps fee + 5 bps slippage Sharpe | -0.316 |
| One-session-delay Sharpe | -0.018 |
| 2x-slippage Sharpe | -0.177 |
| -20% / +20% volatility-target Sharpes | -0.024 / -0.058 |
| 5% missing-input Sharpe | -0.611 |
| Capacity estimate | $19.99m |

The portfolio limit audit passed: maximum asset weight 10.51%, gross 100%,
absolute net 40%, and every asset-class cap remained within its frozen bound.
The panel leakage audit also passed with maximum historical delta 0.0 over
1,761 checked rows. Data integrity and the 100-run placebo sample-size gates
passed. Those controls do not overcome the negative net edge, excessive
turnover, weak bootstrap result, or failed robustness/capacity gates.

## Implemented execution contract

- `src/quant_research/h006_pipeline.py`: 17-asset feature panels,
  cross-sectional standardization and signed five-term composite, locked
  walk-forward evaluation, SHY excess returns, robustness, placebos,
  bootstrap, risk, capacity, and registry integration.
- `src/quant_research/portfolio/h006_portfolio.py`: Wednesday-only decisions,
  one-session return lag, inverse-volatility sizing, position/class/gross/net
  limits, 10% portfolio-volatility ceiling, VIX>75 gross reduction, missing-name
  exclusion, and the frozen turnover scaling rule.
- `src/quant_research/run.py`: dedicated `data.mode == "h006"` engine route.
- `tests/test_h006_pipeline.py`: panel/signal, all-five-terms, self-benchmark,
  leakage, lock, portfolio-limit, VIX, snapshot-replay, and full-run coverage.

`SPY`, `LQD`, and `GLD` are the frozen beta benchmarks. Their beta to
themselves is mathematically constant, and SPY's correlation to itself is also
constant. These standardized terms are explicitly missing rather than derived
from floating-point noise; the all-five-terms rule therefore excludes those
names while leaving 14 possible names and preserving the minimum-12 rule.

## Evidence lineage and invalidation

The following events are preserved rather than hidden:

1. `20260915T180411Z_b728d6716c92a4c5` completed on dataset
   `53ec3599faff65a0`, but is **invalid implementation evidence**. It allowed
   tiny numerical differences in self-beta/self-correlation to become false
   z-scores for SPY/LQD/GLD. It must not be used for H-006's decision.
2. A corrected rerun fetched provider revision `958ffb6d341e3e7e`; the persisted
   lock rejected it before trial increment or evaluation. The lock was not
   deleted or weakened.
3. The valid run replayed the exact original raw snapshot
   `53ec3599faff65a0`, used config fingerprint `e4eee798d3f09582`, and was bound
   to protocol digest `8bb93c7cf69cb156`.

The persistent counter is 2 because the invalid completed record remains
accounted for. Scientifically, the corrected execution is the first valid
H-006 trial. The frozen stop rule retires all remaining budget after this
failure.

## Preregistration discrepancy

The frozen prose says "six" OOS folds but lists seven calendar ranges,
including 2010–2011 even though those 504 sessions are the initial training
window. The numeric contract (504 train, 126 validation, two five-session
boundaries, 504 test, 504 step) yields five complete 504-session OOS folds over
the available observations, covering 2012-07-18 through 2022-07-22. The engine
used that numeric contract without post-result reinterpretation. This
discrepancy is now explicit and is another reason not to claim `ROBUST_OOS`;
the strategy already fails decisively on performance.

## Verification

- Expanded H-006/data/config/feature/pipeline touched-surface suite
  (`pytest -o addopts= -q -p no:cacheprovider`, 2026-09-15): **103 passed,
  0 failed in 9:38**.
- Complete repository suite (`pytest -o addopts= -q -p no:cacheprovider tests/`,
  2026-09-15, finished 21:24 local): **420 passed, 0 failed in 21:12** — exit 0,
  no skips, no teardown errors.

## Artifacts

- Config: `configs/h006_factor_mean_reversion.yaml`
- Protocol: `artifacts/h006/h006_protocol_snapshot_replay.json`
- Valid results: `artifacts/h006/run/20260915T183149Z_ce1050bcacf83541_results.json`
- Fold ledger: `artifacts/h006/run/20260915T183149Z_ce1050bcacf83541_folds.csv`
- Manifest: `artifacts/h006/run/20260915T183149Z_ce1050bcacf83541_manifest.json`
- Raw snapshot: `data/raw_snapshots/20260915T174605Z_h006_ohlcv_53ec3599faff65a0.csv.gz`

H-006 is closed. Any materially revised signal, benchmark treatment,
portfolio rule, or data window must be preregistered as a new family; it cannot
inherit this rejected family's evidence.
