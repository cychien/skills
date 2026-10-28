"""Agent-neutral hook decisions. Each handler returns (action, message); adapters render it per agent."""
import os
import re
import time
import shlex
import subprocess
import sys
from dataclasses import dataclass, field

from . import policy, store

PASS = ("pass", None)
RUN_CONTROL = re.compile(r"\bpython3?\s+\S*autorun\.py['\"]?\s+(start|done|stop)\b")
MODE_DECISION = re.compile(r"autorun\.py['\"]?\s+(start|mode)\b|guard\.py['\"]?\s+todo\b")
PRE_TOOL_ALLOWS = {"claude"}  # agents whose pre-tool hook can grant a call; elsewhere the permission hook does
KINDS = "detail | choice | direction | irreversible | dead-end"


@dataclass
class Event:
    agent: str
    kind: str
    session: str = None
    cwd: str = None
    agent_id: str = None
    prompt: str = ""
    tool: str = None
    tool_input: dict = field(default_factory=dict)
    tool_response: object = None
    last_message: str = ""
    stop_hook_active: bool = False
    waiting_on_background: bool = False
    background_tasks: list = None
    can_inject: bool = True
    stop_status: str = None
    hold: dict = None


def cli():
    return f"python3 {shlex.quote(os.path.abspath(sys.argv[0]))}"


def ask_usage(run_id):
    return (
        f"{cli()} ask --run {run_id} --kind <{KINDS}> --question \"...\" "
        "[--option \"...\" ...] --pick \"<your answer>\" --why \"...\" --confidence <high|medium|low>"
    )


def root_briefing(run, trigger):
    return f"""Autonomous mode is on (run {run.id}, triggered by "{trigger}"). The user wants this finished without them. Load the `autorun` skill for the full protocol. In short:
1. First state a checkable done condition and record it:
   {cli()} start --run {run.id} --done "<condition>" [--check "<command that exits 0 only when done>"]
2. Never ask the user directly, in a question tool or in plain text. When you would ask, route it:
   {ask_usage(run.id)}
   It answers "proceed with X" or tells you to stop and ask.
3. When the done condition holds: {cli()} done --run {run.id} --evidence "<proof>"
Stopping before that is blocked."""


def delegate_briefing(run):
    return f"""You are working inside an autonomous run ({run.id}). The user is not available to you. Never ask them, in a question tool or in plain text; finish your task. When you would ask, route it:
   {ask_usage(run.id)}
If it says to escalate, end your turn with "AUTORUN-BLOCKED gate=<id>" followed by the question, what is done, and what is left."""


def mode_hint(skill, event):
    """The run-mode decision every skill invoked by /name gets, without carrying it. Tools stay gated until it is made."""
    session = f"--session {shlex.quote(f'{event.agent}:{event.session}')}"
    return (
        f"Decide the run mode before any other tool call, because the user invoked /{skill} and autonomous mode is off. "
        "Read their words. If they want this finished without them (they are stepping away, want it run until done, "
        "want to be called when it is done, or want no questions), start autonomous mode and load the `autorun` skill:\n"
        f"   {cli()} start {session} --done \"<condition>\" [--check \"<command>\"]\n"
        "Otherwise record that you will work interactively. A large task alone is not that signal:\n"
        f"   {cli()} mode interactive {session} --reason \"<why>\""
    )


def mode_gate(event):
    """Hold tool calls until the pending run-mode decision is made."""
    skill = store.undecided(event.agent, event.session)
    if not skill or event.agent_id:
        return PASS
    command = policy.shell_command(event.tool, event.tool_input) or ""
    if MODE_DECISION.search(command) or (event.tool or "").lower() == "skill" and (event.tool_input or {}).get("skill") == "autorun":
        return PASS
    return "deny", mode_hint(skill, event)


def ask_protocol(run, role):
    lead = "Autonomous mode is on, so questions do not go straight to the user." if role == "root" else delegate_briefing(run)
    return f"""{lead}
Classify the question and route it instead:
   {ask_usage(run.id)}
detail = a reversible execution detail. choice = picking among options. direction = product direction where a wrong call sends the whole output the wrong way. irreversible = cannot be undone. dead-end = you cannot make progress.
Always give your own best answer in --pick and an honest --confidence: only a high-confidence detail or choice proceeds without independent review. The command tells you to proceed or to escalate."""


