#!/usr/bin/env python3
"""Run one task on several agent:model[:effort] specs in parallel, each in its own workspace.

usage:
  salvo.py run --out <dir> [--clean-room] [--hide-skill <name> ...] agent:model[:effort] ... < task.md
  salvo.py clean <dir>

Inside a git repo, every run gets a detached worktree (a standalone clone with
--clean-room) of a snapshot of the current working tree, uncommitted and untracked
files included. Outside one, every run gets
its own empty directory. Blocks until all runs finish, then prints a JSON summary.
salvo.json in --out says "status": "running" until every run has finished, then "done".

Each runner starts in its own session, so a timeout, or the runner finishing, takes down every process it started
in that session. `clean` stops any process still running from a workspace, the shadow home, or the run directory
(SIGTERM, then SIGKILL) and refuses to delete anything while one survives, because a directory removed under a live
process hides it.

A run stopped by a usage limit that resets within 24 hours waits for the reset and resumes
its own session, up to 3 times; salvo.json lists each wait under "limit_waits". Every limit a run
hits is also recorded in the orchestrator's limits registry (~/.agents/orchestrator/limits.json,
$ORCHESTRATOR_HOME overrides the folder), so other sessions hand that agent's work to another candidate.

--clean-room keeps the setup invisible to the runs: each workspace lives at
/tmp/<random>/<source directory name>, unconnected to --out or the source, and the prompt
carries no orchestration wording.

--hide-skill hides the user-level installs of a skill, so a run sees only the copy in its
workspace, if any. Everything else the user has installed stays visible. Claude gets a
shadow HOME that mirrors the real one minus those skills, because a user-level skill
outranks a project skill of the same name. Codex keeps its real home and has those
skills disabled by path.
"""
import argparse
import datetime
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
import time
from concurrent.futures import ThreadPoolExecutor

AGENTS = ("claude", "codex")
# Byproducts of running code; excluded even when the repo forgets to ignore them.
ARTIFACTS = ["__pycache__", "*.pyc", "node_modules", ".DS_Store", ".pytest_cache", ".venv"]
LIMIT_RESUMES = 3
KILL_WAIT_S = 3.0
RESET_MARGIN_S = 60
MAX_LIMIT_WAIT_S = 24 * 3600
CONTINUE_PROMPT = ("Your usage limit has reset. Continue the task you were working on when the limit was reached; "
                   "do not repeat work that is already complete.")
CODEX_RETRY_AT = re.compile(r"usage limit\b.*\btry again at ([^\n]+?)\.?\s*(?:\n|$)", re.I | re.S)
# Codex states the reset in local clock time, rounded to the minute.
CODEX_CLOCK_SLACK_S = 600

DELEGATE = "You are a delegate of a larger run: never run autorun.py start, done, or stop; only the session that launched you may change or finish that run."
FOOTER_GIT = """
---
Your working directory is {work}, a private copy of {source} in its current state. Edit it freely; nothing you do there touches the original.
""" + DELEGATE
FOOTER_PLAIN = """
---
Your working directory is {work}. It starts empty. Read anything you need from {source}, but write files only inside your working directory.
""" + DELEGATE
FOOTER_CLEAN_GIT = """
---
The project is at {work}."""
FOOTER_CLEAN_PLAIN = """
---
Work in {work}. The material is in {source}."""
FOOTER_COMMON = """
Nobody can answer questions during this run, so make reasonable assumptions and state them.
Your final message is your deliverable. For a question, give the full answer. For changes, say what you changed, how you verified it, and what is left unfinished.
"""


def git(cwd, *args, env=None, check=True, raw=False):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout if raw else r.stdout.strip()


def snapshot_tree(cwd):
    """Tree of the working directory as `git add -A` would see it, without touching the real index."""
    with tempfile.TemporaryDirectory() as tmp:
        index = os.path.join(tmp, "index")
        real = os.path.join(cwd, git(cwd, "rev-parse", "--git-path", "index"))
        if os.path.exists(real):
            shutil.copy(real, index)
        env = {**os.environ, "GIT_INDEX_FILE": index}
        excludes = [f":(exclude,glob)**/{p}" for p in ARTIFACTS] + [f":(exclude,glob)**/{p}/**" for p in ARTIFACTS]
        git(cwd, "add", "-A", "--", ".", *excludes, env=env)
        return git(cwd, "write-tree", env=env)


def label(n, spec):
    return f"{n}-" + re.sub(r"[^A-Za-z0-9.]+", "-", spec.split(":")[1]).strip("-")


def codex_home():
    return os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))


