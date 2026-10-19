---
name: architect
description: "Design the shape of a change before code: types, signatures, and module structure, explored across several models and delivered as a skeleton patch that typechecks, plus its rationale. Use for /architect, 'architect this', 'design this', or non-trivial work where jumping to code would lock in the wrong shape."
disable-model-invocation: true
---

# Architect

Sketch types, function signatures, class shapes, and module boundaries with `not implemented` bodies and pseudocode. Synthesize across multiple model perspectives and deliver the chosen skeleton. Design only: building against the skeleton belongs to the playbook that called this skill, or to the feature skill.

Paths like `../how/SKILL.md` point to skills installed beside this one, relative to this file's folder.

## Start

Open a todolist with one entry per phase before starting.

1. Ground
2. Sketch
3. Deliver

## Phase A: Ground the problem

Build a real mental model of every system the new code touches. Run the **how** skill (`../how/SKILL.md`) over the relevant subsystems. Naming a file isn't grounding. Produce the architectural explanation `how` prescribes. If the design redefines ownership or layering, also run the **why** skill (`../why/SKILL.md`) on the existing shape so the rationale becomes a constraint, not a guess.

Skip Phase A only when the work is genuinely greenfield with no surrounding system to integrate.

## Phase B: Sketch

Run the **arena** skill (`../arena/SKILL.md`) with the design-sketch task and the Phase A grounding artifacts. Pass `references/runner-prompt.md` as each runner's prompt, with this file's absolute path added, because runners work in their own workspaces.

Run the candidates on the planner role, in place of arena's choice of role, because a design sketch is planning work.

When the caller hands a design doc that still applies, frame the arena task as the structural gap the doc leaves open, with the doc as a fixed constraint, so "design it twice" applies to the gap and not to the shape the doc already settled.

Design it twice. Require at least two structurally distinct candidates before synthesis, even when the first looks sufficient. This is the Exhaust the Design Space principle (`../principles/references/principles/exhaust-the-design-space.md`) made concrete. Alternatives to the whole framed task, not point fixes inside one shape.

Screen every candidate against [`references/design-red-flags.md`](references/design-red-flags.md) before synthesis. Assume the next contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that compiles. Prefer the design where a change that looks right from one file is right for the whole repo.

Compare viable candidates on interface depth. Prefer the design that hides more complexity behind a smaller, simpler public surface. A rich interface can keep call chains short by concentrating capability instead of scattering it across layers.

Compare viable candidates on performance too. Pass the verification plan's perf budgets to every runner with the task, and make performance one of arena's rubric criteria: the candidate that meets the budgets at the stated data size with the fewest round trips and the least hot-path work. A candidate that cannot meet a budget loses, unless the user agrees to change the budget.

Arena returns one synthesized design package. Its synthesis decision fills the rationale's "Synthesis decision" section.

## Phase C: Deliver

Write the synthesized skeleton as `skeleton.patch`: real files at the paths the code will live in, types and signatures in full, bodies `not implemented` with pseudocode for the tricky logic. Apply it to a scratch worktree of current main and run the project's typecheck, and fix the skeleton until it passes, because a skeleton that does not compile hides a wrong signature until someone builds against it. Write the rationale beside it, shaped per `references/rationale-template.md`. Save both where the caller names, or in the project's design docs folder when called directly, and present them: the skeleton is the contract the implementation is built and checked against.

If the human pushes back on the shape, treat that as Phase A evidence. Re-ground and re-run Phase B.

## Outputs

`skeleton.patch`, which typechecks against main, and the rationale beside it, including the caller's usage sketch and the synthesis decision.
