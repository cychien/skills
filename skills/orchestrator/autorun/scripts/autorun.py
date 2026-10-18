#!/usr/bin/env python3
"""Autonomous mode: keep an agent working until done, routing its questions instead of blocking on the user.

usage:
  autorun.py hook <agent> <event>        entry point for agent hooks (reads the hook payload on stdin)
  autorun.py start [--run ID] --done TEXT [--check CMD] [--goal TEXT]
  autorun.py ask [--run ID] --kind KIND --question TEXT [--option TEXT ...] --pick TEXT --why TEXT --confidence LEVEL [--command TEXT]
  autorun.py done [--run ID] --evidence TEXT
  autorun.py status | report | stop [--run ID]
  autorun.py install [--agent NAME ...] [--print] | uninstall [--agent NAME ...]
"""
import argparse
import json
import os
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autorun_lib import store  # noqa: E402


def hook(agent, native_event):
    if os.environ.get("AUTORUN_DISABLE"):
        return
    if agent == "claude" and os.environ.get("CURSOR_VERSION"):
        return  # Cursor also runs Claude Code's hooks; its own registration handles the event.
    raw = sys.stdin.read()
    guard = load_guard()
    autonomous = native_event in PROMPT_EVENTS or store.any_active() or store.any_undecided()
    if not autonomous and not guard:
        return
    from autorun_lib import adapters, hooks

    payload = json.loads(raw) if raw.strip() else {}
    event = adapters.parse(agent, native_event, payload)
    if not event:
        return
    decisions = ([hooks.handle(event)] if autonomous else []) + ([guard.handle(event)] if guard else [])
    decision = combine(decisions)
    out, code = adapters.render(agent, native_event, event, decision)
    if os.environ.get("AUTORUN_TRACE"):
        with open(store.HOME / "trace.jsonl", "a") as f:
            f.write(json.dumps({"at": store.now(), "agent": agent, "event": native_event, "session": event.session,
                                "agent_id": event.agent_id, "tool": event.tool, "action": decision[0],
                                "message": (decision[1] or "")[:200]}, ensure_ascii=False) + "\n")
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)


def load_guard():
    """The guard skill's rules, when guard is installed beside this skill. Both share this hook runtime."""
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for scripts in (os.path.join(here, "..", "..", "guard", "scripts"),
                    os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "..", "..", "guard", "scripts")):
        if os.path.isfile(os.path.join(scripts, "guard_lib", "rules.py")):
            sys.path.insert(0, os.path.abspath(scripts))
            from guard_lib import rules

            return rules
    return None


ORDER = ["deny", "refuse", "block", "allow", "retry", "context"]


def combine(decisions):
    """Merge rule sets' decisions: the strictest action wins, and every message for it reaches the agent."""
    acted = [d for d in decisions if d and d[0] != "pass"]
    if not acted:
        return ("pass", None)
    action = min((a for a, _ in acted), key=ORDER.index)
    messages = [m for a, m in acted if a == action and m]
    return action, "\n\n".join(messages) or None


PROMPT_EVENTS = {"UserPromptSubmit", "beforeSubmitPrompt", "userPromptSubmitted", "BeforeAgent"}


def cli_session(ref):
    """(agent, session) from --session AGENT:ID, else the agent CLI this command runs under."""
    if ref:
        agent, _, session = ref.partition(":")
        return agent, session
    agent, session, _ = store.host_agent(store.processes())
    return agent, session


def cmd_mode(args):
    agent, session = cli_session(args.session)
    store.clear_undecided(agent, session)
    print(f"Working interactively: {args.reason}. Ask the user when you genuinely need them.")


def cmd_start(args):
    table = store.processes()
    host, host_session, proc = store.host_agent(table)
    agent, session = cli_session(args.session) if args.session else (host, host_session)
    store.clear_undecided(agent, session)
    bound, role = store.lookup(agent, session)
    run = store.resolve_cli(args.run) if args.run else (bound or store.resolve_cli(None))
    if run:
        refuse_delegate(run, (agent, session), "sets the done condition")
    if not run:
        cwd = (proc and store.proc_cwd(proc["pid"])) or os.getcwd()
        run = store.create_run(agent, session, cwd, "start command", args.goal, proc)
        if not session:
            store.add_pending(run, cwd)
    with run.update() as d:
        if d.get("done") and (d["done"], d.get("check")) != (args.done, args.check):
            d.setdefault("done_history", []).append({"at": store.now(), "done": d["done"], "check": d.get("check")})
        d["done"], d["check"] = args.done, args.check
        if args.goal:
            d["prompt"] = args.goal
    print(f"Run {run.id} is active. Done condition: {args.done}" + (f" (verified by: {args.check})" if args.check else ""))
    print(f"Decisions log: {run.decisions_path}")


