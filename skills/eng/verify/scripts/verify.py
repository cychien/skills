#!/usr/bin/env python3
"""Hard checks for the verify skill. Each subcommand exits 0 only when its rule holds.

usage: verify.py <command> [--dir DIR]
       verify.py plan [--checks]
       verify.py adopt <phase folder> [--base <branch>]
       verify.py base [<branch>]
       verify.py premises [--resolved]
       verify.py freeze [--revision "<what changed and why>" [--gate <autorun gate id>]]
       verify.py units [<base>..<head>] [--test-cmd 'CMD {files}'] [--spec PATH ...] [--timeout SECONDS]
       verify.py dryrun --base <worktree at the base> [--only ID ...] [--jobs N] [--timeout SECONDS] [-- ARGS ...]
       verify.py rerun [--only ID ...] [--jobs N] [--timeout SECONDS] [--force] [--full-reason "<why; agreed by whom>"] [-- ARGS ...]
       verify.py report [--write --author <agent:model> --verifier <agent:model> [--note "<text>" ...]]
       verify.py script-fix <file> --reason "<why it crashed before its predicate>"
       verify.py phases [<plan folder>]
       verify.py leftovers [--kill] [--root DIR ...] [--running-since EPOCH]
       verify.py capacity [--native]

Every command reads the plan from the phase folder's plan.md that `adopt` recorded, else from plan.md in the verification
directory.

  where       print this branch's verification directory
  plan        the plan is complete: checks with every field, a Tier of e2e, unit, or walk on each (a perf check is
              always e2e), and a perf decision. At most 10 e2e checks per plan, with no override: E2E is the most
              expensive tier, so fewer is better: keep only core behavior no unit spec can see, and 10 is a ceiling, not a
              target; move the rest to unit or drop them, or split the phase. A plan with any e2e or walk check needs a
              non-empty '## Drive contract' section: every name those checks drive (test ids, accessible names, routes,
              HTTP paths, CLI commands and flags, wire and event names, file paths), settled before code. The contract
              names product-side names only: a line whose label (the text before its first colon) starts with driver or
              harness is refused, because driver commands are the verifier's own; a line the plan lock already held
              stays. An e2e or perf check may carry '- Base: passes: <why the base already has this behavior>', the only
              way its script may pass on base (see `scripts`); a unit or walk check may not. Every HTTP path
              (`/x` or `GET /x`) and CLI flag (`--name`) an e2e or walk check names in backticks in its Scenario or Pass
              must appear in the Drive contract; a contract path with :id, {id}, <id>, or * segments covers any value
              there. An optional '## Sensitive paths' section lists paths or globs (auth, permissions, crypto) where the
              reviewer looks hardest. --checks checks the checks part only (fields, tiers, the e2e cap, the perf
              decision), before the Drive contract exists. Prints the count per tier.
  adopt       record a phase folder's plan.md from a feature plan as this branch's plan, and HEAD as the phase's base, so
              every command reads the plan where it lives and `lock` measures code from where the phase starts. The plan
              must pass `plan --checks`, and HEAD must pass `base` for --base <branch> (default main, the repository's
              default branch), which it records beside the base commit. A plan.md left in the verification directory by
              an older adopt is removed when it matches, and refused when it differs.
  base        the phase branch is cut from the latest <branch>: runs `git fetch origin <branch>` and passes when
              origin/<branch> is an ancestor of HEAD (without an origin remote, the local <branch>). With no <branch>, the
              branch `adopt --base` recorded for this branch, else main (the repository's default branch). A phase that
              stacks on an earlier phase's open PR passes that phase's branch.
  premises    premises.md and grounding.md sit beside the plan (the phase folder, else the verification directory), each
              with a line 'Base: <sha>' naming the base it was checked at, which must be the phase's base (the commit
              `adopt` recorded, else the merge-base with main); a full or abbreviated sha of it counts. premises.md holds
              a table with the columns Check | Premise | Holds | Evidence | Resolution: every check id of the plan in at
              least one row, and Holds yes or no, with Evidence, or new: a premise is a fact a check assumes already
              holds on the base, and what this phase builds gets one 'new' row per check at most, Evidence optional.
              --resolved also needs a Resolution on every row whose premise does not hold ('new' rows need none).
  driver      a project verification skill is on main, or was committed before any product change, or HEAD holds a
              driver-only commit whose patch (git patch-id) matches a commit on a local branch whose commits since the
              phase base (the commit `adopt` recorded, else the merge-base with main) touch only the driver: the
              verifier built or extended it there, on the unchanged app, and cherry-picked it onto the change
  freeze      record the plan, its hash, the Drive contract and Sensitive paths included, before a verifier runs. A later
              change that only adds checks, Drive contract lines, or Sensitive paths records itself as an automatic
              revision. Any other change (any field, the title, or the text of an existing check; a removed check or line;
              any other added or changed line, the perf decision and its n/a reason included) needs --revision "<what
              changed and why>", and in an autonomous run also --gate <id> of an autorun gate the user answered, each gate
              backing one revision.
  lock        freeze the plan before any code exists: refuses while the working tree changes product files since the
              base (the commit `adopt` recorded, else the merge-base with main), leaving the project's verification
              skill and the adopted plan folder aside. Once locked, passes while the plan is unchanged or every change
              is a recorded revision, and fails for a plan first frozen after code existed.
  oracles     every oracle check has its expected value, computed from the spec after the freeze
  compare     every oracle check's observed value matches its expected value
  review      review.md, written after the freeze, names its 'Reviewer:' (agent:model) under the title and holds a
              '## Review' section and a '## Fix review' section, each with its own 'Head:' line, the commit the reviewer
              read, and nothing else but finding bullets, each triaged ('Triage: fixed | new check | follow-up |
              pre-existing | dismissed'), or 'none found'; any other line fails. The fix review names its own 'Reviewer:',
              the review's, unless a 'Relaxed: <reason>' line says why another took it (a quota fallback), and the report
              lists that. The lead adds 'Fixed at: <sha>' to the fix review once its fixes land: a commit at or after its
              Head, with the Head's product tree when no finding is triaged fixed. HEAD must hold Fixed at's product tree,
              so no product change follows the reviewed fixes.
  scripts     every e2e check, perf checks included, has its <id>.check.<ext> script and an <id>.base.log from
              `dryrun` of that same script that holds a "verify: step <name> within <seconds>" line, reached "verify:
              ready", and failed a predicate: exit 1 with a FAIL line last on stdout. A script that crashed (no ready
              line, an exit other than 0 to 3, or no FAIL line), stalled, or was inconclusive fails the gate. One that
              passes on base fails it too, unless its check carries '- Base: passes: <why>': fix the script or its helper
              so it fails on base, or revise the plan through `freeze --revision` to add the field.
  dryrun      run each saved check script with --base, a worktree at the phase base whose product files match it, as its
              working directory, VERIFY_DRYRUN=1 in its environment, and write <id>.base.log with its output and verdict.
              Scripts start, are supervised, and are requeued on exit 3 the way `rerun` does it, and the compact lines go
              to dryrun.summary. Exits 1 when a script crashed, stalled, or was inconclusive.
  report      every plan check has a verdict backed by evidence on disk, and oracle verdicts match the comparison; the
              report's Head is HEAD or a commit with HEAD's product code (a regrouped history, or later commits that touch
              only the adopted plan folder or the project's verification skills). A PASS is backed by its tier's
              evidence: e2e by its <id>.check.<ext> script and an <id>.rerun.log from a passing run after the freeze whose
              recorded head has no product change before HEAD (any path outside the project's verification skills and
              the adopted plan folder, as `lock` counts them) and that graded no uncommitted product change; unit by the
              last `units` result, after the freeze, passing, on HEAD's product code, with a spec that names the check id; walk
              by a screenshot or video in evidence/<id>/ written after the freeze. Every row has an observation; a FAIL
              row's starts with 'defect:', an INCONCLUSIVE row's with 'blocker:', and an INCONCLUSIVE row needs no
              evidence. review.md passes the review rules except the one on HEAD after Fixed at, since fixes for e2e
              FAILs follow the review. A passing report lists a relaxed fix review, each plan revision, each full rerun
              after the prove, and each script fix, with its reason, and the checks that are not ready to merge.
              --write builds report.md first: Head, Main, --author and --verifier (else the ones report.md names), and one
              row per check from its evidence (e2e from the latest <id>.rerun.log, unit from units.json, walk from
              evidence/<id>/) with its Observed cell from observations.md, where the verifier writes one line per check
              as '<id>: <what it saw>'. A check whose evidence passes is PASS, one whose evidence fails is FAIL, one with
              no current evidence is INCONCLUSIVE, and an observation starting 'defect:' or 'blocker:' makes it FAIL or
              INCONCLUSIVE. A missing observation leaves the cell 'missing', which fails the gate. Any FAIL or
              INCONCLUSIVE row is also listed under '## Not ready to merge' at the top. Each --note "<text>" becomes a line
              of a '## Notes' section (a quota fallback that relaxed a separation rule, for example); without --note the
              notes report.md already holds stay.
  spec        with an adopted phase of a plan folder, the folder's spec.md has a '## Change log' section with a line
              naming this phase's folder, or '<phase>: no design change', and `phases` passes. A base.json an older
              `adopt` wrote names only the plan folder: the phase is the one whose plan shares a check id with the plan.md
              copy in the verification directory, and when none or several do, the gate fails. Only without any plan
              folder does it pass, with a note.
  decisions   the hillclimb decision log is well formed
  units       every spec file added or changed in <base>..<head> (default: <merge-base with main>..HEAD) fails on
              base plus that spec and passes at head. The runner is detected (vitest or jest from package.json,
              else pytest or unittest for .py files), or --test-cmd gives it, with {files} for the spec path.
              A spec file whose text contains "regression-guard" (in a title or a comment) guards behavior that
              already works: it must pass at head but may pass on base. Keep guards in their own spec files.
              Each run records units.json (per spec its verdict and the plan check ids its text names, so a test
              titled "U2: ..." proves unit check U2) and units.log in the verification directory, for `report`.
  rerun       run every saved <id>.check.<ext> script in the verification directory, passing ARGS (for example an
              instance id) to each, and print one compact line per check in id order, '<id> <VERDICT> <seconds>s [step
              <name>] [<reason>]', then a summary; the same lines go to rerun.summary, so read one line per check and
              open a log only on FAIL. A check script prints, on stdout and flushed, "verify: step <name> within
              <seconds>" on entering each step, setup included, with the most that step may take; "verify: ready" once
              its instance is up; and a PASS or FAIL line last. Its exit code is its verdict: 0 PASS, 1 FAIL (a predicate
              failed), 2 INCONCLUSIVE (a premise or blocker named on the last line), 3 ENVIRONMENT (the instance or
              machine could not support the run: a load refusal, an instance that died, a usage limit); any other exit,
              or a kill, is CRASH. Runs are supervised by progress: each step line opens a deadline of its seconds plus
              the larger of 15 s and a quarter of them, and until the first one a 120 s window applies; when the open
              deadline passes, verify kills the script's process group and records STALLED with the step and the last
              output line, however long the run has taken before, so a slow run that progresses is never killed.
              --timeout is only a total safety net, 7200 seconds by default, recorded as CRASH. An ENVIRONMENT run is
              queued again for when `capacity` passes, at most 2 times per run, and is then INCONCLUSIVE with reason
              environment; it writes no log, records no verdict, and is no fix attempt. Scripts run as parallel as
              capacity allows: the next
              starts once every running script has printed the line "verify: ready" (its instance is up; the line stays
              out of its log), while fewer than --jobs run when it is given, and while `capacity` passes, because the
              1-minute load lags an instance start; a script that never prints the line runs alone. While capacity is
              short a script waits, checking every 15 seconds; after 10 minutes it is REQUEUED behind the rest, and
              after a second such wait it is NOT-RUN, which fails the run. A watchdog samples the load every 3 seconds;
              once it stays above 1.0 x cores for 15 seconds, it stops the most recently started script with its
              process group and the detached processes it started, queues it again, prints it as REQUEUED with the load,
              and lowers the jobs to the scripts still running, never below one. A requeued run is neither a FAIL nor a
              fix attempt, and a script that finishes FAIL is never retried. The plan's perf checks always run alone
              after the rest, because concurrent instances skew every timing. A file owned by a check that ran at the
              same time is not held against the other, because that check may be rewriting its own evidence, and a loss
              seen while checks ran side by side FAILs each of them with the names of the others, so `--only` finds the
              culprit. Exits 0 with a "no saved check scripts" line when there are none. A check script runs with zero
              arguments and provisions and tears down its own instance through the project driver (optional ARGS may
              reuse a running instance); it cleans only its own evidence (evidence/<id>/ or files starting with <id>),
              never a shared folder, and a script that deletes or empties another check's file FAILs; the report cites
              <id>.rerun.log, not the script, and the log's last line is "rerun: PASS" or "rerun: <VERDICT> (<why>)".
              After a run where every script passes, rerun stamps rerun.stamp.json with HEAD's tree, a hash of the tracked
              working-tree diff, and a sha256 per check script and helper (.mjs .cjs .js .ts .py .sh). A later rerun with
              the same ARGS and an unchanged stamp prints one line and exits 0 without running; --force skips that check.
              Any run deletes the stamp first, so a failed or interrupted run leaves none. The first full rerun is the
              prove's: before it runs, it writes scripts.lock.json with the time, HEAD, and a sha256 per check script and
              helper. A later full rerun is refused and names the `rerun --only` ids that need a run: each check whose
              latest run failed or predates a product change; --full-reason "<why; agreed by whom>" allows one, records
              it in the lock, and relocks the hashes. Any rerun, --only included, refuses while a locked file differs
              from its hash, until `script-fix` records why it changed; a script or helper added later is locked on its
              first run. --only ID ... runs just those checks; it neither reads nor writes the stamp, and given no ids it
              runs nothing. Every rerun, --only included, records per check it ran the HEAD, a hash of the tracked
              working-tree diff (null when clean), the product paths that diff touches, the verdict, and the time in
              rerun.ledger.json, keeping each check's latest run with its script's sha256, for `report`. Once report.md
              marks a check FAIL, a run in which it still fails is one failed fix attempt, counted in fix-attempts.json,
              when a product file or its script changed since its previous failing run; a rerun with no such change (an
              environment rerun) is not one, and only a FAIL verdict counts, never INCONCLUSIVE, STALLED, or CRASH.
              After 2, every rerun skips the check with a note instead of running it, without failing, because it goes
              to the user or the backlog. A check script finds the repository from its working directory, never a
              hard-coded worktree path.
  script-fix  record why a check script or helper that scripts.lock.json locked changed after the prove: <file> in the
              verification directory and --reason "<why it crashed before its predicate>". It appends the time, the file,
              its old and new sha256, and the reason to the lock's script fixes and locks the new hash, so a rerun may
              grade it again. Refuses a file the lock does not hold or one whose hash did not change.
  phases      every phase of a feature plan has a sound verification plan: <plan folder>/phases/<phase>/plan.md for
              each phase, each passing `plan --checks` (the 10 e2e cap among them; a phase plan holds checks only, so no
              Drive contract is required), check ids unique across the whole feature (the feature plan's Acceptance list
              names each check by id), and, when <plan folder>/skeleton.patch exists, every phase holding a conformance
              check with a Skeleton field naming the skeleton files and symbols it implements. Given a plan folder, it
              records it in this branch's verification directory, so the bare command (a gate) checks the same folder
              later; without one it checks the folder `adopt` recorded.
  leftovers   list processes still running from this run's places: the verification directory,
              ~/.cache/parlor-verify-hello, $PARLOR_VERIFY_HOME, $VERIFY_SCRATCHPAD (the agent scratchpad),
              /tmp/salvo-*, each --root, and, when their parent is init, anything under a worktree of this repo
              (the user's own shells and editors live there). A process counts when its working directory
              (deleted ones included) or its command line is under one of them. The caller and its ancestors never
              count. --running-since EPOCH says a delegate that is still running began then (guard passes it before a
              spawn): a process started since may be that delegate's, so it is listed as in use by a running agent and
              neither counted nor killed. A process whose environment holds VERIFY_LEAD=1, and every descendant of one,
              is the lead's own (a watcher or Monitor loop that names the verification directory): it is listed as
              spared, started by the lead, and neither counted nor killed. Linux exposes another process's environment
              and macOS does not, so the marker also counts anywhere in a command line: start a watcher as
              sh -c 'VERIFY_LEAD=1 ...'. Set it on the watcher's own command, never in the session's environment,
              or every process the session starts is spared. Exits 1 while any remain and 2 when the scan itself cannot
              run. --kill sends SIGTERM to each process group, then SIGKILL to survivors, and rescans. When nothing remains but the
              1-minute load exceeds the core count, it also lists the busiest processes and flags those whose parent is init as
              likely leftovers (the exit code is unaffected).
  capacity    the machine has room for another heavy run: exits 0 when the 1-minute load is below ratio x cores
              (ratio 0.7, $VERIFY_MAX_LOAD_RATIO overrides) and no native app build is running, else exits 1. Native
              builds are xcodebuild, tauri build, cargo build, cap run, cap sync and gradle in the process table;
              without --native a running one is only reported, with --native it also refuses. Prints one line with
              load, cores, threshold and native builds running (pids); a refusal adds the busiest processes.

The verification directory is ~/.agents/verify/<repo>-<clone hash>/<branch>/, so two clones of one repo never share it ($VERIFY_HOME overrides
the root, --dir overrides the whole path). It holds base.json (the adopted plan and base), plan.md when no phase was adopted,
plan.lock, report.md, observations.md, review.md, decision.tsv, units.json, fix-attempts.json, scripts.lock.json,
rerun.ledger.json, rerun.summary, dryrun.summary, the <id>.base.log and <id>.rerun.log files, and the evidence files. An
oracle check <id> also has <id>.expected.json, written by an agent that read only the spec and the seed data, and
<id>.observed.json, read from the running app.
"""
import argparse
import collections
import contextlib
import datetime
import fcntl
import glob
import hashlib
import importlib.util
import itertools
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
BACKTICKED = re.compile(r"`([^`\n]+)`")
HTTP_NAME = re.compile(r"^(?:(?:GET|POST|PUT|PATCH|DELETE)\s+)?(/\S*)$")
FLAG_NAME = re.compile(r"^(--[A-Za-z0-9][\w-]*)")
CONTRACT_PATH = re.compile(r"(?<![\w/.])/[^\s`'\",;)]*")
PATH_PARAM = re.compile(r"^(?::\w+|\{[^/}]+\}|<[^/>]+>|\[[^/\]]+\]|\*)$")
PLACEHOLDER = re.compile(r"<[^<>\n]* [^<>\n]*>")
NA = re.compile(r"^n/a:\s*(.*)$")
OBSERVATION = re.compile(r"^\s*(?:[-*]\s+)?`?([^\s:`]+)`?:\s*(.*\S)\s*$")
MISSING = "missing"
NO_EVIDENCE = "none"
HEADER_FIELD = re.compile(r"^(Head|Main|Author|Verifier):\s*(.*)$", re.M)
MIN_REASON = 10
SECTION_META = re.compile(r"^\s*(?:[-*]\s+)?(Head|Reviewer|Fixed at|Relaxed):[ \t]*(.*?)\s*$", re.M)
REVIEW_META = ("Head", "Reviewer")
FIX_REVIEW_META = ("Head", "Reviewer", "Fixed at", "Relaxed")
BULLET = re.compile(r"^\s*[-*] ")
NONE_FOUND = re.compile(r"^none found\.?$", re.I)
BASE_LINE = re.compile(r"^\s*(?:[-*]\s+)?Base:\s*`?([0-9a-fA-F]{7,40})`?\s*$", re.M)
FIXED = re.compile(r"\bTriage:\s*fixed\b", re.I)
TRIAGE = re.compile(r"\bTriage:\s*(fixed|new check|follow-up|pre-existing|dismissed)\b", re.I)
TIERS = ("e2e", "unit", "walk")
TIER_HELP = ("write e2e (isolation, permissions, revocation, wire compatibility, perf, or a cross-surface flow: a script the "
             "verifier writes, run on the real app), unit (logic: a spec the executor writes, graded by `verify.py units`), or "
             "walk (UI look and interaction: walked once on the real app, saved as a screenshot or video)")
