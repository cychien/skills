"""The verification budget: one verifier per check. A fix is graded by `verify.py rerun --only` and `units`, never by another verifier."""
import json
import pathlib
import re
import time

MARKER = "You are verifying a change you did not write."
EVIDENCE = re.compile(r"^Evidence directory:\s*(\S.*?)\s*$", re.M)
CHECKS = re.compile(r"^Checks:\s*(.*?)\s*$", re.M)
CHECK_ID = re.compile(r"[A-Za-z0-9][\w.-]*")
CHECK_SCRIPT = re.compile(r"\.check\.[^.]+$")
ROUNDS = 1
LEDGER = "verifier-rounds.json"
SPENT = ("Checks {ids} already had a verifier that wrote evidence for them, the whole verification budget: one verifier per "
         "check. Do not spawn another. Grade a fix with `verify.py rerun --only <ids>` and `verify.py units`; to walk a fixed walk "
         "check again, resume that same verifier instead of spawning a new one. After 2 failed fix attempts, take the check to "
         "the user with its repro and what each fix changed, or in an autonomous run record it in the project's backlog with "
         "the fix you recommend, leave it FAIL in the report, and go on with work that does not depend on it.")
NO_CHECKS = ("This verifier prompt has no 'Checks:' line naming the check ids it grades, so the verification budget cannot be "
             "kept. Add the line from the verify skill's verifier prompt, then send it again.")


def over_budget(prompt):
    """A deny message when a verifier prompt would grade a check past its budget, else None; records the spawn when allowed."""
    if not prompt or MARKER not in prompt:
        return None
    evidence, checks = EVIDENCE.search(prompt), CHECKS.search(prompt)
    if not evidence or not checks or not CHECK_ID.findall(checks.group(1)):
        return NO_CHECKS
    directory = pathlib.Path(evidence.group(1)).expanduser()
    ids = CHECK_ID.findall(checks.group(1))
    ledger = directory / LEDGER
    spawns = json.loads(ledger.read_text()) if ledger.is_file() else {}
    spent = [i for i in ids if rounds(spawns.get(i, []), evidence_times(directory, i)) >= ROUNDS]
    if spent:
        return SPENT.format(ids=", ".join(spent))
    now = time.time()
    for i in ids:
        spawns.setdefault(i, []).append(now)
    directory.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(spawns, indent=2) + "\n")
    return None


def rounds(spawned, written):
    """Spawns that left evidence before the next spawn; a verifier that died before grading the check does not count."""
    bounds = sorted(spawned) + [float("inf")]
    return sum(1 for start, end in zip(bounds, bounds[1:]) if any(start <= t < end for t in written))


def evidence_times(directory, check_id):
    """When grading evidence for a check was written; its check script is written before the code lands, so it is not grading."""
    found = [*directory.glob(f"{check_id}*")]
    nested = directory / "evidence" / check_id
    if nested.is_dir():
        found += [p for p in nested.rglob("*") if p.is_file()]
    return [p.stat().st_mtime for p in found if p.is_file() and p.name != LEDGER and not CHECK_SCRIPT.search(p.name)]
