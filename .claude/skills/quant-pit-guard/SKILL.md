---
description: "Leakage-safe quant research guard. Consult before touching data loading, PIT events/features, walk-forward splits, backtests, discovery, robustness/placebo, trial accounting, registry, promotion, or any metric/gate/reproducibility claim. Enforces PIT causality, locked-test identity, scored-timeline preservation, evidence-gate contracts, and all 18 C-finding + 15 D-finding fixes. Trigger on any code change in src/quant_research/ (except docs-only edits)."
name: quant-pit-guard
---

# Quant PIT Guard (Quant Research Engine V2.1.3 — Post C01-C18 + D01-D15 Fix Audit State)

> **Use this skill when** you touch ANY code in `src/quant_research/` — especially data loading, PIT events/features, walk-forward splits, backtests, discovery, robustness/placebo, trial accounting, registry/leaderboard, promotion, or any metric/gate/reproducibility claim.
>
> **Skip it** for: docs-only typo fixes outside `src/`, `tests/`, `configs/`; comments; formatting-only changes with no logic impact.
>
> **This repo is a research platform, not a Sharpe-maximizer.** Promotion defaults to rejection. Every gate must pass explicitly. Never "improve" a metric by relaxing a gate, re-cutting test windows, reselecting on test, or presenting synthetic/offline output as market evidence.
>
> **Status**: All C01–C18 and D01–D15 findings from DEEP_AUDIT 2026-09-09/10 have been resolved and verified with 41+ regression tests in `tests/test_audit_criteria.py`. The skill enforces these fixed invariants. D14 (full replay bundle) remains a documented OUT_OF_SCOPE limitation — do not claim complete reproducibility.

## Quick Reference — Touch This → Check That

| You touch... | Check these findings / invariants |
|--------------|-----------------------------------|
| `features/point_in_time.py` | C10 (boolean exceptions), C11 (per-revision identity), D10 (null revision error), D11 (dedup) |
| `features/information.py` | C01 (ns-precision), D15 (no unit rounding backward, boundary tests) |
| `features/parkinson.py` | D09 (reject `_synthetic_range`), raise `DataValidationError` with "synthetic" |
| `data/loaders.py` | C17 (preserve `_synthetic_range`), D08 (session coverage vs exact request) |
| `data/snapshots.py` | C15 (immutable manifest name), C16 (`np.__version__`), D14 (summary only) |
| `evaluation/walk_forward.py` | D01 (LockedTestViolation on mismatch/corrupt), D05 (`turnover_full`), C06 (persistent lock + identity) |
| `evaluation/robustness.py` | D06 (explicit model fields at factor 1), D07 (anchor + additional-delay) |
| `strategies/baseline.py` | D03 (only dataset-end NaN), D05 (`turnover_full`), D06 (explicit fields) |
| `strategies/discovery.py` | D04 (clock first), D02 (ledger wiring + attempt_id), D10/D11 (null revision + dedup) |
| `experiments/registry.py` | C14 (attempt_id + family_attempt_count), C15 (immutable manifest) |
| `experiments/promotion.py` | D02 (family_attempt_count, family_history_mandatory) |
| `run.py` | D12 (injectable ledger path), D02 (family_attempt_count at promotion) |

---

## Table of Contents

1. Absolute Prohibitions — patterns that cause immediate rejection
2. Core Invariants — non-negotiable rules for this codebase
3. Gate Contracts — promotion and reproducibility gates
4. File-Specific Guardrails — per-module invariants (4.1–4.12)
5. Verification & Promotion Checklist — before you commit
6. Research Ethics Boundary — how to present results
7. Common Pitfalls — anti-patterns and correct approaches
8. Failure Mode Index — all C01-C18 + D01-D15 findings, one row each
9. Out of Scope — documented limitations

---

## 0. Repository Structure & File-Level Detail

