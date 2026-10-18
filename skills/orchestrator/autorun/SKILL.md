---
name: autorun
description: Autonomous mode - keep working until a task is verifiably done instead of stopping to ask the user, with questions routed through a classifier and an independent reviewer, and hooks that enforce it in Claude Code, Codex, Cursor, Copilot CLI, and Gemini CLI. Use whenever a hook message says autonomous mode is on, whenever the user wants a task finished unattended ('run until done', 'going to bed', 'don't ask me', 'full auto', '跑到完', '不要問我', '自動模式'), or to install, configure, or debug autorun's hooks.
---

# Autorun

In autonomous mode the user has handed the task over and stepped away. Every stop to ask costs them a round trip, often hours, so you decide what you can and stop only for calls where a wrong guess is expensive.

Hooks enforce this, so you do not have to remember it. While a run is active they deny question tools, block stopping until the run is done, hold back irreversible commands, route permission prompts to a reviewer, and carry the run into subagents and agent CLIs you launch. A denial or a blocked stop is the protocol telling you the next step, not an error to work around. Every command you need, with the run id filled in, is in the hook's message; `scripts/autorun.py` is this skill's CLI.

## Work the run

1. **Set the done condition first.** Write it as a predicate someone else could check: tests green, the repro no longer reproduces, the page matches the design. Pass `--check` with a command that exits 0 only when it holds, whenever one exists, because `done` then runs it and you cannot declare victory early. If the condition turns out to be wrong, rerun `start` to replace it; every replacement is shown in the final report.

   ```
   python3 scripts/autorun.py start --run <id> --done "<condition>" [--check "<command>"]
   ```

2. **Work in verifiable units.** Make the smallest change the evidence supports, verify it against the predicate, commit when it moves forward, and revert what did not help. A plateau means change approach, not stop.
3. **Route every question.** Do not ask the user in a question tool or in plain text, and do not end a turn on a question. Give your own best answer in `--pick`, since that is what proceeds when the call is yours:

   ```
   python3 scripts/autorun.py ask --run <id> --kind <kind> --question "..." [--option "..."]... --pick "..." --why "..." --confidence <high|medium|low>
   ```

   | kind | when | result |
   |---|---|---|
   | `detail` | a reversible execution detail | high confidence: proceed with your pick, logged. Otherwise reviewed like `direction` |
   | `choice` | picking among options | same as `detail` |
   | `direction` | product direction where a wrong call sends the whole output the wrong way | an independent model reviews it; it proceeds unless the reviewer agrees it needs the user |
   | `irreversible` | cannot be undone: force push, deploy, publish, deleting data, messaging people | always goes to the user; add `--command` with the exact command so the identical call passes once approved |
   | `dead-end` | you cannot make progress after changing approach | goes to the user |

   Do what the output says. `DECIDED` means carry on and list it in the final report. `ESCALATED` means stop that line of work: as the main agent, ask the user now and end your turn; as a subagent or delegate, end your turn with `AUTORUN-BLOCKED gate=<id>` and what is done and left.
4. **Handle permission denials.** A reviewer has already seen any permission prompt or auto-mode denial you hit: what it judged routine was allowed or retried. A denial that stands means it needs the user, so if the action is still necessary, escalate it with `--kind irreversible` and `--command` set to the exact call, and do not hunt for a workaround that does the same thing.
5. **Fix what you find.** Broken tooling, flaky tests, and related bugs on the path are yours to fix. Note out-of-scope discoveries for the report instead of chasing them.
6. **Delegate normally.** Subagents and agent CLIs you launch join the run on their own. When one comes back with `AUTORUN-BLOCKED`, ask the user, then give the original task plus the answer to a fresh subagent, because a resumed one may drop earlier instructions.
7. **Wait without spinning.** Stopping while background tasks or scheduled wakeups are pending is allowed, so wait for those instead of polling.
8. **Finish.** When the predicate holds, run `python3 scripts/autorun.py done --run <id> --evidence "<proof>"`. It refuses while the check fails or a gate is unanswered, then an independent model compares the user's request with the run's changes. It rejects placeholders standing in for requested content, skipped parts, and weakened tests, and escalates a gap only the user can fill. Never weaken the done condition to get past it.

To start a run without a trigger phrase, for example when the user asked for an unattended run in other words, run `start --done ...` without `--run`. It creates a run for the current session. When a prompt invokes a skill by `/name` without a trigger phrase, the hooks hold every tool call until you decide the run mode: `start` if the user's words ask for an unattended run, or `python3 scripts/autorun.py mode interactive --reason "..."` otherwise. Any skill reached directly gets this decision without carrying it, and the decision cannot be skipped. The user can also switch it on with `/auto` anywhere in a prompt, so it combines with another skill's command (`/feature add export /auto`). The user leaves autonomous mode by saying so ("stop autonomous mode", "結束自動模式", `/auto off`) or with `python3 scripts/autorun.py stop`.

## Install

Hooks are not installed with the skill. Run `python3 scripts/autorun.py install` once. It registers the hooks in the user-level config of every agent it detects (`--agent <name>` limits it, `--print` only prints) and leaves other hooks alone. Then tell the user:

- A config reached through a symlink is written at its target, so home-manager out-of-store links work. A read-only config, such as a file in the nix store, is not written; the command prints the entries to merge where it is generated.
- Codex runs new hooks only after the user approves them in `/hooks`. Its workspace-write sandbox blocks the run state and the reviewer's network calls, so the command prints the sandbox settings an unattended Codex run needs.
- The hooks take effect in new sessions. They exit immediately when no run is active.
- Permission review works where the agent lets a hook grant a call: Claude Code, Codex, and Copilot CLI. Cursor and Gemini CLI still show their own approval prompts, so start those sessions with their auto-approve mode (`--force`, `--yolo`) for unattended runs.

The same hooks run the `guard` skill's rules when guard is installed beside this skill.

`python3 scripts/autorun.py uninstall` removes only autorun's entries.

## Configure

`~/.agents/autorun/config.json` overrides any of these keys: `enter` and `exit` (regexes matched against the user's prompt), `irreversible_commands` and `irreversible_tools` (lists of `[label, regex]`), `stop_idle_limit` (stops in a row without progress before the run becomes a dead-end gate, default 3), `notify` (a shell command run with `$AUTORUN_MESSAGE` when the run needs the user), `review` (false skips the independent reviewer), and `review_command` (a shell command that reads the review prompt on stdin and prints the JSON verdict, replacing the default reviewer). By default the reviewer is the planner role from the `setup-orchestrator` config, preferring a different agent from the one asking. With no reviewer, escalations and permission prompts go to the user and `done` relies on the check alone.

State lives in `~/.agents/autorun/`: one folder per run with `run.json`, `decisions.jsonl`, and `gates/`. Hook failures are logged to `errors.log` and never block the agent. Set `AUTORUN_TRACE=1` in the agent's environment to log every hook decision to `trace.jsonl`. A launcher whose children must not join the caller's run, such as a blind experiment, sets `AUTORUN_BOUNDARY_PID` to its own pid: the process search that makes a child a delegate stops there. A delegate cannot replace the root's done condition; `start` refuses it.

## Output

When the run finishes, base the final reply on `python3 scripts/autorun.py report --run <id>`: the done condition and its evidence, what changed, every decision made without the user and its basis, every escalation and its answer, and the out-of-scope findings you noted. Flag decisions the user may want to revisit.
