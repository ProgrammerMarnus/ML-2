"""Offline full-pipeline checks. Product computations are unchanged.

real: reuse a verified existing market snapshot; replace only download and
snapshot-write I/O, capture the normal baseline object for reconciliation.
lock: complete two ordinary synthetic runs in one registry with changed folds.
"""
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import argparse
import json
import numpy as np
import pandas as pd

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
from quant_research.data.snapshots import load_snapshot, dataset_hash
from quant_research.data.validation import validate_ohlcv
from quant_research.evaluation.robustness import assert_cost_accounting
from quant_research.evaluation.metrics import compute_metrics
import quant_research.run as pipeline

OUT = Path(__file__).resolve().parent
PROJECT = Path('/home/marnus/VS-Code/ML-2')


def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2,default=str)+'\n')
    print(json.dumps(obj,indent=2,default=str),flush=True)


def real():
    oldpath = PROJECT/'artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_results.json'
    old = json.loads(oldpath.read_text())
    ds = old['experiment_record']['dataset_version']
    path = PROJECT/f'data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_{ds}.parquet'
    meta = json.loads(path.with_suffix('.meta.json').read_text())
    raw = validate_ohlcv(load_snapshot(path))
    assert dataset_hash(raw) == ds
    cfg = AppConfig.from_yaml(PROJECT/'configs/real_spy.yaml')
    captured = {}
    original = pipeline.run_walk_forward
    def capture(*args,**kw):
        result = original(*args,**kw)
        if 'baseline' not in captured:
            captured['baseline'] = result
        return result
    with patch.object(pipeline,'load_market_data',return_value=(raw,old['data_meta'])), \
         patch.object(pipeline,'save_snapshot',return_value=meta), \
         patch.object(pipeline,'run_walk_forward',side_effect=capture):
        report = pipeline.run_research_pipeline(cfg,str(OUT/'market_snapshot_run'))
    res = captured['baseline']
    assert_cost_accounting(res,cfg.execution.fee_bps,cfg.execution.slippage_bps)
    assert np.isfinite(res.oos_returns.to_numpy()).all()
    assert np.isfinite(res.oos_gross_returns.to_numpy()).all()
    assert np.isfinite(res.oos_positions.to_numpy()).all()
    pos=res.oos_positions
    turn=pos.diff().abs();turn.iloc[0]=abs(pos.iloc[0])
    aligned = pd.DataFrame({'net':res.oos_returns,'gross':res.oos_gross_returns,'position':pos,'turnover':turn})
    aligned.to_csv(OUT/'market-executed-ledger.csv')
    diffs = {k:{'saved':old['baseline_summary'][k],'current':v,'delta':v-old['baseline_summary'][k]}
             for k,v in report['baseline_summary'].items() if k in old['baseline_summary']}
    oldfold=pd.read_csv(PROJECT/'artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_folds.csv')
    fold_deltas=[]
    for (_,a),(_,b) in zip(oldfold.iterrows(),res.folds.iterrows()):
        fold_deltas.append({'fold_id':int(b.fold_id),
            **{k:float(b[k]-a[k]) for k in ('threshold','oos_sharpe','oos_max_dd','oos_turnover','oos_net_return','oos_auc','oos_brier')}})
    bench=res.predictions.fwd.reindex(res.oos_returns.index)
    data={
        'snapshot':str(path),'dataset_hash':ds,'snapshot_hash_verified':True,
        'no_downloads':True,'no_new_original_snapshot':True,
        'config':cfg.to_dict(),'config_fingerprint':cfg.fingerprint(),
        'old_config_fingerprint':old['config_fingerprint'],
        'experiment_id':report['experiment_record']['experiment_id'],
        'all_executed_ledger_values_finite':True,'cost_accounting_passes':True,
        'summary_deltas':diffs,'fold_deltas':fold_deltas,
        'current_summary':report['baseline_summary'],'current_risk':report['risk'],
        'strategy_metrics':compute_metrics(res.oos_returns,res.oos_gross_returns,pos,bench),
        'buy_hold_same_scored_intervals':compute_metrics(bench),
        'bootstrap':report['bootstrap'],'placebo_modes':report['placebo_mode_statistics'],
        'promotion':report['promotion'],'positive_folds':int((res.folds.oos_sharpe>0).sum()),
        'negative_folds':int((res.folds.oos_sharpe<0).sum()),'undefined_folds':int(res.folds.oos_sharpe.isna().sum()),
        'n_oos':len(pos),'first_oos':str(pos.index[0]),'last_oos':str(pos.index[-1]),
        'last_raw':str(raw.timestamp.max())}
    write('market-replay-analysis.json',data)


def lock():
    root=OUT/'test_lock_runs'
    cfg=AppConfig(data=DataConfig(start='2020-01-01',end='2022-01-01',raw_snapshot_dir=str(root/'raw1')),
        evaluation=EvaluationConfig(train_window=120,validation_window=40,test_window=40,step_bars=40,purge_bars=2,embargo_bars=2),
        research=ResearchConfig(threshold_candidates=[.5,.6],placebo_runs=1,bootstrap_samples=20))
    a=pipeline.run_research_pipeline(cfg,str(root/'registry'))
    cfg2=replace(cfg,data=replace(cfg.data,raw_snapshot_dir=str(root/'raw2')),
                 evaluation=replace(cfg.evaluation,test_window=30,step_bars=30))
    b=pipeline.run_research_pipeline(cfg2,str(root/'registry'))
    write('pipeline-lock-analysis.json',{'changed_test_layout_accepted_in_same_registry':True,
        'first_experiment':a['experiment_record']['experiment_id'],
        'second_experiment':b['experiment_record']['experiment_id'],
        'first_test_period':a['experiment_record']['test_period'],
        'second_test_period':b['experiment_record']['test_period'],
        'first_fold_length':int(a['folds'].n_test.iloc[0]),'second_fold_length':int(b['folds'].n_test.iloc[0])})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['real','lock'])
    {'real':real,'lock':lock}[p.parse_args().mode]()
