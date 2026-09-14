> **Historical audit snapshot.** This report describes commit
> `36d87064d8da89fea649573141d5a6521aa1ebc5`; later fixes supersede its open
> finding counts. See [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md)
> for current status.

**Deep audit — Quant Research Engine V2.1.3**  
9 September 2026 · `/home/marnus/VS-Code/ML-2` · commit `36d87064d8da89fea649573141d5a6521aa1ebc5`

**Verdict: retain `RESEARCH_ONLY`.** The default market-data pipeline completes, and several important corrections since yesterday are effective. However, this audit reproduced two forms of historical-information contamination, an unsafe legacy discovery path, lost strategy specifications during replay, incomplete data acceptance, and unreliable research governance. Supported model/delay configurations still fail. The saved market snapshot remains unprofitable after the implemented execution fixes.

There are **18 current findings: 10 P1, 7 P2, and 1 P3**. P1 denotes material correctness, evidence-integrity, or supported-workflow failures; P2 denotes substantive validation, reporting, or reproducibility defects; P3 denotes test isolation. These priorities describe software impact, not financial-loss estimates. Each finding identifies its affected path; optional information/discovery defects are not evidence that the price-only baseline uses future news.

**Scope and verification**

- Reviewed all 37 Python source files (5,015 lines), the tests, both configurations, project metadata, notebook orchestration, prior audit, corrective commits, and saved baseline artifacts. Generated Repomix content was not authoritative over source. Historical files under `Initial Files - do not modify` were preserved.
- Ran the entire existing suite in a temporary project copy: **240 passed, 1,850 warnings, 332.14 seconds**. The warnings principally concern training fixtures with entirely unobserved `momentum_252`, and variance estimates from one placebo repetition. Passing tests do not cover all reproduced defects below.
- Ran **22 deterministic audit probes**, including previously fixed cases and new counterexamples. All probes completed without an unexpected probe error. The scripts assert the behavior described by their evidence; they are diagnostic reproductions, not a replacement regression suite.
- Completed two synthetic pipeline runs in one registry with changed test geometry, demonstrating that the test lock does not persist. These used one null repetition per mode solely for the governance reproduction and are not significance evidence.
- Completed the full current pipeline using the exact saved SPY/QQQ snapshot, including **20 repetitions for each of three placebo modes** and **500 bootstrap samples**. Only download and snapshot-write I/O were replaced to reuse existing data. Strategy, fitting, execution, robustness, and promotion computations were unchanged.
- Independently reconstructed the old fold-reset ledger and reproduced its saved economics. All differences from the current baseline are explained by four observations at fold boundaries or immediately afterward.
- Validated notebook schema and compiled all eight code cells. The notebook itself was not executed end to end; its pipeline and duplicated orchestration were inspected separately.
- SHA-256 manifests confirm that audited source, tests, configurations, README, plan, and notebook remained unchanged. The existing untracked `tests/test_promotion.py.bak` was preserved. This audit adds only this report and its evidence directory.

The installed notebook audit skills describe a previous engine with missing files such as `prompt.txt` and `Institutional_Quant_Pipeline_Elite_Research.ipynb`. Their old finding statuses and purge-window prescriptions do not establish correctness of this engine. No code fixes, new downloads, trades, or external-account actions were performed.

**Current findings**

| ID | Priority | Finding | Affected path |
|---|---|---|---|
| B01 | P1 | Timestamp storage units can make future events immediately available | Information features |
| B02 | P1 | An unavailable earlier publication can erase already available history | Information deduplication |
| B03 | P1 | The legacy discovery API still retrospectively selects earlier OOS strategies | Discovery API |
| B04 | P1 | Stale writers roll back both trial counter and high-water mark | Experiment governance |
| B05 | P1 | Missing assets and truncated requested history pass integrity | CSV/provider ingestion |
| B06 | P1 | Replay does not retain the complete executable strategy | Discovery and nondefault replay |
| B07 | P1 | Gradient boosting fails robustness assertions | Supported model configuration |
| B08 | P1 | A nonzero configured delay fails the stress workflow | Supported execution configuration |
| B09 | P1 | Gapped OOS windows carry exposure across unscored returns | Nondefault fold configuration |
| B10 | P1 | Promotion has no correction for repeated research across the same OOS family | Promotion governance |
| B11 | P2 | Search accounting remains incomplete and output-directory local | Discovery and registries |
| B12 | P2 | Test lock is neither persistent nor a full membership lock | Walk-forward governance |
| B13 | P2 | Daily OHLCV contract accepts impossible, fabricated, or duplicate-session bars | Data validation |
| B14 | P2 | Event identity and exception validation permit inconsistent PIT records | Event ingestion |
| B15 | P2 | Missing-data stress changes the supposedly locked timeline | Robustness with small feature sets |
| B16 | P2 | Saved artifacts lack a durable replay manifest; hashing rounds away differences | Reproducibility |
| B17 | P2 | One-trial DSR applies a two-trial penalty | Standalone statistics |
| B18 | P3 | Tests write snapshots outside their temporary output fixtures | Test isolation |

