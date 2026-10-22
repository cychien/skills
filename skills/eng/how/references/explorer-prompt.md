# Explorer Prompt Template

Build each explorer subagent's prompt from this template. Fill in the placeholders.

---

Other explorers are investigating different slices of the same subsystem in parallel. Don't try to cover everything. Focus on your assigned angle and go deep.

## Question

> {QUESTION}

## Your Exploration Angle

{EXPLORATION_ANGLE}

## Premises to Test

{CHECKS_OR_NONE}

When checks are listed above, test their premises: every fact each check assumes already holds on the base commit given with the checks, whether it holds, and the file and line or command output that shows it. Do not decide what to do about a false one.

## Output

Write the sections below to {OUTPUT_FILE} and hand back its path with at most 200 words.

### Components Found
The key types, services, classes, and abstractions. For each: name, file path, and a one-sentence description of what it does.

### Flow
The execution flow step by step. For each step: what function/method runs, what file it's in, what it does, what it calls next. Include the data that flows between steps.

### Files Read
Every file you read during exploration, so the explainer can reference them.

### Boundaries
Where this subsystem connects to other parts of the codebase. The inputs and outputs.

### Non-Obvious Things
Anything surprising, historically motivated, or easy to get wrong. Things that look like they should work one way but work another.

### Premises
One line per premise when checks were listed: check id, the premise, holds yes or no, and the evidence. For behavior the change itself builds, write one line per check with holds `new` instead of one `no` per missing piece. Skip this section otherwise.

### Open Questions
Anything you couldn't fully trace or understand. Be honest about gaps.
