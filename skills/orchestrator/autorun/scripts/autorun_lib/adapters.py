"""Per-agent hook I/O: native event names and payloads in, native decision JSON out."""
import json

from .hooks import Event

EVENTS = {
    "claude": {"UserPromptSubmit": "prompt", "PreToolUse": "pre_tool", "PostToolUse": "post_tool", "PostToolUseFailure": "post_tool_failure",
               "Stop": "stop", "SubagentStop": "subagent_stop", "PermissionRequest": "permission", "PermissionDenied": "permission_denied"},
    "codex": {"UserPromptSubmit": "prompt", "PreToolUse": "pre_tool", "PostToolUse": "post_tool", "Stop": "stop",
              "SubagentStop": "subagent_stop", "PermissionRequest": "permission"},
    "cursor": {"beforeSubmitPrompt": "prompt", "preToolUse": "pre_tool", "postToolUse": "post_tool", "stop": "stop",
               "subagentStop": "subagent_stop"},
    "copilot": {"userPromptSubmitted": "prompt", "preToolUse": "pre_tool", "postToolUse": "post_tool", "agentStop": "stop",
                "subagentStop": "subagent_stop", "permissionRequest": "permission"},
    "gemini": {"BeforeAgent": "prompt", "BeforeTool": "pre_tool", "AfterTool": "post_tool", "AfterAgent": "stop"},
}

INJECTS = {
    "claude": {"prompt", "post_tool"},
    "codex": {"prompt", "post_tool"},
    "cursor": {"post_tool"},
    "copilot": set(),
    "gemini": {"prompt", "post_tool"},
}


def _get(payload, *keys, default=None):
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return default


def _tool_input(payload):
    value = _get(payload, "tool_input", "toolArgs", "toolInput", default={})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {"command": value}
    return value if isinstance(value, dict) else {}


def parse(agent, native_event, payload):
    kind = EVENTS[agent].get(native_event)
    if not kind:
        return None
    background = bool(payload.get("background_tasks") or payload.get("session_crons"))
    return Event(
        agent=agent,
        kind=kind,
        session=str(_get(payload, "session_id", "sessionId", "conversation_id", default="") or "") or None,
        cwd=_get(payload, "cwd", default=None) or (payload.get("workspace_roots") or [None])[0],
        agent_id=_get(payload, "agent_id", "subagent_id", default=None),
        prompt=_get(payload, "prompt", default="") or "",
        tool=_get(payload, "tool_name", "toolName", default=None),
        tool_input=_tool_input(payload),
        tool_response=_get(payload, "tool_response", "toolResult", "tool_output", "error", default=None),
        last_message=_get(payload, "last_assistant_message", "prompt_response", default="") or "",
        stop_hook_active=bool(_get(payload, "stop_hook_active", default=False)) or (payload.get("loop_count") or 0) > 0,
        waiting_on_background=background,
        can_inject=kind in INJECTS[agent],
        stop_status=payload.get("status"),
    )


def render(agent, native_event, event, decision):
    """(stdout JSON or None, exit code). Every agent proceeds normally on empty output and exit 0."""
    action, message = decision
    if action == "pass" or not message and action not in ("allow", "retry"):
        return None, 0
    if action == "note":
        return ({"systemMessage": message}, 0) if agent in ("claude", "codex") else (None, 0)
    if agent in ("claude", "codex"):
        if action == "deny":
            return {"hookSpecificOutput": {"hookEventName": native_event, "permissionDecision": "deny", "permissionDecisionReason": message}}, 0
        if action == "block":
            return {"decision": "block", "reason": message}, 0
        if action == "allow" and event.kind == "pre_tool":
            return {"hookSpecificOutput": {"hookEventName": native_event, "permissionDecision": "allow"}}, 0
        if action == "allow":
            return {"hookSpecificOutput": {"hookEventName": native_event, "decision": {"behavior": "allow"}}}, 0
        if action == "retry":
            return {"hookSpecificOutput": {"hookEventName": native_event, "retry": True}}, 0
        if action == "refuse":
            return {"hookSpecificOutput": {"hookEventName": native_event, "decision": {"behavior": "deny", "message": message}}}, 0
        return {"hookSpecificOutput": {"hookEventName": native_event, "additionalContext": message}}, 0
    if agent == "cursor":
        if action == "deny":
            return {"permission": "deny", "agent_message": message, "user_message": "autorun: routed through the autonomous-mode protocol"}, 0
        if action == "block":
            return ({"followup_message": message}, 0) if event.stop_status in (None, "completed") else (None, 0)
        if action == "context":
            return {"additional_context": message}, 0
        return None, 0
    if agent == "copilot":
        if action == "deny":
            return {"permissionDecision": "deny", "permissionDecisionReason": message}, 0
        if action == "block":
            return {"decision": "block", "reason": message}, 0
        if action == "allow":
            return {"behavior": "allow"}, 0
        if action == "refuse":
            return {"behavior": "deny", "message": message}, 0
        return None, 0
    if agent == "gemini":
        if action in ("deny", "block"):
            return {"decision": "deny", "reason": message}, 0
        if action == "context":
            return {"hookSpecificOutput": {"hookEventName": native_event, "additionalContext": message}}, 0
        return None, 0
    return None, 0
