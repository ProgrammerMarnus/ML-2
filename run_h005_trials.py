"""H-005 Trials 2-4: Bootstrap Significance Testing + Hyperparameter Variation"""
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
import yfinance as yf

PROJECT_ROOT = Path(__file__).parent
os.chdir(PROJECT_ROOT)

from src.quant_research.features.overnight_intraday import compute_overnight_intraday_features
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

def load_etf_data(assets, start_date, end_date):
    """Load ETF data from yfinance"""
    result = {}
    for asset in assets:
        ticker = yf.Ticker(asset)
        df = ticker.history(start=start_date, end=end_date)
        if len(df) > 0:
            result[f'{asset}_open'] = df['Open']
            result[f'{asset}_high'] = df['High']
            result[f'{asset}_low'] = df['Low']
            result[f'{asset}_close'] = df['Close']
            result[f'{asset}_volume'] = df['Volume']
    return pd.DataFrame(result)

def bootstrap_test(predictions, actuals, n_bootstrap=1000, seed=42):
    """Bootstrap significance test for Sharpe ratio"""
    np.random.seed(seed)
    returns = predictions * actuals
    orig_sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    
    bootstrap_sharpes = []
    n = len(returns)
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, size=n, replace=True)
        boot_returns = returns[idx]
        boot_std = np.std(boot_returns)
        if boot_std > 0:
            bootstrap_sharpes.append(np.mean(boot_returns) / boot_std)
        else:
            bootstrap_sharpes.append(0)
    
    bootstrap_sharpes = np.array(bootstrap_sharpes)
    return {
        'original_sharpe': float(orig_sharpe),
        'bootstrap_mean_sharpe': float(np.mean(bootstrap_sharpes)),
        'bootstrap_std_sharpe': float(np.std(bootstrap_sharpes)),
        'p_value': float(np.mean(bootstrap_sharpes <= 0)),
        'positive_probability': float(np.mean(bootstrap_sharpes > 0)),
        'ci_95_lower': float(np.percentile(bootstrap_sharpes, 2.5)),
        'ci_95_upper': float(np.percentile(bootstrap_sharpes, 97.5)),
        'n_bootstrap': n_bootstrap
    }

