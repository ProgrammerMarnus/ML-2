"""Fresh full-pipeline probes, using isolated synthetic snapshots and output dirs."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import pandas as pd
from quant_research.config import AppConfig,DataConfig,EvaluationConfig,ResearchConfig
from quant_research.data.loaders import load_market_data
from quant_research.data.snapshots import load_snapshot,dataset_hash
from quant_research.data.validation import validate_ohlcv
from quant_research.experiments.registry import SearchLedger
import quant_research.run as pipeline

RESULTS={}
def save(name,value):
    RESULTS[name]=value
    (OUT/'pipeline-probe-results.json').write_text(json.dumps(RESULTS,indent=2,default=str)+'\n')
    print(name,json.dumps(value,default=str),flush=True)

def run(name,cfg,out):
    cfg=replace(cfg,data=replace(cfg.data,raw_snapshot_dir=str(OUT/'synthetic_snapshots'/name)))
    result=pipeline.run_research_pipeline(cfg,str(out))
    manifest=json.loads(Path(result['manifest_path']).read_text())
    rec=result['experiment_record']
    save(name,dict(experiment_id=rec['experiment_id'],family_id=rec['search_family_id'],
        family_count=SearchLedger(rec['search_ledger']).family_search_count(rec['search_family_id']),
        test_period=rec['test_period'],fold_rows=result['folds'].n_test.tolist(),
        ledger_path=rec['search_ledger'],manifest_path=result['manifest_path'],
        versions=manifest['code']['dependencies'],actual_numpy=np.__version__,
        state=rec['promotion_state'],failed_gates=rec['failed_gates'],
        per_run_threshold_trials=rec['trials_this_experiment'],
        search_entries=SearchLedger(rec['search_ledger']).read_all(),
        manifest_feature_keys=list(manifest['inputs']['features']),
        manifest_event_keys=list(manifest['inputs']['events']),
        manifest_fold_keys=list(manifest['folds']['fold_specs'][0]),
        manifest_model_sample=next(iter(manifest['fitted_models'].values()))))
    return result

if __name__=='__main__':
    warnings.filterwarnings('ignore',category=UserWarning)
    warnings.filterwarnings('ignore',category=RuntimeWarning)
    cfg=AppConfig(data=DataConfig(start='2020-01-01',end='2022-01-01'),
        evaluation=EvaluationConfig(train_window=120,validation_window=40,test_window=40,step_bars=40,purge_bars=2,embargo_bars=2),
        research=ResearchConfig(threshold_candidates=[.5,.6],placebo_runs=1,bootstrap_samples=20))
    a=run('first',cfg,OUT/'pipeline_runs'/'same_output')
    b=run('repeat_new_output',cfg,OUT/'pipeline_runs'/'different_output')
    c=run('recut_same_output',replace(cfg,evaluation=replace(cfg.evaluation,test_window=30,step_bars=30)),OUT/'pipeline_runs'/'same_output')
    save('cross_run_checks',dict(same_family_new_output=a['search_family_id']==b['search_family_id'],
        recut_accepted=True,manifest_overwritten=json.loads(Path(a['manifest_path']).read_text())['experiment']['experiment_id']!=a['experiment_record']['experiment_id'],
        persisted_test_lock_files=[str(p) for p in (OUT/'pipeline_runs').rglob('*') if 'lock' in p.name and not p.name.endswith('counter.json.lock')]))
    # Check the real loader without provider access: stub ONLY the download,
    # retaining the full post-download completeness/validation path.
    cfg_real=AppConfig.from_yaml(ROOT/'configs/real_spy.yaml')
    p=ROOT/'data/raw_snapshots/20260907T192329Z_yfinance_ohlcv_b0e94186f465bc47.parquet'
    raw=validate_ohlcv(load_snapshot(p))
    assert dataset_hash(raw)=='b0e94186f465bc47'
    with patch('quant_research.data.loaders.load_yfinance_ohlcv',return_value=raw):
        try:
            load_market_data(cfg_real.data)
        except Exception as exc:
            save('documented_real_config_loader',dict(accepted=False,error=f'{type(exc).__name__}: {exc}'))
        else:
            save('documented_real_config_loader',dict(accepted=True))
    # Exercise the entire configured-delay path, including orchestration anchors.
    delayed=replace(cfg,execution=replace(cfg.execution,signal_delay_bars=1),
        data=replace(cfg.data,raw_snapshot_dir=str(OUT/'synthetic_snapshots'/'delay')))
    try:
        pipeline.run_research_pipeline(delayed,str(OUT/'pipeline_runs'/'delay'))
    except Exception as exc:
        save('full_pipeline_delay',dict(completed=False,error=f'{type(exc).__name__}: {exc}'))
    else:
        save('full_pipeline_delay',dict(completed=True))
