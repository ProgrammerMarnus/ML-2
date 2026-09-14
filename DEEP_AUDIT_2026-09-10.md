> **Historical audit snapshot.** This report describes commit
> `44c85c340699081b0b209cfc2a8326ee613cd2fc`; its suite result and open
> findings are preserved as evidence, not current status. See
> [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md).

**Deep audit — ML-2, 10 September 2026**

**Assessment: retain `RESEARCH_ONLY`. The current tree has 15 actionable findings: five P1 and ten P2. Several recent fixes work, but the assertion that the earlier audit criteria are fully satisfied is unsupported.**

Audited commit: `44c85c340699081b0b209cfc2a8326ee613cd2fc`. The working tree was clean before this audit. Scope covered all 37 Python modules, 26 test modules, both configurations, the active notebook, the latest fix summary, prior audit evidence, and saved market results. No engine, test, configuration, notebook source, original snapshot, or original research-history file was changed. New work is this report and its [evidence directory](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10).

The full suite produced **280 passed, 1,918 warnings, and one teardown error in 323.61 seconds**. The error is a reproducible research-ledger isolation defect, not a failed model assertion. Tests ran against a byte-identical source/test/configuration copy with fresh project state. A follow-up run of the affected test passed after the ledger already existed, while silently appending to that file. This explains how an established workspace can report a green suite despite the defect. [Full test log](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pytest.log), [repeat evidence](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/isolation-repeat-results.json).

Four complete synthetic pipeline runs reproduced cross-run behavior. A complete market run reused the verified saved SPY/QQQ snapshot, stubbing only the provider download; the normal loader, coverage checks, snapshot writer, model fitting, robustness battery, all three placebo modes, registry and promotion gates executed. Its 1,764-row positions/returns/turnover ledger matches the previous audit within **1.12 × 10⁻¹⁶**. There is no demonstrated change in the saved-market baseline economics. There are substantial defects in alternative configurations and in the controls that are supposed to make subsequent research trustworthy.

**Priority and scope**

P1 means a core advertised workflow fails or research evidence can be invalidated under a supported usage path. P2 means a narrower correctness, integrity, validation, or reproducibility defect. No P0 incident or live-order exposure was demonstrated. Synthetic reproductions establish software behavior; they are not evidence of market profitability.

| ID | Priority | Finding | Previous finding |
|---|---|---|---|
| D01 | P1 | Changed policy or corrupt state silently replaces the supposedly locked test | C06; residual C05 |
| D02 | P1 | Promotion ignores abandoned or missing research history; discovery records its start too late | C05/C14 |
| D03 | P1 | Baseline accepts missing or infinite returns at ordinary fold ends | C12 |
| D04 | P1 | Discovery drops missing outcomes before forming folds, changing the scored timeline | C12 |
| D05 | P1 | Nested-strategy replay crashes on undefined `turnover` | Regression in C07 |
| D06 | P2 | Factor-1 model stress does not preserve explicit baseline parameters | C08/C09 |
| D07 | P2 | A baseline delay beyond the stress grid receives no baseline or slower-delay test | Residual C04 |
| D08 | P2 | One missing boundary session is silently accepted and reported complete | Residual C02 |
| D09 | P2 | Parkinson volatility consumes explicitly fabricated ranges | Partial C17 |
| D10 | P2 | Null revisions and missing values bypass event-identity checks | Residual C11 |
| D11 | P2 | Repeated delivery of the same event changes information features | Residual C11 |
| D12 | P2 | Tests mutate shared research history; existing-file mutations escape the guard | Regression of B18 |
| D13 | P2 | Several regression tests do not test their named acceptance criteria | Cross-cutting |
| D14 | P2 | Complete replay provenance remains absent; registry records omit manifest locations | Open C16; residual C15 |
| D15 | P2 | Microsecond conversion rounds a future nanosecond event into the current bar | Precision edge of C01 |

**Detailed findings and acceptance criteria**

**D01 — [P1] A changed configuration unlocks the test it is meant to protect.**

[walk_forward.py:136](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:136), [walk_forward.py:171](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:171), [walk_forward.py:239](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:239), [run.py:140](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:140).

