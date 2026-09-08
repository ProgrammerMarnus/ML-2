"""Strictly lagged Parkinson volatility for normalized long OHLCV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.schemas import (
    FLOAT_COLUMNS,
    OHLCV_COLUMNS,
    PRICE_COLUMNS,
    DataValidationError,
)

PARKINSON_FEATURE_VERSION: str = "parkinson-1.0.0"
FEATURE_NAME: str = "parkinson_vol_20_lag1"
WINDOW: int = 20
ANNUALIZATION_FACTOR: float = 252.0

__all__ = ["lagged_parkinson_volatility"]


def _validate_input(ohlcv: pd.DataFrame) -> None:
    """Validate normalized input without coercing or modifying it.

    Args:
        ohlcv: Nonempty long OHLCV frame with unique column labels, UTC
            timestamps, string symbols, and float64 market columns.

    Raises:
        TypeError: If ohlcv is not a pandas DataFrame.
        DataValidationError: If schema, dtype, value, uniqueness, or
            per-symbol chronological requirements are violated.
    """
    if not isinstance(ohlcv, pd.DataFrame):
        raise TypeError(
            f"ohlcv must be a pandas DataFrame, got {type(ohlcv).__name__}"
        )
    if ohlcv.shape[0] == 0:
        raise DataValidationError("ohlcv is empty")

    if not ohlcv.columns.is_unique:
        raise DataValidationError("column labels must be unique")

    missing = [c for c in OHLCV_COLUMNS if c not in ohlcv.columns]
    if missing:
        raise DataValidationError(f"missing required columns: {missing}")

    # --- timestamps: tz-aware datetime dtype pinned to UTC, no NaT ---------
    ts = ohlcv["timestamp"]
    tz = getattr(ts.dtype, "tz", None)
    if tz is None or str(tz).upper() != "UTC":
        raise DataValidationError(
            "timestamp must be a timezone-aware datetime dtype with "
            f"tz=UTC; got {ts.dtype}"
        )
    if ts.isna().any():
        raise DataValidationError("timestamp contains NaT values")

    # --- symbols: object or pandas string dtype of nonempty strings --------
    sym = ohlcv["symbol"]
    if not (
        pd.api.types.is_object_dtype(sym) or isinstance(sym.dtype, pd.StringDtype)
    ):
        raise DataValidationError(
            f"symbol must have object or pandas string dtype; got {sym.dtype}"
        )
    lengths = sym.str.len()  # NaN/NA wherever a value is not a string
    bad_symbol = sym.isna() | lengths.isna() | (lengths == 0)
    if bool(bad_symbol.fillna(True).any()):
        raise DataValidationError(
            "symbol must contain exclusively nonempty strings "
            "(no nulls, no coercion)"
        )

    # --- market columns: exact float64 dtype, finite, positivity -----------
    for col in FLOAT_COLUMNS:
        colvals = ohlcv[col]
        if colvals.dtype != np.dtype("float64"):
            raise DataValidationError(
                f"'{col}' must be numpy float64 dtype; got {colvals.dtype}"
            )
        arr = colvals.to_numpy()
        if not np.isfinite(arr).all():
            raise DataValidationError(f"'{col}' contains NaN or infinite values")
    for col in PRICE_COLUMNS:
        if not (ohlcv[col].to_numpy() > 0.0).all():
            raise DataValidationError(f"'{col}' must be strictly positive")
    if (ohlcv["volume"].to_numpy() < 0.0).any():
        raise DataValidationError("'volume' must be nonnegative")

    if bool((ohlcv["high"] < ohlcv["low"]).any()):
        raise DataValidationError("high < low violates the OHLC relationship")

    # --- positional copies: the input index never drives alignment ---------
    pos_sym = sym.reset_index(drop=True)
    pos_ts = ts.reset_index(drop=True)

    duplicates = pd.DataFrame(
        {"symbol": pos_sym, "timestamp": pos_ts}
    ).duplicated()
    if bool(duplicates.any()):
        raise DataValidationError("duplicate (symbol, timestamp) pairs found")

    steps = pos_ts.groupby(pos_sym, sort=False, observed=True).diff()
    if bool((steps < pd.Timedelta(0)).any()):
        raise DataValidationError(
            "timestamps must be strictly increasing within each symbol"
        )


def lagged_parkinson_volatility(ohlcv: pd.DataFrame) -> pd.Series:
    """Compute annualized Parkinson volatility using prior symbol bars.

    Args:
        ohlcv: Long OHLCV frame of shape (N, C), C >= 7. Each symbol's
            timestamps must be strictly increasing. Required market
            columns must satisfy the validated normalized-data contract.

    Returns:
        Float64 Series of shape (N,), named "parkinson_vol_20_lag1",
        with the exact input index and row order. At symbol position i,
        the value uses positions i-20 through i-1. The first 20 positions
        of each symbol are NaN. The input is never modified.

    Raises:
        TypeError: If ohlcv is not a pandas DataFrame.
        DataValidationError: If input validation fails.

    Notes:
        Annualization assumes 252 observations per year. The function
        performs no imputation, scaling, or parameter fitting.
    """
    _validate_input(ohlcv)

    work: pd.DataFrame = (
        ohlcv.loc[:, ["symbol", "high", "low"]]
        .reset_index(drop=True)
    )
    positions: pd.Index = work.index
    symbols: pd.Series = work["symbol"]

    log_range: np.ndarray = (
        np.log(work["high"].to_numpy())
        - np.log(work["low"].to_numpy())
    )
    contribution: pd.Series = pd.Series(
        np.square(log_range) / (4.0 * np.log(2.0)),
        index=positions,
        dtype="float64",
    )

    lagged: pd.Series = contribution.groupby(
        symbols, sort=False, observed=True
    ).shift(1)

    rolling_mean: pd.Series = (
        lagged.groupby(symbols, sort=False, observed=True)
        .rolling(window=WINDOW, min_periods=WINDOW, center=False)
        .mean()
        .droplevel(0)
        .reindex(positions)
    )

    values: np.ndarray = np.sqrt(
        ANNUALIZATION_FACTOR * rolling_mean.to_numpy()
    )
    return pd.Series(
        values,
        index=ohlcv.index,
        name=FEATURE_NAME,
        dtype="float64",
    )