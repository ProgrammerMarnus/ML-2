#!/usr/bin/env python3
"""discover-runner.py - fully autonomous 0-interaction strategy discovery.

Per task runs in TWO phases so the long quant pipeline NEVER ties up a model:
  Phase A (agent, ~2-3 min): make code/config changes, launch the pipeline
       as a background process, immediately disconnect.
  WAIT   (no model): discover-runner polls the background process to completion.
  Phase B (agent, ~3-5 min): read results, revert code, write analysis, reply RESULT.

Usage:
    python3 discover-runner.py --hours 8 --mode act
    python3 discover-runner.py -H 4 --dry-run
    python3 discover-runner.py --self-test
    python3 discover-runner.py --cleanup
"""
from __future__ import annotations
import argparse, json, os, re, signal, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
RUNNER = REPO / "cline-runner.py"
LOG = REPO / "strategy-runs.jsonl"
LAUNCH_RE = re.compile(r"LAUNCHED pid=(\d+) log=(\S+) tag=(\S+)")
RESULT_RE = re.compile(r"RESULT net_sharpe=([+-]?[\d.]+) state=(\S+) gates=(\d+)/(\d+)")
TASKS = [
  [
    "seed44",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A seed=44. cp real_spy /tmp/reals_44.yaml; sed seed. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/s44 python3 -m quant_research.run --config /tmp/reals_44.yaml --output artifacts_seed44 > /tmp/disc_artifacts_seed44.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_seed44.log tag=artifacts_seed44. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B seed=44. Read artifacts_seed44/*.json+csv. Append to DISCOVERY_ANALYSIS.txt vs 42/43/7. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "seed45",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A seed=45. cp real_spy /tmp/reals_45.yaml; sed seed. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/s45 python3 -m quant_research.run --config /tmp/reals_45.yaml --output artifacts_seed45 > /tmp/disc_artifacts_seed45.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_seed45.log tag=artifacts_seed45. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B seed=45. Read artifacts_seed45/*.json+csv. Append to DISCOVERY_ANALYSIS.txt vs 42/43/7. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "seed46",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A seed=46. cp real_spy /tmp/reals_46.yaml; sed seed. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/s46 python3 -m quant_research.run --config /tmp/reals_46.yaml --output artifacts_seed46 > /tmp/disc_artifacts_seed46.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_seed46.log tag=artifacts_seed46. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B seed=46. Read artifacts_seed46/*.json+csv. Append to DISCOVERY_ANALYSIS.txt vs 42/43/7. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_overnight_gap",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate overnight_gap. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_overnight_gap python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_overnight_gap > /tmp/disc_artifacts_abl_overnight_gap.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_overnight_gap.log tag=artifacts_abl_overnight_gap. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B overnight_gap. Read artifacts_abl_overnight_gap/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_intraday_return",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate intraday_return. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_intraday_return python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_intraday_return > /tmp/disc_artifacts_abl_intraday_return.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_intraday_return.log tag=artifacts_abl_intraday_return. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B intraday_return. Read artifacts_abl_intraday_return/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_day_range_position",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate day_range_position. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_day_range_position python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_day_range_position > /tmp/disc_artifacts_abl_day_range_position.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_day_range_position.log tag=artifacts_abl_day_range_position. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B day_range_position. Read artifacts_abl_day_range_position/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_rsi_14",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate rsi_14. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_rsi_14 python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_rsi_14 > /tmp/disc_artifacts_abl_rsi_14.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_rsi_14.log tag=artifacts_abl_rsi_14. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B rsi_14. Read artifacts_abl_rsi_14/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_bollinger_position_20",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate bollinger_position_20. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_bollinger_position_20 python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_bollinger_position_20 > /tmp/disc_artifacts_abl_bollinger_position_20.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_bollinger_position_20.log tag=artifacts_abl_bollinger_position_20. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B bollinger_position_20. Read artifacts_abl_bollinger_position_20/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_fifty_two_week_position",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate fifty_two_week_position. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_fifty_two_week_position python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_fifty_two_week_position > /tmp/disc_artifacts_abl_fifty_two_week_position.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_fifty_two_week_position.log tag=artifacts_abl_fifty_two_week_position. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B fifty_two_week_position. Read artifacts_abl_fifty_two_week_position/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_vol_of_vol_20",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate vol_of_vol_20. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_vol_of_vol_20 python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_vol_of_vol_20 > /tmp/disc_artifacts_abl_vol_of_vol_20.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_vol_of_vol_20.log tag=artifacts_abl_vol_of_vol_20. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B vol_of_vol_20. Read artifacts_abl_vol_of_vol_20/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_price_volume_corr_20",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate price_volume_corr_20. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_price_volume_corr_20 python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_price_volume_corr_20 > /tmp/disc_artifacts_abl_price_volume_corr_20.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_price_volume_corr_20.log tag=artifacts_abl_price_volume_corr_20. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B price_volume_corr_20. Read artifacts_abl_price_volume_corr_20/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "abl_amihud_illiquidity_20",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A ablate amihud_illiquidity_20. drop column (19 left). Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_amihud_illiquidity_20 python3 -m quant_research.run --config configs/real_spy.yaml --output artifacts_abl_amihud_illiquidity_20 > /tmp/disc_artifacts_abl_amihud_illiquidity_20.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_abl_amihud_illiquidity_20.log tag=artifacts_abl_amihud_illiquidity_20. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B amihud_illiquidity_20. Read artifacts_abl_amihud_illiquidity_20/*.json. REVERT drop line, retest. Append ESSENTIAL/MARGINAL/DEAD WEIGHT. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "var_logreg",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A logreg. cp real_spy /tmp/real_logreg.yaml; set model.type=logistic. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/var_logreg python3 -m quant_research.run --config /tmp/real_logreg.yaml --output artifacts_var_logreg > /tmp/disc_artifacts_var_logreg.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_var_logreg.log tag=artifacts_var_logreg. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B logreg. Read artifacts_var_logreg/*.json, delete /tmp/real_logreg.yaml. Append verdict. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "var_placebo50",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A placebo50. cp real_spy /tmp/real_placebo50.yaml; set research.placebo_runs=50. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/var_placebo50 python3 -m quant_research.run --config /tmp/real_placebo50.yaml --output artifacts_var_placebo50 > /tmp/disc_artifacts_var_placebo50.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_var_placebo50.log tag=artifacts_var_placebo50. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B placebo50. Read artifacts_var_placebo50/*.json, delete /tmp/real_placebo50.yaml. Append verdict. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "var_hold_longer",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A hold_longer. cp real_spy /tmp/real_hold_longer.yaml; set research.hold_candidates=[20,30,45,60]. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/var_hold_longer python3 -m quant_research.run --config /tmp/real_hold_longer.yaml --output artifacts_var_hold_longer > /tmp/disc_artifacts_var_hold_longer.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_var_hold_longer.log tag=artifacts_var_hold_longer. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B hold_longer. Read artifacts_var_hold_longer/*.json, delete /tmp/real_hold_longer.yaml. Append verdict. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ],
  [
    "var_core_only",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE A core_only. cp real_spy /tmp/real_core_only.yaml; set research.threshold_candidates=[0.5,0.6,0.7]. Launch: nohup env QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/var_core_only python3 -m quant_research.run --config /tmp/real_core_only.yaml --output artifacts_var_core_only > /tmp/disc_artifacts_var_core_only.log 2>&1 &\necho LAUNCHED pid=$! log=/tmp/disc_artifacts_var_core_only.log tag=artifacts_var_core_only. STOP.",
    "REPO /home/marnus/VS-Code/ML-2. Reference: configs/real_spy.yaml, quick_test.yaml, src/quant_research/run.py, config.py, features/price_volume.py. Past anchor (do NOT report as current): GBM-200 once reached CANDIDATE 14/14; follow-ups on fresh yfinance downloads did NOT replicate (RESEARCH_ONLY 12/14). Data: yfinance SPY/QQQ 2012-2025 via real_spy.yaml.\nPHASE B core_only. Read artifacts_var_core_only/*.json, delete /tmp/real_core_only.yaml. Append verdict. commit. RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
  ]
]

def schedule(hours, per_task_min):
    n = int(hours * 60 // per_task_min)
    return TASKS[: max(1, min(n, len(TASKS)))]


def load_done(path):
    done = set()
    try:
        for line in open(path, encoding="utf-8"):
            e = json.loads(line.strip())
            if e.get("status") == "ok":
                done.add(e["task_id"])
    except FileNotFoundError:
        pass
    return done


def wlog(path, entry):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
        fh.flush()


def invoke_agent(runner, prompt, mode, thinking, passthru, timeout_s):
    # Single-shot: cline-runner requires -lp/-lp2 whenever -l is given.
    cmd = [sys.executable, str(runner), prompt, "-m", mode, "-t", thinking] + passthru
    try:
        p = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                           text=True, timeout=timeout_s)
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        return True, p.returncode, out, round(time.time(), 0)
    except subprocess.TimeoutExpired:
        return False, 124, "AGENT-TIMEOUT", round(time.time(), 0)


def wait_for_pipeline(log_path, timeout_s, poll_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if not Path(log_path).exists():
            time.sleep(poll_s); continue
        text = Path(log_path).read_text(errors="ignore")
        if "promotion_state" in text or "experiment_id" in text:
            return True
        time.sleep(poll_s)
    return Path(log_path).exists() and "experiment_id" in Path(log_path).read_text(errors="ignore")


def build_parser():
    ap = argparse.ArgumentParser(description="0-interaction strategy discovery")
    ap.add_argument("--hours", "-H", type=float, default=8.0)
    ap.add_argument("--per-task-min", type=int, default=45)
    ap.add_argument("--poll-s", type=int, default=30)
    ap.add_argument("--mode", default="act", choices=["act", "plan"])
    ap.add_argument("--thinking", "-t", default="xhigh")
    ap.add_argument("--runner", default=str(RUNNER))
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    return ap


def cleanup():
    killed = 0
    for line in subprocess.run(["ps","-eo","pid,args"], capture_output=True,
                               text=True, check=False).stdout.splitlines():
        if "quant_research.run" in line and "discover" not in line:
            try:
                os.kill(int(line.split()[0]), signal.SIGTERM); killed += 1
            except (OSError, ValueError):
                pass
    print(f"cleanup: killed {killed} stray quant_research.run processes")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cleanup:
        return cleanup()
    if args.self_test:
        sc = schedule(args.hours, args.per_task_min)
        assert len(TASKS) == 16, len(TASKS)
        assert schedule(1.0, 45)[0][0] == "seed44"
        assert schedule(8.0, 45)[0][0] == "seed44"
        assert len(schedule(8.0, 45)) <= 10
        assert LAUNCH_RE.search("LAUNCHED pid=12345 log=/tmp/x tag=seed44")
        assert RESULT_RE.search("RESULT net_sharpe=+0.25 state=RESEARCH_ONLY gates=12/14")
        done = set(); done.add("seed44")
        pend = [t for t in TASKS if t[0] not in done]
        assert len(pend) == 15
        print("self-test OK")
        return 0
    if not RUNNER.exists():
        print("ERROR: runner not found", file=sys.stderr); return 2
    os.makedirs("/tmp/ledgers", exist_ok=True)
    tasks = schedule(args.hours, args.per_task_min)
    done = load_done(args.log)
    pending = [(i, t) for i, t in enumerate(tasks) if t[0] not in done]
    if args.dry_run:
        print(f"{len(pending)} pending of {len(tasks)}:")
        for _i, (tag, _a, _b) in pending:
            print(f"  {tag}"); return 0
    print(f"discover-runner: {len(pending)} tasks, {args.per_task_min}min budget each", flush=True)
    ok = 0; t0 = time.time()
    for idx, (tag, phase_a, phase_b) in pending:
        if (time.time() - t0) / 3600 >= args.hours:
            print("budget expired", flush=True); break
        print(f">>> {tag} phase A", flush=True)
        ok_a, rc_a, out_a, _ = invoke_agent(args.runner, phase_a, args.mode,
                                            args.thinking, [], (args.per_task_min // 3 + 5) * 60)
        m = LAUNCH_RE.search(out_a)
        if not ok_a or not m:
            tail = out_a.strip().splitlines()[-2:]
            wlog(args.log, {"task_id": tag, "status": "fail", "phase": "A",
                           "rc": rc_a, "tail": "|".join(tail)})
            print(f"  phase A failed rc={rc_a}", flush=True); continue
        pid, log_path = int(m.group(1)), m.group(2)
        print(f"  launched pid={pid}; waiting for pipeline...", flush=True)
        pipe_ok = wait_for_pipeline(log_path, (args.per_task_min + 10) * 60, args.poll_s)
        if not pipe_ok:
            wlog(args.log, {"task_id": tag, "status": "fail", "phase": "pipeline", "pid": pid})
            print(f"  pipeline did not finish", flush=True); continue
        print(f">>> {tag} phase B", flush=True)
        ok_b, rc_b, out_b, _ = invoke_agent(args.runner, phase_b, args.mode,
                                            args.thinking, [], (args.per_task_min // 3 + 5) * 60)
        m2 = RESULT_RE.search(out_b)
        if ok_b and m2:
            r = m2.group(0)
            wlog(args.log, {"task_id": tag, "status": "ok", "result": r, "pid": pid})
            print(f"  {r}", flush=True); ok += 1
        else:
            tail = out_b.strip().splitlines()[-2:]
            wlog(args.log, {"task_id": tag, "status": "fail", "phase": "B",
                           "rc": rc_b, "tail": "|".join(tail)})
            print(f"  phase B failed rc={rc_b}", flush=True)
    print(f"\nDone: {ok} ok of {len(pending)} attempted.", flush=True)
    print(f"Log: {args.log} (re-run resumes)", flush=True)
    return 0 if ok > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
