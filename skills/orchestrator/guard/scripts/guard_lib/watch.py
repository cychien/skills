"""The watchdog: it asks the lead about a background job that went silent, and never stops one.

It watches the process trees under the agent that started it, one job per shell the agent runs, and counts as progress
any growth of a file the job's processes write as stdout or stderr, CPU time above a floor, or a process with a command
line the job has not run before. Each job's silence threshold adapts to the longest gap between its own progress events.
"""
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

from . import procs, shell, state

INTERVAL_S = 5.0
INITIAL_S = 300.0
MULTIPLE = 3.0
EVENTS = 3
CPU_FLOOR = 0.05
COMMAND_CHARS = 120
LINE_CHARS = 160
TAIL_BYTES = 8192
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
NO_AGENT = 2
ALREADY = 3
UNSEEN = 4
UNSEEN_SAMPLES = 3


class Job:
    """One shell the agent runs and the processes below it, with when it last progressed and its longest quiet gap."""

    def __init__(self, root, now):
        self.root, self.last, self.events, self.longest = root, now, 0, 0.0
        self.cpu, self.at, self.commands, self.sizes = None, now, set(), {}

    def observe(self, rows, tree, sizes, now, cpu_floor):
        """Fold one sample in; returns whether the job progressed since the last one."""
        cpu = sum(rows[pid].cpu for pid in tree)
        commands = {rows[pid].command for pid in tree}
        if self.cpu is None:
            progressed = False
        else:
            grew = any(size > self.sizes[path] for path, size in sizes.items() if path in self.sizes)
            busy = cpu - self.cpu >= cpu_floor * (now - self.at)
            progressed = grew or busy or bool(commands - self.commands)
        self.cpu, self.at, self.sizes = cpu, now, sizes
        self.commands |= commands
        if progressed:
            self.longest = max(self.longest, now - self.last)
            self.events += 1
            self.last = now
        return progressed

    def threshold(self, initial, multiple, events):
        """initial until the job has shown enough progress events to judge its own rhythm, then multiple times its longest
        gap, never below initial, so a healthy job's pause costs no question."""
        return initial if self.events < events else max(initial, multiple * self.longest)


class Outputs:
    """The regular files each process writes as its stdout and stderr, read once per process once it has lived through
    one sample, so a burst of short-lived processes costs no lookups: /proc where the system has it, else lsof; without
    either only CPU time and new processes count."""

    def __init__(self):
        self.files, self.waiting, self.proc = {}, set(), os.path.isdir("/proc/self/fd")
        self.lsof = None if self.proc else shutil.which("lsof")

    @property
    def blind(self):
        return not self.proc and not self.lsof

    def of(self, pids):
        unknown = [pid for pid in pids if pid not in self.files]
        ready = [pid for pid in unknown if pid in self.waiting]
        if ready:
            self.files.update(self.read(ready))
        self.waiting = set(unknown) - set(ready)
        return {pid: self.files.get(pid, []) for pid in pids}

    def read(self, pids):
        found = {pid: [] for pid in pids}
        if self.proc:
            for pid in pids:
                for fd in ("1", "2"):
                    with contextlib.suppress(OSError):
                        found[pid].append(os.readlink(f"/proc/{pid}/fd/{fd}"))
        elif self.lsof:
            try:
                out = subprocess.run([self.lsof, "-a", "-p", ",".join(map(str, pids)), "-d", "1,2", "-Fpn"], capture_output=True,
                                     text=True, timeout=30).stdout
            except (OSError, subprocess.SubprocessError):
                out = ""
            pid = None
            for line in out.splitlines():
                if line.startswith("p"):
                    pid = int(line[1:])
                elif line.startswith("n") and pid in found:
                    found[pid].append(line[1:])
        return {pid: sorted({path for path in paths if os.path.isfile(path)}) for pid, paths in found.items()}

    def forget(self, live):
        self.files = {pid: paths for pid, paths in self.files.items() if pid in live}


def find_agent(rows, me=None):
    """(the agent process, the pid on this process's chain right below it): the first ancestor of this process's parent
    shell that is not a shell, or (None, None)."""
    me = me or os.getpid()
    below = me
    for pid in procs.ancestors(rows, me):
        if not procs.is_shell(rows[pid].command):
            return rows[pid], below
        below = pid
    return None, None


def size(path):
    with contextlib.suppress(OSError):
        return os.stat(path).st_size
    return None


