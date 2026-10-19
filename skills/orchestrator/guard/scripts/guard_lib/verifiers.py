"""The verification budget: each check gets one full-round verifier and one fix-wave verifier, then goes to the user."""
import json
import pathlib
import re
import time

MARKER = "You are verifying a change you did not write."
EVIDENCE = re.compile(r"^Evidence directory:\s*(\S.*?)\s*$", re.M)
CHECKS = re.compile(r"^Checks:\s*(.*?)\s*$", re.M)
CHECK_ID = re.compile(r"[A-Za-z0-9][\w.-]*")
ROUNDS = 2
LEDGER = "verifier-rounds.json"
SPENT = ("Checks {ids} already had a full-round verifier and a fix-wave verifier that wrote evidence for them, the whole "
         "verification budget. Do not spawn another. In an interactive run, take each still-failing check to the user with its "
         "repro and what each fix changed. In an autonomous run, record it in the project's backlog with the repro and the fix "
         "you recommend, leave the check FAIL in the report, and go on with work that does not depend on it.")
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
    found = [*directory.glob(f"{check_id}*")]
    nested = directory / "evidence" / check_id
    if nested.is_dir():
        found += [p for p in nested.rglob("*") if p.is_file()]
    return [p.stat().st_mtime for p in found if p.is_file() and p.name != LEDGER]
