"""The open-pr skill's PR rules, checked on the gh command before it runs."""
import pathlib
import re

from . import shell

TITLE = re.compile(r"^(feat|fix|docs|refactor|test|chore|perf|build|ci|style|revert)(\([^)\s]+\))?!?: (?=\S).*[^.]$")
SECTIONS = ["Not ready to merge", "Why", "What changed", "Scope", "Tradeoffs", "Blast Radius", "Verification"]
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1\b", re.S)


def _invocations(command):
    """(create or edit, its arguments) for each gh pr create or gh pr edit the shell line runs."""
    for tokens in shell.commands(command):
        name, rest = shell.script(tokens)
        if name == "gh" and rest[:1] == ["pr"] and rest[1:2] in (["create"], ["edit"]):
            yield rest[1], rest[2:]


def _value(args, *names):
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if n.startswith("--") and a.startswith(n + "="):
                return a[len(n) + 1:]
    return None


def _body(args, command, cwd):
    body = _value(args, "--body", "-b")
    if body is not None:
        if "$(" in body or "`" in body:
            m = HEREDOC.search(command)
            return m.group(2) if m else None
        return body
    body_file = _value(args, "--body-file", "-F")
    if body_file and body_file != "-":
        try:
            return (pathlib.Path(cwd or ".") / body_file).read_text()
        except OSError:
            return None
    return None


def problems(command, cwd=None):
    """Rule violations in a gh pr create/edit command, or [] when it complies or is not one."""
    found = []
    for sub, args in _invocations(command):
        found += [p for p in _problems(sub, args, command, cwd) if p not in found]
    return found


def _problems(sub, args, command, cwd):
    found = []
    title = _value(args, "--title", "-t")
    if title is not None and not TITLE.match(title.strip()):
        found.append(f"Title {title!r} is not Conventional Commits `type(scope): subject` with no trailing period.")
    if sub == "create" and ("--draft" in args or "-d" in args):
        found.append("Open every PR ready, never as a draft. Drop `--draft`.")
    body = _body(args, command, cwd)
    if body is not None:
        headings = re.findall(r"^## (.+?)\s*$", body, re.M)
        unknown = [h for h in headings if h not in SECTIONS]
        if unknown:
            found.append(f"Description headings must come from {', '.join(SECTIONS)}; found {', '.join(unknown)}.")
        known = [h for h in headings if h in SECTIONS]
        if known != sorted(known, key=SECTIONS.index):
            found.append(f"Description sections go in this order: {', '.join(SECTIONS)}.")
        if "Scope" not in headings:
            found.append("The description needs a `## Scope` section; it is always required.")
    return found
