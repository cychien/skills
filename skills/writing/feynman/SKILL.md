---
name: feynman
description: "Learn a topic by writing about it: teach the user the topic in full, then propose an article outline they write themselves to lock in what they learned. Use for /feynman, 'I want to learn X and write about it', or when the user wants to study a subject with writing as the output."
disable-model-invocation: true
---

# Feynman

The user learns a topic, then writes about it to make the understanding stick. Your job is the teaching and the outline. The writing is theirs, because reconstructing the ideas in their own words is where the learning happens.

Paths like `../salvo/SKILL.md` point to skills installed beside this one, relative to this file's folder.

## Steps

1. **Take the topic as given.** A bare topic is enough; start without asking about their level or goals.
2. **Teach it.** Load the **teach** skill (`../teach/SKILL.md`) and follow it in full, research included. If it is not installed, tell the user and stop, because the outline depends on a complete teaching.
3. **Propose the outline,** in the same reply, after the teaching. Build it from what you just taught, following the rules below.
4. **Revise on feedback.** When the user pushes back on the outline, change it and return the whole updated outline under the same rules.

## Outline rules

The outline serves two people at once. The reader has to want to read the piece, and the writer needs a clear plan of what to say, so their effort goes into explaining each point in their own words.

1. **Pick the objective.** Choose the one the material supports best: distill something complex, overturn a common belief, share a solution, or tell how something came to be. The objective decides what the article argues, so name it first.
2. **Find the peak.** Writing quality is novelty times resonance. Pick the most surprising or counter-intuitive point from the teaching, the one a reader would not guess, and build the piece toward it. Mark which section carries it.
3. **Write the intro in full.** The intro's job is to make the reader want the rest, which is craft rather than understanding, so writing it costs the user no learning. Open with a half-told story: a question without its answer, a claim without its explanation. It must not give away what the body explains.
4. **Order the body.** Supporting points first, the ones the argument needs, then resulting points, what follows if the argument is true. Use as many sections as the material needs, usually three to six.
5. **Give each section a heading, its role in the article, and the points to write.** List the points in the order the section should make them, each as one sentence stating the claim, with the example, number, or source that backs it. Recommend what to say, not how to say it: no drafted paragraphs, because explaining a point in their own words is where the learning happens. A point they cannot explain marks what to revisit in the teaching.
6. **Recommend the ending.** Give the one-sentence takeaway the article earns, and where a reader should go next.

## Output

Write the outline in the user's language, after the teaching, using this shape:

```
## Article outline

**Objective:** <objective>
**Working title:** <title>

### Intro
<the full intro, written out>

### 1. <heading>
<the section's role in one line>
- <point to write, with its example or source>
- <point to write, with its example or source>

### <n>. <heading> (peak)
...

### Ending
- <the one-sentence takeaway>
- <where the reader should go next>
```
