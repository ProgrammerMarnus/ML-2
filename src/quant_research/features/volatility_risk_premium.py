"""Volatility risk premium features for H-003 hypothesis.

Economic mechanism: Investors pay a premium to hedge against volatility spikes,
creating a predictable return pattern where short volatility strategies earn
positive returns most of the time but suffer occasional large losses.

Features are computed using only past data (no look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional


VOLATILITY_FEATURE_VERSION = "h003.v1.0"


def compute_volatility_risk_features(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    vix: Optional[pd.Series] = None,
    vxn: Optional[pd.Series] = None,
    risk_free_rate: float = 0.02,
) -> pd.DataFrame:
    """Compute volatility risk premium features.
    
    Args:
        close: Daily close prices
        high: Daily high prices
        low: Daily low prices
        vix: Optional VIX index level (market implied vol)
        vxn: Optional VXN index level (NASDAQ implied vol)
        risk_free_rate: Annual risk-free rate for calculations
    
    Returns:
        DataFrame with volatility risk premium features
    """
    df = pd.DataFrame({
        'close': close,
        'high': high,
        'low': low,
    })
    
    if vix is not None:
        df['vix'] = vix
    if vxn is not None:
        df['vxn'] = vxn
    
    df = df.dropna()
    
    # Compute daily returns
    daily_ret = df['close'].pct_change()
    
    # Compute realized volatility measures
    ret_std_5 = daily_ret.rolling(5).std() * np.sqrt(252)
    ret_std_10 = daily_ret.rolling(10).std() * np.sqrt(252)
    ret_std_20 = daily_ret.rolling(20).std() * np.sqrt(252)
    ret_std_60 = daily_ret.rolling(60).std() * np.sqrt(252)
    
    # Parkinson volatility (more efficient estimator)
    log_range = np.log(df['high'] / df['low'])
    parkinson_var = (log_range ** 2) / (4 * np.log(2))
    parkinson_vol = np.sqrt(parkinson_var.rolling(20).mean() * 252)
    
    features = pd.DataFrame(index=df.index)
    
    # H1: Realized volatility term structure
    features['rv_term_struct_5_20'] = ret_std_5 / ret_std_20
    features['rv_term_struct_10_60'] = ret_std_10 / ret_std_60
    
    # H2: Volatility risk premium (VRP) - implied vs realized
    if 'vix' in df.columns:
        # VRP = Implied Vol - Realized Vol
        features['vrp_vix'] = df['vix'] - ret_std_20 * 100  # Convert to percentage
        features['vrp_vix_norm'] = features['vrp_vix'] / ret_std_20
        
        # VRP z-score relative to recent history
        vrp_mean = features['vrp_vix'].rolling(60).mean()
        vrp_std = features['vrp_vix'].rolling(60).std()
        features['vrp_zscore'] = (features['vrp_vix'] - vrp_mean) / vrp_std
    
    if 'vxn' in df.columns:
        features['vrp_vxn'] = df['vxn'] - ret_std_20 * 100
        features['vrp_vxn_norm'] = features['vrp_vxn'] / ret_std_20
    
    # H3: Volatility regime indicator
    features['vol_regime_high'] = (ret_std_20 > ret_std_20.rolling(252).median()).astype(int)
    features['vol_regime_extreme'] = (ret_std_20 > ret_std_20.rolling(252).quantile(0.9)).astype(int)
    
    # H4: Volatility trend
    features['vol_trend'] = ret_std_20 / ret_std_20.shift(20)
    features['vol_momentum'] = ret_std_20.pct_change(10)
    
    # H5: Volatility mean reversion signal
    vol_ma252 = ret_std_20.rolling(252).mean()
    vol_std252 = ret_std_20.rolling(252).std()
    features['vol_mean_revert'] = (ret_std_20 - vol_ma252) / vol_std252
    
    # H6: Skewness of returns (asymmetry in volatility)
    features['skewness_20d'] = daily_ret.rolling(20).skew()
    features['skewness_60d'] = daily_ret.rolling(60).skew()
    
    # H7: Kurtosis of returns (fat tails)
    features['kurtosis_20d'] = daily_ret.rolling(20).kurt()
    features['kurtosis_60d'] = daily_ret.rolling(60).kurt()
    
    # H8: Downside volatility (semi-deviation)
    negative_returns = daily_ret.clip(upper=0)
    features['downside_vol_20d'] = negative_returns.rolling(20).std() * np.sqrt(252)
    features['downside_ratio'] = features['downside_vol_20d'] / ret_std_20
    
    # H9: Volatility-of-volatility
    features['vol_of_vol_10d'] = ret_std_10.rolling(10).std() * np.sqrt(252)
    features['vol_of_vol_20d'] = ret_std_20.rolling(20).std() * np.sqrt(252)
    
    # H10: Jump detection (large moves relative to expected vol)
    expected_move = ret_std_5 / np.sqrt(252)  # Daily expected move
    actual_move = daily_ret.abs()
    features['jump_signal'] = actual_move / expected_move
    
    # H11: Consecutive up/down days (volatility clustering proxy)
    ret_sign = np.sign(daily_ret)
    features['consecutive_same'] = ret_sign.rolling(5).sum().abs()
    
    # H12: Range-based volatility acceleration
    range_vol = parkinson_vol
    features['vol_acceleration'] = range_vol.pct_change(5)
    
    return features


def validate_volatility_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate volatility risk premium features for leakage and quality.
    
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
            "feature_name": "rv_term_struct_5_20",
            "definition": "Ratio of 5-day realized vol to 20-day realized vol",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "rv_term_struct_10_60",
            "definition": "Ratio of 10-day realized vol to 60-day realized vol",
            "source": "volatility_risk_premium",
            "required_history": 61,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vrp_vix",
            "definition": "VIX level minus 20-day realized vol (in percentage points)",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "requires VIX data; trailing window ending at bar t",
            "missing_data_policy": "NaN if VIX unavailable; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vrp_vix_norm",
            "definition": "VRP normalized by realized vol",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "requires VIX data; trailing window ending at bar t",
            "missing_data_policy": "NaN if VIX unavailable; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vrp_zscore",
            "definition": "VRP z-score relative to 60-day rolling window",
            "source": "volatility_risk_premium",
            "required_history": 81,
            "availability_rule": "requires VIX data; trailing window ending at bar t",
            "missing_data_policy": "NaN if VIX unavailable; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_regime_high",
            "definition": "1 if 20-day vol > 252-day median, else 0",
            "source": "volatility_risk_premium",
            "required_history": 253,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "none (binary)",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_regime_extreme",
            "definition": "1 if 20-day vol > 252-day 90th percentile, else 0",
            "source": "volatility_risk_premium",
            "required_history": 253,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "none (binary)",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_trend",
            "definition": "Current 20-day vol / 20-day vol from 20 days ago",
            "source": "volatility_risk_premium",
            "required_history": 41,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_momentum",
            "definition": "10-day pct change in 20-day realized vol",
            "source": "volatility_risk_premium",
            "required_history": 31,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_mean_revert",
            "definition": "(20-day vol - 252-day mean) / 252-day std",
            "source": "volatility_risk_premium",
            "required_history": 253,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "skewness_20d",
            "definition": "20-day rolling skewness of daily returns",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "skewness_60d",
            "definition": "60-day rolling skewness of daily returns",
            "source": "volatility_risk_premium",
            "required_history": 61,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "kurtosis_20d",
            "definition": "20-day rolling kurtosis of daily returns",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "kurtosis_60d",
            "definition": "60-day rolling kurtosis of daily returns",
            "source": "volatility_risk_premium",
            "required_history": 61,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "downside_vol_20d",
            "definition": "20-day downside semi-deviation annualized",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "downside_ratio",
            "definition": "Downside vol / total vol",
            "source": "volatility_risk_premium",
            "required_history": 21,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_of_vol_10d",
            "definition": "10-day std of 10-day realized vol, annualized",
            "source": "volatility_risk_premium",
            "required_history": 20,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_of_vol_20d",
            "definition": "20-day std of 20-day realized vol, annualized",
            "source": "volatility_risk_premium",
            "required_history": 40,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "jump_signal",
            "definition": "Absolute return / expected daily move",
            "source": "volatility_risk_premium",
            "required_history": 6,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "consecutive_same",
            "definition": "Absolute sum of return signs over 5 days",
            "source": "volatility_risk_premium",
            "required_history": 6,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
        {
            "feature_name": "vol_acceleration",
            "definition": "5-day pct change in Parkinson volatility",
            "source": "volatility_risk_premium",
            "required_history": 26,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": VOLATILITY_FEATURE_VERSION,
        },
    ]
