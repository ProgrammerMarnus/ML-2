"""Additional audit reproductions. Use a temporary working copy as documented."""
from __future__ import annotations
import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
from quant_research.data.loaders import to_panels
from quant_research.data.snapshots import load_snapshot, dataset_hash
from quant_research.evaluation.metrics import beta
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment

OUT = Path(__file__).resolve().parent
PROJECT = Path('/home/marnus/VS-Code/ML-2')

def write(name, result):
    (OUT/name).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))

def selection():
    from audit_probes import fixture
    from quant_research.strategies.discovery import discover_strategies
    X,y,f,cfg,lt,base=fixture()
    cfg=replace(cfg,research=replace(cfg.research,max_trials=4))
    sets={'a':['a'],'bc':['b','c']}
    original=discover_strategies(X,sets,y,f,cfg)
    start=base.fold_specs[0].test_idx.min()
    mask=f.index>=start
    tries=[]
    for seed in range(4):
        changed=f.copy()
        changed.loc[mask]=np.random.default_rng(seed).normal(0,.02,mask.sum())
        grid=discover_strategies(X,sets,y,changed,cfg)
        tries.append({
            'perturbation_seed':seed,
            'selected_before':int(original.iloc[0].candidate_id),
            'selected_after':int(grid.iloc[0].candidate_id),
            'first_fold_training_returns_unchanged':f.loc[base.fold_specs[0].train_idx].equals(changed.loc[base.fold_specs[0].train_idx]),
            'first_fold_validation_returns_unchanged':f.loc[base.fold_specs[0].val_idx].equals(changed.loc[base.fold_specs[0].val_idx]),
            'baseline_scores':original[['candidate_id','robust_adjusted_score']].to_dict('records'),
            'perturbed_scores':grid[['candidate_id','robust_adjusted_score']].to_dict('records')})
        if tries[-1]['selected_before']!=tries[-1]['selected_after']:
            break
    write('discovery-selection-perturbation.json',tries)

def real():
    import nbformat
    artifact=PROJECT/'artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_results.json'
    previous=json.loads(artifact.read_text())
    ds_hash=previous['experiment_record']['dataset_version']
    snapshot=PROJECT/f'data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_{ds_hash}.parquet'
    raw=load_snapshot(snapshot)
    assert dataset_hash(raw)==ds_hash
    cfg=AppConfig.from_yaml(PROJECT/'configs/real_spy.yaml')
    close,volume=to_panels(raw)
    fwd=close.SPY.shift(-1)/close.SPY-1
    y=(fwd>0).astype(float)
    y[fwd.isna()]=np.nan
    features=build_price_volume_features(close,volume,'SPY')
    result=run_walk_forward(features,y,fwd,cfg)
    summary=summarize_experiment(result)
    comparison={key:{'saved':previous['baseline_summary'][key],'replay':value,'delta':value-previous['baseline_summary'][key]}
                for key,value in summary.items() if key in previous['baseline_summary']}
    positions=result.oos_positions
    risk={'saved_risk':previous['risk'],
          'actual_position_avg':float(positions.abs().mean()),
          'actual_position_max':float(positions.abs().max()),
          'actual_annual_turnover':float(result.folds.oos_turnover.sum()/(len(result.oos_returns)/252)),
          'beta_with_forward_aligned_benchmark':beta(result.oos_returns,fwd.reindex(result.oos_returns.index))}
    turnover=positions.diff().abs()
    turnover.iloc[0]=abs(positions.iloc[0])
    charged=result.folds.oos_turnover.sum()
    boundary={'continuous_turnover':float(turnover.sum()),'sum_charged_fold_turnover':float(charged),
              'unbilled_turnover':float(turnover.sum()-charged),
              'unbilled_fee_plus_slippage':float((turnover.sum()-charged)*6/10000)}
    notebook=nbformat.read(PROJECT/'Institutional_Quant_Research_Engine_V2.1.ipynb',as_version=4)
    nbformat.validate(notebook)
    for i,cell in enumerate(notebook.cells):
        if cell.cell_type=='code':
            compile(cell.source,f'notebook-cell-{i}','exec')
    evidence={'snapshot':str(snapshot),'snapshot_hash_verified':ds_hash,
              'config_fingerprint_matches':cfg.fingerprint()==previous['config_fingerprint'],
              'summary_comparison':comparison,'risk_comparison':risk,'boundary_costs':boundary,
              'notebook_schema_and_compile':'passed',
              'notebook_execution_counts':[c.get('execution_count') for c in notebook.cells if c.cell_type=='code']}
    result.folds.to_csv(OUT/'real-baseline-replay-folds.csv',index=False)
    write('real-baseline-replay.json',evidence)

def lock():
    from quant_research.run import run_research_pipeline
    run_dir=Path(tempfile.mkdtemp(prefix='lock-pipeline-',dir=OUT))
    cfg=AppConfig(
        data=DataConfig(assets=['SPY'],start='2020-01-01',end='2022-01-01',raw_snapshot_dir=str(run_dir/'raw1')),
        evaluation=EvaluationConfig(train_window=120,validation_window=40,test_window=40,step_bars=40,purge_bars=2,embargo_bars=2),
        research=ResearchConfig(threshold_candidates=[.5,.6],placebo_runs=1,bootstrap_samples=20))
    a=run_research_pipeline(cfg,str(run_dir/'artifacts'))
    cfg2=replace(cfg,data=replace(cfg.data,raw_snapshot_dir=str(run_dir/'raw2')),
                 evaluation=replace(cfg.evaluation,test_window=30,step_bars=30))
    b=run_research_pipeline(cfg2,str(run_dir/'artifacts'))
    evidence={'first_test_period':a['experiment_record']['test_period'],
              'second_test_period':b['experiment_record']['test_period'],
              'first_fold_n_test':int(a['folds'].n_test.iloc[0]),
              'second_fold_n_test':int(b['folds'].n_test.iloc[0]),
              'same_output_directory_accepted_changed_test_layout':True,
              'first_experiment':a['experiment_record']['experiment_id'],
              'second_experiment':b['experiment_record']['experiment_id']}
    write('locked-test-pipeline-probe.json',evidence)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['selection','real','lock'])
    args=parser.parse_args()
    {'selection':selection,'real':real,'lock':lock}[args.mode]()
