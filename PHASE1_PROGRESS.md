# Phase 1: Strategy Research Reset - Progress Tracker

**Started:** 2026-09-13  
**Status:** IN PROGRESS  
**Current Step:** 2/5 - Closing pv-2.2.0 line  

---

## Completed Steps ✓

### Step 1: Document Current Strategy Failures ✓

**Status:** COMPLETE  
**Date:** 2026-09-13

**Evidence gathered:**
- Analyzed 6 experimental runs (seed44×3, seed45, seed46, seed44_30min)
- All runs failed `placebo_separates` gate (best: 0.90, required: ≥0.95)
- seed45 also failed `cost_stress_survives`
- Total trials: 250+ with 0% success rate

**Key finding:** Strategy is statistically indistinguishable from noise. Placebo percentile of 0.85-0.90 means random permutations achieve similar results 85-90% of the time.

**Artifacts:** See PV220_CLOSURE_REPORT.md for full analysis.

---

### Step 2: Close pv-2.2.0 Research Line ✓

**Status:** COMPLETE  
**Date:** 2026-09-13

**Actions completed:**
1. ✅ Created closure report (PV220_CLOSURE_REPORT.md)
   - Documents all failures with evidence
   - Root cause analysis (no economic mechanism, overfitting)
   - Lessons learned and recommendations
   
2. ✅ Archived all artifacts
   - Copied to `/workspace/closed_strategies/pv-2.2.0/`
   - Includes: seed44, seed45, seed46, seed44_30min artifacts
   - Preserved for audit trail and learning

3. ⚠️ Update experiment registry
   - **TODO:** Mark families as CLOSED_FAILED in registry
   - Need to add status field to experiment_registry.jsonl

4. ✅ Documented lessons learned
   - Technical analysis alone insufficient
   - Preregistration required for future research
   - Placebo test is the critical gate

**Deliverables:**
- [x] PV220_CLOSURE_REPORT.md
- [x] closed_strategies/pv-2.2.0/ directory with all artifacts
- [ ] Registry updates (pending)

---

## In Progress 🔄

### Step 3: Develop New Signal Hypothesis

**Status:** IN PROGRESS  
**Target Date:** 2026-09-20

**Completed:**
- [x] Created preregistration template (PREREGISTRATION_TEMPLATE.md)
  - Enforces economic mechanism documentation
  - Requires falsifiable predictions
  - Specifies trial budgets and decision rules
  
- [x] Developed first hypothesis (HYPOTHESIS_H001_CROSS_ASSET_SPILLOVER.md)
  - Economic mechanism: Information diffusion lag between SPY/QQQ
  - Testable prediction: Mean reversion after 1.5σ deviation
  - Pre-specified features (9 total, no post-hoc additions)
  - Validation protocol locked (7-fold walk-forward)
  - Trial budget: 10 trials maximum
  - Falsification criteria defined

**Pending:**
- [ ] Human review of H-001 preregistration
- [ ] Develop 2 additional hypotheses as backups
  - Liquidity-based signals
  - Volatility risk premium
  - Seasonal/calendar effects
- [ ] Finalize hypothesis selection

**Next Action:** Await review approval before running experiments

---

## Not Started ⏳

### Step 4: Implement New Strategy Framework

**Status:** NOT STARTED  
**Target Start:** After hypothesis approval

**Planned work:**
- Create new strategy class supporting preregistration metadata
- Add gate enhancements (economic_mechanism_documented, regime_stability)
- Implement trial budget tracking
- Build hypothesis registry system

**Code changes needed:**
```python
# Planned additions to src/quant_research/strategies/
- preregistered_strategy.py  # Base class with prereg support
- hypothesis_registry.py     # Track hypotheses and trial counts
- gates_enhanced.py          # Additional validation gates
```

---

### Step 5: Execute New Research Campaign

**Status:** NOT STARTED  
**Target Start:** After framework ready

**Campaign plan:**
1. Run H-001 trials 1-3 (baseline model)
2. Review results, adjust if needed
3. Run trials 4-6 (hyperparameter optimization)
4. Run trials 7-8 (robustness checks)
5. Run trials 9-10 (final validation)
6. Decision: promote to paper trading OR abandon

**Success criteria:**
- All 14 gates pass with margin
- Placebo percentile ≥ 0.95 (critical)
- Replicate across multiple seeds
- Economic mechanism validated

**Timeline:** 4-6 weeks for complete campaign

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| pv-2.2.0 trials run | 250+ |
| pv-2.2.0 success rate | 0% |
| Families closed | 4 (seed44, seed45, seed46, seed44_30min) |
| New hypotheses proposed | 1 (H-001) |
| Hypotheses pending review | 1 |
| Trials remaining in family budget | 30 |
| Days elapsed in Phase 1 | 0 (just started) |
| Estimated days to completion | 30-45 |

---

## Risks & Blockers

### Current Blockers
- **None** - awaiting human review of H-001 preregistration

### Potential Risks
1. **No viable hypothesis found**
   - Mitigation: Have 3 backup hypotheses ready
   - Expand to alternative data sources if needed

2. **H-001 fails placebo test like pv-2.2.0**
   - Mitigation: Mechanism-based approach should help
   - Early abandonment if placebo < 0.80 after 5 trials

3. **Framework changes delay experiments**
   - Mitigation: Can run initial tests with existing infrastructure
   - Preregistration can be enforced manually initially

---

## Next Milestones

| Date | Milestone | Deliverable |
|------|-----------|-------------|
| 2026-09-13 | Step 2 complete | pv-2.2.0 closed ✓ |
| 2026-09-20 | Step 3 complete | Hypotheses approved |
| 2026-09-27 | Step 4 complete | Framework ready |
| 2026-10-04 | Step 5 mid-point | Trial 5 review |
| 2026-10-11 | Step 5 complete | Promotion decision |

---

**Last Updated:** 2026-09-13  
**Next Review:** After H-001 approval
