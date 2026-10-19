---
name: open-pr
description: "Open pull requests the house way: a worktree off main, small ordered commits, Conventional Commits titles, and a one-minute PR description. Use at the end of every engineering playbook, or for /open-pr."
disable-model-invocation: true
---

# Open a PR

Run at the end of every other engineering playbook.

Paths like `../how/SKILL.md` point to skills installed beside this one, relative to this file's folder.

**Worktree.** Work from a git worktree off main. Subagents inherit it. Multiple subagents on the same branch each get their own worktree, or `git fetch && git reset --hard origin/<branch>` between them. Dirty branch with unrelated work: patch out, fresh worktree, apply. Snarled worktree: reset from main, redo minimally.

**Commits.** Commit liberally. Rebase into small, ordered commits before opening PRs. Each commit is landable and ordered to tell the story. Amend when the fix belongs in a just-made commit. New commit when separable. Commit bodies don't restate the subject.

**PRs.** Confirm the **no-comments** skill (`../no-comments/SKILL.md`) ran on the diff before the verification freeze, and run it now only if it did not, because a pass after the freeze rewrites verified commits. Write every PR title, description, and commit body with the **technical-writing** skill (`../technical-writing/SKILL.md`) (every layer except Diátaxis, and apply the STE vocabulary rules: one word per action, keep articles, a plain verb over `-ing` where one works), then apply the **unslop** skill (`../unslop/SKILL.md`).

**Titles.** Conventional Commits `type(scope): subject`, no trailing period. Type such as `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, or `perf`. Scope is the area, such as `autorun` or `cli`. Subject is short, imperative, and names a real symbol when one carries the change, for example `fix(autorun): ignore quoted trigger phrases`.

**Descriptions.** The PR body is a one-minute briefing, not a lab notebook, for a reviewer who has the diff. It says why the change exists, what it leaves out, what it could break, and how you proved it works. Write short, simple sentences with few identifiers, no walls of text. The body becomes the squash commit body, so keep that commit under about 40 lines. Use `##` headings, not bold lead-ins, in this order, and drop a section with nothing to say:

- `## Why`: the problem and approach, 1–3 short sentences. No SHAs, rebase genealogy, or "based on main" preamble.
- `## What changed`: 1–3 short bullets. Name a real symbol or path only when it carries the change. Name both sides of a rename or retarget.
- `## Scope`: always. 1–3 short items on what it covers and what it deliberately leaves out (a follow-up, a known gap). No symbols, paths, or file-by-file essay.
- `## Tradeoffs`: only rejected alternatives a reviewer would otherwise ask about. Skip when there was no real choice.
- `## Blast Radius`: 1–2 sentences on who or what it touches and why that is safe or risky. If main is red, state the cost of leaving it red.
- `## Verification`: 1–3 bullets, each a real run path and its outcome. Perf: one primary number with its unit, `before → after`, and a link to the arena directory for the rest. No sample-size methodology, run recitals, or metric tables.

After the sections, attach videos or screenshots when they prove a claim. Full SHAs, arena lane recitals, lever-correction essays, file-by-file checklists, and "CLEAN" verdicts go in a linked artifact, not the body.

**Forge.** Use the GitHub CLI (`gh`) for every PR operation. Do not require Graphite (`gt`).

**Size and stacks.** Open one PR per feature carrying the executor's ordered commits. Stack only when the project's AGENTS.md or the user asks, or a phased feature opens one PR per phase, because every rebase repoints every child PR. A stack is a base-branch chain. The root PR targets trunk. Each child branch rebases onto its parent's exact tip and its PR targets the parent branch. Create a child with `gh pr create --base <parent-branch>`, and retarget one with `gh pr edit <pr> --base <parent-branch>`. A commit that fixes something unrelated to the feature, such as a pre-existing bug fixed on sight, goes in its own PR on a branch cut from trunk, and comes off the feature branch, because it must land or roll back without the feature. Rebase on trunk before substantial stack work.

**Link.** Reply with each PR's link as `https://github.com/<owner>/<repo>/pull/<number>`.

**Readiness.** Open every PR ready, never as a draft. With `gh`, omit `--draft`. If a PR still opens as a draft, run `gh pr ready <number>`. Run `gh pr view <number>` before you refer to PR status.

**Babysit.** Opening a PR does not start a babysit. Post the URL and keep building. Finish the phase or stack first. Run a separate babysit pass only when the user asks for one after the whole stack exists. A babysit for each new PR stalls the build and spends checks on commits later waves restart. Push back when feedback drifts from intent.

A subagent that opens a PR runs the **interrogate** skill (`../interrogate/SKILL.md`), confirms the **no-comments** pass ran, posts the URL, and returns to the parent without babysitting.
