#!/usr/bin/env python3
"""Check that every skill installs and loads the same way in every agent.

usage: validate.py [repo root]

Skills live at skills/<category>/<name>/. Installers drop the category, so a skill
reaches another by name, never by path, and names are unique across categories.
"""
import json
import pathlib
import re
import sys

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_REF = re.compile(r"`([a-z0-9-]+)` skill")
PATH_REF = re.compile(r"\.\./([a-z0-9-]+)/")
CODEX_MANUAL_ONLY = re.compile(r"^policy:\n\s+allow_implicit_invocation:\s*false\s*$", re.M)


def frontmatter(text):
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("missing frontmatter")
    fields = {}
    for line in lines[1 : lines.index("---", 1)]:
        key, sep, value = line.partition(": ")
        if not sep or not re.fullmatch(r"[a-z-]+", key):
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        value = value.strip()
        if value.startswith('"'):
            value = json.loads(value)
        elif value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        fields[key] = value
    return fields


def is_manual_only(fields):
    return fields.get("disable-model-invocation") == "true"


def check_skill(skill_dir, fields, body, skills):
    errors = []
    name = fields.get("name", "")
    if not NAME.match(name) or len(name) > 64:
        errors.append(f"invalid name {name!r}")
    if name != skill_dir.name:
        errors.append(f"name {name!r} does not match folder {skill_dir.name!r}")
    if not 1 <= len(fields.get("description", "")) <= 1024:
        errors.append("description must be 1-1024 characters")
    if len(fields.get("compatibility", "")) > 500:
        errors.append("compatibility must be at most 500 characters")
    for ref in set(PATH_REF.findall(body)) & skills.keys():
        errors.append(f"reaches ../{ref}/ by path; write 'the `{ref}` skill' instead")
    for ref in set(NAME_REF.findall(body)) - {name}:
        if ref not in skills:
            errors.append(f"references missing skill {ref!r}")
        elif is_manual_only(skills[ref]):
            errors.append(f"references {ref!r}, which is manual-only, so agents cannot load it")
    if is_manual_only(fields):
        openai_yaml = skill_dir / "agents" / "openai.yaml"
        if not openai_yaml.is_file() or not CODEX_MANUAL_ONLY.search(openai_yaml.read_text()):
            errors.append("manual-only in Claude Code but not in Codex: add agents/openai.yaml with policy.allow_implicit_invocation: false")
    return errors


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    skill_files = sorted(root.glob("skills/**/SKILL.md"))
    if not skill_files:
        sys.exit(f"no skills/<category>/<name>/SKILL.md under {root.resolve()}")
    errors = []
    parsed = {}
    for f in skill_files:
        d = f.parent
        if len(d.relative_to(root / "skills").parts) != 2:
            errors.append(f"{d}: must sit at skills/<category>/<name>/")
            continue
        if d.name in parsed:
            errors.append(f"{d}: name collides with {parsed[d.name][0]} once installed")
            continue
        try:
            text = f.read_text()
            parsed[d.name] = (d, frontmatter(text), text)
        except ValueError as e:
            errors.append(f"{d}: {e}")
    skills = {name: fields for name, (_, fields, _) in parsed.items()}
    for d, fields, text in parsed.values():
        errors += [f"{d}: {e}" for e in check_skill(d, fields, text, skills)]
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"{len(parsed)} skills valid")


if __name__ == "__main__":
    main()
