#!/usr/bin/env python3
"""Autonomous mode: keep an agent working until done, routing its questions instead of blocking on the user.

usage:
  autorun.py hook <agent> <event>        entry point for agent hooks (reads the hook payload on stdin)
  autorun.py start [--run ID] --done TEXT [--check CMD] [--goal TEXT] [--cwd DIR] [--narrows GATE] [--backlog PATH]
  autorun.py ask [--run ID] --kind KIND --question TEXT [--option TEXT ...] --pick TEXT --why TEXT --confidence LEVEL [--command TEXT] [--backlog PATH]
  autorun.py done [--run ID] --evidence TEXT
  autorun.py status | report | stop [--run ID]
  autorun.py install [--agent NAME ...] [--print] | uninstall [--agent NAME ...]
"""
import argparse
import json
import os
import pathlib
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
    if guard and event.kind in ("stop", "subagent_stop"):
        event.hold = guard.active_hold(event)
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


ORDER = ["deny", "refuse", "block", "allow", "retry", "context", "note"]


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
        refuse_delegate(run, (agent, session, proc), "sets the done condition")
    cwd = os.path.realpath(args.cwd or os.getcwd())
    if not os.path.isdir(cwd):
        sys.exit(f"autorun: --cwd {args.cwd}: no such directory")
    if not run:
        run = store.create_run(agent, session, cwd, "start command", args.goal, proc)
        if not session:
            store.add_pending(run, (proc and store.proc_cwd(proc["pid"])) or cwd)
    narrowed_by = narrowing_gate(run, args)
    with run.update() as d:
        if d.get("done") and (d["done"], d.get("check")) != (args.done, args.check):
            d.setdefault("done_history", []).append({"at": store.now(), "done": d["done"], "check": d.get("check"),
                                                     **({"narrowed_by": narrowed_by} if narrowed_by else {})})
        d["done"], d["check"] = args.done, args.check
        if d.get("cwd") != cwd:
            d["cwd"] = cwd
            if not store.has_commit(cwd, d.get("base")):
                d["base"] = store.git_head(cwd)
        if args.goal:
            d["prompt"] = args.goal
        if args.backlog:
            d["backlog"] = os.path.realpath(os.path.expanduser(args.backlog))
    print(f"Run {run.id} is active. Done condition: {args.done}" + (f" (verified by: {args.check})" if args.check else ""))
    print(f"Working directory: {cwd}")
    print(f"Decisions log: {run.decisions_path}")


def segments(check):
    return {part.strip() for part in (check or "").split("&&") if part.strip()}


def extends(old, new):
    """Whether the replacement keeps everything the current done condition demands and only adds to it."""
    def squash(text):
        return " ".join((text or "").lower().split())
    return squash(old["done"]) in squash(new["done"]) and segments(old.get("check")) <= segments(new.get("check"))


def narrowing_gate(run, args):
    """The user gate that authorizes replacing the done condition with one that is not a pure extension, else None."""
    data = run.data()
    current = {"done": data.get("done"), "check": data.get("check")}
    if not current["done"] or extends(current, {"done": args.done, "check": args.check}):
        return None
    if not args.narrows:
        sys.exit(f"""autorun: the new done condition narrows run {run.id}: it drops or rewrites part of the current one ("{current['done']}"{f", checked by `{current['check']}`" if current['check'] else ""}). Shipping less than was asked is the user's call, so an agent cannot decide it, not even through a direction verdict.
1. Ask: {ask_command(run.id)} --kind irreversible --question "Drop <what> from the done condition?" --pick "<your answer>" --why "..." --confidence <level>
2. Once the user has answered, repeat this start with --narrows <gate id>.
To only add conditions, keep the current text and the current check and append to them.""")
    gate = next((g for g in run.gates() if g["id"] == args.narrows), None)
    if not gate:
        sys.exit(f"autorun: --narrows {args.narrows}: no gate with that id in run {run.id}.")
    if gate["kind"] != "irreversible":
        sys.exit(f"autorun: gate {gate['id']} is a {gate['kind']} gate. Narrowing the done condition needs an irreversible gate the user answered.")
    if gate["status"] != "answered":
        sys.exit(f"autorun: gate {gate['id']} is not answered yet ({gate['status']}). Wait for the user's answer.")
    if any(h.get("narrowed_by") == gate["id"] for h in data.get("done_history", [])):
        sys.exit(f"autorun: gate {gate['id']} was already used to narrow the done condition. Ask again for another narrowing.")
    return gate["id"]


