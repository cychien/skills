"""The order of a skill's steps: which earlier steps each one waits on, read from the step text."""
import re

PARALLEL = re.compile(r"\b(?:in parallel with|beside|in the same message as) step (\d+)\b", re.I)
STARTS_AFTER = re.compile(r"\bstarts after steps? (\d+(?:(?:\s*,\s*and\s+|\s*,\s*|\s+and\s+)\d+)*)", re.I)


def references(text):
    """Every step number the text names in an ordering phrase, as (phrase, number)."""
    return ([(m.group(0), int(m.group(1))) for m in PARALLEL.finditer(text)]
            + [(m.group(0), n) for m in STARTS_AFTER.finditer(text) for n in numbers(m.group(1))])


def numbers(listed):
    return [int(n) for n in re.findall(r"\d+", listed)]


def dependencies(steps):
    """{step number: [step numbers it waits on]} for [(number, title, text, mandatory)].

    A step waits on every earlier step nothing waits on yet, which for a plain list is the step before it.
    A step "in parallel with step N" (or beside it, or in the same message as it) waits on what N waits on,
    so the two open together. A step that "Starts after step N" (or "steps N and M", "N, M and K") waits on exactly those. Phrases naming
    a step the skill does not have are ignored here; lint reports them."""
    known = {n for n, *_ in steps}
    group = {n: n for n in known}

    def root(n):
        while group[n] != n:
            n = group[n]
        return n

    for n, _, text, _ in steps:
        for m in PARALLEL.findall(text):
            if int(m) in known:
                group[root(int(m))] = root(n)
    shared, waits, ends = {}, {}, []
    for n, _, text, _ in steps:
        named = [d for m in STARTS_AFTER.findall(text) for d in numbers(m) if d in known and d != n]
        if root(n) not in shared:
            shared[root(n)] = sorted(set(named)) if named else list(ends)
        after = shared[root(n)]
        waits[n] = [d for d in after if d != n]
        ends = [e for e in ends if e not in after] + [n]
    return waits


def cycle(waits):
    """One dependency cycle as a list of step numbers, or None."""
    state = {}

    def visit(n, path):
        state[n] = "open"
        for d in waits.get(n, []):
            if state.get(d) == "open":
                return path[path.index(d):] + [d]
            if d not in state and (found := visit(d, path + [d])):
                return found
        state[n] = "done"
        return None

    for n in waits:
        if n not in state and (found := visit(n, [n])):
            return found
    return None
