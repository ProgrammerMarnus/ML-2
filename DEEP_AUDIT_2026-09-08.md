> **Historical audit snapshot.** This report describes the code as audited on
> 2026-09-08; later fixes changed many findings. For current resolution and
> readiness, use [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) and
> [LIVE_TRADING_READINESS_CHECKLIST.txt](LIVE_TRADING_READINESS_CHECKLIST.txt).

**Deep audit — ML-2 / Quant Research Engine V2.1.3**  
Audited 8 September 2026. Root: `/home/marnus/VS-Code/ML-2`.

**Verdict: retain RESEARCH_ONLY.** The current baseline can be reproduced, and the existing tests pass, but important research safeguards do not enforce their advertised contracts. Two paths contain direct historical-information contamination: information-event deduplication and global strategy discovery. Other defects affect placebo validity, transaction costs, risk diagnostics, trial accounting, and promotion decisions. These findings do not establish that the saved price-only baseline has feature look-ahead; several apply to optional modules or nondefault configurations, as identified below.

This audit identified **24 findings: 12 P1, 11 P2, and 1 P3**. P1 means a material correctness, evidence-integrity, or supported-workflow failure; P2 means a substantive reporting, validation, or reproducibility defect; P3 means test isolation/maintenance work. These are software priorities, not estimates of financial loss.

Source, tests, configuration, the notebook, existing research artifacts, and raw data were left unchanged. Only this report and its evidence bundle were added. Findings describe the observed code, not proposed fixes already applied.

**What was verified**

- Reviewed the active source modules, configuration, notebook orchestration, test coverage, prior audit, and all experiment registries. The generated Repomix export was not treated as authoritative over the actual source. Files under `Initial Files - do not modify` were treated as historical context; `Versions` contained no files in the exposed workspace.
- Ran the complete suite in an isolated copy: **210 passed, 1,642 warnings, 336.23 seconds**. There are 183 test functions, expanded to 210 collected cases through parametrization. Warnings principally concern entirely unobserved `momentum_252` in short training fixtures and variance estimates from one placebo sample.
- Ran 20 targeted audit probes, a discovery-selection perturbation, and two complete synthetic pipeline runs with changed test geometry. All reproduced the conditions described in their saved outputs. These are diagnostic reproductions, separate from the existing passing suite.
- Replayed the latest saved real-data baseline from its existing Parquet snapshot. Its dataset hash and configuration fingerprint match the saved record; all 17 compared summary fields reproduce with zero difference.
- Validated the current notebook schema and compiled all eight code cells. Inspected stored outputs and execution counts; did not re-execute the entire notebook or refresh market data over the network.
- Inspected source for dynamic execution/deserialization sinks and scanned project text for selected credential/private-key patterns without printing secret values. No matching credentials or dangerous execution sinks were found in that limited scan. This was not a package vulnerability scan or an exhaustive security certification.
- Git revision/history checks were unavailable: the exposed `.git` directory contains no repository metadata. An explicit SHA-256 manifest records the audited source, tests, configurations, README, project metadata, and notebook instead.

Runtime: Python 3.13.5; NumPy 2.5.2; pandas 3.0.5; scikit-learn 1.9.0; SciPy 1.18.1; pytest 9.1.1; PyYAML 6.0.2; pyarrow 25.0.1; nbformat 5.11.1; nbclient 0.11.0. Numerical-library thread counts were limited to one for the audit runs.

**Finding index**

| ID | Priority | Finding | Affected path |
|---|---|---|---|
| A01 | P1 | Later news changes earlier corroboration features | Information features |
| A02 | P1 | Global discovery uses future validation outcomes to choose earlier OOS strategy | Discovery API |
| A03 | P1 | Block placebo leaves dated targets unchanged and scrambles risk history | Default pipeline diagnostic |
| A04 | P1 | Executed return interval contradicts documented session-return contract | Baseline and all replays |
| A05 | P1 | Fold resets omit exit costs and lose execution state | Baseline and all replays |
| A06 | P1 | Single-fold concentration gate measures the wrong quantity | Promotion |
| A07 | P1 | Stale counter instances can roll back both count and high-water mark | Trial registry |
| A08 | P1 | Missing assets and truncated provider coverage can pass integrity | Data ingestion |
| A09 | P1 | Robustness replay drops the holding rule | Nondefault strategy replay |
| A10 | P1 | Gradient boosting crashes the robustness checks | Supported model configuration |
| A11 | P1 | Configured nonzero signal delay crashes the stress workflow | Supported execution configuration |
| A12 | P1 | Placebo gate can pass with p = 0.5; search corrections are not enforced | Promotion |
| A13 | P2 | Search trials are omitted and the “global” count is output-directory local | Discovery and governance |
| A14 | P2 | Risk report uses proxy exposure and a misaligned benchmark | Default pipeline report |
| A15 | P2 | Initial drawdown is missed; gate considers only individual folds | Metrics, risk control, promotion |
| A16 | P2 | PBO ranks against fold count instead of strategy count | Standalone statistics |
| A17 | P2 | Deflated-Sharpe correction uses the wrong denominator | Standalone statistics |
| A18 | P2 | Weekend/prehistory events never decay | Information features |
| A19 | P2 | Overlapping OOS windows are accepted and double-counted | Nondefault fold configuration |
| A20 | P2 | Test lock is neither persistent nor a complete membership lock | Experiment governance |
| A21 | P2 | OHLCV validation accepts impossible bars; wide CSV invents OHLC | Data ingestion/feature inputs |
| A22 | P2 | Sortino denominator is not downside deviation | Performance metrics |
| A23 | P2 | Artifacts omit replay inputs and dataset hashing loses precision | Reproducibility |
| A24 | P3 | Test runs write snapshots into the working project's data directory | Test isolation |

