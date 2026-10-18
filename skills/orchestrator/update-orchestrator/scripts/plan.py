#!/usr/bin/env python3
"""Plan which orchestrator config entries move to a newer model, by model line, and print it as JSON.

usage: plan.py <config path> [--catalogs <detect.py output file>]

A model line is a model id without its version, so gpt-5.6-sol and gpt-6-sol are one line and
gpt-6-astra is another. An entry moves only to a newer version of its own line, because the line
is what the user's plan was sized to sustain. Models of lines the config does not use are listed
under new_lines and never placed.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP_SCRIPTS = os.path.join(HERE, "..", "..", "setup-orchestrator", "scripts")
EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
VERSION = re.compile(r"\d+(\.\d+)*")
SNAPSHOT = re.compile(r"\d{8}")


def line_and_version(model):
    line, version = [], []
    for token in model.split("-"):
        if SNAPSHOT.fullmatch(token):
            continue
        if VERSION.fullmatch(token):
            version += [int(n) for n in token.split(".")]
        else:
            line.append(token)
    return "-".join(line), tuple(version)


def nearest_effort(effort, supported):
    if effort is None or not supported:
        return None
    if effort in supported:
        return effort
    rank = EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else len(EFFORT_ORDER)
    lower = [e for e in supported if e in EFFORT_ORDER and EFFORT_ORDER.index(e) < rank]
    return max(lower, key=EFFORT_ORDER.index) if lower else supported[0]


def newest_by_line(catalog):
    newest = {}
    for m in catalog:
        line, version = line_and_version(m["id"])
        if line not in newest or version > line_and_version(newest[line]["id"])[1]:
            newest[line] = m
    return newest


def plan_role(entries, catalogs):
    planned = []
    in_role = {(e["agent"], e["model"]) for e in entries}
    for e in entries:
        catalog = catalogs.get(e["agent"])
        step = {"agent": e["agent"], "model": e["model"], "effort": e["effort"], "action": "keep", "to": None}
        if not catalog:
            step["reason"] = "no catalog for this agent, so nothing is known about its models"
            planned.append(step)
            continue
        by_id = {m["id"]: m for m in catalog}
        line, version = line_and_version(e["model"])
        successor = newest_by_line(catalog).get(line)
        retired = e["model"] not in by_id
        if successor and line_and_version(successor["id"])[1] <= version:
            successor = None
        if successor and (e["agent"], successor["id"]) in in_role:
            step["action"] = "retired" if retired else "keep"
            step["reason"] = f"{successor['id']} is already in this role" + (
                "; pick another model for this slot" if retired else ", so this older model stays as an extra voice"
            )
        elif successor:
            to = {"model": successor["id"], "effort": nearest_effort(e["effort"], successor.get("efforts") or [])}
            old_notice = (by_id.get(e["model"]) or {}).get("notice")
            if successor.get("notice") and not old_notice:
                to["notice"] = successor["notice"]
            step.update(action="replace", to=to, reason=f"newer version of the {line} line")
            in_role.add((e["agent"], successor["id"]))
        elif retired:
            step.update(action="retired", reason=f"not in the catalog and no newer {line} model exists; pick another model for this slot")
        else:
            step["reason"] = f"already the newest {line} model"
        planned.append(step)
    return planned


def spec(agent, model, effort):
    return f"{agent}:{model}" + (f":{effort}" if effort else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--catalogs", help="detect.py output to read instead of running it")
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.config))
    config = json.load(open(path))
    if "subscriptions" not in config:
        sys.exit(f"{path} has no subscriptions; run setup-orchestrator instead")
    if args.catalogs:
        detected = json.load(open(args.catalogs))
    else:
        out = subprocess.run([sys.executable, os.path.join(SETUP_SCRIPTS, "detect.py")], capture_output=True, text=True)
        detected = json.loads(out.stdout)
    catalogs = {agent: models for agent, models in detected["catalogs"].items() if models}

    roles = {role: plan_role(entries, catalogs) for role, entries in config["roles"].items()}
    used_lines = {(e["agent"], line_and_version(e["model"])[0]) for entries in config["roles"].values() for e in entries}
    new_lines = {
        agent: [m["id"] for line, m in newest_by_line(catalog).items() if (agent, line) not in used_lines]
        for agent, catalog in catalogs.items()
    }

    command = [sys.executable, os.path.join(SETUP_SCRIPTS, "write_config.py"), path, "--subscription"]
    for s in config["subscriptions"]:
        command.append(f"{s['agent']}:{s['plan']}" + (f":{s['monthly_usd']}" if s.get("monthly_usd") else ""))
    for role, steps in roles.items():
        command.append(f"--{role}")
        for s in steps:
            target = s["to"] or s
            command.append(spec(s["agent"], target["model"], target["effort"]))

    print(json.dumps({
        "config": path,
        "changes": sum(s["action"] != "keep" for steps in roles.values() for s in steps),
        "roles": roles,
        "new_lines": {agent: ids for agent, ids in new_lines.items() if ids},
        "write_command": command,
    }, indent=2))


if __name__ == "__main__":
    main()
