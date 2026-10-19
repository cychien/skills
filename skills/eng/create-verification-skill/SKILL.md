---
name: create-verification-skill
description: "Generate a project-local verification skill that drives the app the way a user does, in any language, framework, or platform. Use for /create-verification-skill, \"make a verify skill for this repo\", or when a project has no scripted way to prove UI, CLI, or service behavior."
disable-model-invocation: true
---

# Create a verification skill

Every serious project needs a scripted way to drive the real app and prove behavior: launch it, exercise a feature the way a user would, and capture evidence. This skill generates that as a project-local skill, `verify-<app>`. Write it for the next agent, not for a human: an agent that has never seen the app will read it cold, in the middle of a task.

Paths like `../open-pr/SKILL.md` point to skills installed beside this one, relative to this file's folder.

## 1. Interview the repo, not the user

Work in a clean worktree off main, never on a branch that carries unmerged changes. A driver and a feature map read from changed code describe the change as the app's behavior, so they pass the change's bugs instead of catching them.

Answer these from the codebase. Ask the user only what you cannot observe.

- **Surface.** What does a user touch: a web UI, a CLI or TUI, a desktop app, an API, a mobile app, a library? A repo can have several. Pick the primary one and note the rest.
- **Run.** How does the app start locally? Prefer the repo's own documented dev command (package scripts, Makefile, README quickstart). Note ports, env vars, seed data, and auth.
- **Drive.** How can an agent interact with it programmatically? Use an existing harness first: Playwright or Cypress specs, expect scripts, PTY helpers, curl-able endpoints, a debug port. Only then pick a generic recipe: chrome-devtools-axi for web and Electron, a tmux session for a CLI or TUI, plain HTTP for a service.
- **Observe.** What evidence can be captured: screenshots, ARIA snapshots, terminal transcripts, response bodies, logs, exit codes, database state? Also note what the harness itself changes about the app, such as focus, visibility, or timing under remote control, so a verifier does not read a harness artifact as app behavior.
- **Isolate.** Can two instances run side by side (ports, data dirs, browser profiles)? If not, say so in the generated skill, because refusing to double-drive a shared instance beats corrupting the user's session.

If the checkout does not build or start as-is, fix that first or report it precisely before generating, because a skill written against a broken base teaches wrong steps. When an irrelevant missing asset blocks startup (a static dir the API never serves, a sample config), the generated skill may create it, marked as verification scaffolding, and remove it in cleanup.

## 2. Generate the skill

Create the real folder at `.agents/skills/verify-<app>/` and link `.claude/skills/verify-<app>` to `../../.agents/skills/verify-<app>`, so Claude Code and every agent that reads `.agents/skills/` load the same copy. If the project already keeps skills elsewhere, put it there instead.

Write `SKILL.md` with frontmatter (`name: verify-<app>` and a `description` that names the app, the surface, and when to reach for it) and these sections, each grounded in what the interview found, with no placeholders left:

- **Launch.** The exact command that starts the app for verification, and how to tell it is ready (a log line, a prompt). Launch reaches a usable state from an empty data dir, including migrations and seed data. Ready means usable, not just that a process answers: a database health check can pass while its init scripts still run. For a short-lived CLI or TUI there is no server to keep alive: build the binary or install deps once, then start each drive in its own isolated tmux session.
- **Seed.** How to load named datasets, and the datasets themselves, kept in the skill as declarative fixtures (JSON, CSV, or SQL) with a one-line description each. Load them straight into storage, never through the app's business logic, because data created by the code under test inherits its bugs and an oracle could not compute from it independently. Ship at least a `baseline` dataset under which every mapped feature can be reached and shows real content, and a `large` dataset at production-like volume for perf checks. Without seed data a UI often cannot be driven at all, and a computed number cannot be checked against its spec. Loading is idempotent: loading a dataset twice gives the same state.
- **Doctor.** One read-only check that answers "is this instance worth driving?": process up, the right build, the port owned by this run, auth valid. An agent runs it first, and again whenever anything looks off.
- **Drive.** The harness recipe with real selectors and commands from this repo, not examples. Prefer stable handles (ARIA roles and names, data attributes, prompt strings, route paths) over coordinates and tab order.
- **Evidence.** What to capture for a proof, and where it goes. Default to the directory `python3 ../verify/scripts/verify.py where` prints, outside the diff, because the verify skill's report gate looks for evidence there. State the proof standards: exercise the real user path, not internal setters or test-only endpoints; capture the action and the resulting state, not just the final screen; verify side effects (files written, rows inserted, messages sent) alongside what is visible; mock only where a production boundary already isolates the external system. When the safe path is a dry run or test mode, verify what it skips by observing files, network, and git refs, because some dry runs still touch the network or open a browser.
- **Cleanup.** How to tear down what the run created. Never kill by process name; kill what you started. Cleanup removes instances and scratch state, never the evidence.
- **Helpers.** Any script the skill ships is executable and its invocation is shown in the skill body. A helper the reader has to reverse-engineer is not a helper.

## 3. Seed the feature map

Create `features/README.md` in the generated skill, plus one file per user-facing feature you can identify. Start with the top 3 to 5, from routes, commands, menus, or docs. Follow the shape in `references/feature-map-example/`: a README index and one file per feature. Each file answers, from the user's point of view, what the feature is, how to reach it, how to drive it with the harness, and what observable end state proves it works. Its four H2s are `Sub-features`, `How to get to it (user POV)`, `Driving it with <harness>`, and `Gotchas`.

If the seed data lacks a precondition a journey needs, the journey reports a failure and the reason goes in that feature's `Gotchas`. Never weaken the journey to make it pass. The map is the repo's maintained verification source, so a proof that drives one convenient entry point is incomplete when the map lists others.

## 4. Prove the generated skill

Run its own instructions end to end once: launch, load the `baseline` dataset, doctor, drive one mapped feature, capture evidence, clean up. Load `large` once too and confirm the app still starts and shows it. After cleanup, confirm the evidence still exists at the named location, because a cleanup that eats the proof fails this step. Fix what fails, and run the generated cleanup after every failed attempt, so broken attempts do not strand processes and ports. A generated skill that was never executed is a draft, not a deliverable.

If you proved it in a stand-in for the real target (a container in place of a fresh VM, a local stack in place of a remote one), list every setup step the stand-in did that the target will not. Those steps stay unverified until a run on the real target covers them.

## 5. Ship it

The verification skill is team infrastructure, so commit the folder and the symlink and open a PR with the **open-pr** skill (`../open-pr/SKILL.md`). When agents keep writing throwaway scripts to click through the app, propose a small control CLI that the skill calls instead, per the Build the Lever principle (`../principles/references/principles/build-the-lever.md`).

## Output

Report the generated skill's path, the features in its map, the proof run with its evidence path, every step the proof did not cover, and the PR link. Point the user at the **maintain-verification-skill** skill (`../maintain-verification-skill/SKILL.md`) for keeping the map honest as the app changes.
