# Flow v2, workstream C: notes

What changed in the skill texts, what the other workstreams must match, and where the spec looked wrong or silent.

## Files

- `skills/eng/feature/SKILL.md` and `references/phases.md`: the 10 steps of the spec. Throughput checkpoint and principles step gone; the usage-limit, shared-machine, and "a PR may open with FAIL" rules are top paragraphs.
- `skills/eng/plan-feature/SKILL.md` and `references/phase-plan.md`: one living `spec.md` with `## Change log`; phase plans hold checks and the perf decision only; the principles step folded into the design step (so 6 steps now, `phases` gate on step 5).
- `skills/eng/verify/SKILL.md` and references (`plan.md`, `plan-template.md`, `verifier-prompt.md`, `reviewer-prompt.md`, `report-template.md`): review before prove, dry-run plus light-model comparison, FAIL classification, `observations.md` plus `report --write`, capacity-driven rerun, premises section, optional `- Agent:` field, additions-only revisions.
- `skills/eng/quick-feature/SKILL.md`, `skills/eng/bug-fix/SKILL.md`: same order (implement beside scripts, review, prove, fix FAILs, close).
- `skills/eng/how/SKILL.md` and its two prompt templates: premises mode, files written by write-capable types.
- `skills/eng/open-pr/SKILL.md`: `## Not ready to merge` first section, `do not merge` label.
- `skills/eng/perf-issue/SKILL.md`, `skills/eng/hillclimb/SKILL.md`: their fix sentence no longer reruns only some ids, because any product fix now reruns every e2e check.
- `README.md`: lines for the changed skills.
- Outside C, needed for C's contract: `guard_lib/gates.py` GATE regex now accepts flags (`-{0,2}` before each argument word), and `tests/test_guard.py` ShippedPlaybooks match the new step shapes. Without the regex change `plan --checks` and `premises --resolved` are not gates at all. Only those two backticks become new gates in this repo (checked by scanning every .md). Drop this commit if A lands the same change.

## Feature steps as written (for A.14's test)

| Step | Gates | Mandatory | Skip | Parallel phrase |
|---|---|---|---|---|
| 1 | `plan --checks` | yes | | |
| 2 | `premises` | yes | | |
| 3 | `plan`, `premises --resolved` | yes | | |
| 4 | `lock` | yes | | |
| 5 | `units` | yes | | |
| 6 | `scripts` | no | when no e2e check | "in parallel with step 5" |
| 7 | `review` | yes | | |
| 8 | `oracles` | yes | | |
| 9 | none | no | when nothing failed | |
| 10 | `report`, `spec` | yes | | |

quick-feature: 3 implement (`units`), 4 scripts "in parallel with step 3", 5 review. bug-fix: 6 implement, 7 scripts "in parallel with step 6", 8 review.

## Spec gaps and contradictions

1. **Dependencies of step 7 (A.1 vs A.14).** A.1's default makes 7 depend on 6 (the previous item), so review would wait for the scripts. A.14 and the flow want 7 after 5 only, and 8 after 6 and 7. A.1 has no rule that yields this. Suggest: the item after a parallel group depends on the group's first member, and the next one on every member; or parse "as soon as step N closes" (step 7 says exactly that, and quick-feature 5 and bug-fix 8 say the same of their implement step).
2. **GATE regex.** Spec C says gates are `` `../verify/scripts/verify.py <cmd>` `` but two gates carry flags, which the shipped regex rejects. Fixed here (see Files); A should keep it.
3. **PR heading.** guard's `pr.py` allows only Why, What changed, Scope, Tradeoffs, Blast Radius, Verification. open-pr now puts `## Not ready to merge` first, so A must add it to SECTIONS, first in order. Not in the spec.
4. **Stacked PRs dropped.** Step 1 "previous phase merged, base is current main" ends the stack model: phases.md now starts each phase on main after the previous merge, and the patch-id regrade section is gone. Confirm this is intended, because a `do not merge` phase now stops the next one.
5. **Where `grounding.md` lives.** B.5 checks it beside `premises.md` (the phase folder), while plan-feature writes the first one at the plan folder root. Texts say: each phase writes its own in its folder, starting from the newest earlier one.
6. **Relaxations in report.md.** A.13 wants them in report.md, but B.10 builds report.md with no source for them. Texts put them in the PR's Verification section and the reply only. Suggest a `report --write --relaxation "<text>"` flag.
7. **`report --write` flags.** B.10 says Author and Verifier come "from flags" without names. Texts say "naming the executor as the Author and the verifier as the Verifier" and never spell a flag; B should print them in help.
8. **Walk verdicts.** B.10 takes walk rows from `evidence/<id>/`, which shows a walk ran but not its verdict. The verifier's observation line starts with `defect:` or `blocker:` for FAIL or INCONCLUSIVE; B could read the verdict from that.
9. **Review triage vocabulary.** The design doc says findings no longer become plan checks. Texts use `Triage: fixed` (already accepted by verify.py) for a finding fixed with a unit spec and drop `new check`. B may keep accepting `new check`, but nothing writes it now.
10. **Review Head lines.** reviewer-prompt now puts `Head:` as the first line of `## Review` and its own `Head:` as the first line of `## Fix review`, matching B.8's per-section Head. A parser that takes the first `Head:` in the file still reads the review's.
11. **`dryrun` from the base worktree.** The verifier runs in its own base worktree, where `verify.py where` resolves another branch's directory, so the prompt passes `--dir <evidence directory>` to `dryrun`. B should accept `--dir` there, as the other commands do.
12. **Environment reruns and the fix budget.** Texts say an environment FAIL is rerun as is and is not an attempt, but `rerun --only` counts every failing run of a FAIL-marked check. B needs a way to rerun without counting (or count only after a product or script change).
13. **`- Agent:` field.** Parlor writes `- Agent: real: <why>`; A.12 matches `- Agent: real`. plan.md documents `real: <why>`, `fake: <why>`, `n/a: <why>`, so A's match should be a prefix match.
14. **Rerunning a check past its fix budget.** The texts rerun "every e2e check" after a product fix; `rerun --only` refuses a check past its budget. B should skip such a check with a note instead of refusing the whole run.
15. **The `driver` gate** left the feature flow (spec step 6 gates only `scripts`). `scripts` needs dry-run logs, which need a working driver, so nothing is lost; bug-fix still gates `driver` in step 1.

## Choices beyond the spec

- plan-feature lost its principles step too (the brief says to remove the separate principles step everywhere), and quick-feature and bug-fix fold the principles index into their design or plan-the-fix step.
- bug-fix: blast-radius moved from after the rebase into "Plan the fix", and step 4 now also gates `freeze`, so predicates are fixed before the fix exists.
- verify's Autonomous runs section no longer suggests `&& verify.py rerun` as a done check, because the script lock refuses a second full rerun.
