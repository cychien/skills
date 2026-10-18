---
name: benchmark-checklist
description: "Vet a performance measurement (limiter, tuning, physical limits, errors, repeatability, relevance, and whether the work happened) before you report or act on it. Use for /benchmark-checklist, when you run a benchmark, or when you report or receive a speedup or regression."
disable-model-invocation: true
---

# Benchmark checklist

Use this whenever you produce or act on a performance number: a PR's before and after, a regression claim, a benchmark harness, or a choice between libraries or configs. Answer each step's question with evidence from a run, not a guess about the code. This is the working form of the Explain the Number principle (`../principles/references/principles/explain-the-number.md`).

For a quick ballpark the user asked for, one run is enough. Still check questions 4 and 7, and say it is one run. Skip the rest unless that run looks wrong. A choice between options is never a ballpark.

## Before you run anything

- Write down the claim you expect to make, in the words you would ship ("export is 30% faster at p50 on the 60k-row dataset"). The questions test that sentence.
- Read the measurement script. Note what it times, counts, and ignores.
- Check the load with `uptime` and the core count with `sysctl -n hw.ncpu` on macOS or `nproc` on Linux. If the machine is busy, find out what runs. If you cannot stop it, interleave the sides so both see the same noise, and say so in the report.

## Where to measure

Production is the most accurate place to measure, because its data volume and distribution, indexes, caches, and hardware are what users actually wait on, and a local fixture only approximates them. When a read-only connection to production is available, measure there.

- Use only a connection the user provided for this purpose, such as a read replica or a role that can only read. Never search for, borrow, or escalate credentials.
- Confirm it is read-only before the first probe by reading its grants and session settings, not by attempting a write, and open every session in read-only mode (for Postgres, `default_transaction_read_only = on`).
- Swap only the data source. Keep every other integration (mail, payments, queues, third-party APIs) local or sandboxed, so nothing the app does reaches a real user.
- Probe only reads. A path that must write to work gets measured on a production-sized copy or snapshot, never against production.
- Protect production: one probe at a time, a statement timeout on every session, no load tests or concurrency sweeps, and stop at the first sign of strain such as rising replica lag, errors, or timeouts.
- Compare like with like. Production runs main's code, so run main and head locally, both pointed at the same production data source, interleaved. A production number for main against a local number for head is a ratio between unlike scenarios.
- Keep production data out of the evidence: numbers, query plans, and counts, never rows or personal data.
- Without such a connection, use the most production-like source available, such as a staging copy at production volume or a dataset seeded at the plan's stated size.

Name the data source in the report, because it decides how far the number transfers to production.

## Steps

1. **Why not double?** Name the limiter. Profile in a run you do not report, because profilers and tracers slow the work down. Use CPU per process (`top`), a runtime profiler (`node --cpu-prof`, `py-spy`, `perf` on Linux, `sample` or Instruments on macOS), I/O wait, and syscall counts (`strace -c` on Linux, `dtruss -c` on macOS), then map the hot spot to source. Watch the load generator too: if it saturates first, you measured the load generator. If a change did not move the number, the limiter explains why, so find it before you call the change useless.
2. **Was it tuned?** Run every side the way production runs it: release builds, production flags and env, batching and transaction settings, connection pools, caches as warm or cold as production sees them, and the same versions and data. If one side runs on defaults, you compared configurations, not implementations. A limiter that is a setting (a commit per row, a debug build, a missing index) means that side is untuned. Tune it and measure again before you pick a winner. When the user is choosing what to adopt, narrowing the claim to the code as it ships today does not fix this, because they adopt the option, not today's settings.
3. **Did it break limits?** Do the arithmetic. Compare bytes per second with disk and network bandwidth, operations per second times cost per operation with your cores, and the time saved with the time the changed piece took. Removing a piece that takes 10% of the run makes the run at most about 11% faster. A result past a limit measured something other than the work: a cache, a no-op, or a bug.
4. **Did it error?** Count failures and non-success responses, and check that outputs are correct, not just present. Rejections are often fast, and timeouts and retries are slow. If the script does not count errors, add the count.
5. **Does it reproduce?** Run each side at least 5 times, alternating (A, B, A, B, and so on) so warmup, lazy initialization, caches, and drift favor neither. Report the median and range. A gap smaller than the run-to-run variation is no measurable difference. When the call is close, use a rank-sum test or the harness's own statistics.
6. **Does it matter?** Next to any micro result, measure the end-to-end path a user waits on, with realistic data sizes and concurrency, and report the micro result as a share of the whole. A helper that takes 1% of a request can make the request at most 1% faster, however fast the helper gets.
7. **Did it even happen?** Confirm the work ran inside the timed region: the request reached the server, the rows were written, the bytes were read, and the code used the result. Lazy code (generators nobody iterates, promises nobody awaits, results the JIT can discard) and timeouts produce numbers for work that never happened.

## Output

- Lead with the verdict: faster, slower, no measurable difference, or inconclusive.
- Give the number with its unit, the run count, the range, the limiter, and the data source, such as "p50 41 ms → 33 ms, median of 7 runs per side, range 32 to 35 ms after, bound by JSON parsing on one core."
- Call the verdict inconclusive when you claim a difference but cannot name the limiter, when a side ran untuned, or when you could not check questions 4 and 7. Name the gap.
- A PR body carries one primary number, per the **open-pr** skill (`../open-pr/SKILL.md`). Put the runs, range, and limiter evidence in a linked artifact.
