---
name: bug-fix
description: "Fix a bug scientifically: reproduce it on main on the surface the user hit it, binary-search the root cause with runtime evidence, delegate the smallest fix, prove it with an independent verifier, and land the failing repro before the fix. Use for /bug-fix, or when a switchboard routes a bug, regression, or broken behavior here."
disable-model-invocation: true
---

# Bug fix

**You own this task. Plan, review, verify.** Delegate investigation and the fix to subagents, and stay in the lead.

Paths like `../how/SKILL.md` point to skills installed beside this one, relative to this file's folder.

Be scientific. Every shipped line traces to runtime evidence. A belt-and-suspenders change that "might help" is a hypothesis, not a fix, and it does not ship. When evidence refutes a hypothesis, revert what it motivated.

Open a todolist whose first items are the steps below, copied in verbatim, before any task-specific todos. The `guard` skill's `todo from bug-fix` does this; without guard, use your agent's todo tool. A step you choose not to do stays in the list with a one-line `skip: <reason>`, so the user sees what was skipped and why.

1. Read the **principles** skill (`../principles/SKILL.md`) and every principle file it indexes. Mandatory: no skip-with-reason escape, because the principles shape every later step and a citation is only honest when its file was read.
2. Get the driver. Use the project's verification skill (`.agents/skills/verify-<app>/` or `.claude/skills/verify-<app>/`). Without one, run the **create-verification-skill** skill (`../create-verification-skill/SKILL.md`) in a clean worktree off main, so the driver learns the app as it is, not as a fix would make it. Close this step only when `../verify/scripts/verify.py driver` passes, which needs the verification skill on main or committed before any product change. Mandatory: no skip-with-reason escape.
3. Reproduce it yourself on main, on the surface where the user hit it. Mandatory: no skip-with-reason escape, because a fix for a bug you never saw is a guess. If it does not reproduce directly, synthesize the trigger, tighten the conditions, or instrument until it fires. Ask the user only with a specific reason the driver cannot reach the target, after driving it as far as it goes. Save the failing repro output as evidence. If it does not reproduce on main, say so and stop: it is already fixed or depends on state you have not found.
4. Binary-search the cause. List candidate hypotheses, seeded by the **how** skill (`../how/SKILL.md`) over the affected subsystem and the **why** skill (`../why/SKILL.md`) for regression history. Each pass, take the split that cuts the most remaining problem space, get runtime evidence, and eliminate. When program state is unclear, add logging and read it as the code runs instead of guessing. Confirm the surviving mechanism with runtime evidence before planning a fix. When two fixes built on one premise have failed, apply the Attack the Premise principle (`../principles/references/principles/attack-the-premise.md`).
5. Write the verification plan per `../verify/references/plan.md`. Its first check is the repro from step 3, with the predicate it must meet once fixed. Add regression checks for the behavior next to the bug, and a perf check for any path a user waits on that the fix touches, with main as its baseline. Add each check to the todo list as its own item. Close this step only when `../verify/scripts/verify.py plan` passes. Mandatory: no skip-with-reason escape.
6. Plan the fix. If it crosses a function boundary, run the **architect** skill (`../architect/SKILL.md`) first. Fix the root cause, not the symptom, per the Fix Root Causes principle (`../principles/references/principles/fix-root-causes.md`).
7. Delegate the fix to a subagent on the executor model from the orchestrator config (`<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`). Use a native subagent when your agent can run that model, otherwise the **salvo** skill (`../salvo/SKILL.md`) with that one entry, and apply its patch. Give it the root cause with its evidence, the file paths, and the plan's checks as success criteria. When the bug has a cheap local test path, the delegate writes a regression test first and confirms it fails for the reason step 4 found. Prefer no new test over a test of mocks, timing, or internals. Comments per the **code-comments** skill (`../code-comments/SKILL.md`).
8. Prove every check in the plan with the **verify** skill (`../verify/SKILL.md`). The repro must fail on main and pass on head. Mandatory: no skip-with-reason escape, because the author's own run is not a verdict. A unit test shows branch behavior, not that the bug is gone. Close this step only when `../verify/scripts/verify.py report` passes. On a FAIL, delegate the fix to the executor at its root cause, then run the verify skill again for the checks the fix could touch, with a fresh verifier.
9. Rebase into small, ordered commits with the failing repro or regression test before the fix, per the Sequence Work into Verifiable Units principle (`../principles/references/principles/sequence-verifiable-units.md`).
10. If the fix touches a shared primitive, a wire format, a schema, or a flag, run the **blast-radius** skill (`../blast-radius/SKILL.md`).
11. Run the **open-pr** skill (`../open-pr/SKILL.md`).

**Reply:** what was broken, the root cause with its evidence, the fix, the verify skill's check table, and every exploration finding with its triage. Paste the failing-then-passing repro output verbatim. Write it per the **reply** skill (`../reply/SKILL.md`).
