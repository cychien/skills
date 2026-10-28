"""Independent review by a different model, so the asking agent does not grade its own escalations."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from . import store

TIMEOUT = 120

QUESTION_PROMPT = """You review one escalation in an autonomous agent run. The user told the agent to work to completion without them and to stop only for calls where a wrong guess is costly: product direction that would send the whole output the wrong way, or anything irreversible. The agent decides everything else itself, and a needless stop wastes the user's time.

Run goal (the user's request): {goal}
Done condition: {done}
Question: {question}
Options: {options}
Agent's answer: {pick}
Agent's reasoning: {why}
Agent's classification: {kind}, confidence {confidence}
Earlier decisions in this run:
{decisions}

Choose "escalate" only when a wrong answer would waste most of the run's output, or when the user's preference genuinely cannot be inferred from the request and context. Otherwise choose "decide" and give the answer to proceed with, normally the agent's. A placeholder (TBD, TODO, a dummy value) standing in for content the user asked for is not an answer: if the real value cannot be inferred, escalate.

Reply with only a JSON object: {{"verdict": "decide" or "escalate", "pick": "<answer to proceed with>", "reason": "<one sentence>"}}"""

DONE_PROMPT = """You check whether an autonomous agent run is really finished before it reports back. The user handed over this request and stepped away; a premature "done" wastes their return.

The user's request: {goal}
Done condition the agent set: {done}
Agent's evidence: {evidence}
The user's answers and the decisions made during the run:
{decisions}
Changes made during the run:
{changes}

It is done only when the request itself is fulfilled. Not done: placeholders such as TBD or TODO standing in for requested content, requested parts skipped, tests weakened or deleted to pass, a done condition narrower than the request. needs_user is only for a gap that blocks the request and that only the user can fill; details the user left unspecified but a reasonable reader would accept are not gaps, and anything the user already answered is settled.

Reply with only a JSON object: {{"verdict": "done" or "not_done" or "needs_user", "reason": "<one sentence naming the gap, if any>", "question": "<for needs_user: the question to ask the user>"}}"""

IRREVERSIBLE_PROMPT = """You review one irreversible action in an autonomous agent run, on the user's behalf. The user stepped away and told the agent to finish without them. They asked that a stronger model settle these approvals instead of them, because they would only answer yes to a well-founded, bounded action, and that every other irreversible action still waits for them.

Run goal (the user's request): {goal}
Done condition: {done}
Action: {question}
Exact command, if any: {command}
Agent's reasoning: {why}
Earlier decisions in this run:
{decisions}

Approve only when the action clearly belongs to one of these classes and the agent's reasoning names the concrete evidence for it:
1. Read-only access to any system, production included, where the agent states how read-only is enforced (a read-only session setting read back, a read-only role, SELECT-only statements). No writes, no schema changes.
2. Deleting or overwriting resources this run itself created (throwaway test databases, temporary files, worktrees, branches it pushed), named exactly, with how the agent knows the run created them.
3. Changes to the user's own personal repositories, dotfiles, or tooling (not a company or shared repository), local and recoverable through version control, that the request asks for or that fix tooling blocking the run.
4. Rewriting or force-pushing a branch this run created and pushed, with --force-with-lease, to carry a change the user asked for.

Escalate everything else: writes or deletes on production or on shared data the run did not create, deploys, publishing, merging, messages or notifications to people, payments, secrets leaving the machine, changes to a shared default branch, and any case where the evidence for a class is missing, vague, or contradicted by earlier decisions.

Reply with only a JSON object: {{"verdict": "approve" or "escalate", "class": "<1-4, or none>", "reason": "<one sentence>"}}"""

PERMISSION_PROMPT = """You review one blocked action in an autonomous agent run. The user told the agent to work to completion without them. The agent's tool call needs permission. Allow it when it is a normal, recoverable step toward the goal: reading or listing files anywhere, editing or deleting files inside the project, running builds and tests, installing dependencies, local git operations. Leave it to the user when it is irreversible or hard to undo: destroying data the user may want, changing files outside the project, reading or sending secrets and credentials, production systems, or messages to other people.

Run goal (the user's request): {goal}
Working directory: {cwd}
Tool: {tool}
Input: {tool_input}

Reply with only a JSON object: {{"verdict": "allow" or "ask", "reason": "<one sentence>"}}"""


def _models_config(cwd):
    for base in (pathlib.Path(cwd or ".") / ".agents", pathlib.Path.home() / ".agents"):
        try:
            return json.loads((base / "orchestrator" / "models.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return None


def reviewers(cwd, host):
    """Planner entries with an installed CLI, other agents first so the reviewer differs from the asker."""
    config = _models_config(cwd) or {}
    entries = [e for e in config.get("roles", {}).get("planner", []) if e.get("agent") in ("claude", "codex") and shutil.which(e["agent"])]
    return sorted(entries, key=lambda e: e["agent"] == host)


def _call(entry, prompt):
    env = {**os.environ, "AUTORUN_DISABLE": "1"}
    with tempfile.TemporaryDirectory(prefix="autorun-review-") as work:
        if entry["agent"] == "claude":
            cmd = ["claude", "-p", "--model", entry["model"], "--tools", "", "--no-session-persistence", "--output-format", "text"]
            cmd += ["--effort", entry["effort"]] if entry.get("effort") else []
            out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=work, env=env)
            return out.stdout
        result = os.path.join(work, "result.txt")
        cmd = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-C", work, "-m", entry["model"], "-o", result]
        cmd += ["-c", f"model_reasoning_effort={entry['effort']}"] if entry.get("effort") else []
        subprocess.run(cmd + ["-"], input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=work, env=env)
        return pathlib.Path(result).read_text() if os.path.exists(result) else ""


def _parse(text):
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text or "", re.S))):
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    return None


def _custom(command, prompt):
    env = {**os.environ, "AUTORUN_DISABLE": "1"}
    return subprocess.run(command, shell=True, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, env=env).stdout


def review(prompt, cwd, valid_verdicts):
    """The first reviewer's parsed verdict, tagged with the model, or None when no reviewer could answer."""
    from . import policy

    if not policy.config().get("review", True) or os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1":
        return None
    custom = policy.config().get("review_command")
    if custom:
        try:
            verdict = _parse(_custom(custom, prompt))
        except (OSError, subprocess.TimeoutExpired):
            verdict = None
        if verdict and verdict.get("verdict") in valid_verdicts:
            verdict["model"] = "review_command"
            return verdict
        return None
    host, _, _ = store.host_agent(store.processes())
    for entry in reviewers(cwd, host):
        try:
            verdict = _parse(_call(entry, prompt))
        except (OSError, subprocess.TimeoutExpired):
            continue
        if verdict and verdict.get("verdict") in valid_verdicts:
            verdict["model"] = f"{entry['agent']}:{entry['model']}"
            return verdict
    return None


def review_question(run, question):
    data = run.data()
    decisions = "\n".join(f"- {d.get('question')} -> {d.get('pick')}" for d in run.decisions()[-10:]) or "(none)"
    prompt = QUESTION_PROMPT.format(
        goal=data.get("prompt") or "(unknown)", done=data.get("done") or "(not set)", decisions=decisions,
        question=question["question"], options="; ".join(question.get("options") or []) or "(open question)",
        pick=question.get("pick"), why=question.get("why") or "(none)", kind=question["kind"], confidence=question.get("confidence"),
    )
    return review(prompt, data.get("cwd"), {"decide", "escalate"})


def review_irreversible(run, question):
    data = run.data()
    decisions = "\n".join(f"- {d.get('question')} -> {d.get('pick')} ({d.get('basis')})" for d in run.decisions()[-10:]) or "(none)"
    prompt = IRREVERSIBLE_PROMPT.format(
        goal=data.get("prompt") or "(unknown)", done=data.get("done") or "(not set)", decisions=decisions,
        question=question["question"], command=question.get("command") or "(none)", why=question.get("why") or "(none)",
    )
    return review(prompt, data.get("cwd"), {"approve", "escalate"})


def review_permission(run, tool, tool_input):
    data = run.data()
    prompt = PERMISSION_PROMPT.format(goal=data.get("prompt") or "(unknown)", cwd=data.get("cwd"), tool=tool,
                                      tool_input=json.dumps(tool_input, ensure_ascii=False)[:4000])
    return review(prompt, data.get("cwd"), {"allow", "ask"})


def _git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def changes(cwd, base, limit=12000):
    if not cwd or not base:
        return "(not a git repository; no diff available)"
    out = _git(cwd, "diff", base)
    for name in _git(cwd, "ls-files", "--others", "--exclude-standard").splitlines():
        path = pathlib.Path(cwd) / name
        try:
            out += f"\n--- new file {name}\n{path.read_text(errors='replace')[:2000]}"
        except OSError:
            continue
    return (out[:limit] + "\n(truncated)") if len(out) > limit else (out or "(no changes)")


def review_done(run, evidence):
    data = run.data()
    decisions = "\n".join(f"- {d.get('question')} -> {d.get('pick')} ({d.get('basis')})" for d in run.decisions()[-20:]) or "(none)"
    prompt = DONE_PROMPT.format(goal=data.get("prompt") or "(unknown)", done=data.get("done"), evidence=evidence,
                                decisions=decisions, changes=changes(data.get("cwd"), data.get("base")))
    return review(prompt, data.get("cwd"), {"done", "not_done", "needs_user"})