```
src/quant_research/
  config.py                 YAML config + fingerprint; target_vol > 0 enforced (C18)
  data/
    loaders.py              market loading + session-coverage check; rejects _synthetic_range (C17); exact session-set coverage (D08)
    schemas.py|validation.py  long-schema gate; preserves _synthetic_range marker
    snapshots.py            immutable hash-named manifests per experiment (C15); registry locator absent (D14 OUT_OF_SCOPE)
  features/
    point_in_time.py        PIT validation: typed boolean exception (C10), per-revision identity (C11), null revision handling (D10)
    information.py          ns-precision availability eligibility (C01, D15); canon_av_int used for comparison; no submicrosecond rounding backward
    parkinson.py            rejects fabricated ranges (D09); checks _synthetic_range
    price_volume.py|leakage.py|registry.py
  evaluation/
    walk_forward.py         locked test persistence + identity checks (C06); D01: rejects changed config/corrupt lock with LockedTestViolation; D05: turnover_full for nested replay
    backtest.py|bootstrap.py|metrics.py|multiple_testing.py|overfitting.py|placebo.py|robustness.py
    robustness.py           D06: parameter stress preserves explicit model fields; D07: anchor + additional-delay in grid
    placebo.py              C12: finite-only permutation, terminal NaN preserved, no trial touch; D03: internal missing returns rejected
  strategies/
    baseline.py             D03: only dataset-end NaN tolerated; interior NaN/inf rejected; D05: turnover_full for fold_restart; explicit model field preservation (D06)
    discovery.py            D04: clock on declared observations before label/outcome inspection; D02: ledger wiring with attempt_id; D10/D11: null revision error + dedup
  experiments/
    registry.py             family_attempt_count (D02/C14); attempt_id linking; immutable manifest names (C15)
    promotion.py            family_history_mandatory gate (D02); uses family_attempt_count not family_search_count
    leaderboard.py
  execution/
    paper.py|safeguards.py
  run.py                    D12: test isolation via injectable ledger path; D02: family_attempt_count at promotion
  portfolio/
    construction.py|risk.py
```

## 1. Absolute Prohibitions (touching these = immediate rejection)

| Pattern | Why | What to do instead |
|---------|-----|-------------------|
| `fillna/dropna` **before** fold cut in discovery | D04: Timeline re-clocking = scored-timeline corruption | **Clock first on declared observations; never drop or fill missing values before scorable fold assignment;** handle missing via stress tests |
| Bare `turnover` where `turnover_full` is defined | D05: nested fold_restart breaks | Use `turnover_full` or merge actual turnover series |
| `as_unit("us")` / `as_unit("ms")` on availability | D15: ns-precision only; unit rounding leaks backward | Use nanoseconds for all availability comparisons; never round unavailable events backward |
| Threshold chosen on test set | Selection on test = leakage | Threshold must be validation-only |
| Fit on full frame before split | Look-ahead = leakage | Train-slice-only fitting |
| `frozen is False` after tamper | D01/D13: vacuous test | Require `LockedTestViolation` raise; test actual rejection |
| Relaxing any promotion gate | Metric gaming | Gate stays; strategy stays RESEARCH_ONLY |
| Presenting synthetic/offline as market evidence | Misrepresentation | Always label `SYNTHETIC_OFFLINE` |
| Resetting or lowering trial_counter | D02/D13: accounting fraud | Counter only increases; high-water prevents reset |
| Wildcard pass on null revision/identity | D10: silent acceptance | Error on null revision; reject missing identity |
| Duplicate event delivery without dedup | D11: evidence inflation | Dedup, no inflation |
| Using `family_search_count` instead of `family_attempt_count` at promotion | D02: ignores abandoned/missing starts | Use `family_attempt_count`; require `family_history_mandatory` when selection correction active |
| Parameter stress not preserving explicit model fields | D06: different effective model at factor 1 | Resolve and persist one effective per-model spec; alter only intended parameter |
| Delay stress without configured anchor + additional-delay test | D07: only faster executions tested | Always include configured anchor and additional-delay stress; clarify absolute vs added latency |
| One-session completeness exception in loader | D08: undocumented boundary tolerance | Compare observed coverage to exact requested session set; any exception must be explicit, recorded, reflected in integrity |
| Parkinson consuming `_synthetic_range` rows | D09: fabricated volatility | Reject or gate on `_synthetic_range=True`; raise `DataValidationError` |
| Acceptance tests asserting `frozen is False` | D13: vacuous test | Require actual `LockedTestViolation` raise or real criterion |

