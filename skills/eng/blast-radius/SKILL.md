---
name: blast-radius
description: "Find what a change could break elsewhere before it ships, beyond the diff, and prove the one fact it is safe because of by running real code instead of writing it up. Use for /blast-radius, 'blast radius of X', 'what could this break', or reviewing a small diff you do not trust."
disable-model-invocation: true
---

# Blast radius

Find what a change breaks somewhere else, before it ships. The **how** skill (`../how/SKILL.md`) tells you what the code does, and the **why** skill (`../why/SKILL.md`) tells you why it is shaped that way. Blast radius tells you what it breaks elsewhere.

Paths like `../how/SKILL.md` point to skills installed beside this one, relative to this file's folder.

Listing the callers is not the job, because an agent can grep those in a second. The job is the breakage grep does not show.

1. Read the change: a diff, or a type sketch with `not implemented` bodies when no code exists yet, the symbols it adds, changes, and deletes, and what it now does differently, including the part it does not spell out. Steps 2 to 5 work on a sketch's signatures and wire shapes, and step 5's proof script runs against the existing code the sketch will touch, so the review lands before the code does. For a diff, pull the PR and commits the way the why skill's Step 2 does.
2. Find the one fact the change is safe because of. Most changes that look risky are safe because of a single fact, like "this call only drops already-dead cache entries and does nothing else". If it holds, most risky cases clear at once, so spend your time here, not on a long list of maybes.
3. Look where grep stops. Read the source of the libraries you call, at the pinned version, with any local patch. Work out when things run: microtasks, unmount and teardown, framework scheduling. Follow what a symbol search misses: the JSON an API returns, a DB column, a wire format, another language reading the same bytes, a feature flag, code three hops downstream.
4. Rate each risk honestly: a real chance of happening and a real cost if it does. Keep the confirmed risks, and list the ones you checked and cleared separately. Cite a real `file:line`. A search that finds nothing is still an answer. Never make up a caller or an API.
5. Prove the one fact. Write a script or test that runs the real code, run it, and paste what happened.
6. For a big or wide change, run the question through the **arena** skill (`../arena/SKILL.md`) and merge the answers, because different models catch different real bugs.

## How sure are you

Push each fact the change's safety depends on as far down this list as is cheap, and say where it stopped. A writeup that sounds right reads as convincing whether or not it is true, so only the lower levels count as proof.

1. You said so. Worthless on its own.
2. You pointed at the line: a real `file:line`, or the library's own source.
3. You showed the bad case cannot happen, by walking the failure step by step until it does not reach.
4. You ran it: a script or test that calls the real code and fails loudly if you are wrong. Usually one small script that imports the library the app ships and calls the exact function you worry about.
5. You reproduced it in the running app, through the **verify** skill's driver (`../verify/SKILL.md`).

## Output

- **What it does.** What changed, including the part that is not obvious.
- **The one fact it is safe because of.** State it, give the level it reached, and show the proof. If you could not prove it, write unproven.
- **Risks.** Each names how it breaks, the `file:line`, how likely and how bad, and how to check. Paste the proof for the ones that matter.
- **Cleared.** What you checked and why it is fine.
- **Before you merge.** The cheapest test or repro that catches the real bug, including the script you wrote.

Write it per the **unslop** skill (`../unslop/SKILL.md`), and strip anything private before it goes anywhere public.