MAX_E2E = 10
E2E_COST = (f"E2E is the most expensive tier, so fewer is better: keep only core behavior no unit spec can see, and "
            f"{MAX_E2E} is a ceiling, not a target")
DRIVEN_TIERS = ("e2e", "walk")
CONTRACT = "Drive contract"
SENSITIVE = "Sensitive paths"
FIX_REVIEW = "Fix review"
PROTECTED_FIELDS = ("Scenario", "Pass", "Tier", "Oracle", "Seed", "Tolerance", *PERF_FIELDS)
PREMISES = "premises.md"
GROUNDING = "grounding.md"
PREMISE_COLUMNS = ("check", "premise", "holds", "evidence", "resolution")
OBSERVATIONS = "observations.md"
SPEC = "spec.md"
CHANGE_LOG = "Change log"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm"}
DRIVER_LABELS = ("driver", "harness")
PRODUCT_NAMES = ("DOM handles, routes and HTTP paths, the product's CLI commands and flags, env vars, wire and log event names, "
                 "and file paths the product writes")
BASE_PASSES = re.compile(r"^passes:\s*(\S.*)$")
BASE_FIELD = "- Base: passes: <why the base already has this behavior>"
HOLDS = ("yes", "no", "new")


SPEC_FILE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|[^/]*_spec\.rb|[^/]*Tests?\.(swift|kt|java))$")
GUARD_MARK = "regression-guard"
CHECK_SCRIPT = re.compile(r"^(.+)\.check\.[^.]+$")
SCRIPT_RUNNERS = {".py": [sys.executable], ".sh": ["bash"], ".js": ["node"], ".mjs": ["node"], ".ts": ["npx", "tsx"]}
NODE_LOCKS = {"pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bunx", "bun.lockb": "bunx"}
DEPENDENCY_DIRS = {"node_modules", ".venv", "venv"}
SCRIPT_TIMEOUT = 900
RERUN_TIMEOUT = 7200
RERUN_STAMP = "rerun.stamp.json"
SCRIPTS_LOCK = "scripts.lock.json"
RERUN_LEDGER = "rerun.ledger.json"
FAILURE_STATE = ("head", "script", "product_patch")
STATE_LOCK = ".rerun-state.lock"
TMP_SUFFIX = ".verify-tmp"
RERUN_PASS = "rerun: PASS"
BASE_LOG = ".base.log"
DRYRUN_VERDICT = re.compile(r"^dryrun: (FAIL|PASS|CRASH|INCONCLUSIVE|STALLED)\b")
UNGRADED = {"CRASH": "crashed", "STALLED": "stalled", "INCONCLUSIVE": "was inconclusive"}
DRYRUN_SCRIPT = re.compile(r"^dryrun: script sha256 ([0-9a-f]{64})$", re.M)
FAIL_LINE = re.compile(r"^FAIL\b")
FIX_ATTEMPTS = 2
FIX_LEDGER = "fix-attempts.json"
UNITS_RECORD = "units.json"
UNITS_LOG = "units.log"
REVIEW = "review.md"
HELPER_SUFFIXES = {".mjs", ".cjs", ".js", ".ts", ".py", ".sh"}
EVIDENCE_DIR = "evidence"
LISTED_NAMES = 5
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
STEP_FORMAT = "verify: step <name> within <seconds>"
STEP_LINE = re.compile(r"^verify: step (\S.*?) within (\d+(?:\.\d+)?)$")
FIRST_STEP_S = 120.0
STEP_MARGIN_S = 15.0
STEP_MARGIN_RATIO = 0.25
PROGRESS_POLL_S = 0.5
EXIT_VERDICTS = {0: "PASS", 1: "FAIL", 2: "INCONCLUSIVE", 3: "ENVIRONMENT"}
ENVIRONMENT_REQUEUES = 2
SUMMARY = ".summary"
CAPACITY_POLL_S = 15.0
CAPACITY_WAIT_S = 600.0
OVERLOAD_RATIO = 1.0
OVERLOAD_S = 15.0
WATCH_POLL_S = 3.0
# ps rounds elapsed time to the second, so a start can read up to a second early.
ELAPSED_SLACK_S = 1.0
ELAPSED = re.compile(r"^(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)$")
TOP_CPU = 5
SALVO_GLOBS = ("/tmp/salvo-*", "/private/tmp/salvo-*")
LEAD_MARK = "VERIFY_LEAD=1"
LEAD_IN_COMMAND = re.compile(rf"(?<![\w=]){re.escape(LEAD_MARK)}(?!\w)")
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


def check_base(entry, tier, problems):
    field = entry["fields"].get("Base")
    if field is None:
        return
    number, value = field
    if tier != "e2e":
        problems.append(f"{number}: Base belongs to an e2e or perf check, whose script must fail on base; a unit spec of behavior "
                        f"that already works is marked {GUARD_MARK}")
    elif not (m := BASE_PASSES.match(value)) or len(m.group(1)) < MIN_REASON or PLACEHOLDER.search(value):
        problems.append(f"{number}: Base must read 'passes: <why the base already has this behavior>', the only way a check "
                        "may pass on base")


def lint_plan(text, full=True, frozen=()):
    """Return (problems, check ids, {oracle check id: tolerance}, {check id: tier}) for a plan's text. Without full, only the
    checks part: no Drive contract, names, or Sensitive paths rules. frozen holds the Drive contract lines the plan lock
    already holds, which predate the driver-label rule."""
    problems, ids, oracles, tiers = [], [], {}, {}
    found = sections(text.splitlines())
    checks = []
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
            if tier := tiers.get(entry_id(entry)):
                check_base(entry, tier, problems)
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
            check_base(entry, "e2e", problems)
            ids.append((check_id, entry["line"]))
    for name, body in found.items():
        if name not in ("Checks", "Perf"):
            problems += [f"{n}: {m.group(1)} sits under '## {name}', where no gate reads it; checks go under '## Checks' or '## Perf'"
                         for n, line in body if (m := HEADING.match(line))]
    seen = {}
    for check_id, line in ids:
        if check_id and check_id in seen:
            problems.append(f"{line}: id {check_id!r} is used more than once")
        seen.setdefault(check_id, line)
    problems += e2e_cap_problems(tiers)
    if full:
        problems += contract_problems(found, tiers, frozen) + name_problems(found, checks, tiers)
        problems += [f"{n}: {SENSITIVE} still holds a template placeholder" for n, line in found.get(SENSITIVE, []) if PLACEHOLDER.search(line)]
    return problems, [i for i, _ in ids if i], oracles, tiers


def contract_label(line):
    """The text before a Drive contract line's first colon, without its bullet, emphasis, or backticks."""
    return line.strip().lstrip("-*+ ").partition(":")[0].strip("`*_'\" ")


def contract_problems(found, tiers, frozen=()):
    driven = [i for i, t in tiers.items() if t in DRIVEN_TIERS]
    lines = [(n, line) for n, line in found.get(CONTRACT, []) if line.strip()]
    problems = [f"{n}: {CONTRACT} still holds a template placeholder" for n, line in lines if PLACEHOLDER.search(line)]
    problems += [f"{n}: the {CONTRACT} line '{contract_label(line)}' names a driver command. The contract names product-side names "
                 f"only ({PRODUCT_NAMES}); driver commands are the verifier's own, so drop the line"
                 for n, line in lines if contract_label(line).lower().startswith(DRIVER_LABELS) and line.strip() not in frozen]
    if driven and not lines:
        problems.append(f"1: {', '.join(driven)} {'is an e2e or walk check' if len(driven) == 1 else 'are e2e or walk checks'}, "
                        f"but the plan has no '## {CONTRACT}' listing what they drive. Settle every name before any code: DOM "
                        "test ids and accessible names, routes and HTTP paths, CLI commands and flags, wire and event names, "
                        "and the file paths the checks read")
    return problems