def notify(run, text):
    command = policy.config().get("notify")
    if command:
        try:
            subprocess.Popen(command, shell=True, env={**os.environ, "AUTORUN_MESSAGE": text, "AUTORUN_RUN": run.id},
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass


def mark_briefed(run, session):
    with run.update() as d:
        if session not in d["briefed"]:
            d["briefed"].append(session)


def is_briefed(run, session):
    return session in run.data().get("briefed", [])


def handle(event):
    if event.kind == "prompt":
        return on_prompt(event)
    run, role = store.resolve(event.agent, event.session, event.cwd, event.agent_id)
    if not run:
        return mode_gate(event) if event.kind == "pre_tool" else PASS
    if event.kind == "pre_tool":
        return on_pre_tool(event, run, role)
    if event.kind == "post_tool":
        return on_post_tool(event, run, role)
    if event.kind == "stop":
        return on_stop(event, run, role)
    if event.kind == "subagent_stop":
        return on_stop(event, run, "subagent")
    if event.kind == "permission":
        return on_permission(event, run)
    if event.kind == "permission_denied":
        return on_permission_denied(event, run)
    return PASS


def on_prompt(event):
    run, role = store.resolve(event.agent, event.session, event.cwd, event.agent_id)
    prompt = event.prompt or ""
    if run and role == "root":
        if policy.exit_trigger(prompt):
            run.set_status("stopped")
            return "context", "Autonomous mode is off. Work normally and ask the user when you need to."
        if policy.is_system_prompt(prompt):
            return PASS
        waiting = run.gates("open", "asked")
        if waiting and policy.skill_command(prompt, event.cwd):
            ids = ", ".join(g["id"] for g in waiting)
            return "context", (f"This message runs a command and does not answer gate(s) {ids}; they still wait for the user. "
                               "Do what the command asks, then ask the gate's question again.")
        if waiting and policy.asks_back(prompt):
            ids = ", ".join(g["id"] for g in waiting)
            return "context", (f"This message asks something back and does not answer gate(s) {ids}; they still wait for the user. "
                               "Answer it, then ask the gate's question again.")
        if waiting:
            answer_gates(run, waiting, prompt)
            ids = ", ".join(g["id"] for g in waiting)
            return "context", (
                f"This message answers escalated gate(s) {ids}. Apply the answer and continue run {run.id} toward its done condition. "
                "If a gate came from a subagent, give the original task plus this answer to a fresh subagent."
            )
        done = run.data().get("done")
        return "context", f"Autonomous mode is still on (run {run.id}). Done condition: {done or 'not set yet, set it with start'}."
    if run:
        if is_briefed(run, event.session):
            return PASS
        mark_briefed(run, event.session)
        return "context", delegate_briefing(run)
    trigger = policy.enter_trigger(prompt)
    store.clear_undecided(event.agent, event.session)
    if not trigger:
        skill = policy.skill_command(prompt, event.cwd)
        if skill and not policy.is_system_prompt(prompt):
            store.mark_undecided(event.agent, event.session, skill)
            return ("context", mode_hint(skill, event)) if event.can_inject else PASS
        return PASS
    table = store.processes()
    run = store.create_run(event.agent, event.session, event.cwd, trigger, prompt, store.hook_agent_proc(table))
    if not event.can_inject:
        return PASS
    mark_briefed(run, event.session)
    return "context", root_briefing(run, trigger)


def answer_gates(run, gates, answer):
    for gate in gates:
        gate.update(status="answered", answer=answer, answered=store.now())
        run.save_gate(gate)
        run.record_decision({"question": gate["question"], "pick": answer, "kind": gate["kind"], "basis": "user answer", "gate": gate["id"]})
        if gate.get("command"):
            run.add_approval(gate["command"])


def on_pre_tool(event, run, role):
    with run.update() as d:
        d["activity"] = d.get("activity", 0) + 1
    if role != "root" and RUN_CONTROL.search(policy.shell_command(event.tool, event.tool_input) or ""):
        return "deny", (f"You are a {role} in autonomous run {run.id}, and only the root session may start, replace the done condition of, "
                        "finish, or stop it. Finish your task and state in your final message what done means for it.")
    subject = policy.subject(event.tool, event.tool_input)
    if run.has_approval(subject):
        if event.agent in PRE_TOOL_ALLOWS and run.take_approval(subject):
            return "allow", None
        return PASS
    if policy.is_question_tool(event.tool):
        waiting = run.gates("open")
        if role == "root" and waiting:
            for gate in waiting:
                gate["status"] = "asked"
                run.save_gate(gate)
            return PASS
        return "deny", ask_protocol(run, role)
    hit = policy.irreversible(event.tool, event.tool_input)
    if hit:
        label = hit[0]
        return "deny", (
            f"Autonomous mode blocks irreversible actions until the reviewer or the user approves them. This looks like {label}. "
            f"If it is needed, escalate it with --kind irreversible and --command set to exactly the text below; "
            f"once it is approved, the identical call goes through.\n   {ask_usage(run.id)} --command {shlex.quote(subject)}"
        )
    return PASS


def on_post_tool(event, run, role):
    notes = []
    if event.can_inject and not is_briefed(run, event.session):
        mark_briefed(run, event.session)
        notes.append(root_briefing(run, run.data().get("trigger")) if role == "root" else delegate_briefing(run))
    if role == "root":
        if policy.is_question_tool(event.tool):
            response = event.tool_response
            answer_gates(run, run.gates("asked"), response.get("answers", response) if isinstance(response, dict) else response)
        for gate in run.gates("open"):
            if not gate.get("surfaced"):
                gate["surfaced"] = True
                run.save_gate(gate)
                notes.append(
                    f"Gate {gate['id']} needs the user: {gate['question']} (recommended: {gate.get('pick')}). "
                    "If nobody has asked yet, stop other work, ask the user now, and end your turn."
                )
    return ("context", "\n\n".join(notes)) if notes and event.can_inject else PASS


def on_stop(event, run, role):
    if event.waiting_on_background:
        return PASS
    if event.hold:
        until = time.strftime("%H:%M", time.localtime(event.hold["until"]))
        return "note", f"autorun: run {run.id} paused on a timed hold until {until}: {event.hold.get('reason')}"
    if role != "root":
        if event.stop_hook_active or not policy.ends_with_question(event.last_message):
            return PASS
        return "block", (
            "You are in an autonomous run and ended on a question nobody will answer. "
            f"Decide it yourself or route it:\n   {ask_usage(run.id)}\nThen finish your task."
        )
    if run.gates("open", "asked"):
        notify(run, "autorun is waiting for your answer")
        return PASS
    data = run.data()
    with run.update() as d:
        idle = d.get("activity", 0) == d.get("activity_at_last_block", -1)
        d["idle_blocks"] = d.get("idle_blocks", 0) + 1 if idle else 0
        d["activity_at_last_block"] = d.get("activity", 0)
        idle_blocks = d["idle_blocks"]
    if idle_blocks >= policy.config()["stop_idle_limit"]:
        gate = run.new_gate({"kind": "dead-end", "question": "The run stopped making progress. How should it continue?",
                             "why": (event.last_message or "")[-1500:], "source": "stop hook"})
        notify(run, f"autorun stalled: gate {gate['id']}")
        return PASS
    if not data.get("done"):
        return "block", (
            f"Autonomous mode is on (run {run.id}) and no done condition is set. Set one, then keep working:\n"
            f"   {cli()} start --run {run.id} --done \"<condition>\" [--check \"<command>\"]"
        )
    lead = "You ended on a question. Do not wait for the user; decide it or route it with the ask command below. " if policy.ends_with_question(event.last_message) else ""
    return "block", (
        f"{lead}Run {run.id} is not done. Done condition: {data['done']}. Keep working toward it.\n"
        f"Questions: {ask_usage(run.id)}\n"
        f"Finished: {cli()} done --run {run.id} --evidence \"<proof>\""
    )


def on_permission(event, run):
    """A permission prompt mid-run: allow what a reviewer judges routine, show the prompt to the user otherwise."""
    if policy.is_question_tool(event.tool):
        return PASS  # its prompt is the question itself; granting it would dismiss the dialog unanswered
    subject = policy.subject(event.tool, event.tool_input)
    if run.take_approval(subject) or policy.is_own_cli(event.tool, event.tool_input):
        return "allow", None
    hit = policy.irreversible(event.tool, event.tool_input)
    if hit:
        notify(run, f"autorun needs your approval: {hit[0]}")
        return PASS
    if review_permission(event, run, subject):
        return "allow", None
    notify(run, f"autorun needs your approval: {subject}")
    return PASS


def on_permission_denied(event, run):
    """An auto-mode classifier denial: if a reviewer judges the call routine, approve it once and let the agent retry."""
    if policy.irreversible(event.tool, event.tool_input):
        return PASS
    subject = policy.subject(event.tool, event.tool_input)
    if policy.is_own_cli(event.tool, event.tool_input):
        run.add_approval(subject)
        return "retry", None
    if review_permission(event, run, subject):
        run.add_approval(subject)
        return "retry", None
    return PASS


def review_permission(event, run, subject):
    from . import review

    verdict = review.review_permission(run, event.tool, event.tool_input)
    allowed = bool(verdict) and verdict["verdict"] == "allow"
    run.record_decision({"question": f"permission: {subject}", "pick": "allow" if allowed else "left to the user", "kind": "permission",
                         "basis": f"reviewer {verdict['model']}: {verdict.get('reason')}" if verdict else "no reviewer available"})
    return allowed
