import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN = ROOT / "skills" / "orchestrator" / "update-orchestrator" / "scripts" / "plan.py"
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

CLAUDE = [
    {"id": "claude-opus-5-5", "efforts": EFFORTS},
    {"id": "claude-fable-5-1", "efforts": EFFORTS, "notice": "draws down usage much faster"},
    {"id": "claude-sonnet-5-5", "efforts": EFFORTS},
    {"id": "claude-haiku-4-5-20251001", "efforts": []},
    {"id": "claude-opus-5", "efforts": EFFORTS},
    {"id": "claude-fable-5", "efforts": EFFORTS, "notice": "draws down usage much faster"},
]
CODEX = [
    {"id": "gpt-6-astra", "efforts": EFFORTS + ["ultra"]},
    {"id": "gpt-5.6-sol", "efforts": EFFORTS + ["ultra"]},
]


def entry(spec):
    agent, model, effort = (spec.split(":") + [None])[:3]
    return {"agent": agent, "model": model, "effort": effort}


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))

    def plan(self, planner, executor, claude=CLAUDE, codex=CODEX):
        config = self.tmp / "models.json"
        config.write_text(json.dumps({
            "version": 2,
            "subscriptions": [{"agent": "claude", "plan": "max-5x"}, {"agent": "codex", "plan": "plus"}],
            "roles": {"planner": [entry(s) for s in planner], "executor": [entry(s) for s in executor]},
        }))
        catalogs = self.tmp / "catalogs.json"
        catalogs.write_text(json.dumps({"catalogs": {"claude": claude, "codex": codex}}))
        result = subprocess.run([sys.executable, str(PLAN), str(config), "--catalogs", str(catalogs)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def actions(self, plan, role):
        return [(s["model"], s["action"], (s["to"] or {}).get("model")) for s in plan["roles"][role]]

    def test_another_line_never_replaces_an_entry(self):
        plan = self.plan(["codex:gpt-5.6-sol:high"], ["codex:gpt-5.6-sol:medium"])
        self.assertEqual(plan["changes"], 0)
        self.assertIn("gpt-6-astra", plan["new_lines"]["codex"])

    def test_a_newer_version_of_the_line_replaces_it(self):
        codex = CODEX + [{"id": "gpt-6-sol", "efforts": EFFORTS}]
        plan = self.plan(["codex:gpt-5.6-sol:high"], ["codex:gpt-5.6-sol:medium"], codex=codex)
        self.assertEqual(self.actions(plan, "planner"), [("gpt-5.6-sol", "replace", "gpt-6-sol")])
        self.assertEqual(plan["roles"]["executor"][0]["to"], {"model": "gpt-6-sol", "effort": "medium"})

    def test_an_older_model_behind_its_successor_stays(self):
        plan = self.plan(["claude:claude-fable-5-1:high"], ["claude:claude-opus-5-5:high", "claude:claude-opus-5:high"])
        self.assertEqual(plan["changes"], 0)

    def test_a_retired_model_moves_to_its_line_or_is_flagged(self):
        plan = self.plan(["claude:claude-opus-4-1:high", "claude:claude-mythos-1:high"], ["claude:claude-opus-5-5:high"])
        self.assertEqual(
            self.actions(plan, "planner"),
            [("claude-opus-4-1", "replace", "claude-opus-5-5"), ("claude-mythos-1", "retired", None)],
        )

    def test_effort_maps_to_the_nearest_lower_level(self):
        codex = CODEX + [{"id": "gpt-6-sol", "efforts": ["low", "medium", "high"]}]
        plan = self.plan(["codex:gpt-5.6-sol:max"], ["codex:gpt-5.6-sol:medium"], codex=codex)
        self.assertEqual(plan["roles"]["planner"][0]["to"]["effort"], "high")

    def test_flags_a_successor_that_gains_a_usage_notice(self):
        claude = CLAUDE + [{"id": "claude-opus-6", "efforts": EFFORTS, "notice": "uses limits faster"}]
        plan = self.plan(["claude:claude-fable-5-1:high"], ["claude:claude-opus-5-5:high"], claude=claude)
        self.assertEqual(plan["roles"]["executor"][0]["to"]["notice"], "uses limits faster")

    def test_write_command_keeps_subscriptions_and_order(self):
        plan = self.plan(["claude:claude-fable-5:high", "codex:gpt-5.6-sol:high"], ["claude:claude-opus-5:high"])
        self.assertEqual(
            plan["write_command"][2:],
            [str(self.tmp / "models.json"), "--subscription", "claude:max-5x", "codex:plus",
             "--planner", "claude:claude-fable-5-1:high", "codex:gpt-5.6-sol:high",
             "--executor", "claude:claude-opus-5-5:high"],
        )

    def test_agent_without_catalog_is_left_alone(self):
        plan = self.plan(["claude:claude-fable-5-1:high", "codex:gpt-5.6-sol:high"], ["codex:gpt-5.6-sol:medium"], codex=[])
        self.assertEqual(plan["changes"], 0)


if __name__ == "__main__":
    unittest.main()