**B01 — [P1] Normalize datetime units before comparing availability**

[information.py:155](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:155), [information.py:177](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:177), [information.py:193](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:193).

The builder treats `DatetimeIndex.asi8` and event timestamps cast to `int64` as nanoseconds without normalizing their actual resolution. Pandas supports datetime arrays with different resolutions. These integers can differ by a factor of 1,000 for identical timestamps.

**Reproduction:** an event available on **10 January 2024** is correctly absent from 5–9 January when bars and events use microseconds. Changing only the bar index to nanoseconds makes that future event contribute from **5 January**. The indexes compare equal as timestamps. This is direct look-ahead under valid timezone-aware inputs, independent of topic deduplication.

**Acceptance:** normalize every bar, canonical-event, and copy-event timestamp to the same explicit unit, or compare datetime objects directly. Test all supported unit combinations and confirm identical first-eligible bars and decay. Evidence: `extra-probe-results.json → timestamp_units`.

**B02 — [P1] Cluster membership is still decided using unavailable events**

[information.py:89](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:89), [information.py:163](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:163).

The A01 correction counts corroborating copies by availability, but `_assign_clusters` still chooses the canonical story from the full collection sorted by publication time. An earlier publication delivered through a slower feed can become canonical before it is available, relegating an already available story to the discarded-copy set.

**Reproduction:** a story published and available at 02:00 on 5 January contributes normally. Add a matching story published at 01:00 that becomes available only on 12 January: **four earlier trading bars change**, with their sentiment, attention, intensity, and corroboration becoming zero. Both events pass schema validation. Ordinary later-publication corroboration and weekend intensity decay do pass the new regression cases.

**Acceptance:** establish canonical state in availability order, or deduplicate only the collection available at each decision time. Test opposite publication/arrival orders, ties, and delayed old stories. Evidence: `probe-results.json → pit_arrival_inversion`, `pit_fixed_cases`. Previous A01 remains **partial**.

**B03 — [P1] Retire or restrict the contaminated legacy discovery evaluation path**

[discovery.py:129](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:129), [discovery.py:147](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:147), [tests/test_pipeline.py:53](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:53).

`discover_and_evaluate_oos` now nests selection within each outer fold, and its causality tests pass. But `discover_strategies` still ranks candidates using validation windows across the complete history, and `evaluate_candidate_oos` still evaluates that global winner on all earlier test folds while describing them as untouched OOS. The existing integration test continues to demonstrate this unsafe composition.

**Reproduction:** change forward returns and their corresponding sign labels only from the first test period onward, leaving its training and validation data unchanged. The global winner changes from candidate **0 to 3**, and **all 40 first-fold predictions change** when that winner is retrospectively evaluated. Later validation includes outcomes that were future information at the first decision.

**Acceptance:** route evidence through nested selection, or require an explicitly separate holdout strictly after all global selection data. Make the legacy combination reject contaminated evaluation. Evidence: `legacy_discovery`. Previous A02 is **partial**, not closed by adding the new API alone.

**B04 — [P1] Trial persistence permits stale-writer rollback**

[registry.py:122](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:122), [registry.py:143](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:143), [registry.py:153](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:153).

Both counter and high-water values are cached on construction and overwritten during increment. Atomic rename makes one replacement atomic; it does not make read/modify/write transactional.

**Reproduction:** construct two valid counter objects before either writes. Increment the first by 100 and the second by 1. Disk contains **count = 1 and high-water = 1**, and a new reader accepts them. No simultaneous process race is needed. Shared `.tmp` filenames and separate counter/high-water writes add concurrent-write and crash-consistency risks.