**A01 — [P1] Deduplication lets future stories alter historical features**

Locations: [information.py:31](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:31), [information.py:52](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:52), [leakage.py:68](/home/marnus/VS-Code/ML-2/src/quant_research/features/leakage.py:68).

`deduplicate_events` processes the complete event collection before the availability-time join. It adds all later copies to the earliest retained event's corroboration count. That enriched count is then visible from the earliest event's availability, including contributions from copies that have not arrived yet.

Reproduction: an event available on 5 January has `info_corroboration = 1` when calculated from the available prefix. Adding a same-topic copy available on 12 January changes the **5 January** value to **2**. Both input events satisfy the schema. The existing leakage probe still reports `passed = True`: it perturbs by `event_time`, so a late publication about an old event is outside its future-event mask, and it never tests future-event addition/removal.

Impact: historical news features and models trained on them can contain future information. This affects the information feature path; the saved real SPY run has no real information events and is not evidence of this particular exposure.

Fix: maintain corroboration updates as separately timestamped observations, or deduplicate only information available at each decision time. Add prefix-versus-full-history tests, including later syndication, delayed publications, and revisions. Historical features must remain identical when unavailable events are added or deleted. Evidence: `pit_future_corroboration`.

**A02 — [P1] Discovery selection contaminates earlier OOS periods**

Locations: [discovery.py:61](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:61), [discovery.py:117](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:117), [discovery.py:154](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:154).

Each candidate is ranked by aggregated validation performance across the entire walk-forward history. The winning candidate is then evaluated on every historical test fold. Later validation periods overlap earlier test periods: with the supplied defaults, **247 of the first 252 test bars occur in the second validation window**. The global candidate ranking therefore uses outcomes from an earlier period it subsequently calls untouched OOS, as well as outcomes after it.

Reproduction with actual model fitting: changing returns only at or after the first test starts changed the selected candidate from **3 to 2** while every return in that fold's training and validation windows remained identical. See `discovery-selection-perturbation.json`.

Later folds training on earlier observations is legitimate for a fixed walk-forward algorithm. The defect is selecting one global candidate using later outcomes and applying that choice retrospectively to earlier folds. The CLI currently runs only the baseline, so this finding specifically concerns the advertised discovery/evaluation API.

Fix: nest candidate selection within each outer fold, using information available before that fold's test, or reserve a final holdout that starts after all discovery. Test that perturbing any period after an outer decision time cannot change that fold's chosen candidate or predictions. Evidence: `discovery_future_selection` and the separate selection perturbation.

**A03 — [P1] Block permutation does not randomize dated targets**

Locations: [placebo.py:72](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/placebo.py:72), [baseline.py:159](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:159), [baseline.py:171](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:171).

The block branch takes `y.iloc[idx]` and `fwd.iloc[idx]` but retains their original timestamps. Production subsequently selects labels and returns by the chronological anchor, restoring their original values at every date. Meanwhile, `risk_obs = fwd_returns.shift(1)` is calculated on the permuted ordering, and volatility rolls over that ordering. The result is unchanged date-to-target relationships combined with a corrupted risk history; later-dated observations can precede earlier dates in the risk window.

Reproduction: both permuted series become exactly equal to the originals after production-style reindexing. The captured risk-history ordering contains two later-date-to-earlier-date transitions. The null can still produce different Sharpe values because sizing and threshold economics change; it is therefore **not** simply an identical rerun, and those differences do not validate the intended null.

Fix: assign permuted values to the original chronological index for both series, preserve label/return pairing and missingness explicitly, and validate chronology before deriving risk returns. Assert that the intended dated relationship changes and that all three placebo modes retain the declared execution semantics. Evidence: `block_permutation`.

**A04 — [P1] Return accounting does not match the documented execution interval**

Locations: [backtest.py:82](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:82), [backtest.py:113](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:113), [backtest.py:139](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:139), [baseline.py:220](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:220), [run.py:132](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:132).

The backtester documents `session_returns[t] = close[t] / close[t-1] - 1`, but production supplies `fwd[t] = close[t+1] / close[t] - 1`. Combined with the inherent one-bar signal shift, a signal from close `t` is scored against the interval **close t+1 to close t+2**. This is not the documented session-t+1 return and does not implement a next-open fill. Open prices are never used for execution. Daily timestamps at midnight UTC are also described as session opens, although they are date labels rather than actual opening times.

Consequences include inconsistent interpretations of AUC/labels versus traded returns, benchmark misalignment (A14), and ambiguous event-to-fill timing. An explicitly declared delayed close-to-close strategy can be causal; this finding is an economic-contract mismatch, not proof of direct price-feature look-ahead.

Fix: select one explicit contract. For next-open execution, account for the relevant open/intraday/overnight prices. For delayed-close execution, state the actual interval and align labels, risk observations, benchmarks, costs, and event cutoffs to it. Add a hand-calculated path with a large overnight gap that distinguishes the alternatives. Evidence: production call-chain inspection.

**A05 — [P1] Fold boundaries lose execution state and omit exit costs**

Locations: [baseline.py:219](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:219), [backtest.py:113](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:113), [backtest.py:140](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:140).

