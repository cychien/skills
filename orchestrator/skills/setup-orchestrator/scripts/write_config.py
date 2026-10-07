#!/usr/bin/env python3
"""Write the orchestrator model config in one fixed format, so the same choices always produce the same file.

usage: write_config.py <path> --budget <level> --planner agent:model[:effort] ... --executor agent:model[:effort] ... [--gitignore]

With --gitignore, <path> is appended to its repo's .gitignore unless git already ignores it.
"""
import argparse
import json
import os
import subprocess


def entry(spec):
    agent, _, rest = spec.partition(":")
    model, _, effort = rest.partition(":")
    if not agent or not model:
        raise argparse.ArgumentTypeError(f"expected agent:model[:effort], got '{spec}'")
    return {"agent": agent, "model": model, "effort": effort or None}


def git(path, *args):
    return subprocess.run(["git", "-C", os.path.dirname(path), *args], capture_output=True, text=True)


def ensure_ignored(path):
    root = git(path, "rev-parse", "--show-toplevel")
    if root.returncode != 0 or git(path, "check-ignore", "-q", path).returncode == 0:
        return None
    top = root.stdout.strip()
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(top))
    gitignore = os.path.join(top, ".gitignore")
    existing = open(gitignore).read() if os.path.exists(gitignore) else ""
    with open(gitignore, "a") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + rel + "\n")
    return gitignore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--budget", required=True, choices=["unlimited", "large", "medium", "small"])
    parser.add_argument("--planner", nargs="+", type=entry, required=True)
    parser.add_argument("--executor", nargs="+", type=entry, required=True)
    parser.add_argument("--gitignore", action="store_true")
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = {"version": 1, "budget": args.budget, "roles": {"planner": args.planner, "executor": args.executor}}
    with open(path, "w") as f:
        f.write(json.dumps(config, indent=2) + "\n")

    print(f"wrote {path}")
    gitignore = ensure_ignored(path) if args.gitignore else None
    if gitignore:
        print(f"added it to {gitignore}")


if __name__ == "__main__":
    main()
