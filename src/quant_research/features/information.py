"""Information/news feature engine.

Aggregates point-in-time events into per-bar information features.  All joins
are availability-time aware (see features.point_in_time).  Syndicated/copied
stories are deduplicated first: one underlying event across many feeds must
not count as independent evidence without justification.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .point_in_time import join_events_asof, validate_events

INFO_FEATURE_VERSION = "info-2.1.0"
DEFAULT_DECAY_HALFLIFE_BARS = 5.0


def deduplicate_events(
    events: pd.DataFrame,
    topic_window: pd.Timedelta | str = "12h",
) -> pd.DataFrame:
    """Deduplicate syndicated/copied stories.

    Events from different sources sharing symbol+topic with event_time inside
    `topic_window` are the same underlying story: the earliest-published copy
    is kept, its `corroboration` count incremented, the copies dropped.
    Availability semantics of the kept event are never changed.
    """
    ev = validate_events(events)
    if "topic" not in ev.columns or ev["topic"].isna().all():
        return ev.assign(corroboration=1.0)
    window = pd.Timedelta(topic_window).to_pytimedelta()
    ev = ev.sort_values(["publication_time", "event_id"]).reset_index(drop=True)
    keep_mask = np.ones(len(ev), dtype=bool)
    corroborations = np.ones(len(ev), dtype=float)
    topics = ev["topic"].astype("string").fillna("")
    symbols = ev["symbol"].astype("string").fillna("")
    etimes = ev["event_time"]
    for i in range(len(ev)):
        if not keep_mask[i]:
            continue
        for j in range(i + 1, len(ev)):
            if not keep_mask[j] or symbols.iloc[j] != symbols.iloc[i]:
                continue
            if topics.iloc[i] == "" or topics.iloc[j] != topics.iloc[i]:
                continue
            if abs((etimes.iloc[j] - etimes.iloc[i]).to_pytimedelta()) > window:
                continue
            keep_mask[j] = False
            corroborations[i] += 1.0
    kept = ev.loc[keep_mask].copy()
    # corroborations counts kept event itself (1) + copies absorbed;
    # when a corroboration column already exists, add only the absorbed copies
    extra = corroborations[keep_mask] - 1.0
    if "corroboration" in kept.columns:
        kept["corroboration"] = kept["corroboration"].fillna(0.0).to_numpy() + extra
    else:
        kept["corroboration"] = corroborations[keep_mask]
    return kept.reset_index(drop=True)


INFO_COLUMNS = [
    "info_sentiment",
    "info_abs_sentiment",
    "info_attention",
    "info_source_breadth",
    "info_novelty",
    "info_disagreement",
    "info_intensity",
    "info_corroboration",
]


def build_information_features(
    bars_index: pd.DatetimeIndex,
    events: pd.DataFrame,
    symbol: str,
    deduplicate: bool = True,
    decay_halflife_bars: float = DEFAULT_DECAY_HALFLIFE_BARS,
) -> pd.DataFrame:
    """Aggregate events into availability-aware information features.

    For each bar t only events with availability_time <= t contribute
    (enforced via join_events_asof).  Features: recency-decayed sentiment /
    |sentiment| / novelty, attention (log count), source breadth,
    disagreement, event intensity, max corroboration.  Bars with no live
    events get explicit zeros - never forward-filled stale values.
    """
    ev = events
    if ev is not None and not ev.empty and symbol is not None:
        ev = ev[ev["symbol"].astype("string") == symbol]
    if deduplicate and ev is not None and not ev.empty:
        ev = deduplicate_events(ev)
    if ev is not None and not ev.empty:
        ev = validate_events(ev)
    else:
        ev = pd.DataFrame()

    links = join_events_asof(bars_index, ev)
    n = len(bars_index)
    if links.empty:
        return pd.DataFrame(0.0, index=bars_index, columns=INFO_COLUMNS)

    ev = ev.set_index("event_id")
    linked = links.join(ev, on="event_id")
    linked["bar_timestamp"] = pd.to_datetime(linked["bar_timestamp"], utc=True)
    bar_pos = {t: i for i, t in enumerate(bars_index)}
    linked["bar_idx"] = linked["bar_timestamp"].map(bar_pos).astype(int)
    av_pos = pd.to_datetime(linked["availability_time"], utc=True).map(
        lambda t: bar_pos.get(t.floor("D"), n)
    )
    age_bars = np.maximum(linked["bar_idx"].to_numpy() - av_pos.to_numpy(), 0)
    linked["decay"] = 0.5 ** (age_bars / max(decay_halflife_bars, 1e-9))
    for col in ("sentiment", "novelty", "corroboration"):
        if col in linked.columns:
            linked[col] = pd.to_numeric(linked[col], errors="coerce")
        else:
            linked[col] = np.nan
    linked["sentiment"] = linked["sentiment"].fillna(0.0)
    linked["novelty"] = linked["novelty"].fillna(0.0)
    linked["corroboration"] = linked["corroboration"].fillna(1.0)

    rows = np.zeros((n, len(INFO_COLUMNS)))
    for idx, grp in linked.groupby("bar_idx"):
        i = int(idx)
        w = grp["decay"].to_numpy()
        s = grp["sentiment"].to_numpy()
        wsum = w.sum()
        rows[i, 0] = float(np.average(s, weights=w)) if wsum > 0 else 0.0
        rows[i, 1] = float(np.average(np.abs(s), weights=w)) if wsum > 0 else 0.0
        rows[i, 2] = float(np.log1p(len(grp)))
        rows[i, 3] = float(grp["source"].nunique())
        rows[i, 4] = float(np.average(grp["novelty"].to_numpy(), weights=w)) if wsum > 0 else 0.0
        rows[i, 5] = abs(rows[i, 0]) - rows[i, 1]
        rows[i, 6] = float(np.max(np.abs(s) * w))
        rows[i, 7] = float(grp["corroboration"].max())
    return pd.DataFrame(rows, index=bars_index, columns=INFO_COLUMNS)
