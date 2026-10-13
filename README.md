# skills

Agent skills that work in Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, and any other agent that reads the [Agent Skills](https://agentskills.io) format. Each lives at `skills/<category>/<name>/SKILL.md`.

**[writing](./skills/writing/)**

- [rewrite](./skills/writing/rewrite/) - rewrite a draft so it is clear, succinct, and worth reading to the end
- [feynman](./skills/writing/feynman/) - learn a topic, then outline an article to write about it yourself

**[everyday](./skills/everyday/)** - general skills, often called by other skills

- [teach](./skills/everyday/teach/) - explain a body of work plainly so a person actually understands it
- [unslop](./skills/everyday/unslop/) - cut AI tells from writing

**[orchestrator](./skills/orchestrator/)** - coordinating multiple agents across a task

- [setup-orchestrator](./skills/orchestrator/setup-orchestrator/) - choose the agent, model, and effort for each role
- [salvo](./skills/orchestrator/salvo/) - run one task on several models in parallel

**[skill-master](./skills/skill-master/)** - authoring and improving skills

- [create-skill](./skills/skill-master/create-skill/) - create a new skill or improve an existing one
- [eval-skill](./skills/skill-master/eval-skill/) - test whether a skill changes agent behavior with a blind experiment

## Install

```
npx skills add cychien/skills -g --skill '*'
```

This installs every skill for each agent it finds on your machine. Install the whole set, because some skills load others (`feynman` loads `teach`, `eval-skill` drives `salvo`). Drop `-g` to install into the current project instead.

## Update

Rerun the install command. It updates every skill and adds new ones. `npx skills update -g` updates installed skills only.

## Authoring

Installers drop the category folder, so:

- Skill names are unique across categories.
- A skill reaches an auto-invocable skill by name ("load the `teach` skill"). It reaches a manual-only skill, which agents cannot see, by its path beside it once installed ("read `../how/SKILL.md`").
- A manual-only skill also needs `agents/openai.yaml` setting `policy.allow_implicit_invocation: false`, so Codex treats it as manual-only too.

`python3 scripts/validate.py` checks all of this and runs in CI.
