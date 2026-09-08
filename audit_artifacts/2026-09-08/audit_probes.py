"""Read-only audit reproductions; all writes are confined to this audit directory."""
from __future__ import annotations
import json
import tempfile
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scipy.stats import norm

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ExecutionConfig, ModelConfig, ResearchConfig, PromotionConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, load_market_data
from quant_research.data.validation import validate_ohlcv, missing_data_report
from quant_research.data.snapshots import dataset_hash
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.metrics import max_drawdown, sortino_ratio
from quant_research.evaluation.placebo import run_placebo_null, placebo_statistics
from quant_research.evaluation.overfitting import probability_of_backtest_overfitting
from quant_research.evaluation.multiple_testing import deflated_sharpe_pvalue, expected_max_sharpe
from quant_research.evaluation.robustness import cost_stress, delay_stress, replay_oos, missing_data_stress
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.experiments.registry import TrialCounter
from quant_research.experiments.promotion import evaluate_gates
from quant_research.features.information import build_information_features
from quant_research.features.leakage import _info_event_perturbation
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment
from quant_research.portfolio.construction import apply_drawdown_control

ROOT = Path(__file__).parent
RESULTS = {}
def probe(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as e:
        RESULTS[name] = {"PROBE_ERROR": type(e).__name__ + ': ' + str(e)}
    print(name, json.dumps(RESULTS[name], default=str), flush=True)

def event(eid, available, topic='same'):
    return dict(event_id=eid, symbol='SPY', event_time=pd.Timestamp('2024-01-05', tz='UTC'),
                publication_time=pd.Timestamp(available), availability_time=pd.Timestamp(available),
                source=eid, raw_value=1., processed_value=1., sentiment=1., novelty=1., topic=topic)

def pit_future():
    idx=pd.bdate_range('2024-01-05', periods=10,tz='UTC')
    early=event('early','2024-01-05T00:00:00Z')
    late=event('late','2024-01-12T00:00:00Z')
    a=build_information_features(idx,pd.DataFrame([early]),'SPY')
    b=build_information_features(idx,pd.DataFrame([early,late]),'SPY')
    assert a.iloc[0].info_corroboration == 1 and b.iloc[0].info_corroboration == 2
    gate=_info_event_perturbation(idx,pd.DataFrame([early,late]),'SPY')
    return dict(early_bar=str(idx[0]),later_availability=late['availability_time'],
                prefix_only=a.iloc[0].info_corroboration,full_history=b.iloc[0].info_corroboration,
                existing_leakage_probe_passed=gate['passed'])

def weekend_decay():
    idx=pd.bdate_range('2024-01-08',periods=15,tz='UTC')
    e=event('weekend','2024-01-06T10:00:00Z')
    f=build_information_features(idx,pd.DataFrame([e]),'SPY')
    assert f.info_intensity.iloc[0] == f.info_intensity.iloc[-1] == 1
    return dict(intensity_first=f.info_intensity.iloc[0],intensity_15th_bar=f.info_intensity.iloc[-1],halflife_bars=5)

def block_permutation():
    idx=pd.bdate_range('2024-01-01',periods=100,tz='UTC')
    y=pd.Series(np.arange(100)%2,index=idx,dtype=float)
    f=pd.Series(np.arange(100)/10000,index=idx)
    X=pd.DataFrame({'x':np.arange(100)},index=idx)
    captured={}
    def capture(X,yy,ff):
        captured.update(y=yy,f=ff)
        return {'mean_oos_sharpe':0.,'median_oos_sharpe':0.}
    run_placebo_null(X,y,f,capture,1,seed=42,mode='block_permute')
    assert captured['y'].reindex(idx).equals(y) and captured['f'].reindex(idx).equals(f)
    permutation_dates=captured['f'].index
    future_predecessors=int((permutation_dates[:-1] > permutation_dates[1:]).sum())
    return dict(labels_unchanged_after_production_alignment=True,
                returns_unchanged_after_production_alignment=True,
                later_date_precedes_earlier_date_in_risk_history=future_predecessors)

def warm_start():
    idx=pd.bdate_range('2024-01-01',periods=100,tz='UTC')
    s=pd.Series(1.,index=idx)
    r=pd.Series(np.tile([.001,-.001],50),index=idx)
    cfg=ExecutionConfig(target_vol=1.)
    full=backtest(s,r,cfg,risk_returns=r)
    left=backtest(s.iloc[40:60],r.iloc[40:60],cfg,risk_returns=r)
    right=backtest(s.iloc[60:80],r.iloc[60:80],cfg,risk_returns=r)
    assert full.positions.iloc[60] == 1 and right.positions.iloc[0] == 0
    assert left.positions.iloc[-1] == 1 and right.costs.iloc[0] == 0
    return dict(continuous_boundary_position=1.,fold_boundary_position=0.,
                previous_fold_final_position=1.,boundary_exit_fee_charged=0.,
                required_fee_plus_slippage=.0006)

def folds_summary(sharpes):
    f=pd.DataFrame({'oos_sharpe':sharpes,'oos_auc':.5,'oos_brier':.25,'oos_max_dd':-.1,'oos_trades':5})
    res=SimpleNamespace(folds=f,oos_returns=pd.Series([0.,.01,-.01]),oos_gross_returns=None,fee_costs=0.,slippage_costs=0.)
    return summarize_experiment(res)

def fold_share():
    balanced=folds_summary([1,1,1,1])['single_fold_share']
    dominated=folds_summary([10,.01,.01,-9])['single_fold_share']
    assert balanced == 1 and dominated < .6
    return dict(balanced_four_profitable_folds_reported_share=balanced,
                one_winner_dominated_reported_share=dominated,
                actual_largest_positive_share=10/10.02)

def counter_stale():
    p=Path(tempfile.mkdtemp(dir=ROOT))/'counter.json'
    a,b=TrialCounter(p),TrialCounter(p)
    a.increment(100); b.increment(1)
    final=TrialCounter(p).count
    assert final == 1
    return dict(increments_requested=[100,1],persisted_count=final,
                persisted_highwater=json.loads(b.high_water_path.read_text())['count'])

def pbo_rank():
    x=2.**np.arange(8);x-=x.mean()
    matrix=pd.DataFrame([x,-x])
    got=probability_of_backtest_overfitting(matrix,max_combinations=100)
    losses=[]
    for subset in combinations(range(8),4):
        other=list(set(range(8))-set(subset))
        winner=matrix.iloc[:,list(subset)].mean(axis=1).argmax()
        oos=matrix.iloc[:,other].mean(axis=1)
        losses.append(oos.iloc[winner] < oos.median())
    assert got['pbo'] == 0 and all(losses)
    return dict(reported_pbo=got['pbo'],actual_fraction_below_variant_median=float(np.mean(losses)),splits=len(losses))

def dsr_formula():
    annual,nt,n,sk,k=1.5,50,1000,-3.,10.
    sr=annual/np.sqrt(252)
    sr0=expected_max_sharpe(nt,n)
    correct_denom=np.sqrt(1-sk*sr+(k-1)/4*sr**2)
    expected=float(norm.sf(np.sqrt(n-1)*(sr-sr0)/correct_denom))
    got=deflated_sharpe_pvalue(annual,nt,n,sk,k)
    return dict(annualized_sharpe=annual,trials=nt,n_obs=n,skew=sk,kurtosis=k,
                implementation_p=got,p_using_paper_denominator_same_benchmark=expected,
                function_named_annualized_expected_max=sr0,actual_annualized_value=sr0*np.sqrt(252))

def drawdown_initial_loss():
    r=pd.Series([-.2,0.,0.])
    got=max_drawdown(r);w=apply_drawdown_control(r,pd.Series(1.,index=r.index))
    assert got==0 and (w==1).all()
    return dict(returns=r.tolist(),reported_max_drawdown=got,actual_max_drawdown=-.2,controlled_weights=w.tolist())

def sortino_example():
    r=pd.Series([.03,-.01,.03,-.01])
    got=sortino_ratio(r)
    correct=float(r.mean()/np.sqrt(np.mean(np.minimum(r,0)**2))*np.sqrt(252))
    assert np.isnan(got)
    return dict(returns=r.tolist(),reported_sortino=str(got),zero_target_downside_deviation_sortino=correct)

def data_coverage():
    rows=generate_synthetic_ohlcv(['SPY'],'2024-01-02','2024-03-01')
    p=ROOT/'partial-data.csv';rows.to_csv(p,index=False)
    cfg=DataConfig(mode='csv',assets=['SPY','QQQ'],target='SPY',start='2020-01-01',end='2025-01-01',csv_path=str(p))
    loaded,meta=load_market_data(cfg)
    missing=missing_data_report(loaded)
    assert set(loaded.symbol)=={'SPY'} and missing.n_missing_sessions.sum()==0
    return dict(requested_assets=cfg.assets,loaded_assets=list(loaded.symbol.unique()),
                requested_dates=[cfg.start,cfg.end],loaded_dates=[str(loaded.timestamp.min()),str(loaded.timestamp.max())],
                reported_missing_sessions=int(missing.n_missing_sessions.sum()))

def schema_sanity():
    row=generate_synthetic_ohlcv(['SPY'],'2024-01-02','2024-01-04').iloc[[0]].copy()
    row['high']=50.;row['low']=40.;row['close']=100.;row['open']=100.;row['volume']=np.inf
    checked=validate_ohlcv(row)
    assert len(checked)==1
    return dict(accepted_close_outside_high_low=True,accepted_infinite_volume=True)

def hash_collision():
    row=generate_synthetic_ohlcv(['SPY'],'2024-01-02','2024-01-04')
    row['close']=100.;other=row.copy();other.loc[0,'close']+=1e-12
    assert not row.equals(other) and dataset_hash(row)==dataset_hash(other)
    return dict(distinct_numeric_data=True,hash_equal=True,hash=dataset_hash(row))

def placebo_gate_resolution():
    stats=placebo_statistics(2.,pd.DataFrame({'mean_oos_sharpe':[1.]}))
    checks=evaluate_gates({}, {}, {},stats,True,True,1,PromotionConfig())
    gate=next(c for c in checks if c.name=='placebo_separates')
    assert gate.passed and stats['adjusted_p']==.5
    return dict(n_runs=1,percentile=stats['percentile'],adjusted_p=stats['adjusted_p'],gate_passed=gate.passed)

def fixture(model='logistic',delay=0,hold=1,step=40):
    idx=pd.bdate_range('2020-01-01',periods=300,tz='UTC');rng=np.random.default_rng(9)
    X=pd.DataFrame(rng.normal(size=(len(idx),3)),index=idx,columns=['a','b','c'])
    y=pd.Series((X.a+rng.normal(size=len(idx))>0).astype(float),index=idx)
    f=pd.Series(rng.normal(.0005,.01,len(idx)),index=idx)
    cfg=AppConfig(evaluation=EvaluationConfig(train_window=80,validation_window=40,test_window=40,step_bars=step,purge_bars=2,embargo_bars=2),
                  model=ModelConfig(type=model),execution=ExecutionConfig(signal_delay_bars=delay),
                  research=ResearchConfig(threshold_candidates=[.5,.6],hold_candidates=[1],placebo_runs=1,bootstrap_samples=20))
    lt=LockedTestProtocol();base=run_walk_forward(X,y,f,cfg,locked_test=lt,hold_bars=hold)
    return X,y,f,cfg,lt,base

def gradient_stress():
    X,y,f,cfg,lt,base=fixture('gradient_boosting')
    try: cost_stress(X,y,f,cfg,base,lt,fee_grid=[5.])
    except AttributeError as e: return dict(baseline_completed=True,stress_error=str(e))
    raise AssertionError('expected GradientBoosting coef_ failure')

def nonzero_delay_stress():
    X,y,f,cfg,lt,base=fixture(delay=1)
    try: delay_stress(X,y,f,cfg,base,lt,delays=[0])
    except AssertionError as e: return dict(baseline_completed=True,stress_error=str(e))
    raise AssertionError('expected delay-zero baseline mismatch')

def holding_replay():
    X,y,f,cfg,lt,base=fixture(hold=5)
    rep=replay_oos(X,y,f,cfg,base,lt)
    n=int((base.oos_positions!=rep.oos_positions).sum())
    assert n>0
    return dict(holding_bars=5,changed_positions_on_no_override_replay=n,total_positions=len(rep.oos_positions))

def overlapping_oos():
    X,y,f,cfg,lt,base=fixture(step=20)
    n=int(base.oos_returns.index.duplicated().sum())
    assert n>0
    try: cost_stress(X,y,f,cfg,base,lt,fee_grid=[5.])
    except Exception as e: err=type(e).__name__+': '+str(e)
    else: err=None
    return dict(test_window=40,step_bars=20,oos_rows=len(base.oos_returns),duplicate_timestamps=n,stress_error=err)

def discovery_overlap():
    idx=pd.bdate_range('2012-01-01',periods=3520,tz='UTC')
    folds=walk_forward_splits(idx,EvaluationConfig())
    overlap=folds[0].test_idx.intersection(folds[1].val_idx)
    assert len(overlap)==247
    return dict(first_test_bars=len(folds[0].test_idx),bars_used_again_in_second_validation=len(overlap),
                later_validation_is_in_global_candidate_ranking=True)

def weak_fold_lock():
    X,y,f,cfg,lt,base=fixture()
    original=base.fold_specs
    changed=[replace(original[0],test_idx=original[0].test_idx.delete(3))]+original[1:]
    lt.verify(changed)
    return dict(removed_test_timestamp_accepted=True,original_bars=len(original[0].test_idx),changed_bars=len(changed[0].test_idx))

if __name__=='__main__':
    for name,fn in [('pit_future_corroboration',pit_future),('weekend_decay',weekend_decay),('block_permutation',block_permutation),
                    ('fold_state_and_exit_cost',warm_start),('single_fold_share',fold_share),('counter_stale_writer',counter_stale),
                    ('pbo_rank_axis',pbo_rank),('dsr_formula',dsr_formula),('initial_loss_drawdown',drawdown_initial_loss),
                    ('sortino_downside',sortino_example),('missing_universe_and_boundaries',data_coverage),('ohlcv_validation',schema_sanity),
                    ('dataset_hash_collision',hash_collision),('placebo_gate_resolution',placebo_gate_resolution),
                    ('gradient_boosting_stress',gradient_stress),('configured_nonzero_delay',nonzero_delay_stress),('holding_rule_replay',holding_replay),
                    ('overlapping_oos_windows',overlapping_oos),('discovery_future_selection',discovery_overlap),('test_lock_membership',weak_fold_lock)]:
        probe(name,fn)
    (ROOT/'audit-probes-results.json').write_text(json.dumps(RESULTS,indent=2,default=str))
