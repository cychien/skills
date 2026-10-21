# Flow v2, workstream B: verify.py notes

What was built against section B of `flow-v2-spec.md` and the lead's amendments, where the spec was interpreted, and what the other workstreams need to know. Code: `skills/eng/verify/scripts/verify.py`. Tests: `tests/test_verify.py` (151 tests; whole repo suite 282, green).

## Per spec item

1. **Touches and affected removed.** `plan` ignores a `- Touches:` field. `affected` and `--explain` are gone; `rerun --only` stays. The report gate's e2e rule: a PASS needs a passing `<id>.rerun.log` after the freeze, and the ledger's latest run of that check is a PASS whose recorded head has no product change before HEAD. A product change is any path outside the driver dirs and the adopted plan folder, the same set `lock` uses.
2. **One plan copy.** `adopt <phase folder>` writes `base.json` with `base`, `plan` (the plan folder root, as before) and `plan_file` (the phase's `plan.md`). Every command reads the plan through `plan_file()`. No copy is written. A matching `plan.md` left by an older adopt is removed; a different one is refused, and so is adopting a second phase folder. A branch with only `plan.md` in the verification directory and no `plan_file` keeps working.
3. **`plan --checks` and full `plan`.** `--checks` covers fields, tiers, the 10 e2e cap and the perf decision. Full `plan` adds the Drive contract rule, the Sensitive paths placeholder rule and the names lint. `phases` and `adopt` use the checks-only rules.
4. **E2E wording.** The cap message and help say: "E2E is the most expensive tier, so fewer is better: keep only core behavior no unit spec can see, and 10 is a ceiling, not a target".
5. **`premises [--resolved]`.** Reads `premises.md` and `grounding.md` beside the plan file: the phase folder, else the verification directory. It needs a table with the columns `Check | Premise | Holds | Evidence | Resolution`, matched case-insensitively. The other rules: every plan check id appears in some row's Check cell (a cell may name several ids), Holds is `yes` or `no`, and Evidence is non-empty. Both files must be newer than the base commit's committer time. `--resolved` also needs a Resolution on every `no` row.
6. **Revisions classified.** `lock` and `freeze` now store the plan text in `plan.lock`, and a later `freeze` classifies the change:
   - **Recorded automatically:** added checks and added Drive contract lines.
   - **Needs `--revision`:** a removed check, a removed or changed contract line, or a change to a protected field of an existing check. In an autonomous run it also needs `--gate <id>`: an answered gate of that run, and each gate backs only one revision.
   - Run detection loads the autorun skill's `autorun_lib/store.py` from beside the verify skill, the repo layout, or `~/.claude|.agents|.codex/skills`, and calls `resolve_cli()`. If that fails, the session counts as interactive.
   - `report` prints every revision, marking the automatic ones and naming any gate.
   - A lock from before this change has no stored text, so any change to its plan needs `--revision`.
7. **`scripts` and `dryrun`.** `dryrun --base <worktree> [--only] [--jobs] [-- ARGS]`:
   - It refuses a worktree whose product files differ from the phase base. Then it runs each script there with `VERIFY_DIR` and `VERIFY_DRYRUN=1` set, using the rerun scheduler.
   - It writes `<id>.base.log`: the output, then trailer lines for the base, the script's sha256, ready or not, the exit, and `dryrun: FAIL|PASS|CRASH (<why>)`.
   - FAIL means ready was printed, the exit was 1 and the last non-empty stdout line starts with `FAIL`.

   `scripts` requires, for every e2e check (perf included), a script and a base.log made from that same script, that is not a CRASH. A PASS is accepted with a note.
8. **`review`.** `review.md` needs `## Review` and `## Fix review`. Each section has its own `Head:` line (amendment 3: read per section, anywhere in the section) and every bullet triaged, or other text such as "none found"; an empty section fails. The file must be written after the freeze. The 200-line rule is gone.
9. **`rerun` scheduling.** `--jobs` is an optional ceiling and there is none by default. A script starts when every running script has printed `verify: ready`, the ceiling allows it, and capacity passes; capacity is now required for the first script too. While capacity is short a script waits, checking every 15 s. After 10 minutes it is REQUEUED behind the rest. A second 10-minute wait marks it NOT RUN, which fails the run and is not recorded in the ledger. The watchdog, perf-alone rule, script lock, `script-fix` and fix budget are kept.
10. **`report --write`.** Builds `report.md`:
    - **Header:** Head (HEAD), Main (the main branch's sha), Author and Verifier from `--author`/`--verifier`, else from the existing report.
    - **Rows:** one per check, from its evidence: e2e from the rerun log plus the head rule, unit from `units.json`, walk from `evidence/<id>/`, and oracle expected/observed added to the cell.
    - **Verdict:** an Observed cell from `observations.md` (`<id>: <line>`, a `- ` prefix allowed) starting with `defect:` makes the row FAIL, and one starting with `blocker:` makes it INCONCLUSIVE. Otherwise passing evidence gives PASS, failing evidence FAIL, and missing or stale evidence INCONCLUSIVE.
    - **Gaps:** a missing observation writes `missing`, and the gate fails. Pipes in an observation are escaped as `\|`, and the table parser honors that.
    - **Sections:** `## Not ready to merge` at the top when any row is FAIL or INCONCLUSIVE. `## Revisions and fixes` holds plan revisions, full reruns and script fixes. `## Notes` comes from repeatable `--note` (amendment 1); without `--note` the existing notes stay.
    - **Gate:** after writing, it runs the gate and prints why each non-PASS row is not a pass. Plain `report` stays the gate and now prints "not ready to merge: ..." when any row is FAIL or INCONCLUSIVE.
11. **`spec`.** With an adopted `plan_file`, `<plan folder>/spec.md` needs a `## Change log` with a line naming the phase folder (a whole-word match, so `01-json-old` does not count), and `phases` must pass on the folder. Without an adopted phase it passes with a note. `phases` with no argument and no pointer now falls back to the adopted plan folder.
12. **Tests and help.** Every item is covered. The Touches, affected and 200-line fix review tests were removed or rewritten, and the help text was rewritten.

## Amendments from the lead

1. `--note` is built (above).
2. Walk verdicts work as specified: a `defect:` observation makes FAIL, `blocker:` makes INCONCLUSIVE, else PASS when a screenshot or video is in `evidence/<id>/`, and INCONCLUSIVE without one.
3. Each review section's Head is read separately. The triage words are unchanged.
4. `--dir` already works for every command. The tests run `dryrun --dir` from the base worktree.
5. A failing run of a FAIL-marked check is a fix attempt only when something changed since its previous failing run: its script's sha256, the product part of the uncommitted diff, or the committed product code. The ledger now records `script`, `product_dirty` and `product_patch`. Outside a git repository every failing run counts. Counting now applies to full reruns too, not only `--only`.
6. A check past its fix budget is skipped with a `SKIP` note in any rerun, full or `--only`, and does not fail it. The full-rerun stamp lists it as known.
7. The location of `grounding.md` and `premises.md` is as in item 5.

## Interpretations and additions to confirm

- **Fix review Head (item 8).** "Head is HEAD or a commit with HEAD's product tree" would fail every run whose fix review found something that was then fixed, and step 7 says those fixes follow the fix review. So `review` allows product changes after the fix review's Head only when the fix review triaged a finding as `fixed`. The `report` gate checks review.md's shape and freshness but not this head rule, because step 9 changes product code after the review with no new review.
- **Names lint (item 3)** applies only to e2e and walk checks, which drive names; a unit check naming `--flag` does not need a contract. Paths match exactly, or against a contract template whose `:id`, `{id}`, `<id>`, `[id]` or `*` segments match any one segment. A query string is ignored. A flag matches as a whole token (`--dry` does not cover `--dry-run`).
- **Protected fields (item 6).** Following the spec's parenthetical and the design doc, these are Scenario, Pass, Tier, Oracle and Seed, plus Tolerance and the perf predicate fields Path, Metric, Probe, Baseline and Rule, because a looser tolerance or budget moves the goalpost. Edits to other fields, titles or prose are recorded automatically under "other edits", so nothing changes silently.
- **E2E PASS rule (item 1)** also refuses a passing run that graded uncommitted product changes (`product_dirty`), since that run did not grade HEAD.
- **Full rerun after the prove** is still refused without `--full-reason`. The refusal now prints the exact `rerun --only <ids>` for every check whose latest run failed or predates a product change. Step 9 can therefore always grade with `--only`, and guard's A.8 rule covers both forms.
- **New lint.** A `### <id>. ` check heading outside `## Checks` and `## Perf` is an error. An end-to-end run showed a check appended under `## Drive contract` was invisible to every gate.
- **FAIL Observed** must start with `defect:` (before this change `blocker:` was also accepted). An INCONCLUSIVE row needs no evidence file, so a PR can open with a waiting check.

## For workstream C (texts)

- **Gates:** `plan --checks` and `adopt` at step 1, `premises` at step 2, `plan` and `premises --resolved` at step 3, `lock` at step 4, `units` at step 5, `scripts` (after `dryrun --dir <verification dir> --base <worktree>`) at step 6, `review` at step 7, `oracles` and `report --write` at step 8, then `report`, `spec` and `leftovers`.
- **review.md shape:** `## Review` (`Head: <sha>` first, then findings with `Triage: ...`, or "none found") and `## Fix review` (same shape).
- **observations.md:** one line per check, `<id>: <what it saw>`, with `defect:` or `blocker:` prefixes.
- **Check scripts:** print `verify: ready`, then end with a last stdout line `FAIL <id>: ...` and exit 1 when a predicate fails. The parlor phase kit already does this. `VERIFY_DRYRUN=1` marks a dry run.
- **Plan revisions:** additions record themselves with a plain `freeze`. Anything else needs `--revision`, plus `--gate` in autorun.
