# Building a feature plan

The plan-feature skill leaves a plan folder: `plan.md` with the decisions and the phases, `phases/<nn>-<name>/plan.md` with each phase's verification plan, its Drive contract, and its Sensitive paths, `grounding.md`, and `skeleton.patch` with its rationale when the design has one. Build it one phase per session, each a feature run the user starts, one stacked PR per phase. Each phase runs only its own plan's checks, its Regression checks for the earlier behavior it could break among them, plus the project's whole unit test suite. No phase reruns another phase's scripts, because a final run that grows with every phase costs more than the regressions it catches beyond those the phase plan names.

## Once for the whole feature

- Step 3 starts from `grounding.md` and explores only what it does not cover.
- Step 8's verifier extends the driver once for every phase's checks, in phase 1's session on the base, because a harness extended per phase pays its setup and review again each time.

## Each phase, in its own session, in the order of `plan.md`

1. Cut the phase's branch and worktree from the previous phase's tip (phase 1 from main, after the driver commit), and run `todo from feature`.
2. Step 1: `python3 ../../verify/scripts/verify.py adopt <plan folder>/phases/<nn>-<name>`, which copies the phase's plan with its Drive contract and Sensitive paths and records the branch's starting commit as the phase's base. An earlier check the phase entry lists under Changes already holds its new predicate as a check in this phase's plan.
3. Step 4 is case A: an addendum only where this phase's code contradicts the plan folder, with the Drive contract changed only where the addendum changes it.
4. Step 5 locks the phase's plan before its code.
5. Step 6 writes the checkpoint for this phase.
6. Steps 7 to 12 build and verify the phase. The executor's brief carries only the skeleton files and symbols the phase entry names. The verifier writes scripts for and walks only this phase's checks; a native shell or perf check runs only in the phase whose Heavy line names it. The reviewer covers this phase's diff. Step 12's closing run is this phase's `units`, the project's whole unit test suite, and `rerun --only $(verify.py affected)` when it lists any check. Open the PR against the previous phase's branch, tell the user the phase is done and which phase comes next, and stop: the user starts the next phase in a new session, without waiting for review.
7. A check still failing after its 2 failed fix attempts stays FAIL in the phase's report. In an autonomous run it goes to the backlog, and the next phase to start is one whose Depends on line does not reach the failing phase.

## Landing

The user lands the stack bottom up, and may land a verified bottom phase before the rest is built. After a merge, the PR above retargets to main. When `git patch-id` of its change is the same as at its verdict, the verdict stands; otherwise the phase's own `verify.py rerun --only $(verify.py affected)`, `verify.py units`, and the project's whole unit test suite regrade it, never an earlier phase's scripts, and the phase's verifier, resumed, walks again each walk check the difference touches, because guard allows one verifier per check.

A new session resumes at the first phase without a passing report.
