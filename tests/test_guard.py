import contextlib
import datetime
import hashlib
import io
import json
import os
import pathlib
import re
import shlex
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
HOOK = ROOT / "skills" / "orchestrator" / "autorun" / "scripts" / "autorun.py"
GUARD = ROOT / "skills" / "orchestrator" / "guard" / "scripts" / "guard.py"


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.skills = base / "skills"
        self.write_skill("demo", """\
            ---
            name: demo
            description: a demo playbook
            ---

            # Demo

            1. Gather the facts. Read everything first.
            2. Hand it off. Mandatory: no skip.
               This continues step two.
            3. Report back.
            4. Apply what the facts show.

            ## Notes

            1. Not a step.
            """)
        self.write_skill("open-pr", "---\nname: open-pr\ndescription: x\n---\n\n# Open a PR\n")
        self.write_skill("principles", "---\nname: principles\ndescription: x\n---\n\n# Principles\n")
        principles = self.skills / "principles" / "references" / "principles"
        principles.mkdir(parents=True)
        (principles / "fix-root-causes.md").write_text("# Fix Root Causes\n\nReproduce first.\n")
        (principles / "prove-it-works.md").write_text("# Prove It Works\n\nCheck the real thing.\n")
        self.env = {**os.environ, "AUTORUN_HOME": str(base / "autorun"), "GUARD_HOME": str(base / "guard"), "GUARD_SKILL_ROOTS": str(self.skills),
                    "ORCHESTRATOR_HOME": str(base / "orchestrator")}
        self.env["GUARD_HEADLESS"] = "0"
        for k in ("AUTORUN_RUN", "AUTORUN_DISABLE", "CURSOR_VERSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def write_skill(self, name, text):
        d = self.skills / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(textwrap.dedent(text))

    def hook(self, event, payload, agent="claude"):
        payload = {"session_id": "s1", "cwd": self.tmp.name, **payload}
        r = subprocess.run([sys.executable, str(HOOK), "hook", agent, event], input=json.dumps(payload), capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        errors = pathlib.Path(self.env["AUTORUN_HOME"]) / "errors.log"
        self.assertFalse(errors.exists(), errors.read_text() if errors.exists() else "")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def step(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(GUARD), "todo", *args, "--session", "claude:s1"], capture_output=True, text=True, env=self.env, cwd=self.tmp.name)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def stop(self, message, **extra):
        return self.hook("Stop", {"last_assistant_message": message, **extra})

    def test_em_dash_is_sent_back_outside_code(self):
        self.assertEqual(self.stop("Done — all green.")["decision"], "block")
        self.assertIsNone(self.stop("Done. The flag is `a—b` in code."))
        self.assertIsNone(self.stop("Done, all green."))

    def todo(self, *args, ok=True):
        return self.step(*args, ok=ok)

    def token(self, n, *agent):
        return self.todo("show", str(n), *agent).strip().splitlines()[-1].removeprefix("token: ")

    def close(self, *ns, ok=True, agent=()):
        tokens = [a for n in ns for a in ("--token", self.token(n, *agent))]
        return self.todo("done", *map(str, ns), *tokens, *agent, ok=ok)

    def test_a_slash_skill_holds_tools_until_the_todo_is_decided(self):
        hint = self.hook("UserPromptSubmit", {"prompt": "/demo build the thing"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("todo from demo", hint)
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(self.hook("PreToolUse", bash)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.hook("PreToolUse", {**bash, "agent_id": "a1"}))
        for text in ("make deploy; # guard.py todo", f"make deploy # python3 {GUARD} todo none", "echo 'guard.py todo none --reason x'",
                     "git commit -m 'autorun.py start later'", f"grep -n 'guard.py todo' {self.skills}/demo/SKILL.md",
                     f"if grep -q 'guard.py todo' {self.skills}/demo/SKILL.md; then make deploy; fi", f"echo if python3 {GUARD} todo none",
                     f"echo 'if `python3 {GUARD} todo none`'"):
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": text}})
            self.assertEqual(out and out["hookSpecificOutput"]["permissionDecision"], "deny", text)
        for allowed in (f"python3 {GUARD} todo none --reason x; ls", f"python3 {HOOK} mode interactive --reason x", f"cat {self.skills}/demo/SKILL.md",
                        f"bash -lc 'python3 {GUARD} todo none --reason x'", f"if python3 {GUARD} todo show 1; then :; fi",
                        f"while ! python3 {GUARD} todo none --reason x; do sleep 1; done", f"{{ python3 {GUARD} todo show 1; }} 2>&1 | tail -3",
                        f"time -p python3 {GUARD} todo show 1", f'shown="$(python3 {GUARD} todo show 1)"'):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": allowed}}), allowed)
        self.todo("none", "--reason", "one-line change")
        self.assertIsNone(self.hook("PreToolUse", bash))
        self.assertIsNone(self.stop("Done."))

    def test_a_router_without_steps_defers_the_todo_decision_to_the_skill_it_reaches(self):
        self.write_skill("router", "---\nname: router\ndescription: x\n---\n\n# Router\n\n- **Demo.** Uses `../demo/SKILL.md`.\n")
        self.assertIsNone(self.hook("UserPromptSubmit", {"prompt": "/router teach me something"}))
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertIsNone(self.hook("PreToolUse", bash))
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "demo" / "SKILL.md")}})
        out = self.hook("PreToolUse", bash)["hookSpecificOutput"]
        self.assertIn("demo skill you are about to follow has steps", out["permissionDecisionReason"])
        self.todo("from", "demo")
        self.assertIsNone(self.hook("PreToolUse", bash))
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "demo" / "SKILL.md")}})
        self.assertIsNone(self.hook("PreToolUse", bash))

    def test_todo_from_copies_steps_and_every_item_must_resolve(self):
        self.hook("UserPromptSubmit", {"prompt": "/demo build the thing"})
        out = self.todo("from", "demo")
        self.assertIn("1. Gather the facts.", out)
        self.assertNotIn("Not a step", out)
        self.assertIn("looks like a flag", self.todo("add", "Update the changelog", "--session claude:x", ok=False))
        self.todo("add", "Update the changelog")
        blocked = self.stop("Started the work.")
        self.assertIn("5. Update the changelog", blocked["reason"])
        self.assertIsNone(self.stop("Which output format do you want?"))
        self.assertIn("mandatory", self.todo("skip", "2", "--reason", "small", ok=False))
        self.todo("done", "1", "2", "--token", self.token(1), "--token", self.token(2), "--note", "did both")
        self.todo("skip", "3", "--reason", "nothing to report")
        self.close(4)
        self.assertIn("Every item is resolved", self.todo("done", "5"))
        self.assertIsNone(self.stop("All done."))
        self.assertIn("1. Next task", self.todo("add", "Next task"))

    def test_waiting_items_let_the_turn_end_on_a_plain_text_question(self):
        self.todo("add", "Pick the format", "Write the doc")
        blocked = self.stop("Started.")
        self.assertIn("todo wait", blocked["reason"])
        out = self.todo("wait", "1", "--reason", "which format the user wants")
        self.assertNotIn("End the turn now", out)
        self.assertIn("[?] 1. Pick the format - waiting on the user: which format the user wants", out)
        self.assertIn("2. Write the doc", self.stop("I need to know more.")["reason"])
        self.assertNotIn("1. Pick the format", self.stop("I need to know more.")["reason"])
        self.assertIn("End the turn now", self.todo("wait", "2", "--reason", "same answer"))
        self.assertIsNone(self.stop("Tell me the format first."))

    def test_the_next_user_prompt_reopens_waiting_items(self):
        self.todo("add", "Pick the format")
        self.todo("wait", "1", "--reason", "format")
        self.assertIsNone(self.stop("Tell me the format first."))
        self.hook("UserPromptSubmit", {"prompt": "markdown"})
        self.assertIn("[ ] 1. Pick the format", self.todo("list"))
        self.assertEqual(self.stop("Working.")["decision"], "block")

    def test_waiting_items_can_be_done_or_skipped_but_not_waited_twice_over_resolved_ones(self):
        self.todo("add", "One", "Two", "Three")
        self.todo("wait", "1", "2", "--reason", "answer")
        self.assertIn("[x] 1. One", self.todo("done", "1"))
        self.assertIn("[-] 2. Two", self.todo("skip", "2", "--reason", "not needed"))
        self.assertIn("already done", self.todo("wait", "1", "--reason", "again", ok=False))
        self.assertEqual(self.stop("Working.")["decision"], "block")
        self.todo("wait", "3", "--reason", "answer")
        self.assertIn("Every item is resolved", self.todo("done", "3"))

    def test_a_list_of_only_waiting_items_is_not_archived_by_new_items(self):
        self.todo("add", "One")
        self.todo("wait", "1", "--reason", "answer")
        out = self.todo("add", "Two")
        self.assertIn("[?] 1. One", out)
        self.assertIn("2. Two", out)

    def test_skipping_an_item_that_runs_a_skill_skips_that_skills_items(self):
        self.write_skill("outer", """\
            ---
            name: outer
            description: x
            ---

            1. Start.
            2. Run the demo skill (`../demo/SKILL.md`).
            3. Finish.
            """)
        self.todo("from", "outer")
        self.todo("from", "demo")
        self.close(1)
        self.assertIn("Also skipped 4 item(s) from demo", self.todo("skip", "2", "--reason", "too small"))
        self.close(3)
        self.assertIsNone(self.stop("Done."))

    def test_todo_from_recognizes_each_shape_of_steps(self):
        sys.path.insert(0, str(GUARD.parent))
        from guard_lib.skills import steps
        cases = {
            "section": ("# S\n\n## Steps\n\n### First part\n\n1. **Read.** x\n2. Ask.\n\n### Second part\n\n3. Build.\n\n## Notes\n\n1. Not a step.\n", ["Read.", "Ask.", "Build."]),
            "headings": ("# S\n\n## Phase A: Frame\n\n1. sub\n\n## Phase B: Fan out\n\ntext\n\n## Output\n", ["Frame", "Fan out"]),
            "numbered": ("# S\n\n## 1. Assess\n\n## 2. Present\n", ["Assess", "Present"]),
            "rules": ("# S\n\nIntro.\n\n## Work the run\n\n1. Set it.\n2. Do it.\n", []),
        }
        for name, (body, expected) in cases.items():
            f = self.skills / name / "SKILL.md"
            f.parent.mkdir(parents=True)
            f.write_text("---\nname: x\ndescription: x\n---\n\n" + body)
            self.assertEqual([t for _, t, _, _ in steps(f)], expected, name)
        self.assertIn("todo add", self.todo("from", "rules", ok=False))

    def test_a_timed_out_gate_is_stopped_with_everything_it_started(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates
        scripts = self.skills / "slow" / "scripts"
        scripts.mkdir(parents=True)
        self.write_skill("slow", "---\nname: slow\ndescription: x\n---\n")
        pidfile = pathlib.Path(self.tmp.name, "grandchild.pid")
        (scripts / "hang.py").write_text(
            "import pathlib, subprocess, sys, time\n"
            f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))\n"
            "time.sleep(60)\n")
        with mock.patch.dict(os.environ, {"GUARD_SKILL_ROOTS": str(self.skills)}), mock.patch.object(gates, "TIMEOUT", 2):
            started = time.monotonic()
            why = gates.run("slow", "hang.py", ["go"], self.tmp.name)
        grandchild = int(pidfile.read_text())
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(grandchild)], capture_output=True))
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("did not finish within 2 seconds", why)
        self.assertIn(f"python3 {scripts / 'hang.py'} go", why)
        self.assertIn("yourself", why)
        self.assertIn("mark the item done again", why)
        for _ in range(50):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the gate's grandchild is still running")

    def test_an_item_naming_a_check_script_closes_only_when_it_passes(self):
        scripts = self.skills / "checker" / "scripts"
        scripts.mkdir(parents=True)
        self.write_skill("checker", "---\nname: checker\ndescription: x\n---\n")
        (scripts / "check.py").write_text("import pathlib, sys\nok = pathlib.Path('ready').exists()\nprint('ready' if ok else 'not ready: write the ready file')\nsys.exit(0 if ok else 1)\n")
        self.write_skill("gated", """\
            ---
            name: gated
            description: x
            ---

            1. Write the ready file, and close this step only when `../checker/scripts/check.py plan` passes.
            2. Name a missing gate `../absent/scripts/check.py`.
            """)
        self.todo("from", "gated")
        out = self.close(1, ok=False)
        self.assertIn("not ready: write the ready file", out)
        self.assertIn("stays open", out)
        pathlib.Path(self.tmp.name, "ready").write_text("")
        self.close(1)
        self.assertIn("not installed", self.close(2, ok=False))

    def test_a_reply_naming_principles_no_longer_needs_their_files_read(self):
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "principles"}})
        self.assertIsNone(self.stop("Applied Fix Root Causes: reproduced first."))

    def asks_for_a_decision(self):
        out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_shell_variables_in_read_paths_are_expanded(self):
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"D={self.skills}; echo ---; cat ${{D}}/demo/SKILL.md"}})
        self.assertTrue(self.asks_for_a_decision())

    def test_reads_inside_a_for_loop_count(self):
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f'for f in {self.skills}/demo/*.md; do echo "== $f"; cat "$f"; done'}})
        self.assertTrue(self.asks_for_a_decision())

    def test_pr_rules_apply_after_open_pr_is_used(self):
        bad = {"tool_name": "Bash", "tool_input": {"command": "gh pr create --title 'Add export.' --draft --body 'stuff'"}}
        self.assertIsNone(self.hook("PreToolUse", bad))
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "open-pr"}})
        out = self.hook("PreToolUse", bad)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        for fragment in ("Conventional Commits", "--draft", "## Scope"):
            self.assertIn(fragment, out["permissionDecisionReason"])
        wrapped = {"tool_name": "Bash", "tool_input": {"command": "if gh pr create --title 'Add export.' --draft --body 'stuff'; then :; fi"}}
        self.assertEqual(self.hook("PreToolUse", wrapped)["hookSpecificOutput"]["permissionDecisionReason"], out["permissionDecisionReason"])
        for command in ("gh pr create --title 'feat: add export.'; echo opened", "gh pr create --title 'feat: add export' --body '## Scope\nx' && gh pr edit --title 'x'"):
            self.assertIn("Conventional Commits", self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})
                          ["hookSpecificOutput"]["permissionDecisionReason"], command)
        good = textwrap.dedent("""\
            gh pr create --title 'feat(cli): add export command' --body "$(cat <<'EOF'
            ## Why
            Users want their notes out.

            ## Scope
            JSON only.

            ## Verification
            - Ran export on 23 notes.
            EOF
            )\"""")
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": good}}))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": f"if {good}; then :; fi"}}))
        for command in ("gh pr create --title 'feat: x' --body \"$(cat body.md)\"", "gh pr create --title 'fix: y' --body '## Scope\nx'"):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}}), command)
        not_ready = "gh pr create --title 'fix: refuse stale keys' --body '## Not ready to merge\n- T1 FAIL\n\n## Why\ny\n\n## Scope\nx'"
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": not_ready}}))
        late = "gh pr create --title 'fix: refuse stale keys' --body '## Why\ny\n\n## Not ready to merge\n- T1\n\n## Scope\nx'"
        self.assertIn("order", self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": late}})["hookSpecificOutput"]["permissionDecisionReason"])
        misordered = "gh pr create --title 'fix: x' --body '## Scope\nx\n\n## Why\ny'"
        self.assertIn("order", self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": misordered}})["hookSpecificOutput"]["permissionDecisionReason"])


    def test_a_detached_salvo_run_is_denied(self):
        for command in (
            "nohup python3 /x/salvo/scripts/salvo.py run --out /tmp/s claude:m < task.md > log 2>&1 &",
            "(nohup python3 salvo.py run --out /tmp/s claude:m < task.md > log 2>&1 &); sleep 5",
            "python3 scripts/salvo.py run --out /tmp/s claude:m < task.md &",
        ):
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("run_in_background", out["permissionDecisionReason"])
        tracked = {"tool_name": "Bash", "tool_input": {"command": "python3 salvo.py run --out /tmp/s claude:m < task.md && echo done", "run_in_background": True}}
        self.assertIsNone(self.hook("PreToolUse", tracked))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "python3 salvo.py clean /tmp/s &"}}))
        redirected = {"tool_name": "Bash", "tool_input": {"command": "python3 salvo.py run --out /tmp/s claude:m < task.md > log 2>&1", "run_in_background": True}}
        self.assertIsNone(self.hook("PreToolUse", redirected))
        quoted = "python3 - <<'EOF'\nprint('nohup python3 salvo.py run --out /tmp/s claude:m &')\nEOF"
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": quoted}}))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "grep -n 'salvo.py run' notes.md &"}}))

    def verifier(self, evidence, checks):
        prompt = f"You are verifying a change you did not write.\nEvidence directory: {evidence}\nChecks: {checks}\n"
        out = self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": prompt}})
        return out["hookSpecificOutput"]["permissionDecisionReason"] if out else None

    def test_each_check_gets_one_verifier_and_its_check_script_is_not_grading_evidence(self):
        evidence = pathlib.Path(self.tmp.name) / "verification"
        self.assertIsNone(self.verifier(evidence, "C1 C2"))
        (evidence / "C1.check.sh").write_text("x")
        self.assertIsNone(self.verifier(evidence, "C1"))
        time.sleep(0.01)
        (evidence / "C1.rerun.log").write_text("rerun: PASS\n")
        reason = self.verifier(evidence, "C1 C2")
        self.assertIn("Checks C1 already had a verifier that wrote evidence for them, the whole verification budget: one verifier per check.", reason)
        self.assertIn("Grade a fix with `verify.py rerun --only <ids>` and `verify.py units`", reason)
        self.assertIn("resume that same verifier instead of spawning a new one", reason)
        self.assertIsNone(self.verifier(evidence, "C2"))

    def test_a_verifier_that_left_no_evidence_does_not_spend_the_budget(self):
        evidence = pathlib.Path(self.tmp.name) / "verification"
        self.assertIsNone(self.verifier(evidence, "C1"))
        self.assertIsNone(self.verifier(evidence, "C1"))
        (evidence / "evidence" / "C1").mkdir(parents=True)
        (evidence / "evidence" / "C1" / "shot.png").write_text("x")
        self.assertIn("already had a verifier", self.verifier(evidence, "C1"))

    def test_concurrent_verifier_spawns_keep_every_ledger_entry(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import verifiers
        evidence = pathlib.Path(self.tmp.name) / "verification"
        rounds = verifiers.rounds

        def slow(*args):
            time.sleep(0.3)
            return rounds(*args)

        prompt = "You are verifying a change you did not write.\nEvidence directory: {}\nChecks: {}\n"
        with mock.patch.object(verifiers, "rounds", slow):
            spawns = [threading.Thread(target=verifiers.over_budget, args=(prompt.format(evidence, c),)) for c in ("C1", "C2", "C3")]
            for spawn in spawns:
                spawn.start()
            for spawn in spawns:
                spawn.join()
        self.assertEqual(sorted(json.loads((evidence / verifiers.LEDGER).read_text())), ["C1", "C2", "C3"])
        (evidence / "C2.rerun.log").write_text("rerun: PASS\n")
        self.assertIn("Checks C2 already had a verifier", self.verifier(evidence, "C2"))

    def test_a_verifier_prompt_must_name_its_checks(self):
        self.assertIn("no 'Checks:' line", self.verifier(pathlib.Path(self.tmp.name), ""))

    def test_a_prompt_template_with_unfilled_placeholders_is_denied(self):
        self.write_skill("verify", "---\nname: verify\ndescription: x\n---\n\n# Verify\n")
        refs = self.skills / "verify" / "references"
        refs.mkdir()
        (refs / "verifier-prompt.md").write_text(
            "# Verifier prompt\n\n```\nYou are verifying a change you did not write.\n"
            "Head: <head SHA>\nEvidence directory: <verification directory path>\nChecks: <check ids>\n"
            "Full round: <yes or no>.\nWrite <id>.observed.json.\n```\n")
        raw = ("You are verifying a change you did not write.\nHead: <head SHA>\nEvidence directory: <verification directory path>\n"
               "Checks: <check ids>\nFull round: <yes or no>.\nWrite <id>.observed.json.")
        out = self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": raw}})["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("<head SHA>", out["permissionDecisionReason"])
        self.assertIn("<yes or no>", out["permissionDecisionReason"])
        filled = (raw.replace("<head SHA>", "abc123").replace("<yes or no>", "yes").replace("<check ids>", "C1")
                  .replace("<verification directory path>", str(pathlib.Path(self.tmp.name) / "verification")))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": filled}}))
        task = pathlib.Path(self.tmp.name) / "task.md"
        task.write_text(raw)
        salvo = {"tool_name": "Bash", "tool_input": {"command": f"python3 salvo.py run --out /tmp/s claude:m < {task}", "run_in_background": True}}
        self.assertEqual(self.hook("PreToolUse", salvo)["hookSpecificOutput"]["permissionDecision"], "deny")
        task.write_text(filled)
        self.assertIsNone(self.hook("PreToolUse", salvo))
        unrelated = {"tool_name": "Agent", "tool_input": {"prompt": "Summarize <head SHA> notes."}}
        self.assertIsNone(self.hook("PreToolUse", unrelated))

    def test_an_item_naming_skills_closes_on_its_token_and_not_run_is_ignored_with_a_deprecation_line(self):
        self.write_skill("alpha", "---\nname: alpha\ndescription: x\n---\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Settle the design. Run alpha (`../alpha/SKILL.md`) when it spans modules.\n2. Wrap up.\n")
        self.todo("from", "flow")
        self.close(1)
        self.assertIn("--note", self.todo("done", "2", "--reason", "x", ok=False))
        out = self.todo("done", "2", "--not-run", "gamma", "--reason", "single module", "--token", self.token(2))
        self.assertIn("--not-run is deprecated and ignored", out)
        self.assertIn("[x] 2. Wrap up. (flow) - single module", out)

    def test_the_reply_skill_is_enforced(self):
        self.write_skill("reply", "---\nname: reply\ndescription: x\n---\n\n# Writing the reply\n")
        self.write_skill("helper", "---\nname: helper\ndescription: x\n---\n\n# Helper\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Use the helper skill (`../helper/SKILL.md`).\n\n**Reply:** per the reply skill (`../reply/SKILL.md`).\n")
        self.todo("from", "flow")
        self.close(1)
        self.assertIn("reply", self.stop("All done.")["reason"])
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "reply" / "SKILL.md")}})
        self.assertIsNone(self.stop("All done."))

    def test_reading_a_skill_only_because_an_item_cites_it_does_not_ask_for_a_todo_decision(self):
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Use the demo skill (`../demo/SKILL.md`).\n2. Wrap up.\n")
        self.todo("from", "flow")
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        demo = str(self.skills / "demo" / "SKILL.md")
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": demo}})
        self.assertIsNone(self.hook("PreToolUse", bash))
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cat {demo}"}})
        self.assertIsNone(self.hook("PreToolUse", bash))
        self.close(1)
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "demo"}})
        self.assertEqual(self.hook("PreToolUse", bash)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.todo("none", "--reason", "demo is only a reference here")
        self.assertIsNone(self.hook("PreToolUse", bash))

    def test_a_step_continued_after_a_blank_line_keeps_its_citations(self):
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Settle the design.\n   - Case A: write a note.\n\n   When it reaches past the diff, run the demo skill (`../demo/SKILL.md`).\n2. Wrap up.\n")
        self.todo("from", "flow")
        self.assertIn("When it reaches past the diff, run the demo skill (`../demo/SKILL.md`).", self.todo("show", "1"))
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "demo" / "SKILL.md")}})
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.close(1)

    def test_polling_for_a_subagent_is_denied_once_one_was_spawned(self):
        poll = {"tool_name": "Bash", "tool_input": {"command": "for i in $(seq 1 60); do grep -q end_turn /tmp/x/tasks/abc123.output && break; sleep 10; done"}}
        by_file = {"tool_name": "Bash", "tool_input": {"command": "until [ -s /tmp/x/tasks/abc123.output ]; do sleep 5; done; cat /tmp/x/tasks/abc123.output"}}
        server = {"tool_name": "Bash", "tool_input": {"command": "until curl -sf localhost:3000/health; do sleep 1; done"}}
        self.assertIsNone(self.hook("PreToolUse", poll))
        self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "Summarize the notes."}})
        for command in (poll, by_file):
            out = self.hook("PreToolUse", command)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("SubagentHandback", out["permissionDecisionReason"])
            self.assertIn("end the turn or do other work", out["permissionDecisionReason"])
        self.env["GUARD_HEADLESS"] = "1"
        reason = self.hook("PreToolUse", poll)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("foreground", reason)
        self.assertNotIn("end the turn or do other work", reason)
        self.env["GUARD_HEADLESS"] = "0"
        self.assertIsNone(self.hook("PreToolUse", server))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "sleep 5"}}))

    def test_reading_a_skill_that_no_item_cites_still_asks_for_a_todo_decision(self):
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Wrap up.\n")
        self.todo("from", "flow")
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "demo" / "SKILL.md")}})
        self.assertEqual(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}})["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_headless_session_cannot_end_the_turn_on_background_work(self):
        self.todo("add", "Ship it")
        self.env["GUARD_HEADLESS"] = "1"
        blocked = self.stop("Waiting for the executor.", background_tasks=[{"id": "t1"}])
        self.assertIn("non-interactive", blocked["reason"])
        self.env["GUARD_HEADLESS"] = "0"
        self.assertIsNone(self.stop("Waiting for the executor.", background_tasks=[{"id": "t1"}]))

    def test_waiting_on_background_work_may_end_the_turn(self):
        self.todo("add", "Implement it")
        self.assertIsNone(self.stop("Delegated; waiting.", background_tasks=[{"id": "t"}]))

    def test_stuck_lists_are_released_after_three_idle_stops(self):
        self.todo("add", "Implement it")
        for _ in range(3):
            self.assertEqual(self.stop("Still working.")["decision"], "block")
        self.assertIsNone(self.stop("Still working."))

    def test_mandatory_items_are_not_released_by_idle_stops(self):
        self.hook("UserPromptSubmit", {"prompt": "/demo build the thing"})
        self.todo("from", "demo")
        self.close(1)
        self.todo("skip", "3", "4", "--reason", "n/a")
        for _ in range(4):
            blocked = self.stop("Still working.")
            self.assertEqual(blocked["decision"], "block")
        self.assertIn("Item(s) 2 are mandatory", blocked["reason"])
        self.assertIsNone(self.stop("The gate needs a staging database I cannot reach. Can you grant access?"))

    def test_reading_a_skills_source_in_the_working_tree_is_not_following_it(self):
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.write_skill("router", "---\nname: router\ndescription: x\n---\n\n# Router\n")
        self.hook("UserPromptSubmit", {"prompt": "/router edit the demo skill"})
        source = pathlib.Path(self.tmp.name) / "src" / "skills" / "eng" / "demo"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text((self.skills / "demo" / "SKILL.md").read_text())
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(source / "SKILL.md")}})
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "cat src/skills/eng/demo/SKILL.md"}})
        self.assertIsNone(self.hook("PreToolUse", bash))
        with tempfile.TemporaryDirectory() as elsewhere:
            outside = pathlib.Path(elsewhere) / "demo" / "SKILL.md"
            outside.parent.mkdir()
            outside.write_text(source.joinpath("SKILL.md").read_text())
            self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(outside)}})
        self.assertEqual(self.hook("PreToolUse", bash)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_editing_a_skill_file_does_not_count_as_reading_it(self):
        demo = self.skills / "demo" / "SKILL.md"
        for command in [f"python3 - <<'EOF'\nopen('{demo}').read()\nEOF", f"grep -n x {demo}", f"sed -i '' 's/zzz/yyy/' {demo}"]:
            self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertFalse(self.asks_for_a_decision())
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cd /tmp && sed -n '1,80p' {demo}"}})
        self.assertTrue(self.asks_for_a_decision())

    def fake_verify(self, mode):
        self.write_skill("verify", "---\nname: verify\ndescription: x\n---\n\n# Verify\n")
        scripts = self.skills / "verify" / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "verify.py").write_text(textwrap.dedent(f"""\
            import pathlib, sys
            with open(pathlib.Path(__file__).with_name("calls.txt"), "a") as f:
                f.write(" ".join(sys.argv[1:]) + "\\n")
            mode = {mode!r}
            if mode == "survivors":
                print("pid 42 ppid 1 pgid 42 elapsed 03:00 cwd /work/app  node server.js")
                print("1 still running. Stop them with: python3 verify.py leftovers --kill")
                sys.exit(1)
            if mode == "in use":
                if "--running-since" in sys.argv:
                    print("leftovers: none remain")
                    print("1 in use by a running agent, started after it began, so neither counted nor killed:")
                    print("pid 43 ppid 1 pgid 43 elapsed 01:00 cwd /work/app-v7  node bridge.js")
                    sys.exit(0)
                print("pid 43 ppid 1 pgid 43 elapsed 01:00 cwd /work/app-v7  node bridge.js")
                print("1 still running. Stop them with: python3 verify.py leftovers --kill")
                sys.exit(1)
            if mode == "broken":
                print("verify leftovers: cannot read process working directories")
                sys.exit(2)
            print("leftovers: none remain")
            """))
        return scripts / "calls.txt"

    def errors_log(self):
        path = pathlib.Path(self.env["GUARD_HOME"]) / "errors.log"
        return path.read_text() if path.exists() else ""

    def test_stopping_a_task_sweeps_for_leftovers_and_shows_the_result(self):
        calls = self.fake_verify("survivors")
        out = self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {"task_id": "b1"}})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pid 42", out)
        self.assertEqual(calls.read_text().strip(), "leftovers --kill")
        self.fake_verify("clean")
        out = self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {}})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("none remain", out)
        calls.unlink()
        self.assertIsNone(self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertFalse(calls.exists())

    def test_spawning_an_agent_is_denied_while_leftovers_survive(self):
        calls = self.fake_verify("survivors")
        for tool in ("Agent", "Task"):
            out = self.hook("PreToolUse", {"tool_name": tool, "tool_input": {"prompt": "verify it"}})["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("pid 42", out["permissionDecisionReason"])
        self.assertEqual(set(calls.read_text().split("\n")) - {""}, {"leftovers"})
        calls.unlink()
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertFalse(calls.exists())
        self.fake_verify("clean")
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "verify it"}}))

    def spawn(self, agent_id=None):
        payload = {"tool_name": "Agent", "tool_input": {"prompt": "verify it"}}
        out = self.hook("PreToolUse", {**payload, "agent_id": agent_id} if agent_id else payload)
        return out["hookSpecificOutput"]["permissionDecision"] if out else "allow"

    def last_sweep(self, calls):
        return calls.read_text().splitlines()[-1].split()

    def test_a_running_delegates_processes_are_in_use_not_leftovers_until_it_ends(self):
        calls = self.fake_verify("in use")
        self.assertEqual(self.spawn(), "deny")
        before = time.time()
        self.hook("PreToolUse", {"agent_id": "bg1", "tool_name": "Bash", "tool_input": {"command": "node hello.mjs up --id v7"}})
        self.hook("PreToolUse", {"agent_id": "bg1", "tool_name": "Bash", "tool_input": {"command": "node hello.mjs browser v7 open /"}})
        self.assertEqual(self.spawn(), "allow")
        sweep = self.last_sweep(calls)
        self.assertEqual(sweep[:2], ["leftovers", "--running-since"])
        self.assertAlmostEqual(float(sweep[2]), before, delta=5)
        self.assertEqual(self.spawn("bg1"), "deny")
        self.assertEqual(self.last_sweep(calls), ["leftovers"])
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "bg1", "last_assistant_message": "done"}), None)
        self.assertEqual(self.spawn(), "deny")
        self.hook("PreToolUse", {"agent_id": "bg1", "tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertEqual(self.spawn(), "allow")
        self.assertEqual(float(self.last_sweep(calls)[2]), float(sweep[2]))

    def test_a_delegate_stops_running_when_its_task_is_stopped_or_the_lead_ends_with_no_background_work(self):
        calls = self.fake_verify("in use")
        for agent_id in ("bg1", "bg2"):
            self.hook("PreToolUse", {"agent_id": agent_id, "tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {"task_id": "bg1"}})
        self.assertEqual(self.last_sweep(calls)[:3], ["leftovers", "--kill", "--running-since"])
        self.stop("Waiting for the verifier.", background_tasks=[{"id": "bg2"}])
        self.assertEqual(self.spawn(), "allow")
        self.stop("Done.")
        self.assertEqual(self.spawn(), "deny")
        self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {"task_id": "bg2"}})
        self.assertEqual(self.last_sweep(calls), ["leftovers", "--kill"])

    def test_the_leftovers_sweep_fails_open_and_says_why(self):
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "x"}}))
        self.assertIn("not installed", self.errors_log())
        self.fake_verify("broken")
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "x"}}))
        self.assertIsNone(self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {}}))
        self.assertIn("exited 2", self.errors_log())
        self.assertIn("cannot read process working directories", self.errors_log())

    def test_subagent_stops_are_not_checked(self):
        self.todo("add", "Implement it")
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "a1", "last_assistant_message": "done \u2014 ok"}))

    def test_todo_wait_is_allowed_once_an_autonomous_run_waits_on_the_user(self):
        home = pathlib.Path(self.env["AUTORUN_HOME"])
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(json.dumps({"review": False}))
        self.hook("UserPromptSubmit", {"prompt": "going to bed, build it"})
        run = next((home / "active").iterdir()).name
        self.todo("add", "Pick the export format")
        self.assertIn(f"autorun.py ask --run {run}", self.todo("wait", "1", "--reason", "format", ok=False))
        asked = subprocess.run([sys.executable, str(HOOK), "ask", "--run", run, "--kind", "direction", "--question", "Markdown or HTML export?",
                                "--pick", "markdown", "--why", "both are plausible", "--confidence", "low"], env=self.env, capture_output=True, text=True)
        self.assertIn("ESCALATED", asked.stdout)
        self.assertIn("[?] 1. Pick the export format - waiting on the user: the format, escalated as a gate",
                      self.todo("wait", "1", "--reason", "the format, escalated as a gate"))
        self.assertIsNone(self.stop("Escalated the format question; waiting for the answer."))

    def test_a_subagent_cannot_spawn_a_background_agent(self):
        background = {"tool_name": "Agent", "tool_input": {"prompt": "Implement phase 2.", "run_in_background": True}}
        out = self.hook("PreToolUse", {**background, "agent_id": "owner-1"})["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("when your turn ends, the harness kills your background children", out["permissionDecisionReason"])
        self.assertIn("Run it in the foreground; for parallel work, put several foreground Agent calls in one message.", out["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", background))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "Implement phase 2."}, "agent_id": "owner-1"}))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "sleep 1", "run_in_background": True}, "agent_id": "owner-1"}))

    def test_a_subagents_todo_list_stays_its_own_and_holds_only_its_own_turn(self):
        self.todo("add", "Lead: ship phase 3")
        for command in (f"python3 {GUARD} todo from demo --session claude:s1",
                        f'g() {{ python3 {GUARD} "$@" --session claude:s1; }}; g todo list',
                        f"python3 {GUARD} todo add x --session claude:s1 --agent owner-10"):
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}, "agent_id": "owner-1"})["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny", command)
            self.assertIn("Add `--agent owner-1` to every guard todo command", out["permissionDecisionReason"])
            self.assertIn("todo from <skill> --session claude:s1 --agent owner-1", out["permissionDecisionReason"])
        for command in (f"python3 {GUARD} todo add 'Owner: build it' --session claude:s1 --agent owner-1", f"grep -n todo {GUARD}",
                        "grep -n 'guard.py todo from' notes.md", "python3 - <<'EOF'\nprint('g() { python3 guard.py \"$@\" --session x; }')\nEOF"):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}, "agent_id": "owner-1"}), command)
        out = self.todo("add", "Owner: build it", "--agent", "owner-1")
        self.assertIn("1. Owner: build it", out)
        self.assertNotIn("Lead", out)
        lead = self.todo("list")
        self.assertIn("1. Lead: ship phase 3", lead)
        self.assertNotIn("Owner", lead)
        blocked = self.stop("Working.")["reason"]
        self.assertIn("1. Lead: ship phase 3", blocked)
        self.assertNotIn("Owner", blocked)
        held = self.hook("SubagentStop", {"agent_id": "owner-1", "last_assistant_message": "Handing back."})
        self.assertEqual(held["decision"], "block")
        self.assertIn("1. Owner: build it", held["reason"])
        self.assertNotIn("Lead", held["reason"])
        self.assertIn("todo done <n> --token <token> --session claude:s1 --agent owner-1", held["reason"])
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "other-2", "last_assistant_message": "Done."}))
        self.assertIn("Every item is resolved", self.todo("done", "1", "--agent", "owner-1"))
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "owner-1", "last_assistant_message": "Handing back."}))
        self.assertIn("1. Lead: ship phase 3", self.stop("Working.")["reason"])

    def test_autonomous_and_guard_blocks_combine(self):
        self.hook("UserPromptSubmit", {"prompt": "going to bed, build it"})
        out = self.stop("Working \u2014 more to do.")
        self.assertEqual(out["decision"], "block")
        self.assertIn("em dash", out["reason"])
        self.assertIn("done condition", out["reason"])

    def state(self):
        return json.loads(pathlib.Path(self.env["GUARD_HOME"], "sessions", "claude-s1.json").read_text())

    def guard(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(GUARD), *args], capture_output=True, text=True, env=self.env, cwd=self.tmp.name)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def test_todo_from_orders_items_and_done_waits_on_open_dependencies(self):
        self.write_skill("flow", """\
            ---
            name: flow
            description: x
            ---

            1. Plan it.
            2. Build it.
            3. Write the checks, in parallel with step 2.
            4. Review it. Starts after step 2.
            5. Prove it.
            """)
        self.todo("from", "flow")
        self.assertEqual({i["n"]: i["after"] for i in self.state()["todo"]}, {1: [], 2: [1], 3: [1], 4: [2], 5: [3, 4]})
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import order
        texts = ["A.", "B.", "C.", "D, starts after steps 1 and 3.", "E. Starts after steps 1, 2 and 4.", "F, beside step 2.", "G."]
        self.assertEqual(order.dependencies([(n, t, t, False) for n, t in enumerate(texts, 1)]),
                         {1: [], 2: [1], 3: [2], 4: [1, 3], 5: [1, 2, 4], 6: [1], 7: [5, 6]})
        self.assertIn("[ ] 5. Prove it. (flow) [after 3, 4]", self.todo("list"))
        refused = self.close(3, ok=False)
        self.assertIn("item 3 waits on item 1 (Plan it.), still open", refused)
        self.todo("wait", "1", "--reason", "scope")
        self.assertIn("still waiting", self.close(2, ok=False))
        self.close(1)
        self.close(3)
        self.assertIn("waits on item 2 (Build it.)", self.close(4, ok=False))
        self.assertIn("item 5 waits on item 4 (Review it.), still open", self.close(5, ok=False))
        self.todo("skip", "2", "--reason", "already built")
        self.close(4)
        self.todo("add", "Loose end")
        self.todo("done", "6")
        self.assertIn("Every item is resolved", self.close(5))

    def test_todo_show_attaches_the_principles_an_item_names_and_done_needs_its_token(self):
        self.write_skill("principles", "---\nname: principles\ndescription: x\n---\n\n# Principles\n\nThe index.\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n"
                                 "1. Design it from the index (`../principles/SKILL.md`) and Fix Root Causes (`../principles/references/principles/fix-root-causes.md`).\n"
                                 "2. Read every principle file, then wrap up.\n")
        self.todo("from", "flow")
        shown = self.todo("show", "1")
        text = self.state()["todo"][0]["text"]
        principle = self.skills / "principles" / "references" / "principles" / "fix-root-causes.md"
        expected = hashlib.sha256((text + "# Principles\n\nThe index." + principle.read_text()).encode()).hexdigest()[:6]
        self.assertEqual(shown.strip().splitlines()[-1], f"token: {expected}")
        for fragment in ("Item 1 (from flow):", text, "--- ../principles/SKILL.md ---", "The index.",
                         "--- ../principles/references/principles/fix-root-causes.md ---", "Reproduce first."):
            self.assertIn(fragment, shown)
        self.assertNotIn("name: principles", shown)
        self.assertEqual(self.state()["principles_read"], ["fix-root-causes"])
        refused = self.todo("done", "1", ok=False)
        self.assertIn("needs proof you read it", refused)
        self.assertIn("todo show 1 --session claude:s1", refused)
        self.assertIn("does not match its current text", self.todo("done", "1", "--token", "abcdef", ok=False))
        principle.write_text("# Fix Root Causes\n\nReproduce first, then fix.\n")
        self.assertIn("does not match", self.todo("done", "1", "--token", expected, ok=False))
        self.close(1)
        self.todo("add", "Ad hoc")
        self.todo("done", "3")
        self.close(2)

    def test_a_hold_lets_the_turn_end_with_open_items_until_it_expires(self):
        self.todo("add", "Run the codex check")
        self.assertEqual(self.stop("Waiting for the codex limit.")["decision"], "block")
        later = (datetime.datetime.now() + datetime.timedelta(minutes=90)).strftime("%H:%M")
        out = self.todo("hold", "--until", later, "--reason", "codex usage limit resets")
        self.assertIn(f"Held until {later}: codex usage limit resets", out)
        self.assertIsNone(self.stop("Waiting for the codex limit."))
        self.assertIn("has already passed", self.todo("hold", "--until", "2020-01-01T00:00", "--reason", "x", ok=False))
        self.assertIn("HH:MM or an ISO time", self.todo("hold", "--until", "soon", "--reason", "x", ok=False))
        path = pathlib.Path(self.env["GUARD_HOME"], "sessions", "claude-s1.json")
        data = self.state()
        data["hold"]["until"] = time.time() - 1
        path.write_text(json.dumps(data))
        self.assertEqual(self.stop("Waiting for the codex limit.")["decision"], "block")
        self.assertNotIn("Held until", self.todo("list"))

    def test_a_hold_ends_with_the_list_it_was_set_on(self):
        later = (datetime.datetime.now() + datetime.timedelta(minutes=90)).strftime("%H:%M")
        self.todo("add", "Run the codex check")
        self.todo("hold", "--until", later, "--reason", "codex usage limit resets")
        self.todo("done", "1")
        self.todo("add", "Next task's first item")
        self.assertEqual(self.stop("Done for now.")["decision"], "block")
        self.assertNotIn("Held until", self.todo("list"))
        self.todo("hold", "--until", later, "--reason", "codex usage limit resets")
        self.todo("clear", "--reason", "the user stopped the work")
        self.todo("add", "Another task")
        self.assertEqual(self.stop("Done for now.")["decision"], "block")

    def test_an_autonomous_run_lets_a_held_turn_end_without_counting_it_as_idle(self):
        home = pathlib.Path(self.env["AUTORUN_HOME"])
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(json.dumps({"review": False}))
        self.hook("UserPromptSubmit", {"prompt": "going to bed, build it"})
        run = next((home / "active").iterdir()).name
        subprocess.run([sys.executable, str(HOOK), "start", "--run", run, "--session", "claude:s1", "--done", "shipped"], env=self.env, capture_output=True, text=True, cwd=self.tmp.name)
        self.todo("add", "Run the codex check")
        for _ in range(2):
            self.assertEqual(self.stop("Waiting for the codex limit.")["decision"], "block")
        later = (datetime.datetime.now() + datetime.timedelta(minutes=90)).strftime("%H:%M")
        self.todo("hold", "--until", later, "--reason", "codex usage limit resets")
        for _ in range(5):
            out = self.stop("Waiting for the codex limit.")
            self.assertNotIn("decision", out)
            self.assertEqual(out["systemMessage"], f"autorun: run {run} paused on a timed hold until {later}: codex usage limit resets")
        self.assertEqual(self.stop("Waiting \u2014 for the limit.")["decision"], "block")
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": "Waiting?"})["decision"], "block")
        self.todo("add", "Sub item", "--agent", "ex-1")
        self.todo("hold", "--until", later, "--reason", "claude limit", "--agent", "ex-1")
        self.assertIn("claude limit", self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": "Waiting?"})["systemMessage"])
        path = pathlib.Path(self.env["GUARD_HOME"], "sessions", "claude-s1.json")
        data = self.state()
        data["hold"]["until"] = time.time() - 1
        path.write_text(json.dumps(data))
        blocked = self.stop("Waiting for the codex limit.")
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("is not done", blocked["reason"])
        self.assertFalse(any((home / "runs").glob("*/gates/*")) if (home / "runs").exists() else False)

    def test_todo_check_exits_zero_only_when_nothing_is_open_or_waiting(self):
        self.assertIn("empty", self.todo("check"))
        self.todo("add", "One")
        self.assertIn("[ ] 1. One", self.todo("check", ok=False))
        self.todo("wait", "1", "--reason", "answer")
        self.assertIn("[?] 1. One", self.todo("check", ok=False))
        self.todo("done", "1")
        self.assertIn("Every item is resolved", self.todo("check"))

    def test_lint_reports_errors_and_warnings_in_a_skill_as_todo_from_reads_it(self):
        self.write_skill("checker", "---\nname: checker\ndescription: x\n---\n")
        (self.skills / "checker" / "scripts").mkdir()
        (self.skills / "checker" / "scripts" / "check.py").write_text("")
        self.write_skill("good", "---\nname: good\ndescription: x\n---\n\n1. Build. Close this step only when `../checker/scripts/check.py plan --checks` passes.\n"
                                 "2. Check, in parallel with step 1. Uses the demo skill (`../demo/SKILL.md`).\n")
        self.assertIn("no errors", self.guard("lint", "good"))
        self.write_skill("bad", "---\nname: bad\ndescription: x\n---\n\n"
                                "1. Plan. Starts after step 2.\n4. Ship. Starts after steps 2, 3 and 9.\n"
                                "2. Build, beside step 7. Close this step only when `../checker/scripts/gone.py lock` passes.\n"
                                "3. Review. Close this step only when the reviewer agrees. Mandatory. Skip this step when tiny. Run `../absent/SKILL.md`.\n")
        out = self.guard("lint", str(self.skills / "bad" / "SKILL.md"), ok=False)
        for fragment in ("error: step 2: \"beside step 7\" names step 7, which this skill does not have",
                         "error: step 4: \"Starts after steps 2, 3 and 9\" names step 9, which this skill does not have",
                         "error: step 2: the gate `../checker/scripts/gone.py lock` names a script that is not installed beside this skill",
                         "error: the steps wait on each other in a cycle",
                         "warning: step 3: says \"Close this step only when\" but names no backticked gate",
                         "warning: step 3: is Mandatory and also says \"Skip this step\"",
                         "warning: step 3: names ../absent/SKILL.md, which is not installed beside this skill"):
            self.assertIn(fragment, out)
        self.write_skill("vague", "---\nname: vague\ndescription: x\n---\n\n# Vague\n\nFollow the steps below.\n\n- Do it.\n")
        self.assertIn("no steps found", self.guard("lint", "vague", ok=False))
        self.write_skill("rules", "---\nname: rules\ndescription: x\n---\n\n# Rules\n\nLifecycle steps converge. A how-to lists steps to a goal.\n")
        self.assertIn("no errors", self.guard("lint", "rules"))
        everything = self.guard("lint", "--all", ok=False)
        self.assertIn("bad/SKILL.md: error", everything)
        self.assertIn("vague/SKILL.md: error", everything)
        self.assertNotIn("good/SKILL.md: error", everything)
        self.assertIn("a cycle (", self.todo("from", "bad", ok=False))

    def test_a_long_subagent_hand_back_is_sent_back_once_per_length(self):
        long = " ".join(["word"] * 320)
        held = self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": long})
        self.assertEqual(held["decision"], "block")
        self.assertIn("320 words", held["reason"])
        self.assertIn("Put the details in a file and hand back at most 200 words with the file path.", held["reason"])
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": long}))
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": long + " more"})["decision"], "block")
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "ex-2", "last_assistant_message": "字" * 580}))
        self.assertIn("310 words", self.hook("SubagentStop", {"agent_id": "ex-3", "last_assistant_message": "字" * 620})["reason"])
        self.assertIsNone(self.stop(long))
        handback = {"agent_id": "ex-4", "tool_name": "SubagentHandback", "tool_input": {"message": long}}
        out = self.hook("PreToolUse", handback)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("at most 200 words", out["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", handback))

    def test_a_hand_back_passes_once_per_text_and_only_until_its_delegate_ends(self):
        long, other = " ".join(["word"] * 320), " ".join(["ward"] * 320)
        self.hook("PreToolUse", {"agent_id": "ex-1", "tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": long})["decision"], "block")
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": other})["decision"], "block")
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": other}))
        self.assertNotIn("ex-1", self.state().get("handbacks", {}))
        self.assertEqual(self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": other})["decision"], "block")
        self.hook("SubagentStop", {"agent_id": "ex-1", "last_assistant_message": other})
        handback = {"agent_id": "ex-1", "tool_name": "SubagentHandback", "tool_input": {"message": other}}
        self.assertEqual(self.hook("PreToolUse", handback)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.hook("PreToolUse", handback))
        self.hook("PostToolUse", {"tool_name": "TaskStop", "tool_input": {"task_id": "ex-1"}})
        self.assertNotIn("ex-1", self.state().get("handbacks", {}))

    def test_a_rerun_waits_until_every_running_fix_group_has_handed_back(self):
        rerun = {"tool_name": "Bash", "tool_input": {"command": "python3 ../verify/scripts/verify.py rerun --only T1 T2"}}
        full = {"tool_name": "Bash", "tool_input": {"command": "python3 ../verify/scripts/verify.py rerun"}}
        self.assertIsNone(self.hook("PreToolUse", rerun))
        self.hook("PreToolUse", {"agent_id": "fix-1", "tool_name": "Bash", "tool_input": {"command": "ls"}})
        for command in (rerun, full):
            out = self.hook("PreToolUse", command)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("A fix group is still working; rerun once every group has handed back", out["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", {**rerun, "agent_id": "fix-1"}))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "grep -n 'verify.py rerun' notes.md"}}))
        for wrapped in ("bash -lc 'python3 ../verify/scripts/verify.py rerun'", "sh -c \"cd /repo && python3 '../verify/scripts/verify.py' rerun --only T1\"",
                        "env FOO=1 zsh -c 'python3 ../verify/scripts/verify.py rerun'", "eval 'python3 ../verify/scripts/verify.py rerun'",
                        "bash -c \"bash -c 'python3 ../verify/scripts/verify.py rerun'\"",
                        "if python3 ../verify/scripts/verify.py rerun --only T1; then :; fi", "until ! python3 ../verify/scripts/verify.py rerun; do :; done",
                        "if true; then :; elif python3 ../verify/scripts/verify.py rerun; then :; else :; fi",
                        "{ python3 ../verify/scripts/verify.py rerun --only T1; } 2>&1 | tee rerun.out", "time -p python3 ../verify/scripts/verify.py rerun",
                        "2>&1 python3 ../verify/scripts/verify.py rerun", 'out="$(python3 ../verify/scripts/verify.py rerun --only T1)"',
                        "echo `python3 ../verify/scripts/verify.py rerun`", "bash -lc 'if python3 ../verify/scripts/verify.py rerun; then :; fi'"):
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": wrapped}})
            self.assertEqual(out and out["hookSpecificOutput"]["permissionDecision"], "deny", wrapped)
        out = self.hook("PreToolUse", {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "python3 ../verify/scripts/verify.py rerun"]}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        for text in ("echo \"bash -lc 'verify.py rerun'\" >> notes.md", "git commit -m 'run verify.py rerun after fixes'", "ls # verify.py rerun",
                     "if grep -q 'verify.py rerun' notes.md; then echo if; fi", "echo 'then `python3 verify.py rerun`' >> notes.md",
                     "git commit -m \"$(cat <<'EOF'\nif python3 verify.py rerun; then :; fi\nEOF\n)\"", "echo \"run \\`verify.py rerun\\` next\""):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": text}}), text)
        self.hook("SubagentStop", {"agent_id": "fix-1", "last_assistant_message": "Fixed T1."})
        self.assertIsNone(self.hook("PreToolUse", rerun))

    def age_delegate(self, agent_id, since=None, last=None):
        path = pathlib.Path(self.env["GUARD_HOME"], "sessions", "claude-s1.json")
        data = self.state()
        data["delegates"][agent_id].update({k: time.time() - v for k, v in (("since", since), ("last", last)) if v is not None})
        path.write_text(json.dumps(data))

    def rerun_reason(self, agent_id="verifier"):
        out = self.hook("PreToolUse", {"agent_id": agent_id, "tool_name": "Bash", "tool_input": {"command": "python3 ../verify/scripts/verify.py rerun"}})
        return out and out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_once_subagents_announce_their_start_a_forked_helper_calling_tools_is_no_delegate(self):
        calls = self.fake_verify("in use")
        self.hook("SubagentStart", {"agent_id": "verifier", "agent_type": "general-purpose"})
        self.hook("PreToolUse", {"agent_id": "memory-fork", "tool_name": "Read", "tool_input": {"file_path": "/m/MEMORY.md"}})
        self.assertIsNone(self.rerun_reason())
        self.assertNotIn("memory-fork", self.state()["delegates"])
        self.hook("SubagentStart", {"agent_id": "fix-2", "agent_type": "general-purpose"})
        reason = self.rerun_reason()
        self.assertIn("Still running: fix-2.", reason)
        self.assertIn("stops and reports it to the lead instead of retrying", reason)
        self.assertIn("guard.py delegates end <id> --reason", reason)
        before = time.time()
        self.assertEqual(self.spawn(), "allow")
        self.assertLess(float(self.last_sweep(calls)[2]), before)
        self.hook("SubagentStop", {"agent_id": "fix-2", "last_assistant_message": "Fixed T2."})
        self.assertIsNone(self.rerun_reason())

    def test_a_delegate_resumed_after_its_stop_runs_again(self):
        self.hook("SubagentStart", {"agent_id": "fix-2", "agent_type": "general-purpose"})
        self.hook("SubagentStop", {"agent_id": "fix-2", "last_assistant_message": "Fixed T2."})
        self.assertIsNone(self.rerun_reason())
        self.hook("PreToolUse", {"agent_id": "fix-2", "tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertIn("Still running: fix-2.", self.rerun_reason())

    def test_without_subagent_starts_the_first_tool_call_starts_a_delegate(self):
        self.hook("PreToolUse", {"agent_id": "fix-2", "tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertIn("Still running: fix-2.", self.rerun_reason())
        self.hook("SubagentStart", {"agent_id": "verifier", "agent_type": "general-purpose"})
        self.assertIsNone(self.rerun_reason(), "a start in the session proves fix-2 was no started agent")

    def test_a_delegate_silent_past_the_bash_timeout_no_longer_holds_a_rerun_or_its_processes(self):
        calls = self.fake_verify("in use")
        for agent_id in ("gone", "fix-2"):
            self.hook("SubagentStart", {"agent_id": agent_id, "agent_type": "general-purpose"})
        self.age_delegate("gone", since=1500, last=1300)
        self.assertIn("Still running: fix-2.", self.rerun_reason())
        self.assertEqual(self.spawn(), "allow")
        self.assertGreater(float(self.last_sweep(calls)[2]), time.time() - 60)

    def test_the_lead_lists_delegates_and_ends_one_it_confirmed_gone(self):
        self.hook("SubagentStart", {"agent_id": "gone", "agent_type": "general-purpose"})
        run = lambda *args: subprocess.run([sys.executable, str(GUARD), "delegates", *args, "--session", "claude:s1"],
                                           capture_output=True, text=True, env=self.env, cwd=self.tmp.name)
        self.assertRegex(run().stdout, r"gone  running  since \S+")
        self.assertNotEqual(run("end", "gone").returncode, 0)
        self.assertNotEqual(run("end", "nobody", "--reason", "x").returncode, 0)
        self.assertIn("Ended gone: no such agent in ListAgents", run("end", "gone", "--reason", "no such agent in ListAgents").stdout)
        self.assertRegex(run().stdout, r"gone  ended")
        self.assertIsNone(self.rerun_reason())

    def test_only_the_lead_ends_a_delegate(self):
        end = "python3 /x/guard.py delegates end gone --reason gone --session claude:s1"
        out = self.hook("PreToolUse", {"agent_id": "verifier", "tool_name": "Bash", "tool_input": {"command": end}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("Only the lead ends a delegate", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", {"agent_id": "verifier", "tool_name": "Bash",
                                                    "tool_input": {"command": "python3 /x/guard.py delegates --session claude:s1"}}))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": end}}))

    def test_a_pr_waits_for_every_step_before_the_close_step(self):
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Build.\n2. Prove.\n3. Close, then open the PR with the open-pr skill (`../open-pr/SKILL.md`).\n")
        self.todo("from", "flow")
        create = {"tool_name": "Bash", "tool_input": {"command": "gh pr create --title 'feat: x' --body '## Scope\nx'"}}
        out = self.hook("PreToolUse", create)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("The PR opens in item 3", out["permissionDecisionReason"])
        self.assertIn("1. Build., 2. Prove.", out["permissionDecisionReason"])
        for wrapped in ("bash -lc \"gh pr create --title 'feat: x' --body x\"", "env GH_TOKEN=x gh pr create --title x", "eval 'gh pr create -t x'",
                        "if gh pr create --title 'feat: x' --body x; then :; fi", "while ! gh pr create -t x; do sleep 5; done",
                        "if ! git push; then :; else gh pr create -t x; fi", "( cd /repo && gh pr create -t x )",
                        "cat <<'EOF' | gh pr create --title 'feat: x' --body-file -\n## Scope\nx\nEOF", 'url="$(gh pr create -t x)"'):
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": wrapped}})
            self.assertEqual(out and out["hookSpecificOutput"]["permissionDecision"], "deny", wrapped)
        for text in ("echo 'gh pr create next' >> plan.md", "if grep -q 'gh pr create' plan.md; then echo then; fi"):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": text}}), text)
        self.close(1)
        self.todo("skip", "2", "--reason", "no checks")
        self.assertIsNone(self.hook("PreToolUse", create))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "gh pr edit 4 --add-label x"}}))

    def limits(self):
        path = pathlib.Path(self.env["ORCHESTRATOR_HOME"]) / "limits.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def test_a_limit_is_recorded_only_from_an_agent_cli_that_failed_on_it(self):
        codex = "■ You've hit your usage limit. Upgrade to Pro (https://openai.com/chatgpt/pricing), or try again at Oct 23rd, 2026 3:05 PM."
        claude = "Claude usage limit reached. Your limit will reset at 11:59pm (America/Los_Angeles)."
        quoted = {"content": [{"type": "text", "text": f"Review done. A fixture says {codex}\nAnd: {claude}"}]}
        for tool in ("Agent", "Task", "SendMessage"):
            self.hook("PostToolUse", {"tool_name": tool, "tool_input": {"prompt": "x"}, "tool_response": quoted})
        for command in ("cat build.log", "grep -n 'usage limit' notes.md", "python3 ../verify/scripts/verify.py rerun",
                        "python3 /x/salvo/scripts/salvo.py run --out /tmp/s codex:d < t.md", "echo 'codex exec -m x'"):
            self.hook("PostToolUseFailure", {"tool_name": "Bash", "tool_input": {"command": command}, "error": f"Exit code 1\n{codex}"})
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": "x.log"}, "tool_response": codex})
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "codex exec -m gpt - < task.md"}, "tool_response": {"stdout": codex, "stderr": ""}})
        self.hook("PostToolUseFailure", {"tool_name": "Bash", "tool_input": {"command": "codex exec -m gpt - < review.md"}, "error": f"Exit code 1\n{claude}"})
        self.assertEqual(self.limits(), {})
        self.hook("PostToolUseFailure", {"tool_name": "Bash", "tool_input": {"command": "codex exec -m gpt - < task.md"}, "error": f"Exit code 1\n{codex}"})
        entry = self.limits()["codex"]
        self.assertTrue(entry["until"].startswith("2026-10-23T15:05"), entry)
        self.assertIn("try again at", entry["source"])
        self.assertTrue(entry["seen"])
        self.hook("PostToolUseFailure", {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'cd /repo && claude -p --model x < t.md'"},
                                         "error": f"Exit code 1\nStopped early.\n{claude}"})
        until = datetime.datetime.fromisoformat(self.limits()["claude"]["until"])
        self.assertEqual((until.hour, until.minute), (23, 59))
        (pathlib.Path(self.env["ORCHESTRATOR_HOME"]) / "limits.json").unlink()
        for response in (f"Exit code: 0\nWall time: 3 seconds\nOutput:\n{codex}", {"exit_code": 0, "output": codex}):
            self.hook("PostToolUse", {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "codex exec - < t.md"]}, "tool_response": response}, agent="codex")
        self.assertEqual(self.limits(), {})
        for response in (f"Exit code: 1\nWall time: 3 seconds\nOutput:\n{codex}", {"exit_code": 1, "output": codex}):
            self.hook("PostToolUse", {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "codex exec - < t.md"]}, "tool_response": response}, agent="codex")
            self.assertIn("codex", self.limits())
            (pathlib.Path(self.env["ORCHESTRATOR_HOME"]) / "limits.json").unlink()

    def test_limit_times_parse_in_the_local_zone_with_a_date_in_the_text_winning(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import quota
        now = datetime.datetime(2026, 10, 21, 14, 0).timestamp()

        def at(*moment):
            return datetime.datetime(*moment).timestamp()

        cases = {
            "You've hit your usage limit. Upgrade to Pro, or try again at 3:05 PM.": ("codex", at(2026, 10, 21, 15, 5)),
            "You've hit your usage limit, try again at 1:30 PM.": ("codex", at(2026, 10, 22, 13, 30)),
            "You've hit your usage limit. Try again in 2 hours 5 minutes.": ("codex", now + 7500),
            "You've hit your usage limit. Try again at Nov 2nd, 2026 9:00 AM.": ("codex", at(2026, 11, 2, 9, 0)),
            "Claude usage limit reached · resets 5pm (Europe/London)": ("claude", at(2026, 10, 21, 17, 0)),
            "You've reached your usage limit. It resets at 2026-10-22T08:30": ("claude", at(2026, 10, 22, 8, 30)),
            "Claude AI usage limit reached|1792600000": ("claude", 1792600000),
            "Your usage limit resets soon.": ("claude", now + 3600),
        }
        for text, expected in cases.items():
            self.assertEqual([(a, u) for a, u, _ in quota.scan(text, now)], [expected], text)
        self.assertEqual(quota.scan("The usage limit page explains plans.", now), [])
        self.assertEqual(quota.scan("You've hit your usage limit.", now), [])

    def models(self, base=None, planner=("claude:a:high", "codex:b:high"), executor=("claude:c:high", "codex:d:medium")):
        base = pathlib.Path(base or self.env["ORCHESTRATOR_HOME"])
        base.mkdir(parents=True, exist_ok=True)

        def entry(spec):
            return dict(zip(("agent", "model", "effort"), spec.split(":")))

        (base / "models.json").write_text(json.dumps({"version": 2, "roles": {"planner": [entry(s) for s in planner], "executor": [entry(s) for s in executor]}}))

    def limit(self, agent, minutes=60):
        path = pathlib.Path(self.env["ORCHESTRATOR_HOME"]) / "limits.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.limits()
        data[agent] = {"until": (datetime.datetime.now().astimezone() + datetime.timedelta(minutes=minutes)).isoformat(timespec="minutes"),
                       "seen": "2026-10-21T10:00+00:00", "source": f"{agent} limit"}
        path.write_text(json.dumps(data))

    def test_quota_pick_skips_limited_and_avoided_candidates(self):
        self.models()
        self.assertEqual(self.guard("quota", "pick", "--role", "executor").strip(), "claude:c:high")
        self.assertIn("No agent is limited", self.guard("quota", "status"))
        self.limit("claude")
        self.limit("gemini", minutes=-5)
        self.assertIn("claude: limited until", self.guard("quota", "status"))
        self.assertNotIn("gemini", self.guard("quota", "status"))
        self.assertEqual(self.guard("quota", "pick", "--role", "planner").strip(), "codex:b:high")
        self.assertIn("every planner candidate is avoided", self.guard("quota", "pick", "--role", "planner", "--avoid", "codex:b", ok=False))
        self.limit("codex", minutes=30)
        self.assertIn("every candidate is limited until", self.guard("quota", "pick", "--role", "executor", ok=False))
        self.assertIn("hold until then", self.guard("quota", "pick", "--role", "executor", ok=False))
        self.models(pathlib.Path(self.tmp.name) / ".agents" / "orchestrator", executor=("codex:e:low", "claude:f:low"))
        self.assertIn("every candidate is limited", self.guard("quota", "pick", "--role", "executor", ok=False))
        (pathlib.Path(self.env["ORCHESTRATOR_HOME"]) / "limits.json").unlink()
        self.assertEqual(self.guard("quota", "pick", "--role", "executor").strip(), "codex:e:low")

    def test_quota_pick_relax_walks_the_fallback_order(self):
        self.models(planner=("claude:a:high", "codex:b:high"), executor=("claude:c:high", "codex:d:medium"))
        self.limit("claude")
        out = self.guard("quota", "pick", "--role", "planner", "--avoid", "codex", "--relax")
        for line in ("1. a candidate that keeps every separation rule", "2. one that relaxes \"reviewer from a different family\"",
                     "3. one that relaxes \"verifier on a different entry from the executor\"", "4. a candidate from the other role",
                     "codex:b:high", "relaxed: one that relaxes \"reviewer from a different family\""):
            self.assertIn(line, out)
        out = self.guard("quota", "pick", "--role", "executor", "--avoid", "codex:d", "--relax")
        self.assertIn("relaxed: one that relaxes \"verifier on a different entry from the executor\"", out)
        self.models(planner=("codex:b:high",), executor=("claude:c:high",))
        out = self.guard("quota", "pick", "--role", "executor", "--relax")
        self.assertIn("codex:b:high", out)
        self.assertIn("relaxed: a candidate from the other role (planner)", out)
        self.assertNotIn("relaxed", self.guard("quota", "pick", "--role", "planner", "--relax"))

    def test_a_limited_agent_is_not_launched_and_the_deny_names_the_next_candidates(self):
        self.models()
        launches = ["python3 /x/salvo/scripts/salvo.py run --out /tmp/s codex:d:medium < task.md",
                    "cd /repo && CODEX_HOME=/tmp/c codex exec -m gpt-5 - < task.md"]
        for command in launches:
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}}), command)
        self.limit("codex")
        for command in launches:
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("codex is limited until", out["permissionDecisionReason"])
            self.assertIn("planner: claude:a:high", out["permissionDecisionReason"])
            self.assertIn("executor: claude:c:high", out["permissionDecisionReason"])
        for command in ("python3 /x/salvo/scripts/salvo.py run --out /tmp/codex:d claude:c:high < task.md", "grep -n 'codex exec' notes.md",
                        "echo 'codex exec -m x'"):
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}}), command)
        self.limit("claude")
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "Implement it."}}))
        out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": launches[0]}})["hookSpecificOutput"]
        self.assertIn("every candidate is limited until", out["permissionDecisionReason"])

    def plan_with(self, plan, record=None):
        self.write_skill("verify", "---\nname: verify\ndescription: x\n---\n\n# Verify\n")
        scripts = self.skills / "verify" / "scripts"
        scripts.mkdir(exist_ok=True)
        directory = pathlib.Path(self.tmp.name) / "verification"
        directory.mkdir(exist_ok=True)
        (scripts / "verify.py").write_text(f"import sys\nif sys.argv[1:] == ['where']:\n    print({str(directory)!r})\n")
        if record:
            phase = pathlib.Path(self.tmp.name) / "plan" / "phases" / "05" / "plan.md"
            phase.parent.mkdir(parents=True)
            phase.write_text(plan)
            (directory / "base.json").write_text(json.dumps({"base": "abc", "plan": str(phase.parent.parent.parent), "phase_plan": str(phase)}))
        else:
            (directory / "base.json").unlink(missing_ok=True)
            (directory / "plan.md").write_text(plan)

    def test_an_agent_that_real_agent_checks_drive_is_reserved_for_them(self):
        self.models()
        codex = {"tool_name": "Bash", "tool_input": {"command": "codex exec -m gpt-5 - < review.md"}}
        claude = {"tool_name": "Bash", "tool_input": {"command": "python3 salvo.py run --out /tmp/s claude:a:high < review.md"}}
        self.assertIsNone(self.hook("PreToolUse", codex))
        plan = ("# Plan\n\nChecks marked `Agent: real` run once with Claude Code and once with Codex.\n\n## Checks\n\n"
                "### T1. A real turn\n\n- Tier: e2e\n- Agent: real: a model must choose the command\n\n"
                "### T2. A fake turn\n\n- Agent: fake: wire logic\n")
        self.plan_with(plan, record=True)
        out = self.hook("PreToolUse", codex)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("codex is reserved for this branch's real-agent checks (T1)", out["permissionDecisionReason"])
        self.assertIn("quota pick --role <role> --avoid codex", out["permissionDecisionReason"])
        self.assertIn("planner: claude:a:high", out["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", claude))
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "python3 ../verify/scripts/verify.py rerun --only T1"}}))
        self.plan_with(plan.replace("Agent: real", "Agent: fake"))
        self.assertIsNone(self.hook("PreToolUse", codex))
        self.plan_with("# Plan\n\n### T3. Codex asks\n\n- Agent: real: Claude Code is the lead, this drives Codex\n")
        self.assertIn("(T3)", self.hook("PreToolUse", codex)["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.hook("PreToolUse", {**codex, "tool_input": {"command": "codex exec -m gpt-5 -"}}, agent="codex"))

    def plans_where_run(self, plans):
        """A verify skill whose `where` answers per working directory, and each directory's plan."""
        self.write_skill("verify", "---\nname: verify\ndescription: x\n---\n\n# Verify\n")
        scripts = self.skills / "verify" / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "verify.py").write_text("import os, sys\nif sys.argv[1:] == ['where']:\n    print(os.path.join(os.getcwd(), 'verification'))\n")
        for directory, plan in plans.items():
            (directory / "verification").mkdir(parents=True, exist_ok=True)
            (directory / "verification" / "plan.md").write_text(plan)

    def test_the_reserved_agent_is_read_from_the_plan_where_the_command_runs(self):
        self.models()
        here, worktree = pathlib.Path(self.tmp.name), pathlib.Path(self.tmp.name) / "worktrees" / "phase-2"
        real = "# Plan\n\n### T1. A real turn\n\n- Agent: real: Codex must choose the command\n"
        fake = "# Plan\n\n### T1. A fake turn\n\n- Agent: fake: wire logic\n"
        launches = ["codex exec -m gpt-5 - < review.md", "python3 /x/salvo/scripts/salvo.py run --out /tmp/s codex:d:medium < review.md"]
        self.plans_where_run({here: real, worktree: fake})
        for launch in launches:
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": launch}})
            self.assertIn("codex is reserved", out["hookSpecificOutput"]["permissionDecisionReason"], launch)
            for moved in (f"cd {worktree} && {launch}", f"cd worktrees/phase-2; {launch}", f"cd worktrees && cd phase-2 && {launch}"):
                self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": moved}}), moved)
        self.plans_where_run({here: fake, worktree: real})
        for launch in launches:
            self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": launch}}), launch)
            out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cd '{worktree}' && {launch}"}})
            self.assertIn("codex is reserved", out["hookSpecificOutput"]["permissionDecisionReason"], launch)
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": f"ls; cd {worktree} && {launches[0]}"}}),
                          "only a leading cd moves the command")

    def test_a_cd_whose_target_guard_cannot_know_never_applies_the_reservation(self):
        self.models()
        here, home = pathlib.Path(self.tmp.name), pathlib.Path(self.tmp.name) / "home"
        real = "# Plan\n\n### T1. A real turn\n\n- Agent: real: Codex must choose the command\n"
        self.plans_where_run({here: real, home: real})
        self.env["HOME"] = str(home)
        launch = "codex exec -m gpt-5 - < review.md"
        for unknown in ("cd -", 'cd "$WORKTREE"', "cd $(git rev-parse --show-toplevel)", "cd `git rev-parse --show-toplevel`",
                        "cd -P worktrees", "cd worktrees/*"):
            self.assertIsNone(self.denial(f"{unknown} && {launch}"), unknown)
        for literal in ("cd '~'", 'cd "~"', "cd \\~"):
            self.assertIsNone(self.denial(f"{literal} && {launch}"), f"{literal} names the directory '~' here, which has no plan")
        for moved in ("cd ~", "cd ~/", "cd ."):
            self.assertIn("codex is reserved", self.denial(f"{moved} && {launch}") or "", moved)

    def denial(self, command):
        out = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})
        return out and out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_a_process_match_whose_pattern_matches_its_own_command_line_is_denied(self):
        for command in ('until ! pgrep -f "C1.check.sh web-4906" >/dev/null; do sleep 3; done', "pgrep -fl 'shop.server' || echo none",
                        "pkill -f inspector-relay.mjs; sleep 2; node relay.mjs", "running=$(pgrep -af 'next dev')",
                        "bash -lc 'while pgrep -f build.sh >/dev/null; do sleep 5; done'", "sudo pkill -9 -f cl-test/clean.sh",
                        "pgrep --full -u justin 'vite --port 5173'"):
            reason = self.denial(command)
            self.assertIn("matches the shell that runs this command", reason or "", command)
            self.assertIn("[v]erify.py", reason, command)
        for command in ("until ! pgrep -f '[C]1.check.sh web-4906' >/dev/null; do sleep 3; done", "pkill -f '[i]nspector-relay.mjs'",
                        "pkill -f 'cl-test/clean\\.sh'",
                        "pgrep -x node", "pgrep node || echo none", "pkill -F /tmp/server.pid", "grep -f patterns.txt server.log",
                        "echo 'pgrep -f shop.server' >> notes.md", "git commit -m 'stop pkill -f from matching itself'"):
            self.assertIsNone(self.denial(command), command)

    def test_a_poll_loop_waiting_on_a_verify_run_is_denied(self):
        for command in ('until ! pgrep -f "[v]erify.py rerun" >/dev/null; do sleep 10; done',
                        "while ps aux | grep -v grep | grep -q 'verify.py dryrun'; do sleep 5; done",
                        "python3 ../verify/scripts/verify.py rerun > /tmp/r.out 2>&1 & until grep -q 'PASS\\|FAIL' /tmp/r.out; do sleep 5; done",
                        "until [ -s .verification/rerun.summary ]; do sleep 5; done; cat .verification/rerun.summary",
                        "while true; do grep -q done ../verification/dryrun.log && break; sleep 5; done",
                        "while true; do for f in a b; do echo $f; done; grep -q PASS rerun.out && break; sleep 5; done",
                        "bash -c 'until test -s rerun.out; do sleep 2; done'"):
            reason = self.denial(command)
            self.assertIn("Do not poll for a verify.py rerun or dryrun", reason or "", command)
            self.assertIn("completion notification arrives on its own", reason, command)
        for command in ("python3 ../verify/scripts/verify.py rerun > rerun.out 2>&1 &", "nohup python3 ../verify/scripts/verify.py dryrun T1 &",
                        "python3 ../verify/scripts/verify.py rerun --only T1", "until curl -sf localhost:3000/health; do sleep 1; done",
                        "cat .verification/rerun.summary", "while read -r line; do echo \"$line\"; done < rerun.summary",
                        "for i in 1 2 3; do grep -c PASS rerun.out; sleep 1; done"):
            self.assertIsNone(self.denial(command), command)

    def test_a_loop_is_judged_by_what_decides_its_exit_never_by_a_mention_in_its_body(self):
        for command in ("while true; do if pgrep -f '[v]erify.py rerun' >/dev/null; then sleep 5; else break; fi; done",
                        "while :; do [ -s rerun.summary ] && break; sleep 5; done",
                        "while true; do [ -z \"$(pgrep -f '[v]erify.py dryrun')\" ] && exit 0; sleep 5; done",
                        "while true; do if [ -s rerun.summary ]; then echo ready; break; fi; sleep 5; done",
                        "while true; do grep -q PASS rerun.summary && { echo ready; break; }; sleep 5; done",
                        "while true; do [ -s rerun.summary ] && { echo ready; echo done; break; }; sleep 5; done",
                        "while true; do { grep -q PASS rerun.summary; } && break; sleep 5; done",
                        "while true; do (grep -q PASS rerun.summary; echo checked) && break; sleep 5; done"):
            self.assertIn("Do not poll for a verify.py rerun or dryrun", self.denial(command) or "", command)
        for command in ("while true; do echo rerun.log; sleep 5; done",
                        "while sleep 60; do cp rerun.summary backup/; tail -n 1 dryrun.log; done",
                        "for n in 1 2; do while ! curl -sf localhost:3000; do sleep 1; done; echo rerun.out; done",
                        "until python3 ../verify/scripts/verify.py rerun --only T1 > rerun.out; do sleep 30; done",
                        "while true; do python3 ../verify/scripts/verify.py dryrun --only T1 > dryrun.out && break; sleep 30; done",
                        "while true; do { echo tick; grep -c PASS rerun.out; }; [ -f stop ] && { echo stopping; break; }; sleep 5; done",
                        "while true; do [ -f stop ] && { grep -c PASS rerun.out; break; }; sleep 5; done",
                        "while true; do (echo tick; grep -c PASS rerun.out); [ -f stop ] && break; sleep 5; done"):
            self.assertIsNone(self.denial(command), command)

    def start_watchdog(self):
        """A real watchdog of session s1 under this test process, with its pid file in place."""
        dog = subprocess.Popen([sys.executable, str(GUARD), "watch", "--session", "claude:s1", "--interval", "0.2", "--initial", "60"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env)
        self.addCleanup(reap, dog)
        record = pathlib.Path(self.env["GUARD_HOME"]) / "sessions" / "claude-s1.watch.pid"
        deadline = time.monotonic() + 10
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return dog, record

    def watch_shell(self):
        return {"id": "bw", "type": "shell", "status": "running", "description": "watchdog",
                "command": f"python3 {GUARD} watch --session claude:s1"}

    def test_the_lead_cannot_end_its_turn_on_background_work_no_watchdog_watches(self):
        work = [{"id": "b1", "type": "shell", "status": "running", "description": "rerun", "command": "python3 verify.py rerun"}]
        self.assertIsNone(self.stop("Waiting."))
        self.assertIsNone(self.stop("Waiting.", background_tasks=[]))
        self.assertIsNone(self.stop("Waiting.", background_tasks=[{"id": "m1", "type": "MCP task", "status": "running"}]))
        blocked = self.stop("Waiting.", background_tasks=work)
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("Background work is in flight (python3 verify.py rerun) and no watchdog watches it", blocked["reason"])
        self.assertIn(f"python3 {GUARD} watch --session claude:s1\n", blocked["reason"])
        self.assertIsNone(self.stop("Waiting.", background_tasks=[*work, self.watch_shell()]))
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "a1", "last_assistant_message": "done", "background_tasks": work}))
        dog, record = self.start_watchdog()
        self.assertIsNone(self.stop("Waiting.", background_tasks=work))
        r = subprocess.run([sys.executable, str(GUARD), "watch", "--stop", "--session", "claude:s1"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.stdout, f"Stopped the watchdog (pid {dog.pid}).\n")
        self.assertEqual(dog.wait(10), 0)
        self.assertFalse(record.exists())
        self.assertEqual(self.stop("Waiting.", background_tasks=work)["decision"], "block")

    def test_the_watchdog_rule_lets_a_stuck_lead_go_after_three_blocks_until_the_next_prompt(self):
        work = [{"id": "b1", "type": "subagent", "status": "running", "description": "verifier"}]
        for _ in range(3):
            self.assertEqual(self.stop("Waiting.", background_tasks=work)["decision"], "block")
        self.assertIsNone(self.stop("Waiting.", background_tasks=work))
        self.hook("UserPromptSubmit", {"prompt": "go on"})
        self.assertEqual(self.stop("Waiting.", background_tasks=work)["decision"], "block")

    def test_a_session_where_no_watchdog_can_run_is_not_held_and_a_headless_one_stops_a_watchdog_left_alone(self):
        sessions = pathlib.Path(self.env["GUARD_HOME"]) / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "claude-s1.json").write_text(json.dumps({"watch_unavailable": {"at": 1, "why": "no agent"}}))
        self.assertIsNone(self.stop("Waiting.", background_tasks=[{"id": "b1", "type": "shell", "command": "sleep 300"}]))
        (sessions / "claude-s1.json").write_text("{}")
        dog, _ = self.start_watchdog()
        self.assertIsNone(self.stop("Done.", background_tasks=[self.watch_shell()]))
        self.assertIsNone(dog.poll(), "an interactive session keeps its watchdog between turns")
        with mock.patch.dict(self.env, GUARD_HEADLESS="1"):
            self.assertIsNone(self.stop("Done.", background_tasks=[self.watch_shell(), {"id": "b1", "type": "shell", "command": "sleep 9"}]))
            self.assertIsNone(dog.poll(), "a watchdog beside other work keeps watching it")
            self.assertIsNone(self.stop("Done.", background_tasks=[self.watch_shell()]))
        self.assertEqual(dog.wait(10), 0, "a non-interactive session would wait on a lone watchdog forever")

    def test_a_delegates_work_left_after_its_hand_back_holds_the_leads_turn_until_it_stops(self):
        watched = [self.watch_shell()]

        def launch(agent_id, task):
            self.hook("PostToolUse", {"agent_id": agent_id, "tool_name": "Bash", "tool_input": {"command": "sleep 47", "run_in_background": True},
                                      "tool_response": {"stdout": "", "backgroundTaskId": task}})

        def hand_back(agent_id, success=True):
            self.hook("PostToolUse", {"agent_id": agent_id, "tool_name": "SubagentHandback", "tool_input": {"message": "done"},
                                      "tool_response": {"success": success, "message": "Report delivered to your caller."}})
        for agent_id in ("a1", "a2", "a3"):
            self.hook("SubagentStart", {"agent_id": agent_id, "agent_type": "general-purpose"})
        launch("a1", "bx")
        launch("a2", "by")
        self.assertIsNone(self.stop("Waiting.", background_tasks=[*watched, {"id": "bx", "type": "shell", "command": "sleep 47"}]))
        hand_back("a1")
        hand_back("a2", success=False)
        work = [*watched, {"id": "bx", "type": "shell", "status": "running", "command": "sleep 47"},
                {"id": "by", "type": "shell", "status": "running", "command": "sleep 47"}]
        blocked = self.stop("Waiting.", background_tasks=work)
        self.assertEqual(blocked["reason"], "These delegates handed back, but their work still runs, holding the machine and hiding "
                                            "which job causes a later problem:\n   bx: shell sleep 47, of delegate a1\nStop each "
                                            "with your agent's task-stop tool (Claude Code: TaskStop with the id), then end the turn.")
        self.assertIn("   a1: subagent probe", self.stop("Waiting.", background_tasks=[
            *watched, {"id": "a1", "type": "subagent", "status": "running", "description": "probe"}])["reason"])
        self.assertIsNone(self.stop("Waiting.", background_tasks=watched))
        self.hook("PreToolUse", {"tool_name": "SendMessage", "tool_input": {"to": "a1", "message": "one more thing"}})
        self.assertIsNone(self.stop("Waiting.", background_tasks=work))
        launch("a3", "bz")
        self.assertIsNone(self.hook("SubagentStop", {"agent_id": "a3", "last_assistant_message": "a3 done"}))
        self.assertIn("   bz: shell sleep 47, of delegate a3", self.stop("Waiting.", background_tasks=[
            *watched, {"id": "bz", "type": "shell", "status": "running", "command": "sleep 47"}])["reason"])
        self.hook("SubagentStart", {"agent_id": "a3", "agent_type": "general-purpose"})
        self.assertIsNone(self.stop("Waiting.", background_tasks=[*watched, {"id": "bz", "type": "shell", "command": "sleep 47"}]))


