"""Feature engine: point-in-time events, price/volume features, information features, registry."""

from .parkinson import lagged_parkinson_volatility
from .finbert import FinBERTSpec, score_events
from .cross_asset_spillover import compute_spillover_features, validate_spillover_features, get_feature_specs as get_spillover_specs, CROSS_ASSET_FEATURE_VERSION
from .liquidity_reversal import compute_liquidity_features, validate_liquidity_features, get_feature_specs as get_liquidity_specs, LIQUIDITY_FEATURE_VERSION
from .volatility_risk_premium import compute_volatility_risk_features, validate_volatility_features, get_feature_specs as get_volatility_specs, VOLATILITY_FEATURE_VERSION

__all__ = [
    "lagged_parkinson_volatility", 
    "FinBERTSpec", 
    "score_events",
    "compute_spillover_features",
    "validate_spillover_features", 
    "get_spillover_specs",
    "CROSS_ASSET_FEATURE_VERSION",
    "compute_liquidity_features",
    "validate_liquidity_features",
    "get_liquidity_specs",
    "LIQUIDITY_FEATURE_VERSION",
    "compute_volatility_risk_features",
    "validate_volatility_features",
    "get_volatility_specs",
    "VOLATILITY_FEATURE_VERSION",
]
