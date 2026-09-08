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


def dataset_hash(ohlcv: pd.DataFrame) -> str:
    """Deterministic sha256 over canonicalized market data (first 16 hex chars).

    Canonical form: values sorted by (timestamp, symbol), floats formatted to
    10 decimals, UTF-8 encoded CSV bytes.  Independent of row order and dtypes.
    """
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
        ohlcv.to_csv(csv_path, index=False, compression="gzip")
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
        return pd.read_csv(path, compression="gzip")
    return pd.read_csv(path)
