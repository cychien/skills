"""The ten-step feature flow, run end to end through the real guard, autorun hook, and verify CLIs on a tiny repo."""
import datetime
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "skills" / "orchestrator" / "guard" / "scripts" / "guard.py"
HOOK = ROOT / "skills" / "orchestrator" / "autorun" / "scripts" / "autorun.py"
VERIFY = ROOT / "skills" / "eng" / "verify" / "scripts" / "verify.py"
FEATURE = ROOT / "skills" / "eng" / "feature" / "SKILL.md"
PHASE = "01-mul"

AFTER = {1: [], 2: [1], 3: [2], 4: [3], 5: [4], 6: [4], 7: [5], 8: [6, 7], 9: [8], 10: [9]}
GATES = {1: {"plan --checks"}, 2: {"premises"}, 3: {"plan", "premises --resolved"}, 4: {"lock"}, 5: {"units"}, 6: {"scripts"},
         7: {"review"}, 8: {"oracles"}, 9: set(), 10: {"report", "spec", "leftovers"}}
MANDATORY = {1, 2, 3, 4, 5, 7, 8, 10}

PLAN = """\
    # Verification plan: mul

    ## Checks

    ### E1. The command line multiplies

    - Scenario: run `calc.py mul 2 3 --json` in the repository
    - Surface: a real terminal
    - Evidence: E1.rerun.log
    - Pass: stdout is the JSON object {"product": 6}
    - Oracle: n/a: a fixed product of two literals, no data is read
    - Tier: e2e

    ### U1. Multiplying two numbers

    - Scenario: mul(2, 3) in the calc module
    - Surface: the calc module
    - Evidence: units.log
    - Pass: mul(2, 3) returns 6
    - Oracle: n/a: a fixed product of two literals, no data is read
    - Tier: unit

    ## Perf

    n/a: multiplying two numbers is nothing a user waits on
    """
CONTRACT = """
    ## Drive contract

    - `calc.py mul <a> <b> --json`: the command E1 runs, printing a JSON object whose product is a times b

    ## Sensitive paths

    - calc.py: the only module the change touches
    """
PREMISES = """\
    Base: {base}

    | Check | Premise | Holds | Evidence | Resolution |
    |---|---|---|---|---|
    | E1 | calc.py already has a command line | no | calc.py:1 defines only add | {resolution} |
    | U1 | the calc module exports functions a spec imports | yes | calc.py:1, tests/test_add.py:2 | |
    """
CALC = """\
    import json
    import sys


    def add(a, b):
        return a + b


    def mul(a, b):
        return a * b


    if __name__ == "__main__" and sys.argv[1:2] == ["mul"] and "--json" in sys.argv:
        print(json.dumps({"product": mul(int(sys.argv[2]), int(sys.argv[3]))}))
    """
UNIT_SPEC = """\
    import unittest

    from calc import mul


    class Mul(unittest.TestCase):
        def test_U1_mul_multiplies(self):
            self.assertEqual(mul(2, 3), 6)
    """
CHECK_SCRIPT = """\
    echo "verify: step setup within 30"
    echo "verify: ready"
    echo "verify: step mul within 10"
    out=$({python} calc.py mul 2 3 --json 2>&1)
    if [ "$out" = '{{"product": 6}}' ]; then echo "PASS E1: mul 2 3 prints 6"; exit 0; fi
    echo "  not ok: expected {{\\"product\\": 6}}, got: $out"
    echo "FAIL E1: 1 of 1 assertions failed"
    exit 1
    """


def dedent(text):
    return textwrap.dedent(text)


