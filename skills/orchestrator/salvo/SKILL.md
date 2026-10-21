---
name: salvo
description: "Run one task on several different models in parallel, each in its own workspace, and report every model's result without ranking or merging them. Use for /salvo, 'salvo this', or when the user wants several models to each take a shot at the same task."
disable-model-invocation: true
---

# Salvo

Fire one task at several models at once. Each runs on its own, in its own workspace, and you report what each produced. Salvo does not judge, pick, or merge. Deciding what to do with the results belongs to the user, or to whatever skill invoked salvo.

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

## Steps

1. **Take the task as given.** Do not rewrite it or add an approach, rubric, or hints, because the point is to see how each model handles the same task unaided. The models start with no memory of this conversation, so when the task leans on something only this conversation holds (a bug discussed earlier, text the user pasted), append those facts under a `## Context` heading. Facts only, no suggestions.
2. **Choose the models.**
   1. Read `<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`.
   2. Pick the role: `planner` for planning and design tasks (plans, specs, architecture, choosing an approach), `executor` for everything else.
   3. If the user named models, use exactly those. For each, take the effort the user gave, else the effort that role lists for the model, else none.
   4. Otherwise use every entry in that role, once per distinct model, keeping the first effort listed for it. If there is no config, stop and ask the user to run the **setup-orchestrator** skill (`../setup-orchestrator/SKILL.md`) or to name the models.
3. **Launch.** From the directory the task is about, run:

   ```
   python3 scripts/salvo.py run --out /tmp/salvo-<slug> <agent>:<model>[:<effort>] ... <<'EOF'
   <task>
   EOF
   ```

   `<slug>` is a short kebab-case name for the task. The script supports the `claude` and `codex` agents; tell the user about any entry on another agent and leave it out. Inside a git repo it snapshots the working tree, uncommitted and untracked files included, and gives each model a detached worktree of that snapshot. Outside a repo each model gets an empty directory and reads the originals in place. It runs every model in parallel and blocks until all finish, which can take a long time, so in Claude Code run it in the background and wait for the completion notification instead of polling. A run stopped by a usage limit fails at once: its `error` names the reset time, its `limited_until` holds it, and the limit goes to the orchestrator's limits registry, so the caller hands that work to the next candidate (`guard.py quota pick`) instead of waiting. Add `--wait-for-reset` only when the work must stay on that model: a run whose limit resets within 24 hours then waits for the reset and resumes its own session, up to three times, and salvo.json lists each wait under the run's `limit_waits`. Add `--timeout <seconds>` only when the user asks for a limit. Add `--clean-room` when the models must not be able to tell they are part of an orchestrated run, as in a blind experiment: each workspace moves to `/tmp/<random>/<project name>`, git workspaces become standalone clones with no trace of their origin, the prompt drops salvo's wording, and the runs stay out of any autonomous run of the caller. Every other runner prompt tells the runner it is a delegate that must not run `autorun.py start`, `done`, or `stop`. Add `--hide-skill <name>` (repeatable) when each run must see only its workspace's copy of a skill: it hides the user-level installs of that skill from both agents and leaves everything else the user has installed visible. A user-level skill outranks a project skill of the same name in claude, so without it a workspace copy can be silently ignored.
4. **Read every result.** The script ends by printing a JSON summary, also saved as `salvo.json` in the run directory. For each run, read `result.md` (the model's final message) and, when it changed files, `changes.patch`. Each run also keeps its full transcript, the agent's raw event stream, as `transcript.jsonl`; leave it unread unless the result alone cannot explain what the model did. For a failed run, use its `error` and the tail of `stderr.log`. Do not rerun a failure on another model, because swapping models silently changes the lineup the user asked for.

## Output

One block per model, in launch order. Summarize each result on its own terms; do not compare models or say which did best.

```
### <model> · <effort> · <agent> - <ok | failed>, <duration>
<2-5 lines: what it produced, its key answer or changes, assumptions it stated, anything left unfinished; or the error>
Result: <result.md path> · Transcript: <transcript.jsonl path>
Workspace: <work path> · Changes: <n files, changes.patch path, or none>
Resume: <resume command>
```

Then give the run directory and the cleanup command, `python3 <skill dir>/scripts/salvo.py clean /tmp/salvo-<slug>`, which removes the worktrees and the run directory. Run it only after every process the runs started is down: it stops any process still running from a workspace, the shadow home, or the run directory (SIGTERM, then SIGKILL) and exits non-zero without deleting anything while one survives, because a directory deleted under a live process hides it. Flag any model you left out or that failed.
