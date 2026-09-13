"""Exchange-calendar adapter used by daily market-data validation.

The engine deliberately owns the *policy* (missing observations are errors),
but delegates exchange schedules to ``exchange_calendars`` rather than
maintaining a partial holiday table.  The adapter returns normalized UTC
session labels, which keeps the existing daily-bar data contract unchanged.
"""

from __future__ import annotations

import pandas as pd

from .schemas import DataValidationError


_ALIASES = {"US": "XNYS", "NYSE": "XNYS"}


def canonical_exchange(exchange: str) -> str:
    """Return an ``exchange_calendars`` calendar code for a user-facing name."""
    if not isinstance(exchange, str) or not exchange.strip():
        raise DataValidationError("exchange calendar name must be a non-empty string")
    return _ALIASES.get(exchange.upper(), exchange.upper())


def _calendar(name: str):
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover - dependency declared in project
        raise DataValidationError(
            "exchange-calendars is required for market-session validation; "
            "install the project dependencies"
        ) from exc
    try:
        return xcals.get_calendar(canonical_exchange(name))
    except Exception as exc:
        raise DataValidationError(f"unknown or unavailable exchange calendar {name!r}") from exc


def _boundary(value, name: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise DataValidationError(f"{name} must be timezone-aware")
    return ts.tz_convert("UTC").normalize()


def expected_sessions(first, last, exchange: str = "US", tz: str = "UTC") -> pd.DatetimeIndex:
    """Return actual exchange session labels, inclusive, in the requested zone."""
    f, l = _boundary(first, "first"), _boundary(last, "last")
    if l < f:
        raise DataValidationError("last session boundary precedes first boundary")
    sessions = pd.DatetimeIndex(_calendar(exchange).sessions_in_range(f.tz_localize(None), l.tz_localize(None)))
    # exchange_calendars exposes session labels as dates.  Normalize explicitly
    # to make daily coverage checks independent of a calendar's trading hours.
    if sessions.tz is None:
        sessions = sessions.tz_localize("UTC")
    else:
        sessions = sessions.tz_convert("UTC")
    return sessions.normalize().tz_convert(tz).sort_values()


def is_session(value, exchange: str = "US") -> bool:
    """Whether the UTC calendar date is an official session label."""
    ts = _boundary(value, "timestamp")
    return bool(_calendar(exchange).is_session(ts.tz_localize(None)))


def library_version() -> str:
    """Return the installed calendar ruleset version for experiment provenance."""
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover - dependency declared in project
        raise DataValidationError("exchange-calendars is required for market-session validation") from exc
    return str(getattr(xcals, "__version__", "unknown"))