def ask_command(run_id):
    return f"python3 {os.path.abspath(sys.argv[0])} ask --run {run_id}"


def cmd_ask(args):
    from autorun_lib import review

    from autorun_lib import policy

    run = _active_run(args.run)
    if args.kind == "dead-end" and policy.about_usage_limit(args.question, args.pick, args.why):
        sys.exit(NOT_A_GATE)
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
        backlog = args.backlog or run.data().get("backlog")
        if backlog:
            defer(run, question, backlog)
            return
    escalate(run, question)


def defer(run, question, backlog):
    path = pathlib.Path(backlog).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else "# Backlog\n"
    if DEFERRED_SECTION not in text:
        text = text.rstrip("\n") + f"\n\n{DEFERRED_SECTION}\n"
    review = question.get("review")
    fields = [f"- Source: autonomous run {run.id}, {store.now()[:10]}",
              *([f"- Options: {'; '.join(question['options'])}"] if question.get("options") else []),
              f"- Taken: {question['pick']}",
              f"- Why: {question['why']}",
              *([f"- Reviewer: {review['model']}: {review.get('reason')}"] if review else []),
              "- Revisit: confirm what was taken, or say what to change; the run did not wait for an answer."]
    path.write_text(text.rstrip("\n") + f"\n\n### {question['question']}\n\n" + "\n".join(fields) + "\n")
    run.record_decision({**question, "basis": f"deferred to the backlog at {path}"})
    print(f"DEFERRED: proceed with: {question['pick']}\nThe question is in the backlog at {path}, so the user can revisit it. "
          f"{LOGGED.format(path=run.decisions_path)}")


DEFERRED_SECTION = "## Deferred by autonomous runs"


LOGGED = "Recorded in {path}. List it in your final report; do not stop for it."
NOT_A_GATE = ("NOT A GATE: a usage limit resets on its own, so it is neither a dead end nor a question for the user. "
              "Do not ask. Finish the piece in hand and end your turn with a status line, not a question: "
              "Claude Code waits and continues the task after the reset, while a pending question holds the session until the user answers. "
              "After the reset, resume a subagent that stopped on the limit with SendMessage. Salvo runs wait for the reset and resume on their own.")


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
    refuse_delegate(run, None, "stops the run")
    run.set_status("stopped")
    print(f"Run {run.id} stopped. Autonomous mode is off.")


def report(run):
    data = run.data()
    lines = [f"# Autonomous run {run.id} ({data.get('status')})", "",
             f"- Done condition: {data.get('done') or '(not set)'}" + (f", checked by `{data['check']}`" if data.get("check") else "")]
    for old in data.get("done_history", []):
        lines.append(f"- Replaced at {old['at']}: {old['done']}" + (f", checked by `{old['check']}`" if old.get("check") else "")
                     + (f" (narrowed with the user's answer to gate {old['narrowed_by']})" if old.get("narrowed_by") else ""))
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
        caller = store.host_agent(store.processes())
    agent, session, proc = caller
    bound, role = store.lookup(agent, session)
    if bound and bound.id == run.id:
        if role == "root":
            return
        who = f"works inside run {run.id} as a {role}"
    elif os.environ.get("AUTORUN_RUN"):
        who = f"was started by run {os.environ['AUTORUN_RUN']}"
    elif proc and not store.is_registered(run, proc):
        who = f"is an agent process of its own that run {run.id} never registered as its root"
    else:
        return
    sys.exit(f"autorun: this session {who}, and only its root {action}. "
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
    p.add_argument("--cwd")
    p.add_argument("--narrows", metavar="GATE")
    p.add_argument("--backlog", metavar="PATH")
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
    p.add_argument("--backlog", metavar="PATH")
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