def driven_names(value):
    """The HTTP paths and CLI flags a Scenario or Pass names in backticks."""
    names = []
    for token in BACKTICKED.findall(value):
        token = token.strip()
        if m := HTTP_NAME.match(token):
            names.append(("path", re.split(r"[?#]", m.group(1))[0]))
        elif m := FLAG_NAME.match(token):
            names.append(("flag", m.group(1)))
    return names


def path_matches(path, template):
    want, have = path.strip("/").split("/"), template.rstrip(".").strip("/").split("/")
    return len(want) == len(have) and all(w == h or (w and PATH_PARAM.match(h)) for w, h in zip(want, have))


def in_contract(kind, name, contract):
    if kind == "flag":
        return bool(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", contract))
    if re.search(rf"(?<![\w/.]){re.escape(name)}(?![\w/:{{<.-])", contract):
        return True
    return any(path_matches(name, template) for template in CONTRACT_PATH.findall(contract))


def name_problems(found, checks, tiers):
    """Every HTTP path and CLI flag an e2e or walk check names in backticks in its Scenario or Pass is in the Drive contract."""
    contract = "\n".join(line for _, line in found.get(CONTRACT, []))
    if not contract.strip():
        return []
    problems = []
    for entry in checks:
        check_id = entry_id(entry)
        if tiers.get(check_id) not in DRIVEN_TIERS:
            continue
        for field in ("Scenario", "Pass"):
            number, value = entry["fields"].get(field, (entry["line"], ""))
            for kind, name in dict.fromkeys(driven_names(value)):
                if not in_contract(kind, name, contract):
                    problems.append(f"{number}: {check_id}'s {field} names `{name}`, which the '## {CONTRACT}' does not list. "
                                    f"Settle every {'HTTP path' if kind == 'path' else 'CLI flag'} a check drives there before code")
    return problems


def e2e_cap_problems(tiers):
    e2e = [i for i, t in tiers.items() if t == "e2e"]
    if len(e2e) <= MAX_E2E:
        return []
    return [f"1: {len(e2e)} e2e checks ({', '.join(e2e)}), more than {MAX_E2E}. {E2E_COST}. Move the rest to the unit tier or "
            "drop them, or split the phase"]


def plan_file(directory):
    """The plan every command reads: the phase folder's plan.md that `adopt` recorded, else plan.md in the verification directory."""
    record = base_record(directory)
    return pathlib.Path(record["plan_file"]) if record.get("plan_file") else directory / "plan.md"


def frozen_contract(directory):
    """The Drive contract lines of the plan lock's text, stripped."""
    lock_path = directory / "plan.lock"
    try:
        text = json.loads(lock_path.read_text()).get("text", "") if lock_path.is_file() else ""
    except ValueError:
        return set()
    return {line.strip() for _, line in sections(text.splitlines()).get(CONTRACT, []) if line.strip()}


def load_plan(directory, full=True):
    path = plan_file(directory)
    text = read(path, "plan (write it from the verify skill's references/plan-template.md)")
    problems, ids, oracles, tiers = lint_plan(text, full, frozen_contract(directory) if full else ())
    if problems:
        raise Failed("\n".join(f"{path}:{p}" for p in problems))
    return path, text, ids, oracles, tiers


def cmd_plan(directory, args):
    path, _, ids, oracles, tiers = load_plan(directory, full=not args.checks)
    counts = ", ".join(f"{t} {list(tiers.values()).count(t)}" for t in TIERS)
    what = "checks ok" if args.checks else "plan ok"
    return f"{path}: {what}, {len(ids)} checks, {len(oracles)} oracle checks; tiers: {counts}"


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


def driver_only(commit):
    files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", commit).splitlines()
    return bool(files) and all(is_driver_path(f) for f in files)


def patch_id(commit):
    patch = subprocess.run(["git", "show", commit], capture_output=True).stdout
    words = subprocess.run(["git", "patch-id", "--stable"], input=patch, capture_output=True).stdout.split()
    return words[0].decode() if words else None


def driver_branch(base):
    """The local branch whose commits since base touch only driver paths and match a driver-only commit in HEAD by patch, or None."""
    picked = {patch_id(c) for c in git("rev-list", f"{base}..HEAD").splitlines() if driver_only(c)} - {None}
    if not picked:
        return None
    for ref in git("for-each-ref", "--format=%(refname)", "refs/heads").splitlines():
        commits = git("rev-list", f"{base}..{ref}").splitlines()
        if commits and all(driver_only(c) for c in commits) and any(patch_id(c) in picked for c in commits):
            return ref.removeprefix("refs/heads/")
    return None


def cmd_driver(directory, args):
    top = pathlib.Path(git("rev-parse", "--show-toplevel"))
    drivers = sorted(str(p.parent.relative_to(top)) for d in DRIVER_DIRS for p in top.glob(d + "*/SKILL.md"))
    if not drivers:
        raise Failed("no verification skill in this worktree (.agents/skills/verify-<app>/ or .claude/skills/verify-<app>/). "
                     "Run the create-verification-skill skill in a clean worktree off main, then base this branch on it.")
    main = default_branch()
    if has_driver(main):
        return f"driver ok: {', '.join(drivers)} is on {main}"
    if not has_driver("HEAD"):
        raise Failed("the verification skill is not committed. Commit it before any product change, so the history shows "
                     "it was built from the unchanged app.")
    for commit in git("rev-list", "--reverse", "--topo-order", f"{main}..HEAD").splitlines():
        files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", commit).splitlines()
        if any(not is_driver_path(f) for f in files):
            if has_driver(f"{commit}^"):
                break
            base = phase_base(base_record(directory))
            if branch := driver_branch(base):
                return (f"driver ok: {', '.join(drivers)} was cherry-picked from {branch}, which holds only driver commits since "
                        f"the phase base {base[:12]}")
            raise Failed(f"commit {commit[:12]} changed product files before any commit added the verification skill, "
                         "so the driver may have been fitted to the change. Build it from main first, or on the phase base "
                         "in a branch of driver commits only, and cherry-pick it.")
    return f"driver ok: {', '.join(drivers)} was committed before any product change"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def plan_structure(text):
    """({check id: (heading, {field: value}, [its other lines])}, {section: [lines]}) for a plan: every non-blank line,
    stripped, outside the checks goes under its section ('' before the first)."""
    lines = text.splitlines()
    found = sections(lines)
    checks, other = {}, {"": [line.strip() for line in itertools.takewhile(lambda line: not line.startswith("## "), lines) if line.strip()]}
    for name, body in found.items():
        if name not in ("Checks", "Perf"):
            other[name] = [line.strip() for _, line in body if line.strip()]
            continue
        preamble, found_entries = entries(body)
        other[name] = [line.strip() for _, line in preamble if line.strip()]
        for entry in found_entries:
            if check_id := entry_id(entry):
                rest = [line.strip() for _, line in body_lines(body, entry) if line.strip() and not FIELD.match(line)]
                checks[check_id] = (entry["heading"], {k: v for k, (_, v) in entry["fields"].items()}, rest)
    return checks, other


def body_lines(body, entry):
    """The lines of a check entry after its heading, up to the next heading."""
    after = [(n, line) for n, line in body if n > entry["line"]]
    return list(itertools.takewhile(lambda item: not item[1].startswith("### "), after))


def contract_name(line):
    names = BACKTICKED.findall(line)
    return f"`{names[0]}`" if names else line.removeprefix("- ")[:60]


ADDITIVE = (CONTRACT, SENSITIVE)


def classify_revision(old, new):
    """([why a change needs the user], None), or ([], summary) when the new plan only adds checks, Drive contract lines, or
    Sensitive paths. Any change to an existing check, any removal, and any other edit needs the user."""
    old_checks, old_other = plan_structure(old)
    new_checks, new_other = plan_structure(new)
    needs = []
    for check_id, (heading, fields, rest) in old_checks.items():
        if check_id not in new_checks:
            needs.append(f"{check_id} was removed")
            continue
        new_heading, new_fields, new_rest = new_checks[check_id]
        if heading != new_heading:
            needs.append(f"{check_id} title changed")
        for name in sorted({*fields, *new_fields}, key=lambda f: (f not in PROTECTED_FIELDS, f)):
            if fields.get(name) != new_fields.get(name):
                needs.append(f"{check_id} {name} " + ("removed" if name not in new_fields else "added" if name not in fields else "changed"))
        if rest != new_rest:
            needs.append(f"{check_id} text changed")
    added_lines = {}
    for name in dict.fromkeys([*old_other, *new_other]):
        before, after = collections.Counter(old_other.get(name, [])), collections.Counter(new_other.get(name, []))
        where = f"{name} " if name else "the plan's preamble "
        needs += [f"{where}line removed or changed: {line[:80]}" for line in (before - after).elements()]
        if added := list((after - before).elements()):
            if name in ADDITIVE:
                added_lines[name] = added
            else:
                needs += [f"{where}line added: {line[:80]}" for line in added]
    if needs:
        return needs, None
    checks = [f"{i} ({re.sub(r'^### \S+\.\s*', '', heading).strip()})" for i, (heading, _, _) in new_checks.items() if i not in old_checks]
    parts = [f"additions: {', '.join(checks)}"] if checks else []
    parts += [f"{name}: {', '.join(contract_name(line) for line in added_lines[name])}" for name in ADDITIVE if name in added_lines]
    return [], "; ".join(parts) or "formatting only"


def autorun_store():
    """The autorun skill's run store module, when the skill is installed beside this one, else None."""
    here = pathlib.Path(__file__).resolve()
    home = pathlib.Path.home()
    candidates = [here.parents[3] / "orchestrator" / "autorun", here.parents[2] / "autorun"] if len(here.parents) > 3 else []
    candidates += [home / root / "autorun" for root in (".claude/skills", ".agents/skills", ".codex/skills")]
    for skill in candidates:
        path = skill / "scripts" / "autorun_lib" / "store.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("verify_autorun_store", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def autonomous_run():
    """The active autorun run this command runs in, or None in an interactive session. Best effort: an unreadable store is None."""
    try:
        store = autorun_store()
        run = store.resolve_cli() if store else None
        return run if run and run.active else None
    except Exception:
        return None


def revision_gate(run, gate_id, lock):
    """The id of an answered gate of this autonomous run that backs a plan revision, or Failed."""
    revise = "--revision \"<what changed and why>\" --gate <id>"
    if not gate_id:
        raise Failed(f"this is autonomous run {run.id}, so a change to a check needs the user's answer: ask it as an autorun "
                     f"gate (the autorun skill's ask command), and once the user answered, record it with {revise}")
    gate = next((g for g in run.gates() if g.get("id") == gate_id), None)
    if not gate:
        raise Failed(f"--gate {gate_id}: no gate with that id in autonomous run {run.id}")
    if gate.get("status") != "answered":
        raise Failed(f"gate {gate_id} is not answered yet ({gate.get('status')}); wait for the user's answer, then record the revision")
    if used := next((r for r in lock["revisions"] if r.get("gate") == gate_id), None):
        raise Failed(f"gate {gate_id} already backs the revision of {used['at']}; ask the user again for this change")
    return gate_id


def cmd_freeze(directory, args):
    _, text, _, _, _ = load_plan(directory)
    lock_path = directory / "plan.lock"
    now = utc_now()
    if not lock_path.exists():
        lock_path.write_text(json.dumps({"sha": sha(text), "text": text, "frozen_at": now, "frozen_ts": time.time(), "revisions": []},
                                        indent=2) + "\n")
        return f"plan frozen at {now}"
    lock = json.loads(lock_path.read_text())
    if lock["sha"] == sha(text):
        return "plan unchanged since it was frozen"
    revision = {"at": now, "from": lock["sha"], "to": sha(text)}
    needs, summary = classify_revision(lock["text"], text) if "text" in lock else ([], None)
    if summary and not args.revision:
        revision.update(why=summary, auto=True)
    else:
        if not args.revision or len(args.revision.strip()) < MIN_REASON:
            raise Failed("the plan changed after it was frozen" + (f", beyond adding checks, Drive contract lines, or Sensitive paths: "
                                                                    f"{listed(needs)}" if needs else "")
                         + ". A check changes only when the user agrees it was wrong (a looser perf budget also "
                         "needs vetted evidence and a countersign). Record it with --revision \"<what changed and why>\", plus "
                         "--gate <id> of the autorun gate the user answered in an autonomous run, and the report lists it.")
        revision["why"] = args.revision.strip()
        if run := autonomous_run():
            revision["gate"] = revision_gate(run, args.gate, lock)
        elif args.gate:
            revision["gate"] = args.gate
    lock["revisions"].append(revision)
    lock.update(sha=sha(text), text=text)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    if revision.get("auto"):
        return f"revision recorded automatically: {revision['why']}"
    return f"revision recorded: {revision['why']}" + (f" (gate {revision['gate']})" if revision.get("gate") else "")


BASE_RECORD = "base.json"


def latest_base(branch):
    """(ref, sha) of the latest <branch>, which HEAD must descend from: fetched as origin/<branch>, or the local branch in a
    repository without an origin remote. Failed otherwise."""
    ref = branch
    if "origin" in git("remote").split():
        fetched = subprocess.run(["git", "fetch", "-q", "origin", branch], capture_output=True, text=True)
        if fetched.returncode:
            raise Failed(f"cannot fetch {branch} from origin: {fetched.stderr.strip()}. Name the branch this phase is cut from, "
                         "pushed: `verify.py base <branch>`")
        ref = f"origin/{branch}"
    try:
        tip = git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    except Failed:
        raise Failed(f"no branch {ref} to cut the phase from; name the branch this phase stacks on: `verify.py base <branch>`")
    if not is_ancestor(tip, "HEAD"):
        raise Failed(f"the phase branch is not cut from the latest {branch}; fetch it and cut again: HEAD "
                     f"{git('rev-parse', 'HEAD')[:12]} does not descend from {ref} at {tip[:12]}. A phase stacked on an earlier open "
                     "phase passes that phase's branch")
    return ref, tip


def default_base_branch():
    return default_branch().removeprefix("origin/")


def cmd_base(directory, args):
    if len(args.rest) > 1:
        raise Failed("base takes at most one <branch>")
    branch = args.rest[0] if args.rest else base_record(directory).get("base_branch") or default_base_branch()
    ref, tip = latest_base(branch)
    local = "" if ref.startswith("origin/") else ", the local branch, since no origin remote exists"
    return f"base ok: HEAD descends from {ref} at {tip[:12]}{local}"


def cmd_adopt(directory, args):
    if len(args.rest) != 1:
        raise Failed("adopt takes one <phase folder> from the feature plan")
    folder = pathlib.Path(args.rest[0]).expanduser().resolve()
    path = folder / "plan.md"
    text = read(path, "phase plan")
    problems, ids, _, _ = lint_plan(text, full=False)
    if problems:
        raise Failed("\n".join(f"{path}:{p}" for p in problems))
    record = base_record(directory)
    if record.get("plan_file") and pathlib.Path(record["plan_file"]) != path:
        raise Failed(f"this branch already adopted {record['plan_file']}; one branch carries one phase")
    branch = args.base or default_base_branch()
    latest_base(branch)
    copy = directory / "plan.md"
    if copy.exists():
        if copy.read_text() != text:
            raise Failed(f"{copy} already holds a different plan; this branch adopted another phase or edited it")
        copy.unlink()
    directory.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")
    (directory / BASE_RECORD).write_text(json.dumps({"base": head, "base_branch": branch, "plan": str(folder.parent.parent),
                                                     "plan_file": str(path)}, indent=2) + "\n")
    return f"adopted {folder.name}: {len(ids)} checks, base {head[:12]} on {branch}; every command reads {path}"


def listed(names):
    return ", ".join(names[:LISTED_NAMES]) + (f" and {len(names) - LISTED_NAMES} more" if len(names) > LISTED_NAMES else "")


def plan_skip(directory):
    """The adopted plan folder, which never counts as a product change."""
    record = base_record(directory) if directory else {}
    return [record["plan"]] if record.get("plan") else []


def product_only(names, skip, top):
    skipped = [str(pathlib.Path(s).resolve().relative_to(top.resolve())) for s in skip if under(str(pathlib.Path(s).resolve()), str(top.resolve()))]
    return sorted(n for n in names if n and not n.startswith(DRIVER_DIRS) and not any(n == d or n.startswith(d + "/") for d in skipped))


def product_changes(base, skip, cwd=None):
    """Product paths that differ between base and the working tree, untracked files included."""
    top = pathlib.Path(git("rev-parse", "--show-toplevel", cwd=cwd))
    names = set(git("diff", "--name-only", "--no-renames", base, cwd=cwd).splitlines())
    names |= set(git("ls-files", "--others", "--exclude-standard", cwd=cwd).splitlines())
    return product_only(names, skip, top)


def product_diff(old, new, skip):
    """Product paths that differ between two commits, or None when old is not a commit here."""
    try:
        names = git("diff", "--name-only", "--no-renames", old, new).splitlines()
    except Failed:
        return None
    return product_only(names, skip, pathlib.Path(git("rev-parse", "--show-toplevel")))


def base_record(directory):
    path = directory / BASE_RECORD
    return json.loads(path.read_text()) if path.is_file() else {}


def phase_base(record):
    return record.get("base") or git("merge-base", default_branch(), "HEAD")


def cmd_lock(directory, args):
    _, text, _, _, _ = load_plan(directory)
    lock_path = directory / "plan.lock"
    if lock_path.exists():
        if not json.loads(lock_path.read_text()).get("before_code"):
            raise Failed("the plan was frozen after code existed, so it cannot show it was written first. "
                         "Write the plan before the code on the next change.")
        frozen_lock(directory, text)
        return "plan locked before code, unchanged since or changed only by recorded revisions"
    base = phase_base(base_record(directory))
    changed = product_changes(base, plan_skip(directory))
    if changed:
        raise Failed(f"product files already changed since {base[:12]}: {listed(changed)}. Lock the plan before any code: "
                     "stash or move the change aside, lock, then bring it back.")
    now = utc_now()
    lock_path.write_text(json.dumps({"sha": sha(text), "text": text, "frozen_at": now, "frozen_ts": time.time(), "revisions": [],
                                     "before_code": True, "base": base}, indent=2) + "\n")
    return f"plan locked before code at {now}, base {base[:12]}"


def frozen_lock(directory, text):
    lock_path = directory / "plan.lock"
    if not lock_path.exists():
        raise Failed("the plan was never frozen. Run `verify.py freeze` before a verifier runs, so later edits to it show.")
    lock = json.loads(lock_path.read_text())
    if lock["sha"] != sha(text):
        raise Failed("the plan changed after it was frozen. Run `verify.py freeze`: it records added checks and Drive contract "
                     "lines on its own, and any other change needs --revision \"...\", or restore the frozen plan.")
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


def table_cells(line):
    """A markdown table row's cells; a pipe escaped as \\| stays inside its cell."""
    body = line.strip()[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def table_rows(text):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|") or re.match(r"^\|\s*:?-", line):
            continue
        cells = table_cells(line)
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


def review_meta(body, name):
    """The value of a section's '<name>:' line, '' when the line is empty, or None when there is none."""
    return next((m.group(2).strip("`* ") for m in SECTION_META.finditer(body) if m.group(1) == name), None)


def finding_problems(name, body, meta):
    """Every line of a review section is a meta line, a finding bullet (with its indented continuation), or 'none found'."""
    findings, stray, none = [], [], False
    for line in body.splitlines():
        if not line.strip() or ((m := SECTION_META.match(line)) and m.group(1) in meta):
            continue
        if BULLET.match(line):
            findings.append(line.strip())
        elif NONE_FOUND.match(line.strip()):
            none = True
        elif line[:1].isspace() and findings:
            findings[-1] += " " + line.strip()
        else:
            stray.append(line.strip())
    if not findings and not none and not stray:
        return [f"the '## {name}' section of {REVIEW} is empty; list each finding with its triage, or write 'none found'"]
    problems = [f"the '## {name}' section of {REVIEW} holds a line that is not a finding bullet: {line[:80]}; write each finding "
                "as a bullet with its triage" for line in stray]
    return problems + [f"{name.lower()} finding has no 'Triage: fixed | new check | follow-up | pre-existing | dismissed': {f[:80]}"
                       for f in findings if not TRIAGE.search(f)]


def review_head(text):
    return review_meta(text, "Head") or None


def is_ancestor(old, new):
    return subprocess.run(["git", "merge-base", "--is-ancestor", old, new], capture_output=True).returncode == 0


NO_FIXED_AT = (f"the '## {FIX_REVIEW}' section of {REVIEW} names no 'Fixed at:' line. Once its findings' fixes land, the lead writes "
               "'Fixed at: <sha>', the commit that holds them, or the section's Head when nothing was fixed")


def fixed_at_problems(directory, body, head, fix_head):
    """The fix review's 'Fixed at:' line names the commit that holds its fixes (its Head when nothing was fixed), at or after
    its Head; with fix_head, HEAD holds that commit's product tree, so no product change follows the reviewed fixes."""
    fixed_at, skip = review_meta(body, "Fixed at"), plan_skip(directory)
    if not fixed_at:
        return [NO_FIXED_AT]
    if tree_of(fixed_at) is None:
        return [f"the fix review's Fixed at {fixed_at} is not a commit in this repository"]
    if not is_ancestor(head, fixed_at):
        return [f"the fix review's Fixed at {fixed_at[:12]} does not descend from its Head {head[:12]}; its fixes land after the "
                "head it read"]
    if not FIXED.search(body) and (changed := product_diff(head, fixed_at, skip)):
        return [f"no fix review finding is triaged fixed, yet product files changed from its Head {head[:12]} to Fixed at "
                f"{fixed_at[:12]}: {listed(changed)}. Fixed at is the section's Head when nothing was fixed"]
    if fix_head and not same_product(fixed_at, skip):
        changed = product_diff(fixed_at, "HEAD", skip) or ["HEAD's tree"]
        return [f"product files changed after the fix review's fixes (Fixed at {fixed_at[:12]}): {listed(changed)}. No reviewer "
                "read them: send the same reviewer Mode fix on that diff, then update the section's Head and Fixed at"]
    return []


def reviewer_problems(text, body):
    """The fix review names its Reviewer, the review's own, unless a 'Relaxed: <reason>' line says why another took it."""
    top = review_meta("\n".join(itertools.takewhile(lambda line: not line.startswith("## "), text.splitlines())), "Reviewer") \
        or review_meta(section(text, "Review"), "Reviewer")
    fixer, relaxed = review_meta(body, "Reviewer"), review_meta(body, "Relaxed")
    problems = []
    if not top:
        problems.append(f"{REVIEW} names no 'Reviewer:' line; the reviewer writes its agent:model under the title")
    if not fixer:
        problems.append(f"the '## {FIX_REVIEW}' section of {REVIEW} names no 'Reviewer:' line; the reviewer writes its agent:model there")
    if relaxed is not None and len(relaxed) < MIN_REASON:
        problems.append(f"the '## {FIX_REVIEW}' section's 'Relaxed:' line needs the reason another reviewer took the fix review")
    elif top and fixer and fixer != top and relaxed is None:
        problems.append(f"the fix review's Reviewer {fixer} is not the review's {top}; the same reviewer reviews the fixes. When its "
                        f"quota ran out and `guard.py quota pick --relax` gave another, add 'Relaxed: <reason>' to the section")
    return problems


def relaxed_review(directory):
    """A report note for a fix review another reviewer took, from its 'Relaxed:' line."""
    path = directory / REVIEW
    body = section(path.read_text(), FIX_REVIEW) if path.is_file() else ""
    relaxed = review_meta(body, "Relaxed")
    return [f"fix review relaxed: {review_meta(body, 'Reviewer') or 'another reviewer'} took it: {relaxed}"] if relaxed else []


def review_problems(directory, frozen_ts, in_repo, fix_head=False):
    """review.md: a '## Review' and a '## Fix review', each naming the Head it read and triaging every finding, written after
    the freeze, by the same Reviewer unless relaxed. With fix_head, no product change follows the fix review's Fixed at."""
    path = directory / REVIEW
    if not path.is_file():
        return [f"no {REVIEW}. The reviewer writes a 'Reviewer:' line, then a '## Review' section with the 'Head:' it read and every "
                f"finding triaged, or 'none found'; once the review's fixes land, the same reviewer reviews their diff once into a "
                f"'## {FIX_REVIEW}' section of the same shape, and the lead adds its 'Fixed at:' line"]
    text = path.read_text()
    found = sections(text.splitlines())
    problems = []
    if path.stat().st_mtime < frozen_ts:
        problems.append(f"the review in {REVIEW} predates the frozen plan; review the code that ships, after the freeze")
    if "Review" not in found:
        problems.append(f"{REVIEW} has no '## Review' section; the reviewer writes the 'Head:' it read as its first line, then "
                        "each finding triaged, or 'none found'")
    else:
        body = "\n".join(line for _, line in found["Review"])
        problems += finding_problems("Review", body, REVIEW_META)
        reviewed = review_head(body)
        if not reviewed:
            problems.append(f"the '## Review' section of {REVIEW} names no 'Head:' line; the reviewer writes the commit it read "
                            "as the section's first line")
        elif in_repo and tree_of(reviewed) is None:
            problems.append(f"{REVIEW} reviewed Head {reviewed}, which is not a commit in this repository")
    if FIX_REVIEW not in found:
        problems.append(f"{REVIEW} has no '## {FIX_REVIEW}' section. Once the review's fixes land, the same reviewer reviews their "
                        "diff once, writes the 'Head:' it read, and triages every finding, or writes 'none found'")
        return problems
    body = "\n".join(line for _, line in found[FIX_REVIEW])
    problems += finding_problems(FIX_REVIEW, body, FIX_REVIEW_META) + reviewer_problems(text, body)
    fixed = review_head(body)
    if not fixed:
        problems.append(f"the '## {FIX_REVIEW}' section of {REVIEW} names no 'Head:' line; the reviewer writes the commit it "
                        "read as the section's first line")
    elif in_repo and tree_of(fixed) is None:
        problems.append(f"the fix review read Head {fixed}, which is not a commit in this repository")
    elif in_repo:
        problems += fixed_at_problems(directory, body, fixed, fix_head)
    if not in_repo and not review_meta(body, "Fixed at"):
        problems.append(NO_FIXED_AT)
    return problems


def load_units(directory):
    try:
        return json.loads((directory / UNITS_RECORD).read_text())
    except (OSError, ValueError):
        return None


def last_line(path):
    return path.read_text(errors="replace").rstrip("\n").rpartition("\n")[2]


def same_product(rev, skip):
    """Whether rev holds HEAD's product code: HEAD's tree, or a tree that differs only in the adopted plan folder or the driver."""
    if not rev or not tree_of(rev):
        return False
    return tree_of(rev) == tree_of("HEAD") or product_diff(rev, "HEAD", skip) == []


def units_gap(check_id, frozen_ts, units, skip):
    if not units:
        return "no `verify.py units` result is recorded; run it once the code lands"
    if units.get("at", 0) < frozen_ts:
        return "the recorded `verify.py units` result predates the frozen plan; run it again"
    if not units.get("passed"):
        return "the last `verify.py units` run failed; fix what it reports and run it again"
    head_tree = tree_of("HEAD")
    if head_tree and units.get("tree") != head_tree and not same_product(units.get("head"), skip):
        return "the last `verify.py units` ran on other product code than HEAD's; run it again on the code that ships"
    if not any(check_id in spec["checks"] and spec["verdict"] in ("ok", "guard") for spec in units.get("specs", {}).values()):
        return (f"no spec in the last `verify.py units` run names {check_id}; put the check id in the title of the test that "
                "proves it, then run units again")
    return None


def run_gap(check_id, entry, skip):
    """Why the ledger's latest run of an e2e check does not grade HEAD's product code, or None."""
    if not entry:
        return f"{RERUN_LEDGER} records no run of it; run `verify.py rerun --only {check_id}`"
    at, head = entry.get("at"), entry.get("head")
    if entry.get("verdict") != "PASS":
        return f"its latest run, at {at}, failed"
    if not head:
        return f"its latest run, at {at}, ran outside a git repository"
    changed = product_diff(head, "HEAD", skip)
    if changed is None:
        return f"its latest run, at {at}, ran on {head[:12]}, which is not a commit in this repository"
    if changed:
        return (f"product files changed since its latest passing run at {at} on {head[:12]}: {listed(changed)}; rerun it once "
                "every fix has landed")
    if dirty := entry.get("product_dirty"):
        return f"its latest passing run, at {at}, graded uncommitted product changes ({listed(dirty)}); commit them, then rerun it"
    return None


def grading(directory, lock):
    in_repo = head_sha() is not None
    return {"frozen_ts": lock["frozen_ts"], "scripts": {script_id(p) for p in check_scripts(directory)}, "units": load_units(directory),
            "ledger": load_ledger(directory), "skip": plan_skip(directory), "in_repo": in_repo}


def tier_gap(directory, check_id, tier, graded):
    """Why a PASS lacks the evidence its tier needs, or None."""
    frozen_ts = graded["frozen_ts"]
    if tier == "unit":
        return units_gap(check_id, frozen_ts, graded["units"], graded["skip"])
    if tier == "e2e":
        log = directory / f"{check_id}.rerun.log"
        if check_id not in graded["scripts"]:
            return (f"no {check_id}.check.<ext> script is saved; the verifier writes it from the plan and the driver, and "
                    "`verify.py rerun` grades it")
        if not log.is_file() or log.stat().st_mtime < frozen_ts:
            return f"{log.name} is missing or predates the frozen plan; run `verify.py rerun` after the freeze"
        if last_line(log) != RERUN_PASS:
            return f"{log.name} records a failing run; a PASS needs a passing `verify.py rerun`"
        if graded["in_repo"] and (gap := run_gap(check_id, graded["ledger"].get(check_id), graded["skip"])):
            return gap
        return None
    if not walk_media(directory, check_id, frozen_ts):
        return (f"{EVIDENCE_DIR}/{check_id}/ holds no screenshot or video written after the freeze; walk it on the real app "
                "and save one there")
    return None


def walk_media(directory, check_id, frozen_ts):
    folder = directory / EVIDENCE_DIR / check_id
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES
            and p.stat().st_size and p.stat().st_mtime >= frozen_ts] if folder.is_dir() else []


def report_notes(directory, lock):
    scripts_lock = load_scripts_lock(directory) or {}
    notes = relaxed_review(directory) + [f"revision {r['at']}{' (automatic)' if r.get('auto') else ''}: {r['why']}" + (f" (gate {r['gate']})" if r.get("gate") else "")
             for r in lock["revisions"]]
    notes += [f"full rerun {r['at']}: {r['why']}" for r in scripts_lock.get("full_reruns", [])]
    notes += [f"script fix {r['at']} {r['file']}: {r['why']}" for r in scripts_lock.get("script_fixes", [])]
    return notes


def cmd_report(directory, args):
    if args.write:
        written, notes = write_report(directory, args)
        try:
            gate = report_gate(directory)
        except Failed as e:
            raise Failed("\n".join([f"wrote {written}, but the report gate fails:", *notes, str(e)]))
        return "\n".join([f"wrote {written}", *notes, gate])
    return report_gate(directory)


def report_gate(directory):
    _, text, ids, oracles, tiers = load_plan(directory)
    lock = frozen_lock(directory, text)
    path = directory / "report.md"
    report = read(path, "report (build it with `verify.py report --write`)")
    problems = []
    header = dict(HEADER_FIELD.findall(report))
    for name in ("Head", "Main", "Author", "Verifier"):
        value = header.get(name, "").strip()
        if not value or PLACEHOLDER.search(value):
            problems.append(f"missing '{name}:' line")
    reported_head = header.get("Head", "").strip()
    current_head = head_sha()
    same_tree = None
    if current_head and reported_head and not (len(reported_head) >= 7 and current_head.startswith(reported_head)):
        reported_tree = tree_of(reported_head)
        if reported_tree and reported_tree == tree_of("HEAD"):
            same_tree = f"Head {reported_head} has the same tree as HEAD {current_head[:12]}"
        elif same_product(reported_head, plan_skip(directory)):
            same_tree = f"Head {reported_head} differs from HEAD {current_head[:12]} only in the plan folder or the driver"
        else:
            problems.append(f"the report covers Head {reported_head}, but HEAD is now {current_head[:12]}; regrade the code that ships "
                            "with `verify.py rerun` and `verify.py units`, walk again each walk check the later commits touch, "
                            "then set Head")
    if header.get("Author", "").strip() and header.get("Author", "").strip() == header.get("Verifier", "").strip():
        problems.append("the Verifier is the Author; a fresh agent must produce the verdicts")
    graded = grading(directory, lock)
    problems += review_problems(directory, lock["frozen_ts"], graded["in_repo"])
    rows = {}
    for number, cells in table_rows(report):
        if len(cells) < 4:
            problems.append(f"{number}: a row needs Check | Verdict | Evidence | Observed")
            continue
        rows.setdefault(cells[0], (number, cells))
    not_ready = []
    for check_id in ids:
        if check_id not in rows:
            problems.append(f"check {check_id} has no row")
            continue
        number, (_, verdict, evidence, observed, *_) = rows[check_id]
        if verdict not in VERDICTS:
            problems.append(f"{number}: verdict must be one of {', '.join(VERDICTS)}")
        if not observed or observed == MISSING:
            problems.append(f"{number}: {check_id} has no observation; the verifier writes '{check_id}: <what it saw>' in "
                            f"{OBSERVATIONS}, then `verify.py report --write` fills the cell")
        elif verdict == "FAIL" and not observed.lower().startswith("defect:"):
            problems.append(f"{number}: {check_id} is FAIL; start its Observed cell with 'defect:' and the repro")
        elif verdict == "INCONCLUSIVE" and not observed.lower().startswith("blocker:"):
            problems.append(f"{number}: {check_id} is INCONCLUSIVE; start its Observed cell with 'blocker:' and what stopped it")
        if verdict in ("FAIL", "INCONCLUSIVE"):
            not_ready.append(f"{check_id} {verdict}")
        if verdict == "INCONCLUSIVE":
            continue
        files = [e.strip().strip("`") for e in split_cell(evidence) if e.strip() and e.strip() != NO_EVIDENCE]
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
            if gap := tier_gap(directory, check_id, tier, graded):
                problems.append(f"{number}: {check_id} is {'an' if tier == 'e2e' else 'a'} {tier} check marked PASS, but {gap}")
    if problems:
        raise Failed("\n".join(f"{path}: {p}" for p in problems))
    notes = report_notes(directory, lock)
    if not_ready:
        notes.insert(0, f"not ready to merge: {', '.join(not_ready)}; the PR lists them at the top and carries the 'do not merge' label")
    return "\n  ".join([f"report ok: {len(ids)} checks have verdicts backed by evidence", *([same_tree] if same_tree else []), *notes])


def observations(directory, ids):
    path = directory / OBSERVATIONS
    found = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if (m := OBSERVATION.match(line)) and m.group(1) in ids:
                found[m.group(1)] = m.group(2)
    return found


def check_state(directory, check_id, tier, graded, oracles, lock):
    """(pass, fail, or missing; the Evidence cell; why it is not a pass) from the evidence on disk for one check."""
    frozen_ts = graded["frozen_ts"]
    if tier == "e2e":
        log = directory / f"{check_id}.rerun.log"
        evidence = [log.name] if log.is_file() else []
        if check_id not in graded["scripts"] or not log.is_file() or log.stat().st_mtime < frozen_ts:
            state, why = "missing", tier_gap(directory, check_id, tier, graded)
        elif last_line(log) != RERUN_PASS:
            state, why = "fail" if last_line(log).startswith("rerun: FAIL") else "missing", last_line(log)
        else:
            why = tier_gap(directory, check_id, tier, graded)
            state = "missing" if why else "pass"
    elif tier == "unit":
        evidence = [UNITS_LOG] if (directory / UNITS_LOG).is_file() else []
        why = units_gap(check_id, frozen_ts, graded["units"], graded["skip"])
        units = graded["units"] or {}
        broken = [name for name, spec in units.get("specs", {}).items() if check_id in spec["checks"] and spec["verdict"] in ("broken", "vacuous")]
        current = units.get("at", 0) >= frozen_ts and (units.get("tree") == tree_of("HEAD") or same_product(units.get("head"), graded["skip"]))
        state = "pass" if not why else "fail" if broken and current else "missing"
        why = f"{', '.join(broken)} fails at head or passes on base" if state == "fail" else why
    else:
        evidence = [f"{EVIDENCE_DIR}/{check_id}/"] if walk_media(directory, check_id, frozen_ts) else []
        why = tier_gap(directory, check_id, tier, graded)
        state = "missing" if why else "pass"
    if check_id in oracles:
        evidence += [n for n in (f"{check_id}.expected.json", f"{check_id}.observed.json") if (directory / n).is_file()]
        file_problems, diffs = compare_oracle(directory, check_id, oracles[check_id], lock)
        if state == "pass" and (file_problems or diffs):
            state, why = ("missing", file_problems[0]) if file_problems else ("fail", f"observed differs from the oracle: {diffs[0]}")
    return state, ", ".join(evidence) or NO_EVIDENCE, why


def row_verdict(state, observed):
    if observed.lower().startswith("defect:"):
        return "FAIL"
    if observed.lower().startswith("blocker:"):
        return "INCONCLUSIVE"
    return {"pass": "PASS", "fail": "FAIL"}.get(state, "INCONCLUSIVE")


def write_report(directory, args):
    """Build report.md from the evidence on disk and the verifier's observations.md; returns (path, notes on non-PASS rows)."""
    _, text, ids, oracles, tiers = load_plan(directory)
    lock = frozen_lock(directory, text)
    path = directory / "report.md"
    previous = path.read_text() if path.is_file() else ""
    header = dict(HEADER_FIELD.findall(previous))
    author = (args.author or header.get("Author", "")).strip()
    verifier = (args.verifier or header.get("Verifier", "")).strip()
    if not author or not verifier:
        raise Failed("report --write needs --author <agent:model that wrote the code> and --verifier <agent:model that graded it>")
    head = head_sha()
    if head is None:
        raise Failed("report --write reads HEAD and main, so run it inside the repository")
    main = git("rev-parse", default_branch())
    graded, seen = grading(directory, lock), observations(directory, ids)
    rows, not_ready, notes = [], [], []
    for check_id in ids:
        state, evidence, why = check_state(directory, check_id, tiers[check_id], graded, oracles, lock)
        observed = seen.get(check_id, MISSING)
        verdict = row_verdict(state, observed)
        rows.append(f"| {check_id} | {verdict} | {evidence} | {observed.replace('|', chr(92) + '|')} |")
        if verdict != "PASS":
            not_ready.append(f"- {check_id} {verdict}: {observed}")
            notes.append(f"  {check_id} {verdict}" + (f": {why}" if why and state != "pass" else ""))
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
    title = re.sub(r"^Verification plan:\s*", "", title) or plan_file(directory).parent.name
    lines = [f"# Verification report: {title}", ""]
    if not_ready:
        lines += ["## Not ready to merge", "", *not_ready, ""]
    lines += [f"Head: {head}", f"Main: {main}", f"Author: {author}", f"Verifier: {verifier}", "",
              "| Check | Verdict | Evidence | Observed |", "|---|---|---|---|", *rows, ""]
    if extra := report_notes(directory, lock):
        lines += ["## Revisions and fixes", "", *(f"- {note}" for note in extra), ""]
    kept = [line[2:].strip() for line in section(previous, "Notes").splitlines() if line.startswith("- ")]
    if given := [note.strip() for note in args.note if note.strip()] if args.note is not None else kept:
        lines += ["## Notes", "", *(f"- {note}" for note in given), ""]
    path.write_text("\n".join(lines))
    return path, notes


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


def script_hashes(directory, scripts):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted({*scripts, *helper_files(directory)})}


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def head_sha():
    try:
        return git("rev-parse", "HEAD")
    except Failed:
        return None