## 2. Core Invariants (non-negotiable)

### 2.1 Point-in-Time Causality
- Events must be available **after** the bar they influence. No look-ahead.
- PIT validation: boolean typed exceptions only (C10). Per-revision identity preserved (C11). Null revision → error, never wildcard (D10).
- Duplicate event delivery must be deduplicated; no evidence inflation (D11).

### 2.2 Locked Test Integrity
- Once a walk-forward test is frozen, subsequent runs with different config/dataset **must raise `LockedTestViolation`**, not silently clear state (D01).
- Corrupt lock files are rejected, not cleared (D01).
- Test identity includes dataset_id + config_fingerprint; both checked on load (C06).
- `frozen is False` after tampering is a **vacuous test** — require actual raise (D13).

### 2.3 Scored Timeline Preservation
- Fold clock derives from declared observations **before** inspecting labels/outcomes (D04). It must not advance by pre-processing missing values — never fill or drop missing values before scorable fold assignment.
- Discovery does not drop missing outcomes before forming folds (D04).
- Missing labels/returns never move fold membership.

### 2.4 Return Validity
- Only a genuine missing next-return at the **dataset's final timestamp** is tolerable (D03).
- Interior NaN/inf at fold boundaries → `DataValidationError` (D03).
- Infinity is never acceptable as a return (D03).
- Placebo permutes only finite values; terminal NaN preserved; trial count untouched (C12).

### 2.5 Trial Accounting
- `trial_counter` only increases; high-water mark prevents reset (C13).
- After increment, recheck `count >= high_water` under lock; stale/resets rejected (C13).
- `family_attempt_count` counts each attempt once (linked start/outcome + legacy unlinked) (C14/D02).
- `family_search_count` excludes abandoned starts — **do not use at promotion** (D02).
- Discovery records start **before** evaluating candidates (D02).
- Promotion requires `family_history_mandatory` when selection correction is active (D02).

### 2.6 Parameter Stress Integrity
- Parameter stress must preserve explicit model fields (D06).
- At factor 1: identical estimator settings, predictions, and executed ledger required (D06).
- Cover explicit fields, parameter dicts, direct `model_cfg` overrides, mixed-model nested results (D06).

### 2.7 Delay Stress Completeness
- Delay stress table must include configured anchor + declared additional-delay stress (D07).
- Define whether promotion requires absolute or added latency; enforce in table and gate (D07).
- Reconcile anchor for baseline delays 0, 1, and values beyond default grid (D07).

### 2.8 Data Completeness
- Compare observed session coverage to **exact requested session set** (D08).
- Any listing/history exception must be explicit, recorded, and reflected in integrity status (D08).
- One missing leading or trailing session → `DataValidationError` (D08).

### 2.9 Range Fabrication
- `_synthetic_range=True` marker preserved through loader → validator → consumer chain (C17/D09).
- Parkinson volatility **must reject** `_synthetic_range=True` inputs (D09).
- Range consumers must check the marker; no silent consumption of fabricated ranges (D09).

### 2.10 Timestamp Precision
- All availability comparisons at nanosecond precision (C01/D15).
- Never round an unavailable event backward into eligibility (D15).
- Test events just before, exactly at, and just after bar boundary including canonical events and copies (D15).

### 2.11 Configuration
- `target_vol > 0` enforced; zero and negative rejected (C18).

### 2.12 Manifests & Reproducibility
- Each experiment gets immutable `{experiment_id}_manifest.json`; overwrite refused (C15).
- Registry record written before manifest; manifest_path added to report, **not** to immutable registry record (D14 — documented limitation).
- Full executable replay bundle is **OUT_OF_SCOPE** — do not claim complete reproducibility (D14).
- NumPy version captured from `np.__version__`, not `pd.__version__` (C16).

### 2.13 Test Isolation
- Shared research ledger path must be injectable/configurable; override for every test (D12).
- Protect pre-existing project state using hashes or explicit write interception, not only new-path detection (D12).
- Suite must preserve pre-existing ledger content and produce no new project data on both clean and populated workspaces (D12).

