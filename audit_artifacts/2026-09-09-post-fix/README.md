# Current-tree audit evidence — 9 September 2026

> Historical evidence for the 2026-09-09 audited tree. These results are
> intentionally unchanged; current remediation status is in the repository-root
> `CURRENT_PROJECT_STATUS.md`.

The report is [DEEP_AUDIT_2026-09-09_POST_FIX.md](/home/marnus/VS-Code/ML-2/DEEP_AUDIT_2026-09-09_POST_FIX.md).

These are audit artifacts, not product fixes. Existing source/test/configuration/notebook/data files were preserved. Synthetic examples and market replay results are kept distinct. No provider download or order submission was performed.

| Artifact | Purpose |
|---|---|
| `audit_probes.py`, `probe-results.json`, `probes.log` | 22 intended-contract checks: 16 FAIL, 6 PASS, zero ERROR on audited source. A FAIL is a reproduced contract defect; these are deliberately outside the ordinary test suite. |
| `pipeline_probes.py`, `pipeline-probe-results.json`, `pipeline-probes.log` | Three completed synthetic pipeline runs; changed output location and test geometry; manifest contents; real loader with only its download stubbed; one failed nonzero-delay full pipeline. |
| `followup_probes.py`, `followup-results.json`, `followup-probes.log` | Legacy contamination/accounting, all 16 timestamp-unit combinations, invalid-return and negative-sizing cases, and positive statistical/replay controls. |
| `market_evidence.py`, `market-replay-analysis.json`, `market-replay.log` | Previous audit's market harness, reused against current source and isolated new output. Full pipeline over saved verified SPY/QQQ snapshot, replacing only loader/snapshot-write I/O. |
| `market-executed-ledger.csv` | Current market replay's indexed net/gross returns, positions, and turnover. |
| `market_snapshot_run/` | Full fresh market pipeline outputs and manifest, including stress and null tables. |
| `run-diff.json` | Comparison against `2026-09-09-rerun`: same 1,764 timestamps, maximum absolute ledger delta 0.0. |
| `supplemental_readout.py`, `supplemental-readout.json` | Additional 2,000-resample block bootstrap, raw calibration, and per-fold benchmark readout. Does not change recorded experiment settings. |
| `pytest-summary.txt` | Completed existing suite: 242 pass, 1,907 warnings, 401.01 seconds. Summary transcribed from the actual tool result; no JUnit export was requested. |
| `static-validation.json` | Source AST parsing, notebook schema validation and compilation of all eight code cells. Notebook not executed separately. |
| `audit-metadata.json` | Initial Git state, runtime, source/data inventory counts. |
| `source-manifest-before.json`, `source-manifest-after.json` | SHA-256 of active source/tests/configuration/README/notebook. |
| `data-manifest-before.json`, `preservation-check.json` | Existing data contents and before/after preservation evidence. |
| `pipeline_runs/`, `synthetic_snapshots/` | Isolated generated synthetic test outputs. Not market evidence. |

Run from `/home/marnus/VS-Code/ML-2`:

```bash
python -m pytest
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/audit_probes.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/pipeline_probes.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/followup_probes.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/market_evidence.py real
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/supplemental_readout.py
```

The scripts write beside themselves. To preserve this evidence and start fresh counter/ledger state, first copy the Python scripts into a new sibling directory beneath `audit_artifacts/` and use that directory in the commands. The market script requires the existing saved snapshot and prior artifacts referenced in its source. The follow-up script deliberately reuses selected fixtures from `audit_artifacts/2026-09-09/audit_probes.py`; it redirects their writes here.

Primary probe status is saved to JSON rather than reflected in the process exit code: FAIL is an audit result. An ERROR requires investigation, not automatic classification as either a fixed defect or an open finding. The follow-up script explicitly reproduces some defects and asserts some known working controls; interpret its named output fields accordingly.
