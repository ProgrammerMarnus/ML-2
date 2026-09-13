"""Strict data validation.  Fails loudly; never repairs silently.

Includes an exchange-calendar-aware missing-bar diagnostic that distinguishes
true missing sessions (the exchange was open and no bar exists) from expected
calendar closures (weekends and exchange holidays).  No market bars are ever
fabricated or forward-filled in this layer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import expected_sessions as _calendar_expected_sessions, is_session
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

    # Validate the normalized result with the declarative schema only after the
    # engine has emitted its intentionally precise policy errors above.
    _validate_ohlcv_schema(out)
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


def _validate_ohlcv_schema(df: pd.DataFrame) -> None:
    """Apply a declarative Pandera schema before domain-specific validation.

    Pandera is intentionally only the structural layer.  The causal, calendar,
    session-uniqueness and no-repair rules below remain owned by this engine.
    """
    try:
        import pandera.pandas as pa
    except ImportError as exc:  # pragma: no cover - dependency declared in project
        raise DataValidationError("pandera is required for OHLCV schema validation") from exc
    try:
        schema = pa.DataFrameSchema(
            {
                "timestamp": pa.Column(nullable=False),
                "symbol": pa.Column(nullable=False),
                "open": pa.Column(float, nullable=True, coerce=True),
                "high": pa.Column(float, nullable=True, coerce=True),
                "low": pa.Column(float, nullable=True, coerce=True),
                "close": pa.Column(float, nullable=True, coerce=True),
                "volume": pa.Column(float, nullable=True, coerce=True),
            },
            strict=False,
            coerce=False,
        )
        schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataValidationError(f"OHLCV dataframe schema violation: {exc}") from exc


def expected_sessions(
    first,
    last,
    exchange: str = "US",
    tz: str = "UTC",
) -> pd.DatetimeIndex:
    """Exchange trading sessions between two timestamps (inclusive of first/last dates).

    Delegates schedule knowledge to ``exchange_calendars``.  ``US`` remains a
    backwards-compatible alias for ``XNYS``.  Any calendar code supported by
    that package (for example ``XJSE``) is accepted.
    """
    return _calendar_expected_sessions(first, last, exchange=exchange, tz=tz)


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
        weekend_bars = int((have.weekday >= 5).sum())
        holiday_bars = int(sum(d.weekday() < 5 and not is_session(
            pd.Timestamp(d).tz_localize("UTC"), exchange=exchange
        ) for d in have))
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
