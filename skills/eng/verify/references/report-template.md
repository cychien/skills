# Verification report: <change>

Head: <head SHA>
Main: <main SHA>
Author: <agent:model that wrote the change>
Verifier: <agent:model that produced the verdicts>

| Check | Verdict | Evidence | Observed |
|---|---|---|---|
| <id> | <PASS, FAIL, or INCONCLUSIVE> | <evidence files, globs, or brace patterns, comma-separated, relative to this directory; each must match a directory or a non-empty file written after the freeze: <id>.rerun.log for an e2e check, units.log for a unit check, evidence/<id>/ for a walk check> | <one line; a FAIL starts with "defect:" and the repro, an INCONCLUSIVE with "blocker:"> |

## Perf numbers

<each perf check: the number with its unit, run count, range, limiter, and data source>

## Review

<the reviewer's findings, copied from review.md or left there; each ends in a triage:>

- <file:line, the finding, and its repro or reasoning>. Triage: <new check | follow-up | pre-existing | dismissed> <why>

<or "none found" with no list>
