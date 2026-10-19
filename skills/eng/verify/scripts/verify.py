#!/usr/bin/env python3
"""Hard checks for the verify skill. Each subcommand exits 0 only when its rule holds.

usage: verify.py <command> [--dir DIR]
       verify.py units [<base>..<head>] [--test-cmd 'CMD {files}'] [--spec PATH ...] [--timeout SECONDS]
       verify.py rerun [--timeout SECONDS] [-- ARGS ...]
       verify.py commits [<base>..<head>] [--cmd CMD] [--typecheck CMD] [--timeout SECONDS]
       verify.py leftovers [--kill] [--root DIR ...]
       verify.py capacity [--native]

  where       print this branch's verification directory
  plan        the plan is complete: checks with every field, and a perf decision
  driver      a project verification skill is on main, or was committed before any product change
  freeze      record the plan's hash before a verifier runs; --revision "<why; agreed by>"
              records a deliberate change to an already frozen plan
  oracles     every oracle check has its expected value, computed from the spec after the freeze
  compare     every oracle check's observed value matches its expected value
  report      every plan check has a verdict backed by evidence on disk, and oracle verdicts match
              the comparison
  decisions   the hillclimb decision log is well formed
  units       every spec file added or changed in <base>..<head> (default: <merge-base with main>..HEAD) fails on
              base plus that spec and passes at head. The runner is detected (vitest or jest from package.json,
              else pytest or unittest for .py files), or --test-cmd gives it, with {files} for the spec path.
              A spec file whose text contains "regression-guard" (in a title or a comment) guards behavior that
              already works: it must pass at head but may pass on base. Keep guards in their own spec files.
  rerun       run every saved <id>.check.<ext> script in the verification directory, passing ARGS (for example an
              instance id) to each; one PASS or FAIL line per check from its exit code, and a summary. Each script
              gets 300 seconds unless --timeout raises it. Exits 0 with a "no saved check scripts" line when there
              are none.
  commits     check every commit in <base>..<head> (default like units), one at a time in a scratch tree: --typecheck
              first when given, then --cmd (default: the project's test script, else pytest or unittest). One PASS or
              FAIL line per commit; a commit that leaves a process running in its tree FAILs and the process is killed.
              A spec-only commit (subject starting with "test", or only spec files) reports its result but does not
              fail the run.
  leftovers   list processes still running from this run's places: the verification directory,
              ~/.cache/parlor-verify-hello, $PARLOR_VERIFY_HOME, $VERIFY_SCRATCHPAD (the agent scratchpad),
              /tmp/salvo-*, each --root, and, when their parent is init, anything under a worktree of this repo
              (the user's own shells and editors live there). A process counts when its working directory
              (deleted ones included) or its command line is under one of them. The caller and its ancestors never
              count. Exits 1 while any remain and 2 when the scan itself cannot run. --kill sends SIGTERM to each
              process group, then SIGKILL to survivors, and rescans. When nothing remains but the 1-minute load
              exceeds the core count, it also lists the busiest processes and flags those whose parent is init as
              likely leftovers (the exit code is unaffected).
  capacity    the machine has room for another heavy run: exits 0 when the 1-minute load is below ratio x cores
              (ratio 0.7, $VERIFY_MAX_LOAD_RATIO overrides) and no native app build is running, else exits 1. Native
              builds are xcodebuild, tauri build, cargo build, cap run, cap sync and gradle in the process table;
              without --native a running one is only reported, with --native it also refuses. Prints one line with
              load, cores, threshold and native builds running (pids); a refusal adds the busiest processes.

The verification directory is ~/.agents/verify/<repo>-<clone hash>/<branch>/, so two clones of one repo never share it ($VERIFY_HOME overrides
the root, --dir overrides the whole path). It holds plan.md, plan.lock, report.md,
decision.tsv, and the evidence files. An oracle check <id> also has <id>.expected.json, written by an
agent that read only the spec and the seed data, and <id>.observed.json, read from the running app.
"""
import argparse
import contextlib
import datetime
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


