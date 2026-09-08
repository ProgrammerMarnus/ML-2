"""Immutable experiment registry (append-only JSONL) and trial accounting.

Rules
-----
- Experiment records are append-only; existing records are never modified or
  removed.  Duplicate experiment IDs are refused.
- The global trial counter is persistent and monotonic: it can only increase,
  and it refuses resets.  It lives in its own file protected from accidental
  overwrite.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..data.schemas import DataValidationError

REQUIRED_RECORD_FIELDS = [
    "strategy",
    "features",
    "universe",
    "target",
    "timeframe",
    "train_period",
    "validation_period",
    "test_period",
    "trials",
    "dataset_version",
    "feature_version",
    "strategy_version",
    "code_version",
    "seed",
    "gross_metrics",
    "net_metrics",
    "costs",
    "slippage",
    "oos_metrics",
    "bootstrap_interval",
    "robustness",
    "placebo_statistics",
    "information_sources",
    "promotion_state",
]


def _experiment_id(timestamp_utc: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{timestamp_utc}_{digest}"


class ExperimentRegistry:
    """Append-only JSONL registry."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _existing_ids(self) -> set:
        if not self.path.exists():
            return set()
        ids = set()
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                ids.add(json.loads(line)["experiment_id"])
        return ids

    def record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Append one immutable experiment record; returns the stored record."""
        missing = [f for f in REQUIRED_RECORD_FIELDS if f not in payload]
        if missing:
            raise DataValidationError(f"experiment record missing fields: {missing}")
        if "features" not in payload:
            raise DataValidationError("experiment record missing 'features'")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        record = dict(payload)
        record["timestamp_utc"] = ts
        # id uniqueness never depends on wall-clock resolution: a random nonce
        # is mixed into the payload digest
        record["experiment_id"] = _experiment_id(
            ts, {**payload, "_nonce": secrets.token_hex(8)}
        )
        existing = self._existing_ids()
        if record["experiment_id"] in existing:
            raise DataValidationError(
                f"experiment_id {record['experiment_id']} already registered; "
                "records are immutable and never overwritten"
            )
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record

    def read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


class TrialCounter:
    """Persistent, monotonic global research-trial counter.

    Stored in its own JSON file.  `increment` only ever adds; `set` is not
    exposed.  A manual edit that lowers the stored value is detected against
    the high-water mark file and rejected.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.high_water_path = self.path.with_suffix(self.path.suffix + ".highwater")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._count = self._load(self.path, default=0)
        self._high = self._load(self.high_water_path, default=self._count)
        if self._count < self._high:
            raise DataValidationError(
                f"trial counter ({self._count}) is below its high-water mark "
                f"({self._high}); the global trial counter must never be reset"
            )

    @staticmethod
    def _load(path: Path, default: int) -> int:
        if not path.exists():
            return default
        try:
            return int(json.loads(path.read_text(encoding="utf-8"))["count"])
        except Exception as exc:  # noqa: BLE001
            raise DataValidationError(f"unreadable trial counter file {path}: {exc}") from exc

    def _persist(self) -> None:
        for pw, c in ((self.path, self._count), (self.high_water_path, self._high)):
            tmp = pw.with_suffix(pw.suffix + ".tmp")
            tmp.write_text(json.dumps({"count": c}), encoding="utf-8")
            os.replace(tmp, pw)  # atomic rename

    @property
    def count(self) -> int:
        return self._count

    def increment(self, n: int = 1) -> int:
        if n < 0:
            raise DataValidationError("trial counter can only increase")
        self._count += int(n)
        self._high = max(self._high, self._count)
        self._persist()
        return self._count
