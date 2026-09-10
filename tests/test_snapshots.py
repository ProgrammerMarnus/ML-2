"""Snapshot immutability and dataset hashing tests."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
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


# --- B16: full-precision hashing and reproducibility manifest -----------------


def test_dataset_hash_full_precision_detects_1e12_difference():
    """B16: the truncated 10-decimal hash could collide for close prices.
    The full-precision hash must distinguish a 1e-12 price difference that the
    truncated hash rounds away.  (The truncated hash MAY still collide - that
    is precisely the defect the full hash fixes.)"""
    a = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-04-01", seed=42)
    b = a.copy()
    # Perturb one close price by 1e-12 (below the 10-decimal rounding grid)
    b.loc[b.index[0], "close"] = a.loc[a.index[0], "close"] + 1e-12
    # Full-precision hashing MUST distinguish the distinct data
    assert dataset_hash(a, full=True) != dataset_hash(b, full=True)
    # Determinism: same input -> same full hash
    assert dataset_hash(a, full=True) == dataset_hash(a, full=True)


def test_create_run_manifest_captures_executable_spec():
    """B16: the manifest must capture configuration, inputs, fold membership,
    predictions, positions, returns, and model identity needed for replay."""
    from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
    from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
    from quant_research.data.snapshots import create_run_manifest, dataset_hash
    from quant_research.evaluation.walk_forward import LockedTestProtocol
    from quant_research.features.price_volume import build_price_volume_features
    from quant_research.strategies.baseline import run_walk_forward, summarize_experiment

    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2018-01-01"),
        evaluation=EvaluationConfig(train_window=120, validation_window=40,
                                    test_window=80, step_bars=80,
                                    purge_bars=2, embargo_bars=2, expanding=True),
        research=ResearchConfig(placebo_runs=1, bootstrap_samples=20),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    baseline = run_walk_forward(feats, y, fwd, cfg,
                                locked_test=LockedTestProtocol())
    summary = summarize_experiment(baseline)

    snapshot_meta = {
        "snapshot_id": "test_snapshot",
        "path": "/tmp/test.parquet",
        "dataset_hash": dataset_hash(ohlcv),
        "n_rows": len(ohlcv),
        "symbols": ["SPY"],
        "created_utc": "20260909T000000Z",
    }
    rec = {
        "experiment_id": "exp_1234",
        "code_version": "V2.1.3",
        "strategy": "walk_forward_baseline",
        "universe": ["SPY"],
        "target": "SPY",
        "seed": 42,
        "n_trials_global": 10,
        "trials_this_experiment": 10,
        "timestamp_utc": "20260909T000000Z",
        "promotion_state": "RESEARCH_ONLY",
        "failed_gates": ["cost_stress"],
        "config_fingerprint": "abc123",
    }
    m = create_run_manifest(
        cfg=cfg, ohlcv=ohlcv, snapshot_meta=snapshot_meta,
        features=feats, events=None, baseline=baseline,
        robustness={"cost_stress": []}, placebo={"percentile": 0.5},
        bootstrap={"interval": [0, 1]}, summary=summary,
        experiment_record=rec, git_revision="abc", git_dirty=False,
        environment={"pandas": "3.0.5"},
    )
    # Complete configuration (not just a fingerprint)
    assert "data" in m["configuration"] and "model" in m["configuration"]
    assert m["configuration"]["fingerprint"] == "abc123"
    # Market data identity with full precision hash
    assert m["inputs"]["market_data"]["dataset_hash_full"]
    assert m["inputs"]["market_data"]["dataset_hash_full"] != \
        m["inputs"]["market_data"]["dataset_hash_truncated"]
    # Full fold membership
    assert m["folds"]["n_folds"] == len(baseline.folds)
    assert len(m["folds"]["fold_specs"]) == len(baseline.folds)
    spec0 = m["folds"]["fold_specs"][0]
    for key in ("fold_id", "test_start", "test_end", "n_test", "threshold",
                "selected_features", "oos_sharpe"):
        assert key in spec0
    # Executable predictions/positions/returns
    assert len(m["predictions"]["index"]) == len(baseline.predictions)
    assert len(m["positions"]["index"]) == len(baseline.oos_positions)
    assert len(m["returns"]["net"]) == len(baseline.oos_returns)
    assert len(m["returns"]["gross"]) == len(baseline.oos_returns)
    # Code & environment identity
    assert m["code"]["git_revision"] == "abc"
    assert m["code"]["dependencies"]["pandas"] == "3.0.5"
    assert m["code"]["code_version"] == "V2.1.3"
    # Fitted model identity when models are retained
    assert "fitted_models" in m
    assert m["fitted_models"]
    for meta in m["fitted_models"].values():
        assert meta["model_type"] in {"LogisticRegression", "GradientBoostingClassifier"}
