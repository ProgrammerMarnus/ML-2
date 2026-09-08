"""Pure, testable price/volume feature builders.

Every feature uses only data at or before bar t (rolling windows ending at t,
inclusive).  No future returns, no global normalization: standardization
happens fold-locally inside the model pipeline, never here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.validation import validate_wide_panel

FEATURE_VERSION = "pv-2.1.0"


def simple_returns(close: pd.DataFrame) -> pd.DataFrame:
    return close / close.shift(1) - 1.0


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    return np.log(close / close.shift(1))


def momentum(close: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Trailing multi-period return over `window` bars (uses only past data)."""
    return close / close.shift(window) - 1.0


def trend(close: pd.DataFrame, window: int = 50) -> pd.DataFrame:
    """Price relative to its `window`-bar simple moving average."""
    sma = close.rolling(window, min_periods=window).mean()
    return close / sma - 1.0


def mean_reversion(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Negative z-score of recent returns (short-horizon reversal)."""
    rets = simple_returns(close)
    mu = rets.rolling(window, min_periods=window).mean()
    sd = rets.rolling(window, min_periods=window).std()
    z = (rets - mu) / sd.replace(0.0, np.nan)
    return -z


def realized_volatility(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Annualized rolling standard deviation of daily returns."""
    rets = simple_returns(close)
    return rets.rolling(window, min_periods=window).std() * np.sqrt(252.0)


def volatility_ratio(close: pd.DataFrame, short: int = 10, long: int = 60) -> pd.DataFrame:
    """Short-window volatility divided by long-window volatility (regime proxy)."""
    return realized_volatility(close, short) / realized_volatility(close, long)


def volume_zscore(volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Rolling z-score of volume against its own history only."""
    mu = volume.rolling(window, min_periods=window).mean()
    sd = volume.rolling(window, min_periods=window).std()
    return (volume - mu) / sd.replace(0.0, np.nan)


def dollar_volume(close: pd.DataFrame, volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Log average dollar volume (liquidity proxy)."""
    dv = (close * volume).rolling(window, min_periods=window).mean()
    return np.log(dv.where(dv > 0))


def cross_asset_relative_strength(close: pd.DataFrame, target: str) -> pd.DataFrame:
    """Target return minus equal-weight universe return (cross-asset relationship)."""
    rets = simple_returns(close)
    universe_mean = rets.mean(axis=1)
    return rets[target] - universe_mean


def market_regime(close: pd.DataFrame, target: str, window: int = 60) -> pd.DataFrame:
    """Regime features: benchmark drawdown and high-volatility flag.

    Both computed causally from trailing data at each bar.
    """
    bench = close[target]
    roll_max = bench.rolling(window, min_periods=window).max()
    drawdown = bench / roll_max - 1.0
    vol = realized_volatility(close, window=window)[target]
    vol_median = vol.rolling(252, min_periods=window).median()
    high_vol = (vol > vol_median).astype(float)
    out = pd.DataFrame(
        {
            "regime_drawdown": drawdown,
            "regime_high_vol": high_vol,
        },
        index=close.index,
    )
    return out


def build_price_volume_features(
    close: pd.DataFrame, volume: pd.DataFrame, target: str
) -> pd.DataFrame:
    """Assemble the baseline price/volume feature panel for `target`."""
    validate_wide_panel(close, "close")
    validate_wide_panel(volume, "volume", allow_zero=True)
    if target not in close.columns:
        raise KeyError(f"target {target!r} not in close panel")

    parts = {
        "momentum_63": momentum(close, 63)[target],
        "momentum_252": momentum(close, 252)[target],
        "trend_50": trend(close, 50)[target],
        "mean_reversion_20": mean_reversion(close, 20)[target],
        "realized_vol_20": realized_volatility(close, 20)[target],
        "volatility_ratio_10_60": volatility_ratio(close, 10, 60)[target],
        "volume_zscore_20": volume_zscore(volume, 20)[target],
        "log_dollar_volume_20": dollar_volume(close, volume, 20)[target],
        "cross_asset_rel_strength": cross_asset_relative_strength(close, target),
    }
    regime = market_regime(close, target)
    parts["regime_drawdown"] = regime["regime_drawdown"]
    parts["regime_high_vol"] = regime["regime_high_vol"]

    feats = pd.DataFrame(parts, index=close.index).sort_index()
    # Warm-up NaNs from window boundaries are expected and handled by the
    # fold-local imputer; they are never filled with future/global data here.
    return feats


def make_labels(close: pd.DataFrame, target: str, horizon: int = 1) -> pd.Series:
    """Forward-return label: 1 if next `horizon`-bar return > 0, else 0.

    Labels at bar t use returns AFTER t - they are targets, never features.
    The last `horizon` bars have undefined labels (NaN).
    """
    fwd = close[target].shift(-horizon) / close[target] - 1.0
    label = pd.Series(np.nan, index=close.index)
    label[fwd.notna()] = (fwd[fwd.notna()] > 0).astype(float)
    return label
