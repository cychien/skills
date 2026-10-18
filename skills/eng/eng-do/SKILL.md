---
name: eng-do
description: Justin's engineering switchboard - routes software engineering work to its playbook. Use for /eng-do, or when the switchboard routes an engineering task here.
disable-model-invocation: true
---

# eng-do

Route engineering work to its playbook. Paths like `../feature/SKILL.md` point to skills installed beside this one.

- **Feature.** New or changed behavior, built from a named data shape. Uses the **feature** skill (`../feature/SKILL.md`).
- **Bug fix.** A bug, regression, or broken behavior to reproduce, root-cause, and fix. Uses the **bug-fix** skill (`../bug-fix/SKILL.md`).
- **Perf issue.** Something measured or reported as slow, fixed once against a baseline. Uses the **perf-issue** skill (`../perf-issue/SKILL.md`).
- **Hillclimb.** Sustained improvement of one metric against a target, one hypothesis at a time with keep or revert. Uses the **hillclimb** skill (`../hillclimb/SKILL.md`).
- **How it works.** "How does X work", code walkthroughs before changing something, and placement, ownership, or layering questions ("where should this live", "which package owns this"). Uses the **how** skill (`../how/SKILL.md`).
- **Why it is this way.** "Why does X work this way", why Y was picked, design rationale, regressions, postmortems, or data-backed thresholds. Uses the **why** skill (`../why/SKILL.md`).
- **Design before code.** The user wants the design itself: types, signatures, and module structure for code crossing a function boundary, explored in parallel before anyone implements. Uses the **architect** skill (`../architect/SKILL.md`). Work that should end in built behavior goes to Feature, which runs architect as one of its steps.
- **Prototype.** A throwaway sketch to settle a design or behavioral decision cheaply: "prototype", "mock it up", "try a few layouts", or an open question a run could answer instead of the user. Uses the **prototype** skill (`../prototype/SKILL.md`). Work that should end in shipped behavior goes to Feature.
- **Prove it works.** Proving, confirming, or checking that a change works, outside a playbook that already runs it. Uses the **verify** skill (`../verify/SKILL.md`).
- **No way to drive the app.** A project with no scripted way to launch and drive its UI, CLI, or service for verification. Uses the **create-verification-skill** skill (`../create-verification-skill/SKILL.md`).
- **Audit the verification skill.** Checking that a project's verification skill and feature map still match the app. Uses the **maintain-verification-skill** skill (`../maintain-verification-skill/SKILL.md`).
- **A measured number.** Reporting, trusting, or acting on a speedup, regression, latency, or throughput. Uses the **benchmark-checklist** skill (`../benchmark-checklist/SKILL.md`).
- **What could this break.** A diff you do not trust, or "blast radius of X". Uses the **blast-radius** skill (`../blast-radius/SKILL.md`).
- **Contested design or adversarial review.** "Interrogate", "challenge this", "stress test this code", or several models reviewing a change from independent angles before shipping. Uses the **interrogate** skill (`../interrogate/SKILL.md`).
- **Before review.** Strip comments that should be code, and fix what they were covering for. Uses the **no-comments** skill (`../no-comments/SKILL.md`).
- **Opening a PR.** Invoked at the end of every other playbook. Uses the **open-pr** skill (`../open-pr/SKILL.md`).
- **Docs, RFCs, readmes, PR descriptions, or commit messages** use the **technical-writing** skill (`../technical-writing/SKILL.md`).
