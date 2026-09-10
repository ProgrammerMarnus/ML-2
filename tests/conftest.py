"""Shared fixtures: small deterministic panels and configs for fast tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig  # noqa: E402
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels  # noqa: E402


# B18: Track project data directories to verify they're not polluted by tests
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DATA_DIRS = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "data" / "raw_snapshots",
]


@pytest.fixture(scope="session")
def close_panel() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2020-01-01", "2021-12-31", freq="B").tz_localize("UTC")
    ret = rng.normal(0.0003, 0.011, len(idx))
    close = pd.DataFrame(
        {"SPY": 100 * np.exp(np.cumsum(ret)), "QQQ": 100 * np.exp(np.cumsum(ret * 0.9 + rng.normal(0, 0.002, len(idx))))},
        index=idx,
    )
    return close


@pytest.fixture(scope="session")
def volume_panel(close_panel) -> pd.DataFrame:
    rng = np.random.default_rng(12)
    return pd.DataFrame(
        rng.lognormal(13, 0.3, close_panel.shape), index=close_panel.index,
        columns=close_panel.columns,
    )


@pytest.fixture(scope="session")
def small_config(tmp_path_factory) -> AppConfig:
    # B18: Use temporary directory for snapshots to avoid polluting project data/
    snapshot_dir = tmp_path_factory.mktemp("raw_snapshots")
    return AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2020-01-01", end="2022-01-01",
                        raw_snapshot_dir=str(snapshot_dir)),
        evaluation=EvaluationConfig(train_window=120, validation_window=40,
                                    test_window=40, step_bars=40,
                                    purge_bars=2, embargo_bars=2, expanding=True),
        research=ResearchConfig(placebo_runs=3, bootstrap_samples=100),
    )


@pytest.fixture(scope="session")
def universe_small(small_config):
    """Feature panel/labels consistent with small_config's evaluation windows."""
    from quant_research.features.price_volume import build_price_volume_features

    ohlcv = generate_synthetic_ohlcv(
        ["SPY"], small_config.data.start, small_config.data.end, seed=42
    )
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype("float")
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return feats, y, fwd, small_config


@pytest.fixture()
def tmp_output(tmp_path):
    out = tmp_path / "artifacts"
    out.mkdir()
    return out


# B18: Verify no project data directories are polluted by tests
@pytest.fixture(autouse=True)
def _assert_no_project_data_pollution(request):
    """Assert that test runs don't write to the project's data directories.

    This catches test isolation issues where tests might write snapshots
    or other data files outside their temporary output fixtures.
    """
    # Skip this check for tests that explicitly need to test snapshot writing
    if getattr(request.node, "allow_data_dir_writes", False):
        yield
        return

    # Record state before test
    dirs_before = {}
    for d in PROJECT_DATA_DIRS:
        if d.exists():
            dirs_before[d] = set(d.rglob("*")) if d.is_dir() else set()

    yield

    # Check after test
    for d in PROJECT_DATA_DIRS:
        if not d.exists():
            continue
        files_after = set(d.rglob("*")) if d.is_dir() else set()
        files_before = dirs_before.get(d, set())
        new_files = files_after - files_before
        if new_files:
            # Allow temporary files that pytest creates
            temp_files = [f for f in new_files if ".pytest" in str(f) or ".tmp" in str(f)]
            if temp_files:
                continue
            pytest.fail(
                f"Test {request.node.name} wrote files to project data directory {d}:\n"
                + "\n".join(str(f) for f in sorted(new_files))
            )
