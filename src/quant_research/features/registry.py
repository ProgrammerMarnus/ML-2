"""Feature registry: machine-readable metadata for every feature.

The registry records definition, source, required history, availability rule,
missing-data policy, normalization rule, and version so that feature sets are
auditable and hashable per experiment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import List

from .information import INFO_FEATURE_VERSION
from .parkinson import PARKINSON_FEATURE_VERSION
from .price_volume import FEATURE_VERSION, SIGNAL_EXT_VERSION
from .cross_asset_spillover import CROSS_ASSET_FEATURE_VERSION
from .liquidity_reversal import LIQUIDITY_FEATURE_VERSION
from .volatility_risk_premium import VOLATILITY_FEATURE_VERSION
from .factor_mean_reversion import FACTOR_FEATURE_VERSION
from .overnight_intraday import OVERNIGHT_INTRADAY_FEATURE_VERSION

PRICE_VOLUME_SOURCE = "price_volume"
INFORMATION_SOURCE = "information"


@dataclass(frozen=True)
class FeatureSpec:
    feature_name: str
    definition: str
    source: str
    required_history: int
    availability_rule: str
    missing_data_policy: str
    normalization_rule: str
    version: str
    hypothesis: str = ""


def price_volume_feature_specs() -> List[FeatureSpec]:
    v = FEATURE_VERSION
    rule = "trailing window ending at bar t; no future data"
    norm = "fold-local StandardScaler"
    imp = "NaN during warm-up; fold-local imputer"
    return [
        FeatureSpec("momentum_63", "close/close.shift(63)-1", PRICE_VOLUME_SOURCE, 64, rule, imp, norm, v),
        FeatureSpec("momentum_252", "close/close.shift(252)-1", PRICE_VOLUME_SOURCE, 253, rule, imp, norm, v),
        FeatureSpec("trend_50", "close/SMA50-1", PRICE_VOLUME_SOURCE, 50, rule, imp, norm, v),
        FeatureSpec("mean_reversion_20", "-zscore(daily returns, 20)", PRICE_VOLUME_SOURCE, 21, rule, imp, norm, v),
        FeatureSpec("realized_vol_20", "std(daily returns,20)*sqrt(252)", PRICE_VOLUME_SOURCE, 21, rule, imp, norm, v),
        FeatureSpec("volatility_ratio_10_60", "rv10/rv60", PRICE_VOLUME_SOURCE, 61, rule, imp, norm, v),
        FeatureSpec("volume_zscore_20", "(vol-rollmean20)/rollstd20", PRICE_VOLUME_SOURCE, 20, rule, imp, norm, v),
        FeatureSpec("log_dollar_volume_20", "log(mean(close*vol,20))", PRICE_VOLUME_SOURCE, 20, rule, imp, norm, v),
        FeatureSpec("cross_asset_rel_strength", "target return - universe mean return", PRICE_VOLUME_SOURCE, 2, rule, imp, norm, v),
        FeatureSpec("regime_drawdown", "target/rollmax60-1", PRICE_VOLUME_SOURCE, 60, rule, imp, norm, v),
        FeatureSpec("regime_high_vol", "1 if rv60 > 252d rolling median else 0", PRICE_VOLUME_SOURCE, 60, rule, imp, norm, v),
        FeatureSpec(
            "parkinson_vol_20_lag1",
            "sqrt(252 * mean_20(group_shift_1((log(high)-log(low))**2 / (4*log(2)))))",
            PRICE_VOLUME_SOURCE,
            21,
            "symbol-local prior 20 observed bars ending at t-1; explicit shift(1)",
            "first 20 rows per symbol are NaN; invalid raw OHLCV rejected",
            "none in feature; downstream imputer/scaler fit on training fold only",
            PARKINSON_FEATURE_VERSION,
        ),
    ]


def information_feature_specs() -> List[FeatureSpec]:
    v = INFO_FEATURE_VERSION
    rule = "event availability_time <= bar timestamp (session open); PIT join"
    norm = "fold-local StandardScaler"
    imp = "explicit 0 when no live events"
    return [
        FeatureSpec("info_sentiment", "recency-decayed mean event sentiment", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_abs_sentiment", "recency-decayed mean |sentiment|", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_attention", "log1p(live event count)", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_source_breadth", "distinct sources among live events", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_novelty", "recency-decayed mean novelty", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_disagreement", "|mean sent| - mean |sent|", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_intensity", "max |sentiment| * decay", INFORMATION_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("info_corroboration", "max corroboration among live events", INFORMATION_SOURCE, 1, rule, imp, norm, v),
    ]


def signal_extension_feature_specs() -> List[FeatureSpec]:
    v = SIGNAL_EXT_VERSION
    rule = "trailing window ending at bar t (inclusive); no future data"
    norm = "fold-local StandardScaler"
    imp = "NaN during warm-up; fold-local imputer"
    return [
        FeatureSpec("overnight_gap", "open[t]/close[t-1]-1", PRICE_VOLUME_SOURCE, 2, rule, imp, norm, v),
        FeatureSpec("intraday_return", "close[t]/open[t]-1", PRICE_VOLUME_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("day_range_position", "(close-low)/(high-low)", PRICE_VOLUME_SOURCE, 1, rule, imp, norm, v),
        FeatureSpec("rsi_14", "Wilder RSI(14) on daily changes", PRICE_VOLUME_SOURCE, 15, rule, imp, norm, v),
        FeatureSpec("bollinger_position_20", "(close-SMA20)/(2*std20)", PRICE_VOLUME_SOURCE, 21, rule, imp, norm, v),
        FeatureSpec("fifty_two_week_position", "(close-min252)/(max252-min252)", PRICE_VOLUME_SOURCE, 252, rule, imp, norm, v),
        FeatureSpec("vol_of_vol_20", "std(realized_vol_20, 20)", PRICE_VOLUME_SOURCE, 41, rule, imp, norm, v),
        FeatureSpec("price_volume_corr_20", "corr(daily ret, log vol change, 20)", PRICE_VOLUME_SOURCE, 22, rule, imp, norm, v),
        FeatureSpec("amihud_illiquidity_20", "mean(|ret|/dollar_volume, 20)", PRICE_VOLUME_SOURCE, 21, rule, imp, norm, v),
    ]


def cross_asset_spillover_feature_specs() -> List[FeatureSpec]:
    """H-001: Cross-asset information diffusion features."""
    from .cross_asset_spillover import get_feature_specs as get_spillover_specs
    specs_dict = get_spillover_specs()
    return [FeatureSpec(**spec) for spec in specs_dict]


def liquidity_reversal_feature_specs() -> List[FeatureSpec]:
    """H-002: Liquidity imbalance reversal features."""
    from .liquidity_reversal import get_feature_specs as get_liquidity_specs
    specs_dict = get_liquidity_specs()
    return [FeatureSpec(**spec) for spec in specs_dict]


def volatility_risk_premium_feature_specs() -> List[FeatureSpec]:
    """H-003: Multi-asset volatility risk premium features."""
    from .volatility_risk_premium import get_feature_specs as get_volatility_specs
    specs_dict = get_volatility_specs()
    return [FeatureSpec(**spec) for spec in specs_dict]


def h003_r1_feature_specs() -> List[FeatureSpec]:
    """H-003-R1 amended cross-sectional daily-data signal definitions."""
    source = "h003_r1_volatility_shock"
    version = "h003.r1.0"
    rule = "trailing data through close t; target weights execute no earlier than t+1"
    missing = "NaN until every frozen lookback is available; all five terms required"
    norm = "cross-sectional z-score at decision timestamp"
    return [
        FeatureSpec("h003r1_vshock_1d", "positive 20d RV z-score vs lagged-year norm, shifted one session", source, 274, rule, missing, norm, version),
        FeatureSpec("h003r1_vshock_5d", "5-session mean of lagged positive RV shock", source, 278, rule, missing, norm, version),
        FeatureSpec("h003r1_vol_mean_rev", "20d realized volatility / lagged-year mean", source, 273, rule, missing, norm, version),
        FeatureSpec("h003r1_skewness_20d", "20-session return skewness", source, 21, rule, missing, norm, version),
        FeatureSpec("h003r1_correlation_spike", "20d mean correlation to peers minus trailing 252-session norm", source, 272, rule, missing, norm, version),
    ]


def h006_factor_mean_reversion_feature_specs() -> List[FeatureSpec]:
    """H-006 factor exposure mean reversion features."""
    from .factor_mean_reversion import get_feature_specs as get_factor_specs
    specs_dict = get_factor_specs()
    return [FeatureSpec(**spec) for spec in specs_dict]


def overnight_intraday_feature_specs() -> List[FeatureSpec]:
    """H-005: Overnight-intraday return decomposition features."""
    from .overnight_intraday import get_feature_specs as get_overnight_specs
    specs_dict = get_overnight_specs()
    return [FeatureSpec(**spec) for spec in specs_dict]


def registry() -> List[FeatureSpec]:
    return (price_volume_feature_specs() + signal_extension_feature_specs()
            + information_feature_specs() + cross_asset_spillover_feature_specs()
            + liquidity_reversal_feature_specs() + volatility_risk_premium_feature_specs()
            + h003_r1_feature_specs() + h006_factor_mean_reversion_feature_specs()
            + overnight_intraday_feature_specs())


def _hashable_spec(spec: FeatureSpec) -> dict:
    """Serialize a spec for ``registry_hash`` without empty optional metadata.

    ``registry_hash`` pins the pre-existing feature contracts, so adding a new
    optional field must not move a historical hash.  Optional metadata is
    therefore emitted only when it carries a value: H-006 tags its specs with
    ``hypothesis``, while H-001/H-002/H-003/H-005 leave it empty and keep the
    hash they were audited with.
    """
    record = asdict(spec)
    if not record.get("hypothesis"):
        record.pop("hypothesis", None)
    return record


def registry_hash(names: List[str]) -> str:
    """Deterministic hash of a named feature subset (for experiment records)."""
    specs = {s.feature_name: s for s in registry()}
    unknown = [n for n in names if n not in specs]
    if unknown:
        raise KeyError(f"features not in registry: {unknown}")
    payload = json.dumps([_hashable_spec(specs[n]) for n in sorted(names)], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
