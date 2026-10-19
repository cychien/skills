# Backlog

Work agreed on but not started. Each item names where it came from, the problem, and a direction. When work starts, move it into the change and delete it here.

## Arena never reaches its quorum rule while a runner waits on a usage limit

- **Source.** 2026-10-20 arena run on feature tiers: fable and opus finished at 00:00 and 00:06, codex waited on its usage limit until 00:23, and the lead sat idle until the user noticed.
- **Problem.** Arena Phase B says to continue without a runner stopped on a usage limit once two structurally distinct candidates are complete. Salvo's `run` blocks until every run finishes, and the harness notifies the lead only when that background command exits, so nothing tells the lead that the quorum holds. Polling the output is denied by guard. The rule is unreachable as written.
- **Direction.** Give salvo a quorum exit, such as `--quorum N`, that returns once N runs are done and every other run is waiting on a limit or still running, leaving those runs resumable and recorded in `salvo.json`; or have arena watch salvo's `finished` and `waiting` lines with a Monitor until-condition instead of a bare background run. Either way, add a test that a limit-waiting runner does not hold back a met quorum.
