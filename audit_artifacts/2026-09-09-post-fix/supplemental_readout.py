"""Audit-only bootstrap/calibration/benchmark readout from the saved run manifest."""
import sys
import json
from pathlib import Path
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT.parents[1]/'src'))
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss,brier_score_loss
from quant_research.evaluation.bootstrap import bootstrap_sharpe
from quant_research.evaluation.metrics import compute_metrics

m=json.loads((OUT/'market_snapshot_run/run_manifest.json').read_text())
idx=pd.to_datetime(m['predictions']['index'],utc=True)
p=np.array(m['predictions']['prob']);y=np.array(m['predictions']['y'])
fwd=pd.Series(m['predictions']['fwd'],index=idx)
net=pd.Series(m['returns']['net'],index=idx)
positions=pd.Series(m['positions']['position'],index=idx)
reliability=[];ece=0.
for k in range(10):
    mask=(p>=k/10)&((p<(k+1)/10) if k<9 else (p<=1))
    count=int(mask.sum())
    if count:
        mp=float(p[mask].mean());freq=float(y[mask].mean())
        ece+=count/len(p)*abs(mp-freq)
        reliability.append({'bin':f'{k/10:.1f}-{(k+1)/10:.1f}','n':count,
            'mean_probability':mp,'observed_positive_fraction':freq})
folds=[]
fold_file=OUT/'market_snapshot_run'/f"{m['experiment']['experiment_id']}_folds.csv"
for row in pd.read_csv(fold_file).to_dict('records'):
    mask=np.asarray(m['predictions']['fold'])==str(int(row['fold_id']))
    benchmark=compute_metrics(fwd.iloc[np.flatnonzero(mask)])
    folds.append({'fold_id':row['fold_id'],'strategy_sharpe':row['oos_sharpe'],
        'strategy_return':row['oos_net_return'],'buy_hold_sharpe':benchmark['sharpe'],
        'buy_hold_return':benchmark['total_return']})
r={'bootstrap_2000':bootstrap_sharpe(net,n_samples=2000,seed=42),
    'calibration_raw':{'pooled_brier':brier_score_loss(y,p),'log_loss':log_loss(y,p),
        'ece_10_equal_width_bins':ece,'reliability':reliability},
    'time_in_market':float((positions!=0).mean()),'folds_vs_benchmark':folds,
    'calibrator':'not implemented for this baseline',
    'ensemble':'not applicable: single logistic model per fold'}
(OUT/'supplemental-readout.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r,indent=2))
