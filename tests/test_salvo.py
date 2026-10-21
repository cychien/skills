import contextlib
import datetime
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "skills/orchestrator/salvo/scripts/salvo.py"
spec = importlib.util.spec_from_file_location("salvo", SCRIPT)
salvo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(salvo)

FAKE_AGENT = textwrap.dedent('''\
    #!{python}
    import datetime, json, os, subprocess, sys, time
    home = os.environ["FAKE_HOME"]
    prompt = sys.stdin.read()
    calls = os.path.join(home, "calls.jsonl")
    n = sum(1 for _ in open(calls)) if os.path.exists(calls) else 0
    with open(calls, "a") as f:
        f.write(json.dumps({{"argv": sys.argv, "stdin": prompt}}) + "\\n")
    outcome = os.environ["FAKE_PLAN"].split(",")[n]
    if outcome in ("hang", "leak"):
        grandchild = subprocess.Popen(["sleep", "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(os.path.join(home, "grandchild.pid"), "w").write(str(grandchild.pid))
        if outcome == "hang":
            time.sleep(300)
        outcome = "ok"
    agent = os.path.basename(sys.argv[0])
    emit = lambda e: print(json.dumps(e), flush=True)
    if agent == "claude":
        if outcome == "ok":
            emit({{"type": "result", "is_error": False, "result": "done", "session_id": "s-1"}})
            sys.exit(0)
        reset = int(time.time()) + int(outcome.split(":")[1])
        emit({{"type": "rate_limit_event", "rate_limit_info": {{"status": "rejected", "resetsAt": reset}}, "session_id": "s-1"}})
        emit({{"type": "result", "is_error": True, "result": "You've hit your session limit", "session_id": "s-1"}})
        sys.exit(1)
    emit({{"type": "thread.started", "thread_id": "t-1"}})
    if outcome == "ok":
        open(sys.argv[sys.argv.index("-o") + 1], "w").write("codex done")
        emit({{"type": "turn.completed"}})
        sys.exit(0)
    at = datetime.datetime.now() + datetime.timedelta(seconds=int(outcome.split(":")[1]))
    emit({{"type": "turn.failed", "error": {{"message": "You've hit your usage limit. Visit the usage page or try again at " + at.strftime("%I:%M %p").lstrip("0") + "."}}}})
    sys.exit(1)
''')


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name in ("claude", "codex"):
            path = bin_dir / name
            path.write_text(FAKE_AGENT.format(python=sys.executable))
            path.chmod(0o755)
        self.source = self.root / "source"
        self.source.mkdir()
        self.env = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_HOME": str(self.root),
                                                "ORCHESTRATOR_HOME": str(self.root / "orchestrator")})
        self.env.start()
        self.cwd = os.getcwd()
        os.chdir(self.source)

    def tearDown(self):
        os.chdir(self.cwd)
        self.env.stop()
        self.tmp.cleanup()

    def salvo(self, plan, spec, *flags):
        os.environ["FAKE_PLAN"] = plan
        out = self.out = self.root / f"out-{len(list(self.root.glob('out-*')))}"
        sleeps = []
        argv = ["salvo.py", "run", "--out", str(out), *flags, spec]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.StringIO("Write a haiku.")), \
                mock.patch.object(salvo, "sleep_until", sleeps.append), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit):
            salvo.main()
        log = self.root / "calls.jsonl"
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        log.unlink()
        return json.loads((out / "salvo.json").read_text())["runs"][0], calls, sleeps


