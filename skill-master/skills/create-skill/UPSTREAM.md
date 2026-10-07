# Upstream

Derived from Anthropic's `skill-creator` skill.

- Repository: https://github.com/anthropics/skills
- Path: `skills/skill-creator`
- Snapshot commit: `683bc88` (2026-10-05)
- License: Apache 2.0

## What changed

- Renamed to `create-skill`.
- Rewrote `SKILL.md` as a lightweight loop: capture intent, draft, try on a few prompts, review with the user, improve.
- Replaced the testing method with the `eval-skill` skill (blind multi-model runs through `salvo`, a blinded judge, and a promote-or-revise loop), keeping the trigger test. Removed the benchmark statistics, timing capture, description optimization loop, eval viewer, analyzer agent, JSON schemas, packaging, and the platform-specific sections. The `agents/`, `assets/`, `eval-viewer/`, `references/`, and `scripts/` directories were dropped with them.
- Added house rules: every skill artifact is written in English, plain dashes only, concise and to the point.

## Checking for upstream changes

```
git clone --depth 50 https://github.com/anthropics/skills /tmp/anthropic-skills
git -C /tmp/anthropic-skills diff 683bc88..HEAD -- skills/skill-creator
```

Merge by hand what is worth keeping, then update the snapshot commit above.
