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
            4. Read every principle file it indexes.

            ## Notes

            1. Not a step.
            """)
        self.write_skill("open-pr", "---\nname: open-pr\ndescription: x\n---\n\n# Open a PR\n")
        self.write_skill("principles", "---\nname: principles\ndescription: x\n---\n\n# Principles\n")
        principles = self.skills / "principles" / "references" / "principles"
        principles.mkdir(parents=True)
        (principles / "fix-root-causes.md").write_text("# Fix Root Causes\n\nReproduce first.\n")
        (principles / "prove-it-works.md").write_text("# Prove It Works\n\nCheck the real thing.\n")
        self.env = {**os.environ, "AUTORUN_HOME": str(base / "autorun"), "GUARD_HOME": str(base / "guard"), "GUARD_SKILL_ROOTS": str(self.skills)}
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

    def test_a_slash_skill_holds_tools_until_the_todo_is_decided(self):
        hint = self.hook("UserPromptSubmit", {"prompt": "/demo build the thing"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("todo from demo", hint)
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(self.hook("PreToolUse", bash)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.hook("PreToolUse", {**bash, "agent_id": "a1"}))
        for allowed in (f"python3 {GUARD} todo none --reason x; ls", f"python3 {HOOK} mode interactive --reason x", f"cat {self.skills}/demo/SKILL.md"):
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
        self.todo("done", "1", "2", "--note", "did both")
        self.todo("skip", "3", "--reason", "nothing to report")
        self.assertIn("fix-root-causes.md", self.todo("done", "4", ok=False))
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cat {self.skills}/principles/references/principles/*.md"}})
        self.todo("done", "4")
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
        self.todo("done", "1")
        self.assertIn("Also skipped 4 item(s) from demo", self.todo("skip", "2", "--reason", "too small"))
        self.todo("done", "3")
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
        out = self.todo("done", "1", ok=False)
        self.assertIn("not ready: write the ready file", out)
        self.assertIn("stays open", out)
        self.assertIn("not installed", self.todo("done", "2", ok=False))
        pathlib.Path(self.tmp.name, "ready").write_text("")
        self.todo("done", "1")

    def test_principle_citations_need_a_read(self):
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "principles"}})
        out = self.stop("Applied Fix Root Causes: reproduced first.")
        self.assertIn("fix-root-causes.md", out["reason"])
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "principles/references/principles/fix-root-causes.md")}})
        self.assertIsNone(self.stop("Applied Fix Root Causes: reproduced first."))


    def test_shell_variables_in_read_paths_are_expanded(self):
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "principles"}})
        d = self.skills / "principles" / "references" / "principles"
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"D={d}; cat $D/fix-root-causes.md; echo ---; cat ${{D}}/prove-it-works.md"}})
        self.assertIsNone(self.stop("Applied Fix Root Causes, then Prove It Works."))

    def test_reads_inside_a_for_loop_count(self):
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "principles"}})
        d = self.skills / "principles" / "references" / "principles"
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f'for f in {d}/*.md; do echo "== $f"; cat "$f"; done'}})
        self.assertIsNone(self.stop("Applied Fix Root Causes, then Prove It Works."))

    def test_principle_rule_stays_off_without_eng_principles(self):
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "open-pr"}})
        self.assertIsNone(self.stop("I want to prove it works."))

    def test_pr_rules_apply_after_open_pr_is_used(self):
        bad = {"tool_name": "Bash", "tool_input": {"command": "gh pr create --title 'Add export.' --draft --body 'stuff'"}}
        self.assertIsNone(self.hook("PreToolUse", bad))
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "open-pr"}})
        out = self.hook("PreToolUse", bad)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        for fragment in ("Conventional Commits", "--draft", "## Scope"):
            self.assertIn(fragment, out["permissionDecisionReason"])
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

    def test_an_item_closes_without_reading_a_named_skill_that_did_not_run_and_records_why(self):
        self.write_skill("alpha", "---\nname: alpha\ndescription: x\n---\n")
        self.write_skill("beta", "---\nname: beta\ndescription: x\n---\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Settle the design. Run alpha (`../alpha/SKILL.md`) when it spans modules, and beta (`../beta/SKILL.md`) when a prototype helps.\n2. Wrap up.\n")
        self.todo("from", "flow")
        self.assertIn("--not-run", self.todo("done", "1", ok=False))
        self.assertIn("--reason", self.todo("done", "1", "--not-run", "alpha", ok=False))
        self.assertIn("../beta/SKILL.md", self.todo("done", "1", "--not-run", "alpha", "--reason", "single module", ok=False))
        self.assertIn("../gamma/SKILL.md", self.todo("done", "1", "--not-run", "gamma", "--reason", "x", ok=False))
        out = self.todo("done", "1", "--not-run", "alpha", "--not-run", "beta", "--reason", "single module, no premise to test")
        self.assertIn("not run: alpha, beta - single module, no premise to test", out)
        self.assertIn("not run: alpha, beta", self.todo("list"))

    def test_not_run_accepts_the_skill_path_the_refusal_prints(self):
        self.write_skill("alpha", "---\nname: alpha\ndescription: x\n---\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Run alpha (`../alpha/SKILL.md`) when it spans modules.\n")
        self.todo("from", "flow")
        out = self.todo("done", "1", "--not-run", "../alpha/SKILL.md", "--reason", "single module")
        self.assertIn("not run: alpha - single module", out)

    def test_an_item_naming_a_skill_needs_it_read_and_the_reply_skill_is_enforced(self):
        self.write_skill("reply", "---\nname: reply\ndescription: x\n---\n\n# Writing the reply\n")
        self.write_skill("helper", "---\nname: helper\ndescription: x\n---\n\n# Helper\n")
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Use the helper skill (`../helper/SKILL.md`).\n\n**Reply:** per the reply skill (`../reply/SKILL.md`).\n")
        self.todo("from", "flow")
        self.assertIn("../helper/SKILL.md", self.todo("done", "1", ok=False))
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "helper" / "SKILL.md")}})
        self.todo("done", "1")
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
        self.todo("done", "1")
        self.hook("PostToolUse", {"tool_name": "Skill", "tool_input": {"skill": "demo"}})
        self.assertEqual(self.hook("PreToolUse", bash)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.todo("none", "--reason", "demo is only a reference here")
        self.assertIsNone(self.hook("PreToolUse", bash))

    def test_a_step_continued_after_a_blank_line_keeps_its_citations(self):
        self.write_skill("flow", "---\nname: flow\ndescription: x\n---\n\n1. Settle the design.\n   - Case A: write a note.\n\n   When it reaches past the diff, run the demo skill (`../demo/SKILL.md`).\n2. Wrap up.\n")
        self.todo("from", "flow")
        self.assertIn("../demo/SKILL.md", self.todo("done", "1", ok=False))
        self.hook("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": str(self.skills / "demo" / "SKILL.md")}})
        self.assertIsNone(self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.todo("done", "1")

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
        self.todo("done", "1")
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
        principles = self.skills / "principles" / "SKILL.md"
        for command in [f"python3 - <<'EOF'\nopen('{principles}').read()\nEOF", f"grep -n x {principles}", f"sed -i '' 's/a/b/' {principles}"]:
            self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertIsNone(self.stop("Applied Fix Root Causes."))
        self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cd /tmp && sed -n '1,80p' {principles}"}})
        self.assertEqual(self.stop("Applied Fix Root Causes.")["decision"], "block")

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
        self.assertIn("todo done <n> --session claude:s1 --agent owner-1", held["reason"])
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


class ShippedPlaybooks(unittest.TestCase):
    """The verification floor of each feature tier is held by gates on steps guard will not let be skipped."""

    def gated_mandatory_steps(self, skill):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        path = ROOT / "skills" / "eng" / skill / "SKILL.md"
        return {n: {" ".join(args) for _, _, args in gates.named(text)} for n, _, text, mandatory in skills.steps(path) if mandatory}

    def test_quick_feature_freezes_the_plan_before_code_delegates_and_cannot_skip_verification(self):
        mandatory = self.gated_mandatory_steps("quick-feature")
        self.assertEqual(mandatory, {1: {"plan", "lock"}, 3: {"driver"}, 4: set(), 6: {"oracles"}, 7: set(), 8: {"rerun", "report", "leftovers"}})

    def test_feature_locks_the_plan_before_code_and_gates_the_pr_on_the_final_rerun_and_report(self):
        mandatory = self.gated_mandatory_steps("feature")
        self.assertEqual(mandatory, {1: {"plan"}, 2: set(), 5: {"lock"}, 7: {"driver"}, 8: {"units"}, 10: {"oracles"},
                                     12: set(), 13: set(), 14: {"rerun", "report", "leftovers"}})

    def test_the_step_that_opens_the_pr_is_the_one_the_final_run_gates(self):
        sys.path.insert(0, str(GUARD.parent))
        self.addCleanup(sys.path.remove, str(GUARD.parent))
        from guard_lib import gates, skills
        for skill in ("feature", "quick-feature"):
            steps = skills.steps(ROOT / "skills" / "eng" / skill / "SKILL.md")
            opening = [n for n, _, text, _ in steps if "../open-pr/SKILL.md" in text]
            last = steps[-1]
            self.assertEqual(opening, [last[0]], skill)
            self.assertTrue(last[3], skill)
            self.assertLessEqual({"rerun", "report"}, {" ".join(args) for _, _, args in gates.named(last[2])}, skill)

    def test_plan_feature_cannot_hand_back_without_every_phase_plan(self):
        mandatory = self.gated_mandatory_steps("plan-feature")
        self.assertEqual(mandatory, {2: set(), 6: {"phases"}})


if __name__ == "__main__":
    unittest.main()
