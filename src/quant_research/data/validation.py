"""Strict data validation.  Fails loudly; never repairs silently.

Includes an exchange-calendar-aware missing-bar diagnostic that distinguishes
true missing sessions (the exchange was open and no bar exists) from expected
calendar closures (weekends and exchange holidays).  No market bars are ever
fabricated or forward-filled in this layer.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .schemas import FLOAT_COLUMNS, OHLCV_COLUMNS, PRICE_COLUMNS, DataValidationError, DataQualityWarning


def validate_ohlcv(df: pd.DataFrame, require_volume: bool = True) -> pd.DataFrame:
    """Validate the normalized OHLCV long schema.

    Returns a cleaned copy (sorted, UTC-index-normalized).  Raises
    DataValidationError on any schema violation, duplicate observation,
    ordering violation, invalid OHLC relationship, or non-finite price.
    No forward-filling is ever performed here.
    """
    if df is None or len(df) == 0:
        raise DataValidationError("market data is empty")

    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"missing required columns: {missing}")

    out = df.loc[:, OHLCV_COLUMNS].copy()
    # Preserve the synthetic-range flag if present (C17: close-only CSV imports
    # fabricate open/high/low equal to close; downstream range consumers must know
    # the range is not measured).  This column is not part of the core schema but
    # is retained through validation so range-dependent features can be gated.
    if "_synthetic_range" in df.columns:
        out["_synthetic_range"] = df["_synthetic_range"]

    # --- timestamps: tz-aware UTC mandatory; naive rejected so conversion
    # can never silently move information backward in time -------------------
    raw_ts = pd.to_datetime(out["timestamp"], errors="coerce")
    if raw_ts.isna().any():
        raise DataValidationError(
            f"{int(raw_ts.isna().sum())} timestamps could not be parsed as datetimes"
        )
    naive = raw_ts.apply(lambda t: t.tzinfo is None)
    if naive.any():
        raise DataValidationError(
            f"{int(naive.sum())} timezone-naive timestamps; timestamps must be "
            "timezone-aware so UTC conversion is explicit"
        )
    out["timestamp"] = raw_ts.dt.tz_convert("UTC")

    # --- symbols ------------------------------------------------------------
    out["symbol"] = out["symbol"].astype("string")
    if out["symbol"].isna().any() or (out["symbol"].str.len() == 0).any():
        raise DataValidationError("null/empty symbol values found")

    # --- numeric prices -----------------------------------------------------
    for col in FLOAT_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if require_volume or col != "volume":
            if out[col].isna().any():
                bad = out.loc[out[col].isna(), ["timestamp", "symbol"]]
                raise DataValidationError(
                    f"non-numeric/missing values in '{col}' (no silent fill):\n{bad.head()}"
                )

    # --- duplicates ---------------------------------------------------------
    dup_mask = out.duplicated(subset=["timestamp", "symbol"], keep=False)
    if dup_mask.any():
        examples = out.loc[dup_mask, ["timestamp", "symbol"]].head()
        raise DataValidationError(f"duplicate (timestamp, symbol) observations:\n{examples}")

    # B13: one observation per symbol/session.  Daily bars are keyed by exchange
    # session (calendar date); two bars on the same date for the same symbol —
    # e.g. a midnight bar and a same-day 12h bar — are duplicate sessions.
    session_key = out["symbol"].astype(str) + "|" + out["timestamp"].dt.date.astype(str)
    sess_dup_mask = pd.Series(session_key).duplicated(keep=False)
    if sess_dup_mask.any():
        examples = out.loc[sess_dup_mask, ["timestamp", "symbol"]].head()
        raise DataValidationError(
            f"duplicate (symbol, session) observations — one bar per symbol/session "
            f"is required:\n{examples}"
        )

    # --- ordering -----------------------------------------------------------
    if not out["timestamp"].is_monotonic_increasing:
        unsorted = out["timestamp"].diff().dropna()
        bad_pos = int((unsorted < pd.Timedelta(0)).sum())
        raise DataValidationError(
            f"timestamps are not sorted ascending ({bad_pos} descending steps); "
            "ordering must be fixed upstream, not assumed"
        )

    # --- OHLC sanity -------------------------------------------------
    # B13: Enforce complete OHLC relationships. open and close must lie within
    # [low, high], and volume must be finite (not infinite).  Strict contract:
    # fail loudly rather than silently repairing or dropping bars (A21/D08).
    if (out["open"] < out["low"]).any() or (out["open"] > out["high"]).any():
        bad = out[(out["open"] < out["low"]) | (out["open"] > out["high"])]
        raise DataValidationError(
            f"open price outside [low, high] range in {len(bad)} rows:\n{bad.head()}"
        )
    if (out["close"] < out["low"]).any() or (out["close"] > out["high"]).any():
        bad = out[(out["close"] < out["low"]) | (out["close"] > out["high"])]
        raise DataValidationError(
            f"close price outside [low, high] range in {len(bad)} rows:\n{bad.head()}"
        )
    if require_volume:
        if not np.isfinite(out["volume"]).all():
            bad = out[~np.isfinite(out["volume"])]
            raise DataValidationError(
                f"non-finite volume in {len(bad)} rows:\n{bad.head()}"
            )
    bad_hilo = out["high"] < out["low"]
    if bad_hilo.any():
        raise DataValidationError(f"{int(bad_hilo.sum())} rows violate high >= low")
    for col in ("open", "high", "low", "close"):
        bad = (out[col] <= 0) | ~pd.to_numeric(out[col], errors="coerce").apply(
            lambda v: pd.notna(v) and abs(v) != float("inf")
        )
        if bad.any():
            raise DataValidationError(f"{int(bad.sum())} rows have non-positive/non-finite {col}")
    if (out["volume"] < 0).any():
        raise DataValidationError("negative volume found")
    if require_volume and (out["volume"] == 0).all():
        raise DataValidationError("all volumes are zero; volume data looks invalid")

    return out.reset_index(drop=True)


def validate_wide_panel(close: pd.DataFrame, name: str = "close",
                        allow_zero: bool = False) -> pd.DataFrame:
    """Validate a wide (timestamp x symbol) panel used by the feature engine.

    Ensures a unique, sorted, tz-aware UTC DatetimeIndex and finite values;
    values must be positive (or non-negative when allow_zero=True, e.g. for
    volume).  Missing bars are NOT forward-filled here; diagnostics live in
    missing_data_report.
    """
    if close is None or len(close) == 0:
        raise DataValidationError(f"{name} panel is empty")
    idx = close.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise DataValidationError(f"{name} index must be a DatetimeIndex")
    if not idx.is_unique:
        raise DataValidationError(f"{name} index has duplicate timestamps")
    if not idx.is_monotonic_increasing:
        raise DataValidationError(f"{name} index must be sorted ascending")
    if idx.tz is None:
        raise DataValidationError(f"{name} index must be timezone-aware (UTC)")
    vals = close.to_numpy(dtype="float64")
    import numpy as np

    if not np.isfinite(vals).all():
        raise DataValidationError(f"{name} panel contains NaN/inf (no silent fill)")
    if ((vals <= 0) if not allow_zero else (vals < 0)).any():
        raise DataValidationError(
            f"{name} panel contains {'non-positive' if not allow_zero else 'negative'} values"
        )
    return close.sort_index()


def _easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous/Meeus-Jones-Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (Mon=0) of a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last ``weekday`` (Mon=0) of a month."""
    end = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return end - timedelta(days=(end.weekday() - weekday) % 7)


