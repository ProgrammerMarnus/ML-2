# H-001 Corrected Trial 1 — Superseded Diagnostic Result

**Completed:** 2026-09-14  
**Experiment:** `20260914T145039Z_269d17d973bc60cc`  
**Evidence status:** `REAL_DATA`, but **not valid promotion evidence**  
**Engine decision recorded at the time:** `CANDIDATE` — **superseded**  
**Live-trading status:** `RESEARCH_ONLY` — not eligible for paper or live use.

## Supersession notice

This trial's generic feature-placebo implementation held H-001's conditional
SPY/QQQ selected leg fixed while it permuted the feature rows. Because the leg
is itself determined by `ratio_zscore`, that was not a null for the complete
strategy. Its reported placebo gate must therefore not be used as evidence.

The subsequently locked, untouched 2021–2026 confirmation corrected that
procedure by deriving the leg from each permuted feature panel. It failed the
placebo-separation gate: net Sharpe **0.7873**, placebo percentile **0.35**,
adjusted p **0.667** (20 null runs). H-001 is rejected; see the [corrected
confirmation result](artifacts/h001_confirmation_2021_2026/run_corrected_placebo/confirmation_results.json).

## Immutable evidence

- [Frozen protocol](artifacts/h001_cross_asset_corrected_trial_1/protocols/h001_cross_asset_corrected_trial_1.json)
- [Frozen generated configuration](artifacts/h001_cross_asset_corrected_trial_1/configs/h001_cross_asset_corrected_trial_1.yaml)
- [Structured result](artifacts/h001_cross_asset_corrected_trial_1/runs/h001_cross_asset_corrected_trial_1/20260914T145039Z_269d17d973bc60cc_results.json)
- [Fold diagnostics](artifacts/h001_cross_asset_corrected_trial_1/runs/h001_cross_asset_corrected_trial_1/20260914T145039Z_269d17d973bc60cc_folds.csv)
- [Run manifest](artifacts/h001_cross_asset_corrected_trial_1/runs/h001_cross_asset_corrected_trial_1/20260914T145039Z_269d17d973bc60cc_manifest.json)

The run used adjusted daily SPY, QQQ, and `^VIX` history from 2010-01-04 to
2020-12-31. It used the corrected nine-feature H-001 contract and an
asset-specific selected-leg ledger: ratio z-score above zero selects SPY;
otherwise QQQ. A leg switch is charged as two-sided turnover.

## Result summary

| Measure | Result |
|---|---:|
| Full OOS net Sharpe | 1.0802 |
| Full OOS gross Sharpe | 1.1930 |
| Full OOS net return | 52.08% |
| Full OOS max drawdown | -6.69% |
| OOS folds / positive folds | 6 / 6 |
| Annual turnover | 37.91x |
| Fees / slippage paid | 2.27% / 2.27% |
| Bootstrap P(Sharpe > 0) | 1.00 (500 samples) |
| Placebo percentile / adjusted p | 1.00 / 0.0476 (20 null runs) |

All fourteen configured engine gates passed, including 10-bps cost stress,
one-bar delay stress, data integrity, and family-level Bonferroni correction.

## Historical interpretation and controls

This was one corrected, real-data diagnostic—not a promotion. The original
H-001 runs remain invalid and are not used here. The trial consumed six
recorded threshold-evaluation units (one fixed threshold across six OOS folds)
from its ten-unit protocol budget.

The 2010–2020 OOS evidence has now been read. Do not rerun variants against
that window. The pre-frozen later-window confirmation is complete and rejected
H-001. Promotion, paper trading, and live trading remain blocked.
