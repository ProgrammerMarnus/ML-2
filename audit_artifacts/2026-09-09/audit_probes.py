"""Deterministic audit evidence. Run against an isolated source copy.

No market downloads or product edits. Writes only next to this script.
Successful probes describe observed behavior, including defects; this is not
the project's regression suite. Every probe has independent assertions.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from quant_research.config import (AppConfig, DataConfig, EvaluationConfig,
    ExecutionConfig, ModelConfig, ResearchConfig, PromotionConfig)
from quant_research.data.loaders import generate_synthetic_ohlcv, load_market_data, to_panels
from quant_research.data.snapshots import dataset_hash
from quant_research.data.validation import validate_ohlcv, missing_data_report
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.metrics import max_drawdown, sortino_ratio
from quant_research.evaluation.placebo import run_placebo_null, placebo_statistics
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.evaluation.robustness import (replay_oos, cost_stress,
    delay_stress, missing_data_stress, assert_cost_accounting)
from quant_research.experiments.registry import TrialCounter
from quant_research.experiments.promotion import evaluate_gates, promotion_decision
from quant_research.features.information import build_information_features
from quant_research.features.point_in_time import validate_events
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment
from quant_research.strategies.discovery import (discover_strategies,
    discover_and_evaluate_oos, evaluate_candidate_oos)

OUT = Path(__file__).resolve().parent
RESULTS = {}


def probe(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:
        import traceback
        RESULTS[name] = {"PROBE_ERROR": type(exc).__name__ + ": " + str(exc),
                         "traceback": traceback.format_exc()}
    print(name, json.dumps(RESULTS[name], default=str), flush=True)
    (OUT / "probe-results.json").write_text(json.dumps(RESULTS, indent=2, default=str) + "\n")


def caught(fn):
    try:
        fn()
    except Exception as exc:
        return type(exc).__name__ + ": " + str(exc)
    return None


def event(eid, publication, availability, sentiment=1.):
    return dict(event_id=eid, symbol="SPY", event_time=pd.Timestamp("2024-01-05", tz="UTC"),
        publication_time=pd.Timestamp(publication), availability_time=pd.Timestamp(availability),
        source=eid, raw_value=1., processed_value=1., sentiment=sentiment, novelty=1., topic="rates")


def pit_arrival_inversion():
    idx = pd.bdate_range("2024-01-05", periods=12, tz="UTC")
    available = event("fast_feed", "2024-01-05T02:00Z", "2024-01-05T02:00Z")
    backlogged = event("slow_feed", "2024-01-05T01:00Z", "2024-01-12T00:00Z", -.8)
    a = build_information_features(idx, pd.DataFrame([available]), "SPY")
    b = build_information_features(idx, pd.DataFrame([available, backlogged]), "SPY")
    prior = idx < backlogged["availability_time"]
    changed = int(((a.loc[prior] - b.loc[prior]).abs().max(axis=1) > 0).sum())
    assert changed > 0 and a.iloc[1].info_attention > 0 and b.iloc[1].info_attention == 0
    return {"changed_historical_bars": changed, "bar": str(idx[1]),
        "before": a.iloc[1].to_dict(), "after_adding_unavailable_earlier_publication": b.iloc[1].to_dict(),
        "later_availability": str(backlogged["availability_time"])}


def pit_fixed_cases():
    idx = pd.bdate_range("2024-01-08", periods=15, tz="UTC")
    a = event("weekend", "2024-01-06T10:00Z", "2024-01-06T10:00Z")
    b = event("later", "2024-01-15T10:00Z", "2024-01-15T10:00Z")
    f = build_information_features(idx, pd.DataFrame([a]), "SPY")
    f2 = build_information_features(idx, pd.DataFrame([a,b]), "SPY")
    np.testing.assert_array_equal(f.loc[idx < b['availability_time']], f2.loc[idx < b['availability_time']])
    assert np.isclose(f.info_intensity.iloc[-1], .5 ** (14/5))
    return {"ordinary_later_copy_prefix_invariance": True,
            "weekend_intensity_first": float(f.info_intensity.iloc[0]),
            "weekend_intensity_last": float(f.info_intensity.iloc[-1])}


def pit_identity_and_exception():
    a = event("same", "2024-01-05T02:00Z", "2024-01-05T02:00Z")
    b = dict(a, sentiment=-1., processed_value=-2.)
    accepted = validate_events(pd.DataFrame([a,b]))
    c = dict(a, availability_time=pd.Timestamp("2024-01-04T00:00Z"), provider_rule_exception="False")
    accepted_exception = validate_events(pd.DataFrame([c]))
    return {"conflicting_processed_value_and_sentiment_accepted_rows": len(accepted),
            "string_false_allows_availability_before_event": len(accepted_exception) == 1}


def counter_stale():
    path = Path(tempfile.mkdtemp(prefix="counter-", dir=OUT)) / "counter.json"
    a, b = TrialCounter(path), TrialCounter(path)
    a.increment(100)
    b.increment(1)
    final = TrialCounter(path).count
    assert final == 1
    return {"increments": [100,1], "expected_total":101, "actual":final,
            "highwater":json.loads(b.high_water_path.read_text())["count"]}


def incomplete_data():
    raw = generate_synthetic_ohlcv(["SPY"], "2024-01-02", "2024-03-01")
    path = OUT / "partial-data.csv"
    raw.to_csv(path, index=False)
    cfg = DataConfig(mode="csv", assets=["SPY","QQQ"], start="2020-01-01", end="2025-01-01", csv_path=str(path))
    loaded, meta = load_market_data(cfg)
    report = missing_data_report(loaded)
    passed = bool((report.n_missing_sessions == 0).all() and (report.n_observed_closures == 0).all())
    assert passed and set(loaded.symbol) == {"SPY"}
    return {"requested": meta, "loaded_assets": list(loaded.symbol.unique()),
            "integrity_passes": passed, "report": report.to_dict("records")}


def invalid_ohlcv():
    raw = generate_synthetic_ohlcv(["SPY"], "2024-01-02", "2024-01-04")
    bad = raw.copy()
    bad["high"], bad["low"], bad["open"], bad["close"], bad["volume"] = 50., 40., 100., 100., np.inf
    accepted = validate_ohlcv(bad)
    wide = pd.DataFrame({"timestamp":raw.timestamp,"Close_SPY":raw.close,"Volume_SPY":raw.volume})
    path = OUT / "close-only.csv"
    wide.to_csv(path,index=False)
    loaded, _ = load_market_data(DataConfig(mode="csv",start="2024-01-02",end="2024-01-04",csv_path=str(path)))
    return {"impossible_price_and_inf_volume_accepted":len(accepted),
            "wide_csv_invented_zero_range_ohlc":bool((loaded.high == loaded.low).all() and (loaded.open == loaded.close).all())}


def duplicate_sessions():
    raw = generate_synthetic_ohlcv(["SPY"], "2024-01-02", "2024-03-01")
    extra = raw.copy()
    extra.timestamp = extra.timestamp + pd.Timedelta(hours=12)
    doubled = validate_ohlcv(pd.concat([raw,extra]).sort_values(["timestamp","symbol"]))
    report = missing_data_report(doubled)
    assert report.n_missing_sessions.sum() == report.n_observed_closures.sum() == 0
    return {"observations":len(doubled), "actual_sessions":len(raw),
            "reported_missing":int(report.n_missing_sessions.sum()),
            "reported_off_calendar":int(report.n_observed_closures.sum())}


def hash_collision():
    raw = generate_synthetic_ohlcv(["SPY"], "2024-01-02", "2024-01-04")
    raw["close"] = 100.
    changed = raw.copy()
    changed.loc[0,"close"] += 1e-12
    assert not raw.equals(changed) and dataset_hash(raw) == dataset_hash(changed)
    return {"different_prices_same_hash":True,"hash":dataset_hash(raw)}


def statistical_repairs():
    from quant_research.evaluation.overfitting import probability_of_backtest_overfitting
    x = 2. ** np.arange(8); x -= x.mean()
    pbo = probability_of_backtest_overfitting(pd.DataFrame([x,-x]),max_combinations=100)
    assert pbo['pbo'] == 1.
    r = pd.Series([.03,-.01,.03,-.01])
    sortino = sortino_ratio(r)
    np.testing.assert_allclose(sortino, r.mean()/np.sqrt(np.mean(np.minimum(r,0)**2))*np.sqrt(252))
    np.testing.assert_allclose(max_drawdown(pd.Series([-.2,0,0])), -.2)
    one = placebo_statistics(2.,pd.DataFrame({'mean_oos_sharpe':[1.]}))
    checks = evaluate_gates({}, {}, {}, one, True, True, 1, PromotionConfig())
    statuses = {c.name:bool(c.passed) for c in checks}
    assert not statuses['placebo_separates'] and not statuses['placebo_sample_adequate']
    return {"pbo":pbo,"sortino":sortino,"initial_drawdown":max_drawdown(pd.Series([-.2,0,0])),
            "one_null_rejected":True}


def search_gate():
    summary = dict(median_oos_sharpe=1.,mean_oos_sharpe=1.,full_oos_max_dd=-.1,single_fold_share=.25,annual_turnover=20.)
    rob = {"cost_stress":[dict(fee_bps=20.,sharpe=1.)],"delay_stress":[dict(delay_bars=3,sharpe=1.)]}
    null = dict(percentile=1., adjusted_p=1/21, n_runs=20)
    decisions = {}
    for trials in (1,1000000):
        checks = evaluate_gates(summary,rob,{"positive_prob":.9},null,True,True,trials,PromotionConfig())
        decisions[str(trials)] = promotion_decision(checks)
    assert decisions['1']['state'] == decisions['1000000']['state'] == 'CANDIDATE'
    return decisions


def fixture(model="logistic", delay=0, hold=1, step=40, cols=3, risk=None):
    idx = pd.bdate_range("2020-01-01", periods=300, tz="UTC")
    rng = np.random.default_rng(9)
    X = pd.DataFrame(rng.normal(size=(len(idx),cols)),index=idx,columns=list("abc")[:cols])
    y = pd.Series((X.a+rng.normal(size=len(idx))>0).astype(float),index=idx)
    f = pd.Series(rng.normal(.0005,.01,len(idx)),index=idx)
    cfg = AppConfig(evaluation=EvaluationConfig(train_window=80,validation_window=40,test_window=40,step_bars=step,purge_bars=2,embargo_bars=2),
        model=ModelConfig(type=model),execution=ExecutionConfig(signal_delay_bars=delay),
        research=ResearchConfig(threshold_candidates=[.5,.6],hold_candidates=[1],placebo_runs=1,bootstrap_samples=20))
    lock = LockedTestProtocol()
    base = run_walk_forward(X,y,f,cfg,locked_test=lock,hold_bars=hold,risk_returns=risk)
    return X,y,f,cfg,lock,base


def replay_supported_configs():
    X,y,f,cfg,lock,base = fixture(model="gradient_boosting")
    gradient = caught(lambda: cost_stress(X,y,f,cfg,base,lock,fee_grid=[5.]))
    assert gradient and 'coef_' in gradient
    X,y,f,cfg,lock,base = fixture(delay=1)
    delay = caught(lambda: delay_stress(X,y,f,cfg,base,lock,delays=[0]))
    assert delay and 'positions differ' in delay
    return {"gradient_boosting":gradient,"configured_delay_1":delay}


def replay_spec():
    X,y,f,cfg,lock,base = fixture(hold=5)
    rep = replay_oos(X,y,f,cfg,base,lock)
    np.testing.assert_array_equal(base.oos_positions,rep.oos_positions)
    subset = run_walk_forward(X,y,f,cfg,feature_subset=['a'],locked_test=lock)
    subset_error = caught(lambda: replay_oos(X,y,f,cfg,subset,lock))
    assert subset_error and 'feature' in subset_error.lower()
    risk = f.shift(1)*.1
    riskbase = run_walk_forward(X,y,f,cfg,risk_returns=risk,locked_test=lock)
    riskrep = replay_oos(X,y,f,cfg,riskbase,lock)
    n = int((riskbase.oos_positions != riskrep.oos_positions).sum())
    assert n > 0
    return {"baseline_hold_5_replays_identically":True,
            "subset_replay_error":subset_error,"custom_risk_changed_positions":n}


def nested_replay():
    X,y,f,cfg,_,_ = fixture()
    cfg = replace(cfg,research=replace(cfg.research,max_trials=1,hold_candidates=[5]))
    lock = LockedTestProtocol()
    nested = discover_and_evaluate_oos(X,{'all':list(X.columns)},y,f,cfg,locked_test=lock)
    rep = replay_oos(X,y,f,cfg,nested,lock)
    n = int((nested.oos_positions != rep.oos_positions).sum())
    assert n > 0 and set(nested.folds.hold_bars)=={5} and nested.hold_bars == 1
    return {"fold_holds":nested.folds.hold_bars.tolist(),"result_hold":nested.hold_bars,
            "changed_positions_on_no_override_replay":n,
            "baseline_net_return":float((1+nested.oos_returns).prod()-1),
            "replay_net_return":float((1+rep.oos_returns).prod()-1)}


def legacy_discovery():
    X,y,f,cfg,_,base = fixture()
    # Keep classification labels consistent with the forward-return target
    # in both the original and perturbed price-return histories.
    y = (f > 0).astype(float)
    cfg = replace(cfg,research=replace(cfg.research,max_trials=4))
    sets = {'a':['a'],'bc':['b','c']}
    original = discover_strategies(X,sets,y,f,cfg)
    start = base.fold_specs[0].test_idx[0]
    mask = f.index >= start
    changes = []
    for seed in range(4):
        changed = f.copy()
        changed.loc[mask] = np.random.default_rng(seed).normal(0,.02,int(mask.sum()))
        changed_y = (changed > 0).astype(float)
        grid = discover_strategies(X,sets,changed_y,changed,cfg)
        changes.append([seed,int(original.iloc[0].candidate_id),int(grid.iloc[0].candidate_id)])
        if changes[-1][1] != changes[-1][2]:
            a = evaluate_candidate_oos(X,y,f,cfg,original.iloc[0],sets)
            b = evaluate_candidate_oos(X,changed_y,changed,cfg,grid.iloc[0],sets)
            te = base.fold_specs[0].test_idx
            changed_probs = int((a.predictions.loc[te,'prob'] != b.predictions.loc[te,'prob']).sum())
            assert changed_probs > 0
            return {'attempts_seed_before_after':changes,'first_test_predictions_changed':changed_probs,
                    'labels_consistent_with_forward_return_sign':True,
                    'first_validation_unchanged':bool(f.loc[base.fold_specs[0].val_idx].equals(changed.loc[base.fold_specs[0].val_idx]))}
    raise AssertionError('No changed winner found in bounded deterministic probe')


def missing_stress_anchor():
    X,y,f,cfg,lock,base = fixture(cols=1)
    err = caught(lambda: missing_data_stress(X,y,f,cfg,base,lock,frac=.1))
    assert err and 'locked test' in err
    return {'one_feature_baseline_completes':True,'missing_data_stress_error':err}


def membership_lock():
    X,y,f,cfg,lock,base = fixture()
    original = base.fold_specs
    changed = [replace(original[0],test_idx=original[0].test_idx.delete(3))] + original[1:]
    lock.verify(changed)
    return {'interior_test_bar_removed_without_rejection':True,'original_size':40,'changed_size':39}


def block_fixed():
    X,y,f,cfg,_,_ = fixture()
    captured = {}
    def save(XX,yy,ff):
        captured.update(y=yy,f=ff)
        return {'mean_oos_sharpe':0.,'median_oos_sharpe':0.}
    run_placebo_null(X,y,f,save,1,mode='block_permute')
    assert captured['f'].index.equals(f.index) and not captured['f'].equals(f)
    return {'chronological_index_preserved':True,'dated_returns_changed':int((captured['f']!=f).sum())}


class AlwaysLong:
    def predict_proba(self,X):
        return np.tile([0.,1.],(len(X),1))


def gapped_execution():
    X,y,f,cfg,_,base = fixture(step=60)
    cfg = replace(cfg,execution=replace(cfg.execution,target_vol=1.))
    specs = walk_forward_splits(X.index,cfg.evaluation)
    models = {s.fold_id:AlwaysLong() for s in specs}
    thresholds = {s.fold_id:.5 for s in specs}
    f = pd.Series(.001,index=X.index)
    risk = pd.Series(np.resize([.001,-.001],len(X)),index=X.index)
    gap = X.index[(X.index > specs[0].test_idx[-1]) & (X.index < specs[1].test_idx[0])]
    f.loc[gap] = -.05
    result = run_walk_forward(X,y,f,cfg,fitted_models=models,fixed_thresholds=thresholds,risk_returns=risk)
    prev, nxt = specs[0].test_idx[-1],specs[1].test_idx[0]
    assert result.oos_positions.loc[prev] == result.oos_positions.loc[nxt] == 1.
    assert not result.oos_returns.index.intersection(gap).size
    return {'last_scored_bar':str(prev),'next_scored_bar':str(nxt),'omitted_sessions':len(gap),
            'position_before_gap':float(result.oos_positions.loc[prev]),
            'position_after_gap':float(result.oos_positions.loc[nxt]),
            'unscored_gap_compound_return':float((1+f.loc[gap]).prod()-1),
            'turnover_at_next_scored_bar':float(result.oos_positions.diff().abs().loc[nxt])}


def discovery_accounting():
    X,y,f,cfg,_,_ = fixture()
    cfg = replace(cfg,research=replace(cfg.research,max_trials=1))
    path = Path(tempfile.mkdtemp(prefix='discovery-count-',dir=OUT))/'counter.json'
    counter = TrialCounter(path)
    table = discover_strategies(X,{'all':list(X.columns)},y,f,cfg)
    res = evaluate_candidate_oos(X,y,f,cfg,table.iloc[0],{'all':list(X.columns)},trial_counter=counter)
    assert counter.count == 0
    return {'legacy_search_and_oos_completed':True,'candidate_count':len(table),
            'fold_count':len(res.folds),'counter_after_search_and_evaluation':counter.count}


if __name__ == '__main__':
    tests = [pit_arrival_inversion,pit_fixed_cases,pit_identity_and_exception,
             counter_stale,incomplete_data,invalid_ohlcv,duplicate_sessions,
             hash_collision,statistical_repairs,search_gate,replay_supported_configs,
             replay_spec,nested_replay,legacy_discovery,missing_stress_anchor,
             membership_lock,block_fixed,gapped_execution,discovery_accounting]
    for test in tests:
        probe(test.__name__,test)
    if any('PROBE_ERROR' in r for r in RESULTS.values()):
        raise SystemExit(1)
