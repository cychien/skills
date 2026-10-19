"""Gates: a todo item that names a skill's check script closes only when that script exits 0."""
import contextlib
import os
import re
import shlex
import signal
import subprocess
import sys
import time

from . import skills

GATE = re.compile(r"`\.\./([a-z0-9][a-z0-9-]*)/scripts/([A-Za-z0-9_-]+\.py)((?: [a-z][a-z-]*)*)`")
TIMEOUT = 300
TERM_WAIT = 3
OUTPUT_LIMIT = 4000


def named(text):
    """Every gate an item's text names, as (skill, script, args)."""
    return [(skill, script, args.split()) for skill, script, args in GATE.findall(text)]


def stop_group(proc):
    for sig, wait in ((signal.SIGTERM, TERM_WAIT), (signal.SIGKILL, 0)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            proc.poll()
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)


def run_in_group(command, cwd):
    """subprocess.run in its own session, so a timeout stops the gate and every process it started."""
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True) as proc:
        try:
            out, err = proc.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            stop_group(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=TERM_WAIT)
            raise
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def run(skill, script, args, cwd):
    """Run one gate from the agent's working directory. Returns None when it passes, else why it failed."""
    found = skills.find(skill, cwd)
    path = found.parent / "scripts" / script if found else None
    shown = " ".join([f"../{skill}/scripts/{script}", *args])
    if not path or not path.is_file():
        return f"the gate `{shown}` names a script that is not installed."
    command = [sys.executable, str(path), *args]
    try:
        r = run_in_group(command, cwd)
    except subprocess.TimeoutExpired:
        return (f"the gate `{shown}` did not finish within {TIMEOUT} seconds, so guard stopped it and everything it started. "
                f"Run `python3 {shlex.join([str(path), *args])}` yourself, outside the hook, from {cwd}, then mark the item done again; "
                "a result or stamp it leaves behind lets the gate return at once.")
    if r.returncode == 0:
        return None
    output = (r.stdout + r.stderr).strip()[-OUTPUT_LIMIT:]
    return f"the gate `{shown}` failed:\n{output}"


def failures(text, cwd=None):
    cwd = cwd or os.getcwd()
    return [f for skill, script, args in named(text) if (f := run(skill, script, args, cwd))]
