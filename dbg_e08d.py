import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from quant_research.config import AppConfig, EvaluationConfig, ModelConfig, ResearchConfig
from quant_research.strategies.discovery import discover_and_evaluate_oos
from quant_research.evaluation.robustness import replay_oos
idx = pd.bdate_range('2020-01-01', periods=244, tz='UTC')
rng = np.random.default_rng(810)
X = pd.DataFrame(rng.normal(size=(len(idx),3)), index=idx, columns=['a','b','c'])
fwd = pd.Series(rng.normal(0.001,0.009,len(idx)), index=idx)
y=(fwd>0).astype(float)
cfg=AppConfig(evaluation=EvaluationConfig(train_window=60,validation_window=30,test_window=30,step_bars=30,purge_bars=2,embargo_bars=2),model=ModelConfig(type='logistic'),research=ResearchConfig(max_trials=2,threshold_candidates=[0.0],hold_candidates=[1],placebo_runs=1,bootstrap_samples=10))
orig=discover_and_evaluate_oos(X,{'all':list(X)},y,fwd,cfg)
rep=replay_oos(X,y,fwd,cfg,orig,None)
p=orig.oos_positions.sort_index()
tb=p.diff().abs(); tb.iloc[0]=abs(p.iloc[0])
print('continuous turnover total',float(tb.sum()))
for s in orig.fold_specs:
    te=s.test_idx
    print('fold',s.fold_id,'cont slice sum',float(tb.loc[te].sum()),'orig fold row',float(orig.folds.loc[orig.folds.fold_id==s.fold_id,'oos_turnover'].iloc[0]),'replay fold row',float(rep.folds.loc[rep.folds.fold_id==s.fold_id,'oos_turnover'].iloc[0]))
    print('  cont slice head:',tb.loc[te[:3]].values,' pos head:',p.loc[te[:3]].values)
print('last bars fold1 pos:',p.loc[orig.fold_specs[0].test_idx[-3:]].values)
