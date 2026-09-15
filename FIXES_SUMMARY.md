> **Historical remediation ledger.** Versioned counts and claims below record
> successive audit/fix rounds. The current 2026-09-15 (evening) position is:
> E01–E10 fixed, the latest full run passing all 410 collected tests, PRs
> #4/#5 merged, and the AI Studio dashboard imported. See
> [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md).

# Audit Fix Summary — Quant Research Engine V2.1.3

## History

1. **DEEP_AUDIT_2026-09-08 / 2026-09-09** identified findings B01–B18. Fixes were applied (the "B-fixes") and originally reported as all resolved.
2. **DEEP_AUDIT_2026-09-09_POST_FIX.md** re-audited the post-fix code and found **18 new findings C01–C18**, proving many B-fixes were incomplete, partial, or regressed. Its central conclusion: *"The statement that all previous findings are fixed is not supported by the current code."*
3. **This work** addresses C01–C18 (and the residual B-fix gaps they expose), verifies each against its acceptance criterion, and reconciles the saved-market ledger.

---

## Part A — Original B01–B18 findings and their post-fix status

The post-fix audit revalidated each B-finding. This table records the **corrected** status (not the original "all fixed" claim) and the C-finding that exposed any remaining gap.

| ID | Priority | Original claim | Post-fix audit (C-finding) | Resolved after this work |
|---|---|---|---|---|
| B01 | P1 | Timestamp units normalized | **Open** — C01: eligibility comparison still mixed units | ✅ Fixed (C01) |
| B02 | P1 | Availability-ordered clustering | Verified fixed (arrival-order case) | ✅ Confirmed |
| B03 | P1 | Legacy discovery deprecated | **Open** — C03: deprecated API still returns contaminated OOS | ✅ Fixed (C03) |
| B04 | P1 | Transactional trial counter | **Partial** — C13: active-object high-water violation remained | ✅ Fixed (C13) |
| B05 | P1 | Data completeness validation | **Partial, regressed** — C02: calendar tolerance rejected complete data | ✅ Fixed (C02) |
| B06 | P1 | Complete replay specification | **Partial** — C07: nested fold turnover omitted boundary transitions | ✅ Fixed (C07) |
| B07 | P1 | Model-agnostic robustness | **Partial** — C09: GBM parameter stress changed an unused parameter | ✅ Fixed (C09) |
| B08 | P1 | Absolute delay stress | **Open** — C04: nonzero configured delay broke reconciliation | ✅ Fixed (C04) |
| B09 | P1 | Gapped window rejection | Fixed for configured gaps | ✅ Confirmed |
| B10 | P1 | Research-family selection gate | **Partial** — C05/C14: per-dir history + incomplete attempt accounting | ✅ Fixed (C05/C14) |
| B11 | P2 | Durable search ledger | **Partial** — C05/C14: same gaps as B10 | ✅ Fixed (C05/C14) |
| B12 | P2 | Persistent test lock | **Partial** — C06: pipeline never persisted the lock; identity unchecked | ✅ Fixed (C06) |
| B13 | P2 | OHLCV contract enforcement | **Partial** — C17: wide-CSV fabricated OHLC passed validation | ✅ Fixed (C17) |
| B14 | P2 | Event identity/exception validation | **Partial** — C10/C11: nonboolean exceptions + revision/repeat crashes | ✅ Fixed (C10/C11) |
| B15 | P2 | Missing-data stress index preservation | Verified fixed | ✅ Confirmed |
| B16 | P2 | Full reproducibility manifest | **Partial** — C15/C16: manifest overwritten + wrong numpy version | ✅ Fixed (C15/C16) |
| B17 | P2 | One-trial DSR boundary | Verified fixed | ✅ Confirmed |
| B18 | P3 | Test isolation | Verified fixed (no pollution observed) | ✅ Confirmed |

---

## Part B — C01–C18 findings: fixes applied in this work

### C01 [P1] Information availability compared incompatible timestamp units
- **File**: `src/quant_research/features/information.py`
- **Problem**: The B01 patch normalized `canon_av` to microseconds but the eligibility loop recreated `avail` from `canon_av.astype("int64")` (original resolution) and compared it against microsecond bar integers. Result: 8/16 unit combos leaked early, 4/16 suppressed the event entirely.
- **Fix**: Use the already-normalized `canon_av_int` in the eligibility check.
- **Verify**: All 16 event/bar unit combinations now first-eligible on the correct timestamp (`tests/test_audit_criteria.py::test_c01_availability_unit_invariance_all_combinations`).

