---
name: code-comments
description: How code is commented, for every file an engineering playbook or its subagents produce. Use for /code-comments, or when a playbook asks for it.
disable-model-invocation: true
---

# Code comments

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

Comments follow the same rule as the reply (the **reply** skill, `../reply/SKILL.md`). Write them clean as you go. Keep a comment only for a non-obvious *why* the code can't show. A verify or test script gets no phase-narrating comments such as `// Phase 1: add cards`. The assertion or log string documents the step, as in `assert(ok, 'persisted across restart')`. This applies to every file you produce, including the delegate's diff.
