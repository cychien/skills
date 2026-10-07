---
name: create-skill
description: Create a new skill or improve an existing one. Use this whenever the user wants to write, edit, restructure, or tighten a skill, turn a workflow from the current conversation into a skill.
---

# Create skill

A skill is a folder with a `SKILL.md` that teaches an agent how to do one kind of task well.

Work through the sections below as a loop:

1. Capture intent.
2. Write the skill.
3. Test it, and improve it until the runs pass your own review.
4. Show the user the output.
5. Revise on their feedback and return to step 3, until the user is happy or you stop making progress.

Start where the user is. "I want a skill for X" starts at step 1. "Is my draft any good?" starts at step 3. A change to an existing skill, however small, runs the whole loop at the scale of the change, because an untested rule is a guess about agent behavior. Skip testing only when the user says so.

## House rules

These apply to everything you write into a skill.

- **Write in English.** The `SKILL.md`, its references, scripts, comments, and examples are all English, even when the conversation with the user is in another language.
- **Be concise.** Every sentence must change what the agent does. Cut the rest.
- **Write the intent, not the words.** When the user dictates a rule or gives terse feedback, work out what they actually need, then write the shortest version that carries it. Never transcribe their wording.
- **Write for the whole class of task.** The skill will meet prompts nobody has seen, so do not tune it to the example or test prompts in front of you.
- **Explain why, not just what.** A sentence that says why a step matters lets the agent handle cases the skill never anticipated. All-caps `ALWAYS` and `NEVER` are a yellow flag that the reasoning is missing.
- **Lean away from examples.** State the rule and the reason. Add an example only when you believe the agent would get the rule wrong without one. Examples cost lines and tempt the agent to match the case instead of the rule.
- **Use the imperative.** Tell the agent what to do, not what should be done.
- **Number the steps.** When the agent must do things in order, write a numbered list with one action per item, so it can track where it is and skip nothing.
- **Use a plain dash, never an em dash.** Write `-` where you would reach for `—`.
- **Match the description.** A skill does what its description says. Do not build skills that mislead, exfiltrate data, or facilitate unauthorized access. Role-play skills are fine.

## Communicating with the user

People who make skills range from engineers to someone who just opened a terminal for the first time. Read the cues. Terms like "evaluation" are fine. Terms like "JSON", "frontmatter", or "assertion" need a short definition unless the user has already used them.

## Capture intent

1. Mine the current conversation first. It may already contain the workflow, for example when the user says "turn this into a skill": the tools used, the order of steps, corrections the user made, the input and output formats you saw.
2. Settle four questions:
   - What should this skill let the agent do?
   - When should it trigger? Which phrases, file types, or situations?
   - What does the output look like, and does the user review it?
   - Is the output objectively checkable (file transforms, data extraction, fixed workflows) or a matter of taste (writing style, design)?
3. Ask about edge cases, example inputs, and dependencies. If MCPs or search are available, use them to look up prior art so the user carries less of the burden.
4. Confirm the intent with the user before drafting.

## Where the skill lives

Skills follow the Agent Skills open standard. Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Amp, and Cline read `.agents/skills/`. Claude Code reads only `.claude/skills/` but supports symlinks, so one copy can serve every agent. A folder that lives only under `.claude/skills/` is invisible to every other agent on the team.

1. Create the real folder at `.agents/skills/<name>/`, or `~/.agents/skills/<name>/` for a user-level skill.
2. Link `.claude/skills/<name>` (or `~/.claude/skills/<name>`) to `../../.agents/skills/<name>`. A relative link keeps the repo working from any checkout path.
3. Add a `.windsurf/skills/` link only when the project uses Windsurf.
4. Commit both the folder and the symlink.

When the project already keeps skills elsewhere, ask before moving them, because that is a separate decision.

## Write the SKILL.md

When updating an existing skill, first copy it to a scratch directory as the baseline for testing, and keep its folder name and `name` field.

### Anatomy

```
skill-name/
├── SKILL.md          required
│   ├── frontmatter   name and description, both required
│   └── body          the instructions
├── scripts/          executable code for deterministic or repetitive steps
├── references/       docs the agent loads only when it needs them
└── assets/           files used in the output: templates, icons, fonts
```