@contextlib.contextmanager
def rerun_state(directory):
    """Hold the verification directory's rerun bookkeeping: scripts.lock.json, the run ledger, the fix ledger, the stamp,
    and the <id>.rerun.log files. Concurrent reruns serialize their updates here while their scripts run in parallel."""
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / STATE_LOCK, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        yield


def write_json(path, data):
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}{TMP_SUFFIX}")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def load_scripts_lock(directory):
    path = directory / SCRIPTS_LOCK
    return load_json(path) if path.is_file() else None


def write_scripts_lock(directory, lock):
    write_json(directory / SCRIPTS_LOCK, lock)


def unrecorded_edits(directory, lock):
    """Locked files whose content changed since the lock recorded them; a deleted file runs nothing, so it is not one."""
    return sorted(name for name, digest in lock["files"].items()
                  if (directory / name).is_file() and hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest)


def hold_script_lock(directory, lock):
    """Refuse to run while a locked file holds an unrecorded edit, and lock any check script or helper that is new since."""
    if lock is None:
        return
    edited = unrecorded_edits(directory, lock)
    if edited:
        script = shlex.quote(str(pathlib.Path(__file__).resolve()))
        raise Failed(f"{', '.join(edited)} changed since {SCRIPTS_LOCK} recorded {'it' if len(edited) == 1 else 'them'}, so a "
                     "rerun would grade an edit nobody explained. Record why each one changed with: "
                     + "; ".join(f"python3 {script} script-fix {shlex.quote(name)} --reason \"<why it crashed before its predicate>\""
                                 for name in edited))
    current = script_hashes(directory, check_scripts(directory))
    if new := {name: digest for name, digest in current.items() if name not in lock["files"]}:
        lock["files"].update(new)
        write_scripts_lock(directory, lock)


