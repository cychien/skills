import contextlib
import hashlib
import importlib.util
import io
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
import textwrap
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERIFY = ROOT / "skills" / "eng" / "verify" / "scripts" / "verify.py"
TEMPLATES = ROOT / "skills" / "eng" / "verify" / "references"
spec = importlib.util.spec_from_file_location("verify", VERIFY)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
AUTORUN_HOME = tempfile.TemporaryDirectory()
os.environ.update(AUTORUN_HOME=AUTORUN_HOME.name, VERIFY_MAX_LOAD_RATIO="1000")
os.environ.pop("AUTORUN_RUN", None)

CONTRACT = """
    ## Drive contract

    - `export --json`: the CLI command B1 runs, printing the records to stdout
    """
CHECKS = """\
    # Verification plan: json export
    """ + CONTRACT + """
    ## Checks

    ### B1. Export writes JSON

    - Scenario: run export --json on the sample project with 3 records
    - Surface: a real terminal
    - Evidence: the terminal transcript
    - Pass: stdout parses as JSON and holds 3 records
    - Oracle: n/a: the output format is checked, no value is computed
    - Tier: e2e
    """
PERF_NA = "\n## Perf\n\nn/a: only the help text changes, nothing a user waits on\n"
PERF_MAIN = """
    ## Perf

    ### P1. Export time

    - Path: export returns for the 60k-row fixture
    - Metric: wall time and query count
    - Probe: hyperfine 'export --json' on main and head, interleaved
    - Baseline: main
    - Rule: fails when p50 is more than 5% slower than main or any query is added
    """
REPORT = """\
    # Verification report: json export

    Head: abc123
    Main: def456
    Author: claude:claude-opus-5-5
    Verifier: codex:gpt-5.6-sol

    | Check | Verdict | Evidence | Observed |
    |---|---|---|---|
    | B1 | PASS | B1-terminal.txt | stdout parsed, 3 records |
    | P1 | PASS | P1-runs.txt | p50 41 ms on both sides |
    """
REVIEW_MD = ("# Code review\n\nReviewer: {reviewer}\n\n## Review\n\nHead: {head}\n\n{findings}\n\n"
             "## Fix review\n\nHead: {fixed}\nReviewer: {fix_reviewer}\nFixed at: {fixed_at}\n{relaxed}\n{fix_findings}\n")
REVIEWER = "codex:gpt-5.6-sol"


def review_md(head="abc123", fixed=None, findings="none found", fix_findings="none found", fixed_at=None, fix_reviewer=REVIEWER,
              relaxed=None):
    fixed = fixed or head
    return REVIEW_MD.format(reviewer=REVIEWER, head=head, fixed=fixed, findings=findings, fix_reviewer=fix_reviewer,
                            fixed_at=fixed_at or fixed, relaxed=f"Relaxed: {relaxed}\n" if relaxed else "", fix_findings=fix_findings)

UNIT = """
    ### U1. Multiplying two numbers

    - Scenario: mul(2, 3) in the calc module
    - Surface: the calc module
    - Evidence: units.log
    - Pass: mul(2, 3) returns 6
    - Oracle: n/a: a fixed product, no data is read
    - Tier: unit
    """
WALK = """
    ### W1. The export button sits beside Share

    - Scenario: open a project with 3 notes at 390 px width
    - Surface: a real browser
    - Evidence: evidence/W1/
    - Pass: the Export button renders right of Share, on one line
    - Oracle: n/a: layout only, no value is computed
    - Tier: walk
    """


