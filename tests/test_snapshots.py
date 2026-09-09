"""Snapshot immutability and dataset hashing tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

import quant_research.data.snapshots as snapshots
from quant_research.data.loaders import generate_synthetic_ohlcv
from quant_research.data.snapshots import dataset_hash, load_snapshot, save_snapshot
from quant_research.data.schemas import DataValidationError


def test_dataset_hash_deterministic_and_order_independent():
    a = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-04-01", seed=42)
    b = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-04-01", seed=42)
    assert dataset_hash(a) == dataset_hash(b)
    shuffled = a.sample(frac=1.0, random_state=1)
    assert dataset_hash(shuffled) == dataset_hash(a)


def test_dataset_hash_changes_with_data():
    a = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-04-01", seed=42)
    b = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-04-01", seed=43)
    assert dataset_hash(a) != dataset_hash(b)


def test_snapshot_immutable(tmp_path, monkeypatch):
    df = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-03-01", seed=42)
    # Freeze the clock: the snapshot stamp is second-granular wall time, so an
    # unlucky second boundary between the two calls would give the second
    # snapshot a different filename and silently skip the immutability check
    # (observed as a flake under full-suite load).
    frozen = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(snapshots, "datetime", _Frozen)
    meta = save_snapshot(df, tmp_path, name="m")
    assert meta["dataset_hash"] == dataset_hash(df)
    with pytest.raises(DataValidationError, match="never overwritten"):
        save_snapshot(df, tmp_path, name="m")


def test_snapshot_roundtrip(tmp_path):
    df = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-03-01", seed=42)
    meta = save_snapshot(df, tmp_path, name="m")
    loaded = load_snapshot(meta["path"])
    assert len(loaded) == len(df)
    assert dataset_hash(loaded) == meta["dataset_hash"]
