# Phase plan

`plan.md` in the plan folder. The feature skill reads it phase by phase, so every phase entry keeps every field.

```
# <Feature> plan

<Under ten lines: what changes, for whom, and the phases in order.>

## Decisions

- <each decision settled with the user, and each deferred to the backlog with its pointer>

## Acceptance

- <check id> (<e2e, unit, or walk>): <one line in user terms>, proved in phase <n>

## Phases

### Phase <n>: <name>

- Scope: <what a user can do once it lands, and what waits for a later phase>
- Depends on: <earlier phase numbers, or none>
- Skeleton: <files and symbols from skeleton.patch this phase implements, or none>
- Checks: <ids in phases/<nn>-<name>/plan.md>
- Changes: <earlier checks this phase changes on purpose, each with its new predicate, or none>
- Heavy: <native shells, perf paths, and wire formats this phase changes, or none>
```

- A phase lands and reverts alone. When it cannot ship visible to users, name the flag that hides it.
- Heavy decides where expensive checks run: a native shell or perf check runs in the phase that changes it, and later phases regrade it by its carried script.
- Every check has a Tier per `../../verify/references/plan.md`. Only an `e2e` check leaves a script that later phases rerun, so give that tier only to what a unit test cannot see and what costs most when broken.
- Changes is the only way an earlier phase's check stops holding. The feature skill revises that phase's carried check under `verify.py freeze --revision` and never silently.
