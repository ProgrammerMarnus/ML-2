# Phase 1, Step 5: Research Campaign - CRITICAL BLOCKER IDENTIFIED

## Status: ⚠️ BLOCKED - Framework Configuration Issue

**Date:** 2026-09-14  
**Blocker Type:** Technical (not scientific)

---

## Problem Summary

The experiment automation module is **ignoring hypothesis-specific configurations** and always running default templates. This has caused us to waste 4 trial executions on invalid tests.

### Evidence of Bug

| Trial | Config Used | Features Expected | Features Actually Used | Result |
|-------|-------------|-------------------|------------------------|--------|
| H-001 T1 | phase1_hypotheses.yaml | cross_asset_spillover (10) | price_volume only | FAILED |
| H-001 T2 | phase1_hypotheses.yaml | cross_asset_spillover (10) | price_volume only | FAILED (identical) |
| H-002 T1 | phase1_hypotheses.yaml | liquidity_reversal (13) | price_volume only | FAILED |
| H-002 T2 | h002_liquidity_trial.yaml | liquidity_reversal (13) | price_volume only | FAILED (identical) |

**All 4 trials produced IDENTICAL results:**
- Sharpe: -0.41
- Bootstrap: 35%
- Placebo: 0.10
- Same 7 failed gates

This proves the automation is using default `regularized_directional_logistic_*` templates regardless of config file settings.

---

## Root Cause Analysis

The `automation.py` module's `DEFAULT_TEMPLATES` are hardcoded and not overridden by config files:

```python
DEFAULT_TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate(
        strategy_id="regularized_directional_logistic_short_hold",
        mechanism=("Persistent price and information states..."),
        model=ModelConfig(type="logistic", random_seed=42, logreg_C=0.25, hold_bars=3),
    ),
    # ... more hardcoded templates
)
```

The `features:` section in YAML configs is being ignored. The registry shows 73 features available (including 13 liquidity, 10 spillover, 21 vol risk premium), but none are being selected.

---

## Required Fixes

### Option A: Fix Automation Module (Recommended)
Modify `src/quant_research/experiments/automation.py` to:
1. Read `features.include_sources` from config
2. Override default templates with hypothesis-specific settings
3. Bind hypothesis_id to feature selection

### Option B: Direct Pipeline Execution
Bypass automation module and call `run_research_pipeline` directly with proper feature configuration.

### Option C: Manual Config per Hypothesis
Create individual YAML configs for each trial that fully specify all parameters (workaround, not scalable).

---

## Impact Assessment

**Scientific Progress:** ZERO valid hypothesis tests completed  
**Trials Wasted:** 4 of 30 total budget (13%)  
**Time Lost:** ~2 hours of compute time  
**Credibility:** Low - framework producing misleading results

**H-001, H-002, H-003 remain UNTESTED.** We have no evidence for or against any hypothesis.

---

## Immediate Actions Required

1. **STOP** using automation module until fixed
2. **FIX** automation.py to respect config feature specifications
3. **VERIFY** fix with single test trial showing different results for different feature sets
4. **RE-RUN** H-001 Trials 1-2 with correct feature selection
5. **RE-RUN** H-002 Trials 1-2 with correct feature selection

---

## Alternative: Direct Execution Script

If automation fix is complex, create direct execution script:

```python
from src.quant_research.run import run_research_pipeline
from src.quant_research.features.registry import registry

# Load config with specific feature sources
config = load_config('configs/h002_liquidity_trial.yaml')
config.features.include_sources = ['liquidity_reversal', 'price_volume']

# Execute pipeline directly
results = run_research_pipeline(config)
```

---

## Recommendation

**Escalate to framework developer** - This is a critical bug that invalidates all automation-based research. Do not execute more trials until fixed.

Estimated fix time: 2-4 hours  
Estimated re-run time: 30 minutes per trial

---

*Last Updated: 2026-09-14 13:40 UTC*  
*Status: BLOCKED*
