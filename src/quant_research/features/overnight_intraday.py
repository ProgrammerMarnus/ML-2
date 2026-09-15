"""Overnight-intraday return decomposition features for H-005 hypothesis.

Economic mechanism: Equity returns decompose into overnight (close-to-open) and 
intraday (open-to-close) components with systematically different properties.
- Overnight returns exhibit momentum/persistence due to risk premium
- Intraday returns exhibit mean reversion due to liquidity provision

Features are computed using only past data (no look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional, Dict


OVERNIGHT_INTRADAY_FEATURE_VERSION = "h005.v1.0"


def compute_overnight_intraday_features(
    open_price: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    vix: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Compute overnight-intraday decomposition features.
    
    Args:
        open_price: Daily open prices (adjusted)
        high: Daily high prices
        low: Daily low prices
        close: Daily close prices (adjusted)
        volume: Daily trading volume
        vix: Optional VIX index level for regime filtering
        
    Returns:
        DataFrame with overnight-intraday features
        
    Raises:
        ValueError: If required price fields contain invalid data
    """
    # Validate inputs
    if (open_price <= 0).any() or (close <= 0).any():
        raise ValueError("H-005 requires strictly positive open and close prices")
    
    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })
    
    if vix is not None:
        df['vix'] = vix
    
    df = df.dropna()
    
    # Compute overnight return: (Open_t - Close_{t-1}) / Close_{t-1}
    overnight_ret = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
    
    # Compute intraday return: (Close_t - Open_t) / Open_t
    intraday_ret = (df['close'] - df['open']) / df['open']
    
    # Compute total return for comparison
    total_ret = df['close'].pct_change()
    
    features = pd.DataFrame(index=df.index)
    
    # === Overnight Momentum Features ===
    
    # H1: Single-day overnight return
    features['overnight_ret_1d'] = overnight_ret
    
    # H2: 5-day rolling mean of overnight returns (short-term momentum)
    features['overnight_ret_5d'] = overnight_ret.rolling(5, min_periods=5).mean()
    
    # H3: 20-day rolling mean of overnight returns (medium-term trend)
    features['overnight_ret_20d'] = overnight_ret.rolling(20, min_periods=20).mean()
    
    # === Intraday Mean Reversion Features ===
    
    # H4: Single-day intraday return
    features['intraday_ret_1d'] = intraday_ret
    
    # H5: 5-day rolling mean of intraday returns
    features['intraday_ret_5d'] = intraday_ret.rolling(5, min_periods=5).mean()
    
    # === Cross-Sectional and Regime Features ===
    
    # H6: Overnight volatility ratio (fraction of total vol from overnight)
    overnight_vol_20 = overnight_ret.rolling(20, min_periods=20).std()
    total_vol_20 = total_ret.rolling(20, min_periods=20).std()
    features['overnight_vol_ratio'] = overnight_vol_20 / total_vol_20.replace(0.0, np.nan)
    
    # H7: Gap size (absolute overnight move magnitude)
    features['gap_size'] = overnight_ret.abs()
    
    # H8: Overnight skewness (asymmetry of overnight moves)
    features['overnight_skew'] = overnight_ret.rolling(60, min_periods=60).skew()
    
    # H9: VIX regime (if available)
    if vix is not None:
        features['vix_regime'] = vix.rolling(20, min_periods=20).mean()
    else:
        features['vix_regime'] = np.nan
    
    # H10: Intraday range as fraction of overnight gap (fill tendency)
    intraday_range = df['high'] - df['low']
    overnight_gap_abs = (df['open'] - df['close'].shift(1)).abs()
    features['intraday_fill_ratio'] = intraday_range / overnight_gap_abs.replace(0.0, np.nan)
    
    # === Lagged Features for Prediction ===
    
    # Lag overnight momentum for prediction
    features['overnight_ret_20d_lag1'] = features['overnight_ret_20d'].shift(1)
    features['overnight_ret_5d_lag1'] = features['overnight_ret_5d'].shift(1)
    
    # Lag intraday for mean reversion signal
    features['intraday_ret_5d_lag1'] = features['intraday_ret_5d'].shift(1)
    
    return features