**Acceptance:** use a transactional ledger or a process lock covering reload, increment, and durable commit. Test stale instances, concurrent processes, and interrupted writes; the requested increments must total 101. Evidence: `counter_stale`. Previous A07 remains open.

**B05 — [P1] Validate requested universe and boundaries against realized data**

[loaders.py:147](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:147), [loaders.py:211](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:211), [validation.py:270](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:270), [run.py:98](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:98).

Missing-data diagnostics iterate only over returned symbols and use their observed first/last dates. Entirely absent assets and leading/trailing truncation therefore disappear from the integrity calculation. Metadata still records the requested universe and period.

**Reproduction:** request SPY and QQQ from 2020 through 2024, but provide only **41 SPY sessions in January–February 2024**. Loading succeeds and both integrity counts are zero. The same structural omission exists where the provider loader skips missing symbols.

**Acceptance:** compare data with the requested assets and expected sessions over the configured interval, with explicit listing-history exceptions where appropriate. Missingness must identify absent symbols and boundary gaps. Evidence: `incomplete_data`. Previous A08 remains open; this does not claim the audited SPY/QQQ snapshot itself is incomplete.

**B06 — [P1] Persist and replay the complete per-fold executable specification**

[discovery.py:357](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:357), [robustness.py:72](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:72), [discovery.py:165](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:165).

The ordinary baseline now retains a scalar holding period, and a five-bar baseline replay is identical. The new nested discovery result, however, returns `hold_bars=1` even when every selected fold uses five bars. Its fold-local restart convention also differs from the continuous baseline executor used by replay. General replay defaults to all input feature columns and reconstructs risk returns instead of retaining the actual selected subset and risk input. Legacy candidate rows omit their search seed.

**Reproductions:**

- A four-fold nested strategy using five-bar holds changes **53 positions** on a replay with no override. Net return moves from **4.69% to 2.93%**.
- A strategy fitted on feature `a` fails replay when the supplied panel also contains `b` and `c`, because replay passes all columns to its fitted model.
- A baseline using explicit custom risk history changes **67 positions** on a replay with no override.

**Acceptance:** persist feature order, model settings/seed, per-fold holds, risk-input identity, and the fold-boundary execution policy; dispatch replay through that specification. Require equality of probabilities, positions, costs, and net returns before applying a stress. Evidence: `nested_replay`, `replay_spec`. Previous A09 is partial.

**B07 — [P1] Robustness assumes every classifier is logistic regression**

[robustness.py:130](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:130), [robustness.py:352](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:352).

The model identity assertion accesses `coef_` and `intercept_` unconditionally. **Gradient boosting trains and predicts successfully, then cost stress raises `AttributeError: ... no attribute 'coef_'`.** Its parameter stress also changes `C`, which this engine's gradient-boosting constructor ignores. The public estimator documents tree-based fitted attributes rather than logistic coefficients. [Scikit-learn reference](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingClassifier.html).

**Acceptance:** check estimator state without assuming one model family, and perturb parameters the selected estimator actually uses. Complete the full pipeline for both advertised models. Evidence: `replay_supported_configs`. Previous A10 remains open.

**B08 — [P1] Stress delays mix absolute configuration with relative comparison**

[robustness.py:324](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:324), [run.py:166](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:166).

Delay stress replaces the configured delay with each absolute grid value, then compares it as though that value were extra delay relative to the baseline. The pipeline also assumes absolute delay zero equals its configured baseline.

**Reproduction:** a baseline configured with `signal_delay_bars=1` completes; its zero-delay stress raises **`delay=0 replay positions differ from baseline positions`**. Consequently, the documented configuration cannot complete the full workflow.

**Acceptance:** define absolute versus incremental delay explicitly, compare the appropriate relative shift, and reconcile against the actual configured anchor. Evidence: `replay_supported_configs`. Previous A11 remains open.

**B09 — [P1] Do not compress gaps out of a continuous portfolio ledger**

[baseline.py:278](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:278), [baseline.py:285](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:285), [walk_forward.py:102](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:102).

With `step_bars > test_window`, test windows contain gaps. Execution concatenates only scored bars, carries signal/holding/position state across that compressed index, and omits intervening returns. Annualization then treats the selected observations as a continuous daily investment path.

