# Building a feature plan

The plan-feature skill leaves a plan folder: `plan.md` with the decisions and the phases, `phases/<nn>-<name>/plan.md` with each phase's verification plan, `grounding.md`, and `skeleton.patch` with its rationale when the design has one. Build it in one feature run, one stacked PR per phase. Each phase verifies only what it adds; what earlier phases proved is regraded by their saved scripts, never re-specified for a fresh verifier.

## Once for the whole feature

- Step 2 reads the principles once; a later phase in the same session closes it on that read.
- Step 3 starts from `grounding.md` and explores only what it does not cover.
- Step 6 writes the checkpoint for all phases and rewrites it at each phase boundary.
- Step 7 extends the driver once for every phase's checks, before phase 1's code, because a harness extended per phase pays its setup and review again each time.

## Each phase, in the order of `plan.md`

1. Cut the phase's branch and worktree from the previous phase's tip (phase 1 from main, after the driver commit), and run `todo from feature` again.
2. Step 1: `python3 ../../verify/scripts/verify.py adopt <plan folder>/phases/<nn>-<name>`, which copies the phase's plan and records the branch's starting commit as the phase's base. From phase 2, carry the earlier phases' checks with `python3 ../../verify/scripts/verify.py carry <previous phase branch>`, so `rerun` regrades them without an agent; carries are transitive. A check the phase entry lists under Changes gets its new predicate through `freeze --revision` after the lock, and the verifier replaces its carried script.
3. Step 4 is case A: an addendum only where this phase's code contradicts the plan folder.
4. Step 5 locks the phase's plan before its code.
5. Steps 8 to 14 build and verify the phase. The executor's brief carries only the skeleton files and symbols the phase entry names. The verifier writes scripts for and walks only this phase's checks, while `rerun` regrades the carried ones; a native shell or perf check runs only when the phase's Heavy line names it, because later phases regrade it by its carried script. The explorer and the reviewer cover this phase's diff. Open the PR against the previous phase's branch and start the next phase without waiting for review.
6. A check still failing after its 2 failed fix attempts stays FAIL in the phase's report. In an autonomous run it goes to the backlog, and the run continues only with phases whose Depends on line does not reach the failing phase.

## Landing

The user lands the stack bottom up, and may land a verified bottom phase before the rest is built. After a merge, the PR above retargets to main. When `git patch-id` of its change is the same as at its verdict, the verdict stands; otherwise `verify.py rerun` and `verify.py units` regrade it, and the phase's verifier, resumed, walks again each walk check the difference touches, because guard allows one verifier per check.

A run that stops partway resumes at the first phase without a passing report.
