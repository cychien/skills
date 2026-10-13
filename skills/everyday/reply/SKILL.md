---
name: reply
description: How to write the reply to the user at the end of a task or playbook - short declarative sentences, evidence on every claim, impact before implementation. Use for /reply, or when a playbook or switchboard asks for it.
disable-model-invocation: true
---

# Writing the reply

Any prose surface, your reply to the user included, follows the **unslop** skill (`../unslop/SKILL.md`). Write the reply clean as you draft it. A cleanup pass after drafting does not remove these patterns.

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

- **Short declarative sentences.** One thought per sentence, ended with a period.
- **No long-dash character anywhere.** Write a file-list bullet as a sentence ("`main.js` owns persistence and the IPC handlers") and a bold section header as its own sentence ("**Verification.** End to end via CDP").
- **A colon as a mid-sentence connector is also out** (unslop's colon rule). A colon before a list is fine.
- **Terse is not an excuse to drop content.** Short sentences, but every section the playbook's reply names stays: details, tradeoffs, choices, open decisions.
- **Frame impact for the consumer and the maintainer.** Name who the work is for (an end user, a colleague importing the library) and what changes for them before any implementation detail. Then what the next engineer who owns this code inherits. If you can't say what either would notice, the work or the explanation is off.
- **Never fabricate a link, citation, or transcript reference.** Link only artifacts you produced or read this session.
- **Every claim carries its evidence or its label in the same sentence.** Measured, inferred, or guess. A prediction or an unseen cause is a guess. Never hand the human a check you could run.

Every playbook ends with a reply written this way. In an autonomous run, the reply also covers autorun's Output section.
