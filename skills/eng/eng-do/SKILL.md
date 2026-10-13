---
name: eng-do
description: Justin's engineering switchboard - routes software engineering work to its playbook. Use for /eng-do, or when the switchboard routes an engineering task here.
disable-model-invocation: true
---

# eng-do

Route engineering work to its playbook. Paths like `../feature/SKILL.md` point to skills installed beside this one.

- **Feature.** New or changed behavior, built from a named data shape. Uses the **feature** skill (`../feature/SKILL.md`).
- **How it works.** "How does X work", code walkthroughs before changing something, and placement, ownership, or layering questions ("where should this live", "which package owns this"). Uses the **how** skill (`../how/SKILL.md`).
- **Why it is this way.** "Why does X work this way", why Y was picked, design rationale, regressions, postmortems, or data-backed thresholds. Uses the **why** skill (`../why/SKILL.md`).
- **Design before code.** The user wants the design itself: types, signatures, and module structure for code crossing a function boundary, explored in parallel before anyone implements. Uses the **architect** skill (`../architect/SKILL.md`). Work that should end in built behavior goes to Feature, which runs architect as one of its steps.
- **Contested design or adversarial review.** "Interrogate", "challenge this", "stress test this code", or several models reviewing a change from independent angles before shipping. Uses the **interrogate** skill (`../interrogate/SKILL.md`).
- **Before review.** Strip comments that should be code, and fix what they were covering for. Uses the **no-comments** skill (`../no-comments/SKILL.md`).
- **Opening a PR.** Invoked at the end of every other playbook. Uses the **open-pr** skill (`../open-pr/SKILL.md`).
- **Docs, RFCs, readmes, PR descriptions, or commit messages** use the **technical-writing** skill (`../technical-writing/SKILL.md`).
