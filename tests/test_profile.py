import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "skills" / "skill-master" / "reflect" / "scripts" / "profile.py"
spec = importlib.util.spec_from_file_location("profile_script", PROFILE)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def stamp(minute):
    return f"2026-01-01T10:{minute:02d}:00Z"


def user(minute, text):
    return {"type": "user", "timestamp": stamp(minute), "message": {"role": "user", "content": text}}


def assistant(minute, message_id, usage, content=()):
    return {"type": "assistant", "timestamp": stamp(minute),
            "message": {"id": message_id, "model": "claude-test", "usage": usage, "content": list(content)}}


def usage(input_tokens, creation, read, output):
    return {"input_tokens": input_tokens, "cache_creation_input_tokens": creation, "cache_read_input_tokens": read, "output_tokens": output}


class Profile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.session = base / "abc.jsonl"
        self.log = base / "profile" / "runs.jsonl"
        subagents = base / "abc" / "subagents"
        subagents.mkdir(parents=True)
        self.write(self.session, [
            user(0, "setup"),
            assistant(1, "m1", usage(10, 100, 1000, 50)),
            user(10, "start the real work"),
            assistant(11, "m2", usage(20, 200, 2000, 70)),
            assistant(11, "m2", usage(20, 200, 2000, 70)),
            assistant(12, "m3", usage(5, 50, 3000, 30)),
            {"type": "user", "timestamp": stamp(12), "message": {"role": "user", "content": [{"type": "text", "text": "ok"}]}},
        ])
        self.write(subagents / "agent-a1.jsonl", [
            assistant(13, "s1", usage(1, 10, 100, 5), [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 600"}}]),
            {"type": "user", "timestamp": stamp(24), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]}},
            assistant(25, "s2", usage(2, 20, 200, 15)),
        ])
        (subagents / "agent-a1.meta.json").write_text(json.dumps({"description": "worker"}))

    def write(self, path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def run_profile(self, *args):
        out = io.StringIO()
        env = {"PROFILE_LOG": str(self.log)}
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", ["profile.py", str(self.session), *args]), contextlib.redirect_stdout(out):
            profile.main()
        return out.getvalue()

    def test_the_table_totals_count_each_message_once_across_agents(self):
        out = self.run_profile()
        self.assertIn("lead", out)
        self.assertIn("a1", out)
        self.assertIn("worker", out)
        self.assertIn("total output", out)
        data = json.loads(self.run_profile("--json"))
        self.assertEqual(data["lead"]["tokens"]["output_tokens"], 150)
        self.assertEqual(data["lead"]["tokens"]["cache_read_input_tokens"], 6000)
        self.assertEqual(data["a1"]["tokens"]["output_tokens"], 20)
        self.assertEqual(data["a1"]["timeouts"], 1)
        self.assertEqual(data["a1"]["description"], "worker")

    def test_since_starts_the_window_at_the_first_matching_user_message(self):
        data = json.loads(self.run_profile("--since", "real work", "--json"))
        self.assertEqual(data["lead"]["tokens"]["output_tokens"], 100)
        self.assertEqual(data["lead"]["wall_min"], 2.0)

    def test_until_ends_the_window_before_the_first_matching_user_message_after_since(self):
        data = json.loads(self.run_profile("--since", "real work", "--until", "ok", "--json"))
        self.assertEqual(data["lead"]["tokens"]["output_tokens"], 70)
        self.assertNotIn("a1", data)

    def test_until_without_a_match_after_since_exits_with_a_message(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_profile("--since", "real work", "--until", "setup")
        self.assertIn("no user message after the window start contains", str(raised.exception))

    def test_since_without_a_match_exits_with_a_message(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_profile("--since", "nothing like this")
        self.assertIn("no user message contains", str(raised.exception))

    def test_context_prints_the_last_assistant_messages_context_only(self):
        self.assertEqual(self.run_profile("--context"), "3055\n")
        self.assertFalse(self.log.exists())

    def test_record_appends_one_line_and_still_prints_the_table(self):
        out = self.run_profile("--since", "real work", "--record", "baseline")
        self.assertIn("slowest tool calls", out)
        self.run_profile("--record", "second")
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        entry = json.loads(lines[0])
        self.assertEqual(entry["label"], "baseline")
        self.assertEqual(entry["since"], "real work")
        self.assertEqual(entry["wall_min"], 15.0)
        self.assertEqual(entry["idle_min"], 0)
        self.assertEqual(entry["agents"], 2)
        self.assertEqual(entry["output_tokens"], 120)
        self.assertEqual(entry["context_tokens"], 2220 + 3055 + 111 + 222)
        self.assertEqual(entry["lead_context_tokens"], 3055)
        self.assertEqual(entry["timeouts"], 1)
        self.assertRegex(entry["recorded_at"], r"^\d{4}-\d\d-\d\dT")
        self.assertIsNone(json.loads(lines[1])["since"])

    def test_idle_minutes_count_minutes_with_no_lead_entry_and_no_running_subagent(self):
        first = profile.ts(stamp(0))
        lead = [profile.ts(stamp(0)), profile.ts(stamp(1)), profile.ts(stamp(10))]
        spans = [(profile.ts(stamp(4)), profile.ts(stamp(6)))]
        self.assertEqual(profile.idle_minutes(lead, spans, first, profile.ts(stamp(10))), 5)


if __name__ == "__main__":
    unittest.main()
