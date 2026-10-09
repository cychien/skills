---
name: unslop
description: "Cut AI tells from writing so it reads like a person wrote it, in English or Chinese. Use for /unslop, or when another skill asks to run its text through unslop."
disable-model-invocation: true
---

# Unslop

Edit text to remove the patterns that mark it as machine-written. Readers who spot them stop trusting the rest.

## Process

1. Scan the text for the patterns below.
2. Rewrite each hit. Keep the intended tone, and leave code, quotations, and names untouched.
3. Change the wording, never the claims. Keep each claim's certainty, so a suspicion stays a suspicion, and add no fact, detail, or promise the text did not make. When a sentence has nothing concrete behind it, cut it instead of inventing substance for it.

## Patterns to detect and fix

Rule numbers are stable ids that other skills cite. Never renumber; a removed rule leaves a gap.

### Content

1. **Superficial -ing phrases.** "highlighting...", "ensuring...", "reflecting...", "showcasing...", "fostering...". Delete, or keep only the concrete claim underneath.
2. **Vague attributions.** "Experts believe", "Industry reports suggest", "Some critics argue". Name the source when the text gives one, or delete.

### Language

3. **AI vocabulary.** Additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape (abstract), pivotal, showcase, tapestry (abstract), testament, underscore, vibrant. Replace with plain words.
4. **Fancy ways to say "is".** "serves as", "stands as", "boasts", "features". Say "is" or "has".
5. **"Not just X, but Y."** Also 不僅…更…, 不是…而是… when nobody claimed X. State the point directly.
6. **Mirror sentences.** "A without B, or B without A". The symmetry is decoration. Say the one thing that matters.
7. **Rule of three.** Forcing ideas into groups of three. Use the natural number.
8. **Synonym cycling.** Protagonist, main character, central figure, hero in one paragraph. Pick one word and repeat it.
9. **False ranges.** "from X to Y" where X and Y are not on a meaningful scale. List the items directly.

### Style

10. **Em dashes.** Never use an em dash, including the doubled one Chinese uses. A period or comma usually reads best. Where a dash genuinely fits, use a spaced plain hyphen " - ".
11. **Colon overuse.** Colons belong before a list or an example, not as mid-sentence connectors. "If you're coming from traditional automation: instead of registering handlers, you describe conditions" leans on the colon and on comparison framing. Let the point stand alone: "You describe when the scheduler should fire in plain English."
12. **Boldface overuse.** Don't bold every proper noun or acronym.
13. **Inline-header lists.** The tell is a bold label and colon that restates the line: "**Performance:** Performance improved...". Convert those to prose. A bold lead-in that ends in a period, names the item, and is followed by genuinely new detail ("**Schema in TypeScript.** Tables live in one file.") is fine.
14. **Title case headings.** Use sentence case.
15. **Decorative emojis.** Remove them from headings and bullets.
16. **Curly quotes.** Use straight quotes in English. Chinese keeps 「」.

### Communication artifacts

17. **Chatbot phrases.** "I hope this helps!", "Let me know if...", "Of course!", "Certainly!", "Found the smoking gun!". Remove.
18. **Sycophantic tone.** "Great question! You're absolutely right!". Respond directly.
19. **Signposting.** "Here's the key part", "this is the tricky bit", "the core insight is", 重點是, 關鍵在於, 這是整件事的核心. Announcing that something matters instead of saying it. Delete the announcement and state the thing.

### Filler

20. **Filler phrases.** "In order to" becomes "to". "Due to the fact that" becomes "because". "It is important to note that", 值得注意的是, 需要指出的是, 事實上, 不難發現, 可以看出 get deleted.
21. **Excessive hedging.** "could potentially possibly be argued that it might" becomes "may".
22. **Generic conclusions and tidy closers.** "The future looks bright", "the rest follows", "it all falls out", 綜上所述, 總而言之, 讓我們拭目以待, 未來可期. End on a specific fact, plan, or next step, or just stop.

### Jargon

