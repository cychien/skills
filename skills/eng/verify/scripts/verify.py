#!/usr/bin/env python3
"""Hard checks for the verify skill. Each subcommand exits 0 only when its rule holds.

usage: verify.py <command> [--dir DIR]

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

The verification directory is ~/.agents/verify/<repo>-<clone hash>/<branch>/, so two clones of one repo never share it ($VERIFY_HOME overrides
the root, --dir overrides the whole path). It holds plan.md, plan.lock, report.md,
decision.tsv, and the evidence files. An oracle check <id> also has <id>.expected.json, written by an
agent that read only the spec and the seed data, and <id>.observed.json, read from the running app.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
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
TRIAGE = re.compile(r"\bTriage:\s*(fixed|new check|pre-existing|dismissed)\b", re.I)


class Failed(Exception):
    pass


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
                problems.append(f"exploration finding has no 'Triage: fixed | new check | pre-existing | dismissed': {finding[:80]}")
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
        files = [e.strip().strip("`") for e in evidence.split(",") if e.strip()]
        if not files:
            problems.append(f"{number}: {check_id} names no evidence file")
        for f in files:
            p = pathlib.Path(f).expanduser()
            p = p if p.is_absolute() else directory / p
            if p.is_dir():
                files = [x for x in p.rglob("*") if x.is_file() and x.stat().st_size]
                if not files:
                    problems.append(f"{number}: evidence {f} is an empty directory")
                elif min(x.stat().st_mtime for x in files) < lock["frozen_ts"]:
                    problems.append(f"{number}: evidence {f} holds files that predate the frozen plan; freeze the plan before a verifier runs, then verify again")
            elif not p.is_file() or p.stat().st_size == 0:
                problems.append(f"{number}: evidence {f} is missing or empty")
            elif p.stat().st_mtime < lock["frozen_ts"]:
                problems.append(f"{number}: evidence {f} predates the frozen plan; freeze the plan before a verifier runs, then verify again")
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


COMMANDS = {"plan": cmd_plan, "driver": cmd_driver, "freeze": cmd_freeze, "oracles": cmd_oracles, "compare": cmd_compare,
            "report": cmd_report, "decisions": cmd_decisions}


def main():
    parser = argparse.ArgumentParser(usage=__doc__)
    parser.add_argument("command", choices=["where", *COMMANDS])
    parser.add_argument("--dir")
    parser.add_argument("--revision")
    args = parser.parse_args()
    try:
        directory = verification_dir(args.dir)
        if args.command == "where":
            directory.mkdir(parents=True, exist_ok=True)
            print(directory)
            return
        print(COMMANDS[args.command](directory, args))
    except Failed as e:
        print(f"verify {args.command}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