class LimitWait(Harness):
    def test_a_run_that_hits_a_limit_fails_at_once_with_the_reset_time_and_records_it(self):
        for spec in ("claude:m", "codex:m"):
            before = time.time()
            run, calls, sleeps = self.salvo("limit:3600,ok", spec)
            self.assertFalse(run["ok"])
            self.assertEqual((len(calls), sleeps), (1, []))
            self.assertNotIn("limit_waits", run)
            reset = datetime.datetime.fromisoformat(run["limited_until"]).timestamp()
            self.assertAlmostEqual(reset, before + 3600, delta=120)
            self.assertIn(f"usage limit resets at {salvo.clock(reset)}; hand the work to the next candidate with `guard.py quota pick`", run["error"])
            self.assertIn(spec.split(":")[0], json.loads((self.root / "orchestrator" / "limits.json").read_text()))

    def test_a_claude_run_waits_for_the_reset_and_resumes_its_session(self):
        before = int(time.time())
        run, calls, sleeps = self.salvo("limit:5,ok", "claude:m", "--wait-for-reset")
        self.assertTrue(run["ok"], run)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["argv"][-2:], ["--resume", "s-1"])
        self.assertEqual(calls[1]["stdin"], salvo.CONTINUE_PROMPT)
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], before + 5 + salvo.RESET_MARGIN_S)
        self.assertEqual(len(run["limit_waits"]), 1)
        self.assertEqual(run["resume"], f"cd {run['work']} && claude --resume s-1")

    def test_a_codex_run_waits_for_the_reset_and_resumes_its_thread(self):
        run, calls, sleeps = self.salvo("limit:5,ok", "codex:m", "--wait-for-reset")
        self.assertTrue(run["ok"], run)
        resumed = calls[1]["argv"]
        self.assertEqual(resumed[1:3], ["exec", "resume"])
        self.assertEqual(resumed[-2:], ["t-1", "-"])
        self.assertNotIn("-C", resumed)
        self.assertIn('sandbox_mode="workspace-write"', resumed)
        self.assertEqual(calls[1]["stdin"], salvo.CONTINUE_PROMPT)
        self.assertEqual(len(sleeps), 1)

    def test_every_limit_a_run_hits_is_recorded_for_other_sessions(self):
        registry = self.root / "orchestrator" / "limits.json"
        registry.parent.mkdir()
        registry.write_text(json.dumps({"claude": {"until": "2020-01-01T00:00+00:00", "seen": "x", "source": "old"}}))
        before = time.time()
        self.salvo("limit:600,ok", "codex:m", "--wait-for-reset")
        entry = json.loads(registry.read_text())
        self.assertEqual(set(entry), {"codex"})
        until = datetime.datetime.fromisoformat(entry["codex"]["until"]).timestamp()
        self.assertAlmostEqual(until, before + 600, delta=120)
        self.assertEqual(entry["codex"]["source"], "salvo run 1-m hit the codex usage limit")
        self.salvo("ok", "claude:m")
        self.assertEqual(set(json.loads(registry.read_text())), {"codex"})

    def test_a_reset_more_than_a_day_away_is_not_waited_for(self):
        run, calls, sleeps = self.salvo("limit:90000", "claude:m", "--wait-for-reset")
        self.assertFalse(run["ok"])
        self.assertEqual((len(calls), sleeps), (1, []))
        self.assertIn("more than 24 hours away", run["error"])

    def test_repeated_limit_hits_stop_after_the_resume_budget(self):
        plan = ",".join(["limit:5"] * (salvo.LIMIT_RESUMES + 1))
        run, calls, sleeps = self.salvo(plan, "claude:m", "--wait-for-reset")
        self.assertFalse(run["ok"])
        self.assertEqual(len(sleeps), salvo.LIMIT_RESUMES)
        self.assertEqual(len(calls), salvo.LIMIT_RESUMES + 1)
        self.assertIn(f"gave up after {salvo.LIMIT_RESUMES} resumes", run["error"])

    def prompts(self, *flags):
        _, calls, _ = self.salvo("ok", "claude:m", *flags)
        return calls[0]["stdin"]

    def test_a_runner_prompt_says_it_is_a_delegate_that_must_not_run_autorun(self):
        plain = self.prompts()
        self.assertIn("It starts empty", plain)
        subprocess.run(["git", "init", "-q"], cwd=self.source, check=True)
        (self.source / "a.txt").write_text("a")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], cwd=self.source, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a"], cwd=self.source, check=True)
        in_git = self.prompts()
        self.assertIn("private copy", in_git)
        for prompt in (plain, in_git):
            self.assertIn("You are a delegate of a larger run", prompt)
            self.assertIn("autorun.py start, done, or stop", prompt)
        clean = self.prompts("--clean-room")
        self.assertNotIn("autorun", clean)
        self.assertNotIn("delegate", clean)

    def test_codex_reset_times_parse_to_the_next_occurrence(self):
        now = datetime.datetime(2026, 10, 18, 7, 0).timestamp()
        self.assertEqual(salvo.codex_reset("6:15 AM", now), datetime.datetime(2026, 10, 19, 6, 15).timestamp())
        self.assertEqual(salvo.codex_reset("7:45 PM", now), datetime.datetime(2026, 10, 18, 19, 45).timestamp())
        just_past = datetime.datetime(2026, 10, 18, 6, 18).timestamp()
        self.assertEqual(salvo.codex_reset("6:15 AM", just_past), datetime.datetime(2026, 10, 18, 6, 15).timestamp())
        self.assertEqual(salvo.codex_reset("Oct 20th, 2026 6:15 AM", now), datetime.datetime(2026, 10, 20, 6, 15).timestamp())
        self.assertIsNone(salvo.codex_reset("soon", now))


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


