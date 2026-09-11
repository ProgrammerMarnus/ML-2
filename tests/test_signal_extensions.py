"""Signal-extension features (pv-2.2.0): causal, registry-covered, leak-free."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_research.data.loaders import generate_synthetic_ohlcv, to_price_panels
from quant_research.data.schemas import DataValidationError
from quant_research.features.leakage import feature_leakage_report
from quant_research.features.price_volume import (
    SIGNAL_EXTENSION_COLUMNS,
    build_price_volume_features,
    build_signal_extensions,
)
from quant_research.features.registry import registry_hash


def _universe():
    ohlcv = generate_synthetic_ohlcv(["SPY", "QQQ"], "2015-01-01", "2018-01-01", seed=42)
    open_, high, low, close, volume = to_price_panels(ohlcv)
    return open_, high, low, close, volume


def test_signal_extension_column_universe():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    assert list(ext.columns) == SIGNAL_EXTENSION_COLUMNS
    assert len(ext) == len(close)


def test_signal_extensions_are_causal_no_lookahead():
    open_, high, low, close, volume = _universe()
    ext_full = build_signal_extensions(open_, high, low, close, volume, "SPY")
    # Corrupt the LAST bar; early-history features must not change.
    close2 = close.copy()
    close2.iloc[-1] *= 1.5
    volume2 = volume.copy()
    volume2.iloc[-1] *= 3.0
    hi2 = high.copy()
    hi2.iloc[-1] *= 1.2
    ext2 = build_signal_extensions(open_, hi2, low, close2, volume2, "SPY")
    hist = ext_full.index[:-21]
    delta = (ext_full.loc[hist] - ext2.loc[hist]).abs()
    assert float(np.nanmax(delta.to_numpy())) < 1e-12


def test_overnight_and_intraday_decompose_daily_return():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    gap = ext["overnight_gap"].dropna().iloc[1:]
    intra = ext["intraday_return"].dropna().iloc[1:]
    # (1+gap)*(1+intra) - 1 == close[t]/close[t-1] - 1
    both = pd.concat([gap, intra], axis=1, join="inner")
    c = close["SPY"]
    daily = c / c.shift(1) - 1.0
    recombined = (1.0 + both.iloc[:, 0]) * (1.0 + both.iloc[:, 1]) - 1.0
    idx = recombined.index.intersection(daily.index)
    np.testing.assert_allclose(recombined.loc[idx].to_numpy(),
                               daily.loc[idx].to_numpy(), rtol=1e-9)


def test_range_position_bounded():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    rp = ext["day_range_position"].dropna()
    assert bool(((rp >= 0.0) & (rp <= 1.0)).all())


def test_rsi_bounded():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    rsi = ext["rsi_14"].dropna()
    assert bool(((rsi >= 0.0) & (rsi <= 100.0)).all())


def test_fifty_two_week_position_bounded():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    p = ext["fifty_two_week_position"].dropna()
    assert bool(((p >= 0.0) & (p <= 1.0)).all())


def test_extension_registry_hashes_stable():
    for name in SIGNAL_EXTENSION_COLUMNS:
        h1 = registry_hash([name])
        assert h1 == registry_hash([name])
        assert len(h1) == 16


def test_extension_features_in_registry():
    h = registry_hash(SIGNAL_EXTENSION_COLUMNS)
    assert isinstance(h, str) and len(h) == 16


def test_extension_leakage_covered_by_gate():
    open_, high, low, close, volume = _universe()
    report = feature_leakage_report(close, volume, "SPY",
                                    open_=open_, high=high, low=low)
    assert report["passed"]
    assert "future_ohlc_extensions" in report["dimensions"]


def test_extension_warmup_not_future_filled():
    open_, high, low, close, volume = _universe()
    ext = build_signal_extensions(open_, high, low, close, volume, "SPY")
    # Long-warmup features must be NaN early, not zero-filled.
    assert int(ext["fifty_two_week_position"].iloc[:251].isna().sum()) == 251
    assert not bool((ext["fifty_two_week_position"].iloc[:251] == 0.0).any())
    # Overnight gap needs only one prior close: first bar NaN, second finite.
    assert bool(np.isnan(ext["overnight_gap"].iloc[0]))
    assert bool(np.isfinite(ext["overnight_gap"].iloc[1]))


def test_extension_requires_target_member():
    open_, high, low, close, volume = _universe()
    try:
        build_signal_extensions(open_, high, low, close, volume, "NOPE")
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing target")


def test_extension_rejects_nan_timestamps():
    open_, high, low, close, volume = _universe()
    bad = close.copy()
    bad.index = pd.RangeIndex(len(bad))
    try:
        build_signal_extensions(open_, high, low, bad, volume, "SPY")
    except DataValidationError:
        return
    raise AssertionError("expected DataValidationError for non-DatetimeIndex")
