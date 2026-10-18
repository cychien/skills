"""Find installed skills and read what guard enforces from them: playbook steps and principle titles."""
import os
import pathlib
import re
import subprocess

STEP = re.compile(r"^(\d+)\. (.+)$")
STEP_HEADING = re.compile(r"^(?:(?:Step|Phase|Pass)\s+)?(?:\d+|[A-Z])[.,:)]\s*(.+)$")


def roots(cwd):
    configured = os.environ.get("GUARD_SKILL_ROOTS")
    if configured:
        return [pathlib.Path(p) for p in configured.split(os.pathsep) if p]
    home = pathlib.Path.home()
    base = pathlib.Path(cwd or ".")
    return [base / ".claude/skills", base / ".agents/skills", home / ".claude/skills", home / ".agents/skills", home / ".codex/skills"]


def followed(path, cwd):
    """Whether reading this SKILL.md means following the skill: it sits under a skill root, or outside the
    working tree. A skill's own source inside the working tree is being authored, not followed."""
    base = os.path.abspath(cwd or ".")
    target = os.path.abspath(os.path.join(base, os.path.expanduser(path)))
    under = lambda t, root: os.path.commonpath([t, root]) == root
    if any(under(target, os.path.abspath(root)) for root in roots(cwd)):
        return True
    return not under(os.path.realpath(target), os.path.realpath(worktree(base)))


def worktree(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return cwd
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else cwd


def find(name, cwd):
    for root in roots(cwd):
        path = root / name / "SKILL.md"
        if path.is_file():
            return path
    return None


def frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    fields, nested = {}, None
    for line in head.splitlines():
        if nested and line.startswith("  "):
            key, _, value = line.strip().partition(": ")
            fields[nested][key] = value.strip().strip('"')
            continue
        nested = None
        if line.endswith(":") and ": " not in line:
            nested = line[:-1]
            fields[nested] = {}
            continue
        key, _, value = line.partition(": ")
        fields[key] = value.strip()
    return fields, body


def read(path):
    try:
        return pathlib.Path(path).expanduser().read_text()
    except OSError:
        return None


def is_playbook(path):
    """A skill is tracked when its body has steps in one of the shapes steps() recognizes."""
    return bool(steps(path))


def _numbered(lines):
    found, current = [], None
    for line in lines:
        m = STEP.match(line)
        if m:
            current = [int(m.group(1)), m.group(2)]
            found.append(current)
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            current[1] += " " + line.strip()
        elif not line.startswith((" ", "\t")):
            current = None
    return found


def steps(path):
    """The skill's procedure as [(number, title, full text, mandatory)], from the first shape present:
    the numbered items of a `## Steps` section, two or more step headings (`## 1.`, `## Step 1,`,
    `## Phase A:`, `## Pass 1:`), or a numbered list before the first `##` heading."""
    _, body = frontmatter(read(path) or "")
    sections, heading, lines = [], None, []
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((heading, lines))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    sections.append((heading, lines))
    for h, ls in sections:
        if h and h.lower() == "steps":
            found = _numbered(ls)
            if found:
                return [(n, title(t), t, "Mandatory" in t) for n, t in found]
    headed = [(m.group(1), "\n".join(ls)) for h, ls in sections if h and (m := STEP_HEADING.match(h))]
    if len(headed) >= 2:
        return [(i, name, f"{name}\n{text}", "Mandatory" in text) for i, (name, text) in enumerate(headed, 1)]
    found = _numbered(sections[0][1])
    return [(n, title(t), t, "Mandatory" in t) for n, t in found]


def title(text):
    text = text.replace("**", "")
    m = re.match(r"(.+?[.:])(\s|$)", text)
    return (m.group(1) if m else text)[:160]


def principles(cwd):
    """Lowercased principle title -> file stem, from the principles skill."""
    skill = find("principles", cwd)
    if not skill:
        return {}
    titles = {}
    for f in (skill.parent / "references" / "principles").glob("*.md"):
        m = re.search(r"^# (.+)$", read(f) or "", re.M)
        if m:
            titles[m.group(1).strip().lower()] = f.stem
    return titles
