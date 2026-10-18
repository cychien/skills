import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRITE_CONFIG = ROOT / "skills" / "orchestrator" / "setup-orchestrator" / "scripts" / "write_config.py"


def write_config(path, *args):
    return subprocess.run([sys.executable, str(WRITE_CONFIG), str(path), *args], capture_output=True, text=True)


class WriteConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / ".agents" / "orchestrator" / "models.json"

    def run_ok(self, subscriptions, *extra):
        result = write_config(
            self.path, "--subscription", *subscriptions, "--planner", "claude:opus:high", "--executor", "codex:gpt", *extra
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.path.read_text())

    def test_records_subscriptions_and_roles(self):
        config = self.run_ok(["claude:max-20x", "codex:api:200"])
        self.assertEqual(config["version"], 2)
        self.assertEqual(
            config["subscriptions"],
            [{"agent": "claude", "plan": "max-20x"}, {"agent": "codex", "plan": "api", "monthly_usd": 200}],
        )
        self.assertEqual(config["roles"]["planner"], [{"agent": "claude", "model": "opus", "effort": "high"}])
        self.assertEqual(config["roles"]["executor"], [{"agent": "codex", "model": "gpt", "effort": None}])
        self.assertNotIn("budget", config)

    def test_same_answers_give_the_same_file(self):
        self.run_ok(["claude:pro"])
        first = self.path.read_text()
        self.run_ok(["claude:pro"])
        self.assertEqual(self.path.read_text(), first)

    def test_rejects_malformed_subscriptions(self):
        for bad in ["claude", "claude:Max 5x", "codex:api", "codex:api:0", "codex:api:lots", ":pro"]:
            with self.subTest(bad=bad):
                result = write_config(self.path, "--subscription", bad, "--planner", "a:b", "--executor", "a:b")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.path.exists())

    def test_gitignore_anchors_the_config_at_the_repo_root(self):
        repo = pathlib.Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.run_ok(["claude:pro"], "--gitignore")
        self.assertEqual((repo / ".gitignore").read_text(), "/.agents/orchestrator/models.json\n")
        self.run_ok(["claude:pro"], "--gitignore")
        self.assertEqual((repo / ".gitignore").read_text(), "/.agents/orchestrator/models.json\n")


if __name__ == "__main__":
    unittest.main()
