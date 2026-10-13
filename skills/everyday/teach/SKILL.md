---
name: teach
description: "Explain a body of work plainly so a person actually understands it: a topic, a field, a paper, a documentation site, a YouTube or Bilibili video, a codebase, a diff. Covers what it is, how it works, and why it is built that way, presented as a web page when one can be shown. Use only when the user asks to be taught, as in /teach, 'teach me X', or 'help me really understand X', or when another skill asks for it. Not for routine requests to explain code or answer a question."
compatibility: "Reading videos needs yt-dlp, and ffmpeg to extract frames."
disable-model-invocation: true
---

# Teach

Explain a body of work so the person understands what it is, how it works, and why it is built that way. Understanding is the only goal, so change nothing: no edits, no fixes, no refactors, even when you spot a problem. Mention the problem instead.

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

The work has three parts. First settle what the person wants to learn. Then understand that domain yourself, completely and as it stands today. Then explain it to them in terms they already have. Keep the last two apart, because research done with the explanation in mind finds only what you already planned to say.

## Steps

### Find what they want to learn

What they hand you is not always what they want to learn, and the scope you settle here decides everything you research.

1. **Read the input and the request together.** A concept or field means that concept. A video link means what the video says. A paper, codebase, or diff means that work. A page on a documentation site is the input that misleads: people often send the page they happened to be on when they want to learn the whole tool, and just as often want only that page's topic. Their words settle it: "teach me uv, I was reading this page" means the whole tool, so the whole site is the scope; "explain this page" means the page.
2. **Ask when their words do not settle the scope**, as with a bare link to a documentation page. Ask one short question that names the scopes you see, such as this page's topic or the whole tool, and wait for the answer before researching. Use your question tool if you have one; otherwise make the question your whole reply. Do not pick a scope and state it as an assumption, because an explanation built on the wrong scope wastes the person's time. Do not ask when the request already settles it.

### Understand the domain

Build a complete, current, correct picture of the domain. Who is asking and how you will present it play no part yet.

3. **Read the source:**
   - **A concept or field:** there is nothing to read yet, so the web is the source. Search wide in step 4, from several angles, for the newest and most authoritative accounts before you narrow down.
   - **Code, a doc, a diff, a paper:** read it.
   - **A documentation site:** find the full list of pages from `llms.txt` at the docs root, then `sitemap.xml`, then the navigation. Read the raw text, such as `llms-full.txt` or the markdown versions `llms.txt` links to, fetched whole rather than through a tool that summarizes the page, because a summary drops the detail you will teach from. Read every guide and concept page in full, and enough of each reference page (API, CLI, configuration) to know what it covers. When the site is large and you can run subagents, split it by section across them.
   - **A video:** run `scripts/video.py <url> --out <dir>` from this skill's folder and read the whole `transcript.md` it writes, which includes the description and chapters. If it exits with code 3, the video has no subtitles you can read: tell the person you cannot understand this video and stop. Do not teach from the title and description, because that is a guess, and do not improvise another way to recover the speech, such as transcribing the audio or reading subtitles off the frames, because it costs far more time than the person expects from this request. When the speaker leans on what is on screen, such as slides, code, a demo, or "as you can see here", run it again with `--at <times>` for those moments, or `--frames <n>` for an overview, and look at the images.
   - **Any other kind of source:** find a way to read its actual content with the tools you have, because an explanation built from what others say about it is second-hand. If nothing you have can read it, tell the person, as with a video without subtitles.
4. **Research widely.** Search the web for the current, authoritative account: official docs, specs, papers, maintainers, primary sources over summaries. Open and read the sources themselves, because search snippets are too thin to teach from and hide when something was written. Check dates, because a field can move past what you remember, and past what a source says. When the person gave you a source, it sets the scope, and the web supplies context and shows where the source is out of date or wrong.
5. **Reconcile with what you know.** Merge the research with your own knowledge into one broad picture. Where they conflict, find strong evidence that settles it, and do not settle it by guessing. If the evidence stays split, tell the person what each side says.
6. **Map the territory.** Group related concepts the way a mind map would, and order the groups from foundational to advanced, so each one builds on what came before. Map the whole domain, including parts you may not explain at length, because you can only choose what to leave out once you know what is there.

### Explain it to this person

7. **Gauge the person.** Work out what they already know from their role, the words they used, what they asked, and anything you know about them. Assume they are new to the field when nothing says otherwise. A newcomer needs every term and step that might trip them up explained. Someone with a grounding can skip those explanations, but still gets the whole map, not a shortened tour of it.
8. **Teach it.** Start with a plain definition: name the thing, using its common name if it has one, and say what it is in everyday words, the way an expert in the field would say it out loud. Then walk the map in order, in their vocabulary. Tie each new idea to something they already know, and when a concept is too abstract to land in words, demonstrate it with a concrete example from their own work or world.

## Present it as a web page

Deliver the explanation as a web page whenever you can. A page renders diagrams, lets the reader jump between sections and come back later, and keeps a long explanation out of the chat scrollback.

1. If you have a tool that publishes or shows a web page, such as Claude's Artifact tool, use it.
2. Otherwise, if you can write files and open a browser, write one self-contained HTML file in a temporary directory outside the project and open it.
3. Otherwise, teach in the reply.

Only the medium changes; every rule below applies to the page too. Lay the page out in map order, with section headings the reader can navigate by.

## Deliver it whole

Give the whole explanation at once, and put any offer to go deeper at the end.

Skip the classroom theater, because it reads as performance and slows the reader down:

- No quizzes, and never ask them to say it back.
- Never print "Pause" or announce a key sentence.
- Never flag a part as important, tricky, or interesting. Just say it.

## Show, don't only tell

Open the diff, the code, or the debugger when that is the fastest way to land a point. Draw when a picture lands faster than words. A single simple point needs no figure.

Build pictures up instead of dumping them. For anything with three or more moving parts, draw a short series where each diagram redraws the last and adds one part, so the person watches the system assemble. One diagram with everything in it, especially saved for the end, is a reference, not teaching. To teach a flow from A to B to C: draw A to B, then redraw and add C, then redraw and add the return edge or the next piece. On a page, place each step of the series beside the text it illustrates.

Match the medium to the idea, and use both when both help:

- **Flow or structure, where the labels carry the meaning:** a mermaid diagram.
- **Spatial ideas, like layout, overlap, scroll position, or before and after:** generate an image when an image-generation tool is available, marker-on-whiteboard style with a few short labels, because image models garble long text. Generate it rather than describing it. Without such a tool, draw it as SVG on a page, or as ASCII in a chat reply. The build-up rule applies here too.

## Voice

Talk the way you would explain it to a colleague: plain, natural, tight but never so terse it gets hard to follow. Keep everything the person needs to understand.

Before writing the explanation, load the **unslop** skill (`../unslop/SKILL.md`) and apply it to everything the person will read, the page included.

## Reply

When the explanation is on a page, the reply is only the link or file path and the main point in one or two sentences. Everything else belongs on the page, including problems you spotted, assumptions, and where to go deeper, because a reply that summarizes the page competes with it and buries the link. Otherwise the reply is the explanation itself.

Wherever the explanation lives, leave out your own process: what you searched, ran, installed, or cleaned up. When you measured or tried something, present what it showed, and describe how only when the method changes how to read the result. Lead with the main point, then the plain account of what it is, how it works, and why. End by pointing at the areas worth exploring further, so the person knows where to go deeper.
