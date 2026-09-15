"""
H-005 Trial 2: Bootstrap Significance Testing + Hyperparameter Variation
"""
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

# Set up paths
PROJECT_ROOT = Path(__file__).parent
os.chdir(PROJECT_ROOT)

from src.quant_research.data.loader import load_etf_data
from src.quant_research.features.overnight_intraday import compute_overnight_intraday_features
from src.quant_research.validation.walk_forward import walk_forward_validation
from src.quant_research.models.sklearn_adapter import SklearnModelAdapter

from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

def bootstrap_test(predictions, actuals, n_bootstrap=1000, seed=42):
    """Bootstrap significance test for Sharpe ratio"""
    np.random.seed(seed)
    returns = predictions * actuals
    
    # Calculate original Sharpe
    orig_sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    
    # Bootstrap samples
    bootstrap_sharpes = []
    n = len(returns)
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, size=n, replace=True)
        boot_returns = returns[idx]
        boot_mean = np.mean(boot_returns)
        boot_std = np.std(boot_returns)
        if boot_std > 0:
            bootstrap_sharpes.append(boot_mean / boot_std)
        else:
            bootstrap_sharpes.append(0)
    
    bootstrap_sharpes = np.array(bootstrap_sharpes)
    
    # Calculate p-value (proportion of bootstrap sharpes <= 0)
    p_value = np.mean(bootstrap_sharpes <= 0)
    positive_prob = np.mean(bootstrap_sharpes > 0)
    
    # Confidence intervals
    ci_lower = np.percentile(bootstrap_sharpes, 2.5)
    ci_upper = np.percentile(bootstrap_sharpes, 97.5)
    
    return {
        'original_sharpe': float(orig_sharpe),
        'bootstrap_mean_sharpe': float(np.mean(bootstrap_sharpes)),
        'bootstrap_std_sharpe': float(np.std(bootstrap_sharpes)),
        'p_value': float(p_value),
        'positive_probability': float(positive_prob),
        'ci_95_lower': float(ci_lower),
        'ci_95_upper': float(ci_upper),
        'n_bootstrap': n_bootstrap
    }

