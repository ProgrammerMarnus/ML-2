"""Automated feature-leakage checks.

Property test: features at bar t must not change when market/information data
AFTER t changes.  Applied on every research run as an integrity gate.

Covers, independently:
- future target-asset price perturbation
- future volume perturbation
- future cross-asset price perturbation (non-target assets only)
- future target perturbation via the label/price panel
- future information-event perturbation (when events are supplied)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .price_volume import build_price_volume_features, build_signal_extensions
from .information import build_information_features


def _split(n: int) -> int:
    return n // 2


def _build_full_panel(close, volume, target: str, open_=None, high=None, low=None):
    """Legacy price/volume panel joined with signal extensions when OHLC given."""
    feats = build_price_volume_features(close, volume, target)
    if open_ is not None and high is not None and low is not None:
        feats = feats.join(build_signal_extensions(open_, high, low, close, volume, target))
    return feats


def _perturb(close, volume, target: str, perturb_close: bool, perturb_volume: bool,
             columns=None, seed: int = 7, open_=None, high=None, low=None) -> tuple:
    """Build features before/after perturbing only FUTURE observations."""
    feats_before = _build_full_panel(close, volume, target, open_, high, low)
    n = len(close)
    split = _split(n)
    close2 = close.copy()
    volume2 = volume.copy()
    open2 = open_.copy() if open_ is not None else None
    high2 = high.copy() if high is not None else None
    low2 = low.copy() if low is not None else None
    rng = np.random.default_rng(seed)
    cols = columns if columns is not None else list(close.columns)
    if perturb_close:
        pert = 1 + rng.normal(0, 0.05, (n - split, len(cols)))
        close2.loc[close2.index[split:], cols] *= pert
        # OHLC-derived features depend on open/high/low too; perturb them only
        # when the price perturbation is active so the leak check covers them.
        if open2 is not None:
            open2.loc[open2.index[split:], cols] *= pert
            high2.loc[high2.index[split:], cols] *= pert
            low2.loc[low2.index[split:], cols] *= pert
    if perturb_volume:
        volume2.loc[volume2.index[split:], cols] *= (
            rng.lognormal(0, 0.5, (n - split, len(cols)))
        )
    feats_after = _build_full_panel(close2, volume2, target, open2, high2, low2)
    return feats_before, feats_after, split


def _history_delta(feats_before, feats_after, split) -> float:
    history = feats_before.index[:split]
    delta = (feats_before.loc[history] - feats_after.loc[history]).abs()
    return float(np.nanmax(delta.to_numpy())) if delta.size else 0.0


def _info_event_perturbation(bars_index, events, symbol, seed: int = 7) -> dict:
    """Perturb FUTURE events (sentiment flipped + availability pushed forward).

    Perturbation is confined to events at/after the split point; availability
    is only ever pushed forward, never backward, so no perturbed event can
    retroactively become usable in the past.
    """
    feats_before = build_information_features(bars_index, events, symbol)
    split_ts = bars_index[_split(len(bars_index))]
    ev2 = events.copy()
    rng = np.random.default_rng(seed)
    future = pd.to_datetime(ev2["event_time"], utc=True) >= split_ts
    if "sentiment" in ev2.columns and future.any():
        ev2.loc[future, "sentiment"] = -pd.to_numeric(
            ev2.loc[future, "sentiment"], errors="coerce"
        )
    # push availability/publication strictly forward for future events only
    for col in ("availability_time", "publication_time"):
        if col in ev2.columns and future.any():
            ev2.loc[future, col] = pd.to_datetime(
                ev2.loc[future, col], utc=True
            ) + pd.Timedelta(days=1)
    feats_after = build_information_features(bars_index, ev2, symbol)
    split = _split(len(bars_index))
    history = feats_before.index[:split]
    delta = (feats_before.loc[history] - feats_after.loc[history]).abs()
    max_delta = float(np.nanmax(delta.to_numpy())) if delta.size else 0.0
    return {"key": "information_event", "split_ts": split_ts,
            "max_abs_delta_history": max_delta, "passed": bool(max_delta < 1e-12)}


def _info_event_membership_perturbation(bars_index, events, symbol,
                                        seed: int = 7) -> dict:
    """PREFIX-INVARIANCE (A01): ADDING or REMOVING a future event must not change
    historical features.  This is the exact gap the audit identified: the classic
    perturbation flips a future event's *content*, but a later SYNDICATION /
    delayed publication about an old topic is a membership change that the
    old global pre-dedup pipeline leaked into history.
    """
    feats_base = build_information_features(bars_index, events, symbol)
    split = _split(len(bars_index))
    split_ts = bars_index[split]
    history = feats_base.index[:split]
    if feats_base.size == 0:
        return {"max_abs_delta_history": 0.0, "passed": True}
    rng = np.random.default_rng(seed)

    # (a) ADD a brand-new future event (never available in the history)
    future_ts = split_ts + pd.Timedelta(days=1)
    extra = _synthetic_event("added-future-a01", symbol, future_ts, rng)
    ev_add = pd.concat([events.copy(), pd.DataFrame([extra])], ignore_index=True)
    feats_add = build_information_features(bars_index, ev_add, symbol)
    d_add = float(np.nanmax(_history_delta(feats_base, feats_add, split))) \
        if history.size else 0.0

    # (b) REMOVE all currently-FUTURE events (availability at/after split --
    #     the PIT-relevant future notion, matching the audit's complaint that a
    #     late publication about an OLD event escapes an event_time mask)
    d_remove = 0.0
    if events is not None and len(events):
        future_av = pd.to_datetime(events["availability_time"], utc=True) >= split_ts
        if future_av.any():
            ev_rm = events.loc[~future_av]
            feats_rm = build_information_features(bars_index, ev_rm, symbol)
            d_remove = float(np.nanmax(_history_delta(feats_base, feats_rm, split)))
    max_delta = max(d_add, d_remove)
    return {"max_abs_delta_history": max_delta, "passed": bool(max_delta < 1e-12)}


def _synthetic_event(eid, symbol, ts, rng) -> dict:
    """A schema-valid event for membership perturbations."""
    return dict(
        event_id=eid, symbol=symbol,
        event_time=ts, publication_time=ts, availability_time=ts,
        source="a01-probe", raw_value=1.0, processed_value=0.5,
        sentiment=float(rng.normal(0, 0.5)), novelty=1.0, topic="a01_topic",
    )


def feature_leakage_report(
    close: pd.DataFrame, volume: pd.DataFrame, target: str,
    info_events: pd.DataFrame | None = None,
    open_: pd.DataFrame | None = None, high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
) -> dict:
    """Perturb future data; earlier features must be unchanged.

    Returns structured report with per-dimension deltas, aggregate max,
    checked rows, and an overall pass flag.  A failure indicates future
    information entering feature construction.
    """
    if not isinstance(close.index, pd.DatetimeIndex):
        raise TypeError("close.index must be a DatetimeIndex")
    n = len(close)
    split = _split(n)
    non_target = [c for c in close.columns if c != target]
    seed = 7

    dims = {}

    # 1. future price perturbation (all assets) - legacy behavior
    fb, fa, sp = _perturb(close, volume, target, True, False,
                          columns=list(close.columns), seed=seed,
                          open_=open_, high=high, low=low)
    dims["future_price"] = _history_delta(fb, fa, sp)
    if open_ is not None:
        dims["future_ohlc_extensions"] = dims["future_price"]

    # 2. future volume perturbation
    fb, fa, sp = _perturb(close, volume, target, False, True,
                          columns=list(volume.columns), seed=seed,
                          open_=open_, high=high, low=low)
    dims["future_volume"] = _history_delta(fb, fa, sp)

    # 3. future cross-asset price perturbation (non-target assets only)
    if non_target:
        fb, fa, sp = _perturb(close, volume, target, True, False,
                              columns=non_target, seed=seed,
                              open_=open_, high=high, low=low)
        dims["future_cross_asset_price"] = _history_delta(fb, fa, sp)
    else:
        dims["future_cross_asset_price"] = 0.0

    # 4. future target-asset price perturbation (target column only)
    fb, fa, sp = _perturb(close, volume, target, True, False,
                          columns=[target], seed=seed,
                          open_=open_, high=high, low=low)
    dims["future_target_price"] = _history_delta(fb, fa, sp)

    # 5. future information-event perturbation (only when events supplied)
    if info_events is not None and len(info_events):
        info_report = _info_event_perturbation(close.index, info_events, target, seed=seed)
        dims["future_information_event"] = info_report["max_abs_delta_history"]
    else:
        info_report = {"key": "information_event", "split_ts": None,
                       "max_abs_delta_history": 0.0, "passed": True}
        dims["future_information_event"] = 0.0

    # 5b. PREFIX-INVARIANCE: adding/removing a future event must not change
    # history (A01).  Always checked when events are supplied; a schema-valid
    # synthetic future event is used when the supplied set has none.
    if info_events is not None and len(info_events):
        membership = _info_event_membership_perturbation(
            close.index, info_events, target, seed=seed + 999)
        dims["future_information_event_membership"] = membership["max_abs_delta_history"]
    else:
        membership = {"max_abs_delta_history": 0.0, "passed": True}
        dims["future_information_event_membership"] = 0.0

    max_delta = max(dims.values()) if dims else 0.0
    passed = bool(max_delta < 1e-12)  # strict: untouched history must be bit-identical
    return {
        "checked_rows": int(split),
        "max_abs_delta_history": float(max_delta),
        "dimensions": dims,
        "information_event": info_report,
        "information_event_membership": membership,
        "passed": passed,
        "detail": "features on unchanged history identical under future-data perturbation",
    }
