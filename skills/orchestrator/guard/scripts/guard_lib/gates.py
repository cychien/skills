"""Gates: a todo item that names a skill's check script closes only when that script exits 0."""
import os
import re
import subprocess
import sys

from . import skills

GATE = re.compile(r"`\.\./([a-z0-9][a-z0-9-]*)/scripts/([A-Za-z0-9_-]+\.py)((?: [a-z][a-z-]*)*)`")
TIMEOUT = 300
OUTPUT_LIMIT = 4000


def named(text):
    """Every gate an item's text names, as (skill, script, args)."""
    return [(skill, script, args.split()) for skill, script, args in GATE.findall(text)]


def run(skill, script, args, cwd):
    """Run one gate from the agent's working directory. Returns None when it passes, else why it failed."""
    found = skills.find(skill, cwd)
    path = found.parent / "scripts" / script if found else None
    shown = " ".join([f"../{skill}/scripts/{script}", *args])
    if not path or not path.is_file():
        return f"the gate `{shown}` names a script that is not installed."
    try:
        r = subprocess.run([sys.executable, str(path), *args], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"the gate `{shown}` did not finish within {TIMEOUT} seconds."
    if r.returncode == 0:
        return None
    output = (r.stdout + r.stderr).strip()[-OUTPUT_LIMIT:]
    return f"the gate `{shown}` failed:\n{output}"


def failures(text, cwd=None):
    cwd = cwd or os.getcwd()
    return [f for skill, script, args in named(text) if (f := run(skill, script, args, cwd))]