def run_trial(trial_num, config):
    """Run a single trial with specified configuration"""
    print(f"\n{'='*60}")
    print(f"H-005 Trial {trial_num}: {config['name']}")
    print(f"{'='*60}")
    
    # Load data
    print("\n[1/5] Loading data...")
    assets = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'GLD']
    data = load_etf_data(assets, start_date='2010-01-01', end_date='2021-12-31')
    print(f"  Loaded {len(data)} assets, date range: {data[0].index[0]} to {data[0].index[-1]}")
    
    # Compute features
    print("\n[2/5] Computing overnight-intraday features...")
    feature_df = compute_overnight_intraday_features(data)
    
    # Drop vix_regime if all NaN
    if feature_df['vix_regime'].isna().all():
        print("  Dropping vix_regime (all NaN)")
        feature_cols = [c for c in feature_df.columns if c not in ['vix_regime', 'target']]
    else:
        feature_cols = [c for c in feature_df.columns if c != 'target']
    
    print(f"  Features computed: {len(feature_cols)}")
    
    # Prepare target
    y = feature_df['target'].values
    X = feature_df[feature_cols].values
    
    # Impute missing values (simple mean imputation for now)
    from sklearn.impute import SimpleImputer
    imputer = SimpleImputer(strategy='mean')
    X = imputer.fit_transform(X)
    
    # Walk-forward validation
    print("\n[3/5] Running walk-forward validation...")
    model_class = config['model_class']
    hyperparams = config['hyperparameters']
    
    fold_results = []
    all_predictions = []
    all_actuals = []
    
    n_folds = 5
    fold_size = len(X) // n_folds
    
    for fold in range(n_folds):
        # Expanding window: train on folds 0..fold, test on fold+1
        train_end = (fold + 1) * fold_size
        test_start = train_end
        test_end = min(test_start + fold_size, len(X))
        
        if test_end >= len(X):
            break
            
        X_train = X[:train_end]
        y_train = y[:train_end]
        X_test = X[test_start:test_end]
        y_test = y[test_start:test_end]
        
        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train model
        if model_class == 'logistic_regression':
            model = LogisticRegression(**hyperparams, random_state=config.get('random_state', 42))
        elif model_class == 'ridge':
            model = Ridge(**hyperparams, random_state=config.get('random_state', 42))
        else:
            raise ValueError(f"Unknown model: {model_class}")
        
        model.fit(X_train_scaled, y_train)
        
        # Predict
        if model_class in ['logistic_regression']:
            y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
            # Convert to position: long if prob > 0.5
            y_pred = (y_pred_proba > 0.5).astype(float) * 2 - 1  # +1 or -1
        else:
            y_pred_cont = model.predict(X_test_scaled)
            y_pred = np.sign(y_pred_cont)
        
        # Calculate returns
        fold_returns = y_pred * y_test
        
        # Sharpe ratio (annualized, assuming daily)
        if np.std(fold_returns) > 0:
            sharpe = np.mean(fold_returns) / np.std(fold_returns) * np.sqrt(252)
        else:
            sharpe = 0
            
        fold_results.append({
            'fold': fold + 1,
            'sharpe': float(sharpe),
            'return': float(np.sum(fold_returns)),
            'samples': len(fold_returns)
        })
        
        all_predictions.extend(y_pred.tolist())
        all_actuals.extend(y_test.tolist())
        
        print(f"  Fold {fold+1}: Sharpe={sharpe:.3f}, Return={np.sum(fold_returns):.4f}")
    
    # Aggregate results
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
    
    # Bootstrap test
    print("\n[4/5] Running bootstrap significance test...")
    all_predictions = np.array(all_predictions)
    all_actuals = np.array(all_actuals)
    
    bootstrap_results = bootstrap_test(all_predictions, all_actuals, n_bootstrap=1000)
    print(f"  Bootstrap Positive Prob: {bootstrap_results['positive_probability']:.3f}")
    print(f"  P-value: {bootstrap_results['p_value']:.3f}")
    print(f"  95% CI: [{bootstrap_results['ci_95_lower']:.3f}, {bootstrap_results['ci_95_upper']:.3f}]")
    
    # Check gates
    print("\n[5/5] Checking gates...")
    gates = {
        'min_median_oos_sharpe': {
            'threshold': 0.0,
            'actual': aggregate['median_sharpe'],
            'passed': aggregate['median_sharpe'] > 0.0
        },
        'min_mean_oos_sharpe': {
            'threshold': 0.0,
            'actual': aggregate['mean_sharpe'],
            'passed': aggregate['mean_sharpe'] > 0.0
        },
        'min_bootstrap_positive_prob': {
            'threshold': 0.8,
            'actual': bootstrap_results['positive_probability'],
            'passed': bootstrap_results['positive_probability'] > 0.8
        },
        'significant_at_5pct': {
            'threshold': 0.05,
            'actual': bootstrap_results['p_value'],
            'passed': bootstrap_results['p_value'] < 0.05
        }
    }
    
    all_passed = all(g['passed'] for g in gates.values())
    print(f"  All gates passed: {all_passed}")
    for gate_name, gate_info in gates.items():
        status = "✓" if gate_info['passed'] else "✗"
        print(f"    {status} {gate_name}: {gate_info['actual']:.3f} > {gate_info['threshold']}")
    
    # Save results
    artifact_dir = PROJECT_ROOT / 'artifacts' / f'h005_trial{trial_num}'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    
    results = {
        'hypothesis_id': 'H-005',
        'hypothesis_name': 'Overnight-Intraday Return Decomposition',
        'trial_number': trial_num,
        'config_name': config['name'],
        'execution_timestamp': datetime.now().isoformat(),
        'data': {
            'assets': assets,
            'target': 'SPY',
            'period_start': '2010-01-01',
            'period_end': '2021-12-31'
        },
        'model': {
            'type': config['model_class'],
            'hyperparameters': hyperparams
        },
        'features': {
            'count': len(feature_cols),
            'names': feature_cols
        },
        'validation': {
            'method': 'walk_forward',
            'folds': len(fold_results),
            'fold_results': fold_results,
            'aggregate': aggregate
        },
        'bootstrap': bootstrap_results,
        'gates': gates,
        'status': 'passed' if all_passed else 'failed',
        'notes': config.get('notes', [])
    }
    
    results_file = artifact_dir / f'h005_trial{trial_num}_results.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n  Results saved to: {results_file}")
    
    return results

