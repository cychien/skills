# Verification plan

Write the checks before the design, with the requirements. A pass predicate and a perf budget are product decisions as much as the spec is, and a check or budget written after the code tends to describe the code instead of the requirement. Test each check's premises against the code, then add the Drive contract and the Sensitive paths once the design settles, because they name what the design builds, and lock all of it before any code.

Write it as `plan.md` in the verification directory that `python3 ../scripts/verify.py where` prints (a path beside this file's folder), from `plan-template.md` beside this file. A phase folder's own `plan.md` is the plan once `verify.py adopt` points the branch at it, and no copy exists. `verify.py plan --checks` checks the checks alone, and `verify.py plan` checks the whole plan, so a check without a predicate or a plan without a perf decision cannot reach a verifier.

## Terms

- **Check.** One acceptance condition, written in the plan before any code and locked. Its fields are Scenario, Surface, Evidence, Pass, Oracle, and Tier.
- **Premise.** A fact about the code as it is that a check assumes already holds: a route exists, a dialog asks before it acts, an adapter queues while offline. A false premise makes a check fail for a reason no fix to the change can reach.
- **Drive contract.** Every product-side name an e2e or walk check drives, settled before any code: DOM test ids and accessible names, routes and HTTP paths, the product's CLI commands and flags, wire and event names, and the file paths the checks read. The executor builds those names exactly, and the verifier writes its scripts against them alone.
- **Verify.** Proving the checks: an agent that did not write the code runs every check and records PASS, FAIL, or INCONCLUSIVE with its evidence, which `verify.py report --write` turns into `report.md`.
- **Tier.** How a check is proved, one of:
  - `e2e`: core behavior no unit spec can see, such as isolation, permissions, revocation, wire compatibility, perf budgets, and cross-surface flows. Proved by a zero-argument `<id>.check.<ext>` script the verifier writes and dry-runs on the base, and `verify.py rerun` runs on the real app once in full on the reviewed code.
  - `unit`: logic. Proved by a spec the executor writes, graded fail-first by `verify.py units`, with the check id in its test title so `units` records which spec proves it.
  - `walk`: UI look and interaction. The verifier walks it once on the real app and saves a screenshot or video in `evidence/<id>/`; no script.

Prove each fact at the cheapest level that can prove it, per the Prove at the Cheapest Level principle (`../../principles/references/principles/prove-at-the-cheapest-level.md`). E2E is the most expensive tier, because each script starts a real instance and runs for minutes, and every product fix after the e2e run reruns all of them. Pick `e2e` only for core behavior a unit spec cannot see, and give logic a spec can reach `unit`. Fewer is better, and a plan with no e2e check is fine. A plan holds at most 10 `e2e` checks, perf checks included, and `verify.py plan` refuses more with no override; 10 is a ceiling, not a target. Rank them by risk, keep the riskiest and costliest-to-break behavior, and move the rest to `unit` or drop them, or split the phase.

## Checks

Each check has these parts:

- **Scenario.** One user-visible behavior in user terms, with a concrete input and starting state.
- **Surface.** Where a user meets the behavior, from the table below.
- **Evidence.** The artifact that proves it: a screenshot, a video, a terminal transcript, a response body, a value read back.
- **Pass.** A predicate another agent can check against that evidence with no judgment call. "The export parses as JSON and holds 3 rows" is a predicate. "Export works" is not.
- **Tier.** `e2e`, `unit`, or `walk`, per the Terms above. `verify.py plan` refuses a check without one and prints the count per tier, and the `report` gate holds a PASS to its tier's evidence.
- **Base** (optional, e2e and perf checks). `passes: <why the base already has this behavior>`, written before the lock, for a check that guards behavior the base already has. It is the only way a check may pass its dry run on the base: `verify.py scripts` refuses any other check that passes there, because a check that passes without the change proves nothing about it.
- **Agent** (optional). `real: <why>` when the check needs a real coding agent (such as Claude Code or Codex) rather than a fake one, else `fake: <why>` or `n/a: <why>`. A real agent's subscription is reserved for the check, so guard keeps every delegate off it, and while its usage limit holds the check waits, which is not a FAIL.

When the change implements a skeleton from the architect skill, one **conformance** check adds a **Skeleton** field naming the skeleton files and symbols it covers, and passes when the skeleton's type tests pass unchanged against the implementation and its import guards hold; a difference from the skeleton goes in the spec or the design note with the user's agreement. Its Tier is `unit`: static specs the unit suite runs, with the check id in a test title, so it never spends the e2e budget, which exists for the cost of driving an app.

A check can also name a **Seed**: the dataset it starts from. Name one whenever the scenario needs data to exist, because a page with no data proves nothing about how it shows data.

## Oracle checks

When a check's result is computed from data (a total, count, sum, average, rate, ranking, filter, or any analytics number), the author's own reading of the screen is not proof: whoever wrote or watched the code sees what they expect. Split it between two agents that never see each other's work. An oracle reads only the spec and the seed data and writes the expected value. An observer reads the actual value from the running app and never sees the expected one. A script compares the two. A mismatch is a code bug, an oracle misreading, or an ambiguous spec, and an ambiguous spec is a product decision for the user.

Every check states its **Oracle**, and `verify.py plan` refuses a check without one, so the decision is made per check and shows in the plan. An oracle check's value is read from the running app, so its Tier is `e2e` or `walk`. It adds these fields:

- **Oracle.** The spec's definition of the value, in words precise enough to compute by hand: what is counted, over which rows, in which time zone, how ties and empties behave. For a check whose result is not computed from data, write `n/a: <why>`; a reviewer reads these, so a computed value marked n/a stands out.
- **Seed.** The dataset the value is computed from. Make it small enough to compute by hand and shaped to catch the likely mistakes: boundary dates, refunds, duplicates, empty groups, ties.
- **Shape.** The JSON both sides write, such as `{"<tier>": <revenue in cents>}`, so the comparison is mechanical. Lists compare in order, so a ranking is a list and an unordered set is an object.
- **Tolerance** (optional). The absolute difference allowed between numbers, for rounding the spec permits.

Cover:

1. **Behavior.** Every behavior the change adds or alters, including the edges settled with the user: empty input, errors, boundaries, permissions.
2. **Regression.** The load-bearing existing behavior the change could break, run on the base and on head. Name what must stay identical, such as byte-identical output or the same screen. When main lacks the feature, say so and gate head on its own predicates. In a phased feature these checks are the only regrade an earlier phase's behavior gets, because no phase reruns another phase's scripts, so name each earlier behavior this phase could break.
3. **Unit.** Unit-tier checks for logic with a cheap local test path, each a spec written to fail before the change and pass after, with the check id in its test title. Assert behavior per the Test Behavior, Not Implementation principle (`../../principles/references/principles/test-behavior-not-implementation.md`). Prefer no new test over a test of mocks, timing, or internals. Tests are one part of the plan, never all of it. Grade fail-first with `python3 ../scripts/verify.py units`: each spec file added or changed in the range, which defaults to the merge-base with the default branch through HEAD, fails on base plus the spec and passes at head, never judged from commit order, so commits group freely and no history is rewritten for evidence. A spec that already passes on base must be a regression guard in its own spec file containing the marker `regression-guard`. Compile-time type tests, import guards, and regression tests that pin behavior main already has cannot fail first: they land in the commit with the code they guard and are exempt from the fail-first predicate, so say so in the check.

## Premises

Before the design, test every check's premises against the code as it is, because a false premise found before the code costs a line and one found at the e2e run costs a fix round. The how skill's explorers do it, and its explainer writes two files beside the plan (the phase's folder, else the verification directory), each starting with a line `Base: <sha>`, the base commit it checked the code at:

- `grounding.md`: how the subsystems the checks run through work today, the starting model for the design and for the next phase.
- `premises.md`: one table with a row per premise and at least one row per check.

```
| Check | Premise | Holds | Evidence | Resolution |
|---|---|---|---|---|
| <id> | <a fact the check assumes already holds> | <yes, no, or new> | <file:line, or the command and its output> | <empty until the design; for a no: what the design adds, how the check changes, or where it moves> |
```

`verify.py premises` passes when both files name the phase's base in their `Base:` line (the commit `verify.py adopt` recorded, else the merge-base with main), every check id has a row, and every `yes` or `no` row has its Evidence. What the change itself builds is not a premise: a check whose behavior is new gets one row with Holds `new`, never one `no` per missing piece, because a table full of planned work buries the assumptions that are actually false, and the gate refuses a second `new` row for a check. The design fills the Resolution of every `no` row, and `verify.py premises --resolved` checks it. Never resolve a premise by guessing. A check the code cannot satisfy changes with the user's agreement, or the design adds what it needs.

## Drive contract

Every plan with an `e2e` or `walk` check lists, under `## Drive contract`, each product-side name those checks drive (never a driver command, which is the verifier's own, and `verify.py plan` refuses a contract line labeled `driver` or `harness`), one per line with what it is and which checks use it, and `verify.py plan` refuses the plan without it. It comes from the design, written at the last step before code. A name that exists today takes its real value from `grounding.md`, and a new one comes from the spec, the skeleton, or the design note. Every backticked HTTP path and CLI flag in a check's Scenario or Pass must appear in the contract, and `verify.py plan` names each one missing. A name stays fixed once locked: the executor implements it exactly, and a change it needs goes through `verify.py freeze --revision` with the user's agreement. The verifier drives only these names, so a script never depends on what the author happened to call something.

## Sensitive paths

Name, under `## Sensitive paths`, the paths or globs where a defect costs most: authentication, permissions, crypto, and similar. The reviewer looks hardest there. Write `n/a: <reason>` when the change touches none.

## Perf

Every plan decides its perf acceptance, because a correct result that is too slow still fails the user, and nobody measures what nobody asked for. For each path a user waits on that the change adds or alters (a page becoming usable, a command returning, a job finishing, a request answering), write one perf check, but only where the change adds work the user waits on or work that scales with data. A perf check is always `e2e`: its script measures main and head and compares against the Rule itself, and runs alone after the other scripts.

- **Path.** The wait as the user experiences it, at a stated, realistic data size.
- **Metric.** What is measured. Prefer a count (queries, requests, bytes, renders) when it captures the cost, because counts carry no run-to-run noise. Add a timing for the wait itself.
- **Probe.** The command or procedure, run on main and on head, interleaved. Both sides must produce the metric. Name the data source per the benchmark-checklist skill's "Where to measure" section (`../../benchmark-checklist/SKILL.md`): read-only production when available.
- **Baseline.** `main` when main already has the path; the verifier measures main first. `none: <why>` when main lacks it.
- **Rule.** The number that fails. Against a `main` baseline, a relative limit such as "p50 more than 5% slower than main" or "any added query". With no baseline, absolute budgets for both the work the change adds and the end state the user waits for, such as "the list is usable within 1 s with 10,000 rows". Never claim a ratio between unlike scenarios.

Propose the budgets from the user's stated expectations, comparable paths in the same app, and common thresholds (about 100 ms feels instant, about 1 s keeps the user in flow), and let the user decide. "Not slower than main" on a path the change leaves untouched is `n/a`, because nothing could have moved it. When the change alters nothing a user waits on, write `n/a: <reason>` under the Perf heading. The user sees it and can reject it.

## Surface by change

| Change | Surface | Check |
|---|---|---|
| CLI | A real terminal | Run the real command and compare stdout, stderr, and exit code |
| Web UI | A real browser through chrome-devtools-axi | Walk the changed flow; diff screenshots against a frozen baseline when it must match pixel for pixel |
| API or service | HTTP | Send a real request, check status and body, read the side effect back |
| Agent-facing tool (MCP, an agent API) | A direct protocol client; a real agent run only for checks about how an agent reads the tool | Call the tool with set arguments and check the result. Spend a real agent run, which costs a model turn per call, only where the check is whether an agent picks the right tool or argument from a sentence |
| Parser, migration, or transform | Saved inputs | Replay recorded inputs and diff old against new outputs |
| Storage | The store | Write, then read back through the public path |
| Refactor | The surface the code serves | Same inputs give the same outputs before and after |
| Performance | A benchmark | Interleave main and head, vetted with the benchmark-checklist skill |

A check that compares against a baseline treats the baseline as the spec. Capture it before the change, and never edit the baseline, the harness, or the component to make a diff pass. If the baseline looks wrong, stop and ask.

## Revising the plan

A design, a prototype, or a false premise can show that a predicate or a budget was wrong, or that a check is missing. Revise the plan then, with the user's agreement, before the lock. After the lock, `verify.py freeze` sorts each change on its own. A change that only adds checks, Drive contract names, or Sensitive paths is recorded as an addition and passes, because it narrows nothing. Any other change, to any field, the title, or the text of an existing check, a removed check or line, any other added line, or the perf decision and its n/a reason, happens only under the verify skill's Fixed goalposts rule, recorded with `verify.py freeze --revision "<what and why>"` and, in an autonomous run, `--gate <id>` of the autorun gate the user answered, never to make a check pass. The report lists every revision.

## Autonomous runs

When the `autorun` skill has a run active, the plan is its done condition. Restart the run with the predicates and budgets as `--done` and `--check "python3 <verify skill>/scripts/verify.py report"`, so `done` refuses until they hold. `start` records the shell's cwd, so run it inside the worktree, or pass `--cwd <worktree>`, because the check runs there.
