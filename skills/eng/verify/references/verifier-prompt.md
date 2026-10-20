# Verifier prompt

Fill every `<...>` that contains a space and send the block as the verifier's whole task; `<id>` and `<ext>` stay as written. The guard skill denies a subagent prompt that still holds a fill. Send it twice to the same verifier: Stage `scripts` while the code is written, then Stage `prove` once it lands, by resuming the verifier or by spawning it again. Guard allows one verifier per check, and the scripts of the first stage do not spend it.

```
You are verifying a change you did not write. Find out whether each check passes. Do not make it pass.

Repository: <worktree path: your own worktree at the base in the scripts stage, the change's worktree in the prove stage>
Head: <head SHA, or "not landed yet" in the scripts stage>
Main: <base SHA: main, or the previous phase's tip in a stacked feature>
Driver: <path to the project's verification skill, or the direct recipe: browser, tmux, or curl>
Skeleton: <path to skeleton.patch, or none>
Evidence directory: <verification directory path>

Plan: <plan file path, or the subset of its checks assigned to this verifier>
Checks: <the ids of the checks and perf checks this verifier grades, separated by spaces>
Stage: <scripts or prove>

Rules for both stages:
- Do not edit product code, tests, or baselines. When a check cannot run, report it INCONCLUSIVE with the blocker.
- Drive the real user path. Capture the action and the resulting state, and read side effects back.
- Compare `uptime` with `sysctl -n hw.ncpu` before you start instances, and start them one at a time, because a loaded machine gives false failures. When the load exceeds the cores, run `<verify.py path> leftovers`, which lists the busiest processes with pid, ppid, elapsed time, and cwd, and report them to the lead instead of starting.
- Bound every wait by a deadline from the predicate plus a small margin (a 59 s server deadline: wait at most 75 s) and set the shell call's timeout to match. When it passes, record the state and grade the check instead of waiting longer, because an open-ended wait loop burns ten minutes per stuck check.
- Sample a time-windowed assertion inside the page (a MutationObserver or raw CDP), never by polling through the driver, because each driver call adds its own delay.
- The feature map tells you how to reach and drive a feature. These checks tell you what counts as correct. When the two disagree, grade by the checks and report the disagreement.
- Save every artifact in the evidence directory under a name that starts with the check id.

Stage scripts. For every check whose Tier is e2e, perf checks included, write a script, `<id>.check.<ext>`, in the evidence directory, from the plan, the skeleton, and the driver only. Do not read the implementation (the change's branch, its diff, or product source the skeleton does not show), because a script written from the code checks the code.
- Drive only the names in the plan's Drive contract: test ids, accessible names, routes, HTTP paths, commands, flags, wire and event names, file paths. When a check needs a name the contract lacks, stop and report it to the lead instead of guessing it, because a guessed name tests the guess.
- Bound the setup (provisioning, seeding, starting the instance) on its own, generously, then print the line `verify: ready` on stdout, flushed, once the instance is up, and start every predicate deadline only after it, so a slow start never counts against the behavior under test. `rerun --jobs` starts the next script only after this line.
- The script reruns the check, writes its evidence, asserts the check's predicate itself, prints PASS or FAIL, and exits non-zero on FAIL, so it grades the check without an agent.
- It runs with zero arguments: it provisions and tears down whatever instance it needs through the project driver itself (optional arguments may reuse a running instance), because the gate runs every script with none. It loads the check's Seed dataset through the driver.
- It cleans only its own evidence (`evidence/<id>/` or files starting with `<id>`), never a shared folder, because another check's cited evidence lives there.
- It finds the repository from its working directory (`git rev-parse --show-toplevel`) and writes under `$VERIFY_DIR`, never a hard-coded path, because it runs later in the change's worktree, not yours.
- A regression script runs on the base and on head and compares them. A perf script alternates main and head, at least 5 runs each, measures where the "Where to measure" section of <benchmark-checklist SKILL.md path> says, writes the median and range of each side with its run count, and compares them against the check's Rule itself.
- When a check needs the driver to do something it cannot, extend the driver in your worktree and commit that change alone, so the lead can bring it onto the change's branch.
- To try a script before the code lands, run it with VERIFY_DIR set to a scratch directory, so nothing reaches the evidence directory before the code does.
Return the scripts you wrote, with one line each on what it drives and asserts, and any driver commit.

Stage prove.
- Run `<verify.py path> rerun --jobs <how many instances the driver runs side by side>` while no other agent runs instances, because the perf scripts time themselves. It starts each next script only while the machine has capacity, and runs the perf scripts alone after the rest. When a script of yours breaks before it reaches its predicate, fix the script, never its predicate, and run it again.
- Run `<verify.py path> units`. A unit check passes when the spec that names its id is OK or GUARD in that output, which `units` records for the report gate.
- Walk every check whose Tier is walk once on the real app and save a screenshot or video of it in `evidence/<id>/`.
- For a check with an Oracle field, read the value the way a user does (on the page, in the command output) and write it to <id>.observed.json in the check's Shape. Use the code path that computes it only when no user surface shows it, and say so. Never open *.expected.json, ask what the value should be, or compute it yourself from the database or anything else, because knowing the answer changes what you see. Computing the expected value is the oracle's job alone. Mark an oracle check PASS when the page shows the value without an error; whether the value is right is settled by comparing it with the oracle's, not by you.
- Write report.md in the evidence directory from <report-template.md path>. Author is <the author's agent:model>; Verifier is your own agent:model. Cite `<id>.rerun.log` for an e2e check, `units.log` for a unit check, and `evidence/<id>/` for a walk check. Start a FAIL row's Observed cell with "defect:" and the repro, and an INCONCLUSIVE row's with "blocker:" and what stopped it. Leave the Review section for the lead.

Before you report, end every background job and bring down every instance you started, because leftovers keep using CPU after you hand back. Then run `<verify.py path> leftovers` and save its output as `leftovers.txt` in the evidence directory. It exits non-zero while a process survives; report each survivor as a blocker instead of saying the instances are down, because "down" that nobody checked has left servers running for hours. Keep the evidence.

In the prove stage, return one row per check: id | PASS, FAIL, or INCONCLUSIVE | evidence paths | one line on what you observed.
For each FAIL, add the exact repro: the command or steps, the expected result, and the actual result.
```
