#!/usr/bin/env python3
"""Hard checks for the verify skill. Each subcommand exits 0 only when its rule holds.

usage: verify.py <command> [--dir DIR]
       verify.py units [<base>..<head>] [--test-cmd 'CMD {files}'] [--spec PATH ...] [--timeout SECONDS]
       verify.py rerun [--only ID ...] [--jobs N] [--timeout SECONDS] [--force] [-- ARGS ...]
       verify.py phases [<plan folder>]
       verify.py adopt <phase folder>
       verify.py leftovers [--kill] [--root DIR ...] [--running-since EPOCH]
       verify.py capacity [--native]

  where       print this branch's verification directory
  plan        the plan is complete: checks with every field, a Tier of e2e, unit, or walk on each (a perf check is
              always e2e), and a perf decision. A plan with any e2e or walk check needs a non-empty '## Drive contract'
              section: every name those checks drive (test ids, accessible names, routes, HTTP paths, CLI commands and
              flags, wire and event names, file paths), settled before code. At most 10 e2e checks per plan, with no
              override: keep the riskiest, move the rest to unit or drop them, or split the phase. An optional
              '## Sensitive paths' section lists paths or globs (auth, permissions, crypto) whose fixes need a fix
              review. Prints the count per tier.
  driver      a project verification skill is on main, or was committed before any product change
  freeze      record the plan's hash, the Drive contract and Sensitive paths included, before a verifier runs;
              --revision "<why; agreed by>" records a deliberate change to an already frozen plan
  lock        freeze the plan before any code exists: refuses while the working tree changes product files since the
              base (the commit `adopt` recorded, else the merge-base with main), leaving the project's verification
              skill and the adopted plan folder aside. Once locked, passes while the plan is unchanged or every change
              is a recorded revision, and fails for a plan first frozen after code existed.
  adopt       copy a phase's plan.md from a feature plan folder into this branch's verification directory and record
              HEAD as the phase's base, so `lock` measures code from where the phase starts.
  oracles     every oracle check has its expected value, computed from the spec after the freeze
  compare     every oracle check's observed value matches its expected value
  report      every plan check has a verdict backed by evidence on disk, and oracle verdicts match
              the comparison; the report's Head is HEAD or a commit with HEAD's tree (a regrouped history). A PASS
              is backed by its tier's evidence: e2e by its <id>.check.<ext> script and an <id>.rerun.log from a passing
              rerun after the freeze; unit by the last `units` result, after the freeze, passing, on HEAD's tree, with
              a spec that names the check id; walk by a screenshot or video in evidence/<id>/ written after the freeze.
              A '## Review' section in report.md, or review.md, written after the freeze, holds the code review's
              findings, each triaged, or 'none found'. In a git repository, review.md's 'Head:' line names the commit the
              reviewer read; when the diff from it to HEAD changes more than 200 lines or touches a path the plan's
              '## Sensitive paths' lists, review.md needs a '## Fix review' section, written after HEAD's commit, every
              finding triaged.
  decisions   the hillclimb decision log is well formed
  units       every spec file added or changed in <base>..<head> (default: <merge-base with main>..HEAD) fails on
              base plus that spec and passes at head. The runner is detected (vitest or jest from package.json,
              else pytest or unittest for .py files), or --test-cmd gives it, with {files} for the spec path.
              A spec file whose text contains "regression-guard" (in a title or a comment) guards behavior that
              already works: it must pass at head but may pass on base. Keep guards in their own spec files.
              Each run records units.json (per spec its verdict and the plan check ids its text names, so a test
              titled "U2: ..." proves unit check U2) and units.log in the verification directory, for `report`.
  rerun       run every saved <id>.check.<ext> script in the verification directory, passing ARGS (for example an
              instance id) to each; one PASS or FAIL line per check from its exit code, in id order, and a summary. Each
              script gets 300 seconds unless --timeout raises it. --jobs N runs up to N scripts at once, starting them one
              at a time: the next starts only once every running script has printed the line "verify: ready" (its
              instance is up; the line stays out of its log) and while `capacity` would pass, because the 1-minute load
              lags an instance start; a script that never prints it runs alone (one always runs, so a busy machine slows
              the run instead of stalling it). A watchdog samples the load every 3 seconds; once it stays above 1.0 x
              cores for 15 seconds, it stops the most recently started script with its process group and the detached
              processes it started, queues it again, prints it as REQUEUED with the load, and lowers the jobs to the
              scripts still running, never below one. A requeued run is neither a FAIL nor a fix attempt, and a script
              that finishes FAIL is never retried. The plan's perf checks always run alone after the rest, because
              concurrent instances skew every timing. Under --jobs, a file owned by a check that ran at the same time is not held against the
              other, because that check may be rewriting its own evidence, and a loss seen while checks ran side by
              side FAILs each of them with the names of the others, so `--only` finds the culprit. Exits 0 with a "no saved check scripts"
              line when there are none. A check script runs with zero arguments and provisions and tears down its own instance through
              the project driver (optional ARGS may reuse a running instance); it cleans only its own evidence
              (evidence/<id>/ or files starting with <id>), never a shared folder, and a script that deletes or empties
              another check's file FAILs; the report cites <id>.rerun.log, not the script, and the log's last line is
              "rerun: PASS" or "rerun: FAIL (<why>)". After a run where every script passes, rerun stamps
              rerun.stamp.json with HEAD's tree, a hash of the tracked working-tree diff, and a sha256 per check script
              and helper (.mjs .cjs .js .ts .py .sh). A later rerun with the same ARGS and an unchanged stamp prints one
              line and exits 0 without running; --force always runs. Any run deletes the stamp first, so a failed or
              interrupted run leaves none. --only ID (repeatable) runs just those checks, for grading a fix; it neither
              reads nor writes the stamp, so the full rerun still decides the gate. Once report.md marks a check FAIL,
              each --only run in which it still fails is one failed fix attempt, counted in fix-attempts.json; after 2,
              --only refuses it, and the full rerun reports it as left FAIL without failing, because it goes to the
              user or the backlog. A check script finds the repository from its working directory, never a hard-coded
              worktree path.
  phases      every phase of a feature plan has a sound verification plan: <plan folder>/phases/<phase>/plan.md for
              each phase, each passing the plan rules (the Drive contract and the 10 e2e cap among them), check ids unique across the whole feature (the feature
              plan's Acceptance list names each check by id), and, when <plan folder>/skeleton.patch exists, every
              phase holding a conformance check with a Skeleton field naming the skeleton files and symbols it implements. Given a plan folder, it records it in
              this branch's verification directory, so the bare command (a gate) checks the same folder later.
  leftovers   list processes still running from this run's places: the verification directory,
              ~/.cache/parlor-verify-hello, $PARLOR_VERIFY_HOME, $VERIFY_SCRATCHPAD (the agent scratchpad),
              /tmp/salvo-*, each --root, and, when their parent is init, anything under a worktree of this repo
              (the user's own shells and editors live there). A process counts when its working directory
              (deleted ones included) or its command line is under one of them. The caller and its ancestors never
              count. --running-since EPOCH says a delegate that is still running began then (guard passes it before a
              spawn): a process started since may be that delegate's, so it is listed as in use by a running agent and
              neither counted nor killed. Exits 1 while any remain and 2 when the scan itself cannot run. --kill sends
              SIGTERM to each process group, then SIGKILL to survivors, and rescans. When nothing remains but the
              1-minute load exceeds the core count, it also lists the busiest processes and flags those whose parent is init as
              likely leftovers (the exit code is unaffected).
  capacity    the machine has room for another heavy run: exits 0 when the 1-minute load is below ratio x cores
              (ratio 0.7, $VERIFY_MAX_LOAD_RATIO overrides) and no native app build is running, else exits 1. Native
              builds are xcodebuild, tauri build, cargo build, cap run, cap sync and gradle in the process table;
              without --native a running one is only reported, with --native it also refuses. Prints one line with
              load, cores, threshold and native builds running (pids); a refusal adds the busiest processes.

The verification directory is ~/.agents/verify/<repo>-<clone hash>/<branch>/, so two clones of one repo never share it ($VERIFY_HOME overrides
the root, --dir overrides the whole path). It holds plan.md, plan.lock, report.md, review.md,
decision.tsv, units.json, fix-attempts.json, and the evidence files. An oracle check <id> also has <id>.expected.json, written by an
agent that read only the spec and the seed data, and <id>.observed.json, read from the running app.
"""
import argparse
import collections
import contextlib
import datetime
import fnmatch
import glob
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

CHECK_FIELDS = ("Scenario", "Surface", "Evidence", "Pass")
PERF_FIELDS = ("Path", "Metric", "Probe", "Baseline", "Rule")
ORACLE_FIELDS = ("Seed", "Shape")
FLOAT_SLACK = 1e-9
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")
DECISION_HEADER = ["id", "hypothesis", "change", "before", "after", "delta", "gate", "verdict", "note"]
DECISION_VERDICTS = ("kept", "reverted")
DRIVER_DIRS = (".agents/skills/verify-", ".claude/skills/verify-")
FIELD = re.compile(r"^- ([A-Z][a-z]+):\s*(.*)$")
HEADING = re.compile(r"^### (\S+)\. \S")
PLACEHOLDER = re.compile(r"<[^<>\n]* [^<>\n]*>")
NA = re.compile(r"^n/a:\s*(.*)$")
HEADER_FIELD = re.compile(r"^(Head|Main|Author|Verifier):\s*(.*)$", re.M)
MIN_REASON = 10
TRIAGE = re.compile(r"\bTriage:\s*(fixed|new check|follow-up|pre-existing|dismissed)\b", re.I)
TIERS = ("e2e", "unit", "walk")
TIER_HELP = ("write e2e (isolation, permissions, revocation, wire compatibility, perf, or a cross-surface flow: a script the "
             "verifier writes, run on the real app), unit (logic: a spec the executor writes, graded by `verify.py units`), or "
             "walk (UI look and interaction: walked once on the real app, saved as a screenshot or video)")