Full risk history now warms volatility, but every test slice still restarts its signal shift, holding state, and position accounting. The first bar is flat. If the previous contiguous fold ended invested, that position disappears without an exit cost: the new fold sees its first zero as an initial position, and the prior fold has no closing trade.

A constant-long reproduction gives position **1** in a continuous run and **0** at the same fold boundary, with **zero exit cost** instead of 6 bps for a unit position. In the saved real-data replay, summed fold turnover is **197.603902**, while turnover over the actual concatenated position path is **198.603448**. The omitted transition turnover is **0.999546**, or **5.9973 bps** of summed return costs at the configured fee plus slippage. That cost discrepancy is small for this run, but the loss of boundary exposure/holding state is a separate economic change.

The passing warm-start test happens to use a boundary where its chosen random signal is flat. It does not establish equivalence for invested boundaries or persistent holding rules.

Fix: carry execution state and pre-window signals across adjacent folds, or explicitly liquidate/re-enter and charge every transition. Derive total costs from a continuous ledger; reconcile each fold to slices of that ledger. Evidence: `fold_state_and_exit_cost` and `real-baseline-replay.json`.

**A06 — [P1] The single-fold gate measures positive Sharpe share, not single-fold concentration**

Locations: [baseline.py:273](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:273), [baseline.py:288](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:288), [promotion.py:121](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:121).

`single_fold_share` sums **all positive** fold Sharpes and divides by the sum of absolute fold Sharpes. There is no maximum over individual folds. Four equally profitable folds `[1, 1, 1, 1]` produce **1.0** and fail the 0.60 gate. `[10, 0.01, 0.01, -9]` produces **0.5268** and passes this gate despite one fold supplying **99.80%** of positive Sharpe contributions.

The saved real run's 0.579684 value should therefore not be interpreted as the contribution of its largest fold. A maximum-absolute-Sharpe diagnostic would be 0.272537 for that run, but Sharpe ratios are not additive P&L contributions; the desired definition must be chosen explicitly.

Fix: define concentration on economically meaningful fold contributions, including treatment of losses and zero-trading folds, and use the largest contribution. Add balanced-positive, single-winner, and mixed-sign fixtures. Evidence: `single_fold_share`.

**A07 — [P1] Counter writers can silently erase both trial history and the high-water mark**

Locations: [registry.py:126](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:126), [registry.py:143](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:143), [registry.py:153](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:153).

Each `TrialCounter` caches count and high-water state at construction and persists those cached values without locking or reloading. Atomic rename protects an individual file replacement, not the read-modify-write transaction. Two instances opened at zero, followed by `a.increment(100)` and `b.increment(1)`, leave **both files at 1**. A newly opened counter accepts that state. This is deterministic even without simultaneous writes.

Actual concurrent writers also share fixed `.tmp` filenames, and count/high-water updates are separate operations. The registry append path has no transaction tying a run's count, record, and artifact completion together.

Fix: serialize reload/check/increment/persist under one lock or database transaction, use unique temporary files if files remain, and protect the high-water mark with the same transaction. Test stale writers, true multiprocess increments, and interrupted writes. Evidence: `counter_stale_writer`.

**A08 — [P1] Integrity checks can accept a missing asset and incomplete requested history**

Locations: [loaders.py:116](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:116), [loaders.py:143](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:143), [validation.py:270](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:270), [run.py:98](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:98).

Loaders do not reconcile observed symbols with the requested universe. The yfinance path skips unavailable symbols; CSV filtering likewise does not require every requested asset. `missing_data_report` evaluates only symbols present and only between each symbol's own first and last observations. Leading/trailing omissions and entirely absent symbols are invisible.

Reproduction: request SPY and QQQ for 2020–2025, supply only SPY from January–February 2024, and loading succeeds with **zero missing sessions**. Metadata continues to describe the requested two-asset universe. A sufficiently long partial dataset can reach modeling with a changed cross-asset feature definition while the integrity checks pass.

Fix: compare observed coverage against the declared universe and requested trading-session interval, with explicit rules for listings/delistings and approved exclusions. Save the realized universe and completeness decisions in the record. Evidence: `missing_universe_and_boundaries`.

**A09 — [P1] Robustness replay drops the candidate's holding period**

Locations: [robustness.py:68](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:68), [baseline.py:37](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:37), [baseline.py:124](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:124).

Discovery now forwards `hold_bars` into the selected candidate's initial OOS run. However, `ExperimentResult` does not retain that rule, and `replay_oos` does not pass it back. A no-override replay therefore defaults to one bar.

Reproduction: replaying a baseline generated with a five-bar hold changes **53 of 160** OOS positions even though no stress parameter was changed. Calling the assertion-based stress helpers on that result can fail instead of producing a robustness report. The default CLI's one-bar baseline does not expose this case.

Fix: persist a complete executable strategy specification in the result and replay it directly, including holding rule, features, seed, model parameters, execution settings, risk inputs, and boundary state. Also reconcile discovery's explicit `seed` with the config seed used by `evaluate_candidate_oos`; the selected row currently does not retain the discovery seed. Evidence: `holding_rule_replay`.

**A10 — [P1] Supported gradient boosting cannot complete the robustness stage**

Location: [robustness.py:125](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:125).

`_assert_selection_identical` reads `.coef_` and `.intercept_` on every classifier. `GradientBoostingClassifier` exposes neither attribute. A gradient-boosting baseline fits and evaluates successfully, then `cost_stress` raises **`AttributeError: 'GradientBoostingClassifier' object has no attribute 'coef_'`**. Since the full pipeline always runs this battery, a supported `model.type` cannot complete.