def cmd_ask(args):
    from autorun_lib import review

    run = _active_run(args.run)
    question = {"kind": args.kind, "question": args.question, "options": args.option or [], "pick": args.pick,
                "why": args.why, "confidence": args.confidence, "command": args.command}
    if args.kind in ("detail", "choice") and args.confidence == "high":
        run.record_decision({**question, "basis": f"high-confidence {args.kind}"})
        print(f"DECIDED: proceed with: {args.pick}\n{LOGGED.format(path=run.decisions_path)}")
        return
    if args.kind in ("detail", "choice", "direction"):
        verdict = review.review_question(run, question)
        if verdict and verdict["verdict"] == "decide":
            pick = verdict.get("pick") or args.pick
            run.record_decision({**question, "pick": pick, "basis": f"reviewer {verdict['model']}: {verdict.get('reason')}"})
            print(f"DECIDED by independent review ({verdict['model']}): proceed with: {pick}\n"
                  f"Reviewer: {verdict.get('reason')}\n{LOGGED.format(path=run.decisions_path)}")
            return
        if verdict:
            question["review"] = {"model": verdict["model"], "reason": verdict.get("reason")}
    escalate(run, question)


LOGGED = "Recorded in {path}. List it in your final report; do not stop for it."


def escalate(run, question, code=0):
    from autorun_lib import hooks

    gate = run.new_gate(question)
    hooks.notify(run, f"autorun needs you: {question['question']}")
    options = "".join(f"\n  - {o}" for o in question.get("options") or [])
    recommendation = f"\nRecommendation: {question['pick']} - {question.get('why')}" if question.get("pick") else ""
    print(f"""ESCALATED as gate {gate['id']}. Stop this line of work now.
- Main agent: ask the user now, in your question tool (it is unlocked for this) or in plain text, then end your turn. Include the options and your recommendation. Their reply is recorded automatically.
- Subagent or delegate: end your turn now. Start your final message with "AUTORUN-BLOCKED gate={gate['id']}", then the question, what is done, and what is left.
Question: {question['question']}{options}{recommendation}""")
    sys.exit(code)


def cmd_done(args):
    from autorun_lib import review

    run = _active_run(args.run)
    refuse_delegate(run, None, "declares the run done")
    data = run.data()
    if not data.get("done"):
        sys.exit("NOT DONE: no done condition is set. Set one with start first.")
    waiting = run.gates("open", "asked")
    if waiting:
        sys.exit(f"NOT DONE: gate(s) {', '.join(g['id'] for g in waiting)} are still waiting for the user.")
    if data.get("check"):
        result = subprocess.run(data["check"], shell=True, cwd=data.get("cwd") or None, capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr)[-3000:]
            sys.exit(f"NOT DONE: the check `{data['check']}` exited {result.returncode}. Keep working.\n{tail}")
    verdict = review.review_done(run, args.evidence)
    if verdict:
        if verdict["verdict"] == "not_done":
            sys.exit(f"NOT DONE according to independent review ({verdict['model']}): {verdict.get('reason')}\n"
                     "Keep working. If you disagree, fix the gap the reviewer names or explain it in --evidence.")
        if verdict["verdict"] == "needs_user":
            escalate(run, {"kind": "direction", "question": verdict.get("question") or verdict.get("reason"),
                           "why": verdict.get("reason"), "source": f"done review {verdict['model']}"}, code=1)
    with run.update() as d:
        d["evidence"] = args.evidence
    run.set_status("done")
    print(f"Run {run.id} is done. Autonomous mode is off.\n")
    print(report(run))


