---
name: eval-skill
description: "Find out whether a new or changed skill actually changes agent behavior, with a blind experiment: an organic task run in parallel on several models through salvo, a blinded judge on a different model, and your own grading, reconciled into a promote-or-not recommendation. Use for /eval-skill, 'eval this skill', or when the user wants evidence that a skill works before shipping it."
---

# Eval skill

You own the experiment design. The question is always whether the variant makes agents behave the way it promises on a task where nothing tells them they are being watched. A run that knows it is observed performs for the grader, and a judge that knows which output came from the variant grades its own expectations. Either way you learn about the experiment, not the skill.

This skill drives the `salvo` skill. Load it for how it picks models, and run `scripts/salvo.py` from salvo's folder. If salvo is not installed, stop and tell the user.

## Blinding

Everything a run can see counts: the prompt, the project, every directory, file, and branch name, and the git history.

- Use no word that signals measurement: eval, test, judge, experiment, rubric, score, compare, benchmark, candidate, arena, variant, baseline. A project's own test suite is fine, because a real project would have one.
- Write the prompt as an ordinary user request. State the goal, never what is being measured.
- Never ask a run to list the skills, principles, or files it used. Self-report is cheap to fake and cues the behavior you are trying to observe. Grade chain-following from what the transcript shows the run opened and from the shape of its output.
- Name projects, directories, and commits as a user would.
- Never mention other runs.

The judge may know it is judging, but sees runs only by shuffled label, never by model or arm.

## Steps

1. **Frame.**
   1. Name the variant (its path) and the behavior it should produce.
   2. Write 3-6 concrete criteria that hold only when that behavior happens. Only the judge sees them.
   3. Decide on a baseline arm. It doubles the cost, so run one only when success is relative: a rewrite or restructure that could regress what the old version did, or a new skill, however small. A new skill always gets a no-skill baseline, because without one nothing shows that the behavior came from the skill rather than the model, or that the skill triggered at all. An added or changed rule passes when the runs show the behavior it asks for, whether or not models would have done it anyway, so it gets no baseline, even when the user asks whether the rule works. The baseline is the previous version (from git or a snapshot) for a change, and no skill for a new one.
2. **Build the project.**
   1. Make a private experiment directory with `mktemp -d /tmp/eval-<slug>-XXXXXX`, or inside your scratchpad if you have one. Never reuse a fixed path: another eval running at the same time would overwrite it. Keep everything below in it. Salvo puts the run workspaces elsewhere, so runs never see this directory.
   2. Create a git repo there, at `variant/<project-name>/`, shaped like a real project where the task would come up. Plant what an organic task would have: code, docs, and the other skills a user would have installed. When the project is copied from a real one, give each arm its own version of the skill in place of the one it shipped with. Leave out anything that already demonstrates the behavior under test, such as an existing file written the way the skill prescribes, because runs copy what they see and the baseline would pass without the skill. Plant it only when that situation is what you mean to measure.
   3. Install the variant the way a user would: the folder at `.agents/skills/<name>/` and a relative symlink to it at `.claude/skills/<name>`, so both claude and codex discover it. Commit with ordinary messages.
   4. For a baseline, build `baseline/<project-name>/` identically except for the skill.
