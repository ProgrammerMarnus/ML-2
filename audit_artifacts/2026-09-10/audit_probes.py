"""Fresh audit probes; writes only into this audit directory and /tmp.

Run with PYTHONPATH pointing to the byte-identical isolated source copy.
Exceptions are recorded as evidence, not interpreted as passing regressions.
"""
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import json
import tempfile
import traceback

import numpy as np
import pandas as pd

from quant_research.config import (
    AppConfig, DataConfig, EvaluationConfig, ResearchConfig, ModelConfig,
    PromotionConfig,
)
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels, load_market_data
from quant_research.data.validation import expected_sessions, missing_data_report
from quant_research.data.schemas import DataValidationError
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.evaluation.metrics import compute_metrics
from quant_research.experiments.registry import SearchLedger, TrialCounter
from quant_research.experiments.promotion import evaluate_gates, promotion_decision
from quant_research.features.price_volume import build_price_volume_features
from quant_research.features.information import build_information_features
from quant_research.features.point_in_time import validate_events
from quant_research.features.parkinson import lagged_parkinson_volatility
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment
import quant_research.strategies.discovery as discovery
import quant_research.evaluation.robustness as robustness

OUT = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix='ml2-audit-probes-'))
RESULTS = {}


def probe(name, fn):
    try:
        result = fn()
        RESULTS[name] = {'status': 'completed', 'evidence': result}
    except Exception as exc:
        RESULTS[name] = {'status': 'exception', 'type': type(exc).__name__,
                         'error': str(exc), 'traceback': traceback.format_exc()}
    (OUT / 'probe-results.json').write_text(json.dumps(RESULTS, indent=2, default=str))
    print(name, json.dumps(RESULTS[name], default=str), flush=True)


CFG = AppConfig(
    data=DataConfig(start='2020-01-01', end='2022-01-01', raw_snapshot_dir=str(TMP/'snapshots')),
    evaluation=EvaluationConfig(train_window=120, validation_window=40,
        test_window=40, step_bars=40, purge_bars=2, embargo_bars=2),
    research=ResearchConfig(threshold_candidates=[.5,.6], hold_candidates=[1],
        max_trials=1, placebo_runs=1, bootstrap_samples=20))
RAW = generate_synthetic_ohlcv(['SPY'], CFG.data.start, CFG.data.end)
CLOSE, VOLUME = to_panels(RAW)
X = build_price_volume_features(CLOSE, VOLUME, 'SPY')
FWD = CLOSE.SPY.shift(-1)/CLOSE.SPY-1
Y = (FWD > 0).astype(float).mask(FWD.isna())
BASE = run_walk_forward(X,Y,FWD,CFG)


def locks():
    folds=walk_forward_splits(X.index,CFG.evaluation)
    revised=replace(CFG.evaluation,test_window=30,step_bars=30)
    recut=walk_forward_splits(X.index,revised)
    cases={}
    for case in ['same_policy_recut','changed_policy_recut','changed_dataset','corrupt_json']:
        p=TMP/f'{case}.lock'
        LockedTestProtocol(p,dataset_id='A',config_fingerprint='original').verify(folds)
        if case=='corrupt_json': p.write_text('{bad-json')
        instance=LockedTestProtocol(p,dataset_id='B' if case=='changed_dataset' else 'A',
            config_fingerprint='revised' if case=='changed_policy_recut' else 'original')
        frozen=instance.frozen
        try:
            instance.verify(recut if 'recut' in case or case=='corrupt_json' else folds)
            cases[case]={'accepted':True,'frozen_before_verify':frozen,
                         'persisted':json.loads(p.read_text())}
        except Exception as exc:
            cases[case]={'accepted':False,'type':type(exc).__name__,'error':str(exc)}
    for case in cases.values():
        if 'persisted' in case:
            p=case['persisted']; case['persisted']={k:p[k] for k in ['hash','dataset_id','config_fingerprint','n_folds']}
    return cases