MAX_E2E = 10
DRIVEN_TIERS = ("e2e", "walk")
CONTRACT = "Drive contract"
SENSITIVE = "Sensitive paths"
FIX_REVIEW = "Fix review"
FIX_REVIEW_LINES = 200
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm"}


SPEC_FILE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|[^/]*_spec\.rb|[^/]*Tests?\.(swift|kt|java))$")
GUARD_MARK = "regression-guard"
CHECK_SCRIPT = re.compile(r"^(.+)\.check\.[^.]+$")
SCRIPT_RUNNERS = {".py": [sys.executable], ".sh": ["bash"], ".js": ["node"], ".mjs": ["node"], ".ts": ["npx", "tsx"]}
NODE_LOCKS = {"pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bunx", "bun.lockb": "bunx"}
DEPENDENCY_DIRS = {"node_modules", ".venv", "venv"}
SCRIPT_TIMEOUT = 900
RERUN_TIMEOUT = 300
RERUN_STAMP = "rerun.stamp.json"
RERUN_PASS = "rerun: PASS"
FIX_ATTEMPTS = 2
FIX_LEDGER = "fix-attempts.json"
UNITS_RECORD = "units.json"
UNITS_LOG = "units.log"
REVIEW = "review.md"
HELPER_SUFFIXES = {".mjs", ".cjs", ".js", ".ts", ".py", ".sh"}
EVIDENCE_DIR = "evidence"
LISTED_LOSSES = 5
LOAD_RATIO = 0.7
NATIVE_BUILDS = {
    "xcodebuild": re.compile(r"(?:^|/)xcodebuild(?:\s|$)"),
    "tauri build": re.compile(r"\btauri build\b"),
    "cargo build": re.compile(r"(?:^|/)cargo build\b"),
    "cap run/sync": re.compile(r"\bcap (?:run|sync)\b"),
    "gradle": re.compile(r"(?:^|/)gradlew?(?:\s|$)|org\.gradle\.(?:wrapper\.GradleWrapperMain|launcher\.GradleMain)"),
}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
GLOB_MAGIC = re.compile(r"[*?\[]")
KILL_WAIT_S = 3.0
ADMIT_POLL_S = 1.0
READY_LINE = "verify: ready"
OVERLOAD_RATIO = 1.0
OVERLOAD_S = 15.0
WATCH_POLL_S = 3.0
# ps rounds elapsed time to the second, so a start can read up to a second early.
ELAPSED_SLACK_S = 1.0
ELAPSED = re.compile(r"^(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)$")
TOP_CPU = 5
SALVO_GLOBS = ("/tmp/salvo-*", "/private/tmp/salvo-*")
# A scratch tree borrows the checkout's installed dependencies through symlinks, which pnpm 11's pre-run deps check rejects.
SCRATCH_ENV = {"pnpm_config_verify_deps_before_run": "false"}


class Failed(Exception):
    code = 1


class CannotScan(Failed):
    code = 2


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise Failed(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.rstrip("\n")


def tree_of(rev):
    try:
        return git("rev-parse", "--verify", "-q", f"{rev}^{{tree}}")
    except Failed:
        return None


def verification_dir(override):
    if override:
        return pathlib.Path(override).expanduser()
    common = pathlib.Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    name = common.parent.name if common.name == ".git" else common.name.removesuffix(".git")
    repo = f"{name}-{hashlib.sha256(str(common).encode()).hexdigest()[:8]}"
    branch = git("rev-parse", "--abbrev-ref", "HEAD").replace("/", "-")
    root = pathlib.Path(os.environ.get("VERIFY_HOME") or pathlib.Path.home() / ".agents" / "verify")
    return root / repo / branch


def read(path, what):
    if not path.is_file():
        raise Failed(f"no {what} at {path}")
    return path.read_text()


def sections(lines):
    found, current = {}, None
    for number, line in enumerate(lines, 1):
        if line.startswith("## "):
            current = line[3:].strip()
            found[current] = []
        elif current is not None:
            found[current].append((number, line))
    return found


def entries(body):
    preamble, found, current = [], [], None
    for number, line in body:
        if line.startswith("### "):
            current = {"line": number, "heading": line, "fields": {}}
            found.append(current)
        elif current is None:
            preamble.append((number, line))
        elif m := FIELD.match(line):
            current["fields"][m.group(1)] = (number, m.group(2).strip())
    return preamble, found


def entry_id(entry):
    m = HEADING.match(entry["heading"])
    return m.group(1) if m else None


def check_entry(entry, required, problems):
    line = entry["line"]
    if not entry_id(entry):
        problems.append(f"{line}: heading must read '### <id>. <title>'")
    for name in required:
        if name not in entry["fields"]:
            problems.append(f"{line}: missing '- {name}:'")
            continue
        number, value = entry["fields"][name]
        if not value:
            problems.append(f"{number}: {name} is empty")
        elif name != "Shape" and PLACEHOLDER.search(value):
            problems.append(f"{number}: {name} still holds a template placeholder")


def check_perf_entry(entry, problems):
    baseline = entry["fields"].get("Baseline")
    rule = entry["fields"].get("Rule")
    if baseline and baseline[1]:
        number, value = baseline
        if value != "main" and not re.match(r"^none:\s*\S", value):
            problems.append(f"{number}: Baseline must be 'main' or 'none: <why>'")
        elif value.startswith("none") and rule and re.search(r"\bmain\b", rule[1]):
            problems.append(f"{rule[0]}: with no baseline, Rule must be an absolute budget, not a comparison with main")
    if rule and rule[1] and not re.search(r"\d", rule[1]):
        problems.append(f"{rule[0]}: Rule must name the number that fails")


def check_oracle(entry, problems, oracles):
    fields = entry["fields"]
    oracle = fields.get("Oracle")
    if oracle is None:
        problems.append(f"{entry['line']}: missing '- Oracle:'. Give the spec's definition of the value this check computes "
                        "from data, with '- Seed:' and '- Shape:', or write '- Oracle: n/a: <why no value is computed>'")
        return
    number, value = oracle
    if m := NA.match(value):
        if len(m.group(1)) < MIN_REASON:
            problems.append(f"{number}: Oracle n/a needs a reason the user can judge")
        return
    check_entry(entry, ORACLE_FIELDS, problems)
    tolerance = fields.get("Tolerance")
    try:
        slack = float(tolerance[1]) if tolerance else 0.0
    except ValueError:
        problems.append(f"{tolerance[0]}: Tolerance must be a number")
        slack = 0.0
    if check_id := entry_id(entry):
        oracles[check_id] = slack


def check_tier(entry, problems, tiers, oracles):
    field = entry["fields"].get("Tier")
    if field is None:
        problems.append(f"{entry['line']}: missing '- Tier:'; {TIER_HELP}")
        return
    number, value = field
    if value not in TIERS:
        problems.append(f"{number}: Tier must be e2e, unit, or walk, not {value!r}; {TIER_HELP}")
        return
    check_id = entry_id(entry)
    if value == "unit" and check_id in oracles:
        problems.append(f"{number}: an oracle check reads its value from the running app, so its Tier is e2e or walk")
    if check_id:
        tiers[check_id] = value


def lint_plan(text):
    """Return (problems, check ids, {oracle check id: tolerance}, {check id: tier}) for a plan's text."""
    problems, ids, oracles, tiers = [], [], {}, {}
    found = sections(text.splitlines())
    if "Checks" not in found:
        problems.append("1: missing '## Checks' section")
    else:
        _, checks = entries(found["Checks"])
        if not checks:
            problems.append("1: '## Checks' has no checks")
        for entry in checks:
            check_entry(entry, CHECK_FIELDS, problems)
            check_oracle(entry, problems, oracles)
            check_tier(entry, problems, tiers, oracles)
            ids.append((entry_id(entry), entry["line"]))
    if "Perf" not in found:
        problems.append("1: missing '## Perf' section: add perf checks, or 'n/a: <reason>'")
    else:
        preamble, perf = entries(found["Perf"])
        na = [(n, m.group(1)) for n, line in preamble if (m := NA.match(line.strip()))]
        if perf and na:
            problems.append(f"{na[0][0]}: Perf has both checks and n/a; keep one")
        elif not perf and not na:
            problems.append("1: '## Perf' needs perf checks, or 'n/a: <reason>'")
        elif na and len(na[0][1]) < MIN_REASON:
            problems.append(f"{na[0][0]}: n/a needs a reason the user can judge")
        for entry in perf:
            check_entry(entry, PERF_FIELDS, problems)
            check_perf_entry(entry, problems)
            tier = entry["fields"].get("Tier")
            if tier and tier[1] != "e2e":
                problems.append(f"{tier[0]}: a perf check is always e2e: a script that measures and compares against its Rule")
            if check_id := entry_id(entry):
                tiers[check_id] = "e2e"
            ids.append((check_id, entry["line"]))
    seen = {}
    for check_id, line in ids:
        if check_id and check_id in seen:
            problems.append(f"{line}: id {check_id!r} is used more than once")
        seen.setdefault(check_id, line)
    problems += contract_problems(found, tiers) + e2e_cap_problems(tiers)
    problems += [f"{n}: {SENSITIVE} still holds a template placeholder" for n, line in found.get(SENSITIVE, []) if PLACEHOLDER.search(line)]
    return problems, [i for i, _ in ids if i], oracles, tiers


def contract_problems(found, tiers):
    driven = [i for i, t in tiers.items() if t in DRIVEN_TIERS]
    lines = [(n, line) for n, line in found.get(CONTRACT, []) if line.strip()]
    problems = [f"{n}: {CONTRACT} still holds a template placeholder" for n, line in lines if PLACEHOLDER.search(line)]
    if driven and not lines:
        problems.append(f"1: {', '.join(driven)} {'is an e2e or walk check' if len(driven) == 1 else 'are e2e or walk checks'}, "
                        f"but the plan has no '## {CONTRACT}' listing what they drive. Settle every name before any code: DOM "
                        "test ids and accessible names, routes and HTTP paths, CLI commands and flags, wire and event names, "
                        "and the file paths the checks read")
    return problems


def e2e_cap_problems(tiers):
    e2e = [i for i, t in tiers.items() if t == "e2e"]
    if len(e2e) <= MAX_E2E:
        return []
    return [f"1: {len(e2e)} e2e checks ({', '.join(e2e)}), more than {MAX_E2E}. Keep the {MAX_E2E} most important, the "
            "riskiest and costliest-to-break behavior, and move the rest to the unit tier or drop them, or split the phase"]


def sensitive_paths(text):
    found = sections(text.splitlines()).get(SENSITIVE, [])
    words = [line[2:].split(None, 1) for _, line in found if line.startswith(("- ", "* "))]
    return [w[0].strip("`,:") for w in words if w and not PLACEHOLDER.search(w[0])]


def is_sensitive(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) if GLOB_MAGIC.search(p) else under(path, p.rstrip("/")) for p in patterns)