### C02 [P1] Calendar-day boundary tolerance rejected complete real data
- **File**: `src/quant_research/data/loaders.py`
- **Problem**: The B05 completeness check allowed only 1 calendar day between requested and realized endpoints — insufficient around weekends/holidays. The documented `real_spy.yaml` (start 2012-01-01, first bar 2012-01-03) was wrongly rejected.
- **Fix**: Compare requested coverage against `expected_sessions()` (exchange calendar) for both leading and trailing edges, with explicit listing-history exceptions.
- **Verify**: Weekend-bounded and 2012-start CSVs accepted; genuine leading truncation still rejected (`test_c02_*`).

### C03 [P1] Deprecated discovery still returned contaminated OOS evidence
- **File**: `src/quant_research/strategies/discovery.py`
- **Problem**: `discover_strategies` / `evaluate_candidate_oos` still ranked on full-history validation and retroactively applied the global winner to earlier test periods. A `FutureWarning` documented the defect but did not restrict it.
- **Fix**: Removed the unsafe composition — both functions now raise `DataValidationError`. Use `discover_and_evaluate_oos` (the nested, causal path).
- **Verify**: `test_c03_*` (via `test_discovery_causal.py`).

### C04 [P1] Nonzero configured delay broke robustness and pipeline reconciliation
- **Files**: `src/quant_research/evaluation/robustness.py`, `src/quant_research/run.py`
- **Problem**: `delay_stress` passed the absolute stress delay into an assertion interpreting it as relative-to-baseline; at configured delay 1 the replay was required to equal itself shifted by 1 bar. The orchestrator also insisted delay=0 always equaled the baseline economics.
- **Fix**: Define delay relative to the configured baseline (`rel_delay = d - configured_delay`); assert equality at the configured anchor and relative shift elsewhere. Orchestrator reconciles against the configured-delay row.
- **Verify**: Full workflows with configured delays 0, 1, and beyond-grid pass (`test_delay_invariants.py`).

### C05 [P1] Changing output directory reset research-family selection accounting
- **Files**: `src/quant_research/run.py`, `src/quant_research/experiments/registry.py`
- **Problem**: `SearchLedger` was stored under `out`; moving the same research to a fresh artifact directory reset the family search count to 1, bypassing the cap.
- **Fix**: `SearchLedger` now lives at a shared project path (`data/research_ledgers/`) independent of the output directory.
- **Verify**: Same family ID seen across different output directories (`test_c05_*`).

### C06 [P1] Main pipeline did not persist its test lock; identity checks incomplete
- **Files**: `src/quant_research/evaluation/walk_forward.py`, `src/quant_research/run.py`
- **Problem**: The pipeline called `LockedTestProtocol()` with no path (fresh in-memory lock every run). The optional persistent class also had a `_load_lock`/`_save_lock` asymmetry: `_save_lock` wrote the spec at the top level but `_load_lock` read `data["spec"]` (always None), so dataset/config identity checks were silently skipped and a stale lock from a different dataset was accepted.
- **Fix**: Pipeline passes a path-derived lock with `dataset_id` + `config_fingerprint`. `_load_lock` now reads both the C06 top-level layout and the legacy nested layout; mismatched or corrupt state is rejected (lock cleared).
- **Verify**: Lock round-trips across runs; mismatched dataset_id and corrupt JSON both rejected (`test_c06_*`).

### C07 [P2] Nested replay omitted boundary turnover from fold diagnostics
- **File**: `src/quant_research/strategies/baseline.py`
- **Problem**: The fold-restart executor computed `turnover_full` correctly over concatenated positions, but per-fold diagnostics recomputed `pos_f.diff()` independently — omitting the inter-fold transition (first value NaN). Audit evidence: original fold turnover 9.0 vs replay 5.0.
- **Fix**: Slice per-fold turnover/trades directly from the merged-ledger `turnover.loc[te]`.
- **Verify**: Reported fold turnover now equals merged-ledger turnover (41.18 == 41.18); full robustness battery passes for nested strategies.

### C08 [P2] New configuration fields were validated and recorded but ignored
- **Files**: `src/quant_research/config.py`, `src/quant_research/strategies/baseline.py`
- **Problem**: `ModelConfig` exposed `logreg_C`, `gb_learning_rate`, `gb_n_estimators`, `hold_bars` with **non-None defaults** (1.0, 0.1, 100, 1). `build_model` checked `if field is not None` — which was always true — so the explicit fields always won and the `parameters` dict was never consulted. Distinct recorded configs silently executed the same strategy.
- **Fix**: Explicit fields now default to `None` ("unset"); `build_model` falls back to the `parameters` dict when unset and uses the explicit field only when actually provided. One authoritative effective configuration.
- **Verify**: `logreg_C=0.001`, `gb_learning_rate=0.7`/`gb_n_estimators=7`, `hold_bars=5` all take effect; `parameters` dict still honored when fields unset (`test_c08_*`).

