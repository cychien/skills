"""Guard's hard rules. Each hook event returns (action, message); the shared hook runtime renders it per agent."""
import glob
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time

from . import pr, skills, state, verifiers

PASS = ("pass", None)
DECISION = re.compile(r"guard\.py['\"]?\s+todo\b|autorun\.py['\"]?\s+(start|mode)\b")
SLASH = re.compile(r"^\s*/([a-z0-9][a-z0-9-]*)\b")
PRINCIPLE_FILE = re.compile(r"references/principles/([a-z0-9-]+)\.md$")
SKILL_FILE = re.compile(r"(?:^|/)([a-z0-9][a-z0-9-]*)/SKILL\.md$")
READ_TOOLS = {"read", "read_file", "view", "readfile"}
READERS = {"cat", "head", "tail", "less", "more", "bat", "nl", "sed"}
SHELL_SPLIT = re.compile(r"&&|\|\||;|\||\n")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
FOR_LOOP = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([^;]+?)\s*;\s*do\b")
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
SALVO_RUN = re.compile(r"salvo\.py['\"]?\s+run\b")
FILL = re.compile(r"<[^<>\n]* [^<>\n]*>")
STDIN_FILE = re.compile(r"<\s*([^\s<>|;&]+)")
DETACHED = re.compile(r"\bnohup\b|(?<![&|<>])&(?![&>])")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\b", re.S)
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
SALVO_DETACHED = ("salvo runs every model and blocks until all finish. Detaching it with nohup or a trailing & hides it from the "
                  "harness, so nothing notifies you when it ends. Run the same command without nohup or & in a background tool call "
                  "(Claude Code: Bash with run_in_background) and wait for its completion notification.")


POLL_LOOP = re.compile(r"\b(while|until|for)\b")
POLL_SLEEP = re.compile(r"\bsleep\b|select\s*\(\s*undef|Start-Sleep")
POLL_TARGET = re.compile(r"/tasks/[\w.-]+\.output|stop_reason|end_turn")
POLLING_DENIED = ("Do not wait for a subagent by polling. A subagent finishes with a SubagentHandback tool call (stop_reason tool_use), "
                  "so a loop that greps for end_turn never matches and runs to its cap. ")
POLLING_INTERACTIVE = "Its hand-back arrives on its own as a message, so end the turn or do other work."
POLLING_HEADLESS = ("This session is non-interactive, so ending the turn ends the process and kills the subagent. Run the subagent in the "
                    "foreground (not in the background), so its hand-back is the tool result.")
SPAWN_TOOLS = {"agent", "task"}
LEFTOVERS_TIMEOUT = 30
LEFTOVERS_DENIED = ("Processes from earlier delegates or tasks are still running. Spawning another agent on top of them hides which one "
                    "caused any later problem and burns the machine. Stop them, then spawn again.\n")


def expand(text, variables):
    """Substitute $NAME from assignments earlier in the same command, then from the environment."""
    return VARIABLE.sub(lambda m: variables.get(m.group(1), os.environ.get(m.group(1), m.group(0))), text)
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
QUESTION_END = re.compile(r"[?？]\s*\**\s*$")
IDLE_LIMIT = 3
HEADLESS = re.compile(r"(^|/)claude\b.*\s(-p|--print)\b|(^|/)codex\s+exec\b")


def headless():
    """Whether this hook runs under a non-interactive agent, where ending the turn ends the process and its background work."""
    if os.environ.get("GUARD_HEADLESS"):
        return os.environ["GUARD_HEADLESS"] == "1"
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    pid, seen = os.getppid(), set()
    while pid in table and pid not in seen and pid > 1:
        seen.add(pid)
        if HEADLESS.search(table[pid][1]):
            return True
        pid = table[pid][0]
    return False


def cli(session_ref):
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
    return f"python3 {shlex.quote(script)}", f"--session {shlex.quote(session_ref)}"


def session_ref(event):
    return f"{event.agent}:{event.session}"


def handle(event):
    if not event.session:
        return PASS
    if event.kind == "prompt":
        return on_prompt(event)
    if event.kind == "pre_tool":
        return on_pre_tool(event)
    if event.kind == "post_tool":
        return on_post_tool(event)
    if event.kind == "stop" and not event.agent_id:
        return on_stop(event)
    return PASS