def load_plan(directory):
    path = directory / "plan.md"
    text = read(path, "plan (write it from the verify skill's references/plan-template.md)")
    problems, ids, oracles, tiers = lint_plan(text)
    if problems:
        raise Failed("\n".join(f"{path}:{p}" for p in problems))
    return path, text, ids, oracles, tiers


def cmd_plan(directory, args):
    path, _, ids, oracles, tiers = load_plan(directory)
    counts = ", ".join(f"{t} {list(tiers.values()).count(t)}" for t in TIERS)
    return f"{path}: plan ok, {len(ids)} checks, {len(oracles)} oracle checks; tiers: {counts}"


def default_branch():
    for ref in ("refs/remotes/origin/HEAD",):
        try:
            return git("symbolic-ref", "--short", ref)
        except Failed:
            pass
    for name in ("origin/main", "main", "origin/master", "master"):
        try:
            git("rev-parse", "--verify", "--quiet", name)
            return name
        except Failed:
            continue
    raise Failed("cannot find the main branch to compare against")


def is_driver_path(path):
    return any(path.startswith(d) for d in DRIVER_DIRS)


def has_driver(rev):
    return any(is_driver_path(p) and p.endswith("/SKILL.md") for p in git("ls-tree", "-r", "--name-only", rev).splitlines())


def cmd_driver(directory, args):
    top = pathlib.Path(git("rev-parse", "--show-toplevel"))
    drivers = sorted(str(p.parent.relative_to(top)) for d in DRIVER_DIRS for p in top.glob(d + "*/SKILL.md"))
    if not drivers:
        raise Failed("no verification skill in this worktree (.agents/skills/verify-<app>/ or .claude/skills/verify-<app>/). "
                     "Run the create-verification-skill skill in a clean worktree off main, then base this branch on it.")
    base = default_branch()
    if has_driver(base):
        return f"driver ok: {', '.join(drivers)} is on {base}"
    if not has_driver("HEAD"):
        raise Failed("the verification skill is not committed. Commit it before any product change, so the history shows "
                     "it was built from the unchanged app.")
    for commit in git("rev-list", "--reverse", "--topo-order", f"{base}..HEAD").splitlines():
        files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", commit).splitlines()
        if any(not is_driver_path(f) for f in files):
            if not has_driver(f"{commit}^"):
                raise Failed(f"commit {commit[:12]} changed product files before any commit added the verification skill, "
                             "so the driver may have been fitted to the change. Build it from main first.")
            break
    return f"driver ok: {', '.join(drivers)} was committed before any product change"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def cmd_freeze(directory, args):
    _, text, _, _, _ = load_plan(directory)
    lock_path = directory / "plan.lock"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    if not lock_path.exists():
        lock_path.write_text(json.dumps({"sha": sha(text), "frozen_at": now, "frozen_ts": time.time(), "revisions": []}, indent=2) + "\n")
        return f"plan frozen at {now}"
    lock = json.loads(lock_path.read_text())
    if lock["sha"] == sha(text):
        return "plan unchanged since it was frozen"
    if not args.revision or len(args.revision.strip()) < MIN_REASON:
        raise Failed("the plan changed after it was frozen. A check or budget changes only when the user agrees it was wrong "
                     "(a looser perf budget also needs vetted evidence and a countersign). Record it with "
                     "--revision \"<what changed and why; agreed by whom>\", and list it in the report.")
    lock["revisions"].append({"at": now, "from": lock["sha"], "to": sha(text), "why": args.revision.strip()})
    lock["sha"] = sha(text)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    return f"revision recorded: {args.revision.strip()}"


BASE_RECORD = "base.json"


def cmd_adopt(directory, args):
    if len(args.rest) != 1:
        raise Failed("adopt takes one <phase folder> from the feature plan")
    folder = pathlib.Path(args.rest[0]).expanduser().resolve()
    text = read(folder / "plan.md", "phase plan")
    problems, ids, _, _ = lint_plan(text)
    if problems:
        raise Failed("\n".join(f"{folder / 'plan.md'}:{p}" for p in problems))
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "plan.md"
    if target.exists() and target.read_text() != text:
        raise Failed(f"{target} already holds a different plan; this branch adopted another phase or edited it")
    target.write_text(text)
    head = git("rev-parse", "HEAD")
    (directory / BASE_RECORD).write_text(json.dumps({"base": head, "plan": str(folder.parent.parent)}, indent=2) + "\n")
    return f"adopted {folder.name}: {len(ids)} checks, base {head[:12]}"


def product_changes(base, skip):
    top = pathlib.Path(git("rev-parse", "--show-toplevel"))
    names = set(git("diff", "--name-only", base).splitlines()) | set(git("ls-files", "--others", "--exclude-standard").splitlines())
    skipped = [str(pathlib.Path(s).resolve().relative_to(top.resolve())) for s in skip if under(str(pathlib.Path(s).resolve()), str(top.resolve()))]
    return sorted(n for n in names if n and not n.startswith(DRIVER_DIRS) and not any(n == d or n.startswith(d + "/") for d in skipped))


def cmd_lock(directory, args):
    _, text, _, _, _ = load_plan(directory)
    lock_path = directory / "plan.lock"
    if lock_path.exists():
        if not json.loads(lock_path.read_text()).get("before_code"):
            raise Failed("the plan was frozen after code existed, so it cannot show it was written first. "
                         "Write the plan before the code on the next change.")
        frozen_lock(directory, text)
        return "plan locked before code, unchanged since or changed only by recorded revisions"
    record = json.loads((directory / BASE_RECORD).read_text()) if (directory / BASE_RECORD).is_file() else {}
    base = record.get("base") or git("merge-base", default_branch(), "HEAD")
    changed = product_changes(base, [record["plan"]] if record.get("plan") else [])
    if changed:
        shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
        raise Failed(f"product files already changed since {base[:12]}: {shown}. Lock the plan before any code: "
                     "stash or move the change aside, lock, then bring it back.")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    lock_path.write_text(json.dumps({"sha": sha(text), "frozen_at": now, "frozen_ts": time.time(), "revisions": [],
                                     "before_code": True, "base": base}, indent=2) + "\n")
    return f"plan locked before code at {now}, base {base[:12]}"


def frozen_lock(directory, text):
    lock_path = directory / "plan.lock"
    if not lock_path.exists():
        raise Failed("the plan was never frozen. Run `verify.py freeze` before a verifier runs, so later edits to it show.")
    lock = json.loads(lock_path.read_text())
    if lock["sha"] != sha(text):
        raise Failed("the plan changed after it was frozen. Record the change with `verify.py freeze --revision \"...\"`, "
                     "or restore the frozen plan.")
    return lock


