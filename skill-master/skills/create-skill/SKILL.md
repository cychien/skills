---
name: create-skill
description: Create a new skill or improve an existing one. Use this whenever the user wants to write, edit, restructure, or tighten a skill, turn a workflow from the current conversation into a skill.
---

# Create skill

A skill is a folder with a `SKILL.md` that teaches an agent how to do one kind of task well.

Work through the sections below as a loop:

1. Capture intent.
2. Write the skill.
3. Test it, and improve it until the eval recommends promoting it.
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

Test with the `eval-skill` skill. It runs only on explicit invocation, so read its `SKILL.md` and follow it directly. Run every round in full, judge included: you wrote the skill, so your own grading alone is not a test. Each round ends with eval-skill's report and recommendation. Promote means the test passed; Revise or Reject means it failed. If eval-skill is not installed, tell the user the skill cannot be tested and stop. The eval checks what the skill makes agents do, not when they load it, so it does not replace the trigger test below; run both.

A failed test means the skill does not work yet, so revise it and run the eval again:

- Change only the skill's own files. Making runs pass by editing anything else, such as the project the skill works on, proves nothing about the skill and ships changes nobody asked for. Propose such changes to the user instead.
- When runs never opened the skill, the problem is triggering, not the instructions. Revise the description once, per the trigger test below. If a model still does not load the skill, report that as a finding and stop; never plant the skill's rules, or pointers to it, anywhere else to get around it, because the eval would then measure the copy instead of the skill.
- If a rule keeps failing, reframe it or change the working pattern instead of making it stricter. If a transcript shows the agent doing unproductive work, cut the part of the skill that causes it.
- Keep the prompt and criteria the same in every round, so each round measures the same thing. Changing them mid-loop moves the goalposts; do it only with the user's agreement.
- Stop when the eval promotes, or when a revision no longer improves the result, and report the latter as a finding. A disagreement the experiment could not settle is a call for the user.

### Trigger test

Run this whenever the description is new or changed. An agent sees only the name and description when deciding whether to consult a skill, and it consults skills mainly for tasks it cannot handle in one step, so a simple "read this PDF" may never trigger a PDF skill.

1. Write six to ten realistic queries: half that should trigger, half that should not. The valuable negatives are near-misses that share keywords but need something else.
2. Run each query two or three times in a fresh session with the skill installed (`claude -p "<query>"` works in Claude Code), because triggering is not deterministic.
3. Check each transcript for whether the skill was read.
4. Fix misses by changing the description, not the body, and rerun.

## Output

Once the eval recommends promoting the skill, or you are stuck on a call only the user can make, show the user:

- The final round's eval-skill report, with its recommendation. For an update, point at where the change made a difference.
- What you already fixed along the way.
- Any step you skipped, and why.
- Any call only the user can make.
- Paths to any file the user needs to open.

Then ask: "How does this look? What would you change?" Empty feedback means fine.
