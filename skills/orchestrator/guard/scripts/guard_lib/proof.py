"""Proof that an item was read: `todo show` prints its text with the principles it names, and a token of both."""
import hashlib
import pathlib
import re

from . import skills

INDEX = "../principles/SKILL.md"
PRINCIPLE = re.compile(r"\.\./principles/references/principles/([a-z0-9][a-z0-9-]*)\.md")


def principles_dir(item, cwd):
    """The principles skill beside the skill the item came from, else the installed one."""
    if item.get("source_path"):
        beside = pathlib.Path(item["source_path"]).parent.parent / "principles"
        if (beside / "SKILL.md").is_file():
            return beside
    found = skills.find("principles", cwd)
    return found.parent if found else None


def attachments(item, cwd):
    """[(path as the item names it, content or None when missing, principle stem or None)] in order of first mention."""
    text, found = item["text"], []
    base = principles_dir(item, cwd)
    if INDEX in text:
        body = skills.frontmatter(skills.read(base / "SKILL.md") or "")[1].strip() if base else None
        found.append((INDEX, body or None, None))
    for stem in dict.fromkeys(PRINCIPLE.findall(text)):
        content = skills.read(base / "references" / "principles" / f"{stem}.md") if base else None
        found.append((f"../principles/references/principles/{stem}.md", content, stem))
    return found


def token(item, cwd):
    digest = hashlib.sha256((item["text"] + "".join(c or "" for _, c, _ in attachments(item, cwd))).encode("utf-8"))
    return digest.hexdigest()[:6]


def render(item, cwd):
    source = f" (from {item['source']})" if item.get("source") else ""
    parts = [f"Item {item['n']}{source}:", item["text"]]
    for path, content, _ in attachments(item, cwd):
        parts += ["", f"--- {path} ---", content.strip() if content else "(not installed)"]
    parts += ["", f"token: {token(item, cwd)}"]
    return "\n".join(parts)
