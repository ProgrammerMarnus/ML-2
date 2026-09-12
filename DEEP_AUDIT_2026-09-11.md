# Deep audit — ML-2 — 11 September 2026

The saved-market baseline is reproducible, but the repository's research-history controls and paper-validation states are not dependable enough to support a readiness claim. This audit identifies **25 actionable findings: 10 P1 and 15 P2**. The most serious demonstrated failures are promotion to `LIVE_ELIGIBLE` without any elapsed trading sessions, execution after a kill switch, blocked position liquidation, and incorrect costs when replaying nested discovery.

The seven-fold seed-7 market baseline was reconstructed from its saved, full-hash-verified snapshot and manifest. Predictions and net returns match the saved experiment **exactly**, and a baseline replay preserves positions and returns exactly. The continuous baseline passes independent turnover/cost reconciliation. Its recorded result remains `RESEARCH_ONLY`; the failures below do not establish that this saved baseline's arithmetic is wrong. See [market evidence](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/market-results.json).

**Scope and evidence**

Audited commit: `0f98bb89bb838d603f9ae712c6dab48c724c63d6`. The working tree was clean at the start. Reviewed the production Python package, tests, five configurations, both active notebooks, the runner helper, saved experiment evidence, and relevant previous audit findings. Original source, tests, configurations, notebooks, market snapshots and research history were not edited. The deliverables are this report and its [evidence directory](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11).

Validation combines the complete existing pytest suite in a byte-identical temporary source/test/configuration copy, independent behavioral probes, a saved-market baseline reconstruction, static analysis of the remaining paths, and a limited tracked-file secret scan. The initial in-place pytest attempt was interrupted after two completed tests; the isolated run is the authoritative full-suite result. The copy comparison verifies 73 source/test/configuration files remained unchanged. Runtime: Python 3.13.5, NumPy 2.5.2, pandas 3.0.5, scikit-learn 1.9.0, SciPy 1.18.1.

The complete suite finished with **308 passed, 6 failed, 1 teardown error and 1,906 warnings in 573.93 seconds**. Two failures reconstruct outdated feature sets and compare different experiments; four assume logistic-regression attributes on gradient-boosting models. The teardown error demonstrates shared research-state pollution. These test failures are explained in E22–E23; they are separate from the independently demonstrated production defects. [Full pytest log](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/pytest.log), [JUnit results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/pytest.xml).

Independent reproductions and machine-readable outcomes:

- [Main probe program](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/probes.py) and [results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/probe-results.json).
- [Follow-up checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/followup_checks.py) and [results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/followup-results.json).
- [Saved-market reconstruction](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/market_check.py), [results](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/market-results.json), and [folds](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/saved-market-folds.csv).
- [Scope and source-parity checks](/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-11/scope-checks.json).

P1 denotes a failure that can invalidate a core research control or the advertised paper-execution/readiness workflow. P2 denotes a narrower correctness, integrity, reproducibility or test defect. No P0 incident or live-broker order was demonstrated. Paper findings concern the simulator and its evidence reports; the repository has no implemented live-broker adapter.

