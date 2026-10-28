# Flow v2.1 feature skills (archived)

The `feature` and `plan-feature` skills as they stood at commit `1001ded` (tag `flow-v21-feature`), after flow v2.1 merged, kept for reference. They are not installed: the files are not named `SKILL.md`, and their `../` paths point at skills as they were then. Restore them with `git checkout flow-v21-feature -- skills/eng/feature skills/eng/plan-feature`. Tag `flow-v2-feature` holds the flow v2 texts before v2.1.

- `feature.md` and `feature-phases.md`: the ten-step feature flow (a base gate, premises, plan lock, an independent verifier writing e2e scripts, review, one e2e run, a FAIL loop) and how it built a plan folder one phase per session.
- `plan-feature.md` and `plan-feature-phase-plan.md`: planning that also wrote `grounding.md` and every phase's checks before any code.

## Why they were replaced

A review of the flow v2 runs from 2026-10-17 to 2026-10-27 (parlor agent-ui and inline-agent phases 3 to 7, developer-experience, device-linking; ezdesign canvas and capture; firstory ad-downloads):

- The cross-family code review carried the quality gap over quick-feature: 35 fixed findings in inline-agent phases 4 to 7 and firstory A1, about 85% of them security, concurrency, cross-account, or failure-path defects that unit tests and one run on the real surface would miss, and 11 of them introduced by the fixes the first review asked for.
- The independent verifier's e2e scripts found about 7 product defects across every run, none in phases 6 and 7, while taking about half the wall time (phase 6: 16 e2e FAILs, all driver or environment). In phase 3 the owner's own runs found about 13 defects and five independent verifiers found 1.
- The worst escapes were packaging and fresh-install defects that both flows missed, found by running a freshly published app.
- Of 21 plan revisions after a lock, 4 changed a predicate, each for a false premise.
- From plan-feature, the phase cut (26 of 26 phases built as planned), the decisions, and the skeleton (69 to 77% of its lines shipped) paid off. `grounding.md` went unread in three of four builds, checks written for distant phases kept 0 to 37% of their wording, and regression checks were mostly never written and never caught anything.
