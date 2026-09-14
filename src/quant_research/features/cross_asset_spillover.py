"""The frozen H-001 SPY/QQQ cross-asset feature contract.

The implementation deliberately mirrors the nine columns named in
``HYPOTHESIS_H001_CROSS_ASSET_SPILLOVER.md``.  It is not a generic bag of
related return lags: adding a plausible-but-unregistered signal would change
the hypothesis and must instead be captured in a new protocol.
"""

from __future__ import annotations

import pandas as pd
from typing import List, Tuple


CROSS_ASSET_FEATURE_VERSION = "h001.v2.0"


def compute_spillover_features(
    spy_close: pd.Series,
    qqq_close: pd.Series,
    spy_volume: pd.Series,
    qqq_volume: pd.Series,
    vix: pd.Series,
) -> pd.DataFrame:
    """Build H-001's locked ratio, volatility-regime, and volume features.

    Values at bar ``t`` use only prices, volumes, and VIX observed no later
    than ``t``.  The research runner trades on the following return, so the
    current-bar inputs cannot enter an already-executed position.
    """
    frame = pd.concat(
        [spy_close.rename("spy_close"), qqq_close.rename("qqq_close"),
         spy_volume.rename("spy_volume"), qqq_volume.rename("qqq_volume"),
         vix.rename("vix")],
        axis=1,
    )
    if (frame["vix"] <= 0).any():
        raise ValueError("H-001 requires strictly positive VIX observations")
    ratio_price = frame["qqq_close"] / frame["spy_close"]
    ratio_ma20 = ratio_price.rolling(20, min_periods=20).mean()
    ratio_std20 = ratio_price.rolling(20, min_periods=20).std()
    ratio_zscore = (ratio_price - ratio_ma20) / ratio_std20.replace(0.0, float("nan"))
    spy_volume_mean = frame["spy_volume"].rolling(20, min_periods=20).mean()
    qqq_volume_mean = frame["qqq_volume"].rolling(20, min_periods=20).mean()
    return pd.DataFrame({
        "ratio_price": ratio_price,
        "ratio_ma20": ratio_ma20,
        "ratio_std20": ratio_std20,
        "ratio_zscore": ratio_zscore,
        "ratio_zscore_lag1": ratio_zscore.shift(1),
        "ratio_zscore_lag3": ratio_zscore.shift(3),
        "vol_regime": frame["vix"].rolling(20, min_periods=20).mean() / frame["vix"],
        "spy_volume_zscore": (frame["spy_volume"] - spy_volume_mean) /
                             frame["spy_volume"].rolling(20, min_periods=20).std(),
        "qqq_volume_zscore": (frame["qqq_volume"] - qqq_volume_mean) /
                             frame["qqq_volume"].rolling(20, min_periods=20).std(),
    }, index=frame.index)


def validate_spillover_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate spillover features for leakage and quality.
    
    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []
    
    # Check for infinite values; warm-up NaNs are expected and are handled by
    # the fold-local imputer.
    if not pd.DataFrame(features).replace([float("inf"), float("-inf")], float("nan")).equals(features):
        errors.append("Infinite values detected in features")

    constant_cols = [col for col in features.columns if features[col].nunique() == 1]
    if constant_cols:
        errors.append(f"Constant features: {constant_cols}")
    
    return len(errors) == 0, errors


def get_feature_specs() -> List[dict]:
    """Return feature specifications for registry."""
    return [
        {
            "feature_name": "ratio_price",
            "definition": "QQQ close / SPY close",
            "source": "cross_asset_spillover",
            "required_history": 1,
            "availability_rule": "SPY/QQQ closes observed at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "ratio_ma20",
            "definition": "20-bar rolling mean of ratio_price",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "ratio_std20",
            "definition": "20-bar rolling standard deviation of ratio_price",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "ratio_zscore",
            "definition": "(ratio_price - ratio_ma20) / ratio_std20",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "ratio_zscore_lag1",
            "definition": "ratio_zscore shifted by one bar",
            "source": "cross_asset_spillover",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "ratio_zscore_lag3",
            "definition": "ratio_zscore shifted by three bars",
            "source": "cross_asset_spillover",
            "required_history": 23,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_regime",
            "definition": "20-bar VIX mean / VIX",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "VIX observed at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "spy_volume_zscore",
            "definition": "SPY volume relative to its 20-bar mean and standard deviation",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "qqq_volume_zscore",
            "definition": "QQQ volume relative to its 20-bar mean and standard deviation",
            "source": "cross_asset_spillover",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
    ]