def claim_full_rerun(directory, lock, scripts, args):
    """Write the scripts lock for the prove's full rerun, or record an agreed later one; refuse any other."""
    if lock is None:
        write_scripts_lock(directory, {"at": now_iso(), "head": head_sha(), "files": script_hashes(directory, scripts),
                                       "full_reruns": [], "script_fixes": []})
        return
    if not args.full_reason or len(args.full_reason.strip()) < MIN_REASON:
        stale = stale_checks(directory)
        grade = (f"`verify.py rerun --only {' '.join(stale)}`, the checks whose latest run failed or predates a product change"
                 if stale else "nothing: every check's latest run passed on HEAD's product code")
        raise Failed(f"the prove's full rerun already ran at {lock['at']}. Grade later changes with {grade}. A full rerun needs "
                     "--full-reason \"<why; agreed by whom>\", and the report lists it.")
    lock.setdefault("full_reruns", []).append({"at": now_iso(), "why": args.full_reason.strip()})
    lock["files"] = script_hashes(directory, scripts)
    write_scripts_lock(directory, lock)


def cmd_script_fix(directory, args):
    if len(args.rest) != 1:
        raise Failed("script-fix takes one <file>: a check script or helper in the verification directory")
    if not args.reason or len(args.reason.strip()) < MIN_REASON:
        raise Failed("script-fix needs --reason \"<why it crashed before its predicate>\"")
    with rerun_state(directory):
        return record_script_fix(directory, args)


