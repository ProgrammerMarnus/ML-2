"""Shared test helpers (imported by test modules via tests dir on sys.path)."""


def valid_record(**overrides):
    """A complete, registry-valid experiment record for tests."""
    base = {
        "strategy": "test_strategy",
        "features": ["momentum_63"],
        "universe": ["SPY"],
        "target": "SPY",
        "timeframe": "1d",
        "train_period": ["2020-01-01", "2021-01-01"],
        "validation_period": ["2021-01-01", "2021-06-01"],
        "test_period": ["2021-06-01", "2022-01-01"],
        "trials": 3,
        "dataset_version": "abc123",
        "feature_version": "def456",
        "strategy_version": "1.0",
        "code_version": "V2.1.0",
        "seed": 42,
        "gross_metrics": {"sharpe": 0.5},
        "net_metrics": {"sharpe": 0.4},
        "costs": {"fee_bps": 5},
        "slippage": {"bps": 1},
        "oos_metrics": {"mean_oos_sharpe": 0.4},
        "bootstrap_interval": {"lo": -0.2, "hi": 0.8},
        "robustness": {
            "survives_cost_stress": True,
            "survives_delay_stress": True,
            "cost_stress": [],
            "delay_stress": [],
            "slippage_stress": [],
            "parameter_perturbation": [],
            "missing_data": [],
        },
        "placebo_statistics": {"percentile": 0.97},
        "information_sources": ["price_volume"],
        "promotion_state": "RESEARCH_ONLY",
    }
    base.update(overrides)
    return base
