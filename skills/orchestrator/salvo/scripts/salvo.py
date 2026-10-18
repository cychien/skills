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
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import tomllib
import time
from concurrent.futures import ThreadPoolExecutor

AGENTS = ("claude", "codex")
# Byproducts of running code; excluded even when the repo forgets to ignore them.
ARTIFACTS = ["__pycache__", "*.pyc", "node_modules", ".DS_Store", ".pytest_cache", ".venv"]

FOOTER_GIT = """
---
Your working directory is {work}, a private copy of {source} in its current state. Edit it freely; nothing you do there touches the original."""
FOOTER_PLAIN = """
---
Your working directory is {work}. It starts empty. Read anything you need from {source}, but write files only inside your working directory."""
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


def command(agent, model, effort, work, result_path, hidden):
    if agent == "claude":
        cmd = ["claude", "-p", "--model", model, "--permission-mode", "bypassPermissions",
               "--output-format", "stream-json", "--verbose"]
        return cmd + (["--effort", effort] if effort else [])
    cmd = ["codex", "exec", "--skip-git-repo-check", "-C", work, "-m", model,
           "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
           "--json", "-o", result_path]
    cmd += codex_skill_overrides(hidden) if hidden else []
    return cmd + (["-c", f"model_reasoning_effort={effort}"] if effort else []) + ["-"]


def read_events(log_path):
    events = []
    with open(log_path, errors="ignore") as f:
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
    return session, False, f"codex resume {session}"


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
    cmd = command(agent, model, effort, run["work"], result_path, hidden)
    env = {**os.environ, "HOME": manifest["shadow_home"]} if agent == "claude" and manifest.get("shadow_home") else None
    if manifest.get("clean_room"):
        env = {k: v for k, v in (env or os.environ).items() if k != "AUTORUN_RUN"}
        env["AUTORUN_BOUNDARY_PID"] = str(os.getpid())
    print(f"started  {run['label']}", flush=True)
    start = time.time()
    try:
        with open(log_path, "w") as out, open(err_path, "w") as err:
            r = subprocess.run(cmd, input=prompt, stdout=out, stderr=err, text=True, cwd=run["work"], timeout=timeout, env=env)
        code, timed_out = r.returncode, False
    except subprocess.TimeoutExpired:
        code, timed_out = None, True
    run["duration_s"] = round(time.time() - start)
    session, is_error, resume = collect(agent, run, log_path, result_path)
    run.update(session_id=session, resume=resume if session else None)
    record_changes(run, manifest)
    ok = code == 0 and not is_error and os.path.exists(result_path) and os.path.getsize(result_path) > 0
    if timed_out:
        run["error"] = f"timed out after {timeout}s"
    elif not ok:
        tail = [line for line in open(err_path, errors="ignore").read().splitlines() if line.strip()][-5:]
        run["error"] = run.pop("agent_error", None) or "\n".join(tail) or f"exit code {code}"
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
    manifest = json.load(open(manifest_path))
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
