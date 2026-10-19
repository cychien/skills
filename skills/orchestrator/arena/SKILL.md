---
name: arena
description: "Spawn N parallel candidates at the same task, pick a base, graft the strongest parts of the losers into it. Use for /arena, 'arena this', 'throw it in the arena', or when one attempt at a non-trivial artifact would lock in the wrong shape."
disable-model-invocation: true
---

# Arena

Open a todolist with one entry per phase (Frame, Fan out, Cross-judge, Pick, Graft, Verify) before launching anything.

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

## Phase A: Frame

Every candidate gets the same prompt, so the prompt is the contract.

1. State the artifact each candidate is producing.
2. Derive the rubric, 3-6 concrete gradeable criteria for what success looks like on *this* task. It is the picker's tool in Phase D. Candidates only see the task.
3. Pick the runners: one per distinct model in the role that fits the artifact in the orchestrator config (`<project>/.agents/orchestrator/models.json`, falling back to `~/.agents/orchestrator/models.json`), the planner role for designs, plans, specs, and reviews, the executor role for code. If there is no config, ask the user to run the **setup-orchestrator** skill (`../setup-orchestrator/SKILL.md`) or to name the models. Spawn more runners when the arena covers multiple design directions. Use the same model N times when the work is generation-bound rather than judgment-sensitive.
4. Give each candidate its own output location, per the Separate Before Serializing Shared State principle (`../principles/references/principles/separate-before-serializing-shared-state.md`). The **salvo** skill (`../salvo/SKILL.md`) gives each run its own workspace.

## Phase B: Fan out

Launch all N candidates in one run of the **salvo** skill (`../salvo/SKILL.md`), in the background where your agent supports it, each with the task, the path to the shared grounding, and instructions to produce the artifact and a short rationale naming the alternatives it considered and what it rejected.

If a candidate produces no output, proceed with N-1 and note the dropout. When a runner stops on a usage limit and at least two structurally distinct candidates are complete, continue without it as a dropout; wait for the reset only while fewer than two are in hand, because the wait idles the run for hours to add a candidate you no longer need.

## Phase C: Cross-judge

After all Phase B candidates complete or drop out, choose one planner model from the orchestrator config, preferring a different model family from yours. Run it alone through `salvo` as a read-only judge, from the directory holding the candidates' outputs. It sees the rubric and the candidates by path label, scores each criterion, and recommends a base with rationale. It runs in parallel with your reading in Phase D. Don't spawn it while candidates are still writing.

## Phase D: Pick a base

Read every candidate end to end before picking. Score each against the rubric criterion by criterion, not on holistic feel, and compare with the cross-judge. Agreement on the base confirms the pick. Disagreement means one of you is biased or the rubric was ambiguous. Read both rationales before deciding.

Pick the base a future maintainer can extend most easily without breaking invariants. When two feel tied, prefer the cleaner boundary or smaller API, per the Laziness Protocol.

## Phase E: Graft

Walk each losing candidate once more for what is worth porting into the base, usually one or two things per candidate, not most of it. Fold each graft in by hand, per the Redesign from First Principles principle (`../principles/references/principles/redesign-from-first-principles.md`), so the result stays coherent under one mental model. Don't paste mechanically.

If the candidates converge on one shape, that is strong agreement. Note it and ship the consensus shape. No graft is needed. If they wildly diverge, Phase A was under-specified. Reframe and re-run rather than averaging the divergence.

## Phase F: Verify

Verify the synthesized artifact like any other output, per the Prove It Works principle (`../principles/references/principles/prove-it-works.md`). If verification finds a problem the arena missed, either Phase A was wrong (re-frame and re-run) or a candidate caught it and you missed the graft (go back to Phase E). Don't paper over it.

## Outputs

One synthesized artifact, with a short synthesis note alongside naming the base and why, the cross-judge's verdict, each graft with its source candidate, what was rejected and why, any convergence or dropouts, and the verification result.
