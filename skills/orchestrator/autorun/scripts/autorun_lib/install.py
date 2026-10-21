"""Register autorun's hooks in each agent's user-level config. Idempotent; leaves every other hook alone."""
import json
import os
import pathlib
import shlex
import shutil
import time

HOME = pathlib.Path.home()
PROMPT, PRE, POST, FAILED, STOP, START, SUB, PERM, DENIED = "prompt", "pre", "post", "failed", "stop", "start", "sub", "perm", "denied"
TIMEOUTS = {PERM: 300, DENIED: 300}

AGENTS = {
    "claude": {"config": HOME / ".claude" / "settings.json", "binary": "claude", "style": "claude",
               "events": {PROMPT: "UserPromptSubmit", PRE: "PreToolUse", POST: "PostToolUse", FAILED: "PostToolUseFailure", STOP: "Stop",
                          START: "SubagentStart", SUB: "SubagentStop", PERM: "PermissionRequest", DENIED: "PermissionDenied"}},
    "codex": {"config": HOME / ".codex" / "hooks.json", "binary": "codex", "style": "claude",
              "events": {PROMPT: "UserPromptSubmit", PRE: "PreToolUse", POST: "PostToolUse", STOP: "Stop", SUB: "SubagentStop", PERM: "PermissionRequest"}},
    "cursor": {"config": HOME / ".cursor" / "hooks.json", "binary": "cursor-agent", "style": "cursor",
               "events": {PROMPT: "beforeSubmitPrompt", PRE: "preToolUse", POST: "postToolUse", STOP: "stop", SUB: "subagentStop"}},
    "copilot": {"config": HOME / ".copilot" / "hooks" / "autorun.json", "binary": "copilot", "style": "copilot",
                "events": {PROMPT: "userPromptSubmitted", PRE: "preToolUse", POST: "postToolUse", STOP: "agentStop", SUB: "subagentStop", PERM: "permissionRequest"}},
    "gemini": {"config": HOME / ".gemini" / "settings.json", "binary": "gemini", "style": "gemini",
               "events": {PROMPT: "BeforeAgent", PRE: "BeforeTool", POST: "AfterTool", STOP: "AfterAgent"}},
}


def is_ours(entry):
    text = json.dumps(entry)
    return "autorun.py" in text and " hook " in text


def command(script, agent, event):
    return f"python3 {shlex.quote(script)} hook {agent} {event}"


def entry(style, cmd, role):
    timeout = TIMEOUTS.get(role, 30)
    if style == "claude":
        return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
    if style == "cursor":
        return {"command": cmd, "timeout": timeout, **({"loop_limit": None} if role in (STOP, SUB) else {})}
    if style == "copilot":
        return {"type": "command", "bash": cmd, "timeoutSec": timeout}
    return {"matcher": ".*", "hooks": [{"type": "command", "command": cmd, "timeout": timeout * 1000}]} if role in (PRE, POST) else \
        {"hooks": [{"type": "command", "command": cmd, "timeout": timeout * 1000}]}


def merged(agent, script, existing):
    spec = AGENTS[agent]
    config = dict(existing)
    hooks = {k: [e for e in v if not is_ours(e)] for k, v in config.get("hooks", {}).items()}
    for role, event in spec["events"].items():
        hooks.setdefault(event, []).append(entry(spec["style"], command(script, agent, event), role))
    config["hooks"] = {k: v for k, v in hooks.items() if v}
    if spec["style"] in ("cursor", "copilot"):
        config.setdefault("version", 1)
    return config


def detected():
    return [a for a, s in AGENTS.items() if shutil.which(s["binary"]) or s["config"].parent.is_dir()]


def _read(path):
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"autorun: {path} is not valid JSON ({e}); fix it and rerun.") from None


def install(script, agents=None, print_only=False):
    for agent in agents or detected():
        link = AGENTS[agent]["config"]
        path = link.resolve()
        config = merged(agent, script, _read(path))
        if print_only or not _writable(path):
            reason = "requested" if print_only else f"{path} is read-only"
            ours = {k: [e for e in v if is_ours(e)] for k, v in config["hooks"].items()}
            print(f"## {agent}: not written, {reason}. Merge these into the `hooks` of {link}:\n")
            print(json.dumps({k: v for k, v in ours.items() if v}, indent=2) + "\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                _backup(agent, path)
            path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
            print(f"## {agent}: hooks written to {path}" + (f" (via {link})" if path != link else ""))
            if agent == "codex":
                print("   Codex runs new hooks only after you trust them: open codex and approve them in /hooks.")
        if agent == "codex":
            codex_sandbox_advice()


def _backup(agent, path):
    from . import store

    backups = store.HOME / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backups / f"{agent}-{time.strftime('%Y%m%d-%H%M%S')}-{path.name}")


def _writable(path):
    """Symlinks into a user-owned file (home-manager out-of-store links) are fine; the nix store is not."""
    return os.access(path if path.exists() else path.parent, os.W_OK) and not str(path).startswith("/nix/store/")


def codex_sandbox_advice():
    """Codex's workspace-write sandbox blocks the run state and the reviewer's network calls."""
    from . import store

    config = HOME / ".codex" / "config.toml"
    text = config.read_text() if config.exists() else ""
    # Codex refuses a writable root with a symlink in its path, so name the resolved directory.
    root = os.path.realpath(store.HOME)
    if f'"{root}"' in text and "network_access = true" in text:
        return
    print(f"""   Under Codex's workspace-write sandbox, autorun cannot save run state or reach the reviewer.
   For unattended runs, either start Codex with full access, or add this to {config}:

   [sandbox_workspace_write]
   writable_roots = ["{root}"]
   network_access = true
""")


def uninstall(agents=None):
    for agent in agents or detected():
        path = AGENTS[agent]["config"].resolve()
        if not path.exists():
            continue
        config = _read(path)
        hooks = {k: [e for e in v if not is_ours(e)] for k, v in config.get("hooks", {}).items()}
        config["hooks"] = {k: v for k, v in hooks.items() if v}
        if not _writable(path):
            print(f"## {agent}: {path} is read-only; remove the autorun entries where it is generated.")
            continue
        _backup(agent, path)
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        print(f"## {agent}: autorun hooks removed from {path}")