def codex_skill_overrides(hidden):
    """skills.config for codex: the user's own entries plus a disable for each hidden install."""
    config = os.path.join(codex_home(), "config.toml")
    entries = []
    if os.path.exists(config):
        with open(config, "rb") as f:
            entries = tomllib.load(f).get("skills", {}).get("config", [])
    for name in hidden:
        for root in (os.path.expanduser("~/.agents/skills"), os.path.join(codex_home(), "skills")):
            skill = os.path.join(root, name, "SKILL.md")
            if os.path.exists(skill):
                entries += [{"path": p, "enabled": False} for p in {skill, os.path.realpath(skill)}]
    if not entries:
        return []
    items = ",".join("{" + ",".join(f"{k}={json.dumps(v)}" for k, v in e.items()) + "}" for e in entries)
    return ["-c", f"skills.config=[{items}]"]


def build_shadow_home(root, hidden):
    """A HOME whose entries all link to the real one, except ~/.claude/skills without the hidden skills."""
    real = os.path.expanduser("~")
    home = os.path.join(root, os.path.basename(real))
    os.makedirs(os.path.join(home, ".claude", "skills"))
    for name in os.listdir(real):
        if name != ".claude":
            os.symlink(os.path.join(real, name), os.path.join(home, name))
    real_claude = os.path.join(real, ".claude")
    for name in os.listdir(real_claude) if os.path.isdir(real_claude) else []:
        if name != "skills":
            os.symlink(os.path.join(real_claude, name), os.path.join(home, ".claude", name))
    real_skills = os.path.join(real_claude, "skills")
    for name in os.listdir(real_skills) if os.path.isdir(real_skills) else []:
        if name not in hidden:
            os.symlink(os.path.realpath(os.path.join(real_skills, name)), os.path.join(home, ".claude", "skills", name))
    return home


def command(agent, model, effort, work, result_path, hidden, session=None):
    if agent == "claude":
        cmd = ["claude", "-p", "--model", model, "--permission-mode", "bypassPermissions",
               "--output-format", "stream-json", "--verbose"]
        cmd += ["--effort", effort] if effort else []
        return cmd + (["--resume", session] if session else [])
    # codex exec resume takes neither -C nor -s; it runs in the subprocess cwd.
    head = ["codex", "exec", "resume"] if session else ["codex", "exec"]
    sandbox = ["-c", 'sandbox_mode="workspace-write"'] if session else ["-C", work, "-s", "workspace-write"]
    cmd = head + ["--skip-git-repo-check", *sandbox, "-m", model, "-c", "sandbox_workspace_write.network_access=true",
                  "--json", "-o", result_path]
    cmd += codex_skill_overrides(hidden) if hidden else []
    cmd += ["-c", f"model_reasoning_effort={effort}"] if effort else []
    return cmd + ([session, "-"] if session else ["-"])


def read_events(log_path, start=0):
    events = []
    with open(log_path, errors="ignore") as f:
        f.seek(start)
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def collect(agent, run, log_path, result_path):
    events = read_events(log_path)
    if agent == "claude":
        final = next((e for e in reversed(events) if e.get("type") == "result"), {})
        session = final.get("session_id")
        is_error = final.get("is_error", not final)
        if is_error and final.get("result"):
            run["agent_error"] = final["result"]
        else:
            with open(result_path, "w") as f:
                f.write(final.get("result") or "")
        return session, is_error, f"cd {run['work']} && claude --resume {session}"
    session = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
    last_turn = next((e for e in reversed(events) if e.get("type") in ("turn.completed", "turn.failed")), {})
    return session, last_turn.get("type") == "turn.failed", f"codex resume {session}"


def codex_reset(text, now):
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip())
    for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            return datetime.datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    try:
        clock = datetime.datetime.strptime(text, "%I:%M %p")
    except ValueError:
        return None
    at = datetime.datetime.fromtimestamp(now).replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
    if at.timestamp() < now - CODEX_CLOCK_SLACK_S:
        at += datetime.timedelta(days=1)
    return at.timestamp()


def limit_reset(agent, events, now):
    """When the usage limit that ended this attempt resets, in epoch seconds, or None if no limit ended it."""
    if agent == "claude":
        hit = next((e for e in reversed(events) if e.get("type") == "rate_limit_event"), {})
        info = hit.get("rate_limit_info") or {}
        return info.get("resetsAt") if info.get("status") == "rejected" else None
    failed = next((e for e in reversed(events) if e.get("type") == "turn.failed"), {})
    found = CODEX_RETRY_AT.search((failed.get("error") or {}).get("message") or "")
    return codex_reset(found.group(1), now) if found else None


