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

from .price_volume import build_price_volume_features
from .information import build_information_features


def _split(n: int) -> int:
    return n // 2


def _perturb(close, volume, target: str, perturb_close: bool, perturb_volume: bool,
             columns=None, seed: int = 7) -> tuple:
    """Build features before/after perturbing only FUTURE observations."""
    feats_before = build_price_volume_features(close, volume, target)
    n = len(close)
    split = _split(n)
    close2 = close.copy()
    volume2 = volume.copy()
    rng = np.random.default_rng(seed)
    cols = columns if columns is not None else list(close.columns)
    if perturb_close:
        close2.loc[close2.index[split:], cols] *= (
            1 + rng.normal(0, 0.05, (n - split, len(cols)))
        )
    if perturb_volume:
        volume2.loc[volume2.index[split:], cols] *= (
            rng.lognormal(0, 0.5, (n - split, len(cols)))
        )
    feats_after = build_price_volume_features(close2, volume2, target)
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


def feature_leakage_report(
    close: pd.DataFrame, volume: pd.DataFrame, target: str,
    info_events: pd.DataFrame | None = None,
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
                          columns=list(close.columns), seed=seed)
    dims["future_price"] = _history_delta(fb, fa, sp)

    # 2. future volume perturbation
    fb, fa, sp = _perturb(close, volume, target, False, True,
                          columns=list(volume.columns), seed=seed)
    dims["future_volume"] = _history_delta(fb, fa, sp)

    # 3. future cross-asset price perturbation (non-target assets only)
    if non_target:
        fb, fa, sp = _perturb(close, volume, target, True, False,
                              columns=non_target, seed=seed)
        dims["future_cross_asset_price"] = _history_delta(fb, fa, sp)
    else:
        dims["future_cross_asset_price"] = 0.0

    # 4. future target-asset price perturbation (target column only)
    fb, fa, sp = _perturb(close, volume, target, True, False,
                          columns=[target], seed=seed)
    dims["future_target_price"] = _history_delta(fb, fa, sp)

    # 5. future information-event perturbation (only when events supplied)
    if info_events is not None and len(info_events):
        info_report = _info_event_perturbation(close.index, info_events, target, seed=seed)
        dims["future_information_event"] = info_report["max_abs_delta_history"]
    else:
        info_report = {"key": "information_event", "split_ts": None,
                       "max_abs_delta_history": 0.0, "passed": True}
        dims["future_information_event"] = 0.0

    max_delta = max(dims.values()) if dims else 0.0
    passed = bool(max_delta < 1e-12)  # strict: untouched history must be bit-identical
    return {
        "checked_rows": int(split),
        "max_abs_delta_history": float(max_delta),
        "dimensions": dims,
        "information_event": info_report,
        "passed": passed,
        "detail": "features on unchanged history identical under future-data perturbation",
    }
