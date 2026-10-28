---
name: prototype
description: "Settle a design or behavioral decision cheaply with throwaway sketches instead of debate: build variants, observe them on the real surface, recommend one. Use for /prototype, 'prototype', 'mock it up', 'try a few layouts', 'sketch it to decide', or when an open question could be answered by running something instead of asking the user."
disable-model-invocation: true
---

# Prototype

**You own the design decision, not the code. The prototype is a throwaway instrument. The real build follows the feature or quick-feature skill.**

Paths like `../feature/SKILL.md` point to skills installed beside this one, relative to this file's folder.

This is the one playbook where the smallest-change rule of the Laziness Protocol (`../principles/references/principles/laziness-protocol.md`) and the verification bar invert. Speed over polish, code quality does not matter, no planning. The rigor is in picking the right design cheaply. Propose variations the user did not ask for, and throw an approach away to try another.

Open a todolist whose first items are the steps below, copied in verbatim, before any task-specific todos. The `guard` skill's `todo from prototype` does this; without guard, use your agent's todo tool. A step you choose not to do stays in the list with a one-line `skip: <reason>`.

1. Scope the decision the prototype exists to make: which layout, which interaction, which density, or for an empirical fork which behavior, timing, or approach. No decision means no prototype; route to the **feature** skill (`../feature/SKILL.md`), or for a small change the **quick-feature** skill (`../quick-feature/SKILL.md`). A question no run can settle (whether to build it, pricing, a product preference with nothing to look at) goes to the user instead.
2. Gather references when the design space is open. Search for prior art, summarize the themes, palettes, and layouts it shows, and let the user pick directions before building. Skip when the direction is set.
3. Build throwaway in a scratch directory outside the repository, such as your agent's scratchpad, because prototype code must never reach a diff or be held to the repo's rules. For a visual decision, plain HTML, CSS, and JS or the lightest stack that renders the idea, CDN dependencies, a dev server with hot reload. For a behavioral or timing decision, the smallest script that exercises the question. No production framework, no tests, no abstractions.
4. When comparing alternatives, build them behind one switcher (buttons or a keypress), each variant labeled. This is the Exhaust the Design Space principle (`../principles/references/principles/exhaust-the-design-space.md`) made cheap.
5. Observe on the matching surface. For a visual decision, drive each variant through chrome-devtools-axi, or the project's verification skill when the prototype runs inside the app, and screenshot every variant in the states that matter. For a behavioral or timing decision, observe the thing you are deciding: log the timing, print the output, watch the render. The observation is the test here, not an assertion.
6. Present the alternatives, tradeoffs, and a recommendation. The output is the decision plus the throwaway artifact, not shippable code. Hand the chosen direction back to the step that asked for it: the feature skill's first step when it settles a requirement or pass predicate, the **architect** skill (`../architect/SKILL.md`) when it settles the shape, otherwise the feature skill for the real build.

**Reply:** the variants explored, the evidence (screenshots for a visual decision, the observed output or timing for a behavioral one), tradeoffs, your recommendation, and the scratch path. Say plainly that the prototype is throwaway. Write it per the **reply** skill (`../reply/SKILL.md`).
