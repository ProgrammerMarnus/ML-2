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
    # ``revision`` is optional in the external event contract.  Downstream
    # point-in-time resolution always operates on an explicit numeric revision,
    # so ordinary one-version events receive the canonical base revision.
    if "revision" not in out.columns:
        out["revision"] = 0
    for col in TIME_COLUMNS:
        out[col] = _to_utc(out[col], col)

    av_before_event = out["availability_time"] < out["event_time"]
    av_before_pub = out["availability_time"] < out["publication_time"]
    if "provider_rule_exception" in out.columns:
        raw_exc = out["provider_rule_exception"]

        # C10: Reject any non-boolean provider_rule_exception values.
        # The column must be explicitly True/False; strings, numbers, NaN, or
        # other truthy values are rejected so that authorization is never inferred
        # from truthiness.
        if pd.api.types.is_bool_dtype(raw_exc.dtype):
            # Plain numpy bool ("b") or pandas nullable boolean ("boolean").
            # Plain bool cannot hold NA; nullable boolean can — reject it.
            if raw_exc.isna().any():
                raise DataValidationError(
                    "provider_rule_exception contains missing (NA) values; "
                    "use explicit True/False — never NA — so authorization is deliberate"
                )
        elif raw_exc.dtype.kind in ("O", "U", "S"):
            # String / object columns: reject (including "False", "True", "", etc.)
            raise DataValidationError(
                "provider_rule_exception contains string values; "
                "use explicit boolean True/False, not strings"
            )
        else:
            # Numeric or other dtype: reject (2, 0.5, np.nan, etc. all rejected)
            raise DataValidationError(
                "provider_rule_exception must be a boolean (True/False); "
                f"received dtype {raw_exc.dtype}"
            )

        # Now safe: convert to plain bool and apply the exception.
        rule = raw_exc.astype(bool)
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
        # C11: Reuse of an event_id is only permitted for versioned revisions
        # (distinct ``revision``).  A revision with conflicting identity fields
        # is rejected even if another revision for the same event_id exists;
        # identical repeats within one revision are permitted (deduplicated
        # downstream), never a runtime crash.
        identity_cols = ["raw_value", "processed_value", "source",
                         "availability_time", "publication_time", "event_time"]
        has_revision = "revision" in out.columns
        conflicting = []
        for eid, grp in dup.groupby("event_id", sort=False):
            # D10: Null revisions are treated as a distinct revision group,
            # not merged with non-null revisions.  This prevents a null
            # revision from masking conflicts with a numbered revision.
            if has_revision:
                # Fill NaN revisions with a sentinel so they form their own
                # group and don't merge with numbered revisions.
                rev_col = grp["revision"].fillna("__null_revision__")
                rev_groups = grp.groupby(rev_col, sort=False)
            else:
                rev_groups = [(None, grp)]
            for rev, rev_grp in rev_groups:
                for col in identity_cols:
                    vals = rev_grp[col]
                    if pd.api.types.is_datetime64_any_dtype(vals):
                        # D10: For datetime columns, count NaT as a distinct
                        # value so missing timestamps don't mask conflicts.
                        nunique = len(vals.dropna().unique()) + int(vals.isna().any())
                    else:
                        # E16: missing identity values are DISTINCT from any
                        # populated value (and never silently equal to it).
                        # Mirror the datetime branch: count NaN/None as its own
                        # value so [1.0, NaN] or [None, "wire"] conflict instead
                        # of being silently equated (pandas nunique() drops
                        # NaN, which hid the conflict).  Two rows that both
                        # lack the field ([NaN, NaN]) still dedup.
                        try:
                            n_non_null = vals[~vals.isna()].nunique(dropna=True)
                            has_null = bool(vals.isna().any())
                        except Exception:
                            n_non_null = vals.nunique()
                            has_null = False
                        nunique = int(n_non_null) + int(has_null)
                    if nunique > 1:
                        conflicting.append(
                            (str(eid), col, int(rev) if rev is not None and rev != "__null_revision__" else None))
                        break
                # Optional sentiment conflict (only when the column is present).
                if "sentiment" in rev_grp.columns and rev_grp["sentiment"].nunique() > 1:
                    conflicting.append(
                        (str(eid), "sentiment", int(rev) if rev is not None and rev != "__null_revision__" else None))
        if conflicting:
            raise DataValidationError(
                f"event_id reused with conflicting identity fields "
                f"(revisions must be versioned): {conflicting[:5]}"
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