### 2.14 Acceptance Test Quality
- Replace tautologies with observable requirements (D13).
- Each regression must fail against the corresponding defective behavior (D13).
- Test actual `verify` calls across process restarts, changed policies/datasets, corruption, different output paths, concurrent initialization (D01/D13).

## 3. Gate Contracts

### 3.1 Promotion Gate
- Requires `family_attempt_count` (not `family_search_count`) when selection correction active.
- `family_history_mandatory` gate enforced.
- Discovery attempts recorded before candidate evaluation.
- No gate relaxation permitted.
- Strategy remains `RESEARCH_ONLY` unless all gates pass explicitly.

### 3.2 Selection Correction
- Nested selection only (C03 fix: deprecated API removed, unsafe global-winner composition removed).
- Threshold from validation only, never test.

### 3.3 Robustness Battery
- All stresses must complete through shared replay engine.
- Nested results: full robustness battery with changing features, model types, holding periods (D05).
- Cost/slippage/delay stress reconciles per-fold and aggregate (D05).

## 4. File-Specific Guardrails

### 4.1 `src/quant_research/features/point_in_time.py`
- PIT exceptions must be boolean-typed (C10).
- Per-revision identity: same event, different revision → separate identity (C11).
- Null/missing revision → error (D10).
- Repeat validation: same event delivered twice → dedup, no inflation (D11).

### 4.2 `src/quant_research/features/information.py`
- Use `canon_av_int` (ns-precision) for eligibility comparison (C01).
- No `as_unit("us")` / `as_unit("ms")` on availability (D15).
- Never round unavailable event backward into eligibility (D15).
- Test boundary cases: just before, exactly at, just after bar (D15).

### 4.3 `src/quant_research/features/parkinson.py`
- Check `_synthetic_range` marker; reject if True (D09).
- Raise `DataValidationError` with "synthetic" in message (D09).

### 4.4 `src/quant_research/data/loaders.py`
- Preserve `_synthetic_range` marker through validation (C17).
- Session coverage check against exact requested set (D08).
- No undocumented one-session exception (D08).
- Reject `_synthetic_range` wide-CSV fabricated OHLC (C17).

### 4.5 `src/quant_research/data/snapshots.py`
- Immutable per-experiment manifest name: `{experiment_id}_manifest.json` (C15).
- Refuse overwrite of existing manifest (C15).
- NumPy version from `np.__version__` (C16).
- Manifest is audit summary, not full replay bundle (D14).

### 4.6 `src/quant_research/evaluation/walk_forward.py`
- `_load_lock` raises `LockedTestViolation` on dataset_id/config_fingerprint mismatch (D01).
- `_load_lock` raises `LockedTestViolation` on corrupt JSON (D01).
- Never silently clear `_frozen_hash` / `_frozen_spec` (D01).
- `turnover_full` for nested fold_restart replay (D05).
- Persistent lock + identity checks (C06).

### 4.7 `src/quant_research/evaluation/robustness.py`
- Parameter stress preserves explicit model fields (D06).
- Factor-1 stress: identical estimator, predictions, ledger (D06).
- Delay stress: include configured anchor + additional-delay (D07).
- Define absolute vs added latency for promotion (D07).

### 4.8 `src/quant_research/strategies/baseline.py`
- Only dataset-end NaN tolerated; interior NaN/inf → `DataValidationError` (D03).
- `turnover_full` for fold_restart (D05).
- Explicit model field preservation in parameter stress (D06).
- Finite-return validation before metrics (D03).

### 4.9 `src/quant_research/strategies/discovery.py`
- Clock on declared observations (`features.dropna(how="all")` only) before labels/outcomes (D04).
- `_reject_nonfinite_outcomes` guard on every fold slice (D04/D03).
- Ledger wiring: `record_start` before evaluation, `record_outcome` after (D02/C14).
- `attempt_id` links start to completion (C14).
- Null revision → error (D10).
- Dedup repeated events (D11).

### 4.10 `src/quant_research/experiments/registry.py`
- `family_attempt_count` counts each attempt once (C14).
- `record_start` issues unique `attempt_id` (C14).
- Immutable manifest names (C15).
- Registry record written before manifest (D14).

