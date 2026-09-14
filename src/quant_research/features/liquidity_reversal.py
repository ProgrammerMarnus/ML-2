"""Liquidity reversal features for H-002 hypothesis.

Economic mechanism: Liquidity imbalances in small-cap stocks create temporary
price pressure that reverses over 1-5 day horizons as liquidity providers
step in to absorb the imbalance.

Features are computed using only past data (no look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional


LIQUIDITY_FEATURE_VERSION = "h002.v1.0"


def compute_liquidity_features(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    dollar_volume: Optional[pd.Series] = None,
    market_cap: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Compute liquidity reversal features.
    
    Args:
        high: Daily high prices
        low: Daily low prices
        close: Daily close prices
        volume: Daily volume
        dollar_volume: Optional pre-computed dollar volume (close * volume)
        market_cap: Optional market cap for scaling
    
    Returns:
        DataFrame with liquidity features, indexed to match input
    """
    # Compute dollar volume if not provided
    if dollar_volume is None:
        dollar_volume = close * volume
    
    df = pd.DataFrame({
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'dollar_volume': dollar_volume,
    })
    
    if market_cap is not None:
        df['market_cap'] = market_cap
    
    df = df.dropna()
    
    features = pd.DataFrame(index=df.index)
    
    # H1: Amihud illiquidity - price impact per dollar of volume
    daily_ret = df['close'].pct_change()
    features['amihud_1d'] = (daily_ret.abs() / df['dollar_volume']).rolling(1).mean()
    features['amihud_5d'] = (daily_ret.abs() / df['dollar_volume']).rolling(5).mean()
    features['amihud_20d'] = (daily_ret.abs() / df['dollar_volume']).rolling(20).mean()
    
    # H2: Volume imbalance - signed volume relative to recent average
    ret_sign = np.sign(daily_ret)
    signed_volume = ret_sign * df['volume']
    vol_ma20 = df['volume'].rolling(20).mean()
    features['volume_imbalance'] = signed_volume / vol_ma20
    
    # H3: Liquidity shock - sudden increase in volume
    vol_std20 = df['volume'].rolling(20).std()
    features['volume_shock'] = (df['volume'] - vol_ma20) / vol_std20
    
    # H4: Price pressure - extreme returns on high volume
    ret_std20 = daily_ret.rolling(20).std()
    features['price_pressure'] = (daily_ret / ret_std20) * (df['volume'] / vol_ma20)
    
    # H5: Reversal signal - lagged price pressure predicts reversal
    features['lagged_pressure_1d'] = features['price_pressure'].shift(1)
    features['lagged_pressure_2d'] = features['price_pressure'].shift(2)
    features['lagged_pressure_3d'] = features['price_pressure'].shift(3)
    
    # H6: Liquidity dry-up - declining volume trend
    vol_ma5 = df['volume'].rolling(5).mean()
    vol_ma20 = df['volume'].rolling(20).mean()
    features['liquidity_ratio'] = vol_ma5 / vol_ma20
    
    # H7: Turnover rate (if market cap available)
    if 'market_cap' in df.columns:
        features['turnover'] = df['dollar_volume'] / df['market_cap']
        features['turnover_5d'] = features['turnover'].rolling(5).mean()
    
    # H8: Bid-ask spread proxy (using high-low range)
    log_range = np.log(df['high'] / df['low'])
    features['spread_proxy'] = log_range.rolling(5).mean()
    
    # H9: Effective spread (Kyle's lambda proxy)
    cum_vol = df['volume'].rolling(5).sum()
    cum_ret = daily_ret.rolling(5).sum()
    features['kyles_lambda'] = cum_ret.abs() / cum_vol
    
    # H10: Liquidity innovation - unexpected liquidity
    liq_ma = features['amihud_5d'].rolling(20).mean()
    liq_std = features['amihud_5d'].rolling(20).std()
    features['liquidity_innovation'] = (features['amihud_5d'] - liq_ma) / liq_std
    
    return features


def validate_liquidity_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate liquidity features for leakage and quality.
    
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
        inf_mask = np.isinf(features.values)
        inf_cols = features.columns[inf_mask.any(axis=0)].tolist()
        errors.append(f"Infinite values in: {inf_cols}")
    
    # Check for constant features
    constant_cols = [col for col in features.columns if features[col].nunique() == 1]
    if constant_cols:
        errors.append(f"Constant features: {constant_cols}")
    
    # Check for extreme outliers (>10 std)
    for col in features.columns:
        col_data = features[col].dropna()
        if len(col_data) > 10:
            mean = col_data.mean()
            std = col_data.std()
            if std > 0:
                z_scores = (col_data - mean).abs() / std
                if (z_scores > 10).any():
                    errors.append(f"Extreme outliers in {col}")
    
    return len(errors) == 0, errors


def get_feature_specs() -> List[dict]:
    """Return feature specifications for registry."""
    return [
        {
            "feature_name": "amihud_1d",
            "definition": "1-day rolling mean of |return| / dollar_volume",
            "source": "liquidity_reversal",
            "required_history": 2,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "amihud_5d",
            "definition": "5-day rolling mean of |return| / dollar_volume",
            "source": "liquidity_reversal",
            "required_history": 6,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "amihud_20d",
            "definition": "20-day rolling mean of |return| / dollar_volume",
            "source": "liquidity_reversal",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "volume_imbalance",
            "definition": "sign(return) * volume / 20-day volume MA",
            "source": "liquidity_reversal",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "volume_shock",
            "definition": "(volume - 20d MA) / 20d std",
            "source": "liquidity_reversal",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "price_pressure",
            "definition": "(return / 20d std) * (volume / 20d MA)",
            "source": "liquidity_reversal",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "lagged_pressure_1d",
            "definition": "price_pressure shifted by 1 day",
            "source": "liquidity_reversal",
            "required_history": 22,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "lagged_pressure_2d",
            "definition": "price_pressure shifted by 2 days",
            "source": "liquidity_reversal",
            "required_history": 23,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "lagged_pressure_3d",
            "definition": "price_pressure shifted by 3 days",
            "source": "liquidity_reversal",
            "required_history": 24,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "liquidity_ratio",
            "definition": "5-day volume MA / 20-day volume MA",
            "source": "liquidity_reversal",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "spread_proxy",
            "definition": "5-day mean of log(high/low)",
            "source": "liquidity_reversal",
            "required_history": 6,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "kyles_lambda",
            "definition": "|5-day cumulative return| / 5-day cumulative volume",
            "source": "liquidity_reversal",
            "required_history": 6,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
        {
            "feature_name": "liquidity_innovation",
            "definition": "(amihud_5d - 20d MA) / 20d std",
            "source": "liquidity_reversal",
            "required_history": 26,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": LIQUIDITY_FEATURE_VERSION,
        },
    ]
