#!/usr/bin/env python3
"""The todo list guard holds an agent to. The agent decides what goes in it; guard makes every item resolve.

usage:
  guard.py todo from <skill> [--session AGENT:ID]        copy a skill's steps in, verbatim
  guard.py todo add <text> [<text> ...] [--session AGENT:ID]
  guard.py todo done <n> [<n> ...] [--note TEXT] [--session AGENT:ID]
  guard.py todo skip <n> [<n> ...] --reason TEXT [--session AGENT:ID]
  guard.py todo wait <n> [<n> ...] --reason TEXT [--session AGENT:ID]  end the turn on a question only the user can answer
  guard.py todo none --reason TEXT [--session AGENT:ID]  this task needs no list
  guard.py todo list [--session AGENT:ID]
  guard.py todo clear --reason TEXT [--session AGENT:ID] the user stopped the work
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard_lib import autonomy, gates, skills, state  # noqa: E402


def session(ref):
    if ref:
        agent, _, sid = ref.partition(":")
        return agent, sid
    for agent, var in (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"), ("gemini", "GEMINI_SESSION_ID")):
        if os.environ.get(var):
            return agent, os.environ[var]
    sys.exit("guard: pass --session AGENT:ID from the hook message.")


def show(data):
    if not data["todo"]:
        return "The todo list is empty."
    marks = {"open": "[ ]", "waiting": "[?]", "done": "[x]", "skipped": "[-]"}
    lines = ["Todo:"]
    for i in data["todo"]:
        source = f" ({i['source']})" if i["source"] else ""
        note = f" - {'waiting on the user: ' if i['status'] == 'waiting' else ''}{i['note']}" if i["note"] else ""
        lines.append(f"  {marks[i['status']]} {i['n']}. {i['title']}{source}{note}")
    return "\n".join(lines)


def resolve(data, n, status, note):
    item = next((i for i in data["todo"] if i["n"] == n), None)
    if not item:
        sys.exit(f"guard: the todo list has no item {n}.")
    if status == "skipped" and item["mandatory"]:
        sys.exit(f"guard: item {n} is mandatory and cannot be skipped.")
    if status == "waiting" and item["status"] in ("done", "skipped"):
        sys.exit(f"guard: item {n} is already {item['status']}, so it has nothing to wait on.")
    if status == "done":
        unread = sorted(set(skills.SKILL_REF.findall(item["text"])) - set(data["skills"]))
        if unread:
            sys.exit("guard: item {} names skills you have not read this session: {}. Read them first.".format(
                n, ", ".join(f"../{u}/SKILL.md" for u in unread)))
        if "every principle file" in item["text"]:
            missing = sorted(set(skills.principles(os.getcwd()).values()) - set(data["principles_read"]))
            if missing:
                sys.exit("guard: item {} needs every principle file read first; still unread: {}.".format(
                    n, ", ".join(f"references/principles/{m}.md" for m in missing)))
        failed = gates.failures(item["text"])
        if failed:
            sys.exit(f"guard: item {n} stays open, because " + "\n".join(failed) + "\nFix what the gate reports, then mark the item done again.")
    item["status"], item["note"] = status, note
    message = f"Item {n} {status}."
    if status == "skipped":
        children = set(skills.SKILL_REF.findall(item["text"]))
        dropped = [i for i in state.unresolved(data) if i["source"] in children]
        for child in dropped:
            child["status"], child["note"] = "skipped", f"item {n} that runs {child['source']} was skipped"
        if dropped:
            message += f" Also skipped {len(dropped)} item(s) from {', '.join(sorted({d['source'] for d in dropped}))}, which item {n} would have run."
    return message


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    todo = sub.add_parser("todo").add_subparsers(dest="action", required=True)
    p = todo.add_parser("from")
    p.add_argument("skill")
    p = todo.add_parser("add")
    p.add_argument("text", nargs="+")
    p = todo.add_parser("done")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--note")
    p = todo.add_parser("skip")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--reason", required=True)
    p = todo.add_parser("wait")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--reason", required=True)
    for name in ("none", "clear"):
        todo.add_parser(name).add_argument("--reason", required=True)
    todo.add_parser("list")
    for p in todo.choices.values():
        p.add_argument("--session")
    args = parser.parse_args()
    agent, sid = session(args.session)

    if args.action == "list":
        print(show(state.load(agent, sid)))
        return
    if args.action == "wait":
        ask = autonomy.ask_command(agent, sid)
        if ask:
            sys.exit(f"guard: this session is in an autonomous run, where the user is not available. Route the question with `{ask} --kind <kind> --question \"...\" --pick \"...\" --why \"...\" --confidence <level>` and keep working.")
    with state.update(agent, sid) as data:
        decided = data.get("todo_undecided")
        if decided and args.action in ("from", "add", "none"):
            data.setdefault("todo_decided", []).append(decided)
        if args.action == "from":
            path = skills.find(args.skill, os.getcwd())
            steps = skills.steps(path) if path else []
            if not steps:
                sys.exit(f"guard: found no steps in the {args.skill} skill. Add its steps with `todo add`, or run `todo none` if it has none.")
            state.add_items(data, [t for _, _, t, _ in steps], source=args.skill, source_path=path,
                            titles=[t for _, t, _, _ in steps], mandatory=[m for _, _, _, m in steps])
            if args.skill not in data["skills"]:
                data["skills"].append(args.skill)
            message = f"Copied {len(steps)} steps from {args.skill}. Add task-specific items after them with `todo add`."
        elif args.action == "add":
            flags = [t for t in args.text if t.startswith("-")]
            if flags:
                sys.exit(f"guard: {flags[0]!r} looks like a flag, not an item. Put flags after the items, outside their quotes.")
            state.add_items(data, args.text)
            message = f"Added {len(args.text)} item(s)."
        elif args.action == "none":
            data["todo_undecided"] = None
            message = f"No todo list for this task: {args.reason}"
        elif args.action == "clear":
            data["archived"].append({"cleared": args.reason, "items": data["todo"]})
            data["todo"], data["todo_undecided"] = [], None
            message = f"Todo list cleared: {args.reason}. Say so in your final reply."
        else:
            status = {"done": "done", "skip": "skipped", "wait": "waiting"}[args.action]
            note = args.note if args.action == "done" else args.reason
            message = "\n".join(resolve(data, n, status, note) for n in args.n)
            if data["todo"] and not state.unresolved(data):
                message += "\nEvery item is resolved; list them with their marks in your final reply."
            elif status == "waiting" and not state.open_items(data):
                message += "\nEnd the turn now with your question in plain text. Waiting items reopen when the user replies."
        data["activity"] = data.get("activity", 0) + 1
        report = show(data)
    print(message)
    print(report)


if __name__ == "__main__":
    main()
