#!/usr/bin/env python3
"""Confirm each agent:model[:effort] can actually run, with one tiny real call per entry.

Prints a JSON list of {spec, ok, error}. Exit code 1 if any entry failed.
Probes do not save sessions, so they never show up in usage history.
"""
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

PROMPT = "Reply with exactly: OK"


def command(agent, model, effort, cwd):
    if agent == "claude":
        cmd = ["claude", "-p", "--no-session-persistence", "--model", model]
        return cmd + (["--effort", effort] if effort else []) + [PROMPT]
    if agent == "codex":
        cmd = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-C", cwd, "-m", model]
        return cmd + (["-c", f"model_reasoning_effort={effort}"] if effort else []) + [PROMPT]
    return None


def probe(spec, cwd):
    agent, _, rest = spec.partition(":")
    model, _, effort = rest.partition(":")
    cmd = command(agent, model, effort or None, cwd)
    if cmd is None:
        return {"spec": spec, "ok": False, "error": f"no probe for agent '{agent}'; verify it by hand"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=cwd, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"spec": spec, "ok": False, "error": "timed out after 300s"}
    except OSError as e:
        return {"spec": spec, "ok": False, "error": str(e)}
    if r.returncode == 0 and r.stdout.strip():
        return {"spec": spec, "ok": True, "error": None}
    lines = [l for l in (r.stderr + r.stdout).splitlines() if l.strip()]
    return {"spec": spec, "ok": False, "error": "\n".join(lines[-3:]) or f"exit code {r.returncode}"}


def main():
    specs = sys.argv[1:]
    if not specs:
        sys.exit("usage: verify.py agent:model[:effort] ...")
    with tempfile.TemporaryDirectory() as cwd, ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: probe(s, cwd), specs))
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
