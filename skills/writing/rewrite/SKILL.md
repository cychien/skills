---
name: rewrite
description: Rewrite an existing draft so it is clear, succinct, and worth reading to the end, while keeping the author's meaning and voice. Handles English, Chinese, and mixed Chinese-English text. Use this whenever the user pastes or points at prose and asks to rewrite, tighten, polish, simplify, shorten, or improve it, in any language, including 改寫, 潤稿, 精簡, 修一下, or "make this read better".
disable-model-invocation: true
---

# Rewrite

A first draft is written for the author. The rewrite is written for the reader. Map the key terms first, then run the draft through four passes in order. Each pass has one job, and mixing them produces timid edits.

Keep the text in its original language. Keep the author's voice, their claims, and every nuance. The job is to make what they meant land, not to say something else.

## Before the passes: map the key terms

Readers assume two different words name two different things, and one word means the same thing every time. Drafts break both: the author swaps synonyms for variety, or lets one word drift between two concepts. The reader then cannot tell whether "rule", "skill", and "workflow" are three things, one thing, or parts of each other.

1. List the terms the argument rests on: the nouns a reader must keep apart to follow it.
2. For each, work out what it refers to and how it relates to the others: the same thing, a part of, a kind of, or unrelated. Derive this from every place the author uses it and from its meaning in the subject's field, never from one sentence or one convenient example.
3. A term is open when the draft never states its meaning or relationship and more than one reading would change what the reader believes, such as who does what or how many steps a process has. Two names that sit side by side without a stated link are open, however likely one reading feels. If any term is open, reply with the question and no rewrite, even when you cannot wait for the answer: the author reads the reply either way, so a question costs one round trip, while a guessed rewrite silently changes their argument and reads too fluently to catch. Ask only about open terms, and show the map you inferred for the rest, so one reply confirms everything.
4. During the passes, give each concept one term and each term one concept. Keep the author's own word, not a synonym you prefer.
5. Where the reader cannot infer a term's relationship to its neighbours, define it in a short clause where the term first appears. State only relationships the author stated; never add one to make the text flow.

## Pass 1: clarity

Make the text understandable by a thirteen-year-old who knows nothing about the topic, without dropping any nuance or key fact.

- Use the plain word. "Use", not "utilize". "Hard", not "non-trivial".
- One idea per sentence. Split sentences that carry two.
- Put the actor first. "The compiler rejects it", not "it is rejected".
- Where an abstract claim stays fuzzy, add a concrete example. A before-and-after pair is the strongest form.

Before: "The obstacle facing media organizations is charting an economically sustainable course through a landscape of commodity journalism."

After: "News companies are struggling to stay in business because anyone with a Twitter account can report the news now."

## Pass 2: succinctness

Succinct is a ratio, not a word count. It is the share of sentences that carry a significant thought. A long piece can be succinct. A short one can be padded.

Three steps, in order:

1. **Rebuild each section from its summary.** Write a one or two sentence summary of what the section must say. Rewrite the section from that summary, adding words only where the reader needs them. Filler does not survive this because you never put it back.
2. **Strip filler words.** Remove every word that adds no context: hedges, throat-clearing openers, restated subjects, "in order to", "it is important to note that". Extra words make the reader slow down and hunt for the point.
3. **Rephrase each paragraph from scratch.** Now that you know exactly what the paragraph says, say it in the fewest sentences that still read naturally.

Before: "To be brief on the sentence level, you should remove filler words that don't add necessary context to the sentence. This isn't intuitive to novice writers: these extra words cause readers to unwittingly slow down and do extra work while reading."

After: "Your sentence is brief when no more words can be removed. Filler buries the point and bores readers into quitting."

The tweet test: if the whole piece compresses into one tweet with nothing lost, tell the user. They may want the tweet instead of the piece.

## Pass 3: intrigue

Clarity and succinctness lower the cost of reading. Intrigue is what makes someone keep reading. Readers judge a piece by its peak and its ending, not by the average paragraph, so you do not need every paragraph to sparkle. You need three things:

1. **An opening that earns goodwill.** A hook is a half-told story: a question without its answer, a story without its ending, a claim without its explanation. If the draft opens with preamble, cut to the first interesting sentence.
2. **At least one peak.** One section with a genuine surprise, a counter-intuitive point, or an insight stated so well the reader wants to quote it. If the draft has none, tell the user. Do not invent one.
3. **An ending that justifies the read.** One sentence that makes the reader think "that is why this mattered", then where they go next. Not a summary of the sections.

In long pieces, spread the interesting moments out. A long stretch with nothing new in it is a cue to shorten it or move something interesting into it.

## Pass 4: copyedit

- Paragraphs of five sentences or fewer. White space lowers the perceived workload.
- Verbs carry the adverb. "She shouted", not "she spoke loudly".
- Adjectives and adverbs stay only when they add information.
- Use words the author would say out loud. "Plethora", "myriad", "delve", and "leverage" rarely pass that test.
- Prefer the precise word to the vivid one, and the vivid one to the vague one.
- Use a plain dash, never an em dash.

### Bold

Bold marks the one thing a skimming reader must not miss. Bold the claim, not the whole sentence, and at most a few per section. When everything is bold, nothing is.

## Chinese and mixed Chinese-English text

Apply these on top of the four passes whenever the text is Chinese or mixes Chinese with English.

- **Third-person pronouns follow the referent.** 他 is a man, 她 is a woman, 它 is anything without life: an object, an animal, a system, a company, an idea. Mixing them up is a correctness error, not a style choice, so check every 他, 她, and 它 against what it points to.
- Put one space between Chinese characters and any Latin letters or digits: "這個 feature 跑了 3 次", not "這個feature跑了3次".
- Keep proper nouns in their official capitalization: GitHub, Claude Code, React, TypeScript.
- Lowercase common English words used inside Chinese sentences: "這個 feature", "跑一次 eval", "開一個 pull request". Capitalizing them reads like shouting.
- Do not translate a term the author left in English, and do not rewrite digits as Chinese numerals. They chose it.

## Output

If a key term is open, return only the questions and the inferred term map. Otherwise return the full rewritten text. When a pass changed the structure (cut a section, moved the hook, replaced the ending), add three to five short bullets under "What changed" so the author can object. When you unified or defined terms, list each one with the meaning you gave it, so the author can correct the map. Skip the bullets for sentence-level edits. Never explain the passes to the user unless they ask.

Done when the author's meaning survives intact, every key term names one concept, no sentence can lose a word without losing information, and the opening, peak, and ending are each in place or the user has been told which one is missing.
