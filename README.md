# Institutional Quant Research Engine V2.1.5

A point-in-time, leakage-safe, walk-forward quantitative research platform.

`raw data -> PIT data -> features -> TRAIN/VAL/OOS walk-forward -> robustness
-> information ablation -> strategy discovery -> portfolio/risk -> experiment
registry`

**The engine is a research platform, not a Sharpe-maximizer.** Its promotion
gates are deliberately conservative and default to rejection. A strategy is
promoted only when every explicit evidence gate passes.

---

## Layout

```
src/quant_research/
  config.py                 typed YAML configuration + fingerprinting
  data/                     schemas, loaders, snapshots, validation
  features/                 PIT events, price/volume, information, leakage, registry
  evaluation/               metrics, backtest, walk_forward, bootstrap, placebo,
                            multiple_testing, overfitting, robustness
  strategies/               baseline, discovery
  portfolio/                construction, risk
  experiments/              registry, leaderboard, promotion
  execution/                paper simulator, safeguards, operational controls
  run.py                    one-command research pipeline (CLI)
tests/                      pytest suite (322 collected tests)
configs/                    baseline.yaml (synthetic), real_spy.yaml (yfinance)
Institutional_Quant_Research_Engine_V2.1.ipynb   thin orchestration notebook
```

---

## Quick start

```bash
pip install -e .[dev]
pytest                        # full test suite
python -m quant_research.run --config configs/baseline.yaml --output artifacts
```

### Research run

```bash
# Synthetic/offline smoke run (defaults, no credentials)
python -m quant_research.run --config configs/baseline.yaml --output artifacts

# Real daily data (yfinance; no credentials required)
python -m quant_research.run --config configs/real_spy.yaml --output artifacts_real
```

Each run produces, under the output directory:

- `experiment_registry.jsonl` - one immutable record per run
- `<experiment_id>_folds.csv` - per-fold OOS diagnostics
- `<experiment_id>_results.json` - full structured results
- `trial_counter.json` (+ `.highwater`) - persistent global trial count

For a new strategy hypothesis, create and freeze a
`quant_research.experiments.protocol.ResearchProtocol` before running the
pipeline, then set `research.protocol_path` in the configuration. The protocol
binds the hypothesis, mechanism, features, data split, trial budget, and config
fingerprint. It is immutable and is recorded with the experiment.

---

## Data contract

Normalized long schema (one row per symbol-bar):

| column               | type   | notes                              |
|----------------------|--------|------------------------------------|
| `timestamp`          | datetime (UTC, tz-aware) | naive timestamps REJECTED |
| `symbol`             | string |                                    |
| `open/high/low/close`| float  | positive, finite, high >= low      |
| `volume`             | float  | non-negative                       |

The loader **never** silently forward-fills, repairs, or estimates missing
market observations. Violations raise `DataValidationError` with a visible
message. A missing provider bar is a data-integrity exception, not an
imputation opportunity.

Raw downloads are preserved as immutable snapshots (hash named, never
overwritten). `dataset_hash` is a deterministic sha256 over the canonicalized
frame and is versioned into every experiment record.

### Corporate-action assumption (documented)
yfinance loads use `auto_adjust=True`: split/dividend-adjusted OHLC so
historical returns are tradable-return-consistent. For CSV mode the
corporate-action basis is the user's responsibility and must be documented.
---

## Point-in-time model (highest priority)

Every alternative-data event carries:

```
event_id, symbol, event_time, publication_time, availability_time,
source, raw_value, processed_value
```

Rules enforced by `features/point_in_time.py`:

1. `availability_time` controls when the information becomes usable.
2. A feature at bar `t` consumes only events with `availability_time <= t`.
3. Event, publication, and availability times are distinct concepts.
4. Missing availability time is an error - never silent immediate tradability.
5. Revised values must be versioned (new `event_id` / `revision`); reusing an
   `event_id` with a conflicting value is rejected.
6. Naive timestamps are rejected so timezone conversion can never move
   information backward in time.
7. Availability before event time is rejected unless the event carries an
   explicit, documented `provider_rule_exception`.

Daily-bar convention (conservative): the permitted execution timestamp of a
daily bar is the bar's session open. Consequently, an event published after
`t`'s close only affects bars strictly after `t` - next-session execution.
This can never introduce look-ahead; at worst it adds one day of delay.

---

## Walk-forward contract

Layout per fold (bar counts):

```
[ train ][ purge ][ validation ][ embargo ][ test ]
```

- rolling and expanding train windows
- scalers/imputers/models are fit **only on training bars** per fold
- thresholds/parameters are selected only on validation
- test is evaluation-only
- `LockedTestProtocol` freezes the fold specification: any later run that
  would re-cut the test windows raises `LockedTestViolation`

---

## Backtest execution model

- signal computed from data through bar `t`'s close is traded at the earliest
  at session `t+1` (inherent one-bar execution delay) plus any configured
  `signal_delay_bars`
