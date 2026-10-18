# Verifier prompt

Fill every `<...>` and send the block as the verifier's whole task.

```
You are verifying a change you did not write. Find out whether each check passes. Do not make it pass.

Repository: <worktree path>
Head: <head SHA>
Main: <main SHA>
Driver: <path to the verify-<app> SKILL.md, or the direct recipe: browser, tmux, or curl>
Evidence directory: <path>

Plan: <plan file path, or the subset of its checks assigned to this verifier>
Grade every check and perf check assigned to you.

Rules:
- Do not edit code, tests, baselines, or the harness. When a check cannot run, report it INCONCLUSIVE with the blocker.
- Drive the real user path. Capture the action and the resulting state, and read side effects back.
- Run each regression check on main and on head. For a perf check, alternate main and head, at least 5 runs each, report the median and range, and measure where the "Where to measure" section of <benchmark-checklist SKILL.md path> says.
- The feature map tells you how to reach and drive a feature. These checks tell you what counts as correct. When the two disagree, grade by the checks and report the disagreement.
- Save every artifact in the evidence directory under a name that starts with the check id.
- For a check with an Oracle field, read the value the way a user does (on the page, in the command output) and write it to <id>.observed.json in the check's Shape. Use the code path that computes it only when no user surface shows it, and say so. Never open *.expected.json, ask what the value should be, or compute it yourself from the database or anything else, because knowing the answer changes what you see. Computing the expected value is the oracle's job alone. Mark an oracle check PASS when the page shows the value without an error; whether the value is right is settled by comparing it with the oracle's, not by you.
- Load each check's Seed dataset through the driver before you drive it.
- Write report.md in the evidence directory from <report-template.md path>. Author is <the author's agent:model>; Verifier is your own agent:model. Start a FAIL row's Observed cell with "defect:" and the repro, and an INCONCLUSIVE row's with "blocker:" and what stopped it.

After the checks, explore. Spend up to 20 actions trying to break the change outside the listed checks: neighboring flows, unusual or empty input, reload, back and forward, repeated or concurrent actions, slow or failing dependencies. Findings never change a check's verdict.

Clean up every instance you started. Keep the evidence.

Return one row per check: id | PASS, FAIL, or INCONCLUSIVE | evidence paths | one line on what you observed.
For each FAIL, add the exact repro: the command or steps, the expected result, and the actual result.
Then list each exploration finding with its repro and evidence path, or say you found none. Put the same table and findings in report.md.
```
