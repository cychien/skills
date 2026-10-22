"""The process table as guard reads it: one ps call, every process with its parent, CPU time, start, and command line."""
import collections
import os
import re
import signal
import subprocess
import time

from . import shell

Process = collections.namedtuple("Process", "pid ppid started cpu command")
DURATION = re.compile(r"^(?:(\d+)-)?(\d+(?:\.\d+)?)(?::(\d+(?:\.\d+)?))?(?::(\d+(?:\.\d+)?))?$")
SAME_START_S = 2.0


def seconds(text):
    """Seconds in a ps duration, [dd-][hh:]mm:ss[.cc] (etime, and time on Linux) or mmm:ss.cc (time on macOS)."""
    m = DURATION.match(text.strip())
    if not m:
        return None
    days, *parts = m.groups()
    total = 0.0
    for part in filter(None, parts):
        total = total * 60 + float(part)
    return int(days or 0) * 86400 + total


class Unseen(Exception):
    """ps could not list the processes, so which ones run is unknown, never "none"."""


def table():
    """{pid: Process}; raises Unseen when ps cannot run or lists nothing (it always lists itself)."""
    try:
        done = subprocess.run(["ps", "-ww", "-axo", "pid=,ppid=,etime=,time=,command="], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise Unseen(f"ps could not run: {e}")
    now, rows = time.time(), {}
    for line in done.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
            elapsed = seconds(parts[2])
            rows[int(parts[0])] = Process(int(parts[0]), int(parts[1]), now - elapsed if elapsed is not None else None,
                                          seconds(parts[3]) or 0.0, parts[4])
    if done.returncode or not rows:
        raise Unseen(f"ps exited {done.returncode}: {done.stderr.strip() or 'it listed no process'}")
    return rows


def ancestors(rows, pid):
    """pid's parent, its parent, and so on, nearest first."""
    chain, seen = [], {pid}
    pid = rows[pid].ppid if pid in rows else None
    while pid in rows and pid not in seen and pid > 1:
        chain.append(pid)
        seen.add(pid)
        pid = rows[pid].ppid
    return chain


def descendants(rows, pid):
    """pid and every process below it by parent."""
    children = collections.defaultdict(list)
    for row in rows.values():
        children[row.ppid].append(row.pid)
    found, todo = [], [pid]
    while todo:
        current = todo.pop()
        if current not in found:
            found.append(current)
            todo += children[current]
    return found


def is_shell(command):
    words = command.split()
    return bool(words) and os.path.basename(words[0]).lstrip("-") in shell.SHELLS


def same(rows, process):
    """Whether process still runs as the same process, not another that reused its pid."""
    now = rows.get(process.pid)
    return bool(now and now.command == process.command and
                (now.started is None or process.started is None or abs(now.started - process.started) <= SAME_START_S))


def command(pid):
    """pid's command line as ps prints it now, or None when no process has that pid; raises Unseen when ps cannot run."""
    try:
        done = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise Unseen(f"ps could not run: {e}")
    line = (done.stdout.splitlines() or [""])[0].strip()
    return line if not done.returncode and line else None


def signal_if(pid, is_it, sig):
    """Send sig to pid only while is_it(its command line, read right before the signal) holds; returns whether it was sent.
    Where the system has pidfds the signal goes through one opened before the read, so it cannot reach a process that took
    the pid after the check. Raises Unseen when ps cannot run, and then signals nothing."""
    pidfd, open_pidfd = None, getattr(os, "pidfd_open", None)
    if open_pidfd:
        try:
            pidfd = open_pidfd(pid)
        except ProcessLookupError:
            return False
        except OSError:
            pass
    try:
        now = command(pid)
        if now is None or not is_it(now):
            return False
        if pidfd is None:
            os.kill(pid, sig)
        else:
            signal.pidfd_send_signal(pidfd, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    finally:
        if pidfd is not None:
            os.close(pidfd)