The pipeline now persists a lock, and its full-membership hash detects a changed window when the configuration identity is unchanged. However, `_load_lock` clears the frozen state when the dataset or configuration fingerprint differs, or when parsing fails. `verify` then treats the cleared object as a new lock and writes the replacement. This is acceptance of incompatible state, despite comments describing it as rejection.

**Reproduction:** identical-policy recutting raises `LockedTestViolation`, as it should. Changing the configuration fingerprint first permits the recut. Reopening with another dataset is also accepted. Replacing the file with invalid JSON permits a new layout. In two complete pipeline runs using the **same output directory**, the 40-bar tests ending on 1 December 2021 were replaced by 30-bar tests ending on 15 December 2021. Both runs completed. The changed evaluation policy also created a new family ID and reset that family's apparent search count to one. This combines lock replacement with loss of overlapping-evidence lineage.

**Impact:** an ordinary configuration edit can reuse and recut previously examined test observations while the artifacts still describe locked OOS research. Putting a lock file in a new output directory supplies another fresh lock; the shared family ledger does not prevent that recut when the family ID changes.

**Acceptance:** reject corrupt/incompatible persisted state before fitting or selection; do not convert it to an unfrozen object. Declare a durable research-family identity independent of export paths and preserve parent/overlap lineage when evaluation geometry or data versions change. Keep immutable test membership under that family. Test actual `verify` calls across process restarts, changed policies/datasets, corruption, different output paths and concurrent initialization. The current tests asserting `frozen is False` must instead require the dependent evaluation to be rejected. Evidence: [lock probes](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json), key `locks`; [pipeline checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pipeline-check-results.json).

**D02 — [P1] The promotion gate consumes incomplete research history.**

[run.py:365](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:365), [registry.py:352](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:352), [registry.py:255](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:255), [promotion.py:72](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:72), [discovery.py:195](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:195).

`family_attempt_count` correctly links starts and outcomes, but the pipeline calls the older `family_search_count`, which counts only completed/aborted outcome rows. A start without an outcome remains invisible to promotion. Missing history defaults to zero and is accepted by the family-cap gate. Malformed JSON lines are silently skipped. Separately, discovery evaluates its candidate grid before recording the start at line 225, so an interruption during the search leaves no start at all. The trial increments also occur later during OOS evaluation.

**Reproduction:** one abandoned start plus one completed search gives `family_search_count=1` and `family_attempt_count=2`. In an otherwise-passing evidence fixture, the count used by the pipeline returns **`CANDIDATE`**, while the correct attempt count returns **`RESEARCH_ONLY`**. Zero history also returns `CANDIDATE`. Corrupting a previously populated ledger causes its reader to return an empty history and count zero. Injecting an interruption into discovery's validation search produces **zero ledger entries and zero recorded attempts**.

The shared project ledger is a real improvement: identical research in two output directories now produces family counts **1 then 2**, and the second run fails the family cap. That closes the basic output-directory bypass. It does not close the incomplete-history paths above. The supposedly global trial counter itself remains local to each output directory: both separate-output synthetic runs report 16, not a project-wide total.

**Acceptance:** make verified attempt history mandatory at promotion; include abandoned starts exactly once and fail on missing/corrupt required history. Record discovery attempts before evaluating candidates. Preserve the family lineage addressed in D01. Clearly distinguish per-output counters from genuinely shared research counts. Test a full orchestration path with an interrupted attempt, then an otherwise-passing result; a helper-only count test is insufficient. Evidence: `attempts_and_gates`, `corrupt_search_ledger`, and `discovery_aborted` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D03 — [P1] The terminal-return exception also applies to internal fold boundaries and infinity.**

[baseline.py:279](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:279), [metrics.py:15](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/metrics.py:15).

The new guard allows one non-finite value at the last position of *any test fold*. It does not require that timestamp to be the end of the complete dataset, and it does not restrict the exception to NaN. The earlier `notna` filter removes NaN but retains infinity. Consequently a missing internal return disappears from the timeline, while an infinite return remains in the ledger. Metric cleaning replaces infinities with NaN and drops them, producing finite-looking statistics from a corrupted path.

