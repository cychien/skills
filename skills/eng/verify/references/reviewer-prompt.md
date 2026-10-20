# Reviewer prompt

Fill every `<...>` that contains a space and send the block as the reviewer's whole task. The guard skill denies a subagent prompt that still holds a fill. Send it in Mode `change` once the code has landed, in the same message as the verifier's prove stage, and in Mode `fix` at most once more, after the fix loop, when the fix diff changes more than 200 lines or touches a path the plan's Sensitive paths lists. Start the reviewer through the salvo skill from the change's worktree, on a planner-role model from a different family than the author's when the orchestrator config has one, else on a different entry, because a reviewer of the author's family shares its blind spots.

```
You are reviewing a change you did not write. Find the defects its checks miss. Do not fix them.

Repository: <the change's worktree path>
Head: <head SHA>
Mode: <change for the whole change, or fix for the fixes made after the first review>
Diff: <the command that prints what to review: git diff BASE..HEAD in Mode change, git diff REVIEWED..HEAD from the Head the first review read in Mode fix>
Plan: <plan file path; read what was intended, then look for what it misses>
Review file: <verification directory path>/review.md

Read the diff and the code it calls. Look hardest at:
- Security: authentication and authorization on every new path; input that reaches a query, a shell, a file path, or HTML; secrets in logs or responses.
- Error paths: what each failure leaves behind (half-written state, a held lock, an open resource), and errors swallowed or reported as success.
- Concurrency: two requests or tabs at once, retries, ordering, a cache or subscription that outlives what it reflects.
- Multi-account state: data of one user, account, or tenant reaching another after a sign-out, an account switch, or a revocation.
- Wire and back compatibility: an older client against a newer server, a stored record in the old shape, a renamed field or route, a migration and its rollback.

Rules:
- Do not edit any file except the review file.
- Report a finding only with its location and either a repro or the exact reasoning from the code, because a hunch costs the lead a reproduction.
- Say how likely each finding is and how bad.

In Mode change, write the review file as a title line, a Head line with the SHA above, a Reviewer line with your agent:model, and a "## Review" section with one bullet per finding: the file and line, the finding, its repro or reasoning, and its likelihood and impact. Write "none found" in that section when you found none. In Mode fix, review only the fixes in the diff and what they call, leave everything already in the review file as it is, and append a "## Fix review" section in the same shape. Never write a Triage; the lead does. Return the same list.
```