def record_limit(agent, reset, source):
    """Add the limit to the orchestrator's limits registry, in the format guard's quota rules read."""
    folder = os.environ.get("ORCHESTRATOR_HOME") or os.path.expanduser("~/.agents/orchestrator")
    now = time.time()
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, ".limits.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = os.path.join(folder, "limits.json")
            try:
                with open(path) as f:
                    current = json.load(f)
            except (OSError, json.JSONDecodeError):
                current = {}
            current = {a: e for a, e in current.items() if isinstance(e, dict) and limit_until(e) > now}
            current[agent] = {"until": local_iso(reset), "seen": local_iso(now), "source": source}
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w") as f:
                json.dump(current, f, indent=2)
                f.write("\n")
            os.replace(tmp, path)
    except OSError as e:
        print(f"salvo: could not record the {agent} usage limit: {e}", file=sys.stderr)


def local_iso(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="minutes")


def limit_until(entry):
    try:
        return datetime.datetime.fromisoformat(entry.get("until")).timestamp()
    except (TypeError, ValueError):
        return 0


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def process_table():
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,command="], capture_output=True, text=True, timeout=15).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit():
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]), "stat": parts[3], "command": parts[4]})
    return rows


def process_cwds():
    """Working directory of every process this user can see; a deleted one keeps the path it had."""
    if os.path.exists("/proc/self/cwd"):
        cwds = {}
        for name in os.listdir("/proc"):
            try:
                cwds[int(name)] = os.readlink(f"/proc/{name}/cwd").removesuffix(" (deleted)")
            except (ValueError, OSError):
                pass
        return cwds
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.exit(f"cannot read process working directories with lsof: {e}")
    cwds, pid = {}, None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            cwds[pid] = line[1:]
    return cwds


def lineage(table):
    parents = {row["pid"]: row["ppid"] for row in table}
    chain, pid = set(), os.getpid()
    while pid and pid not in chain:
        chain.add(pid)
        pid = parents.get(pid)
    return chain


def processes_under(roots):
    """Processes whose working directory or command line is under any root, excluding this process and its ancestors."""
    paths = {p.rstrip("/") for r in roots if r for p in (r, os.path.realpath(r))} - {""}
    if not paths:
        return []
    body = "|".join(re.escape(p) for p in sorted(paths))
    in_cwd, in_command = re.compile(rf"^(?:{body})(?:/|$)"), re.compile(rf"(?<![\w./-])(?:{body})(?=/|$|[^\w.-])")
    table = process_table()
    skip = lineage(table)
    cwds = process_cwds()
    return [{**row, "cwd": cwds.get(row["pid"])} for row in table
            if row["pid"] not in skip and not row["stat"].startswith("Z")
            and ((cwds.get(row["pid"]) and in_cwd.search(cwds[row["pid"]])) or in_command.search(row["command"]))]


def signal_processes(found, sig):
    table = process_table()
    skip = lineage(table)
    protected = {row["pgid"] for row in table if row["pid"] in skip}
    for proc in found:
        try:
            if proc["pgid"] in protected or proc["pgid"] <= 1:
                os.kill(proc["pid"], sig)
            else:
                os.killpg(proc["pgid"], sig)
        except (ProcessLookupError, PermissionError):
            pass


def stop_processes_under(roots):
    """SIGTERM, then SIGKILL after a grace period, to every process under the roots; returns those still running."""
    found = processes_under(roots)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not found:
            break
        signal_processes(found, sig)
        deadline = time.time() + KILL_WAIT_S
        while found and time.time() < deadline:
            time.sleep(0.1)
            running = {row["pid"] for row in process_table() if not row["stat"].startswith("Z")}
            found = [p for p in found if p["pid"] in running]
    return processes_under(roots)


def sleep_until(wake):
    while (left := wake - time.time()) > 0:
        time.sleep(min(left, 60))