class FlowV2(unittest.TestCase):
    """Each step closes only in order, with the token `todo show` prints, once its gate passes on the artifacts the step makes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.root = pathlib.Path(self.tmp.name).resolve()
        self.repo = base / "calc"
        self.env = {**os.environ, "HOME": str(base / "home"), "GUARD_HOME": str(base / "guard"), "AUTORUN_HOME": str(base / "autorun"),
                    "ORCHESTRATOR_HOME": str(base / "orchestrator"), "VERIFY_HOME": str(base / "verify"),
                    "GUARD_SKILL_ROOTS": os.pathsep.join(str(p) for p in sorted(ROOT.glob("skills/*")) if p.is_dir()),
                    "GUARD_HEADLESS": "0", "VERIFY_MAX_LOAD_RATIO": "1000",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for k in ("AUTORUN_RUN", "AUTORUN_DISABLE", "CURSOR_VERSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "PARLOR_VERIFY_HOME",
                  "VERIFY_SCRATCHPAD", "VERIFY_LEAD", "VERIFY_DRYRUN", "VERIFY_DIR"):
            self.env.pop(k, None)
        (base / "home").mkdir()
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.put("calc.py", "def add(a, b):\n    return a + b\n")
        self.put("tests/test_add.py", "import unittest\nfrom calc import add\n\n\nclass Add(unittest.TestCase):\n"
                                      "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
        self.commit("Start calc")
        self.plan_root = self.repo / "docs" / "mul"
        self.phase = self.plan_root / "phases" / PHASE
        self.put(f"docs/mul/phases/{PHASE}/plan.md", dedent(PLAN))
        self.put("docs/mul/spec.md", "# Mul\n\nThe calc module multiplies two numbers.\n\n## Change log\n\n- plan: first version\n")
        self.commit("Plan mul")
        models = base / "orchestrator" / "models.json"
        models.parent.mkdir(parents=True)
        models.write_text(json.dumps({"version": 2, "roles": {
            "planner": [{"agent": "codex", "model": "gpt-5.6", "effort": "high"}, {"agent": "claude", "model": "opus", "effort": "high"}],
            "executor": [{"agent": "claude", "model": "sonnet", "effort": "high"}, {"agent": "codex", "model": "gpt-5.6", "effort": "medium"}]}}))

    def run_cli(self, argv, ok=True, cwd=None):
        r = subprocess.run(argv, cwd=cwd or self.repo, capture_output=True, text=True, env=self.env)
        if ok is not None:
            self.assertEqual(r.returncode == 0, ok, f"{shlex.join(map(str, argv))}\n{r.stdout}{r.stderr}")
        return r.stdout + r.stderr

    def git(self, *args):
        return self.run_cli(["git", *args]).strip()

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def verify(self, *args, ok=True, cwd=None):
        return self.run_cli([sys.executable, str(VERIFY), *args], ok=ok, cwd=cwd)

    def todo(self, *args, ok=True):
        return self.run_cli([sys.executable, str(GUARD), "todo", *map(str, args), "--session", "claude:s1"], ok=ok)

    def guard(self, *args, ok=True):
        return self.run_cli([sys.executable, str(GUARD), *args], ok=ok)

    def token(self, n):
        shown = self.todo("show", n)
        last = shown.strip().splitlines()[-1]
        self.assertRegex(last, r"^token: [0-9a-f]{6}$")
        return last.split()[1]

    def close(self, n, ok=True):
        return self.todo("done", n, "--token", self.token(n), ok=ok)

    def items(self):
        return {i["n"]: i for i in json.loads((pathlib.Path(self.env["GUARD_HOME"]) / "sessions" / "claude-s1.json").read_text())["todo"]}

    def hook(self, event, payload, agent="claude"):
        payload = {"session_id": "s1", "cwd": str(self.repo), **payload}
        r = subprocess.run([sys.executable, str(HOOK), "hook", agent, event], input=json.dumps(payload), capture_output=True, text=True,
                           env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        errors = pathlib.Path(self.env["AUTORUN_HOME"]) / "errors.log"
        self.assertFalse(errors.exists(), errors.read_text() if errors.exists() else "")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def denied(self, payload):
        out = self.hook("PreToolUse", payload)
        self.assertIsNotNone(out, payload)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def bash(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def gates(self, text):
        sys.path.insert(0, str(GUARD.parent))
        try:
            from guard_lib import gates
            return {" ".join(args) for _, _, args in gates.named(text)}
        finally:
            sys.path.remove(str(GUARD.parent))

    def test_the_feature_flow_closes_every_step_in_order_on_its_gate(self):
        self.assertIn("Copied 10 steps from feature", self.todo("from", "feature"))
        items = self.items()
        self.assertEqual({n: i["after"] for n, i in items.items()}, AFTER)
        self.assertEqual({n for n, i in items.items() if i["mandatory"]}, MANDATORY)
        self.assertEqual({n: self.gates(i["text"]) for n, i in items.items()}, GATES)
        self.assertTrue(all(i["source_path"] == str(FEATURE) for i in items.values()))

        self.assertIn("item 2 waits on item 1", self.todo("done", 2, "--token", self.token(2), ok=False))
        self.assertIn("needs proof you read it", self.todo("done", 1, ok=False))
        self.assertIn("does not match its current text", self.todo("done", 1, "--token", "000000", ok=False))

        self.git("checkout", "-qb", "feature/mul")
        self.assertIn("adopted 01-mul: 2 checks", self.verify("adopt", str(self.phase)))
        where = pathlib.Path(self.verify("where").strip())
        self.assertFalse((where / "plan.md").exists())
        base = self.git("rev-parse", "HEAD")
        self.assertIn("Item 1 done.", self.close(1))

        self.assertIn("the gate `../verify/scripts/verify.py premises` failed", self.close(2, ok=False))
        (self.phase / "grounding.md").write_text("# How calc works\n\ncalc.py holds add; tests import it.\n")
        (self.phase / "premises.md").write_text(dedent(PREMISES).format(base=base, resolution=""))
        self.assertIn("grounding.md names no 'Base: <sha>' line", self.close(2, ok=False))
        (self.phase / "grounding.md").write_text(f"Base: {base}\n\n# How calc works\n\ncalc.py holds add; tests import it.\n")
        self.close(2)

        shown = self.todo("show", 3)
        self.assertIn("--- ../principles/SKILL.md ---", shown)
        self.assertIn("no '## Drive contract'", self.close(3, ok=False))
        self.put(f"docs/mul/phases/{PHASE}/plan.md", dedent(PLAN) + dedent(CONTRACT))
        self.assertIn("the premise does not hold and has no Resolution", self.close(3, ok=False))
        (self.phase / "premises.md").write_text(dedent(PREMISES).format(base=base, resolution="the design adds a command line to calc.py"))
        spec = self.plan_root / "spec.md"
        spec.write_text(spec.read_text() + f"- {PHASE}: calc.py gains a mul command line, because premise E1 does not hold\n")
        self.commit("Design mul")
        self.close(3)

        self.assertIn("plan locked before code", self.verify("lock"))
        self.close(4)

        self.assertIn("item 7 waits on item 5", self.todo("done", 7, "--token", self.token(7), ok=False))
        check = where / "E1.check.sh"
        check.write_text(dedent(CHECK_SCRIPT).format(python=shlex.quote(sys.executable)))
        self.assertIn("no E1.base.log", self.close(6, ok=False))
        at_base = self.root / "at-base"
        self.git("worktree", "add", "-q", "--detach", str(at_base), base)
        dry = self.verify("dryrun", "--dir", str(where), "--base", str(at_base), cwd=at_base)
        self.assertIn("1 fail a predicate, 0 pass (behavior already on base), 0 crash", dry)
        self.assertTrue((where / "E1.base.log").read_text().endswith("dryrun: FAIL (it reached its predicates and one failed)\n"))
        self.assertIn("Item 6 done.", self.close(6))

        self.assertEqual(self.guard("quota", "pick", "--role", "executor").strip(), "claude:sonnet:high")
        limit = "Claude usage limit reached. Your limit will reset at 11:59pm."
        self.hook("PostToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "Implement mul."}, "tool_response": {"content": [{"type": "text", "text": limit}]}})
        self.assertIn("No agent is limited", self.guard("quota", "status"))
        self.hook("PostToolUseFailure", {**self.bash("claude -p --model sonnet < t.md"), "error": f"Exit code 1\n{limit}"})
        self.assertIn("claude: limited until", self.guard("quota", "status"))
        self.assertEqual(self.guard("quota", "pick", "--role", "executor").strip(), "codex:gpt-5.6:medium")
        self.assertIn("claude is limited until", self.denied(self.bash("python3 /x/salvo/scripts/salvo.py run --out /tmp/s claude:sonnet:high < t.md")))

        self.assertIn("no spec files were added or changed", self.close(5, ok=False))
        self.put("calc.py", dedent(CALC))
        self.put("tests/test_mul.py", dedent(UNIT_SPEC))
        head = self.commit("Add mul")
        units = self.verify("units", "--test-cmd", f"{shlex.quote(sys.executable)} -m unittest {{files}}")
        self.assertIn("units: 1 specs, 1 fail on base and pass at head", units)
        self.assertEqual(json.loads((where / "units.json").read_text())["specs"]["tests/test_mul.py"]["checks"], ["U1"])
        self.close(5)

        self.assertIn("item 8 waits on item 7", self.todo("done", 8, "--token", self.token(8), ok=False))
        review = (f"# Code review\n\nReviewer: codex:gpt-5.6\n\n## Review\n\nHead: {head}\n\n"
                  "- calc.py: a non-integer argument raises ValueError. Triage: follow-up: no user flow passes one; in the backlog\n\n"
                  f"## Fix review\n\nHead: {head}\nReviewer: claude:sonnet\n\nnone found\n")
        (where / "review.md").write_text(review)
        refused = self.close(7, ok=False)
        self.assertIn("the fix review's Reviewer claude:sonnet is not the review's codex:gpt-5.6", refused)
        self.assertIn("names no 'Fixed at:' line", refused)
        review = review.replace("Reviewer: claude:sonnet\n", f"Reviewer: codex:gpt-5.6\nFixed at: {head}\n")
        (where / "review.md").write_text(review)
        self.close(7)

        self.hook("PreToolUse", {"agent_id": "fix-1", **self.bash("ls")})
        self.assertIn("A fix group is still working", self.denied(self.bash("python3 ../verify/scripts/verify.py rerun")))
        self.hook("SubagentStop", {"agent_id": "fix-1", "last_assistant_message": "Fixed the error message."})
        self.assertIsNone(self.hook("PreToolUse", self.bash("python3 ../verify/scripts/verify.py rerun")))
        self.assertRegex(self.verify("rerun"), r"E1 PASS ")
        self.assertEqual((where / "E1.rerun.log").read_text().splitlines()[-1], "rerun: PASS")
        (where / "observations.md").write_text('E1: stdout was {"product": 6}\nU1: mul(2, 3) returned 6 in tests/test_mul.py\n')
        written = self.verify("report", "--write", "--author", "codex:gpt-5.6", "--verifier", "claude:sonnet")
        self.assertIn("report ok: 2 checks have verdicts backed by evidence", written)
        report = (where / "report.md").read_text()
        self.assertIn('| E1 | PASS | E1.rerun.log | stdout was {"product": 6} |', report)
        self.assertIn("| U1 | PASS | units.log | mul(2, 3) returned 6 in tests/test_mul.py |", report)
        self.assertNotIn("Not ready to merge", report)
        self.close(8)

        create = self.bash("gh pr create --title 'feat: mul' --body '## Scope\nx'")
        self.assertIn("The PR opens in item 10", self.denied(create))
        self.todo("skip", 9, "--reason", "nothing failed")
        self.assertIsNone(self.hook("PreToolUse", create))

        spec.write_text(spec.read_text() + f"- {PHASE}: shipped as designed; the backlog holds non-integer arguments\n")
        self.commit("Reconcile the mul spec")
        if "none remain" not in self.verify("leftovers", ok=None):
            self.skipTest("another agent on this machine has processes under /tmp/salvo-*, which the leftovers gate counts")
        closed = self.close(10)
        self.assertIn("Every item is resolved", closed)
        self.assertIn("Every item is resolved", self.todo("check"))

    def test_a_timed_hold_lets_an_autonomous_turn_end_with_open_steps(self):
        home = pathlib.Path(self.env["AUTORUN_HOME"])
        home.mkdir(parents=True)
        (home / "config.json").write_text(json.dumps({"review": False}))
        self.hook("UserPromptSubmit", {"prompt": "going to bed, build the mul feature"})
        run = next((home / "active").iterdir()).name
        self.run_cli([sys.executable, str(HOOK), "start", "--run", run, "--session", "claude:s1", "--done", "the PR is open"])
        self.todo("from", "feature")
        self.assertEqual(self.hook("Stop", {"last_assistant_message": "Waiting for the codex limit."})["decision"], "block")
        later = (datetime.datetime.now() + datetime.timedelta(minutes=90)).strftime("%H:%M")
        self.assertIn(f"Held until {later}", self.todo("hold", "--until", later, "--reason", "codex limit for E1"))
        out = self.hook("Stop", {"last_assistant_message": "Waiting for the codex limit."})
        self.assertNotIn("decision", out)
        self.assertRegex(out["systemMessage"], rf"paused on a timed hold until {re.escape(later)}: codex limit for E1")
        self.assertIn("[ ] 1.", self.todo("check", ok=False))


if __name__ == "__main__":
    unittest.main()