def reap(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait()


FEATURE_V2 = """\
---
name: feature
description: x
---

# Feature

1. Clarify the requirements and run the basic checks. Close this step only when `../verify/scripts/verify.py base` and `../verify/scripts/verify.py plan --checks` pass. Mandatory: no skip-with-reason escape.
2. Ground in the code with the how skill (`../how/SKILL.md`) and check every check's premises. Close this step only when `../verify/scripts/verify.py premises` passes.
3. Design. Read the principles index (`../principles/SKILL.md`) and the principles you apply. Close this step only when `../verify/scripts/verify.py plan` and `../verify/scripts/verify.py premises --resolved` pass.
4. Lock. Close this step only when `../verify/scripts/verify.py lock` passes. Mandatory: no skip-with-reason escape.
5. Implement with one executor. Close this step only when `../verify/scripts/verify.py units` passes. Mandatory: no skip-with-reason escape.
6. Write the e2e scripts, in parallel with step 5, and dry-run each on the base. Close this step only when `../verify/scripts/verify.py scripts` passes. Skip this step with the reason only when the plan has no e2e or walk check.
7. Review the code. Starts after step 5. Close this step only when `../verify/scripts/verify.py review` passes. Mandatory: no skip-with-reason escape.
8. Prove with one full e2e run, then `verify.py report --write`. Starts after steps 6 and 7. Close this step only when `../verify/scripts/verify.py oracles` passes. Mandatory: no skip-with-reason escape.
9. Fix the e2e FAILs, classified first, then one rerun. Skip this step with the reason when nothing failed.
10. Close, then open the PR with the open-pr skill (`../open-pr/SKILL.md`). Close this step only when `../verify/scripts/verify.py report`, `../verify/scripts/verify.py spec` and `../verify/scripts/verify.py leftovers` pass. Mandatory: no skip-with-reason escape.
"""
FEATURE_V2_AFTER = {1: [], 2: [1], 3: [2], 4: [3], 5: [4], 6: [4], 7: [5], 8: [6, 7], 9: [8], 10: [9]}
FEATURE_V2_GATES = {1: {"base", "plan --checks"}, 2: {"premises"}, 3: {"plan", "premises --resolved"}, 4: {"lock"}, 5: {"units"}, 6: {"scripts"},
                    7: {"review"}, 8: {"oracles"}, 9: set(), 10: {"report", "spec", "leftovers"}}
REPO_FEATURE = ROOT / "skills" / "eng" / "feature" / "SKILL.md"


class FeatureFlow(unittest.TestCase):
    """`todo from feature` turns the ten-step flow into ordered, gated items: scripts open with the code, review waits on the code,
    and the one e2e run waits on both."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.env = {**os.environ, "AUTORUN_HOME": str(base / "autorun"), "GUARD_HOME": str(base / "guard"), "ORCHESTRATOR_HOME": str(base / "orchestrator")}
        for k in ("AUTORUN_RUN", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            self.env.pop(k, None)

    def items(self, roots):
        self.env["GUARD_SKILL_ROOTS"] = str(roots)
        r = subprocess.run([sys.executable, str(GUARD), "todo", "from", "feature", "--session", "claude:s1"], capture_output=True, text=True, env=self.env, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates
        todo = json.loads(pathlib.Path(self.env["GUARD_HOME"], "sessions", "claude-s1.json").read_text())["todo"]
        return {i["n"]: (i["after"], i["mandatory"], {" ".join(args) for _, _, args in gates.named(i["text"])}) for i in todo}

    def assert_flow(self, items, exact_gates):
        self.assertEqual(sorted(items), list(range(1, 11)))
        self.assertEqual({n: after for n, (after, _, _) in items.items()}, FEATURE_V2_AFTER)
        mandatory = {n for n, (_, m, _) in items.items() if m}
        self.assertLessEqual({1, 4, 5, 7, 8, 10}, mandatory)
        self.assertFalse({6, 9} & mandatory)
        for n, expected in FEATURE_V2_GATES.items():
            found = items[n][2]
            self.assertTrue(found == expected if exact_gates else expected <= found, (n, found))
            self.assertNotIn("report --write", found, n)

    def test_the_ten_step_flow_orders_its_items_with_their_gates(self):
        skill = pathlib.Path(self.tmp.name) / "skills" / "feature" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(FEATURE_V2)
        self.assert_flow(self.items(skill.parent.parent), exact_gates=True)
        verify = skill.parent.parent / "verify"
        (verify / "scripts").mkdir(parents=True)
        (verify / "SKILL.md").write_text("---\nname: verify\ndescription: x\n---\n")
        (verify / "scripts" / "verify.py").write_text("")
        r = subprocess.run([sys.executable, str(GUARD), "lint", str(skill)], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_the_repo_feature_skill_orders_its_items_with_their_gates(self):
        self.assert_flow(self.items(REPO_FEATURE.parent.parent), exact_gates=False)


class ShippedPlaybooks(unittest.TestCase):
    """The verification floor of each feature tier is held by gates on steps guard will not let be skipped."""

    def test_every_skill_in_this_repo_lints_without_errors(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import lint
        paths = sorted(ROOT.glob("skills/*/*/SKILL.md"))
        self.assertGreater(len(paths), 20)
        errors = {str(p.relative_to(ROOT)): lint.lint(p)[0] for p in paths}
        self.assertEqual({p: e for p, e in errors.items() if e}, {})

    def gated_mandatory_steps(self, skill):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        path = ROOT / "skills" / "eng" / skill / "SKILL.md"
        return {n: {" ".join(args) for _, _, args in gates.named(text)} for n, _, text, mandatory in skills.steps(path) if mandatory}

    def test_quick_feature_is_four_steps_with_no_gates_and_ends_on_the_pr(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        steps = skills.steps(ROOT / "skills" / "eng" / "quick-feature" / "SKILL.md")
        self.assertEqual([n for n, _, _, _ in steps], [1, 2, 3, 4])
        self.assertEqual([gates.named(text) for _, _, text, _ in steps], [[], [], [], []])
        self.assertIn("../open-pr/SKILL.md", steps[-1][2])

    def test_feature_tests_premises_locks_before_code_reviews_before_the_e2e_run_and_gates_the_pr(self):
        mandatory = self.gated_mandatory_steps("feature")
        self.assertEqual(mandatory, {
            1: {"base", "plan --checks"}, 2: {"premises"}, 3: {"plan", "premises --resolved"}, 4: {"lock"},
            5: {"units"}, 7: {"review"}, 8: {"oracles"}, 10: {"report", "spec", "leftovers"},
        })

    def test_e2e_scripts_are_written_beside_the_code_and_gated_on_their_base_dry_run(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        for skill, implement in (("feature", 5), ("bug-fix", 6)):
            steps = skills.steps(ROOT / "skills" / "eng" / skill / "SKILL.md")
            scripts = [(n, text) for n, _, text, _ in steps if {"scripts"} <= {" ".join(args) for _, _, args in gates.named(text)}]
            self.assertEqual([n for n, _ in scripts], [implement + 1], skill)
            self.assertIn(f"in parallel with step {implement}", scripts[0][1], skill)

    def test_the_step_that_opens_the_pr_is_the_one_the_final_run_gates(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        for skill, final in (("feature", {"report", "spec", "leftovers"}), ("bug-fix", {"report", "leftovers"})):
            steps = skills.steps(ROOT / "skills" / "eng" / skill / "SKILL.md")
            opening = [n for n, _, text, _ in steps if "../open-pr/SKILL.md" in text]
            last = steps[-1]
            self.assertEqual(opening, [last[0]], skill)
            self.assertTrue(last[3], skill)
            self.assertLessEqual(final, {" ".join(args) for _, _, args in gates.named(last[2])}, skill)

    def test_plan_feature_cannot_hand_back_without_every_phase_plan(self):
        mandatory = self.gated_mandatory_steps("plan-feature")
        self.assertEqual(mandatory, {5: {"phases"}})

FAKE_AGENT = """\
import json, os, subprocess, sys, time
spec = json.loads(sys.argv[1])
d = spec["dir"]

def publish(name, value):
    with open(os.path.join(d, name + ".tmp"), "w") as f:
        f.write(json.dumps(value))
    os.replace(os.path.join(d, name + ".tmp"), os.path.join(d, name))

jobs = {}
for name, command in spec["jobs"].items():
    out = open(os.path.join(d, name + ".out"), "w")
    jobs[name] = subprocess.Popen(["/bin/sh", "-c", command + "\\nexit $?"], stdout=out, stderr=subprocess.STDOUT,
                                  start_new_session=True).pid
publish("jobs.json", jobs)
while not os.path.exists(os.path.join(d, "go")):
    time.sleep(0.05)
for i, watch in enumerate(spec["watch"]):
    dog = subprocess.Popen(["/bin/sh", "-c", watch + "\\nexit $?"], stdout=open(os.path.join(d, f"watch{i}.out"), "w"),
                           stderr=subprocess.STDOUT)
    publish(f"watch{i}.pid", dog.pid)
    if i + 1 < len(spec["watch"]):
        time.sleep(1)
publish("exit.json", dog.wait())
time.sleep(600)
"""


class Watch(unittest.TestCase):
    """The watchdog on real processes: a fake agent (a process that is not a shell) runs each job in a shell of its own,
    with its output in a file, the way an agent harness runs background jobs, then starts the watchdog the same way."""

    SESSION = "claude:w1"

    @classmethod
    def scenario(cls, tmp, jobs, watch=None, ack=(), initial=1.5):
        d = pathlib.Path(tmp)
        env = {**os.environ, "GUARD_HOME": str(d / "guard")}
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD))} watch --session {cls.SESSION} --interval 0.2 --initial {initial}"
        (d / "agent.py").write_text(FAKE_AGENT)
        spec = {"dir": str(d), "jobs": jobs, "watch": watch or [command]}
        agent = subprocess.Popen([sys.executable, str(d / "agent.py"), json.dumps(spec)], env=env, start_new_session=True)
        pids = json.loads(wait_for(d / "jobs.json"))
        for name in ack:
            r = subprocess.run([sys.executable, str(GUARD), "watch", "--ack", str(pids[name]), "--session", cls.SESSION],
                               capture_output=True, text=True, env=env)
            assert r.returncode == 0, r.stdout + r.stderr
        (d / "go").touch()
        return agent, pids, env

    @staticmethod
    def end(agent, pids):
        for pid in [*pids.values(), agent.pid]:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)
        agent.wait()

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        jobs = {"silent": "sleep 30", "printer": "while :; do echo tick $(date +%s); sleep 0.2; done",
                "busy": f"{shlex.quote(sys.executable)} -c 'while True: pass'",
                "children": "i=0; while :; do i=$((i+1)); sleep 0.3$i; done", "idle": "sleep 31"}
        started = time.monotonic()
        agent, cls.pids, _ = cls.scenario(cls.tmp.name, jobs, ack=["idle"])
        try:
            cls.exit = json.loads(wait_for(pathlib.Path(cls.tmp.name) / "exit.json", 20))
            cls.elapsed = time.monotonic() - started
            cls.report = (pathlib.Path(cls.tmp.name) / "watch0.out").read_text()
        finally:
            cls.end(agent, cls.pids)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def reported(self):
        return {int(m) for m in re.findall(r"^pid (\d+) silent", self.report, re.M)}

    def test_a_silent_sleep_job_is_reported_and_the_watchdog_exits_zero(self):
        self.assertEqual(self.exit, 0, self.report)
        self.assertIn(self.pids["silent"], self.reported(), self.report)
        self.assertRegex(self.report, rf"(?m)^pid {self.pids['silent']} silent \d\.\ds \(asks after 1\.5s; no progress since the watchdog "
                                      rf"started\): sleep 30; last output: \(none\) \[.*silent\.out\]$")
        self.assertIn(f"acknowledge one meant to idle with `python3 {GUARD} watch --ack <pid> --session {self.SESSION}`", self.report)
        self.assertLess(self.elapsed, 15)

    def test_a_job_that_prints_steadily_is_not_reported(self):
        self.assertNotIn(self.pids["printer"], self.reported(), self.report)

    def test_a_silent_job_that_keeps_the_cpu_busy_is_not_reported(self):
        self.assertNotIn(self.pids["busy"], self.reported(), self.report)

    def test_a_job_whose_children_change_is_not_reported(self):
        self.assertNotIn(self.pids["children"], self.reported(), self.report)

    def test_an_acknowledged_process_is_not_reported(self):
        self.assertNotIn(self.pids["idle"], self.reported(), self.report)
        self.assertEqual(self.reported(), {self.pids["silent"]}, self.report)

    def test_a_second_watchdog_of_the_session_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD))} watch --session {self.SESSION} --interval 0.2 --initial 60"
            agent, pids, _ = self.scenario(tmp, {"silent": "sleep 30"}, watch=[first, first])
            try:
                self.assertEqual(json.loads(wait_for(pathlib.Path(tmp) / "exit.json", 20)), 3)
                self.assertRegex((pathlib.Path(tmp) / "watch1.out").read_text(),
                                 r"^guard watch: a watchdog already watches this session \(pid \d+\); nothing to start\.\n$")
                first_dog = json.loads((pathlib.Path(tmp) / "guard" / "sessions" / "claude-w1.watch.pid").read_text())["pid"]
                self.assertTrue(proc_alive(first_dog))
            finally:
                self.end(agent, pids)

    def test_the_watchdog_exits_when_its_agent_process_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, pids, _ = self.scenario(tmp, {"printer": "while :; do echo tick; sleep 0.2; done"}, initial=60)
            record = pathlib.Path(tmp) / "guard" / "sessions" / "claude-w1.watch.pid"
            try:
                dog = json.loads(wait_for(record))["pid"]
                self.assertTrue(proc_alive(dog))
                os.kill(agent.pid, signal.SIGKILL)
                agent.wait()
                deadline = time.monotonic() + 10
                while proc_alive(dog) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(proc_alive(dog))
                self.assertFalse(record.exists())
            finally:
                self.end(agent, pids)

    def test_the_threshold_grows_for_a_job_with_long_natural_gaps_and_never_drops_below_the_initial_value(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import procs, watch
        root = procs.Process(10, 1, 0.0, 0.0, "sh -c job")

        def job_with(beats):
            job, cpu = watch.Job(root, 0.0), 0.0
            for t in range(0, 200, 5):
                cpu += 1.0 if t in beats else 0.001
                job.observe({10: root._replace(cpu=cpu)}, [10], {}, float(t), watch.CPU_FLOOR)
            return job
        steady, slow = job_with(set(range(0, 200, 10))), job_with({0, 40, 80, 120})
        self.assertEqual((steady.events, steady.longest), (19, 10.0))
        self.assertEqual(steady.threshold(30, 3, 3), 30)
        self.assertEqual((slow.events, slow.longest), (3, 40.0))
        self.assertEqual(slow.threshold(30, 3, 3), 120)
        self.assertEqual(slow.threshold(30, 3, 4), 30, "too few events yet: the initial value")
        self.assertEqual(job_with(set()).events, 0, "CPU under the floor is no progress")

    def test_with_no_agent_process_above_it_the_watchdog_says_so_and_watches_nothing(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import procs, state, watch
        rows = {pid: procs.Process(pid, parent, 0.0, 0.0, command) for pid, parent, command in
                ((1, 0, "/sbin/launchd"), (5, 1, "-zsh"), (6, 5, "bash -c x"), (7, 6, "python3 guard.py watch"))}
        self.assertEqual(watch.find_agent(rows, me=7), (None, None))
        rows[5] = rows[5]._replace(command="node agent.js")
        self.assertEqual(watch.find_agent(rows, me=7), (rows[5], 6))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(state, "SESSIONS", pathlib.Path(tmp)), \
                mock.patch.object(procs, "table", return_value={**rows, 5: rows[5]._replace(command="-zsh")}), \
                mock.patch.object(os, "getpid", return_value=7), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.run("claude", "w2"), watch.NO_AGENT)
            self.assertIn("found no agent process above this one", out.getvalue())
            self.assertIn("no agent process", state.load("claude", "w2")["watch_unavailable"]["why"])


def wait_for(path, wait=10):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def proc_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return not subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip().startswith("Z")


if __name__ == "__main__":
    unittest.main()
