"""Point-in-time (PIT) event schema and availability enforcement.

Core rules
----------
1. ``availability_time`` controls when information becomes usable.
2. A feature at bar ``t`` may only consume events whose ``availability_time``
   is at or before the bar's permitted execution timestamp.
3. Event time, publication time, and availability time are distinct concepts.
4. Missing ``availability_time`` is an error, not silent immediate tradability.
5. Revised values must be versioned (distinct ``event_id`` + ``revision``);
   an identical ``event_id`` with conflicting raw_value is rejected.
6. All timestamps must be timezone-aware UTC; naive timestamps are rejected so
   timezone conversion can never move information backward in time.

Daily-bar convention (conservative): the permitted execution timestamp of a
daily bar is the bar's own timestamp (session open).  Therefore an event
published after the close of session ``t`` only affects bars with timestamp
strictly after day ``t`` - i.e. next-session execution.  Deliberately
conservative: it can never introduce look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..data.schemas import DataValidationError

EVENT_REQUIRED_COLUMNS = [
    "event_id",
    "symbol",
    "event_time",
    "publication_time",
    "availability_time",
    "source",
    "raw_value",
    "processed_value",
]
EVENT_OPTIONAL_COLUMNS = [
    "author_id",
    "topic",
    "sentiment",
    "confidence",
    "engagement",
    "novelty",
    "source_quality",
    "corroboration",
    "disagreement",
    "revision",
]
TIME_COLUMNS = ["event_time", "publication_time", "availability_time"]


@dataclass(frozen=True)
class EventRecord:
    """One point-in-time information event."""

    event_id: str
    symbol: str
    event_time: pd.Timestamp
    publication_time: pd.Timestamp
    availability_time: pd.Timestamp
    source: str
    raw_value: object
    processed_value: object
    author_id: Optional[str] = None
    topic: Optional[str] = None
    sentiment: Optional[float] = None
    confidence: Optional[float] = None
    engagement: Optional[float] = None
    novelty: Optional[float] = None
    source_quality: Optional[float] = None
    corroboration: Optional[float] = None
    disagreement: Optional[float] = None
    revision: int = 0


def _to_utc(series: pd.Series, name: str) -> pd.Series:
    """Convert to tz-aware UTC; reject naive timestamps (no silent shifting)."""
    if series.isna().any():
        raise DataValidationError(f"{name} contains missing timestamps")
    raw = pd.to_datetime(series, errors="coerce")
    if raw.isna().any():
        raise DataValidationError(f"{name} contains unparseable timestamps")
    naive = raw.apply(lambda t: t.tzinfo is None)
    if naive.any():
        raise DataValidationError(
            f"{name} contains timezone-naive timestamps; tz must be explicit "
            "so conversion can never move information backward"
        )
    return raw.dt.tz_convert("UTC")


def validate_events(events: pd.DataFrame) -> pd.DataFrame:
    """Validate the PIT event schema and temporal ordering rules.

    Raises DataValidationError on schema violations, naive timestamps,
    missing availability_time, publication before event, availability before
    publication, or a duplicate event_id with conflicting raw_value.  The
    optional boolean column ``provider_rule_exception`` explicitly whitelists
    availability earlier than event time for documented provider rules.
    """
    if events is None or len(events) == 0:
        raise DataValidationError("event frame is empty")
    missing = [c for c in EVENT_REQUIRED_COLUMNS if c not in events.columns]
    if missing:
        raise DataValidationError(f"event frame missing required columns: {missing}")

    out = events.copy()
    for col in TIME_COLUMNS:
        out[col] = _to_utc(out[col], col)

    av_before_event = out["availability_time"] < out["event_time"]
    av_before_pub = out["availability_time"] < out["publication_time"]
    if "provider_rule_exception" in out.columns:
        rule = out["provider_rule_exception"].fillna(False).astype(bool)
        av_before_event = av_before_event & ~rule
        av_before_pub = av_before_pub & ~rule
    if av_before_event.any():
        raise DataValidationError(
            f"{int(av_before_event.sum())} events have availability_time earlier than "
            "event_time without an explicit provider rule exception"
        )
    if (out["publication_time"] < out["event_time"]).any():
        raise DataValidationError("publication_time earlier than event_time")
    if av_before_pub.any():
        raise DataValidationError("availability_time earlier than publication_time")

    if out["event_id"].isna().any():
        raise DataValidationError("event_id cannot be null")
    dup = out[out["event_id"].duplicated(keep=False)]
    if not dup.empty:
        conflicting = dup.groupby("event_id")["raw_value"].nunique()
        if (conflicting > 1).any():
            raise DataValidationError(
                "event_id reused with conflicting raw_value; revisions must be versioned"
            )
    return out.reset_index(drop=True)


def available_asof(events: pd.DataFrame, timestamp: pd.Timestamp) -> pd.DataFrame:
    """Return only events whose availability_time is <= timestamp."""
    if events is None or len(events) == 0:
        return events
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        raise DataValidationError("as-of timestamp must be timezone-aware")
    av = pd.to_datetime(events["availability_time"], utc=True)
    return events.loc[av <= ts]


def join_events_asof(bars_index: pd.DatetimeIndex, events: pd.DataFrame) -> pd.DataFrame:
    """PIT join: for each bar timestamp t, the events available at or before t.

    Bars are daily sessions; the permitted execution timestamp of bar t is t
    itself (session open), so after-close publications land in the next
    session.  Returns a long frame (bar_timestamp, event_id) of usable events.
    """
    if not isinstance(bars_index, pd.DatetimeIndex) or bars_index.tz is None:
        raise DataValidationError("bars_index must be a timezone-aware DatetimeIndex")
    rows = []
    ev = events
    if ev is not None and not ev.empty:
        ev = ev.copy()
        ev["availability_time"] = pd.to_datetime(ev["availability_time"], utc=True)
        ev = ev.sort_values("availability_time")
        for t in bars_index:
            lo = int(ev["availability_time"].searchsorted(t, side="right"))
            if lo > 0:
                for eid in ev["event_id"].iloc[:lo].tolist():
                    rows.append({"bar_timestamp": t, "event_id": eid})
    return pd.DataFrame(rows, columns=["bar_timestamp", "event_id"])