def plan(*parts):
    return "".join(textwrap.dedent(part) for part in parts)


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.dir = self.base / "verification"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_verify(self, command, *extra, ok=True, cwd=None, env=None):
        args = [sys.executable, "-I", str(VERIFY), command, *extra]
        if cwd is None:
            args += ["--dir", str(self.dir)]
        env = {**os.environ, "VERIFY_HOME": str(self.base / "home"), **(env or {})}
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd or self.base, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def write(self, name, text):
        (self.dir / name).write_text(text)

    def test_accepts_a_plan_with_perf_na_and_a_reason(self):
        self.write("plan.md", plan(CHECKS, PERF_NA))
        self.assertIn("plan ok, 1 checks", self.run_verify("plan"))

    def test_accepts_a_perf_check_against_main(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN))
        self.run_verify("plan")

    def test_rejects_a_missing_plan(self):
        self.assertIn("no plan", self.run_verify("plan", ok=False))

    def test_rejects_a_plan_without_a_perf_decision(self):
        self.write("plan.md", plan(CHECKS))
        self.assertIn("missing '## Perf' section", self.run_verify("plan", ok=False))

    def test_rejects_an_empty_perf_section(self):
        self.write("plan.md", plan(CHECKS, "\n## Perf\n"))
        self.assertIn("needs perf checks, or 'n/a: <reason>'", self.run_verify("plan", ok=False))

    def test_rejects_na_without_a_real_reason(self):
        self.write("plan.md", plan(CHECKS, "\n## Perf\n\nn/a: none\n"))
        self.assertIn("n/a needs a reason", self.run_verify("plan", ok=False))

    def test_rejects_a_check_missing_its_predicate(self):
        self.write("plan.md", plan(CHECKS.replace("    - Pass: stdout parses as JSON and holds 3 records\n", ""), PERF_NA))
        self.assertIn("missing '- Pass:'", self.run_verify("plan", ok=False))

    def test_rejects_the_unfilled_template(self):
        self.write("plan.md", (TEMPLATES / "plan-template.md").read_text())
        self.assertIn("template placeholder", self.run_verify("plan", ok=False))

    def test_rejects_a_comparison_with_main_when_main_lacks_the_path(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN.replace("Baseline: main", "Baseline: none: main has no json export")))
        self.assertIn("absolute budget", self.run_verify("plan", ok=False))

    def test_rejects_a_rule_without_a_number(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN.replace(
            "fails when p50 is more than 5% slower than main or any query is added", "should not get slower")))
        self.assertIn("number that fails", self.run_verify("plan", ok=False))

    def test_rejects_duplicate_ids(self):
        self.write("plan.md", plan(CHECKS, CHECKS.split("## Checks\n")[1], PERF_NA))
        self.assertIn("used more than once", self.run_verify("plan", ok=False))

    def new_prove(self):
        (self.dir / "scripts.lock.json").unlink(missing_ok=True)

    def passing_scripts(self, *ids):
        self.new_prove()
        for check_id in ids:
            self.check_script(f"{check_id}.check.sh", "exit 0\n")
        self.run_verify("rerun")

    def ready_report(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN))
        self.run_verify("freeze")
        self.passing_scripts("B1", "P1")
        self.write("B1-terminal.txt", "[{...}]\n")
        self.write("P1-runs.txt", "41 ms\n")
        self.write("report.md", plan(REPORT))
        self.write("review.md", review_md())

    def test_accepts_a_report_with_evidence_for_every_check(self):
        self.ready_report()
        self.assertIn("2 checks have verdicts backed by evidence", self.run_verify("report"))

    def test_rejects_a_report_before_the_plan_was_frozen(self):
        self.ready_report()
        (self.dir / "plan.lock").unlink()
        self.assertIn("never frozen", self.run_verify("report", ok=False))

    def with_evidence(self, cell):
        self.ready_report()
        self.write("report.md", plan(REPORT).replace("| B1 | PASS | B1-terminal.txt |", f"| B1 | PASS | {cell} |"))

    def test_a_glob_or_brace_in_an_evidence_cell_expands_to_non_empty_files(self):
        runs = self.dir / "B1"
        runs.mkdir()
        self.with_evidence("B1/B1.C*")
        (runs / "B1.C1.a.txt").write_text("one\n")
        (runs / "B1.C2.b.txt").write_text("two\n")
        for cell in ("B1/B1.C*", "B1/B1.C{1.a,2.b}.txt", "B1/B1.C{1,2}.*.txt, B1/B1.C1.a.txt", "B1/", "B1-terminal.txt, B1/B1.C?.*"):
            self.with_evidence(cell)
            self.run_verify("report")

    def test_a_glob_that_matches_nothing_or_only_empty_files_is_rejected_by_name(self):
        runs = self.dir / "B1"
        runs.mkdir()
        (runs / "B1.C1.a.txt").write_text("one\n")
        (runs / "empty.log").write_text("")
        self.with_evidence("B1/B1.X*")
        out = self.run_verify("report", ok=False)
        self.assertIn("B1 evidence B1/B1.X* matches nothing", out)
        self.with_evidence("B1/empty.*")
        self.assertIn("B1/empty.* matches only empty files", self.run_verify("report", ok=False))
        self.with_evidence("B1/B1.C{1,3}.*.txt")
        self.assertIn("B1/B1.C3.*.txt matches nothing", self.run_verify("report", ok=False))

    def test_a_glob_that_matches_files_older_than_the_freeze_is_rejected(self):
        runs = self.dir / "B1"
        runs.mkdir()
        old = runs / "B1.C1.a.txt"
        old.write_text("one\n")
        os.utime(old, (1, 1))
        self.with_evidence("B1/B1.C*")
        self.assertIn("predate the frozen plan", self.run_verify("report", ok=False))

    def test_a_directory_of_evidence_counts_when_it_holds_files(self):
        self.ready_report()
        self.write("report.md", plan(REPORT).replace("| B1 | PASS | B1-terminal.txt |", "| B1 | PASS | B1-runs/ |"))
        (self.dir / "B1-runs").mkdir()
        self.assertIn("empty directory", self.run_verify("report", ok=False))
        (self.dir / "B1-runs" / "main.txt").write_text("[{...}]\n")
        self.run_verify("report")

    def test_rejects_a_check_with_no_row_or_missing_evidence(self):
        self.ready_report()
        self.write("report.md", plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", ""))
        self.assertIn("check P1 has no row", self.run_verify("report", ok=False))
        self.write("report.md", plan(REPORT))
        (self.dir / "B1-terminal.txt").write_text("")
        self.assertIn("evidence B1-terminal.txt is missing or empty", self.run_verify("report", ok=False))

    def test_a_failing_check_needs_a_fix_or_a_named_blocker(self):
        self.ready_report()
        self.write("report.md", plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |", "| P1 | FAIL | P1-runs.txt | 9% slower |"))
        self.assertIn("'defect:'", self.run_verify("report", ok=False))
        self.write("report.md", plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |", "| P1 | INCONCLUSIVE | P1-runs.txt | blocker: shared CI box, rerun scheduled |"))
        self.run_verify("report")

    def test_the_author_cannot_be_the_verifier(self):
        self.ready_report()
        self.write("report.md", plan(REPORT).replace("Verifier: codex:gpt-5.6-sol", "Verifier: claude:claude-opus-5-5"))
        self.assertIn("Verifier is the Author", self.run_verify("report", ok=False))

    def test_a_plan_edited_after_freezing_needs_a_recorded_revision(self):
        self.ready_report()
        self.write("plan.md", plan(CHECKS, PERF_MAIN.replace("5%", "20%")))
        self.assertIn("changed after it was frozen", self.run_verify("report", ok=False))
        self.assertIn("--revision", self.run_verify("freeze", ok=False))
        self.run_verify("freeze", "--revision", "budget raised to 20%: CI noise is 12%; agreed by the user")
        out = self.run_verify("report")
        self.assertIn("revision", out)
        self.assertIn("agreed by the user", out)
        lock = json.loads((self.dir / "plan.lock").read_text())
        self.assertEqual(len(lock["revisions"]), 1)

    def test_evidence_must_come_after_the_plan_was_frozen(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN))
        self.write("B1-terminal.txt", "[{...}]\n")
        os.utime(self.dir / "B1-terminal.txt", (1, 1))
        self.run_verify("freeze")
        self.write("P1-runs.txt", "41 ms\n")
        self.write("report.md", plan(REPORT))
        out = self.run_verify("report", ok=False)
        self.assertIn("B1-terminal.txt predates the frozen plan", out)
        self.assertNotIn("P1-runs.txt predates", out)

    ORACLE = """
    ### A1. Monthly revenue per tier

    - Scenario: open the revenue page for March 2024 with the tiers dataset loaded
    - Surface: a real browser
    - Evidence: A1.expected.json, A1.observed.json, A1-page.png
    - Pass: each tier's revenue matches the spec's definition
    - Oracle: revenue is the sum of quantity times unit price over orders placed in the month, refunds excluded
    - Seed: tiers dataset
    - Shape: {"<tier>": <revenue in cents>}
    - Tier: e2e
    """

    def oracle_plan(self, oracle=ORACLE):
        self.write("plan.md", plan(CHECKS, oracle, PERF_NA))

    def test_every_check_states_its_oracle(self):
        bare = self.ORACLE.split("    - Oracle:")[0] + "    - Tier: e2e\n"
        self.oracle_plan(bare)
        self.assertIn("missing '- Oracle:'", self.run_verify("plan", ok=False))
        self.oracle_plan(bare + "    - Oracle: n/a: x\n")
        self.assertIn("Oracle n/a needs a reason", self.run_verify("plan", ok=False))
        self.oracle_plan(bare + "    - Oracle: n/a: the page only echoes a stored total\n")
        self.run_verify("plan")
        self.oracle_plan(self.ORACLE.replace("    - Seed: tiers dataset\n", ""))
        self.assertIn("missing '- Seed:'", self.run_verify("plan", ok=False))
        self.oracle_plan()
        self.assertIn("1 oracle checks", self.run_verify("plan"))

    def oracle_report(self, verdict="PASS"):
        return plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n",
                                    f"| A1 | {verdict} | A1.expected.json, A1.observed.json | values read from the page |\n")

    def test_oracle_and_observer_values_must_postdate_the_freeze(self):
        self.oracle_plan()
        self.write("A1.expected.json", '{"wholesale": 1200, "retail": 300}')
        os.utime(self.dir / "A1.expected.json", (1, 1))
        self.run_verify("freeze")
        self.assertIn("predates the frozen plan", self.run_verify("oracles", ok=False))
        self.write("A1.observed.json", '{"wholesale": 1200, "retail": 300}')
        self.write("A1.expected.json", '{"wholesale": 1200, "retail": 300}')
        self.assertIn("1 expected values", self.run_verify("oracles"))
        self.assertIn("A1: match", self.run_verify("compare"))

    def test_report_compares_observed_with_expected(self):
        self.oracle_plan()
        self.run_verify("freeze")
        self.passing_scripts("B1", "A1")
        self.write("B1-terminal.txt", "[{...}]\n")
        self.write("A1.expected.json", '{"wholesale": 1200, "retail": 300}')
        self.write("A1.observed.json", '{"wholesale": 1200, "retail": 310}')
        self.write("report.md", self.oracle_report())
        self.write("review.md", review_md())
        out = self.run_verify("report", ok=False)
        self.assertIn("differs from the oracle", out)
        self.assertIn("$.retail: expected 300, observed 310", out)
        self.assertIn("$.retail", self.run_verify("compare", ok=False))
        self.write("report.md", self.oracle_report("FAIL"))
        self.assertIn("start its Observed cell with 'defect:'", self.run_verify("report", ok=False))
        self.write("report.md", self.oracle_report("FAIL").replace("values read from the page", "defect: refunds are subtracted twice"))
        self.run_verify("report")
        self.write("A1.observed.json", '{"wholesale": 1200, "retail": 300}')
        self.write("report.md", self.oracle_report())
        self.assertIn("A1: match", self.run_verify("compare"))
        self.run_verify("report")

    def test_tolerance_allows_rounding_and_order_matters_in_lists(self):
        self.oracle_plan(self.ORACLE.replace("    - Shape:", "    - Tolerance: 0.01\n    - Shape:"))
        self.run_verify("freeze")
        self.write("A1.expected.json", '{"wholesale": 0.333, "top": [3, 1, 2]}')
        self.write("A1.observed.json", '{"wholesale": 0.33, "top": [3, 1, 2]}')
        self.run_verify("compare")
        self.write("A1.observed.json", '{"wholesale": 0.33, "top": [1, 3, 2]}')
        self.assertIn("$.top[0]: expected 3, observed 1", self.run_verify("compare", ok=False))

    def check_script(self, name, body, mode=0o644):
        path = self.dir / name
        path.write_text(body)
        path.chmod(mode)

    def test_rerun_runs_every_saved_check_script_and_reports_each_verdict(self):
        self.check_script("B1.check.sh", "echo \"args: $*\" > \"$(dirname \"$0\")/B1.args\"\nexit 0\n")
        self.check_script("B2.check.py", "import sys\nprint('observed 2 rows')\nsys.exit(1)\n")
        self.check_script("B3.check.sh", "#!/bin/sh\nexit 0\n", 0o755)
        self.write("B1.observed.json", "{}")
        out = self.run_verify("rerun", "inst-7", "extra", ok=False)
        self.assertRegex(out, r"PASS\s+B1")
        self.assertRegex(out, r"FAIL\s+B2.*exit 1")
        self.assertIn("observed 2 rows", out)
        self.assertRegex(out, r"PASS\s+B3")
        self.assertIn("rerun: 3 checks, 2 PASS, 1 FAIL", out)
        self.assertEqual((self.dir / "B1.args").read_text().strip(), "args: inst-7 extra")
        self.assertNotIn("B1.observed", out)

    def test_rerun_exits_zero_when_every_check_passes_and_when_there_are_none(self):
        self.assertIn("no saved check scripts", self.run_verify("rerun"))
        self.check_script("B1.check.sh", "exit 0\n")
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL", self.run_verify("rerun"))

    def test_rerun_fails_a_script_that_cannot_run_or_hangs(self):
        self.check_script("B1.check.rb", "puts 1\n")
        self.check_script("B2.check.sh", "sleep 30\n")
        out = self.run_verify("rerun", "--timeout", "1", ok=False)
        self.assertRegex(out, r"FAIL\s+B1.*no interpreter")
        self.assertRegex(out, r"FAIL\s+B2.*timed out after 1s")

    def test_rerun_passes_flags_after_a_double_dash(self):
        self.check_script("B1.check.sh", "test \"$1\" = --instance && test \"$2\" = a\n")
        env = {**os.environ, "VERIFY_HOME": str(self.base / "home")}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "rerun", "--dir", str(self.dir), "--", "--instance", "a"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rerun_fails_a_check_that_deletes_or_empties_another_checks_evidence(self):
        for name, text in (("evidence/B2/shot.png", "png"), ("evidence/B3/log.txt", "log"), ("B1-own.txt", "own"), ("evidence/B1/own.png", "own")):
            path = self.dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"\nrm -rf "$d/evidence/B2" "$d/B1-own.txt" "$d/evidence/B1"\n: > "$d/evidence/B3/log.txt"\n')
        self.check_script("B2.check.sh", "exit 0\n")
        out = self.run_verify("rerun", ok=False)
        self.assertRegex(out, r"FAIL\s+B1.*deleted or emptied files that are not its own: evidence/B2/shot.png, evidence/B3/log.txt\n")
        self.assertRegex(out, r"PASS\s+B2")
        self.assertNotIn("B1-own", out)
        self.assertNotIn("evidence/B1", out)

    MEET = ('d="$(dirname "$0")"; touch "$d/{me}.started"; echo "verify: ready"\n'
            'for i in $(seq 30); do [ -e "$d/{other}.started" ] && exit 0; sleep 0.1; done\necho "{other} never ran beside it"; exit 1\n')

    def meeting_checks(self):
        self.new_prove()
        for name in self.dir.glob("*.started"):
            name.unlink()
        self.check_script("B1.check.sh", self.MEET.format(me="B1", other="B2"))
        self.check_script("B2.check.sh", self.MEET.format(me="B2", other="B1"))

    def test_rerun_jobs_runs_scripts_side_by_side_and_reports_them_in_id_order(self):
        self.meeting_checks()
        self.assertRegex(self.run_verify("rerun", "--jobs", "1", ok=False), r"FAIL\s+B1.*\n\s+B2 never ran beside it")
        self.meeting_checks()
        out = self.run_verify("rerun", "--jobs", "2", env={"VERIFY_MAX_LOAD_RATIO": "1000"})
        self.assertRegex(out, r"^PASS\s+B1 .*\nPASS\s+B2 .*\nrerun: 2 checks, 2 PASS, 0 FAIL\n$")
        self.assertEqual((self.dir / "B2.rerun.log").read_text(), "rerun: PASS\n")

    def capacity_rerun(self, load, wait=1.0):
        args = mock.Mock(only=None, rest=[], jobs=None, timeout=30, force=False, full_reason=None)
        with mock.patch.multiple(verify, CAPACITY_POLL_S=0.05, CAPACITY_WAIT_S=wait, ADMIT_POLL_S=0.05, WATCH_POLL_S=0.05), \
                mock.patch.object(verify.os, "getloadavg", side_effect=lambda: (load(),) * 3), \
                mock.patch.object(verify.os, "cpu_count", return_value=4), mock.patch.dict(os.environ):
            os.environ.pop("VERIFY_MAX_LOAD_RATIO", None)
            try:
                return verify.cmd_rerun(self.dir, args)
            except verify.Failed as e:
                return str(e)

    def test_rerun_starts_a_script_only_while_the_machine_has_capacity_and_requeues_one_that_waits_too_long(self):
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; touch "$d/B1.started"; echo "verify: ready"; sleep 0.2\n')
        self.check_script("B2.check.sh", 'd="$(dirname "$0")"; [ -e "$d/B1.rerun.log" ] || { echo "started beside B1 without capacity"; exit 1; }\n')
        out = self.capacity_rerun(lambda: 3.0 if (self.dir / "B1.started").exists() and not (self.dir / "B1.rerun.log").exists() else 0.0)
        self.assertRegex(out, r"PASS\s+B1 .*\nPASS\s+B2 ")
        self.assertNotIn("REQUEUED", out)
        self.new_prove()
        for name in ("rerun.stamp.json", "B1.started", "B1.rerun.log"):
            (self.dir / name).unlink(missing_ok=True)
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; touch "$d/B1.started"; echo "verify: ready"; sleep 1.5\n')
        out = self.capacity_rerun(lambda: 3.0 if (self.dir / "B1.started").exists() and not (self.dir / "B1.rerun.log").exists() else 0.0)
        self.assertRegex(out, r"REQUEUED B2  waited 0\.01\d* min for capacity \(load 3\.0 on 4 cores, threshold 2\.8\); queued again behind the rest\n")
        self.assertRegex(out, r"PASS\s+B1 .*\nPASS\s+B2 ")
        self.assertIn("rerun: 2 checks, 2 PASS, 0 FAIL, 1 requeued", out)

    def concurrent_reruns(self, *onlys, slow):
        """Run cmd_rerun once per --only list at the same time, with slow() widening each bookkeeping read; return each outcome."""
        outcomes = {}

        def rerun(key, only):
            args = mock.Mock(only=only, rest=[], jobs=None, timeout=30, force=False, full_reason=None)
            try:
                outcomes[key] = verify.cmd_rerun(self.dir, args)
            except verify.Failed as e:
                outcomes[key] = f"Failed: {e}"

        with mock.patch.object(verify, slow.__name__, slow):
            threads = [threading.Thread(target=rerun, args=(i, only)) for i, only in enumerate(onlys)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        return [outcomes[i] for i in range(len(onlys))]

    def test_concurrent_reruns_serialize_their_bookkeeping(self):
        self.check_script("B1.check.sh", "exit 0\n")
        self.check_script("B2.check.sh", "exit 0\n")
        load_scripts_lock = verify.load_scripts_lock

        def slow_lock(directory):
            time.sleep(0.3)
            return load_scripts_lock(directory)

        slow_lock.__name__ = "load_scripts_lock"
        outcomes = self.concurrent_reruns(None, None, slow=slow_lock)
        self.assertEqual(sum("the prove's full rerun already ran" in o for o in outcomes), 1, outcomes)
        self.assertEqual(sum(o.endswith("rerun: 2 checks, 2 PASS, 0 FAIL") for o in outcomes), 1, outcomes)
        load_ledger = verify.load_ledger

        def slow_ledger(directory):
            time.sleep(0.3)
            return load_ledger(directory)

        slow_ledger.__name__ = "load_ledger"
        (self.dir / "rerun.ledger.json").unlink()
        self.concurrent_reruns(["B1"], ["B2"], slow=slow_ledger)
        self.assertEqual(sorted(verify.load_ledger(self.dir)), ["B1", "B2"])
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(verify.TMP_SUFFIX)], [])

    def test_a_script_that_waits_twice_for_capacity_is_not_run_and_fails_the_rerun(self):
        self.check_script("B1.check.sh", "exit 0\n")
        out = self.capacity_rerun(lambda: 9.0, wait=0.2)
        self.assertIn("REQUEUED B1  waited", out)
        self.assertRegex(out, r"NOT RUN B1  \(0\.0s\)  waited .* twice; run it with --only B1 once the machine has room")
        self.assertIn("rerun: 1 checks, 0 PASS, 0 FAIL, 1 not run for lack of capacity, 1 requeued", out)
        self.assertFalse((self.dir / "B1.rerun.log").exists())
        self.assertNotIn("B1", verify.load_ledger(self.dir))
        self.assertIn("--jobs needs at least 1", subprocess.run([sys.executable, "-I", str(VERIFY), "rerun", "--jobs", "0", "--dir", str(self.dir)],
                                                                capture_output=True, text=True).stderr)

    def test_rerun_jobs_runs_perf_checks_alone_after_the_rest(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN.replace("P1", "A0")))
        self.meeting_checks()
        self.check_script("A0.check.sh", 'd="$(dirname "$0")"; ls "$d"/*.started >/dev/null 2>&1 || exit 1\n'
                                         'for c in B1 B2; do [ -e "$d/$c.rerun.log" ] || { echo "$c still running"; exit 1; }; done\n')
        out = self.run_verify("rerun", "--jobs", "3", env={"VERIFY_MAX_LOAD_RATIO": "1000"})
        self.assertRegex(out, r"^PASS\s+A0 .*\nPASS\s+B1 .*\nPASS\s+B2 ")

    def test_rerun_jobs_admits_the_next_script_only_once_the_running_ones_print_ready(self):
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; sleep 0.5; touch "$d/B1.readied"; echo "verify: ready"; sleep 1\n')
        self.check_script("B2.check.sh", 'd="$(dirname "$0")"; [ -e "$d/B1.readied" ] || { echo "started before B1 was ready"; exit 1; }\n'
                                         '[ -e "$d/B1.rerun.log" ] && { echo "waited for B1 to end"; exit 1; }; exit 0\n')
        out = self.run_verify("rerun", "--jobs", "2", env={"VERIFY_MAX_LOAD_RATIO": "1000"})
        self.assertRegex(out, r"PASS\s+B1 .*\nPASS\s+B2 ")
        self.assertEqual((self.dir / "B1.rerun.log").read_text(), "rerun: PASS\n")
        (self.dir / "B1.rerun.log").unlink()
        self.new_prove()
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; sleep 0.5; touch "$d/B1.readied"\n')
        self.check_script("B2.check.sh", 'd="$(dirname "$0")"; [ -e "$d/B1.rerun.log" ] || { echo "started beside a script that never printed ready"; exit 1; }\n')
        self.assertRegex(self.run_verify("rerun", "--jobs", "2", "--force", env={"VERIFY_MAX_LOAD_RATIO": "1000"}), r"PASS\s+B1 .*\nPASS\s+B2 ")

    def test_rerun_jobs_requeues_the_newest_script_while_the_load_stays_over_the_cores_and_never_retries_a_fail(self):
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; echo "verify: ready"; sleep 1.5; touch "$d/B1.done"\n')
        self.check_script("B2.check.sh", 'd="$(dirname "$0")"; n=$(cat "$d/B2.count" 2>/dev/null || echo 0); echo $((n + 1)) > "$d/B2.count"\n'
                                         'echo "verify: ready"; [ "$n" = 0 ] && { sleep 5; echo "never stopped"; exit 1; }\n'
                                         '[ -e "$d/B1.done" ] || { echo "ran beside B1 after the requeue"; exit 1; }; exit 0\n')
        self.check_script("B3.check.sh", 'd="$(dirname "$0")"; echo x >> "$d/B3.runs"; exit 1\n')

        def load():
            path = self.dir / "B2.count"
            overloaded = path.exists() and path.read_text().strip() == "1" and not (self.dir / "B1.done").exists()
            return (100.0 if overloaded else 0.0,) * 3

        args = mock.Mock(only=None, rest=[], jobs=3, timeout=30, force=False)
        with mock.patch.multiple(verify, WATCH_POLL_S=0.05, OVERLOAD_S=0.3, ADMIT_POLL_S=0.05, CAPACITY_POLL_S=0.05), \
                mock.patch.object(verify, "default_roots", lambda d: [str(d)]), \
                mock.patch.object(verify.os, "getloadavg", side_effect=load), mock.patch.object(verify.os, "cpu_count", return_value=4), \
                mock.patch.dict(os.environ):
            os.environ.pop("VERIFY_MAX_LOAD_RATIO", None)
            with self.assertRaises(verify.Failed) as raised:
                verify.cmd_rerun(self.dir, args)
        out = str(raised.exception)
        self.assertRegex(out, r"REQUEUED B2  load 100\.0 on 4 cores for 0s; stopped and queued again, --jobs now 1\n")
        self.assertRegex(out, r"PASS\s+B1 .*\nPASS\s+B2 .*\nFAIL\s+B3 ")
        self.assertIn("rerun: 3 checks, 2 PASS, 1 FAIL, 1 requeued", out)
        self.assertEqual((self.dir / "B2.count").read_text(), "2\n")
        self.assertEqual((self.dir / "B3.runs").read_text(), "x\n")
        self.assertFalse((self.dir / "fix-attempts.json").exists())

    def test_rerun_jobs_never_blames_a_check_for_the_evidence_a_concurrent_check_is_rewriting(self):
        for name in ("evidence/B1/shot.png", "evidence/W1/walk.png"):
            (self.dir / name).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / name).write_text("png")
        self.check_script("B1.check.sh", 'd="$(dirname "$0")"; echo "verify: ready"; sleep 0.5; rm "$d/evidence/B1/shot.png"; sleep 1.5; echo png > "$d/evidence/B1/shot.png"\n')
        self.check_script("B2.check.sh", 'd="$(dirname "$0")"; sleep 1.2; rm "$d/evidence/W1/walk.png"\n')
        out = self.run_verify("rerun", "--jobs", "2", ok=False, env={"VERIFY_MAX_LOAD_RATIO": "1000"})
        self.assertRegex(out, r"FAIL\s+B1 .*files that are not its own were deleted or emptied while it ran beside B2: evidence/W1/walk.png\n")
        self.assertRegex(out, r"FAIL\s+B2 .*while it ran beside B1: evidence/W1/walk.png\n")
        self.new_prove()
        self.check_script("B2.check.sh", "sleep 1.2\n")
        self.assertRegex(self.run_verify("rerun", "--jobs", "2", env={"VERIFY_MAX_LOAD_RATIO": "1000"}), r"PASS\s+B1 .*\nPASS\s+B2 ")

    def test_every_check_names_its_tier_and_the_plan_counts_them(self):
        self.write("plan.md", plan(CHECKS, UNIT, WALK, PERF_MAIN))
        self.assertIn("plan ok, 4 checks, 0 oracle checks; tiers: e2e 2, unit 1, walk 1", self.run_verify("plan"))
        self.write("plan.md", plan(CHECKS.replace("    - Tier: e2e\n", ""), PERF_NA))
        out = self.run_verify("plan", ok=False)
        self.assertIn("missing '- Tier:'; write e2e (isolation, permissions, revocation, wire compatibility, perf, or a cross-surface flow", out)
        self.assertIn("unit (logic: a spec the executor writes, graded by `verify.py units`)", out)
        self.write("plan.md", plan(CHECKS.replace("Tier: e2e", "Tier: smoke"), PERF_NA))
        self.assertIn("Tier must be e2e, unit, or walk, not 'smoke'", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(CHECKS, PERF_MAIN.replace("    - Rule:", "    - Tier: walk\n    - Rule:")))
        self.assertIn("a perf check is always e2e", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(CHECKS, self.ORACLE.replace("Tier: e2e", "Tier: unit"), PERF_NA))
        self.assertIn("an oracle check reads its value from the running app, so its Tier is e2e or walk", self.run_verify("plan", ok=False))

    def b1_report(self):
        self.write("plan.md", plan(CHECKS, PERF_NA))
        self.run_verify("freeze")
        self.write("B1-terminal.txt", "[{...}]\n")
        self.write("report.md", plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", ""))
        self.write("review.md", review_md())

    def test_an_e2e_pass_needs_its_script_and_a_passing_rerun_after_the_freeze(self):
        self.b1_report()
        self.assertIn("B1 is an e2e check marked PASS, but no B1.check.<ext> script is saved", self.run_verify("report", ok=False))
        self.check_script("B1.check.sh", "echo 3 records\nexit 0\n")
        self.assertIn("B1.rerun.log is missing or predates the frozen plan", self.run_verify("report", ok=False))
        self.run_verify("rerun")
        self.assertEqual((self.dir / "B1.rerun.log").read_text(), "3 records\nrerun: PASS\n")
        os.utime(self.dir / "B1.rerun.log", (1, 1))
        self.assertIn("B1.rerun.log is missing or predates the frozen plan", self.run_verify("report", ok=False))
        self.check_script("B1.check.sh", "echo 2 records\nexit 1\n")
        self.run_verify("script-fix", "B1.check.sh", "--reason", "the fixture now holds 2 records; agreed by the user")
        self.run_verify("rerun", "--only", "B1", ok=False)
        self.assertEqual((self.dir / "B1.rerun.log").read_text(), "2 records\nrerun: FAIL (exit 1)\n")
        self.assertIn("B1.rerun.log records a failing run; a PASS needs a passing `verify.py rerun`", self.run_verify("report", ok=False))
        self.write("report.md", plan(REPORT).replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", "")
                   .replace("| B1 | PASS | B1-terminal.txt | stdout parsed, 3 records |", "| B1 | FAIL | B1.rerun.log | defect: 2 records |"))
        self.run_verify("report")

    WALK_CONTRACT = """
    ## Drive contract

    - button "Export": the button W1 looks at, beside button "Share"
    """

    def test_an_e2e_or_walk_check_needs_a_drive_contract_settled_before_code(self):
        bare = CHECKS.replace(CONTRACT, "\n")
        self.write("plan.md", plan(bare, PERF_NA))
        out = self.run_verify("plan", ok=False)
        self.assertIn("B1 is an e2e or walk check, but the plan has no '## Drive contract' listing what they drive", out)
        self.assertIn("DOM test ids and accessible names, routes and HTTP paths, CLI commands and flags", out)
        self.write("plan.md", plan("# Verification plan: export button\n\n## Checks\n", WALK, PERF_NA))
        self.assertIn("W1 is an e2e or walk check", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(bare, PERF_MAIN))
        self.assertIn("B1, P1 are e2e or walk checks", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(bare.replace("## Checks", "## Drive contract\n\n    ## Checks"), PERF_NA))
        self.assertIn("no '## Drive contract'", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(bare.replace("## Checks", "## Drive contract\n\n    - <test id or route>: <what it is>\n\n    ## Checks"), PERF_NA))
        self.assertIn("Drive contract still holds a template placeholder", self.run_verify("plan", ok=False))
        self.write("plan.md", plan("# Verification plan: mul\n\n## Checks\n", UNIT, PERF_NA))
        self.run_verify("plan")
        self.write("plan.md", plan(CHECKS, WALK, PERF_MAIN))
        self.run_verify("plan")

    def e2e_checks(self, count):
        body = CHECKS.split("## Checks\n")[1]
        return [body.replace("B1", f"E{n}") for n in range(1, count + 1)]

    def test_a_plan_holds_at_most_ten_e2e_checks(self):
        head = CHECKS.split("## Checks\n")[0] + "## Checks\n"
        self.write("plan.md", plan(head, *self.e2e_checks(10), UNIT, WALK, PERF_NA))
        self.assertIn("tiers: e2e 10, unit 1, walk 1", self.run_verify("plan"))
        self.write("plan.md", plan(head, *self.e2e_checks(11), PERF_NA))
        out = self.run_verify("plan", ok=False)
        self.assertIn("11 e2e checks (E1, E2, E3, E4, E5, E6, E7, E8, E9, E10, E11), more than 10. E2E is the most expensive tier, "
                      "so fewer is better: keep only core behavior no unit spec can see, and 10 is a ceiling, not a target. Move the "
                      "rest to the unit tier or drop them, or split the phase", out)
        self.write("plan.md", plan(head, *self.e2e_checks(10), PERF_MAIN))
        self.assertIn("11 e2e checks", self.run_verify("plan", ok=False))

    def test_a_check_outside_the_checks_and_perf_sections_is_refused(self):
        self.write("plan.md", plan(CHECKS, PERF_NA, self.WALK_CONTRACT, UNIT.replace("U1", "U2")))
        self.assertIn("U2 sits under '## Drive contract', where no gate reads it; checks go under '## Checks' or '## Perf'",
                      self.run_verify("plan", "--checks", ok=False))

    def test_touches_is_no_longer_asked_for_and_is_ignored_when_present(self):
        self.write("plan.md", plan(CHECKS, PERF_NA))
        self.run_verify("plan")
        self.write("plan.md", plan(CHECKS.replace("    - Tier: e2e\n", "    - Tier: e2e\n    - Touches: <path glob>\n"), PERF_NA))
        self.run_verify("plan")

    def test_plan_checks_checks_the_checks_part_before_any_drive_contract_exists(self):
        bare = CHECKS.replace(CONTRACT, "\n")
        self.write("plan.md", plan(bare, WALK, PERF_NA, "\n## Sensitive paths\n\n- <path or glob>: <why>\n"))
        self.assertIn("checks ok, 2 checks, 0 oracle checks; tiers: e2e 1, unit 0, walk 1", self.run_verify("plan", "--checks"))
        out = self.run_verify("plan", ok=False)
        self.assertIn("no '## Drive contract'", out)
        self.assertIn("Sensitive paths still holds a template placeholder", out)
        self.write("plan.md", plan(bare, PERF_NA).replace("- Tier: e2e", "- Tier: smoke"))
        self.assertIn("Tier must be e2e, unit, or walk", self.run_verify("plan", "--checks", ok=False))
        self.write("plan.md", plan(bare.split("## Checks\n")[0], "## Checks\n", *self.e2e_checks(11)))
        out = self.run_verify("plan", "--checks", ok=False)
        self.assertIn("11 e2e checks", out)
        self.assertIn("missing '## Perf' section", out)

    NAMED = """
    ### B2. Export over HTTP

    - Scenario: `POST /api/projects/p1/export` with `--format json` on a project with 3 records, then `GET /api/exports?latest=1`
    - Surface: the HTTP API
    - Evidence: B2.rerun.log
    - Pass: the response holds 3 records and `--dry-run` writes nothing; `/health` stays 200 and `exportJson()` is called once
    - Oracle: n/a: the output format is checked, no value is computed
    - Tier: e2e
    """

    def test_every_http_path_and_cli_flag_a_driven_check_names_is_in_the_drive_contract(self):
        self.write("plan.md", plan(CHECKS, self.NAMED, PERF_NA))
        out = self.run_verify("plan", ok=False)
        self.assertIn(":20: B2's Scenario names `/api/projects/p1/export`, which the '## Drive contract' does not list. Settle "
                      "every HTTP path a check drives there before code", out)
        self.assertIn("B2's Scenario names `--format`, which the '## Drive contract' does not list. Settle every CLI flag", out)
        self.assertIn("B2's Scenario names `/api/exports`", out)
        self.assertIn(":23: B2's Pass names `--dry-run`", out)
        self.assertIn("B2's Pass names `/health`", out)
        self.assertNotIn("exportJson", out)
        self.run_verify("plan", "--checks")
        contract = CONTRACT + ("    - `POST /api/projects/:id/export`: starts an export; B2 drives it\n"
                               "    - `GET /api/exports`, `/health`: read the latest export and the liveness probe\n"
                               "    - flags `--format json` and `--dry-run` of the export command\n")
        self.write("plan.md", plan(CHECKS.replace(CONTRACT, contract), self.NAMED, PERF_NA))
        self.run_verify("plan")
        self.write("plan.md", plan(CHECKS.replace(CONTRACT, contract.replace("/api/projects/:id/export", "/api/projects/:id")), self.NAMED, PERF_NA))
        self.assertIn("names `/api/projects/p1/export`", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(CHECKS.replace(CONTRACT, contract.replace("`--dry-run`", "`--dry`")), self.NAMED, PERF_NA))
        self.assertIn("names `--dry-run`", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(CHECKS, self.NAMED.replace("Tier: e2e", "Tier: unit").replace("B2.rerun.log", "units.log"), PERF_NA))
        self.run_verify("plan")

    def test_sensitive_paths_cannot_keep_the_template_placeholder(self):
        self.write("plan.md", plan(CHECKS, PERF_NA, "\n## Sensitive paths\n\n- <path or glob>: <why>\n"))
        self.assertIn("Sensitive paths still holds a template placeholder", self.run_verify("plan", ok=False))
        self.write("plan.md", plan(CHECKS, PERF_NA, "\n## Sensitive paths\n\n- `src/auth/`: sessions and tokens\n"))
        self.run_verify("plan")

    def test_a_walk_pass_needs_a_screenshot_or_video_in_its_evidence_folder(self):
        self.write("plan.md", plan("# Verification plan: export button\n", self.WALK_CONTRACT, "\n## Checks\n", WALK, PERF_NA))
        self.run_verify("freeze")
        report = plan(REPORT).replace("| B1 | PASS | B1-terminal.txt | stdout parsed, 3 records |\n", "").replace(
            "| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |", "| W1 | PASS | evidence/W1/ | Export right of Share |")
        self.write("report.md", report)
        self.write("review.md", review_md())
        folder = self.dir / "evidence" / "W1"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("walked at 390 px\n")
        self.assertIn("W1 is a walk check marked PASS, but evidence/W1/ holds no screenshot or video written after the freeze",
                      self.run_verify("report", ok=False))
        (folder / "walk.mov").write_text("")
        self.assertIn("holds no screenshot or video", self.run_verify("report", ok=False))
        (folder / "share-row.PNG").write_text("png")
        self.assertIn("report ok: 1 checks", self.run_verify("report"))

    def test_the_report_needs_a_triaged_review_and_fix_review_written_after_the_freeze(self):
        self.ready_report()
        (self.dir / "review.md").unlink()
        self.assertIn("no review.md. The reviewer writes a 'Reviewer:' line, then a '## Review' section", self.run_verify("report", ok=False))
        finding = "- src/auth.ts:42 a revoked token still reads the old account's rows."
        self.write("review.md", review_md(findings=finding))
        self.assertIn("review finding has no 'Triage:", self.run_verify("report", ok=False))
        self.write("review.md", review_md(findings=f"{finding} Triage: new check, R1 proves revocation", fix_findings=finding))
        self.assertIn("fix review finding has no 'Triage:", self.run_verify("report", ok=False))
        self.write("review.md", review_md(findings=f"{finding} Triage: fixed in abc124",
                                          fix_findings=f"{finding} Triage: dismissed, the token check runs first on line 30"))
        self.run_verify("report")
        self.write("review.md", review_md(findings=f"{finding}\n  Triage: fixed in abc124, the continuation of its bullet"))
        self.run_verify("report")
        for prose in ("Potential auth bypass in app.py:1", "Base: abc122", "Fixed at: abc124"):
            self.write("review.md", review_md(findings=prose))
            self.assertIn(f"the '## Review' section of review.md holds a line that is not a finding bullet: {prose}; write each finding "
                          "as a bullet with its triage", self.run_verify("report", ok=False), prose)
        self.write("review.md", review_md(fix_findings="none found\nThe fix looks right, but app.py:9 still swallows the error"))
        self.assertIn("the '## Fix review' section of review.md holds a line that is not a finding bullet: The fix looks right",
                      self.run_verify("report", ok=False))
        self.write("review.md", review_md(fix_reviewer="claude:claude-opus-5-5"))
        self.assertIn(f"the fix review's Reviewer claude:claude-opus-5-5 is not the review's {REVIEWER}; the same reviewer reviews "
                      "the fixes", self.run_verify("report", ok=False))
        self.write("review.md", review_md(fix_reviewer="claude:claude-opus-5-5", relaxed="short"))
        self.assertIn("'Relaxed:' line needs the reason", self.run_verify("report", ok=False))
        self.write("review.md", review_md(fix_reviewer="claude:claude-opus-5-5", relaxed="codex was limited until 14:00; quota pick --relax"))
        self.assertIn("fix review relaxed: claude:claude-opus-5-5 took it: codex was limited until 14:00; quota pick --relax",
                      self.run_verify("report"))
        self.write("review.md", review_md().replace(f"Reviewer: {REVIEWER}\n", ""))
        out = self.run_verify("report", ok=False)
        self.assertIn("review.md names no 'Reviewer:' line; the reviewer writes its agent:model under the title", out)
        self.assertIn("the '## Fix review' section of review.md names no 'Reviewer:' line", out)
        self.write("review.md", review_md().replace("Fixed at: abc123\n", ""))
        self.assertIn("the '## Fix review' section of review.md names no 'Fixed at:' line", self.run_verify("report", ok=False))
        self.write("review.md", review_md().split("## Fix review")[0])
        self.assertIn("review.md has no '## Fix review' section", self.run_verify("report", ok=False))
        self.write("review.md", "# Code review\n\nHead: abc123\n\n## Review\n\nnone found\n\n## Fix review\n\n\n")
        out = self.run_verify("report", ok=False)
        self.assertIn("the '## Review' section of review.md names no 'Head:' line", out)
        self.assertIn("the '## Fix review' section of review.md is empty", out)
        self.write("review.md", review_md())
        os.utime(self.dir / "review.md", (1, 1))
        self.assertIn("the review in review.md predates the frozen plan", self.run_verify("report", ok=False))

    FAIL_REPORT = "| Check | Verdict | Evidence | Observed |\n|---|---|---|---|\n| B2 | FAIL | B2.rerun.log | defect: 2 rows, expected 3 |\n"

    def test_a_check_the_report_marks_fail_gets_two_failed_fix_attempts_then_every_rerun_skips_it(self):
        self.check_script("B1.check.sh", "exit 0\n")
        self.check_script("B2.check.sh", "echo still 2 rows\nexit 1\n")
        self.assertNotIn("fix attempt", self.run_verify("rerun", "--only", "B2", ok=False))
        self.assertFalse((self.dir / "fix-attempts.json").exists())
        self.write("report.md", self.FAIL_REPORT)
        self.assertIn("fix attempt 1 of 2 for B2 failed\n", self.run_verify("rerun", "--only", "B2", ok=False))
        self.assertIn("fix attempt 2 of 2 for B2 failed; that was the last one, so the next rerun skips it",
                      self.run_verify("rerun", "--only", "B2", ok=False))
        out = self.run_verify("rerun", "--only", "B1", "B2")
        self.assertIn("SKIP  B2  its fix budget is spent: 2 failed fix attempts since report.md marked it FAIL", out)
        self.assertIn("in an autonomous run put it in the project's backlog with the fix you recommend and leave it FAIL", out)
        self.assertRegex(out, r"PASS\s+B1 ")
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL, 1 skipped past the fix budget", out)
        self.assertNotIn("still 2 rows", out)
        self.assertEqual(json.loads((self.dir / "fix-attempts.json").read_text()), {"B2": 2})
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL, 1 skipped past the fix budget", self.run_verify("rerun"))
        self.new_prove()
        self.check_script("B1.check.sh", "exit 1\n")
        self.assertIn("rerun: 1 checks, 0 PASS, 1 FAIL, 1 skipped past the fix budget", self.run_verify("rerun", ok=False))

    def test_a_fix_that_passes_spends_nothing(self):
        self.check_script("B2.check.sh", "exit 1\n")
        self.write("report.md", self.FAIL_REPORT)
        self.run_verify("rerun", "--only", "B2", ok=False)
        self.check_script("B2.check.sh", "exit 0\n")
        self.assertNotIn("fix attempt", self.run_verify("rerun", "--only", "B2"))
        self.assertEqual(json.loads((self.dir / "fix-attempts.json").read_text()), {"B2": 1})

    def test_the_report_lists_each_full_rerun_and_script_fix(self):
        self.ready_report()
        self.check_script("B1.check.sh", "exit 0\n# waits for the port\n")
        self.run_verify("script-fix", "B1.check.sh", "--reason", "it read the port before the server bound it")
        self.run_verify("rerun", "--full-reason", "the driver changed its seed; agreed by the user")
        self.assertRegex(self.run_verify("report"), r"^report ok: 2 checks have verdicts backed by evidence\n"
                         r"  full rerun \S+: the driver changed its seed; agreed by the user\n"
                         r"  script fix \S+ B1.check.sh: it read the port before the server bound it\n$")

    def test_decision_log_needs_its_header_and_a_verdict_per_attempt(self):
        header = "id\thypothesis\tchange\tbefore\tafter\tdelta\tgate\tverdict\tnote\n"
        self.write("decision.tsv", header + "1\tbatch queries\tjoin orders\t4.1s\t0.9s\t-78%\tgreen\tkept\t\n")
        self.assertIn("1 attempts, 1 kept", self.run_verify("decisions"))
        self.write("decision.tsv", header + "1\tbatch queries\tjoin orders\t4.1s\t0.9s\t-78%\tgreen\tmaybe\t\n")
        self.assertIn("kept or reverted", self.run_verify("decisions", ok=False))


class Driver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "shop"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('shop')\n")
        self.git("add", ".")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Start the shop")
        self.git("checkout", "-qb", "feature/search")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def driver(self, ok=True):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "driver"], cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def add_driver(self):
        skill = self.repo / ".agents" / "skills" / "verify-shop"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: verify-shop\ndescription: x\n---\n")

    def test_needs_a_verification_skill(self):
        self.assertIn("no verification skill", self.driver(ok=False))

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)

    def test_an_uncommitted_driver_does_not_count(self):
        self.add_driver()
        self.assertIn("not committed", self.driver(ok=False))

    def test_passes_when_the_driver_was_committed_before_the_product_change(self):
        self.add_driver()
        self.commit("Add the shop verification skill")
        self.assertIn("committed before any product change", self.driver())
        (self.repo / "app.py").write_text("print('search')\n")
        self.driver()
        self.commit("Add search")
        self.assertIn("committed before any product change", self.driver())

    def test_fails_when_product_code_came_first(self):
        (self.repo / "app.py").write_text("print('search')\n")
        self.commit("Add search")
        self.add_driver()
        self.commit("Add the shop verification skill")
        self.assertIn("before any commit added the verification skill", self.driver(ok=False))

    def driver_base_branch(self, *product):
        (self.repo / "app.py").write_text("print('search')\n")
        self.commit("Add search")
        self.git("checkout", "-qb", "verify-base", "main")
        self.add_driver()
        self.commit("Add the shop verification skill")
        for name in product:
            (self.repo / name).write_text("print('fitted')\n")
            self.commit("Change the product on the driver branch")
        built = subprocess.run(["git", "rev-list", "-1", "HEAD", "--", ".agents"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.git("checkout", "-q", "feature/search")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "cherry-pick", built)

    def test_passes_when_the_driver_was_cherry_picked_from_a_branch_of_driver_commits_on_the_base(self):
        self.driver_base_branch()
        base = subprocess.run(["git", "rev-parse", "main"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual(self.driver(), f"driver ok: .agents/skills/verify-shop was cherry-picked from verify-base, which holds only "
                                        f"driver commits since the phase base {base[:12]}\n")

    def test_a_cherry_picked_driver_from_a_branch_that_also_changed_the_product_fails(self):
        self.driver_base_branch("app.py")
        self.assertIn("changed product files before any commit added the verification skill", self.driver(ok=False))

    def test_a_driver_on_main_always_counts(self):
        self.git("checkout", "-q", "main")
        self.add_driver()
        self.commit("Add the shop verification skill")
        self.git("checkout", "-q", "feature/search")
        self.git("rebase", "-q", "main")
        (self.repo / "app.py").write_text("print('search')\n")
        self.commit("Add search")
        self.assertIn("is on main", self.driver())

    def test_the_report_must_cover_the_current_head(self):
        d = pathlib.Path(self.tmp.name) / "verification"
        d.mkdir()
        (d / "plan.md").write_text(plan(CHECKS, PERF_NA))
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        def run(*a):
            return subprocess.run([sys.executable, "-I", str(VERIFY), *a, "--dir", str(d)], cwd=self.repo, capture_output=True, text=True, env=env)
        run("freeze")
        (d / "B1.check.sh").write_text("exit 0\n")
        run("rerun")
        (d / "B1-terminal.txt").write_text("[{...}]\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        report = plan(REPORT).replace("Head: abc123", f"Head: {head[:9]}").replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", "")
        (d / "report.md").write_text(report)
        (d / "review.md").write_text(review_md(head))
        self.assertEqual(run("report").returncode, 0, run("report").stdout)
        (self.repo / "app.py").write_text("print('later fix')\n")
        self.commit("Fix after verification")
        out = run("report")
        self.assertEqual(out.returncode, 1)
        self.assertIn("but HEAD is now", out.stdout)

    def test_the_report_accepts_a_regrouped_head_with_the_same_tree(self):
        d = pathlib.Path(self.tmp.name) / "verification"
        d.mkdir()
        (d / "plan.md").write_text(plan(CHECKS, PERF_NA))
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        def run(*a):
            return subprocess.run([sys.executable, "-I", str(VERIFY), *a, "--dir", str(d)], cwd=self.repo, capture_output=True, text=True, env=env)
        run("freeze")
        (d / "B1.check.sh").write_text("exit 0\n")
        run("rerun")
        (d / "B1-terminal.txt").write_text("[{...}]\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        report = plan(REPORT).replace("Head: abc123", f"Head: {head[:9]}").replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", "")
        (d / "report.md").write_text(report)
        (d / "review.md").write_text(review_md(head))
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "Regroup commits")
        out = run("report")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"Head {head[:9]} has the same tree as HEAD", out.stdout)
        (self.repo / "app.py").write_text("print('later fix')\n")
        self.commit("Fix after verification")
        out = run("report")
        self.assertEqual(out.returncode, 1)
        self.assertIn("but HEAD is now", out.stdout)

    def reviewed_report(self):
        d = pathlib.Path(self.tmp.name) / "verification"
        d.mkdir()
        (d / "plan.md").write_text(plan(CHECKS, PERF_NA))
        def run(*a):
            return subprocess.run([sys.executable, "-I", str(VERIFY), *a, "--dir", str(d)], cwd=self.repo, capture_output=True, text=True,
                                  env={**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")})
        run("freeze")
        (d / "B1.check.sh").write_text("exit 0\n")
        run("rerun")
        (d / "B1-terminal.txt").write_text("[{...}]\n")
        (d / "review.md").write_text(review_md(self.head()))
        def report():
            (d / "report.md").write_text(plan(REPORT).replace("Head: abc123", f"Head: {self.head()}")
                                         .replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", ""))
            return run("report")
        return d, report, run

    def head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()

    def test_the_review_gate_needs_heads_product_tree_to_be_the_fix_reviews_fixed_at(self):
        d, report, run = self.reviewed_report()
        reviewed = self.head()
        self.assertEqual(run("review").stdout, "review ok: the review and the fix review name the Head they read and triage every finding\n")
        (self.repo / "app.py").write_text("print('fixed')\n")
        self.commit("Fix the review's finding")
        out = run("review")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"product files changed after the fix review's fixes (Fixed at {reviewed[:12]}): app.py. No reviewer read them",
                      out.stdout)
        fixed = self.head()
        (d / "review.md").write_text(review_md(reviewed, fixed, fix_findings="- app.py:1 prints the wrong word."))
        self.assertIn("fix review finding has no 'Triage:", run("review").stdout)
        triaged = "- app.py:1 prints the wrong word. Triage: fixed in the next commit"
        (d / "review.md").write_text(review_md(reviewed, fixed, fix_findings=triaged))
        self.assertEqual(run("review").returncode, 0)
        (self.repo / "app.py").write_text("print('right')\n")
        self.commit("Fix the fix review's finding")
        self.assertIn(f"product files changed after the fix review's fixes (Fixed at {fixed[:12]}): app.py", run("review").stdout)
        (d / "review.md").write_text(review_md(reviewed, fixed, fix_findings=triaged, fixed_at=f"`{self.head()}`"))
        self.assertEqual(run("review").returncode, 0, "Fixed at names the commit that holds the fix review's fixes")
        fixed_at = self.head()
        (self.repo / "auth.py").write_text("ALLOW_ALL = True\n")
        self.commit("An unrelated auth change")
        self.assertIn(f"product files changed after the fix review's fixes (Fixed at {fixed_at[:12]}): auth.py", run("review").stdout)
        (d / "review.md").write_text(review_md(reviewed, fixed, fixed_at=self.head()))
        self.assertIn(f"no fix review finding is triaged fixed, yet product files changed from its Head {fixed[:12]} to Fixed at "
                      f"{self.head()[:12]}: app.py, auth.py. Fixed at is the section's Head when nothing was fixed", run("review").stdout)
        (d / "review.md").write_text(review_md(reviewed, self.head(), fixed_at=reviewed))
        self.assertIn(f"the fix review's Fixed at {reviewed[:12]} does not descend from its Head {self.head()[:12]}", run("review").stdout)
        (d / "review.md").write_text(review_md(reviewed, self.head(), fixed_at="0123456789ab"))
        self.assertIn("the fix review's Fixed at 0123456789ab is not a commit in this repository", run("review").stdout)
        (d / "review.md").write_text(review_md(reviewed, self.head()))
        self.assertEqual(run("review").returncode, 0)
        self.add_driver()
        self.commit("Extend the driver")
        self.assertEqual(run("review").returncode, 0, "a driver commit after Fixed at is not a product change")
        (d / "review.md").write_text(review_md("0123456789ab"))
        self.assertIn("review.md reviewed Head 0123456789ab, which is not a commit in this repository", run("review").stdout)

    def test_an_e2e_pass_needs_a_passing_run_with_no_later_product_change(self):
        d, report, run = self.reviewed_report()
        self.assertEqual(report().returncode, 0, report().stdout)
        ledger = json.loads((d / "rerun.ledger.json").read_text())["B1"]
        self.add_driver()
        self.commit("Add the driver")
        out = report()
        self.assertEqual(out.returncode, 0, out.stdout)
        (self.repo / "src" / "export").mkdir(parents=True)
        (self.repo / "src" / "export" / "json.py").write_text("print('json')\n")
        self.commit("Export JSON")
        out = report()
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"B1 is an e2e check marked PASS, but product files changed since its latest passing run at {ledger['at']} on "
                      f"{ledger['head'][:12]}: src/export/json.py; rerun it once every fix has landed", out.stdout)
        (self.repo / "app.py").write_text("print('uncommitted')\n")
        self.assertIn("1 PASS", run("rerun", "--only", "B1").stdout)
        self.assertEqual(json.loads((d / "rerun.ledger.json").read_text())["B1"]["product_dirty"], ["app.py"])
        self.git("checkout", "--", "app.py")
        out = report()
        self.assertEqual(out.returncode, 1)
        self.assertIn("graded uncommitted product changes (app.py); commit them, then rerun it", out.stdout)
        run("rerun", "--only", "B1")
        out = report()
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_the_report_needs_the_review_heads(self):
        d, report, run = self.reviewed_report()
        (d / "review.md").write_text("# Code review\n\n## Review\n\nnone found\n\n## Fix review\n\nnone found\n")
        out = report().stdout
        self.assertIn("the '## Review' section of review.md names no 'Head:' line", out)
        self.assertIn("the '## Fix review' section of review.md names no 'Head:' line", out)
        (d / "review.md").write_text(review_md("0123456789ab"))
        self.assertIn("review.md reviewed Head 0123456789ab, which is not a commit in this repository", report().stdout)

    def test_where_names_the_repo_and_branch(self):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        out = subprocess.run([sys.executable, "-I", str(VERIFY), "where"], cwd=self.repo, capture_output=True, text=True, env=env).stdout
        self.assertRegex(out.strip(), r"home/shop-[0-9a-f]{8}/feature-search$")
        other = pathlib.Path(self.tmp.name) / "copy"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        out2 = subprocess.run([sys.executable, "-I", str(VERIFY), "where"], cwd=other, capture_output=True, text=True, env=env).stdout
        self.assertNotEqual(out.strip(), out2.strip())


class RerunStamp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "app"
        self.repo.mkdir()
        self.dir = pathlib.Path(self.tmp.name) / "verification"
        self.dir.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('app')\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Start the app")
        self.script("B1.check.sh", 'echo run >> "$(dirname "$0")/runs.txt"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo, check=True, capture_output=True)

    def script(self, name, body):
        (self.dir / name).write_text(body)

    def runs(self):
        return len((self.dir / "runs.txt").read_text().split())

    def rerun(self, *extra, ok=True):
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "rerun", "--dir", str(self.dir), *extra], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def test_a_second_rerun_on_the_same_tree_prints_one_line_without_running(self):
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL", self.rerun())
        out = self.rerun()
        self.assertRegex(out, r"^rerun: 1 checks passed at \S+ on this tree; nothing changed since \(pass --force to run again\)\n$")
        self.assertEqual(self.runs(), 1)

    def script_fix(self, name, ok=True):
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "script-fix", name, "--reason", "it read the port before the server bound it",
                            "--dir", str(self.dir)], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    REASON = ("--full-reason", "regrade the whole tree; agreed by the user")

    def test_force_runs_again_and_restamps(self):
        self.rerun()
        self.assertIn("the prove's full rerun already ran at", self.rerun("--force", ok=False))
        self.assertIn("1 PASS", self.rerun("--force", *self.REASON))
        self.assertEqual(self.runs(), 2)
        self.assertIn("nothing changed", self.rerun())

    def test_a_regrouped_commit_with_the_same_tree_keeps_the_stamp(self):
        self.rerun()
        self.git("commit", "--allow-empty", "-qm", "Regroup")
        self.assertIn("nothing changed", self.rerun())

    def test_a_changed_tree_diff_script_helper_or_args_run_again(self):
        self.rerun()
        (self.repo / "app.py").write_text("print('edited')\n")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.assertIn("nothing changed", self.rerun())
        (self.repo / "app.py").write_text("print('edited again')\n")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.git("commit", "-qam", "Edit")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.assertIn("nothing changed", self.rerun())
        (self.dir / "drive.mjs").write_text("export const a = 1\n")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.assertIn("nothing changed", self.rerun())
        (self.dir / "drive.mjs").write_text("export const a = 2\n")
        self.script_fix("drive.mjs")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.script("B1.check.sh", 'echo run >> "$(dirname "$0")/runs.txt"\n# edited\n')
        self.script_fix("B1.check.sh")
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.assertIn("1 PASS", self.rerun(*self.REASON, "--", "inst-1"))
        self.assertIn("nothing changed", self.rerun("--", "inst-1"))
        self.assertEqual(self.runs(), 8)

    def test_evidence_files_do_not_invalidate_the_stamp(self):
        self.rerun()
        (self.dir / "evidence" / "B1").mkdir(parents=True)
        (self.dir / "evidence" / "B1" / "shot.py").write_text("x\n")
        (self.dir / "B1.observed.json").write_text("{}")
        self.assertIn("nothing changed", self.rerun())

    def test_a_failing_run_deletes_the_stamp(self):
        self.rerun()
        self.assertTrue((self.dir / "rerun.stamp.json").exists())
        self.script("B2.check.sh", "exit 1\n")
        self.rerun(*self.REASON, ok=False)
        self.assertFalse((self.dir / "rerun.stamp.json").exists())
        (self.dir / "B2.check.sh").unlink()
        self.assertIn("1 PASS", self.rerun(*self.REASON))

    def lock(self):
        return json.loads((self.dir / "scripts.lock.json").read_text())

    def test_the_prove_locks_its_scripts_and_a_later_full_rerun_needs_an_agreed_reason(self):
        self.rerun("--only", "B1")
        self.assertFalse((self.dir / "scripts.lock.json").exists())
        self.rerun()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        lock = self.lock()
        digest = hashlib.sha256((self.dir / "B1.check.sh").read_bytes()).hexdigest()
        self.assertEqual((lock["head"], lock["files"], lock["full_reruns"], lock["script_fixes"]), (head, {"B1.check.sh": digest}, [], []))
        (self.repo / "app.py").write_text("print('fixed')\n")
        refusal = (f"verify rerun: the prove's full rerun already ran at {lock['at']}. Grade later changes with nothing: every "
                   "check's latest run passed on HEAD's product code. A full rerun needs --full-reason \"<why; agreed by whom>\", and "
                   "the report lists it.\n")
        self.assertEqual(self.rerun(ok=False), refusal)
        self.git("commit", "-qam", "Fix")
        self.assertIn("Grade later changes with `verify.py rerun --only B1`, the checks whose latest run failed or predates a product "
                      "change. A full rerun needs", self.rerun(ok=False))
        self.git("reset", "-q", "--soft", "HEAD~1")
        self.assertEqual(self.rerun("--full-reason", "rebuilt", ok=False), refusal)
        self.assertIn("1 PASS", self.rerun("--only", "B1"))
        self.assertIn("1 PASS", self.rerun(*self.REASON))
        self.assertEqual([r["why"] for r in self.lock()["full_reruns"]], ["regrade the whole tree; agreed by the user"])
        self.assertEqual(self.runs(), 4)

    def test_a_script_edit_after_the_prove_needs_a_recorded_script_fix_before_any_rerun(self):
        self.assertIn("verify script-fix: no scripts.lock.json in", self.script_fix("B1.check.sh", ok=False))
        self.rerun()
        self.script("B1.check.sh", 'echo run >> "$(dirname "$0")/runs.txt"\nsleep 0\n')
        script = shlex.quote(str(VERIFY))
        refusal = ("verify rerun: B1.check.sh changed since scripts.lock.json recorded it, so a rerun would grade an edit nobody "
                   f"explained. Record why each one changed with: python3 {script} script-fix B1.check.sh --reason "
                   "\"<why it crashed before its predicate>\"\n")
        self.assertEqual(self.rerun("--only", "B1", ok=False), refusal)
        self.assertEqual(self.rerun(*self.REASON, ok=False), refusal)
        self.assertIn("verify script-fix: nope.sh is not a check script or helper that scripts.lock.json recorded; locked: B1.check.sh",
                      self.script_fix("nope.sh", ok=False))
        before = self.lock()["files"]["B1.check.sh"]
        self.assertEqual(self.script_fix("B1.check.sh"), "script fix recorded for B1.check.sh: it read the port before the server bound it\n")
        fix = self.lock()["script_fixes"]
        self.assertEqual([(f["file"], f["before"], f["after"], f["why"]) for f in fix],
                         [("B1.check.sh", before, self.lock()["files"]["B1.check.sh"], "it read the port before the server bound it")])
        self.assertNotEqual(before, fix[0]["after"])
        self.assertIn("verify script-fix: B1.check.sh is unchanged since scripts.lock.json recorded it; script-fix records an edit, so "
                      "edit it first", self.script_fix("B1.check.sh", ok=False))
        self.assertIn("1 PASS", self.rerun("--only", "B1"))
        self.assertIn("the prove's full rerun already ran", self.rerun(ok=False))

    def test_a_script_added_after_the_prove_is_locked_on_its_first_run(self):
        self.rerun()
        self.script("B2.check.sh", "exit 0\n")
        self.rerun("--only", "B2")
        self.assertIn("B2.check.sh", self.lock()["files"])
        self.script("B2.check.sh", "exit 0\n# edited\n")
        self.assertIn("B2.check.sh changed since scripts.lock.json recorded it", self.rerun("--only", "B2", ok=False))

    def test_only_runs_the_named_checks_and_leaves_the_stamp_alone(self):
        self.script("B2.check.sh", 'echo two >> "$(dirname "$0")/runs2.txt"\n')
        self.rerun()
        stamp = (self.dir / "rerun.stamp.json").read_text()
        out = self.rerun("--only", "B2", "--only", "B2")
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL (--only: no stamp; the ledger records these runs)", out)
        self.assertNotIn("B1", out)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(len((self.dir / "runs2.txt").read_text().split()), 2)
        self.assertEqual((self.dir / "rerun.stamp.json").read_text(), stamp)
        self.assertIn("nothing changed", self.rerun())

    def test_a_check_left_fail_after_its_fix_budget_is_skipped_by_the_full_rerun_and_shows_in_the_stamp(self):
        self.script("B2.check.sh", "exit 1\n")
        (self.dir / "report.md").write_text("| Check | Verdict | Evidence | Observed |\n|---|---|---|---|\n| B2 | FAIL | B2.rerun.log | defect: x |\n")
        self.assertIn("fix attempt 1 of 2", self.rerun("--only", "B2", ok=False))
        self.assertIn("B2 still fails with no product or script change since its previous failing run, so this run is not a fix attempt",
                      self.rerun("--only", "B2", ok=False))
        (self.repo / "app.py").write_text("print('fix 1')\n")
        self.assertIn("fix attempt 2 of 2", self.rerun("--only", "B2", ok=False))
        self.assertIn("rerun: 1 checks, 1 PASS, 0 FAIL, 1 skipped past the fix budget", self.rerun())
        out = self.rerun()
        self.assertRegex(out, r"^rerun: 2 checks passed at \S+ on this tree except B2, left FAIL after the fix budget; nothing changed since")

    def test_only_names_a_check_without_a_script(self):
        out = self.rerun("--only", "B9", ok=False)
        self.assertIn("no saved check script for B9; saved: B1", out)
        self.assertFalse((self.dir / "runs.txt").exists())


class Phases(unittest.TestCase):
    CONFORMANCE = """
    ### K1. Phase 1 follows the skeleton

    - Scenario: the public types and signatures phase 1 implements
    - Surface: the source at head
    - Evidence: K1-signatures.diff
    - Pass: the diff against skeleton.patch is empty, or each difference is in the design addendum with the user's agreement
    - Oracle: n/a: compares signatures, no value is computed
    - Tier: e2e
    - Skeleton: src/export.ts: exportJson, ExportOptions
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.dir = self.base / "verification"
        self.root = self.base / "docs" / "export"

    def tearDown(self):
        self.tmp.cleanup()

    def phases(self, *extra, ok=True):
        env = {**os.environ, "VERIFY_HOME": str(self.base / "home")}
        args = [sys.executable, "-I", str(VERIFY), "phases", *extra, "--dir", str(self.dir)]
        r = subprocess.run(args, capture_output=True, text=True, cwd=self.base, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def write_phase(self, name, text):
        folder = self.root / "phases" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.md").write_text(text)

    def test_records_the_plan_folder_so_the_bare_gate_checks_every_phase(self):
        self.write_phase("01-json", plan(CHECKS, PERF_NA))
        self.write_phase("02-csv", plan(CHECKS.replace("B1", "B2"), PERF_NA))
        self.assertIn("phases ok: 2 phases, 2 checks", self.phases(str(self.root)))
        self.assertIn("phases ok: 2 phases", self.phases())

    def test_the_bare_gate_asks_for_the_plan_folder_first(self):
        self.assertIn("verify.py phases <plan folder>", self.phases(ok=False))

    def test_refuses_a_folder_without_phases_or_a_phase_without_a_plan(self):
        self.root.mkdir(parents=True)
        self.assertIn("no phases", self.phases(str(self.root), ok=False))
        (self.root / "phases" / "01-json").mkdir(parents=True)
        self.assertIn("01-json/plan.md: missing", self.phases(ok=False))

    def test_refuses_a_phase_plan_that_breaks_the_plan_rules(self):
        self.write_phase("01-json", plan(CHECKS))
        self.assertIn("missing '## Perf' section", self.phases(str(self.root), ok=False))

    def test_a_phase_plan_holds_checks_only_and_stays_under_the_e2e_cap(self):
        self.write_phase("01-json", plan(CHECKS.replace(CONTRACT, "\n"), PERF_NA))
        self.assertIn("phases ok: 1 phases, 1 checks", self.phases(str(self.root)))
        head, body = CHECKS.split("## Checks\n")
        self.write_phase("01-json", plan(head, "## Checks\n", *(body.replace("B1", f"E{n}") for n in range(1, 12)), PERF_NA))
        self.assertIn("01-json/plan.md:1: 11 e2e checks", self.phases(ok=False))

    def test_refuses_a_check_id_reused_by_another_phase(self):
        self.write_phase("01-json", plan(CHECKS, PERF_NA))
        self.write_phase("02-csv", plan(CHECKS, PERF_NA))
        self.assertIn("id 'B1' is also used in 01-json", self.phases(str(self.root), ok=False))

    def test_with_a_skeleton_every_phase_needs_a_conformance_check(self):
        self.write_phase("01-json", plan(CHECKS, PERF_NA))
        (self.root / "skeleton.patch").write_text("diff --git a/src/export.ts b/src/export.ts\n")
        self.assertIn("no conformance check", self.phases(str(self.root), ok=False))
        self.write_phase("01-json", plan(CHECKS, self.CONFORMANCE, PERF_NA))
        self.assertIn("each with a skeleton conformance check", self.phases())

    def test_a_skeleton_field_still_holding_the_placeholder_does_not_count(self):
        (self.root / "phases").mkdir(parents=True)
        (self.root / "skeleton.patch").write_text("diff\n")
        placeholder = self.CONFORMANCE.replace("src/export.ts: exportJson, ExportOptions", "<files and symbols>")
        self.write_phase("01-json", plan(CHECKS, placeholder, PERF_NA))
        self.assertIn("no conformance check", self.phases(str(self.root), ok=False))


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "calc"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.put("calc.py", "def add(a, b):\n    return a + b\n")
        self.put("tests/test_add.py", self.spec("from calc import add", "self.assertEqual(add(1, 2), 3)"))
        self.commit("Start calc")
        self.base = self.rev()
        self.git("checkout", "-qb", "feature/mul")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def rev(self):
        return self.git("rev-parse", "HEAD")

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)

    def spec(self, imports, body, marker=""):
        return f"{marker}import unittest\n{imports}\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        {body}\n"

    def feature(self, **specs):
        self.put("calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
        for name, text in specs.items():
            self.put(f"tests/{name}.py", text)
        self.commit("Add mul")

    def verify(self, command, *args, ok=True, env=None):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home"), **(env or {})}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), command, *args], cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def units(self, *args, ok=True):
        return self.verify("units", *args, ok=ok)

    NEW = "from calc import mul"
    NEW_BODY = "self.assertEqual(mul(2, 3), 6)"


class Lock(RepoFixture):
    def where(self):
        return pathlib.Path(self.verify("where").strip())

    def write_plan(self, text=None):
        self.where().joinpath("plan.md").write_text(text or plan(CHECKS, PERF_NA))

    def test_locks_before_code_and_keeps_passing_while_the_plan_holds(self):
        self.write_plan()
        self.assertIn("plan locked before code", self.verify("lock"))
        self.feature()
        self.assertIn("unchanged since", self.verify("lock"))
        self.write_plan(plan(CHECKS.replace("3 records", "4 records"), PERF_NA))
        self.assertIn("plan changed after it was frozen", self.verify("lock", ok=False))
        self.verify("freeze", "--revision", "export holds 4 records now; agreed by the user")
        self.verify("lock")

    def test_the_drive_contract_is_locked_with_the_checks(self):
        self.write_plan()
        self.verify("lock")
        self.feature()
        self.write_plan(plan(CHECKS.replace("`export --json`", "`export --format json`"), PERF_NA))
        self.assertIn("plan changed after it was frozen", self.verify("lock", ok=False))
        self.verify("freeze", "--revision", "the flag is --format json to match import; agreed by the user")
        self.verify("lock")

    def test_refuses_once_product_code_has_changed(self):
        self.write_plan()
        self.put(".claude/skills/verify-calc/SKILL.md", "driver\n")
        self.commit("Add the driver")
        self.verify("lock")
        self.where().joinpath("plan.lock").unlink()
        self.put("calc.py", "def add(a, b):\n    return b + a\n")
        self.assertIn("product files already changed", self.verify("lock", ok=False))
        self.git("checkout", "--", "calc.py")
        self.put("mul.py", "def mul(a, b):\n    return a * b\n")
        self.assertIn("mul.py", self.verify("lock", ok=False))

    def test_a_plan_frozen_after_the_code_cannot_pass_as_locked(self):
        self.feature()
        self.write_plan()
        self.verify("freeze")
        self.assertIn("frozen after code existed", self.verify("lock", ok=False))

    def phase(self, name="02-csv", text=None):
        folder = self.repo / "docs" / "export" / "phases" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.md").write_text(text or plan(CHECKS, PERF_NA))
        return folder

    def test_adopt_starts_a_phase_from_its_own_base_and_every_command_reads_the_plan_where_it_lives(self):
        self.feature()
        folder = self.phase()
        self.assertIn(f"adopted 02-csv: 1 checks, base {self.rev()[:12]}; every command reads {folder.resolve() / 'plan.md'}",
                      self.verify("adopt", str(folder)))
        self.assertFalse(self.where().joinpath("plan.md").exists())
        self.assertIn(f"{folder.resolve() / 'plan.md'}: plan ok", self.verify("plan"))
        self.assertIn("plan locked before code", self.verify("lock"))
        (folder / "plan.md").write_text(plan(CHECKS.replace("3 records", "4 records"), PERF_NA))
        self.assertIn("plan changed after it was frozen", self.verify("lock", ok=False))

    def test_adopt_needs_only_the_checks_part(self):
        folder = self.phase(text=plan(CHECKS.replace(CONTRACT, "\n"), PERF_NA))
        self.verify("adopt", str(folder))
        self.verify("plan", "--checks")
        self.assertIn("no '## Drive contract'", self.verify("plan", ok=False))

    def test_adopt_refuses_to_replace_a_different_plan_and_removes_a_matching_copy(self):
        self.write_plan(plan(CHECKS.replace("B1", "Z9"), PERF_NA))
        folder = self.phase("01-json")
        self.assertIn("already holds a different plan", self.verify("adopt", str(folder), ok=False))
        self.write_plan()
        self.verify("adopt", str(folder))
        self.assertFalse(self.where().joinpath("plan.md").exists())
        self.verify("adopt", str(folder))
        self.assertIn("this branch already adopted", self.verify("adopt", str(self.phase("02-csv")), ok=False))

    def test_an_existing_plan_in_the_verification_directory_without_adopt_keeps_working(self):
        self.write_plan()
        self.assertIn(f"{self.where() / 'plan.md'}: plan ok", self.verify("plan"))
        self.verify("lock")

    B2 = """
    ### B2. Export writes CSV

    - Scenario: run export --csv on the sample project with 3 records
    - Surface: a real terminal
    - Evidence: B2.rerun.log
    - Pass: stdout parses as CSV and holds 3 rows
    - Oracle: n/a: the output format is checked, no value is computed
    - Tier: e2e
    """
    CSV = "    - `export --csv`: the CLI command B2 runs\n"

    def locked(self):
        folder = self.phase()
        self.verify("adopt", str(folder))
        self.verify("lock")
        return folder / "plan.md"

    def revisions(self):
        return json.loads(self.where().joinpath("plan.lock").read_text())["revisions"]

    def test_added_checks_and_drive_contract_lines_record_themselves(self):
        path = self.locked()
        path.write_text(plan(CHECKS.replace(CONTRACT, CONTRACT + self.CSV), self.B2, PERF_NA))
        self.assertIn("plan changed after it was frozen. Run `verify.py freeze`", self.verify("lock", ok=False))
        self.assertEqual(self.verify("freeze"), "revision recorded automatically: additions: B2 (Export writes CSV); "
                                                "Drive contract: `export --csv`\n")
        self.verify("lock")
        sensitive = "\n## Sensitive paths\n\n- `src/auth/**`: token checks\n"
        path.write_text(plan(CHECKS.replace(CONTRACT, CONTRACT + self.CSV), self.B2, PERF_NA) + sensitive)
        self.assertEqual(self.verify("freeze"), "revision recorded automatically: Sensitive paths: `src/auth/**`\n")
        self.assertEqual([r.get("auto") for r in self.revisions()], [True, True])
        current = path.read_text()
        for changed, why in ((current.replace("- Surface: a real terminal", "- Surface: a terminal", 1), "B1 Surface changed"),
                             (current.replace("Export writes JSON", "Export prints JSON"), "B1 title changed"),
                             (current.replace("- Tier: e2e\n", "- Tier: e2e\n- Agent: real, the CLI under test\n", 1), "B1 Agent added"),
                             (current.replace("- Tier: e2e\n", "- Tier: e2e\n\nRun it twice.\n", 1), "B1 text changed"),
                             (current.replace("only the help text changes", "only the help changes"),
                              "Perf line removed or changed: n/a: only the help text changes"),
                             (current.replace("- `src/auth/**`: token checks\n", ""), "Sensitive paths line removed or changed: - `src/auth/**`"),
                             (current.replace("# Verification plan: json export", "# Verification plan: json export\n\nAlso CSV."),
                              "the plan's preamble line added: Also CSV.")):
            path.write_text(changed)
            self.assertIn(why, self.verify("freeze", ok=False), why)
        path.write_text(current)
        self.assertEqual(self.verify("freeze"), "plan unchanged since it was frozen\n")

    def test_a_changed_predicate_or_a_removed_check_or_contract_line_needs_a_revision(self):
        path = self.locked()
        for changed, why in ((plan(CHECKS.replace("3 records", "4 records"), PERF_NA), "B1 Pass changed"),
                             (plan(CHECKS.replace("Tier: e2e", "Tier: walk"), PERF_NA), "B1 Tier changed"),
                             (plan(CHECKS.replace("`export --json`", "`export --format json`"), PERF_NA),
                              "Drive contract line removed or changed: - `export --json`"),
                             (plan("# Verification plan: none\n\n## Checks\n", UNIT, PERF_NA), "B1 was removed")):
            path.write_text(changed)
            out = self.verify("freeze", ok=False)
            self.assertIn(f"the plan changed after it was frozen, beyond adding checks, Drive contract lines, or Sensitive paths: {why}", out)
            self.assertIn("--revision \"<what changed and why>\", plus --gate <id> of the autorun gate the user answered", out)
        path.write_text(plan(CHECKS.replace("3 records", "4 records"), PERF_NA))
        self.assertEqual(self.verify("freeze", "--revision", "export holds 4 records now; agreed by the user"),
                         "revision recorded: export holds 4 records now; agreed by the user\n")
        self.verify("lock")

    def autonomous(self, gates):
        home = pathlib.Path(self.tmp.name) / "autorun"
        run = home / "runs" / "r-1"
        (run / "gates").mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({"id": "r-1", "status": "active"}))
        for gate_id, status in gates.items():
            (run / "gates" / f"{gate_id}.json").write_text(json.dumps({"id": gate_id, "status": status, "kind": "irreversible",
                                                                         "created": "2026-10-21T10:00:00+0800", "question": "q"}))
        return {"AUTORUN_HOME": str(home), "AUTORUN_RUN": "r-1"}

    def test_in_an_autonomous_run_a_revision_needs_a_gate_the_user_answered(self):
        path = self.locked()
        env = self.autonomous({"g-aaa": "answered", "g-bbb": "open"})
        path.write_text(plan(CHECKS.replace("3 records", "4 records"), PERF_NA))
        reason = ("--revision", "export holds 4 records now")
        self.assertIn("this is autonomous run r-1, so a change to a check needs the user's answer",
                      self.verify("freeze", *reason, env=env, ok=False))
        self.assertIn("--gate g-zzz: no gate with that id in autonomous run r-1", self.verify("freeze", *reason, "--gate", "g-zzz", env=env, ok=False))
        self.assertIn("gate g-bbb is not answered yet (open)", self.verify("freeze", *reason, "--gate", "g-bbb", env=env, ok=False))
        self.assertIn("revision recorded: export holds 4 records now (gate g-aaa)", self.verify("freeze", *reason, "--gate", "g-aaa", env=env))
        path.write_text(plan(CHECKS.replace("3 records", "5 records"), PERF_NA))
        self.assertIn("gate g-aaa already backs the revision of", self.verify("freeze", *reason, "--gate", "g-aaa", env=env, ok=False))
        path.write_text(plan(CHECKS.replace("3 records", "4 records").replace(CONTRACT, CONTRACT + self.CSV), self.B2, PERF_NA))
        self.assertIn("revision recorded automatically: additions: B2", self.verify("freeze", env=env))
        self.assertEqual(self.revisions()[0]["gate"], "g-aaa")


class Premises(RepoFixture):
    TABLE = ("| Check | Premise | Holds | Evidence | Resolution |\n|---|---|---|---|---|\n"
             "| B1 | export already writes a record list | yes | calc.py:1 | |\n"
             "| B1, P1 | the CLI \\| parses --json | no | bin/export:3 has no flag parser | {resolution} |\n")

    def setUp(self):
        super().setUp()
        self.folder = (self.repo / "docs" / "export" / "phases" / "01-json").resolve()
        self.folder.mkdir(parents=True)
        (self.folder / "plan.md").write_text(plan(CHECKS, PERF_MAIN))
        self.commit("Plan the export")
        self.verify("adopt", str(self.folder))

    def premises(self, *flags, ok=True):
        return self.verify("premises", *flags, ok=ok)

    def based(self, text, base=None):
        return f"Base: {base or self.rev()}\n\n{text}"

    def test_premises_and_grounding_sit_beside_the_plan_and_cover_every_check(self):
        out = self.premises(ok=False)
        self.assertIn(f"no premises.md beside the plan, in {self.folder}", out)
        self.assertIn("no grounding.md beside the plan", out)
        self.assertIn(f"with the line 'Base: {self.rev()}'", out)
        (self.folder / "grounding.md").write_text(self.based("# How export works\n"))
        (self.folder / "premises.md").write_text(self.based(self.TABLE.format(resolution="").replace("| B1, P1 |", "| B1 |")))
        self.assertIn("no premise row for P1; every check of the plan gets at least one row", self.premises(ok=False))
        (self.folder / "premises.md").write_text(self.based(self.TABLE.format(resolution="")))
        self.assertEqual(self.premises(), "premises ok: 2 premises cover 2 checks, 1 do not hold; resolve them in the design, "
                                          "then pass `verify.py premises --resolved`\n")
        self.assertIn(":6: the premise does not hold and has no Resolution", self.premises("--resolved", ok=False))
        (self.folder / "premises.md").write_text(self.based(self.TABLE.format(resolution="the design adds a --json flag to bin/export")))
        self.assertEqual(self.premises("--resolved"), "premises ok: 2 premises cover 2 checks, 1 do not hold, each with its resolution\n")

    def test_each_row_says_whether_it_holds_with_evidence_and_both_files_name_the_base(self):
        (self.folder / "grounding.md").write_text(self.based("# How export works\n"))
        (self.folder / "premises.md").write_text(self.based(self.TABLE.format(resolution="x").replace("| yes | calc.py:1 |", "| maybe |  |")))
        out = self.premises(ok=False)
        self.assertIn(":5: Holds must be yes or no, not 'maybe'", out)
        self.assertIn(":5: Evidence is empty; cite the file:line on main", out)
        (self.folder / "premises.md").write_text(self.based(self.TABLE.format(resolution="x")))
        self.premises()
        base, old = self.rev(), self.git("rev-list", "--max-parents=0", "HEAD")
        (self.folder / "grounding.md").write_text("# How export works\n")
        os.utime(self.folder / "grounding.md")
        self.assertIn(f"{self.folder / 'grounding.md'} names no 'Base: <sha>' line; the explainer writes the commit it checked the code at, "
                      f"the adopted base: 'Base: {base}'", self.premises(ok=False))
        (self.folder / "grounding.md").write_text(self.based("# How export works\n", old))
        self.assertIn(f"{self.folder / 'grounding.md'} was checked at {old}, not at the adopted base {base[:12]}", self.premises(ok=False))
        (self.folder / "grounding.md").write_text(self.based("# How export works\n", f"`{base[:9]}`"))
        self.premises()
        (self.folder / "premises.md").write_text("no table here\n")
        self.assertIn("holds no table with the columns Check | Premise | Holds | Evidence | Resolution", self.premises(ok=False))

    def test_without_a_plan_folder_they_sit_in_the_verification_directory(self):
        where = pathlib.Path(self.verify("where").strip())
        (where / "base.json").unlink()
        (where / "plan.md").write_text(plan(CHECKS, PERF_MAIN))
        base = self.git("merge-base", "main", "HEAD")
        (where / "grounding.md").write_text(self.based("# How export works\n", base))
        (where / "premises.md").write_text(self.based(self.TABLE.format(resolution=""), base))
        self.assertIn("premises ok: 2 premises cover 2 checks", self.premises())


class DryRun(RepoFixture):
    SCRIPT = ('echo "verify: ready"\nif grep -q "def mul" calc.py; then echo "PASS B1: mul exists"; exit 0; fi\n'
              'echo "  not ok: mul is missing"\necho "FAIL B1: 1 of 1 assertions failed"\nexit 1\n')

    def setUp(self):
        super().setUp()
        self.where = pathlib.Path(self.verify("where").strip())
        (self.where / "plan.md").write_text(plan(CHECKS, PERF_NA))
        self.verify("lock")
        self.feature()
        self.worktree = pathlib.Path(self.tmp.name) / "at-base"
        self.git("worktree", "add", "-q", "--detach", str(self.worktree), self.base)
        (self.where / "B1.check.sh").write_text(self.SCRIPT)

    def dryrun(self, *flags, ok=True, base=None):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "dryrun", "--dir", str(self.where), "--base", str(base or self.worktree), *flags],
                           cwd=self.worktree, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def test_every_e2e_script_reaches_ready_and_fails_a_predicate_on_base(self):
        self.assertIn("B1: no B1.base.log; dry-run the script on base with `verify.py dryrun --only B1 --base <worktree at the base>`",
                      self.verify("scripts", ok=False))
        out = self.dryrun()
        self.assertRegex(out, r"FAIL\s+B1  \(\d+\.\ds\)  it reached its predicates and one failed\n")
        self.assertIn(f"dryrun: 1 scripts on base {self.base[:12]}: 1 fail a predicate, 0 pass (behavior already on base), 0 crash", out)
        log = (self.where / "B1.base.log").read_text()
        self.assertTrue(log.startswith("  not ok: mul is missing\nFAIL B1: 1 of 1 assertions failed\n"), log)
        self.assertNotIn("verify: ready\n", log)
        self.assertTrue(log.endswith("dryrun: ready\ndryrun: exit 1\ndryrun: FAIL (it reached its predicates and one failed)\n"), log)
        self.assertEqual(self.verify("scripts"), "scripts ok: 1 e2e checks dry-ran on base, 1 failed a predicate there\n")
        (self.where / "B1.check.sh").write_text(self.SCRIPT + "# edited\n")
        self.assertIn("B1: B1.check.sh changed since its dry run", self.verify("scripts", ok=False))

    def test_a_script_that_crashes_on_base_fails_the_gate(self):
        for body, why in (('echo "verify: ready"\nexit 3\n', "exit 3, not the exit 1 of a failed predicate"),
                          ('echo "FAIL B1: no instance"\nexit 1\n', 'it never printed "verify: ready", so it failed before its instance was up'),
                          ('echo "verify: ready"\necho "TypeError: x is undefined"\nexit 1\n', "exit 1 with no FAIL line last on stdout, so no predicate reported the failure")):
            (self.where / "B1.check.sh").write_text(body)
            self.assertRegex(self.dryrun(ok=False), rf"CRASH B1  \(\d+\.\ds\)  {re.escape(why)}")
            self.assertIn(f"B1: it crashed on base: ({why}). A script reaches \"verify: ready\" and fails on a predicate there",
                          self.verify("scripts", ok=False))

    def test_a_script_that_passes_on_base_is_accepted_with_a_note(self):
        (self.where / "B1.check.sh").write_text('echo "verify: ready"\necho "PASS B1"\n')
        self.assertIn("1 pass (behavior already on base)", self.dryrun())
        self.assertEqual(self.verify("scripts"), "scripts ok: 1 e2e checks dry-ran on base, 0 failed a predicate there\n"
                                                 "note: B1 passes on base, so its behavior already exists there\n")

    def test_the_base_worktree_must_hold_the_base_product_code(self):
        self.assertIn(f"is not at the phase base {self.base[:12]}: its product files differ (calc.py). Check out the base there",
                      self.dryrun(base=self.repo, ok=False))
        self.assertIn("dryrun needs --base <path to a worktree at the phase base>", self.verify("dryrun", ok=False))


class ReportWrite(RepoFixture):
    def setUp(self):
        super().setUp()
        self.where = pathlib.Path(self.verify("where").strip())
        walk_contract = CONTRACT + '    - button "Export": the button W1 looks at\n'
        (self.where / "plan.md").write_text(plan(CHECKS.replace(CONTRACT, walk_contract), UNIT, WALK, PERF_NA))
        self.verify("lock")
        self.feature(test_mul=f"import unittest\n{self.NEW}\n\n\nclass T(unittest.TestCase):\n    def test_U1_mul(self):\n        {self.NEW_BODY}\n")
        self.units()
        (self.where / "B1.check.sh").write_text('echo "3 records"\n')
        self.verify("rerun")
        (self.where / "evidence" / "W1").mkdir(parents=True)
        (self.where / "evidence" / "W1" / "row.png").write_text("png")
        (self.where / "review.md").write_text(review_md(self.rev()))

    def observe(self, **lines):
        (self.where / "observations.md").write_text("".join(f"{k}: {v}\n" for k, v in lines.items()))

    def write(self, *flags, ok=True):
        return self.verify("report", "--write", *flags, ok=ok)

    def report(self):
        return (self.where / "report.md").read_text()

    def test_builds_the_report_from_the_evidence_and_the_observations(self):
        self.assertIn("report --write needs --author <agent:model that wrote the code> and --verifier", self.write(ok=False))
        self.observe(B1="stdout parsed, 3 records", U1="mul(2, 3) is 6")
        out = self.write("--author", "claude:claude-opus-5-5", "--verifier", "codex:gpt-5.6-sol", ok=False)
        self.assertIn("wrote", out)
        self.assertIn("W1 has no observation; the verifier writes 'W1: <what it saw>' in observations.md", out)
        main = self.git("rev-parse", "main")
        self.assertEqual(self.report(), textwrap.dedent(f"""\
            # Verification report: json export

            Head: {self.rev()}
            Main: {main}
            Author: claude:claude-opus-5-5
            Verifier: codex:gpt-5.6-sol

            | Check | Verdict | Evidence | Observed |
            |---|---|---|---|
            | B1 | PASS | B1.rerun.log | stdout parsed, 3 records |
            | U1 | PASS | units.log | mul(2, 3) is 6 |
            | W1 | PASS | evidence/W1/ | missing |
            """))
        self.observe(B1="stdout parsed, 3 records", U1="mul(2, 3) is 6", W1="Export sits right of Share")
        self.assertIn("report ok: 3 checks have verdicts backed by evidence", self.write())
        self.assertIn("Author: claude:claude-opus-5-5", self.report())

    def test_a_fail_or_inconclusive_row_goes_under_not_ready_to_merge(self):
        self.observe(B1="stdout parsed, 3 records", U1="mul(2, 3) is 6", W1="defect: Export wraps below Share | at 390 px")
        out = self.write("--author", "a:x", "--verifier", "b:y")
        self.assertIn("not ready to merge: W1 FAIL; the PR lists them at the top and carries the 'do not merge' label", out)
        self.assertIn("## Not ready to merge\n\n- W1 FAIL: defect: Export wraps below Share | at 390 px\n\nHead:", self.report())
        self.assertIn("| W1 | FAIL | evidence/W1/ | defect: Export wraps below Share \\| at 390 px |", self.report())
        (self.where / "B1.check.sh").write_text('echo "2 records"\nexit 1\n')
        self.verify("script-fix", "B1.check.sh", "--reason", "the fixture now holds 2 records; agreed by the user")
        self.verify("rerun", "--only", "B1", ok=False)
        out = self.write(ok=False)
        self.assertIn("B1 is FAIL; start its Observed cell with 'defect:' and the repro", out)
        self.assertIn("  B1 FAIL: rerun: FAIL (exit 1)", out)
        self.observe(B1="blocker: the instance never came up", U1="mul(2, 3) is 6", W1="Export sits right of Share")
        (self.where / "B1.rerun.log").unlink()
        self.write()
        self.assertIn("| B1 | INCONCLUSIVE | none | blocker: the instance never came up |", self.report())
        self.assertIn("- B1 INCONCLUSIVE: blocker: the instance never came up", self.report())

    def test_notes_go_in_their_own_section_and_survive_a_rewrite(self):
        self.observe(B1="3 records", U1="6", W1="right of Share")
        self.write("--author", "a:x", "--verifier", "b:y", "--note", "reviewer on claude: codex was limited until 14:00", "--note", "second")
        self.assertIn("## Notes\n\n- reviewer on claude: codex was limited until 14:00\n- second\n", self.report())
        self.write()
        self.assertIn("## Notes\n\n- reviewer on claude: codex was limited until 14:00\n- second\n", self.report())
        self.write("--note", "only this")
        self.assertIn("## Notes\n\n- only this\n", self.report())

    def test_a_relaxed_fix_review_is_listed_in_the_report(self):
        self.observe(B1="3 records", U1="6", W1="right of Share")
        (self.where / "review.md").write_text(review_md(self.rev(), fix_reviewer="claude:claude-opus-5-5",
                                                        relaxed="codex was limited until 14:00, so quota pick --relax gave claude"))
        out = self.write("--author", "a:x", "--verifier", "b:y")
        line = "fix review relaxed: claude:claude-opus-5-5 took it: codex was limited until 14:00, so quota pick --relax gave claude"
        self.assertIn(line, out)
        self.assertIn(f"## Revisions and fixes\n\n- {line}\n", self.report())


class Spec(RepoFixture):
    def test_the_spec_change_log_names_the_phase_and_the_later_phases_still_pass(self):
        self.assertIn("spec: no plan folder adopted on this branch", self.verify("spec"))
        root = (self.repo / "docs" / "export").resolve()
        folder = root / "phases" / "01-json"
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(plan(CHECKS, PERF_NA))
        self.verify("adopt", str(folder))
        self.assertIn(f"no spec.md in the plan folder (the plan-feature skill writes it) at {root / 'spec.md'}", self.verify("spec", ok=False))
        (root / "spec.md").write_text("# Export\n\nThe design.\n")
        self.assertIn("has no '## Change log' section; add it with a line for 01-json", self.verify("spec", ok=False))
        (root / "spec.md").write_text("# Export\n\n## Change log\n\n- 01-json-old: renamed the flag\n\n## Later\n\n01-json\n")
        self.assertIn("'## Change log' has no line for 01-json. Log what this phase changed in the design", self.verify("spec", ok=False))
        (root / "spec.md").write_text("# Export\n\n## Change log\n\n- 01-json: no design change\n")
        self.assertEqual(self.verify("spec"), "spec ok: spec.md's change log names 01-json; phases ok: 1 phases, 1 checks\n")
        (root / "phases" / "02-csv").mkdir()
        self.assertIn("02-csv/plan.md: missing", self.verify("spec", ok=False))


    def test_an_older_adopt_record_names_its_phase_through_the_plan_copy(self):
        root = (self.repo / "docs" / "export").resolve()
        for name, check in (("01-json", "B1"), ("02-csv", "C1")):
            (root / "phases" / name).mkdir(parents=True)
            (root / "phases" / name / "plan.md").write_text(plan(CHECKS.replace("B1", check), PERF_NA))
        where = pathlib.Path(self.verify("where").strip())
        where.mkdir(parents=True, exist_ok=True)
        (where / "base.json").write_text(json.dumps({"base": self.rev(), "plan": str(root)}))
        (where / "plan.md").write_text(plan(CHECKS, PERF_NA))
        (root / "spec.md").write_text("# Export\n\n## Change log\n\n- 02-csv: no design change\n")
        self.assertIn("'## Change log' has no line for 01-json", self.verify("spec", ok=False))
        (root / "spec.md").write_text("# Export\n\n## Change log\n\n- 01-json: no design change\n")
        self.assertEqual(self.verify("spec"), "spec ok: spec.md's change log names 01-json; phases ok: 2 phases, 2 checks\n")
        (where / "plan.md").write_text(plan(CHECKS.replace("B1", "Z9"), PERF_NA))
        out = self.verify("spec", ok=False)
        self.assertIn(f"this branch records the plan folder {root}, but no phase under {root / 'phases'} holds the checks", out)
        self.assertIn("Run `verify.py adopt <phase folder>` with this branch's phase", out)
        (where / "plan.md").unlink()
        self.assertIn("but no phase under", self.verify("spec", ok=False))


class Units(RepoFixture):
    def test_specs_that_fail_on_base_and_pass_at_head_satisfy_the_gate(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        out = self.units(f"{self.base}..{self.rev()}")
        self.assertRegex(out, r"OK\s+tests/test_mul.py")
        self.assertIn("units: 1 specs, 1 fail on base and pass at head", out)

    def test_no_argument_defaults_to_the_merge_base_with_main(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        self.assertRegex(self.units(), r"OK\s+tests/test_mul.py")
        self.git("checkout", "-q", "main")
        self.put("README.md", "main moved on\n")
        self.commit("Move main")
        self.git("checkout", "-q", "feature/mul")
        out = self.units()
        self.assertRegex(out, r"OK\s+tests/test_mul.py")
        self.assertNotIn("README", out)

    def test_a_spec_that_passes_on_base_is_not_new_behavior(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY), test_vacuous=self.spec("from calc import add", "self.assertEqual(add(2, 2), 4)"))
        out = self.units(ok=False)
        self.assertRegex(out, r"OK\s+tests/test_mul.py")
        self.assertRegex(out, r"PASSES ON BASE\s+tests/test_vacuous.py")
        self.assertIn("1 pass without the implementation", out)

    def test_a_marked_regression_guard_may_pass_on_base_but_not_fail_at_head(self):
        guard = self.spec("from calc import add", "self.assertEqual(add(2, 2), 4)", marker="# regression-guard\n")
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY), test_guard=guard)
        out = self.units()
        self.assertRegex(out, r"GUARD\s+tests/test_guard.py")
        self.assertIn("1 regression guards", out)
        self.put("tests/test_guard.py", self.spec("from calc import add", "self.assertEqual(add(2, 2), 5)", marker="# regression-guard\n"))
        self.commit("Break the guard")
        self.assertRegex(self.units(ok=False), r"FAILS AT HEAD\s+tests/test_guard.py")

    def test_a_spec_that_fails_at_head_fails_the_gate(self):
        self.feature(test_mul=self.spec(self.NEW, "self.assertEqual(mul(2, 3), 7)"))
        self.assertRegex(self.units(ok=False), r"FAILS AT HEAD\s+tests/test_mul.py")

    def test_a_changed_spec_runs_against_base_code_with_the_new_spec(self):
        self.feature()
        self.put("tests/test_add.py", self.spec("from calc import add, mul", self.NEW_BODY))
        self.commit("Extend the add spec")
        self.assertRegex(self.units(), r"OK\s+tests/test_add.py")

    def test_no_new_or_changed_spec_fails_the_gate(self):
        self.feature()
        self.assertIn("no spec files", self.units(ok=False))

    def test_test_cmd_replaces_the_detected_runner_and_receives_the_spec_path(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        marker = pathlib.Path(self.tmp.name) / "ran.txt"
        cmd = f"echo {{files}} >> {marker} && {shlex.quote(sys.executable)} -m unittest {{files}}"
        self.assertRegex(self.units("--test-cmd", cmd), r"OK\s+tests/test_mul.py")
        self.assertEqual(marker.read_text().split(), ["tests/test_mul.py"] * 2)

    def test_a_worktree_cannot_leak_into_the_checkout(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        self.units()
        self.assertEqual(self.git("worktree", "list").count("\n"), 0)
        self.assertEqual(self.git("status", "--porcelain"), "")


class FixAttempts(RepoFixture):
    def setUp(self):
        super().setUp()
        self.where = pathlib.Path(self.verify("where").strip())
        (self.where / "plan.md").write_text(plan(CHECKS, PERF_NA))
        (self.where / "B1.check.sh").write_text('test ! -e "$(dirname "$0")/B1.broken"\n')
        (self.where / "report.md").write_text(Verify.FAIL_REPORT.replace("B2", "B1"))

    def attempts(self):
        path = self.where / "fix-attempts.json"
        return json.loads(path.read_text()).get("B1", 0) if path.is_file() else 0

    def test_a_failing_run_is_a_fix_attempt_only_when_a_product_file_or_its_script_changed(self):
        (self.where / "B1.broken").write_text("x\n")
        self.verify("rerun", "--only", "B1", ok=False)
        self.assertEqual(self.attempts(), 1)
        self.assertIn("not a fix attempt", self.verify("rerun", "--only", "B1", ok=False))
        self.put("docs/notes.md", "a plan note\n")
        self.verify("adopt", str(self.plan_folder()))
        self.commit("Plan only")
        self.assertIn("not a fix attempt", self.verify("rerun", "--only", "B1", ok=False))
        self.put("calc.py", "def add(a, b):\n    return b + a\n")
        self.assertIn("fix attempt 2 of 2 for B1 failed", self.verify("rerun", "--only", "B1", ok=False))
        self.assertIn("SKIP  B1  its fix budget is spent", self.verify("rerun", "--only", "B1"))

    def plan_folder(self):
        folder = self.repo / "docs" / "phases" / "01-mul"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.md").write_text(plan(CHECKS, PERF_NA))
        (self.where / "plan.md").unlink(missing_ok=True)
        return folder

    def test_the_ledger_records_the_script_and_the_uncommitted_product_changes_of_each_run(self):
        self.put("calc.py", "def add(a, b):\n    return b + a\n")
        self.verify("rerun", "--only", "B1")
        entry = json.loads((self.where / "rerun.ledger.json").read_text())["B1"]
        self.assertEqual((entry["head"], entry["product_dirty"], entry["verdict"]), (self.rev(), ["calc.py"], "PASS"))
        self.assertEqual(entry["script"], hashlib.sha256((self.where / "B1.check.sh").read_bytes()).hexdigest())
        self.assertEqual(len(entry["product_patch"]), 64)


class UnitTier(RepoFixture):
    def report(self, ok=True):
        head = self.rev()
        (self.where / "review.md").write_text(review_md(head))
        (self.where / "report.md").write_text(textwrap.dedent(f"""\
            # Verification report: mul

            Head: {head[:12]}
            Main: {self.base[:12]}
            Author: claude:claude-sonnet-5-5
            Verifier: claude:claude-opus-5-5

            | Check | Verdict | Evidence | Observed |
            |---|---|---|---|
            | U1 | PASS | units.log | the spec fails on base and passes at head |

            ## Review

            none found
            """))
        return self.verify("report", ok=ok)

    def named_spec(self, body):
        return f"import unittest\n{self.NEW}\n\n\nclass T(unittest.TestCase):\n    def test_U1_mul_multiplies(self):\n        {body}\n"

    def test_a_unit_pass_needs_a_passing_units_run_on_head_whose_spec_names_the_check(self):
        self.where = pathlib.Path(self.verify("where").strip())
        (self.where / "plan.md").write_text(plan("# Verification plan: mul\n\n## Checks\n", UNIT, PERF_NA))
        self.verify("lock")
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        self.assertIn("U1 is a unit check marked PASS, but no `verify.py units` result is recorded", self.report(ok=False))
        self.units()
        self.assertIn("no spec in the last `verify.py units` run names U1; put the check id in the title of the test that proves it",
                      self.report(ok=False))
        self.put("tests/test_mul.py", self.named_spec(self.NEW_BODY))
        self.commit("Name the check the mul spec proves")
        self.assertIn("the last `verify.py units` ran on other product code than HEAD's", self.report(ok=False))
        self.units()
        self.assertEqual(json.loads((self.where / "units.json").read_text())["specs"], {"tests/test_mul.py": {"verdict": "ok", "checks": ["U1"]}})
        self.assertIn("report ok: 1 checks", self.report())
        self.put("tests/test_mul.py", self.named_spec("self.assertEqual(mul(2, 3), 7)"))
        self.commit("Break the mul spec")
        self.units(ok=False)
        self.assertIn("FAILS AT HEAD  tests/test_mul.py", (self.where / "units.log").read_text())
        self.assertIn("the last `verify.py units` run failed", self.report(ok=False))

    def test_a_later_commit_outside_the_product_keeps_the_units_run_and_the_report_current(self):
        self.where = pathlib.Path(self.verify("where").strip())
        (self.where / "plan.md").write_text(plan("# Verification plan: mul\n\n## Checks\n", UNIT, PERF_NA))
        self.verify("lock")
        self.feature(test_mul=self.named_spec(self.NEW_BODY))
        self.units()
        reported = self.rev()
        self.assertIn("report ok: 1 checks", self.report())
        self.put(".claude/skills/verify-calc/SKILL.md", "# Drive calc\n")
        self.commit("Extend the driver")
        out = self.verify("report")
        self.assertIn("report ok: 1 checks", out)
        self.assertIn(f"Head {reported[:12]} differs from HEAD {self.rev()[:12]} only in the plan folder or the driver", out)
        self.put("README.md", "calc multiplies\n")
        self.commit("Document mul")
        out = self.verify("report", ok=False)
        self.assertIn("ran on other product code than HEAD's", out)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return not subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip().startswith("Z")


def gone(pid, wait=5):
    deadline = time.time() + wait
    while alive(pid) and time.time() < deadline:
        time.sleep(0.05)
    return not alive(pid)


def wait_for_file(path, wait=10):
    deadline = time.time() + wait
    while not path.exists() and time.time() < deadline:
        time.sleep(0.05)
    return int(path.read_text())


class Leftovers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.root = self.base / "instance"
        self.root.mkdir()
        self.sleepers = []
        self.addCleanup(self.reap_sleepers)

    def tearDown(self):
        self.tmp.cleanup()

    def reap_sleepers(self):
        for p in self.sleepers:
            if p.poll() is None:
                p.kill()
            p.wait()
            if p.stdout:
                p.stdout.close()

    def spawn(self, cwd, *argv):
        p = subprocess.Popen(argv or ["sleep", "300"], cwd=cwd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sleepers.append(p)
        time.sleep(0.2)
        return p

    def orphan(self, cwd):
        r = subprocess.run(["sh", "-c", "sleep 300 >/dev/null 2>&1 & echo $!"], cwd=cwd, capture_output=True, text=True)
        pid = int(r.stdout)
        self.addCleanup(lambda: os.kill(pid, signal.SIGKILL) if alive(pid) else None)
        time.sleep(0.2)
        return pid

    def leftovers(self, *args, ok=True, cwd=None, env=None):
        full = {**os.environ, "HOME": str(self.base / "home"), "VERIFY_HOME": str(self.base / "home"), **(env or {})}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "leftovers", *args], cwd=cwd or self.base, capture_output=True, text=True, env=full)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def test_lists_a_detached_process_under_a_root_and_kill_removes_it(self):
        p = self.spawn(self.root)
        out = self.leftovers("--root", str(self.root), ok=False)
        self.assertRegex(out, rf"\b{p.pid}\b.*{self.root}")
        self.assertIn("leftovers --kill", out)
        out = self.leftovers("--kill", "--root", str(self.root))
        self.assertIn("none", out)
        self.assertTrue(gone(p.pid))
        self.assertIn("none", self.leftovers("--root", str(self.root)))

    def test_a_process_started_since_a_running_delegate_began_is_in_use_and_never_killed(self):
        orphan = self.spawn(self.root)
        time.sleep(2)
        since = time.time()
        busy = self.spawn(self.root, sys.executable, "-c", "import time; time.sleep(300)", str(self.root / "bridge.js"))
        out = self.leftovers("--root", str(self.root), "--running-since", str(since), ok=False)
        listed, _, spared = out.partition("in use by a running agent")
        self.assertRegex(listed, rf"\bpid {orphan.pid}\b")
        self.assertNotRegex(listed, rf"\bpid {busy.pid}\b")
        self.assertIn("1 still running", listed)
        self.assertRegex(spared, rf"\bpid {busy.pid}\b")
        out = self.leftovers("--kill", "--root", str(self.root), "--running-since", str(since))
        self.assertRegex(out, rf"^leftovers: killed 1, none remain\n1 in use by a running agent, started after it began, so neither counted nor killed:\npid {busy.pid}\b")
        self.assertTrue(gone(orphan.pid))
        self.assertTrue(alive(busy.pid))
        self.assertRegex(self.leftovers("--root", str(self.root), ok=False), rf"\bpid {busy.pid}\b")

    def test_the_leads_own_processes_and_their_descendants_are_spared_and_never_killed(self):
        leftover = self.spawn(self.root)
        child = self.base / "child.pid"
        lead = self.spawn(self.root, "sh", "-c", f": VERIFY_LEAD=1; sleep 300 & echo $! > {shlex.quote(str(child))}; wait")
        sleeper = wait_for_file(child)
        self.addCleanup(lambda: os.kill(sleeper, signal.SIGKILL) if alive(sleeper) else None)
        out = self.leftovers("--kill", "--root", str(self.root))
        self.assertRegex(out, rf"^leftovers: killed 1, none remain\n2 spared, started by the lead \(VERIFY_LEAD=1\), so neither counted "
                              rf"nor killed:\npid {lead.pid} .*\npid {sleeper} .*\n")
        self.assertTrue(gone(leftover.pid))
        self.assertTrue(alive(lead.pid) and alive(sleeper))
        self.assertIn("2 spared, started by the lead", self.leftovers("--root", str(self.root)))

    @unittest.skipUnless(pathlib.Path("/proc/self/environ").is_file(), "only Linux exposes another process's environment")
    def test_a_process_whose_environment_holds_the_lead_marker_is_spared(self):
        p = subprocess.Popen(["sleep", "300"], cwd=self.root, start_new_session=True, env={**os.environ, "VERIFY_LEAD": "1"})
        self.sleepers.append(p)
        time.sleep(0.2)
        self.assertRegex(self.leftovers("--kill", "--root", str(self.root)), rf"1 spared, started by the lead .*\npid {p.pid} ")
        self.assertTrue(alive(p.pid))

    def test_a_process_ignoring_sigterm_is_killed(self):
        script = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(300)\n"
        p = subprocess.Popen([sys.executable, "-c", script], cwd=self.root, start_new_session=True, stdout=subprocess.PIPE, text=True)
        self.sleepers.append(p)
        p.stdout.readline()
        self.leftovers("--kill", "--root", str(self.root))
        self.assertTrue(gone(p.pid))

    def test_a_process_whose_cwd_was_deleted_is_still_found(self):
        doomed = self.root / "state"
        doomed.mkdir()
        p = self.spawn(doomed)
        shutil.rmtree(doomed)
        self.assertRegex(self.leftovers("--root", str(self.root), ok=False), rf"\b{p.pid}\b")

    def test_a_process_is_found_by_a_command_path_under_a_root(self):
        p = self.spawn(self.base, sys.executable, "-c", "import time; time.sleep(300)", str(self.root / "server.js"))
        self.assertRegex(self.leftovers("--root", str(self.root), ok=False), rf"\b{p.pid}\b")

    def test_a_process_outside_every_root_is_left_alone(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        p = self.spawn(elsewhere)
        self.assertIn("none", self.leftovers("--root", str(self.root)))
        self.assertTrue(alive(p.pid))

    def test_named_roots_come_from_the_environment_and_globs(self):
        home, scratch = self.base / "hello-home", self.base / "scratchpad"
        salvo = pathlib.Path(tempfile.mkdtemp(prefix="salvo-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, salvo, True)
        for d in (home, scratch):
            d.mkdir()
        procs = [self.spawn(d).pid for d in (home, scratch, salvo)]
        out = self.leftovers(ok=False, env={"PARLOR_VERIFY_HOME": str(home), "VERIFY_SCRATCHPAD": str(scratch)})
        for pid in procs:
            self.assertRegex(out, rf"\b{pid}\b")

    def test_orphans_in_any_worktree_of_the_repo_are_leftovers_but_the_users_live_processes_are_not(self):
        repo = self.base / "shop"
        repo.mkdir()
        def run(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
        run("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a")
        run("add", ".")
        run("commit", "-qm", "a")
        tree = self.base / "shop-feature"
        run("worktree", "add", "-q", "--detach", str(tree))
        working = self.spawn(tree)
        orphans = [self.orphan(tree), self.orphan(repo)]
        out = self.leftovers(ok=False, cwd=repo)
        for pid in orphans:
            self.assertRegex(out, rf"\b{pid}\b")
        self.assertNotRegex(out, rf"\b{working.pid}\b")

    def test_the_verification_dir_is_a_root(self):
        p = self.spawn(self.root)
        self.assertRegex(self.leftovers("--dir", str(self.root), ok=False), rf"\b{p.pid}\b")

    def test_the_caller_and_its_ancestors_are_never_listed(self):
        shell = f"{shlex.quote(sys.executable)} {shlex.quote(str(VERIFY))} leftovers --root {shlex.quote(str(self.root))}; exit $?"
        r = subprocess.run(["sh", "-c", shell], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_kill_spares_the_callers_own_process_group(self):
        shell = f"sleep 20 & {shlex.quote(sys.executable)} {shlex.quote(str(VERIFY))} leftovers --kill --root {shlex.quote(str(self.root))}; code=$?; wait; exit $code"
        r = subprocess.run(["sh", "-c", shell], cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_kill_fails_while_a_process_survives(self):
        p = self.spawn(self.root)
        with mock.patch.object(verify, "signal_processes"), mock.patch.object(verify, "KILL_WAIT_S", 0.2), \
                mock.patch.object(verify, "default_roots", return_value=[]), mock.patch.object(verify, "worktree_paths", return_value=[]):
            with self.assertRaises(verify.Failed) as raised:
                verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=True, running_since=None))
        self.assertIn(str(p.pid), str(raised.exception))

    def test_high_load_with_nothing_left_names_the_top_cpu_processes(self):
        table = [
            {"pid": 900, "ppid": 1, "pgid": 900, "stat": "R", "elapsed": "3-02:00:00", "cpu": 310.0, "command": "node drizzle-kit studio"},
            {"pid": 901, "ppid": 4242, "pgid": 901, "stat": "R", "elapsed": "00:10", "cpu": 90.0, "command": "vitest run"},
            {"pid": 902, "ppid": 1, "pgid": 902, "stat": "S", "elapsed": "01:00", "cpu": 0.0, "command": "idle"},
        ]
        cwds = {900: "/work/app", 901: "/work/app"}
        with mock.patch.object(verify, "process_table", return_value=table), mock.patch.object(verify, "process_cwds", return_value=cwds), \
                mock.patch.object(verify.os, "getloadavg", return_value=(50.0, 40.0, 30.0)), mock.patch.object(verify.os, "cpu_count", return_value=8), \
                mock.patch.object(verify, "default_roots", return_value=[]), mock.patch.object(verify, "worktree_paths", return_value=[]):
            out = verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=False, running_since=None))
        self.assertIn("load 50.0 exceeds 8 cores", out)
        first, second = [line for line in out.splitlines() if "drizzle-kit" in line or "vitest" in line]
        self.assertIn("900", first)
        self.assertIn("likely leftover", first)
        self.assertIn("/work/app", first)
        self.assertNotIn("likely leftover", second)
        self.assertNotIn("idle", out)

    def test_a_scan_that_cannot_run_exits_2_not_1(self):
        with mock.patch.object(verify.subprocess, "run", side_effect=FileNotFoundError("ps")):
            with self.assertRaises(verify.CannotScan):
                verify.process_table()
        self.assertEqual((verify.Failed.code, verify.CannotScan.code), (1, 2))

    def test_normal_load_prints_no_cpu_report(self):
        with mock.patch.object(verify.os, "getloadavg", return_value=(0.5, 0.5, 0.5)), \
                mock.patch.object(verify, "default_roots", return_value=[]), mock.patch.object(verify, "worktree_paths", return_value=[]):
            out = verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=False, running_since=None))
        self.assertNotIn("exceeds", out)


class ProcCwds(unittest.TestCase):
    def test_reads_only_numbered_process_entries_from_proc(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = pathlib.Path(tmp)
            for name, cwd in (("41", "/srv/app"), ("42", "/srv/gone (deleted)")):
                (proc / name).mkdir()
                (proc / name / "cwd").symlink_to(cwd)
            (proc / "self").symlink_to(proc / "41")
            (proc / "thread-self").mkdir()
            (proc / "sys").mkdir()
            self.assertEqual(verify.process_cwds(proc), {41: "/srv/app", 42: "/srv/gone"})


class LeadProcesses(unittest.TestCase):
    def row(self, pid, ppid, command):
        return {"pid": pid, "ppid": ppid, "pgid": pid, "stat": "S", "elapsed": "00:10", "cpu": 0.0, "command": command}

    def test_a_marked_environment_or_command_line_marks_the_process_and_every_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = pathlib.Path(tmp)
            for pid, environ in ((10, b"HOME=/h\0VERIFY_LEAD=1\0"), (20, b"VERIFY_LEAD=10\0"), (40, b"PATH=/bin\0")):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "environ").write_bytes(environ)
            table = [self.row(10, 1, "node watch.js"), self.row(11, 10, "sh -c tail"), self.row(12, 11, "tail -f log"),
                     self.row(20, 1, "sleep 9"), self.row(30, 1, "sh -c 'VERIFY_LEAD=1 tail -f log'"), self.row(31, 30, "tail -f log"),
                     self.row(40, 1, "echo XVERIFY_LEAD=1 VERIFY_LEAD=12"), self.row(50, 40, "sleep 1")]
            from_lead = verify.lead_test(table, proc)
            self.assertEqual({row["pid"] for row in table if from_lead(row["pid"])}, {10, 11, 12, 30, 31})


class Capacity(unittest.TestCase):
    BUSY = {"pid": 900, "ppid": 1, "pgid": 900, "stat": "R", "elapsed": "01:00", "cpu": 200.0, "command": "node vitest"}

    def row(self, pid, command):
        return {"pid": pid, "ppid": 4242, "pgid": pid, "stat": "R", "elapsed": "00:30", "cpu": 50.0, "command": command}

    def capacity(self, load, table, *, native=False, cores=10, env=None):
        with mock.patch.object(verify, "process_table", return_value=table), mock.patch.object(verify, "process_cwds", return_value={}), \
                mock.patch.object(verify.os, "getloadavg", return_value=(load, load, load)), mock.patch.object(verify.os, "cpu_count", return_value=cores), \
                mock.patch.dict(os.environ):
            os.environ.pop("VERIFY_MAX_LOAD_RATIO", None)
            os.environ.update(env or {})
            return verify.cmd_capacity(None, mock.Mock(native=native))

    def test_passes_below_the_threshold_with_no_native_build(self):
        out = self.capacity(3.0, [self.BUSY])
        self.assertEqual(out, "capacity: load 3.0, cores 10, threshold 7.0, native builds running: none")

    def test_refuses_at_or_above_the_threshold_and_names_the_busiest_processes(self):
        with self.assertRaises(verify.Failed) as raised:
            self.capacity(7.0, [self.BUSY])
        message = str(raised.exception)
        self.assertIn("load 7.0, cores 10, threshold 7.0", message)
        self.assertIn("node vitest", message)
        self.assertIn("likely leftover", message)

    def test_the_ratio_comes_from_the_environment(self):
        self.assertIn("threshold 9.0", self.capacity(8.0, [], env={"VERIFY_MAX_LOAD_RATIO": "0.9"}))
        with self.assertRaises(verify.Failed):
            self.capacity(8.0, [], env={"VERIFY_MAX_LOAD_RATIO": "0.5"})
        with self.assertRaises(verify.CannotScan):
            self.capacity(1.0, [], env={"VERIFY_MAX_LOAD_RATIO": "lots"})

    def test_a_native_build_is_only_reported_without_native(self):
        table = [self.row(31, "/usr/bin/xcodebuild -scheme App build"), self.row(32, "cargo build --release")]
        out = self.capacity(1.0, table)
        self.assertIn("native builds running: 2 (pids 31, 32)", out)

    def test_a_native_build_refuses_with_native(self):
        table = [self.row(31, "node /app/node_modules/.bin/tauri build"), self.row(32, "./gradlew assembleDebug"), self.row(33, "npx cap sync ios")]
        with self.assertRaises(verify.Failed) as raised:
            self.capacity(1.0, table, native=True)
        self.assertIn("native builds running: 3 (pids 31, 32, 33)", str(raised.exception))
        self.assertIn("a native build is running", str(raised.exception))

    def test_shells_and_this_process_tree_never_count_as_builds(self):
        table = [self.row(41, "bash -c cargo build"), self.row(42, "grep xcodebuild"), self.row(43, "cargo test"),
                 {**self.row(os.getpid(), "python3 verify.py capacity --native cap run"), "ppid": 1}]
        self.assertIn("native builds running: none", self.capacity(1.0, table, native=True))

    def test_the_command_exits_1_on_refusal(self):
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "capacity"], capture_output=True, text=True,
                           env={**os.environ, "VERIFY_MAX_LOAD_RATIO": "0.0001"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("capacity: load", r.stdout)


class RerunTimeout(unittest.TestCase):
    def rerun_timeout(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            (directory / "B1.check.sh").write_text("exit 0\n")
            done = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(verify, "run_in_group", return_value=done) as run, \
                    mock.patch.object(sys, "argv", ["verify.py", "rerun", "--dir", tmp, *extra]), contextlib.redirect_stdout(io.StringIO()):
                verify.main()
            return run.call_args.args[1]

    def test_defaults_to_300_seconds_and_timeout_raises_it(self):
        self.assertEqual(self.rerun_timeout(), 300)
        self.assertEqual(self.rerun_timeout("--timeout", "600"), 600)


class RunGroup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def grandchild_command(self):
        return f"sleep 20 & echo $! > {shlex.quote(str(self.base / 'pid'))}; wait"

    def test_a_timed_out_spec_dies_with_its_grandchildren(self):
        ok, detail = verify.run_spec(self.base, self.grandchild_command(), 1)
        self.assertEqual((ok, detail), (False, "timed out after 1s"))
        self.assertTrue(gone(int((self.base / "pid").read_text())))

    def test_rerun_timeouts_kill_the_script_tree(self):
        directory = self.base / "verification"
        directory.mkdir()
        script = directory / "B1.check.sh"
        script.write_text(f"#!/bin/sh\n{self.grandchild_command()}\n")
        script.chmod(0o755)
        env = {**os.environ, "VERIFY_HOME": str(self.base / "home")}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), "rerun", "--dir", str(directory), "--timeout", "1"], capture_output=True, text=True, env=env, cwd=self.base)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("timed out after 1s", r.stdout)
        self.assertTrue(gone(int((self.base / "pid").read_text())))

    def test_a_scratch_tree_kills_processes_running_in_it_before_removal(self):
        repo = self.base / "repo"
        repo.mkdir()
        def run(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
        run("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a")
        run("add", ".")
        run("commit", "-qm", "a")
        with verify.scratch_tree(repo, "HEAD") as tree:
            p = subprocess.Popen(["sleep", "300"], cwd=tree, start_new_session=True)
        self.assertTrue(gone(p.pid))
        p.wait()
        self.assertFalse(tree.exists())

    def test_a_spec_in_a_scratch_tree_runs_with_pnpm_deps_check_off(self):
        tree = self.base / "tree"
        tree.mkdir()
        ok, tail = verify.run_spec(tree, 'printf "%s" "$pnpm_config_verify_deps_before_run"', 30)
        self.assertEqual((ok, tail.strip()), (True, "false"))


if __name__ == "__main__":
    unittest.main()