### 4.11 `src/quant_research/experiments/promotion.py`
- Use `family_attempt_count`, not `family_search_count` (D02).
- `family_history_mandatory` gate when selection correction active (D02).
- No gate relaxation (core invariant).

### 4.12 `src/quant_research/run.py`
- Injectable/configurable ledger path for test isolation (D12).
- Pre-existing state protection via hashes or write interception (D12).
- `family_attempt_count` at promotion (D02).
- Discovery start recorded before candidate evaluation (D02).

## 5. Verification & Promotion Checklist

Before committing any change that touches `src/quant_research/`, complete both the generic checks and the module-specific checks for the files you modified.

### 5.1 Generic (always run)

1. **Run full test suite**: `pytest`
2. **Run audit criteria tests**: `pytest tests/test_audit_criteria.py -v`
3. **Verify no gate was silently relaxed**
4. **Verify synthetic/offline labelling is preserved**
5. **Check trial accounting is intact** (high-water, family_attempt_count)
6. **Verify test isolation** (if run.py or shared state touched)

### 5.2 Module-specific (run the ones that apply)

| If you touched... | Also verify... |
|-------------------|----------------|
| Walk-forward / evaluation | Lock persistence works; identity checks intact (C06/D01) |
| Promotion / experiments | Family history gate enforces; family_attempt_count used (D02) |
| Robustness / parameter stress | Explicit model fields preserved at factor 1 (D06); anchor + additional-delay in delay grid (D07) |
| Features (Parkinson) | Parkinson rejects synthetic ranges; `_synthetic_range` propagation (D09/C17) |
| Features (information) | ns-precision availability comparison; no unit rounding backward (C01/D15) |
| Features (PIT) | Boolean exceptions; per-revision identity; null revision error; dedup (C10/C11/D10/D11) |
| Discovery / strategies | Clock on declared observations before labels; null revision error; dedup (D04/D10/D11) |
| Snapshots / manifests | Manifest immutability; `np.__version__` captured; summary-only (C15/C16/D14) |
| Data loaders | Session coverage vs exact requested set; `_synthetic_range` preserved (D08/C17) |

### 5.3 Final gate

- Strategy remains `RESEARCH_ONLY` unless **all** gates pass explicitly.
- No gate relaxation permitted.
- Every gate must pass **explicitly**.

## 6. Research Ethics Boundary
- Promotion defaults to **REJECTION**.
- Every gate must pass **explicitly**.
- Never "improve" a metric by:
  - Relaxing a gate
  - Re-cutting test windows
  - Reselecting on test
  - Presenting synthetic/offline output as market evidence
- Always label `SYNTHETIC_OFFLINE` for non-market results.
- Saved-market baseline: SPY/QQQ, 22 Jan 2018 – 27 Jan 2025, 1,764 OOS intervals. Net return -5.164%, CAGR -0.755%, Sharpe -0.0649. **Do not claim profitability.**

## 7. Common Pitfalls

| Pitfall | Correct Approach |
|---------|-----------------|
| "The test passed because `frozen is False`" | D01/D13: require `LockedTestViolation` raise; test actual rejection |
| "Parameter stress at factor 1 is a no-op" | D06: verify identical estimator/predictions/ledger; explicit fields must survive |
| "Delay stress covers all latencies" | D07: verify anchor + additional-delay in table; check outside-grid baseline |
| "One missing session is harmless" | D08: compare to exact requested set; any omission → error |
| "Synthetic range is just zero volatility" | D09: reject, don't compute; marker must propagate |
| "Nanosecond precision doesn't matter" | D15: submicrosecond events can round backward; test boundary cases |
| "Discovery can drop missing outcomes" | D04: clock first; missing outcomes never move folds |
| "Promotion can use completed-only counts" | D02: use `family_attempt_count`; abandoned starts count |
| "Test isolation is just a new path" | D12: protect pre-existing state; hash or intercept writes |
| "Manifest overwrite is fine" | C15: immutable per-experiment names; refuse overwrite |
| "Full replay is available" | D14: OUT_OF_SCOPE; do not claim complete reproducibility |

## 8. Failure Mode Index (quick reference)

