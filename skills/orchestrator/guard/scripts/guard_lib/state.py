"""Per-session guard state: skills loaded, principle files read, and the todo lists of the lead and each subagent."""
import contextlib
import fcntl
import json
import os
import pathlib
import re
import time

HOME = pathlib.Path(os.environ.get("GUARD_HOME") or pathlib.Path.home() / ".agents" / "guard")
SESSIONS = HOME / "sessions"


def key(agent, session):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{agent}-{session}")


def path(agent, session):
    return SESSIONS / f"{key(agent, session)}.json"


def exists(agent, session):
    return bool(session) and path(agent, session).exists()


def fresh():
    return {"skills": [], "principles_read": [], "todo": [], "todo_undecided": None, "archived": [],
            "activity": 0, "activity_at_block": -1, "idle_blocks": 0}


def fresh_list():
    return {"todo": [], "archived": [], "todo_undecided": None, "activity": 0, "activity_at_block": -1, "idle_blocks": 0}


def own_list(data, agent_id):
    """The todo list of one agent in the session: the lead's when agent_id is None, else that subagent's own."""
    if not agent_id:
        return data
    return data.setdefault("agents", {}).setdefault(agent_id, fresh_list())


def load(agent, session):
    try:
        return {**fresh(), **json.loads(path(agent, session).read_text())}
    except (OSError, json.JSONDecodeError):
        return fresh()


@contextlib.contextmanager
def update(agent, session):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS / f".{key(agent, session)}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(agent, session)
        yield data
        tmp = path(agent, session).with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path(agent, session))


def reopen_waiting(data):
    reopened = [i for i in data["todo"] if i["status"] == "waiting"]
    for item in reopened:
        item["status"], item["note"] = "open", None
    return reopened


def open_items(data):
    return [i for i in data["todo"] if i["status"] == "open"]


def unresolved(data):
    return [i for i in data["todo"] if i["status"] in ("open", "waiting")]


def add_items(data, texts, source=None, source_path=None, titles=None, mandatory=None):
    """Append items; a list whose every item is resolved is archived first, so a new task starts a new list."""
    if data["todo"] and not unresolved(data):
        data["archived"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "items": data["todo"]})
        data["todo"] = []
    start = len(data["todo"]) + 1
    for i, text in enumerate(texts):
        data["todo"].append({
            "n": start + i,
            "title": (titles[i] if titles else text)[:160],
            "text": text,
            "source": source,
            "source_path": str(source_path) if source_path else None,
            "mandatory": bool(mandatory[i]) if mandatory else "Mandatory" in text,
            "status": "open",
            "note": None,
        })
    data["todo_undecided"] = None