**Reproduction:** set the first fold's final return, **21 October 2020**, to NaN while retaining all later data. Evaluation succeeds, loses that bar and returns **319 instead of 320** OOS observations. The strategy is long on both sides of the missing interval; the omitted return and ordinary position continuity are not reconciled by a gap policy. Set the same return to infinity and evaluation succeeds with a **non-finite 320-row return ledger**. Moving the NaN into the interior of the same fold correctly raises, proving the hole is the terminal exemption. Independently, `compute_metrics([.01, -.02, -inf, .03])` returns the same metrics as removing the `-inf`, including Sharpe **4.2053**.

**Acceptance:** permit only a genuine missing next-return at the dataset's final timestamp, and never infinity. Validate the full scored return path before filtering; reject internal missing observations rather than joining the surrounding rows. Require finite executed ledgers before computing or exporting metrics, and make any analytical missing-value policy explicit. Cover every fold boundary, positive/negative infinity, the actual dataset endpoint, and positions on both sides of a missing interval. Evidence: `missing_baseline` and `metrics_invalid` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D04 — [P1] Discovery constructs the fold clock after deleting missing labels and returns.**

[discovery.py:63](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:63), [discovery.py:209](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:209).

Both validation search and nested evaluation intersect the feature index with `y.dropna()` and `fwd.dropna()` before constructing folds. The later missing-return check cannot detect rows already removed from its input. Outcome availability therefore changes train/validation/test membership, and the position ledger carries across the omitted interval. This is separate from D03: fixing the baseline's final-bar check does not fix discovery's earlier index construction.

**Reproduction:** remove the return for **10 September 2020** while leaving the feature panel and every other return unchanged. Nested discovery succeeds. The first test end moves from **21 to 22 October 2020**, and the next test starts **23 rather than 22 October**. The missing observation is absent from the scored stream, whose remaining values are finite. The normal API permits this because its lock argument is optional; using a frozen compatible lock would detect changed geometry but would still detect it only after validation search has already run.

**Acceptance:** derive the immutable fold clock from declared observations before inspecting labels/outcomes, verify the lock before searching, and reject missing realized returns inside scored history. Use one anchoring convention for baseline, discovery, placebo and replay. Prove unchanged fold membership under outcome perturbations and prove missing internal outcomes cause rejection. Evidence: `nested_missing` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D05 — [P1] Every fold-restart replay reaches an undefined turnover variable.**

[baseline.py:379](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:379), [baseline.py:424](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:424).

The C07 fix changed the fold diagnostic to `turnover.loc[te]`, but that function creates `turnover_full`, not `turnover`. Nested discovery returns `boundary_policy="fold_restart"`, so its normal replay reaches this branch and raises `NameError`.

**Reproduction:** run `discover_and_evaluate_oos`, then invoke `replay_oos` without any override. Discovery completes; replay raises **`NameError: name 'turnover' is not defined`**. Thus cost/slippage/delay stress for a nested result cannot complete through the advertised shared replay engine. The ordinary baseline uses the continuous branch, explaining why its full market run and the existing suite's model assertions pass.

**Acceptance:** slice the actual merged turnover series and prove both per-fold and aggregate costs/trades reconcile. Add a no-override nested replay regression and run the full robustness battery on nested results with changing features, model types and holding periods. Evidence: `nested_replay` and its traceback in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json). This is a regression from an inaccurate diagnostic into a runtime failure.

**D06 — [P2] Parameter stress rebuilds a different effective model.**

[robustness.py:394](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:394), [robustness.py:403](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:403), [robustness.py:72](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:72).

Baseline fitting now honors explicit hyperparameter fields. The perturbation path still reads only `parameters` and constructs a new `ModelConfig` without the explicit fields. Its factor-1 identity claim is false for those supported configurations. Replay also falls back to `cfg.model`, not the model configuration stored on the baseline result, when refitting without an explicit override.

**Reproduction:** an explicitly configured logistic **C=0.001** becomes **C=1.0** at factor 1, changing probabilities by as much as **0.4369**. An explicit gradient booster with **learning_rate=0.7 and 7 estimators** becomes **0.05 and 100 estimators**, changing probabilities by **0.4133** and net Sharpe from **0.2026 to 0.7248**. These are synthetic diagnostic numbers, not performance claims.

**Acceptance:** resolve and persist one effective per-model specification, then alter only the intended parameter. At factor 1 require identical estimator settings, predictions and executed ledger. Cover explicit fields, parameter dictionaries, direct `model_cfg` overrides and mixed-model nested results. Evidence: `parameter_factor_one` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D07 — [P2] Delay stress can test only faster executions than the baseline.**