23. **Abstract metaphor nouns.** Substrate, wedge, vector, locus, vantage, nexus, primitive (as noun), harness (as metaphor), surface (as in "API surface"), bedrock, scaffolding (as metaphor), modality, paradigm, gold-plating, ratchet (as metaphor), evacuate (for moving code), endgame, north star, flywheel. They sound technical but usually hide a plainer concrete word: "substrate" is "base", "wedge in" is "add", "vector" is "way", "gold-plating" is "more than the job needs", "evacuate" is "move out". Pick the concrete word.

### Plain speech

24. **Say what it does, not how it feels.** "The database stays close at hand" and "types that follow your schema" name a feeling. Name the mechanism or number the text supports instead: "`.toSQL()` returns the exact string sent to the database", "a column rename fails the build". If a sentence cannot be restated as a concrete instruction, fact, or number, cut it. If it could appear unchanged in another project's docs, it says nothing about this one, so cut it.
25. **Dense sentences.** If the reader has to backtrack to parse a sentence, split it or drop clauses. One idea per sentence.
26. **Active voice.** Catch "is/are/was/were + past participle" and name the actor: "queries are validated" becomes "the compiler validates queries". Keep passive only when the actor is unknown or does not matter.
27. **Adverbs.** "runs quickly" becomes "is fast" or the number. "significantly improves" becomes the measured delta. An adverb propping up a verb means the verb is wrong.
28. **The plain word.** "utilize" and "leverage" become "use", "facilitate" becomes "help", "numerous" becomes "many", "in the event that" becomes "if".
29. **Mannered prose.** Metaphor or flourish where a literal phrase exists: aphorisms ("wire it or delete it"), rhetorical fragments, personified code ("the plan holds it"), figurative verbs ("rides along", "stands on"), stock framing phrases. "A dial worth turning" becomes "a parameter worth varying".
30. **Over-compression.** Dropped articles, verbless fragments, arrows, and abbreviations make the reader decode instead of read. "Parser rejects bad date → exit 2, no write" becomes "The parser rejects a bad date, exits with code 2, and writes nothing."

### Chinese

The rules above apply to Chinese too. These patterns are specific to Chinese.

31. **Buzzwords.** 賦能, 抓手, 閉環, 底層邏輯, 顆粒度, 打通, 助力, 深耕, 全方位, 一站式, 痛點 (outside product talk). Say what actually happens: 「賦能團隊」 becomes what the team can now do.
32. **進行 / 作出 + verb.** 「對系統進行全面測試」 becomes 「全面測試系統」. 「作出調整」 becomes 「調整」.
33. **Chains of 的.** 「這是一個十億參數的開源小模型的微調的完整方案」. Split the sentence or reorder so each 的 does one job.
34. **Stacked 被.** 「被社群多次回報，被認為與記憶體洩漏有關」. Name the actor when the text knows it, as in rule 26, and otherwise restructure without inventing one: 「社群回報過很多次，可能跟記憶體洩漏有關」.
35. **Four-character stacking.** 「穩定可靠、快速響應、易於維護」 sounds solid and says nothing. Replace with the specific fact or number.
36. **Era openings.** 「隨著…的快速發展」, 「在…的時代背景下」. Start at the first sentence that says something.
37. **Translationese.** 「作為一個開發者」, 「對於…來說」, 「使得」, 「基於…」, an 一個 before every noun. Write the sentence a native speaker would say.
38. **Mechanical sequencing.** 首先、其次、最後 when the points are not a real sequence. Drop the markers or use a list.
39. **Pronouns.** 他 for a man, 她 for a woman, 它 for anything without life: objects, systems, companies, ideas. Check each against its referent.

## Output

When the user hands you text, return only the edited text in full, ready to paste. Skip any list of changes or explanation of the edits: it buries the result, and the user can compare the two versions themselves. The one exception is a claim you could not keep or that looks wrong; flag it in one line after the text. When another skill runs its own draft through unslop, apply the edits silently and send only the clean result.