**Reproduction:** use 40-bar test windows with a 60-bar step and an always-long signal. Position is **1.0 before and after a 20-session gap**, with zero transition turnover. A toy −5% return on each omitted session compounds to **−64.15%**, yet none appears in the reported stream. If the portfolio is instead intended to be flat during gaps, its liquidation and re-entry are absent.

**Acceptance:** reject gapped geometry until policy is explicit, or execute every intervening session and score the desired slices; a flat-between-windows policy must include its costs and cash days. Evidence: `gapped_execution`. This is separate from the fixed adjacent-fold reset defect and the now-rejected overlapping-window case.

**B10 — [P1] Distinguish Monte Carlo correction from research-family selection correction**

[run.py:256](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:256), [run.py:295](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:295), [promotion.py:156](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/promotion.py:156).

Promotion now correctly requires adequate placebo repetitions and a conservative Monte Carlo p-value. It still consumes only the feature-shuffle result and merely checks that the trial counter is positive. Family-adjusted p-values, DSR, and PBO do not enter the run or promotion decision. There is no persisted policy governing repeated candidate research on the same OOS history.

**Reproduction:** identical otherwise-passing evidence is promoted to `CANDIDATE` with a trial count of **1 or 1,000,000**. This demonstrates the gate's insensitivity; it does not assert that every counter increment is an independent hypothesis. The placebo reruns already repeat within-fold threshold selection, so multiplying their p-value by all threshold evaluations indiscriminately would also be wrong. The missing control concerns additional research across a shared evaluation family. Selection bias from repeated searches is distinct from Monte Carlo sampling correction. [Bailey and López de Prado](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

**Acceptance:** define the research family and what counts as a search, preserve all candidate outcomes, and predeclare the corresponding selection correction or a genuinely separated final evaluation. Document which null modes govern promotion. Evidence: `search_gate`. Previous A12's single-null defect is fixed; its broader governance issue remains.

**B11 — [P2] Count search work durably and independently of artifact location**

[discovery.py:106](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:106), [discovery.py:313](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:313), [baseline.py:225](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:225), [run.py:137](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:137).

Legacy discovery has no counter integration; evaluating its pinned thresholds adds no count. Nested discovery increments only after candidate search and OOS evaluation, so interrupted work is unrecorded. Baseline selection similarly increments after evaluation. Each output directory owns a separate supposedly global counter, and no ledger links searches to datasets or evidence families.

**Reproduction:** a legacy search and four-fold candidate evaluation complete while the supplied counter stays **zero**. New nested discovery does count completed fold searches, which is an improvement, but it is not a transactional search ledger. The current pipeline's price-only ablation also performs a new threshold search without recording it; the project needs an explicit policy for which diagnostic searches count.

**Acceptance:** record a started trial before evaluation and its outcome afterward, under a durable family identifier independent of output location. Preserve failed/abandoned searches and state a policy for deterministic replays. Evidence: `discovery_accounting`. Previous A13 remains partial/open.

**B12 — [P2] Persist full test membership for each research family**

[walk_forward.py:120](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:120), [run.py:136](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:136).

The lock hashes only minimum and maximum test timestamps, and every pipeline invocation constructs a fresh in-memory lock. It neither records complete membership nor survives a process/run boundary.

**Reproductions:** deleting an interior bar changes a locked fold from **40 to 39 observations** without rejection. Two completed pipeline runs in the same registry accept **40-bar and 30-bar** test layouts, with different test end dates. The existing test named `test_locked_test_survives_across_pipeline_runs` only reruns identical configurations; it never attempts a changed layout.

**Acceptance:** persist and verify complete test membership and dataset identity against a stable family ID before fitting. Support a separately identified new research family when intentionally changing evaluation policy. Evidence: `membership_lock`, `pipeline-lock-analysis.json`. Previous A20 remains open.

**B13 — [P2] Enforce the complete daily OHLCV contract**

[validation.py:80](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:80), [loaders.py:93](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:93), [validation.py:274](/home/marnus/VS-Code/ML-2/src/quant_research/data/validation.py:274).

The normalized validator checks high ≥ low, but not that open and close lie within the range; it also accepts infinite volume. The wide-CSV loader invents open/high/low from close. Daily uniqueness is checked by full timestamp rather than exchange session, while missing-data diagnostics reduce timestamps to dates.

