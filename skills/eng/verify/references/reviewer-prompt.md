# Reviewer prompt

Fill every `<...>` that contains a space and send the block as the reviewer's whole task. The guard skill denies a subagent prompt that still holds a fill. Start the reviewer once the code has landed, through the salvo skill from the change's worktree, on a planner-role model from a different family than the author's when the orchestrator config has one, else on a different entry, because a reviewer of the author's family shares its blind spots.

```
You are reviewing a change you did not write. Find the defects its checks miss. Do not fix them.

Repository: <the change's worktree path>
Head: <head SHA>
Diff: <the command that prints the change, such as git diff BASE..HEAD with both SHAs>
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

Write the review file as a title line, a Head line with the SHA above, a Reviewer line with your agent:model, and a "## Review" section with one bullet per finding: the file and line, the finding, its repro or reasoning, and its likelihood and impact. Write "none found" in that section when you found none. Never write a Triage; the lead does. Return the same list.
```
