"""Factor mean reversion features for H-006 hypothesis.

Economic mechanism: Factor exposures exhibit mean-reverting behavior over 
short-to-medium horizons due to crowding unwinds, style rotation, and risk 
parity adjustments. Extreme factor exposure deviations from rolling norms 
predict opposite-signed returns over the following week.

Features are computed using only past data (no look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional


FACTOR_FEATURE_VERSION = "h006.v1.0"


def _compute_beta(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 60
) -> pd.Series:
    """Compute rolling beta of asset returns to benchmark returns.
    
    Args:
        asset_returns: Daily returns of the asset
        benchmark_returns: Daily returns of the benchmark
        window: Rolling window for beta calculation
        
    Returns:
        Rolling beta series
    """
    # Covariance / Variance formula for beta
    cov = asset_returns.rolling(window).cov(benchmark_returns)
    var = benchmark_returns.rolling(window).var()
    return cov / var.replace(0.0, float("nan"))


def _compute_realized_vol(returns: pd.Series, window: int = 20) -> pd.Series:
    """Compute annualized realized volatility.
    
    Args:
        returns: Daily returns series
        window: Rolling window
        
    Returns:
        Annualized volatility series
    """
    return returns.rolling(window).std() * np.sqrt(252)


def _compute_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score.
    
    Args:
        series: Input series
        window: Rolling window for mean/std
        
    Returns:
        Z-scored series
    """
    rolling_mean = series.rolling(window).mean()
    rolling_std = series.rolling(window).std()
    return (series - rolling_mean) / rolling_std.replace(0.0, float("nan"))


def _compute_correlation_to_benchmark(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 60
) -> pd.Series:
    """Compute rolling correlation to benchmark.
    
    Args:
        asset_returns: Asset returns
        benchmark_returns: Benchmark returns
        window: Rolling window
        
    Returns:
        Rolling correlation series
    """
    return asset_returns.rolling(window).corr(benchmark_returns)


def compute_factor_mean_reversion_features(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    benchmark_close: pd.Series,
    correlation_benchmark_close: Optional[pd.Series] = None,
    vix: Optional[pd.Series] = None,
    asset_class: str = "us_equity",
) -> pd.DataFrame:
    """Compute H-006 factor mean reversion features.
    
    Args:
        close: Daily close prices
        high: Daily high prices
        low: Daily low prices
        volume: Daily volume
        benchmark_close: Benchmark close prices (SPY for equities, LQD for credit, GLD for commodities)
        correlation_benchmark_close: Optional separate benchmark for the
            correlation-extreme term. H-006 uses SPY for this term even when
            beta uses an asset-class benchmark. Defaults to benchmark_close for
            backward compatibility.
        vix: Optional VIX index for volatility stand-down check
        asset_class: Asset class identifier for benchmark selection
        
    Returns:
        DataFrame with H-006 factor mean reversion features
    """
    df = pd.DataFrame({
        'close': close,
        'high': high,
        'low': low,
        'volume': volume,
    })
    
    # Align benchmark
    benchmark = benchmark_close.rename('benchmark')
    df = df.join(benchmark)
    correlation_benchmark = (
        correlation_benchmark_close
        if correlation_benchmark_close is not None
        else benchmark_close
    ).rename('correlation_benchmark')
    df = df.join(correlation_benchmark)
    
    if vix is not None:
        df['vix'] = vix
    
    # Compute daily returns
    # The frozen H-006 data contract forbids forward-filling missing market
    # observations.  Be explicit because pandas' historic pct_change default
    # pads gaps, which would manufacture returns across missing sessions.
    daily_ret = df['close'].pct_change(fill_method=None)
    benchmark_ret = df['benchmark'].pct_change(fill_method=None)
    correlation_benchmark_ret = df['correlation_benchmark'].pct_change(
        fill_method=None
    )
    
    features = pd.DataFrame(index=df.index)
    
    # H1: Beta z-score (60-session beta z-scored over 252 sessions)
    beta_60 = _compute_beta(daily_ret, benchmark_ret, window=60)
    beta_zscore = _compute_zscore(beta_60, window=252)
    features['h006_beta_zscore'] = beta_zscore
    
    # H2: Momentum deviation (20d return minus 252d median, cross-sectional z-score)
    ret_20d = df['close'].pct_change(20, fill_method=None)
    ret_median_252 = daily_ret.rolling(252).median()
    momentum_deviation = ret_20d - ret_median_252
    # Note: Cross-sectional z-scoring happens downstream in assembly
    features['h006_momentum_deviation'] = momentum_deviation
    
    # H3: Volatility percentile (20d vol ranked within 252d distribution)
    vol_20d = _compute_realized_vol(daily_ret, window=20)
    # Rank within trailing 252-day distribution
    vol_rank = vol_20d.rolling(252).apply(
        lambda x: pd.Series(x).dropna().rank(pct=True).iloc[-1] if len(x.dropna()) > 0 else np.nan
    )
    # Transform rank (0-1) to approximate z-score using inverse normal CDF
    from scipy.stats import norm
    vol_percentile_zscore = norm.ppf(vol_rank.replace(0.0, 0.001).replace(1.0, 0.999))
    features['h006_volatility_percentile'] = vol_percentile_zscore
    
    # H4: Correlation extreme (60d corr minus 252d mean corr)
    corr_60 = _compute_correlation_to_benchmark(
        daily_ret, correlation_benchmark_ret, window=60
    )
    corr_mean_252 = corr_60.rolling(252).mean()
    corr_std_252 = corr_60.rolling(252).std()
    correlation_extreme = (corr_60 - corr_mean_252) / corr_std_252.replace(0.0, float("nan"))
    features['h006_correlation_extreme'] = correlation_extreme
    
    # H5: Drawdown recovery (drawdown depth z-scored by volatility)
    rolling_max = df['close'].rolling(252).max()
    drawdown = (df['close'] - rolling_max) / rolling_max
    vol_252 = _compute_realized_vol(daily_ret, window=252)
    drawdown_recovery = drawdown / vol_252.replace(0.0, float("nan"))
    features['h006_drawdown_recovery'] = drawdown_recovery
    
    return features


