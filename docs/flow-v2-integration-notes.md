# Flow v2: integration notes

Branch `flow-v2`: workstream A (guard), B (`flow-v2-verify`) and C (`flow-v2-texts`) merged, then checked end to end.

## Merges

- `flow-v2-verify`: clean. Suite green right after it (299 tests).
- `flow-v2-texts`: one conflict, `tests/test_guard.py` (ShippedPlaybooks). A had kept the old twelve-step feature tests behind a `skipIf` on the step count; C had rewritten them for the ten-step flow. Took C's tests and dropped A's `skipIf`/`step_count` scaffolding, so `FeatureFlow.test_the_repo_feature_skill...` now always runs against the real feature skill. `gates.py` (GATE regex with flags) was the same change on both sides and merged clean. README merged clean.

## Text and code alignment

- Feature step 10 now gates `../verify/scripts/verify.py leftovers` beside `report` and `spec`, so A's `FeatureFlow` test and `test_the_step_that_opens_the_pr_is_the_one_the_final_run_gates` agree with the text.
- The verify skill's step 7 lint warning was in main's text; C's rewrite already drops the gateless "Close this step only when" there. `guard.py lint --all` (skill roots = every `skills/<category>`) reports 0 errors and 0 warnings.
- Fix budget wording (feature step 9, quick-feature step 7) said `rerun --only` counts every failing run and then refuses the check. The code counts a failing run only when a product file or the script changed since the previous failing run, counts full reruns too, and skips a spent check with a note. Texts now say that.
- guard's "PR before the close step" denial told the lead to run `todo done <n>` without a token, which is refused for skill items. It now names `todo show <n>`, then `todo done <n> --token <token>`, or `todo skip`.

## Bug found by the end-to-end run

Step 10 reconciles `spec.md` and commits it. That commit touches only the plan folder, yet the `report` gate then failed twice: the report's Head was no longer HEAD's tree ("regrade the code that ships with `verify.py rerun`..."), and the unit check's `units` run was "on another tree than HEAD". The lead would have rerun every e2e check for a doc commit. Fix in `verify.py`: `same_product(rev, skip)` accepts HEAD's tree or a tree whose only differences are in the adopted plan folder or the driver (the same product set the e2e rule and `lock` use). The report Head check and the unit evidence check both use it. Help text updated; `UnitTier.test_a_later_commit_outside_the_product_keeps_the_units_run_and_the_report_current` covers it (a driver commit passes, a README commit still fails).

## New tests

- `tests/test_skill_references.py`: every backticked command (and every line of a fenced block, including a shell alias for guard.py such as `g todo ...`) in every SKILL.md, `references/*.md` and README that names `verify.py`, `guard.py`, or starts with `todo`/`quota` is checked against the CLIs' own `--help`. verify.py: the command is a real choice, and each flag is a real option listed in that command's help synopsis line (or the global `--dir`). guard.py: the subcommand path is walked through the nested help, and flags must be the leaf's options (a hidden `--not-run` fails). A reference to another skill's same-named script (setup-orchestrator's `verify.py`) is skipped. 222 commands checked, 0 mismatches.
- `tests/test_flow_v2.py`: temp git repo, temp HOME, GUARD_HOME, ORCHESTRATOR_HOME, AUTORUN_HOME, VERIFY_HOME, GUARD_SKILL_ROOTS at this worktree's skill categories. `todo from feature` on the real SKILL.md (10 items, dependencies, mandatory set, gates), then steps 1 to 10 closed in order through `todo show` tokens and the real gates, each failing first where the step's artifact is missing (premises, Drive contract, unresolved premise, base log, units spec). Hooks checked on the way: a Claude limit in an Agent result goes to `limits.json`, `quota pick --role executor` moves to codex, a salvo launch on claude is denied; `verify.py rerun` denied while a subagent runs and allowed after its stop; `gh pr create` denied until step 9 resolves. Second test: in an autonomous run, a stop with open steps blocks until `todo hold --until`.
- Step 10's `leftovers` gate scans `/tmp/salvo-*` machine-wide, so the flow test skips its last step (with a reason) when another agent on the machine has processes there.

## Results

- `python3 -m unittest discover -s tests`: 305 tests, OK, 1 skip (Linux-only `/proc` test).
- `uvx ruff check --select E4,E7,E9,F .` (the rule set the repo follows): clean.
- `python3 scripts/validate.py`: 41 skills valid.
- `guard.py lint --all`: 41 skills, no errors, no warnings.

## Still worth a look

- A's notes flag that an Agent hand-back quoting a Claude limit message with a reset phrase marks claude limited for an hour. Unchanged.
- The `leftovers` gate counts any process under `/tmp/salvo-*`, including another session's salvo run on the same machine, so a lead can be held at step 10 by unrelated work.
- B's `review` gate allows product changes after the fix review only when it triaged a finding `fixed`; step 9 fixes come after the review with no new review, which the `report` gate tolerates by not applying the head rule. Consistent with the texts, but worth confirming as intended.