| ID | Priority | Finding |
|---|---|---|
| E01 | P1 | Paper execution days count function calls, allowing instant live eligibility |
| E02 | P1 | Paper safety gates pass after real breaches and discard critical test results |
| E03 | P1 | Pending limit orders fill after the kill switch trips |
| E04 | P1 | Position checks reject orders that reduce or close exposure |
| E05 | P1 | Pending orders bypass exposure limits and cash constraints |
| E06 | P1 | Market paper orders fill immediately despite configured latency |
| E07 | P1 | Retrying an order ID executes twice and overwrites its history |
| E08 | P1 | Nested discovery replay omits liquidation costs at fold boundaries |
| E09 | P1 | Nested discovery ignores the supplied locked-test protocol |
| E10 | P1 | Tiny data revisions reset the apparent research family |
| E11 | P2 | Discovery records its start after completing candidate search |
| E12 | P2 | Structurally malformed JSON locks are silently replaced |
| E13 | P2 | Corrupt search-ledger rows disappear from trial history |
| E14 | P2 | Parameter stress ignores explicit baseline hyperparameters |
| E15 | P2 | Undefined candidate scores can outrank valid negative scores |
| E16 | P2 | Repeated event delivery changes evidence; missing identity values evade checks |
| E17 | P2 | Event revisions are treated as corroborating copies instead of updates |
| E18 | P2 | New OHLC features consume fabricated ranges from close-only CSVs |
| E19 | P2 | Partial or invalid price updates corrupt paper portfolio valuation |
| E20 | P2 | Paper validation adds historical fees again on every step |
| E21 | P2 | The public backtester hides missing/non-finite realized returns |
| E22 | P2 | Test execution still writes shared research state |
| E23 | P2 | Several regression tests are stale or cannot detect their named defect |
| E24 | P2 | Notebook diagnostics can describe a different experiment |
| E25 | P2 | The runner retries successful work when output mentions error codes |

**Detailed findings**

**E01 — [P1] Require actual, uniquely identified trading sessions before paper promotion.**

[paper_validation.py:102](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/paper_validation.py:102), [paper_validation.py:168](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/paper_validation.py:168).

`record_step` increments `n_days_executed` without checking a timestamp, market bar, elapsed session, source, or strategy identity. Its `bar_data` argument is unused. A fresh runner defaults to `PAPER_READY` without linking to an approved research record. Calling `test_kill_switch`, then `record_step` 60 times, then `finalize` returns `LIVE_ELIGIBLE` with **zero filled orders and approximately 0.3 milliseconds between report start and end**. Thus the report is not evidence of 60 days of paper operation. Evidence: `paper_evidence`.

Count unique completed exchange sessions from an authenticated execution feed or explicit replay clock; reject duplicates and backwards time. Bind evidence to the research experiment, configuration and strategy, and distinguish historical simulation from observed paper operation. A repeated call for one session must leave duration unchanged.

**E02 — [P1] Derive paper safety gates from observed events, not default fields.**

[paper_validation.py:115](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/paper_validation.py:115), [paper_validation.py:169](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/paper_validation.py:169).

`n_safeguard_breaches` is never incremented. The daily-loss gate accepts any historical `kill_switch_tripped=True`, including the intentional test. `finalize` overwrites the `kill_switch_blocks_orders` and `kill_switch_resets_cleanly` results collected by `test_kill_switch`; it checks flags saying a test ran rather than the blocking result. `max_reconciliation_failures` is declared but is not used in the final gates. A probe trips a real −20% daily loss, rejects an order, records a −20% drawdown, and still returns `LIVE_ELIGIBLE` with **zero breaches and every gate passing**. Evidence: `paper_breaches`.

Maintain an event-derived breach ledger, distinguish deliberate tests from operational trips, enforce the configured reconciliation-failure budget, and retain and consume actual kill-switch assertions. A historical test trip must not justify subsequent losses.

**E03 — [P1] Apply the kill switch to pending fills.**

[paper.py:367](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:367).

Safeguards run at submission, but `process_bar` fills pending limit orders directly. Submit a 10-share limit buy, trip the kill switch, and deliver a price below the limit: the order becomes `FILLED` and opens ten shares while the switch remains active. Evidence: `paper_kill_pending`.

Enforce execution permission immediately before each fill and define whether pending exposure-increasing orders are cancelled or held on a trip. Test a switch transition after submission and before the next bar, not only rejection of newly submitted orders.

**E04 — [P1] Compute signed post-trade exposure so liquidation remains possible.**

[paper.py:243](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:243), [operational.py:146](/home/marnus/VS-Code/ML-2/src/quant_research/execution/operational.py:146).

