"""Information/news feature engine.

Aggregates point-in-time events into per-bar information features.  All joins
are availability-time aware (see features.point_in_time).  Syndicated/copied
stories are deduplicated: one underlying event across many feeds must not count
as independent evidence without justification.

PREFIX-INVARIANCE (A01): corroboration is a PIT observation, not a global
count.  A feature at bar t may only count copies whose ``availability_time``
has arrived by t.  Adding or removing an event that is not yet available can
never change any historical feature.  Corroboration for the retained story
grows over time as corroborating copies become available, and decays from the
first eligible session (A18).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .point_in_time import validate_events

INFO_FEATURE_VERSION = "info-2.1.1"
DEFAULT_DECAY_HALFLIFE_BARS = 5.0


def deduplicate_events(
    events: pd.DataFrame,
    topic_window: pd.Timedelta | str = "12h",
) -> pd.DataFrame:
    """Deduplicate syndicated/copied stories (static view).

    Events from different sources sharing symbol+topic with event_time inside
    `topic_window` are the same underlying story: the earliest-published copy
    is kept, its `corroboration` count incremented by every absorbed copy, the
    copies dropped.  This is the STATIC (full-collection) summary of the story
    count.  For point-in-time feature construction, corroboration must grow as
    copies become available (use the feature builder, which is prefix-invariant).
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


