"""Walk-forward engine tests: separation, purge/embargo, locked test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import EvaluationConfig
from quant_research.data.schemas import DataValidationError
from quant_research.evaluation.walk_forward import (
    LockedTestProtocol,
    LockedTestViolation,
    walk_forward_splits,
)


@pytest.fixture()
def idx():
    return pd.bdate_range("2020-01-01", periods=500, freq="B").tz_localize("UTC")


def test_basic_fold_geometry(idx):
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=40,
                           step_bars=40, purge_bars=2, embargo_bars=2, expanding=False)
    folds = walk_forward_splits(idx, cfg)
    # first test window starts at train+purge+val+embargo bars; last ends at n
    first_test_start = 100 + 2 + 40 + 2
    expected = (500 - first_test_start - 40) // 40 + 1
    assert len(folds) == expected
    for f in folds:
        assert len(f.train_idx) == 100
        assert len(f.val_idx) == 40
        assert len(f.test_idx) == 40
        # purge: gap between train end and val start
        gap_tv = idx.get_loc(f.val_idx[0]) - idx.get_loc(f.train_idx[-1]) - 1
        assert gap_tv == cfg.purge_bars
        # embargo: gap between val end and test start
        gap_vt = idx.get_loc(f.test_idx[0]) - idx.get_loc(f.val_idx[-1]) - 1
        assert gap_vt == cfg.embargo_bars


def test_folds_do_not_overlap_and_are_chronological(idx):
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=40,
                           step_bars=40, purge_bars=2, embargo_bars=2, expanding=False)
    folds = walk_forward_splits(idx, cfg)
    for prev, cur in zip(folds, folds[1:]):
        assert cur.test_idx[0] > prev.test_idx[-1]
    for f in folds:
        assert f.train_idx[-1] < f.val_idx[0] < f.val_idx[-1] < f.test_idx[0]


def test_expanding_window_grows(idx):
    # Use step_bars == test_window to avoid gapped windows (B09)
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=100,
                           step_bars=100, purge_bars=0, embargo_bars=0, expanding=True)
    folds = walk_forward_splits(idx, cfg)
    sizes = [len(f.train_idx) for f in folds]
    assert len(folds) >= 2
    assert sizes[0] < sizes[1]


def test_insufficient_history_rejected(idx):
    # Use non-gapped configuration (step_bars <= test_window)
    cfg = EvaluationConfig(train_window=400, validation_window=100, test_window=100,
                           step_bars=100, purge_bars=0, embargo_bars=0)
    with pytest.raises(DataValidationError, match="too short"):
        walk_forward_splits(idx, cfg)


def test_naive_index_rejected(idx):
    # Use step_bars <= test_window to avoid gapped window rejection
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=100, step_bars=100)
    with pytest.raises(DataValidationError, match="timezone-aware"):
        walk_forward_splits(idx.tz_localize(None), cfg)


def test_locked_test_freezes_layout(idx):
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=40,
                           step_bars=40, purge_bars=2, embargo_bars=2)
    protocol = LockedTestProtocol()
    folds = walk_forward_splits(idx, cfg)
    protocol.freeze(folds)
    protocol.verify(walk_forward_splits(idx, cfg))  # same layout passes

    # Use different test_window with non-gapped step_bars
    tampered = EvaluationConfig(train_window=100, validation_window=40,
                                test_window=30, step_bars=30,
                                purge_bars=2, embargo_bars=2)
    with pytest.raises(LockedTestViolation):
        protocol.verify(walk_forward_splits(idx, tampered))


def test_locked_test_first_freeze_is_allowed(idx):
    # Use step_bars == test_window to avoid gapped window rejection
    cfg = EvaluationConfig(train_window=100, validation_window=40, test_window=100, step_bars=100)
    protocol = LockedTestProtocol()
    assert not protocol.frozen
    protocol.verify(walk_forward_splits(idx, cfg))  # lazily freezes
    assert protocol.frozen