def passing_gates(n):
    summary={'median_oos_sharpe':1.,'mean_oos_sharpe':1.,'full_oos_max_dd':-.1,
             'single_fold_share':.3,'annual_turnover':10.}
    rob={'cost_stress':[{'fee_bps':10.,'sharpe':1.}],
         'delay_stress':[{'delay_bars':1,'sharpe':1.}]}
    return promotion_decision(evaluate_gates(summary,rob,{'positive_prob':.9},
        {'percentile':1.,'adjusted_p':1/21,'n_runs':20},True,True,1,PromotionConfig(),
        n_family_searches=n))


def attempts():
    ledger=SearchLedger(TMP/'attempts.jsonl')
    ledger.record_start('f','abandoned',10)
    start=ledger.record_start('f','completed',10)
    ledger.record_outcome('f','completed',10,'completed',attempt_id=start['attempt_id'])
    completed=ledger.family_search_count('f'); all_attempts=ledger.family_attempt_count('f')
    return {'started_entries':len(ledger.family_started_attempts('f')),
        'pipeline_count_method':completed,'all_attempts_method':all_attempts,
        'pipeline_count_gate':passing_gates(completed),
        'all_attempts_gate':passing_gates(all_attempts),'missing_history_gate':passing_gates(0)}


def corrupt_ledger():
    ledger=SearchLedger(TMP/'corrupt-ledger.jsonl')
    entry=ledger.record_start('f','abandoned',10)
    ledger.path.write_text('{truncated JSON')
    return {'read_all':ledger.read_all(),'attempt_count':ledger.family_attempt_count('f'),
            'promotion_state':passing_gates(ledger.family_search_count('f'))['state']}


def missing_baseline():
    boundary=BASE.fold_specs[0].test_idx[-1]
    evidence={}
    for val, name in [(np.nan,'nan_at_fold_end'),(np.inf,'inf_at_fold_end'),
                      (np.nan,'nan_inside_fold')]:
        t=BASE.fold_specs[0].test_idx[10] if name=='nan_inside_fold' else boundary
        bad=FWD.copy(); bad.loc[t]=val
        try:
            result=run_walk_forward(X,Y,bad,CFG, fitted_models=BASE.fitted_models,
                fixed_thresholds={s.fold_id:0. for s in BASE.fold_specs})
            p=result.oos_positions
            evidence[name]={'accepted':True,'n_oos':len(result.oos_returns),
                'bad_timestamp':str(t),'bad_timestamp_scored':t in result.oos_returns.index,
                'finite_returns':bool(np.isfinite(result.oos_returns).all()),
                'positions_around_gap':{str(k):float(v) for k,v in
                    (p.loc[:t].tail(2).to_dict()|p.loc[t:].head(2).to_dict()).items()},
                'reported_metrics':summarize_experiment(result)}
        except Exception as exc:
            evidence[name]={'accepted':False,'error':str(exc),'type':type(exc).__name__}
    return evidence


def nested_missing():
    cols={'small':['trend_50','realized_vol_20','volume_zscore_20']}
    a=discovery.discover_and_evaluate_oos(X,cols,Y,FWD,CFG)
    t=a.fold_specs[0].test_idx[10]
    ff=FWD.copy();ff.loc[t]=np.nan
    b=discovery.discover_and_evaluate_oos(X,cols,Y,ff,CFG)
    return {'accepted':True,'missing_timestamp':str(t),'missing_timestamp_scored':t in b.oos_returns.index,
        'old_first_test_end':str(a.fold_specs[0].test_idx[-1]),
        'new_first_test_end':str(b.fold_specs[0].test_idx[-1]),
        'old_second_test_start':str(a.fold_specs[1].test_idx[0]),
        'new_second_test_start':str(b.fold_specs[1].test_idx[0]),
        'finite_returns':bool(np.isfinite(b.oos_returns).all())}


