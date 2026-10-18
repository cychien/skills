#!/usr/bin/env python3
"""Write the orchestrator model config in one fixed format, so the same choices always produce the same file.

usage: write_config.py <path> --subscription agent:plan[:monthly_usd] ... --planner agent:model[:effort] ... --executor agent:model[:effort] ... [--gitignore]

With --gitignore, <path> is appended to its repo's .gitignore unless git already ignores it.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile


def entry(spec):
    agent, _, rest = spec.partition(":")
    model, _, effort = rest.partition(":")
    if not agent or not model:
        raise argparse.ArgumentTypeError(f"expected agent:model[:effort], got '{spec}'")
    return {"agent": agent, "model": model, "effort": effort or None}


def subscription(spec):
    agent, _, rest = spec.partition(":")
    plan, _, usd = rest.partition(":")
    if not agent or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", plan):
        raise argparse.ArgumentTypeError(f"expected agent:plan[:monthly_usd] with a kebab-case plan, got '{spec}'")
    if plan == "api" and not usd:
        raise argparse.ArgumentTypeError(f"a metered api plan needs its monthly spend, as in {agent}:api:200, got '{spec}'")
    if not usd:
        return {"agent": agent, "plan": plan}
    try:
        amount = float(usd)
    except ValueError:
        amount = 0
    if amount <= 0:
        raise argparse.ArgumentTypeError(f"monthly_usd must be a positive number, got '{spec}'")
    return {"agent": agent, "plan": plan, "monthly_usd": int(amount) if amount.is_integer() else amount}


def git(path, *args):
    return subprocess.run(["git", "-C", os.path.dirname(path), *args], capture_output=True, text=True)


def ensure_ignored(path):
    root = git(path, "rev-parse", "--show-toplevel")
    if root.returncode != 0 or git(path, "check-ignore", "-q", path).returncode == 0:
        return None
    top = root.stdout.strip()
    rel = "/" + os.path.relpath(os.path.realpath(path), os.path.realpath(top))
    gitignore = os.path.join(top, ".gitignore")
    existing = open(gitignore).read() if os.path.exists(gitignore) else ""
    with open(gitignore, "a") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + rel + "\n")
    return gitignore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--subscription", nargs="+", type=subscription, required=True)
    parser.add_argument("--planner", nargs="+", type=entry, required=True)
    parser.add_argument("--executor", nargs="+", type=entry, required=True)
    parser.add_argument("--gitignore", action="store_true")
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = {
        "version": 2,
        "subscriptions": args.subscription,
        "roles": {"planner": args.planner, "executor": args.executor},
    }
    with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(path), delete=False) as f:
        f.write(json.dumps(config, indent=2) + "\n")
    os.replace(f.name, path)

    print(f"wrote {path}")
    gitignore = ensure_ignored(path) if args.gitignore else None
    if gitignore:
        print(f"added it to {gitignore}")


if __name__ == "__main__":
    main()
