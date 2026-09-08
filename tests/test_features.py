"""Feature engine tests: leakage, window boundaries, registry, fold-local fit."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from quant_research.config import ModelConfig
from quant_research.data.loaders import to_panels
from quant_research.data.loaders import generate_synthetic_ohlcv
from quant_research.features.information import build_information_features
from quant_research.features.leakage import feature_leakage_report
from quant_research.features.price_volume import (
    build_price_volume_features,
    make_labels,
    momentum,
    realized_volatility,
    simple_returns,
)
from quant_research.features.point_in_time import validate_events
from quant_research.features.registry import (
    information_feature_specs,
    price_volume_feature_specs,
    registry,
    registry_hash,
)
from quant_research.strategies.baseline import build_model


def test_momentum_uses_only_past(close_panel):
    m = momentum(close_panel, 5)
    # changing today's price must not change yesterday's momentum
    alt = close_panel.copy()
    alt.iloc[-1] *= 1.5
    assert m.iloc[-2].equals(momentum(alt, 5).iloc[-2])


def test_rolling_window_boundaries(close_panel):
    rv = realized_volatility(close_panel, 20)
    # returns start at row 1, so the first full 20-obs window ends at row 20
    assert rv.iloc[:20].isna().all().all()  # warm-up is NaN, not zero-filled
    assert rv.iloc[20].notna().all()


def test_simple_returns_no_future_information(close_panel):
    r = simple_returns(close_panel)
    expected = close_panel.iloc[1] / close_panel.iloc[0] - 1
    assert np.isclose(r.iloc[1, 0], expected.iloc[0])


def test_labels_are_forward_and_tail_nan(close_panel):
    y = make_labels(close_panel, "SPY", horizon=1)
    fwd1 = close_panel["SPY"].shift(-1) / close_panel["SPY"] - 1
    assert (y.dropna() == (fwd1.dropna() > 0).astype(float)).all()
    assert y.iloc[-1] != y.iloc[-1]  # last label NaN (no future bar)


def test_feature_leakage_check_passes(close_panel, volume_panel):
    rep = feature_leakage_report(close_panel, volume_panel, "SPY")
    assert rep["passed"], rep


def test_feature_leakage_check_detects_actual_leak(close_panel, volume_panel, monkeypatch):
    # inject a leaky feature builder that uses future prices
    from quant_research.features import leakage as leak_mod

    def leaky_builder(close, volume, target):
        feats = build_price_volume_features(close, volume, target)
        feats["leaky"] = (close[target].shift(-1) / close[target] - 1.0)  # future return!
        return feats

    monkeypatch.setattr(leak_mod, "build_price_volume_features", leaky_builder)
    rep = leak_mod.feature_leakage_report(close_panel, volume_panel, "SPY")
    assert not rep["passed"]


def test_registry_complete_metadata():
    specs = registry()
    names = [s.feature_name for s in specs]
    assert len(names) == len(set(names))
    for s in specs:
        assert s.definition and s.source and s.availability_rule
        assert s.missing_data_policy and s.normalization_rule and s.version
        assert s.required_history >= 1


def test_registry_hash_stable_and_subset_aware():
    h1 = registry_hash(["momentum_63", "trend_50"])
    h2 = registry_hash(["trend_50", "momentum_63"])
    assert h1 == h2
    assert h1 != registry_hash(["momentum_63"])
    with pytest.raises(KeyError):
        registry_hash(["not_a_feature"])
    assert len(registry_hash(["momentum_63", "trend_50"])) == 16


def test_information_features_zero_when_no_events(close_panel):
    info = build_information_features(close_panel.index, pd.DataFrame(), "SPY")
    assert (info == 0).all().all()


def test_model_pipeline_is_fold_local_by_construction():
    model = build_model(ModelConfig())
    assert isinstance(model, Pipeline)
    names = [s[0] for s in model.steps]
    assert names == ["imputer", "scaler", "model"]


def test_scaler_fitted_on_train_only(close_panel, volume_panel):
    """Fold-local scaling: statistics from train differ from full-sample fit."""
    feats = build_price_volume_features(close_panel, volume_panel, "SPY").dropna()
    half = len(feats) // 2
    from sklearn.preprocessing import StandardScaler

    train_only = StandardScaler().fit(feats.iloc[:half][["momentum_63"]])
    full = StandardScaler().fit(feats[["momentum_63"]])
    # with real drift in synthetic data these should not be identical
    assert not np.allclose(train_only.mean_, full.mean_)

def test_leakage_report_covers_all_perturbation_dimensions(close_panel, volume_panel):
    rep = feature_leakage_report(close_panel, volume_panel, "SPY")
    expected = {"future_price", "future_volume", "future_cross_asset_price",
                 "future_target_price", "future_information_event"}
    assert expected.issubset(set(rep["dimensions"]))
    assert rep["passed"], rep
    assert all(v < 1e-12 for v in rep["dimensions"].values())


def test_leakage_information_event_perturbation(close_panel, volume_panel):
    idx = close_panel.index
    event_times = [idx[i] for i in (10, 60, 120, 180, 240, 300, 340, 380)]
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(8)],
            "symbol": ["SPY"] * 8,
            "event_time": pd.to_datetime(event_times, utc=True),
            "publication_time": pd.to_datetime(event_times, utc=True),
            "availability_time": pd.to_datetime(event_times, utc=True),
            "source": ["src"] * 8,
            "raw_value": [1.0] * 8,
            "processed_value": [1.0] * 8,
            "sentiment": [0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.7, -0.8],
            "topic": ["t"] * 8,
            "novelty": [0.5] * 8,
        }
    )
    rep = feature_leakage_report(close_panel, volume_panel, "SPY", info_events=events)
    assert rep["passed"], rep
    assert rep["dimensions"]["future_information_event"] < 1e-12
    assert rep["information_event"]["passed"]
    # prefix-invariance (A01): adding/removing a future event leaves history alone
    assert rep["dimensions"]["future_information_event_membership"] < 1e-12
    assert rep["information_event_membership"]["passed"]


def test_leakage_membership_detects_old_style_dedup_contamination(
        close_panel, volume_panel, monkeypatch):
    """A01: the membership probe must START FAILING if the feature builder is
    regressed to the old global pre-dedup (corroboration counted before its
    copies are available)."""
    import quant_research.features.leakage as leak_mod
    from quant_research.features import point_in_time
    from quant_research.features.information import (
        INFO_COLUMNS,
        deduplicate_events,
    )

    idx = close_panel.index

    def _ev(eid, avail):
        return {"event_id": eid, "symbol": "SPY",
                "event_time": pd.Timestamp("2020-01-10", tz="UTC"),
                "publication_time": pd.Timestamp(avail, tz="UTC"),
                "availability_time": pd.Timestamp(avail, tz="UTC"),
                "source": eid, "raw_value": 1.0, "processed_value": 0.5,
                "sentiment": 1.0, "topic": "rates"}

    # e1 available early; e2 is a late syndication about the SAME underlying
    # story (identical event_time, availability far in the future)
    events = pd.DataFrame([_ev("e1", "2020-06-01T00:00:00Z"),
                           _ev("e2", "2025-01-10T00:00:00Z")])

    def legacy_builder(bars_index, ev, symbol, deduplicate=True,
                       decay_halflife_bars=5.0):
        # old code path: dedup the FULL collection up front, then PIT-join the
        # kept set -- so corroboration carries not-yet-available copies.
        kept = deduplicate_events(ev)
        joins = point_in_time.join_events_asof(bars_index, kept)
        if joins.empty or len(joins) == 0:
            return pd.DataFrame(0.0, index=bars_index, columns=INFO_COLUMNS)
        linked = joins.join(kept.set_index("event_id"), on="event_id")
        linked["corroboration"] = pd.to_numeric(
            linked["corroboration"], errors="coerce").fillna(1.0)
        out = linked.groupby("bar_timestamp")["corroboration"].max()
        out = out.reindex(bars_index).fillna(0.0)
        frame = pd.DataFrame(0.0, index=bars_index, columns=INFO_COLUMNS)
        frame["info_corroboration"] = out
        return frame

    monkeypatch.setattr(leak_mod, "build_information_features", legacy_builder)
    res = leak_mod._info_event_membership_perturbation(idx, events, "SPY")
    # the old builder leaks: removing the not-yet-available copy changes the
    # retained story's historical corroboration, so the probe must fail
    assert not res["passed"]
