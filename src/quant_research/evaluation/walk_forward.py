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
from dataclasses import dataclass
from typing import List

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
    """

    def __init__(self) -> None:
        self._frozen_hash: str | None = None

    @staticmethod
    def _hash(folds: List[FoldSpec]) -> str:
        payload = json.dumps(
            [f.test_idx.min().isoformat() + "|" + f.test_idx.max().isoformat() for f in folds]
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def freeze(self, folds: List[FoldSpec]) -> str:
        h = self._hash(folds)
        if self._frozen_hash is not None and self._frozen_hash != h:
            raise LockedTestViolation(
                "test specification already frozen; refusing to re-cut test windows"
            )
        self._frozen_hash = h
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