The position check adds the absolute existing position and the order value regardless of side. With $1,000 equity and eight shares at $100, `ManualOverride.flatten_position` submits an eight-share sell, but the broker calculates 160% exposure and rejects it; all eight shares remain. The actual post-trade position would be zero. Also, the unconditional kill-switch rejection prevents the same flatten operation during an emergency. Evidence: `paper_exit`; the kill-switch path is directly visible in `_run_safeguards`.

Check signed post-fill quantity and distinguish reducing exposure from opening or reversing a position. Provide an explicit, audited liquidation policy for emergency stops. Test long and short positions near the limit and with an active kill switch.

**E05 — [P1] Reserve pending exposure and validate buying power at fill time.**

[paper.py:243](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:243), [paper.py:300](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:300).

The submission check considers only filled positions; outstanding orders reserve neither exposure nor cash. Two pending buys of eight shares at $100 each pass independently against $1,000 equity. The next bar fills both, leaving **16 shares, −$600 cash and 160% position weight despite `max_position=1`**. Fill-time price changes can similarly invalidate the original check. Evidence: `pending_exposure`.

Reserve outstanding commitments, enforce portfolio buying power including fees and slippage, and recheck the resulting exposure before every fill. Cover multiple orders for one symbol and simultaneous orders across symbols.

**E06 — [P1] Enforce the configured paper execution latency.**

[paper.py:211](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:211), [paper.py:265](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:265).

`submit` immediately calls `_try_fill_market`; latency is merely copied onto the order. With `latency_bars=3`, the order is filled at its submission timestamp. This cannot validate the research engine's delayed-close execution convention, and the recorded nonzero latency is misleading. Evidence: `paper_latency`.

Queue market orders with an earliest eligible execution bar and use that bar's permitted price. Verify fill timestamps, prices and bar counts against the research contract. The existing test that asserts `order.latency_bars >= 1` does not establish delayed execution.

**E07 — [P1] Make order-ID retries idempotent.**

[paper.py:187](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:187), [paper.py:205](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:205).

`submit` does not check whether an order ID already exists. Submit two separately constructed one-share orders with the same ID: two shares are bought, but `self.orders[id]` retains only the second one-share record. Reconciliation reports expected quantity one and actual quantity two. Retrying a request after an uncertain response therefore duplicates execution and destroys the original order record. Evidence: `paper_duplicate_id`.

Return the original result for an identical request ID and reject conflicting content under an existing ID. Test fresh objects with the same ID, including retries after submission, partial fill, cancellation and completion.

**E08 — [P1] Recompute turnover across the merged nested-strategy position path.**

[baseline.py:366](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:366), [baseline.py:381](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/baseline.py:381).

Discovery correctly computes turnover from the concatenated fold positions. Its replay uses `boundary_policy='fold_restart'` and instead concatenates fold-local turnover. Each new fold starts flat, so closing the previous fold's nonzero position costs nothing in replay. In five actual discovery folds, replay positions are identical, but fees fall from **0.0050629843 to 0.0035449673**, a **29.98% undercharge**. Each later fold's first net return is overstated. Both the cost-accounting assertion and `cost_stress` fail. Evidence: `discovery_replay`.

Form the merged positions first, derive `abs(diff(position))` once across the entire timeline, then slice costs and metrics by fold. Require exact baseline/replay identity and stress completion for a discovery result with nonzero positions at fold ends. This is the remaining economic defect after the earlier undefined-variable crash was removed.

**E09 — [P1] Verify the discovery test lock before candidate evaluation.**

[discovery.py:221](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:221), [discovery.py:280](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:280).

`discover_and_evaluate_oos` accepts `locked_test` but never uses it. A supplied lock whose `verify` method always rejects is called **zero times**, while all five OOS folds are evaluated. The notebook/test call signature therefore gives a false impression that discovery uses the same protection as baseline research. Evidence: `discovery_lock`.

Construct and verify the intended fold specification before searching or fitting. Test a real persisted lock with changed membership as well as an instrumented rejecting lock, and require zero model evaluations after rejection.

