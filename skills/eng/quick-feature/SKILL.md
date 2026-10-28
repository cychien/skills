---
name: quick-feature
description: "Build a small change about as fast as asking an agent to do it: make the change yourself, test it, run it once on the real surface, open a PR. No design step and no review. Use for /quick-feature, or when a switchboard routes a small change here."
disable-model-invocation: true
---

# Quick feature

**Speed first.** The user picks this skill to iterate fast, so it runs about as fast as asking an agent directly. It drops the design step, the oracle and perf checks, the run from a fresh install, and the cross-family review that the **feature** skill keeps, and keeps only what a careful engineer does anyway: tests for the change and one run on the real surface. Never switch to another playbook on your own, because the user chose this one.

Paths like `../open-pr/SKILL.md` point to skills installed beside this one, relative to this file's folder.

**With a plan folder** from the **plan-feature** skill (`../plan-feature/SKILL.md`), build every phase that has not landed, in its order, in this one session. Run the four steps once per phase, starting each phase with a fresh `todo from quick-feature`. The Acceptance items the phase's entry in `plan.md` proves list what to prove: write a unit test for each one a unit spec can see, and drive each other one once by hand in step 3. Read `spec.md` before each phase, and when the design has to differ from it, change `spec.md` and the later phase entries the change affects, with a line in its `## Change log`, so the next phase builds on what shipped. Open one PR per phase, the first against main and each later one against the phase before it, because plan-feature cut the phases so each lands and reverts alone.

Open a todolist whose first items are the steps below, copied in verbatim. The `guard` skill's `todo from quick-feature` does this; print each step with guard's `todo show <n>` and close it with the token that prints. Without guard, use your agent's todo tool.

1. Understand the change and make it. Read the code it touches and find the pattern it copies, a file and a symbol, then make the change yourself instead of delegating it, because a delegate costs a start and a hand-off. Ask the user only what the request leaves truly ambiguous, all in one message, because each extra round is idle time.
2. Test it. Write or update the unit tests for the behavior the change adds or alters, with literal expected values, and run only the specs it touches. Then run the project's lint and typecheck. Fix what fails before you go on.
3. Run it once. When the change shows on a surface (a page, a CLI, an API), drive it once on the real app, through the project's verification skill (`.agents/skills/verify-<app>/` or `.claude/skills/verify-<app>/`) when there is one, else directly (the browser, a terminal, curl). Keep a screenshot or a transcript for the PR. Skip this step with the reason when nothing user-visible changed.
4. Open the PR with the **open-pr** skill (`../open-pr/SKILL.md`), with the screenshot or transcript from step 3 in its Verification section. Never merge, because the user lands every PR.

**Reply** in a few lines: what changed, the pattern it copied, how you tested and ran it, the PR link, and any question left open.