3. **Check for contamination.** Salvo's `--hide-skill` keeps every user-level install of the skill under test out of the runs, so each run sees only its arm's copy, while the rest of the user's skills and settings stay in place. What remains is anything else every run reads that already asks for the behavior under test, such as a rule in the user's `CLAUDE.md` or `~/.codex/AGENTS.md`: it makes runs pass regardless of the skill. If you find one, say so, and drop the agent it affects or treat the result as confounded. A run can also still open a file by path; step 9 catches that from the transcripts.
4. **Write one organic prompt.** What a user of this project would type when the skill ought to matter. Make it exercise every case the skill's rules tell apart, such as both branches of a conditional rule, as long as the request stays natural, because a case no run meets is a case the eval never checked. Prefer a task where the skill should trigger on its own. For a skill that only runs when invoked by name, invocation differs per agent (`/name` in claude, `$name` in codex), so use one agent's syntax and run only that agent's models.
5. **Run the arms.** Choose the models by salvo's rules, reading `models.json` from the project the user is working in, not from your experiment repos, which have none. With fewer than two models, say in the report that one model's quirks decide the verdict. Use the same list in every arm, because a model difference between arms would read as a skill difference. From each arm's repo, run `python3 <salvo>/scripts/salvo.py run --clean-room --hide-skill <name> --out <experiment dir>/<arm>-runs <specs> <<'EOF' ... EOF` with the prompt. Pass `--hide-skill` even when the user has no global install, because it costs nothing and a stray one would override the arm's copy. Run the arms in parallel; in Claude Code, run them in the background and wait for the notifications. Send each command's output to a log file and do not read it before step 9, because salvo's summary names each run's model and duration per arm, which unblinds your grading.
6. **Blind the results.** Once every arm's `salvo.json` says `"status": "done"`, run `python3 scripts/blind.py --packet <experiment dir>/packet --key <experiment dir>/key.json --skill <name> variant=<variant out> [baseline=<baseline out>]`, repeating `--skill` (and salvo's `--hide-skill`) for skills that ship together. It refuses arms whose projects differ outside the skill's folders, because then the arms test more than the skill; fix the repos rather than working around it. It pools every successful run under a shuffled label with its result, changes, and a transcript stripped of model identifiers, and records failures in the key as dropouts. Do not open the key until step 9, so your own grading stays blind too.
7. **Start the judge.** Pick a model from the `planner` role that no run used; if there is none, use the first planner entry and note the overlap. From the packet directory, run salvo on that one model, without `--clean-room`, in the background, with this prompt:

   ```
   Each directory here (A, B, ...) is one attempt at this task:
   <the organic prompt>

   Grade every attempt against these criteria, each from 1 to 5, quoting evidence from its files:
   <criteria>

   Score all attempts in a single pass on one scale, from their outputs. Read an attempt's transcript.md only for a criterion its output cannot show, after scoring the rest. Reply with a table of scores per attempt and criterion, then a short note per attempt.
   ```

8. **Grade it yourself while the judge works.**
   1. Read every label's output end to end and score it on the same criteria. Do this before opening any transcript, because a transcript shows which version of the skill the run read and so unblinds its arm.
   2. Then read each transcript to verify the chain: which files the run actually opened (the skill's `SKILL.md`, the references it points to) and what it ran. Grade chain-following from this, not from what the run says it did.
   3. Finish both before reading the judge's verdict.
9. **Unblind and reconcile.**
   1. Open the key. A run that opened the other arm's version of the skill is contaminated; drop it from the analysis and say so.
   2. Check which variant runs opened the skill. A run that never did says nothing about the skill's instructions, only that it did not trigger for that model. Report those runs as a trigger result and base the verdict only on runs that loaded the skill; if none did, the verdict is a trigger failure, whatever the scores say.
   3. Compare your scores with the judge's, label by label.
   4. If you agree on whether the variant does what it promises (and beats the baseline, if there is one), go to step 10. That includes agreeing that it does not help: that is a result, so report it rather than rerunning.
   5. If you disagree, find out why from the evidence. When one side misread an output, settle it from the evidence and go to step 10.
   6. When the disagreement comes from the task or the criteria allowing both readings, the experiment was flawed. Fix the prompt or criteria and rerun from step 2, once. If the rerun still disagrees, report the disagreement instead of a verdict.
10. **Clean up.** Run `salvo.py clean` on every arm's run directory. That removes the workspaces; the packet and key stay in the experiment directory. Stop any background command or wait you started, so no late notification lands after your report and replaces it as your last message.

## Output

```
## Variant
<path> - <the behavior it should produce>. Baseline: <what it was, or why there was none>.

## Task
<the organic prompt>

## Criteria
1. <criterion>

## Runs
| Label | Arm | Model | Your scores | Judge scores | Notes |

## Judge
<model> - <its verdict in two or three lines>

## Synthesis
<where you and the judge agreed or differed and how it was resolved; chain evidence from transcripts; dropouts and contamination>

## Recommendation
<Promote | Revise: what to change | Reject> - <one-line reason>
```

End with the experiment directory path, where the packet and key stay, and flag any rerun, dropped model, or contaminated run.