- position at `t` = vol-targeted scale (trailing realized vol through `t-1`)
  x direction(signal at `t-1-delay`)
- costs: (fee_bps + slippage_bps) charged on absolute position change
- gross -> costs -> slippage -> net is always kept distinct in metrics

## Paper simulator boundary

The paper broker is a simulator, not a live-broker adapter. Orders have an
explicit bar-based eligibility time; pending buys reserve cash across symbols;
cash and exposure are checked again at fill time; and a tripped kill switch
cancels exposure-increasing pending orders. Explicit `reduce_only` orders may
flatten a position during a kill switch but cannot reverse it. Paper-validation
promotion requires unique processed sessions from an `observed_paper` source,
a compatible approved research record, reconciliation, and a tested kill
switch. Simulated replay evidence remains `PAPER_READY`.

`PaperBroker.save_state()` writes a non-overwriting recovery snapshot; loading
it rechecks both position reconciliation and a hash-chained audit trail before
orders can resume. This is simulator recovery evidence, not proof of a live
broker's recovery behavior.

---

## Robustness / anti-overfitting

Automated, structured diagnostics (each returns data, not just text):

cost stress, slippage stress, signal-delay stress, missing-data stress,
regime analysis, parameter perturbation, empirical-null placebo
(shuffle-feature / target-permutation / block-permutation), bootstrap CIs,
PBO (CSCV), and deflated Sharpe. Multiple-testing corrections (Bonferroni,
Benjamini-Hochberg, Holm) are available.

### Placebo test
The null is an **empirical distribution** built from many full walk-forward
pipeline repetitions with randomized inputs. The strategy is reported as a
percentile within that null plus a conservative adjusted p-value
`(1 + #{null >= observed}) / (1 + n_runs)`. One arbitrary placebo comparison
is never used.

---

## Research trial accounting

Every strategy/model search trial is counted persistently in
`trial_counter.json`. The counter:

- only ever increases (negative increments rejected)
- refuses accidental reset (a lowered counter triggers an error via the
  high-water mark file)
- is recorded as `trials` / `n_trials_global` in every experiment record

Statistical claims must be interpreted in light of the search size
(`one_shot_hypothesis_test` / `bounded_small_search` / `large_scale_search`).

---

## Experiment registry / leaderboard

`experiment_registry.jsonl` is append-only and never overwritten. Each record
captures: experiment_id, timestamp, strategy, features, universe, target,
timeframe, train/validation/test periods, trials, dataset/feature/strategy/code
versions, seed, gross & net metrics, costs, slippage, OOS metrics, bootstrap
interval, robustness score, placebo statistics, information sources, and
promotion state.

The leaderboard (`experiments/leaderboard.py`) answers: what was tested, when,
with what dataset, how many trials, what was untouched OOS performance, did it
survive costs/delay, how it compared with the empirical null, and why it was
promoted or rejected.

---

## Promotion gates

```
RESEARCH_ONLY -> CANDIDATE -> ROBUST_OOS -> PAPER_READY
              -> PAPER_VALIDATED -> LIVE_ELIGIBLE
```

A run reaches `CANDIDATE` only when **all** gates pass; any failure holds the
strategy at `RESEARCH_ONLY` with the failed gate named:

- median/mean OOS Sharpe > 0
- worst OOS drawdown within limit
- cost stress survives (>= 10bps)
- delay stress survives (>= 1 bar)
- bootstrap P(SR > 0) >= 0.60
- placebo percentile >= 0.95 (real strategy must beat the empirical null)
- no single fold dominates
- annual turnover plausible
- data-integrity checks pass
- look-ahead risk resolved
- trial accounting consistent

The gates never modify metrics to improve optics, and synthetic/offline
results are always labelled `SYNTHETIC_OFFLINE` - never market evidence.

---

## Real-data setup

`yfinance` mode needs no credentials:

```bash
python -m quant_research.run --config configs/real_spy.yaml --output artifacts_real
```

Provider credentials (future feeds) belong in environment variables only -
never in source code. When a provider is unavailable or returns empty data,
the loader raises `DataValidationError`; there is no fabricated success path.

---

## Known limitations

- Only daily frequency (`1d`) is implemented.
- The business-day calendar in `missing_data_report` treats exchange holidays
  as missing gaps; real SPY data therefore has a nonzero missing-bar report.
  Follow-up work should use a per-symbol exchange calendar.
- The information/news engine is exercised with synthetic labelled events in
  offline mode; real news/Reddit/X providers are an external integration that
  has no credentials in this environment (interface + offline path exist).
- Paper trading and live deployment states are state-machine targets only;
  they require live evidence that this platform cannot fabricate.
- Strategy discovery currently grid-truncates deterministically to
  `max_trials`; threshold selection stays on validation (keeping the search
  bounded), and the final candidate is then evaluated on OOS exactly once.
