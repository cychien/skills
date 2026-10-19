"""Run state on disk. Autonomous mode is on for a session exactly when it maps to an active run."""
import contextlib
import fcntl
import json
import os
import pathlib
import re
import secrets
import subprocess
import time

HOME = pathlib.Path(os.environ.get("AUTORUN_HOME") or pathlib.Path.home() / ".agents" / "autorun")
RUNS = HOME / "runs"
ACTIVE = HOME / "active"
SESSIONS = HOME / "sessions"
PENDING = HOME / "pending"
UNDECIDED = HOME / "undecided"

SESSION_ENV = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID", "gemini": "GEMINI_SESSION_ID"}
AGENT_BINARIES = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "copilot": "copilot",
    "cursor-agent": "cursor",
    "agent": "cursor",
}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
INTERPRETERS = {"node", "bun", "deno"}
PENDING_TTL = 600


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def mark_undecided(agent, session, skill):
    UNDECIDED.mkdir(parents=True, exist_ok=True)
    (UNDECIDED / _session_key(agent, session)).write_text(skill)


def undecided(agent, session):
    """The skill whose invocation still awaits a run-mode decision in this session, if any."""
    try:
        return (UNDECIDED / _session_key(agent, session)).read_text()
    except OSError:
        return None


def clear_undecided(agent, session):
    if agent and session:
        (UNDECIDED / _session_key(agent, session)).unlink(missing_ok=True)


def any_undecided():
    return UNDECIDED.is_dir() and any(UNDECIDED.iterdir())


def any_active():
    return ACTIVE.is_dir() and any(ACTIVE.iterdir())


def _write_json(path, data):
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _session_key(agent, session):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{agent}-{session}")