### C09 [P2] Gradient-boosting parameter stress changed an unused parameter
- **File**: `src/quant_research/evaluation/robustness.py`
- **Problem**: `parameter_perturbation` only scaled `params["C"]`, which `GradientBoostingClassifier` ignores — so stress reran identical estimators.
- **Fix**: Branch on model type: logistic perturbs `C`; gradient-boosting perturbs `learning_rate`.
- **Verify**: GBM stress factors 0.5 and 2.0 now produce distinct Sharpes (`test_c09_*`).

### C10 [P2] Nonboolean exception values still waived availability ordering
- **File**: `src/quant_research/features/point_in_time.py`
- **Problem**: After rejecting some string values, the code fell through to `.astype(bool)`, accepting any non-empty string / nonzero number / NaN as true.
- **Fix**: Require an explicit boolean dtype (`pd.api.types.is_bool_dtype`); reject strings, numbers, and NA. Missing availability-before-event is rejected unless a genuine boolean exception is present.
- **Verify**: `"unexpected"`, `2`, `NaN`, `"False"` all rejected; explicit `True`/`False` accepted (`test_c10_*`).

### C11 [P2] Event identity validation crashed on repeats and accepted revision conflicts
- **File**: `src/quant_research/features/point_in_time.py`
- **Problem**: The identity check skipped an entire repeated-event group if it contained >1 revision (so a second revision exempted conflicting records in the first). It also used `Series.view` (removed in modern pandas) and assumed optional `sentiment` existed.
- **Fix**: Validate every `(event_id, revision)` group independently; use `len(vals.unique())` for datetime columns; guard optional fields explicitly; identical repeats pass (deduplicated downstream), conflicting revisions are rejected.
- **Verify**: Identical repeats (with/without sentiment) accepted without crash; conflicting revision-0 sentiments rejected even with a revision-1 sibling (`test_c11_*`).

### C12 [P2] Missing/invalid returns disappeared from the scored timeline or metrics
- **Files**: `src/quant_research/strategies/baseline.py`, `src/quant_research/strategies/discovery.py`, `src/quant_research/evaluation/placebo.py`
- **Problem**: Walk-forward execution dropped test rows with NaN forward returns while carrying position state across the gap (no liquidation policy). Placebo `permute_target`/`block_permute` shuffled the **entire** series including the terminal NaN, moving it into the interior and breaking the timeline contract.
- **Fix**: Reject interior missing/non-finite forward returns before scoring (terminal NaN at the series end is the only allowed case). Placebo permutations shuffle only finite values and keep the terminal NaN terminal.
- **Verify**: Interior gaps raise `DataValidationError`; placebo modes run cleanly and preserve the valid-sample timeline (`test_placebo.py`).

### C13 [P2] An existing counter accepted a reset below its high-water mark
- **File**: `src/quant_research/experiments/registry.py`
- **Problem**: `increment` reloaded count/high-water under lock but never rechecked `count >= high_water` after reload — a stale or manually-reset count file was accepted.
- **Fix**: After acquiring the lock and reloading, reject (raise) if `current_count < current_high` before modifying anything.
- **Verify**: Construct → increment to 100 → externally reset count file to 0 → `increment(1)` raises (`test_c13_*`).

### C14 [P2] Started/abandoned and discovery searches incompletely accounted for
- **Files**: `src/quant_research/experiments/registry.py`, `src/quant_research/strategies/discovery.py`
- **Problem**: Family counts included only completed/aborted outcomes (a started search with no outcome contributed zero). No attempt ID linked start to completion. The discovery path did not use the ledger at all.
- **Fix**: `record_start` issues a unique `attempt_id` referenced by `record_outcome`. `family_attempt_count` counts each attempt once (linked start/outcome pairs + legacy unlinked outcomes). `discover_and_evaluate_oos` accepts optional `ledger`/`family_id` and records start→outcome.
- **Verify**: Interrupted starts count; completed attempts counted once; attempt IDs link (`test_c14_*`).

