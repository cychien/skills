#!/usr/bin/env python3
"""Pool salvo runs from one or more arms into a blinded packet for a judge.

usage: blind.py --packet <dir> --key <file> --skill <name> <arm>=<salvo out dir> ...

Every successful run gets a shuffled label (A, B, ...) shared across arms, so the
judge cannot tell runs, models, or arms apart. Each label holds result.md, the
workspace changes, and a transcript.md with model identifiers removed. The key that
maps labels back to arm and model goes to --key, which must stay out of the packet.
Failed runs are left out of the packet and listed in the key as dropouts.
It refuses arms that are still running, and arms whose projects differ anywhere
outside the skill's own folders, since then the arms test more than the skill.
"""
import argparse
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys


def fenced(text, lang=""):
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


def tool_result_text(content):
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if c.get("type") == "text" else f"[{c.get('type')}]" for c in content)
    return content if isinstance(content, str) else json.dumps(content, indent=2)


def claude_blocks(events):
    for e in events:
        if e.get("type") not in ("assistant", "user"):
            continue
        scope = " (subagent)" if e.get("parent_tool_use_id") else ""
        for c in e.get("message", {}).get("content", []):
            if not isinstance(c, dict):
                continue
            kind = c.get("type")
            if kind == "text" and c.get("text", "").strip():
                yield f"### Assistant{scope}\n\n{c['text'].strip()}"
            elif kind == "thinking" and (c.get("thinking") or "").strip():
                yield f"### Thinking{scope}\n\n{c['thinking'].strip()}"
            elif kind == "tool_use":
                yield f"### Tool call{scope}: {c.get('name')}\n\n" + fenced(json.dumps(c.get("input"), indent=2, ensure_ascii=False), "json")
            elif kind == "tool_result":
                label = "Tool error" if c.get("is_error") else "Tool result"
                yield f"### {label}{scope}\n\n" + fenced(tool_result_text(c.get("content")))


def codex_blocks(events):
    for e in events:
        if e.get("type") in ("error", "turn.failed"):
            yield "### Error\n\n" + fenced(json.dumps(e, indent=2, ensure_ascii=False), "json")
        if e.get("type") != "item.completed":
            continue
        item = e["item"]
        kind = item.get("type")
        if kind == "agent_message":
            yield f"### Assistant\n\n{item.get('text', '').strip()}"
        elif kind == "reasoning" and item.get("text", "").strip():
            yield f"### Thinking\n\n{item['text'].strip()}"
        elif kind == "command_execution":
            yield "### Tool call: shell\n\n" + fenced(item.get("command", ""), "sh")
            label = "Tool result" if item.get("exit_code") == 0 else f"Tool error (exit {item.get('exit_code')})"
            yield f"### {label}\n\n" + fenced(item.get("aggregated_output", ""))
        elif kind == "file_change":
            yield "### File changes\n\n" + "\n".join(f"- {c.get('kind')}: {c.get('path')}" for c in item.get("changes", []))
        else:
            fields = {k: v for k, v in item.items() if k not in ("id", "type")}
            yield f"### {kind}\n\n" + fenced(json.dumps(fields, indent=2, ensure_ascii=False), "json")


def read_events(path):
    events = []
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def scrub(text, run):
    """Replace everything that ties a run to its model or arm, longest first so paths stay whole."""
    workspaces = {run.get("workspace_root"), run.get("checkout"), run.get("work")} - {None}
    for path in sorted(workspaces | {os.path.realpath(p) for p in workspaces}, key=len, reverse=True):
        text = text.replace(path, "[workspace]")
    for needle in sorted({run["model"], run["spec"], run["label"], run["dir"]}, key=len, reverse=True):
        text = text.replace(needle, "[redacted]")
    return text


