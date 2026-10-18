import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERIFY = ROOT / "skills" / "eng" / "verify" / "scripts" / "verify.py"
TEMPLATES = ROOT / "skills" / "eng" / "verify" / "references"

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

    def test_where_names_the_repo_and_branch(self):
        env = {**os.environ, "VERIFY_HOME": str(pathlib.Path(self.tmp.name) / "home")}
        out = subprocess.run([sys.executable, "-I", str(VERIFY), "where"], cwd=self.repo, capture_output=True, text=True, env=env).stdout
        self.assertRegex(out.strip(), r"home/shop-[0-9a-f]{8}/feature-search$")
        other = pathlib.Path(self.tmp.name) / "copy"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        out2 = subprocess.run([sys.executable, "-I", str(VERIFY), "where"], cwd=other, capture_output=True, text=True, env=env).stdout
        self.assertNotEqual(out.strip(), out2.strip())


if __name__ == "__main__":
    unittest.main()
