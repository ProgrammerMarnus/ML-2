import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from quant_research.config import AppConfig, EvaluationConfig, ModelConfig, ResearchConfig
from quant_research.strategies.discovery import discover_and_evaluate_oos
from quant_research.evaluation.robustness import replay_oos
from quant_research.strategies import baseline as B
idx = pd.bdate_range('2020-01-01', periods=244, tz='UTC')
rng = np.random.default_rng(810)
X = pd.DataFrame(rng.normal(size=(len(idx),3)), index=idx, columns=['a','b','c'])
fwd = pd.Series(rng.normal(0.001,0.009,len(idx)), index=idx)
y=(fwd>0).astype(float)
cfg=AppConfig(evaluation=EvaluationConfig(train_window=60,validation_window=30,test_window=30,step_bars=30,purge_bars=2,embargo_bars=2),model=ModelConfig(type='logistic'),research=ResearchConfig(max_trials=2,threshold_candidates=[0.0],hold_candidates=[1],placebo_runs=1,bootstrap_samples=10))
orig=discover_and_evaluate_oos(X,{'all':list(X)},y,fwd,cfg)
# monkeypatch backtest to capture bt
capt={}
import quant_research.strategies.baseline as Bmod
real_bt=Bmod.backtest
def spy(*a,**k):
    r=real_bt(*a,**k)
    capt['bt']=r
    return r
Bmod.backtest=spy
try:
    rep=replay_oos(X,y,fwd,cfg,orig,None)
finally:
    Bmod.backtest=real_bt
bt=capt['bt']
for s in orig.fold_specs[:2]:
    te=s.test_idx
    print('fold',s.fold_id,'window',te[0],te[-1])
    print(' bt.pos head:',bt.positions.loc[te[:3]].values)
    print(' bt.turn head:',bt.turnover.loc[te[:3]].values)
print('boundary fold1last->fold2first:')
t0=orig.fold_specs[0].test_idx[-1]; t1=orig.fold_specs[1].test_idx[0]
print(' bt pos:',bt.positions.loc[t0],bt.positions.loc[t1],'bt turn at t1:',bt.turnover.loc[t1])
p=rep.oos_positions.sort_index(); tb=p.diff().abs(); tb.iloc[0]=abs(p.iloc[0])
print(' replay slice turn at t1:',tb.loc[t1])
print('replay fold2 row turnover:',rep.folds.loc[rep.folds.fold_id==2,'oos_turnover'].iloc[0])
print('bt slice sum fold2:',float(bt.turnover.loc[orig.fold_specs[1].test_idx].sum()))
