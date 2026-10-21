# Verification report: <change>

`python3 ../scripts/verify.py report --write --author <agent:model> --verifier <agent:model> [--note "<text>" ...]` builds this file from the evidence, so nobody writes it by hand: the table from each check's latest `<id>.rerun.log`, `units.json`, or `evidence/<id>/`, each Observed cell from the verifier's line in `observations.md`, and the Review section from `review.md`. A cell with no observation reads `missing`, and the `report` gate fails until the verifier writes it. Build it again after every change to the evidence.

Head: <head SHA>
Main: <main SHA>
Author: <agent:model that wrote the change>
Verifier: <agent:model that produced the verdicts>

## Not ready to merge

<present only when a row is FAIL or INCONCLUSIVE: one bullet per such check, with its Observed cell>

| Check | Verdict | Evidence | Observed |
|---|---|---|---|
| <id> | <PASS, FAIL, or INCONCLUSIVE> | <evidence files, globs, or brace patterns, comma-separated, relative to this directory; each must match a directory or a non-empty file written after the freeze: <id>.rerun.log for an e2e check, units.log for a unit check, evidence/<id>/ for a walk check> | <one line from observations.md; a FAIL starts with "defect:" and the repro, an INCONCLUSIVE with "blocker:"> |

## Notes

<one bullet per `--note`: each quota fallback that relaxed a separation rule, who replaced whom, for which limit>

## Perf numbers

<each perf check: the number with its unit, run count, range, limiter, and data source>

## Review

<the reviewer's findings from review.md, the review and the fix review; each ends in a triage:>

- <file:line, the finding, and its repro or reasoning>. Triage: <fixed | follow-up | pre-existing | dismissed> <why, and for fixed the unit spec that proves it>

<or "none found" with no list>