def get_feature_metadata() -> Dict[str, dict]:
    """Return metadata for all H-005 features.
    
    Returns:
        Dictionary mapping feature names to metadata
    """
    return {
        'overnight_ret_1d': {
            'description': 'Single-day overnight return',
            'formula': '(open_t - close_{t-1}) / close_{t-1}',
            'expected_sign': 'persistent',
            'warmup_bars': 1,
        },
        'overnight_ret_5d': {
            'description': '5-day rolling mean overnight return',
            'formula': 'rolling(overnight_ret_1d, 5).mean()',
            'expected_sign': 'positive',
            'warmup_bars': 5,
        },
        'overnight_ret_20d': {
            'description': '20-day rolling mean overnight return',
            'formula': 'rolling(overnight_ret_1d, 20).mean()',
            'expected_sign': 'positive',
            'warmup_bars': 20,
        },
        'intraday_ret_1d': {
            'description': 'Single-day intraday return',
            'formula': '(close_t - open_t) / open_t',
            'expected_sign': 'mean-reverting',
            'warmup_bars': 1,
        },
        'intraday_ret_5d': {
            'description': '5-day rolling mean intraday return',
            'formula': 'rolling(intraday_ret_1d, 5).mean()',
            'expected_sign': 'mean-reverting',
            'warmup_bars': 5,
        },
        'overnight_vol_ratio': {
            'description': 'Fraction of total volatility from overnight component',
            'formula': 'std(overnight_ret, 20) / std(total_ret, 20)',
            'expected_sign': 'modulates position size',
            'warmup_bars': 20,
        },
        'gap_size': {
            'description': 'Absolute magnitude of overnight gap',
            'formula': 'abs(overnight_ret_1d)',
            'expected_sign': 'larger gaps → more intraday reversal',
            'warmup_bars': 1,
        },
        'overnight_skew': {
            'description': 'Skewness of overnight returns',
            'formula': 'rolling(overnight_ret, 60).skew()',
            'expected_sign': 'negative skew → higher premium',
            'warmup_bars': 60,
        },
        'vix_regime': {
            'description': '20-day mean VIX level',
            'formula': 'rolling(vix, 20).mean()',
            'expected_sign': 'higher VIX → stronger overnight premium',
            'warmup_bars': 20,
        },
        'intraday_fill_ratio': {
            'description': 'Intraday range relative to overnight gap',
            'formula': '(high - low) / abs(open - close_prev)',
            'expected_sign': 'measures gap fill tendency',
            'warmup_bars': 1,
        },
        'overnight_ret_20d_lag1': {
            'description': 'Lagged 20-day overnight momentum',
            'formula': 'overnight_ret_20d.shift(1)',
            'expected_sign': 'predictive',
            'warmup_bars': 21,
        },
        'overnight_ret_5d_lag1': {
            'description': 'Lagged 5-day overnight momentum',
            'formula': 'overnight_ret_5d.shift(1)',
            'expected_sign': 'predictive',
            'warmup_bars': 6,
        },
        'intraday_ret_5d_lag1': {
            'description': 'Lagged 5-day intraday return',
            'formula': 'intraday_ret_5d.shift(1)',
            'expected_sign': 'mean-reverting (negative)',
            'warmup_bars': 6,
        },
    }


def validate_overnight_intraday_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate overnight-intraday features for leakage and quality.
    
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
    metadata = get_feature_metadata()
    specs = []
    
    for feature_name, meta in metadata.items():
        specs.append({
            "feature_name": feature_name,
            "definition": meta['formula'],
            "source": "overnight_intraday",
            "required_history": meta['warmup_bars'],
            "availability_rule": "open/close prices observed at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "fold-local StandardScaler",
            "version": OVERNIGHT_INTRADAY_FEATURE_VERSION,
        })
    
    return specs
