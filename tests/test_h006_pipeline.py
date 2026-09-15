"""Behavioral tests for the H-006 cross-sectional portfolio path."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from quant_research.config import (
    AppConfig,
    DataConfig,
    EvaluationConfig,
    ExecutionConfig,
    FeatureConfig,
    ModelConfig,
    PromotionConfig,
    ResearchConfig,
)
from quant_research.data.loaders import generate_synthetic_ohlcv, load_market_data
from quant_research.data.schemas import DataValidationError
from quant_research.h006_pipeline import (
    H006_ASSET_CLASSES,
    H006_FEATURES,
    H006_INVESTABLES,
    build_h006_feature_panels,
    build_h006_signal,
    h006_feature_leakage_report,
    run_h006_pipeline,
)
from quant_research.portfolio.h006_portfolio import (
    H006_PORTFOLIO_PARAMS,
    construct_h006_portfolio,
    validate_h006_limits,
)


def _close_panel(n: int = 900) -> pd.DataFrame:
    idx = pd.bdate_range("2010-01-04", periods=n, tz="UTC")
    rng = np.random.default_rng(606)
    returns = rng.normal(0.0002, 0.01, (n, len(H006_INVESTABLES)))
    return pd.DataFrame(
        100.0 * np.exp(np.cumsum(returns, axis=0)),
        index=idx, columns=H006_INVESTABLES,
    )


def _ohlcv(start="2010-01-01", end="2016-01-01") -> pd.DataFrame:
    assets = list(H006_INVESTABLES) + ["^VIX"]
    frame = generate_synthetic_ohlcv(assets, start, end)
    is_vix = frame["symbol"].eq("^VIX")
    for field in ("open", "high", "low", "close"):
        frame.loc[is_vix, field] = 20.0
    return frame


def _config(tmp_path, *, placebo_runs=2, bootstrap_samples=20) -> AppConfig:
    assets = list(H006_INVESTABLES) + ["^VIX"]
    return AppConfig(
        data=DataConfig(
            mode="h006", assets=assets, target="SPY",
            start="2010-01-01", end="2016-01-01",
            raw_snapshot_dir=str(tmp_path / "snapshots"),
        ),
        evaluation=EvaluationConfig(
            train_window=252, validation_window=63, test_window=126,
            step_bars=126, purge_bars=5, embargo_bars=5,
        ),
        execution=ExecutionConfig(
            fee_bps=5.0, slippage_bps=3.0, target_vol=0.10,
            max_position=0.12, gross_leverage_cap=1.0,
            net_exposure_cap=0.40,
        ),
        model=ModelConfig(
            type="none", random_seed=42, hold_bars=5,
            rebalance_day="wednesday",
        ),
        features=FeatureConfig(include_sources=["factor_mean_reversion"]),
        research=ResearchConfig(
            max_trials=10, bootstrap_samples=bootstrap_samples,
            placebo_runs=placebo_runs, threshold_candidates=[],
            hold_candidates=[5],
        ),
        promotion=PromotionConfig(
            min_placebo_runs=placebo_runs,
            max_placebo_adjusted_p=0.5,
            min_capacity_aum=1.0,
        ),
    )


def test_h006_feature_panels_and_signal_match_frozen_contract():
    close = _close_panel()
    high, low = close * 1.01, close * 0.99
    volume = pd.DataFrame(1_000_000.0, index=close.index, columns=close.columns)
    panels = build_h006_feature_panels(close, high, low, volume)
    assert tuple(panels) == H006_FEATURES
    assert all(frame.shape == close.shape for frame in panels.values())
    signal = build_h006_signal(panels)
    assert signal.shape == close.shape
    assert (signal.notna().sum(axis=1) >= 12).any()


def test_h006_self_benchmarks_are_excluded_instead_of_scoring_float_noise():
    close = _close_panel()
    high, low = close * 1.01, close * 0.99
    volume = pd.DataFrame(1_000_000.0, index=close.index, columns=close.columns)
    panels = build_h006_feature_panels(close, high, low, volume)

    assert panels["h006_beta_zscore"][["SPY", "LQD", "GLD"]].isna().all().all()
    assert panels["h006_correlation_extreme"]["SPY"].isna().all()

    signal = build_h006_signal(panels)
    assert signal[["SPY", "LQD", "GLD"]].isna().all().all()


def test_h006_signal_requires_all_five_terms():
    idx = pd.bdate_range("2020-01-01", periods=2, tz="UTC")
    cols = list(H006_INVESTABLES)
    panels = {
        name: pd.DataFrame(
            np.tile(np.linspace(-1.0, 1.0, len(cols)), (2, 1)),
            index=idx, columns=cols,
        )
        for name in H006_FEATURES
    }
    panels["h006_beta_zscore"].loc[idx[0], "QQQ"] = np.nan
    signal = build_h006_signal(panels)
    assert pd.isna(signal.loc[idx[0], "QQQ"])
    assert pd.notna(signal.loc[idx[1], "QQQ"])


def test_h006_portfolio_rebalances_wednesday_and_enforces_all_limits():
    close = _close_panel(180)
    signal = pd.DataFrame(
        np.tile(np.linspace(-2.0, 2.0, len(close.columns)), (len(close), 1)),
        index=close.index, columns=close.columns,
    )
    vix = pd.Series(20.0, index=close.index)
    weights = construct_h006_portfolio(
        signal, close, H006_ASSET_CLASSES, vix, **H006_PORTFOLIO_PARAMS,
    )
    changed = weights.diff().abs().sum(axis=1)
    changed_days = changed.index[changed > 1e-12]
    assert len(changed_days) > 0
    assert set(changed_days.weekday) == {2}
    assert validate_h006_limits(weights, H006_ASSET_CLASSES)["passed"]


def test_h006_vix_rule_reduces_gross_instead_of_flattening():
    close = _close_panel(180)
    signal = pd.DataFrame(
        np.tile(np.linspace(-2.0, 2.0, len(close.columns)), (len(close), 1)),
        index=close.index, columns=close.columns,
    )
    vix = pd.Series(20.0, index=close.index)
    last_wednesday = close.index[close.index.weekday == 2][-1]
    vix.loc[last_wednesday] = 80.0
    weights = construct_h006_portfolio(
        signal, close, H006_ASSET_CLASSES, vix, **H006_PORTFOLIO_PARAMS,
    )
    gross = float(weights.loc[last_wednesday].abs().sum())
    assert 0.0 < gross <= 0.30 + 1e-10


def test_h006_leakage_report_is_panel_aware():
    report = h006_feature_leakage_report(_ohlcv("2010-01-01", "2014-01-01"))
    assert report["passed"] is True
    assert report["max_abs_delta_history"] == 0.0


def test_h006_pipeline_fails_closed_without_vix(tmp_path):
    frame = _ohlcv()
    frame = frame[frame["symbol"] != "^VIX"]
    cfg = _config(tmp_path)
    try:
        run_h006_pipeline(cfg, frame, tmp_path, "synthetic-h006")
    except DataValidationError as exc:
        assert "requires ^VIX" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("H-006 accepted a run that could not enforce its VIX rule")


def test_h006_mode_can_replay_exact_raw_snapshot(tmp_path, monkeypatch):
    frame = _ohlcv()
    snapshot = tmp_path / "h006.csv.gz"
    frame.to_csv(snapshot, index=False)
    cfg = _config(tmp_path).data
    cfg = replace(cfg, csv_path=str(snapshot))

    monkeypatch.setattr(
        "quant_research.data.loaders.load_yfinance_ohlcv",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    replayed, meta = load_market_data(cfg)

    assert len(replayed) == len(frame)
    assert set(replayed["symbol"]) == set(frame["symbol"])
    assert "frozen raw-snapshot replay" in meta["assumptions"]


def test_h006_pipeline_builds_locked_portfolio_result(tmp_path, monkeypatch):
    from quant_research import h006_pipeline as module

    monkeypatch.setattr(
        module, "h006_feature_leakage_report",
        lambda _ohlcv: {"passed": True, "checked_rows": 1,
                        "max_abs_delta_history": 0.0},
    )
    report = run_h006_pipeline(
        _config(tmp_path), _ohlcv(), tmp_path, "synthetic-h006",
    )
    assert report["baseline"].execution_contract == "h006_cross_sectional_portfolio"
    assert len(report["folds"]) >= 1
    assert report["h006_limit_report"]["passed"]
    assert (tmp_path / "test_lock.json").exists()


def test_h006_full_runner_records_portfolio_native_evidence(tmp_path, monkeypatch):
    from quant_research import h006_pipeline as h006_module
    from quant_research import run as run_module

    frame = _ohlcv()
    cfg = _config(tmp_path)
    monkeypatch.setattr(
        run_module, "load_market_data",
        lambda _cfg: (frame, {"mode": "synthetic H-006 fixture"}),
    )
    monkeypatch.setattr(
        h006_module, "h006_feature_leakage_report",
        lambda _ohlcv: {"passed": True, "checked_rows": 1,
                        "max_abs_delta_history": 0.0},
    )
    report = run_module.run_research_pipeline(cfg, str(tmp_path / "run"))
    record = report["experiment_record"]
    assert record["strategy"] == "h006_factor_mean_reversion_portfolio"
    assert record["evidence_status"] == "REAL_DATA"
    assert record["information_sources"] == ["factor_mean_reversion"]
    assert record["trials_this_experiment"] == 1
    assert len(report["placebo_null"]) == cfg.research.placebo_runs
    assert len(record["additional_gate_checks"]) == 7
    assert (tmp_path / "run" / "experiment_registry.jsonl").exists()
