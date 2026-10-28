"""The feature flow, run end to end through the real guard, autorun hook, and verify CLIs on a tiny repo."""
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

AFTER = {1: [], 2: [1], 3: [2], 4: [3], 5: [3], 6: [4, 5]}
GATES = {1: set(), 2: set(), 3: set(), 4: set(), 5: {"review"}, 6: {"review"}}
MANDATORY = {5, 6}

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
def dedent(text):
    return textwrap.dedent(text)


class FeatureFlow(unittest.TestCase):
    """Each step closes only in order, with the token `todo show` prints, once its gate passes on what the step makes."""

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
        self.assertIn("Copied 6 steps from feature", self.todo("from", "feature"))
        items = self.items()
        self.assertEqual({n: i["after"] for n, i in items.items()}, AFTER)
        self.assertEqual({n for n, i in items.items() if i["mandatory"]}, MANDATORY)
        self.assertEqual({n: self.gates(i["text"]) for n, i in items.items()}, GATES)
        self.assertTrue(all(i["source_path"] == str(FEATURE) for i in items.values()))

        self.assertIn("item 2 waits on item 1", self.todo("done", 2, "--token", self.token(2), ok=False))
        self.assertIn("needs proof you read it", self.todo("done", 1, ok=False))
        self.assertIn("does not match its current text", self.todo("done", 1, "--token", "000000", ok=False))

        self.git("checkout", "-qb", "feature/mul")
        where = pathlib.Path(self.verify("where").strip())
        self.close(1)
        self.assertIn("--- ../principles/SKILL.md ---", self.todo("show", 2))
        where.mkdir(parents=True, exist_ok=True)
        (where / "design.md").write_text("# Mul\n\ncalc.py gains mul and a command line for it.\n\nSensitive paths: none\n")
        self.close(2)

        self.put("calc.py", dedent(CALC))
        self.put("tests/test_mul.py", dedent(UNIT_SPEC))
        head = self.commit("Add mul")
        self.close(3)
        self.assertIn("item 6 waits on item 4 (Run it where the user meets it.), item 5 (Review across model families.)", self.todo("done", 6, "--token", self.token(6), ok=False))

        self.assertEqual(self.guard("quota", "pick", "--role", "planner", "--avoid", "claude").strip(), "codex:gpt-5.6:high")
        limit = "Claude usage limit reached. Your limit will reset at 11:59pm."
        self.hook("PostToolUseFailure", {**self.bash("claude -p --model opus < t.md"), "error": f"Exit code 1\n{limit}"})
        self.assertIn("claude: limited until", self.guard("quota", "status"))
        self.assertIn("claude is limited until", self.denied(self.bash("python3 /x/salvo/scripts/salvo.py run --out /tmp/s claude:opus:high < t.md")))

        create = self.bash("gh pr create --title 'feat: mul' --body '## Scope\nx'")
        self.assertIn("The PR opens in item 6", self.denied(create))
        self.assertIn("no review.md", self.close(5, ok=False))
        review = (f"# Code review\n\nReviewer: codex:gpt-5.6\n\n## Review\n\nHead: {head}\n\n"
                  "- calc.py: a non-integer argument raises ValueError. Triage: follow-up: no user flow passes one; in the backlog\n\n"
                  f"## Fix review\n\nHead: {head}\nReviewer: claude:opus\n\nnone found\n")
        (where / "review.md").write_text(review)
        refused = self.close(5, ok=False)
        self.assertIn("the fix review's Reviewer claude:opus is not the review's codex:gpt-5.6", refused)
        self.assertIn("names no 'Fixed at:' line", refused)
        review = review.replace("Reviewer: claude:opus\n", f"Reviewer: codex:gpt-5.6\nFixed at: {head}\n")
        (where / "review.md").write_text(review)
        self.close(5)
        self.todo("skip", 4, "--reason", "the change is driven by its unit spec here")
        self.assertIsNone(self.hook("PreToolUse", create))

        self.put("calc.py", dedent(CALC).replace("return a * b", "return b * a"))
        self.commit("Change mul after the fix review")
        self.assertIn("product files changed after the fix review's fixes", self.close(6, ok=False))
        self.git("revert", "--no-edit", "HEAD")
        closed = self.close(6)
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
