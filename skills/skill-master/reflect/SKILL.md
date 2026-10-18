---
name: reflect
description: "Mine the current session for durable learnings with three parallel reviewers, route each to a concrete edit on an existing skill, and list the rules that need a hard check as a backlog. Use for /reflect, or when the user says 'reflect' after a session worth learning from."
disable-model-invocation: true
---

# Reflect

**You own the routing and the user owns the approval.** Reviewers find learnings, a synthesizer sorts them, you apply only what the user approves.

Paths like `../create-skill/SKILL.md` point to skills installed beside this one, relative to this file's folder.

Skip when the session was trivial, off-topic, or followed its skills correctly. One-offs are not learnings.

Open a todolist whose first items are the steps below, copied in verbatim, before any task-specific todos. The `guard` skill's `todo from reflect` does this; without guard, use your agent's todo tool. A step you choose not to do stays in the list with a one-line `skip: <reason>`.

1. Locate the transcript. When the user points at one, use it. Otherwise find this session's: look only in the current project's transcript folder, because other folders hold private chats from unrelated work: `~/.claude/projects/<project path with / and . replaced by ->/` in Claude Code (subagents under `<session id>/subagents/`), `~/.codex/sessions/<yyyy>/<mm>/<dd>/` in Codex, the `agent-transcripts/` folder the system prompt names in Cursor. List the newest few `.jsonl` files and take the one whose first user message matches this session's opening prompt. If none matches, write a tight digest of the session instead.
2. Spawn three reviewers in parallel, one per lens in `references/lenses.md`: Judgment, Tooling, and Divergent. Fill `references/reviewer-prompt.md` for each with that lens's section and the transcript path or digest. Take models from the orchestrator config (`<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`): planner-role entries for Judgment and Divergent, an executor-role entry for Tooling, on different model families where the config allows, because different models miss different things. Use a native subagent when your agent can run that model, otherwise the **salvo** skill (`../salvo/SKILL.md`) with that one entry. If there is no config, ask the user to run the **setup-orchestrator** skill (`../setup-orchestrator/SKILL.md`) or to name the models.
3. Synthesize. Spawn one more agent on a planner-role entry with `references/synthesizer.md`, each reviewer's full output pasted where marked. It returns Accepted, Backlog, and Rejected.
4. Check each Accepted row against its target. Resolve the skill's real path, following symlinks, and edit that source. Move a row whose source is not editable (a plugin cache, a generated or read-only copy) to Backlog with where its source lives. List any row a check would enforce more reliably than prose in Backlog too, per the Encode Lessons in Structure principle (`../principles/references/principles/encode-lessons-in-structure.md`). Keep its one-line prose edit in Accepted as well when the skill does not yet say it, because the check may be weeks away and until then the skill must not leave the user's most repeated correction unwritten.
5. Present the full Accepted, Backlog, and Rejected output and wait for the user's approval before editing anything, because a skill edit changes every future agent that reads it. The user may approve a subset or redirect a routing.
6. Apply each approved Accepted row per its routing. Make a trivial edit (one bullet, a tightened sentence, a stale fact) directly. Hand a substantive edit (a new section, a new table, more than about ten lines), a description or route tuning, and a new skill to the **create-skill** skill (`../create-skill/SKILL.md`), which tests the change, instead of inventing its shape here. Run the skill repo's validator, if it has one, on every touched skill.
7. Leave the Backlog in the report. Implement a Backlog item only when the user asks, through the skill or repo its Where column names.

## Output

A short report, no preamble:

- **Applied.** Each edited skill path and what changed, one line each.
- **New skills.** Each path, one line each.
- **Backlog.** The synthesizer's Backlog table as it stands after step 4, so the rules that need a hard check stay visible until someone builds them.
- **Dropped.** One line per rejected finding with the synthesizer's reason.