def differences(expected, observed, slack, path="$"):
    if isinstance(expected, bool) or isinstance(observed, bool):
        return [] if expected == observed else [f"{path}: expected {expected!r}, observed {observed!r}"]
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        limit = max(slack, FLOAT_SLACK * max(abs(expected), abs(observed), 1))
        return [] if abs(expected - observed) <= limit else [f"{path}: expected {expected!r}, observed {observed!r}"]
    if isinstance(expected, dict) and isinstance(observed, dict):
        found = [f"{path}.{k}: missing from observed" for k in expected if k not in observed]
        found += [f"{path}.{k}: not in expected" for k in observed if k not in expected]
        for k in expected:
            if k in observed:
                found += differences(expected[k], observed[k], slack, f"{path}.{k}")
        return found
    if isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            return [f"{path}: expected {len(expected)} entries, observed {len(observed)}"]
        return [d for i, (e, o) in enumerate(zip(expected, observed)) for d in differences(e, o, slack, f"{path}[{i}]")]
    return [] if expected == observed else [f"{path}: expected {expected!r}, observed {observed!r}"]


def load_json(path):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise Failed(f"{path} is not valid JSON: {e}")


def compare_oracle(directory, check_id, slack, lock):
    """Problems with one oracle check's files, then the value differences, if both files are sound."""
    expected, observed = directory / f"{check_id}.expected.json", directory / f"{check_id}.observed.json"
    problems = []
    if not expected.is_file():
        problems.append(f"{check_id}: no {expected.name}; copy it from the oracle's workspace")
    elif expected.stat().st_mtime < lock["frozen_ts"]:
        problems.append(f"{check_id}: {expected.name} predates the frozen plan")
    if not observed.is_file():
        problems.append(f"{check_id}: no {observed.name}; the verifier reads it from the running app")
    elif observed.stat().st_mtime < lock["frozen_ts"]:
        problems.append(f"{check_id}: {observed.name} predates the frozen plan")
    if problems:
        return problems, []
    return [], differences(load_json(expected), load_json(observed), slack)


def cmd_oracles(directory, args):
    _, text, _, oracles, _ = load_plan(directory)
    lock = frozen_lock(directory, text)
    problems = []
    for check_id in oracles:
        expected = directory / f"{check_id}.expected.json"
        if not expected.is_file():
            problems.append(f"{check_id}: no {expected.name}")
        elif expected.stat().st_mtime < lock["frozen_ts"]:
            problems.append(f"{check_id}: {expected.name} predates the frozen plan")
        else:
            load_json(expected)
    if problems:
        raise Failed("\n".join(problems))
    return f"oracles ok: {len(oracles)} expected values computed after the freeze"


def cmd_compare(directory, args):
    _, text, _, oracles, _ = load_plan(directory)
    lock = frozen_lock(directory, text)
    lines, failed = [], False
    for check_id, slack in oracles.items():
        problems, diffs = compare_oracle(directory, check_id, slack, lock)
        failed |= bool(problems or diffs)
        lines += problems or ([f"{check_id}: differs"] + [f"  {d}" for d in diffs[:20]] if diffs else [f"{check_id}: match"])
    if failed:
        raise Failed("\n".join(lines))
    return "\n".join(lines) or "no oracle checks"


def table_rows(text):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|") or re.match(r"^\|\s*:?-", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].lower() == "check":
            continue
        rows.append((number, cells))
    return rows


def split_cell(text):
    """Split an Evidence cell on commas outside braces."""
    parts, depth, last = [], 0, 0
    for i, c in enumerate(text):
        depth += (c == "{") - (c == "}" and depth > 0)
        if c == "," and depth == 0:
            parts.append(text[last:i])
            last = i + 1
    return parts + [text[last:]]


def expand_braces(pattern):
    start = pattern.find("{")
    depth, parts, last = 0, [], start + 1
    for i in range(max(start, 0), len(pattern)):
        c = pattern[i]
        if c == "{":
            depth += 1
        elif c == "," and depth == 1:
            parts.append(pattern[last:i])
            last = i + 1
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                parts.append(pattern[last:i])
                head, tail = pattern[:start], pattern[i + 1:]
                return [x for part in parts for x in expand_braces(head + part + tail)]
    return [pattern]


def evidence_files(directory, pattern):
    """(matched paths, their non-empty files) for one evidence pattern, relative to the verification directory."""
    p = pathlib.Path(pattern).expanduser()
    full = str(p if p.is_absolute() else directory / p)
    if GLOB_MAGIC.search(pattern):
        matches = [pathlib.Path(m) for m in glob.glob(full, recursive=True)]
    else:
        matches = [pathlib.Path(full)] if os.path.exists(full) else []
    found = [f for m in matches for f in ([m] if m.is_file() else m.rglob("*")) if f.is_file() and f.stat().st_size]
    return matches, found


def evidence_problems(directory, check_id, spec, frozen_ts):
    """Problems with one Evidence entry: a file, a directory, or a glob or brace pattern, each needing non-empty files made after the freeze."""
    problems = []
    for pattern in expand_braces(spec):
        matches, found = evidence_files(directory, pattern)
        plain = not GLOB_MAGIC.search(pattern) and pattern == spec
        if found:
            if min(f.stat().st_mtime for f in found) >= frozen_ts:
                continue
            single = plain and matches[0].is_file()
            problems.append(f"evidence {pattern} {'predates' if single else 'holds files that predate'} the frozen plan; "
                            "freeze the plan before a verifier runs, then verify again")
        elif plain:
            problems.append(f"evidence {pattern} is " + ("an empty directory" if matches and matches[0].is_dir() else "missing or empty"))
        else:
            problems.append(f"{check_id} evidence {pattern} " + ("matches only empty files" if matches else "matches nothing"))
    return problems


def section(text, name):
    m = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def untriaged(body):
    findings = [line.strip() for line in body.splitlines() if re.match(r"^\s*[-*] ", line)]
    return [f"has no 'Triage: fixed | new check | follow-up | pre-existing | dismissed': {f[:80]}" for f in findings if not TRIAGE.search(f)]


def review_problems(directory, report, frozen_ts):
    """The code review: report.md's '## Review' section and review.md, written after the freeze, every finding triaged."""
    sources = [(directory / "report.md", section(report, "Review"))]
    if (directory / REVIEW).is_file():
        text = (directory / REVIEW).read_text()
        sources.append((directory / REVIEW, section(text, "Review") or text.strip()))
    found = [(path, body) for path, body in sources if body]
    if not found:
        return ["missing the code review: a '## Review' section in report.md or review.md with a fresh reviewer's findings, "
                "or 'none found'"]
    problems = []
    for path, body in found:
        problems += [f"review finding {p}" for p in untriaged(body)]
        if path.stat().st_mtime < frozen_ts:
            problems.append(f"the review in {path.name} predates the frozen plan; review the code that ships, after the freeze")
    return problems


def fix_review_problems(directory, plan_text):
    """The fixes made after the review: past FIX_REVIEW_LINES changed lines or on a sensitive path, they need a triaged fix review."""
    path = directory / REVIEW
    text = path.read_text() if path.is_file() else ""
    m = re.search(r"^Head:\s*(\S+)", text, re.M)
    if not m:
        return [f"{REVIEW} names no 'Head:' line; the reviewer writes the commit it read, so `report` can measure the fixes "
                "made after it"]
    reviewed = m.group(1)
    try:
        numstat = git("diff", "--numstat", "--no-renames", reviewed, "HEAD")
    except Failed:
        return [f"{REVIEW} reviewed Head {reviewed}, which is not a commit in this repository"]
    changed, count = [], 0
    for row in numstat.splitlines():
        added, deleted, name = row.split("\t", 2)
        count += sum(int(n) for n in (added, deleted) if n.isdigit())
        changed.append(name)
    touched = [n for n in changed if is_sensitive(n, sensitive_paths(plan_text))]
    reasons = ([f"change {count} lines, over {FIX_REVIEW_LINES}"] if count > FIX_REVIEW_LINES else []) + \
              ([f"touch the plan's {SENSITIVE} ({', '.join(touched[:5])})"] if touched else [])
    if not reasons:
        return []
    why = f"the fixes since the reviewed Head {reviewed[:12]} " + " and ".join(reasons)
    body = section(text, FIX_REVIEW)
    if not body:
        return [f"{why}, so they need a fix review: the reviewer reviews that diff once into a '## {FIX_REVIEW}' section of "
                f"{REVIEW}, and every finding is triaged"]
    problems = [f"fix review finding {p}" for p in untriaged(body)]
    if path.stat().st_mtime < int(git("log", "-1", "--format=%ct", "HEAD")):
        problems.append(f"the fix review in {REVIEW} predates the last fix commit; review the fix diff that ships")
    return problems


def load_units(directory):
    try:
        return json.loads((directory / UNITS_RECORD).read_text())
    except (OSError, ValueError):
        return None


def last_line(path):
    return path.read_text(errors="replace").rstrip("\n").rpartition("\n")[2]


def units_gap(check_id, frozen_ts, units):
    if not units:
        return "no `verify.py units` result is recorded; run it once the code lands"
    if units.get("at", 0) < frozen_ts:
        return "the recorded `verify.py units` result predates the frozen plan; run it again"
    if not units.get("passed"):
        return "the last `verify.py units` run failed; fix what it reports and run it again"
    head_tree = tree_of("HEAD")
    if head_tree and units.get("tree") != head_tree:
        return "the last `verify.py units` ran on another tree than HEAD; run it again on the code that ships"
    if not any(check_id in spec["checks"] and spec["verdict"] in ("ok", "guard") for spec in units.get("specs", {}).values()):
        return (f"no spec in the last `verify.py units` run names {check_id}; put the check id in the title of the test that "
                "proves it, then run units again")
    return None