def record_script_fix(directory, args):
    lock = load_scripts_lock(directory)
    if lock is None:
        raise Failed(f"no {SCRIPTS_LOCK} in {directory}; the prove's full `verify.py rerun` writes it, and until then a "
                     "script changes freely")
    given = pathlib.Path(args.rest[0]).expanduser()
    path = (given if given.is_absolute() else directory / given).resolve()
    name = str(path.relative_to(directory.resolve())) if under(str(path), str(directory.resolve())) else str(given)
    if name not in lock["files"] or not path.is_file():
        raise Failed(f"{name} is not a check script or helper that {SCRIPTS_LOCK} recorded; locked: {', '.join(sorted(lock['files']))}")
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if after == lock["files"][name]:
        raise Failed(f"{name} is unchanged since {SCRIPTS_LOCK} recorded it; script-fix records an edit, so edit it first")
    lock.setdefault("script_fixes", []).append({"at": now_iso(), "file": name, "before": lock["files"][name], "after": after,
                                                "why": args.reason.strip()})
    lock["files"][name] = after
    write_scripts_lock(directory, lock)
    return f"script fix recorded for {name}: {args.reason.strip()}"


def working_state(directory):
    """(HEAD, a hash of the tracked working-tree diff or None when it is clean, the product paths that diff touches, a hash of
    the product part of that diff or None), or (None, None, [], None) outside a git repository."""
    head = head_sha()
    if head is None:
        return None, None, [], None
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True)
    dirty = hashlib.sha256(diff.stdout).hexdigest() if diff.returncode == 0 and diff.stdout else None
    names = git("diff", "--name-only", "--no-renames", "HEAD").splitlines() if dirty else []
    product = product_only(names, plan_skip(directory), pathlib.Path(git("rev-parse", "--show-toplevel")))
    patch = subprocess.run(["git", "diff", "HEAD", "--", *product], capture_output=True).stdout if product else b""
    return head, dirty, product, hashlib.sha256(patch).hexdigest() if patch else None


def load_ledger(directory):
    path = directory / RERUN_LEDGER
    return load_json(path) if path.is_file() else {}


def last_failure(entry):
    """The state of the latest failing run a ledger entry knows: the entry itself when it failed, else the one it carries."""
    if not entry:
        return None
    if entry.get("verdict") == "FAIL":
        return {key: entry.get(key) for key in FAILURE_STATE}
    return entry.get("last_failure")


def record_run(directory, path, verdict, state):
    """Record a check's run as its latest in the ledger, and spend its fix budget when the run is a fix attempt; return that
    budget line, or None. The caller holds rerun_state, with the run's log just written, so a run is weighed against the
    failing run the ledger holds at this moment, one that finished beside it included."""
    check_id = script_id(path)
    head, dirty, product_dirty, product_patch = state
    script = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    ledger = load_ledger(directory)
    previous = last_failure(ledger.get(check_id))
    entry = {"head": head, "dirty": dirty, "product_dirty": product_dirty, "product_patch": product_patch, "script": script,
             "verdict": verdict, "at": now_iso()}
    if verdict != "FAIL" and previous:
        entry["last_failure"] = previous
    ledger[check_id] = entry
    write_json(directory / RERUN_LEDGER, dict(sorted(ledger.items())))
    return spend_fix_budget(directory, check_id, previous, state, script) if verdict == "FAIL" else None


def spend_fix_budget(directory, check_id, previous, state, script):
    """The budget line for a failing run, counting it in the fix ledger when report.md marks the check FAIL and the run is a
    fix attempt; None for a check the report does not mark FAIL."""
    if check_id not in reported_failures(directory):
        return None
    if not fix_attempt(previous, state, script, plan_skip(directory)):
        return (f"{check_id} still fails with no product or script change since its previous failing run, so this run is not a "
                "fix attempt")
    attempts = fix_attempts(directory)
    spent = attempts.get(check_id, 0)
    if spent >= FIX_ATTEMPTS:
        return f"{check_id} still fails, and a run beside this one spent its fix budget, so the next rerun skips it"
    attempts[check_id] = spent + 1
    write_json(directory / FIX_LEDGER, attempts)
    return (f"fix attempt {spent + 1} of {FIX_ATTEMPTS} for {check_id} failed"
            + ("; that was the last one, so the next rerun skips it" if spent + 1 >= FIX_ATTEMPTS else ""))


def stale_checks(directory):
    """The saved check scripts whose latest run failed or does not grade HEAD's product code, leaving out a check past its fix
    budget, which `rerun --only` refuses."""
    if head_sha() is None:
        return []
    failing, attempts = reported_failures(directory), fix_attempts(directory)
    ledger, skip = load_ledger(directory), plan_skip(directory)
    return [i for i in (script_id(p) for p in check_scripts(directory))
            if not (i in failing and attempts.get(i, 0) >= FIX_ATTEMPTS) and run_gap(i, ledger.get(i), skip)]


def rerun_inputs(directory, scripts, rest, left):
    """What a passing rerun depends on, or None outside a git repository."""
    tree = tree_of("HEAD")
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True)
    if not tree or diff.returncode:
        return None
    return {"args": rest, "tree": tree, "diff": hashlib.sha256(diff.stdout).hexdigest(), "files": script_hashes(directory, scripts), "left": left}


def file_sizes(directory):
    sizes = {}
    for root, dirs, names in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in DEPENDENCY_DIRS]
        for name in (n for n in names if not n.endswith(TMP_SUFFIX)):
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
    if len(lost) > LISTED_NAMES:
        lost = [*lost[:LISTED_NAMES], f"and {len(lost) - LISTED_NAMES} more"]
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


def could_not_run(error):
    return f"verify could not run it: {type(error).__name__}: {error}"


def supervised_run(path, args, env, run, cwd=None):
    """One run of a check script under progress supervision: its exit code, stdout, output, whether it printed READY_LINE,
    its last step and output line, and, when verify stopped it (killed) or could not start it, the verdict and reason."""
    progress, seen = {"step": None, "last": ""}, threading.Event()

    def on_ready():
        seen.set()
        if run:
            run["ready"]()
    hooks = {"on_start": lambda pid: run.update(pid=pid)} if run else {}
    outcome = {"code": None, "stdout": "", "output": "", "verdict": None, "reason": "", "killed": False}
    command = script_command(path)
    if not command:
        outcome.update(verdict="CRASH", reason=f"{path.name} is not executable and has no interpreter for {path.suffix}")
    else:
        try:
            r = run_in_group([*command, *args.rest], args.timeout, cwd=cwd, env=env, on_ready=on_ready, progress=progress, **hooks)
            outcome.update(code=r.returncode, stdout=r.stdout, output=(r.stdout + r.stderr).strip("\n"))
        except Stalled as e:
            outcome.update(verdict="STALLED", reason=str(e), output=(e.output + e.stderr).strip("\n"), killed=True)
        except subprocess.TimeoutExpired as e:
            outcome.update(verdict="CRASH", reason=f"timed out after {args.timeout}s, the --timeout safety net",
                           output=((e.output or "") + (e.stderr or "")).strip("\n"), killed=True)
        except Exception as e:
            outcome.update(verdict="CRASH", reason=could_not_run(e))
    return {**outcome, "ready": seen.is_set(), "step": progress["step"], "last": progress["last"]}


def rerun_verdict(outcome):
    """(verdict, reason) of a rerun: the class of its exit code (EXIT_VERDICTS, else CRASH), or why verify stopped it."""
    if outcome["verdict"]:
        return outcome["verdict"], outcome["reason"]
    code, last = outcome["code"], outcome["last"]
    verdict = EXIT_VERDICTS.get(code, "CRASH")
    return verdict, "" if verdict == "PASS" else f"exit {code}" + (f": {last}" if last else "")


def environment_retry(verdict, reason, run):
    """An ENVIRONMENT run with requeues left stays ENVIRONMENT, for run_checks to queue again; past them it is INCONCLUSIVE."""
    if verdict != "ENVIRONMENT" or (run and not run["last_chance"]):
        return verdict, reason
    return "INCONCLUSIVE", f"environment: {reason}"


def verdict_tail(verdict, step, reason):
    """'[step <name>] [<reason>]' on one line: where a run that did not pass ended, and why."""
    return " ".join([*([f"step {step}"] if step and verdict != "PASS" else []), *([" ".join(reason.split())] if reason else [])])


def compact_line(check_id, verdict, seconds, step, reason):
    """`<id> <VERDICT> <seconds>s [step <name>] [<reason>]`: one line per script, for an agent that opens a log only on FAIL."""
    return " ".join([check_id, verdict, f"{seconds:.1f}s", *filter(None, [verdict_tail(verdict, step, reason)])])


def write_summary(directory, kind, lines):
    (directory / f"{kind}{SUMMARY}").write_text("".join(f"{line}\n" for line in lines))


def run_check(directory, path, args, env, concurrent=set, run=None, record=None):
    """(verdict, reason, step) for one check script; its output and verdict go to <id>.rerun.log, and record(path, verdict)
    runs in the same locked step, a script verify could not start included. concurrent() names the checks that ran beside
    it. run, when given, learns the script's pid and readiness; a run the watchdog evicted is REQUEUED, and an ENVIRONMENT
    run with requeues left records nothing."""
    check_id = script_id(path)
    before = file_sizes(directory)
    outcome = supervised_run(path, args, env, run)
    if run and run["evicted"]:
        return "REQUEUED", "", None
    verdict, reason = environment_retry(*rerun_verdict(outcome), run)
    if verdict == "ENVIRONMENT":
        return verdict, reason, outcome["step"]
    beside = sorted(concurrent())
    lost = lost_files(before, file_sizes(directory), {check_id, *beside})
    if lost:
        verdict = "FAIL"
        culprit = f"files that are not its own were deleted or emptied while it ran beside {', '.join(beside)}" if beside else \
            "deleted or emptied files that are not its own"
        reason = f"{culprit}: {', '.join(lost)}" + (f"; {reason}" if reason else "")
    output, tail = outcome["output"], verdict_tail(verdict, outcome["step"], reason)
    with rerun_state(directory):
        (directory / f"{check_id}.rerun.log").write_text((output + "\n" if output else "") + f"rerun: {verdict}"
                                                         + (f" ({tail})" if tail else "") + "\n")
        if record:
            record(path, verdict)
    return verdict, reason, outcome["step"]


def run_checks(directory, scripts, args, run_one):
    """({check id: (verdict, detail, seconds, step)}, [requeue lines]). A script starts while every running one has printed
    READY_LINE, the running count is under --jobs when given, and the machine has capacity; a script that waits
    CAPACITY_WAIT_S for capacity is queued again behind the rest, and after a second such wait it is NOT-RUN. The watchdog
    evicts the newest while the load stays overloaded. An ENVIRONMENT run is queued again, up to ENVIRONMENT_REQUEUES times.
    Perf checks run alone at the end."""
    perf = perf_ids(directory)
    batches = (([p for p in scripts if script_id(p) not in perf], args.jobs), ([p for p in scripts if script_id(p) in perf], 1))
    results, beside, running, requeued = {}, {}, {}, []
    queue = collections.deque()
    turn = threading.Condition()
    jobs = args.jobs
    waits, environment = collections.Counter(), collections.Counter()
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
            verdict, detail, step = run_one(run["path"], lambda: beside_of(check_id), run)
        except Exception as e:
            verdict, detail, step = "ERROR", could_not_run(e), None
        with turn:
            running.pop(check_id, None)
            if verdict == "REQUEUED":
                queue.appendleft(run["path"])
            elif verdict == "ENVIRONMENT":
                environment[check_id] += 1
                queue.append(run["path"])
                requeued.append(f"REQUEUED {check_id}  {detail}: the instance or machine could not support the run; queued again "
                                f"for when `capacity` passes ({environment[check_id]} of {ENVIRONMENT_REQUEUES})")
            else:
                results[check_id] = (verdict, detail, time.time() - started, step)
            turn.notify_all()

    def room(width):
        ceiling = min((n for n in (width, jobs) if n is not None), default=None)
        return not running or ((ceiling is None or len(running) < ceiling) and all(r["is_ready"] for r in running.values()))

    over_since, sampled, refused_since, next_check = None, 0.0, None, 0.0
    with turn:
        for batch, width in batches:
            queue.extend(batch)
            while queue or running:
                now = time.monotonic()
                if (args.jobs is None or args.jobs > 1) and now - sampled >= WATCH_POLL_S:
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
                if not (queue and room(width)):
                    refused_since = None
                elif now >= next_check and has_capacity():
                    path = queue.popleft()
                    check_id = script_id(path)
                    beside[check_id] = set(running)
                    for other in running:
                        beside[other].add(check_id)
                    run = {"path": path, "started": time.time(), "pid": None, "is_ready": False, "evicted": False,
                           "last_chance": environment[check_id] >= ENVIRONMENT_REQUEUES}
                    run["ready"] = lambda run=run: ready(run)
                    running[check_id] = run
                    threading.Thread(target=work, args=(check_id, run), daemon=True).start()
                    refused_since, next_check = None, 0.0
                    continue
                elif now >= next_check:
                    refused_since = refused_since or now
                    next_check = now + CAPACITY_POLL_S
                if refused_since is not None and now - refused_since >= CAPACITY_WAIT_S:
                    path = queue.popleft()
                    check_id = script_id(path)
                    waits[check_id] += 1
                    load, cores = os.getloadavg()[0], os.cpu_count() or 1
                    why = (f"waited {CAPACITY_WAIT_S / 60:g} min for capacity (load {load:.1f} on {cores} cores, threshold "
                           f"{load_ratio() * cores:.1f})")
                    if waits[check_id] == 1:
                        queue.append(path)
                        requeued.append(f"REQUEUED {check_id}  {why}; queued again behind the rest")
                    else:
                        results[check_id] = ("NOT-RUN", f"{why} twice; run it with --only {check_id} once the machine has room",
                                             0.0, None)
                    refused_since, next_check = None, 0.0
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


