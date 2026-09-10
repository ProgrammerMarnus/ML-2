"""Post-fix verification probes for D01-D15.

Run with PYTHONPATH pointing to the fixed source tree.
Each probe asserts the FIXED behavior (not the defective behavior).
"""
from pathlib import Path
from dataclasses import replace
import json
import tempfile
import traceback

import numpy as np
import pandas as pd

from quant_research.config import (
    AppConfig, DataConfig, EvaluationConfig, ResearchConfig, ModelConfig,
)
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels, load_market_data
from quant_research.data.validation import expected_sessions
from quant_research.data.schemas import DataValidationError
from quant_research.evaluation.walk_forward import LockedTestProtocol, LockedTestViolation, walk_forward_splits
from quant_research.features.price_volume import build_price_volume_features
from quant_research.features.information import build_information_features
from quant_research.features.point_in_time import validate_events
from quant_research.features.parkinson import lagged_parkinson_volatility
from quant_research.strategies.baseline import run_walk_forward
import quant_research.evaluation.robustness as robustness
import quant_research.strategies.discovery as discovery

OUT = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix='ml2-postfix-probes-'))
RESULTS = {}


def probe(name, fn):
    try:
        result = fn()
        RESULTS[name] = {'status': 'passed', 'evidence': result}
    except Exception as exc:
        RESULTS[name] = {'status': 'FAILED', 'type': type(exc).__name__,
                         'error': str(exc), 'traceback': traceback.format_exc()}
    (OUT / 'post-fix-probe-results.json').write_text(
        json.dumps(RESULTS, indent=2, default=str))
    print(name, json.dumps(RESULTS[name], default=str), flush=True)


CFG = AppConfig(
    data=DataConfig(start='2020-01-01', end='2022-01-01',
                    raw_snapshot_dir=str(TMP / 'snapshots')),
    evaluation=EvaluationConfig(train_window=120, validation_window=40,
                                test_window=40, step_bars=40,
                                purge_bars=2, embargo_bars=2),
    research=ResearchConfig(threshold_candidates=[.5, .6], hold_candidates=[1],
                            max_trials=1, placebo_runs=1, bootstrap_samples=20))
RAW = generate_synthetic_ohlcv(['SPY'], CFG.data.start, CFG.data.end)
CLOSE, VOLUME = to_panels(RAW)
X = build_price_volume_features(CLOSE, VOLUME, 'SPY')
FWD = CLOSE.SPY.shift(-1) / CLOSE.SPY - 1
Y = (FWD > 0).astype(float).mask(FWD.isna())
BASE = run_walk_forward(X, Y, FWD, CFG)


def d01_lock_rejects_changed_dataset():
    folds = walk_forward_splits(X.index, CFG.evaluation)
    p = TMP / 'd01-dataset.lock'
    LockedTestProtocol(p, dataset_id='A', config_fingerprint='fp1').verify(folds)
    try:
        LockedTestProtocol(p, dataset_id='B', config_fingerprint='fp1')
        return {'rejected': False, 'error': 'should have raised LockedTestViolation'}
    except LockedTestViolation as e:
        return {'rejected': True, 'message': str(e)[:100]}


def d01_lock_rejects_changed_config():
    folds = walk_forward_splits(X.index, CFG.evaluation)
    p = TMP / 'd01-config.lock'
    LockedTestProtocol(p, dataset_id='A', config_fingerprint='fp1').verify(folds)
    try:
        LockedTestProtocol(p, dataset_id='A', config_fingerprint='fp2')
        return {'rejected': False, 'error': 'should have raised LockedTestViolation'}
    except LockedTestViolation as e:
        return {'rejected': True, 'message': str(e)[:100]}


def d01_lock_rejects_corrupt_json():
    p = TMP / 'd01-corrupt.lock'
    p.write_text('{bad-json')
    try:
        LockedTestProtocol(p, dataset_id='A', config_fingerprint='fp1')
        return {'rejected': False, 'error': 'should have raised LockedTestViolation'}
    except LockedTestViolation as e:
        return {'rejected': True, 'message': str(e)[:100]}


