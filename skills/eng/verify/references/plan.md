# Verification plan

Write the plan before the design, with the requirements. A pass predicate and a perf budget are product decisions as much as the spec is, and a check or budget written after the code tends to describe the code instead of the requirement.

Write it as `plan.md` in the verification directory that `python3 ../scripts/verify.py where` prints (a path beside this file's folder), from `plan-template.md` beside this file. `verify.py plan` checks its shape, and the playbook step that writes the plan closes only when that passes, so a check without a predicate or a plan without a perf decision cannot reach a verifier.

## Checks

Each check has four parts:

- **Scenario.** One user-visible behavior in user terms, with a concrete input and starting state.
- **Surface.** Where a user meets the behavior, from the table below.
- **Evidence.** The artifact that proves it: a screenshot, a video, a terminal transcript, a response body, a value read back.
- **Pass.** A predicate another agent can check against that evidence with no judgment call. "The export parses as JSON and holds 3 rows" is a predicate. "Export works" is not.

When the change implements a skeleton from the architect skill, one **conformance** check adds a **Skeleton** field naming the skeleton files and symbols it covers, and passes when the implemented signatures match the skeleton or each difference is in the design addendum with the user's agreement.

A check can also name a **Seed**: the dataset it starts from. Name one whenever the scenario needs data to exist, because a page with no data proves nothing about how it shows data.

## Oracle checks

When a check's result is computed from data (a total, count, sum, average, rate, ranking, filter, or any analytics number), the author's own reading of the screen is not proof: whoever wrote or watched the code sees what they expect. Split it between two agents that never see each other's work. An oracle reads only the spec and the seed data and writes the expected value. An observer reads the actual value from the running app and never sees the expected one. A script compares the two. A mismatch is a code bug, an oracle misreading, or an ambiguous spec, and an ambiguous spec is a product decision for the user.

Every check states its **Oracle**, and `verify.py plan` refuses a check without one, so the decision is made per check and shows in the plan. An oracle check adds three fields:

- **Oracle.** The spec's definition of the value, in words precise enough to compute by hand: what is counted, over which rows, in which time zone, how ties and empties behave. For a check whose result is not computed from data, write `n/a: <why>`; a reviewer reads these, so a computed value marked n/a stands out.
- **Seed.** The dataset the value is computed from. Make it small enough to compute by hand and shaped to catch the likely mistakes: boundary dates, refunds, duplicates, empty groups, ties.
- **Shape.** The JSON both sides write, such as `{"<tier>": <revenue in cents>}`, so the comparison is mechanical. Lists compare in order, so a ranking is a list and an unordered set is an object.
- **Tolerance** (optional). The absolute difference allowed between numbers, for rounding the spec permits.

Cover:

1. **Behavior.** Every behavior the change adds or alters, including the edges settled with the user: empty input, errors, boundaries, permissions.
2. **Regression.** The load-bearing existing behavior the change could break, run on the base (main, or the previous phase's tip in a stacked feature) and on head. Name what must stay identical, such as byte-identical output or the same screen. When main lacks the feature, say so and gate head on its own predicates.
3. **Unit.** Tests for logic with a cheap local test path, written to fail before the change and pass after. Assert behavior per the Test Behavior, Not Implementation principle (`../../principles/references/principles/test-behavior-not-implementation.md`). Prefer no new test over a test of mocks, timing, or internals. Tests are one part of the plan, never all of it. Grade fail-first with `python3 ../scripts/verify.py units`: each spec file added or changed in the range, which defaults to the merge-base with the default branch through HEAD, fails on base plus the spec and passes at head, never judged from commit order, so commits group freely and no history is rewritten for evidence. A spec that already passes on base must be a regression guard in its own spec file containing the marker `regression-guard`. Compile-time type tests, import guards, and regression tests that pin behavior main already has cannot fail first: they land in the commit with the code they guard and are exempt from the fail-first predicate, so say so in the check.

## Perf

Every plan decides its perf acceptance, because a correct result that is too slow still fails the user, and nobody measures what nobody asked for. For each path a user waits on that the change adds or alters (a page becoming usable, a command returning, a job finishing, a request answering), write one perf check, but only where the change adds work the user waits on or work that scales with data:

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

A design or a prototype can show that a predicate or a budget was wrong, or that a check is missing. Revise the plan then, with the user's agreement, before any verifier runs, and list the revision in the report. Once the plan is frozen for a verifier, a predicate or budget changes only under the verify skill's Fixed goalposts rule, recorded with `verify.py freeze --revision`, never to make a check pass.

## Autonomous runs

When the `autorun` skill has a run active, the plan is its done condition. Restart the run with the predicates and budgets as `--done` and `--check "python3 <verify skill>/scripts/verify.py report"`, adding `&& python3 <verify skill>/scripts/verify.py rerun` when every check is scripted, so `done` refuses until they hold. `start` records the shell's cwd, so run it inside the worktree, or pass `--cwd <worktree>`, because the check runs there.
