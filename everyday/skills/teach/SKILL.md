---
name: teach
description: "Explain a body of work plainly so a person actually understands it: a topic, a field, a paper, a codebase, a diff. Covers what it is, how it works, and why it is built that way. Use for 'teach me this', 'help me really understand X', 'explain this to me', 'walk me through how X works', or when another skill needs to teach the user something."
disable-model-invocation: true
---

# Teach

Explain a body of work so the person understands what it is, how it works, and why it is built that way. Understanding is the only goal, so change nothing: no edits, no fixes, no refactors, even when you spot a problem. Mention the problem instead.

## Steps

1. **Research widely.** Read the material itself when it is in front of you: the code, the doc, the diff. Then search the web for the current, authoritative account: official docs, specs, papers, maintainers, primary sources over summaries. Check dates, because a field can move past what you remember.
2. **Reconcile with what you know.** Merge the research with your own knowledge into one broad picture. Where they conflict, find strong evidence that settles it, and do not settle it by guessing. If the evidence stays split, tell the person what each side says.
3. **Map the territory.** Group related concepts the way a mind map would, and order the groups from simple to deep, so each one builds on what came before.
4. **Gauge the person.** Assume they are new to the field unless you already know their level. A newcomer needs every term and step that might trip them up explained. Someone with a grounding can skip those explanations, but still gets the whole body of work, not a shortened tour of it.
5. **Teach it.** Start with a plain definition: name the thing, using its common name if it has one, and say what it is in everyday words, the way an expert in the field would say it out loud. Then walk the map in order. When a concept is too abstract to land in words, demonstrate it with a concrete example.

## Keep it a conversation

Talk with the person, not at them. Offer to go deeper or move on, and follow their lead. Where you would naturally pause, stop and let them respond.

Skip the classroom theater, because it reads as performance and slows them down:

- No quizzes, and never ask them to say it back.
- Never print "Pause" or announce a key sentence.
- Never flag a part as important, tricky, or interesting. Just say it.

Running one-shot with no live person, deliver the whole explanation cleanly and put any offer to go deeper at the end.

## Show, don't only tell

Open the diff, the code, or the debugger when that is the fastest way to land a point. Draw when a picture lands faster than words. A single simple point needs no figure.

Build pictures up instead of dumping them. For anything with three or more moving parts, draw a short series where each diagram redraws the last and adds one part, so the person watches the system assemble. One diagram with everything in it, especially saved for the end, is a reference, not teaching. To teach a flow from A to B to C: draw A to B, then redraw and add C, then redraw and add the return edge or the next piece.

Match the medium to the idea, and use both when both help:

- **Flow or structure, where the labels carry the meaning:** a mermaid diagram.
- **Spatial ideas, like layout, overlap, scroll position, or before and after:** generate an image when an image-generation tool is available, marker-on-whiteboard style with a few short labels, because image models garble long text. Generate it rather than describing it. Without such a tool, draw it as ASCII or a small HTML page. The build-up rule applies here too.

## Voice

Talk the way you would explain it to a colleague: plain, natural, tight but never so terse it gets hard to follow. Keep everything the person needs to understand.

Before sending each reply, read the `unslop` skill's `SKILL.md`, in the folder next to this skill's, and apply it to your draft. It cannot be invoked as a skill, so read the file.

## Reply

The reply is the explanation itself. Leave out your own process: what you searched, ran, installed, or cleaned up. When you measured or tried something, present what it showed, and describe how only when the method changes how to read the result. Lead with the main point, then the plain account of what it is, how it works, and why. End by pointing at the areas worth exploring further, so the person knows where to go deeper.
