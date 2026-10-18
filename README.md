# skills

Agent skills that work in Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, and any other agent that reads the [Agent Skills](https://agentskills.io) format. Each lives at `skills/<category>/<name>/SKILL.md`.

**[switchboard](./skills/switchboard/)**

- [justin-do](./skills/switchboard/justin-do/) - take any task, decide whether it runs autonomously or interactively, and route it to its category's switchboard. Holds what every category shares.

**[eng](./skills/eng/)** - software engineering

- [eng-do](./skills/eng/eng-do/) - the engineering switchboard: routes engineering work to its playbook
- [principles](./skills/eng/principles/) - the engineering principles playbooks read before they design or build
- [code-comments](./skills/eng/code-comments/) - how code is commented in every file a playbook produces
- [feature](./skills/eng/feature/) - build new or changed behavior: clarify the spec, ground, design, delegate, verify, open a PR
- [bug-fix](./skills/eng/bug-fix/) - fix a bug: reproduce on main, find the root cause from runtime evidence, verify, land the failing repro before the fix
- [perf-issue](./skills/eng/perf-issue/) - fix a slowness against a vetted baseline, cheapest performance mantra first
- [hillclimb](./skills/eng/hillclimb/) - improve one metric against a target: frozen harness, keep or revert, decision log
- [open-pr](./skills/eng/open-pr/) - open PRs as small ordered commits with a one-minute description
- [how](./skills/eng/how/) - explain how a subsystem works
- [why](./skills/eng/why/) - find the rationale behind code from history, tickets, docs, and chat
- [architect](./skills/eng/architect/) - sketch types and module structure across several models before writing code
- [interrogate](./skills/eng/interrogate/) - adversarial review of changes by several models
- [verify](./skills/eng/verify/) - prove a change works: a plan of checkable predicates, an independent verifier on the real surface, an evidence audit
- [create-verification-skill](./skills/eng/create-verification-skill/) - generate a project-local `verify-<app>` skill that launches and drives the app
- [maintain-verification-skill](./skills/eng/maintain-verification-skill/) - keep a verification skill and its feature map honest as the app changes
- [benchmark-checklist](./skills/eng/benchmark-checklist/) - vet a performance number before you report or act on it, measured on read-only production when available
- [blast-radius](./skills/eng/blast-radius/) - find what a change breaks beyond its diff, and prove the fact it is safe because of
- [no-comments](./skills/eng/no-comments/) - strip comments that should be code
- [technical-writing](./skills/eng/technical-writing/) - the standard for docs, PR descriptions, and commit messages

**[writing](./skills/writing/)**

- [writing-do](./skills/writing/writing-do/) - the writing switchboard
- [rewrite](./skills/writing/rewrite/) - rewrite a draft so it is clear, succinct, and worth reading to the end
- [feynman](./skills/writing/feynman/) - learn a topic, then outline an article to write about it yourself

**[everyday](./skills/everyday/)** - general skills, often called by other skills

- [everyday-do](./skills/everyday/everyday-do/) - the switchboard for tasks that belong to no other category
- [reply](./skills/everyday/reply/) - how to write the reply at the end of a task
- [teach](./skills/everyday/teach/) - explain a body of work plainly so a person actually understands it
- [unslop](./skills/everyday/unslop/) - cut AI tells from writing

**[orchestrator](./skills/orchestrator/)** - coordinating multiple agents across a task

- [orchestrator-do](./skills/orchestrator/orchestrator-do/) - the orchestration switchboard: model roles, the model config, and orchestration playbooks
- [setup-orchestrator](./skills/orchestrator/setup-orchestrator/) - choose the agent, model, and effort for each role
- [salvo](./skills/orchestrator/salvo/) - run one task on several models in parallel
- [arena](./skills/orchestrator/arena/) - several candidates at one task, a cross-judge, then pick a base and graft
- [guard](./skills/orchestrator/guard/) - hard rules that enforce skill conventions through hooks: playbook steps, principle citations, no em dash, PR rules
- [autorun](./skills/orchestrator/autorun/) - autonomous mode: keep an agent working until the task is verifiably done, enforced by hooks

**[skill-master](./skills/skill-master/)** - authoring and improving skills

- [skill-master-do](./skills/skill-master/skill-master-do/) - the skill-authoring switchboard
- [create-skill](./skills/skill-master/create-skill/) - create a new skill or improve an existing one
- [eval-skill](./skills/skill-master/eval-skill/) - test whether a skill changes agent behavior with a blind experiment

## Install

```
npx skills add cychien/skills -g --skill '*'
```

This installs every skill for each agent it finds on your machine. Install the whole set, because some skills load others (`feynman` loads `teach`, `eval-skill` drives `salvo`, `justin-do` loads each category's switchboard, and those load their category's skills). Drop `-g` to install into the current project instead.

`autorun` also needs its hooks registered once per machine (they also run `guard`'s rules): `python3 ~/.agents/skills/autorun/scripts/autorun.py install` (the path of wherever the skill was installed).

## Update

Rerun the install command. It updates every skill and adds new ones. `npx skills update -g` updates installed skills only.

## Authoring

Installers drop the category folder, so:

- Skill names are unique across categories.
- A skill reaches an auto-invocable skill by name ("load the `teach` skill"). It reaches a manual-only skill, which agents cannot see, by its path beside it once installed ("read `../how/SKILL.md`").
- A manual-only skill also needs `agents/openai.yaml` setting `policy.allow_implicit_invocation: false`, so Codex treats it as manual-only too.

`python3 scripts/validate.py` checks all of this, and `python3 -m unittest discover -s tests` runs the script tests. Both run in CI.
