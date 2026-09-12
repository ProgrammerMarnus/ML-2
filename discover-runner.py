#!/usr/bin/env python3
"""discover-runner.py - time-boxed autonomous strategy-discovery orchestrator.

Runs unattended quant-research discovery on the ML-2 repo by shelling out to
`cline-runner.py` (one invocation per task; it handles model/account
failover), for a fixed wall-clock budget (default 8h).

Stdlib only. Never displays raw agent output; prints one compact line per task.

Usage:
    python3 discover-runner.py --hours 8 --mode act --start-model solar-pro4
    python3 discover-runner.py -H 4 --dry-run
    python3 discover-runner.py --self-test

Task pool (fixed order; schedule = first N tasks):
    t0  seed44   full real-data pipeline, seed 44 (cheap, confirmatory)
    t1  abl_overnight_gap
    t2  seed45
    t3  abl_intraday_return
    t4  seed46
    t5  abl_day_range_position
    t6  abl_rsi_14
    t7  abl_bollinger_position_20
    t8  abl_fifty_two_week_position
    t9  abl_vol_of_vol_20
    t10 abl_price_volume_corr_20
    t11 abl_amihud_illiquidity_20
    t12 var_logreg
    t13 var_placebo50
    t14 var_hold_longer
    t15 var_core_only

Schedule: N = floor(hours*60 / per_task_min), min 1, capped at 16.
Default 8h @45min -> tasks t0..t9 (3 seeds + 7 ablations). Seeds are
interleaved with ablations so one stuck task cannot eat the whole budget.

Each task: `python3 cline-runner.py "<prompt>" -l 1 -m MODE -t THINKING ...`
with a subprocess timeout (per-task minutes + 5 min grace). Failures and
timeouts are logged; the schedule continues. Re-running resumes: tasks with
status=ok in strategy-runs.jsonl are skipped (unless --redo).

Guards baked into every prompt (hard rules, never violated):
  * research runs only; no live orders, no broker/execution code
  * no promotion-gate changes, no threshold reselection on test data
  * strategy stays RESEARCH_ONLY unless run_research_pipeline output says otherwise
  * one-line code patches for ablations are reverted immediately after the run
  * own output dir + fresh QUANT_RESEARCH_LEDGER_DIR per real-data run
  * reply ends with: RESULT net_sharpe=+X.XXXX state=STATE gates=P/T

Exit codes: 0 = schedule processed (any mix incl. budget expiry), 2 = usage,
3 = zero tasks succeeded.
"""
from __future__ import annotations

import argparse
import os
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CLINE_RUNNER = REPO_ROOT / "cline-runner.py"
LOG_FILE = REPO_ROOT / "strategy-runs.jsonl"
RESULT_RE = re.compile(
    r"RESULT\s+net_sharpe=([+-]?\d+(?:\.\d+)?)\s+state=([A-Z_]+)\s+gates=(\d+)/(\d+)"
)

GUARDS = """HARD RULES (never violate):
- RESEARCH RUNS ONLY. No live orders, no broker code, do not touch
  paper.py / operational.py / paper_validation.py.
- Do NOT edit promotion gates, walk-forward, audit criteria, or tests.
  No threshold/hold reselection on test data.
- Record results honestly: the strategy stays RESEARCH_ONLY unless
  run_research_pipeline output literally says otherwise.
- End your final reply with exactly one line:
  RESULT net_sharpe=+X.XXXX state=STATE gates=P/T
- Time guard: stop starting new work after {m} minutes from now;
  write partial results and finish."""

BASE_CTXT = (
    "REPO: /home/marnus/VS-Code/ML-2 (ML-2 quant research engine). "
    "Refs: configs/real_spy.yaml, src/quant_research/run.py, "
    "src/quant_research/config.py, "
    "src/quant_research/features/price_volume.py "
    "(legacy 11 + SIGNAL_EXTENSION_COLUMNS pv-2.2.0). "
    "Anchor (do NOT report as current): a GBM-200 run once hit CANDIDATE "
    "14/14; follow-ups on fresh downloads did not replicate (RESEARCH_ONLY "
    "12/14). Artifacts go under artifacts_<name>/."
)