def todo_hint(skill, event):
    cmd, sess = cli(session_ref(event))
    return f"""Decide the todo list before any other tool call, because the {skill} skill you are about to follow has steps. Copy them in verbatim, then add task-specific items:
   {cmd} todo from {skill} {sess}
   {cmd} todo add "<item>" ["<item>" ...] {sess}
If this task needs no list, say why:
   {cmd} todo none {sess} --reason "<why>"
Resolve each item as you go with `todo done <n> [<n> ...]` or `todo skip <n> [<n> ...] --reason "..."`. The turn cannot end while an item is open, except to ask the user a question: mark the items that wait on the answer with `todo wait <n> [<n> ...] --reason "..."` first."""


def on_prompt(event):
    """A new prompt resets which skills still await a todo decision; a /skill with steps asks for one now."""
    prompt = event.prompt or ""
    m = SLASH.match(prompt)
    path = skills.find(m.group(1), event.cwd) if m else None
    if not path and not state.exists(event.agent, event.session):
        return PASS
    with state.update(event.agent, event.session) as data:
        data["todo_undecided"], data["todo_decided"] = None, []
        state.reopen_waiting(data)
        if path and m.group(1) not in data["skills"]:
            data["skills"].append(m.group(1))
        ask = bool(path) and needs_decision(data, m.group(1), path)
        if ask:
            data["todo_undecided"] = m.group(1)
    return ("context", todo_hint(m.group(1), event)) if ask and event.can_inject else PASS


def needs_decision(data, skill, path):
    """A skill with steps needs a todo decision, unless this prompt already made one for it or its steps are listed."""
    if skill in data.get("todo_decided", []) or any(i["source"] == skill for i in state.unresolved(data)):
        return False
    return bool(skills.steps(path))


def files_read(event):
    """Paths the call read: the read tool's file, or file arguments of plain read commands. Edits and searches do not count."""
    inp = event.tool_input if isinstance(event.tool_input, dict) else {}
    if event.tool and event.tool.lower() in READ_TOOLS:
        return [v for k in ("file_path", "path", "absolute_path", "target_file") if isinstance(v := inp.get(k), str)]
    command = shell_command(event)
    if not command or "<<" in command:
        return []
    paths, variables = [], {}
    for name, items in FOR_LOOP.findall(command):
        variables[name] = items.strip()
    for segment in SHELL_SPLIT.split(command):
        segment = re.sub(r"^\s*(do|then)\s+", "", segment)
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        while tokens and (tokens[0] == "cd" or ASSIGNMENT.match(tokens[0])):
            if tokens[0] == "cd":
                tokens = tokens[2:]
                continue
            name, _, value = tokens.pop(0).partition("=")
            variables[name] = expand(value, variables)
        tokens = [w for t in tokens for w in expand(t, variables).split()]
        if not tokens or os.path.basename(tokens[0]) not in READERS:
            continue
        if tokens[0].endswith("sed") and "-n" not in tokens:
            continue
        for arg in tokens[1:]:
            if arg.startswith("-") or (tokens[0].endswith("sed") and re.fullmatch(r"[\d,$]*p", arg)):
                continue
            expanded = glob.glob(os.path.join(event.cwd or "", os.path.expanduser(arg))) if "*" in arg else []
            paths += expanded or [arg]
    return paths


