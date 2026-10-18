---
name: update-orchestrator
description: Bring the orchestrator model config up to date with newly released or retired models, keeping the user's subscriptions and the shape of each role. Use this whenever the user mentions a new model release and wants the orchestrator to use it, asks to refresh or update the orchestrator models, or an orchestrator skill fails because a configured model no longer exists.
---

# Update orchestrator

The orchestrator config, written by the **setup-orchestrator** skill (`../setup-orchestrator/SKILL.md`), names a model for every slot in each role. Providers release and retire models, so a slot can fall behind while the user's subscriptions stay the same. This skill swaps the models in those slots and leaves everything else alone, because the user already chose the subscriptions, the order, and the efforts, and an update that reshuffles them undoes those choices.

An entry moves only to a newer version of its own model line, such as `gpt-5.6-sol` to `gpt-6-sol`, never to a different line such as `gpt-6-astra`, because the line is what the user's plan was sized to sustain. A stronger model that a plan cannot sustain burns through its limit and stalls the user's own work. This holds when the user asks for "the latest models" too; a different line enters the config only when the user names it.

Talk to the user in plain terms: which models are new, and which entries change. Model lines and catalogs are your working.

## Steps

1. **Find the config.** Use `<project>/.agents/orchestrator/models.json` when you were loaded from a project-level install, otherwise `~/.agents/orchestrator/models.json`, the same scope rule setup-orchestrator uses. When the file is missing, has no `subscriptions` field (a version 1 file), or the user says a subscription changed, follow setup-orchestrator instead, because new capacity reshapes the roles rather than swapping models in place.
2. **Plan.** Run `python3 scripts/plan.py <config path>`. It reads the catalogs and marks each entry `keep`, `replace` (with the newer model of its line and the effort mapped onto it), or `retired` (no newer model of its line to take the slot). It keeps an older model whose successor is already in the role, because that slot adds a voice on purpose. Take its plan as the change set; do not add swaps of your own.
3. **Resolve the exceptions.**
   1. For a `retired` entry, pick a replacement by setup-orchestrator's steps 4.3 to 4.5 (`../setup-orchestrator/SKILL.md`), at the tier the retired model held and within the capacity its agent's subscription sustains.
   2. When a replacement in the executor carries a `notice` that it uses limits faster, keep the old model if it is still in the catalog, because setup-orchestrator sized the executor without that cost.
4. **Probe every entry.** Run `python3 ../setup-orchestrator/scripts/verify.py <agent>:<model>[:<effort>] ...` on every entry exactly as it will be written, kept ones included, because a model can stop running for this account before it leaves the catalog. A kept entry that fails becomes `retired`; resolve it by step 3. A replacement that fails falls back to the old entry when that one passed; otherwise ask the user for a replacement, with the error in the question.
5. **Stop when nothing changes.** Tell the user the config already uses the newest model of every line it holds, and write nothing. Mention `new_lines` as in step 6.
6. **Confirm.** Ask with your structured question tool (`AskUserQuestion` in Claude Code), falling back to plain text only when there is none, in one question. Put the changes in the question text, one line per changed entry, grouped by role, so the user sees exactly what moves:

   ```
   Planner
   2. <old model> · <effort> → <new model> · <effort> · <agent>

   Executor
   1. <old model> · <effort> → <new model> · <effort> · <agent>

   Apply these updates?
   ```

   Below the changes, name the models in `new_lines` that look like a new top or standard model, in one line, as available but not added. Adding one changes what the plan must sustain, so offer setup-orchestrator for it rather than adding it here.
7. **Write.** Run the plan's `write_command`, with the entries steps 3 and 4 changed and any change the user named, and nothing else. It keeps the subscriptions and the order. Add `--gitignore` for a project-level file.

## Output

The config path, the entries that changed (old to new, per role), any entry kept on its old model and why, and that the change applies to new sessions.