SPEC_FILE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|[^/]*_spec\.rb|[^/]*Tests?\.(swift|kt|java))$")
GUARD_MARK = "regression-guard"
CHECK_SCRIPT = re.compile(r"^(.+)\.check\.[^.]+$")
SCRIPT_RUNNERS = {".py": [sys.executable], ".sh": ["bash"], ".js": ["node"], ".mjs": ["node"], ".ts": ["npx", "tsx"]}
NODE_LOCKS = {"pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bunx", "bun.lockb": "bunx"}
DEPENDENCY_DIRS = {"node_modules", ".venv", "venv"}
SCRIPT_TIMEOUT = 900
RERUN_TIMEOUT = 300
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
TOP_CPU = 5
SALVO_GLOBS = ("/tmp/salvo-*", "/private/tmp/salvo-*")
# A scratch tree borrows the checkout's installed dependencies through symlinks, which pnpm 11's pre-run deps check rejects.
SCRATCH_ENV = {"pnpm_config_verify_deps_before_run": "false"}
TEST_SCRIPTS = {"pnpm-lock.yaml": "pnpm test", "yarn.lock": "yarn test", "bun.lock": "bun run test", "bun.lockb": "bun run test"}


class Failed(Exception):
    code = 1


class CannotScan(Failed):
    code = 2


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise Failed(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.rstrip("\n")


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


def lint_plan(text):
    """Return (problems, check ids, {oracle check id: tolerance}) for a plan's text."""
    problems, ids, oracles = [], [], {}
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
            ids.append((entry_id(entry), entry["line"]))
    seen = {}
    for check_id, line in ids:
        if check_id and check_id in seen:
            problems.append(f"{line}: id {check_id!r} is used more than once")
        seen.setdefault(check_id, line)
    return problems, [i for i, _ in ids if i], oracles


def load_plan(directory):
    path = directory / "plan.md"
    text = read(path, "plan (write it from the verify skill's references/plan-template.md)")
    problems, ids, oracles = lint_plan(text)
    if problems:
        raise Failed("\n".join(f"{path}:{p}" for p in problems))
    return path, text, ids, oracles


def cmd_plan(directory, args):
    path, _, ids, oracles = load_plan(directory)
    return f"{path}: plan ok, {len(ids)} checks, {len(oracles)} oracle checks"


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
    _, text, _, _ = load_plan(directory)
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
    _, text, _, oracles = load_plan(directory)
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
    _, text, _, oracles = load_plan(directory)
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


def cmd_report(directory, args):
    _, text, ids, oracles = load_plan(directory)
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
    if current_head and reported_head and not (len(reported_head) >= 7 and current_head.startswith(reported_head)):
        problems.append(f"the report covers Head {reported_head}, but HEAD is now {current_head[:12]}; verify the code that ships, "
                        "sending the checks the later commits could touch to a fresh verifier")
    if header.get("Author", "").strip() and header.get("Author", "").strip() == header.get("Verifier", "").strip():
        problems.append("the Verifier is the Author; a fresh agent must produce the verdicts")
    exploration = re.search(r"^## Exploration\s*\n(.*?)(?=^## |\Z)", report, re.M | re.S)
    if not exploration or not exploration.group(1).strip():
        problems.append("missing '## Exploration' section with the verifier's findings, or 'none found'")
    else:
        findings = [line.strip() for line in exploration.group(1).splitlines() if re.match(r"^\s*[-*] ", line)]
        for finding in findings:
            if not TRIAGE.search(finding):
                problems.append(f"exploration finding has no 'Triage: fixed | new check | follow-up | pre-existing | dismissed': {finding[:80]}")
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
        if verdict == "FAIL" and not observed.lower().startswith(("defect:", "blocker:")):
            problems.append(f"{number}: {check_id} is FAIL; start its Observed cell with 'defect:' and the repro")
        if verdict == "INCONCLUSIVE" and not observed.lower().startswith("blocker:"):
            problems.append(f"{number}: {check_id} is INCONCLUSIVE; start its Observed cell with 'blocker:' and what stopped it")
    if problems:
        raise Failed("\n".join(f"{path}: {p}" for p in problems))
    revisions = "".join(f"\n  revision {r['at']}: {r['why']}" for r in lock["revisions"])
    return f"report ok: {len(ids)} checks have verdicts backed by evidence{revisions}"


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


def cmd_rerun(directory, args):
    scripts = check_scripts(directory)
    if not scripts:
        return f"no saved check scripts (<id>.check.<ext>) in {directory}; nothing to rerun"
    env = {**os.environ, "VERIFY_DIR": str(directory)}
    lines, failed = [], 0
    for path in scripts:
        check_id = CHECK_SCRIPT.match(path.name).group(1)
        command = script_command(path)
        started = time.time()
        if not command:
            verdict, detail = "FAIL", f"{path.name} is not executable and has no interpreter for {path.suffix}"
        else:
            try:
                r = run_in_group([*command, *args.rest], args.timeout, env=env)
                output = (r.stdout + r.stderr).strip()
                (directory / f"{check_id}.rerun.log").write_text(output + "\n")
                verdict = "PASS" if r.returncode == 0 else "FAIL"
                detail = "" if verdict == "PASS" else f"exit {r.returncode}"
                if verdict == "FAIL" and output:
                    detail += "\n" + "\n".join(f"    {line}" for line in output.splitlines()[-5:])
            except subprocess.TimeoutExpired:
                verdict, detail = "FAIL", f"timed out after {args.timeout}s"
        failed += verdict == "FAIL"
        head, _, rest = detail.partition("\n")
        lines.append(f"{verdict:<5} {check_id}  ({time.time() - started:.1f}s)" + (f"  {head}" if head else "") + (f"\n{rest}" if rest else ""))
    summary = f"rerun: {len(scripts)} checks, {len(scripts) - failed} PASS, {failed} FAIL"
    lines.append(summary)
    if failed:
        raise Failed("\n" + "\n".join(lines))
    return "\n".join(lines)


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


def run_in_group(command, timeout, **kwargs):
    """subprocess.run in its own session, so a timeout kills the command and everything it started."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, **kwargs) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=KILL_WAIT_S)
            raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def process_table():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,etime=,pcpu=,command="], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CannotScan(f"cannot list processes with ps: {e}")
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) == 7 and parts[0].isdigit():
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]), "stat": parts[3],
                         "elapsed": parts[4], "cpu": float(parts[5]), "command": parts[6]})
    return rows


def process_cwds():
    """Working directory of every process this user can see; a deleted one keeps the path it had."""
    proc = pathlib.Path("/proc")
    if (proc / "self" / "cwd").exists():
        cwds = {}
        for entry in proc.iterdir():
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


def cmd_leftovers(directory, args):
    roots, orphan_roots = [*default_roots(directory), *(args.root or [])], worktree_paths()
    found = find_leftovers(roots, orphan_roots)
    killed = len(found) if args.kill else 0
    if found and args.kill:
        stop_processes(found)
        found = find_leftovers(roots, orphan_roots)
    if found:
        script = shlex.quote(str(pathlib.Path(__file__).resolve()))
        raise Failed("\n" + "\n".join(describe(p) for p in found)
                     + f"\n{len(found)} still running. Stop them with: python3 {script} leftovers --kill")
    lines = [f"leftovers: " + (f"killed {killed}, " if killed else "") + "none remain"]
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
    guards = {s for s in specs if GUARD_MARK in git("show", f"{head}:{s}")}
    with scratch_tree(top, base, specs, head) as tree:
        on_base = {s: run_spec(tree, commands[s], args.timeout) for s in specs}
    with scratch_tree(top, head) as tree:
        at_head = {s: run_spec(tree, commands[s], args.timeout) for s in specs}
    lines, tally = [], {"ok": 0, "guard": 0, "vacuous": 0, "broken": 0}
    for s in specs:
        (base_ok, base_tail), (head_ok, head_tail) = on_base[s], at_head[s]
        if not head_ok:
            tally["broken"] += 1
            lines.append(f"FAILS AT HEAD  {s}\n" + indent(head_tail))
        elif s in guards:
            tally["guard"] += 1
            lines.append(f"GUARD          {s}  marked {GUARD_MARK}, exempt from failing on base")
        elif base_ok:
            tally["vacuous"] += 1
            lines.append(f"PASSES ON BASE {s}  passes without the implementation, so it does not show new behavior; "
                         f"make it assert the new behavior, or mark a spec of behavior that already worked with '{GUARD_MARK}'")
        else:
            tally["ok"] += 1
            lines.append(f"OK             {s}  fails on base, passes at head\n" + indent(base_tail))
    lines.append(f"units: {len(specs)} specs, {tally['ok']} fail on base and pass at head, {tally['guard']} regression guards, "
                 f"{tally['vacuous']} pass without the implementation, {tally['broken']} fail at head")
    if tally["vacuous"] or tally["broken"]:
        raise Failed("\n" + "\n".join(lines))
    return "\n".join(lines)


def default_test_command(top):
    package = top / "package.json"
    if package.is_file() and "test" in json.loads(package.read_text()).get("scripts", {}):
        return next((cmd for lock, cmd in TEST_SCRIPTS.items() if (top / lock).exists()), "npm test")
    if any(SPEC_FILE.search(n) for n in git("ls-files", "*.py", cwd=top).splitlines()):
        python = shlex.quote(sys.executable)
        if importlib.util.find_spec("pytest"):
            return f"{python} -m pytest"
        return f"{python} -m unittest discover" + (" -s tests" if (top / "tests").is_dir() else "")
    raise Failed("cannot detect how to run the project's tests. Pass --cmd '<command>', for example --cmd 'pnpm test'.")


def spec_only(commit, subject):
    if subject.lower().startswith("test"):
        return True
    names = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit).splitlines()
    return bool(names) and all(SPEC_FILE.search(n) for n in names)


def check_commit(tree, typecheck, command, timeout):
    if typecheck:
        ok, tail = run_spec(tree, typecheck, timeout)
        if not ok:
            return False, f"typecheck failed: {tail}"
    return run_spec(tree, command, timeout)


def cmd_commits(directory, args):
    top = pathlib.Path(git("rev-parse", "--show-toplevel"))
    base, head = resolve_range("commits", args.rest)
    commits = git("rev-list", "--reverse", "--topo-order", f"{base}..{head}").splitlines()
    if not commits:
        raise Failed(f"no commits in {base[:12]}..{head[:12]}")
    command = args.cmd or default_test_command(top)
    verdicts = []
    for commit in commits:
        subject = git("log", "-1", "--format=%s", commit)
        pin = spec_only(commit, subject)
        with scratch_tree(top, commit) as tree:
            ok, detail = check_commit(tree, args.typecheck, command, args.timeout)
            strays = reap(str(tree))
        if strays:
            detail = "; ".join(filter(None, [detail.partition("\n")[0] if not ok else "",
                                             "leftover processes killed: " + ", ".join(str(p["pid"]) for p in strays)]))
        verdict = "PASS" if ok and not strays else "FAIL"
        counted = verdict == "FAIL" and (strays or not pin)
        verdicts.append((verdict, counted))
        head_line, _, rest = detail.partition("\n")
        note = "  (spec-only commit, not counted)" if verdict == "FAIL" and not counted else ""
        print(f"{verdict:<5} {commit[:12]} {subject}" + (f"  {head_line}" if head_line else "") + note
              + (f"\n{indent(rest)}" if rest and verdict == "FAIL" else ""), flush=True)
    failed = sum(v == "FAIL" for v, _ in verdicts)
    summary = f"commits: {len(commits)} checked, {len(commits) - failed} PASS, {failed} FAIL"
    if any(counted for _, counted in verdicts):
        raise Failed(summary)
    return summary + (" (all failures were spec-only commits)" if failed else "")


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
            "commits": cmd_commits, "leftovers": cmd_leftovers, "capacity": cmd_capacity}


def main():
    parser = argparse.ArgumentParser(usage=__doc__)
    parser.add_argument("command", choices=["where", *COMMANDS])
    parser.add_argument("--dir")
    parser.add_argument("--revision")
    parser.add_argument("--test-cmd")
    parser.add_argument("--cmd")
    parser.add_argument("--typecheck")
    parser.add_argument("--kill", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--root", action="append")
    parser.add_argument("--spec", action="append")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("rest", nargs="*")
    args = parser.parse_args()
    if args.rest and args.command not in ("units", "rerun", "commits"):
        parser.error(f"{args.command} takes no arguments")
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
