# Verification report: <change>

Head: <head SHA>
Main: <main SHA>
Author: <agent:model that wrote the change>
Verifier: <agent:model that produced the verdicts>

| Check | Verdict | Evidence | Observed |
|---|---|---|---|
| <id> | <PASS, FAIL, or INCONCLUSIVE> | <evidence files, comma-separated, relative to this directory> | <one line; a FAIL starts with "defect:" and the repro, an INCONCLUSIVE with "blocker:"> |

## Perf numbers

<each perf check: the number with its unit, run count, range, limiter, and data source>

## Exploration

- <finding, its repro and evidence>. Triage: <new check | pre-existing | dismissed> <why>

<or "none found" with no list>
