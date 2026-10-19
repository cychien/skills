---
name: guard
description: Hard rules that enforce skill conventions through hooks, so an agent cannot skip them - a todo list every item of which must resolve, check-script gates on playbook steps, principle citations backed by reads, no em dash in replies, and the open-pr PR rules. Use when a guard message blocks you, to manage the todo list, or to add, change, or debug a guard rule.
---

# Guard

An instruction in a skill fails silently when an agent skips it. Guard moves the rules that can be checked mechanically into hooks, where skipping one blocks the agent and names the fix. A guard message is the rule speaking, not an error to work around.

## Rules

- **Todo list.** The agent decides what goes in the todo list, as in pstack: usually a skill's steps copied in verbatim, then task-specific items. Guard holds it to the list. Once a list exists, the turn cannot end while an item is open, except to ask the user a question or while background work is pending. In a non-interactive session (`claude -p`, `codex exec`), pending background work does not count, because ending the turn ends the process and kills that work. An item whose text says "Mandatory" cannot be skipped. An item that names other skills by path (`../<skill>/SKILL.md`) can be marked done only after those skills were read this session, and an item that reads "every principle file" only after each file in the **principles** skill was read. Skipping an item that would run another skill also skips that skill's items. After three stops in a row with no progress in between, guard lets the turn end, so a stuck run cannot loop forever, unless a Mandatory item is open: that one holds until it closes, and the only way out is a question to the user that names what blocks it.
- **Gates.** An item whose text names a skill's check script in backticks, as in `` `../verify/scripts/verify.py plan` ``, can be marked done only when guard runs that script from the agent's working directory and it exits 0. A failing gate prints the script's output and keeps the item open, so a playbook step backed by a check cannot be closed on the agent's word.
- **Todo decision.** When the agent is about to follow a skill that has steps, whether the user invoked it by `/name` or a switchboard led the agent to it, tool calls stay held until the agent decides the list: copy the skill's steps, add its own items, or record that it needs none. A switchboard without steps asks nothing, so the decision falls on the playbook it leads to. Reading a `SKILL.md` counts as following that skill when the file sits under a skill root (`.agents/skills`, `.claude/skills`, and their home-directory counterparts) or outside the current git working tree; a skill's own source inside the working tree is being authored, so reading it asks nothing. A read that only satisfies an open item's citation asks nothing; a `/name` invocation or a Skill tool load still does.
- **Principle citations.** Once a session uses the **principles** skill or reads a principle file, a reply that names a principle must come after reading that principle's file in `references/principles/` this session. Only real reads count (the read tool, or `cat`, `head`, `sed -n`, and similar on the file); editing or searching a file does not.
- **No em dash.** A reply with an em dash outside code is sent back for a rewrite. This holds in every session.
- **Tracked salvo.** A shell command that runs `salvo.py run` detached with `nohup` or a trailing `&` is denied, because the harness then never notifies the agent when it ends. Run it in a background tool call instead. Text inside quotes or a heredoc does not count. This holds in every session.
- **Filled templates.** A subagent prompt (the Agent tool's prompt, or the file a `salvo.py run` reads on stdin) that starts from a skill's `references/*-prompt.md` template is denied while it still holds one of that template's fills, any `<...>` containing a space. This holds in every session.
- **Leftover sweep.** After a TaskStop call, guard runs the **verify** skill's `verify.py leftovers --kill` and shows the agent its output. A spawn (the Agent tool) is denied with the sweep's output while `verify.py leftovers` still lists survivors, because a new delegate on top of an old one's processes hides which one caused any later problem. When the verify skill is not installed or the sweep cannot run, the spawn is allowed and the reason goes to `errors.log` in the guard state folder.
- **Reply.** When a skill in the todo list asks for its reply per the **reply** skill, the turn cannot end after the list resolves until that skill was read.
- **PR rules.** Once a session uses the **open-pr** skill, `gh pr create` and `gh pr edit` are checked before they run: a Conventional Commits title with no trailing period, no `--draft`, and description headings drawn from Why, What changed, Scope, Tradeoffs, Blast Radius, and Verification, in that order, with Scope always present.

## The todo list

The hook messages give these commands with the session filled in. Define `g` once as a shell function, never a variable holding the command, because zsh does not word-split a variable and every command then silently does nothing:

```
g() { python3 scripts/guard.py "$@" --session <agent:id>; }
g todo from <skill>
g todo add "<item>" ["<item>" ...]
g todo done <n> [<n> ...] [--note "..."]
g todo skip <n> [<n> ...] --reason "..."
g todo none --reason "..."
g todo list
g todo clear --reason "..."
```

Never pipe guard output through a filter such as grep, because a refusal prints its reason there and the filter hides it.

`todo from` copies the numbered items of a `## Steps` section, step headings (`## 1.`, `## Step 1,`, `## Phase A:`, `## Pass 1:`), or a numbered list right after the title. For a skill written another way, add its steps with `todo add`. Skip an item only for a reason the user would accept, because the reason is what they read. Clear the list only when the user stops the work. When every item resolves, list them with their marks in the final reply.

## Install and state

Guard has no hooks of its own. It runs inside the hook runtime of the `autorun` skill, which loads guard's rules whenever guard is installed beside it, so install autorun's hooks once (`python3 <autorun>/scripts/autorun.py install`) and keep both skills installed.

State lives in `~/.agents/guard/sessions/`, one file per agent session; sweeps that could not run are logged in `~/.agents/guard/errors.log`. Set `GUARD_SKILL_ROOTS` to a path list to override where guard looks for installed skills.

## Adding a rule

Write the rule in `scripts/guard_lib/rules.py` as a check on one hook event (`prompt`, `pre_tool`, `post_tool`, or `stop`) that returns `("deny", message)`, `("block", message)`, `("context", message)`, or `("pass", None)`, and add tests to `tests/test_guard.py` in this repo. Name the fix in the message, since the agent acts on it directly. Prefer a rule over another line of skill text whenever the convention can be checked from a hook payload.