Fix: verify replay through retained model identity, predictions, and model-appropriate state rather than assuming logistic-regression attributes. Parameter perturbation also varies only `C`, which gradient boosting ignores; select meaningful parameters per supported model. Add a full pipeline case for each supported model type. Evidence: `gradient_boosting_stress`.

**A11 — [P1] Supported nonzero execution delay cannot complete the stress stage**

Locations: [robustness.py:301](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:301), [robustness.py:218](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:218), [run.py:168](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:168).

The delay battery replaces the configured delay with absolute values 0, 1, 2, 3, then asserts that the zero-delay row equals the supplied baseline. If the baseline configuration already has delay 1, zero delay is a different strategy timing and must not equal it. The orchestration reconciliation makes the same zero-delay assumption.

Reproduction: a delay-1 baseline completes, then `delay_stress(..., delays=[0])` raises **`AssertionError: delay=0 replay positions differ from baseline positions`**.

Fix: specify whether stress values are additional latency or absolute delay. For additional latency, use `configured_delay + stress_delay` and anchor stress zero to the baseline. If absolute, anchor comparisons to the configured-delay row and compare relative shifts consistently. Evidence: `configured_nonzero_delay`.

**A12 — [P1] Promotion can accept a one-run null with p = 0.5**

Locations: [promotion.py:114](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:114), [run.py:260](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:260), [promotion.py:136](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:136).

The placebo gate checks percentile only. `ResearchConfig` permits one run, and neither sample count nor adjusted p-value enters the gate. An observed Sharpe of 2 versus a single null Sharpe of 1 gives percentile **1.0**, adjusted p-value **0.5**, and a **passing placebo gate**. This does not mean all other gates pass; it shows that this evidence requirement can accept essentially uninformative null evidence.

Even at the default 20 runs, percentile 0.95 corresponds to one null at or above the observation and a corrected tail probability of **2/21 = 0.09524**. All three null modes are calculated, but only feature shuffling is consumed by promotion. PBO, deflated Sharpe, and family-adjusted p-values are not wired into acceptance. `trial_accounting_consistent` means only `trials >= 1`.

Fix: predeclare the primary null and significance rule, enforce adequate valid repetitions, report Monte Carlo uncertainty, and apply the declared search-family correction. Save and gate the same evidence objects. Repeated searches require selection-bias control; this is the role described in the original [deflated-Sharpe paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). Evidence: `placebo_gate_resolution` and call-chain inspection.

**A13 — [P2] Trial accounting omits discovery and is not global across output directories**

Locations: [discovery.py:91](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:91), [baseline.py:215](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:215), [run.py:137](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:137), [run.py:237](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:237).

Only baseline threshold evaluations with a supplied counter increment the ledger. `discover_strategies` has no counter argument and records none of its feature/model/holding searches or internal threshold evaluations. Price-only ablation performs another selection run without a counter. Null repetitions should be identified separately from research hypotheses, but genuine candidate searches cannot simply disappear from the ledger.

The counter lives below the selected output directory. Moving from `artifacts_real_v3` to `artifacts_real_v4` therefore starts a new count: the records show **378** in the former and **63** in the latter, both described as global counts. This is independent of the stale-writer rollback in A07. The V2.1.3 `trials_this_experiment` subtraction is present and works for the counted baseline evaluations; it does not repair incomplete search coverage.

Fix: introduce a persistent research-family ledger shared across output versions, define hypothesis versus threshold/fit counts, and require discovery/ablation entry points to register the appropriate attempts. Reconcile the experiment record with ledger entries, rather than checking a positive integer. Evidence: source inspection and existing registries.

**A14 — [P2] Risk diagnostics describe proxy positions and compare the wrong return interval**

Locations: [run.py:212](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:212), [run.py:273](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:273).

The risk report thresholds contemporaneous prediction probabilities at an arbitrary 0.55. It ignores the actual per-fold thresholds, execution lag, volatility sizing, and executed positions already available as `baseline.oos_positions`. It also compares the forward-indexed strategy return with a contemporaneous close-to-close benchmark, shifted one return interval relative to the scored P&L.

Verified against the exact real-data baseline replay:

| Diagnostic | Saved risk report | From the actual replay |
|---|---:|---:|
| Average gross exposure | 36.3940% | **25.8424%** |
| Annual turnover | 50.8571 | **28.2291**, using charged fold turnover |
| Beta | −0.023029 | **+0.272888**, using the same forward interval |

Correcting beta here only aligns it with the engine's existing return convention; it does not resolve A04's execution-price contract. The current code correctly reports concentration HHI as null when no weight matrix is supplied; the earlier misleading time-series HHI has been removed.

Fix: use actual executed positions and ledger turnover, align the benchmark to the same realized interval, and integrate any advertised portfolio controls into the scored portfolio before reporting their effects. `construct_portfolio` is not called by the main pipeline. Evidence: `real-baseline-replay.json`.

**A15 — [P2] Drawdown excludes starting capital and the promotion limit ignores cross-fold accumulation**

Locations: [metrics.py:46](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/metrics.py:46), [construction.py:62](/home/marnus/VS-Code/ML-2/src/quant_research/portfolio/construction.py:62), [baseline.py:284](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:284), [promotion.py:91](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:91).

