# Reviewer prompt

Fill every `<...>` that contains a space and send the block as the reviewer's whole task. The guard skill denies a subagent prompt that still holds a fill. Send it in Mode `change` once the code has landed, before the e2e run, and in Mode `fix` exactly once more to the same reviewer after the review's fixes land, even when nothing was fixed, so the code the e2e run grades is code a reviewer read. Once the fix review's own fixes land, add `Fixed at: <sha>` to its section yourself, the commit that holds them, or its Head when nothing was fixed. When the same reviewer cannot take Mode `fix` (its quota ran out), send it to the next candidate from `guard.py quota pick --relax` and add `Relaxed: <reason>` to the section. Start the reviewer through the salvo skill from the change's worktree, on a planner-role model from a different family than the author's when the orchestrator config has one, else on a different entry, picked with `guard.py quota pick --role planner --avoid <author's agent:model>`, because a reviewer of the author's family shares its blind spots.

```
You are reviewing a change you did not write. Find the defects its checks miss. Do not fix them.

Repository: <the change's worktree path>
Head: <head SHA>
Mode: <change for the whole change, or fix for the fixes made after the first review>
Diff: <the command that prints what to review: git diff BASE..HEAD in Mode change, git diff REVIEWED..HEAD from the Head the first review read in Mode fix>
Plan: <plan file path; read what was intended, then look for what it misses>
Sensitive paths: <the plan's Sensitive paths, or none>
Review file: <verification directory path>/review.md

Read the diff and the code it calls. Look hardest at the Sensitive paths, and at:
- Security: authentication and authorization on every new path; input that reaches a query, a shell, a file path, or HTML; secrets in logs or responses.
- Error paths: what each failure leaves behind (half-written state, a held lock, an open resource), and errors swallowed or reported as success.
- Concurrency: two requests or tabs at once, retries, ordering, a cache or subscription that outlives what it reflects.
- Multi-account state: data of one user, account, or tenant reaching another after a sign-out, an account switch, or a revocation.
- Wire and back compatibility: an older client against a newer server, a stored record in the old shape, a renamed field or route, a migration and its rollback.

Rules:
- Do not edit any file except the review file.
- Report a finding only with its location and either a repro or the exact reasoning from the code, because a hunch costs the lead a reproduction.
- Say how likely each finding is and how bad.

In Mode change, write the review file as a title line, a Reviewer line with your agent:model, and a "## Review" section whose first line is "Head: " and the SHA above, then one bullet per finding: the file and line, the finding, its repro or reasoning, and its likelihood and impact. Write "none found" in that section when you found none. In Mode fix, review only the fixes in the diff and what they call, leave everything already in the review file as it is, and append a "## Fix review" section in the same shape, with its own Head line naming the head you read and its own Reviewer line with your agent:model. Write "none found" there when the diff is empty or you found nothing. Write every finding as a bullet, never as plain prose, because a line that is not a bullet fails the review gate. Never write a Triage, a Fixed at line, or a Relaxed line; the lead does. Return the same list, at most 200 words.
```
