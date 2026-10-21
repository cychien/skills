---
name: perf-issue
description: "Fix a measured slowness: capture a vetted baseline on the surface the user waits on, find the limiter, try the performance mantras cheapest first, and prove the gain with an independent verifier. Use for /perf-issue, or when something is slow, a page or command takes too long, or a perf regression needs a one-off fix."
disable-model-invocation: true
---

# Perf issue

**You own the measurement story. Plan, review, verify the numbers.** Tie every fix to a measurement, and never read source in place of measuring.

Paths like `../how/SKILL.md` point to skills installed beside this one, relative to this file's folder.

For sustained improvement of one metric against a target, use the **hillclimb** skill (`../hillclimb/SKILL.md`) instead.

Open a todolist whose first items are the steps below, copied in verbatim, before any task-specific todos. The `guard` skill's `todo from perf-issue` does this; without guard, use your agent's todo tool. A step you choose not to do stays in the list with a one-line `skip: <reason>`, so the user sees what was skipped and why.

1. Read the **principles** skill (`../principles/SKILL.md`) and every principle file it indexes. Mandatory: no skip-with-reason escape, because the principles shape every later step and a citation is only honest when its file was read.
2. Get the driver. Use the project's verification skill (`.agents/skills/verify-<app>/` or `.claude/skills/verify-<app>/`). Without one, run the **create-verification-skill** skill (`../create-verification-skill/SKILL.md`) in a clean worktree off main. Close this step only when `../verify/scripts/verify.py driver` passes, which needs the verification skill on main or committed before any product change. Mandatory: no skip-with-reason escape.
3. Capture a baseline on main, on the surface the user waits on, with a trace or profile alongside the metric. Measure where the **benchmark-checklist** skill's "Where to measure" section says (`../benchmark-checklist/SKILL.md`): read-only production when available. Vet the baseline with that checklist and name the limiter. Mandatory: no skip-with-reason escape, because a fix planned without a baseline cannot show it helped.
4. Write the verification plan per `../verify/references/plan.md`. The perf check carries the target the user agreed to as its rule, with main as its baseline. Add regression checks for the behavior the fix must keep, because a faster wrong answer is not a fix. Close this step only when `../verify/scripts/verify.py plan` passes. Mandatory: no skip-with-reason escape.
5. Ground hypotheses with the **how** skill (`../how/SKILL.md`) over the code the trace points at. Never claim a perf ceiling without running it. Order hypotheses by the performance mantras, cheapest first, and stop at the first one that meets the target:
   1. Don't do it. Stop work whose result nothing uses, rather than making it cheaper.
   2. Do it, but don't do it again.
   3. Do it less.
   4. Do it later.
   5. Do it when the user is not looking.
   6. Do it concurrently.
   7. Do it cheaper.
6. Plan the fix from the trace. If it crosses a function boundary, run the **architect** skill (`../architect/SKILL.md`) first.
7. Delegate each attempt to a subagent on the executor model from the orchestrator config (`<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`), with the trace, the limiter, the hypothesis, and the file paths. Review its diff. Measure every attempt with the same probe before the next one, and revert an attempt that does not move the metric past noise, per the Sequence Work into Verifiable Units principle (`../principles/references/principles/sequence-verifiable-units.md`).
8. Prove the plan with the **verify** skill (`../verify/SKILL.md`). Compare the baseline and post-fix artifacts by parsing them, not by eye. Mandatory: no skip-with-reason escape, because the author's own measurement is not a verdict. Close this step only when `../verify/scripts/verify.py report` passes. On a FAIL, classify it and delegate a product fix to the executor at its root cause, then grade it with one `verify.py rerun --only` of every e2e check, because a product change voids every e2e PASS before it, never with a fresh verifier, at most 2 failed attempts per check, per the verify skill's step 11.
9. Rebase into small, ordered commits: any probe or harness first, then each kept fix.
10. Run the **open-pr** skill (`../open-pr/SKILL.md`), with the primary number in the Verification section.

**Reply:** baseline number, post-fix number, delta, limiter, data source, artifact path, and every review finding with its triage. Write it per the **reply** skill (`../reply/SKILL.md`).