def last_line(path):
    with contextlib.suppress(OSError), open(path, "rb") as f:
        f.seek(max(0, os.fstat(f.fileno()).st_size - TAIL_BYTES))
        lines = [ANSI.sub("", line).strip() for line in f.read().decode(errors="replace").replace("\r", "\n").splitlines()]
        return next((line for line in reversed(lines) if line), "")
    return ""


def clip(text, limit):
    return text if len(text) <= limit else text[:limit - 3] + "..."


class Watchdog:
    def __init__(self, agent, own, initial=INITIAL_S, multiple=MULTIPLE, events=EVENTS, cpu_floor=CPU_FLOOR, outputs=None):
        self.agent, self.own = agent, own
        self.initial, self.multiple, self.events, self.cpu_floor = initial, multiple, events, cpu_floor
        self.outputs = outputs or Outputs()
        self.jobs = {}

    def sample(self, rows, now, acks=()):
        """The jobs silent past their threshold in this sample of the process table; a job holding an acknowledged process
        is not watched."""
        held = {a["pid"] for a in acks if procs.same(rows, procs.Process(a["pid"], 0, a["started"], 0.0, a["command"]))}
        trees = {root.pid: procs.descendants(rows, root.pid) for root in rows.values()
                 if root.ppid == self.agent.pid and root.pid != self.own and procs.is_shell(root.command)}
        trees = {pid: tree for pid, tree in trees.items() if not held & set(tree)}
        files = self.outputs.of([pid for tree in trees.values() for pid in tree])
        live = {}
        for pid, tree in trees.items():
            job = self.jobs.get(pid)
            if not job or not procs.same(rows, job.root):
                job = Job(rows[pid], now)
            job.tree, job.files = tree, {p: files[p] for p in tree}
            sizes = {path: s for p in tree for path in files[p] if (s := size(path)) is not None}
            job.observe(rows, tree, sizes, now, self.cpu_floor)
            live[pid] = job
        self.jobs = live
        self.outputs.forget(files)
        return [job for job in live.values() if now - job.last >= job.threshold(self.initial, self.multiple, self.events)]

    def report(self, job, rows, now):
        """One line: the job's pid, what it runs, how long it is silent against its usual gap, and its last output line."""
        runs = [rows[pid] for pid in job.tree[1:] if pid in rows and not procs.is_shell(rows[pid].command)]
        command = min(runs, key=lambda p: p.started or now).command if runs else job.root.command
        files = job.files.get(job.root.pid) or next((paths for paths in job.files.values() if paths), [])
        gap = f"its longest gap before was {span(job.longest)}" if job.events else "no progress since the watchdog started"
        output = f"; last output: {clip(last_line(files[0]), LINE_CHARS) or '(none)'} [{files[0]}]" if files else "; no output file"
        threshold = job.threshold(self.initial, self.multiple, self.events)
        return (f"pid {job.root.pid} silent {span(now - job.last)} (asks after {span(threshold)}; {gap}): "
                f"{clip(' '.join(command.split()), COMMAND_CHARS)}{output}")


def span(seconds):
    return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"


def cli(agent, session, *flags):
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
    return shlex.join(["python3", script, "watch", *flags, "--session", f"{agent}:{session}"]).replace("'<pid>'", "<pid>")


def runs_watchdog(command):
    return any(rest[:1] == ["watch"] and not ({"--ack", "--stop"} & set(rest)) for rest in shell.invocations(command or "", "guard.py"))


def record(agent, session):
    with contextlib.suppress(OSError, ValueError):
        return json.loads(state.watch_path(agent, session).read_text())
    return None


def alive(agent, session, rows=None):
    """The watchdog record of this session while the process it names is that watchdog: the pid runs a watchdog that
    started when the record says, and the record is this session's. Else None; raises procs.Unseen when ps cannot run."""
    found = record(agent, session)
    if not isinstance(found, dict) or found.get("session") != f"{agent}:{session}":
        return None
    rows = rows if rows is not None else procs.table()
    process = rows.get(found.get("pid"))
    if process and procs.born_at(rows, process.pid, found.get("started")) and runs_watchdog(process.command):
        return found
    return None


def claim(agent, session, agent_pid):
    """Record this process as the session's watchdog; the record of one already running when another holds it. Raises
    procs.Unseen when ps cannot run, because another watchdog may then be alive."""
    with state.lock(agent, session):
        rows = procs.table()
        running = alive(agent, session, rows)
        if running and running["pid"] != os.getpid():
            return running
        me = rows.get(os.getpid())
        state.watch_path(agent, session).write_text(json.dumps({
            "pid": os.getpid(), "started": me.started if me else None, "session": f"{agent}:{session}", "agent": agent_pid,
            "since": time.time()}) + "\n")
        with state.update(agent, session, locked=True) as data:
            data.pop("watch_unavailable", None)
            data["watch_blocks"] = 0
    return None


