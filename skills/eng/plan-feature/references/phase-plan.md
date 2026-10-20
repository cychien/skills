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
- Heavy decides where expensive checks run: a native shell or perf check runs only in the phase that changes it.
- Every check has a Tier per `../../verify/references/plan.md`. An `e2e` check is a script that starts an instance on every rerun of its phase, so give that tier only to what a unit test cannot see and what costs most when broken.
- No phase reruns another phase's scripts, so each phase's plan holds Regression checks for the earlier behavior it could break.
- Changes is the only way an earlier phase's check stops holding. The phase that changes it holds a check with the new predicate in its own plan, so the change is never silent.
