"""The process table as guard reads it: one ps call, every process with its parent, CPU time, start, and command line."""
import collections
import os
import re
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


def table():
    """{pid: Process}, or {} when ps cannot run."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,time=,command="], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    now, rows = time.time(), {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
            elapsed = seconds(parts[2])
            rows[int(parts[0])] = Process(int(parts[0]), int(parts[1]), now - elapsed if elapsed is not None else None,
                                          seconds(parts[3]) or 0.0, parts[4])
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
