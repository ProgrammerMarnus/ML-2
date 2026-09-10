"""Independent post-fix audit. No product edits, provider calls, or shared data writes.

Run: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python audit_artifacts/2026-09-09-post-fix/audit_probes.py
Each check asserts the intended contract. FAIL means a reproduced defect;
ERROR means an unexpected probe failure requiring manual interpretation.
"""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import json
import sys
import traceback
import warnings
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import pandas as pd
from quant_research.config import *
from quant_research.data.loaders import generate_synthetic_ohlcv, load_market_data, load_csv_ohlcv
from quant_research.data.validation import validate_ohlcv, missing_data_report
from quant_research.data.snapshots import save_manifest
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.evaluation.robustness import replay_oos, delay_stress, cost_stress, parameter_perturbation, assert_cost_accounting, missing_data_stress
from quant_research.experiments.registry import TrialCounter, SearchLedger
from quant_research.features.point_in_time import validate_events
from quant_research.features.information import build_information_features
from quant_research.strategies.baseline import build_model, run_walk_forward
from quant_research.strategies.discovery import discover_and_evaluate_oos
from quant_research.evaluation.multiple_testing import expected_max_sharpe

RESULTS = {}
def check(name, fn):
    try:
        detail = fn()
        RESULTS[name] = dict(status="PASS", detail=detail)
    except AssertionError as exc:
        RESULTS[name] = dict(status="FAIL", detail=str(exc))
    except Exception as exc:
        RESULTS[name] = dict(status="ERROR", detail=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    print(name, json.dumps(RESULTS[name], default=str), flush=True)
    (OUT / "probe-results.json").write_text(json.dumps(RESULTS, indent=2, default=str) + "\n")

def outcome(fn):
    try:
        result = fn()
        return dict(accepted=True, result=result)
    except Exception as exc:
        return dict(accepted=False, error=f"{type(exc).__name__}: {exc}")

def event(eid="a", when="2024-01-10T00:00Z", **extra):
    return dict(event_id=eid, symbol="SPY", event_time=pd.Timestamp(when),
                publication_time=pd.Timestamp(when), availability_time=pd.Timestamp(when),
                source="wire", raw_value=1., processed_value=1., sentiment=1., topic="rates", **extra)

def event_units():
    idx = pd.date_range("2024-01-05", periods=10, tz="UTC")
    rows = {}
    for unit in ("s", "ms", "us", "ns"):
        ev = pd.DataFrame([event()])
        for col in ("event_time", "publication_time", "availability_time"):
            ev[col] = ev[col].dt.as_unit(unit)
        f = build_information_features(idx, ev, "SPY")
        rows[unit] = f.info_attention.tolist()
    assert all(v == rows["us"] for v in rows.values()), json.dumps(rows)
    return rows

def arrival_inversion():
    idx = pd.date_range("2024-01-05", periods=15, tz="UTC")
    a = event("fast", "2024-01-05T02:00Z")
    b = event("slow", "2024-01-05T01:00Z")
    b["availability_time"] = pd.Timestamp("2024-01-12T00:00Z")
    x = build_information_features(idx, pd.DataFrame([a]), "SPY")
    z = build_information_features(idx, pd.DataFrame([a,b]), "SPY")
    pd.testing.assert_frame_equal(x.loc[idx < b["availability_time"]], z.loc[idx < b["availability_time"]])
    assert x.info_attention.iloc[1] > 0
    return "historical features unchanged, available event contributes"

def exception_types():
    rows = {}
    for flag in ("unexpected", 2, float("nan"), "False", True, False):
        ev = event(provider_rule_exception=flag)
        ev["availability_time"] = pd.Timestamp("2024-01-01T00:00Z")
        rows[repr(flag)] = outcome(lambda: len(validate_events(pd.DataFrame([ev]))))
    assert all(not rows[repr(v)]["accepted"] for v in ("unexpected", 2, float("nan"), "False", False)), json.dumps(rows)
    return rows

def identical_event_ids():
    ev = event()
    with_sentiment = outcome(lambda: len(validate_events(pd.DataFrame([ev,ev]))))
    del ev["sentiment"]
    without_sentiment = outcome(lambda: len(validate_events(pd.DataFrame([ev,ev]))))
    assert with_sentiment["accepted"] and without_sentiment["accepted"], json.dumps(dict(with_sentiment=with_sentiment, without_sentiment=without_sentiment))
    return with_sentiment

def revision_conflict():
    a = event(revision=0)
    b = dict(a, sentiment=-1.)
    c = dict(a, revision=1)
    r = outcome(lambda: len(validate_events(pd.DataFrame([a,b,c]))))
    assert not r["accepted"], json.dumps(r)

def stale_counter():
    with TemporaryDirectory() as d:
        p=Path(d)/"counter.json"
        a,b=TrialCounter(p),TrialCounter(p)
        a.increment(100); b.increment(1)
        assert TrialCounter(p).count == 101
        return 101

def live_counter_reset():
    with TemporaryDirectory() as d:
        p=Path(d)/"counter.json"
        c=TrialCounter(p); c.increment(100)
        p.write_text('{"count":0}')
        r=outcome(lambda:c.increment(1))
        assert not r["accepted"], json.dumps(dict(increment=r, count=c.count, highwater=c.high_water))

def cfg_and_data(seed=123, hold=1, model="logistic"):
    idx=pd.bdate_range("2020-01-01",periods=340,tz="UTC")
    rng=np.random.default_rng(seed)
    X=pd.DataFrame(rng.normal(size=(len(idx),3)),index=idx,columns=["a","b","c"])
    f=pd.Series(rng.normal(.0002,.01,len(idx)),index=idx)
    y=(f>0).astype(float)
    cfg=AppConfig(evaluation=EvaluationConfig(train_window=100,validation_window=30,test_window=40,step_bars=40,purge_bars=2,embargo_bars=2),
          execution=ExecutionConfig(target_vol=1.),
          model=ModelConfig(type=model, hold_bars=hold, parameters={"n_estimators":15,"max_depth":2} if model=="gradient_boosting" else {"C":1.}),
          research=ResearchConfig(threshold_candidates=[.4,.5,.6],hold_candidates=[5],max_trials=1,placebo_runs=1,bootstrap_samples=20))
    return X,y,f,cfg

def lock_roundtrip():
    X,y,f,cfg=cfg_and_data()
    folds=walk_forward_splits(X.index,cfg.evaluation)
    with TemporaryDirectory() as d:
        p=Path(d)/"lock.json"
        a=LockedTestProtocol(p); a.freeze(folds,dataset_id="A")
        b=LockedTestProtocol(p)
        same=outcome(lambda:b.freeze(folds,dataset_id="B"))
        p.write_text('{broken')
        malformed=outcome(lambda:LockedTestProtocol(p).verify(folds))
        assert not same["accepted"] and not malformed["accepted"], json.dumps(dict(dataset_replacement=same, corrupted_lock=malformed))

def full_membership_lock():
    X,y,f,cfg=cfg_and_data()
    folds=walk_forward_splits(X.index,cfg.evaluation)
    lock=LockedTestProtocol(); lock.freeze(folds)
    altered=list(folds); altered[0]=replace(folds[0],test_idx=folds[0].test_idx.delete(10))
    r=outcome(lambda:lock.verify(altered))
    assert not r["accepted"] and "LockedTestViolation" in r["error"], str(r)
    return r

def search_ledger_scope():
    with TemporaryDirectory() as d:
        fid=SearchLedger.family_id("same-data","same-policy")
        a=SearchLedger(Path(d)/"run-a"/"search_ledger.jsonl")
        b=SearchLedger(Path(d)/"run-b"/"search_ledger.jsonl")
        a.record_start(fid,"baseline",9)
        started_count=a.family_search_count(fid)
        a.record_outcome(fid,"baseline",9,"completed")
        r=dict(started_count=started_count, completed_count=a.family_search_count(fid), same_family_other_output_count=b.family_search_count(fid))
        assert started_count == 1 and r["same_family_other_output_count"] == 1, json.dumps(r)

def calendar_boundaries():
    with TemporaryDirectory() as d:
        rows=[]
        for start,end in [("2012-01-01","2012-02-01"),("2024-01-02","2024-01-07"),("2024-01-02","2024-02-01")]:
            raw=generate_synthetic_ohlcv(["SPY"],start,end)
            p=Path(d)/(start+end+".csv");raw.to_csv(p,index=False)
            cfg=DataConfig(mode="csv",assets=["SPY"],start=start,end=end,csv_path=str(p))
            r=outcome(lambda:len(load_market_data(cfg)[0]))
            rows.append(dict(start=start,end=end,first=str(raw.timestamp.min()),last=str(raw.timestamp.max()),**r))
        assert all(r["accepted"] for r in rows), json.dumps(rows)
        return rows

def wide_csv_range():
    with TemporaryDirectory() as d:
        raw=generate_synthetic_ohlcv(["SPY"],"2024-01-02","2024-02-01")
        p=Path(d)/"close.csv"
        pd.DataFrame(dict(timestamp=raw.timestamp,Close_SPY=raw.close,Volume_SPY=raw.volume)).to_csv(p,index=False)
        r=outcome(lambda:load_csv_ohlcv(str(p),["SPY"]))
        if r["accepted"]:
            r["result"]={"rows":len(r["result"]),"all_ranges_zero":bool((r["result"].high==r["result"].low).all())}
        assert not r["accepted"], json.dumps(r)

def ohlcv_controls():
    raw=generate_synthetic_ohlcv(["SPY"],"2024-01-02","2024-02-01")
    rows={}
    for name in ("range","infinite_volume","duplicate_session"):
        bad=raw.copy()
        if name=="range":bad.loc[0,"open"]=bad.loc[0,"high"]*2
        elif name=="infinite_volume":bad.loc[0,"volume"]=np.inf
        else:
            extra=raw.iloc[[0]].copy();extra.timestamp+=pd.Timedelta(hours=12)
            bad=pd.concat([bad,extra]).sort_values("timestamp").reset_index(drop=True)
        rows[name]=outcome(lambda:len(validate_ohlcv(bad)))
    assert all(not r["accepted"] for r in rows.values()),json.dumps(rows)
    return rows

def configured_delay():
    X,y,f,cfg=cfg_and_data()
    cfg=replace(cfg,execution=replace(cfg.execution,signal_delay_bars=1))
    b=run_walk_forward(X,y,f,cfg)
    r=outcome(lambda:delay_stress(X,y,f,cfg,b,None).to_dict("records"))
    assert r["accepted"],json.dumps(r)
    return r

def nested_replay():
    X,y,f,cfg=cfg_and_data()
    cfg=replace(cfg,research=replace(cfg.research,threshold_candidates=[.01]))
    b=discover_and_evaluate_oos(X,{"abc":list(X.columns)},y,f,cfg)
    r=replay_oos(X,y,f,cfg,b,None)
    checks={"positions_equal":bool(b.oos_positions.equals(r.oos_positions)),
            "net_equal":bool(np.allclose(b.oos_returns,r.oos_returns,atol=1e-15)),
            "original_fold_turnover":float(b.folds.oos_turnover.sum()),
            "replay_fold_turnover":float(r.folds.oos_turnover.sum()),
            "cost_stress":outcome(lambda:len(cost_stress(X,y,f,cfg,b,None,fee_grid=[5.])))}
    assert checks["positions_equal"] and checks["net_equal"] and checks["cost_stress"]["accepted"],json.dumps(checks)
    return checks

def configured_model_parameters():
    c=build_model(ModelConfig(logreg_C=.001)).named_steps["model"].C
    g=build_model(ModelConfig(type="gradient_boosting",gb_learning_rate=.7,gb_n_estimators=7)).named_steps["model"]
    X,y,f,cfg=cfg_and_data(hold=5)
    b=run_walk_forward(X,y,f,cfg)
    r=dict(requested=dict(C=.001,learning_rate=.7,n_estimators=7,hold=5),actual=dict(C=c,learning_rate=g.learning_rate,n_estimators=g.n_estimators,hold=b.hold_bars))
    assert c==.001 and g.learning_rate==.7 and g.n_estimators==7 and b.hold_bars==5,json.dumps(r)

def gradient_parameter_stress():
    X,y,f,cfg=cfg_and_data(model="gradient_boosting")
    b=run_walk_forward(X,y,f,cfg)
    z=parameter_perturbation(X,y,f,cfg,b,None,factors=[.5,2.])
    assert z.sharpe.nunique()>1,json.dumps(z.to_dict("records"))

def missing_returns():
    X,y,f,cfg=cfg_and_data()
    cfg=replace(cfg,research=replace(cfg.research,threshold_candidates=[.01]))
    b=run_walk_forward(X,y,f,cfg)
    k=b.oos_returns.index[12]; damaged=f.copy();damaged.loc[k]=np.nan
    r=run_walk_forward(X,y,damaged,cfg)
    detail=dict(missing_bar=str(k),baseline_rows=len(b.oos_returns),after_rows=len(r.oos_returns),before_position=float(r.oos_positions.loc[:k].iloc[-1]),after_position=float(r.oos_positions.loc[k:].iloc[0]))
    assert len(r.oos_returns)==len(b.oos_returns),json.dumps(detail)

def negative_target_vol():
    r=outcome(lambda:ExecutionConfig(target_vol=-.1).target_vol)
    assert not r["accepted"],json.dumps(r)

def manifest_overwrite():
    with TemporaryDirectory() as d:
        a=save_manifest({"experiment":{"experiment_id":"A"}},Path(d))
        b=save_manifest({"experiment":{"experiment_id":"B"}},Path(d))
        detail=dict(same_path=a==b,first_path_now_contains=json.loads(a.read_text()))
        assert a!=b,json.dumps(detail)

def missing_feature_control():
    X,y,f,cfg=cfg_and_data();X=X[["a"]]
    b=run_walk_forward(X,y,f,cfg)
    z=missing_data_stress(X,y,f,cfg,b,None)
    assert len(z)==1
    return z.to_dict("records")

def single_trial_dsr():
    actual=expected_max_sharpe(1,1000)
    assert actual==0.,str(actual)
    return {"actual":actual,"expected":0.}

if __name__=="__main__":
    warnings.filterwarnings("ignore", category=UserWarning)
    for fn in (event_units,arrival_inversion,exception_types,identical_event_ids,revision_conflict,
               stale_counter,live_counter_reset,full_membership_lock,lock_roundtrip,search_ledger_scope,
               calendar_boundaries,wide_csv_range,ohlcv_controls,configured_delay,nested_replay,
               configured_model_parameters,gradient_parameter_stress,missing_returns,negative_target_vol,
               manifest_overwrite,missing_feature_control):
        check(fn.__name__,fn)
    check("single_trial_dsr",single_trial_dsr)