| ID | Trigger | Correct behavior | Status |
|----|---------|------------------|--------|
| C01 | Mixed timestamp units in availability comparison | Use canon_av_int (ns-precision) | ✅ Fixed |
| C02 | Calendar tolerance rejecting complete data | Proper exchange-calendar coverage check | ✅ Fixed |
| C03 | Deprecated API returning contaminated OOS | Removed; validate-then-OOS-once | ✅ Fixed |
| C04 | Nonzero configured delay breaking reconciliation | Relative delay + anchor in grid | ✅ Fixed |
| C05 | Per-dir ledger + incomplete attempt accounting | Shared ledger path + family_attempt_count | ✅ Fixed |
| C06 | Lock not persisted + identity unchecked | Persisted lock + identity checks + load/save symmetry | ✅ Fixed |
| C07 | Nested fold turnover omitting boundary transitions | turnover_full resolves boundaries | ✅ Fixed |
| C08 | Config resolution issues | None-defaulted fields + proper resolution | ✅ Fixed |
| C09 | Parameter stress changing unused parameter | Explicit field preservation | ✅ Fixed |
| C10 | Non-boolean PIT exceptions | Typed boolean exception | ✅ Fixed |
| C11 | Revision/repeat crashes | Per-revision identity, no crash | ✅ Fixed |
| C12 | Placebo touching trial count / permuting NaN | Finite-only permutation, terminal NaN preserved, no trial touch | ✅ Fixed |
| C13 | High-water violation | High-water invariant enforced; recheck under lock | ✅ Fixed |
| C14 | Missing attempt IDs + counting | Attempt IDs + family_attempt_count | ✅ Fixed |
| C15 | Manifest overwritten | Immutable per-experiment manifest name; refuse overwrite | ✅ Fixed |
| C16 | Wrong numpy version in manifest | True numpy version captured (np.__version__) | ✅ Fixed |
| C17 | Wide-CSV fabricated OHLC passing validation | _synthetic_range preserved + rejected | ✅ Fixed |
| C18 | target_vol <= 0 accepted | Positive target_vol enforced | ✅ Fixed |
| D01 | Changed policy/dataset/corrupt lock/different output | LockedTestViolation, no silent unfreeze | ✅ Fixed |
| D02 | Interrupted attempt then passing / missing history | RESEARCH_ONLY, family_attempt_count, family_history_mandatory | ✅ Fixed |
| D03 | NaN/inf at interior fold end | Reject (only dataset-end terminal NaN ok) | ✅ Fixed |
| D04 | Missing labels/returns before fold cut | Clock first, no pre-fold drop | ✅ Fixed |
| D05 | Nested fold_restart replay | turnover_full resolves, no NameError | ✅ Fixed |
| D06 | Param stress factor 1 | Identical estimator/preds/ledger; explicit fields preserved | ✅ Fixed |
| D07 | Configured delay 0/1/beyond-grid | Anchor in grid + added-delay stress | ✅ Fixed |
| D08 | Missing leading/trailing boundary session | DataValidationError (no listing-date tolerance) | ✅ Fixed |
| D09 | Fabricated range reaches volatility | Reject or explicit unavailability policy | ✅ Fixed |
| D10 | Null revision/identity | Error, never wildcard pass | ✅ Fixed |
| D11 | Duplicate event delivery | Dedup, no evidence inflation | ✅ Fixed |
| D12 | Test writes real ledger | Tmp isolation; pre-existing-file guard fails loudly | ✅ Fixed |
| D13 | frozen is False / vacuous test | Require raise / real criterion | ✅ Fixed |
| D14 | "Replay from manifest" claim | Refuse claim — summary only; OUT_OF_SCOPE | ⚠️ Documented limitation |
| D15 | as_unit(us/ms) on availability / submicrosecond rounding | ns-precision compare only; never round backward | ✅ Fixed |

## 9. Out of Scope / Documented Limitations

- **D14**: Full executable replay bundle is not implemented. Manifest is an audit summary, not a reloadable replay package. Do not claim complete reproducibility.
- **Paper/live operational readiness**: Paper-order recorder and safeguards present, but no live broker adapter validated. No real-order, fill, latency, broker reconciliation, or deployment validation performed.
- **External dependency certification**: No vulnerability-database certification or provider-service availability check claimed.