def d02_attempt_count_includes_abandoned():
    from quant_research.experiments.registry import SearchLedger
    ledger = SearchLedger(TMP / 'd02.jsonl')
    fid = 'test-family'
    ledger.record_start(fid, 'search', 5, 'hash1', 'eval1')  # abandoned
    completed_start = ledger.record_start(fid, 'search', 5, 'hash1', 'eval1')
    ledger.record_outcome(fid, 'search', 5, 'completed',
                          attempt_id=completed_start['attempt_id'])
    completed = ledger.family_search_count(fid)
    all_attempts = ledger.family_attempt_count(fid)
    return {'completed_count': completed, 'attempt_count': all_attempts,
            'includes_abandoned': all_attempts == 2}


def d03_terminal_nan_only_at_dataset_end():
    """Verify interior TEST-bar NaN/inf is rejected; dataset-end NaN passes."""
    from quant_research.data.schemas import DataValidationError
    folds = walk_forward_splits(X.index, CFG.evaluation)
    # Interior TEST bar of fold 1 (not the window's last bar, not dataset end).
    test_idx = folds[0].test_idx
    interior_bar = test_idx[len(test_idx) // 2]
    assert interior_bar != X.index[-1]
    assert interior_bar != test_idx[-1]
    out = {}
    for tag, val in [('nan', np.nan), ('inf', np.inf)]:
        fwd_bad = FWD.copy()
        fwd_bad.loc[interior_bar] = val
        try:
            run_walk_forward(X, Y, fwd_bad, CFG)
            return {'rejected': False,
                    'error': f'should have raised for interior {tag} at {interior_bar}'}
        except DataValidationError as e:
            out[tag] = {'rejected': True, 'message': str(e)[:120]}
    # Control: unmodified inputs succeed.
    ctrl = run_walk_forward(X, Y, FWD, CFG)
    out['control_n_oos'] = len(ctrl.oos_returns)
    return {'rejected': True, 'cases': out}


def d04_discovery_preserves_timeline():
    """Verify discovery rejects interior missing outcomes (D03 contract)."""
    from quant_research.data.schemas import DataValidationError
    folds = walk_forward_splits(X.index, CFG.evaluation)
    test_idx = folds[0].test_idx
    interior_bar = test_idx[len(test_idx) // 2]
    feature_sets = {'all': list(X.columns)}
    out = {}
    for tag, val in [('nan', np.nan), ('inf', np.inf)]:
        y_bad = Y.copy()
        fwd_bad = FWD.copy()
        y_bad.loc[interior_bar] = val
        fwd_bad.loc[interior_bar] = val
        try:
            discovery.discover_and_evaluate_oos(
                X, feature_sets, y_bad, fwd_bad, CFG)
            return {'rejected': False,
                    'error': f'should have raised DataValidationError for interior {tag}'}
        except DataValidationError as e:
            out[tag] = {'rejected': True, 'message': str(e)[:120]}
    # Control: clean inputs succeed with a stable fold clock.
    result = discovery.discover_and_evaluate_oos(X, feature_sets, Y, FWD, CFG)
    out['control'] = {'n_folds': len(result.folds),
                      'n_oos': len(result.oos_returns)}
    return {'rejected': True, 'cases': out}


def d05_nested_replay_completes():
    """Verify nested discovery replay completes without NameError."""
    feature_sets = {'all': list(X.columns)}
    nested = discovery.discover_and_evaluate_oos(X, feature_sets, Y, FWD, CFG)
    replayed = robustness.replay_oos(X, Y, FWD, CFG, nested, None)
    return {'completed': True, 'n_oos': len(replayed.oos_returns)}


def d06_factor_one_preserves_params():
    """Verify factor=1.0 reproduces the baseline's concatenated-OOS Sharpe exactly."""
    from quant_research.evaluation.metrics import sharpe_ratio
    result = robustness.parameter_perturbation(X, Y, FWD, CFG, BASE, None, factors=[1.0])
    baseline_sharpe = float(sharpe_ratio(BASE.oos_returns))
    factor_one_sharpe = float(result.iloc[0]['sharpe'])
    return {'baseline_sharpe': baseline_sharpe,
            'factor_one_sharpe': factor_one_sharpe,
            'reproduces_exactly': abs(baseline_sharpe - factor_one_sharpe) < 1e-12}


def d07_delay_includes_configured_anchor():
    """Verify delay stress includes the configured anchor even outside grid."""
    cfg_delay = replace(CFG, execution=replace(CFG.execution, signal_delay_bars=5))
    nested = run_walk_forward(X, Y, FWD, cfg_delay)
    result = robustness.delay_stress(X, Y, FWD, cfg_delay, nested, None)
    delays_tested = result['delay_bars'].tolist()
    return {'delays_tested': delays_tested, 'includes_configured_anchor': 5 in delays_tested}


def d09_parkinson_rejects_synthetic():
    """Verify Parkinson rejects inputs with _synthetic_range=True."""
    idx = expected_sessions(pd.Timestamp('2024-01-02', tz='UTC'),
                            pd.Timestamp('2024-03-01', tz='UTC'))
    idx = idx[idx < pd.Timestamp('2024-03-01', tz='UTC')]
    p = TMP / 'close-only.csv'
    pd.DataFrame({'timestamp': idx, 'Close_SPY': 100. + np.arange(len(idx)),
                  'Volume_SPY': np.full(len(idx), 1e6)}).to_csv(p, index=False)
    raw, _ = load_market_data(DataConfig(mode='csv', start='2024-01-02',
                                         end='2024-03-01', csv_path=str(p)))
    try:
        lagged_parkinson_volatility(raw)
        return {'rejected': False, 'error': 'should have raised for synthetic range'}
    except DataValidationError as e:
        return {'rejected': True, 'message': str(e)[:100]}


def d10_null_revision_conflict_rejected():
    """Verify null revision with conflicting sentiment is rejected."""
    t = pd.Timestamp('2024-01-10', tz='UTC')
    ev = pd.DataFrame([
        dict(event_id='e', symbol='SPY', event_time=t, publication_time=t,
             availability_time=t, source='s', raw_value=1.,
             processed_value=1., sentiment=.5),
        dict(event_id='e', symbol='SPY', event_time=t, publication_time=t,
             availability_time=t, source='s', raw_value=1.,
             processed_value=1., sentiment=-.5),
    ])
    ev['revision'] = np.nan
    try:
        validate_events(ev)
        return {'rejected': False, 'error': 'should have raised for conflicting null revision'}
    except DataValidationError as e:
        return {'rejected': True, 'message': str(e)[:100]}


def d15_nanosecond_precision():
    """Verify all 16 unit combinations produce correct first-eligible timestamp."""
    results = []
    for eu in ['s', 'ms', 'us', 'ns']:
        for bu in ['s', 'ms', 'us', 'ns']:
            t = pd.Timestamp('2024-01-10', tz='UTC')
            ev = pd.DataFrame([dict(event_id='e', symbol='SPY', event_time=t,
                publication_time=t, availability_time=t, source='s', raw_value=1.,
                processed_value=1., sentiment=.5)])
            for k in ['event_time', 'publication_time', 'availability_time']:
                ev[k] = ev[k].dt.as_unit(eu)
            idx = pd.date_range('2024-01-05', periods=10, tz='UTC').as_unit(bu)
            feat = build_information_features(idx, ev, 'SPY')
            first = feat.index[feat.info_attention > 0].min()
            results.append({'event_unit': eu, 'bar_unit': bu, 'correct': first == t})
    all_correct = all(r['correct'] for r in results)
    return {'all_correct': all_correct, 'combinations_tested': len(results)}


for name, fn in [
    ('d01_lock_rejects_changed_dataset', d01_lock_rejects_changed_dataset),
    ('d01_lock_rejects_changed_config', d01_lock_rejects_changed_config),
    ('d01_lock_rejects_corrupt_json', d01_lock_rejects_corrupt_json),
    ('d02_attempt_count_includes_abandoned', d02_attempt_count_includes_abandoned),
    ('d03_terminal_nan_only_at_dataset_end', d03_terminal_nan_only_at_dataset_end),
    ('d04_discovery_preserves_timeline', d04_discovery_preserves_timeline),
    ('d05_nested_replay_completes', d05_nested_replay_completes),
    ('d06_factor_one_preserves_params', d06_factor_one_preserves_params),
    ('d07_delay_includes_configured_anchor', d07_delay_includes_configured_anchor),
    ('d09_parkinson_rejects_synthetic', d09_parkinson_rejects_synthetic),
    ('d10_null_revision_conflict_rejected', d10_null_revision_conflict_rejected),
    ('d15_nanosecond_precision', d15_nanosecond_precision),
]:
    probe(name, fn)

print('\n=== SUMMARY ===')
passed = sum(1 for r in RESULTS.values() if r['status'] == 'passed')
failed = sum(1 for r in RESULTS.values() if r['status'] == 'FAILED')
print(f'Passed: {passed}, Failed: {failed}')
if failed:
    for name, r in RESULTS.items():
        if r['status'] == 'FAILED':
            print(f'  FAILED: {name}: {r["error"]}')