**Reproductions:** open=close=100, high=50, low=40, volume=∞ passes `validate_ohlcv`. A close-only CSV becomes fabricated zero-range OHLC. Two timestamps per session produce **82 observations for 41 sessions**, yet missing and off-calendar counts are zero.

These defects can invalidate range features and daily annualization. Infinite volume is subsequently rejected by the standard wide-panel feature validator, so this audit does not claim it silently passes the full baseline pipeline.

**Acceptance:** enforce finite numeric data, complete OHLC relationships, one bar per symbol/session, and explicit session timestamp policy. Give close/volume-only input an honest separate schema or require true OHLC. Evidence: `invalid_ohlcv`, `duplicate_sessions`. Previous A21 remains open.

**B14 — [P2] Validate immutable event identity and typed exceptions**

[point_in_time.py:117](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:117), [point_in_time.py:133](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:133).

Duplicate IDs are rejected only when `raw_value` differs. Conflicting processed values, sentiments, sources, or availability can share one identity. An exception flag is converted with `.astype(bool)`, so the string **`"False"` becomes true** and waives availability ordering.

**Reproduction:** conflicting processed value and sentiment with the same ID/raw value are accepted; `provider_rule_exception="False"` accepts an event available before its event/publication time. These are input-boundary failures; ordinary validated default synthetic events do not require either behavior.

**Acceptance:** define immutable identity fields, reject conflicts, require proper revision identities, and accept only explicit boolean exceptions with a documented rule. Evidence: `pit_identity_and_exception`.

**B15 — [P2] Missing-feature stress must preserve the baseline time axis**

[robustness.py:381](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:381), [baseline.py:179](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:179).

Stress masks feature cells, then the executor drops rows that become entirely missing before rebuilding folds. Thus the probability of changing geometry increases sharply with small feature sets; the test lock correctly rejects the stress rather than producing a comparable result.

**Reproduction:** a valid one-feature baseline succeeds; masking 10% of cells raises **`LockedTestViolation`**. The data perturbation has become a timeline perturbation.

**Acceptance:** retain the baseline anchor/fold specification and apply the fold-local imputer to missing rows without dropping their timestamps. Evidence: `missing_stress_anchor`.

**B16 — [P2] Save sufficient evidence to reproduce the executable experiment**

[snapshots.py:23](/home/marnus/VS-Code/ML-2/src/quant_research/data/snapshots.py:23), [run.py:104](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:104), [run.py:302](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:302), [run.py:352](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:352).

The snapshot metadata returned by saving is discarded except for its hash. Artifact records omit the full config, exact snapshot locator/file checksum, Git revision and dirty-source identity, environment lock, event snapshot, fitted preprocessing/models or reconstructable equivalents, per-bar predictions/positions, and full fold membership. `CODE_VERSION` stays `V2.1.3` across substantive corrections. Dataset hashing formats prices to ten decimal places before hashing.

**Reproduction:** distinct close prices separated by 10⁻¹² produce the same dataset hash. The difference is small economically, but the advertised identifier is not an exact identity check. This audit could replay the old data because the repository still contained the matching snapshot and configuration; that does not make an exported results JSON self-sufficient.

**Acceptance:** publish a complete content-addressed manifest for raw inputs, event inputs, code, configuration, environment, fold membership, and executable strategy. Use a canonical serialization that preserves consumed values, and verify it when loading. Evidence: `hash_collision`, current artifact contents, and `market-replay-analysis.json`. Previous A23 remains open.

**B17 — [P2] Handle the one-trial DSR boundary explicitly**

[multiple_testing.py:61](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/multiple_testing.py:61).

The principal skew/kurtosis denominator correction from A17 is implemented and regression-tested. A residual boundary error remains: `n = max(n_trials, 2)` means a one-trial hypothesis receives a two-trial selection penalty. A maximum over one zero-mean null variable has expected value zero.

**Reproduction:** for annualized Sharpe 1.0 and 1,000 observations, the API's one-trial p-value is **0.07087**, versus **0.02335** for the corresponding single-strategy PSR tail. Its expected daily null maximum is 0.01644 instead of zero. This is a conservative false-rejection error in the standalone statistics API; DSR is not currently a promotion gate.

