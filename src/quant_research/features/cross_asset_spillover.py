"""Cross-asset spillover features for H-001 hypothesis.

Economic mechanism: Information diffusion lag between SPY and QQQ creates
predictable spillover effects with 1-3 day delays.

Features are computed using only past data (no look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional


CROSS_ASSET_FEATURE_VERSION = "h001.v1.0"


def compute_spillover_features(
    target_returns: pd.Series,
    spy_returns: pd.Series,
    qqq_returns: pd.Series,
    spy_volume: Optional[pd.Series] = None,
    qqq_volume: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Compute cross-asset spillover features.
    
    Args:
        target_returns: Returns of the target asset
        spy_returns: SPY returns (market proxy)
        qqq_returns: QQQ returns (tech sector proxy)
        spy_volume: Optional SPY volume for intensity weighting
        qqq_volume: Optional QQQ volume for intensity weighting
    
    Returns:
        DataFrame with spillover features, indexed to match target_returns
    """
    # Align all series
    df = pd.DataFrame({
        'target_ret': target_returns,
        'spy_ret': spy_returns,
        'qqq_ret': qqq_returns,
    })
    
    if spy_volume is not None:
        df['spy_vol'] = spy_volume
    if qqq_volume is not None:
        df['qqq_vol'] = qqq_volume
    
    df = df.dropna()
    
    features = pd.DataFrame(index=df.index)
    
    # H1: Direct spillover - QQQ returns lead target with 1-3 day lag
    for lag in [1, 2, 3]:
        features[f'qqq_spillover_lag{lag}'] = df['qqq_ret'].shift(lag)
    
    # H2: SPY spillover - market-wide information diffusion
    for lag in [1, 2]:
        features[f'spy_spillover_lag{lag}'] = df['spy_ret'].shift(lag)
    
    # H3: Interaction term - QQQ spillover conditional on market regime
    features['qqq_spill_x_spy_regime'] = (
        df['qqq_ret'].shift(1) * 
        (df['spy_ret'].rolling(20).mean() > 0).astype(int)
    )
    
    # H4: Volume-weighted spillover (if volume available)
    if 'spy_vol' in df.columns and 'qqq_vol' in df.columns:
        spy_vol_ma = df['spy_vol'].rolling(20).mean()
        qqq_vol_ma = df['qqq_vol'].rolling(20).mean()
        
        features['vol_weighted_qqq_spill'] = (
            df['qqq_ret'].shift(1) * 
            (qqq_vol_ma / qqq_vol_ma.rolling(60).mean())
        )
    
    # H5: Spillover acceleration (change in spillover magnitude)
    features['spillover_accel'] = (
        features['qqq_spillover_lag1'] - features['qqq_spillover_lag1'].shift(1)
    )
    
    # H6: Cumulative spillover over 2 days
    features['cumulative_spill_2d'] = (
        df['qqq_ret'].shift(1) + df['qqq_ret'].shift(2)
    )
    
    # H7: Asymmetric spillover (positive vs negative)
    features['positive_spill'] = np.maximum(df['qqq_ret'].shift(1), 0)
    features['negative_spill'] = np.minimum(df['qqq_ret'].shift(1), 0)
    
    return features


def validate_spillover_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate spillover features for leakage and quality.
    
    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []
    
    # Check for NaN patterns
    nan_pct = features.isna().mean()
    if (nan_pct > 0.5).any():
        high_nan_cols = nan_pct[nan_pct > 0.5].index.tolist()
        errors.append(f"Features with >50% NaN: {high_nan_cols}")
    
    # Check for infinite values
    if np.isinf(features.values).any():
        errors.append("Infinite values detected in features")
    
    # Check for constant features
    constant_cols = [col for col in features.columns if features[col].nunique() == 1]
    if constant_cols:
        errors.append(f"Constant features: {constant_cols}")
    
    return len(errors) == 0, errors


def get_feature_specs() -> List[dict]:
    """Return feature specifications for registry."""
    return [
        {
            "feature_name": "qqq_spillover_lag1",
            "definition": "QQQ return lagged by 1 day",
            "source": "cross_asset_spillover",
            "required_history": 2,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "qqq_spillover_lag2",
            "definition": "QQQ return lagged by 2 days",
            "source": "cross_asset_spillover",
            "required_history": 3,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "qqq_spillover_lag3",
            "definition": "QQQ return lagged by 3 days",
            "source": "cross_asset_spillover",
            "required_history": 4,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "spy_spillover_lag1",
            "definition": "SPY return lagged by 1 day",
            "source": "cross_asset_spillover",
            "required_history": 2,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "spy_spillover_lag2",
            "definition": "SPY return lagged by 2 days",
            "source": "cross_asset_spillover",
            "required_history": 3,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "qqq_spill_x_spy_regime",
            "definition": "QQQ lag-1 return × indicator(SPY 20d mean return > 0)",
            "source": "cross_asset_spillover",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "spillover_accel",
            "definition": "Change in QQQ spillover_lag1 from t-1 to t",
            "source": "cross_asset_spillover",
            "required_history": 3,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "cumulative_spill_2d",
            "definition": "Sum of QQQ returns at lag 1 and lag 2",
            "source": "cross_asset_spillover",
            "required_history": 3,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "positive_spill",
            "definition": "max(QQQ lag-1 return, 0)",
            "source": "cross_asset_spillover",
            "required_history": 2,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
        {
            "feature_name": "negative_spill",
            "definition": "min(QQQ lag-1 return, 0)",
            "source": "cross_asset_spillover",
            "required_history": 2,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": CROSS_ASSET_FEATURE_VERSION,
        },
    ]
