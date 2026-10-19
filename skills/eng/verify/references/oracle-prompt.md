# Oracle prompt

Fill every `<...>` that contains a space and send the block as the oracle's whole task; `<id>` stays as written. The guard skill denies a subagent prompt that still holds a fill. Copy the seed files into a fresh directory outside the repository, and launch the oracle from there with salvo, so the repository's code is out of reach. Use a different model family from the author's when the orchestrator config has one, because a shared misreading of the spec would match itself.

```
Compute what a correct implementation must show, from the definition and the data below. You have no access to any implementation, and you must not look for one.

Request: <the user's request, verbatim>
Definitions:
<for each oracle check: id, Oracle, Shape, Tolerance>
Seed data: <paths of the copied seed files>
Output directory: this working directory

Rules:
- Compute each value from the seed files alone, by hand or with a small script you write here. Do not run or read the application.
- Where the definition leaves a case open (a time zone, a tie, an empty group, a boundary date), do not guess. Write the open question instead of a value.
- Write <id>.expected.json for each check, in exactly its Shape, in this working directory. Do not look outside it.

Reply with each id, its value, and how you computed it, plus every open question.
```