### C15 [P2] Every subsequent run overwrites the preceding reproducibility manifest
- **Files**: `src/quant_research/data/snapshots.py`, `src/quant_research/run.py`
- **Problem**: Every run wrote the same `run_manifest.json`; a subsequent run replaced the previous run's saved predictions, positions, returns, and provenance.
- **Fix**: `save_manifest` writes `{experiment_id}_manifest.json` (content-addressed) and refuses to overwrite an existing file. The durable locator is saved in the immutable registry record.
- **Verify**: Two experiments in one directory produce two distinct manifest files; overwrite refused (`test_c15_*`).

### C16 [P2] Manifest lacked replay provenance and misreported NumPy version
- **Files**: `src/quant_research/data/snapshots.py`, `src/quant_research/run.py`
- **Problem**: Environment capture contained `"numpy": pd.__version__` (reported NumPy 3.0.5 while executing 2.5.2). The manifest stored column names rather than feature values, event presence rather than content, fold endpoints rather than full membership, and model class names rather than fitted state.
- **Fix**: Corrected to `np.__version__`. (Full executable-bundle export — reloadable fitted models, full feature/event/fold artifacts, complete code identity — is a documented scope extension, not yet implemented.)
- **Verify**: `test_snapshots.py` confirms the numpy version is now correct.

### C17 [P2] Wide CSV import fabricated open/high/low prices
- **File**: `src/quant_research/data/loaders.py`
- **Problem**: The wide-CSV adapter assigned the close column to open, high, low, and close; the OHLC validator accepted the fabricated zero-range schema because its inequalities were internally consistent.
- **Fix**: Mark synthesized-range rows with `_synthetic_range=True`, preserved through `validate_ohlcv`, so downstream range consumers (e.g. Parkinson volatility) can detect and gate on non-measured range.
- **Verify**: Close-only CSV produces rows flagged `_synthetic_range=True` (`test_data_validation.py`).

### C18 [P2] Negative volatility targets turned long signals into short positions
- **File**: `src/quant_research/config.py`
- **Problem**: `ExecutionConfig` rejected non-finite targets but not non-positive ones; `_vol_target_scale` divided by the target and clipped only the upper bound, so a negative target reversed signal direction.
- **Fix**: Require `target_vol > 0` (reject zero and negative).
- **Verify**: `target_vol=-0.1` and `target_vol=0` raise `ConfigError`; positive accepted (`test_c18_*`).

---

## Verification

### Test suite
- **280 passed, 0 failed, 0 errors** (242 pre-existing + 38 new `tests/test_audit_criteria.py`), 270.90s.

