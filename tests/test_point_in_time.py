"""Point-in-time adversarial tests (highest priority)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.features.information import (
    build_information_features,
    deduplicate_events,
)
from quant_research.features.point_in_time import (
    available_asof,
    join_events_asof,
    validate_events,
)


def make_events(idx, symbol="SPY"):
    return pd.DataFrame([
        {
            "event_id": "e1",
            "symbol": symbol,
            "event_time": idx[5],
            "publication_time": idx[5],
            "availability_time": idx[5],
            "source": "wire",
            "raw_value": 1.0,
            "processed_value": 0.5,
            "sentiment": 0.6,
        },
        {
            "event_id": "e2",
            "symbol": symbol,
            "event_time": idx[8],
            "publication_time": idx[8],
            "availability_time": idx[8] + pd.Timedelta(days=1),  # next-session
            "source": "feed",
            "raw_value": 2.0,
            "processed_value": 1.0,
            "sentiment": -0.4,
        },
    ])


@pytest.fixture()
def idx():
    return pd.bdate_range("2020-01-01", periods=20, freq="B").tz_localize("UTC")


def test_future_event_cannot_affect_earlier_bars(idx):
    ev = validate_events(make_events(idx))
    links = join_events_asof(idx, ev)
    bar_e1 = links[links["event_id"] == "e1"]["bar_timestamp"]
    assert (bar_e1 >= idx[5]).all()  # no bar before availability sees e1
    bar_e2 = links[links["event_id"] == "e2"]["bar_timestamp"]
    assert (bar_e2 > idx[8]).all()  # e2 available next session, not on idx[8]


def test_after_close_publication_requires_next_session(idx):
    ev = validate_events(make_events(idx))
    # e2 published at session close of idx[8]; usable strictly after idx[8]
    links = join_events_asof(idx, ev)
    assert idx[8] not in set(links[links["event_id"] == "e2"]["bar_timestamp"])
    assert idx[9] in set(links[links["event_id"] == "e2"]["bar_timestamp"])


def test_event_time_before_availability_is_valid(idx):
    ev = make_events(idx)
    ev.loc[0, "availability_time"] = idx[6]  # learned about later - legal
    validate_events(ev)


def test_availability_before_event_rejected_unless_provider_rule(idx):
    ev = make_events(idx)
    ev.loc[0, "availability_time"] = idx[3]  # before event time - illegal
    with pytest.raises(DataValidationError, match="earlier than event_time"):
        validate_events(ev)
    ev["provider_rule_exception"] = True  # explicit documented provider rule
    validate_events(ev)


def test_naive_timestamps_rejected_no_silent_conversion(idx):
    ev = make_events(idx)
    ev["availability_time"] = ev["availability_time"].dt.tz_localize(None)
    with pytest.raises(DataValidationError, match="timezone-naive"):
        validate_events(ev)


def test_missing_availability_rejected_not_immediate_tradability(idx):
    ev = make_events(idx)
    ev.loc[0, "availability_time"] = pd.NaT
    with pytest.raises(DataValidationError):
        validate_events(ev)


def test_publication_before_event_rejected(idx):
    ev = make_events(idx)
    ev.loc[0, "publication_time"] = idx[2]
    with pytest.raises(DataValidationError, match="publication_time"):
        validate_events(ev)


def test_duplicate_event_id_conflicting_value_rejected(idx):
    ev = make_events(idx)
    clash = ev.iloc[[0]].copy()
    clash["raw_value"] = 99.0
    ev2 = pd.concat([ev, clash], ignore_index=True)
    with pytest.raises(DataValidationError, match="versioned"):
        validate_events(ev2)


def test_revised_values_versioned_are_accepted(idx):
    ev = make_events(idx)
    rev = ev.iloc[[0]].copy()
    rev["event_id"] = "e1-rev1"
    rev["raw_value"] = 1.5
    rev["revision"] = 1
    rev["availability_time"] = idx[6]
    validate_events(pd.concat([ev, rev], ignore_index=True))


def test_available_asof_filters_correctly(idx):
    ev = validate_events(make_events(idx))
    early = available_asof(ev, idx[6])
    assert list(early["event_id"]) == ["e1"]
    # e2's availability is idx[8]+1day: not yet usable at idx[8]
    assert set(available_asof(ev, idx[8])["event_id"]) == {"e1"}
    # usable once we are past its availability
    assert set(available_asof(ev, idx[10])["event_id"]) == {"e1", "e2"}


def test_naive_asof_timestamp_rejected(idx):
    ev = validate_events(make_events(idx))
    with pytest.raises(DataValidationError, match="timezone-aware"):
        available_asof(ev, idx[6].tz_localize(None))


def test_deduplication_counts_corroboration_not_independent_evidence(idx):
    ev = make_events(idx)
    syndicated = pd.DataFrame([
        {"event_id": f"s{i}", "symbol": "SPY", "event_time": idx[5],
         "publication_time": idx[5], "availability_time": idx[5],
         "source": f"src{i}", "raw_value": 1.0, "processed_value": 0.5,
         "sentiment": 0.6, "topic": "rates", "corroboration": 1.0}
        for i in range(4)
    ])
    all_ev = pd.concat([ev, syndicated], ignore_index=True)
    dedup = deduplicate_events(all_ev)
    s_ids = set(dedup[dedup["topic"] == "rates"]["event_id"])
    assert len(s_ids) == 1  # one underlying story kept
    kept = dedup[dedup["event_id"].isin(s_ids)].iloc[0]
    assert kept["corroboration"] == 4.0  # 4 feeds, not 4 independent events


def test_information_features_respect_availability(idx):
    ev = validate_events(make_events(idx))
    info = build_information_features(idx, ev, "SPY")
    one_event = float(np.log1p(1))
    # e1 available at idx[5] -> attention starts at idx[5]
    assert info.loc[idx[4], "info_attention"] == 0.0
    assert info.loc[idx[5], "info_attention"] == pytest.approx(one_event)
    # e2 NOT usable at idx[8] (availability idx[8]+1day); only e1 live
    assert info.loc[idx[8], "info_attention"] == pytest.approx(one_event)
    # e2 live by idx[9]: two live events
    assert info.loc[idx[9], "info_attention"] == pytest.approx(float(np.log1p(2)))


def _story_event(eid, available, event_time="2024-01-05", topic="rates",
                 sentiment=1.0):
    return dict(event_id=eid, symbol="SPY",
                event_time=pd.Timestamp(event_time, tz="UTC"),
                publication_time=pd.Timestamp(available, tz="UTC"),
                availability_time=pd.Timestamp(available, tz="UTC"),
                source=eid, raw_value=1.0, processed_value=0.5,
                sentiment=sentiment, novelty=1.0, topic=topic)


def test_corroboration_is_prefix_point_in_time():
    """A01: corroboration is a PIT observation.  A copy available later must
    not change the retained story's corroboration on an earlier bar.  The audit
    reproduction: prefix-only and full-history must agree on 5 January (1)."""
    idx = pd.bdate_range("2024-01-05", periods=10, tz="UTC")
    early = _story_event("early", "2024-01-05T00:00:00Z")
    late = _story_event("late", "2024-01-12T00:00:00Z")  # same underlying story
    a = build_information_features(idx, pd.DataFrame([early]), "SPY")
    b = build_information_features(idx, pd.DataFrame([early, late]), "SPY")
    assert a.iloc[0]["info_corroboration"] == pytest.approx(1.0)
    assert b.iloc[0]["info_corroboration"] == pytest.approx(1.0)
    # once the copy is available, corroboration grows to 2 at the 12 January bar
    jan12 = idx[idx >= pd.Timestamp("2024-01-12", tz="UTC")][0]
    assert b.loc[jan12, "info_corroboration"] == pytest.approx(2.0)


def test_adding_unavailable_event_does_not_change_any_history():
    """A01: prefix-invariance across ALL information columns.  Adding a later
    syndication / delayed publication must leave every feature bit-identical
    on every earlier bar."""
    idx = pd.bdate_range("2024-01-05", periods=10, tz="UTC")
    early = _story_event("early", "2024-01-05T00:00:00Z")
    late_sync = _story_event("late_sync", "2024-01-12T00:00:00Z")  # syndication
    late_delayed = _story_event("late_delayed", "2024-01-15T00:00:00Z",
                                event_time="2024-01-03")  # delayed publication
    from quant_research.features.information import INFO_COLUMNS

    base = build_information_features(idx, pd.DataFrame([early]), "SPY")
    for extra in (late_sync, late_delayed):
        full = build_information_features(
            idx, pd.DataFrame([early, extra]), "SPY")
        # only bars BEFORE the extra's availability are required to match
        av = pd.Timestamp(extra["availability_time"])
        history = idx[idx < av]
        pd.testing.assert_frame_equal(
            base.loc[history, INFO_COLUMNS],
            full.loc[history, INFO_COLUMNS])


def test_weekend_event_decays_from_first_eligible_session():
    """A18: an event available on a weekend/holiday must decay normally from
    the first eligible session, never stay at full intensity forever."""
    idx = pd.bdate_range("2024-01-08", periods=15, tz="UTC")  # starts Monday
    sat = _story_event("sat", "2024-01-06T10:00:00Z", event_time="2024-01-05")
    info = build_information_features(idx, pd.DataFrame([sat]), "SPY",
                                      decay_halflife_bars=5.0)
    first = info.iloc[0]["info_intensity"]
    last = info.iloc[-1]["info_intensity"]
    assert first == pytest.approx(1.0)  # full attention on the first session
    assert last < first  # decays over the 15 business bars