class Lifecycle(Harness):
    def grandchild(self):
        return int((self.root / "grandchild.pid").read_text())

    def straggler(self, cwd, *, ignore_term=False):
        script = "import signal, time\n" + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "") + "print('ready', flush=True)\ntime.sleep(300)\n"
        p = subprocess.Popen([sys.executable, "-c", script], cwd=cwd, start_new_session=True, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        p.stdout.readline()
        return p

    def clean(self, out=None):
        argv = ["salvo.py", "clean", str(out or self.out)]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            try:
                salvo.main()
            except SystemExit as e:
                return e.code, stdout.getvalue()
        return None, stdout.getvalue()

    def test_a_timed_out_runner_dies_with_its_whole_tree(self):
        run, _, _ = self.salvo("hang", "claude:m", "--timeout", "1")
        self.assertEqual(run["error"], "timed out after 1s")
        self.assertTrue(gone(self.grandchild()))

    def test_a_runner_that_finishes_leaves_none_of_its_children_running(self):
        run, _, _ = self.salvo("leak", "claude:m")
        self.assertTrue(run["ok"], run)
        self.assertTrue(gone(self.grandchild()))

    def test_clean_stops_processes_running_in_a_workspace_before_deleting_it(self):
        run, _, _ = self.salvo("ok", "claude:m")
        p = self.straggler(run["work"])
        code, out = self.clean()
        self.assertIsNone(code)
        self.assertTrue(gone(p.pid))
        self.assertFalse(self.out.exists())

    def test_clean_kills_what_ignores_sigterm(self):
        run, _, _ = self.salvo("ok", "claude:m")
        p = self.straggler(run["work"], ignore_term=True)
        with mock.patch.object(salvo, "KILL_WAIT_S", 0.5):
            code, _ = self.clean()
        self.assertIsNone(code)
        self.assertTrue(gone(p.pid))

    def test_clean_covers_the_clean_room_workspace_the_shadow_home_and_the_run_dir(self):
        run, _, _ = self.salvo("ok", "claude:m", "--clean-room", "--hide-skill", "nothing")
        manifest = json.loads((self.out / "salvo.json").read_text())
        places = [run["workspace_root"], manifest["shadow_root"], run["dir"]]
        procs = [self.straggler(place) for place in places]
        code, _ = self.clean()
        self.assertIsNone(code)
        self.assertTrue(all(gone(p.pid) for p in procs))
        self.assertFalse(any(os.path.exists(place) for place in places))

    def test_clean_deletes_nothing_while_a_process_survives(self):
        run, _, _ = self.salvo("ok", "claude:m")
        p = self.straggler(run["work"])
        with mock.patch.object(salvo, "signal_processes"), mock.patch.object(salvo, "KILL_WAIT_S", 0.2):
            code, _ = self.clean()
        self.assertIn(str(p.pid), code)
        self.assertTrue(self.out.exists())
        self.assertTrue(os.path.isdir(run["work"]))
        self.assertTrue(alive(p.pid))

    def test_clean_leaves_a_process_elsewhere_alone(self):
        self.salvo("ok", "claude:m")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        p = self.straggler(elsewhere)
        self.assertIsNone(self.clean()[0])
        self.assertTrue(alive(p.pid))


if __name__ == "__main__":
    unittest.main()