def spent_line(check_id):
    return (f"SKIP  {check_id}  its fix budget is spent: {FIX_ATTEMPTS} failed fix attempts since report.md marked it FAIL. "
            "Take it to the user with its repro, what each fix changed, and the premise the fixes shared, or in an autonomous "
            "run put it in the project's backlog with the fix you recommend and leave it FAIL in report.md. Only the user grants "
            f"another attempt, by deleting its entry from {FIX_LEDGER}")


def fix_attempt(previous, state, script_sha, skip):
    """Whether a failing run of a FAIL-marked check is a fix attempt: a product file or its script changed since previous, the
    state of its previous failing run. Outside a git repository every failing run is one."""
    head, _, _, patch = state
    if head is None or not previous or not previous.get("head"):
        return True
    if previous.get("script") != script_sha or previous.get("product_patch") != patch:
        return True
    changed = product_diff(previous["head"], head, skip)
    return changed is None or bool(changed)


def cmd_rerun(directory, args):
    if args.only == []:
        return "rerun --only: no check ids given, so nothing to rerun"
    scripts = check_scripts(directory)
    if args.only:
        scripts = only_scripts(scripts, args.only)
    if not scripts:
        return f"no saved check scripts (<id>.check.<ext>) in {directory}; nothing to rerun"
    with rerun_state(directory):
        failing, attempts = reported_failures(directory), fix_attempts(directory)
        left = sorted(i for i in failing if attempts.get(i, 0) >= FIX_ATTEMPTS)
        skipped = [script_id(p) for p in scripts if script_id(p) in left]
        lock = load_scripts_lock(directory)
        hold_script_lock(directory, lock)
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
            claim_full_rerun(directory, lock, check_scripts(directory), args)
            stamp_path.unlink(missing_ok=True)
    runnable = [p for p in scripts if script_id(p) not in left]
    env = {**os.environ, "VERIFY_DIR": str(directory)}
    state, budget = working_state(directory), {}

    def record(path, verdict):
        if line := record_run(directory, path, verdict, state):
            budget[script_id(path)] = line
    results, requeued = run_checks(directory, runnable, args,
                                   lambda path, beside, run: run_check(directory, path, args, env, beside, run, record))
    verdicts = collections.defaultdict(list)
    compact = {i: compact_line(i, "SKIP", 0.0, None, "its fix budget is spent") for i in skipped}
    for path in runnable:
        check_id = script_id(path)
        verdict, detail, seconds, step = results[check_id]
        verdicts[verdict].append(check_id)
        compact[check_id] = compact_line(check_id, verdict, seconds, step, detail)
    lines = [*requeued, *map(spent_line, skipped), *(compact[script_id(p)] for p in runnable)]
    summary = f"rerun: {len(runnable)} checks, {len(verdicts['PASS'])} PASS, {len(verdicts['FAIL'])} FAIL"
    summary += "".join(f", {len(verdicts[v])} {v}" for v in ("INCONCLUSIVE", "STALLED", "CRASH") if verdicts[v])
    summary += f", {len(skipped)} skipped past the fix budget" if skipped else ""
    summary += f", {len(verdicts['NOT-RUN'])} not run for lack of capacity" if verdicts["NOT-RUN"] else ""
    summary += f", {len(verdicts['ERROR'])} errored before verify recorded the run" if verdicts["ERROR"] else ""
    summary += f", {len(requeued)} requeued" if requeued else ""
    lines.append(summary + (" (--only: no stamp; the ledger records these runs)" if args.only else ""))
    lines += [budget[i] for i in verdicts["FAIL"] if i in budget]
    with rerun_state(directory):
        write_summary(directory, "rerun", [compact[i] for i in sorted(compact)])
        if any(ids for verdict, ids in verdicts.items() if verdict != "PASS"):
            raise Failed("\n" + "\n".join(lines))
        if inputs:
            write_json(stamp_path, {**inputs, "at": now_iso(), "known": skipped})
    return "\n".join(lines)


def dry_verdict(outcome):
    """(verdict, why) of a run on base: FAIL when it reached READY_LINE and failed a predicate (exit 1 with a FAIL line last
    on stdout), PASS when the behavior already exists there, INCONCLUSIVE or ENVIRONMENT on exit 2 or 3, and CRASH or
    STALLED otherwise."""
    if outcome["verdict"]:
        return outcome["verdict"], outcome["reason"]
    code, last = outcome["code"], f": {outcome['last']}" if outcome["last"] else ""
    printed = [line for line in outcome["stdout"].splitlines() if line.strip()]
    if EXIT_VERDICTS.get(code) in ("INCONCLUSIVE", "ENVIRONMENT"):
        return EXIT_VERDICTS[code], f"exit {code}{last}"
    if not outcome["ready"]:
        return "CRASH", f"it never printed \"{READY_LINE}\", so it failed before its instance was up"
    if code == 0:
        return "PASS", "the behavior already exists on base"
    if code == 1 and printed and FAIL_LINE.match(printed[-1].strip()):
        return "FAIL", "it reached its predicates and one failed"
    if code == 1:
        return "CRASH", "exit 1 with no FAIL line last on stdout, so no predicate reported the failure"
    return "CRASH", f"exit {code}, not the exit 1 of a failed predicate"


def dry_check(directory, path, args, env, base, run):
    """(verdict, reason, step) for one check script run on base, graded by dry_verdict. The log goes to <id>.base.log."""
    check_id = script_id(path)
    outcome = supervised_run(path, args, env, run, cwd=base["path"])
    if run and run["evicted"]:
        return "REQUEUED", "", None
    verdict, why = environment_retry(*dry_verdict(outcome), run)
    if verdict == "ENVIRONMENT":
        return verdict, why, outcome["step"]
    ended = f"exit {outcome['code']}" if outcome["code"] is not None else outcome["reason"] if outcome["killed"] else None
    trailer = [f"dryrun: base {base['path']} at {base['head']}", f"dryrun: script sha256 {hashlib.sha256(path.read_bytes()).hexdigest()}",
               "dryrun: ready" if outcome["ready"] else f"dryrun: never printed \"{READY_LINE}\""]
    trailer += [f"dryrun: {ended}"] if ended else []
    trailer += [f"dryrun: last step {outcome['step']}"] if outcome["step"] else []
    output = outcome["output"]
    (directory / f"{check_id}{BASE_LOG}").write_text((output + "\n" if output else "") + "\n".join([*trailer, f"dryrun: {verdict} ({why})"]) + "\n")
    if verdict == "CRASH" and outcome["code"] is not None and outcome["last"]:
        why += f"; last line: {outcome['last']}"
    return verdict, why, outcome["step"]


def cmd_dryrun(directory, args):
    if not args.base:
        raise Failed("dryrun needs --base <path to a worktree at the phase base>: the verifier's own worktree, where the change "
                     "does not exist yet")
    base = pathlib.Path(args.base).expanduser().resolve()
    if not base.is_dir():
        raise Failed(f"--base {base} is not a directory")
    phase = phase_base(base_record(directory))
    base_top = pathlib.Path(git("rev-parse", "--show-toplevel", cwd=base)).resolve()
    skip = []
    for folder in map(pathlib.Path, plan_skip(directory)):
        with contextlib.suppress(Failed, OSError, ValueError):
            skip.append(str(base_top / folder.resolve().relative_to(pathlib.Path(git("rev-parse", "--show-toplevel", cwd=folder)).resolve())))
    if changed := product_changes(phase, skip, cwd=base):
        raise Failed(f"{base} is not at the phase base {phase[:12]}: its product files differ ({listed(changed)}). Check out the "
                     "base there, keeping only driver commits, so the dry run shows what the scripts do before the change exists.")
    if args.only == []:
        return "dryrun --only: no check ids given, so nothing to run"
    scripts = only_scripts(check_scripts(directory), args.only) if args.only else check_scripts(directory)
    if not scripts:
        return f"no saved check scripts (<id>.check.<ext>) in {directory}; nothing to dry-run"
    where = {"path": str(base), "head": git("rev-parse", "HEAD", cwd=base)}
    env = {**os.environ, "VERIFY_DIR": str(directory), "VERIFY_DRYRUN": "1"}
    results, lines = run_checks(directory, scripts, args, lambda path, beside, run: dry_check(directory, path, args, env, where, run))
    tally = collections.Counter(verdict for verdict, *_ in results.values())
    compact = [compact_line(script_id(p), verdict, seconds, step, detail)
               for p in scripts for verdict, detail, seconds, step in [results[script_id(p)]]]
    lines += compact
    summary = (f"dryrun: {len(scripts)} scripts on base {where['head'][:12]}: {tally['FAIL']} fail a predicate, {tally['PASS']} pass "
               f"(behavior already on base), {tally['CRASH']} crash")
    summary += "".join(f", {tally[v]} {v.lower()}" for v in ("INCONCLUSIVE", "STALLED") if tally[v])
    summary += f", {tally['NOT-RUN']} not run for lack of capacity" if tally["NOT-RUN"] else ""
    lines.append(summary + (f", {tally['ERROR']} errored before verify recorded the run" if tally["ERROR"] else ""))
    write_summary(directory, "dryrun", compact)
    if any(tally[v] for v in ("CRASH", "INCONCLUSIVE", "STALLED", "NOT-RUN", "ERROR")):
        raise Failed("\n" + "\n".join(lines))
    return "\n".join(lines)


def base_passes(text):
    """{check id: why} for each check whose '- Base: passes: <why>' allows it to pass on base."""
    found = sections(text.splitlines())
    return {check_id: m.group(1) for name in ("Checks", "Perf") for entry in entries(found.get(name, []))[1]
            if (check_id := entry_id(entry)) and (m := BASE_PASSES.match(entry["fields"].get("Base", (0, ""))[1]))}


def has_step_line(text):
    return any(STEP_LINE.match(line.strip()) for line in text.splitlines())


def dry_run_problems(check_id, script, log, allowed):
    """(problems, note) for one e2e check's dry run on base."""
    again = f"`verify.py dryrun --only {check_id} --base <worktree at the base>`"
    if not log.is_file():
        return [f"{check_id}: no {log.name}; dry-run the script on base with {again}"], None
    text = log.read_text(errors="replace")
    recorded, verdict = DRYRUN_SCRIPT.search(text), DRYRUN_VERDICT.match(last_line(log))
    if not recorded or not verdict:
        return [f"{check_id}: {log.name} is not a `verify.py dryrun` log; run {again}"], None
    if recorded.group(1) != hashlib.sha256(script.read_bytes()).hexdigest():
        return [f"{check_id}: {script.name} changed since its dry run; run {again}"], None
    problems = [] if has_step_line(text) else [
        f"{check_id}: {log.name} holds no '{STEP_FORMAT}' line, so {script.name} reports no progress and a stall waits for the "
        f"--timeout safety net. Print one, flushed, on entering each step, setup included, then run {again}"]
    graded = verdict.group(1)
    if graded in UNGRADED:
        problems.append(f"{check_id}: it {UNGRADED[graded]} on base: {last_line(log).removeprefix(f'dryrun: {graded} ')}. A script "
                        f"reaches \"{READY_LINE}\" and fails on a predicate there; fix it, then run {again}")
    elif graded == "PASS" and check_id not in allowed:
        problems.append(f"{check_id}: it passes on base, so it shows no new behavior. Fix {script.name} or its helper so it fails "
                        f"on base, then run {again}; or, when the base already has this behavior, revise the plan with "
                        f"`verify.py freeze --revision \"<what changed and why>\"` to give {check_id} '{BASE_FIELD}'")
    elif graded == "PASS":
        return problems, f"note: {check_id} passes on base, as its Base field allows: {allowed[check_id]}"
    return problems, None


def cmd_scripts(directory, args):
    _, text, ids, _, tiers = load_plan(directory)
    e2e = [i for i in ids if tiers.get(i) == "e2e"]
    scripts = {script_id(p): p for p in check_scripts(directory)}
    allowed = base_passes(text)
    problems, notes = [], []
    for check_id in e2e:
        if check_id not in scripts:
            problems.append(f"{check_id}: no {check_id}.check.<ext>; the verifier writes one per e2e check, perf checks included")
            continue
        found, note = dry_run_problems(check_id, scripts[check_id], directory / f"{check_id}{BASE_LOG}", allowed)
        problems += found
        notes += [note] if note else []
    if problems:
        raise Failed("\n".join(problems))
    failed = len(e2e) - len(notes)
    return "\n".join([f"scripts ok: {len(e2e)} e2e checks dry-ran on base, {failed} failed a predicate there", *notes])


def perf_ids(directory):
    path = plan_file(directory)
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
    if pointer.is_file():
        return pathlib.Path(json.loads(pointer.read_text())["root"])
    if adopted := base_record(directory).get("plan"):
        return pathlib.Path(adopted)
    raise Failed("no feature plan recorded for this branch. Run `verify.py phases <plan folder>` once.")


def check_phases(root):
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
        found, ids, _, _ = lint_plan(text, full=False)
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


def cmd_phases(directory, args):
    if len(args.rest) > 1:
        raise Failed("phases takes at most one <plan folder>")
    return check_phases(phase_root(directory, args))


def cmd_review(directory, args):
    _, text, _, _, _ = load_plan(directory)
    lock = frozen_lock(directory, text)
    if problems := review_problems(directory, lock["frozen_ts"], head_sha() is not None, fix_head=True):
        raise Failed("\n".join(f"{directory / REVIEW}: {p}" for p in problems))
    return "review ok: the review and the fix review name the Head they read and triage every finding"


