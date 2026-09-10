"""Offline integration evidence against an isolated, unmodified engine copy."""
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import json
import numpy as np
import pandas as pd
from quant_research.config import AppConfig,DataConfig,EvaluationConfig,ResearchConfig
from quant_research.data.snapshots import load_snapshot,dataset_hash
from quant_research.data.validation import validate_ohlcv
from quant_research.evaluation.metrics import compute_metrics
from quant_research.evaluation.bootstrap import bootstrap_sharpe
from quant_research.evaluation.robustness import assert_cost_accounting
import quant_research.data.loaders as loaders
import quant_research.run as pipeline

ROOT=Path('/home/marnus/VS-Code/ML-2')
OUT=Path(__file__).resolve().parent


def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2,default=str))
    print(name,json.dumps(obj,default=str),flush=True)


def record_info(r):
    e=r['experiment_record']
    return {'experiment_id':e['experiment_id'],'family_id':e['search_family_id'],
        'test_period':e['test_period'],'trials_global':e['n_trials_global'],
        'search_ledger':e['search_ledger'],'promotion':r['promotion'],
        'manifest_path':r['manifest_path'],
        'registry_record_has_manifest_locator':'manifest_path' in e,
        'first_fold_length':int(r['folds'].n_test.iloc[0])}


def synthetic():
    work=OUT/'pipeline-runs'
    cfg=AppConfig(data=DataConfig(start='2020-01-01',end='2022-01-01',
        raw_snapshot_dir=str(work/'first-snapshots')),
        evaluation=EvaluationConfig(train_window=120,validation_window=40,test_window=40,
            step_bars=40,purge_bars=2,embargo_bars=2),
        research=ResearchConfig(threshold_candidates=[.5,.6],placebo_runs=1,bootstrap_samples=20))
    a=pipeline.run_research_pipeline(cfg,str(work/'same-output'))
    b=pipeline.run_research_pipeline(replace(cfg,data=replace(cfg.data,
        raw_snapshot_dir=str(work/'second-snapshots'))),str(work/'other-output'))
    c=pipeline.run_research_pipeline(replace(cfg,data=replace(cfg.data,
        raw_snapshot_dir=str(work/'recut-snapshots')),
        evaluation=replace(cfg.evaluation,test_window=30,step_bars=30)),str(work/'same-output'))
    d=pipeline.run_research_pipeline(replace(cfg,data=replace(cfg.data,
        raw_snapshot_dir=str(work/'delay-snapshots')),
        execution=replace(cfg.execution,signal_delay_bars=5)),str(work/'delay-output'))
    write('pipeline-check-results.json',{'first':record_info(a),'same_family_other_output':record_info(b),
        'recut_same_output':record_info(c),'delay_five':record_info(d),
        'delay_five_grid':d['delay_stress'].to_dict('records'),
        'accepted_changed_geometry':True,
        'recut_creates_new_family':a['search_family_id']!=c['search_family_id'],
        'same_family_shared_across_outputs':a['search_family_id']==b['search_family_id']})


def market():
    old=json.loads((ROOT/'artifacts_real_v4/20260907T192434Z_b7d280a2f7b6276a_results.json').read_text())
    ds=old['experiment_record']['dataset_version']
    path=ROOT/f'data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_{ds}.parquet'
    raw=validate_ohlcv(load_snapshot(path));assert dataset_hash(raw)==ds
    cfg=AppConfig.from_yaml(ROOT/'configs/real_spy.yaml')
    cfg=replace(cfg,data=replace(cfg.data,raw_snapshot_dir=str(OUT/'market-snapshots')))
    captures=[];original=pipeline.run_walk_forward
    def capture(*args,**kwargs):
        res=original(*args,**kwargs);captures.append(res);return res
    # Replace provider download only. Normal load_market_data coverage checks,
    # snapshot writing, fitting, stresses, placebos and gates all execute.
    with patch.object(loaders,'load_yfinance_ohlcv',return_value=raw), \
         patch.object(pipeline,'run_walk_forward',side_effect=capture):
        report=pipeline.run_research_pipeline(cfg,str(OUT/'market-run'))
    base=captures[0];assert_cost_accounting(base,cfg.execution.fee_bps,cfg.execution.slippage_bps)
    p=base.oos_positions;turn=p.diff().abs();turn.iloc[0]=abs(p.iloc[0])
    ledger=pd.DataFrame({'net':base.oos_returns,'gross':base.oos_gross_returns,'position':p,'turnover':turn})
    assert np.isfinite(ledger.to_numpy()).all()
    ledger.to_csv(OUT/'market-executed-ledger.csv')
    prior=pd.read_csv(ROOT/'audit_artifacts/2026-09-09-post-fix/market-executed-ledger.csv',index_col=0)
    prior.index=pd.to_datetime(prior.index,utc=True)
    assert ledger.index.equals(prior.index)
    delta={c:float((ledger[c]-prior[c]).abs().max()) for c in ledger.columns}
    bench=base.predictions.fwd.reindex(ledger.index)
    from sklearn.metrics import log_loss,brier_score_loss
    pred=base.predictions
    buckets=pd.cut(pred.prob,np.linspace(0,1,11),include_lowest=True)
    cal=pred.groupby(buckets,observed=True).agg(n=('y','size'),mean_probability=('prob','mean'),fraction_positive=('y','mean'))
    ece=float((cal.n*(cal.mean_probability-cal.fraction_positive).abs()).sum()/len(pred))
    fees=[]
    for fee in [0.,2.,5.,10.,20.]:
        ret=base.oos_gross_returns-turn*(fee+cfg.execution.slippage_bps)/10000
        fees.append({'fee_bps':fee,'slippage_bps':cfg.execution.slippage_bps,**compute_metrics(ret)})
    write('market-replay-results.json',{
        'snapshot':str(path),'dataset_hash':ds,'provider_download_stubbed':True,
        'normal_loader_coverage_check_executed':True,'baseline_summary':report['baseline_summary'],
        'strategy_metrics':compute_metrics(base.oos_returns,base.oos_gross_returns,p,bench),
        'buy_hold_same_intervals':compute_metrics(bench),
        'bootstrap_2000':bootstrap_sharpe(base.oos_returns,n_samples=2000),
        'placebo_modes':report['placebo_mode_statistics'],'promotion':report['promotion'],
        'n_oos':len(ledger),'n_source_bars':len(raw)//2,'first_oos':str(ledger.index[0]),
        'last_oos':str(ledger.index[-1]),'last_raw':str(raw.timestamp.max()),
        'positive_folds':int((base.folds.oos_sharpe>0).sum()),
        'negative_folds':int((base.folds.oos_sharpe<0).sum()),
        'undefined_folds':int(base.folds.oos_sharpe.isna().sum()),
        'same_scored_index_as_prior':True,'max_abs_ledger_delta':delta,
        'all_ledger_values_finite':True,'accounting_invariants_pass':True,
        'cost_sensitivity':fees,'regimes':report['regime'].to_dict('records'),
        'calibration':{'brier':brier_score_loss(pred.y,pred.prob),
            'log_loss':log_loss(pred.y,pred.prob),'ece':ece,'buckets':cal.reset_index(drop=True).to_dict('records')},
        'risk':report['risk'],'experiment':record_info(report)})


if __name__=='__main__':
    import sys
    {'synthetic':synthetic,'market':market}[sys.argv[1]]()
