import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERIFY = ROOT / "skills" / "eng" / "verify" / "scripts" / "verify.py"
TEMPLATES = ROOT / "skills" / "eng" / "verify" / "references"
spec = importlib.util.spec_from_file_location("verify", VERIFY)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

CHECKS = """\
    # Verification plan: json export

    ## Checks

    ### B1. Export writes JSON

    - Scenario: run export --json on the sample project with 3 records
    - Surface: a real terminal
    - Evidence: the terminal transcript
    - Pass: stdout parses as JSON and holds 3 records
    - Oracle: n/a: the output format is checked, no value is computed
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

    ## Exploration

    none found
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

    def run_verify(self, command, *extra, ok=True, cwd=None):
        args = [sys.executable, "-I", str(VERIFY), command, *extra]
        if cwd is None:
            args += ["--dir", str(self.dir)]
        env = {**os.environ, "VERIFY_HOME": str(self.base / "home")}
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

    def ready_report(self):
        self.write("plan.md", plan(CHECKS, PERF_MAIN))
        self.run_verify("freeze")
        self.write("B1-terminal.txt", "[{...}]\n")
        self.write("P1-runs.txt", "41 ms\n")
        self.write("report.md", plan(REPORT))

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

    def test_the_report_needs_an_exploration_section(self):
        self.ready_report()
        self.write("report.md", plan(REPORT).split("## Exploration")[0])
        self.assertIn("Exploration", self.run_verify("report", ok=False))

    def test_every_exploration_finding_needs_a_triage(self):
        self.ready_report()
        found = plan(REPORT).replace("none found", "- A 20-digit customer id drops the connection instead of a 404.")
        self.write("report.md", found)
        self.assertIn("has no 'Triage:", self.run_verify("report", ok=False))
        self.write("report.md", found.replace("instead of a 404.", "instead of a 404. Triage: follow-up, the error wording only; user agreed"))
        self.run_verify("report")
        self.write("report.md", found.replace("instead of a 404.", "instead of a 404. Triage: pre-existing, main crashes the same way"))
        self.run_verify("report")

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
    """

    def oracle_plan(self, oracle=ORACLE):
        self.write("plan.md", plan(CHECKS, oracle, PERF_NA))

    def test_every_check_states_its_oracle(self):
        self.oracle_plan(self.ORACLE.split("    - Oracle:")[0])
        self.assertIn("missing '- Oracle:'", self.run_verify("plan", ok=False))
        self.oracle_plan(self.ORACLE.split("    - Oracle:")[0] + "    - Oracle: n/a: x\n")
        self.assertIn("Oracle n/a needs a reason", self.run_verify("plan", ok=False))
        self.oracle_plan(self.ORACLE.split("    - Oracle:")[0] + "    - Oracle: n/a: the page only echoes a stored total\n")
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
        self.write("B1-terminal.txt", "[{...}]\n")
        self.write("A1.expected.json", '{"wholesale": 1200, "retail": 300}')
        self.write("A1.observed.json", '{"wholesale": 1200, "retail": 310}')
        self.write("report.md", self.oracle_report())
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
        run = lambda *a: subprocess.run([sys.executable, "-I", str(VERIFY), *a, "--dir", str(d)], cwd=self.repo, capture_output=True, text=True, env=env)
        run("freeze")
        (d / "B1-terminal.txt").write_text("[{...}]\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        report = plan(REPORT).replace("Head: abc123", f"Head: {head[:9]}").replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", "")
        (d / "report.md").write_text(report)
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
        run = lambda *a: subprocess.run([sys.executable, "-I", str(VERIFY), *a, "--dir", str(d)], cwd=self.repo, capture_output=True, text=True, env=env)
        run("freeze")
        (d / "B1-terminal.txt").write_text("[{...}]\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        report = plan(REPORT).replace("Head: abc123", f"Head: {head[:9]}").replace("| P1 | PASS | P1-runs.txt | p50 41 ms on both sides |\n", "")
        (d / "report.md").write_text(report)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "Regroup commits")
        out = run("report")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"Head {head[:9]} has the same tree as HEAD", out.stdout)
        (self.repo / "app.py").write_text("print('later fix')\n")
        self.commit("Fix after verification")
        out = run("report")
        self.assertEqual(out.returncode, 1)
        self.assertIn("but HEAD is now", out.stdout)

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

    def test_force_runs_again_and_restamps(self):
        self.rerun()
        self.assertIn("1 PASS", self.rerun("--force"))
        self.assertEqual(self.runs(), 2)
        self.assertIn("nothing changed", self.rerun())

    def test_a_regrouped_commit_with_the_same_tree_keeps_the_stamp(self):
        self.rerun()
        self.git("commit", "--allow-empty", "-qm", "Regroup")
        self.assertIn("nothing changed", self.rerun())

    def test_a_changed_tree_diff_script_helper_or_args_run_again(self):
        self.rerun()
        (self.repo / "app.py").write_text("print('edited')\n")
        self.assertIn("1 PASS", self.rerun())
        self.assertIn("nothing changed", self.rerun())
        (self.repo / "app.py").write_text("print('edited again')\n")
        self.assertIn("1 PASS", self.rerun())
        self.git("commit", "-qam", "Edit")
        self.assertIn("1 PASS", self.rerun())
        self.assertIn("nothing changed", self.rerun())
        (self.dir / "drive.mjs").write_text("export const a = 1\n")
        self.assertIn("1 PASS", self.rerun())
        self.assertIn("nothing changed", self.rerun())
        (self.dir / "drive.mjs").write_text("export const a = 2\n")
        self.assertIn("1 PASS", self.rerun())
        self.script("B1.check.sh", 'echo run >> "$(dirname "$0")/runs.txt"\n# edited\n')
        self.assertIn("1 PASS", self.rerun())
        self.assertIn("1 PASS", self.rerun("--", "inst-1"))
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
        self.rerun(ok=False)
        self.assertFalse((self.dir / "rerun.stamp.json").exists())
        (self.dir / "B2.check.sh").unlink()
        self.assertIn("1 PASS", self.rerun())


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

    def verify(self, command, *args, ok=True):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        r = subprocess.run([sys.executable, "-I", str(VERIFY), command, *args], cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout

    def units(self, *args, ok=True):
        return self.verify("units", *args, ok=ok)

    NEW = "from calc import mul"
    NEW_BODY = "self.assertEqual(mul(2, 3), 6)"


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
        run = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
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
                verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=True))
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
            out = verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=False))
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
            out = verify.cmd_leftovers(None, mock.Mock(root=[str(self.root)], kill=False))
        self.assertNotIn("exceeds", out)


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
        run = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
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


