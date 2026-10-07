#!/usr/bin/env python3
"""Report agent CLIs, their local model catalogs, and model usage history as JSON."""
import argparse
import collections
import glob
import json
import os
import shutil
import subprocess
import time

HOME = os.path.expanduser("~")
KNOWN_CLIS = ["claude", "codex", "gemini", "opencode", "cursor-agent", "amp", "copilot", "qwen", "droid", "goose", "aider"]


def run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def detect_clis():
    found = {}
    for name in KNOWN_CLIS:
        path = shutil.which(name)
        if path:
            found[name] = {"path": path, "version": run([name, "--version"], timeout=15).strip().splitlines()[:1]}
    return found


def claude_catalog():
    files = glob.glob(os.path.join(HOME, ".claude/cache/model-catalog/*-cc.json"))
    if not files:
        return None
    data = json.load(open(max(files, key=os.path.getmtime)))
    models = []
    for m in data["catalog"]["config"]["models"]:
        thinking = m.get("thinking") or {}
        models.append({
            "id": m["id"],
            "name": m.get("name"),
            "description": m.get("description"),
            "notice": (m.get("notice") or {}).get("text"),
            "section": m.get("section"),
            "efforts": [e["id"] for e in thinking.get("effort_options", [])],
        })
    return models


def codex_catalog():
    raw = run(["codex", "debug", "models"]) if shutil.which("codex") else ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        cache = os.path.join(HOME, ".codex/models_cache.json")
        if not os.path.exists(cache):
            return None
        data = json.load(open(cache))
    models = []
    for m in sorted(data.get("models", []), key=lambda m: m.get("priority", 999)):
        if m.get("visibility") != "list":
            continue
        models.append({
            "id": m["slug"],
            "name": m.get("display_name"),
            "description": m.get("description"),
            "efforts": [r["effort"] for r in m.get("supported_reasoning_levels", [])],
            "effort_descriptions": {r["effort"]: r.get("description") for r in m.get("supported_reasoning_levels", [])},
        })
    return models


def claude_usage(since, counts):
    for path in glob.glob(os.path.join(HOME, ".claude/projects/*/*.jsonl")):
        if os.path.getmtime(path) < since:
            continue
        combos = set()
        with open(path, errors="ignore") as f:
            for line in f:
                if '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant" or d.get("isSidechain"):
                    continue
                model = d.get("message", {}).get("model")
                if not model or model.startswith("<"):
                    continue
                interactive = not str(d.get("entrypoint", "")).startswith("sdk")
                combos.add((model, d.get("effort"), interactive))
        for model, effort, interactive in combos:
            counts[("claude", model, effort)]["interactive" if interactive else "automated"] += 1


def codex_usage(since, counts):
    for path in glob.glob(os.path.join(HOME, ".codex/sessions/**/*.jsonl"), recursive=True):
        if os.path.getmtime(path) < since:
            continue
        source, combos = None, set()
        with open(path, errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "session_meta":
                    source = d["payload"].get("source")
                elif d.get("type") == "turn_context":
                    p = d["payload"]
                    combos.add((p.get("model"), p.get("effort")))
        if not isinstance(source, str):
            continue  # Codex-internal subagents such as the auto-review guardian
        for model, effort in combos:
            counts[("codex", model, effort)]["interactive" if source in ("cli", "vscode") else "automated"] += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    since = time.time() - args.days * 86400
    counts = collections.defaultdict(collections.Counter)
    claude_usage(since, counts)
    codex_usage(since, counts)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["interactive"], -kv[1]["automated"]))
    usage = [
        {"agent": a, "model": m, "effort": e, "interactive_sessions": c["interactive"], "automated_sessions": c["automated"]}
        for (a, m, e), c in ranked[: args.top]
    ]

    print(json.dumps({
        "clis": detect_clis(),
        "catalogs": {"claude": claude_catalog(), "codex": codex_catalog()},
        "usage": {"days": args.days, "ranked_by": "interactive_sessions", "top": usage},
    }, indent=2))


if __name__ == "__main__":
    main()