def seed_prompt(seed):
    return BASE_CTXT + (
        "TASK: independent replication, model.random_seed=%d. " % seed
        + "Copy configs/real_spy.yaml to /tmp/reals_%d.yaml, set ONLY " % seed
        + "random_seed. Run QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/s%d " % seed
        + "timeout 2000 python -m quant_research.run --config "
        + "/tmp/reals_%d.yaml --output artifacts_seed%d. " % (seed, seed)
        + "Read results JSON: net Sharpe, state, gates, bootstrap P(>0), "
        + "placebo pct/adj_p, cost+delay grids, dataset_version, per-fold "
        + "threshold/sharpe/trades. Append one section to DISCOVERY_ANALYSIS.txt "
        + "comparing vs seed-42 (+0.718, 14/14 CANDIDATE), seed-43 (+0.250, "
        + "12/14), seed-7 (+0.197, 12/14). git add the log+artifacts and "
        + "commit (do NOT push). End with: "
        + "RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
    )


def ablation_prompt(feature):
    return BASE_CTXT + (
        "TASK: leakage-safe ablation of pv-2.2.0 feature %s. " % feature
        + "In run.py after the ext_feats join, drop ONLY that column via "
        + "features.drop(columns=[...]) as a one-line caller-side exclusion "
        + "(do NOT edit shared builders/registry/leakage). Confirm 19 "
        + "features remain. Run QUANT_RESEARCH_LEDGER_DIR=/tmp/ledgers/abl_%s " % feature
        + "timeout 2000 python -m quant_research.run --config "
        + "configs/real_spy.yaml --output artifacts_abl_%s. " % feature
        + "Read net Sharpe, state/gates, placebo pct/adj_p, cost at 10+20bps. "
        + "REVERT the one-line exclusion, verify git diff shows run.py "
        + "restored, re-run the signal-extension tests quickly. Append verdict "
        + "to DISCOVERY_ANALYSIS.txt: ESSENTIAL (net drops >=0.15 or gates "
        + "refail), MARGINAL (0.05-0.15), or DEAD WEIGHT (noise). End with: "
        + "RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
    )


LOGLINE_PROMPT = (
    "Variant: logistic regression with pv-2.2.0 features. Copy "
    "configs/real_spy.yaml to /tmp/real_logreg.yaml, set ONLY model type "
    "to logistic. Run with private ledger /tmp/ledgers/logreg and output "
    "artifacts_var_logreg (timeout 2000). Read net Sharpe, state/gates, "
    "placebo pct. Append verdict to DISCOVERY_ANALYSIS.txt (GBM net +0.718 "
    "vs logistic). Delete the /tmp yaml. Confirm no src/ changes. End: "
    "RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
)
PBO50_PROMPT = (
    "Variant: placebo_runs 20->50 to tighten the Monte Carlo margin "
    "(seed-42 sat at pct 0.95/adj-p 0.0952). Copy config to "
    "/tmp/real_pbo50.yaml changing ONLY placebo_runs to 50. Run with "
    "ledger /tmp/ledgers/pbo50, output artifacts_var_placebo50, timeout "
    "2400. Read placebo pct/adj_p/n_runs + gates/state. Append whether "
    "0.95 survives 50 draws. Delete the /tmp yaml. Confirm no src/ changes. "
    "End with: RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
)
HOLDLONG_PROMPT = (
    "Variant: holds [20,30,45,60] to cut turnover further. Copy config to "
    "/tmp/real_hold.yaml changing ONLY hold_candidates. Run with ledger "
    "/tmp/ledgers/holdlong, output artifacts_var_holdlong, timeout 2000. "
    "Read net Sharpe, trades, turnover, gates, cost grid. Append verdict vs "
    "V3 turnover baseline. Delete the /tmp yaml. Confirm no src/ changes. "
    "End with: RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
)
COREONLY_PROMPT = (
    "Variant: 11 legacy features only (no extensions) - attribution baseline. "
    "In run.py comment out ONLY the ext_feats lines with a # COREONLY-TEMP "
    "marker (do NOT edit shared builders). Run with ledger "
    "/tmp/ledgers/coreonly, output artifacts_var_coreonly, timeout 2000. "
    "Read net Sharpe, gates, placebo pct. Restore ext lines immediately, "
    "verify git diff shows run.py clean, rerun signal-extension tests. "
    "Append the 9-extension block contribution to DISCOVERY_ANALYSIS.txt. "
    "End with: RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
)


ABLATION_FEATURES = [
    "overnight_gap", "intraday_return", "day_range_position",
    "rsi_14", "bollinger_position_20", "fifty_two_week_position",
    "vol_of_vol_20", "price_volume_corr_20", "amihud_illiquidity_20",
]