The peak starts at the first post-return equity value instead of including initial capital. Returns `[-0.20, 0, 0]` therefore report **zero drawdown**, and the drawdown controller remains at full exposure after that 20% loss. The controller's causal one-period shift is present; the remaining error is its peak initialization.

Separately, promotion consumes the worst individual fold drawdown rather than the drawdown of the complete OOS equity path. Consecutive losing folds can breach a portfolio drawdown limit while each fold remains within it. The saved run illustrates the difference: worst fold drawdown **−17.7808%**, full-path drawdown **−22.9232%**. Both happen to be within the current −50% limit, so this discrepancy does not change that run's gate outcome.

Fix: include starting equity in the high-water calculation and gate the actual concatenated portfolio path. Keep per-fold drawdown as a separate stability diagnostic. Evidence: `initial_loss_drawdown`, saved risk output, and summary call chain.

**A16 — [P2] PBO compares the strategy rank with the number of folds**

Location: [overfitting.py:44](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/overfitting.py:44).

`oos_rank` ranks a selected candidate among strategy variants, but the threshold is `len(oos_folds) // 2`. That compares quantities from different dimensions. With two variants and eight folds, the maximum rank is 1 and the threshold is 2, so the function can never flag overfitting.

The audit constructed two opposite variants whose IS winner falls below the variant median OOS in **all 70** combinations. The function returns **PBO = 0.0**, while the direct rank calculation returns **1.0**.

Fix: rank against the strategy distribution, define tie handling, validate finite observations, and test both few-strategy/many-fold and many-strategy/few-fold cases. Also bound combination generation before materializing it; `max_combinations` currently limits evaluation only after the full combinatorial list is allocated. This utility is not used by current promotion, so it is a latent statistical defect rather than the cause of the saved promotion state. Evidence: `pbo_rank_axis`.

**A17 — [P2] Deflated Sharpe does not implement its stated skew/kurtosis correction**

Locations: [multiple_testing.py:41](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/multiple_testing.py:41), [multiple_testing.py:65](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/multiple_testing.py:65).

The denominator is `sqrt(1 - skew/3 + (kurtosis-3)/24)`. The published probabilistic-Sharpe correction instead depends on the estimated per-period Sharpe: `sqrt(1 - skew*SR + (kurtosis-1)*SR**2/4)`. The module's null benchmark also assumes a particular Sharpe variance rather than accepting the cross-trial estimate. These are material departures from its stated methodology. See equation 2 of the original [paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

Holding its benchmark assumption constant, annual Sharpe 1.5, 1,000 observations, 50 trials, skew −3, and kurtosis 10 produce p **0.319466**, versus **0.266938** with the published denominator. In addition, `expected_max_sharpe` documents an annualized output but returns daily-scale values: 0.072019 here corresponds to annualized 1.143267. The caller's conversion to daily Sharpe is internally compatible with that output; the defect is not an extra annualization mismatch in the caller.

Fix: implement and document the full intended estimator, return units, trial dependence/variance assumptions, and edge cases; test published numerical examples. Do not wire this utility into promotion before fixing it. Evidence: `dsr_formula`.

**A18 — [P2] Events outside an indexed session date never decay**

Location: [information.py:111](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:111).

Event age uses `bar_pos.get(availability.floor('D'), n)`. A weekend/holiday event, an event predating the first bar, or an event joined to non-midnight bars has no matching dictionary key and receives position `n`. Every actual bar position is smaller, so clipping the difference at zero makes its age stay zero forever.

Reproduction: a Saturday event has `info_intensity = 1.0` both on the first eligible Monday and on the 15th business bar, despite a five-bar half-life.

Fix: map availability to its first eligible session with a sorted-index search and apply a consistent prehistory policy. Test weekend, holiday, intraday, prehistory, and alternate-timezone/session-timestamp cases. Evidence: `weekend_decay`.

**A19 — [P2] Overlapping test folds duplicate OOS observations**

Locations: [config.py:57](/home/marnus/VS-Code/ML-2/src/quant_research/config.py:57), [walk_forward.py:100](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:100), [baseline.py:259](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:259).

Configuration accepts `step_bars < test_window`. Baseline evaluation concatenates all overlapping test results without a policy selecting or combining predictions for the same date. A 40-bar test with 20-bar steps yields **280 rows but 120 duplicated timestamps** in the audit fixture. Metrics and sample counts then treat repeated dates as sequential observations. The cost-stress checker subsequently raises `ValueError: cannot reindex on an axis with duplicate labels`.

Fix: reject overlapping OOS windows until a prediction-selection/portfolio-combination policy is implemented, or aggregate to one chronological executed portfolio before metrics. Validate index uniqueness and define treatment of gaps when step size exceeds test length. The supplied defaults do not overlap. Evidence: `overlapping_oos_windows`.

**A20 — [P2] The locked-test protocol does not survive runs or lock full membership**

Locations: [run.py:136](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:136), [walk_forward.py:116](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:116), [walk_forward.py:120](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:120).

Every pipeline invocation creates a fresh lock object. No frozen specification is loaded or saved. Two full runs against the same output registry accepted changed test windows: 40-bar folds ending 1 December 2021 versus 30-bar folds ending 15 December 2021. The existing test named `test_locked_test_survives_across_pipeline_runs` only repeats an identical configuration and checks equal resulting dates; it does not attempt a changed specification.

Within one object, the hash includes only each test window's first and last timestamps. Removing an interior date from a 40-bar test is accepted by `verify` as the same frozen test, even though membership changes to 39 bars.

