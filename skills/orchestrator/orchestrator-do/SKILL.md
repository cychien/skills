---
name: orchestrator-do
description: Justin's orchestration switchboard - routes work across agents and models, or unattended, to its playbook. Use for /orchestrator-do, or when the switchboard routes an orchestration task here.
disable-model-invocation: true
---

# orchestrator-do

Route orchestration work to its playbook. Paths like `../arena/SKILL.md` point to skills installed beside this one.

- **Several models attempt the same task**, for a second opinion or to compare their results, uses the **salvo** skill (`../salvo/SKILL.md`).
- **Choosing or changing which models fill each role**, or new subscriptions, uses the **setup-orchestrator** skill (`../setup-orchestrator/SKILL.md`).
- **Moving the config onto newly released models**, with the same subscriptions, uses the `update-orchestrator` skill.
- **A task that must finish without the user** uses the `autorun` skill.
- **Design or code bakeoffs** with base selection and grafting use the **arena** skill (`../arena/SKILL.md`).
