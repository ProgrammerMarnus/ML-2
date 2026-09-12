"""Additional bounded integrity and regression checks; writes only audit evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_research.config import AppConfig, EvaluationConfig, ModelConfig, ResearchConfig
from quant_research.experiments.registry import SearchLedger
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.strategies.discovery import discover_and_evaluate_oos
from quant_research.strategies.baseline import run_walk_forward

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
results = {}
idx = pd.bdate_range("2020-01-01", periods=244, tz="UTC")
rng = np.random.default_rng(810)
X = pd.DataFrame(rng.normal(size=(len(idx), 3)), index=idx, columns=["a", "b", "c"])
fwd = pd.Series(rng.normal(0.001, 0.009, len(idx)), index=idx)
y = (fwd > 0).astype(float)
cfg = AppConfig(evaluation=EvaluationConfig(train_window=60, validation_window=30,
    test_window=30, step_bars=30, purge_bars=2, embargo_bars=2),
    model=ModelConfig(type="logistic"),
    research=ResearchConfig(max_trials=2, threshold_candidates=[0.0], hold_candidates=[1]))
folds = walk_forward_splits(idx, cfg.evaluation)


def fake_validation(*args, **kwargs):
    score = -2.0 if args[5] == "logistic" else np.nan
    thresholds = {f.fold_id: 0.0 for f in folds}
    scores = {f.fold_id: score for f in folds}
    dds = {f.fold_id: -0.1 for f in folds}
    return score, -0.1, 0.0, thresholds, scores, dds


with patch("quant_research.strategies.discovery._validation_sharpe", side_effect=fake_validation):
    r = discover_and_evaluate_oos(X, {"all": list(X)}, y, fwd, cfg)
results["nonfinite_discovery_ranking"] = {
    "candidate_validation_scores": {"logistic": -2.0, "gradient_boosting": "NaN"},
    "selected_model_types": r.folds.model_type.tolist(),
    "selected_validation_scores": r.folds.validation_sharpe.tolist(),
}

snapshots = sorted(ROOT.joinpath("data/raw_snapshots").glob("*yfinance*.parquet"))[-2:]
panels = [pd.read_parquet(p).sort_values(["timestamp", "symbol"]).reset_index(drop=True) for p in snapshots]
nums = ["open", "high", "low", "close", "volume"]
results["saved_market_family_fragmentation"] = {
    "snapshots": [str(p) for p in snapshots],
    "same_symbol_timestamps": panels[0][["timestamp", "symbol"]].equals(panels[1][["timestamp", "symbol"]]),
    "maximum_absolute_differences": (panels[0][nums]-panels[1][nums]).abs().max().to_dict(),
    "records": [],
}
for p in sorted(ROOT.glob("artifacts_stab_seed*/*results.json")):
    r = json.loads(p.read_text())
    e = r["experiment_record"]
    results["saved_market_family_fragmentation"]["records"].append({
        "path": str(p), "family": e["search_family_id"], "dataset": e["dataset_version"],
        "ledger": e["search_ledger"], "global_trials": e["n_trials_global"],
        "family_gate": [x for x in r["promotion"]["detail"] if "family" in x],
    })

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    p = td / "test_lock.json"
    lock = LockedTestProtocol(p, dataset_id="A", config_fingerprint="policy")
    lock.verify(folds)
    fixed = {}
    for name, action in [
        ("incompatible_dataset_rejected", lambda: LockedTestProtocol(p, dataset_id="B", config_fingerprint="policy")),
        ("incompatible_policy_rejected", lambda: LockedTestProtocol(p, dataset_id="A", config_fingerprint="other")),
    ]:
        try: action(); fixed[name] = False
        except Exception as e: fixed[name] = type(e).__name__
    p.write_text("{broken")
    try: LockedTestProtocol(p); fixed["invalid_json_rejected"] = False
    except Exception as e: fixed["invalid_json_rejected"] = type(e).__name__
    ff = fwd.copy()
    ff.loc[folds[0].test_idx[-1]] = np.nan
    try: run_walk_forward(X, y, ff, cfg); fixed["interior_fold_end_nan_rejected"] = False
    except Exception as e: fixed["interior_fold_end_nan_rejected"] = type(e).__name__
    ff.loc[folds[0].test_idx[-1]] = np.inf
    try: run_walk_forward(X, y, ff, cfg); fixed["interior_fold_end_infinity_rejected"] = False
    except Exception as e: fixed["interior_fold_end_infinity_rejected"] = type(e).__name__
    results["confirmed_prior_fixes"] = fixed

# Load the helper without running its CLI or calling Cline.
import runpy
runner = runpy.run_path(str(ROOT / "cline-runner.py"), run_name="audit_module")
results["runner_classifier"] = {
    text: runner["classify_output"](0, text).__dict__
    for text in ["Task completed. Added HTTP 403 and 429 regression tests.",
                 "Task completed successfully."]
}
results["runner_self_test"] = subprocess.run(
    ["python", str(ROOT / "cline-runner.py"), "--self-test"], capture_output=True, text=True).stdout
OUT.joinpath("followup-results.json").write_text(json.dumps(results, indent=2, default=str)+"\n")
print(json.dumps(results, indent=2, default=str))
