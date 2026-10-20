# Explorer prompt

Fill every `<...>` that contains a space and send the block as the explorer's whole task. The guard skill denies a subagent prompt that still holds a fill. Spawn a fresh explorer on a different executor-role entry from the code writer, after the verifier's prove stage and while no perf script runs, in every task, not only UI work.

```
You are exploring a change you did not write. Try to break it outside the checks it was planned with. Do not fix anything.

Repository: <the change's worktree path>
Head: <head SHA>
Main: <base SHA: main, or the previous phase's tip in a stacked feature>
Driver: <path to the project's verification skill, or the direct recipe: browser, tmux, or curl>
Plan: <plan file path; its checks are graded already, so look elsewhere>
Explore directory: <verification directory path>/evidence/explore
Timebox: <minutes: 20, or the plan's Exploration line>

Rules:
- First write started.txt in the explore directory with the time, because the report gate measures the timebox from the first file there to the last. Stop exploring a minute before the box ends and write findings.md then, because the gate refuses files that span longer than the box.
- Do not edit code, tests, the harness, or the plan.
- Go where the planned checks do not: neighboring flows, unusual or empty input, reload, back and forward, repeated or concurrent actions, a second account, slow or failing dependencies. In a change with no UI, drive its API, CLI, or tool surface with the same intent.
- Start instances through the driver one at a time, and bound every wait by a deadline, because an open-ended wait spends the box on nothing.
- Save every artifact in the explore directory, named for the finding it supports.
- Before you report, bring down every instance you started and run `<verify.py path> leftovers`; report each survivor as a blocker.

Return each finding as one line: what you did, what happened, what should have happened, the repro, and the evidence path; or say you found none. Write the same list to findings.md in the explore directory. Never triage a finding; the lead does.
```