def tier_gap(directory, check_id, tier, frozen_ts, scripts, units):
    """Why a PASS lacks the evidence its tier needs, or None."""
    if tier == "unit":
        return units_gap(check_id, frozen_ts, units)
    if tier == "e2e":
        log = directory / f"{check_id}.rerun.log"
        if check_id not in scripts:
            return (f"no {check_id}.check.<ext> script is saved; the verifier writes it from the plan and the driver, and "
                    "`verify.py rerun` grades it")
        if not log.is_file() or log.stat().st_mtime < frozen_ts:
            return f"{log.name} is missing or predates the frozen plan; run `verify.py rerun` after the freeze"
        if last_line(log) != RERUN_PASS:
            return f"{log.name} records a failing run; a PASS needs a passing `verify.py rerun`"
        return None
    folder = directory / EVIDENCE_DIR / check_id
    media = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES
             and p.stat().st_size and p.stat().st_mtime >= frozen_ts] if folder.is_dir() else []
    if not media:
        return (f"{EVIDENCE_DIR}/{check_id}/ holds no screenshot or video written after the freeze; walk it on the real app "
                "and save one there")
    return None


def cmd_report(directory, args):
    _, text, ids, oracles, tiers = load_plan(directory)
    lock = frozen_lock(directory, text)
    path = directory / "report.md"
    report = read(path, "report (write it from the verify skill's references/report-template.md)")
    problems = []
    header = dict(HEADER_FIELD.findall(report))
    for name in ("Head", "Main", "Author", "Verifier"):
        value = header.get(name, "").strip()
        if not value or PLACEHOLDER.search(value):
            problems.append(f"missing '{name}:' line")
    reported_head = header.get("Head", "").strip()
    try:
        current_head = git("rev-parse", "HEAD")
    except Failed:
        current_head = None
    same_tree = None
    if current_head and reported_head and not (len(reported_head) >= 7 and current_head.startswith(reported_head)):
        reported_tree = tree_of(reported_head)
        if reported_tree and reported_tree == tree_of("HEAD"):
            same_tree = f"Head {reported_head} has the same tree as HEAD {current_head[:12]}"
        else:
            problems.append(f"the report covers Head {reported_head}, but HEAD is now {current_head[:12]}; regrade the code that ships "
                            "with `verify.py rerun` and `verify.py units`, walk again each walk check the later commits touch, "
                            "then set Head")
    if header.get("Author", "").strip() and header.get("Author", "").strip() == header.get("Verifier", "").strip():
        problems.append("the Verifier is the Author; a fresh agent must produce the verdicts")
    problems += review_problems(directory, report, lock["frozen_ts"])
    if current_head:
        problems += fix_review_problems(directory, text)
    units = load_units(directory)
    scripts = {script_id(p) for p in check_scripts(directory)}
    rows = {}
    for number, cells in table_rows(report):
        if len(cells) < 4:
            problems.append(f"{number}: a row needs Check | Verdict | Evidence | Observed")
            continue
        rows.setdefault(cells[0], (number, cells))
    for check_id in ids:
        if check_id not in rows:
            problems.append(f"check {check_id} has no row")
            continue
        number, (_, verdict, evidence, observed, *_) = rows[check_id]
        if verdict not in VERDICTS:
            problems.append(f"{number}: verdict must be one of {', '.join(VERDICTS)}")
        files = [e.strip().strip("`") for e in split_cell(evidence) if e.strip()]
        if not files:
            problems.append(f"{number}: {check_id} names no evidence file")
        for f in files:
            problems += [f"{number}: {p}" for p in evidence_problems(directory, check_id, f, lock["frozen_ts"])]
        if check_id in oracles:
            file_problems, diffs = compare_oracle(directory, check_id, oracles[check_id], lock)
            problems += [f"{number}: {p}" for p in file_problems]
            if diffs and verdict == "PASS":
                problems.append(f"{number}: {check_id} is PASS, but its observed value differs from the oracle's: {diffs[0]}")
        if verdict == "PASS" and check_id in tiers:
            tier = tiers[check_id]
            gap = tier_gap(directory, check_id, tier, lock["frozen_ts"], scripts, units)
            if gap:
                problems.append(f"{number}: {check_id} is {'an' if tier == 'e2e' else 'a'} {tier} check marked PASS, but {gap}")
        if verdict == "FAIL" and not observed.lower().startswith(("defect:", "blocker:")):
            problems.append(f"{number}: {check_id} is FAIL; start its Observed cell with 'defect:' and the repro")
        if verdict == "INCONCLUSIVE" and not observed.lower().startswith("blocker:"):
            problems.append(f"{number}: {check_id} is INCONCLUSIVE; start its Observed cell with 'blocker:' and what stopped it")
    if problems:
        raise Failed("\n".join(f"{path}: {p}" for p in problems))
    revisions = "".join(f"\n  revision {r['at']}: {r['why']}" for r in lock["revisions"])
    return f"report ok: {len(ids)} checks have verdicts backed by evidence" + (f"\n  {same_tree}" if same_tree else "") + revisions


def cmd_decisions(directory, args):
    path = directory / "decision.tsv"
    lines = read(path, "decision log").splitlines()
    if not lines or lines[0].split("\t") != DECISION_HEADER:
        raise Failed(f"{path}: the header must be: " + "\t".join(DECISION_HEADER))
    rows = [line.split("\t") for line in lines[1:] if line.strip()]
    if not rows:
        raise Failed(f"{path}: no attempts logged")
    problems = []
    for number, row in enumerate(rows, 2):
        if len(row) != len(DECISION_HEADER):
            problems.append(f"{number}: expected {len(DECISION_HEADER)} tab-separated cells, found {len(row)}")
        elif row[7] not in DECISION_VERDICTS:
            problems.append(f"{number}: verdict must be kept or reverted")
    if problems:
        raise Failed("\n".join(f"{path}:{p}" for p in problems))
    kept = sum(1 for r in rows if r[7] == "kept")
    return f"decision log ok: {len(rows)} attempts, {kept} kept"


def check_scripts(directory):
    return sorted(p for p in directory.iterdir() if p.is_file() and CHECK_SCRIPT.match(p.name))


def script_command(path):
    if os.access(path, os.X_OK):
        return [str(path)]
    runner = SCRIPT_RUNNERS.get(path.suffix)
    return [*runner, str(path)] if runner else None


def helper_files(directory):
    skipped = {EVIDENCE_DIR, *DEPENDENCY_DIRS}
    return [p for p in directory.rglob("*")
            if p.is_file() and p.suffix in HELPER_SUFFIXES and not skipped & set(p.relative_to(directory).parts[:-1])]


def rerun_inputs(directory, scripts, rest, left):
    """What a passing rerun depends on, or None outside a git repository."""
    tree = tree_of("HEAD")
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True)
    if not tree or diff.returncode:
        return None
    files = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted({*scripts, *helper_files(directory)})}
    return {"args": rest, "tree": tree, "diff": hashlib.sha256(diff.stdout).hexdigest(), "files": files, "left": left}


def file_sizes(directory):
    sizes = {}
    for root, dirs, names in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in DEPENDENCY_DIRS]
        for name in names:
            path = pathlib.Path(root, name)
            with contextlib.suppress(OSError):
                sizes[path.relative_to(directory)] = path.stat().st_size
    return sizes


def owned_by(path, check_id):
    parts = path.parts
    if parts[0] == EVIDENCE_DIR and len(parts) > 1:
        parts = parts[1:]
    return parts[0].startswith(check_id)


def lost_files(before, after, owners):
    lost = sorted(str(p) for p, size in before.items() if size and not after.get(p) and not any(owned_by(p, o) for o in owners))
    if len(lost) > LISTED_LOSSES:
        lost = [*lost[:LISTED_LOSSES], f"and {len(lost) - LISTED_LOSSES} more"]
    return lost


def script_id(path):
    return CHECK_SCRIPT.match(path.name).group(1)


def only_scripts(scripts, wanted):
    by_id = {script_id(p): p for p in scripts}
    unknown = [i for i in wanted if i not in by_id]
    if unknown:
        raise Failed(f"no saved check script for {', '.join(unknown)}; saved: {', '.join(sorted(by_id)) or 'none'}")
    return [by_id[i] for i in dict.fromkeys(wanted)]


def reported_failures(directory):
    path = directory / "report.md"
    if not path.is_file():
        return set()
    return {cells[0] for _, cells in table_rows(path.read_text()) if len(cells) > 1 and cells[1] == "FAIL"}


def fix_attempts(directory):
    try:
        return json.loads((directory / FIX_LEDGER).read_text())
    except (OSError, ValueError):
        return {}