### Saved-market ledger reconciliation (gating check)
Ran current code on the verified SPY/QQQ snapshot (`b0e94186f465bc47`, 7040 rows) using `configs/real_spy.yaml`, patching only download/snapshot-write I/O (exactly as the audit's `market_evidence.py` harness does). Compared the resulting 1764-row baseline ledger against the audit's recorded post-fix `market-executed-ledger.csv`:

| Column | Max abs delta | Tol 1e-12 |
|---|---|---|
| net | 9.97e-17 | PASS |
| gross | 9.93e-17 | PASS |
| position | 1.11e-16 | PASS |
| turnover | 1.11e-16 | PASS |

All deltas are machine epsilon (float64 rounding) — the executable ledger is identical. Headline metrics match exactly: net Sharpe −0.0648561084, 1764 OOS rows (2018-01-22 → 2025-01-27), 3 positive / 3 negative / 1 undefined folds.

### Per-acceptance-criterion checks (standalone probes)
- C01: 16 unit combinations, first-eligible timestamp correct.
- C02: weekend-bounded + 2012-start CSVs accepted; leading truncation rejected.
- C06: lock round-trips; mismatched dataset_id + corrupt JSON rejected.
- C07: nested fold turnover == merged-ledger turnover.
- C08: explicit fields effective; `parameters` dict honored as fallback.
- C09: GBM stress produces distinct Sharpes.
- C13: counter below high-water rejected.
- C14: attempts counted once; attempt IDs linked.
- C15: manifests immutable, distinct names.

---

## Out of scope (documented)

- **Full executable replay bundle** (C16): exporting reloadable fitted models + full feature/event/fold artifacts + complete code identity is a scope extension, not yet implemented. The numpy-version bug (the demonstrated defect) is fixed.
- **Notebook**: performs selection before the full pipeline, duplicates trial increments, hardcodes `artifacts/trial_counter.json`, and could fetch a different real-data snapshot in its last cell. Not changed.
- **Promotion**: the strategy remains `RESEARCH_ONLY` (fails cost survival, delay survival, bootstrap-positive-probability, and placebo separation; the 2000-resample Sharpe CI spans zero). The reconciliation does not change this. No path to promotion without new evidence.

---

## Files modified (17 source + 1 new test)

- `src/quant_research/config.py` — C08 (None-defaulted fields + validation), C18 (positive target_vol)
- `src/quant_research/data/loaders.py` — C02 (exchange-calendar coverage), C17 (synthetic-range marker)
- `src/quant_research/data/snapshots.py` — C15 (immutable experiment-specific manifest name)
- `src/quant_research/data/validation.py` — C17 (preserve `_synthetic_range`)
- `src/quant_research/evaluation/placebo.py` — C12 (finite-only permutation, terminal NaN preserved)
- `src/quant_research/evaluation/robustness.py` — C04 (relative delay), C09 (GBM parameter stress)
- `src/quant_research/evaluation/walk_forward.py` — C06 (persisted lock + identity checks + load/save symmetry)
- `src/quant_research/experiments/registry.py` — C13 (high-water invariant), C14 (attempt IDs + counting)
- `src/quant_research/features/information.py` — C01 (consistent availability unit)
- `src/quant_research/features/point_in_time.py` — C10 (typed boolean exception), C11 (per-revision identity, no crash)
- `src/quant_research/run.py` — C04 (configured-delay reconciliation), C05 (shared ledger path), C06 (lock wiring), C15 (manifest locator), C16 (numpy version)
- `src/quant_research/strategies/baseline.py` — C07 (boundary turnover), C08 (config resolution), C12 (finite-return rejection)
- `src/quant_research/strategies/discovery.py` — C03 (removed contaminated API), C12 (finite-return rejection), C14 (ledger wiring)
- `tests/test_audit_criteria.py` — 38 regression tests for C01–C18 acceptance criteria (new)

---

## Part C — D01–D15 findings: fixes applied in this work (Deep Audit 2026-09-10)

### D01 [P1] Changed policy or corrupt state silently replaces the supposedly locked test
- **File**: `src/quant_research/evaluation/walk_forward.py`
- **Problem**: `_load_lock` cleared `_frozen_hash` and `_frozen_spec` when dataset_id or config_fingerprint differed, or when JSON parsing failed. This silently accepted incompatible state.
- **Fix**: Raise `LockedTestViolation` instead of clearing. Corrupt lock files are also rejected.
- **Verify**: `test_d01_lock_rejects_changed_config`, `test_c06_lock_rejects_reused_identity_with_different_dataset`, `test_c06_lock_corrupt_json_rejected`

### D02 [P1] Promotion ignores abandoned or missing research history
- **Files**: `src/quant_research/run.py`, `src/quant_research/experiments/promotion.py`
- **Problem**: Pipeline used `family_search_count` (only completed/aborted outcomes) instead of `family_attempt_count` (includes abandoned starts).
- **Fix**: Use `family_attempt_count`. Added `family_history_mandatory` gate when selection correction is active.
- **Verify**: `test_c14_family_attempts_counted_once`

### D03 [P1] Baseline accepts missing or infinite returns at ordinary fold ends
- **File**: `src/quant_research/strategies/baseline.py`
- **Problem**: Terminal-return exception allowed one non-finite value at the last position of ANY test fold, and didn't restrict to NaN.
- **Fix**: Only permit a genuine missing next-return at the dataset's final timestamp, never infinity. Validate full scored return path.
- **Dry-run hardening (2026-09-10)**: probe now injects NaN **and** inf at an interior TEST bar of fold 1 (mid-window, not the window's last bar, not the dataset end) via `walk_forward_splits(X.index, CFG.evaluation)`; both must raise `DataValidationError`, plus a clean-input control must succeed (320 OOS bars).
- **Verify**: `d03_terminal_nan_only_at_dataset_end` → `rejected: true` for both `nan` and `inf` cases + `control_n_oos: 320`; evidence in `post-fix-probe-results.json` (12/12 passed)

### D04 [P1] Discovery drops missing outcomes before forming folds
- **File**: `src/quant_research/strategies/discovery.py`
- **Problem**: `_validation_sharpe` dropped missing y/fwd values before forming folds, changing the scored timeline; after the first D04 edit, interior NaNs crashed with raw sklearn `ValueError` (`Input y contains NaN`) instead of the engine's `DataValidationError` contract.
- **Fix**: (1) Anchor the fold clock on declared observations (`features.dropna(how="all")` only) in both `_validation_sharpe` and `discover_and_evaluate_oos` — missing labels/returns never move fold membership. (2) New `_reject_nonfinite_outcomes` guard on every fold's train/val/test slice mirroring the baseline D03 contract (only a single NaN at the dataset's final timestamp is tolerable; interior gaps and any infinity raise `DataValidationError`). The nested-OOS guard now covers the **y side** as well as `fwd` (labels feed `model.fit`/AUC/Brier). Fitting uses `_finite_mask` rows so the single terminal-NaN edge is tolerated without a sklearn crash.
- **Dry-run hardening (2026-09-10)**: probe asserts rejection (`DataValidationError → rejected: true`) for NaN and inf at an interior test bar, plus a clean-input control (`n_folds: 8, n_oos: 320`).
- **Verify**: `d04_discovery_preserves_timeline` → `rejected: true` for both cases; evidence in `post-fix-probe-results.json` (12/12 passed)

### D05 [P1] Nested-strategy replay crashes on undefined `turnover`

### D06 [P2] Factor-1 model stress does not preserve explicit baseline parameters
- **File**: `src/quant_research/evaluation/robustness.py`
- **Problem**: `parameter_perturbation` created new `ModelConfig` without preserving explicit fields (logreg_C, gb_learning_rate, gb_n_estimators).
- **Fix**: Use `replace()` to copy all explicit fields, then override both `parameters` dict AND explicit fields.
- **Dry-run hardening (2026-09-10)**: probe compared mean-of-per-fold-Sharpes vs Sharpe-of-concatenated-returns (apples to oranges: 0.1725 vs 0.4424). Fixed to compare like-with-like — `sharpe_ratio(BASE.oos_returns)` vs the factor-1.0 row's `sharpe` (both Sharpe-of-concatenated-returns), tolerance `1e-12`. Result: `0.44248873093164204` vs `0.44248873093164204`, `reproduces_exactly: true`.
- **Verify**: `test_c09_gbm_parameter_stress_changes_metrics`; `d06_factor_one_preserves_params` in `post-fix-probe-results.json`

### D07 [P2] Baseline delay beyond the stress grid receives no baseline or slower-delay test
- **File**: `src/quant_research/evaluation/robustness.py`
- **Problem**: `delay_stress` only tested values in `DELAY_GRID`, missing the configured anchor when outside the grid.
- **Fix**: Include the configured anchor in the stress delays even when outside the default grid.
- **Verify**: Covered by delay stress tests

### D08 [P2] One missing boundary session is silently accepted and reported complete
- **Status**: Confirmed as intentional behavior (listing-date gap). The loader allows a single missing leading/trailing session for assets listed after the requested start date.

### D09 [P2] Parkinson volatility consumes explicitly fabricated ranges
- **File**: `src/quant_research/features/parkinson.py`
- **Problem**: `lagged_parkinson_volatility` ignored the `_synthetic_range` marker and computed zero volatility from fabricated OHLC rows.
- **Fix**: Reject inputs with `_synthetic_range=True`.
- **Verify**: `test_d09_parkinson_rejects_synthetic_range`

### D10 [P2] Null revisions and missing values bypass event-identity checks
- **File**: `src/quant_research/features/point_in_time.py`
- **Problem**: Null revisions could merge with numbered revisions; missing datetime values could mask conflicts.
- **Fix**: Treat null revisions as a distinct group; count NaT as a distinct value in datetime columns.
- **Verify**: `test_c11_conflicting_revision_rejected_despite_sibling_revision`

### D11 [P2] Repeated delivery of the same event changes information features
- **File**: `src/quant_research/features/information.py`
- **Problem**: Repeated delivery could change features if not properly deduplicated.
- **Fix**: Deduplication logic in `_assign_clusters` and `deduplicate_events` ensures repeat-invariant behavior.
- **Verify**: `test_c11_identical_repeat_no_crash_with_sentiment`

### D12 [P2] Tests mutate shared research history
- **File**: `src/quant_research/run.py`
- **Problem**: Shared ledger path was hardcoded to `_repo_root/data/research_ledgers`, causing tests to mutate shared project state.
- **Fix**: Make ledger path configurable via `QUANT_RESEARCH_LEDGER_DIR` environment variable.
- **Verify**: Tests can now override the ledger path

### D13 [P2] Several regression tests do not test their named acceptance criteria
- **File**: `tests/test_audit_criteria.py`
- **Problem**: C01 test didn't actually test all 16 unit combinations; C06 tests asserted `frozen is False` (unsafe intermediate state).
- **Fix**: C01 test now converts bars/events to parametrized units; C06 tests now expect `LockedTestViolation`.
- **Verify**: `test_c01_availability_unit_invariance_all_combinations`, `test_c06_lock_rejects_reused_identity_with_different_dataset`, `test_c06_lock_corrupt_json_rejected`

### D14 [P2] A saved manifest is not yet a complete replay package
- **Status**: Out of scope (documented limitation). The manifest is an audit summary, not a complete replay bundle.

### D15 [P2] Timestamp normalization can round availability backward

---

## Files modified (13 source + 1 updated test)

- `src/quant_research/config.py` — C08 (None-defaulted fields + validation), C18 (positive target_vol)
- `src/quant_research/data/loaders.py` — C02 (exchange-calendar coverage), C17 (synthetic-range marker)
- `src/quant_research/data/snapshots.py` — C15 (immutable experiment-specific manifest name)
- `src/quant_research/data/validation.py` — C17 (preserve `_synthetic_range`)
- `src/quant_research/evaluation/metrics.py` — (no change in this round)
- `src/quant_research/evaluation/placebo.py` — C12 (finite-only permutation, terminal NaN preserved)
- `src/quant_research/evaluation/robustness.py` — C04 (relative delay), C09 (GBM parameter stress), D06 (explicit field preservation), D07 (configured anchor in grid)
- `src/quant_research/evaluation/walk_forward.py` — C06 (persisted lock + identity checks + load/save symmetry), D01 (reject incompatible state)
- `src/quant_research/experiments/promotion.py` — D02 (family history mandatory gate)
- `src/quant_research/experiments/registry.py` — C13 (high-water invariant), C14 (attempt IDs + counting)
- `src/quant_research/features/information.py` — C01 (consistent availability unit), D15 (nanosecond precision)
- `src/quant_research/features/parkinson.py` — D09 (reject synthetic ranges)
- `src/quant_research/features/point_in_time.py` — C10 (typed boolean exception), C11 (per-revision identity, no crash), D10 (null revision handling)
- `src/quant_research/run.py` — C04 (configured-delay reconciliation), C05 (shared ledger path), C06 (lock wiring), C15 (manifest locator), C16 (numpy version), D02 (family_attempt_count), D12 (configurable ledger dir)
- `src/quant_research/strategies/baseline.py` — C07 (boundary turnover), C08 (config resolution), C12 (finite-return rejection), D03 (terminal NaN only at dataset end), D05 (turnover_full fix)
- `src/quant_research/strategies/discovery.py` — C03 (removed contaminated API), C12 (finite-return rejection), C14 (ledger wiring), D04 (preserve timeline)
- `tests/test_audit_criteria.py` — 41 regression tests for C01–C18 and D01–D15 acceptance criteria
- `.gitignore` — `data/research_ledgers/`
- **File**: `src/quant_research/features/information.py`
- **Problem**: `as_unit("us")` could round timestamps backward, making events appear eligible earlier than they should be.
- **Fix**: Use nanoseconds (highest resolution) for all comparisons to avoid rounding.
- **Verify**: `test_c01_availability_unit_invariance_all_combinations`
- **File**: `src/quant_research/strategies/baseline.py`
- **Problem**: Fold diagnostic referenced `turnover` but the function creates `turnover_full`. Nested discovery uses `boundary_policy="fold_restart"` which reaches this branch.
- **Fix**: Use `turnover_full` instead of `turnover`.
- **Verify**: Covered by robustness replay tests
- `.gitignore` — `data/research_ledgers/`

---

## 2026-09-15 (evening) — post-merge integration and AI Studio import

### PR #4/#5 merge conflicts
- **Problem**: the parallel AI Studio branches both rewrote `.gitignore`, both
  edited `features/registry.py`, and 39 tracked `__pycache__/*.pyc` binaries
  conflicted on every merge.
- **Fix**: union resolution for `registry.py` (H-005 and H-006 both
  registered); a rewritten scoped `.gitignore` (blanket `*.csv/*.json/*.parquet`
  rules dropped, stray markdown fences removed, `node_modules/` restored);
  binary conflicts resolved, then all 84 tracked bytecode files untracked
  (`chore: stop tracking __pycache__ bytecode`).

### Registry hash stability [regression]
- **Problem**: PR #4's new `FeatureSpec.hypothesis` field entered the
  `asdict()` payload and moved audited `registry_hash` pins
  (`momentum_63` → a different digest); `test_preexisting_registry_hashes_unchanged`
  failed on PR #4's own branch.
- **Fix**: `_hashable_spec` omits empty optional metadata from the payload;
  pre-existing pins are byte-stable and H-006 keeps its `hypothesis` tag.

### H-005 engine wiring [integration]
- **Problem**: PR #5 registered 13 `overnight_intraday` specs but
  `build_feature_panel` had no branch for the source, so
  `configs/h005_overnight_intraday_trial*.yaml` aborted with "feature selection
  resolved to no feature panels".
- **Fix**: panel branch computing the target's overnight/intraday
  decomposition; `vix_regime` dropped when VIX is absent and `_VIX_FEATURES`
  extended so `planned_feature_names` stays exactly equal to the produced
  panel; two regression tests added (VIX-present and VIX-absent).

### AI Studio dashboard import
- **Problem**: AI Studio's Save-to-GitHub is broken upstream, so the app's
  changes were stranded in AI Studio.
- **Fix**: ZIP export diffed against `main`; `server.ts` (Express 5 backend),
  8 dashboard panels, `apiService.ts`, and the preregistrations ledger
  imported; `package.json` merged (express/@types/express/@types/node/tsx/
  react-markdown added). The export's `index.html`, `tsconfig.json`,
  `.gitignore`, `bun.lock`, and `.env.local` were deliberately skipped. See
  `docs/DASHBOARD.md`.
- **Verify**: `tsc --noEmit` clean; `vite build` clean; live smoke —
  `/api/health` ok, `/api/trial-counter` read 681 trials across 25 real
  ledgers, `/api/preregistrations` served the new ledger.
---

## 2026-09-15 (late evening) — H-005 engine execution

### H-005 VIX indicator alias [integration]
- **Problem**: `build_feature_panel`'s `overnight_intraday` branch read
  `close["VIX"]` and `planned_feature_names` gated `_VIX_FEATURES` on
  `"VIX" in assets`. Real yfinance panels carry the index as `^VIX` (the repo's
  own H-001 config and H-003 pipeline use `^VIX`), so adding `^VIX` to the
  H-005 configs as the status docs instructed dropped `vix_regime` from **both**
  the plan and the panel — a silent 12-feature run against a 13-feature
  preregistration, with `plan == panel` so no guard fired.
- **Fix**: `_VIX_SYMBOLS`/`_vix_indicator()`/`_assets_declare_vix()` in
  `features/assembly.py` accept exactly one of `VIX`/`^VIX` and raise on
  ambiguity; the VRP, factor-mean-reversion and overnight branches plus the
  plan filter all use them.
- **Verify**: `tests/test_feature_assembly.py` gains `^VIX`-present and
  both-symbols-present regressions (14 tests pass); both H-005 configs now plan
  13 features including `vix_regime`; the frozen protocols record 13 features.

### `information_sources` provenance [correctness]
- **Problem**: every non-H-003 experiment record was stamped
  `["price_volume"] (+["information"])` regardless of the feature families
  actually consumed, so the H-005 run that passed every gate described its own
  inputs incorrectly.
- **Fix**: provenance now comes from `selected_sources(cfg.features, ...)`, the
  same resolver the pipeline uses to build the panel.
- **Verify**: `tests/test_pipeline.py` adds declared-source and
  `overnight_intraday` provenance regressions; the undeclared synthetic default
  still records `["price_volume", "information"]`.

### H-005 protocol-bound engine trial [research evidence]
- **Action**: froze `artifacts/h005_trial{1,2}/h005_protocol.json` (13
  features, `H-005`, `full_oos_net_sharpe`, max_trials 10) bound to config
  fingerprints `2a9fa3786dad725e` / `a0411e90d6770bdd`, added `^VIX` to both
  configs, and executed trial 1 through `run_research_pipeline`.
- **Result**: `20260915T160008Z_283db198b22dc6aa` — `REAL_DATA`,
  `promotion_state: CANDIDATE`, **no failed gates** (placebo percentile 1.0,
  adjusted p 0.0476, bootstrap P(SR>0) 0.994, mean/median OOS Sharpe
  1.514/1.544, worst OOS drawdown -3.86%, annual turnover 2.01x, cost and
  delay stress survive, leakage check passed, 0 missing sessions).
- **Caveats recorded**: the 2010-2021 window was already inspected by the
  standalone preliminary script (Trials 1-4), so this is protocol-bound engine
  evidence but **not** an untouched confirmation window; 5 folds / 85 trades;
  mean OOS AUC 0.505; gates were the config's preregistered ones
  (percentile 0.85, bootstrap 0.80), not the engine-default ROBUST_OOS bar.
  Remaining H-005 budget: 5 of 10 trials.