**Acceptance:** special-case one trial and test the mathematical boundary alongside multi-trial examples. Preserve the corrected daily/annual units and moment denominator. Evidence: `extra-probe-results.json → single_trial_deflation`; [DSR/PSR paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

**B18 — [P3] Make every test snapshot path temporary**

[tests/conftest.py:45](/home/marnus/VS-Code/ML-2/tests/conftest.py:45), [tests/test_pipeline.py:93](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:93), [run.py:104](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:104).

The shared test configuration retains `data/raw_snapshots`, even when tests pass a temporary artifact directory. The full suite created **18 snapshot/metadata files** under the isolated copy's working-directory data folder. The snapshot-path test variable is computed but never asserted.

**Acceptance:** give every test configuration a `tmp_path` snapshot directory and assert no files appear elsewhere. This audit ran tests in a copy, so the user's data folder was not polluted. Previous A24 remains open.

**Status of yesterday's findings**

| Previous ID | Verified status today | Evidence or remaining issue |
|---|---|---|
| A01 | PARTIAL | Ordinary corroboration fixed; availability-order clustering still changes history (B02), plus independent units bug B01 |
| A02 | PARTIAL | Nested selection causality tests pass; legacy contaminated API remains (B03) |
| A03 | FIXED | Block permutation moves dated values while preserving chronological indexes |
| A04 | FIXED in backtester contract | Explicit delayed close-to-close convention and timing tests; README/session-open wording remains stale |
| A05 | FIXED for adjacent baseline folds | Continuous costs/state reconcile; gapped timelines remain unsupported in substance (B09) |
| A06 | FIXED | Largest positive fold Sharpe share now 0.25 for four equal positive folds |
| A07 | OPEN | Stale writers still reset both files (B04) |
| A08 | OPEN | Requested universe and date completeness still absent (B05) |
| A09 | PARTIAL | Scalar baseline hold preserved; nested and other replay specifications incomplete (B06) |
| A10 | OPEN | Gradient-boosting robustness failure (B07) |
| A11 | OPEN | Nonzero configured delay failure (B08) |
| A12 | PARTIAL | Minimum repetitions and Monte Carlo p enforced; research-family governance remains (B10) |
| A13 | PARTIAL | Nested completed searches counted; legacy, interrupted work, and shared scope unresolved (B11) |
| A14 | FIXED for current baseline | Risk exposure, turnover, and beta use the actual ledger and aligned benchmark |
| A15 | FIXED | Initial capital included in drawdown; promotion consumes full-path drawdown |
| A16 | FIXED for reported defect | Two-variant adversarial PBO is 1.0; large combination enumeration is bounded |
| A17 | PARTIAL | Principal DSR denominator/units repaired; one-trial boundary still wrong (B17) |
| A18 | FIXED for reported decay defect | Weekend event intensity falls from 1.0 to 0.14359 across 15 bars |
| A19 | FIXED by rejection | Duplicate OOS timestamps now raise an explicit unsupported-overlap error |
| A20 | OPEN | New lock each run; only endpoints hashed (B12) |
| A21 | OPEN | OHLCV schema and fabricated range problems remain (B13) |
| A22 | FIXED | Standard all-observation downside deviation; independent numerical example passes |
| A23 | OPEN | Replay manifest and exact data identity remain incomplete (B16) |
| A24 | OPEN | Suite still writes default working-directory snapshots (B18) |

The latest commit title mentions a transactional ledger and data-completeness restoration, but the checked-out `registry.py`, `loaders.py`, and `validation.py` are unchanged from the initial Git snapshot `05cd573`. Its actual diff does not contain those claimed changes. This audit therefore relies on source and reproductions rather than the commit title when assessing closure.

**Current market-snapshot result**

Data identity: `b0e94186f465bc47`, original SPY/QQQ adjusted daily snapshot from 7 September. The current executable convention is **delayed close-to-close**, not next-open execution. There are **1,764 scored intervals**, beginning at the 22 January 2018 close and ending with the interval indexed 27 January 2025. Raw data extends to 31 December 2025; the incomplete final fold is dropped. These figures do not describe the entire remaining 2025 period.

| Measure | Current strategy | SPY buy-and-hold, same scored intervals |
|---|---:|---:|
| Total return | **−5.16% net**, +6.76% gross | +139.49% before trading costs |
| Annualized Sharpe | **−0.0649 net**, +0.1633 gross | 0.7385 |
| Sortino | −0.0856 | 1.0276 |
| CAGR | −0.75% | +13.29% |
| Maximum drawdown | **−22.93%** | −33.72% |
| Annualized volatility | 7.42% | 19.48% |
| Mean absolute exposure | 25.90% | 100% |
| Annual turnover | 28.20 | — |
| Positive / negative / undefined fold Sharpes | 3 / 3 / 1 | — |

Strategy costs are 5 bps fees plus 1 bp slippage per unit turnover. Summed return deductions are 9.87 percentage points of fees and 1.97 points of slippage; the **compounded gross–net terminal return difference is 11.93 points**. These are different accounting quantities and should not be conflated.

| Fee bps, plus 1 bp slippage | Net Sharpe | Total net return |
|---:|---:|---:|
| 0 | 0.1253 | +4.68% |
| 2.5 | 0.0302 | −0.36% |
| 5 | −0.0649 | −5.16% |
| 10 | −0.2544 | −14.08% |
| 20 | −0.6297 | −29.49% |

Additional delays of 1 and 2 bars have positive net Sharpes, but 3 bars gives −0.0480; the configured gate requires all tested delays at or beyond one bar to survive, so it fails. These stress outcomes are diagnostics, not new delay selections endorsed by this audit.

The 500-sample block-bootstrap Sharpe interval is **[−0.681, +0.664]**, with a positive-Sharpe resampling fraction of **0.496**. This does not establish positive performance at the reported confidence level; the resampling fraction is not a posterior probability. The implementation uses fixed-length moving blocks despite its module description saying stationary bootstrap.

| Placebo mode, 20 runs each | Observed percentile | Monte Carlo adjusted p |
|---|---:|---:|
| Feature shuffle | 45% | 0.5714 |
| Joint target/return permutation | 20% | 0.8095 |
| Block target/return permutation | 5% | 0.9524 |

Mean fold AUC is **0.5010** and Brier score **0.2521**. The current run contains no calibrated ensemble. Conditional high-volatility observations have net Sharpe −0.2647 versus +0.2185 in the other volatility segment. Regime tables concatenate selected observations; their drawdowns are conditional diagnostics, not additional continuously invested portfolios.

The run's failed gates are **cost stress, delay stress, bootstrap positivity, and placebo separation**. The full executed return/position ledger is finite and cost reconciliation passes. The one undefined fold Sharpe is an all-flat fold. A JSON scan found one remaining nonfinite value in the report: the unused `level` marker of the `regime=all` row. Encode that marker as JSON null for portability.

**Explanation of changes from the saved baseline:** old net Sharpe −0.07121 becomes −0.06486, and old net return −5.48% becomes −5.16%. Rebuilding the old reset-at-each-fold execution reproduces its saved return and cost values to 10⁻¹². Current predictions, thresholds, AUC, and Brier remain the same; only four ledger observations around the starts of folds 2 and 5 change. Those economic changes are expected from carrying execution state. The fold-share metric changes by definition, while risk diagnostics now use the actual positions. The block-null result is newly recomputed under the repaired permutation. There are no unexplained baseline economic deltas in this replay.

**Additional observations and audit limits**

- The notebook performs loading, baseline search, stress, and placebo work before invoking the complete pipeline again. This duplicates computation and trial increments, uses a hardcoded `artifacts/trial_counter.json`, and could fetch a different real-data snapshot in its last cell. Its earlier feature-leakage call omits information events. A single retained pipeline result should populate notebook views.
- README still advertises approximately 152 tests, describes the calendar as business-day based, and describes execution using session-open language. The current suite has 240 cases and explicit US holiday rules; the backtester earns delayed close-to-close intervals.
- Main orchestration evaluates one baseline plus risk diagnostics. It does not run the discovery engine or apply the separate portfolio drawdown/turnover construction controls. Availability of those modules should not be presented as evidence that their controls were applied to reported returns.
- Config validation does not consistently enforce finite values or integer types. A NaN fee is accepted by `ExecutionConfig`; the standalone backtest reports NaN net observations and zero summed fee cost. The production accounting assertion rejects that example, so there is no demonstrated successful invalid-fee promotion. Validate inputs before doing expensive research and distinguish missing observations from zero returns.
- PBO is explicitly simplified: it ranks averages of fold Sharpes, has an unused `n_splits` argument, and an optimistic tie policy. The original rank-axis and combination-allocation defects are repaired; this does not establish equivalence to a complete CSCV analysis on strategy return matrices.
- Paper trading is a stub: `latency_bars` is metadata, there is no fill timestamp or portfolio cash ledger, and `submit` does not invoke safeguards. The separate freshness check accepts future-dated bars as negative age. These interfaces do not establish paper-validation readiness; no live broker is implemented.
- The package has broad dependency lower bounds and no environment lock. No CI workflow is present. The tested environment is Python 3.13.5, NumPy 2.5.2, pandas 3.0.5, scikit-learn 1.9.0, SciPy 1.18.1, and pytest 9.1.1. This audit did not test every permitted dependency combination or perform a dependency-vulnerability assessment.
- The custom calendar is US-only and lacks a declared historical support range. Provider-side corrections, point-in-time corporate-action adjustments, execution capacity, market impact, and cash financing were not established by this audit. Existing benchmark and strategy figures are simulation evidence under the stated contract.
- The Parkinson feature uses an explicit per-symbol lag and positional alignment, and its 41 tests pass. It is registered but not included in the current baseline builder. Its correct lag does not repair the upstream fabricated-OHLC issue.

**Remediation order and completion criteria**

1. **Close temporal contamination:** normalize timestamp units, make deduplication availability-ordered, and prevent the legacy discovery API from creating contaminated OOS evidence. Require historical features and first-fold decisions to survive the exact counterexamples in B01–B03.
2. **Unify execution and replay:** retain full per-fold specifications, define gap policy, and complete supported model/delay paths. A replay with no override must produce the identical ledger before any stress is trusted.
3. **Harden ingestion:** enforce requested universe/date completeness, honest OHLC schemas, one observation per session, and typed immutable event records. Fail at ingestion with explicit coverage diagnostics.
4. **Make governance durable:** transactional trial ledger, stable family identifiers, complete persistent test membership, and a predeclared research-family evidence policy. Prove correctness across processes and aborted searches.
5. **Export reproducible evidence and rerun:** save exact data/code/config/environment/execution manifests; fix remaining statistical boundaries and test isolation. After changes, rerun the suite, these independent probes, and the exact snapshot comparison in a new artifact directory. New results should explain every delta without selecting a favorable stress outcome retrospectively.

**Evidence and reproduction**

The evidence bundle is [audit_artifacts/2026-09-09](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-09).

| Artifact | Purpose |
|---|---|
| `audit-metadata.json` | Commit, environment, scope, completed checks |
| `source-manifest-before.json`, `source-manifest-after.json` | Unchanged audited-file identities |
| `pytest.log`, `pytest-results.xml` | Full existing-suite result |
| `audit_probes.py`, `probe-results.json`, `probes.log` | 19 deterministic defect/fix probes |
| `legacy-discovery-followup.log` | Stronger discovery reproduction with labels consistent with return signs; supersedes its initial log entry |
| `extra_probes.py`, `extra-probe-results.json` | Timestamp units, nonfinite-fee boundary, single-trial DSR |
| `pipeline_evidence.py`, `pipeline-lock-analysis.json` | Two completed runs accepting changed test layouts |
| `market_snapshot_run/` | Full current market-snapshot research report, folds, and separate registry |
| `market-replay-analysis.json`, `market-executed-ledger.csv` | Performance, uncertainty, original/current deltas, actual execution |
| `reconcile_legacy_ledger.py`, `ledger-delta-explanation.json` | Independent explanation of all baseline economic differences |

Reproduction uses the temporary source copy recorded in `audit-metadata.json`; all probe writes are confined to this evidence directory. To repeat elsewhere, copy `src`, `tests`, `configs`, and `pyproject.toml` into a new temporary directory, set `PYTHONPATH` to that copy's `src`, and run from the copy. Set `PYTHONDONTWRITEBYTECODE=1` and `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1`. Run pytest, then the probe scripts. `pipeline_evidence.py real` reads the explicitly identified original snapshot without a download; `pipeline_evidence.py lock` creates isolated synthetic artifacts. Do not run the product suite from the original project until B18 is fixed if working-directory snapshot writes are undesirable.

Probe scripts deliberately assert reproduced defects as well as verified fixes. After remediation, update their expected outcomes or convert their independent invariants into regression tests; a diagnostic assertion changing is not automatically a product regression.