**E10 — [P1] Preserve research lineage when data versions change.**

[registry.py:217](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:217), [run.py:167](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:167).

The family ID hashes exact dataset content and evaluation policy. A provider revision or window-policy change creates an unrelated family even when the test observations overlap completely. The saved seed-43 and seed-7 snapshots contain identical **7,040 symbol/timestamp rows**, identical volume, and maximum close difference **$0.000213623**. They nevertheless receive distinct families; both saved reports state `family search count 1 <= max_family_searches 1`. Their explicit ledger locations are also separate `/tmp/ledgers/seed...` paths. Both records call the per-output count of 42 `n_trials_global`. Evidence: `saved_market_family_fragmentation` in the follow-up results.

These runs still fail other gates, so no false promotion of them is claimed. The demonstrated problem is that the family gate does not account for repeated use of effectively the same historical evidence. Use a durable declared research-family identity with dataset/evaluation versions as children, track overlapping test lineage, and separate per-run/per-output counts from genuinely shared counts. A tiny revision must not reset the evidence budget.

**E11 — [P2] Record discovery attempts before searching.**

[discovery.py:262](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:262), [discovery.py:289](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:289).

The complete grid calls `_validation_sharpe` before `ledger.record_start`; counter increments happen still later during OOS evaluation. An injected interruption inside the validation search leaves **zero ledger entries and zero trials**. The comment saying interrupted searches remain visible is therefore inaccurate for the expensive search phase. Evidence: `discovery_start`.

Persist the attempt before evaluating the first candidate and record evaluated trials durably as work advances. Preserve an unresolved or aborted attempt on exceptions. This part of the earlier D02 finding remains open.

**E12 — [P2] Reject malformed lock schemas as well as invalid JSON.**

[walk_forward.py:150](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:150), [walk_forward.py:167](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/walk_forward.py:167).

Invalid JSON and incompatible dataset/policy values are now rejected. However, existing files containing `{}`, `{"spec": {}}`, or `{"folds": [], "hash": null}` are treated as an unfrozen lock and overwritten by `verify`. All three probes silently accept and replace the file with a five-fold specification. Evidence: `malformed_lock`.

Validate schema, identity, hash and membership when any existing lock file is present; fail closed on missing or inconsistent fields. Do not interpret a corrupt existing file as first-time initialization. This is a residual D01 issue, not a claim that the incompatible-identity fix failed.

**E13 — [P2] Fail visibly on corrupt search-ledger entries.**

[registry.py:245](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/registry.py:245).

`SearchLedger._iter` catches `JSONDecodeError` and silently continues. Corrupting one recorded attempt and then appending another leaves the family count at one, hiding the earlier search. The gate cannot distinguish missing history from a genuinely fresh family. Evidence: `corrupt_ledger`.

Reject malformed records or require explicit, auditable recovery; validate required fields and preserve conservative attempt accounting. Tests should cover a truncated final write, a corrupt middle record and a subsequent successful search.

**E14 — [P2] Perturb the effective explicit model parameters.**

[robustness.py:413](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/robustness.py:413).

`parameter_perturbation` starts from the saved model configuration but derives its scaled value from `parameters`, overwriting the explicit override. A baseline with `logreg_C=0.01` and `parameters['C']=1.0` is refitted with **C=1.0 at factor 1**, changing probabilities by as much as **0.125313**. The gradient-boosting learning-rate branch has the same precedence error. Evidence: `parameter_anchor`.

Resolve the effective baseline value using exactly the precedence in `build_model`, then multiply it. Factor 1 must preserve fitted predictions and execution for both estimators, including conflicting explicit/bag settings. Earlier D06 remains unresolved.

**E15 — [P2] Rank non-finite discovery scores after every finite score.**

[discovery.py:343](/home/marnus/VS-Code/ML-2/src/quant_research/strategies/discovery.py:343).

