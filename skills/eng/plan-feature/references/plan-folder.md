# Plan folder

A plan folder holds `plan.md` (decisions, acceptance, phases), `spec.md` (the design), and, when the design has one, `skeleton.patch` with its rationale. The feature skill reads `plan.md` phase by phase, so every phase entry keeps every field.

## plan.md

```
# <Feature> plan

<Under ten lines: what changes, for whom, and the phases in order.>

## Decisions

- <each decision settled with the user, and each deferred to the backlog with its pointer>

## Acceptance

- <id>: <one line in user terms>. Proved by <a unit spec, a drive on the real surface, an oracle over edge-shaped seeds, or a perf budget at a stated data size>, in phase <n>

## Phases

### Phase <n>: <name>

- Scope: <what a user can do once it lands, and what waits for a later phase>
- Depends on: <earlier phase numbers, or none>
- Skeleton: <files and symbols from skeleton.patch this phase implements, or none>
- Proves: <Acceptance ids>
- Heavy: <native shells, installed artifacts, perf paths, and wire formats this phase changes, or none>
```

- A phase lands and reverts alone. When it cannot ship visible to users, name the flag that hides it.
- Heavy tells the build where the expensive runs go: a native shell, a fresh install from a published artifact, or a perf measurement runs in the phase that changes it.
- Acceptance ids never repeat, so a Change log line can name the item it moved.

## spec.md

```
# <Feature> spec

<The whole design, in the sections it needs: the data shape and who owns it, the modules and their boundaries, the flows, the wire and storage formats, failure behavior, and the names the design builds (routes, HTTP paths, commands and flags, test ids and accessible names, wire and event names, file paths). Fold in the skeleton's notes and its rationale's decisions.>

## Change log

- <phase>: <what changed in the design, why, and which later phases it affects>
```

- `spec.md` is the one design document. No phase keeps design decisions in a file of its own, because a later phase reads only the spec.
- Any later phase may change `spec.md`, the Acceptance list, and the entries of the phases after it whenever building shows the design was wrong, with a Change log line in the same edit. A naming or placement detail the design did not fix is not a design change and stays out of the log.
