#!/usr/bin/env python3
"""Profile where a Claude Code session spent its wall-clock time and tokens.

usage: profile.py <session.jsonl> [--since TEXT] [--until TEXT] [--json] [--slow SECONDS] [--context] [--record LABEL]

Reads the session transcript and every subagent transcript beside it (<session>/subagents/*.jsonl).
--since starts the window at the first user message containing TEXT.
--until ends it before the first later user message containing TEXT.
--context prints only the lead's current context size in tokens and exits.
--record appends one JSON line for the window to $PROFILE_LOG (default ~/.agents/profile/runs.jsonl) and still prints the table.
"""
import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

TOOL_TIMEOUT_S = 590
SUITE = re.compile(r"pnpm (?:-r )?(?:test|typecheck)\b|pnpm -r typecheck|vitest run(?! \S+\.spec)")
INSTANCE_UP = re.compile(r"hello\.mjs\"? up\b|\$H up\b|\bup (?:web|mac|ios)\b")
READ_CMD = re.compile(r"\b(?:cat|sed -n|head|tail)\s+(?:-\S+\s+)*(\S+\.(?:md|ts|tsx|mjs|py|json))")


def ts(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def load(path):
    rows = []
    with open(path) as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("timestamp"):
                rows.append(row)
    return rows


def context_tokens(usage):
    return sum(usage.get(key) or 0 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def lead_context(rows):
    for row in reversed(rows):
        message = row.get("message")
        if row.get("type") == "assistant" and isinstance(message, dict) and message.get("usage"):
            return context_tokens(message["usage"])
    return 0


def minute_of(moment, first):
    return int((moment - first).total_seconds() // 60)


def idle_minutes(lead_times, spans, first, last):
    busy = {minute_of(moment, first) for moment in lead_times}
    for began, ended in spans:
        busy.update(range(minute_of(began, first), minute_of(ended, first) + 1))
    return sum(1 for minute in range(minute_of(last, first) + 1) if minute not in busy)


class Window:
    def __init__(self):
        self.start = None
        self.end = None

    def holds(self, row):
        moment = ts(row["timestamp"])
        return (self.start is None or moment >= self.start) and (self.end is None or moment < self.end)


def first_prompt(rows, text, after):
    for row in rows:
        message = row.get("message")
        moment = ts(row["timestamp"])
        if (row.get("type") == "user" and isinstance(message, dict) and (after is None or moment > after)
                and text in text_of(message.get("content"))):
            return moment
    return None


def record_run(args, main_rows, window, spans, agents):
    lead_times = [ts(row["timestamp"]) for row in main_rows if window.holds(row)]
    moments = [*lead_times, *(edge for span in spans for edge in span)]
    first, last = min(moments), max(moments)
    tokens = Counter()
    for agent in agents.values():
        tokens.update(agent["tokens"])
    entry = {
        "label": args.record,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "since": args.since,
        "until": args.until,
        "wall_min": round((last - first).total_seconds() / 60, 1),
        "idle_min": idle_minutes(lead_times, spans, first, last),
        "agents": len(agents),
        "output_tokens": tokens["output_tokens"],
        "context_tokens": context_tokens(tokens),
        "lead_context_tokens": lead_context(main_rows),
        "timeouts": sum(agent["timeouts"] for agent in agents.values()),
    }
    log = Path(os.environ.get("PROFILE_LOG") or Path.home() / ".agents" / "profile" / "runs.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as handle:
        handle.write(json.dumps(entry) + "\n")


def profile_agent(rows, window, slow_s):
    rows = [row for row in rows if window.holds(row)]
    if not rows:
        return None
    usage, seen = Counter(), set()
    pending, tool_calls = {}, []
    reads, suites, ups, model = Counter(), 0, 0, None
    for row in rows:
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        if row.get("type") == "assistant":
            model = message.get("model") or model
            if message.get("id") not in seen and message.get("usage"):
                seen.add(message.get("id"))
                for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                    usage[key] += message["usage"].get(key) or 0
        for part in message.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                arguments = json.dumps(part.get("input"))
                pending[part["id"]] = (ts(row["timestamp"]), part.get("name"), arguments)
                suites += len(SUITE.findall(arguments))
                ups += bool(INSTANCE_UP.search(arguments))
                if part.get("name") == "Read":
                    reads[(part.get("input") or {}).get("file_path", "")] += 1
                for match in READ_CMD.findall(arguments):
                    reads[match] += 1
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in pending:
                began, name, arguments = pending.pop(part["tool_use_id"])
                tool_calls.append(((ts(row["timestamp"]) - began).total_seconds(), name, arguments))
    first, last = ts(rows[0]["timestamp"]), ts(rows[-1]["timestamp"])
    wall = (last - first).total_seconds()
    tool_wait = sum(seconds for seconds, name, _ in tool_calls if name not in ("Agent", "AskUserQuestion"))
    return {
        "model": model,
        "start": first.isoformat(),
        "wall_min": round(wall / 60, 1),
        "tool_wait_min": round(tool_wait / 60, 1),
        "tool_calls": len(tool_calls),
        "timeouts": sum(1 for seconds, _, _ in tool_calls if seconds >= TOOL_TIMEOUT_S),
        "slow_calls": [
            {"min": round(seconds / 60, 1), "tool": name, "input": arguments[:160]}
            for seconds, name, arguments in sorted(tool_calls, reverse=True)
            if seconds >= slow_s and name not in ("Agent", "AskUserQuestion")
        ][:8],
        "suite_runs": suites,
        "instance_ups": ups,
        "reads": dict(reads),
        "tokens": dict(usage),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--slow", type=float, default=300)
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--record", metavar="LABEL")
    args = parser.parse_args()
    session = Path(args.session)
    main_rows = load(session)
    if args.context:
        print(lead_context(main_rows))
        return
    window = Window()
    if args.since:
        window.start = first_prompt(main_rows, args.since, None)
        if window.start is None:
            sys.exit(f"profile: no user message contains {args.since!r}")
    if args.until:
        window.end = first_prompt(main_rows, args.until, window.start)
        if window.end is None:
            sys.exit(f"profile: no user message after the window start contains {args.until!r}")
    agents = {"lead": profile_agent(main_rows, window, args.slow)}
    spans = []
    for path in sorted((session.parent / session.stem / "subagents").glob("*.jsonl")):
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        rows = load(path)
        result = profile_agent(rows, window, args.slow)
        if result:
            times = [ts(row["timestamp"]) for row in rows if window.holds(row)]
            spans.append((min(times), max(times)))
            result["description"] = meta.get("description", "")
            agents[path.stem.removeprefix("agent-")] = result
    agents = {name: value for name, value in agents.items() if value}
    if args.record:
        record_run(args, main_rows, window, spans, agents)
    if args.json:
        print(json.dumps(agents, indent=2))
        return
    total = Counter()
    print(f"{'agent':<18} {'model':<18} {'wall':>6} {'wait':>6} {'calls':>5} {'t/o':>3} {'suite':>5} {'ups':>3} {'out_k':>6} {'in_k':>7}  description")
    for name, agent in sorted(agents.items(), key=lambda item: item[1]["start"]):
        tokens = agent["tokens"]
        fresh = tokens.get("input_tokens", 0) + tokens.get("cache_creation_input_tokens", 0)
        for key, value in tokens.items():
            total[key] += value
        print(
            f"{name[:18]:<18} {str(agent['model'])[:18]:<18} {agent['wall_min']:>5}m {agent['tool_wait_min']:>5}m "
            f"{agent['tool_calls']:>5} {agent['timeouts']:>3} {agent['suite_runs']:>5} {agent['instance_ups']:>3} "
            f"{tokens.get('output_tokens', 0) / 1000:>6.0f} {(fresh + tokens.get('cache_read_input_tokens', 0)) / 1000:>7.0f}  "
            f"{agent.get('description', '')[:40]}"
        )
    repeated = Counter()
    for agent in agents.values():
        for path in agent["reads"]:
            repeated[Path(path).name] += 1
    print(f"\ntotal output {total['output_tokens'] / 1e6:.2f}M, cache read {total['cache_read_input_tokens'] / 1e6:.1f}M, "
          f"cache write {total['cache_creation_input_tokens'] / 1e6:.1f}M, uncached input {total['input_tokens'] / 1e6:.2f}M")
    print("files read by the most agents: " + ", ".join(f"{name} x{count}" for name, count in repeated.most_common(8)))
    slow = sorted(
        ((call["min"], name, call["input"]) for name, agent in agents.items() for call in agent["slow_calls"]),
        reverse=True,
    )
    print(f"\nslowest tool calls (>= {args.slow:.0f}s):")
    for minutes, name, arguments in slow[:15]:
        print(f"  {minutes:>5}m {name[:10]:<10} {arguments[:120]}")


if __name__ == "__main__":
    main()
