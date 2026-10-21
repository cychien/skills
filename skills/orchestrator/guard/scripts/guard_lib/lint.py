"""Lint a skill as `todo from` reads it, so a step guard cannot order, gate, or attach fails before a run does."""
import pathlib
import re

from . import gates, order, skills

OWN_STEPS = re.compile(r"\bstep \d+\b|\b(?:these|following) steps\b|\bsteps (?:below|above)\b", re.I)
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
CLOSE_WHEN = re.compile(r"Close this step only when", re.I)
SKIP = re.compile(r"Skip this step", re.I)


def beside(path, name):
    """Where skill `name` is installed beside the skill at path: its sibling folder, or, in a repo that groups skills
    into category folders (installers drop the category), any category's folder of that name."""
    folder = pathlib.Path(path).resolve().parent
    candidates = [folder.parent / name, *sorted(folder.parent.parent.glob(f"*/{name}"))]
    return next((c for c in candidates if (c / "SKILL.md").is_file()), None)


def lint(path):
    """(errors, warnings) for the SKILL.md at path."""
    _, body = skills.frontmatter(skills.read(path) or "")
    steps = skills.steps(path)
    errors, warnings = [], []
    if not steps:
        if OWN_STEPS.search(CODE.sub("", body)):
            errors.append("no steps found, though the body refers to its steps: write them as a `## Steps` list, step headings "
                          "(`## 1.`, `## Step 1,`), or a numbered list right after the title, so `todo from` can copy them")
        return errors, warnings
    known = {n for n, *_ in steps}
    for n, _, text, mandatory in steps:
        for phrase, ref in order.references(text):
            if ref not in known:
                errors.append(f"step {n}: \"{phrase}\" names step {ref}, which this skill does not have")
        named = gates.named(text)
        for skill, script, args in named:
            home = beside(path, skill)
            if not home or not (home / "scripts" / script).is_file():
                errors.append(f"step {n}: the gate `{' '.join([f'../{skill}/scripts/{script}', *args])}` names a script that is not installed beside this skill")
        if CLOSE_WHEN.search(text) and not named:
            warnings.append(f"step {n}: says \"Close this step only when\" but names no backticked gate (`../<skill>/scripts/<script>.py <command>`), so guard cannot hold it")
        if mandatory and SKIP.search(text):
            warnings.append(f"step {n}: is Mandatory and also says \"Skip this step\"; guard refuses every skip of a Mandatory step")
        for name in dict.fromkeys(skills.SKILL_REF.findall(text)):
            if not beside(path, name):
                warnings.append(f"step {n}: names ../{name}/SKILL.md, which is not installed beside this skill")
    loop = order.cycle(order.dependencies(steps))
    if loop:
        errors.append("the steps wait on each other in a cycle: " + " -> ".join(str(s) for s in loop))
    return errors, warnings


def installed(cwd):
    """Every SKILL.md under the guard skill roots."""
    found = []
    for root in skills.roots(cwd):
        found += sorted(root.glob("*/SKILL.md"))
    return found
