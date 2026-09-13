"""Deterministic dataset hashing and immutable raw snapshots.

Raw downloaded data is preserved before any transformation.  Snapshots are
append-only: an existing snapshot file is never overwritten or deleted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .schemas import DataValidationError


def dataset_hash(ohlcv: pd.DataFrame, full: bool = False) -> str:
    """Deterministic sha256 over canonicalized market data.

    Canonical form: values sorted by (timestamp, symbol), floats formatted to
    10 decimals (or full precision if full=True), UTF-8 encoded CSV bytes.
    Independent of row order and dtypes.

    B16 FIX: When full=True, use full float precision instead of 10 decimals
    to avoid hash collisions from tiny price differences (e.g., 1e-12).
    """
    canon = ohlcv.sort_values(["timestamp", "symbol"]).copy()
    if full:
        for col in ("open", "high", "low", "close", "volume"):
            canon[col] = canon[col].astype("float64").map(lambda v: repr(float(v)))
    else:
        for col in ("open", "high", "low", "close", "volume"):
            canon[col] = canon[col].astype("float64").map(lambda v: f"{v:.10f}")
    canon["timestamp"] = pd.to_datetime(canon["timestamp"], utc=True).map(
        lambda t: t.isoformat()
    )
    canon["symbol"] = canon["symbol"].astype("string")
    blob = canon.to_csv(index=False).encode("utf-8")
    full_hash = hashlib.sha256(blob).hexdigest()
    return full_hash if full else full_hash[:16]
    canon = ohlcv.sort_values(["timestamp", "symbol"]).copy()
    for col in ("open", "high", "low", "close", "volume"):
        canon[col] = canon[col].astype("float64").map(lambda v: f"{v:.10f}")
    canon["timestamp"] = pd.to_datetime(canon["timestamp"], utc=True).map(
        lambda t: t.isoformat()
    )
    canon["symbol"] = canon["symbol"].astype("string")
    blob = canon.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def save_snapshot(ohlcv: pd.DataFrame, snapshot_dir: str | Path, name: str = "market") -> Dict[str, Any]:
    """Persist an immutable raw snapshot (parquet if available, else csv).

    Returns snapshot metadata including the dataset hash.  Refuses to
    overwrite an existing snapshot file.
    """
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    ds_hash = dataset_hash(ohlcv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{name}_{ds_hash}"
    pq_path = snapshot_dir / f"{base}.parquet"
    csv_path = snapshot_dir / f"{base}.csv.gz"
    if pq_path.exists() or csv_path.exists():
        raise DataValidationError(
            f"snapshot {base} already exists; snapshots are immutable and never overwritten"
        )
    try:
        ohlcv.to_parquet(pq_path, index=False)
        path = pq_path
    except (ImportError, OSError):
        # The snapshot hash canonicalizes numeric values to ten decimal places.
        # Persist CSV snapshots at that same precision so a CSV round-trip has
        # the identical identity rather than changing a last binary digit during
        # text parsing and crossing a decimal rounding boundary.
        ohlcv.to_csv(csv_path, index=False, compression="gzip", float_format="%.10f")
        path = csv_path
    meta = {
        "snapshot_id": base,
        "path": str(path),
        "dataset_hash": ds_hash,
        "n_rows": int(len(ohlcv)),
        "symbols": sorted(str(s) for s in ohlcv["symbol"].unique()),
        "created_utc": stamp,
    }
    meta_path = snapshot_dir / f"{base}.meta.json"
    if meta_path.exists():
        raise DataValidationError(f"snapshot metadata {meta_path} already exists")
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return meta


def load_snapshot(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".gz":
        return pd.read_csv(path, compression="gzip", float_precision="round_trip")
    return pd.read_csv(path, float_precision="round_trip")


def create_run_manifest(
    cfg: Any,
    ohlcv: pd.DataFrame,
    snapshot_meta: Dict[str, Any],
    features: pd.DataFrame,
    events: pd.DataFrame | None,
    baseline: Any,
    robustness: Dict[str, Any],
    placebo: Dict[str, Any],
    bootstrap: Dict[str, Any],
    summary: Dict[str, Any],
    experiment_record: Dict[str, Any],
    git_revision: str | None = None,
    git_dirty: bool = False,
    environment: Dict[str, str] | None = None,
    output_dir: Path | None = None,
) -> Dict[str, Any]:
    """B16: Create a complete content-addressed manifest for reproducible replay.

    Captures all inputs, code state, configuration, and outputs needed to
    reproduce an experiment result independently of the original runtime.
    """
    import sys
    from dataclasses import asdict
    from quant_research import __version__ as pkg_version

    def _cfg_block(subcfg) -> dict:
        # Dataclass configs serialize losslessly via asdict (JSON-compatible).
        try:
            return asdict(subcfg)
        except TypeError:  # pragma: no cover - configs are dataclasses
            return {"repr": str(subcfg)}

    manifest = {
        "code": {
            "package_version": pkg_version,
            "code_version": experiment_record.get("code_version", "unknown"),
            "git_revision": git_revision,
            "git_dirty": git_dirty,
            "python_version": sys.version,
            "dependencies": environment or {},
        },
        "configuration": {
            "data": _cfg_block(cfg.data),
            "evaluation": _cfg_block(cfg.evaluation),
            "execution": _cfg_block(cfg.execution),
            "model": _cfg_block(cfg.model),
            "research": _cfg_block(cfg.research),
            "promotion": _cfg_block(cfg.promotion),
            "fingerprint": experiment_record.get("config_fingerprint"),
        },
        "inputs": {
            "market_data": {
                "snapshot_id": snapshot_meta.get("snapshot_id"),
                "path": snapshot_meta.get("path"),
                "dataset_hash_truncated": snapshot_meta.get("dataset_hash"),
                "dataset_hash_full": dataset_hash(ohlcv, full=True),
                "n_rows": snapshot_meta.get("n_rows"),
                "symbols": snapshot_meta.get("symbols"),
                "created_utc": snapshot_meta.get("created_utc"),
            },
            "features": {
                "columns": sorted(features.columns),
                "index_start": str(features.index.min()),
                "index_end": str(features.index.max()),
                "n_rows": len(features),
            },
            "events": {
                "present": events is not None and len(events) > 0,
                "n_events": len(events) if events is not None else 0,
            } if events is not None else {"present": False},
        },
        "experiment": {
            "experiment_id": experiment_record.get("experiment_id"),
            "strategy": experiment_record.get("strategy"),
            "universe": experiment_record.get("universe"),
            "target": experiment_record.get("target"),
            "seed": experiment_record.get("seed"),
            "trials_global": experiment_record.get("n_trials_global"),
            "trials_this_experiment": experiment_record.get("trials_this_experiment"),
            "timestamp_utc": experiment_record.get("timestamp_utc"),
        },
        "results": {
            "promotion_state": experiment_record.get("promotion_state"),
            "failed_gates": experiment_record.get("failed_gates", []),
            "summary": summary,
            "bootstrap": bootstrap,
            "placebo": placebo,
            "robustness": robustness,
        },
        "folds": {
            "n_folds": int(len(baseline.folds)),
            "fold_specs": [
                {
                    "fold_id": int(row["fold_id"]),
                    "train_start": str(row["train_start"]),
                    "train_end": str(row["train_end"]),
                    "val_start": str(row["val_start"]),
                    "val_end": str(row["val_end"]),
                    "test_start": str(row["test_start"]),
                    "test_end": str(row["test_end"]),
                    "purge_bars": int(row["purge_bars"]),
                    "embargo_bars": int(row["embargo_bars"]),
                    "n_train": int(row["n_train"]),
                    "n_val": int(row["n_val"]),
                    "n_test": int(row["n_test"]),
                    "threshold": float(row["threshold"]),
                    "selected_features": str(row["selected_features"]),
                    "oos_sharpe": float(row["oos_sharpe"]) if pd.notna(row.get("oos_sharpe")) else None,
                    "oos_auc": float(row["oos_auc"]) if pd.notna(row.get("oos_auc")) else None,
                    "oos_brier": float(row["oos_brier"]) if pd.notna(row.get("oos_brier")) else None,
                }
                for _, row in baseline.folds.iterrows()
            ],
        },
        "predictions": {
            "index": [str(ts) for ts in baseline.predictions.index],
            "prob": [float(v) if pd.notna(v) else None for v in baseline.predictions["prob"]],
            "y": [int(v) if pd.notna(v) else None for v in baseline.predictions["y"]],
            "fwd": [float(v) if pd.notna(v) else None for v in baseline.predictions["fwd"]],
            "fold": [str(v) for v in baseline.predictions["fold"]],
        },
        "positions": {
            "index": [str(ts) for ts in baseline.oos_positions.index],
            "position": [float(v) if pd.notna(v) else 0.0 for v in baseline.oos_positions],
        },
        "returns": {
            "index": [str(ts) for ts in baseline.oos_returns.index],
            "net": [float(v) if pd.notna(v) else 0.0 for v in baseline.oos_returns],
            "gross": [float(v) if pd.notna(v) else 0.0
                      for v in (baseline.oos_gross_returns
                                if baseline.oos_gross_returns is not None
                                else baseline.oos_returns)],
        },
    }

    if hasattr(baseline, "fitted_models") and baseline.fitted_models:
        manifest["fitted_models"] = {
            str(fold_id): {
                "model_type": str(model.named_steps["model"].__class__.__name__),
            }
            for fold_id, model in baseline.fitted_models.items()
        }

    return manifest


def save_manifest(manifest: Dict[str, Any], output_dir: Path,
                  experiment_id: str | None = None) -> Path:
    """B16/C15: Save the run manifest under an experiment-specific immutable name.

    The manifest is written to ``{experiment_id}_manifest.json`` (falling back
    to ``run_manifest.json`` when no experiment id is available) so that
    multiple runs in the same output directory never overwrite each other's
    provenance (C15).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"{experiment_id}_manifest.json" if experiment_id else "run_manifest.json"
    manifest_path = output_dir / name
    if manifest_path.exists():
        raise DataValidationError(
            f"manifest {manifest_path.name} already exists; experiment manifests "
            f"are immutable and must not be overwritten (C15 evidence loss guard)"
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest_path


def get_git_info() -> tuple[str | None, bool]:
    """Get git revision and dirty status if available."""
    import subprocess
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            stderr=subprocess.DEVNULL
        ).returncode != 0
        return revision, dirty
    except (subprocess.SubprocessError, FileNotFoundError):
        return None, False
