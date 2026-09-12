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
print('gross equal',(orig.oos_gross_returns==rep.oos_gross_returns).all())
print('net equal',(orig.oos_returns==rep.oos_returns).all())
print('oos pos head fold2 orig:'); print(orig.oos_positions.loc[orig.fold_specs[1].test_idx[:3]])
print('oos pos head fold2 replay:'); print(rep.oos_positions.loc[rep.fold_specs[1].test_idx[:3]])
print('preds equal',orig.predictions.equals(rep.predictions))
print('predictions head fold2 orig:'); print(orig.predictions.loc[orig.fold_specs[1].test_idx[:3]])
print('predictions head fold2 replay:'); print(rep.predictions.loc[rep.fold_specs[1].test_idx[:3]])
print('orig fees',orig.fee_costs,'replay fees',rep.fee_costs)
# check where they differ
d=(orig.oos_returns-rep.oos_returns).abs()
print(d[d>1e-12].head(20))