def clock(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def record_changes(run, manifest):
    if not manifest.get("base_tree"):
        files = [os.path.relpath(os.path.join(d, f), run["work"]) for d, _, fs in os.walk(run["work"]) for f in fs]
        run["changed_files"] = sorted(files)
        return
    tree = snapshot_tree(run["work"])
    patch = os.path.join(run["dir"], "changes.patch")
    with open(patch, "w") as f:
        f.write(git(run["work"], "diff", "--binary", manifest["base_tree"], tree, raw=True))
    names = git(run["work"], "diff", "--name-status", manifest["base_tree"], tree)
    run["changed_files"] = names.splitlines() if names else []
    run["patch"] = patch if names else None


def execute(run, prompt, manifest, timeout, hidden):
    agent, model, effort = run["agent"], run["model"], run["effort"]
    log_path = os.path.join(run["dir"], "transcript.jsonl")
    err_path = os.path.join(run["dir"], "stderr.log")
    result_path = os.path.join(run["dir"], "result.md")
    run.update(result=result_path, transcript=log_path, stderr=err_path)
    env = {**os.environ, "HOME": manifest["shadow_home"]} if agent == "claude" and manifest.get("shadow_home") else None
    if manifest.get("clean_room"):
        env = {k: v for k, v in (env or os.environ).items() if k != "AUTORUN_RUN"}
        env["AUTORUN_BOUNDARY_PID"] = str(os.getpid())
    print(f"started  {run['label']}", flush=True)
    start = time.time()
    session, waits = None, []
    while True:
        offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        cmd = command(agent, model, effort, run["work"], result_path, hidden, session)
        run.pop("agent_error", None)
        with open(log_path, "a") as out, open(err_path, "a") as err, \
                subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True, cwd=run["work"], env=env, start_new_session=True) as proc:
            try:
                proc.communicate(prompt, timeout=timeout)
                code, timed_out = proc.returncode, False
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
            finally:
                kill_group(proc.pid)
        session, is_error, resume = collect(agent, run, log_path, result_path)
        ok = code == 0 and not is_error and os.path.exists(result_path) and os.path.getsize(result_path) > 0
        reset = None if ok or timed_out else limit_reset(agent, read_events(log_path, offset), time.time())
        if reset is not None:
            record_limit(agent, reset, f"salvo run {run['label']} hit the {agent} usage limit")
        if reset is None or len(waits) == LIMIT_RESUMES or reset - time.time() > MAX_LIMIT_WAIT_S:
            break
        wake = max(reset, time.time()) + RESET_MARGIN_S
        print(f"waiting  {run['label']} for its usage limit to reset, resuming at {clock(wake)}", flush=True)
        asleep = time.time()
        sleep_until(wake)
        waits.append({"reset": clock(reset), "waited_s": round(time.time() - asleep)})
        prompt = CONTINUE_PROMPT if session else prompt
    run["duration_s"] = round(time.time() - start)
    if waits:
        run["limit_waits"] = waits
    run.update(session_id=session, resume=resume if session else None)
    record_changes(run, manifest)
    if timed_out:
        run["error"] = f"timed out after {timeout}s"
    elif not ok:
        with open(err_path, errors="ignore") as f:
            tail = [line for line in f.read().splitlines() if line.strip()][-5:]
        run["error"] = run.pop("agent_error", None) or "\n".join(tail) or f"exit code {code}"
        if reset is not None:
            why = "more than 24 hours away" if reset - time.time() > MAX_LIMIT_WAIT_S else f"gave up after {LIMIT_RESUMES} resumes"
            run["error"] += f" (usage limit resets at {clock(reset)}; not resumed: {why})"
    run["ok"] = ok
    print(f"finished {run['label']} {'ok' if ok else 'FAILED'} in {run['duration_s']}s", flush=True)
    return run


