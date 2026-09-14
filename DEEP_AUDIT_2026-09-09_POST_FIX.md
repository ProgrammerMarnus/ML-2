> **Historical audit snapshot.** “Current working tree” below means the tree
> audited on 2026-09-09, not the present repository. Later remediation is
> summarized in [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md).

# Deep audit — current working tree, 9 September 2026

**Assessment: retain `RESEARCH_ONLY`. I found 18 actionable findings: 6 high priority (P1) and 12 medium priority (P2). The statement that all previous findings are fixed is not supported by the current code.**

The existing suite passes: **242 passed, 1,907 warnings, 401.01 seconds**. Independent checks nevertheless reproduce future-information leakage, a broken documented real-data configuration, a contaminated discovery API, failures for nonzero execution delay, incomplete research-history controls, and lost experiment evidence. These are observed behaviors, not hypothetical deployment risks.

There is also substantial working code. The ordinary price-only baseline replays the saved market snapshot with **zero difference in its 1,764-row executed ledger** versus the previous post-fix replay. Its accounting reconciles. Several earlier defects are repaired. Those successes do not establish correctness of the alternative configurations and public APIs tested below.

**Scope and method.** I audited the current files, including the 27 pre-existing modified source/test files, rather than only Git HEAD. I read all active package modules, configuration, the orchestration notebook, relevant tests, and prior audit/fix evidence. The audit used the full test suite, 22 focused contract checks, additional discovery/statistics/return probes, three successful synthetic full-pipeline runs, a failing delayed full-pipeline run, and a full saved-market-data replay. The active notebook validates and its eight code cells compile; it was inspected but not executed separately. Historical material under `Initial Files - do not modify` was treated as reference material, not the active implementation. No provider downloads, orders, or external writes were made.

The 22 primary checks produced **16 contract failures, 6 passes, and no unexpected probe errors**. These counts are checks, not finding counts: some checks expose multiple related defects, and some findings come from integration/follow-up evidence. The old discovery/statistical fixtures were selectively reused against current source; the new contract and pipeline checks are saved separately. All source, tests, configuration, notebook, and existing market-data files were preserved, verified by hashes. This audit created only this report and the new evidence directory.

Evidence: [primary probes](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/probe-results.json), [pipeline checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/pipeline-probe-results.json), [follow-up checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/followup-results.json), [test summary](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/pytest-summary.txt), [preservation check](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/preservation-check.json).

**Priority index**

P1 means an issue blocks an advertised core workflow or undermines the validity of research evidence. P2 means a material correctness, data-contract, accounting, or reproducibility defect on a narrower path. No P0 incident was demonstrated.

| ID | Priority | Finding | Relation to previous audit |
|---|---|---|---|
| C01 | P1 | Information availability still compares incompatible timestamp units | B01 remains open |
| C02 | P1 | Calendar-day boundary tolerance rejects complete real data | Regression in B05 fix |
| C03 | P1 | Deprecated discovery still returns contaminated OOS evidence | B03 remains open |
| C04 | P1 | Configured nonzero delay breaks robustness and pipeline reconciliation | B08 remains open |
| C05 | P1 | Changing output directory resets research-family selection accounting | B10/B11 remain partial |
| C06 | P1 | Main pipeline does not persist its test lock; lock identity checks are incomplete | B12 remains partial |
| C07 | P2 | Nested replay omits boundary turnover from fold diagnostics | B06 remains partial |
| C08 | P2 | New model configuration fields are validated and recorded but ignored | New regression |
| C09 | P2 | Gradient-boosting parameter stress changes an unused parameter | B07 remains partial |
| C10 | P2 | Nonboolean exception values still waive availability ordering | B14 remains partial |
| C11 | P2 | Event identity validation crashes on repeats and accepts revision conflicts | B14 remains partial |
| C12 | P2 | Missing/invalid returns disappear from the scored timeline or metrics | Residual integrity gap |
| C13 | P2 | An existing counter accepts a reset below its high-water mark | B04 remains partial |
| C14 | P2 | Started/abandoned and discovery searches are incompletely accounted for | B11 remains partial |
| C15 | P2 | Every subsequent run overwrites the preceding reproducibility manifest | B16 remains partial |
| C16 | P2 | Manifest lacks replay inputs/code identity and misreports NumPy version | B16 remains partial |
| C17 | P2 | Wide CSV import fabricates open/high/low prices | B13 remains partial |
| C18 | P2 | Negative volatility targets turn long signals into short positions | Configuration defect |

**Detailed findings**

**C01 — [P1] Use the normalized availability values in the actual eligibility check.**

[information.py:195](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:195), [information.py:210](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:210).

The B01 patch normalizes bars and `canon_av_int` to microseconds, but the loop does not use `canon_av_int` to decide which events are live. It recreates `avail` from `canon_av.astype("int64")`, retaining the event array's original resolution, and compares that with microsecond bar integers.