def run_check(directory, path, args, env, concurrent=set, run=None):
    """(verdict, detail) for one check script; its output and verdict go to <id>.rerun.log. concurrent() names the checks
    that ran beside it. run, when given, learns the script's pid and readiness, and a run the watchdog evicted is REQUEUED."""
    check_id = script_id(path)
    command = script_command(path)
    before = file_sizes(directory)
    output = ""
    hooks = {"on_start": lambda pid: run.update(pid=pid), "on_ready": run["ready"]} if run else {}
    if not command:
        verdict, detail = "FAIL", f"{path.name} is not executable and has no interpreter for {path.suffix}"
    else:
        try:
            r = run_in_group([*command, *args.rest], args.timeout, env=env, **hooks)
            output = (r.stdout + r.stderr).strip()
            verdict = "PASS" if r.returncode == 0 else "FAIL"
            detail = "" if verdict == "PASS" else f"exit {r.returncode}"
            if verdict == "FAIL" and output:
                detail += "\n" + "\n".join(f"    {line}" for line in output.splitlines()[-5:])
        except subprocess.TimeoutExpired:
            verdict, detail = "FAIL", f"timed out after {args.timeout}s"
    if run and run["evicted"]:
        return "REQUEUED", ""
    beside = sorted(concurrent())
    lost = lost_files(before, file_sizes(directory), {check_id, *beside})
    if lost:
        verdict = "FAIL"
        culprit = f"files that are not its own were deleted or emptied while it ran beside {', '.join(beside)}" if beside else \
            "deleted or emptied files that are not its own"
        detail = f"{culprit}: {', '.join(lost)}" + (f"\n{detail}" if detail else "")
    reason = detail.partition("\n")[0]
    (directory / f"{check_id}.rerun.log").write_text((output + "\n" if output else "") + f"rerun: {verdict}" + (f" ({reason})" if reason else "") + "\n")
    return verdict, detail


def run_checks(directory, scripts, args, env):
    """({check id: (verdict, detail, seconds)}, [requeue lines]). Under --jobs a script starts only while every running one
    has printed READY_LINE and the machine has capacity; the watchdog evicts the newest while the load stays overloaded.
    Perf checks run alone at the end."""
    perf = perf_ids(directory)
    batches = (([p for p in scripts if script_id(p) not in perf], args.jobs), ([p for p in scripts if script_id(p) in perf], 1))
    results, beside, running, requeued = {}, {}, {}, []
    queue = collections.deque()
    turn = threading.Condition()
    jobs = args.jobs
    if jobs > 1:
        load_ratio()

    def beside_of(check_id):
        with turn:
            return set(beside[check_id])

    def ready(run):
        with turn:
            run["is_ready"] = True
            turn.notify_all()

    def work(check_id, run):
        started = time.time()
        try:
            verdict, detail = run_check(directory, run["path"], args, env, lambda: beside_of(check_id), run)
        except Exception as e:
            verdict, detail = "FAIL", f"rerun could not run it: {type(e).__name__}: {e}"
        with turn:
            running.pop(check_id, None)
            if verdict == "REQUEUED":
                queue.appendleft(run["path"])
            else:
                results[check_id] = (verdict, detail, time.time() - started)
            turn.notify_all()

    def admissible(width):
        if not running:
            return True
        return len(running) < min(width, jobs) and all(r["is_ready"] for r in running.values()) and has_capacity()

    over_since, sampled = None, 0.0
    with turn:
        for batch, width in batches:
            queue.extend(batch)
            while queue or running:
                now = time.monotonic()
                if args.jobs > 1 and now - sampled >= WATCH_POLL_S:
                    sampled = now
                    load, cores = os.getloadavg()[0], os.cpu_count() or 1
                    over_since = (over_since or now) if load > OVERLOAD_RATIO * cores else None
                    if over_since is not None and now - over_since >= OVERLOAD_S and len(running) > 1:
                        check_id, run = max(running.items(), key=lambda item: item[1]["started"])
                        if run["pid"] and not run["evicted"]:
                            run["evicted"] = True
                            others = {r["pid"] for r in running.values() if r is not run}
                            threading.Thread(target=evict, args=(directory, run, others), daemon=True).start()
                            jobs = len(running) - 1
                            over_since = now
                            requeued.append(f"REQUEUED {check_id}  load {load:.1f} on {cores} cores for {OVERLOAD_S:.0f}s; "
                                            f"stopped and queued again, --jobs now {jobs}")
                if queue and admissible(width):
                    path = queue.popleft()
                    check_id = script_id(path)
                    beside[check_id] = set(running)
                    for other in running:
                        beside[other].add(check_id)
                    run = {"path": path, "started": time.time(), "pid": None, "is_ready": False, "evicted": False}
                    run["ready"] = lambda run=run: ready(run)
                    running[check_id] = run
                    threading.Thread(target=work, args=(check_id, run), daemon=True).start()
                    continue
                turn.wait(min(ADMIT_POLL_S, WATCH_POLL_S))
    return results, requeued


def evict(directory, run, others):
    """Stop an evicted script's process group, then the detached processes it started under this run's places."""
    with contextlib.suppress(CannotScan):
        stop_processes([row for row in process_table() if row["pgid"] == run["pid"]])
        # Admission waits for every running script's ready line, so a detached process started after this one began is its own.
        stray = [row for row in find_leftovers(default_roots(directory)) if row["ppid"] == 1 and row["pgid"] not in others
                 and row["started"] is not None and row["started"] >= run["started"] - ELAPSED_SLACK_S]
        if stray:
            stop_processes(stray)
    kill_group(run["pid"])


def cmd_rerun(directory, args):
    scripts = check_scripts(directory)
    if args.only:
        scripts = only_scripts(scripts, args.only)
    if not scripts:
        return f"no saved check scripts (<id>.check.<ext>) in {directory}; nothing to rerun"
    failing, attempts = reported_failures(directory), fix_attempts(directory)
    left = sorted(i for i in failing if attempts.get(i, 0) >= FIX_ATTEMPTS)
    if args.only and (spent := [i for i in dict.fromkeys(args.only) if i in left]):
        raise Failed(f"{', '.join(spent)} failed {FIX_ATTEMPTS} fix attempts since report.md marked them FAIL, the whole fix "
                     "budget. Stop fixing: take each to the user with its repro, what each fix changed, and the premise the fixes "
                     "shared, or in an autonomous run put it in the project's backlog with the fix you recommend and leave it FAIL "
                     f"in report.md. Only the user grants another attempt, by deleting its entry from {FIX_LEDGER}.")
    stamp_path = directory / RERUN_STAMP
    inputs = None if args.only else rerun_inputs(directory, scripts, args.rest, left)
    if inputs and not args.force and stamp_path.exists():
        try:
            stamp = json.loads(stamp_path.read_text())
        except ValueError:
            stamp = {}
        if {k: stamp.get(k) for k in inputs} == inputs:
            known = stamp.get("known") or []
            return (f"rerun: {len(scripts)} checks passed at {stamp.get('at')} on this tree"
                    + (f" except {', '.join(known)}, left FAIL after the fix budget" if known else "")
                    + "; nothing changed since (pass --force to run again)")
    if not args.only:
        stamp_path.unlink(missing_ok=True)
    env = {**os.environ, "VERIFY_DIR": str(directory)}
    results, requeued = run_checks(directory, scripts, args, env)
    lines, failed, known = list(requeued), [], []
    for path in scripts:
        check_id = script_id(path)
        verdict, detail, seconds = results[check_id]
        if verdict == "FAIL":
            failed.append(check_id)
            if check_id in left:
                known.append(check_id)
                detail = "left FAIL: its fix budget is spent and report.md marks it FAIL" + (f"; {detail}" if detail else "")
        head, _, rest = detail.partition("\n")
        lines.append(f"{verdict:<5} {check_id}  ({seconds:.1f}s)" + (f"  {head}" if head else "") + (f"\n{rest}" if rest else ""))
    summary = f"rerun: {len(scripts)} checks, {len(scripts) - len(failed)} PASS, {len(failed)} FAIL"
    summary += f" ({len(known)} left FAIL after the fix budget)" if known else ""
    summary += f", {len(requeued)} requeued under load" if requeued else ""
    lines.append(summary + (" (--only: no stamp; the full rerun decides the gate)" if args.only else ""))
    if args.only:
        for check_id in (i for i in failed if i in failing):
            attempts[check_id] = attempts.get(check_id, 0) + 1
            lines.append(f"fix attempt {attempts[check_id]} of {FIX_ATTEMPTS} for {check_id} failed"
                         + ("; that was the last one, so the next rerun --only refuses it" if attempts[check_id] >= FIX_ATTEMPTS else ""))
        if any(i in failing for i in failed):
            (directory / FIX_LEDGER).write_text(json.dumps(attempts, indent=2) + "\n")
    if len(failed) > len(known):
        raise Failed("\n" + "\n".join(lines))
    if inputs:
        at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        stamp_path.write_text(json.dumps({**inputs, "at": at, "known": known}, indent=2) + "\n")
    return "\n".join(lines)


def perf_ids(directory):
    path = directory / "plan.md"
    if not path.is_file():
        return set()
    _, perf = entries(sections(path.read_text().splitlines()).get("Perf", []))
    return {check_id for entry in perf if (check_id := entry_id(entry))}


def under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


PHASES_POINTER = "phases.json"


def phase_root(directory, args):
    pointer = directory / PHASES_POINTER
    if args.rest:
        root = pathlib.Path(args.rest[0]).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({"root": str(root)}, indent=2) + "\n")
        return root
    if not pointer.is_file():
        raise Failed("no feature plan recorded for this branch. Run `verify.py phases <plan folder>` once.")
    return pathlib.Path(json.loads(pointer.read_text())["root"])