# Known ad-hoc NYSE closures that no regular rule produces.  These are real
# exchange closures, so they are excluded from expected sessions (and any bar
# on such a day would be an off-calendar observation).
_NYSE_SPECIAL_CLOSURES = {
    date(2012, 10, 29),  # Hurricane Sandy
    date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),   # national mourning - G.H.W. Bush
    date(2025, 1, 9),    # national mourning - J. Carter
}


def _observed(d: date, new_year: bool = False) -> date:
    """NYSE weekend-observance rule: Saturday holidays are observed the prior
    Friday and Sunday holidays the following Monday -- except New Year's Day,
    for which the prior Friday (in the previous calendar year) is NOT observed
    (e.g. NYSE stayed open on 2021-12-31 for Sat 2022-01-01)."""
    if d.weekday() == 5:  # Saturday
        return d if new_year else d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def nyse_holidays(first: pd.Timestamp, last: pd.Timestamp) -> set:
    """NYSE regular holiday schedule between two tz-aware timestamps (inclusive).

    Rule-based (no external calendar package):
      - New Year's Day (Jan 1; Sun -> Mon after; Sat -> NOT observed prior Fri)
      - Martin Luther King Jr. Day (3rd Monday January)
      - Washington's Birthday (3rd Monday February)
      - Good Friday (Easter Sunday - 2; never shifted)
      - Memorial Day (last Monday May)
      - Juneteenth (Jun 19, observed from 2022; Sat -> prior Fri, Sun -> Mon)
      - Independence Day (Jul 4; Sat -> prior Fri, Sun -> Mon after)
      - Labor Day (1st Monday September)
      - Thanksgiving (4th Thursday November)
      - Christmas Day (Dec 25; Sat -> prior Fri, Sun -> Mon after)
      - plus known ad-hoc closures (``_NYSE_SPECIAL_CLOSURES``).
    """
    y0, y1 = first.year, last.year
    lo, hi = first.date(), last.date()
    out: set = set()

    def add(d: date) -> None:
        if lo <= d <= hi:
            out.add(d)

    for y in range(y0, y1 + 1):
        add(_observed(date(y, 1, 1), new_year=True))          # New Year's Day
        add(_nth_weekday(y, 1, 0, 3))                          # MLK Day
        add(_nth_weekday(y, 2, 0, 3))                          # Presidents' Day
        add(_easter_sunday(y) - timedelta(days=2))             # Good Friday
        add(_last_weekday(y, 5, 0))                            # Memorial Day
        if y >= 2022:                                          # Juneteenth (2022+)
            add(_observed(date(y, 6, 19)))
        add(_observed(date(y, 7, 4)))                          # Independence Day
        add(_nth_weekday(y, 9, 0, 1))                          # Labor Day
        add(_nth_weekday(y, 11, 3, 4))                         # Thanksgiving
        add(_observed(date(y, 12, 25)))                        # Christmas Day
    out |= {d for d in _NYSE_SPECIAL_CLOSURES if lo <= d <= hi}
    return out


