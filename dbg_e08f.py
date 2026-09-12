import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from quant_research.config import AppConfig, EvaluationConfig, ModelConfig, ResearchConfig
from quant_research.strategies.discovery import discover_and_evaluate_oos
from quant_research.evaluation.robustness import fixed_thresholds_from
import quant_research.strategies.baseline as Bmod
from quant_research.evaluation import walk_forward as WF
idx = pd.bdate_range('2020-01-01', periods=244, tz='UTC')
rng = np.random.default_rng(810)
X = pd.DataFrame(rng.normal(size=(len(idx),3)), index=idx, columns=['a','b','c'])
fwd = pd.Series(rng.normal(0.001,0.009,len(idx)), index=idx)
y=(fwd>0).astype(float)
cfg=AppConfig(evaluation=EvaluationConfig(train_window=60,validation_window=30,test_window=30,step_bars=30,purge_bars=2,embargo_bars=2),model=ModelConfig(type='logistic'),research=ResearchConfig(max_trials=2,threshold_candidates=[0.0],hold_candidates=[1],placebo_runs=1,bootstrap_samples=10))
orig=discover_and_evaluate_oos(X,{'all':list(X)},y,fwd,cfg)
print('orig anchor len',len(orig.anchor_index),'policy',orig.boundary_policy)
print('fitted keys',list(orig.fitted_models.keys()),'thresholds',orig.thresholds)
print('per_fold_subsets keys',list(orig.per_fold_feature_subsets.keys()))
print('feature_subset',orig.feature_subset)
folds = WF.walk_forward_splits(orig.anchor_index, cfg.evaluation)
print('n folds recomputed',len(folds))
for s in folds:
    print(s.fold_id, s.test_idx.min(), s.test_idx.max())
# replicate replay arg resolution
from quant_research.evaluation.robustness import replay_oos
print('fixed_thresholds',fixed_thresholds_from(orig))
capt={}
real_bt=Bmod.backtest
def spy(sig,*a,**k):
    print('backtest called with sig len',len(sig),sig.index.min(),sig.index.max())
    r=real_bt(sig,*a,**k)
    capt['bt']=r
    return r
Bmod.backtest=spy
try:
    rep=replay_oos(X,y,fwd,cfg,orig,None)
finally:
    Bmod.backtest=real_bt
print('rep folds',len(rep.folds),'oos len',len(rep.oos_positions))
