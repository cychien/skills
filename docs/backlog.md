# Backlog

Work agreed on but not started. Each item names where it came from, the problem, and a direction. When work starts, move it into the change and delete it here.

## Arena never reaches its quorum rule while a runner waits on a usage limit

- **Source.** 2026-10-20 arena run on feature tiers: fable and opus finished at 00:00 and 00:06, codex waited on its usage limit until 00:23, and the lead sat idle until the user noticed.
- **Problem.** Arena Phase B says to continue without a runner stopped on a usage limit once two structurally distinct candidates are complete. Salvo's `run` blocks until every run finishes, and the harness notifies the lead only when that background command exits, so nothing tells the lead that the quorum holds. Polling the output is denied by guard. The rule is unreachable as written.
- **Direction.** Give salvo a quorum exit, such as `--quorum N`, that returns once N runs are done and every other run is waiting on a limit or still running, leaving those runs resumable and recorded in `salvo.json`; or have arena watch salvo's `finished` and `waiting` lines with a Monitor until-condition instead of a bare background run. Either way, add a test that a limit-waiting runner does not hold back a met quorum.

## Feature tiers steer the lead to TaskStop where SendMessage would do

- **Source.** 2026-10-20 review of `skills/eng/feature/SKILL.md` while asking whether SendMessage interrupts a running subagent. It does not: the message queues until the subagent's next tool boundary, and neither guard nor autorun (`policy.py` lets SendMessage through) blocks it.
- **Problem.** Step 8's "stopping the previous agent's task and running `verify.py leftovers --kill` before another touches it" and the closing "Spawn a fresh owner rather than chaining interrupts, and a fresh executor for follow-up work rather than resuming a long one" read as if SendMessage were an interrupt. A lead that wants to correct a running executor then stops it and respawns, losing its progress and paying setup again.
- **Direction.** In feature and quick-feature, separate the three cases: correct or extend a running agent with SendMessage; give follow-up work after a long agent finished to a fresh executor; TaskStop only to hand a worktree to another agent. Replace "chaining interrupts" with wording that names TaskStop.
