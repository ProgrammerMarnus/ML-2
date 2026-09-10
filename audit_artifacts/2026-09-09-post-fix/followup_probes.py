"""Recheck legacy discovery and additional boundary contracts on current source."""
import sys
import json
import warnings
import importlib.util
from pathlib import Path
from dataclasses import replace
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import pandas as pd
from quant_research.config import ExecutionConfig,PromotionConfig
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.robustness import replay_oos,missing_data_stress
from quant_research.experiments.promotion import evaluate_gates,promotion_decision
from quant_research.strategies.baseline import run_walk_forward
from quant_research.features.information import build_information_features

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.OUT=OUT
    return m
old=module(ROOT/'audit_artifacts/2026-09-09/audit_probes.py','prior_probes')
new=module(OUT/'audit_probes.py','current_probes')
results={}
def record(k,v):
    results[k]=v
    (OUT/'followup-results.json').write_text(json.dumps(results,indent=2,default=str)+'\n')
    print(k,json.dumps(v,default=str),flush=True)

warnings.filterwarnings('ignore')
record('legacy_discovery',old.legacy_discovery())
record('legacy_discovery_accounting',old.discovery_accounting())
record('statistical_controls',old.statistical_repairs())
record('block_permutation_control',old.block_fixed())
X,y,f,cfg=new.cfg_and_data()
base=run_walk_forward(X,y,f,cfg,feature_subset=['a'],risk_returns=f.shift(1)*.1,hold_bars=5)
rep=replay_oos(X,y,f,cfg,base,None)
record('subset_custom_risk_hold_replay',{'prob_equal':base.predictions.prob.equals(rep.predictions.prob),'positions_equal':base.oos_positions.equals(rep.oos_positions),'net_equal':base.oos_returns.equals(rep.oos_returns)})
# A negative target reverses a nominally long direction.
bt=backtest(pd.Series(1.,index=f.index),f,ExecutionConfig(target_vol=-.1),risk_returns=f.shift(1))
record('negative_target_position',{'minimum_position':float(bt.positions.min()),'short_bars':int((bt.positions<0).sum())})
# Non-finite returns are not valid realizations; the API currently drops them
# from metric calculations while retaining them in the executable ledger.
bad=f.copy();bad.iloc[160]=np.inf
res=run_walk_forward(X,y,bad,cfg)
record('nonfinite_forward_return',{'infinite_ledger_rows':int(np.isinf(res.oos_returns).sum()),'reported_fold_sharpes':res.folds.oos_sharpe.tolist()})
# Family evidence with omitted ledger count remains promotable.
summary=dict(median_oos_sharpe=1.,mean_oos_sharpe=1.,full_oos_max_dd=-.1,single_fold_share=.25,annual_turnover=20.)
rob={'cost_stress':[dict(fee_bps=20.,sharpe=1.)],'delay_stress':[dict(delay_bars=3,sharpe=1.)]}
null=dict(percentile=1.,adjusted_p=1/21,n_runs=20)
record('family_gate_no_ledger',{str(n):promotion_decision(evaluate_gates(summary,rob,{'positive_prob':.9},null,True,True,1000000,PromotionConfig(),n_family_searches=n)) for n in (0,1,2)})
# Every event/bar resolution pair uses the same logical timestamps.
idx=pd.date_range('2024-01-05',periods=10,tz='UTC');matrix={}
for eu in ('s','ms','us','ns'):
    ev=pd.DataFrame([new.event()])
    for col in ('event_time','publication_time','availability_time'):
        ev[col]=ev[col].dt.as_unit(eu)
    for bu in ('s','ms','us','ns'):
        result=build_information_features(idx.as_unit(bu),ev,'SPY')
        nonzero=result.index[result.info_attention>0]
        matrix[f'events={eu},bars={bu}']=str(nonzero[0]) if len(nonzero) else None
record('timestamp_16_combinations',matrix)