def nested_replay():
    a=discovery.discover_and_evaluate_oos(X,{'small':['trend_50','realized_vol_20']},Y,FWD,CFG)
    replay=robustness.replay_oos(X,Y,FWD,CFG,a,None)
    return {'replay_completed':True,'max_return_delta':float((a.oos_returns-replay.oos_returns).abs().max())}


def discovery_aborted():
    ledger=SearchLedger(TMP/'discovery-start.jsonl')
    try:
        with patch.object(discovery,'_validation_sharpe',side_effect=RuntimeError('audit interruption during search')):
            discovery.discover_and_evaluate_oos(X,{'all':list(X.columns)},Y,FWD,CFG,
                ledger=ledger,family_id='f')
    except RuntimeError:
        pass
    return {'ledger_entries_after_search_interruption':ledger.read_all(),
            'attempts_counted':ledger.family_attempt_count('f')}


def parameter_identity():
    results={}
    for model in [ModelConfig(type='logistic',logreg_C=.001),
                  ModelConfig(type='gradient_boosting',gb_learning_rate=.7,gb_n_estimators=7)]:
        cfg=replace(CFG,model=model)
        base=run_walk_forward(X,Y,FWD,cfg)
        captured=[];original=robustness.replay_oos
        def capture(*a,**kw):
            r=original(*a,**kw);captured.append(r);return r
        with patch.object(robustness,'replay_oos',side_effect=capture):
            robustness.parameter_perturbation(X,Y,FWD,cfg,base,None,factors=[1.])
        replay=captured[0]
        m0=base.fitted_models[1].named_steps['model']
        m1=replay.fitted_models[1].named_steps['model']
        fields=['C'] if model.type=='logistic' else ['learning_rate','n_estimators']
        results[model.type]={'baseline':{k:getattr(m0,k) for k in fields},
            'factor_one':{k:getattr(m1,k) for k in fields},
            'max_probability_delta':float((base.predictions.prob-replay.predictions.prob).abs().max()),
            'baseline_net_sharpe':summarize_experiment(base)['full_oos_net_sharpe'],
            'factor_one_net_sharpe':summarize_experiment(replay)['full_oos_net_sharpe']}
    return results


def delay_anchor():
    cfg=replace(CFG,execution=replace(CFG.execution,signal_delay_bars=5))
    base=run_walk_forward(X,Y,FWD,cfg)
    result=robustness.delay_stress(X,Y,FWD,cfg,base,None)
    return {'configured_delay':5,'tested_delays':list(result.delay_bars),
        'has_baseline_anchor':bool((result.delay_bars==5).any()),
        'has_slower_execution':bool((result.delay_bars>5).any())}


def coverage():
    rows=[]
    for name,start,end,cut in [('leading','2024-01-02','2024-02-03','head'),
                              ('trailing','2024-01-02','2024-02-03','tail')]:
        raw=generate_synthetic_ohlcv(['SPY'],start,end)
        raw=raw.iloc[1:] if cut=='head' else raw.iloc[:-1]
        p=TMP/f'{name}.csv';raw.to_csv(p,index=False)
        cfg=DataConfig(mode='csv',assets=['SPY'],start=start,end=end,csv_path=str(p))
        try:
            result,_=load_market_data(cfg)
            rows.append({'case':name,'accepted':True,'first':str(result.timestamp.min()),
                'last':str(result.timestamp.max()),'integrity_report':missing_data_report(result).to_dict('records')})
        except Exception as exc:rows.append({'case':name,'accepted':False,'error':str(exc)})
    # Session dates with an explicit intraday timestamp (one bar per session).
    raw=generate_synthetic_ohlcv(['SPY'],'2024-01-02','2024-02-03')
    raw.timestamp=raw.timestamp+pd.Timedelta(hours=21)
    p=TMP/'session_close.csv';raw.to_csv(p,index=False)
    result,_=load_market_data(DataConfig(mode='csv',assets=['SPY'],start='2024-01-02',end='2024-02-03',csv_path=str(p)))
    rows.append({'case':'session-close-timestamps','accepted':True,'rows':len(result)})
    return rows


