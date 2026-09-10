"""Data validation tests: schema, duplicates, ordering, timezone, missing data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.data.schemas import DataValidationError
from quant_research.data.validation import (
    missing_data_report,
    validate_ohlcv,
    validate_wide_panel,
)


def make_long(idx, symbol="SPY", **overrides):
    n = len(idx)
    base = dict(
        timestamp=idx,
        symbol=symbol,
        open=np.full(n, 100.0),
        high=np.full(n, 101.0),
        low=np.full(n, 99.0),
        close=np.full(n, 100.0),
        volume=np.full(n, 1000.0),
    )
    base.update(overrides)
    return pd.DataFrame(base)


@pytest.fixture()
def idx():
    return pd.bdate_range("2020-01-01", periods=10, freq="B").tz_localize("UTC")


def test_valid_schema_passes(idx):
    out = validate_ohlcv(make_long(idx))
    assert len(out) == 10
    assert list(out.columns[:2]) == ["timestamp", "symbol"]


def test_missing_column_rejected(idx):
    df = make_long(idx).drop(columns=["volume"])
    with pytest.raises(DataValidationError, match="missing required columns"):
        validate_ohlcv(df)


def test_duplicate_timestamp_symbol_rejected(idx):
    df = pd.concat([make_long(idx), make_long(idx[:1])], ignore_index=True)
    with pytest.raises(DataValidationError, match="duplicate"):
        validate_ohlcv(df)


def test_unsorted_timestamps_rejected(idx):
    df = make_long(idx).iloc[::-1].reset_index(drop=True)
    with pytest.raises(DataValidationError, match="not sorted"):
        validate_ohlcv(df)


def test_naive_timestamps_rejected():
    idx = pd.bdate_range("2020-01-01", periods=5, freq="B")  # tz-naive
    with pytest.raises(DataValidationError, match="timezone-naive"):
        validate_ohlcv(make_long(idx))


def test_high_low_violation_rejected(idx):
    df = make_long(idx)
    df.loc[df.index[3], "high"] = 90.0
    # Note: with B13, OHLC containment is checked before high>=low.
    # This test creates open=100, high=90, low=99, close=100 which fails
    # the "open outside [low, high]" check first.
    with pytest.raises(DataValidationError, match="open price outside"):
        validate_ohlcv(df)


def test_non_positive_price_rejected(idx):
    df = make_long(idx)
    df.loc[df.index[2], "close"] = 0.0
    # Note: with B13, OHLC containment is checked before non-positive.
    # close=0 with high=101, low=99 fails "close outside [low, high]" first.
    with pytest.raises(DataValidationError, match="close price outside"):
        validate_ohlcv(df)


def test_missing_price_not_silently_filled(idx):
    df = make_long(idx)
    df.loc[df.index[5], "open"] = np.nan
    with pytest.raises(DataValidationError, match="no silent fill"):
        validate_ohlcv(df)


def test_missing_data_report_counts(idx):
    df = make_long(idx)
    df = df.drop(index=[df.index[3], df.index[7]])
    rep = missing_data_report(df)
    # two genuine missing sessions (2020-01-02 is a holiday, so only the two
    # dropped mid-week bar dates count as missing)
    assert rep.loc[0, "n_missing_sessions"] == 2
    # timestamps stay timezone-aware
    assert rep.loc[0, "first"].tz is not None
    assert rep.loc[0, "last"].tz is not None
    # observed bars on exchange-closed days (e.g. New Year's holiday) are
    # reported separately from missing sessions
    assert rep.loc[0, "n_observed_closures"] >= 1


def test_synthetic_loader_valid_and_deterministic():
    a = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-06-01", seed=42)
    b = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2020-06-01", seed=42)
    pd.testing.assert_frame_equal(a, b)
    validate_ohlcv(a)  # must pass strict validation
    assert set(a["symbol"].unique()) == {"SPY"}
    assert str(a["timestamp"].dt.tz) == "UTC"


def test_panels_are_sorted_utc():
    ohlcv = generate_synthetic_ohlcv(["SPY", "QQQ"], "2020-01-01", "2020-06-01", seed=42)
    close, volume = to_panels(ohlcv)
    assert close.index.is_monotonic_increasing
    assert close.index.tz is not None


def test_wide_panel_rejects_duplicates_and_naive(close_panel):
    with pytest.raises(DataValidationError, match="timezone-aware"):
        validate_wide_panel(close_panel.tz_localize(None))
    dup = pd.concat([close_panel, close_panel.iloc[[-1]]]).sort_index()
    with pytest.raises(DataValidationError, match="duplicate"):
        validate_wide_panel(dup)
