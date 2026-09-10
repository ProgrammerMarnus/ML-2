"""Strict walk-forward engine: TRAIN -> VALIDATION -> PURGE/EMBARGO -> TEST.

Rules enforced structurally:
- test is evaluation-only; thresholds/parameters are selected on validation
- preprocessing is fold-local (imputer/scaler fit on train only)
- purge removes train bars adjacent to validation; embargo separates
  validation from test
- rolling and expanding train windows supported
- LockedTestProtocol freezes the fold specification so a later run cannot
  silently retune on a different test layout
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from ..config import EvaluationConfig
from ..data.schemas import DataValidationError


class LockedTestViolation(RuntimeError):
    """Raised when a run would alter a frozen test specification."""


@dataclass(frozen=True)
class FoldSpec:
    fold_id: int
    train_idx: pd.DatetimeIndex
    val_idx: pd.DatetimeIndex
    test_idx: pd.DatetimeIndex
    purge_bars: int
    embargo_bars: int

    def summary(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "train_start": str(self.train_idx.min().date()),
            "train_end": str(self.train_idx.max().date()),
            "val_start": str(self.val_idx.min().date()),
            "val_end": str(self.val_idx.max().date()),
            "test_start": str(self.test_idx.min().date()),
            "test_end": str(self.test_idx.max().date()),
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
            "n_train": len(self.train_idx),
            "n_val": len(self.val_idx),
            "n_test": len(self.test_idx),
        }


def walk_forward_splits(
    index: pd.DatetimeIndex,
    cfg: EvaluationConfig,
) -> List[FoldSpec]:
    """Generate chronological folds.

    Layout per fold (bar counts): [train][purge][validation][embargo][test].
    Rolling mode keeps train_window fixed; expanding mode grows the train
    window from the start of the index.  Folds advance by step_bars.
    """
    if index.tz is None:
        raise DataValidationError("walk-forward index must be timezone-aware")
    if not index.is_monotonic_increasing:
        raise DataValidationError("walk-forward index must be sorted")
    n = len(index)
    required = cfg.train_window + cfg.purge_bars + cfg.validation_window + cfg.embargo_bars + cfg.test_window
    if n < required:
        raise DataValidationError(
            f"index too short for one fold: need {required} bars, have {n}"
        )

    folds: List[FoldSpec] = []
    test_start = cfg.train_window + cfg.purge_bars + cfg.validation_window + cfg.embargo_bars
    fold_id = 0
    while test_start + cfg.test_window <= n:
        if cfg.expanding:
            train_lo = 0
        else:
            train_lo = test_start - cfg.embargo_bars - cfg.validation_window - cfg.purge_bars - cfg.train_window
        train_hi = test_start - cfg.embargo_bars - cfg.validation_window - cfg.purge_bars
        val_lo = train_hi + cfg.purge_bars
        val_hi = val_lo + cfg.validation_window
        train_idx = index[train_lo:train_hi]
        val_idx = index[val_lo:val_hi]
        test_idx = index[test_start:test_start + cfg.test_window]
        fold_id += 1
        folds.append(
            FoldSpec(
                fold_id=fold_id,
                train_idx=train_idx,
                val_idx=val_idx,
                test_idx=test_idx,
                purge_bars=cfg.purge_bars,
                embargo_bars=cfg.embargo_bars,
            )
        )
        test_start += cfg.step_bars
    if not folds:  # pragma: no cover - guarded by required check above
        raise DataValidationError("no complete folds could be constructed")
    return folds


class LockedTestProtocol:
    """Freeze the fold specification once a research specification is locked.

    `freeze` records a hash of every fold's test window.  Any later call to
    `verify` with a different test layout raises LockedTestViolation, so test
    data cannot be re-cut to feed tuning.

    B12 FIX: Persist full test membership and survive process/run boundaries.
    The lock now:
    - Hashes complete test membership (all timestamps), not just endpoints
    - Can persist to/from a JSON file for cross-run verification
    - Includes dataset identity and configuration fingerprint
    """

    def __init__(self, lock_path: str | os.PathLike | None = None,
                 dataset_id: str | None = None,
                 config_fingerprint: str | None = None) -> None:
        self._frozen_hash: str | None = None
        self._lock_path = Path(lock_path) if lock_path else None
        self._frozen_spec: dict | None = None
        self._dataset_id = dataset_id
        self._config_fingerprint = config_fingerprint
        # Load existing lock if path provided
        if self._lock_path and self._lock_path.exists():
            self._load_lock()

    def _load_lock(self) -> None:
        """Load a previously persisted lock.

        C06: After loading, verify that the stored dataset_id and
        config_fingerprint are compatible with the constructor values.  A lock
        persisted under a different dataset or evaluation policy must not be
        silently reused.
        """
        try:
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("spec"), dict):
                # B12-era nested layout: {"hash":..., "spec": {...}}
                self._frozen_spec = data["spec"]
                self._frozen_hash = data.get("hash") or self._frozen_spec.get("hash")
            elif isinstance(data, dict) and "folds" in data and "hash" in data:
                # C06 layout: _save_lock writes the spec at the TOP LEVEL
                # (hash/n_folds/folds/dataset_id/config_fingerprint).
                self._frozen_spec = data
                self._frozen_hash = data.get("hash")
            else:
                self._frozen_spec = None
                self._frozen_hash = None
        except Exception:
            self._frozen_hash = None
            self._frozen_spec = None
            return
        if self._frozen_spec is None:
            return
        stored_did = self._frozen_spec.get("dataset_id")
        stored_cfp = self._frozen_spec.get("config_fingerprint")
        if self._dataset_id is not None and stored_did is not None \
                and stored_did != self._dataset_id:
            # Lock was persisted under a different dataset; reject it.
            self._frozen_hash = None
            self._frozen_spec = None
        if self._config_fingerprint is not None and stored_cfp is not None \
                and stored_cfp != self._config_fingerprint:
            # Lock was persisted under a different evaluation policy; reject it.
            self._frozen_hash = None
            self._frozen_spec = None

    def _save_lock(self) -> None:
        """Persist the current lock to disk."""
        if self._lock_path and self._frozen_spec:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_path.write_text(
                json.dumps(self._frozen_spec, indent=2, default=str),
                encoding="utf-8"
            )

    @staticmethod
    def _hash(folds: List[FoldSpec]) -> str:
        # B12: Hash complete test membership, not just endpoints
        payload = json.dumps(
            [
                {
                    "fold_id": f.fold_id,
                    "test_timestamps": [ts.isoformat() for ts in f.test_idx],
                    "n_test": len(f.test_idx),
                }
                for f in folds
            ],
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def freeze(
        self,
        folds: List[FoldSpec],
        dataset_id: str | None = None,
        config_fingerprint: str | None = None,
    ) -> str:
        # Use explicitly passed values, then stored constructor values, then None.
        did = dataset_id if dataset_id is not None else self._dataset_id
        cfp = config_fingerprint if config_fingerprint is not None else self._config_fingerprint
        h = self._hash(folds)
        if self._frozen_hash is not None and self._frozen_hash != h:
            raise LockedTestViolation(
                "test specification already frozen; refusing to re-cut test windows"
            )
        self._frozen_hash = h
        # B12/C06: Store complete specification for verification and persistence,
        # including dataset identity and config fingerprint so a lock can be
        # rejected when the dataset or evaluation policy changes across runs.
        self._frozen_spec = {
            "hash": h,
            "n_folds": len(folds),
            "folds": [
                {
                    "fold_id": f.fold_id,
                    "test_start": str(f.test_idx.min().date()),
                    "test_end": str(f.test_idx.max().date()),
                    "n_test": len(f.test_idx),
                    "test_timestamps": [str(ts.date()) for ts in f.test_idx],
                }
                for f in folds
            ],
            "dataset_id": did,
            "config_fingerprint": cfp,
        }
        self._save_lock()
        return h

    def verify(self, folds: List[FoldSpec]) -> None:
        if self._frozen_hash is None:
            self.freeze(folds)
            return
        if self._hash(folds) != self._frozen_hash:
            raise LockedTestViolation(
                "requested test windows differ from the frozen locked test; "
                "evaluation on a re-cut test set is forbidden"
            )

    @property
    def frozen(self) -> bool:
        return self._frozen_hash is not None