An undefined score receives key `(1.0, candidate_id)` while a finite score receives `(-score, candidate_id)`. Consequently, NaN beats any score below −1 and can win ties at −1. With controlled candidate scores of logistic −2 and gradient boosting NaN, discovery chooses gradient boosting in all five folds despite documenting non-finite scores as last. Evidence: `nonfinite_discovery_ranking`.

Use a separate non-finite discriminator, such as `(is_nonfinite, negative_score, id)`, and define an explicit reject/fallback policy when no candidate is eligible. Cover finite negative, zero, positive, NaN and infinity values.

**E16 — [P2] Make repeated event delivery idempotent and validate missing identity values.**

[point_in_time.py:168](/home/marnus/VS-Code/ML-2/src/quant_research/features/point_in_time.py:168), [information.py:161](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:161).

Identical deliveries survive validation and enter story clustering separately. Without a topic, repeating the same event changes attention from **log(2)=0.693147 to log(3)=1.098612**; with a topic it can increase corroboration instead. Additionally, `nunique()` omits missing values: conflicting `processed_value=1` versus NaN under the same event/revision is accepted. Evidence: `event_identity`.

Collapse identical `(event_id, revision)` deliveries before clustering, compare missingness when checking identity, and reject inconsistent identity payloads. Require identical features after feed retries with and without topic metadata. These are residual D10/D11 defects.

**E17 — [P2] Apply event revisions at their own availability times.**

[information.py:73](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:73), [information.py:177](/home/marnus/VS-Code/ML-2/src/quant_research/features/information.py:177).

Validation permits versioned revisions, but clustering ignores `revision`. A revised event with the same topic and event time becomes a syndicated copy and is removed from the sentiment input. In the probe, sentiment is revised from +1 to −1 at the next bar, yet the feature remains **+1 on every later bar**. With no topic, both revisions remain active independently instead. Evidence: `event_identity.revised_sentiment`.

Resolve revisions separately from independent-source corroboration. Use the latest eligible revision for an event at each bar while retaining prior historical values before the update becomes available. Test both positive-to-negative updates and arrival out of order.

**E18 — [P2] Propagate measured-OHLC provenance into signal extensions.**

[loaders.py:110](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:110), [loaders.py:382](/home/marnus/VS-Code/ML-2/src/quant_research/data/loaders.py:382), [run.py:124](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:124).

The close-only CSV adapter fabricates `open=high=low=close` and correctly marks `_synthetic_range=True`. Parkinson now rejects that marker, but `to_price_panels` discards it and the newly included signal extensions always run. All 244 fabricated rows are accepted: `overnight_gap` becomes the full close-to-close return, `intraday_return` is identically zero, and range position is wholly missing. These are not measured overnight/intraday features. Evidence: `fabricated_ohlc`.

Carry provenance through panel conversion and either reject unavailable OHLC inputs or explicitly disable those features with accurate registry metadata. Cover the full CSV pipeline, not only Parkinson's direct API.

**E19 — [P2] Validate paper marks and preserve held assets on partial updates.**

[paper.py:367](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:367), [paper.py:383](/home/marnus/VS-Code/ML-2/src/quant_research/execution/paper.py:383).

Portfolio valuation includes only symbols present in the latest `prices` dictionary, and the bar-processing boundary validates neither price finiteness nor chronological freshness. An account worth $1,000 with $500 in SPY becomes worth **$500** when the next update contains only QQQ; a later NaN SPY price makes equity NaN. Risk checks and monitoring then operate on invalid equity. Evidence: `paper_marks`.

Declare whether updates must be complete or may be incremental. Reject incomplete full snapshots, or retain explicitly timestamped last marks under a freshness policy. Reject NaN, infinity, nonpositive prices and backwards/stale execution data before mutating account state.

**E20 — [P2] Count each fill fee once in paper validation.**

[paper_validation.py:117](/home/marnus/VS-Code/ML-2/src/quant_research/experiments/paper_validation.py:117).

