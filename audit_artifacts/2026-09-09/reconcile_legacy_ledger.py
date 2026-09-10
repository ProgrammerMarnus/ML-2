"""Explain all current-vs-saved baseline economics using fold execution state."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from quant_research.config import AppConfig
from quant_research.data.snapshots import load_snapshot
from quant_research.data.loaders import to_panels
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.metrics import sharpe_ratio

OUT=Path(__file__).resolve().parent
ROOT=Path('/home/marnus/VS-Code/ML-2')
saved=json.loads((ROOT/'artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_results.json').read_text())
ds=saved['experiment_record']['dataset_version']
raw=load_snapshot(ROOT/f'data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_{ds}.parquet')
close,volume=to_panels(raw)
X=build_price_volume_features(close,volume,'SPY')
f=close.SPY.shift(-1)/close.SPY-1.
y=(f>0).astype(float);y[f.isna()]=np.nan
cfg=AppConfig.from_yaml(ROOT/'configs/real_spy.yaml')
current=run_walk_forward(X,y,f,cfg)
pieces=[]
for spec in current.fold_specs:
    te=spec.test_idx
    bt=backtest(current.predictions.loc[te,'prob'],f.loc[te],cfg.execution,
                threshold=current.thresholds[spec.fold_id],risk_returns=f.shift(1))
    pieces.append(pd.DataFrame({'net':bt.net_returns,'gross':bt.gross_returns,
                               'position':bt.positions,'turnover':bt.turnover}))
legacy=pd.concat(pieces).sort_index()
values={'full_oos_net_sharpe':sharpe_ratio(legacy.net),'full_oos_gross_sharpe':sharpe_ratio(legacy.gross),
        'full_oos_net_return':float((1+legacy.net).prod()-1),
        'full_oos_gross_return':float((1+legacy.gross).prod()-1),
        'fee_cost':float(legacy.turnover.sum())*cfg.execution.fee_bps/10000,
        'slippage_cost':float(legacy.turnover.sum())*cfg.execution.slippage_bps/10000}
for k,v in values.items():
    np.testing.assert_allclose(v,saved['baseline_summary'][k],rtol=0,atol=1e-12)
turn=current.oos_positions.diff().abs();turn.iloc[0]=abs(current.oos_positions.iloc[0])
new=pd.DataFrame({'net':current.oos_returns,'gross':current.oos_gross_returns,
                  'position':current.oos_positions,'turnover':turn})
delta=(new-legacy).abs()
changed=delta.index[(delta>1e-12).any(axis=1)]
starts={spec.test_idx[0] for spec in current.fold_specs}
adjacent={spec.test_idx[1] for spec in current.fold_specs}
assert set(changed) <= starts | adjacent
rows=[{'timestamp':str(t),'old':legacy.loc[t].to_dict(),'current':new.loc[t].to_dict()} for t in changed]
result={'legacy_reset_ledger_matches_saved_economics':True,
        'legacy_reconstructed_summary':values,'changed_bars':rows,
        'all_changes_at_fold_start_or_following_bar':True,
        'classification':'EXPECTED: same predictions/thresholds; continuous signal and position state replaces fold restarts. No unexplained baseline economic differences.'}
(OUT/'ledger-delta-explanation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2),flush=True)