def build_tasks():
    tasks = []
    tasks.append(("t0", "seed44", seed_prompt(44)))
    for i, feat in enumerate(ABLATION_FEATURES):
        tasks.append(("t%d" % (i + 1), "abl_%s" % feat, ablation_prompt(feat)))
        if i == 0:
            tasks.append(("tX", "seed45", seed_prompt(45)))
        if i == 1:
            tasks.append(("tY", "seed46", seed_prompt(46)))
    tasks.append(("v0", "var_logreg", LOGLINE_PROMPT))
    tasks.append(("v1", "var_placebo50", PBO50_PROMPT))
    tasks.append(("v2", "var_hold_longer", HOLDLONG_PROMPT))
    tasks.append(("v3", "var_core_only", COREONLY_PROMPT))
    out = []
    for n, (old_tid, tag, prompt) in enumerate(tasks):
        out.append(("t%02d" % n, tag, prompt))
    return out


def load_log(path):
    done = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if e.get("status") == "ok":
                        done[e["task_id"]] = e
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return done


def write_log(path, entry):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
        fh.flush()


def prune_task_artifacts(root, tag):
    removed = 0
    keep = ("results.json", "folds.csv", "experiment_registry", "manifest.json")
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        hit = tag in name
        if not hit:
            continue
        for dirpath, _d, files in os.walk(p):
            for fn in files:
                if fn.endswith(".parquet") or (fn.endswith(".json") and not any(
                        fn.endswith(k) for k in keep)):
                    try:
                        os.remove(os.path.join(dirpath, fn))
                        removed += 1
                    except OSError:
                        pass
    return removed


