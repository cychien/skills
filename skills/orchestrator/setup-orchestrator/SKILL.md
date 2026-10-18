---
name: setup-orchestrator
description: Choose which agent, model, and reasoning effort each orchestrator role uses, and save it as the config the orchestrator skills read. Use this whenever the user wants to set up or reconfigure the orchestrator, pick or change models for planning or execution, tell it which subscriptions they have so models match their plans, or when an orchestrator skill reports a missing model config.
disable-model-invocation: true
---

# Setup orchestrator

Orchestrator skills hand work to other agents. This skill decides which agent, model, and reasoning effort fill each role, verifies every choice with a real call, and writes the result to a config file.

## Roles

- **planner** - plans, designs approaches, writes specs, reviews. Quality matters most and it spends few tokens, so it gets a stronger model or effort than the executor.
- **executor** - implements, verifies, tests. It spends most of the tokens, so it gets what each subscription can sustain.

Give each role three to five entries, best first, spanning at least two agents when the user has two with capacity. Skills that need one model take the first entry, and skills that cross-check work run several, because different models fail in different ways.

## Config file

The scope follows where this skill is installed. Judge by the path you loaded this `SKILL.md` from, not a symlink target.

- **User-level** (under `~/.agents/skills/` or `~/.claude/skills/`): `~/.agents/orchestrator/models.json`
- **Project-level** (under `<project>/.agents/skills/` or `<project>/.claude/skills/`): `<project>/.agents/orchestrator/models.json`. It stays out of git, because it records which subscriptions and models this user's accounts have, and teammates' accounts differ.

Orchestrator skills read the project file first and fall back to the user file. The config lives outside the skill folder so that updating or reinstalling skills never erases it.

The file records the user's subscriptions, which are facts, and the roles chosen from them, with entries in order of preference:

```json
{
  "version": 2,
  "subscriptions": [
    { "agent": "claude", "plan": "<plan>" },
    { "agent": "codex", "plan": "api", "monthly_usd": 200 }
  ],
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

`agent` is the CLI name (`claude`, `codex`, ...). `plan` is the plan's name in lowercase kebab-case, `api` for a metered key. `effort` uses that agent's own level names, and is `null` for a model without effort levels. A version 1 file has a `budget` field in place of `subscriptions`; ignore it and ask for the subscriptions.

## Steps

Talk to the user in plain terms: which subscriptions they have, which models work, and what each role will use and why. Capacity levels, tiers, probes, and catalogs are your working, not their decision, so keep them out of messages unless asked.

1. **Detect available models.**
   1. Run `python3 scripts/detect.py`. It reports agent CLIs on `PATH`, the model catalogs Claude Code and Codex keep for the signed-in account (with each model's effort levels), and usage history.
   2. For any other agent CLI it found, use that CLI's own model-listing command if it has one.
   3. Probe every catalog model at its lowest effort with `python3 scripts/verify.py <agent>:<model>:<effort> ...` (omit `:<effort>` when the model has none). A catalog lists what exists, not what this account can run, so only probed models are candidates. Probing is slow, so start it in the background and ask step 2 while it runs.
   4. If no model passes, ask the user to paste the model ids they can use, then probe those.
2. **Ask which subscriptions the user has.**
   1. When a config exists, read its `subscriptions` and ask only whether they changed.
   2. Otherwise ask with your structured question tool (`AskUserQuestion` in Claude Code), falling back to plain text only when there is none, in one call: a multi-select of the providers behind the agent CLIs step 1 found, then one question per provider for its plan. Offer the plans in `references/plans.md` and let the user type another. For a metered API key, ask the monthly spend they are comfortable with.
   3. Record any limit the user volunteers: an agent they reserve for their own work gets capacity `none`, and one they want used sparingly drops one capacity level.
3. **Derive each agent's capacity.** Read `references/plans.md` and turn each subscription into `none`, `small`, `medium`, `large`, or `unlimited`, following its rules for plans it does not list. An agent with capacity `none` gets no entries. A subscription on an agent without a probe or salvo support gets none either; tell the user which.
4. **Choose models.**
   1. Read the top five or more agent, model, and effort combinations from the `usage` section. They are ranked by sessions the user started, because automated runs mostly inherit a default rather than reflect a choice. Use them only as a preference: they say what the user trusts, not how much they can spend.
   2. Sort the candidates into tiers, judging from each catalog's descriptions, notices, and order:
      - **top** - the provider's most capable current model.
      - **standard** - the provider's current everyday workhorse.
      - **light** - models described as fast, cheap, or for simple tasks. Use them only to reach three entries.

      Older generations rank below the current one in the same tier. Map effort names per agent: "max" is the level named `max`, never a level above it that delegates to subagents (Codex `ultra`), because the orchestrator does its own delegation. When a model lacks a level, use its nearest lower one.
   3. For each agent with capacity, find the strongest option each role can sustain: the best model and effort the user can run through a working day without hitting the plan's limit, because a hit limit also stalls the user's own work. Start from these rows:

      | Capacity | Executor | Planner |
      |---|---|---|
      | unlimited | top model at max | top model at max |
      | large | top model at medium, or standard model at extra-high | top model at extra-high |
      | medium | standard model at high | top model at high |
      | small | standard model at medium | standard model at high |

      The planner spends few tokens, so it sits higher than the executor on the same plan. The executor spends most of them, so for the executor a model whose catalog notice says it uses limits faster needs one row more capacity than its tier suggests.
   4. Order each role from strongest to weakest, by tier, then effort, then the usage habits from step 4.1, then newer models, because skills that take one entry use the first. The planner's first entry must be at least as strong as the executor's first.
   5. Include at least two agents in each role when the user has two with capacity, so multi-model skills hear different opinions. A weaker agent's entries go after the stronger ones, at the level its capacity sustains. When another agent can fill the rest, give a `small` agent at most one entry per role, because multi-model skills run every entry. Fill the remaining slots, up to five, with other strong sustainable models, spread across families. When fewer than three options fit a role, go outside capacity freely to reach three and note which entries did.
   6. Confirm with the structured question tool: one question per role, planner first and executor second, in a single call. Put that role's list in the question text itself, above the question, because text written right before a question tool call is often condensed to a one-line status and a list anywhere else can vanish. Open with one plain sentence on why the lists look as they do, such as which subscription carries the executor. Offer keeping the list or changing it. Without a question tool, end your message with both lists and ask in plain text. Write each question in the user's language, in this shape:

      ```
      Planner
      1. <model> · <effort> · <agent>
      2. <model> · <effort> · <agent>

      Keep these, or change which models?
      ```

5. **Verify.** Run `scripts/verify.py` on every entry exactly as it will be written, effort included. If any fails, stop and ask the user for a replacement from the verified candidates, with the failing entry and its error in the question itself. Repeat until every entry passes. Never write an entry that has not passed.
6. **Write.** Run `python3 scripts/write_config.py <path> --subscription <agent>:<plan>[:<monthly usd>] ... --planner <agent>:<model>[:<effort>] ... --executor ...` with the user's subscriptions and the verified entries in order, plus `--gitignore` for a project-level file. It overwrites the whole file in one fixed format, so the same answers always produce the same file.
7. **Confirm.** Tell the user the config path, that the settings apply to new sessions, and that rerunning this skill updates them.