Every `record_step` adds the total fee of every historical filled order to `_fees_paid` again. One order actually pays **0.50005**, but three recording steps report **1.50015**. The reported fee depends on report frequency rather than execution. Evidence: `paper_fees`.

Accumulate newly observed immutable fill events, or recompute a cumulative total without incrementing it. Cover partial fills and repeated calls with no new fills.

**E21 — [P2] Reject invalid realized returns at the public backtest boundary.**

[backtest.py:117](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:117), [backtest.py:158](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/backtest.py:158), [metrics.py:15](/home/marnus/VS-Code/ML-2/src/quant_research/evaluation/metrics.py:15).

The baseline wrapper now rejects interior missing/non-finite test returns, but direct `backtest` calls still turn missing returns into zero and allow infinity. With 69.1% exposure, a missing realized return is reported as zero gross return. An infinite realized return produces an infinite net bar while `compute_metrics` drops it and reports a finite Sharpe of **4.037628**. Evidence: `invalid_return`.

Enforce the same finite, chronological realized-return contract in the reusable backtester, with any terminal unavailable-return policy explicit. Metrics must not silently describe a different sample from the executed ledger.

**E22 — [P2] Isolate the shared research ledger in all tests.**

[run.py:157](/home/marnus/VS-Code/ML-2/src/quant_research/run.py:157), [conftest.py:87](/home/marnus/VS-Code/ML-2/tests/conftest.py:87).

The environment override was added, but the test fixtures do not set `QUANT_RESEARCH_LEDGER_DIR`. Pipeline tests therefore append to shared project state by default. The isolated run creates `/tmp/ml2-audit-20260911/data/research_ledgers/search_ledger.jsonl`, causing a teardown error; by suite completion that file contains 18 records. The fixture compares path sets only, so further modifications to that existing file escape detection. This also explains why an established workspace can hide the isolation defect. See the full-suite evidence.

Set an isolated ledger directory per test or test session, validate content as well as file creation, and avoid writing installed-package directories as the default application-state location. Test both absent and pre-existing ledger files. Earlier D12 is not closed by adding an unused environment hook.

**E23 — [P2] Repair stale regression tests and assertions that are always true.**

[test_accounting.py:35](/home/marnus/VS-Code/ML-2/tests/test_accounting.py:35), [test_selection_isolation.py:42](/home/marnus/VS-Code/ML-2/tests/test_selection_isolation.py:42), [test_pipeline.py:31](/home/marnus/VS-Code/ML-2/tests/test_pipeline.py:31).

The accounting test reconstructs price/information features without the nine extensions now included by the pipeline, so it compares different strategies. Selection-isolation tests assume every estimator has `coef_`/`intercept_` even though their default configuration now creates gradient boosting. Discovery's bounded-search assertion is `n <= max or n > max`, which is always true; its valid-score assertion is also tautological. The paper test infers latency from an integer field, and its purported duplicate test resubmits the already-mutated object rather than a reconstructed request with the same ID.

Use the production input assembly for same-experiment reconciliation, explicitly configure the estimator being tested or compare model-appropriate state, and assert observable effects rather than descriptive fields. Count actual candidate fits and actual OOS evaluations. Include the failing paths demonstrated in E03–E09 and E14–E17.

**E24 — [P2] Bind notebook diagnostics to the current experiment.**

[Institutional notebook, feature and baseline cells](/home/marnus/VS-Code/ML-2/Institutional_Quant_Research_Engine_V2.1.ipynb), [Colab notebook, per-fold-results cell](/home/marnus/VS-Code/ML-2/colab_test.ipynb).

The institutional notebook manually builds the older price/information feature set, uses an in-memory lock and local counter, displays its baseline and stress results, then invokes the current full pipeline, which adds nine signal extensions and uses different persistent controls. Those displayed diagnostics and the final registered experiment are different model specifications. The Colab notebook reads `glob.glob(f'{output_dir}/*_folds.csv')[0]`, so repeated runs can display a previous experiment's fold table next to the current report's summary. Static findings; the notebooks were inspected, not executed.

