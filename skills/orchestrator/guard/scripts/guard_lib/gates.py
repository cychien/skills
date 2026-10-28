"""Gates: a todo item that names a skill's check script closes only when that script exits 0."""
import contextlib
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time

from . import skills

GATE = re.compile(r"`\.\./([a-z0-9][a-z0-9-]*)/scripts/([A-Za-z0-9_-]+\.py)((?: -{0,2}[a-z][a-z-]*)*)`")
STALL = 600
POLL = 2
TERM_WAIT = 3
OUTPUT_LIMIT = 4000


class Stalled(Exception):
    """The gate and everything it started used no CPU and wrote no output for STALL seconds."""


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


def cpu_seconds(text):
    """`ps` time, `[[dd-]hh:]mm:ss[.ss]`, as seconds."""
    days, _, clock = text.rpartition("-")
    seconds = 0.0
    for field in clock.split(":"):
        seconds = seconds * 60 + float(field)
    return seconds + (int(days) * 86400 if days else 0)


def group_activity(pgid):
    """How many processes the group has and the CPU seconds they used; None when `ps` cannot say."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pgid=,time="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    rows = [line.split() for line in out.splitlines()]
    times = [cpu_seconds(row[1]) for row in rows if len(row) == 2 and row[0] == str(pgid)]
    return len(times), round(sum(times), 2)


def drain(stream, chunks):
    for line in stream:
        chunks.append(line)


def run_in_group(command, cwd):
    """Run the gate in its own session and wait for it however long it works; stop it and everything it started
    only once the whole group has used no CPU and written no output for STALL seconds."""
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True) as proc:
        out, err = [], []
        readers = [threading.Thread(target=drain, args=pair, daemon=True) for pair in ((proc.stdout, out), (proc.stderr, err))]
        for reader in readers:
            reader.start()
        last, quiet_since = None, time.monotonic()
        while proc.poll() is None or any(reader.is_alive() for reader in readers):
            mark = (group_activity(proc.pid), len(out), len(err))
            if mark != last:
                last, quiet_since = mark, time.monotonic()
            elif time.monotonic() - quiet_since >= STALL:
                stop_group(proc)
                raise Stalled
            if proc.poll() is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=POLL)
            else:
                for reader in readers:
                    reader.join(POLL)
    return subprocess.CompletedProcess(command, proc.returncode, "".join(out), "".join(err))


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
    except Stalled:
        return (f"the gate `{shown}` is stuck: it and everything it started used no CPU and wrote no output for {STALL} seconds, "
                "so guard stopped them. This is a tooling failure, not a failing check. "
                f"Run `python3 {shlex.join([str(path), *args])}` yourself from {cwd} to see where it hangs, fix that, "
                "then mark the item done again.")
    if r.returncode == 0:
        return None
    output = (r.stdout + r.stderr).strip()[-OUTPUT_LIMIT:]
    return f"the gate `{shown}` failed:\n{output}"


def failures(text, cwd=None):
    cwd = cwd or os.getcwd()
    return [f for skill, script, args in named(text) if (f := run(skill, script, args, cwd))]