Every file the body references must exist. When every test run writes the same helper or takes the same multi-step detour, write it once in `scripts/` and tell the skill to run it.

### Frontmatter

- **name**: the skill's identifier, kebab-case, matching the folder name.
- **description**: what the skill does and when to trigger. This is the main triggering mechanism, so every "when to use" fact lives here, and the internal workflow does not. Agents tend to undertrigger skills, so make it a little pushy. Instead of "How to build a dashboard for internal metrics", write "How to build a dashboard for internal metrics. Use this whenever the user mentions dashboards, charts, metrics, or wants to display company data, even if they never say 'dashboard'."

### Progressive disclosure

Skills load in three levels:

1. **Metadata** (name and description) is always in context. About 100 words.
2. **The `SKILL.md` body** loads when the skill triggers. Keep it under about 500 lines.
3. **Bundled resources** load on demand. Scripts can run without ever being read.

So put the workflow and the decisions in `SKILL.md`, and push long reference material into `references/` with a note on when to read each file. A reference file over 300 lines gets a table of contents. When a skill covers several variants (say, AWS, GCP, and Azure), keep the selection logic in `SKILL.md` and give each variant its own reference file so the agent reads only the one it needs.

### Output format

When the output has a fixed shape, give the agent a template to fill instead of describing the shape in prose.

When the user reviews the result, end the `SKILL.md` with an `## Output` section that says what the agent returns when it finishes: which artifacts, in what form, and what to flag for review, such as judgment calls, open questions, or skipped steps. Without it, agents either narrate their process or bury the result, and the reviewer has to dig. Leave it out when nobody reviews the result directly.

## Test

1. Write two or three test prompts that sound like something a real user would type, with concrete details: file names, a bit of backstory, casual phrasing. For an update, write prompts that exercise the change, because existing prompts rarely touch a new rule.
2. For checkable output, write two to four assertions per prompt: concrete statements that are true only when the skill did its job ("the CSV has a header row", "the summary names the root cause, not the symptom"). An assertion that a wrong output would also pass is worthless. Skip assertions for output judged by taste.
3. Run each prompt twice, in the same turn:
   - **With the skill.** A fresh subagent gets the skill path and the prompt, and saves its outputs to a scratch directory. Fresh context matters, because you wrote the skill and would otherwise fill its gaps from memory.
   - **Baseline.** Another fresh subagent gets the same prompt with no skill, or with the snapshot when you are updating. Without it you cannot tell whether the skill adds anything.

   Without subagents, follow the `SKILL.md` yourself, one prompt at a time, and skip the baseline. Less rigorous, still useful.
4. When there are assertions, have a fresh subagent grade each run from its real outputs and transcript, never from the run's own summary. It marks every assertion pass or fail with evidence, and flags assertions that passed too easily or outcomes nothing checked.
5. Review the runs yourself before the user sees anything. Read every output and transcript against the intent and the baseline. When a run misses the intent, fails an assertion, or is no better than the baseline, improve the skill and return to step 3. If a rule keeps failing, reframe it or change the working pattern instead of making it stricter. If a transcript shows the agent doing unproductive work, cut the part of the skill that causes it. The user's time goes to judgment calls, not to catching failures you could have caught.

### Trigger test

Run this whenever the description is new or changed. An agent sees only the name and description when deciding whether to consult a skill, and it consults skills mainly for tasks it cannot handle in one step, so a simple "read this PDF" may never trigger a PDF skill.

1. Write six to ten realistic queries: half that should trigger, half that should not. The valuable negatives are near-misses that share keywords but need something else.
2. Run each query two or three times in a fresh session with the skill installed (`claude -p "<query>"` works in Claude Code), because triggering is not deterministic.
3. Check each transcript for whether the skill was read.
4. Fix misses by changing the description, not the body, and rerun.

## Output

Once the runs pass your own review, or you are stuck on a call only the user can make, show the user:

- The test prompts and the outputs side by side, with grades when there are any. For an update, point at where the change made a difference.
- What you already fixed along the way.
- Any step you skipped, and why.
- Any call only the user can make.
- Paths to any file the user needs to open.

Then ask: "How does this look? What would you change?" Empty feedback means fine.
