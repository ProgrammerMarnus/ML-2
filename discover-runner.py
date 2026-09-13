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
PID_DIR = Path("/tmp/discovery-runner-pids")
RESULT_RE = re.compile(
    r"RESULT net_sharpe=([+-]?[\d.]+) state=(\S+) gates=(\d+)/(\d+)"
)
AGENT_SEC_RE = re.compile(
    r"--- AGENT OUTPUT BEGIN ---\s*(.*?)\s*--- AGENT OUTPUT END ---",
    re.S,
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
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("status") == "ok":
                # legacy logs used task_id, current runner writes tag
                if e.get("tag"):
                    done.add(e["tag"])
                if e.get("task_id"):
                    done.add(e["task_id"])
    except FileNotFoundError:
        pass
    return done


def wlog(path, entry):
    entry = dict(entry)
    # always record both keys; legacy logs only had task_id
    if "tag" in entry and "task_id" not in entry:
        entry["task_id"] = entry["tag"]
    if "task_id" in entry and "tag" not in entry:
        entry["tag"] = entry["task_id"]
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
        # Insert once, after the LAST features-join line, so the drop
        # applies to both the events and no-events branches.
        lines = text.splitlines()
        join_idxs = [
            i for i, ln in enumerate(lines)
            if "ext_feats" in ln and "join" in ln and "features =" in ln
        ]
        if not join_idxs:
            raise RuntimeError(
                "ablation anchor not found in run.py: "
                "expected 'features = ... join ext_feats' line"
            )
        insert_at = max(join_idxs) + 1
        base = lines[max(join_idxs)]
        indent = base[: len(base) - len(base.lstrip())]
        lines.insert(
            insert_at,
            indent + 'features = features.drop(columns=["'
            + feat + '"])  ' + marker,
        )
        RUNPY.write_text("\n".join(lines) + "\n")
        print("    patched run.py to drop " + feat, flush=True)
    elif task["kind"] == "seed":
        # derive seed number from tag like "seed44" -> 44
        tag = task["tag"]
        if tag.startswith("seed") and tag[4:].isdigit():
            seed = int(tag[4:])
        else:
            raise ValueError(
                f"seed task tag '{tag}' does not look like seed<N>"
            )
        cfg = REPO / "configs" / "real_spy.yaml"
        text, n = re.subn(
            r"^(\s*random_seed:)\s*\d+\s*$", r"\1 " + str(seed),
            cfg.read_text(), count=1, flags=re.M,
        )
        if n != 1:
            raise RuntimeError("expected exactly one model.random_seed in base config")
        Path(task["cfg"]).write_text(text)
    elif task["kind"] == "variant":
        # A variant without declared configuration changes is a mislabeled
        # baseline rerun, not valid new research evidence.
        cfg = REPO / "configs" / "real_spy.yaml"
        text = cfg.read_text()
        yml = task.get("yml", "")
        if not yml:
            raise ValueError(
                f"variant task {task['tag']} has no declared yml overrides"
            )
        for line in yml.split(","):
            line = line.strip()
            if not line or "=" not in line:
                raise ValueError(f"invalid variant override {line!r}")
            k, v = line.split("=", 1)
            text, n = re.subn(
                r"^(\s*" + re.escape(k.strip()) + r":).*",
                r"\1 " + v.strip(), text, count=1, flags=re.M,
            )
            if n != 1:
                raise ValueError(f"variant override key not found: {k.strip()}")
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


def _pid_path(pid):
    return PID_DIR / f"{pid}.pid"


def _forget_pipeline(pid):
    _pid_path(pid).unlink(missing_ok=True)


def _terminate_pipeline(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _forget_pipeline(pid)


def launch_pipeline(task, allow_existing_output=False):
    """Launch pipeline as background process. Returns (pid, logfile)."""
    log = "/tmp/disc_" + task["tag"] + ".log"
    out_dir = task["out"]
    out_path = REPO / out_dir
    if out_path.exists() and any(out_path.iterdir()) and not allow_existing_output:
        raise FileExistsError(
            f"refusing to reuse non-empty output directory: {out_path}; "
            "preserve the prior evidence or choose a new task output"
        )
    env = os.environ.copy()
    env["QUANT_RESEARCH_LEDGER_DIR"] = task["ledger"]
    with open(log, "w", encoding="utf-8") as stream:
        proc = subprocess.Popen(
            [sys.executable, "-m", "quant_research.run", "--config", task["cfg"],
             "--output", out_dir],
            cwd=str(REPO), env=env, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_DIR.mkdir(parents=True, exist_ok=True)
    _pid_path(proc.pid).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid, log


def wait_for_pipeline(pid, log, timeout_s, poll_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if Path(log).exists():
            text = Path(log).read_text(errors="ignore")
            if "promotion_state:" in text and "experiment_id:" in text:
                return True
            # Detect crash: Traceback in log means pipeline died
            if "Traceback" in text or "Exception" in text:
                print("  pipeline crashed (see log)", flush=True)
                return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            print("  pipeline exited before producing a result (see log)", flush=True)
            return False
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
        # cline-runner forwards agent stdout between AGENT OUTPUT markers;
        # prefer that section so headers/Done lines can't shadow RESULT.
        # Fall back to full output for older cline-runner versions.
        # NOTE: the RESULT regex needs literal digits (gates=N/M); the prompt
        # below therefore shows a concrete example, never "P/T".
        m_sec = AGENT_SEC_RE.search(out)
        hay = m_sec.group(1) if m_sec else out
        m = RESULT_RE.search(hay[-20000:])
        if p.returncode == 0 and m:
            return True, m.group(0), out
        tail = "\n".join(out.splitlines()[-15:]) if out.strip() else "(empty)"
        return False, "NO-RESULT rc=%s tail=%s" % (p.returncode, tail), out
    except subprocess.TimeoutExpired:
        return False, "AGENT-TIMEOUT", ""


def cleanup_stray():
    killed = 0
    if not PID_DIR.exists():
        print("cleanup: no runner-owned pipelines")
        return
    for path in PID_DIR.glob("*.pid"):
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore")
        except OSError:
            path.unlink(missing_ok=True)
            continue
        if "quant_research.run" not in cmdline:
            path.unlink(missing_ok=True)
            continue
        try:
            os.killpg(pid, signal.SIGTERM)
            killed += 1
        except OSError:
            pass
        path.unlink(missing_ok=True)
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
    ap.add_argument("--mode", default="act", choices=["act"],
                    help="CLI compatibility with cline-runner; "
                         "agent always runs in act mode")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--allow-existing-output", action="store_true",
                    help="allow a task to target an existing output directory")
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
            ln for ln in text.splitlines()
            if "# ABLATE-" not in ln and "# PHASE A ablation" not in ln
        )
        RUNPY.write_text(cleaned + "\n")
        print("reset: removed all ablation patches (incl. legacy Phase A)")
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
    PID_DIR.mkdir(parents=True, exist_ok=True)

    tasks = schedule(all_tasks, args.hours, args.per_task_min)
    done = load_done(args.log)
    pending = [
        t for t in tasks
        if t["tag"] not in done and t.get("task_id", t["tag"]) not in done
    ]

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
                pid, log = launch_pipeline(task, args.allow_existing_output)
                if pid < 0:
                    print("  launch failed", flush=True)
                    wlog(args.log, {"task_id": tag, "status": "fail", "phase": "launch"})
                    continue
                print(f"  pipeline pid={pid}; waiting...", flush=True)
                if not wait_for_pipeline(
                    pid, log, (args.per_task_min + 10) * 60, args.poll_s
                ):
                    print("  pipeline timed out", flush=True)
                    _terminate_pipeline(pid)
                    wlog(args.log, {"task_id": tag, "status": "fail", "phase": "pipeline"})
                    revert_change(task)
                    continue
                _forget_pipeline(pid)

            if args.phase in ("analyze", "full"):
                print("  analyzing...", flush=True)
                # Concrete example (NOT literal P/T): the RESULT regex
                # requires gates=<digits>/<digits>, so a literal-minded
                # agent copying "P/T" verbatim could never match.
                full_prompt = (
                    task["analysis"]
                    + "\nHARD RULES: RESEARCH ONLY. Do NOT edit gates. "
                    + "End with a line like: "
                    "RESULT net_sharpe=+0.1234 state=RESEARCH_ONLY gates=12/14 "
                    "(use your real numbers)."
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