def write_label(run, dest):
    os.makedirs(dest)
    events = read_events(run["transcript"])
    blocks = claude_blocks(events) if run["agent"] == "claude" else codex_blocks(events)
    with open(os.path.join(dest, "transcript.md"), "w") as f:
        f.write(scrub("# Transcript\n" + "".join(f"\n{b}\n" for b in blocks), run))
    with open(run["result"], errors="ignore") as src, open(os.path.join(dest, "result.md"), "w") as f:
        f.write(scrub(src.read(), run))
    if run.get("patch"):
        with open(run["patch"], errors="ignore") as src, open(os.path.join(dest, "changes.patch"), "w") as f:
            # Blob hashes on index lines differ per arm whenever a touched file differs.
            f.write(re.sub(r"(?m)^index [0-9a-f]+\.\.[0-9a-f]+.*\n", "", src.read()))
    elif run.get("changed_files"):
        shutil.copytree(run["work"], os.path.join(dest, "files"), symlinks=True)


def project_files(manifest, skill):
    """Path -> blob of the arm's starting project, minus the skill under test."""
    if not manifest.get("repo"):
        return None
    listing = subprocess.run(["git", "-C", manifest["repo"], "ls-tree", "-r", manifest["base_tree"]],
                             capture_output=True, text=True, check=True).stdout
    skill_dirs = tuple(f"{root}/skills/{skill}" for root in (".agents", ".claude"))
    files = {}
    for line in listing.splitlines():
        meta, path = line.split("\t", 1)
        if not any(path == d or path.startswith(d + "/") for d in skill_dirs):
            files[path] = meta.split()[2]
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--skill", required=True, help="name of the skill under test")
    parser.add_argument("arms", nargs="+", help="<arm>=<salvo out dir>")
    args = parser.parse_args()
    packet, key_path = os.path.abspath(args.packet), os.path.abspath(args.key)
    if os.path.commonpath([packet, key_path]) == packet:
        sys.exit("--key must live outside --packet, or the judge can unblind itself")
    if os.path.exists(packet):
        sys.exit(f"{packet} already exists")

    runs, dropouts, projects = [], [], {}
    for arm_spec in args.arms:
        arm, _, out = arm_spec.partition("=")
        manifest = json.load(open(os.path.join(out, "salvo.json")))
        if manifest.get("status") != "done":
            sys.exit(f"arm '{arm}' has not finished; wait until {out}/salvo.json says \"status\": \"done\"")
        projects[arm] = project_files(manifest, args.skill)
        for run in manifest["runs"]:
            (runs if run.get("ok") else dropouts).append({"arm": arm, **run})
    empty = [a.partition("=")[0] for a in args.arms if not any(r["arm"] == a.partition("=")[0] for r in runs)]
    if empty:
        reasons = sorted({r.get("error") or "unknown" for r in dropouts})
        sys.exit(f"no successful runs in arm(s) {empty}; nothing to compare. Errors: {reasons}")
    first_arm, first = next(iter(projects.items()))
    for arm, files in projects.items():
        if files != first:
            differing = sorted(p for p in set(files or {}) | set(first or {}) if (files or {}).get(p) != (first or {}).get(p))
            sys.exit(f"arms '{first_arm}' and '{arm}' differ outside the skill: {differing[:10]}")
    random.SystemRandom().shuffle(runs)
    if len(runs) > 26:
        sys.exit("more than 26 runs; split the packet")

    os.makedirs(packet)
    key = {"labels": {}, "dropouts": [{"arm": r["arm"], "spec": r["spec"], "error": r.get("error")} for r in dropouts]}
    if len(runs) > len(string.ascii_uppercase):
        sys.exit(f"{len(runs)} runs exceed the {len(string.ascii_uppercase)} labels A-Z; split them across packets")
    for letter, run in zip(string.ascii_uppercase, runs, strict=False):
        write_label(run, os.path.join(packet, letter))
        key["labels"][letter] = {"arm": run["arm"], "spec": run["spec"], "run_dir": run["dir"]}
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "w") as f:
        json.dump(key, f, indent=2)
    print(json.dumps({"packet": packet, "labels": sorted(key["labels"]), "dropouts": len(dropouts)}))


if __name__ == "__main__":
    main()