def run_one(runner, prompt, mode, thinking, passthru, per_task_min, task_id, tag):
    cmd = [sys.executable, str(runner), prompt, "-l", "1",
           "-m", mode, "-t", thinking] + passthru
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                              text=True, timeout=(per_task_min + 5) * 60)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        m = RESULT_RE.search(out[-4000:])
        ok = bool(m) and proc.returncode == 0
        return ok, proc.returncode, (m.group(0) if m else "NO-RESULT-LINE"), round(time.time() - t0, 1)
    except subprocess.TimeoutExpired:
        return False, 124, "TIMEOUT", round(time.time() - t0, 1)


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Time-boxed autonomous strategy-discovery orchestrator.")
    ap.add_argument("--hours", "-H", type=float, default=8.0)
    ap.add_argument("--per-task-min", type=int, default=45)
    ap.add_argument("--seed-start", type=int, default=44)
    ap.add_argument("--mode", "-m", default="act", choices=["act", "plan", "yolo"])
    ap.add_argument("--thinking", "-t", default="xhigh")
    ap.add_argument("--runner", default=str(CLINE_RUNNER))
    ap.add_argument("--log", default=str(LOG_FILE))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--redo", action="store_true",
                    help="re-run tasks already marked ok in the log")
    ap.add_argument("--prune", action="store_true",
                    help="delete bulky intermediate files, keep results/folds/manifests")
    ap.add_argument("--no-commit", action="store_true",
                    help="strip per-task git-commit instructions from prompts")
    ap.add_argument("--start-model")
    ap.add_argument("--account-order", nargs="*", default=None)
    ap.add_argument("--cooldown", type=int, default=0)
    ap.add_argument("--no-clear", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    return ap


def self_test():
    tasks = build_tasks()
    assert len(tasks) == 16, tasks
    tids = [t[0] for t in tasks]
    assert tids == sorted(tids) and len(set(tids)) == 16
    tags = [t[1] for t in tasks]
    assert tags[0] == "seed44"
    assert tags[2] == "seed45" and tags[4] == "seed46"
    guards_ok = "research runs only" in GUARDS.lower()
    assert guards_ok, "GUARDS must forbid live trading"
    seeds = [t for t in tasks if t[1].startswith("seed")]
    flags = sum(
        1 for _tid, _tag, prompt in tasks
        if "result net_sharpe=" in prompt.lower()
        and "ledgers/" in prompt
        and "timeout " in prompt
    )
    assert flags == len(tasks), f"{flags}/{len(tasks)} prompts carry RESULT+ledger+timeout"
    seed_tasks = [t for t in tasks if t[1].startswith("seed")]
    assert [t[1] for t in seed_tasks][:3] == ["seed44", "seed45", "seed46"]
    n45 = schedule(1.0, 45)
    assert n45[0][0] == "t00" and len(n45) == 1
    ndefault = schedule(8.0, 45)
    assert [t[0] for t in ndefault] == ["t%02d" % i for i in range(10)]
    nall = schedule(12.0, 45)
    assert len(nall) == 16
    import tempfile
    fd, lp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    assert load_log(lp) == {}
    write_log(lp, {"task_id": "t00", "status": "ok"})
    assert "t00" in load_log(lp)
    os.remove(lp)
    m = RESULT_RE.search("RESULT net_sharpe=+0.25 state=RESEARCH_ONLY gates=12/14")
    assert m and m.groups() == ("+0.25", "RESEARCH_ONLY", "12", "14")
    print("self-test OK: 16 tasks, schedule math, log, regex all verified")
    return 0


def schedule(hours, per_task_min):
    tasks = build_tasks()
    n = int(hours * 60 // per_task_min)
    n = max(1, min(n, len(tasks)))
    return tasks[:n]


def strip_commits(prompt):
    out = []
    skip_next = False
    for line in prompt.splitlines():
        low = line.lower()
        if "git add" in low or ("git commit" in low and "message" in low):
            skip_next = "message:" in low and not low.rstrip().endswith('"')
            continue
        if skip_next and "push" in low:
            skip_next = False
            continue
        out.append(line)
    return "\n".join(out)


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not CLINE_RUNNER.exists():
        print(f"ERROR: cline-runner not found at {CLINE_RUNNER}", file=sys.stderr)
        return 2
    if args.hours <= 0 or args.per_task_min <= 0:
        print("ERROR: --hours and --per-task-min must be positive", file=sys.stderr)
        return 2
    tasks = schedule(args.hours, args.per_task_min)
    done = {} if args.redo else load_log(args.log)
    pending = [(tid, tag, p) for (tid, tag, p) in tasks if tid not in done]
    passthru = []
    if args.start_model:
        passthru += ["--start-model", args.start_model]
    if args.account_order:
        passthru += ["--account-order"] + list(args.account_order)
    if args.cooldown:
        passthru += ["--cooldown", str(args.cooldown)]
    if args.no_clear:
        passthru += ["--no-clear"]
    if args.dry_run:
        print(f"schedule: {len(pending)} pending of {len(tasks)} (budget {args.hours}h)")
        for tid, tag, prompt in pending:
            first = prompt.splitlines()[0][:80]
            print(f"  {tid} [{tag}] {first!r}")
        return 0
    print(f"discover-runner: {len(pending)} tasks, ~{args.per_task_min}min each", flush=True)
    ok_count = skipped = 0
    t_start = time.time()
    try:
        for i, (tid, tag, prompt) in enumerate(pending, 1):
            elapsed_h = (time.time() - t_start) / 3600.0
            if elapsed_h >= args.hours:
                print(f"budget expired at {elapsed_h:.2f}h - stopping", flush=True)
                break
            if args.no_commit:
                prompt = strip_commits(prompt)
            full_prompt = prompt + "\n\n" + GUARDS.format(m=args.per_task_min)
            ok, rc, result, secs = run_one(
                args.runner, full_prompt, args.mode, args.thinking,
                passthru, args.per_task_min, tid, tag)
            entry = {"task_id": tid, "tag": tag, "status": "ok" if ok else "fail",
                     "rc": rc, "result": result, "secs": secs,
                     "ts": datetime.now(timezone.utc).isoformat()}
            write_log(args.log, entry)
            if args.prune and ok:
                removed = prune_task_artifacts(str(REPO_ROOT), tag.replace("abl_", "abl").split("_")[0] + "_" + tag.split("_", 1)[-1] if "_" in tag else tag)
                entry["pruned"] = removed
            mark = "OK " if ok else "FAIL"
            print(f"[{mark}] {tid} {tag} {result} ({secs}s)", flush=True)
            if ok:
                ok_count += 1
            else:
                skipped += 1
    except KeyboardInterrupt:
        print("\nInterrupted - resume with the same command.", file=sys.stderr)
        return 130
    print(f"\nDone: {ok_count} ok, {skipped} failed/skipped of {len(pending)} attempted.", flush=True)
    print(f"Log: {args.log} (re-run resumes automatically)", flush=True)
    return 0 if ok_count > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