Fix: persist a research-family-specific lock over complete timestamps, dataset identity, and the executable evaluation specification. Require an explicit new family for a newly designed holdout, and record access/evaluation history if “evaluate once” is a requirement. Do not conflate legitimate new experiments with silent changes to the same claimed holdout. Evidence: `test_lock_membership` and `locked-test-pipeline-probe.json`.

**A21 — [P2] The raw-data contract permits invalid and fabricated OHLC values**

Locations: [validation.py:80](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:80), [validation.py:90](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:90), [loaders.py:98](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:98).

`validate_ohlcv` checks `high >= low` and positive finite prices, but not `low <= open/close <= high`. It does not reject positive infinity in volume. A bar with open/close 100, high 50, low 40, and infinite volume passes that validator. Later wide-panel validation catches infinite volume before the standard baseline features, but the raw-data validator and snapshot stage still accept it; impossible OHLC containment also matters to range features.

The wide CSV adapter invents open/high/low by copying close, without marking those columns as synthetic. Passing such normalized output to the Parkinson feature yields zero intraday ranges despite the input having no range observations. This contradicts the documented no-fabrication contract. The new Parkinson function itself has strong lag, dtype, and per-symbol validation tests; the integration risk lies in what its upstream schema claims to supply.

Fix: validate finite volume and full OHLC containment. Keep close-only data in an explicit close-only schema or require genuine OHLC for consumers that need it. Store field provenance and reject unavailable fields instead of manufacturing prices. Evidence: `ohlcv_validation` and adapter inspection.

**A22 — [P2] Sortino uses dispersion of losses instead of downside deviation**

Location: [metrics.py:34](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/metrics.py:34).

The denominator is the sample standard deviation of only negative returns. Equal-sized losses therefore have zero dispersion and produce an undefined Sortino despite meaningful downside exposure. Returns `[0.03, -0.01, 0.03, -0.01]` return **NaN**; explicitly using the all-observation zero-target downside deviation produces **22.449944** under the engine's annualization convention.

Fix: define the minimum acceptable return and observation denominator, implement downside semideviation, and test repeated equal losses, single losses, no losses, and all-loss paths. If a nonstandard ratio is intended, rename it rather than presenting it as standard Sortino. Evidence: `sortino_downside`.

**A23 — [P2] Saved evidence is insufficient for durable executable replay**

Locations: [run.py:296](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:296), [run.py:346](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:346), [snapshots.py:21](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:21), [pyproject.toml](/home/marnus/VS-Code/ML-2/pyproject.toml).

Records retain a configuration fingerprint but not the full configuration, complete executable model specification, fitted preprocessing/models, dependency lock, or actual source digest. The separate fold CSV includes thresholds, but cannot recover omitted model/execution settings. `CODE_VERSION = V2.1.3` is a manually maintained string. CLI replay also reloads the provider rather than accepting the exact stored snapshot as a dedicated mode.

The audit could reproduce the saved real baseline because its current config and source remain available and the snapshot was identifiable. That successful replay does not make the record independently sufficient after future config/code edits.

Dataset hashing formats prices and volume to ten decimal places. The probe changes a price by about `1e-12` and obtains an identical hash for numerically distinct data. This is a demonstrated precision collision, not a claim of a cryptographic SHA-256 collision. The hash is also truncated to 16 hex characters.

Fix: save a complete run manifest, full configuration and fold membership, provider/snapshot identity, source digest, dependency versions, and selected executable model state where appropriate. Hash losslessly canonicalized values and verify snapshot integrity on load. Make exact-snapshot replay an explicit CLI workflow. Evidence: `dataset_hash_collision`, current artifact schema, and the saved source manifest.

**A24 — [P3] The test suite writes raw snapshots outside its temporary output fixture**

Locations: [conftest.py:43](/home/marnus/VS-Code/ML-2/tests/conftest.py:43), [test_pipeline.py:73](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:73), [run.py:104](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:104).

`small_config` retains `data/raw_snapshots` as its relative snapshot directory. Passing a temporary artifact output does not redirect that separate data path. The complete suite created **eight snapshot metadata files plus corresponding data files under the isolated copy's `data/raw_snapshots`**. Running the same command in the real workspace would create them there. Several tests contain similar standalone configurations.

The audit avoided that side effect by copying the code/tests/configs into `/tmp`. Existing snapshots are not automatically loaded as a cache, so this finding is test pollution and operational ambiguity, not evidence that those synthetic files feed real-data runs.

Fix: use `tmp_path_factory` or per-test configurations for every filesystem destination, and assert that the project data directories are untouched after tests. Evidence: suite output-directory inspection.

**The saved real-data result, read honestly**

Audited artifact: [20260907T192434Z_b7d280a2f7b6276a_results.json](/home/marnus/VS-Code/ML-2/artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_results.json). Dataset snapshot: [20260907T192329Z_yfinance_ohlcv_b0e94186f465bc47.parquet](/home/marnus/VS-Code/ML-2/data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_b0e94186f465bc47.parquet).