def premise_rows(path):
    """[(line, {column: cell})] from the premises table, or Failed when the file holds no table with its columns."""
    columns, rows = None, []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip().startswith("|"):
            columns = None if rows else columns
            continue
        cells = table_cells(line)
        if columns is None:
            names = [c.strip("*` ").lower() for c in cells]
            columns = names if all(c in names for c in PREMISE_COLUMNS) else None
        elif not re.match(r"^\|?\s*:?-", line.strip()):
            rows.append((number, {name: cells[i].strip() if i < len(cells) else "" for i, name in enumerate(columns)}))
    if not rows:
        raise Failed(f"{path} holds no table with the columns Check | Premise | Holds | Evidence | Resolution and at least one row")
    return rows


def cmd_premises(directory, args):
    _, _, ids, _, _ = load_plan(directory, full=False)
    folder = plan_file(directory).parent
    path, grounding = folder / PREMISES, folder / GROUNDING
    base = phase_base(base_record(directory))
    problems = []
    for name, file in ((PREMISES, path), (GROUNDING, grounding)):
        if not file.is_file():
            problems.append(f"no {name} beside the plan, in {folder}; the explainer writes it from the explorers' findings, with "
                            f"the line 'Base: {base}'")
        elif not (named := BASE_LINE.search(file.read_text())):
            problems.append(f"{file} names no 'Base: <sha>' line; the explainer writes the commit it checked the code at, the "
                            f"adopted base: 'Base: {base}'")
        elif not base.startswith(named.group(1).lower()):
            problems.append(f"{file} was checked at {named.group(1)}, not at the adopted base {base[:12]}; check the premises "
                            f"against the base again and write 'Base: {base}'")
    if not path.is_file():
        raise Failed("\n".join(problems))
    rows = premise_rows(path)
    covered, false, new, built = set(), 0, 0, {}
    for number, row in rows:
        named = [i for i in ids if re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", row.get("check", ""))]
        covered.update(named)
        holds = row.get("holds", "").strip("*` ").lower()
        problems += premise_row_problems(path, number, row, holds, args.resolved)
        false += holds == "no"
        new += holds == "new"
        if holds == "new":
            problems += [f"{path}:{number}: {i} has a second 'new' row (the first is line {built[i]}). What the phase builds gets "
                         f"one 'new' row per check; merge them, and keep as premises only what {i} assumes already holds on the base"
                         for i in named if i in built]
            built.update({i: number for i in named if i not in built})
    if missing := [i for i in ids if i not in covered]:
        problems.append(f"{path}: no premise row for {', '.join(missing)}; every check of the plan gets at least one row")
    if problems:
        raise Failed("\n".join(problems))
    open_note = "" if args.resolved or not false else "; resolve them in the design, then pass `verify.py premises --resolved`"
    return (f"premises ok: {len(rows)} premises cover {len(ids)} checks, {false} do not hold"
            + (", each with its resolution" if args.resolved and false else "") + (f", {new} new" if new else "") + open_note)


def premise_row_problems(path, number, row, holds, resolved):
    """A premises row holds yes, no, or new (built by this phase); yes and no rows cite Evidence, and with resolved a no row
    names its Resolution."""
    problems = [] if holds in HOLDS else [
        f"{path}:{number}: Holds must be yes, no, or new (built by this phase), not {row.get('holds', '')!r}"]
    if holds != "new" and (not row.get("evidence", "").strip("-– ") or PLACEHOLDER.search(row.get("evidence", ""))):
        problems.append(f"{path}:{number}: Evidence is empty; cite the file:line on main that shows whether the premise holds")
    if holds == "no" and resolved and not row.get("resolution", "").strip("-– "):
        problems.append(f"{path}:{number}: the premise does not hold and has no Resolution; say how the design resolves it "
                        "(build what is missing, change the check, or the user's call)")
    return problems


def adopted_phase(directory):
    """(plan folder, phase folder) of the phase this branch carries, or (None, None) when no plan folder is recorded. An older
    adopt recorded only the plan folder and copied the phase plan here; that phase is the one whose plan shares a check id with
    the copy. A plan folder whose phase cannot be told is Failed, never a pass."""
    record = base_record(directory)
    if record.get("plan_file"):
        phase = pathlib.Path(record["plan_file"]).parent
        return pathlib.Path(record.get("plan") or phase.parent.parent), phase
    pointer = directory / PHASES_POINTER
    root = record.get("plan") or (json.loads(pointer.read_text()).get("root") if pointer.is_file() else None)
    if not root:
        return None, None
    root, copy = pathlib.Path(root), directory / "plan.md"
    ids = set(lint_plan(copy.read_text(), full=False)[1]) if copy.is_file() else set()
    owners = [p.parent for p in sorted(root.glob("phases/*/plan.md")) if ids & set(lint_plan(p.read_text(), full=False)[1])]
    if len(owners) != 1:
        found = "no phase" if not owners else f"{len(owners)} phases ({', '.join(o.name for o in owners)})"
        raise Failed(f"this branch records the plan folder {root}, but {found} under {root / 'phases'} holds the checks of "
                     f"{copy if copy.is_file() else 'an adopted plan'}, so the change log cannot be checked. Run "
                     "`verify.py adopt <phase folder>` with this branch's phase")
    return root, owners[0]


def cmd_spec(directory, args):
    root, folder = adopted_phase(directory)
    if root is None:
        return "spec: no plan folder adopted on this branch, so there is no spec.md to reconcile"
    phase = folder.name
    path = root / SPEC
    text = read(path, f"{SPEC} in the plan folder (the plan-feature skill writes it)")
    if not re.search(rf"^## {re.escape(CHANGE_LOG)}\s*$", text, re.M):
        raise Failed(f"{path} has no '## {CHANGE_LOG}' section; add it with a line for {phase}")
    if not any(re.search(rf"(?<![\w-]){re.escape(phase)}(?![\w-])", line) for line in section(text, CHANGE_LOG).splitlines()):
        raise Failed(f"{path}'s '## {CHANGE_LOG}' has no line for {phase}. Log what this phase changed in the design, why, and "
                     f"which later phases it touched, or add '{phase}: no design change'")
    return f"spec ok: {SPEC}'s change log names {phase}; " + check_phases(root)


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


def step_window(seconds):
    return seconds + max(STEP_MARGIN_S, STEP_MARGIN_RATIO * seconds)


class Stalled(Exception):
    """A supervised command passed the deadline its last step line opened, or printed none within FIRST_STEP_S."""

    def __init__(self, progress):
        step, last = progress["step"], progress["last"]
        why = f"passed its {progress['window']:g}s deadline" if step else f"no '{STEP_FORMAT}' line within {FIRST_STEP_S:g}s"
        super().__init__(why + (f"; last line: {last}" if last else ""))
        self.output = self.stderr = ""


def run_in_group(command, timeout, on_start=None, on_ready=None, progress=None, **kwargs):
    """subprocess.run in its own session, so a timeout kills the command and everything it started. on_start gets the
    pid (the process group), and on_ready runs when stdout prints READY_LINE. With progress, a dict, each STEP_LINE on
    stdout opens a deadline (FIRST_STEP_S until the first), and one that passes kills the group and raises Stalled;
    progress holds the step, its window, and the last output line."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, **kwargs) as proc:
        if on_start:
            on_start(proc.pid)
        out, err = [], []
        if progress is not None:
            progress.update(step=None, window=FIRST_STEP_S, until=time.monotonic() + FIRST_STEP_S, last="")

        def drain(stream, sink, stdout):
            for line in stream:
                text = line.rstrip("\n")
                if stdout and on_ready and text == READY_LINE:
                    on_ready()
                    continue
                sink.append(line)
                if progress is None or not text.strip():
                    continue
                progress["last"] = text.strip()
                if stdout and (m := STEP_LINE.match(text.strip())):
                    window = step_window(float(m.group(2)))
                    progress.update(step=m.group(1), window=window, until=time.monotonic() + window)

        readers = [threading.Thread(target=drain, args=(proc.stdout, out, True), daemon=True),
                   threading.Thread(target=drain, args=(proc.stderr, err, False), daemon=True)]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None or any(reader.is_alive() for reader in readers):
                now = time.monotonic()
                if now >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                if progress is not None and now >= progress["until"]:
                    raise Stalled(progress)
                limit = min(deadline, progress["until"]) if progress is not None else deadline
                wait = min(PROGRESS_POLL_S, limit - now)
                if proc.poll() is None:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=wait)
                else:
                    next((r for r in readers if r.is_alive()), readers[0]).join(wait)
        except (subprocess.TimeoutExpired, Stalled) as e:
            kill_group(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=KILL_WAIT_S)
            for reader in readers:
                reader.join(KILL_WAIT_S)
            e.output, e.stderr = "".join(out), "".join(err)
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


def environ_holds(pid, mark, proc=pathlib.Path("/proc")):
    """Whether a process's environment holds mark, where /proc exposes it (Linux); macOS's ps shows no other process's environment."""
    with contextlib.suppress(OSError):
        return mark.encode() in (proc / str(pid) / "environ").read_bytes().split(b"\0")
    return False


def lead_test(table, proc=pathlib.Path("/proc")):
    """A test of whether the lead started a pid: it or an ancestor holds LEAD_MARK in its environment or command line."""
    parents = {row["pid"]: row["ppid"] for row in table}
    commands = {row["pid"]: row["command"] for row in table}
    marked = {}

    def is_marked(pid):
        if pid not in marked:
            marked[pid] = bool(LEAD_IN_COMMAND.search(commands.get(pid, ""))) or environ_holds(pid, LEAD_MARK, proc)
        return marked[pid]

    def from_lead(pid):
        seen = set()
        while pid and pid > 1 and pid not in seen:
            if is_marked(pid):
                return True
            seen.add(pid)
            pid = parents.get(pid)
        return False
    return from_lead


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


def scan_processes(roots, orphan_roots=()):
    """(leftovers, lead's): processes under any root, plus orphans (parent init) under orphan roots, where the user's own
    shells and editors live, split by whether the lead started them."""
    under, orphaned_under = root_patterns(roots), root_patterns(orphan_roots)
    table = process_table()
    skip = lineage(table)
    cwds = process_cwds()
    found = [{**row, "cwd": cwds.get(row["pid"])} for row in table
             if row["pid"] not in skip and not row["stat"].startswith("Z")
             and (under(cwds.get(row["pid"]), row["command"]) or (row["ppid"] == 1 and orphaned_under(cwds.get(row["pid"]), row["command"])))]
    from_lead = lead_test(table)
    lead = [p for p in found if from_lead(p["pid"])]
    return [p for p in found if p not in lead], lead


def find_leftovers(roots, orphan_roots=()):
    return scan_processes(roots, orphan_roots)[0]


def signal_processes(found, sig):
    table = process_table()
    skip = lineage(table)
    protected = {row["pgid"] for row in table if row["pid"] in skip}
    from_lead = lead_test(table)
    members = collections.defaultdict(list)
    for row in table:
        members[row["pgid"]].append(row["pid"])
    for proc in found:
        group = proc["pgid"]
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if group in protected or group <= 1 or any(from_lead(pid) for pid in members[group]):
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
    found, lead = scan_processes(roots, orphan_roots)
    return (*split_in_use(found, running_since), lead)


def cmd_leftovers(directory, args):
    roots, orphan_roots = [*default_roots(directory), *(args.root or [])], worktree_paths()
    found, busy, lead = scan_leftovers(roots, orphan_roots, args.running_since)
    killed = len(found) if args.kill else 0
    if found and args.kill:
        stop_processes(found)
        found, busy, lead = scan_leftovers(roots, orphan_roots, args.running_since)
    spared = ([f"{len(busy)} in use by a running agent, started after it began, so neither counted nor killed:"]
              + [describe(p) for p in busy]) if busy else []
    spared += ([f"{len(lead)} spared, started by the lead ({LEAD_MARK}), so neither counted nor killed:"]
               + [describe(p) for p in lead]) if lead else []
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
    path = plan_file(directory)
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
            "report": cmd_report, "decisions": cmd_decisions, "units": cmd_units, "rerun": cmd_rerun, "dryrun": cmd_dryrun,
            "scripts": cmd_scripts, "review": cmd_review, "premises": cmd_premises, "spec": cmd_spec, "script-fix": cmd_script_fix,
            "phases": cmd_phases, "lock": cmd_lock, "adopt": cmd_adopt, "base": cmd_base, "leftovers": cmd_leftovers,
            "capacity": cmd_capacity}


def main():
    parser = argparse.ArgumentParser(usage=__doc__)
    parser.add_argument("command", choices=["where", *COMMANDS])
    parser.add_argument("--dir")
    parser.add_argument("--revision")
    parser.add_argument("--reason")
    parser.add_argument("--full-reason")
    parser.add_argument("--test-cmd")
    parser.add_argument("--kill", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", action="append")
    parser.add_argument("--spec", action="append")
    parser.add_argument("--only", action="extend", nargs="*")
    parser.add_argument("--checks", action="store_true")
    parser.add_argument("--resolved", action="store_true")
    parser.add_argument("--gate")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--author")
    parser.add_argument("--verifier")
    parser.add_argument("--note", action="append")
    parser.add_argument("--base")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--running-since", type=float)
    parser.add_argument("rest", nargs="*")
    argv = sys.argv[1:]
    passthrough = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_intermixed_args(argv[:len(argv) - len(passthrough) - 1] if "--" in argv else argv)
    args.rest += passthrough
    if args.rest and args.command not in ("units", "rerun", "dryrun", "phases", "adopt", "script-fix", "base"):
        parser.error(f"{args.command} takes no arguments")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs needs at least 1")
    args.timeout = args.timeout or (RERUN_TIMEOUT if args.command in ("rerun", "dryrun") else SCRIPT_TIMEOUT)
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
        if out := COMMANDS[args.command](directory, args):
            print(out)
    except Failed as e:
        print(f"verify {args.command}: {e}")
        sys.exit(e.code)


if __name__ == "__main__":
    main()