def ranges():
    idx=expected_sessions(pd.Timestamp('2024-01-02',tz='UTC'),pd.Timestamp('2024-03-01',tz='UTC'))
    idx=idx[idx<pd.Timestamp('2024-03-01',tz='UTC')]
    p=TMP/'close-only.csv'
    pd.DataFrame({'timestamp':idx,'Close_SPY':100.+np.arange(len(idx)),
                  'Volume_SPY':np.full(len(idx),1e6)}).to_csv(p,index=False)
    raw,_=load_market_data(DataConfig(mode='csv',start='2024-01-02',end='2024-03-01',csv_path=str(p)))
    feature=lagged_parkinson_volatility(raw)
    return {'all_rows_marked_synthetic_range':bool(raw._synthetic_range.all()),
        'range_feature_accepted':True,'nonmissing_values':len(feature.dropna()),
        'all_nonmissing_values_zero':bool((feature.dropna()==0).all())}


def event_fixture():
    t=pd.Timestamp('2024-01-10',tz='UTC')
    return pd.DataFrame([dict(event_id='e',symbol='SPY',event_time=t,
        publication_time=t,availability_time=t,source='s',raw_value=1.,
        processed_value=1.,sentiment=.5)])


def event_units():
    result=[]
    for eu in ['s','ms','us','ns']:
        for bu in ['s','ms','us','ns']:
            ev=event_fixture()
            for k in ['event_time','publication_time','availability_time']:
                ev[k]=ev[k].dt.as_unit(eu)
            idx=pd.date_range('2024-01-05',periods=10,tz='UTC').as_unit(bu)
            feat=build_information_features(idx,ev,'SPY')
            first=feat.index[feat.info_attention>0].min()
            result.append({'event_unit':eu,'bar_unit':bu,'first_eligible':str(first),
                'correct':first==pd.Timestamp('2024-01-10',tz='UTC')})
    return result


def event_identity():
    ev=event_fixture();idx=pd.date_range('2024-01-10',periods=3,tz='UTC')
    single=build_information_features(idx,ev,'SPY')
    repeated=build_information_features(idx,pd.concat([ev,ev],ignore_index=True),'SPY')
    conflicted=pd.concat([ev,ev],ignore_index=True)
    conflicted['revision']=np.nan;conflicted.loc[1,'sentiment']=-.5
    try:
        validate_events(conflicted);conflict_accepted=True
    except DataValidationError:conflict_accepted=False
    missing=pd.concat([ev,ev],ignore_index=True);missing.loc[1,'processed_value']=np.nan
    try:
        validate_events(missing);missing_accepted=True
    except DataValidationError:missing_accepted=False
    return {'single_attention':float(single.info_attention.iloc[0]),
        'repeated_attention':float(repeated.info_attention.iloc[0]),
        'repeat_invariant':bool(single.equals(repeated)),
        'conflicting_null_revision_accepted':conflict_accepted,
        'missing_vs_nonmissing_identity_accepted':missing_accepted}


def metrics_invalid():
    bad=pd.Series([.01,-.02,-np.inf,.03])
    clean=bad[np.isfinite(bad)]
    return {'invalid_input':bad.tolist(),'metrics_with_inf':compute_metrics(bad),
            'metrics_without_inf':compute_metrics(clean)}


for name,fn in [('locks',locks),('attempts_and_gates',attempts),
    ('corrupt_search_ledger',corrupt_ledger),('missing_baseline',missing_baseline),
    ('nested_missing',nested_missing),('nested_replay',nested_replay),
    ('discovery_aborted',discovery_aborted),('parameter_factor_one',parameter_identity),
    ('delay_anchor',delay_anchor),('coverage',coverage),('synthetic_ranges',ranges),
    ('event_unit_matrix',event_units),('event_identity',event_identity),
    ('metrics_invalid',metrics_invalid)]:
    probe(name,fn)
