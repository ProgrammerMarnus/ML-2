"""Immutable experiment registry (append-only JSONL) and trial accounting.

Rules
-----
- Experiment records are append-only; existing records are never modified or
  removed.  Duplicate experiment IDs are refused.
- The global trial counter is persistent and monotonic: it can only increase,
  and it refuses resets.  It lives in its own file protected from accidental
  overwrite (B04 transactional locking).
- The search ledger is durable and output-directory-independent: keyed by a
  stable research-family id so repeated research on the same OOS family is
  visible wherever it is evaluated (B11).
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

    @property
    def path_exists(self) -> bool:
        return self.path.exists()


class TrialCounter:
    """Persistent monotonic global trial counter (B04 transactional).

    B04: counter and high-water mark are cached at construction but reloaded
    under an exclusive file lock on every increment, so stale instances
    cannot roll back values.  Read/modify/write is serialized with fcntl;
    unique .tmp filenames prevent concurrent-write corruption.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.high_water_path = self.path.with_suffix(self.path.suffix + ".highwater")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock_fd: Optional[Any] = None
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
            raise DataValidationError(
                f"unreadable trial counter file {path}: {exc}"
            ) from exc

    def _acquire_lock(self) -> None:
        """Acquire an exclusive lock using a file-based mutex (B04)."""
        import fcntl

        self._lock_fd = open(self._lock_path, "w")
        fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX)

    def _release_lock(self) -> None:
        """Release the exclusive lock (B04)."""
        if self._lock_fd is None:
            return
        import fcntl

        fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
        self._lock_fd.close()
        self._lock_fd = None

    def _persist(self) -> None:
        """B04: Persist counter and high-water mark atomically within lock."""
        for pw, c in ((self.path, self._count),
                       (self.high_water_path, self._high)):
            tmp = pw.with_suffix(
                pw.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(4)}"
            )
            tmp.write_text(json.dumps({"count": c}), encoding="utf-8")
            os.replace(tmp, pw)

    @property
    def count(self) -> int:
        return self._count

    @property
    def high_water(self) -> int:
        return self._high

    def increment(self, n: int = 1) -> int:
        if n < 0:
            raise DataValidationError("trial counter can only increase")
        self._acquire_lock()
        try:
            current_count = self._load(self.path, default=0)
            current_high = self._load(self.high_water_path, default=current_count)
            # C13: enforce the high-water invariant even after a reload under
            # lock.  A count that has fallen below the high-water mark indicates
            # file corruption (e.g. manual reset of the count file while the
            # high-water file was preserved, or a stale-write rollback).  Reject
            # rather than silently accept a lowered count that an in-memory object
            # could feed into registry/promotion code.
            if current_count < current_high:
                raise DataValidationError(
                    f"trial counter count ({current_count}) is below the "
                    f"high-water mark ({current_high}); the counter file may be "
                    f"corrupt or have been manually reset — increment refused"
                )
            new_count = current_count + int(n)
            new_high = max(current_high, new_count)
            self._count = new_count
            self._high = new_high
            self._persist()
        finally:
            self._release_lock()
        return self._count


def family_id_for_search(dataset_hash: str, eval_fingerprint: str) -> str:
    """B11: stable research-family identifier (output-directory independent)."""
    raw = f"{dataset_hash}|{eval_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class SearchLedger:
    """Durable, output-directory-independent research-search audit trail (B11/C14).

    Keyed by the stable ``family_id``.  Every search attempt is recorded
    BEFORE evaluation (``record_start``) and completed AFTER
    (``record_outcome``), so interrupted or abandoned work stays visible.

    C14: each start record carries a unique ``attempt_id`` (UUID) that is
    referenced by the matching outcome record, so starts and completions can be
    paired even when multiple searches on the same family are interleaved.
    File locking (fcntl.flock) keeps concurrent writers consistent.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path  # lock the ledger file itself

    @staticmethod
    def family_id(dataset_hash: str, eval_fingerprint: str) -> str:
        return family_id_for_search(dataset_hash, eval_fingerprint)

    def _iter(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    def _append(self, entry: Dict[str, Any]) -> None:
        """Append one JSON-line entry under file lock (C14 process safety)."""
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def record_start(
        self,
        family_id: str,
        search_type: str,
        n_trials: int,
        dataset_hash: str = "",
        eval_fingerprint: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record the START of one search attempt (before evaluation).

        Returns the start entry including a unique ``attempt_id`` that must be
        passed to ``record_outcome`` to link start and completion (C14).
        """
        import uuid
        attempt_id = str(uuid.uuid4())
        entry = {
            "family_id": family_id,
            "search_type": search_type,
            "n_trials": int(n_trials),
            "stage": "started",
            "attempt_id": attempt_id,
            "dataset_hash": dataset_hash,
            "eval_fingerprint": eval_fingerprint,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "meta": meta or {},
        }
        self._append(entry)
        return entry

    def record_outcome(
        self,
        family_id: str,
        search_type: str,
        n_trials: int,
        outcome: str,
        summary: Optional[Dict[str, Any]] = None,
        aborted: bool = False,
        attempt_id: str = "",
    ) -> Dict[str, Any]:
        """Record the OUTCOME of one search attempt.

        ``attempt_id`` should match the one returned by ``record_start`` so the
        pair is linkable (C14).  When omitted the outcome is still recorded but
        not explicitly paired.
        """
        entry = {
            "family_id": family_id,
            "search_type": search_type,
            "n_trials": int(n_trials),
            "stage": "aborted" if aborted else "completed",
            "outcome": outcome,
            "attempt_id": attempt_id,
            "dataset_hash": "",
            "eval_fingerprint": "",
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "summary": summary or {},
        }
        self._append(entry)
        return entry

    def read_all(self) -> List[Dict[str, Any]]:
        return self._iter()

    def family_searches(self, family_id: str) -> List[Dict[str, Any]]:
        """Completed/aborted outcome entries for one family (each = one search)."""
        return [
            e
            for e in self.read_all()
            if e.get("family_id") == family_id
            and e.get("stage") in ("completed", "aborted")
        ]

    def family_started_attempts(self, family_id: str) -> List[Dict[str, Any]]:
        """All STARTED entries for one family, including unresolved ones (C14)."""
        return [
            e
            for e in self.read_all()
            if e.get("family_id") == family_id and e.get("stage") == "started"
        ]

    def family_search_count(self, family_id: str) -> int:
        """Number of completed/aborted searches on a family (legacy behavior)."""
        return len(self.family_searches(family_id))

    def family_attempt_count(self, family_id: str) -> int:
        """C14: total attempts on a family.

        An attempt is one START record, or (legacy) an OUTCOME record without a
        matching attempt_id.  A completed attempt therefore counts exactly ONCE:
        its start record provides the identity; the linked outcome is not a
        separate attempt.
        """
        entries = [e for e in self.read_all() if e.get("family_id") == family_id]
        ids_linked = {
            e.get("attempt_id")
            for e in entries
            if e.get("attempt_id") and e.get("stage") in ("started", "completed", "aborted")
        }
        ids_linked.discard(None)
        n_unlinked_outcomes = sum(
            1
            for e in entries
            if e.get("stage") in ("completed", "aborted") and not e.get("attempt_id")
        )
        return len(ids_linked) + n_unlinked_outcomes

    @property
    def path_exists(self) -> bool:
        return self.path.exists()
