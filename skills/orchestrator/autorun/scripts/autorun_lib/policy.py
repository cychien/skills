"""Hard rules: what turns autonomous mode on and off, what counts as a question, what counts as irreversible."""
import json
import os
import pathlib
import re
import shlex

from . import store

CLAUSE = r"(?:^|[\n，。、,.!！?？；;：:（(])\s*"  # mode-switch verbs count only as an instruction opening a clause, not inside talk about the mode

DEFAULTS = {
    "enter": [
        r"(?:^|\s)/(auto|autorun)\b(?!\s+off)",
        r"\brun (it |this )?(until|till) (it'?s |it is )?(done|finished|complete)\b",
        r"\bgoing to (bed|sleep)\b",
        r"\bdon'?t (ask me|stop until)\b",
        r"\b(be |go |run )fully autonomous(ly)?\b",
        r"\bfull[- ]?auto(nomous)?( mode)?\b",
        CLAUSE + r"(please\s+)?(turn on|enable|enter|start|use|go into|switch to) (the )?(autonomous|auto) mode\b",
        "跑到完", "做到完", "做完為止", "做完为止",
        "不要問我", "不要问我", "別問我", "别问我", "不用問我", "不用问我",
        CLAUSE + r"(請|请|幫我|帮我|直接|就)?(進入|进入|開啟|开启|打開|打开|切到|切換到|切换到|用|以)自[動动]模式",
        CLAUSE + r"(請|请|幫我|帮我|直接|就)?全自[動动]地?(跑|做|完成|處理|处理|執行|执行)",
        "我去睡", "要去睡",
    ],
    "exit": [
        r"(?:^|\s)/(auto|autorun)\s+off\b",
        r"\b(stop|exit|end|leave|turn off) (the )?(autonomous|auto) mode\b",
        r"\bautonomous mode off\b",
        "結束自動模式", "结束自动模式", "關掉自動模式", "关掉自动模式", "關閉自動模式", "关闭自动模式",
        "退出自動模式", "退出自动模式", "停止自動模式", "停止自动模式",
    ],
    "irreversible_commands": [
        ["force push", r"\bgit\s+push\b[^|;&]*(\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S)"],
        ["remote branch or tag deletion", r"\bgit\s+push\b[^|;&]*(\s--delete\b|\s-d\b|\s:\S)"],
        ["merging a pull request", r"\bgh\s+pr\s+merge\b"],
        ["publishing a release", r"\bgh\s+release\s+create\b"],
        ["deleting a repository", r"\bgh\s+repo\s+delete\b"],
        ["publishing a package", r"\b(npm|pnpm|yarn|bun)\s+publish\b|\bcargo\s+publish\b|\btwine\s+upload\b|\bgem\s+push\b"],
        ["pushing an image", r"\bdocker\s+push\b"],
        ["a deploy", r"\b(vercel\b[^|;&]*--prod|fly\s+deploy|flyctl\s+deploy|netlify\s+deploy[^|;&]*--prod|firebase\s+deploy|wrangler\s+(deploy|publish)|serverless\s+deploy|sls\s+deploy)\b"],
        ["changing live infrastructure", r"\b(terraform|tofu)\s+(apply|destroy)\b|\bkubectl\s+(apply|delete|replace|scale|rollout)\b|\bhelm\s+(install|upgrade|uninstall|delete)\b"],
        ["destroying data", r"\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b"],
        ["deleting outside the workspace", r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+(/|~|\$HOME|\.\.)(\s|/?$)"],
    ],
    "irreversible_tools": [
        ["sending a message or email", r"(?i)(send_?(message|email|mail)|post_?message|reply_?(to_?)?(message|thread|email))"],
    ],
    "stop_idle_limit": 3,
    "notify": None,
    "review": True,
    "review_command": None,
}

# Messages to agents the session launched, not to people.
AGENT_MESSAGE_TOOLS = re.compile(r"^SendMessage$")
USAGE_LIMIT = re.compile(r"(?i)\b(usage|session|weekly)[ -]limits?\b|額度|用量上限")
QUESTION_TOOLS = re.compile(r"(?i)^(askuserquestion|ask_?user(_?question)?|ask_?question|request_?user_?input)$")
SHELL_TOOLS = re.compile(r"(?i)^(bash|shell|exec_command|local_shell|run_shell_command|terminal|powershell|run_terminal_cmd)$")
NOT_THE_USERS_WORDS = re.compile(
    r"<pasted_content\b.*?</pasted_content[^>]*>|```.*?```|`[^`\n]*`|\"[^\"\n]{0,120}\"|“[^”\n]{0,120}”|「[^」\n]{0,120}」|『[^』\n]{0,120}』",
    re.S,
)
SYSTEM_PROMPT = re.compile(r"^\s*<(task-notification|system-reminder|local-command|command-name)")
QUESTION_ENDING = re.compile(
    r"([?？]\s*\**\s*$)|(?i:\b(should i|shall i|do you want|would you like|want me to|let me know (if|whether|which))\b)|"
    r"(要不要|需要我|你想要|你希望|請確認|请确认|請告訴我|请告诉我|是否要)"
)


SKILL_COMMAND = re.compile(r"^\s*/([a-z0-9][a-z0-9-]*)\b")


def skill_command(prompt, cwd):
    """The installed skill a prompt invokes with /name, if any."""
    m = SKILL_COMMAND.match(prompt or "")
    if not m or m.group(1) in ("auto", "autorun"):
        return None
    configured = os.environ.get("AUTORUN_SKILL_ROOTS")
    home, base = pathlib.Path.home(), pathlib.Path(cwd or ".")
    roots = [pathlib.Path(p) for p in configured.split(os.pathsep)] if configured else \
        [base / ".claude/skills", base / ".agents/skills", home / ".claude/skills", home / ".agents/skills", home / ".codex/skills"]
    return m.group(1) if any((r / m.group(1) / "SKILL.md").is_file() for r in roots) else None


def config():
    merged = dict(DEFAULTS)
    try:
        merged.update(json.loads((store.HOME / "config.json").read_text()))
    except (OSError, json.JSONDecodeError):
        pass
    return merged


def _first_match(patterns, text):
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def users_own_words(prompt):
    """Drop pasted blocks, code, and quotations, so a trigger phrase someone quotes does not count as the user saying it."""
    return NOT_THE_USERS_WORDS.sub(" ", prompt)


def enter_trigger(prompt):
    return None if SYSTEM_PROMPT.match(prompt) else _first_match(config()["enter"], users_own_words(prompt))


def exit_trigger(prompt):
    return None if SYSTEM_PROMPT.match(prompt) else _first_match(config()["exit"], users_own_words(prompt))


def is_system_prompt(prompt):
    return bool(SYSTEM_PROMPT.match(prompt))


def is_question_tool(tool):
    return bool(tool and QUESTION_TOOLS.match(tool))


def shell_command(tool, tool_input):
    if not tool or not SHELL_TOOLS.match(tool) or not isinstance(tool_input, dict):
        return None
    for key in ("command", "cmd", "commandLine", "script"):
        value = tool_input.get(key)
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
        if isinstance(value, str):
            return value
    return None


def is_own_cli(tool, tool_input):
    """A shell call that only runs autorun's own CLI, with nothing chained to it."""
    command = shell_command(tool, tool_input)
    if not command:
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        tokens = list(lexer)
    except ValueError:
        return False
    if any(t and set(t) <= set(";&|<>()") for t in tokens):
        return False
    return len(tokens) >= 3 and re.fullmatch(r"python3?", tokens[0]) is not None and tokens[1].endswith("/autorun.py") \
        and tokens[2] in ("start", "ask", "done", "status", "report", "stop", "mode")


def subject(tool, tool_input):
    """The exact call an approval applies to."""
    command = shell_command(tool, tool_input)
    return command if command is not None else f"{tool} {json.dumps(tool_input, sort_keys=True, ensure_ascii=False)}"


def irreversible(tool, tool_input):
    """(label, subject) when this call cannot be undone, else None."""
    cfg = config()
    command = shell_command(tool, tool_input)
    if command is not None:
        for label, pattern in cfg["irreversible_commands"]:
            if re.search(pattern, command, re.IGNORECASE):
                return label, command
        return None
    if AGENT_MESSAGE_TOOLS.match(tool or ""):
        return None
    for label, pattern in cfg["irreversible_tools"]:
        if tool and re.search(pattern, tool):
            return label, tool
    return None


def about_usage_limit(*texts):
    return any(USAGE_LIMIT.search(t or "") for t in texts)


def ends_with_question(message):
    lines = [line.strip() for line in (message or "").strip().splitlines() if line.strip()]
    return bool(lines) and bool(QUESTION_ENDING.search(lines[-1]))
