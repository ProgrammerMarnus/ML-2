"""Build the exact, configuration-selected feature panel for a research run."""

from __future__ import annotations

import pandas as pd

from ..config import FeatureConfig
from ..data.schemas import DataValidationError
from .cross_asset_spillover import compute_spillover_features
from .information import build_information_features
from .liquidity_reversal import compute_liquidity_features
from .price_volume import build_price_volume_features, build_signal_extensions
from .registry import registry
from .volatility_risk_premium import compute_volatility_risk_features


KNOWN_SOURCES = frozenset(spec.source for spec in registry())
_VIX_FEATURES = frozenset({"vrp_vix", "vrp_vix_norm", "vrp_zscore"})
_VXN_FEATURES = frozenset({"vrp_vxn", "vrp_vxn_norm"})


def h001_selected_legs(features: pd.DataFrame) -> pd.Series:
    """Return H-001's conditional SPY/QQQ leg from its feature row.

    The leg is part of the hypothesis, rather than an execution detail. This
    helper deliberately accepts the current feature panel so a feature placebo
    also permutes the associated leg selection.
    """
    if "ratio_zscore" not in features:
        raise DataValidationError("H-001 requires the ratio_zscore feature")
    return pd.Series("SPY", index=features.index, dtype="object").where(
        features["ratio_zscore"] > 0.0, "QQQ"
    ).where(features["ratio_zscore"].notna())


def selected_sources(config: FeatureConfig, *, events_available: bool) -> list[str]:
    """Resolve the source contract, retaining the legacy default explicitly."""
    sources = list(config.include_sources) if config.include_sources else ["price_volume"]
    if not config.include_sources and events_available:
        sources.append("information")
    unknown = sorted(set(sources).difference(KNOWN_SOURCES))
    if unknown:
        raise DataValidationError(f"unknown feature source(s): {unknown}")
    if "information" in sources and not events_available:
        raise DataValidationError(
            "features.include_sources requests information, but no PIT event feed is available"
        )
    return sources


def planned_feature_names(
    config: FeatureConfig, *, events_available: bool, assets: list[str]
) -> list[str]:
    """Feature names the pipeline can construct for a declared data universe."""
    sources = set(selected_sources(config, events_available=events_available))
    if "cross_asset_spillover" in sources:
        missing = sorted({"SPY", "QQQ"}.difference(assets))
        vix_count = sum(symbol in assets for symbol in ("VIX", "^VIX"))
        if missing or vix_count != 1:
            detail = f"missing {missing}" if missing else ""
            raise DataValidationError(
                "cross_asset_spillover requires SPY, QQQ, and exactly one VIX "
                f"indicator asset (VIX or ^VIX); {detail}".rstrip("; ")
            )
    names = {spec.feature_name for spec in registry() if spec.source in sources}
    # Registered independently, not included by the wide-panel assembly yet.
    names.discard("parkinson_vol_20_lag1")
    if "VIX" not in assets:
        names.difference_update(_VIX_FEATURES)
    if "VXN" not in assets:
        names.difference_update(_VXN_FEATURES)
    names.difference_update(config.exclude_features)
    return sorted(names)


def _registered_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Reject implementation/registry drift instead of silently using it."""
    known = {spec.feature_name for spec in registry()}
    unexpected = sorted(set(frame.columns).difference(known))
    if unexpected:
        raise DataValidationError(f"feature implementation produced unregistered columns: {unexpected}")
    return frame


def build_feature_panel(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    target: str,
    config: FeatureConfig,
    *,
    open_: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Assemble only the requested, centrally registered features.

    This is the single construction path for direct runs and automated plans,
    so a YAML feature contract cannot be accepted yet ignored by model input.
    """
    sources = selected_sources(config, events_available=events is not None)
    panels: list[pd.DataFrame] = []
    if "price_volume" in sources:
        panels.extend((
            build_price_volume_features(close, volume, target),
            build_signal_extensions(open_, high, low, close, volume, target),
        ))
    if "information" in sources:
        assert events is not None
        panels.append(build_information_features(close.index, events, target))
    if "cross_asset_spillover" in sources:
        required = {"SPY", "QQQ"}
        missing = sorted(required.difference(close.columns))
        if missing:
            raise DataValidationError(
                "cross_asset_spillover requires close data for SPY and QQQ; "
                f"missing {missing}"
            )
        vix_symbols = [symbol for symbol in ("VIX", "^VIX") if symbol in close.columns]
        if len(vix_symbols) != 1:
            raise DataValidationError(
                "cross_asset_spillover requires exactly one VIX indicator column "
                "named VIX or ^VIX"
            )
        panels.append(compute_spillover_features(
            close["SPY"], close["QQQ"], volume["SPY"], volume["QQQ"],
            close[vix_symbols[0]],
        ).reindex(close.index))
    if "liquidity_reversal" in sources:
        panels.append(compute_liquidity_features(
            high[target], low[target], close[target], volume[target]
        ).reindex(close.index))
    if "volatility_risk_premium" in sources:
        vix = close["VIX"] if "VIX" in close else None
        vxn = close["VXN"] if "VXN" in close else None
        panels.append(compute_volatility_risk_features(
            close[target], high[target], low[target], vix=vix, vxn=vxn
        ).reindex(close.index))
    if not panels:
        raise DataValidationError("feature selection resolved to no feature panels")
    features = _registered_columns(pd.concat(panels, axis=1))
    if features.columns.duplicated().any():
        duplicated = sorted(features.columns[features.columns.duplicated()].unique())
        raise DataValidationError(f"feature selection produced duplicate columns: {duplicated}")
    unknown_exclusions = sorted(set(config.exclude_features).difference(features.columns))
    if unknown_exclusions:
        raise DataValidationError(
            "features.exclude_features contains unavailable feature(s): "
            f"{unknown_exclusions}"
        )
    return features.drop(columns=config.exclude_features, errors="ignore")
