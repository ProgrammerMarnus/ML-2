#!/usr/bin/env python3
"""discover-runner.py - autonomous 0-interaction strategy discovery.

Pipeline launched directly as a background process. Agent used ONLY for
~3-min analysis after each run completes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
RUNNER = REPO / "cline-runner.py"
LOG = REPO / "strategy-runs.jsonl"
TASKS_FILE = REPO / "tasks2.json"
RUNPY = REPO / "src" / "quant_research" / "run.py"
RESULT_RE = re.compile(
    r"RESULT net_sharpe=([+-]?[\d.]+) state=(\S+) gates=(\d+)/(\d+)"
)


def load_tasks():
    with open(TASKS_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def schedule(tasks, hours, per_task_min):
    n = int(hours * 60 // per_task_min)
    return tasks[: max(1, min(n, len(tasks)))]


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


def apply_change(task):
    """Apply the one-line code change needed before launch."""
    if task["kind"] == "ablation":
        feat = task["feature"]
        marker = "# ABLATE-" + feat
        text = RUNPY.read_text()
        if marker in text:
            return
        lines = text.splitlines()
        out = []
        for ln in lines:
            out.append(ln)
            if "ext_feats" in ln and "join" in ln:
                out.append(
                    '    features = features.drop(columns=["' + feat + '"])  ' + marker
                )
        RUNPY.write_text("\n".join(out) + "\n")
        print("    patched run.py to drop " + feat, flush=True)
    elif task["kind"] == "seed":
        cfg = REPO / "configs" / "real_spy.yaml"
        text = cfg.read_text().replace(
            "random_seed: 42", "random_seed: " + str(task["seed"])
        )
        Path(task["cfg"]).write_text(text)
    elif task["kind"] == "variant":
        cfg = REPO / "configs" / "real_spy.yaml"
        text = cfg.read_text()
        for line in task["yml"].split(","):
            k, v = line.split("=", 1)
            text = re.sub(
                r"^(\s*" + re.escape(k) + r":).*", r"\1 " + v, text, flags=re.M
            )
        Path(task["cfg"]).write_text(text)


def revert_change(task):
    if task["kind"] != "ablation":
        return
    feat = task["feature"]
    marker = "# ABLATE-" + feat
    text = RUNPY.read_text()
    if marker not in text:
        return
    lines = [ln for ln in text.splitlines() if marker not in ln]
    RUNPY.write_text("\n".join(lines) + "\n")
    print("    reverted " + feat + " patch", flush=True)
    subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_signal_extensions.py", "-q", "-p", "no:warnings"],
        cwd=str(REPO), capture_output=True, timeout=120,
    )


def launch_pipeline(task):
    """Launch pipeline as background process. Returns (pid, logfile)."""
    log = "/tmp/disc_" + task["tag"] + ".log"
    cmd = (
        "nohup env QUANT_RESEARCH_LEDGER_DIR=" + task["ledger"]
        + " python3 -m quant_research.run --config " + task["cfg"]
        + " --output " + task["out"] + " > " + log
        + " 2>&1 & echo LAUNCHED pid=$!"
    )
    proc = subprocess.run(
        ["bash", "-c", cmd], cwd=str(REPO),
        capture_output=True, text=True, timeout=30,
    )
    m = re.search(r"pid=(\d+)", proc.stdout)
    return (int(m.group(1)) if m else -1), log


def wait_for_pipeline(log, timeout_s, poll_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if Path(log).exists():
            text = Path(log).read_text(errors="ignore")
            if "promotion_state" in text or "experiment_id" in text:
                return True
        time.sleep(poll_s)
    return False


def invoke_agent(prompt, timeout_s):
    cmd = [sys.executable, str(RUNNER), prompt, "-m", "act", "-t", "xhigh"]
    try:
        p = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True,
            text=True, timeout=timeout_s,
        )
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        m = RESULT_RE.search(out[-5000:])
        if p.returncode == 0 and m:
            return True, m.group(0), out
        return False, "NO-RESULT", out
    except subprocess.TimeoutExpired:
        return False, "AGENT-TIMEOUT", ""


def cleanup_stray():
    killed = 0
    out = subprocess.run(
        ["ps", "-eo", "pid,args"], capture_output=True,
        text=True, check=False,
    ).stdout
    for line in out.splitlines():
        if "quant_research.run" in line and "discover" not in line:
            try:
                os.kill(int(line.split()[0]), signal.SIGTERM)
                killed += 1
            except (OSError, ValueError):
                pass
    print(f"cleanup: killed {killed} stray pipelines")


def build_parser():
    ap = argparse.ArgumentParser(description="0-interaction strategy discovery")
    ap.add_argument("--hours", "-H", type=float, default=8.0)
    ap.add_argument("--per-task-min", type=int, default=45)
    ap.add_argument("--poll-s", type=int, default=30)
    ap.add_argument("--phase", default="full",
                    choices=["launch", "analyze", "full"])
    ap.add_argument("--runner", default=str(RUNNER))
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cleanup:
        cleanup_stray()
        return 0

    if args.reset:
        text = RUNPY.read_text()
        cleaned = "\n".join(
            ln for ln in text.splitlines() if "# ABLATE-" not in ln
        )
        RUNPY.write_text(cleaned + "\n")
        print("reset: removed all ablation patches")
        return 0

    all_tasks = load_tasks()

    if args.self_test:
        assert len(all_tasks) == 16
        scheduled = schedule(all_tasks, 1.0, 45)
        assert scheduled[0]["tag"] == "seed44"
        assert len(schedule(all_tasks, 8.0, 45)) <= 10
        print("self-test OK")
        return 0

    if not RUNNER.exists():
        print("ERROR: cline-runner.py not found", file=sys.stderr)
        return 2

    os.makedirs("/tmp/ledgers", exist_ok=True)
    cleanup_stray()

    tasks = schedule(all_tasks, args.hours, args.per_task_min)
    done = load_done(args.log)
    pending = [t for t in tasks if t["tag"] not in done]

    if args.dry_run:
        print(f"{len(pending)} pending of {len(tasks)}:")
        for t in pending:
            print(f"  {t['tag']}")
        return 0

    print(f"discover-runner: {len(pending)} tasks", flush=True)
    ok = 0
    t0 = time.time()

    for task in pending:
        if (time.time() - t0) / 3600 >= args.hours:
            print("budget expired", flush=True)
            break

        tag = task["tag"]
        print(f">>> {tag}", flush=True)

        try:
            if args.phase in ("launch", "full"):
                apply_change(task)
                pid, log = launch_pipeline(task)
                if pid < 0:
                    print("  launch failed", flush=True)
                    wlog(args.log, {"task_id": tag, "status": "fail", "phase": "launch"})
                    continue
                print(f"  pipeline pid={pid}; waiting...", flush=True)
                if not wait_for_pipeline(
                    log, (args.per_task_min + 10) * 60, args.poll_s
                ):
                    print("  pipeline timed out", flush=True)
                    wlog(args.log, {"task_id": tag, "status": "fail", "phase": "pipeline"})
                    revert_change(task)
                    continue

            if args.phase in ("analyze", "full"):
                print("  analyzing...", flush=True)
                full_prompt = (
                    task["analysis"]
                    + "\nHARD RULES: RESEARCH ONLY. Do NOT edit gates. "
                    + "End with: RESULT net_sharpe=+X.XXXX state=STATE gates=P/T"
                )
                ok_b, res, _ = invoke_agent(
                    full_prompt, (args.per_task_min // 3 + 5) * 60
                )
                revert_change(task)
                if ok_b:
                    wlog(args.log, {"task_id": tag, "status": "ok", "result": res})
                    print(f"  {res}", flush=True)
                    ok += 1
                else:
                    wlog(args.log, {"task_id": tag, "status": "fail",
                                   "phase": "analyze", "result": res})
                    print(f"  analyze failed: {res}", flush=True)
        except Exception as e:
            revert_change(task)
            wlog(args.log, {"task_id": tag, "status": "error", "error": str(e)})
            print(f"  error: {e}", flush=True)

    print(f"\nDone: {ok} ok of {len(pending)} attempted.", flush=True)
    print(f"Log: {args.log}", flush=True)
    return 0 if ok > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