Drive all diagnostic cells from one returned report, or label and register separate experiments explicitly. Select fold artifacts by the returned `experiment_id`, or use `report['folds']` directly. Verify a notebook run with existing output files.

**E25 — [P2] Do not classify successful task content as a transport failure.**

[cline-runner.py:113](/home/marnus/VS-Code/ML-2/cline-runner.py:113), [cline-runner.py:336](/home/marnus/VS-Code/ML-2/cline-runner.py:336).

Error regexes scan all task/tool output and match bare `401`, `403`, `429`, `billing`, and similar content. Exit code zero with `Task completed. Added HTTP 403 and 429 regression tests.` is classified as an authentication failure. The main loop then switches accounts and reruns the same prompt with automatic approval, potentially repeating already-completed side effects. The helper's existing ten self-tests all pass despite this. Evidence: `runner_classifier` and `runner_self_test`.

Use structured CLI status/error information or tightly scoped terminal error records; preserve ordinary successful output as data. Test successful work discussing error codes and define safe recovery for ambiguous failures after partial completion. No Cline task was launched during this audit.

**What is working, and what remains outside the finding count**

- The saved seed-7 market baseline reproduces its 1,764 OOS observations exactly: net Sharpe **0.1973496855**, gross Sharpe **0.3403221182**, fee total **0.037473994**, slippage total **0.007494799**. Full source-feature leakage perturbation checks pass on that snapshot. These checks establish reproducibility for this run, not universal absence of leakage or trading profitability.
- Previous fixes confirmed by independent probes: incompatible persisted lock dataset/policy now raise; invalid JSON now raises; interior fold-end NaN and infinity now raise in baseline evaluation. The direct Parkinson consumer now rejects fabricated ranges. Discovery's global legacy APIs remain explicitly disabled. Baseline preprocessing is fitted on training data, and per-fold threshold selection uses validation data.
- Source review found additional limitations worth making explicit: no live order adapter or durable broker restart restoration; `FailureRestartTest` exercises operations on the same in-memory object, not process recovery; `_check_audit_trail_intact` is always true because it checks `len(...) >= 0`; monitoring's `n_filled_today` counts all filled orders. These should not be presented as verified operational readiness.
- Reproducibility metadata remains incomplete for arbitrary externally supplied features/events or dirty code: manifests contain event counts rather than event payloads, and only estimator class names rather than fitted state. The default synthetic event path can be regenerated, but this does not establish general replay. `get_git_info` depends on the caller's working directory and `git diff --quiet` omits staged-only and untracked changes. The confirmed saved-market replay used a clean recorded revision and saved inputs.
- No high-confidence private-key/AWS/GitHub/OpenAI key pattern was found in the 386 tracked paths scanned. This was a limited static scan, not a secret-history audit or dependency-CVE certification. No fresh provider download, external account access, live trading, package installation, or deployment was performed. The full 20-repetition-per-mode saved-market placebo battery was not rerun; market validation here covers the baseline, its exact replay, data integrity and feature-causality checks.

**Recommended repair order**

1. Prevent readiness promotion without real session evidence; correct breach accounting and kill-switch enforcement. Then repair liquidation, pending exposure, fill latency and order-ID idempotency together as one coherent execution ledger.
2. Fix nested replay costs and enforce discovery locks before fitting. Require a no-override nested replay to match the original positions, gross returns, turnover, fees, slippage and net returns exactly.
3. Make research history durable across data revisions and output locations; record starts before evaluation; reject corrupt history and malformed locks.
4. Correct parameter stress, candidate ranking, event revision/idempotency handling and OHLC provenance; repair the regression suite and notebook experiment binding.

Each repair should be accepted against the concrete behavioral counterexample above. Changing a comment, stored field or assertion name is not evidence that the underlying failure is resolved.
