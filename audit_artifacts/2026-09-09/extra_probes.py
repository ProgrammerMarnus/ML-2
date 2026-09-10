"""Follow-up boundary probes discovered during source review."""
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
from scipy.stats import norm
from quant_research.features.information import build_information_features
from quant_research.config import ExecutionConfig
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.multiple_testing import expected_max_sharpe, deflated_sharpe_pvalue
from quant_research.evaluation.robustness import assert_cost_accounting
from types import SimpleNamespace

OUT = Path(__file__).resolve().parent
results = {}

idx = pd.date_range('2024-01-05',periods=10,tz='UTC')
events = pd.DataFrame([dict(event_id='future',symbol='SPY',event_time=pd.Timestamp('2024-01-10',tz='UTC'),
    publication_time=pd.Timestamp('2024-01-10',tz='UTC'),availability_time=pd.Timestamp('2024-01-10',tz='UTC'),
    source='wire',raw_value=1.,processed_value=1.,sentiment=1.)])
for col in ('event_time','publication_time','availability_time'):
    events[col] = events[col].dt.as_unit('us')
us = build_information_features(idx.as_unit('us'),events,'SPY')
ns = build_information_features(idx.as_unit('ns'),events,'SPY')
assert us.info_attention.iloc[0] == 0 and ns.info_attention.iloc[0] > 0
results['timestamp_units'] = {'events_dtype':str(events.availability_time.dtype),
    'same_logical_timestamps':bool(idx.as_unit('us').equals(idx.as_unit('ns'))),
    'bars_us_attention':us.info_attention.tolist(),'bars_ns_attention':ns.info_attention.tolist(),
    'event_available':'2024-01-10T00:00:00Z','first_bar':'2024-01-05T00:00:00Z',
    'units_must_not_change_logical_availability':True}

# Current configuration accepts undefined fees. The standalone backtest
# reports zero summed fees, while the production accounting check rejects it.
idx=pd.bdate_range('2024-01-01',periods=100,tz='UTC')
r=pd.Series(np.resize([.002,-.001],len(idx)),index=idx)
bt=backtest(pd.Series(1.,index=idx),r,ExecutionConfig(fee_bps=float('nan')),risk_returns=r)
assert bt.net_returns.isna().all()
stub=SimpleNamespace(oos_positions=bt.positions,oos_returns=bt.net_returns,oos_gross_returns=bt.gross_returns,
    fee_costs=bt.metrics['fee_cost'],slippage_costs=bt.metrics['slippage_cost'],
    folds=pd.DataFrame({'oos_turnover':[bt.turnover.sum()]}))
try:
    assert_cost_accounting(stub,float('nan'),1.)
except AssertionError as exc:
    accounting={'rejected':True,'error':str(exc)}
else:
    accounting={'rejected':False}
results['nonfinite_fee']={'accepted_configuration':True,'nonfinite_net_bars':int(bt.net_returns.isna().sum()),
    'reported_metrics':bt.metrics,'accounting':accounting}

# With one trial, max over one zero-mean null is itself zero-mean. The API
# silently applies a two-trial search correction instead.
e=expected_max_sharpe(1,1000)
got=deflated_sharpe_pvalue(1.,1,1000)
sr=1/np.sqrt(252)
reference=float(norm.sf(np.sqrt(999)*sr/np.sqrt(1+.5*sr**2)))
assert e > 0 and got > reference
results['single_trial_deflation']={'expected_null_max_for_one_trial':0.,'actual_daily_null_max':e,
    'actual_one_trial_p':got,'single_strategy_psr_tail':reference}

(OUT/'extra-probe-results.json').write_text(json.dumps(results,indent=2,default=str)+'\n')
print(json.dumps(results,indent=2,default=str),flush=True)
