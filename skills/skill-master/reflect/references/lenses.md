# Lenses

Paste one section into `reviewer-prompt.md` per reviewer.

## Judgment

Your strength is judgment and synthesis. Name the durable principle behind a specific incident, the thing that saves future agents real time.

Scan for:

- Mistakes made and corrections the user gave
- User preferences and workflow patterns
- Codebase knowledge gained: architecture, gotchas, patterns
- Decisions and their rationale
- Friction in following a skill, orchestrating, or delegating
- Repeated manual steps that could be automated or encoded

## Tooling

Your strength is code and tooling specifics. Name the concrete tool, command, path convention, or flag behavior that future agents would otherwise re-derive.

Scan for:

- Tool invocations and command flags the agent had to discover
- Library and framework quirks: config, lockfiles, environment variables, version-specific gotchas
- File or path conventions that are not obvious from a glance at the code
- Test commands, CI flags, and how to reproduce a failing run locally
- Debugging entry points: how to capture a trace, where logs land
- Build, package-manager, or sandbox surprises that cost minutes the first time

Also flag every moment the user supplied context the agent could have fetched itself through an MCP tool, a CLI, or another skill: a pasted ticket title, a linked chat thread, "this is from PR #X". Route each to the skill that owns that workflow, so the next agent fetches it itself.

## Divergent

Your strength is the angle the other two reviewers will miss: second-order effects, what did not happen but should have, alternative paths not taken. If the obvious learning is X, find the Y that complicates or contradicts it.

Scan for:

- Decisions that worked for the wrong reasons, or survived only because the test path was lucky
- Verification that was skipped, deferred, or self-reported instead of checked against an artifact
- A local fix that missed its second-order effect on callers, sibling consumers, or downstream data
- Architectural smells the immediate fix papered over
- Skills that should have run but did not, or ran too late
- Implicit assumptions about scope, side effects, or what the user actually wanted

For evidence, cite what was said and what was not.
