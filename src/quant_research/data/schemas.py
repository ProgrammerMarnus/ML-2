"""Normalized market data schema.

Minimum normalized schema (long format, one row per symbol-bar):

    timestamp  symbol  open  high  low  close  volume

All timestamps must be timezone-aware UTC.  Missing market observations are
never silently filled and bad provider data is never silently repaired.
"""

from __future__ import annotations

OHLCV_COLUMNS = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
PRICE_COLUMNS = ["open", "high", "low", "close"]
FLOAT_COLUMNS = PRICE_COLUMNS + ["volume"]
SYMBOL_DTYPE = "string"


class DataValidationError(ValueError):
    """Raised when raw data violates the normalized schema or sanity rules."""
