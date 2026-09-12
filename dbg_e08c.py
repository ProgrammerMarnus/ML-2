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
for s in orig.fold_specs[1:]:
    t=s.test_idx[0]
    print(t, 'pos', orig.oos_positions.loc[t], 'orig net', orig.oos_returns.loc[t], 'replay net', rep.oos_returns.loc[t], 'gross', orig.oos_gross_returns.loc[t], 'fee+slip rate', (cfg.execution.fee_bps+cfg.execution.slippage_bps)/1e4, 'implied cost orig', orig.oos_gross_returns.loc[t]-orig.oos_returns.loc[t], 'replay', rep.oos_gross_returns.loc[t]-rep.oos_returns.loc[t])
print('turnover_full orig at starts:'); p=orig.oos_positions.sort_index(); tb=p.diff().abs(); tb.iloc[0]=abs(p.iloc[0]); print(tb.loc[[s.test_idx[0] for s in orig.fold_specs[1:]]])
print('per-fold turn replay fold slices first bars:')
for s in rep.fold_specs[1:]:
    print(s.fold_id, rep.oos_positions.loc[s.test_idx[:2]].values)