class Commits(RepoFixture):
    TESTS = f"{shlex.quote(sys.executable)} -m unittest discover -s tests"

    def commits(self, *args, ok=True):
        return self.verify("commits", "--cmd", self.TESTS, *args, ok=ok)

    def test_each_commit_gets_a_verdict_and_a_broken_one_fails_the_run(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        self.put("calc.py", "def add(a, b):\n    return 0\n\n\ndef mul(a, b):\n    return a * b\n")
        self.commit("Break add")
        broken = self.rev()
        self.put("calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
        self.commit("Fix add")
        out = self.commits(ok=False)
        lines = [line for line in out.splitlines() if line.startswith(("PASS", "FAIL"))]
        self.assertEqual([line.split()[0] for line in lines], ["PASS", "FAIL", "PASS"])
        self.assertIn(broken[:12], lines[1])
        self.assertIn("Break add", lines[1])
        self.assertIn("commits: 3 checked, 2 PASS, 1 FAIL", out)

    def test_an_explicit_range_limits_the_commits(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        self.put("README.md", "docs\n")
        self.commit("Docs")
        out = self.commits(f"{self.base}..HEAD~1")
        self.assertIn("Add mul", out)
        self.assertNotIn("Docs", out)

    def test_a_spec_only_commit_reports_its_result_without_failing_the_run(self):
        self.feature()
        self.put("tests/test_mul.py", self.spec(self.NEW, "self.assertEqual(mul(2, 3), 7)"))
        self.commit("Pin multiplication")
        out = self.commits()
        self.assertRegex(out, r"FAIL .*Pin multiplication.*spec-only")
        self.assertIn("commits: 2 checked", out)
        self.put("tests/test_other.py", self.spec(self.NEW, "self.assertEqual(mul(2, 3), 7)"))
        self.put("README.md", "docs\n")
        self.commit("test: red spec with docs")
        self.assertRegex(self.commits(), r"FAIL .*test: red spec with docs.*spec-only")

    def test_a_hung_commit_times_out_and_leaves_no_process(self):
        self.feature()
        pidfile = pathlib.Path(self.tmp.name) / "pid"
        hang = f"sleep 20 & echo $! > {shlex.quote(str(pidfile))}; wait"
        out = self.verify("commits", "--cmd", hang, "--timeout", "1", ok=False)
        self.assertRegex(out, r"FAIL .*Add mul.*timed out after 1s")
        self.assertTrue(gone(int(pidfile.read_text())))
        self.assertEqual(self.git("worktree", "list").count("\n"), 0)

    def test_a_process_left_running_by_a_commit_fails_it_and_is_killed(self):
        self.feature()
        pidfile = pathlib.Path(self.tmp.name) / "pid"
        spawn = "import subprocess, sys; p = subprocess.Popen(['sleep', '20'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); open(sys.argv[1], 'w').write(str(p.pid))"
        out = self.verify("commits", "--cmd", f"{shlex.quote(sys.executable)} -c {shlex.quote(spawn)} {shlex.quote(str(pidfile))}", ok=False)
        self.assertRegex(out, r"FAIL .*Add mul.*leftover")
        self.assertTrue(gone(wait_for_file(pidfile)))

    def test_the_typecheck_runs_first_and_a_failure_skips_the_tests(self):
        self.feature()
        marker = pathlib.Path(self.tmp.name) / "tests-ran"
        out = self.verify("commits", "--typecheck", "exit 3", "--cmd", f"touch {shlex.quote(str(marker))}", ok=False)
        self.assertRegex(out, r"FAIL .*Add mul.*typecheck")
        self.assertFalse(marker.exists())

    def test_an_empty_range_is_an_error(self):
        self.assertIn("no commits", self.verify("commits", "--cmd", "true", ok=False))

    def test_the_test_command_is_detected_when_not_given(self):
        self.feature(test_mul=self.spec(self.NEW, self.NEW_BODY))
        out = self.verify("commits")
        self.assertIn("commits: 1 checked, 1 PASS, 0 FAIL", out)


if __name__ == "__main__":
    unittest.main()
