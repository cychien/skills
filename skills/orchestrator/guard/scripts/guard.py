#!/usr/bin/env python3
"""The todo list guard holds an agent to. The agent decides what goes in it; guard makes every item resolve, in order.

usage:
  guard.py todo from <skill> [--session AGENT:ID]        copy a skill's steps in, verbatim, with their order
  guard.py todo add <text> [<text> ...] [--session AGENT:ID]
  guard.py todo show <n> [--session AGENT:ID]            print an item with the principles it names, and its token
  guard.py todo done <n> [<n> ...] [--token TOKEN ...] [--note TEXT] [--session AGENT:ID]
  guard.py todo skip <n> [<n> ...] --reason TEXT [--session AGENT:ID]
  guard.py todo wait <n> [<n> ...] --reason TEXT [--session AGENT:ID]  end the turn on a question only the user can answer
  guard.py todo hold --until <HH:MM or ISO time> --reason TEXT [--session AGENT:ID]  end turns with open items until then
  guard.py todo none --reason TEXT [--session AGENT:ID]  this task needs no list
  guard.py todo list [--session AGENT:ID]
  guard.py todo check [--session AGENT:ID]               exit 0 when no item is open or waiting, else 1 and the list
  guard.py todo clear --reason TEXT [--session AGENT:ID] the user stopped the work
  guard.py lint <skill name or SKILL.md path> | --all    report what keeps guard from reading a skill's steps
  guard.py quota status                                  the usage limits in force
  guard.py quota pick --role <planner|executor> [--avoid AGENT[:MODEL] ...] [--relax]
  guard.py delegates [--session AGENT:ID]                the subagents guard tracks, and whether each still runs
  guard.py delegates end <id> --reason TEXT [--session AGENT:ID]  the lead ends one it confirmed gone
  guard.py watch [--session AGENT:ID] [--interval S] [--initial S] [--multiple N] [--events N] [--cpu-floor F]
                                                         run as a background job: exit with a report when a job goes silent
  guard.py watch --ack <pid> [--session AGENT:ID]        never ask about this intentionally idle process again
  guard.py watch --stop [--session AGENT:ID]             end the session's watchdog

A subagent adds --agent ID (its agent id, which guard names when it asks) to every todo command, so its list stays its own.
An item copied from a skill closes only with the token `todo show` prints for it, and only once the items it waits on resolve.
"""
import argparse
import datetime
import os
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard_lib import autonomy, gates, lint, order, proof, quota, skills, state, watch  # noqa: E402

MARKS = {"open": "[ ]", "waiting": "[?]", "done": "[x]", "skipped": "[-]"}
NOT_RUN_DEPRECATED = ("guard: --not-run is deprecated and ignored: an item no longer needs the skills it names read first. "
                      "Its --reason is kept as the note. The flag goes away in the next release.")