**Reproduction:** keep an event's logical availability at 10 January 2024 and bars from 5–14 January. With event timestamps in seconds or milliseconds, its attention feature is already positive on **5 January**, five days early. With microseconds, it correctly starts on **10 January**. With nanoseconds, the event contributes on **none** of the ten bars. The same pattern occurs for all four bar resolutions: the 16 event/bar unit combinations produce 8 early-exposure cases, 4 correct cases, and 4 suppressed-event cases.

This directly violates the PIT contract. The default synthetic run in this environment uses a compatible resolution; a green test on that input does not cover the other valid resolutions. Pandas documents that the integer representation depends on datetime resolution and provides explicit conversion through `as_unit`. [Pandas integer representation](https://pandas.pydata.org/docs/dev/reference/api/pandas.DatetimeIndex.asi8.html), [resolution conversion](https://pandas.pydata.org/pandas-docs/version/3.0/reference/api/pandas.DatetimeIndex.as_unit.html).

**Acceptance:** use one consistent representation for every availability comparison, without rounding events backward across the eligibility boundary. Assert the first eligible timestamp and equality of all features for all 16 unit combinations, including delayed copies. Evidence: `probe-results.json → event_units`; `followup-results.json → timestamp_16_combinations`.

**C02 — [P1] Compare requested coverage with expected exchange sessions.**

[loaders.py:230](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:230), [loaders.py:245](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:245), [real_spy.yaml](/home/marnus/VS-Code/ML-2/configs/real_spy.yaml).

The new completeness check allows only one calendar day between requested and realized endpoints. That is insufficient when the interval begins or ends around weekends and exchange holidays. The module already imports an exchange-session calculator but does not use it for these endpoint comparisons.

**Reproduction:** the documented real configuration requests `start="2012-01-01"`. Feeding its own saved, validated SPY/QQQ snapshot through the actual post-download loader produces `DataValidationError: asset SPY: data starts 2012-01-03 but requested start is 2012-01-01; leading truncation detected`. No provider request was needed to reproduce this. A complete CSV covering 2–5 January 2024 also fails when the exclusive end date is Sunday, 7 January. An ordinary weekday-bounded control succeeds.

This is a regression introduced by the B05 fix. Rejecting missing symbols is correct; the endpoint rule now rejects complete data. Exchange holidays must be incorporated into coverage checks. [NYSE calendar rules](https://www.nyse.com/markets/hours-calendars).

**Acceptance:** derive the first/last expected sessions inside `[start, end)` and compare each requested symbol against them, with explicit listing-history exceptions if supported. Test the supplied real config, weekend endpoints, holiday weekends, actual leading/trailing missing sessions, and absent assets. Evidence: `calendar_boundaries`; `pipeline-probe-results.json → documented_real_config_loader`.

**C03 — [P1] Prevent contaminated legacy search results from being evaluated as untouched OOS.**

[discovery.py:106](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:106), [discovery.py:159](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:159), [test_pipeline.py:40](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:40).

`discover_strategies` still ranks candidates using validation results across the whole history. `evaluate_candidate_oos` still retrospectively applies the selected global winner to earlier test periods. Adding a `FutureWarning` documents the defect but does not restrict the unsafe composition, and an integration test still exercises it as OOS evaluation.

**Reproduction:** preserve the first fold's training/validation data; change only forward returns from its test start onward and keep labels consistent with those returns. The selected global winner changes from candidate **0 to 3**, and **all 40 first-fold predictions change**. Its validation data is unchanged. Later selection information is influencing earlier decisions.

The nested API is the appropriate direction and its existing causality tests pass. This finding concerns the still-callable legacy path, not a claim that ordinary baseline model fitting uses future rows.

**Acceptance:** remove or make the unsafe composition raise a clear exception, or require an explicit final holdout that begins strictly after every selection window. A warning is insufficient if the result still carries an OOS claim. Re-run the future-outcome perturbation and demonstrate that past decisions cannot change. Evidence: `followup-results.json → legacy_discovery`.

**C04 — [P1] Reconcile delay stress against the configured baseline using relative delay.**

[robustness.py:355](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:355), [robustness.py:266](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:266), [run.py:187](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:187).

The partial fix compares only when a stress delay equals the configured baseline delay, but passes that absolute delay into an assertion that interprets it as a shift relative to baseline. At a configured delay of one, the exact replay is required to equal itself shifted another bar. Separately, the orchestrator still insists that absolute delay zero has the baseline economics, even for a nonzero configured baseline.

**Reproduction:** a baseline with `signal_delay_bars=1` fits and evaluates, then `delay_stress` raises `delayed positions are not the baseline positions shifted by 1 bars over the continuous OOS path`. A complete synthetic pipeline with this configuration fails at the same assertion. Fixing only that assertion would expose the remaining zero-anchor comparison in `run.py`.

**Acceptance:** define absolute versus additional delay once. Require exact equality at the configured delay, compare other rows using the appropriate relative policy, and include the configured anchor even when it is outside the default grid. Test full workflows with configured delays 0, 1, and a value beyond the grid. Evidence: `configured_delay`; `pipeline-probe-results.json → full_pipeline_delay`.

**C05 — [P1] Make research-family history shared across output locations.**

[run.py:143](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:143), [promotion.py:169](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:169), [registry.py:219](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:219).

A stable family ID does not make separate files share history. The pipeline stores `search_ledger.jsonl` under `out`, then promotion counts only entries in that file. Moving the same research to a fresh artifact directory restores the family search count to one. The trial counter is also local to that directory.

**Reproduction:** two full synthetic runs with the same data, evaluation windows, and family ID (`1be09994aa1708b9`) complete in different output directories. Each records **family count 1** and passes the family-cap gate. Their synthetic results fail other gates, so this does not claim these particular runs were promoted. A separate otherwise-passing evidence fixture returns `CANDIDATE` with the default missing-ledger count of **0**, or with count 1, and rejects count 2. The gate works only when it receives trustworthy shared history.

Changing evaluation geometry also automatically creates a new family ID, without preserving a parent family for the overlapping evidence. That combines with C06 to make repeated recutting invisible to the intended cap.

**Acceptance:** introduce a durable, explicit research-family store independent of export directories, preserve lineage for intentionally changed evaluation policies, and reject promotion when required family evidence is absent. Re-run across different output directories and processes. Evidence: `pipeline-probe-results.json`; `followup-results.json → family_gate_no_ledger`.

**C06 — [P1] Wire persistent test locks into the pipeline and reject invalid lock state.**

[run.py:139](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:139), [walk_forward.py:135](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:135), [walk_forward.py:173](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:173).

Complete timestamp membership is now hashed, which correctly rejects removing an interior test bar within one lock instance. However, the main pipeline calls `LockedTestProtocol()` without a path, dataset ID, or persisted family policy. Every invocation therefore starts with a fresh lock.

**Reproduction:** two full runs in the same registry accept first 40-bar and then 30-bar test windows. Their last test dates change from **1 December to 15 December 2021**, and no persisted test-lock file exists. The current test named `test_locked_test_survives_across_pipeline_runs` only repeats identical settings, so it does not exercise this rejection requirement.

The optional persistent class also has gaps: freezing identical timestamps with dataset ID A, reopening, and freezing with dataset ID B is accepted; dataset identity is stored but never enforced. Malformed lock JSON is caught and converted into an unfrozen state, allowing a new lock. `_load_lock` expects a `spec` member although `_save_lock` writes the specification directly; the hash loads but the stored specification is not restored consistently.

**Acceptance:** persist and validate the full lock against a declared family before fitting; include actual timestamp membership and dataset policy; reject corrupt or incompatible state. Test process restarts, changed geometry, changed identity, corrupt JSON, and concurrent initialization. Evidence: `full_membership_lock`, `lock_roundtrip`, and `pipeline-probe-results.json → cross_run_checks`.

**C07 — [P2] Slice nested-replay turnover from the merged ledger.**

[baseline.py:311](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:311), [baseline.py:372](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:372).

The fold-restart executor correctly computes `turnover_full` over concatenated positions and uses it for net returns and total costs. But fold diagnostics later recompute `pos_f.diff()` independently. For every fold after the first, the first value is NaN, so the transition from the previous fold is omitted from `oos_turnover` and `oos_trades`.

**Reproduction:** a five-fold, five-bar-hold nested discovery run with a low threshold produces matching positions and net returns on no-override replay. Original fold turnover totals **9.0**; replay fold turnover totals **5.0**. `cost_stress` raises `delay=0 replay turnover differs`. Four boundary liquidations disappear from the replay diagnostics. This is narrower than the prior position-replay bug: the executable stream is now repaired in this case, but its fold accounting is not.

**Acceptance:** take each fold's turnover/trade diagnostics directly from `turnover_full.loc[te]`, including its first timestamp. Require equality of probabilities, positions, gross/net returns, total costs, per-fold turnover, and trade counts, then run the full robustness battery for nested strategies. Evidence: `probe-results.json → nested_replay`.

**C08 — [P2] Resolve the new configuration fields into the executed model and holding rule.**

[config.py:112](/home/marnus/VS-Code/ML-2/src/quant_research/config.py:112), [baseline.py:66](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:66), [baseline.py:144](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:144).

`ModelConfig` now exposes `logreg_C`, `gb_learning_rate`, `gb_n_estimators`, and `hold_bars`. They are validated and serialized into the configuration fingerprint, but `build_model` reads only `parameters`, and ordinary walk-forward execution uses its separate `hold_bars=1` argument. The comment that effective parameters are resolved by `build_model` is inaccurate.

**Reproduction:** request `logreg_C=0.001`: the estimator uses **C=1.0**. Request gradient-boosting learning rate 0.7 and 7 estimators: it uses **0.05 and 100**. Request `cfg.model.hold_bars=5`: the result records and executes **hold 1**. Thus distinct recorded configurations can silently execute the same strategy.

**Acceptance:** define one authoritative effective configuration, including precedence between legacy `parameters` and explicit fields; reject conflicts or resolve them visibly. Thread the holding rule through baseline execution and replay. Verify actual fitted estimator settings and resulting position timing, not only dataclass validation. Evidence: `configured_model_parameters`.

**C09 — [P2] Perturb a parameter that gradient boosting actually consumes.**

[robustness.py:370](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:370), [baseline.py:76](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:76).

Model identity checks no longer unconditionally access logistic coefficients, so gradient-boosting cost replay is improved. Parameter stress, however, still modifies only `params["C"]`. The gradient-boosting constructor ignores C. Its advertised stress reruns therefore fit the same estimator settings.

**Reproduction:** factors 0.5 and 2.0 produce exactly the same net Sharpe (**−1.2665979093**), return, positions-derived turnover, and fees. The unchanged metrics are supported by the direct source defect: no consumed gradient-boosting hyperparameter changes. This cannot be interpreted as evidence of robustness to model parameter variation. The estimator exposes parameters such as learning rate, tree count, and depth. [Scikit-learn estimator reference](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingClassifier.html).

**Acceptance:** choose and record model-specific perturbations with a declared rationale. Check the actual estimator parameter delta; a factor-one replay must match baseline, while stress must change the intended effective parameter without reselecting thresholds. Evidence: `gradient_parameter_stress`.

**C10 — [P2] Require a typed boolean before waiving timestamp ordering.**

[point_in_time.py:117](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:117).

The patch rejects a list of common string values, including `"False"`, then converts remaining values using `.astype(bool)`. That accepts arbitrary nonempty strings, nonzero numbers, and floating NaN as true. A malformed exception flag can still waive both availability-before-event and availability-before-publication validation.

**Reproduction:** an event dated 10 January but marked available on 1 January is accepted with `provider_rule_exception="unexpected"`, **2**, or **NaN**. Explicit false and the string `"False"` are rejected, while explicit true is accepted as intended.

**Acceptance:** validate the column's values against an explicit boolean contract; define missing values as false or reject them. Do not infer authorization from truthiness. Require the documented exception rule if that is part of the provider schema. Cover object/string/nullable-boolean/numeric inputs. Evidence: `exception_types`.

**C11 — [P2] Validate event identity per revision and handle repeated records without runtime errors.**

[point_in_time.py:150](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:150).

The identity check skips an entire repeated-event group whenever it contains more than one revision. Consequently, the presence of a second revision exempts conflicting records within the first revision. On the nonrevision branch it also assumes optional `sentiment` exists and calls `Series.view`, which is unavailable in the installed pandas version.

**Reproductions:** two records with the same event ID and revision 0 but conflicting sentiment are accepted when a third record with revision 1 is added. Two identical records with sentiment instead raise **AttributeError: Series has no attribute view**. Omitting the schema-optional sentiment field produces **KeyError: sentiment**. These are not deliberate `DataValidationError` rejections with a usable contract.

**Acceptance:** define immutable identity and revision keys, validate every `(event_id, revision)` group independently, handle optional fields explicitly, and deduplicate identical repeats or reject them intentionally. Use a supported datetime conversion. Test repeated ingestion and conflicting revisions through both validation and feature construction. Evidence: `identical_event_ids`, `revision_conflict`.

**C12 — [P2] Reject or explicitly model missing and non-finite realized returns.**

[baseline.py:235](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:235), [baseline.py:347](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:347), [metrics.py:15](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/metrics.py:15).

Rejecting `step_bars > test_window` closes configured gaps but does not ensure a continuous realized-return ledger. Walk-forward execution removes test rows whose forward return is NaN, then concatenates the remaining timestamps and carries position state across them. Infinite returns are not excluded by `.notna()`; metric cleaning subsequently drops infinity even when it remains in the execution stream.

**Reproductions:** one missing interior return reduces a **200-row** OOS stream to **199 rows**, retaining position **1.0 immediately before and after** the missing bar. There is no explicit liquidation or missing-interval policy. A separate infinite forward-return probe produces an **infinite net-ledger row while all five reported fold Sharpes are finite**.

The validated normal-price pipeline did not produce invalid ledger rows in the saved-market replay. This finding concerns the reusable backtest/walk-forward APIs and their integrity boundaries; it does not allege infinity in the reported market result. Permuting labels/returns can also move an endpoint NaN into the interior, so null experiments need a declared valid-sample timeline policy.

**Acceptance:** validate finite realized returns before scoring, distinguish a known terminal unobservable return from interior missing observations, and retain or reject timeline gaps explicitly. Never present finite aggregate metrics as a clean result while the executable ledger contains non-finite observations. Evidence: `missing_returns`; `followup-results.json → nonfinite_forward_return`.

**C13 — [P2] Check the high-water invariant after reloading under the increment lock.**

[registry.py:188](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:188).

File locking repairs the demonstrated stale-writer race: two objects incrementing by 100 and 1 now leave 101. However, `increment` reloads count/high-water without rechecking `current_count >= current_high`, even though the constructor enforces that invariant.

**Reproduction:** construct a counter, increment it to 100, reset only its count file to zero, and reuse the existing object. `increment(1)` succeeds and exposes **count=1, high-water=100**. A fresh instance would reject this state, but the active instance can already feed its lowered count into registry/promotion code.

**Acceptance:** after acquiring the lock and reloading, reject or recover a count below high-water before modifying anything. Cover a reset after construction and persistence interruptions. Keep the stale-writer regression that now passes. Evidence: `stale_counter` and `live_counter_reset`.

**C14 — [P2] Count research attempts before evaluation and cover every selection entry point.**

[registry.py:291](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:291), [run.py:149](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:149), [discovery.py:225](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:225), [discovery.py:329](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:329).

This is separate from C05's storage location. Even within one ledger, family counts include only completed or explicitly aborted outcomes. A recorded start with no outcome contributes **zero**. Search entries lack a unique attempt ID connecting start and completion, and malformed JSON lines are silently skipped. The main pipeline records one baseline search but does not integrate this ledger with public discovery.

**Reproductions:** a started search counts zero until its outcome is appended. A completed legacy search and four-fold OOS evaluation leave a supplied trial counter at **zero**. Nested discovery performs candidate search before incrementing its counter later during OOS evaluation. In a full eight-fold baseline run, the search ledger records **n_trials=2** while the experiment counter records **16 threshold trials**; the field does not describe the full operation it labels.

Predeclared null repetitions and deterministic execution replays need not be treated as independent hypotheses. The defect is the absence of a consistent, persisted distinction between those diagnostics, discretionary searches, and interrupted attempts. The notebook also performs a selection before calling the full pipeline, outside its new search ledger.

**Acceptance:** assign durable attempt IDs and record starts before selection; count unresolved attempts conservatively; reconcile actual candidate/fold evaluations; cover baseline and both discovery entry points. Define which ablations and nulls are predeclared diagnostics versus additional research. Evidence: `search_ledger_scope`, `legacy_discovery_accounting`, and pipeline `search_entries`.

**C15 — [P2] Store manifests under immutable experiment-specific names.**

[snapshots.py:249](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:249), [run.py:407](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:407).

Every run writes the same `run_manifest.json` with `write_text`. The registry/results are experiment-specific, but their manifest locator points to a mutable shared file. A subsequent run replaces the previous run's saved predictions, positions, returns, and provenance.

**Reproduction:** write manifests for experiments A and B into one directory. The returned paths are identical and A's path now contains B. This is also reproduced with two complete pipeline runs: the first report's manifest path resolves to the second experiment. The remaining per-experiment results file does not preserve the manifest's executable arrays, so this is real evidence loss.

**Acceptance:** use an experiment ID/content-addressed filename, avoid overwriting existing evidence, and save the durable locator in the immutable record. Stage or transactionally publish the artifact set so a failed manifest write does not leave a completed-looking registry record. Evidence: `manifest_overwrite`; `pipeline-probe-results.json → cross_run_checks`.

**C16 — [P2] Preserve sufficient replay provenance and record the correct environment.**

[snapshots.py:135](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:135), [snapshots.py:163](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:163), [snapshots.py:238](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:238), [run.py:378](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:378).

The new manifest is useful for checking saved outputs, but the claim of a complete independently reproducible executable experiment is too strong. It stores feature column names and endpoints rather than feature values/hash; event presence/count rather than event content or an immutable event artifact; fold endpoints/counts rather than full training/validation membership; and fitted model class names rather than fitted state. It also omits persisted custom risk inputs and the full per-fold holding/model specification exposed by `ExperimentResult`.

For dirty code, Git HEAD plus a boolean does not identify the source that ran. Different uncommitted implementations produce the same provenance fields. `git diff --quiet` also ignores staged-only changes and untracked source. The environment capture contains a direct error: `"numpy": pd.__version__`.

**Reproduction:** the full-pipeline manifest records **NumPy 3.0.5**, while the executing NumPy version is **2.5.2**. Its event object has only `present`/`n_events`, its feature object only columns/endpoints/count, and a fitted model entry only `model_type: LogisticRegression`. The new full-precision market hash does distinguish small price changes; that isolated improvement is confirmed by the existing tests.

**Acceptance:** export either reloadable fitted models and their preprocessing or a complete retraining specification with all immutable input artifacts and full code identity; preserve the effective per-fold execution specification. Correct the dependency versions. Test reconstruction in a fresh process using only the exported experiment bundle, rather than presence of JSON keys. Evidence: pipeline `versions`, `manifest_*` fields and saved `run_manifest.json`.

**C17 — [P2] Do not label close-only CSV values as measured open/high/low prices.**

[loaders.py:79](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:79).

The wide CSV adapter still assigns the close column to open, high, low, and close. The improved OHLC validator accepts this fabricated zero-range schema because its inequalities are internally consistent. Range-dependent features can then consume an invented history without any marker that the fields were synthesized.

**Reproduction:** a CSV with only timestamp, `Close_SPY`, and `Volume_SPY` becomes 21 accepted OHLCV rows with **high=low=open=close on every row**. This invalidates the meaning of range measures such as the exposed Parkinson-volatility feature. The ordinary baseline currently consumes close/volume, so the finding is scoped to the data contract and downstream range consumers.

**Acceptance:** support an explicit close/volume-only schema with corresponding capability restrictions, or require measured OHLC input. Never make absent range data appear measured. Evidence: `wide_csv_range`.

**C18 — [P2] Require a positive volatility target.**

[config.py:83](/home/marnus/VS-Code/ML-2/src/quant_research/config.py:83), [config.py:103](/home/marnus/VS-Code/ML-2/src/quant_research/config.py:103), [backtest.py:78](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:78).

Execution configuration now rejects non-finite targets but does not require them to be positive. `_vol_target_scale` divides the target by positive realized volatility and clips only its upper bound. A negative target produces negative sizing, reversing the direction of a nominally long signal.

**Reproduction:** `ExecutionConfig(target_vol=-0.1)` is accepted. An always-long signal then produces **319 short-position bars**, with minimum position **−0.90518** in the deterministic probe. A zero target is also accepted and produces a degenerate flat strategy.

**Acceptance:** reject nonpositive targets unless zero has a separately documented disable-trading meaning. If shorting is supported, express direction through the strategy specification rather than the sign of a risk target. Verify configuration rejection and long-signal position direction. Evidence: `negative_target_vol`; `followup-results.json → negative_target_position`.

**Revalidation of the previous 18 findings**

The final table in [FIXES_SUMMARY.md](/home/marnus/VS-Code/ML-2/FIXES_SUMMARY.md) marks every finding fixed. The current evidence supports the following narrower assessment. `Verified` here describes the stated reproduced defect, not certification of an entire module.

| Previous ID | Current assessment | Fresh evidence / remaining work |
|---|---|---|
| B01 | Open | C01: actual eligibility comparison still has a unit mismatch |
| B02 | Verified fixed for arrival-order case | Adding a delayed earlier publication leaves prior features unchanged and available events still contribute |
| B03 | Open | C03: global winner 0→3; all 40 earlier predictions change |
| B04 | Partial | Stale objects now total 101; C13 retains an active-object high-water violation |
| B05 | Partial, with regression | Missing symbols are rejected; C02 blocks complete data for supplied real config |
| B06 | Partial | Subset/custom-risk/five-bar-hold replay matches; nested positions/net match but C07 turnover does not |
| B07 | Partial | Logistic-only coefficient crash addressed; C09 leaves boosting parameter stress ineffective |
| B08 | Open | C04 fails the supported nonzero-delay workflow |
| B09 | Fixed for configured gaps | `step_bars > test_window` is rejected; C12 covers a distinct route to timeline gaps |
| B10 | Partial | Gate reacts to count 2, but missing/local history bypasses intended protection: C05/C14 |
| B11 | Partial | Starts/outcomes exist, but C05/C14 prevent durable comprehensive family accounting |
| B12 | Partial | Interior membership edits rejected in-memory; C06 shows pipeline persistence/identity gaps |
| B13 | Partial | OHLC containment, infinite volume, duplicate sessions rejected; C17 remains |
| B14 | Partial | String `"False"` blocked; C10/C11 retain coercion/revision/repeat defects |
| B15 | Verified fixed for original one-feature stress | Masked feature rows no longer recut that baseline's geometry |
| B16 | Partial | Full-precision hash and output arrays added; C15/C16 prevent durable independent replay |
| B17 | Verified fixed | Expected maximum Sharpe for one zero-mean trial is 0 |
| B18 | Improved; no pollution observed | Full suite and audit left existing `data/` contents byte-identical |

An important evidence-quality issue is the earlier revalidation method: several probes assert that a defect exists. Their `AssertionError` after a repair can be expected, but a runtime exception, schema rejection, or failed fixture does not establish that the intended end-to-end behavior now works. For example, a failed nested-position assertion does not test fold turnover, and a zero-delay-only probe does not test the configured nonzero-delay anchor. This audit distinguishes contract failures, expected validation rejections, and unexpected probe errors.

**Saved market snapshot: economic and accounting readout**

I reran the configured research computations on the saved SPY/QQQ snapshot `b0e94186f465bc47`, verifying its hash. Only download/snapshot-write I/O was substituted. Consequently this validates the downstream computation on that data; it **does not** clear the loader regression in C02. The full pipeline performed its ordinary robustness, 500-resample bootstrap, and 20 repetitions of each of three placebo modes. A separate 2,000-resample bootstrap was added for the audit readout, leaving the recorded run unchanged.

The dataset extends through **31 December 2025**, but the full-fold-only policy scores **1,764 forward-return intervals indexed 22 January 2018 through 27 January 2025**. The final interval ends at the following close. The incomplete trailing fold is not evaluated; these figures must not be described as performance through December 2025. This policy matches the prior replay.

| Metric | Strategy, after 5 bps fee + 1 bp slippage | SPY buy/hold on the same intervals |
|---|---:|---:|
| Total return | −5.16% | +139.49% |
| Annualized return | −0.75% | +13.29% |
| Sharpe | −0.0649 | 0.7385 |
| Sortino | −0.0856 | 1.0276 |
| Calmar | −0.0329 | 0.3941 |
| Maximum drawdown | −22.93% | −33.72% |
| Annualized volatility | 7.42% | 19.48% |
| Nonzero-return hit rate | 44.16% | 55.23% |

The benchmark is an unlevered reference with no additional simulated entry/exit fee. It has substantially more exposure: the strategy averages **25.90% gross exposure** and holds nonzero positions on **42.18% of scored bars**. Cash interest, financing, and an asset-size-dependent impact model are not part of this engine's reported result. Its lower drawdown therefore must be interpreted alongside lower exposure and lower return.

The strategy's gross return is **+6.76%**, gross Sharpe **0.1633**, and compounded gross-to-net drag **11.93 percentage points**. Summed turnover-based fees are 9.87% and slippage 1.97% in the engine's return accounting; their simple sum is not identical to compounded drag. Annual turnover is **28.20**. Bar-level costs and fold turnover reconcile in this ordinary continuous baseline.

| Fee stress, with slippage fixed at 1 bp | Net Sharpe | Net total return |
|---|---:|---:|
| 0 bps | 0.1253 | +4.68% |
| 2.5 bps | 0.0302 | −0.36% |
| 5 bps | −0.0649 | −5.16% |
| 10 bps | −0.2544 | −14.08% |
| 20 bps | −0.6297 | −29.49% |

The measured grid brackets zero total return between **0 and 2.5 fee bps**, with slippage still 1 bp. Zero Sharpe is bracketed between 2.5 and 5 fee bps. These are different break-even definitions. The engine uses a linear turnover-cost model; a multi-component spread/participation-impact stress is not implemented and was not fabricated for this audit.

Additional absolute signal delays 0/1/2/3 produce net Sharpes **−0.0649 / 0.2285 / 0.1446 / −0.0480** on the configured zero-delay baseline. The gate requires survival across its selected stressed rows, so the negative three-bar result makes delay survival fail. This is a sensitivity diagnostic, not authorization to choose the best delay after seeing test performance.

The audit's **2,000-resample block-bootstrap 95% Sharpe interval is [−0.6936, 0.7109]**, with **P(Sharpe > 0)=0.492**. It spans zero: **the positive-edge claim is not statistically significant under this bootstrap**. The pipeline's original 500-resample interval is [−0.6811, 0.6641], P=0.496. The Monte Carlo difference is expected; no experiment settings were retuned.

All three null comparisons are weak:

| Placebo mode | Observed percentile | Conservative Monte Carlo p-value | Valid repetitions |
|---|---:|---:|---:|
| Feature shuffle | 45% | 0.5714 | 20 |
| Joint target/return permutation | 20% | 0.8095 | 20 |
| Block target/return permutation | 5% | 0.9524 | 20 |

These null statistics use **mean fold Sharpe (0.1290)** as defined by the pipeline, whereas the bootstrap/headline use **the full path Sharpe (−0.0649)**. They are different statistics and should not be interchanged. Promotion currently consumes the feature-shuffle object; the other two are diagnostics. Family governance limitations in C05/C14 remain even if an individual Monte Carlo calculation is internally consistent.

| Fold test window | Strategy Sharpe | Strategy return | SPY return on same intervals |
|---|---:|---:|---:|
| 2018-01-22 → 2019-01-22 | −1.2645 | −13.03% | −5.05% |
| 2019-01-23 → 2020-01-22 | 0.5455 | +0.39% | +28.32% |
| 2020-01-23 → 2021-01-21 | −0.5862 | −5.50% | +17.58% |
| 2021-01-22 → 2022-01-20 | 0.9373 | +8.67% | +15.92% |
| 2022-01-21 → 2023-01-23 | −0.0609 | −0.89% | −7.14% |
| 2023-01-24 → 2024-01-24 | Undefined: flat | 0.00% | +23.80% |
| 2024-01-25 → 2025-01-27 | 1.2026 | +6.72% | +25.46% |

There are **3 positive, 3 negative, and 1 flat folds**. The flat fold's Sharpe is undefined because its return variance is zero; this is an explained NaN, not a non-finite executed ledger. Mean/median fold Sharpe ignore that undefined ratio, so they describe six defined folds. Long/cash exposure accounts for part of the substantial lag in rising SPY periods.

The pipeline's regime slices report net Sharpes **0.2185 in lower volatility** and **−0.2647 in higher volatility**; the corresponding slice returns are +4.05% and −8.85%. Its shallow/deep drawdown slices report **−0.2710 / 0.3168**, with returns −9.52% / +4.81%. These are descriptive subsets of the ledger, not separately executable continuous portfolios; regime-slice drawdown should not be substituted for whole-portfolio drawdown.

Mean fold AUC is **0.5010**. Pooled Brier score is **0.25205**, log loss **0.69762**, and ten-equal-width-bin ECE **0.04202**. For example, the 0.6–0.7 probability bucket averages 0.6306 predicted probability but 0.5156 observed positive frequency over 192 rows. The full reliability table is in the supplemental artifact. This active baseline has no separate probability calibrator and uses one logistic model per fold; calibrated-vs-raw and ensemble-weight comparisons are therefore not applicable.

**Reconciliation:** timestamps, positions, turnover, gross returns, and net returns match the previous post-fix saved ledger exactly after CSV loading: maximum absolute delta **0.0**. The new configuration fields change metadata/fingerprints but do not change this default executable baseline. All scored ledger values are finite. The strategy remains `RESEARCH_ONLY`, failing cost survival, delay survival, bootstrap-positive-probability, and placebo separation.

Evidence: [market replay](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/market-replay-analysis.json), [ledger comparison](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/run-diff.json), [supplemental bootstrap/calibration/folds](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/supplemental-readout.json).

**Coverage, limitations, and recommended order**

The existing tests provide useful coverage of ordinary causal scaling, fold-local fitting, continuous baseline accounting, future-data feature perturbation, permutation ordering, statistical formulas, and Parkinson-volatility indexing. Fresh checks also confirm the repaired initial-capital drawdown and downside-deviation formulas, the demonstrated PBO ranking case, the one-run-null rejection, arrival-order clustering, custom-risk/subset/hold replay, and the original missing-feature stress case.

Coverage is thin where the remaining defects cluster: combinations of model family, nondefault delay, nested execution, persistent state across processes/locations, supported datetime resolutions, malformed-but-plausible event inputs, and artifact reload. In particular, neither a warning nor JSON-key presence is an adequate acceptance test for leakage removal or reproducibility.

The paper broker and safeguard modules were inspected. They are separate simulation interfaces; the broker does not itself enforce the safeguard object, actual fill timestamps, or a live account ledger. There is no live broker adapter in the reviewed package. That is a documented scope boundary, not a demonstrated live-order exploit. Dependency minimums are recorded in `pyproject.toml`; there is no pinned portable environment bundle. No dependency vulnerability database scan or provider connectivity test was performed, and this report does not certify either. The legacy audit skills describe an older notebook architecture, so their conceptual checks were applied where relevant without imposing obsolete stage/file assumptions.

Recommended remediation order:

1. **Restore evidence validity:** C01/C03/C10/C11, with adversarial PIT and future-outcome tests that assert the correct result.
2. **Restore advertised workflows:** C02/C04/C07; test the supplied real config through the actual loader boundary and run the full battery for nonzero delay and nested strategies.
3. **Make governance durable:** C05/C06/C13/C14, with shared family identity, process-safe state, counted starts, and rejection of missing/corrupt evidence.
4. **Make recorded experiments executable:** C08/C09/C15/C16; resolve configuration once and reload a complete immutable bundle in a fresh process.
5. **Close reusable API boundaries:** C12/C17/C18; preserve the timeline and prohibit fabricated or invalid financial inputs.

After remediation, rerun the existing suite and the specific acceptance cases above. Reconcile the same saved-market ledger before evaluating any new data or changing strategy choices. Do not promote a strategy based on selectively improved stress parameters or on a historical test period repeatedly used to guide research.

Reproduction scripts are saved under [the audit evidence directory](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09-post-fix/README.md). The audit changed no product implementation and applied no fixes.