def run_salvo(args):
    prompt_task = sys.stdin.read().strip()
    if not prompt_task:
        sys.exit("task text is empty; pipe it on stdin")
    unsupported = [s for s in args.specs if not re.fullmatch(r"[^:\s]+:[^:\s]+(:[^:\s]+)?", s) or s.partition(":")[0] not in AGENTS]
    if unsupported:
        sys.exit(f"unsupported specs {unsupported}; expected agent:model[:effort] with agent in {AGENTS}")
    out = os.path.abspath(args.out)
    if os.path.exists(out):
        sys.exit(f"{out} already exists; pick another --out or clean it first")
    source = os.getcwd()
    os.makedirs(out)
    with open(os.path.join(out, "task.md"), "w") as f:
        f.write(prompt_task + "\n")

    manifest = {"status": "running", "source": source, "repo": None, "base_tree": None, "shadow_home": None,
                "clean_room": args.clean_room, "runs": []}
    if args.hide_skill and any(spec.startswith("claude:") for spec in args.specs):
        manifest["shadow_root"] = os.path.join("/tmp", secrets.token_hex(4))
        manifest["shadow_home"] = build_shadow_home(manifest["shadow_root"], set(args.hide_skill))
    in_git = git(source, "rev-parse", "--is-inside-work-tree", check=False) == "true"
    if in_git:
        manifest["repo"] = git(source, "rev-parse", "--show-toplevel")
        manifest["base_tree"] = snapshot_tree(source)
        parent = git(source, "rev-parse", "--verify", "-q", "HEAD", check=False)
        if parent and git(source, "rev-parse", "HEAD^{tree}") == manifest["base_tree"]:
            base = parent
        else:
            base = git(source, "commit-tree", manifest["base_tree"], *(["-p", parent] if parent else []), "-m", "WIP")
        branch = git(source, "branch", "--show-current", check=False) or "main"

    for n, spec in enumerate(args.specs, 1):
        agent, _, rest = spec.partition(":")
        model, _, effort = rest.partition(":")
        run = {"spec": spec, "agent": agent, "model": model, "effort": effort or None, "label": label(n, spec)}
        run["dir"] = os.path.join(out, run["label"])
        os.makedirs(run["dir"])
        if args.clean_room:
            run["workspace_root"] = os.path.join("/tmp", secrets.token_hex(4))
            checkout = os.path.join(run["workspace_root"], os.path.basename(manifest["repo"] or source))
        else:
            checkout = os.path.join(run["dir"], "work")
        run["work"] = checkout
        if in_git and args.clean_room:
            # A standalone clone, unlike a worktree, cannot list its sibling workspaces.
            git(manifest["repo"], "clone", "-q", manifest["repo"], checkout)
            git(checkout, "checkout", "-q", "-B", branch, base)
            for ref in git(manifest["repo"], "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines():
                if ref != branch:
                    git(checkout, "branch", "-f", ref, f"origin/{ref}")
            git(checkout, "remote", "remove", "origin")
            git(checkout, "reflog", "expire", "--expire=now", "--all")
            run["work"] = os.path.normpath(os.path.join(checkout, os.path.relpath(source, manifest["repo"])))
        elif in_git:
            git(manifest["repo"], "worktree", "add", "--detach", checkout, base)
            run["work"] = os.path.normpath(os.path.join(checkout, os.path.relpath(source, manifest["repo"])))
        else:
            os.makedirs(checkout)
        run["checkout"] = checkout
        manifest["runs"].append(run)
    manifest_path = os.path.join(out, "salvo.json")

    def save():
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    save()
    footer = {(True, False): FOOTER_GIT, (False, False): FOOTER_PLAIN,
              (True, True): FOOTER_CLEAN_GIT, (False, True): FOOTER_CLEAN_PLAIN}[(in_git, args.clean_room)]

    def one(run):
        prompt = prompt_task + footer.format(work=run["work"], source=source) + FOOTER_COMMON
        try:
            return execute(run, prompt, manifest, args.timeout, args.hide_skill)
        except Exception as e:
            run.update(ok=False, error=f"{type(e).__name__}: {e}")
            return run

    with ThreadPoolExecutor(max_workers=len(manifest["runs"])) as pool:
        list(pool.map(one, manifest["runs"]))
    manifest["status"] = "done"
    save()
    print(json.dumps(manifest, indent=2))
    sys.exit(0 if all(r.get("ok") for r in manifest["runs"]) else 1)


def clean(args):
    out = os.path.abspath(args.dir)
    manifest_path = os.path.join(out, "salvo.json")
    if not os.path.exists(manifest_path):
        sys.exit(f"{manifest_path} not found; not a salvo run directory")
    with open(manifest_path) as f:
        manifest = json.load(f)
    places = [out, *(r.get("workspace_root") for r in manifest["runs"]), *(r["checkout"] for r in manifest["runs"]), manifest.get("shadow_root")]
    survivors = stop_processes_under(places)
    if survivors:
        lines = "\n".join(f"  pid {p['pid']} ppid {p['ppid']} pgid {p['pgid']} cwd {p.get('cwd') or '-'}  {p['command'][:160]}" for p in survivors)
        sys.exit(f"not removed: {len(survivors)} process(es) still run from the workspaces, so deleting them would hide the processes\n{lines}\n"
                 "Stop them, then run clean again.")
    if manifest.get("repo"):
        for run in manifest["runs"]:
            git(manifest["repo"], "worktree", "remove", "--force", run["checkout"], check=False)
        git(manifest["repo"], "worktree", "prune", check=False)
    for path in [r.get("workspace_root") for r in manifest["runs"]] + [manifest.get("shadow_root")]:
        if path:
            shutil.rmtree(path, ignore_errors=True)
    shutil.rmtree(out)
    print(f"removed {out}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--timeout", type=int, default=None, help="seconds per run")
    p_run.add_argument("--clean-room", action="store_true", help="hide the orchestration from the runs")
    p_run.add_argument("--hide-skill", action="append", default=[], metavar="NAME", help="hide the user-level installs of this skill")
    p_run.add_argument("specs", nargs="+")
    p_clean = sub.add_parser("clean")
    p_clean.add_argument("dir")
    args = parser.parse_args()
    run_salvo(args) if args.cmd == "run" else clean(args)


if __name__ == "__main__":
    main()
