"""The open-pr skill's PR rules, checked on the gh command before it runs."""
import pathlib
import re
import shlex

GH_PR = re.compile(r"\bgh\s+pr\s+(create|edit)\b")
TITLE = re.compile(r"^(feat|fix|docs|refactor|test|chore|perf|build|ci|style|revert)(\([^)\s]+\))?!?: \S.*[^.]$")
SECTIONS = ["Why", "What changed", "Scope", "Tradeoffs", "Blast Radius", "Verification"]
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1\b", re.S)


def _args(command):
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None, []
    for i in range(len(tokens) - 2):
        if tokens[i] == "gh" and tokens[i + 1] == "pr" and tokens[i + 2] in ("create", "edit"):
            rest = []
            for t in tokens[i + 3:]:
                if t in ("&&", "||", ";", "|"):
                    break
                rest.append(t)
            return tokens[i + 2], rest
    return None, []


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
        if "<<" in body:
            m = HEREDOC.search(body) or HEREDOC.search(command)
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
    if not GH_PR.search(command):
        return []
    sub, args = _args(command)
    if not sub:
        return []
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
