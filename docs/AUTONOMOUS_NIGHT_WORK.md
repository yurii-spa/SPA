# Autonomous Night Work — durable, high-throughput charter

> Written 2026-07-09 after an overnight run delivered only ~3 items in 6h. Root cause: a single
> `ScheduleWakeup` fired once and the loop **died** (never re-armed) → ~6h dormant. This charter makes
> the loop unkillable and the throughput high. Follow it whenever the owner says "work the backlog
> overnight / while I sleep / take control until <time>".

## 1. The loop MUST be self-sustaining (never dies)

**Preferred: a recurring `CronCreate`.** Create a recurring cron (every 10–15 min) whose prompt is the
autonomous sentinel `<<autonomous-loop>>` (or an explicit backlog-work prompt). The harness fires it on
schedule **independently of whether the previous run re-armed** — so a crashed/ended run cannot kill the
loop. This is structurally unkillable. Cancel with `CronDelete` in the morning (recurring crons also
auto-expire after 7 days).

**If using `ScheduleWakeup` instead: re-arm FIRST.** The very first action of every wake is to schedule
the next wakeup — BEFORE doing any work. Then if the work chunk errors or the turn ends early, the next
wake is already booked. Never leave re-arming to the end (that is exactly what failed on 2026-07-08).

**Interval:** 10–15 min between firings (not 20+). Each firing does a BIG batch (below), so the gap is
small relative to work done.

## 2. Throughput: many items per firing, not one

Each firing works **continuously in one long turn** — pick items off the priority queue and do them
back-to-back (many tool calls), only ending the turn when the batch is done or context is full. Do NOT
do one item then sleep. Sleep is only the gap between firings, not between items. Target: several items
per firing, 10–20+ items per night — not 3.

## 3. Verification scaled to risk (this is where time was wasted)

Match the check to the blast radius. Do NOT run the full suite + build + changelog after every trivial edit.

| Change type | Per-change verification | Notes |
|---|---|---|
| **Money-path / RiskPolicy / kill-switch / execution / methodology / schema / security / auth** | **HEAVY, immediately**: full test suite + tsc + build + an adversarial/red-team read before commit. Version bump + changelog. | Never batch these. A wrong money/risk change must fail loudly at once. |
| **New analyzer signal / scoring / data source** | **MEDIUM**: targeted unit tests for the new module + tsc, then include in the end-of-batch full run. | |
| **Copy / UI / CSS / docs / scaffold / coming-soon** | **LIGHT**: a compile/build check only. | |
| **End of each firing (batch gate)** | Run the FULL test suite + `npm run build` (exit 0) ONCE over the whole batch, THEN one consolidated commit/push (or a few grouped commits). | The single expensive check amortised over many small edits. |

If the end-of-batch full run fails, bisect the batch — do not push red.

## 4. Invariants (always, every firing)

- NO fabrication — honest "coming soon" / "not covered" where data is missing (the whole brand).
- Tests + build green before any push; `npm run build` exit 0 before site/checkup pushes.
- Deterministic, stdlib-only in SPA runtime; LLM forbidden in risk/exec/monitoring.
- Secrets from Keychain, never in files. Atomic writes.
- Push: SPA → `push_to_github_batch.py` to origin/main; DeFi Checkup → `git push` PAT-URL to
  `yurii-spa/defi-checkup master` (repo has NO git identity → commit with
  `git -c user.name="Yurii SPA" -c user.email="yuriycooleshov@gmail.com"`; `rm -f .git/index.lock`
  before commit; never a `.git/*.lock` glob — zsh aborts the line).
- Verify a deploy by real content (a marker string) + CI conclusion, never curl HTTP status.
- A CF prebuild that exits non-zero silently blocks the WHOLE site — keep gates warn-only.

## 5. Morning report

At the stop time, produce a consolidated report: items shipped (commit shas + live status), tests green,
what's still open, and an HONEST throughput note (no inflation).