def cmd_status(args):
    run = store.resolve_cli(args.run)
    if not run:
        print("No autonomous run for this session.")
        return
    print(report(run))


def cmd_stop(args):
    run = _active_run(args.run)
    run.set_status("stopped")
    print(f"Run {run.id} stopped. Autonomous mode is off.")


def report(run):
    data = run.data()
    lines = [f"# Autonomous run {run.id} ({data.get('status')})", "",
             f"- Done condition: {data.get('done') or '(not set)'}" + (f", checked by `{data['check']}`" if data.get("check") else "")]
    for old in data.get("done_history", []):
        lines.append(f"- Replaced at {old['at']}: {old['done']}" + (f", checked by `{old['check']}`" if old.get("check") else ""))
    if data.get("evidence"):
        lines.append(f"- Evidence: {data['evidence']}")
    decisions = [d for d in run.decisions() if d.get("basis") != "user answer"]
    lines += ["", f"## Decisions made without the user ({len(decisions)})", ""]
    lines += [f"- {d.get('question')} -> {d.get('pick')} ({d.get('basis')})" for d in decisions] or ["- none"]
    gates = run.gates()
    lines += ["", f"## Escalations ({len(gates)})", ""]
    lines += [f"- {g['id']} [{g['status']}] {g['question']}" + (f" -> {g['answer']}" if g.get("answer") else "") for g in gates] or ["- none"]
    lines += ["", f"Files: {run.dir}"]
    return "\n".join(lines)


def refuse_delegate(run, caller, action):
    """Only the run's root session may change its done condition or finish it."""
    if caller is None:
        agent, session, _ = store.host_agent(store.processes())
        caller = (agent, session)
    bound, role = store.lookup(*caller) if caller[1] else (None, None)
    if bound and bound.id == run.id and role != "root":
        sys.exit(f"autorun: this session works inside run {run.id} as a {role}, and only its root {action}. "
                 "Finish your task and state in your final message what done means for it.")


def _active_run(run_id):
    run = store.resolve_cli(run_id)
    if not run or not run.active:
        sys.exit("autorun: no active run. Pass --run <id> from the hook message.")
    return run


def cmd_install(args):
    from autorun_lib import install

    install.install(os.path.abspath(sys.argv[0]), args.agent, args.print)


def cmd_uninstall(args):
    from autorun_lib import install

    install.uninstall(args.agent)


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "hook":
        try:
            hook(sys.argv[2], sys.argv[3])
        except SystemExit:
            raise
        except Exception:
            store.HOME.mkdir(parents=True, exist_ok=True)
            with open(store.HOME / "errors.log", "a") as f:
                f.write(f"{store.now()} hook {sys.argv[2]} {sys.argv[3]}\n{traceback.format_exc()}\n")
        return
    parser = argparse.ArgumentParser(description="Autonomous mode for coding agents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("--run")
    p.add_argument("--session")
    p.add_argument("--done", required=True)
    p.add_argument("--check")
    p.add_argument("--goal")
    p = sub.add_parser("mode")
    p.add_argument("mode", choices=["interactive"])
    p.add_argument("--reason", required=True)
    p.add_argument("--session")
    p = sub.add_parser("ask")
    p.add_argument("--run")
    p.add_argument("--kind", required=True, choices=["detail", "choice", "direction", "irreversible", "dead-end"])
    p.add_argument("--question", required=True)
    p.add_argument("--option", action="append")
    p.add_argument("--pick", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--confidence", required=True, choices=["high", "medium", "low"])
    p.add_argument("--command")
    p = sub.add_parser("done")
    p.add_argument("--run")
    p.add_argument("--evidence", required=True)
    for name in ("status", "report", "stop"):
        sub.add_parser(name).add_argument("--run")
    p = sub.add_parser("install")
    p.add_argument("--agent", action="append")
    p.add_argument("--print", action="store_true")
    sub.add_parser("uninstall").add_argument("--agent", action="append")
    args = parser.parse_args()
    {"start": cmd_start, "mode": cmd_mode, "ask": cmd_ask, "done": cmd_done, "status": cmd_status, "report": cmd_status,
     "stop": cmd_stop, "install": cmd_install, "uninstall": cmd_uninstall}[args.cmd](args)


if __name__ == "__main__":
    main()