def run_trial(trial_num, config):
    """Run a single trial"""
    print(f"\n{'='*60}")
    print(f"H-005 Trial {trial_num}: {config['name']}")
    print(f"{'='*60}")
    
    print("\n[1/5] Loading data...")
    assets = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'GLD']
    raw_data = load_etf_data(assets, '2010-01-01', '2021-12-31')
    print(f"  Loaded {len(assets)} assets: {raw_data.index[0]} to {raw_data.index[-1]}")
    
    print("\n[2/5] Computing features...")
    feature_df = compute_overnight_intraday_features(
        open_price=raw_data['SPY_open'],
        high=raw_data['SPY_high'],
        low=raw_data['SPY_low'],
        close=raw_data['SPY_close'],
        volume=raw_data['SPY_volume']
    )
    
    # Add target: next day's overnight return (what we're predicting)
    # Target = sign of next day's overnight return
    overnight_ret = (raw_data['SPY_open'] - raw_data['SPY_close'].shift(1)) / raw_data['SPY_close'].shift(1)
    feature_df['target'] = np.sign(overnight_ret.shift(-1))  # Predict next day's overnight direction
    
    if 'vix_regime' in feature_df.columns and feature_df['vix_regime'].isna().all():
        print("  Dropping vix_regime (all NaN)")
        feature_cols = [c for c in feature_df.columns if c not in ['vix_regime', 'target']]
    else:
        feature_cols = [c for c in feature_df.columns if c != 'target']
    
    print(f"  Features: {len(feature_cols)}, Target: overnight return direction")
    
    y = feature_df['target'].values
    X = feature_df[feature_cols].values
    
    imputer = SimpleImputer(strategy='mean')
    X = imputer.fit_transform(X)
    
    print("\n[3/5] Walk-forward validation...")
    model_class = config['model_class']
    hyperparams = config['hyperparameters']
    
    fold_results = []
    all_predictions = []
    all_actuals = []
    
    n_folds = 5
    fold_size = len(X) // n_folds
    
    for fold in range(n_folds):
        train_end = (fold + 1) * fold_size
        test_start = train_end
        test_end = min(test_start + fold_size, len(X))
        
        if test_end >= len(X):
            break
        
        X_train, y_train = X[:train_end], y[:train_end]
        X_test, y_test = X[test_start:test_end], y[test_start:test_end]
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        if model_class == 'logistic_regression':
            model = LogisticRegression(**hyperparams, random_state=config.get('random_state', 42))
        elif model_class == 'ridge':
            model = Ridge(**hyperparams, random_state=config.get('random_state', 42))
        else:
            raise ValueError(f"Unknown model: {model_class}")
        
        model.fit(X_train_scaled, y_train)
        
        if model_class == 'logistic_regression':
            y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
            y_pred = (y_pred_proba > 0.5).astype(float) * 2 - 1
        else:
            y_pred = np.sign(model.predict(X_test_scaled))
        
        fold_returns = y_pred * y_test
        sharpe = np.mean(fold_returns) / np.std(fold_returns) * np.sqrt(252) if np.std(fold_returns) > 0 else 0
        
        fold_results.append({'fold': fold+1, 'sharpe': float(sharpe), 'return': float(np.sum(fold_returns)), 'samples': len(fold_returns)})
        all_predictions.extend(y_pred.tolist())
        all_actuals.extend(y_test.tolist())
        print(f"  Fold {fold+1}: Sharpe={sharpe:.3f}, Return={np.sum(fold_returns):.4f}")
    
    sharpes = [f['sharpe'] for f in fold_results]
    returns = [f['return'] for f in fold_results]
    
    aggregate = {
        'mean_sharpe': float(np.mean(sharpes)),
        'std_sharpe': float(np.std(sharpes)),
        'median_sharpe': float(np.median(sharpes)),
        'total_return': float(np.sum(returns)),
        'positive_folds': sum(1 for s in sharpes if s > 0),
        'total_folds': len(sharpes)
    }
    
    print(f"\n  Aggregate: Mean Sharpe={aggregate['mean_sharpe']:.3f}, Total Return={aggregate['total_return']:.4f}")
    
    print("\n[4/5] Bootstrap test...")
    all_predictions, all_actuals = np.array(all_predictions), np.array(all_actuals)
    bootstrap_results = bootstrap_test(all_predictions, all_actuals, n_bootstrap=1000)
    print(f"  Positive Prob: {bootstrap_results['positive_probability']:.3f}, P-value: {bootstrap_results['p_value']:.3f}")
    print(f"  95% CI: [{bootstrap_results['ci_95_lower']:.3f}, {bootstrap_results['ci_95_upper']:.3f}]")
    
    print("\n[5/5] Checking gates...")
    gates = {
        'min_median_oos_sharpe': {'threshold': 0.0, 'actual': aggregate['median_sharpe'], 'passed': aggregate['median_sharpe'] > 0.0},
        'min_mean_oos_sharpe': {'threshold': 0.0, 'actual': aggregate['mean_sharpe'], 'passed': aggregate['mean_sharpe'] > 0.0},
        'min_bootstrap_positive_prob': {'threshold': 0.8, 'actual': bootstrap_results['positive_probability'], 'passed': bootstrap_results['positive_probability'] > 0.8},
        'significant_at_5pct': {'threshold': 0.05, 'actual': bootstrap_results['p_value'], 'passed': bootstrap_results['p_value'] < 0.05}
    }
    
    all_passed = all(g['passed'] for g in gates.values())
    print(f"  All gates passed: {all_passed}")
    for name, info in gates.items():
        print(f"    [{'PASS' if info['passed'] else 'FAIL'}] {name}: {info['actual']:.3f} vs {info['threshold']}")
    
    artifact_dir = PROJECT_ROOT / 'artifacts' / f'h005_trial{trial_num}'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    
    results = {
        'hypothesis_id': 'H-005',
        'hypothesis_name': 'Overnight-Intraday Return Decomposition',
        'trial_number': trial_num,
        'config_name': config['name'],
        'execution_timestamp': datetime.now().isoformat(),
        'data': {'assets': assets, 'target': 'SPY', 'period_start': '2010-01-01', 'period_end': '2021-12-31'},
        'model': {'type': config['model_class'], 'hyperparameters': hyperparams},
        'features': {'count': len(feature_cols), 'names': list(feature_cols)},
        'validation': {'method': 'walk_forward', 'folds': len(fold_results), 'fold_results': fold_results, 'aggregate': aggregate},
        'bootstrap': bootstrap_results,
        'gates': gates,
        'status': 'passed' if all_passed else 'failed',
        'notes': config.get('notes', [])
    }
    
    with open(artifact_dir / f'h005_trial{trial_num}_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n  Saved: {artifact_dir / f'h005_trial{trial_num}_results.json'}")
    return results

if __name__ == '__main__':
    configs = [
        (2, {'name': 'Ridge Regression + Bootstrap', 'model_class': 'ridge', 'hyperparameters': {'alpha': 1.0}, 'random_state': 42, 'notes': ['Testing ridge regression']}),
        (3, {'name': 'Logistic C=1.0', 'model_class': 'logistic_regression', 'hyperparameters': {'C': 1.0, 'max_iter': 1000}, 'random_state': 42, 'notes': ['Weaker regularization']}),
        (4, {'name': 'Logistic C=0.1', 'model_class': 'logistic_regression', 'hyperparameters': {'C': 0.1, 'max_iter': 1000}, 'random_state': 42, 'notes': ['Moderate regularization']})
    ]
    
    print("="*60)
    print("H-005: Trials 2-4 with Bootstrap Testing")
    print("="*60)
    
    results = []
    for trial_num, config in configs:
        results.append(run_trial(trial_num, config))
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    trial1_file = PROJECT_ROOT / 'artifacts' / 'h005_trial1' / 'h005_trial1_results.json'
    if trial1_file.exists():
        trial1 = json.loads(open(trial1_file).read())
        print(f"\nTrial 1 (Logistic C=0.01): Sharpe={trial1['validation']['aggregate']['mean_sharpe']:.3f}, Status={trial1['status']}")
    
    for r in results:
        print(f"Trial {r['trial_number']} ({r['config_name']}): Sharpe={r['validation']['aggregate']['mean_sharpe']:.3f}, BootProb={r['bootstrap']['positive_probability']:.3f}, Status={r['status']}")
    
    all_trials = results[:]
    if trial1_file.exists():
        all_trials.append(json.loads(open(trial1_file).read()))
    
    best = max(all_trials, key=lambda x: x['validation']['aggregate']['mean_sharpe'])
    print(f"\n{'='*60}")
    print(f"BEST: Trial {best['trial_number']} ({best.get('config_name', 'N/A')})")
    print(f"  Sharpe: {best['validation']['aggregate']['mean_sharpe']:.3f}")
    print(f"  Gates: {sum(1 for g in best['gates'].values() if g['passed'])}/{len(best['gates'])}")
    print(f"{'='*60}")