[robustness.py:355](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:355), [run.py:140](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:140).

The default grid remains absolute delays `[0,1,2,3]`. The orchestrator explicitly skips reconciliation when the configured baseline is outside that grid. For a configured delay of 5, every tested policy is faster. No row reproduces the baseline and no row measures additional latency, yet the same table supplies the delay-survival evidence.

**Reproduction:** both the isolated stress call and a complete configured-delay-5 pipeline succeed with only `[0,1,2,3]` in the table. There is **no baseline anchor and no slower-execution test**. Delays within the grid now execute correctly; the previous assertion bug is fixed for those cases.

**Acceptance:** always include the configured anchor and a declared additional-delay stress. Define whether promotion requires absolute latency or added latency and enforce that interpretation in both the table and gate. Reconcile the anchor for baseline delays 0, 1 and values beyond the default grid. Evidence: `delay_anchor` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json), `delay_five_grid` in [pipeline checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pipeline-check-results.json).

**D08 — [P2] The loader grants an undocumented one-session completeness exception.**

[loaders.py:299](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:299), [loaders.py:310](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:310).

Coverage is now checked against exchange sessions, fixing the earlier weekend/holiday rejection. But both boundary checks raise only when `n_missing > 1`. A comment speculates about listing history; there is no explicit listing-date exception supplied or verified. `missing_data_report` uses each symbol's observed endpoints, so it cannot detect the omitted requested boundary afterward.

**Reproduction:** for requested `[2 January, 3 February 2024)`, remove only 2 January. The CSV loads starting 3 January and the integrity report says **zero missing sessions**. Remove only the final expected session, 2 February, instead: it loads ending 1 February, again with zero missing sessions. Complete weekend-bounded inputs and the documented real-data configuration now pass, as intended.

**Acceptance:** compare observed session coverage to the exact requested session set. Any listing/history exception must be explicit, recorded and reflected in integrity status. Test one missing leading session, one missing trailing session, weekend and holiday endpoints, and multiple symbols with different boundaries. Evidence: `coverage` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D09 — [P2] The fabricated-range marker is not enforced by the range consumer.**

[loaders.py:110](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:110), [parkinson.py:23](/home/marnus/VS-Code/ML-2/src/quant_research/features/parkinson.py:23), [parkinson.py:134](/home/marnus/VS-Code/ML-2/src/quant_research/features/parkinson.py:134).

The wide close/volume CSV adapter now marks its fabricated OHLC rows `_synthetic_range=True`, and validation preserves the marker. `lagged_parkinson_volatility` ignores it and computes measured-looking volatility from the invented zero ranges.

**Reproduction:** load a close-only CSV and pass the result to Parkinson volatility. Every input row is marked synthetic; the function accepts it and returns **21 non-missing values, all zero**. The ordinary baseline currently does not include this feature, so this does not invalidate the reconciled baseline ledger. It invalidates use of this otherwise supported input with the exported range feature.

**Acceptance:** reject fabricated ranges at the range-consuming boundary, or require and propagate a distinct unavailable-measurement policy. Cover mixed measured/fabricated rows and preserve the provenance marker through serialization. Evidence: `synthetic_ranges` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D10 — [P2] Missing revisions and identity values evade conflict detection.**

[point_in_time.py:176](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:176), [point_in_time.py:185](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:185).

The revised validator checks `(event_id, revision)` groups, but pandas grouping excludes null revisions by default. A nullable revision column can therefore remove the conflicting records from validation. For ordinary value fields, `nunique()` also excludes missing values, so missing-versus-populated conflicts are treated as a single identity value.

**Reproduction:** two records with the same event ID, `revision=NaN`, and conflicting sentiments **+0.5 and −0.5** are accepted. Two otherwise identical records with `processed_value=1.0` versus NaN are also accepted. The common valid-revision case with conflicting finite values is now rejected, and identical records no longer crash on removed pandas methods; those repairs are confirmed.

**Acceptance:** validate revision type and presence before grouping; either normalize an absent revision column to a declared default or require it, but reject missing/invalid supplied values. Include missingness in identity comparison, and declare which event fields may legitimately be missing. Test null revisions mixed with valid siblings and missing/non-missing identity conflicts. Evidence: `event_identity` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D11 — [P2] Re-delivering an identical event increases information evidence.**