def _assign_clusters(ev: pd.DataFrame,
                     topic_window: pd.Timedelta | str = "12h") -> pd.DataFrame:
    """Assign each event to its dedup cluster (matching ``deduplicate_events``)
    WITHOUT dropping copies.

    Adds ``_canonical_id`` (event_id of the retained story) and ``_is_copy``.
    ``_is_copy == True`` events are absorbed copies that must NOT contribute
    independent sentiment/attention, but DO extend the retained story's
    corroboration count as they become available.

    B02 FIX: Canonical state is established in availability order, not publication
    order. An earlier-published copy that arrives later must not preempt an
    already-available story. Cluster membership is decided using only events
    available at each decision time.

    E17: revisions of the SAME event_id (same event_id, different revision)
    are versions of one story, never syndicated copies of each other.  They
    are never assigned to another event's cluster and never marked
    ``_is_copy``; revision resolution happens per-bar in
    ``build_information_features`` via the latest eligible revision.
    """
    out = ev.copy()
    if "topic" not in out.columns or out["topic"].isna().all():
        out["_canonical_id"] = out["event_id"].astype(object)
        out["_is_copy"] = False
        return out
    window = pd.Timedelta(topic_window).to_pytimedelta()
    # B02: Sort by availability_time first, then publication_time for ties.
    # This ensures the first-available event becomes canonical, preventing
    # a later-arriving earlier-published copy from preempting an available story.
    out = out.sort_values(["availability_time", "publication_time", "event_id"]).reset_index(drop=True)
    canonical = np.empty(len(out), dtype=object)
    is_copy = np.zeros(len(out), dtype=bool)
    topics = out["topic"].astype("string").fillna("")
    symbols = out["symbol"].astype("string").fillna("")
    etimes = out["event_time"]
    eids = out["event_id"].astype(object).to_numpy()
    # E17: rows sharing an event_id are revisions of one story — pin each to
    # its own event_id so same-topic revisions can never absorb each other
    # (or any other event's rows).
    eid_series = out["event_id"].astype("string")
    _multi_ids = set(eid_series.value_counts().loc[lambda s: s > 1].index.astype(str))
    for i in range(len(out)):
        if is_copy[i]:
            continue
        canonical[i] = eids[i]
        if str(eids[i]) in _multi_ids:
            continue  # E17: revised story — neither absorbs nor is absorbed
        for j in range(i + 1, len(out)):
            if is_copy[j] or symbols.iloc[j] != symbols.iloc[i]:
                continue
            if str(eids[j]) in _multi_ids or str(eids[j]) == str(eids[i]):
                continue  # E17: never absorb another event's revision chain
            if topics.iloc[i] == "" or topics.iloc[j] != topics.iloc[i]:
                continue
            if abs((etimes.iloc[j] - etimes.iloc[i]).to_pytimedelta()) > window:
                continue
            is_copy[j] = True
            canonical[j] = eids[i]
    out["_canonical_id"] = pd.Series(canonical, index=out.index)
    out["_is_copy"] = is_copy
    return out.reset_index(drop=True)


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
    (enforced via join_events_asof semantics).  Deduplication is PREFIX-INVARIANT:
    a retained story's corroboration at bar t equals 1 plus the number of its
    absorbed copies AVAILABLE by t -- later (not-yet-available) copies can never
    change an earlier feature.  Features: recency-decayed sentiment /
    |sentiment| / novelty, attention (log count of distinct live stories),
    source breadth, disagreement, event intensity, and the maximum live-story
    corroboration.  Bars with no live events get explicit zeros - never
    forward-filled stale values.  Event age (half-life decay) is measured from
    the first eligible session (the first bar at/after availability), so
    weekend/holiday/prehistory events decay normally instead of never (A18).
    """
    ev = events
    if ev is not None and not ev.empty and symbol is not None:
        ev = ev[ev["symbol"].astype("string") == symbol]
    n = len(bars_index)
    if ev is None or ev.empty:
        return pd.DataFrame(0.0, index=bars_index, columns=INFO_COLUMNS)
    ev = validate_events(ev)

    ts = pd.DatetimeIndex(bars_index)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    # B01/D01: Normalize all timestamps to a safe common precision for consistent
    # comparison.  Pandas supports datetime arrays with different resolutions
    # (ns, us, ms, s), and asi8 values can differ by factors of 1000 for
    # identical timestamps.  Use nanoseconds (the highest resolution) to avoid
    # rounding an unavailable event backward into eligibility.
    ts_us = ts.as_unit("ns")
    ts_int = ts_us.asi8  # ns since epoch, sorted
    halflife = max(float(decay_halflife_bars), 1e-9)

    if deduplicate and len(ev) > 1:
        evc = _assign_clusters(ev)
        copies = evc[evc["_is_copy"]]
        # E17: resolutions must be REVISION-aware, never double-count revisions.
        # Same-id rows are versions of ONE story, not independent evidence.
        # Keep every revision row here; the per-bar loop below resolves each
        # event_id to its single latest eligible revision (highest revision
        # with availability_time <= t, ties -> earliest availability).
        rev_num_all = pd.to_numeric(evc["revision"], errors="coerce").fillna(0).to_numpy()
        evc = evc.assign(_rev_num=rev_num_all)
        evc_av = pd.to_datetime(evc["availability_time"], utc=True)
        evc_av_idx = pd.DatetimeIndex(evc_av)
        evc_av_us = evc_av_idx.as_unit("ns")
        evc = evc.assign(_av_int=evc_av_us.asi8)
        canon_all = evc[~evc["_is_copy"]].reset_index(drop=True)
        # copy availability (ns) per canonical story, sorted, for live counting
        copy_by_canon: dict = {}
        if len(copies):
            for cid, grp in copies.groupby("_canonical_id", sort=False):
                av = pd.to_datetime(grp["availability_time"], utc=True)
                av_idx = pd.DatetimeIndex(av)
                av_us = av_idx.as_unit("ns")
                copy_by_canon[cid] = np.sort(av_us.asi8)
        canon = canon_all
    else:
        canon = ev.assign(_canonical_id=ev["event_id"].astype(object))
        copy_by_canon = {}

    canon_av = pd.to_datetime(canon["availability_time"], utc=True)
    # B01/D01: Normalize canonical availability to same unit as bar index (ns)
    # Convert Series to DatetimeIndex for as_unit/asi8 access
    canon_av_idx = pd.DatetimeIndex(canon_av)
    canon_av_us = canon_av_idx.as_unit("ns")
    canon_av_int = canon_av_us.asi8  # ns since epoch (numpy array)
    first_bar = np.searchsorted(ts_int, canon_av_int, side="left")

    def _num(col: str, default: float) -> np.ndarray:
        if col in canon.columns:
            return pd.to_numeric(canon[col], errors="coerce").fillna(default).to_numpy()
        return np.full(len(canon), default)

    sentiment_all = _num("sentiment", 0.0)
    novelty_all = _num("novelty", 0.0)
    sources_all = canon["source"].astype("string").fillna("").to_numpy()
    cid_all = canon["_canonical_id"].astype(object).to_numpy()
    avail_all = canon_av_int
    eid_all = canon["event_id"].astype(object).to_numpy()
    if "_rev_num" in canon.columns:
        rev_all = canon["_rev_num"].to_numpy()
    else:
        rev_all = np.zeros(len(canon))

    rows = np.zeros((n, len(INFO_COLUMNS)))
    for i, t in enumerate(ts_int):
        live_mask = avail_all <= t
        if not live_mask.any():
            continue
        # E17: resolve each event_id to its latest eligible revision only.
        live_pos = np.flatnonzero(live_mask)
        # highest revision first; ties -> earliest availability (stable order)
        order = live_pos[np.lexsort((avail_all[live_pos], -rev_all[live_pos]))]
        seen: set = set()
        keep = []
        for p in order:
            eid = eid_all[p]
            if eid in seen:
                continue
            seen.add(eid)
            keep.append(p)
        keep = np.asarray(keep)
        live_idx = np.zeros(len(canon), dtype=bool)
        live_idx[keep] = True
        live = live_idx
        age = np.maximum(i - first_bar[live], 0)
        w = 0.5 ** (age / halflife)
        s = sentiment_all[live]
        nv = novelty_all[live]
        wsum = w.sum()
        rows[i, 0] = float(np.average(s, weights=w)) if wsum > 0 else 0.0
        rows[i, 1] = float(np.average(np.abs(s), weights=w)) if wsum > 0 else 0.0
        rows[i, 2] = float(np.log1p(int(live.sum())))
        rows[i, 3] = float(np.unique(sources_all[live]).size)
        rows[i, 4] = float(np.average(nv, weights=w)) if wsum > 0 else 0.0
        rows[i, 5] = abs(rows[i, 0]) - rows[i, 1]
        rows[i, 6] = float(np.max(np.abs(s) * w))
        # corroboration of each live story: 1 (itself) + live absorbed copies
        counts = np.ones(int(live.sum()), dtype=float)
        for k, cid in enumerate(cid_all[live]):
            ck = copy_by_canon.get(cid)
            if ck is not None and len(ck):
                counts[k] += float(np.searchsorted(ck, t, side="right"))
        rows[i, 7] = float(counts.max()) if len(counts) else 1.0
    return pd.DataFrame(rows, index=bars_index, columns=INFO_COLUMNS)
