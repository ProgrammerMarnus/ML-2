"""Exchange-calendar-aware data-integrity tests.

Distinguishes genuine missing sessions (exchange open, no bar) from expected
calendar closures (weekends / US market holidays); preserves timezone-aware
timestamps; never fabricates or forward-fills bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.data.validation import (
    expected_sessions,
    missing_data_report,
    validate_ohlcv,
)


def _long_from_dates(dates, symbol="SPY"):
    n = len(dates)
    return pd.DataFrame({
        "timestamp": pd.DatetimeIndex(dates),
        "symbol": symbol,
        "open": np.full(n, 100.0),
        "high": np.full(n, 101.0),
        "low": np.full(n, 99.0),
        "close": np.full(n, 100.0),
        "volume": np.full(n, 1000.0),
    })


@pytest.fixture(scope="module")
def q1_2020():
    return expected_sessions(
        pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2020-03-31", tz="UTC")
    )


@pytest.fixture(scope="module")
def year_2020():
    return expected_sessions(
        pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2020-12-31", tz="UTC")
    )


def test_weekends_are_not_missing_sessions(q1_2020):
    assert (q1_2020.weekday >= 5).sum() == 0  # no weekend sessions in calendar
    rep = missing_data_report(_long_from_dates(q1_2020))
    assert rep.loc[0, "n_missing_sessions"] == 0
    assert rep.loc[0, "n_weekend_bars"] == 0
    assert rep.loc[0, "n_observed_closures"] == 0


def test_us_holidays_are_not_missing_sessions(year_2020):
    # known US market holidays are excluded from the expected sessions
    for h in ("2020-01-20", "2020-07-03", "2020-11-26", "2020-12-25"):
        assert pd.Timestamp(h, tz="UTC") not in year_2020
    rep = missing_data_report(_long_from_dates(year_2020))
    assert rep.loc[0, "n_missing_sessions"] == 0
    assert rep.loc[0, "n_holiday_bars"] == 0


def test_true_missing_bar_detected(q1_2020):
    dropped = q1_2020.drop(q1_2020[10])  # remove one genuine session
    rep = missing_data_report(_long_from_dates(dropped))
    assert rep.loc[0, "n_missing_sessions"] == 1
    assert rep.loc[0, "n_obs"] == len(q1_2020) - 1


def test_weekend_bar_reported_as_closure_not_missing(q1_2020):
    sat = pd.Timestamp("2020-01-04", tz="UTC")  # a Saturday
    df = _long_from_dates(list(q1_2020) + [sat])
    rep = missing_data_report(df)
    assert rep.loc[0, "n_missing_sessions"] == 0
    assert rep.loc[0, "n_observed_closures"] == 1
    assert rep.loc[0, "n_weekend_bars"] == 1


def test_holiday_bar_reported_as_closure(q1_2020):
    mlk = pd.Timestamp("2020-01-20", tz="UTC")  # MLK day, exchange closed
    df = _long_from_dates(list(q1_2020) + [mlk])
    rep = missing_data_report(df)
    assert rep.loc[0, "n_observed_closures"] == 1
    assert rep.loc[0, "n_holiday_bars"] == 1
    assert rep.loc[0, "n_missing_sessions"] == 0


def test_duplicate_bars_rejected(q1_2020):
    df = _long_from_dates(list(q1_2020) + [q1_2020[5]])
    with pytest.raises(DataValidationError, match="duplicate"):
        validate_ohlcv(df)


def test_timezone_normalization_preserved(q1_2020):
    rep = missing_data_report(_long_from_dates(q1_2020))
    assert rep.loc[0, "first"].tz is not None
    assert str(rep.loc[0, "first"].tz) == "UTC"
    assert str(rep.loc[0, "last"].tz) == "UTC"
    # naive timestamps are rejected upstream (no silent shifting)
    naive = pd.DatetimeIndex(q1_2020).tz_localize(None)
    with pytest.raises(DataValidationError, match="timezone-naive"):
        validate_ohlcv(_long_from_dates(naive))


def test_synthetic_loader_is_exchange_calendar_clean():
    from quant_research.data.loaders import generate_synthetic_ohlcv

    ohlcv = generate_synthetic_ohlcv(["SPY"], "2020-01-01", "2021-01-01", seed=42)
    rep = missing_data_report(ohlcv)
    assert rep.loc[0, "n_missing_sessions"] == 0
    assert rep.loc[0, "n_observed_closures"] == 0
    assert rep.loc[0, "n_holiday_bars"] == 0


def test_nyse_calendar_not_federal_calendar():
    """The calendar must be NYSE-aware, not USFederalHolidayCalendar.

    NYSE is OPEN on Columbus Day and Veterans Day (federal holidays) and
    CLOSED on Good Friday (not a federal holiday).
    """
    y2020 = expected_sessions(
        pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2020-12-31", tz="UTC"))
    assert pd.Timestamp("2020-10-12", tz="UTC") in y2020   # Columbus Day: NYSE open
    assert pd.Timestamp("2020-11-11", tz="UTC") in y2020   # Veterans Day: NYSE open
    assert pd.Timestamp("2020-04-10", tz="UTC") not in y2020  # Good Friday: closed


def test_nyse_good_friday_is_not_missing_session(q1_2020):
    """Q1 2020 includes Good Friday (Apr 10): no bar there is NOT a gap."""
    assert pd.Timestamp("2020-04-10", tz="UTC") not in q1_2020
    rep = missing_data_report(_long_from_dates(q1_2020))
    assert rep.loc[0, "n_missing_sessions"] == 0


def test_nyse_new_year_saturday_not_observed_prior_friday():
    """Jan 1 2022 (Saturday): NYSE stayed OPEN on Fri 2021-12-31."""
    y21 = expected_sessions(
        pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2021-12-31", tz="UTC"))
    assert pd.Timestamp("2021-12-31", tz="UTC") in y21
    # but Christmas Sat 2021-12-25 IS observed the prior Friday
    assert pd.Timestamp("2021-12-24", tz="UTC") not in y21


def test_nyse_juneteenth_starts_2022():
    """Juneteenth is an NYSE holiday only from 2022 (observed Mon Jun 20 2022);
    in 2021 NYSE remained open on Fri Jun 18."""
    y21 = expected_sessions(
        pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2021-12-31", tz="UTC"))
    y22 = expected_sessions(
        pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC"))
    assert pd.Timestamp("2021-06-18", tz="UTC") in y21
    assert pd.Timestamp("2022-06-20", tz="UTC") not in y22


def test_nyse_session_count_matches_real_data_extent():
    """The real SPY/QQQ dataset (2012-01-03 .. 2025-12-31) holds 3520 bars;
    the calendar must expect exactly that many sessions."""
    sessions = expected_sessions(
        pd.Timestamp("2012-01-03", tz="UTC"), pd.Timestamp("2025-12-31", tz="UTC"))
    assert len(sessions) == 3520