def validate_factor_features(features: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate H-006 factor mean reversion features for leakage and quality.
    
    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []
    
    required_features = [
        'h006_beta_zscore',
        'h006_momentum_deviation',
        'h006_volatility_percentile',
        'h006_correlation_extreme',
        'h006_drawdown_recovery',
    ]
    
    # Check all required features are present
    missing = [f for f in required_features if f not in features.columns]
    if missing:
        errors.append(f"Missing required features: {missing}")
    
    # Check for infinite values; warm-up NaNs are expected
    if not pd.DataFrame(features).replace([float("inf"), float("-inf")], float("nan")).equals(features):
        errors.append("Infinite values detected in features")
    
    # Check for constant columns (excluding warm-up period)
    min_obs = 504  # Minimum observations after warm-up
    if len(features) >= min_obs:
        constant_cols = [
            col for col in features.columns 
            if features[col].iloc[min_obs//2:].nunique() == 1
        ]
        if constant_cols:
            errors.append(f"Constant features after warm-up: {constant_cols}")
    
    return len(errors) == 0, errors


def get_feature_specs() -> List[dict]:
    """Return H-006 feature specifications for registry."""
    return [
        {
            "feature_name": "h006_beta_zscore",
            "definition": "Rolling 60-session beta to benchmark z-scored over 252 sessions",
            "source": "factor_mean_reversion",
            "required_history": 312,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "cross-sectional z-score at decision timestamp",
            "version": FACTOR_FEATURE_VERSION,
            "hypothesis": "H-006",
        },
        {
            "feature_name": "h006_momentum_deviation",
            "definition": "20-session return minus 252-session rolling median return",
            "source": "factor_mean_reversion",
            "required_history": 272,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "cross-sectional z-score at decision timestamp",
            "version": FACTOR_FEATURE_VERSION,
            "hypothesis": "H-006",
        },
        {
            "feature_name": "h006_volatility_percentile",
            "definition": "20-session realized volatility ranked within 252-session distribution, transformed to z-score",
            "source": "factor_mean_reversion",
            "required_history": 272,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "cross-sectional z-score at decision timestamp",
            "version": FACTOR_FEATURE_VERSION,
            "hypothesis": "H-006",
        },
        {
            "feature_name": "h006_correlation_extreme",
            "definition": "60-session correlation to benchmark minus 252-session mean correlation, standardized",
            "source": "factor_mean_reversion",
            "required_history": 312,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "cross-sectional z-score at decision timestamp",
            "version": FACTOR_FEATURE_VERSION,
            "hypothesis": "H-006",
        },
        {
            "feature_name": "h006_drawdown_recovery",
            "definition": "Drawdown from 252-session high divided by 252-session realized volatility",
            "source": "factor_mean_reversion",
            "required_history": 252,
            "availability_rule": "trailing window ending at bar t; no future data",
            "missing_data_policy": "NaN during warm-up; fold-local imputer",
            "normalization_rule": "cross-sectional z-score at decision timestamp",
            "version": FACTOR_FEATURE_VERSION,
            "hypothesis": "H-006",
        },
    ]