if __name__ == '__main__':
    # Trial 2: Ridge regression with regularization
    config_trial2 = {
        'name': 'Ridge Regression + Bootstrap Test',
        'model_class': 'ridge',
        'hyperparameters': {'alpha': 1.0},
        'random_state': 42,
        'notes': ['Testing ridge regression for robustness', 'Bootstrap test with 1000 samples']
    }
    
    # Trial 3: Logistic with different regularization
    config_trial3 = {
        'name': 'Logistic L2 Regularization C=1.0',
        'model_class': 'logistic_regression',
        'hyperparameters': {'C': 1.0, 'max_iter': 1000},
        'random_state': 42,
        'notes': ['Testing weaker regularization']
    }
    
    # Trial 4: Logistic with stronger regularization
    config_trial4 = {
        'name': 'Logistic L2 Regularization C=0.1',
        'model_class': 'logistic_regression',
        'hyperparameters': {'C': 0.1, 'max_iter': 1000},
        'random_state': 42,
        'notes': ['Testing moderate regularization']
    }
    
    print("="*60)
    print("H-005: Overnight-Intraday Return Decomposition")
    print("Executing Trials 2-4 with Bootstrap Significance Testing")
    print("="*60)
    
    results = []
    for trial_num, config in [(2, config_trial2), (3, config_trial3), (4, config_trial4)]:
        result = run_trial(trial_num, config)
        results.append(result)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY OF ALL TRIALS")
    print("="*60)
    
    # Include Trial 1
    trial1_file = PROJECT_ROOT / 'artifacts' / 'h005_trial1' / 'h005_trial1_results.json'
    if trial1_file.exists():
        with open(trial1_file, 'r') as f:
            trial1 = json.load(f)
        print(f"\nTrial 1 (Logistic C=0.01):")
        print(f"  Mean Sharpe: {trial1['validation']['aggregate']['mean_sharpe']:.3f}")
        print(f"  Status: {trial1['status']}")
    
    for result in results:
        print(f"\n{result['trial_number']} ({result['config_name']}):")
        print(f"  Mean Sharpe: {result['validation']['aggregate']['mean_sharpe']:.3f}")
        print(f"  Bootstrap Positive Prob: {result['bootstrap']['positive_probability']:.3f}")
        print(f"  P-value: {result['bootstrap']['p_value']:.3f}")
        print(f"  Status: {result['status']}")
    
    # Determine best trial
    best_trial = max(results + [json.loads(open(trial1_file).read())] if trial1_file.exists() else results,
                     key=lambda x: x['validation']['aggregate']['mean_sharpe'])
    
    print(f"\n{'='*60}")
    print(f"BEST PERFORMING TRIAL: {best_trial['trial_number']} ({best_trial.get('config_name', 'N/A')})")
    print(f"  Mean Sharpe: {best_trial['validation']['aggregate']['mean_sharpe']:.3f}")
    print(f"  Gates Passed: {sum(1 for g in best_trial['gates'].values() if g['passed'])}/{len(best_trial['gates'])}")
    print(f"{'='*60}")