def release(agent, session):
    with state.lock(agent, session):
        found = record(agent, session)
        if isinstance(found, dict) and found.get("pid") == os.getpid():
            state.watch_path(agent, session).unlink(missing_ok=True)


def stop(agent, session):
    """SIGTERM the session's watchdog once its pid file and the process agree on who it is; returns its pid, or None when
    none runs. Raises procs.Unseen when ps cannot run, and then signals nothing."""
    running = alive(agent, session)
    if not running:
        return None
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(running["pid"], signal.SIGTERM)
    return running["pid"]


def unavailable(agent, session, why):
    with state.update(agent, session) as data:
        data["watch_unavailable"] = {"at": time.time(), "why": why}


def acknowledged(agent, session):
    """The processes the lead acknowledged as intentionally idle in this session."""
    return state.load(agent, session).get("watch_acked", [])


def ack(agent, session, pid):
    try:
        rows = procs.table()
    except procs.Unseen as e:
        sys.exit(f"guard: cannot list processes ({e}), so {pid} cannot be acknowledged; try again.")
    process = rows.get(pid)
    if not process:
        sys.exit(f"guard: no process {pid} runs, so there is nothing to acknowledge.")
    with state.update(agent, session) as data:
        kept = [a for a in data.get("watch_acked", []) if a["pid"] in rows and a["pid"] != pid]
        data["watch_acked"] = kept + [{"pid": pid, "started": process.started, "command": process.command}]
    return f"Acknowledged {pid} ({clip(' '.join(process.command.split()), COMMAND_CHARS)}): the watchdog never asks about it again in this session."


def run(agent, session, interval=INTERVAL_S, initial=INITIAL_S, multiple=MULTIPLE, events=EVENTS, cpu_floor=CPU_FLOOR):
    """Watch until a job goes silent (print the report, exit 0), the agent process exits, or a signal stops it. When ps
    fails, which processes run is unknown: it never starts over another watchdog it cannot rule out, and it exits with an
    error after UNSEEN_SAMPLES failed samples in a row instead of watching blind."""
    try:
        rows = procs.table()
        found, own = find_agent(rows)
        running = claim(agent, session, found.pid) if found else None
    except procs.Unseen as e:
        why = f"cannot list processes ({e}), so it cannot tell whether another watchdog of this session runs"
        print(f"guard watch: {why}; nothing started.")
        return UNSEEN
    if not found:
        why = "found no agent process above this one (no ancestor of its parent shell that is not a shell)"
        unavailable(agent, session, why)
        print(f"guard watch: {why}, so it would watch nothing. Start it from your agent's own shell tool, as a background job.")
        return NO_AGENT
    if running:
        print(f"guard watch: a watchdog already watches this session (pid {running['pid']}); nothing to start.")
        return ALREADY
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        dog = Watchdog(found, own, initial, multiple, events, cpu_floor)
        if dog.outputs.blind:
            print("guard watch: lsof is not installed, so output growth is not watched; CPU time and new processes still count.",
                  flush=True)
        unseen = 0
        while True:
            now = time.time()
            if not procs.same(rows, found) or os.getppid() == 1:
                return 0
            silent = dog.sample(rows, now, acknowledged(agent, session))
            if silent:
                print("\n".join([*(dog.report(job, rows, now) for job in silent),
                                 "guard watch: the jobs above went silent. Read each one's output and processes, then stop a stuck "
                                 "one (your task-stop tool; `verify.py stop <id>` for a verify script) or acknowledge one meant "
                                 f"to idle with `{cli(agent, session, '--ack', '<pid>')}`, and start the watchdog again in the "
                                 f"background: {cli(agent, session)}"]))
                return 0
            while True:
                time.sleep(interval)
                try:
                    rows = procs.table()
                    break
                except procs.Unseen as e:
                    unseen += 1
                    if unseen >= UNSEEN_SAMPLES:
                        why = f"cannot list processes: {UNSEEN_SAMPLES} samples in a row failed ({e})"
                        unavailable(agent, session, why)
                        print(f"guard watch: {why}, so it cannot see the jobs or whether its agent still runs, and it stops "
                              f"watching instead of watching blind. Start it again once ps works: {cli(agent, session)}")
                        return UNSEEN
            unseen = 0
    finally:
        release(agent, session)