def expected_sessions(
    first,
    last,
    exchange: str = "US",
    tz: str = "UTC",
) -> pd.DatetimeIndex:
    """Exchange trading sessions between two timestamps (inclusive of first/last dates).

    Uses the NYSE exchange calendar (see :func:`nyse_holidays`): weekends and
    valid exchange holidays are excluded, so the returned sessions are the
    sessions the exchange was actually open.  Returns a timezone-aware
    DatetimeIndex of session opens at midnight UTC.  Only ``exchange="US"``
    is supported.
    """
    if exchange != "US":
        raise DataValidationError(f"unsupported exchange calendar {exchange!r}")
    f = pd.Timestamp(first)
    l = pd.Timestamp(last)
    if f.tzinfo is None or l.tzinfo is None:
        raise DataValidationError("expected_sessions requires timezone-aware boundaries")
    holidays = pd.DatetimeIndex(sorted(nyse_holidays(f, l)))
    bdays = pd.bdate_range(f.tz_localize(None).normalize(), l.tz_localize(None).normalize(),
                           freq="B")
    sessions = bdays.difference(holidays)
    return sessions.tz_localize(tz).sort_values()


def missing_data_report(ohlcv: pd.DataFrame, exchange: str = "US") -> pd.DataFrame:
    """Per-symbol missing-bar diagnostics against a real exchange calendar.

    Returns a DataFrame with, per symbol: n_obs, first, last (tz-aware UTC),
    n_expected_sessions (how many sessions the exchange was open), and counts
    of:

    - ``n_missing_sessions``: genuine missing bars - the exchange was open but
      no bar exists.  This is the field the data-integrity gate consumes.
    - ``n_observed_closures``: bars present on days the exchange was closed
      (weekends/holidays) - i.e. fabricated/off-calendar observations.
    - ``n_weekend_bars`` / ``n_holiday_bars``: the calendar-closure breakdown
      of any off-calendar bars (reported separately, never treated as missing).
    - ``n_zero_volume``: bars with zero volume (informational).

    Purely diagnostic - never mutates, never fabricates bars, never
    forward-fills.  Timestamps stay timezone-aware.
    """
    if ohlcv is None or len(ohlcv) == 0:
        raise DataValidationError("market data is empty")
    reports = []
    for symbol, grp in ohlcv.groupby("symbol", observed=True):
        ts = pd.DatetimeIndex(grp["timestamp"])
        first, last = ts.min(), ts.max()
        expected = expected_sessions(first, last, exchange=exchange)
        have = pd.DatetimeIndex(pd.to_datetime(ts.date))
        exp = pd.DatetimeIndex(pd.to_datetime(expected.date))
        missing = exp.difference(have)            # exchange open, no bar
        closures_observed = have.difference(exp)  # bar on closed day
        holidays = nyse_holidays(first, last)
        weekend_bars = int((have.weekday >= 5).sum())
        holiday_bars = int(sum(d.date() in holidays for d in have))
        reports.append(
            {
                "symbol": str(symbol),
                "n_obs": len(grp),
                "first": first,
                "last": last,
                "n_expected_sessions": int(len(expected)),
                "n_missing_sessions": int(len(missing)),
                "n_observed_closures": int(len(closures_observed)),
                "n_weekend_bars": weekend_bars,
                "n_holiday_bars": holiday_bars,
                "n_zero_volume": int((grp["volume"] == 0).sum()),
            }
        )
    return pd.DataFrame(reports)
