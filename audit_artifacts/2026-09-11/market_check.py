"""Offline reproduction of an existing saved-market experiment's baseline."""
import json
from pathlib import Path
import numpy as np
from quant_research.config import AppConfig
from quant_research.data.snapshots import load_snapshot, dataset_hash
from quant_research.data.validation import validate_ohlcv, missing_data_report
from quant_research.data.loaders import to_price_panels
from quant_research.features.price_volume import build_price_volume_features, build_signal_extensions
from quant_research.features.leakage import feature_leakage_report
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment
from quant_research.evaluation.robustness import replay_oos, assert_cost_accounting

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
manifest_path = next(root.joinpath("artifacts_stab_seed7").glob("*_manifest.json"))
manifest = json.loads(manifest_path.read_text())
cfg = AppConfig.from_dict(manifest["configuration"])
snap = manifest["inputs"]["market_data"]
data = validate_ohlcv(load_snapshot(root / snap["path"]))
assert dataset_hash(data, full=True) == snap["dataset_hash_full"]
open_, high, low, close, volume = to_price_panels(data)
X = build_price_volume_features(close, volume, cfg.data.target).join(
    build_signal_extensions(open_, high, low, close, volume, cfg.data.target))
fwd = close[cfg.data.target].shift(-1) / close[cfg.data.target] - 1
y = (fwd > 0).astype(float).where(fwd.notna())
baseline = run_walk_forward(X, y, fwd, cfg)
replay = replay_oos(X, y, fwd, cfg, baseline, None)
assert_cost_accounting(baseline, cfg.execution.fee_bps, cfg.execution.slippage_bps)
assert_cost_accounting(replay, cfg.execution.fee_bps, cfg.execution.slippage_bps)
results = {
    "reference_manifest": str(manifest_path), "snapshot": snap,
    "missing_sessions": missing_data_report(data).to_dict("records"),
    "leakage": feature_leakage_report(close, volume, cfg.data.target, open_=open_, high=high, low=low),
    "baseline_summary": summarize_experiment(baseline),
    "replay_positions_equal": baseline.oos_positions.equals(replay.oos_positions),
    "replay_net_equal": baseline.oos_returns.equals(replay.oos_returns),
    "reference_max_probability_difference": float(np.max(np.abs(
        baseline.predictions.prob.to_numpy()-np.asarray(manifest["predictions"]["prob"])))),
    "reference_max_net_difference": float(np.max(np.abs(
        baseline.oos_returns.to_numpy()-np.asarray(manifest["returns"]["net"])))),
    "environment_reference": manifest["code"]["dependencies"],
}
baseline.folds.to_csv(out / "saved-market-folds.csv", index=False)
out.joinpath("market-results.json").write_text(json.dumps(results, indent=2, default=str)+"\n")
print(json.dumps(results, indent=2, default=str))
