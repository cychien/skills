---
name: justin-do
description: Justin's switchboard. Takes any task, decides whether it runs autonomously to completion or interactively, routes it to the installed skill that fits, and carries it through to verified work. Use for /justin-do.
disable-model-invocation: true
---

# justin-do

Route the task to the switchboard of its category, which lists that category's playbooks. Each playbook carries its own rules.

- **Engineering.** Writing, changing, debugging, reviewing, or designing code, tests, and infrastructure goes to the **eng-do** skill (`../eng-do/SKILL.md`).
- **Writing.** Drafting, rewriting, or outlining prose goes to the **writing-do** skill (`../writing-do/SKILL.md`).
- **Orchestration.** Running work on several agents or models, choosing models per role, or running a task unattended goes to the **orchestrator-do** skill (`../orchestrator-do/SKILL.md`).
- **Skills.** Creating, improving, or testing a skill goes to the **skill-master-do** skill (`../skill-master-do/SKILL.md`).
- **Everything else** goes to the **everyday-do** skill (`../everyday-do/SKILL.md`).

Write the reply per the **reply** skill (`../reply/SKILL.md`), a path beside this skill's folder.