| Measure | Reproduced/saved value | Interpretation |
|---|---:|---|
| Full OOS net Sharpe | −0.071213 | Negative under the current execution convention |
| Full OOS gross Sharpe | +0.157243 | Gross result before configured costs |
| Full OOS net compounded return | −5.476473% | Does not include the omitted boundary exits in A05 |
| Full OOS gross compounded return | +6.427191% | Same executed exposure path, before costs |
| Gross-minus-net compounded drag | 11.903663 percentage points | Not the same operation as summing daily fees |
| Sum of fee deductions | 9.880195% | Simple sum of return deductions |
| Sum of slippage deductions | 1.976039% | Simple sum of return deductions |
| Bootstrap Sharpe interval | [−0.689990, +0.657300] | Saved diagnostic; bootstrap was not rerun for this real snapshot |
| Bootstrap fraction SR > 0 | 0.486 | Saved resampling frequency, not a posterior probability |
| Feature-shuffle placebo percentile | 0.45 | Saved result |
| Feature-shuffle corrected p-value | 0.571429 | Saved result from 20 null runs |
| Positive folds | 3 of 7 | Three negative folds and one flat fold complete the seven |
| Flat fold | 24 Jan 2023–24 Jan 2024 | Zero turnover; undefined Sharpe is expected for all-zero returns |
| State | RESEARCH_ONLY | Saved failed gates: costs, delay, bootstrap positivity, placebo separation |

The OOS sample comprises **1,764 bars**, from 22 January 2018 through 27 January 2025. Input data extends through 31 December 2025, but the splitter drops the incomplete final fold. The remaining 2025 observations are not included in these OOS performance figures; the record's test-period fields disclose the shorter interval.

Mean and median fold Sharpes skip the flat fold's NaN, whereas the full OOS return stream includes its zeros. This is not a fake-label failure, but the effective fold counts for each statistic should be explicit. The existing ratio-based single-fold gate remains invalid as explained in A06. One JSON nonfinite value in the saved report is the `regime = all` level marker; using JSON null would be more portable than NaN.

The matched replay establishes reproducibility **under the present implementation**, not correctness of the execution convention or readiness for promotion. The negative net result and weak saved null/bootstrap evidence remain negative/weak after this audit. The block-null diagnostic should be regenerated after A03 is fixed, and any substantive strategy/execution change requires newly versioned evaluation.

**Status of the previous audit's main claims**

| Previous finding | Status verified now | Remaining work |
|---|---|---|
| 2.1: forward returns used as volatility observations | Fixed for the standard chronological baseline path | Economic return/fill contract remains inconsistent (A04); block-null risk chronology is broken (A03) |
| 2.2: per-fold volatility cold starts | Partially fixed | Historical risk returns warm scale, but signal/holding/position state still resets (A05) |
| 2.3: daily execution semantics | Open | A04 |
| 2.4: same-day drawdown reaction | Causal shift fixed | Initial peak and path-level drawdown remain wrong/incomplete (A15) |
| 2.5: selected hold/threshold discarded in candidate OOS | Direct forwarding fixed | Robustness loses hold again (A09); global discovery remains contaminated (A02) |
| 2.6: anti-overfitting functions not enforced | Open | A12; additionally PBO/DSR implementations are defective (A16–A17) |
| 2.7: per-run versus cumulative trial count | Per-run delta added | Coverage, scope, and concurrency still fail (A07/A13) |
| 2.8: misleading time-series HHI | Fixed | Absent weight matrix now produces null HHI; exposure/beta still use wrong inputs (A14) |
| 2.9: portfolio construction not integrated | Open | Main pipeline still scores baseline execution and uses proxy risk inputs |
| 2.10–2.11: small/single-mode placebo gate | Open | A12 |
| 2.12: Sortino definition | Open | A22 |
| 2.13: concurrent registry/counter safety | Partially changed | Atomic replacement exists; no transactional stale-writer protection (A07) |
| 2.14: rounded dataset hashing | Open | A23 |
| 2.15: incomplete executable manifest | Open | A23 |

**Why the tests did not catch the most serious defects**

| Existing coverage | Missing invariant |
|---|---|
| Information perturbation changes future event sentiment/timestamps | Adding or removing a later publication about an old event must not change history |
| Per-fold baseline selection isolation | Global discovered-candidate selection must also be isolated from later outcomes |
| Block placebo completes and returns finite values | Permuted values must actually change their association with dates after production alignment |
| Warm-start toy with one fixed random seed | All-long/invested boundary, holding-state persistence, and continuous cost reconciliation |
| PBO example with many variants | Rank thresholds must work for two variants and many folds |
| Trial counter manually lowered on disk | Two valid stale writer instances must not undo each other |
| Repeated identical pipeline configurations | Changed test membership/layout must be rejected within a locked research family |
| Default logistic / zero-delay replay | Every supported model and configured execution delay must complete the pipeline |
| Synthetic integrity checks over observed history | Entire missing symbols and leading/trailing provider truncation must be detected |

Do not add tests that merely assert current outputs as golden values for these paths. Use independent timing, accounting, rank, and prefix-invariance expectations; otherwise the wrong answer will become more firmly preserved.

**Additional observations and limits**

