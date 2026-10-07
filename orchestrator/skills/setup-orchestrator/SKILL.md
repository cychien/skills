---
name: setup-orchestrator
description: Choose which agent, model, and reasoning effort each orchestrator role uses, and save it as the config the orchestrator skills read. Use this whenever the user wants to set up or reconfigure the orchestrator, pick or change models for planning or execution, set a model budget, or when an orchestrator skill reports a missing model config.
---

# Setup orchestrator

Orchestrator skills hand work to other agents. This skill decides which agent, model, and reasoning effort fill each role, verifies every choice with a real call, and writes the result to a config file.

## Roles

- **planner** - plans, designs approaches, writes specs, reviews. Quality matters most and it spends few tokens, so it may run one budget level above the user's choice.
- **executor** - implements, verifies, tests. It spends most of the tokens, so it stays at the user's budget.

Give each role three to five entries, spread across agents and model families where possible. Orchestrator skills cross-check work between models, and different models fail in different ways.

## Config file

The scope follows where this skill is installed. Judge by the path you loaded this `SKILL.md` from, not a symlink target.

- **User-level** (under `~/.agents/skills/` or `~/.claude/skills/`): `~/.agents/orchestrator/models.json`
- **Project-level** (under `<project>/.agents/skills/` or `<project>/.claude/skills/`): `<project>/.agents/orchestrator/models.json`. It stays out of git, because it records which models this user's accounts can run, and teammates' accounts differ.

Orchestrator skills read the project file first and fall back to the user file. The config lives outside the skill folder so that updating or reinstalling skills never erases it.

The file has this shape, with entries in order of preference:

```json
{
  "version": 1,
  "budget": "medium",
  "roles": {
    "planner": [
      { "agent": "claude", "model": "<model id>", "effort": "<effort>" }
    ],
    "executor": [
      { "agent": "codex", "model": "<model id>", "effort": "<effort>" }
    ]
  }
}
```

`agent` is the CLI name (`claude`, `codex`, ...). `effort` uses that agent's own level names, and is `null` for a model without effort levels.

## Steps

Talk to the user in plain terms: which models work, their budget, and what each role will use. Tiers, probes, catalogs, and how the budget maps onto each role are your working, not their decision, so keep them out of messages unless asked.

1. **Detect available models.**
   1. Run `python3 scripts/detect.py`. It reports agent CLIs on `PATH`, the model catalogs Claude Code and Codex keep for the signed-in account (with each model's effort levels), and usage history.
   2. For any other agent CLI it found, use that CLI's own model-listing command if it has one.
   3. Probe every catalog model at its lowest effort with `python3 scripts/verify.py <agent>:<model>:<effort> ...` (omit `:<effort>` when the model has none). A catalog lists what exists, not what this account can run, so only probed models are candidates.
   4. If no model passes, ask the user to paste the model ids they can use, then probe those.
2. **Read usage habits.** Take the top five or more agent, model, and effort combinations from the `usage` section. They are ranked by sessions the user started, because automated runs mostly inherit a default rather than reflect a choice.
3. **Choose models.**
   1. Ask "What's your token budget?" with your structured question tool (`AskUserQuestion` in Claude Code), falling back to plain text only when there is none. Ask only that; do not explain how the budget applies to each role. Options:
      - **unlimited** - strongest models at max reasoning
      - **large** - strongest models at medium reasoning, or standard models at extra-high reasoning
      - **medium** - standard models at high reasoning
      - **small** - standard models at medium reasoning
   2. Sort the candidates into tiers, judging from each catalog's descriptions, notices, and order:
      - **top** - the provider's most capable current model.
      - **standard** - the provider's current everyday workhorse.
      - **light** - models described as fast, cheap, or for simple tasks. Use them only to reach three entries.

      Older generations rank below the current one in the same tier. Map effort names per agent: "max" is the level named `max`, never a level above it that delegates to subagents (Codex `ultra`), because the orchestrator does its own delegation. When a model lacks a level, use its nearest lower one.
   3. Fill the roles. The executor takes options at the budget level. The planner takes options one level higher (unlimited stays unlimited). Within the allowed options, prefer the models from step 2, then diversity across agents and families, then newer models. When fewer than three options fit a role, go outside the budget freely to reach three and note which entries did.
   4. Ask with the structured question tool whether to keep the proposal or change it, and to which models. Put the whole proposal in every option's `preview` (in `AskUserQuestion`), so it stays visible while the user decides what to change: one table per role with agent, model, effort, and a short why that cites the user's sessions when step 2 drove the pick. Text written right before a question tool call is often condensed to a one-line status, so a proposal anywhere else can vanish. Without a question tool, end your message with the tables and ask in plain text.
4. **Verify.** Run `scripts/verify.py` on every entry exactly as it will be written, effort included. If any fails, stop and ask the user for a replacement from the verified candidates, with the failing entry and its error in the question itself. Repeat until every entry passes. Never write an entry that has not passed.
5. **Write.** Run `python3 scripts/write_config.py <path> --budget <level> --planner <agent>:<model>[:<effort>] ... --executor ...` with the verified entries in order, plus `--gitignore` for a project-level file. It overwrites the whole file in one fixed format, so the same answers always produce the same file.
6. **Confirm.** Tell the user the config path, that the settings apply to new sessions, and that rerunning this skill updates them.