def sweep_leftovers(event, *flags):
    """Run the verify skill's leftovers sweep. Returns (exit code, output), or None when it cannot run, which is logged and never blocks the agent."""
    found = skills.find("verify", event.cwd)
    script = found.parent / "scripts" / "verify.py" if found else None
    if not script or not script.is_file():
        return skipped("the verify skill is not installed")
    try:
        r = subprocess.run([sys.executable, str(script), "leftovers", *flags], cwd=event.cwd, capture_output=True, text=True, timeout=LEFTOVERS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return skipped(f"{type(e).__name__}: {e}")
    output = (r.stdout + r.stderr).strip()
    if r.returncode not in (0, 1):
        return skipped(f"the sweep exited {r.returncode}: {output[-300:]}")
    return r.returncode, output


def skipped(why):
    try:
        state.HOME.mkdir(parents=True, exist_ok=True)
        with open(state.HOME / "errors.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} leftovers sweep skipped: {why}\n")
    except OSError:
        pass
    return None


def on_post_tool(event):
    if (event.tool or "").lower() == "taskstop":
        swept = sweep_leftovers(event, "--kill")
        return ("context", swept[1]) if swept and swept[1] and event.can_inject else PASS
    loaded, read, invoked = [], [], set()
    if event.tool and event.tool.lower() == "skill" and isinstance(event.tool_input, dict) and event.tool_input.get("skill"):
        loaded.append(event.tool_input["skill"].split(":")[-1])
        invoked.add(loaded[-1])
    for path in files_read(event):
        if (m := SKILL_FILE.search(path)) and skills.followed(path, event.cwd):
            loaded.append(m.group(1))
        if m := PRINCIPLE_FILE.search(path):
            read.append(m.group(1))
    if not loaded and not read and not state.exists(event.agent, event.session):
        return PASS
    with state.update(event.agent, event.session) as data:
        data["activity"] = data.get("activity", 0) + 1
        for name in loaded:
            if name not in data["skills"]:
                data["skills"].append(name)
            path = skills.find(name, event.cwd)
            cited = name not in invoked and any(name in skills.SKILL_REF.findall(i["text"]) for i in state.open_items(data))
            if not data.get("todo_undecided") and not event.agent_id and not cited and path and needs_decision(data, name, path):
                data["todo_undecided"] = name
        for name in read:
            if name not in data["principles_read"]:
                data["principles_read"].append(name)
    return PASS


def on_pre_tool(event):
    command = shell_command(event) or ""
    if detached_salvo(command):
        return "deny", SALVO_DETACHED
    prompt = outgoing_prompt(event, command)
    unfilled = unfilled_template(prompt, event.cwd)
    if unfilled:
        return "deny", ("This subagent prompt comes from a skill's prompt template but still holds unfilled placeholders: "
                        + ", ".join(unfilled) + ". Fill each one, then send it again.")
    spent = verifiers.over_budget(prompt)
    if spent:
        return "deny", spent
    if (event.tool or "").lower() in SPAWN_TOOLS:
        swept = sweep_leftovers(event)
        if swept and swept[0] == 1:
            return "deny", LEFTOVERS_DENIED + swept[1]
        if not event.agent_id:
            with state.update(event.agent, event.session) as data:
                data["spawned"] = data.get("spawned", 0) + 1
    if not state.exists(event.agent, event.session):
        return PASS
    data = state.load(event.agent, event.session)
    if data.get("spawned") and not event.agent_id and polls_for_subagent(command):
        return "deny", POLLING_DENIED + (POLLING_HEADLESS if headless() else POLLING_INTERACTIVE)
    skill = data.get("todo_undecided")
    if skill and not event.agent_id and not DECISION.search(command) and not reads_a_skill(event):
        return "deny", todo_hint(skill, event)
    if "gh" not in command or "open-pr" not in data["skills"]:
        return PASS
    found = pr.problems(command, event.cwd)
    if not found:
        return PASS
    return "deny", "The open-pr skill's PR rules reject this command:\n- " + "\n- ".join(found) + "\nFix the command and run it again."


def polls_for_subagent(command):
    return all(p.search(command) for p in (POLL_LOOP, POLL_SLEEP, POLL_TARGET))


def outgoing_prompt(event, command):
    inp = event.tool_input if isinstance(event.tool_input, dict) else {}
    if isinstance(inp.get("prompt"), str):
        return inp["prompt"]
    if not SALVO_RUN.search(command):
        return ""
    found = STDIN_FILE.search(HEREDOC.sub("", command))
    if not found:
        return ""
    path = os.path.join(event.cwd or ".", os.path.expanduser(found.group(1)))
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def prompt_templates(cwd):
    found = []
    for root in skills.roots(cwd):
        for path in glob.glob(str(root / "*" / "references" / "*-prompt.md")):
            try:
                text = pathlib.Path(path).read_text(encoding="utf-8")
            except OSError:
                continue
            blocks = text.split("```")
            if len(blocks) < 3:
                continue
            block = blocks[1].split("\n", 1)[-1]
            marker = next((line.strip() for line in block.splitlines() if line.strip()), "")
            fills = sorted(set(FILL.findall(block)))
            if marker and fills:
                found.append((marker, fills))
    return found


def unfilled_template(text, cwd):
    if not text:
        return []
    left = []
    for marker, fills in prompt_templates(cwd):
        if marker in text:
            left += [fill for fill in fills if fill in text and fill not in left]
    return left


def detached_salvo(command):
    bare = QUOTED.sub("", HEREDOC.sub("", command))
    return bool(SALVO_RUN.search(bare) and DETACHED.search(bare))


def reads_a_skill(event):
    if (event.tool or "").lower() == "skill":
        return True
    return any(SKILL_FILE.search(p) for p in files_read(event))


def shell_command(event):
    if not isinstance(event.tool_input, dict):
        return None
    for k in ("command", "cmd", "commandLine"):
        v = event.tool_input.get(k)
        if isinstance(v, list):
            return " ".join(map(str, v))
        if isinstance(v, str):
            return v
    return None


def em_dash(message):
    prose = CODE.sub("", message or "")
    return "—" in prose


def uncited_principles(event, data, message):
    if not message or not ("principles" in data["skills"] or data["principles_read"]):
        return []
    titles = skills.principles(event.cwd)
    lowered = CODE.sub("", message).lower()
    return sorted({stem for t, stem in titles.items() if t in lowered and stem not in data["principles_read"]})


def on_stop(event):
    message = event.last_message or ""
    problems = []
    if em_dash(message):
        problems.append("Your reply uses an em dash. Rewrite it without one; a period or comma usually reads best.")
    if not state.exists(event.agent, event.session):
        return ("block", "\n".join(problems)) if problems else PASS
    data = state.load(event.agent, event.session)
    unread = uncited_principles(event, data, message)
    if unread:
        files = ", ".join(f"references/principles/{s}.md" for s in unread)
        problems.append(f"Your reply cites principles whose file you did not read this session ({files} in the principles skill). Read them, or remove those citations.")
    sources = {i["source"]: i["source_path"] for i in data["todo"] if i["source"] and i["source_path"]}
    needs_reply = [name for name, path in sources.items() if "../reply/SKILL.md" in (skills.read(path) or "")]
    if needs_reply and data["todo"] and not state.unresolved(data) and "reply" not in data["skills"]:
        problems.append(f"The `{needs_reply[0]}` skill asks for its reply per the reply skill. Read `../reply/SKILL.md` beside it and write the reply that way.")
    items = state.open_items(data)
    mandatory = [i for i in items if i["mandatory"]]
    asking = bool(QUESTION_END.search(CODE.sub("", message).strip()))
    if items and not problems and event.waiting_on_background and headless():
        problems.append("This session is non-interactive, so ending the turn ends the process and kills the background work "
                        "it is waiting on. Wait for that work in the foreground, finish the open items, then end the turn.")
    if items and not problems and (asking or event.waiting_on_background):
        return PASS
    if items:
        with state.update(event.agent, event.session) as d:
            idle = d.get("activity", 0) == d.get("activity_at_block", -1)
            d["idle_blocks"] = d.get("idle_blocks", 0) + 1 if idle else 0
            d["activity_at_block"] = d.get("activity", 0)
            idle_blocks = d["idle_blocks"]
        if idle_blocks < IDLE_LIMIT or mandatory:
            cmd, sess = cli(session_ref(event))
            lines = ["The todo list has open items:"] + [f"   {i['n']}. {i['title']}" for i in items]
            problems.append("\n".join(lines) + f"\nDo each one and mark it `{cmd} todo done <n> {sess}`, or skip it with `{cmd} todo skip <n> {sess} --reason \"...\"`. To end the turn on a question only the user can answer, even one asked in plain text after they declined a question tool, first mark the items that wait on the answer with `{cmd} todo wait <n> {sess} --reason \"<what the user must answer>\"`; they reopen when the user replies.")
        if idle_blocks >= IDLE_LIMIT and mandatory:
            problems.append("Item(s) {} are mandatory, so stopping repeatedly does not release them. If something outside your control "
                            "keeps one from closing, ask the user a question that names the item and what blocks it.".format(
                                ", ".join(str(i["n"]) for i in mandatory)))
    return ("block", "\n\n".join(problems)) if problems else PASS
