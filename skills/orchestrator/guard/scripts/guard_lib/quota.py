"""Usage limits shared by every session: which agent's subscription is limited until when, and who takes its work."""
import calendar
import contextlib
import datetime
import fcntl
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time

from . import shell, skills

AGENTS = ("claude", "codex")
ROLES = ("planner", "executor")
DEFAULT_WAIT_S = 3600
CLOCK_SLACK_S = 600
SOURCE_LIMIT = 200
WHERE_TIMEOUT = 10
CODEX_HIT = re.compile(r"you(?:'|’)ve hit your usage limit", re.I)
CODEX_AGAIN = re.compile(r"try again (at|in) ([^\n]+)", re.I)
CLAUDE_HIT = re.compile(r"usage limit", re.I)
CLAUDE_RESET = re.compile(r"\bresets?(?: at)? ([^\n]+)", re.I)
CLAUDE_EPOCH = re.compile(r"usage limit reached\|(\d{10})\b", re.I)
MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", re.I)
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
CLOCK = re.compile(r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b\.?|(?<![\d:])(\d{1,2}):(\d{2})(?![\d])", re.I)
DURATION = re.compile(r"(\d+)\s*(day|hour|hr|minute|min)s?\b", re.I)
SALVO_VALUED = {"--out", "--timeout", "--hide-skill"}
SPEC = re.compile(r"^(claude|codex):[^:\s]+(?::[^:\s]+)?$")
AGENT_NAME = re.compile(r"\b(claude(?: code)?|codex)\b", re.I)
REAL = re.compile(r"^- Agent:\s*real\b", re.I | re.M)
FALLBACK = ["a candidate that keeps every separation rule",
            "one that relaxes \"reviewer from a different family\"",
            "one that relaxes \"verifier on a different entry from the executor\"",
            "a candidate from the other role"]


def home():
    return pathlib.Path(os.environ.get("ORCHESTRATOR_HOME") or pathlib.Path.home() / ".agents" / "orchestrator")


def iso(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="minutes")


def clock(ts):
    moment = datetime.datetime.fromtimestamp(ts)
    return moment.strftime("%H:%M") if moment.date() == datetime.date.today() else moment.strftime("%Y-%m-%d %H:%M")


def epoch(text):
    try:
        moment = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return moment.timestamp()


def limits(now=None):
    """{agent: entry} for every limit still in force."""
    try:
        data = json.loads((home() / "limits.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    now = now or time.time()
    return {a: e for a, e in data.items() if isinstance(e, dict) and (epoch(e.get("until")) or 0) > now}


def record(agent, until, source, now=None):
    now = now or time.time()
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ".limits.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = limits(now)
        current[agent] = {"until": iso(until), "seen": iso(now), "source": source.strip()[:SOURCE_LIMIT]}
        tmp = folder / f"limits.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(current, indent=2) + "\n")
        os.replace(tmp, folder / "limits.json")


def when(text, now):
    """The moment a limit message names, in epoch seconds: a duration, an ISO time, or a clock time on the date it gives
    (local time zone), else its next occurrence. None when the text names no time."""
    text = re.sub(r"\([^)]*\)", " ", text)
    stripped = text.strip().rstrip(".")
    if (moment := epoch(stripped.split()[0] if stripped else "")) and "T" in stripped.split()[0]:
        return moment
    lead = text.strip().lower()
    if lead.startswith("in ") or (DURATION.match(lead) and not CLOCK.match(lead)):
        spans = DURATION.findall(lead)
        if spans:
            seconds = {"day": 86400, "hour": 3600, "hr": 3600, "minute": 60, "min": 60}
            return now + sum(int(n) * seconds[unit.lower()] for n, unit in spans)
    hit = CLOCK.search(text)
    if not hit:
        return None
    if hit.group(1):
        hour, minute = int(hit.group(1)) % 12 + (12 if hit.group(3).lower() == "p" else 0), int(hit.group(2) or 0)
    else:
        hour, minute = int(hit.group(4)), int(hit.group(5))
    if hour > 23 or minute > 59:
        return None
    today = datetime.datetime.fromtimestamp(now)
    if day := ISO_DATE.search(text):
        date = datetime.date(int(day.group(1)), int(day.group(2)), int(day.group(3)))
    elif day := MONTH.search(text):
        month = list(calendar.month_abbr).index(day.group(1).title())
        date = datetime.date(int(day.group(3) or today.year), month, int(day.group(2)))
    else:
        moment = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment.timestamp() < now - CLOCK_SLACK_S:
            moment += datetime.timedelta(days=1)
        return moment.timestamp()
    return datetime.datetime(date.year, date.month, date.day, hour, minute).timestamp()


def scan(text, now=None):
    """[(agent, until, source line)] for each usage-limit message in text."""
    now = now or time.time()
    found = []
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        window = " ".join(lines[i:i + 2])
        if CODEX_HIT.search(line):
            again = CODEX_AGAIN.search(window)
            if again:
                moment = when(("in " if again.group(1).lower() == "in" else "") + again.group(2), now)
                found.append(("codex", moment or now + DEFAULT_WAIT_S, line))
        elif stamp := CLAUDE_EPOCH.search(line):
            found.append(("claude", float(stamp.group(1)), line))
        elif CLAUDE_HIT.search(line) and (reset := CLAUDE_RESET.search(window)):
            found.append(("claude", when(reset.group(1), now) or now + DEFAULT_WAIT_S, line))
    return found


def runs_agent(command):
    """The agents whose CLI a shell line runs headless: codex, and claude with -p or --print."""
    found = set()
    for tokens in shell.commands(command):
        name, rest = shell.script(tokens)
        if name == "codex" or (name == "claude" and {"-p", "--print"} & set(rest)):
            found.add(name)
    return found


def launches(command):
    """[(agent, spec)] for each agent a shell line starts: salvo.py run entries and codex exec."""
    found = []
    for tokens in shell.commands(command):
        name, rest = shell.script(tokens)
        if name == "codex" and "exec" in rest:
            found.append(("codex", "codex exec"))
        elif name == "salvo.py" and rest[:1] == ["run"]:
            skip = False
            for token in rest[1:]:
                if skip:
                    skip = False
                elif token in SALVO_VALUED:
                    skip = True
                elif SPEC.match(token):
                    found.append((token.split(":")[0], token))
    return found


def config_paths(cwd):
    bases = [pathlib.Path(cwd or ".")]
    for args in (["rev-parse", "--show-toplevel"], ["rev-parse", "--path-format=absolute", "--git-common-dir"]):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            out = subprocess.run(["git", "-C", str(bases[0]), *args], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                path = pathlib.Path(out.stdout.strip())
                bases.append(path.parent if path.name == ".git" else path)
    return [b / ".agents" / "orchestrator" / "models.json" for b in dict.fromkeys(bases)] + [home() / "models.json"]


def config(cwd):
    for path in config_paths(cwd):
        with contextlib.suppress(OSError, json.JSONDecodeError):
            return json.loads(path.read_text())
    return None


def spec(entry):
    return ":".join(p for p in (entry.get("agent"), entry.get("model"), entry.get("effort")) if p)


def avoided(entry, avoid):
    full = spec(entry)
    return any(full == a or full.startswith(a + ":") for a in avoid)


def candidates(cwd, role):
    return [e for e in ((config(cwd) or {}).get("roles") or {}).get(role, []) if e.get("agent") and e.get("model")]


def pick(cwd, role, avoid=(), relax=False, now=None):
    """(entry, relaxation or None, None) for the first usable candidate, else (None, None, why)."""
    limited = limits(now)
    other = ROLES[1 - ROLES.index(role)]
    entries = candidates(cwd, role)
    pool = entries + (candidates(cwd, other) if relax else [])
    if not pool:
        return None, None, f"the orchestrator config has no {role} entries"
    free = [e for e in entries if e["agent"] not in limited]
    tiers = [(None, [e for e in free if not avoided(e, avoid)])]
    if relax:
        tiers += [(FALLBACK[1] if role == "planner" else FALLBACK[2], [e for e in free if avoided(e, avoid)]),
                  (f"{FALLBACK[3]} ({other})", [e for e in candidates(cwd, other) if e["agent"] not in limited and not avoided(e, avoid)])]
    for relaxed, found in tiers:
        if found:
            return found[0], relaxed, None
    if all(e["agent"] in limited for e in (pool if relax else entries)):
        earliest = min(epoch(limited[e["agent"]]["until"]) for e in pool if e["agent"] in limited)
        return None, None, f"every candidate is limited until {clock(earliest)}; hold until then"
    if relax:
        return None, None, "every candidate left is avoided or limited; drop an --avoid or hold until a limit resets"
    return None, None, f"every {role} candidate is avoided; run `quota pick --role {role} --relax` for the fallback order"


def picks(cwd, avoid=()):
    lines = []
    for role in ROLES:
        entry, _, why = pick(cwd, role, avoid)
        lines.append(f"   {role}: {spec(entry) if entry else why}")
    return "\n".join(lines)


def guard_cli():
    return f"python3 {shlex.quote(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'guard.py'))}"


def spawn_problem(command, cwd, lead):
    """A deny message when a shell line starts an agent that is limited or reserved for the real-agent checks of the branch
    it runs on, read from the directory a leading cd moves it to. A cd guard cannot follow reserves nothing, because a
    false deny stops every agent while a missed reservation costs one run's quota."""
    started = launches(command)
    if not started:
        return None
    where = shell.workdir(command, cwd)
    cwd = where or cwd
    limited = limits()
    for agent, launched in started:
        if agent in limited:
            entry = limited[agent]
            return (f"{agent} is limited until {clock(epoch(entry['until']))} ({entry.get('source', '')}), so `{launched}` would stall. "
                    f"Hand the work to the next candidate (`{guard_cli()} quota pick --role <role>`):\n{picks(cwd)}")
    if any(rest[:1] == ["rerun"] for rest in shell.invocations(command, "verify.py")):
        return None
    others = {a for a, _ in started if a != lead}
    if not others or where is None:
        return None
    held = reserved(cwd, lead)
    clash = sorted(others & set(held))
    if not clash:
        return None
    avoid = " ".join(f"--avoid {a}" for a in clash)
    return (f"{', '.join(clash)} is reserved for this branch's real-agent checks ({', '.join(sorted({c for a in clash for c in held[a]}))}), "
            f"so its quota stays for them. Use another candidate (`{guard_cli()} quota pick --role <role> {avoid}`):\n{picks(cwd, clash)}")


def plan_text(cwd):
    found = skills.find("verify", cwd)
    script_path = found.parent / "scripts" / "verify.py" if found else None
    if not script_path or not script_path.is_file():
        return None
    try:
        out = subprocess.run([sys.executable, str(script_path), "where"], cwd=cwd, capture_output=True, text=True, timeout=WHERE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    directory = pathlib.Path(out.stdout.strip().splitlines()[-1])
    for path in plan_candidates(directory):
        text = skills.read(path)
        if text:
            return text
    return None


def plan_candidates(directory):
    """The branch's plan: the adopted phase plan a record in the verification directory points to, else its own copy."""
    found = []
    for record in sorted(directory.glob("*.json")):
        with contextlib.suppress(OSError, json.JSONDecodeError):
            data = json.loads(record.read_text())
            for value in (data.values() if isinstance(data, dict) else []):
                if isinstance(value, str) and value.endswith("plan.md"):
                    found.append(pathlib.Path(value))
    return found + [directory / "plan.md"]


def reserved(cwd, lead):
    """{agent: [check ids]} the plan's `- Agent: real` checks drive, other than the lead's own agent."""
    text = plan_text(cwd)
    if not text or not REAL.search(text):
        return {}
    preamble, *checks = re.split(r"^(?=### )", text, flags=re.M)
    held = {}
    for check in checks:
        if not REAL.search(check):
            continue
        named = {m.lower().split()[0] for m in AGENT_NAME.findall(check)} or {m.lower().split()[0] for m in AGENT_NAME.findall(preamble)} or set(AGENTS)
        ident = re.match(r"### ([^\s.:]+)", check)
        for agent in named - {lead}:
            held.setdefault(agent, []).append(ident.group(1) if ident else "?")
    return held


def status(now=None):
    current = limits(now)
    if not current:
        return "No agent is limited."
    return "\n".join(f"{a}: limited until {clock(epoch(e['until']))} (seen {e.get('seen')}; {e.get('source', '')})" for a, e in sorted(current.items()))