[point_in_time.py:199](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:199), [information.py:89](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:89), [information.py:224](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:224).

Identical repeats are accepted and retained by validation. The feature builder deduplicates stories by topic, rather than first deduplicating exact event identity. When topic is absent, repeated deliveries of the same record remain separate live stories. A retry/replayed feed batch therefore changes the features despite supplying no additional information. This contradicts the fix summary's claim that identical repeats are deduplicated downstream.

**Reproduction:** one event produces attention `log(2)=0.693147`; repeating the same event row produces `log(3)=1.098612`. No new event, revision, source or availability time was introduced.

**Acceptance:** deduplicate identical `(event_id, revision)` deliveries before story/topic clustering, while preserving genuinely distinct revisions and independently sourced corroboration according to an explicit policy. Require exact feature equality when identical records are appended with or without topic/sentiment columns. Evidence: `event_identity` in [probe results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/probe-results.json).

**D12 — [P2] The test suite writes into persistent research history.**

[run.py:151](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:151), [conftest.py:102](/home/marnus/VS-Code/ML-2/tests/conftest.py:102), [conftest.py:115](/home/marnus/VS-Code/ML-2/tests/conftest.py:115).

Snapshot and output fixtures use temporary paths, but the pipeline's shared ledger path is derived from the source repository. Tests invoking the pipeline use that shared path. The autouse guard compares sets of paths, not file content, so it detects a new ledger but misses appends to an existing one.

**Reproduction:** the fresh isolated suite creates `data/research_ledgers/search_ledger.jsonl` and raises a teardown error on `test_registry_record_accounting_invariant`. The suite leaves **18 rows for nine completed attempts across two families**. Re-run only that test with the ledger present: pytest exits **0**, while history grows from **18 to 20 rows** and **7,058 to 7,844 bytes**. These synthetic test attempts can alter later family-cap decisions for the same synthetic research family.

**Acceptance:** make the shared-history location injectable/configurable and override it for every test. Protect pre-existing project state using hashes or an explicit write interception, not only new-path detection. Prove a full suite preserves pre-existing ledger content and produces no new project data on both clean and populated workspaces. The audit's original project ledger was protected by running these checks in isolated copies. Evidence: [full log](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pytest.log), [repeat results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/isolation-repeat-results.json), [isolated suite ledger](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pytest-shared-ledger.jsonl).

**D13 — [P2] Some acceptance tests are vacuous or assert the unsafe intermediate state.**

[test_audit_criteria.py:39](/home/marnus/VS-Code/ML-2/tests/test_audit_criteria.py:39), [test_audit_criteria.py:134](/home/marnus/VS-Code/ML-2/tests/test_audit_criteria.py:134), [test_audit_criteria.py:297](/home/marnus/VS-Code/ML-2/tests/test_audit_criteria.py:297), [test_pipeline.py:40](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:40), [test_pipeline.py:129](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:129).

The 16-case timestamp test never converts either the events or bars to its parameterized unit: those parameters only appear in the failure string. The lock tests named “rejects” assert the object becomes unfrozen without attempting the newly permitted evaluation. The attempt-count test explicitly shows the completed-only count is one but does not check which method promotion uses. Discovery's bound assertion is `n <= max or n > max`, and its NaN assertion is likewise exhaustive; neither can fail for the property it purports to verify. The cross-run lock test repeats identical settings and never tries to change a window.

**Impact:** these tests provide passing counts while missing the demonstrated regressions and bypasses. The independent *actual* 16-resolution matrix passed, so the defective test does not itself prove the ordinary timestamp bug remains. D15 documents the separate rounding edge.