- `README.md` still says approximately 152 tests and describes the missing-data calendar as plain business days. The current suite has 210 collected cases and the source contains explicit NYSE holiday rules. The documented architecture also includes discovery and portfolio construction although the main run path does not execute those stages as described.
- The notebook manually runs data loading, baseline selection, and diagnostics, then invokes the full pipeline again. This duplicates computation and baseline trial increments, and real-data mode can obtain a new provider snapshot in the final cell. Its earlier feature-leakage cell does not pass information events to the leakage checker. Prefer one pipeline invocation whose retained intermediate outputs populate notebook displays.
- Event identity validation rejects duplicate IDs only when `raw_value` differs. It does not enforce uniqueness or version changes for processed value, sentiment, publication/availability timestamps, or source changes. Joining duplicate IDs can duplicate event contributions. Extend immutable event identity validation when hardening A01.
- The paper broker is an interface stub: `latency_bars = 1` is metadata, not a checked fill timestamp; duplicate protection is only whether the same order object is already filled. Quantity/side/price validation and safeguards are not enforced by `submit`. No live broker integration exists, consistent with the documented limitation; these stubs should not count as paper-validation evidence.
- Configuration dataclasses provide partial value checks, not runtime type/finite-value validation. Empty threshold sets, nonintegral delays, NaN costs, and nonpositive target volatility need explicit policy. The hardcoded US calendar is not instrument-specific and should have a declared historical coverage range before accepting arbitrary universes/start dates.
- Metrics generally discard NaN/infinity, and assertions using comparisons such as `abs(a-b) > tolerance` do not fail on NaN. Current full-path baseline metrics reproduced as finite, so this audit does not claim a hidden current NaN performance result. Add explicit finiteness and required-observation checks before reconciliation/promotion, while retaining meaningful undefined diagnostics for no-trade paths.
- No changes to purge windows are recommended solely because a causal feature has a long lookback. The older installed notebook skills refer to a different pipeline and a different purge contract. Purging should be justified by the actual label/information-overlap and evaluation policy of this engine.
- Provider-side data revisions, adjusted-price point-in-time properties, full historical calendar accuracy, capacity/market impact, and third-party dependency vulnerabilities were not established by this code audit. No fresh provider request, external account access, or trade was performed.

**Recommended remediation order and acceptance criteria**

1. **Establish one execution and evidence contract.** Resolve A04, then implement a continuous position/transaction ledger for A05. Use explicit signal/decision/fill/return timestamps. Require equality between full-history execution and scored slices, including invested fold boundaries and all fees. Make A14 and A15 consume that same ledger.
2. **Close historical-information contamination.** Make event aggregation prefix-invariant (A01) and selection nested or strictly pre-holdout (A02). Repair and separately test each null transformation and chronological risk history (A03).
3. **Make supported replay paths complete.** Carry the full executable specification, including hold and seed (A09); run end-to-end tests for every supported model, baseline delay, and permitted fold layout (A10/A11/A19).
4. **Repair promotion and statistical evidence.** Replace the fold concentration calculation (A06), set explicit null sample/significance requirements (A12), and validate PBO/DSR/Sortino against independent examples before using them (A16/A17/A22). Gate full-path drawdown and actual execution economics.
5. **Make governance durable.** Implement a transactional search ledger (A07/A13), research-family test lock (A20), requested-versus-realized data completeness (A08/A21), and a complete snapshot/code/config/environment manifest (A23).
6. **Rerun evidence only after those contracts are fixed.** Run regression probes and the full suite, then regenerate synthetic and exact-snapshot real reports in new artifact directories. Compare changed outputs with causal/accounting expectations. Treat any subsequent strategy selection using the current test history as additional research, with an appropriately separated future evaluation period.

**Evidence bundle and reproduction**

The permanent evidence directory is [audit_artifacts/2026-09-08](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-08).

| File | Contents |
|---|---|
| `audit_probes.py` | Twenty deterministic diagnostic probes; writes only below its own directory |
| `audit-probes-results.json` / `audit-probes.log` | Observed probe results and warnings |
| `audit_extra_probes.py` | Discovery perturbation, saved-real baseline replay, and full-pipeline lock probe |
| `discovery-selection-perturbation.json` | Winner changes after first-test/future-return perturbation |
| `real-baseline-replay.json` / `real-baseline-replay-folds.csv` | Exact saved-summary comparison, risk discrepancies, and omitted boundary costs |
| `locked-test-pipeline-probe.json` | Two completed runs accepting different test layouts in one registry |
| `pytest.log` / `pytest-results.xml` | Full existing-suite results |
| `source-manifest.json` | SHA-256 identity of the reviewed project files |
| `audit-metadata.json` | Runtime, scope, final integrity check, and evidence inventory |

To reproduce without adding test snapshots to the project, copy source/tests/configs, project metadata, and the probe scripts to a temporary directory; run from that directory. For example:

```bash
audit_dir=$(mktemp -d /tmp/ml2-audit-repro.XXXXXX)
cp -a /home/marnus/VS-Code/ML-2/src "$audit_dir/src"
cp -a /home/marnus/VS-Code/ML-2/tests "$audit_dir/tests"
cp -a /home/marnus/VS-Code/ML-2/configs "$audit_dir/configs"
cp /home/marnus/VS-Code/ML-2/pyproject.toml "$audit_dir/"
cp /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-08/audit_probes.py "$audit_dir/"
cp /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-08/audit_extra_probes.py "$audit_dir/"
cd "$audit_dir"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$audit_dir/src"
python3 -m pytest -v --junitxml=pytest-results.xml > pytest.log 2>&1
python3 audit_probes.py > audit-probes.log 2>&1
python3 audit_extra_probes.py selection > selection.log 2>&1
python3 audit_extra_probes.py real > real-replay.log 2>&1
python3 audit_extra_probes.py lock > lock-probe.log 2>&1
```

The diagnostic scripts intentionally demonstrate current defects; their successful execution does not mean the product behavior is correct. Their outputs should change when the corresponding fixes are made. The real replay reads the identified existing snapshot from the project and does not download data. No source fixes were made during this audit.
