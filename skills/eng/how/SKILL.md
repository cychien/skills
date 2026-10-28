---
name: how
description: "Use for \"how does X work\", code walkthroughs before changing something, and placement / ownership / layering questions (\"where should this live\", \"which package owns this\", \"is this the right layer\"). Explains subsystem architecture, runtime flow, onboarding mental models. Use why for motivation."
disable-model-invocation: true
---

# How

Explore the codebase to answer "how does X work?" questions. Produce architectural explanations at the level of a senior engineer onboarding onto a subsystem, enough to build a working mental model, not so much that it reads like annotated source code.

Every spawn reads the repository and never edits its code. Every explorer and explainer writes its findings to a file (in the scratchpad, or where the caller names) and hands back the path with at most 200 words, so give each an agent type with a write tool, never a read-only type, because a type without one returns everything inline into the caller's context. Explorers use an executor model and every explainer a planner model from the orchestrator config (`<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`): the first entry in that role your agent can run as a subagent. Without a config, or when your agent cannot choose a subagent's model, use its default model.

When the caller gives a verification plan, how also tests every check's premises against the base commit the caller names, per "With a verification plan" below.

## 1. Assess complexity

If the scope is ambiguous, state your interpretation and explore. The user can redirect.

- **Simple** (a single module, a small utility, a narrow question such as "how does function X work"): no explorers. Spawn one explainer that explores and explains in one pass, built from `references/explainer-prompt.md` without the explorer-findings section. Go to step 4.
- **Complex** (a subsystem spanning multiple files or services, a cross-cutting feature, a full architectural overview): go to step 2.

When in doubt, take the simple path.

## 2. Explore (complex only)

Decompose the question into 2 to 4 angles, each a distinct slice of the subsystem. Spawn all explorers in a single message, each with `references/explorer-prompt.md` and its angle filled in.

## 3. Synthesize (complex only)

Once all explorers have returned, spawn one explainer with `references/explainer-prompt.md` and every explorer's findings filled in.

## 4. Present

Present the explainer's output. Light edits for clarity or context from the conversation are fine. Do not substantially rewrite it. With a verification plan, present the paths of `grounding.md` and `premises.md` and one line per premise that does not hold.

## With a verification plan

The caller passes the plan, the place its files go (the plan's phase folder, else the verification directory), and the base commit the premises are checked at. Then:

- Give every check to at least one explorer, beside its angle: the checks whose scenario runs through its slice, with the base commit. The explorer lists each fact the check assumes already holds on the base (a route exists, a dialog asks before it acts, an adapter queues while offline), whether it holds, and the file and line or the command output that shows it, because a false assumption found before the design costs a line. What the change itself will build is not a premise: the explorer notes it once per check as new, not once per missing piece, because a table full of planned work buries the few assumptions that are actually false.
- When the caller passes an earlier `grounding.md`, the explorers start from it and look only at what changed since and at the premises.
- The explainer writes two files there: `grounding.md`, the explanation in the sections below, whole even when it started from an earlier one; and `premises.md`, the table of `../verify/references/plan.md`'s Premises section, one row per premise and at least one per check. Each file starts with the line `Base: <sha>`, the base commit the caller passed, because `verify.py premises` accepts the files only for that base. It checks every `no` row in the code itself before writing it, and leaves every Resolution empty, because the design resolves premises, not how.

## Output format

The explanation uses the sections defined in `references/explainer-prompt.md`, dropping any that do not apply: Overview, Key Concepts, How It Works, Where Things Live, Gotchas.
