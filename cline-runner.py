#!/usr/bin/env python3
"""cline-runner.py - loop runner with model/account failover (always yolo).

Single self-contained file (merged from the former cline_failover.py,
cline-runner.py, and the cline-runner shim). Stdlib only.
Shells out to `cline` (v3.0.61):

    cline -P <provider> -m <model> --config <account-dir> --auto-approve true <prompt>

Usage:
    cline-runner "prompt" -l 10 -lp "loop prompt" -m act -t xhigh
    cline-runner "prompt" -l 10 -lp "even" -lp2 "odd"
    cline-runner --self-test
    cline-runner --dry-run "prompt"

Loop semantics: -l is the per-prompt loop count. Main prompt runs once, then
EACH loop prompt runs -l times (1 + N_lp * -l total). With two loop prompts,
-lp runs even iterations (2,4,..2l), -lp2 runs odd (1,3,..2l-1): 1 + 2*-l total.

Always runs Cline with --auto-approve true (yolo: no approval prompts).
Each attempt clears the terminal and prints only:

    <account>|<model>|<mode>|<i>/<N>      e.g.  a|cline-free/solar-pro4|act|3/5

Cline tool/thinking output is captured for classification, never displayed.
On failure a single [action] line prints below the header.

Exit codes: 0 = all ok, 2 = usage error, 3 = combos exhausted.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()

# Accounts verified on this machine 2026-09-10.
ACCOUNTS: dict[str, str] = {
    "a": str(HOME / ".cline-account-a"),
    "b": str(HOME / ".cline-account-b"),
    "c": str(HOME / ".cline-account-c"),
    "d": str(HOME / ".cline-account-d"),
    "main": str(HOME / ".cline"),
}
DEFAULT_ACCOUNT_ORDER = ["a", "b", "c", "d", "main"]

# The 6 FREE models from the VSCode screenshot, via the `cline-pass`
# provider (the exact free-tier route the extension uses — globalState.json
# shows planModeApiProvider=cline-pass). Free availability is per-account
# (daily limits / promo windows), so failover walks all 5 accounts to find
# one whose free quota for that model is intact.
# Canonical IDs verified live 2026-09-11 across accounts a..d + main:
#   solar-pro4 + longcat-2.0 -> OK (via cline-pass, all accounts).
# Screenshot order kept.
CLINE_PASS_MODELS: list[tuple[str, str]] = [
    ("cline-pass", "cline-free/muse-spark-1.3-contributor"),   # img #1 Muse Spark 1.3
    ("cline-pass", "cline-free/deepseek-v4-flash"),            # img #2 DeepSeek V4 Flash
    ("cline-pass", "cline-free/glm-5.3-flash"),                # img #3 GLM-5.3-Flash
    ("cline-pass", "cline-free/solar-pro4"),                   # img #4 Solar Pro 4
    ("cline-pass", "cline-free/longcat-2.0"),                  # img #5 LongCat 2.0
    ("cline-pass", "cline-free/laguna-s-2.1"),                 # img #6 Laguna S 2.1
]


# Error classification: CLI 3.0.61 has no quota API, so we parse output.
# Exhausted-model signals -> try NEXT MODEL (same account).
# 'Insufficient balance' is included on purpose: the free img models are
# billed per-request and a near-zero $ balance rejects even "free" calls,
# so it rotates instead of stopping.
RETRYABLE_MODEL_RE = re.compile(
    r"429|rate[\s_-]*limit|quota|exhausted|overloaded|capacity|"
    r"temporarily[\s_-]*unavailable|model[\s_-]*not[\s_-]*available|"
    r"no[\s_-]*capacity|insufficient[\s_-]*(credit|quota|balance)|"
    r"billing|usage[\s_-]*limit|context[\s_-]*window|"
    r"promotion[\s_-]*ended|no[\s_-]*longer[\s_-]*available|"
    r"select another model|"
    r"max[\s_-]*tokens|invalid[\s_-]*model|model[\s_-]*not[\s_-]*found",
    re.IGNORECASE,
)

# Dead-login signals -> skip rest of THIS ACCOUNT, go to next account now.
AUTH_FAILURE_RE = re.compile(
    r"401|403|unauthorized|forbidden|invalid[\s_-]*token|expired[\s_-]*token|"
    r"refresh[\s_-]*token|reauth|login[\s_-]*required|sign[\s_-]*in|"
    r"account[\s_-]*not[\s_-]*found|session[\s_-]*expired",
    re.IGNORECASE,
)

# Hard user/config errors -> abort immediately, do NOT rotate.
FATAL_RE = re.compile(
    r"interactive mode requires a TTY|invalid option|unknown option|"
    r"no such file|cannot find|command not found",
    re.IGNORECASE,
)


@dataclass
class AttemptResult:
    ok: bool
    # success | next-model | next-account | fatal
    action: str
    reason: str
    exit_code: int
    output_tail: str


def classify_output(exit_code: int, output: str) -> AttemptResult:
    tail = "\n".join(output.splitlines()[-25:])
    if exit_code == 0 and not RETRYABLE_MODEL_RE.search(output) \
            and not AUTH_FAILURE_RE.search(output):
        return AttemptResult(True, "success", "exit 0, no error",
                             exit_code, tail)
    if FATAL_RE.search(output):
        return AttemptResult(False, "fatal", "fatal CLI error",
                             exit_code, tail)
    if AUTH_FAILURE_RE.search(output):
        return AttemptResult(False, "next-account", "auth failure",
                             exit_code, tail)
    return AttemptResult(False, "next-model", "retryable model error",
                         exit_code, tail)


def self_test() -> int:
    cases = [
        (1, "Error 429 rate limit exceeded", "next-model"),
        (1, "quota exhausted, try later", "next-model"),
        (1, "Model temporarily unavailable", "next-model"),
        (1, "invalid model 'cline-free/xyz'", "next-model"),
        (1, "Free model promotion ended, select another model", "next-model"),
        (1, "error: Insufficient balance. Your Cline Credits "
            "balance is $0.01", "next-model"),
        (1, "401 unauthorized, refresh token expired", "next-account"),
        (1, "session expired, please sign in", "next-account"),
        (1, "error: interactive mode requires a TTY", "fatal"),
        (0, "task completed successfully", "success"),
    ]
    failed = 0
    for code, out, want in cases:
        got = classify_output(code, out).action
        ok = got == want
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] want={want} got={got}")
    print(f"self-test: {len(cases)-failed}/{len(cases)} passed")
    return 0 if failed == 0 else 1



def clear_screen(enabled):
    if not enabled or not sys.stdout.isatty():
        return
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def header(acct, model, mode, i, total):
    return f"{acct}|{model}|{mode}|{i}/{total}"


def build_cmd(provider, model, cfg, mode, thinking, prompt, extra_args):
    cmd = ["cline", "-P", provider, "-m", model, "--config", cfg,
           "--auto-approve", "true"]
    if mode == "plan":
        cmd.append("--plan")
    if thinking:
        cmd += ["--thinking", thinking]
    cmd += extra_args
    cmd.append(prompt)
    return cmd


def run_stream(provider, model, cfg, mode, thinking, prompt, extra_args):
    cmd = build_cmd(provider, model, cfg, mode, thinking, prompt, extra_args)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        print("ERROR: `cline` binary not found on PATH.", flush=True)
        return AttemptResult(False, "fatal", "cline binary missing", 127, "")
    assert proc.stdout is not None
    try:
        out, _ = proc.communicate()
        rc = proc.returncode if proc.returncode is not None else -1
    except KeyboardInterrupt:
        proc.kill()
        raise
    res = classify_output(rc, out or "")
    if not res.ok:
        print(f"[{res.action}] exit={rc} reason={res.reason}", flush=True)
    return res


def run_capture(provider, model, cfg, mode, thinking, prompt, extra_args):
    cmd = build_cmd(provider, model, cfg, mode, thinking, prompt, extra_args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return AttemptResult(False, "fatal", "cline binary missing", 127, "")
    return classify_output(proc.returncode,
                          (proc.stdout or "") + "\n" + (proc.stderr or ""))


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="cline-runner: loop with model/account failover "
                    "(always yolo).")
    p.add_argument("prompt", nargs="?", default="",
                   help="Main prompt (runs once, first).")
    p.add_argument("-l", "--loops", type=int, default=0,
                   help="Per-loop-prompt count (default 0 = main only).")
    p.add_argument("-lp", "--loop-prompt", default=None,
                   help="Loop prompt: even loop iterations (2,4,6..).")
    p.add_argument("-lp2", "--loop-prompt2", default=None,
                   help="2nd loop prompt: odd loop iterations (1,3,5..).")
    p.add_argument("-m", "--mode", choices=["act", "plan"],
                   default="act", help="Cline mode (default act).")
    p.add_argument("-t", "--thinking", default=None,
                   choices=["none", "low", "medium", "high", "xhigh"],
                   help="Reasoning effort.")
    p.add_argument("--account-order", nargs="+",
                   default=DEFAULT_ACCOUNT_ORDER)
    p.add_argument("--start-model", default=None)
    p.add_argument("--cooldown", type=float, default=5.0)
    p.add_argument("--json-log", default=None)
    p.add_argument("--no-clear", action="store_true",
                   help="Do not clear terminal between outputs.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--self-test", action="store_true",
                   help="Test error classifier without calling cline.")
    args, unknown = p.parse_known_args(argv)
    if unknown and unknown[:1] == ["--"]:
        unknown = unknown[1:]
    args.extra = unknown
    if args.loops < 0:
        p.error("-l must be >= 0")
    if args.loops > 0 and not args.loop_prompt \
            and not args.loop_prompt2:
        p.error("-l needs at least one of -lp / -lp2")
    return args


def build_schedule(main_prompt, lp, lp2, loops):
    """Return ordered run list: [main] + alternating loop prompts.

    -l is the PER-PROMPT loop count: each loop prompt runs -l times.
    With both -lp and -lp2: they alternate starting with -lp (1st prompt
    runs on odd iterations, 2nd on even), so 2*-l loop runs total.
    With one of them: it simply runs -l times.
    """
    sched = [("main", main_prompt)]
    if loops <= 0:
        return sched
    if lp and lp2:
        for k in range(1, 2 * loops + 1):
            sched.append((f"lp-{k}" if k % 2 == 1 else f"lp2-{k}",
                          lp if k % 2 == 1 else lp2))
    elif lp:
        for k in range(1, loops + 1):
            sched.append((f"lp-{k}", lp))
    elif lp2:
        for k in range(1, loops + 1):
            sched.append((f"lp2-{k}", lp2))
    return sched


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.prompt.strip():
        print("ERROR: empty prompt (use --self-test to run without one).",
              file=sys.stderr)
        return 2
    for key in args.account_order:
        if key not in ACCOUNTS:
            print(f"ERROR: unknown account '{key}'.", file=sys.stderr)
            return 2
        if not Path(ACCOUNTS[key]).exists():
            print(f"WARNING: config dir missing: {ACCOUNTS[key]}",
                  file=sys.stderr)
    sched = build_schedule(args.prompt, args.loop_prompt,
                           args.loop_prompt2, args.loops)
    total = len(sched)
    combos = [(a, ACCOUNTS[a], pv, md)
              for a in args.account_order
              for (pv, md) in CLINE_PASS_MODELS]
    if args.start_model:
        needle = args.start_model.lower()
        idx = next((i for i, c in enumerate(combos)
                    if needle in c[3].lower()), None)
        if idx is None:
            print("ERROR: --start-model matches nothing.", file=sys.stderr)
            return 2
        combos = combos[idx:]
    if args.dry_run:
        for n, (tag, pr) in enumerate(sched, 1):
            print(f"run {n}/{total} [{tag}] prompt={pr[:60]!r}")
        for (a, c, pv, md) in combos:
            print(f"  {a} {pv}/{md} {args.mode}")
        return 0
    log_fh = open(args.json_log, "a",
                  encoding="utf-8") if args.json_log else None
    pos = 0
    failures = 0
    try:
        for i, (tag, prompt) in enumerate(sched, 1):
            done = False
            while pos < len(combos):
                acct, cfg, provider, model = combos[pos]
                clear_screen(not args.no_clear)
                print(header(acct, model, args.mode, i, total), flush=True)
                runner = run_stream if sys.stdout.isatty() else run_capture
                res = runner(provider, model, cfg, args.mode,
                             args.thinking, prompt, args.extra)
                entry = {"run": f"{i}/{total}", "slot": tag,
                         "account": acct, "config": cfg,
                         "provider": provider, "model": model,
                         "mode": args.mode, "action": res.action,
                         "reason": res.reason, "exit_code": res.exit_code}
                if log_fh:
                    log_fh.write(json.dumps(entry) + "\n")
                    log_fh.flush()
                if res.ok:
                    done = True
                    break
                if res.action == "fatal":
                    print(f"\nFATAL run {i}/{total} [{tag}] - stop.\n"
                          f"{res.output_tail}", file=sys.stderr)
                    return 3
                if res.action == "next-account":
                    pos += 1
                    while (pos < len(combos) and combos[pos][1] == cfg):
                        pos += 1
                    print(f"--> auth fail: skip rest of '{acct}'.", flush=True)
                else:
                    pos += 1
                failures += 1
                if pos < len(combos) and args.cooldown > 0:
                    time.sleep(args.cooldown)
            if not done:
                print(f"\nALL COMBOS EXHAUSTED at run {i}/{total} [{tag}].",
                      file=sys.stderr)
                return 3
            if i < total and args.cooldown > 0:
                time.sleep(args.cooldown)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    finally:
        if log_fh:
            log_fh.close()
    print(f"\nDone: {total}/{total} runs ok ({failures} failovers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
