# Backlog

Work agreed on but not started. Each item names where it came from, the problem, and a direction. When work starts, move it into the change and delete it here.

## Arena never reaches its quorum rule while a runner waits on a usage limit

- **Source.** 2026-10-20 arena run on feature tiers: fable and opus finished at 00:00 and 00:06, codex waited on its usage limit until 00:23, and the lead sat idle until the user noticed.
- **Problem.** Arena Phase B says to continue without a runner stopped on a usage limit once two structurally distinct candidates are complete. Salvo's `run` blocks until every run finishes, and the harness notifies the lead only when that background command exits, so nothing tells the lead that the quorum holds. Polling the output is denied by guard. The rule is unreachable as written.
- **Direction.** Give salvo a quorum exit, such as `--quorum N`, that returns once N runs are done and every other run is waiting on a limit or still running, leaving those runs resumable and recorded in `salvo.json`; or have arena watch salvo's `finished` and `waiting` lines with a Monitor until-condition instead of a bare background run. Either way, add a test that a limit-waiting runner does not hold back a met quorum.

## Remove the phase and premise machinery no playbook runs anymore

- **Source.** 2026-10-28, replacing the flow v2.1 feature and plan-feature skills (archived in `docs/archive/flow-v21/`). The new feature skill has no plan lock, premises, or adopted phase plans, and plan-feature no longer writes phase plans.
- **Problem.** `verify.py adopt`, `premises`, `phases`, and `spec`, the how skill's "With a verification plan" section, the Premises section of `verify/references/plan.md`, and guard's reading of an adopted phase plan for reserved subscriptions now serve no playbook. They were left in place so the rewrite of the skills landed as one change.
- **Direction.** Delete the four commands with their tests and help text, the how section, the plan.md Premises section, and the adopted-plan lookup in guard, and check that bug-fix and verify still pass `guard.py lint` and the suite.