**Acceptance:** replace tautologies with observable requirements: actual supplied dtypes, rejected dependent operations, counted attempts at the real gate, bounded executed candidate calls, and full no-override replay equality. Each regression should fail against the corresponding defective behavior. Evidence: [static checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/static-check-results.json), source locations above, and D01/D02/D05 runtime evidence. Pandas documents that integer datetime values depend on resolution, and `as_unit` changes that resolution explicitly. [Pandas resolution conversion](https://pandas.pydata.org/pandas-docs/version/3.0/reference/api/pandas.DatetimeIndex.as_unit.html).

**D14 — [P2] A saved manifest is not yet a complete replay package.**

[snapshots.py:163](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:163), [snapshots.py:239](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:239), [snapshots.py:274](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:274), [run.py:417](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:417), [run.py:452](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:452).

Manifests are now experiment-specific and refuse overwrite. NumPy's version is correctly recorded. Those fixes are verified. However, the feature block contains names/endpoints/counts, the event block contains presence/count, and fitted-model entries contain only class names. Full train/validation membership, fitted preprocessing/model state and actual feature/event contents are absent. Dirty source contents are not preserved. `get_git_info` runs relative to the caller's working directory and only checks unstaged tracked changes, so it is not a complete code-identity mechanism.

The registry record is written before manifest creation. `manifest_path` is subsequently added only to the returned report, not to the immutable registry record, despite the fix summary saying the locator is recorded there. Every new integration record confirmed the locator is absent.

**Status distinction:** the fix summary explicitly declares the full executable bundle out of scope. This is a documented open capability, not a newly introduced regression; it must remain open when assessing claims of complete reproducibility. The immutable filename/NumPy repairs should not be conflated with closing that capability.

**Acceptance:** either narrow the public contract to an audit summary with deterministic rebuild requirements, or export a reloadable, versioned replay bundle with immutable locators/hashes for all required inputs, memberships, preprocessing and model state, plus actual source identity. Reserve the experiment ID and artifact paths before writing the immutable record, and publish the record only after its referenced artifacts exist. Verify replay in a separate process with the exported material. Evidence: [static checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/static-check-results.json), [market experiment](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/market-replay-results.json).

**D15 — [P2] Timestamp normalization can round availability backward.**

[information.py:173](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:173), [information.py:197](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:197).

Using the normalized array in the eligibility loop fixes the large unit mismatch. Converting all event timestamps to microseconds still truncates valid nanosecond values. If an event is available just after a bar timestamp, conversion can make it appear available at that bar.

**Reproduction:** bar `2024-01-10 00:00:00 UTC`; event availability `2024-01-10 00:00:00.000000001 UTC`. The event is later than the bar but contributes attention **0.693147** at that bar. This is a very narrow precision case, not the former multi-day leakage. The implementation accepts nanosecond datetimes and promises an exact availability predicate, so silently rounding toward earlier availability violates its contract.

**Acceptance:** compare at a safe common precision or reject precision loss explicitly; never round an unavailable event backward into eligibility. Test events just before, exactly at, and just after a bar boundary, including canonical events and copies. Evidence: [precision probe](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/submicrosecond-results.json), [reproduction source](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/followup_probes.py).

**What is working, and what changed from the previous audit**

| Earlier item | Current assessment |
|---|---|
| C01 timestamp-unit mismatch | Ordinary 16 event/bar resolution combinations all behave correctly in fresh probes; D15 is the remaining submicrosecond boundary case. |
| C02 complete-data calendar rejection | Documented real configuration and complete weekend-bounded data pass. D08 retains a one-session omission gap. |
| C03 contaminated legacy discovery | Both deprecated entry points now raise; the unsafe global-winner composition is removed. Nested selection remains the correct direction. |
| C04 nonzero-delay reconciliation | In-grid delays work; outside-grid anchoring/additional stress remains incomplete in D07. |
| C05 shared research-family history | Same family in different output directories is now shared and capped. D01/D02 retain lineage and incomplete-history gaps. |
| C06 persistent test lock | Persistence is wired in, but incompatible/corrupt state unlocks evaluation: D01. |
| C07 nested turnover diagnostics | Regressed into undefined-variable failure: D05. |
| C08 explicit model fields | Direct baseline fitting honors them; downstream parameter stress does not preserve them: D06. |
| C09 meaningful GBM perturbation | Changes a consumed parameter, but does not center the stress on explicit baseline settings: D06. |
| C10 strict exception booleans | Existing regression cases pass; nonboolean and missing authorization values are rejected. |
| C11 event repeats/revisions | Common finite-value revision conflicts are rejected and repeat validation no longer crashes. D10/D11 retain validation/dedup gaps. |
| C12 invalid-return handling | Still open through both baseline fold endpoints and discovery's pre-filtered clock: D03/D04. |
| C13 counter high-water reset | The reset-after-construction regression passes; increments now recheck persisted high-water under lock. This does not make separate output counters project-global. |
| C14 attempt accounting | Helper counts are available and linked; orchestration still consumes incomplete counts and starts discovery too late: D02. |
| C15 immutable manifests | Distinct files preserve successive manifests. Registry locator remains absent: D14. |
| C16 environment/replay provenance | NumPy version fixed; full replay explicitly remains open: D14. |
| C17 fabricated OHLC | Marker survives the loader/validator; range consumer ignores it: D09. |
| C18 nonpositive volatility targets | Existing regression cases pass; zero and negative targets are rejected. |

The market baseline fits imputation/scaling/model state on training folds, chooses thresholds from validation, and reuses fitted models/thresholds for execution-only stresses. Future-data perturbation checks pass on the audited feature builders. Baseline cost accounting reconciles over the continuous OOS position ledger. Drawdown includes initial capital. These are substantive correctness improvements. Fitting preprocessing on training data and applying it to later data is also the documented scikit-learn pipeline practice. [Scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html).

The legacy notebook skills are not an accurate inventory of this repository: the named Elite notebook and its validation script are absent. In particular, a maximum historical feature lookback is not by itself proof of leakage across an expanding chronological split. This audit examined causal use, outcomes, train-only fitting and actual execution, rather than mechanically applying the legacy “purge must equal every lookback” rule to the current engine.

**Independent saved-market readout**

Input: 7,040 SPY/QQQ OHLCV rows, 3,520 sessions per asset, dataset hash `b0e94186f465bc47`. Provider data were reused from the existing verified snapshot; no new market download was made. Source coverage ends 31 December 2025. The configured complete-fold policy scores **22 January 2018 through 27 January 2025**, 1,764 forward close-to-close intervals. The return at the last scored timestamp is earned into the following session. The remaining data tail is not scored because it does not complete another 252-bar fold; this is the existing policy, not new missing-return evidence.

| Same scored intervals | Strategy | SPY buy-and-hold reference |
|---|---:|---:|
| Total return | −5.164% net | +139.486% |
| CAGR | −0.755% | +13.288% |
| Annualized Sharpe | −0.0649 | 0.7385 |
| Sortino | −0.0856 | 1.0276 |
| Calmar | −0.0329 | 0.3941 |
| Maximum drawdown | −22.925% | −33.717% |
| Annualized volatility | 7.421% | 19.477% |
| Hit rate among nonzero-return bars | 44.165% | 55.227% |

The strategy uses less exposure: average absolute position **25.902%**, beta **0.2729**, and annual turnover **28.196**. The benchmark is an uncosted adjusted-close return reference on the identical intervals; it is not an equal-volatility comparator. The strategy's gross return is **+6.764%**, gross Sharpe **0.1633**, and compounded gross-to-net drag **11.928 percentage points**. Its model charges fixed fees/slippage per weight change; spread, market impact, cash yield, capacity and detailed fill mechanics are not modeled. No live execution claim follows from these results.

The same fixed execution path, with slippage held at 1 bp and no threshold reselection, has the following fee sensitivity:

| Fee per turnover unit | Net Sharpe | Total return |
|---|---:|---:|
| 0 bp | 0.1253 | +4.677% |
| 2 bp | 0.0492 | +0.624% |
| 5 bp (configured) | −0.0649 | −5.164% |
| 10 bp | −0.2544 | −14.083% |
| 20 bp | −0.6297 | −29.491% |

Seven folds contain **three positive, three negative and one flat/undefined Sharpe**. Fold net Sharpes are **−1.2645, 0.5455, −0.5862, 0.9373, −0.0609, undefined, 1.2026**. The mean of finite fold Sharpes is +0.1290 and their median +0.2423, while the full concatenated portfolio Sharpe is negative. Averaging fold ratios does not reproduce portfolio performance; the full-path result is the appropriate headline. The flat fold's zero trades and zero returns explain its undefined Sharpe; it is not a corrupted executed return.

The **2,000-resample, 20-bar moving-block bootstrap** gives a 95% Sharpe interval **[−0.6936, +0.7109]**, with **P(Sharpe > 0)=0.492**. The interval spans zero: **the observed result is not statistically significant** under this diagnostic. The pipeline's configured 500-resample bootstrap gives positive probability 0.496 and also fails its gate. Increasing the audit resampling count adds uncertainty detail; it does not replace the stored promotion evidence or remove prior search exposure.

All three empirical nulls are unfavorable: the strategy is at the **45th percentile** of shuffled-feature runs (adjusted p **0.5714**), **35th percentile** of target permutations (p **0.6667**), and **15th percentile** of block permutations (p **0.8571**). Each uses 20 repetitions. These diagnostics compare the mean fold Sharpe statistic that the code actually supplies; they are not p-values for an independent, newly untouched final holdout.

Raw OOS classification AUC is **0.5010**, Brier score **0.25205**, log loss **0.69762**, and 10-bin ECE **0.04202**. No validation-fitted recalibration or ensemble comparison exists in this single-classifier baseline, so neither is implied. The regime readout gives Sharpe **0.2185** in low-volatility observations and **−0.2647** in high-volatility observations; the deep-drawdown flag gives **0.3168** versus **−0.2710** outside it. Regime slices are descriptive subsets, not independent tradable strategies.

Promotion remains **`RESEARCH_ONLY`**, failing cost survival, delay survival, bootstrap positive probability and placebo separation. The fresh isolated history contains one market-family attempt; this is an audit isolation choice, not a claim that the real research family has only been examined once. [Full metrics, calibration, regimes, placebo and run comparison](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/market-replay-results.json), [executed ledger](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/market-executed-ledger.csv).

**Notebook, operations and verification limits**

The notebook is valid nbformat, and every code cell compiles. A fresh Jupyter kernel could not start because this environment denied local socket creation (`PermissionError`). Saved outputs were cleared. Its **unchanged code cells then executed successfully, in order, in a fresh Python process** with display capture supplied by the audit harness. This proves the current source path completes in that process; it does not claim a successful kernel-backed Jupyter execution.

The notebook computes a baseline and then runs the full pipeline again. In an initially fresh artifact directory its single registered experiment reports **126 cumulative trials**, of which **63 belong to the final pipeline call**. This is repeated research by design in the current notebook, not a corrupt counter arithmetic result. The first notebook evaluation uses an in-memory test lock and is outside the shared ledger; the final pipeline reloads market data. Those already documented notebook limitations should be addressed by making it display one pipeline run's results. Only its synthetic path was freshly executed here. [Notebook execution evidence](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/notebook-check-results.json), [fresh captured outputs](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/notebook-executed.ipynb).

Source and tests compile. The 1,918 suite warnings are predominantly all-empty `momentum_252` training features in deliberately short fixtures, plus variance warnings from tiny placebo samples; they were not silently counted as additional test failures. Saved-market executed positions, gross/net returns and turnover are all finite, and the accounting assertions pass. NaN diagnostic statistics were classified separately from invalid executable returns.

The package has a paper-order recorder and separate safeguards, with no live broker adapter. Their presence does not establish paper/live operational readiness: this audit did not validate real orders, fills, latency, broker reconciliation or deployment permissions. Dependency versions were recorded, and code execution/configuration surfaces were inspected; no external vulnerability-database certification or provider-service availability check is claimed. Exact environment and source provenance are in [audit metadata](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/audit-metadata.json).

**Remediation order**

1. Close D01–D04 before further research is represented as locked or untouched OOS: enforce persistent identity/history and preserve the scored clock.
2. Fix D05 and D06, then require identity replay for baseline and nested strategies before interpreting robustness results.
3. Close D07–D11 and D15 at their input/consumer boundaries, with the exact reproduced cases retained as regression tests.
4. Isolate shared state and repair the acceptance tests in D12/D13 before using suite counts as completion evidence.
5. Resolve the explicit replay contract in D14, simplify notebook orchestration, and repeat the saved-market ledger reconciliation. Stronger strategy research should follow correctness closure; these results do not justify promotion.

Each finding's machine-readable status, evidence and acceptance requirement is recorded in the [current finding index](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/findings-index.json). Verification commands, harness limitations and artifact locations are in the [evidence README](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/README.md). Original source, tests, configurations, data and historical artifacts are checked against the [before manifest](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/preservation-before.json); the final result is in the [preservation check](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/preservation-check.json).
