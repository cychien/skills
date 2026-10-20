# Verification plan: <change>

## Checks

### <id>. <title>

- Scenario: <one user-visible behavior, with a concrete input and starting state>
- Surface: <where a user meets it>
- Evidence: <the artifact that proves it>
- Pass: <a predicate another agent can check against the evidence>
- Oracle: n/a: <why the result is not a value computed from data>
- Tier: <e2e, unit, or walk, per the Terms in plan.md>
- Touches: <e2e only: `<path glob>`, `<path glob>`, every package the scenario runs through>

### <id>. <title of a check whose result is computed from data>

- Scenario: <the computed value, with the seed it starts from>
- Surface: <where a user reads it>
- Evidence: <id>.expected.json, <id>.observed.json, <screenshot or transcript>
- Pass: <the observed value matches the oracle's>
- Oracle: <the spec's definition, precise enough to compute by hand>
- Seed: <the dataset>
- Shape: <the JSON both sides write>
- Tier: <e2e or walk: an oracle value is read from the running app>
- Touches: <e2e only: `<path glob>`, every package the scenario runs through>

## Perf

### <id>. <title>

- Path: <the wait as the user experiences it, at a stated data size>
- Metric: <what is measured: a count where it captures the cost, plus the timing of the wait>
- Probe: <the command or procedure, run on main and head, interleaved>
- Baseline: <main, or none: why main lacks the path>
- Rule: <the number that fails: a limit against main, or absolute budgets for the added work and the end state>
- Touches: `<path glob>`, <every package on the measured path>

## Drive contract

- <kind: test id, accessible name, route, HTTP path, CLI command or flag, wire or event name, or file path>: `<the exact name>`, <what it is and which checks drive it>

## Sensitive paths

- `<path or glob>`: <why a defect there costs most: auth, permissions, crypto, or similar>