def session(ref):
    if ref:
        agent, _, sid = ref.partition(":")
        return agent, sid
    for agent, var in (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"), ("gemini", "GEMINI_SESSION_ID")):
        if os.environ.get(var):
            return agent, os.environ[var]
    sys.exit("guard: pass --session AGENT:ID from the hook message.")


def command(agent, sid, agent_id):
    flags = f"--session {shlex.quote(f'{agent}:{sid}')}" + (f" --agent {shlex.quote(agent_id)}" if agent_id else "")
    return f"python3 {shlex.quote(os.path.abspath(__file__))}", flags


def listing(data):
    if not data["todo"]:
        return "The todo list is empty."
    lines = ["Todo:"]
    for i in data["todo"]:
        source = f" ({i['source']})" if i["source"] else ""
        note = f" - {'waiting on the user: ' if i['status'] == 'waiting' else ''}{i['note']}" if i["note"] else ""
        blocked = state.blocking(data, i) if i["status"] == "open" else []
        after = f" [after {', '.join(str(b['n']) for b in blocked)}]" if blocked else ""
        lines.append(f"  {MARKS[i['status']]} {i['n']}. {i['title']}{source}{after}{note}")
    hold = state.held(data)
    if hold:
        lines.append(f"Held until {quota.clock(hold['until'])}: {hold['reason']}")
    return "\n".join(lines)


def item_of(own, n):
    item = next((i for i in own["todo"] if i["n"] == n), None)
    if not item:
        sys.exit(f"guard: the todo list has no item {n}.")
    return item


def resolve(own, n, status, note, tokens, cli):
    item = item_of(own, n)
    cmd, sess = cli
    if status == "skipped" and item["mandatory"]:
        sys.exit(f"guard: item {n} is mandatory and cannot be skipped.")
    if status == "waiting" and item["status"] in ("done", "skipped"):
        sys.exit(f"guard: item {n} is already {item['status']}, so it has nothing to wait on.")
    if status == "done":
        blocked = state.blocking(own, item)
        if blocked:
            sys.exit("guard: item {} waits on {}, still {}. Resolve {} first, then mark item {} done.".format(
                n, ", ".join(f"item {b['n']} ({b['title']})" for b in blocked), " or ".join(sorted({b["status"] for b in blocked})),
                "it" if len(blocked) == 1 else "them", n))
        if item["source"] and proof.token(item, os.getcwd()) not in tokens:
            why = "The token does not match its current text" if tokens else f"It came from the {item['source']} skill, so closing it needs proof you read it"
            sys.exit(f"guard: item {n} stays open. {why}: run `{cmd} todo show {n} {sess}`, read it, then "
                     f"`{cmd} todo done {n} --token <token> {sess}` with the token it prints.")
        failed = gates.failures(item["text"])
        if failed:
            sys.exit(f"guard: item {n} stays open, because " + "\n".join(failed) + "\nFix what the gate reports, then mark the item done again.")
    item["status"], item["note"] = status, note
    message = f"Item {n} {status}."
    if status == "skipped":
        children = set(skills.SKILL_REF.findall(item["text"]))
        dropped = [i for i in state.unresolved(own) if i["source"] in children]
        for child in dropped:
            child["status"], child["note"] = "skipped", f"item {n} that runs {child['source']} was skipped"
        if dropped:
            message += f" Also skipped {len(dropped)} item(s) from {', '.join(sorted({d['source'] for d in dropped}))}, which item {n} would have run."
    return message


def until(text, now=None):
    """Epoch seconds for --until: HH:MM is its next occurrence, an ISO time is taken as given (local when it has no zone)."""
    now = now or time.time()
    try:
        clock = datetime.datetime.strptime(text, "%H:%M")
    except ValueError:
        clock = None
    if clock:
        moment = datetime.datetime.fromtimestamp(now).replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
        return (moment + datetime.timedelta(days=1) if moment.timestamp() <= now else moment).timestamp()
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        sys.exit(f"guard: --until takes HH:MM or an ISO time such as 2026-10-21T15:05, not {text!r}.")
    if moment.timestamp() <= now:
        sys.exit(f"guard: {text} has already passed; hold until a time still ahead.")
    return moment.timestamp()


def from_skill(own, data, name):
    path = skills.find(name, os.getcwd())
    steps = skills.steps(path) if path else []
    if not steps:
        sys.exit(f"guard: found no steps in the {name} skill. Add its steps with `todo add`, or run `todo none` if it has none.")
    waits = order.dependencies(steps)
    loop = order.cycle(waits)
    if loop:
        sys.exit(f"guard: the {name} skill's steps wait on each other in a cycle ({' -> '.join(map(str, loop))}), so its list could "
                 f"never close. Run `guard.py lint {path}` and fix the step text, or add the steps with `todo add`.")
    position = {n: i for i, (n, *_) in enumerate(steps)}
    state.add_items(own, [t for _, _, t, _ in steps], source=name, source_path=path, titles=[t for _, t, _, _ in steps],
                    mandatory=[m for _, _, _, m in steps], after=[[position[d] for d in waits[n]] for n, *_ in steps])
    if name not in data["skills"]:
        data["skills"].append(name)
    return f"Copied {len(steps)} steps from {name}. Add task-specific items after them with `todo add`. Close each with the token `todo show <n>` prints."


def run_todo(args):
    agent, sid = session(args.session)
    cli = command(agent, sid, args.agent)
    if args.action == "list":
        print(listing(state.own_list(state.load(agent, sid), args.agent)))
        return
    if args.action == "check":
        own = state.own_list(state.load(agent, sid), args.agent)
        if state.unresolved(own):
            print(listing(own))
            sys.exit(1)
        print("Every item is resolved." if own["todo"] else "The todo list is empty.")
        return
    if args.action == "wait":
        run = autonomy.active_run(agent, sid)
        if run and not autonomy.waiting_on_user(run):
            sys.exit(f"guard: this session is in an autonomous run, where the user is not available. Route the question with `{autonomy.ask_command(run)} --kind <kind> --question \"...\" --pick \"...\" --why \"...\" --confidence <level>` and keep working. Once `ask` escalates it to the user, `todo wait` is allowed.")
    if args.action == "done" and args.reason and not args.not_run:
        sys.exit("guard: --reason on done only goes with the deprecated --not-run. Use --note to annotate.")
    with state.update(agent, sid) as data:
        own = state.own_list(data, args.agent)
        decided = own.get("todo_undecided")
        if decided and args.action in ("from", "add", "none"):
            data.setdefault("todo_decided", []).append(decided)
        if args.action == "show":
            item = item_of(own, args.n)
            for _, content, stem in proof.attachments(item, os.getcwd()):
                if stem and content and stem not in data["principles_read"]:
                    data["principles_read"].append(stem)
            own["activity"] = own.get("activity", 0) + 1
            print(proof.render(item, os.getcwd()))
            return
        if args.action == "from":
            message = from_skill(own, data, args.skill)
        elif args.action == "add":
            flags = [t for t in args.text if t.startswith("-")]
            if flags:
                sys.exit(f"guard: {flags[0]!r} looks like a flag, not an item. Put flags after the items, outside their quotes.")
            state.add_items(own, args.text)
            message = f"Added {len(args.text)} item(s)."
        elif args.action == "none":
            own["todo_undecided"] = None
            message = f"No todo list for this task: {args.reason}"
        elif args.action == "clear":
            own["archived"].append({"cleared": args.reason, "items": own["todo"]})
            own["todo"], own["todo_undecided"], own["hold"] = [], None, None
            message = f"Todo list cleared: {args.reason}. Say so in your final reply."
        elif args.action == "hold":
            at = until(args.until)
            own["hold"] = {"until": at, "reason": args.reason}
            message = (f"Held until {quota.clock(at)}: {args.reason}. Until then a turn may end with open items; "
                       "the hold expires on its own.")
        else:
            status = {"done": "done", "skip": "skipped", "wait": "waiting"}[args.action]
            note = args.reason if args.action != "done" else " - ".join(filter(None, [args.reason, args.note])) or None
            if args.action == "done" and args.not_run:
                print(NOT_RUN_DEPRECATED)
            tokens = set(args.token) if args.action == "done" else set()
            message = "\n".join(resolve(own, n, status, note, tokens, cli) for n in args.n)
            if own["todo"] and not state.unresolved(own):
                message += "\nEvery item is resolved; list them with their marks in your final reply."
            elif status == "waiting" and not state.open_items(own):
                message += "\nEnd the turn now with your question in plain text. Waiting items reopen when the user replies."
        own["activity"] = own.get("activity", 0) + 1
        report = listing(own)
    print(message)
    print(report)


def run_lint(args):
    if args.all:
        paths = lint.installed(os.getcwd())
    elif args.target:
        found = args.target if args.target.endswith(".md") else skills.find(args.target, os.getcwd())
        if not found or not os.path.isfile(found):
            sys.exit(f"guard: no skill {args.target!r} under the skill roots; pass its SKILL.md path.")
        paths = [found]
    else:
        sys.exit("guard: lint takes a skill name, a SKILL.md path, or --all.")
    failed = False
    for path in paths:
        errors, warnings = lint.lint(path)
        failed = failed or bool(errors)
        for kind, problems in (("error", errors), ("warning", warnings)):
            for problem in problems:
                print(f"{path}: {kind}: {problem}")
    print(f"Linted {len(paths)} skill(s): {'errors found' if failed else 'no errors'}.")
    sys.exit(1 if failed else 0)


def run_quota(args):
    if args.action == "status":
        print(quota.status())
        return
    entry, relaxed, why = quota.pick(os.getcwd(), args.role, args.avoid, relax=args.relax)
    if args.relax:
        print("Fallback order:\n" + "\n".join(f"  {i}. {step}" for i, step in enumerate(quota.FALLBACK, 1)))
    if not entry:
        sys.exit(f"guard: {why}")
    print(quota.spec(entry))
    if relaxed:
        print(f"relaxed: {relaxed}. Report it in the PR's Verification section and in report.md.")


def run_delegates(args):
    agent, sid = session(args.session)
    if args.action == "end":
        with state.update(agent, sid) as data:
            delegate = data.get("delegates", {}).get(args.id)
            if not delegate:
                sys.exit(f"guard: no delegate {args.id!r} in this session.")
            delegate.update(running=False, ended_by_lead=args.reason)
        print(f"Ended {args.id}: {args.reason}")
        return
    data = state.load(agent, sid)
    delegates = data.get("delegates", {})
    if not delegates:
        print("No delegates tracked.")
    now = time.time()
    for agent_id, delegate in sorted(delegates.items(), key=lambda pair: pair[1]["since"]):
        status = state.delegate_status(data, delegate, now)
        last = delegate.get("last", delegate["since"])
        print(f"{agent_id}  {status}  since {quota.clock(delegate['since'])}  last tool call {int(now - last)}s ago")


def run_watch(args):
    agent, sid = session(args.session)
    if args.ack is not None:
        print(watch.ack(agent, sid, args.ack))
        return
    if args.stop:
        stopped = watch.stop(agent, sid)
        print(f"Stopped the watchdog (pid {stopped})." if stopped else "No watchdog runs for this session.")
        return
    sys.exit(watch.run(agent, sid, interval=args.interval, initial=args.initial, multiple=args.multiple, events=args.events,
                       cpu_floor=args.cpu_floor))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    todo = sub.add_parser("todo").add_subparsers(dest="action", required=True)
    p = todo.add_parser("from")
    p.add_argument("skill")
    p = todo.add_parser("add")
    p.add_argument("text", nargs="+")
    p = todo.add_parser("show")
    p.add_argument("n", type=int)
    p = todo.add_parser("done")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--token", action="append", default=[])
    p.add_argument("--note")
    p.add_argument("--not-run", action="append", default=[], metavar="SKILL", help=argparse.SUPPRESS)
    p.add_argument("--reason")
    p = todo.add_parser("skip")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--reason", required=True)
    p = todo.add_parser("wait")
    p.add_argument("n", type=int, nargs="+")
    p.add_argument("--reason", required=True)
    p = todo.add_parser("hold")
    p.add_argument("--until", required=True)
    p.add_argument("--reason", required=True)
    for name in ("none", "clear"):
        todo.add_parser(name).add_argument("--reason", required=True)
    todo.add_parser("list")
    todo.add_parser("check")
    for p in todo.choices.values():
        p.add_argument("--session")
        p.add_argument("--agent")
    p = sub.add_parser("lint")
    p.add_argument("target", nargs="?")
    p.add_argument("--all", action="store_true")
    q = sub.add_parser("quota").add_subparsers(dest="action", required=True)
    q.add_parser("status")
    p = q.add_parser("pick")
    p.add_argument("--role", required=True, choices=quota.ROLES)
    p.add_argument("--avoid", action="append", default=[], metavar="AGENT[:MODEL]")
    p.add_argument("--relax", action="store_true")
    d = sub.add_parser("delegates")
    d.add_argument("action", nargs="?", choices=["end"])
    d.add_argument("id", nargs="?")
    d.add_argument("--reason")
    d.add_argument("--session")
    w = sub.add_parser("watch", description="Ask the lead about background jobs that went silent; never stop one.")
    w.add_argument("--session")
    w.add_argument("--ack", type=int, metavar="PID", help="acknowledge an intentionally idle process: never ask about it again")
    w.add_argument("--stop", action="store_true", help="end the session's watchdog")
    w.add_argument("--interval", type=float, default=watch.INTERVAL_S, help="seconds between samples (default %(default)g)")
    w.add_argument("--initial", type=float, default=watch.INITIAL_S,
                   help="seconds of silence before a question while a job has too few progress events to judge its rhythm, "
                        "and the least it ever waits (default %(default)g)")
    w.add_argument("--multiple", type=float, default=watch.MULTIPLE,
                   help="a job is silent after this many times its longest gap between progress events (default %(default)g)")
    w.add_argument("--events", type=int, default=watch.EVENTS,
                   help="progress events a job shows before its own gaps set its threshold (default %(default)d)")
    w.add_argument("--cpu-floor", type=float, default=watch.CPU_FLOOR,
                   help="share of one core a job's processes must use between samples for CPU time to count as progress, "
                        "so idle timers and pollers do not (default %(default)g)")
    args = parser.parse_args()
    if args.cmd == "delegates" and args.action == "end" and not (args.id and args.reason):
        parser.error("delegates end takes an id and --reason")
    {"todo": run_todo, "lint": run_lint, "quota": run_quota, "delegates": run_delegates, "watch": run_watch}[args.cmd](args)


if __name__ == "__main__":
    main()