def cmd_phases(directory, args):
    if len(args.rest) > 1:
        raise Failed("phases takes at most one <plan folder>")
    root = phase_root(directory, args)
    phases = sorted(p for p in (root / "phases").glob("*/") if p.is_dir()) if (root / "phases").is_dir() else []
    if not phases:
        raise Failed(f"no phases under {root / 'phases'}: write one folder per phase, each with its plan.md")
    skeleton = (root / "skeleton.patch").is_file()
    problems, owner, total = [], {}, 0
    for phase in phases:
        path = phase / "plan.md"
        if not path.is_file():
            problems.append(f"{path}: missing")
            continue
        text = path.read_text()
        found, ids, _, _ = lint_plan(text)
        problems += [f"{path}:{p}" for p in found]
        for check_id in ids:
            if check_id in owner:
                problems.append(f"{path}: id {check_id!r} is also used in {owner[check_id]}; number checks across the feature")
            owner.setdefault(check_id, phase.name)
        total += len(ids)
        if skeleton and not conformance_checks(text):
            problems.append(f"{path}: no conformance check; add one whose '- Skeleton:' names the skeleton files and symbols "
                            "this phase implements")
    if problems:
        raise Failed("\n".join(problems))
    return f"phases ok: {len(phases)} phases, {total} checks" + (", each with a skeleton conformance check" if skeleton else "")


def conformance_checks(text):
    found = sections(text.splitlines())
    _, checks = entries(found.get("Checks", []))
    return [c for c in checks if (field := c["fields"].get("Skeleton")) and field[1] and not PLACEHOLDER.search(field[1])]


def changed_specs(base, head):
    names = git("diff", "--name-only", "--diff-filter=ACMR", base, head).splitlines()
    return [n for n in names if SPEC_FILE.search(n)]


def spec_command(top, spec, template):
    if template:
        return template.replace("{files}", shlex.quote(spec)) if "{files}" in template else f"{template} {shlex.quote(spec)}"
    if spec.endswith(".py"):
        module = "pytest" if importlib.util.find_spec("pytest") else "unittest"
        return f"{shlex.quote(sys.executable)} -m {module} {shlex.quote(spec)}"
    package = top / "package.json"
    if package.is_file():
        data = json.loads(package.read_text())
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        runner = next((r for r in ("vitest", "jest") if r in deps), None)
        if runner:
            launcher = next((cmd for lock, cmd in NODE_LOCKS.items() if (top / lock).exists()), "npx")
            return f"{launcher} {runner}{' run' if runner == 'vitest' else ''} {shlex.quote(spec)}"
    raise Failed(f"cannot detect how to run {spec}. Pass --test-cmd '<command>' with {{files}} where the spec path goes, "
                 "for example --test-cmd 'pnpm vitest run {files}'.")


def kill_group(pgid):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def run_in_group(command, timeout, on_start=None, on_ready=None, **kwargs):
    """subprocess.run in its own session, so a timeout kills the command and everything it started. on_start gets the
    pid (the process group), and on_ready runs when stdout prints READY_LINE."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, **kwargs) as proc:
        if on_start:
            on_start(proc.pid)
        out, err = [], []

        def drain(stream, sink, ready):
            for line in stream:
                if ready and line.rstrip("\n") == READY_LINE:
                    ready()
                else:
                    sink.append(line)

        readers = [threading.Thread(target=drain, args=(proc.stdout, out, on_ready), daemon=True),
                   threading.Thread(target=drain, args=(proc.stderr, err, None), daemon=True)]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        try:
            proc.wait(timeout=timeout)
            for reader in readers:
                reader.join(max(0.0, deadline - time.monotonic()))
            if any(reader.is_alive() for reader in readers):
                raise subprocess.TimeoutExpired(command, timeout)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=KILL_WAIT_S)
            for reader in readers:
                reader.join(KILL_WAIT_S)
            raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, "".join(out), "".join(err))


def started_at(elapsed, now):
    """When a process started, from ps's elapsed time ([[dd-]hh:]mm:ss), or None when it does not parse."""
    m = ELAPSED.match(elapsed)
    if not m:
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return now - (((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def process_table():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,etime=,pcpu=,command="], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CannotScan(f"cannot list processes with ps: {e}")
    now, rows = time.time(), []
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) == 7 and parts[0].isdigit():
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]), "stat": parts[3],
                         "elapsed": parts[4], "started": started_at(parts[4], now), "cpu": float(parts[5]), "command": parts[6]})
    return rows


def process_cwds(proc=pathlib.Path("/proc")):
    """Working directory of every process this user can see; a deleted one keeps the path it had."""
    if (proc / "self").is_dir():
        cwds = {}
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            with contextlib.suppress(OSError):
                cwds[int(entry.name)] = os.readlink(entry / "cwd").removesuffix(" (deleted)")
        return cwds
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CannotScan(f"cannot read process working directories with lsof: {e}")
    cwds, pid = {}, None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            cwds[pid] = line[1:]
    return cwds


def lineage(table):
    """This process and its ancestors, which must never count as leftovers."""
    parents = {row["pid"]: row["ppid"] for row in table}
    chain, pid = set(), os.getpid()
    while pid and pid not in chain:
        chain.add(pid)
        pid = parents.get(pid)
    return chain


def worktree_paths():
    try:
        out = git("worktree", "list", "--porcelain")
    except (Failed, OSError):
        return []
    return [line.removeprefix("worktree ") for line in out.splitlines() if line.startswith("worktree ")]


def default_roots(directory):
    named = [directory, "~/.cache/parlor-verify-hello", os.environ.get("PARLOR_VERIFY_HOME"), os.environ.get("VERIFY_SCRATCHPAD"), *SALVO_GLOBS]
    return [str(pathlib.Path(r).expanduser()) for r in named if r]


def root_patterns(roots):
    """A test of (working directory, command line) against the roots and their real paths; * in a root matches within one path segment."""
    skipped = {"/", str(pathlib.Path.home())}
    paths = {p.rstrip("/") for r in roots for p in (r, os.path.realpath(r)) if p.rstrip("/") not in skipped | {""}}
    body = "|".join("[^/]*".join(re.escape(piece) for piece in p.split("*")) for p in sorted(paths))
    if not body:
        return lambda cwd, command: False
    in_cwd, in_command = re.compile(rf"^(?:{body})(?:/|$)"), re.compile(rf"(?<![\w./-])(?:{body})(?=/|$|[^\w.-])")
    return lambda cwd, command: bool((cwd and in_cwd.search(cwd)) or in_command.search(command))


def find_leftovers(roots, orphan_roots=()):
    """Processes under any root, plus orphans (parent init) under orphan roots, where the user's own shells and editors live."""
    under, orphaned_under = root_patterns(roots), root_patterns(orphan_roots)
    table = process_table()
    skip = lineage(table)
    cwds = process_cwds()
    return [{**row, "cwd": cwds.get(row["pid"])} for row in table
            if row["pid"] not in skip and not row["stat"].startswith("Z")
            and (under(cwds.get(row["pid"]), row["command"]) or (row["ppid"] == 1 and orphaned_under(cwds.get(row["pid"]), row["command"])))]


def signal_processes(found, sig):
    table = process_table()
    skip = lineage(table)
    protected = {row["pgid"] for row in table if row["pid"] in skip}
    for proc in found:
        group = proc["pgid"]
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if group in protected or group <= 1:
                os.kill(proc["pid"], sig)
            else:
                os.killpg(group, sig)


def stop_processes(found):
    """SIGTERM, then SIGKILL after a grace period, to each process group; returns when they are gone or the waits ran out."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        signal_processes(found, sig)
        deadline = time.time() + KILL_WAIT_S
        while found and time.time() < deadline:
            time.sleep(0.1)
            running = {row["pid"] for row in process_table() if not row["stat"].startswith("Z")}
            found = [p for p in found if p["pid"] in running]
        if not found:
            return


def reap(*roots):
    """Kill whatever still runs under these paths; returns the processes it found."""
    found = find_leftovers(roots)
    if found:
        stop_processes(found)
    return found


def describe(proc):
    return f"pid {proc['pid']} ppid {proc['ppid']} pgid {proc['pgid']} elapsed {proc['elapsed']} cwd {proc.get('cwd') or '-'}  {proc['command'][:160]}"


def busiest_lines():
    busiest = sorted((row for row in process_table() if row["cpu"] > 0), key=lambda row: -row["cpu"])[:TOP_CPU]
    cwds = process_cwds()
    return [f"  {describe({**row, 'cwd': cwds.get(row['pid'])})} cpu {row['cpu']:.0f}%"
            + ("  <- likely leftover: its parent is init" if row["ppid"] == 1 else "") for row in busiest]


def load_report():
    load, cores = os.getloadavg()[0], os.cpu_count() or 1
    if load <= cores:
        return ""
    return "\n".join([f"load {load:.1f} exceeds {cores} cores and no leftovers matched; busiest processes:", *busiest_lines()])


def split_in_use(found, running_since):
    """(leftovers, in use): a process started since a delegate that is still running began may be that delegate's."""
    if running_since is None:
        return found, []
    busy = [p for p in found if p.get("started") is not None and p["started"] >= running_since - ELAPSED_SLACK_S]
    return [p for p in found if p not in busy], busy


def scan_leftovers(roots, orphan_roots, running_since):
    return split_in_use(find_leftovers(roots, orphan_roots), running_since)


