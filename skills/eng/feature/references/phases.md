# Building a feature plan

The plan-feature skill leaves a plan folder: `plan.md` with the decisions and the phases, `spec.md` with the whole design and its Change log, `phases/<nn>-<name>/plan.md` with each phase's checks, `grounding.md`, and `skeleton.patch` with its rationale when the design has one. Build it one phase per session, each a feature run the user starts once the previous phase's PR is merged, one PR per phase against main. Each phase runs only its own plan's checks, its Regression checks for the earlier behavior it could break among them, plus the project's whole unit test suite. No phase reruns another phase's scripts, because a final run that grows with every phase costs more than the regressions it catches beyond those the phase plan names.

## Once for the whole feature

- Step 6's verifier extends the driver once for every phase's checks, in phase 1's session on the base, because a driver extended per phase pays its setup and review again each time.

## Each phase, in its own session, in the order of `plan.md`

1. Confirm the previous phase's PR is merged, cut the phase's branch and worktree from current main, and run `todo from feature`.
2. Step 1: `python3 ../../verify/scripts/verify.py adopt <plan folder>/phases/<nn>-<name>`, which points the branch at the phase's `plan.md` and records the branch's starting commit as the phase's base. The plan stays in the phase's folder, the one copy every command reads. An earlier check the phase entry lists under Changes already holds its new predicate as a check in this phase's plan.
3. Step 2 starts how from the newest `grounding.md` (the plan folder's for the first phase, else the previous phase's folder) and writes this phase's `grounding.md` and `premises.md` in the phase's folder, so the next phase starts from it.
4. Step 3 is case A: it resolves every false premise, updates `spec.md` and the later phase plans with a Change log line for each change, and writes the phase plan's Drive contract and Sensitive paths from `spec.md`, the skeleton, and the grounding.
5. Step 4 locks the phase's plan before its code. `spec.md` and the later phase plans stay open to change.
6. Steps 5 to 10 build and verify the phase. The executor's brief carries only the skeleton files and symbols the phase entry names. The verifier writes scripts for and walks only this phase's checks; a native shell or perf check runs only in the phase whose Heavy line names it. The reviewer covers this phase's diff. Whenever a step changes the design (an approved deviation, a design decision, a false premise, a review finding, an autorun decision), update `spec.md` and every later phase plan it affects then, with a Change log line, because a later phase built from a stale design builds the wrong thing. This phase's own locked checks still change only through `verify.py freeze`. Step 10 reconciles `spec.md` with what ships. Open the PR against main, tell the user the phase is done and which phase comes next, and stop.
7. A check still failing after its 2 failed fix attempts stays FAIL in the phase's report, and the PR opens with it at the top of the description and the `do not merge` label. In an autonomous run it also goes to the backlog.

## Landing

The user merges each phase's PR. The next phase starts only after that merge, on current main, because it builds on the code that ships and needs no regrade when a phase below it changes.

A new session starts at the first phase whose PR is not merged.