class Run:
    def __init__(self, run_id):
        self.id = run_id
        self.dir = RUNS / run_id

    @property
    def path(self):
        return self.dir / "run.json"

    @property
    def decisions_path(self):
        return self.dir / "decisions.jsonl"

    @property
    def gates_dir(self):
        return self.dir / "gates"

    def data(self):
        return _read_json(self.path) or {}

    @property
    def active(self):
        return self.data().get("status") == "active"

    @contextlib.contextmanager
    def update(self):
        with open(self.dir / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.data()
            yield data
            _write_json(self.path, data)

    def set_status(self, status):
        with self.update() as d:
            d["status"] = status
            d["ended"] = now()
        (ACTIVE / self.id).unlink(missing_ok=True)

    def record_decision(self, entry):
        entry = {"at": now(), **entry}
        with open(self.decisions_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def decisions(self):
        if not self.decisions_path.exists():
            return []
        out = []
        for line in self.decisions_path.read_text().splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
        return out

    def new_gate(self, gate):
        self.gates_dir.mkdir(exist_ok=True)
        gate = {"id": "g-" + secrets.token_hex(3), "created": now(), "status": "open", "surfaced": False, **gate}
        _write_json(self.gates_dir / f"{gate['id']}.json", gate)
        return gate

    def gates(self, *statuses):
        if not self.gates_dir.is_dir():
            return []
        found = [_read_json(p) for p in sorted(self.gates_dir.glob("g-*.json"))]
        return sorted((g for g in found if g and (not statuses or g["status"] in statuses)), key=lambda g: g["created"])

    def add_approval(self, subject):
        with self.update() as d:
            d.setdefault("approvals", []).append(subject)

    def has_approval(self, subject):
        return subject in self.data().get("approvals", [])

    def take_approval(self, subject):
        """Consume one approval for exactly this call; approvals are single-use."""
        with self.update() as d:
            approvals = d.get("approvals", [])
            if subject not in approvals:
                return False
            approvals.remove(subject)
            return True

    def save_gate(self, gate):
        _write_json(self.gates_dir / f"{gate['id']}.json", gate)


def create_run(agent, session, cwd, trigger, prompt, agent_proc=None):
    run_id = time.strftime("r-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    run = Run(run_id)
    run.dir.mkdir(parents=True)
    ACTIVE.mkdir(parents=True, exist_ok=True)
    data = {
        "id": run_id,
        "status": "active",
        "created": now(),
        "agent": agent,
        "root_session": session,
        "cwd": cwd,
        "trigger": trigger,
        "prompt": (prompt or "")[:4000],
        "base": git_head(cwd),
        "done": None,
        "check": None,
        "agent_procs": [agent_proc] if agent_proc else [],
        "briefed": [],
        "activity": 0,
        "activity_at_last_block": -1,
        "idle_blocks": 0,
    }
    _write_json(run.path, data)
    (ACTIVE / run_id).touch()
    if session:
        bind(agent, session, run, "root")
    return run


def git_head(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd or ".", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def has_commit(cwd, rev):
    if not rev:
        return False
    try:
        return subprocess.run(["git", "-C", cwd, "cat-file", "-e", f"{rev}^{{commit}}"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_registered(run, proc):
    return proc in run.data().get("agent_procs", [])


def bind(agent, session, run, role):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    _write_json(SESSIONS / _session_key(agent, session), {"run": run.id, "role": role})


def lookup(agent, session):
    if not session:
        return None, None
    entry = _read_json(SESSIONS / _session_key(agent, session))
    if not entry:
        return None, None
    run = Run(entry["run"])
    return (run, entry["role"]) if run.active else (None, None)


def active_runs():
    if not ACTIVE.is_dir():
        return []
    return [r for r in (Run(p.name) for p in ACTIVE.iterdir()) if r.active]


def processes():
    """pid -> (ppid, start time, program name), from one ps call."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,lstart=,command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 7:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        start = " ".join(parts[2:7])
        argv = parts[7].split() if len(parts) > 7 else []
        names = [os.path.basename(a) for a in argv[:2]]
        name = names[1] if names and names[0] in INTERPRETERS and len(names) > 1 else (names[0] if names else "")
        table[pid] = (ppid, start, name.removesuffix(".js"))
    return table


def ancestors(table, pid):
    """pid and its ancestors, stopping below $AUTORUN_BOUNDARY_PID, which a launcher sets so its children stay out of its run."""
    boundary = int(os.environ.get("AUTORUN_BOUNDARY_PID") or 0)
    seen = []
    while pid in table and pid not in seen and pid > 1 and pid != boundary:
        seen.append(pid)
        pid = table[pid][0]
    return seen


def proc_ref(table, pid):
    return {"pid": pid, "start": table[pid][1]} if pid in table else None


def hook_agent_proc(table):
    """The agent process that ran this hook: the nearest ancestor that is not a shell."""
    for pid in ancestors(table, os.getppid()):
        if table[pid][2] not in SHELLS:
            return proc_ref(table, pid)
    return None


def proc_cwd(pid):
    """The working directory of a process: where an agent session started, unaffected by the agent's own `cd`s."""
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        pass
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return next((line[1:] for line in out.splitlines() if line.startswith("n")), None)


def host_agent(table):
    """(agent, session, proc) for the nearest agent CLI above this process, as seen from a shell it spawned."""
    for pid in ancestors(table, os.getpid()):
        agent = AGENT_BINARIES.get(table[pid][2])
        if agent:
            return agent, os.environ.get(SESSION_ENV.get(agent, ""), "") or None, proc_ref(table, pid)
    return None, None, None


def run_owning_ancestor(table, pid):
    """The active run whose registered agent process is an ancestor of pid, if any."""
    chain = {(p, table[p][1]) for p in ancestors(table, pid)}
    for run in active_runs():
        for proc in run.data().get("agent_procs", []):
            if (proc["pid"], proc["start"]) in chain:
                return run
    return None


def register_proc(run, proc):
    if not proc:
        return
    with run.update() as d:
        if proc not in d.setdefault("agent_procs", []):
            d["agent_procs"].append(proc)


def add_pending(run, cwd):
    PENDING.mkdir(parents=True, exist_ok=True)
    _write_json(PENDING / run.id, {"run": run.id, "cwd": cwd, "at": time.time()})


def claim_pending(cwd):
    if not PENDING.is_dir():
        return None
    for p in PENDING.iterdir():
        entry = _read_json(p)
        p_age = time.time() - entry["at"] if entry else PENDING_TTL + 1
        if p_age > PENDING_TTL:
            p.unlink(missing_ok=True)
        elif entry["cwd"] == cwd and Run(entry["run"]).active:
            p.unlink(missing_ok=True)
            return Run(entry["run"])
    return None


def resolve(agent, session, cwd, agent_id=None):
    """(run, role) for a hook call, joining a run this session descends from. role: root, subagent, delegate."""
    run, role = lookup(agent, session)
    if run:
        return run, ("subagent" if agent_id and role == "root" else role)
    if not any_active():
        return None, None
    explicit = os.environ.get("AUTORUN_RUN")
    if explicit and Run(explicit).active:
        run = Run(explicit)
        role = "delegate"
    else:
        table = processes()
        own = hook_agent_proc(table)
        # One agent process can host unrelated sessions (Cursor), so only a strict ancestor counts.
        run = run_owning_ancestor(table, table[own["pid"]][0]) if own else None
        role = "delegate"
        if not run:
            run = claim_pending(cwd)
            role = "root"
            if run:
                with run.update() as d:
                    d["agent"], d["root_session"] = agent, session
                register_proc(run, own)
    if run and session:
        bind(agent, session, run, role)
    return (run, role) if run else (None, None)


def resolve_cli(run_id=None):
    """The run a CLI command acts on: explicit id, then the calling agent's session, then process ancestry."""
    if run_id:
        run = Run(run_id)
        if not run.path.exists():
            raise SystemExit(f"autorun: no run {run_id}")
        return run
    explicit = os.environ.get("AUTORUN_RUN")
    if explicit and Run(explicit).path.exists():
        return Run(explicit)
    table = processes()
    agent, session, _ = host_agent(table)
    run, _ = lookup(agent, session) if agent else (None, None)
    return run or run_owning_ancestor(table, os.getpid())
