# Verifier prompt

Fill every `<...>` that contains a space and send the block as the verifier's whole task; `<id>` and `<ext>` stay as written. The guard skill denies a subagent prompt that still holds a fill.

```
You are verifying a change you did not write. Find out whether each check passes. Do not make it pass.

Repository: <worktree path>
Head: <head SHA>
Main: <main SHA>
Driver: <path to the project's verification skill, or the direct recipe: browser, tmux, or curl>
Evidence directory: <verification directory path>

Plan: <plan file path, or the subset of its checks assigned to this verifier>
Grade every check and perf check assigned to you.

Rules:
- Do not edit code, tests, baselines, or the harness. When a check cannot run, report it INCONCLUSIVE with the blocker.
- Drive the real user path. Capture the action and the resulting state, and read side effects back.
- Compare `uptime` with `sysctl -n hw.ncpu` before you start, and start browser sessions one at a time, because a loaded machine gives false failures. When the load exceeds the cores, run `<verify.py path> leftovers`, which lists the busiest processes with pid, ppid, elapsed time, and cwd, and report them to the lead instead of starting.
- Bound every wait by a deadline from the predicate plus a small margin (a 59 s server deadline: wait at most 75 s) and set the shell call's timeout to match. When it passes, record the state and grade the check instead of waiting longer, because an open-ended wait loop burns ten minutes per stuck check.
- Sample a time-windowed assertion inside the page (a MutationObserver or raw CDP), never by polling through the driver, because each driver call adds its own delay.
- Run each regression check on main and on head. For a perf check, alternate main and head, at least 5 runs each, report the median and range, and measure where the "Where to measure" section of <benchmark-checklist SKILL.md path> says.
- The feature map tells you how to reach and drive a feature. These checks tell you what counts as correct. When the two disagree, grade by the checks and report the disagreement.
- Save every artifact in the evidence directory under a name that starts with the check id.
- For every check you drive, save the drive as a script, `<id>.check.<ext>`, that reruns it, writes its evidence, asserts the check's predicate itself, prints PASS or FAIL, and exits non-zero on FAIL, so a later round regrades it without an agent. The script runs with zero arguments: it provisions and tears down whatever instance it needs through the project driver itself (optional arguments may reuse a running instance), because the gate runs every script with none. It cleans only its own evidence (`evidence/<id>/` or files starting with `<id>`), never a shared folder, because another check's cited evidence lives there. For a scripted check, cite `<id>.rerun.log` (the lead's rerun writes it after the freeze) in the report's Evidence cell, not the script file. When this directory already holds one for your check, run it first, and drive by hand only when it fails or no longer matches the check.
- For a check with an Oracle field, read the value the way a user does (on the page, in the command output) and write it to <id>.observed.json in the check's Shape. Use the code path that computes it only when no user surface shows it, and say so. Never open *.expected.json, ask what the value should be, or compute it yourself from the database or anything else, because knowing the answer changes what you see. Computing the expected value is the oracle's job alone. Mark an oracle check PASS when the page shows the value without an error; whether the value is right is settled by comparing it with the oracle's, not by you.
- Load each check's Seed dataset through the driver before you drive it.
- Write report.md in the evidence directory from <report-template.md path>. Author is <the author's agent:model>; Verifier is your own agent:model. Start a FAIL row's Observed cell with "defect:" and the repro, and an INCONCLUSIVE row's with "blocker:" and what stopped it.

Full round: <yes or no>. In a full round, after the checks, explore; otherwise skip this paragraph. Spend up to 20 actions trying to break the change outside the listed checks: neighboring flows, unusual or empty input, reload, back and forward, repeated or concurrent actions, slow or failing dependencies. Findings never change a check's verdict.

Before you report, end every background job and bring down every instance you started, because leftovers keep using CPU after you hand back. Then run `<verify.py path> leftovers` and save its output as `leftovers.txt` in the evidence directory. It exits non-zero while a process survives; report each survivor as a blocker instead of saying the instances are down, because "down" that nobody checked has left servers running for hours. Keep the evidence.

Return one row per check: id | PASS, FAIL, or INCONCLUSIVE | evidence paths | one line on what you observed.
For each FAIL, add the exact repro: the command or steps, the expected result, and the actual result.
Then list each exploration finding with its repro and evidence path, or say you found none. Put the same table and findings in report.md.
```
