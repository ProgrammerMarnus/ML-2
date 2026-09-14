**Audit evidence — 10 September 2026**

> Historical evidence for the 2026-09-10 audited commit. These results are
> intentionally unchanged; current remediation status is in the repository-root
> `CURRENT_PROJECT_STATUS.md`.

The main report is [DEEP_AUDIT_2026-09-10.md](/home/marnus/VS-Code/ML-2/DEEP_AUDIT_2026-09-10.md). This directory contains fresh audit outputs, not engine changes or remediations.

| File | Purpose |
|---|---|
| `audit-metadata.json` | Audited Git commit, initially clean status, dependency/runtime versions and isolation information. |
| `preservation-before.json`, `preservation-check.json` | Hashes and final comparison protecting original code, tests, configs, notebook, data and historical artifacts. |
| `pytest.log`, `pytest-results.xml` | Full fresh-state suite: 280 passed, 1 teardown error, 1,918 warnings, exit 1. |
| `isolation-repeat.log`, `isolation-repeat-results.json` | Existing shared-ledger mutation escapes the guard; same test exits 0. |
| `audit_probes.py`, `probe-results.json`, `probes.log` | Fourteen independent probe groups. An expected product exception is recorded with its traceback, not called a passing regression. |
| `pipeline_checks.py`, `pipeline-check-results.json` | Four full synthetic runs: first, separate output with the same family, changed geometry in the same output, and configured delay 5. |
| `market-replay-results.json`, `market-executed-ledger.csv`, `market-replay.log` | Full saved-market pipeline and independent accounting, benchmark, cost, calibration and bootstrap readout. |
| `run-diff.json` | Comparison with prior audit folds. Fold metrics, memberships, thresholds and NaN patterns are unchanged. |
| `followup_probes.py`, `static-check-results.json`, `submicrosecond-results.json` | Source compilation, regression-test inspection, manifest inspection and nanosecond boundary probe. |
| `notebook_check.py`, `notebook-check-results.json`, `notebook-executed.ipynb` | Fresh source-cell execution after a local-socket restriction prevented Jupyter kernel startup. Saved outputs were cleared before source execution. |
| `notebook-run-accounting.json` | Fresh notebook result and duplicate-stage trial accounting. |
| `pytest-shared-ledger.jsonl`, `integration-shared-ledger.jsonl` | Copies of histories created in isolated trees, including attempts from these audit runs. |
| `findings-index.json` | D01–D15 priorities, OPEN status, evidence locations and acceptance criteria. |
| `report-validation.json` | Report links, source locations, count and preservation checks. |
| `audit-operations.log` | Audit-harness setup/serialization issues and their resolutions, distinguished from product findings. |

The suite used `/tmp/ml2-deep-audit-20260910`, a byte-identical copy of `src/quant_research`, `tests`, `configs` and project metadata. It intentionally began without historical research data so that tests could not consume or alter the real research ledger. Integration/notebook runs used a separate byte-identical package copy at `/tmp/ml2-deep-audit-integration-20260910`. The original repository was initially clean and all protected file hashes were checked afterward. These `/tmp` copies are execution workspaces and may be ephemeral; this directory preserves the result evidence and harnesses.

The full-suite command, from the isolated suite tree, was:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m pytest --junitxml=/home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pytest-results.xml
```

For probe/integration runs the relevant isolated `src` directory was explicitly selected through `PYTHONPATH`, with the same single-thread BLAS settings. The commands executed were:

```bash
python3 /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/audit_probes.py
python3 /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pipeline_checks.py synthetic
python3 /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/pipeline_checks.py market
python3 /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/followup_probes.py
python3 /home/marnus/VS-Code/ML-2/audit_artifacts/2026-09-10/notebook_check.py
```

These commands write evidence files and research artifacts. To repeat them, use fresh isolated copies and a separate evidence directory; do not point them at the production source tree's shared ledger. The notebook harness currently names its isolated working directory explicitly. Exact first/second-family counts require fresh history. New experiment IDs, snapshot timestamps and absolute artifact locations will differ between executions.

The market harness verifies and reuses `data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_b0e94186f465bc47.parquet`. It replaces only `load_yfinance_ohlcv` with that normalized frame; `load_market_data` and its normal period/universe checks execute. It captures the baseline return object without changing its calculations. Snapshot exports are directed into this audit directory. The market Git manifest can report no Git repository in the isolated execution tree; audited source identity is instead preserved in this audit's metadata and hash manifest. No external provider download or original snapshot/ledger write occurs.

The Jupyter kernel restriction was environmental, not a notebook failure and not an automatic-approval rejection. Its unchanged Python source cells completed sequentially in a fresh process. Kernel message transport, widgets, and interactive frontend behavior were not validated. Reports explicitly distinguish this from kernel-backed notebook execution.

Diagnostic JSON follows the engine's convention of emitting NaN for undefined statistics. This is not strict RFC JSON. Flat/zero-trading Sharpe and one-sample variance values were classified as undefined diagnostics; all saved-market executable return/position/turnover values were checked finite. D03 separately records the unsupported non-finite executable-ledger case found by a deliberate input probe.
