"""Additional precision and static provenance evidence for the deep audit."""
from pathlib import Path
import ast,json
import numpy as np
import pandas as pd
from quant_research.features.information import build_information_features

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
t=pd.Timestamp('2024-01-10',tz='UTC')
a=t+pd.Timedelta(nanoseconds=1)
ev=pd.DataFrame([dict(event_id='e',symbol='SPY',event_time=t,publication_time=a,
    availability_time=a,source='s',raw_value=1.,processed_value=1.,sentiment=.5)])
for c in ['event_time','publication_time','availability_time']:
    ev[c]=ev[c].dt.as_unit('ns')
idx=pd.date_range(t,periods=2).as_unit('ns')
f=build_information_features(idx,ev,'SPY')
precision={'bar_time':str(t),'availability_time':str(a),
    'attention_at_bar':float(f.info_attention.iloc[0]),
    'ineligible_event_included':bool(a>t and f.info_attention.iloc[0]>0)}
(OUT/'submicrosecond-results.json').write_text(json.dumps(precision,indent=2))

paths=list((ROOT/'src/quant_research').rglob('*.py'))+list((ROOT/'tests').glob('*.py'))
for p in paths:compile(p.read_text(),str(p),'exec')
criteria=ast.parse((ROOT/'tests/test_audit_criteria.py').read_text())
unit_test=next(n for n in criteria.body if isinstance(n,ast.FunctionDef) and n.name=='test_c01_availability_unit_invariance_all_combinations')
calls=[ast.unparse(n) for n in ast.walk(unit_test) if isinstance(n,ast.Call)]
manifest=json.loads(next((OUT/'market-run').glob('*_manifest.json')).read_text())
registry=[json.loads(l) for l in (OUT/'market-run/experiment_registry.jsonl').read_text().splitlines()]
static={'all_source_and_test_files_compile':True,'compiled_file_count':len(paths),
    'source_modules':len(list((ROOT/'src/quant_research').rglob('*.py'))),
    'test_modules':len(list((ROOT/'tests').glob('test_*.py'))),
    'unit_regression_calls':calls,
    'unit_regression_has_as_unit_call':any('.as_unit(' in c for c in calls),
    'manifest_features_keys':list(manifest['inputs']['features']),
    'manifest_events_keys':list(manifest['inputs']['events']),
    'manifest_fitted_model_fields':list(next(iter(manifest['fitted_models'].values()))),
    'registry_record_has_manifest_path':any('manifest_path' in r for r in registry)}
(OUT/'static-check-results.json').write_text(json.dumps(static,indent=2))
print(json.dumps({'precision':precision,'static':static},indent=2))