def cmd_leftovers(directory, args):
    roots, orphan_roots = [*default_roots(directory), *(args.root or [])], worktree_paths()
    found, busy = scan_leftovers(roots, orphan_roots, args.running_since)
    killed = len(found) if args.kill else 0
    if found and args.kill:
        stop_processes(found)
        found, busy = scan_leftovers(roots, orphan_roots, args.running_since)
    spared = ([f"{len(busy)} in use by a running agent, started after it began, so neither counted nor killed:"]
              + [describe(p) for p in busy]) if busy else []
    if found:
        script = shlex.quote(str(pathlib.Path(__file__).resolve()))
        raise Failed("\n" + "\n".join([*(describe(p) for p in found),
                                        f"{len(found)} still running. Stop them with: python3 {script} leftovers --kill", *spared]))
    lines = ["leftovers: " + (f"killed {killed}, " if killed else "") + "none remain", *spared]
    return "\n".join([*lines, load_report()]).strip()


@contextlib.contextmanager
def scratch_tree(top, rev, specs=(), specs_from=None):
    """A temporary worktree at rev, optionally with the specs from another rev copied over it, sharing the checkout's installed dependencies."""
    parent = tempfile.mkdtemp(prefix="verify-units-")
    path = pathlib.Path(parent).resolve() / "tree"
    git("worktree", "add", "--detach", str(path), rev, cwd=top)
    links = []
    try:
        ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", "--directory", cwd=top).splitlines()
        for name in ignored:
            source = top / name.rstrip("/")
            if source.name in DEPENDENCY_DIRS and not (path / name.rstrip("/")).exists():
                target = path / name.rstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source)
                links.append(target)
        if specs:
            git("checkout", specs_from, "--", *specs, cwd=path)
        yield path
    finally:
        reap(str(path))
        for link in links:
            link.unlink(missing_ok=True)
        subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=top, capture_output=True)
        shutil.rmtree(parent, ignore_errors=True)


def run_spec(tree, command, timeout):
    try:
        r = run_in_group(command, timeout, shell=True, cwd=tree, env={**os.environ, **SCRATCH_ENV})
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    return r.returncode == 0, "\n".join((r.stdout + r.stderr).strip().splitlines()[-3:])


def resolve_range(command, rest):
    if len(rest) > 1:
        raise Failed(f"{command} takes one <base>..<head> range")
    given = rest[0] if rest else f"{git('merge-base', default_branch(), 'HEAD')}..HEAD"
    base, sep, head = given.partition("..")
    if not sep or not base or not head or head.startswith("."):
        raise Failed(f"the range must read <base>..<head>, not {given!r}")
    return git("rev-parse", "--verify", f"{base}^{{commit}}"), git("rev-parse", "--verify", f"{head}^{{commit}}")


def cmd_units(directory, args):
    top = pathlib.Path(git("rev-parse", "--show-toplevel"))
    base, head = resolve_range("units", args.rest)
    specs = args.spec or changed_specs(base, head)
    if not specs:
        raise Failed(f"no spec files were added or changed in {base[:12]}..{head[:12]}. A feature ships with specs that fail without it; "
                     "write them, or name spec files with --spec when the project's test files do not follow the usual naming.")
    commands = {s: spec_command(top, s, args.test_cmd) for s in specs}
    texts = {s: git("show", f"{head}:{s}") for s in specs}
    guards = {s for s in specs if GUARD_MARK in texts[s]}
    with scratch_tree(top, base, specs, head) as tree:
        on_base = {s: run_spec(tree, commands[s], args.timeout) for s in specs}
    with scratch_tree(top, head) as tree:
        at_head = {s: run_spec(tree, commands[s], args.timeout) for s in specs}
    lines, tally, verdicts = [], {"ok": 0, "guard": 0, "vacuous": 0, "broken": 0}, {}
    for s in specs:
        (base_ok, base_tail), (head_ok, head_tail) = on_base[s], at_head[s]
        if not head_ok:
            verdicts[s] = "broken"
            lines.append(f"FAILS AT HEAD  {s}\n" + indent(head_tail))
        elif s in guards:
            verdicts[s] = "guard"
            lines.append(f"GUARD          {s}  marked {GUARD_MARK}, exempt from failing on base")
        elif base_ok:
            verdicts[s] = "vacuous"
            lines.append(f"PASSES ON BASE {s}  passes without the implementation, so it does not show new behavior; "
                         f"make it assert the new behavior, or mark a spec of behavior that already worked with '{GUARD_MARK}'")
        else:
            verdicts[s] = "ok"
            lines.append(f"OK             {s}  fails on base, passes at head\n" + indent(base_tail))
        tally[verdicts[s]] += 1
    lines.append(f"units: {len(specs)} specs, {tally['ok']} fail on base and pass at head, {tally['guard']} regression guards, "
                 f"{tally['vacuous']} pass without the implementation, {tally['broken']} fail at head")
    ids = plan_ids(directory)
    record = {"at": time.time(), "base": base, "head": head, "tree": tree_of(head), "passed": not (tally["vacuous"] or tally["broken"]),
              "specs": {s: {"verdict": verdicts[s], "checks": named_checks(texts[s], ids)} for s in specs}}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / UNITS_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    (directory / UNITS_LOG).write_text("\n".join(lines) + "\n")
    if not record["passed"]:
        raise Failed("\n" + "\n".join(lines))
    return "\n".join(lines)


def plan_ids(directory):
    path = directory / "plan.md"
    return [m.group(1) for line in path.read_text().splitlines() if (m := HEADING.match(line))] if path.is_file() else []


def named_checks(text, ids):
    """The plan's check ids a spec names, as in a test titled 'U2: rounds half up'."""
    return sorted(i for i in ids if re.search(rf"(?<![A-Za-z0-9]){re.escape(i)}(?![A-Za-z0-9])", text))


def load_ratio():
    raw = os.environ.get("VERIFY_MAX_LOAD_RATIO")
    if raw is None:
        return LOAD_RATIO
    try:
        ratio = float(raw)
    except ValueError:
        ratio = 0.0
    if ratio <= 0:
        raise CannotScan(f"VERIFY_MAX_LOAD_RATIO must be a positive number, got {raw!r}")
    return ratio


def native_builds(table):
    skip = lineage(table)
    found = []
    for row in table:
        words = row["command"].split()
        if row["pid"] in skip or not words or pathlib.PurePath(words[0]).name in SHELLS:
            continue
        if any(pattern.search(row["command"]) for pattern in NATIVE_BUILDS.values()):
            found.append(row)
    return found


def has_capacity():
    return os.getloadavg()[0] < load_ratio() * (os.cpu_count() or 1)


def cmd_capacity(directory, args):
    load, cores = os.getloadavg()[0], os.cpu_count() or 1
    threshold = load_ratio() * cores
    builds = native_builds(process_table())
    running = ", ".join(str(row["pid"]) for row in builds)
    line = f"capacity: load {load:.1f}, cores {cores}, threshold {threshold:.1f}, native builds running: " + (f"{len(builds)} (pids {running})" if builds else "none")
    reasons = [reason for refused, reason in ((load >= threshold, "load is at or above the threshold"),
                                              (bool(builds) and args.native, "a native build is running")) if refused]
    if reasons:
        raise Failed("\n" + "\n".join([f"{line}\nrefused: " + "; ".join(reasons), "busiest processes:", *busiest_lines()]))
    return line


def indent(text):
    return "\n".join(f"    {line}" for line in text.splitlines())


COMMANDS = {"plan": cmd_plan, "driver": cmd_driver, "freeze": cmd_freeze, "oracles": cmd_oracles, "compare": cmd_compare,
            "report": cmd_report, "decisions": cmd_decisions, "units": cmd_units, "rerun": cmd_rerun,
            "phases": cmd_phases, "lock": cmd_lock, "adopt": cmd_adopt, "leftovers": cmd_leftovers, "capacity": cmd_capacity}


def main():
    parser = argparse.ArgumentParser(usage=__doc__)
    parser.add_argument("command", choices=["where", *COMMANDS])
    parser.add_argument("--dir")
    parser.add_argument("--revision")
    parser.add_argument("--test-cmd")
    parser.add_argument("--kill", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", action="append")
    parser.add_argument("--spec", action="append")
    parser.add_argument("--only", action="append")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--running-since", type=float)
    parser.add_argument("rest", nargs="*")
    argv = sys.argv[1:]
    passthrough = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_intermixed_args(argv[:len(argv) - len(passthrough) - 1] if "--" in argv else argv)
    args.rest += passthrough
    if args.rest and args.command not in ("units", "rerun", "phases", "adopt"):
        parser.error(f"{args.command} takes no arguments")
    if args.jobs < 1:
        parser.error("--jobs needs at least 1")
    args.timeout = args.timeout or (RERUN_TIMEOUT if args.command == "rerun" else SCRIPT_TIMEOUT)
    try:
        try:
            directory = verification_dir(args.dir)
        except Failed:
            if args.command not in ("leftovers", "capacity"):
                raise
            directory = None
        if args.command == "where":
            directory.mkdir(parents=True, exist_ok=True)
            print(directory)
            return
        print(COMMANDS[args.command](directory, args))
    except Failed as e:
        print(f"verify {args.command}: {e}")
        sys.exit(e.code)


if __name__ == "__main__":
    main()
