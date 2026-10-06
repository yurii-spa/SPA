# A4 — Studio OS reliability and readiness scope (RM-TRUTH-01, Phase 1, read-only)

Measured 2026-10-05 ~08:10–08:20Z. Code was read from `~/Documents/SPA_mirror` at b36acda46. Runtime was read from `~/Documents/SPA_Claude/data`, `~/Library/LaunchAgents`, `launchctl list`, `ps` and `/tmp/spa_*`. No writers or agents were run.

The only check executed was `agent_code_freshness.check_agent_code_freshness()`. It is read-only: it calls `launchctl list` and `ps` and writes nothing.

Every claim is labelled with one of three outcomes: **measured**, **measured = 0**, or **NOT MEASURED**. Register: `A4_register.json` (31 components, 12 fleet defects, 5 readiness scopes).

## 1. Fleet re-measured now

| Count | Value | Source |
|---|---|---|
| `com.spa.*` files in ~/Library/LaunchAgents | 97 = **92 `.plist`** + 5 `*.plist.disabled` | `ls` |
| Loaded in launchctl | **91** (the brief's "97" counted files, not loaded agents) | `launchctl list` |
| `.plist` installed but not loaded | 1: `com.spa.mission_tick` | comm diff |
| Loaded with no plist | 0 (measured = 0) | comm diff |
| agent_health `total_agents` | 89. It is 91 loaded minus `digest_weekly`, `tier1_digest` and `weekly_backup` (all in RETIRED_LABELS), plus `mission_tick` | label diff |
| self_heal "expected" | 88 | `data/self_heal_status.json` |
| Installer-declared | 83 | `data/fleet_parity.json` |
| Repo plists | 102 | `data/fleet_parity.json` |
| Manifest | 107: 92 active / 13 retired / 2 designed | `architecture/manifest.json` |
| Registry | 99 known | `data/agent_registry.json` |

So seven numbers for "the fleet" (83 / 88 / 89 / 91 / 92 / 99 / 107), and no two of them come from the same definition.

### WARN and CRIT agents (agent_health @07:36Z: 84 OK / 4 WARN / 1 CRIT)

| Agent | Status | Root cause (measured) | How long it has persisted, and why |
|---|---|---|---|
| novel_edge_rnd | CRIT, log 3.2 d | **False positive.** The plist's `StartCalendarInterval` is an *array* (Tue + Fri 04:00). `classify_agent` (agent_health_monitor.py:509-522) handles only a dict, so the agent falls through to `CAT_DAILY`, and 2×26 h ≈ 2.2 d makes it CRIT. The last run was a clean exit 0 at 2026-10-02 05:56. | It recurs every Fri→Tue gap. The plist dates from 09-02. Push_policy is edge-triggered, so each recurrence sends one "critical" and one "recovered" message: alert_history has 14 + 14 such messages between 08-25 and 10-04. The timing fits Sun/Tue and Fri cycles, but I could not attribute individual alerts to this agent because the previews are truncated (NOT MEASURED). The same bug class was already fixed for monthly agents (L161-167). |
| site_freshness | WARN, exit 1 | `PUBLISHER_STUCK` (CRITICAL inside the report). The site shows as-of 2026-10-01 (101 h old) while the shelf is at 10-04, and the site has 100 evidenced days against 103. | 22 of 22 runs since the log began (09-29 22:56Z) exited 1, and each one sent an alert (latest message_id 10602). The fix is outside the repo: the Cloudflare Pages build. No card names PUBLISHER_STUCK (grep). |
| swarm_health | WARN, exit 1 | guardian_forward reports "unknown guardian states" for 9 books, and chaos_drill's control check returned WARNING where OK was expected. | 130 of 130 runs since 09-29. This is the advisory layer, the warning has become normal, and no card exists. |
| orchestrator | WARN, exit 124 | A 4 h timeout. The timeout evidence shows the full prescribed pytest (pid 99207, age 11954 s) running inside the LLM cycle. | 2 of the 17 cycles in the current log (10-04 21:12, 10-05 09:15). There is no follow-up. |
| resource_guard | WARN, exit 1 (now 0) | A genuine signal: swap at 87.1% from concurrent pytest load; disk has 75.6 GB free. | 65 of 478 runs since 10-03. Transient. |
| **weekly_backup** (not monitored) | exit 1 | The backup failed on 10-03 (tar exit 1). The archives from 09-26 (1.66 GB) and 10-03 (2.64 GB) are much smaller than the earlier 3.0–3.9 GB ones, so they are probably truncated (not verified). | agent_health and self_heal treat it as RETIRED, but it is still loaded, and the manifest says active. Two owner cards (zombie 08-08, dead 09-02) were both "ingested" and nobody unloaded the agent. **It is invisible to every monitor.** |
| mission_tick | not loaded | Its plist runs `~/studio-os-scratch/v03/...`, which is outside the repo. | architecture_conformance has flagged it B1 CRITICAL since 09-30 22:56Z. It went to the owner as a decision card; the owner acked on 10-01, and it is still dead. |

**Long-lived processes** (re-measured with LC_ALL=C):
- `rtmr_sense` is running code **3.7 days stale**. It started 09-29 22:56Z; the newest tree file is `telegram/push_policy.py` from 10-03.
- `apiserver` is 0.9 days stale, below the voice threshold.
- The rest are fresh.
- Under the ru_RU locale, 6 of 9 come back UNCHECKED because the `ps lstart` output is localized. That is an honest third outcome, but it is fragile.
- Restarting is the owner's action (deployment.md p.6), and I found no card for it.

**Parity** (`fleet_parity.json` @06:01Z): DRIFT.
- 8 orphan plists, all from ADR-551..560 agents shipped without an installer declaration.
- 5 retired-but-installed.
- director_build and director_server are running but not declared.
- A duplicate `novel_edge_rnd.plist.disabled` sits next to the live plist.

**Other defects:**
- `/tmp/spa_decision_loop.log` is **4.0 GB** of test-fixture output.
- system_health has said WARNING on all 30 of its last 30 runs. It still checks the retired `dfb_capture` (862 h stale), and `d3.cycle.ran_today` races the 08:00 cycle.

## 2. Self-heal / incident / problem loop

| Step | Exists? | Evidence |
|---|---|---|
| ERROR | yes | agent_health, system_health, cycle_health, telegram_health, watchdog |
| INCIDENT | partial | Only the edge-triggered state in `data/telegram/push_state.json`. `agents/incident_commander.py` (timeline + post-mortem) **is not run** (cycle_runner.py:1433). |
| RESTORE | yes | self_heal (bootstrap / kickstart, breaker 5/h/label), telegram_health (50 bot restarts 08-12..09-30) |
| RECURRENCE | partial | The revival counter (breaker only), and findings_bridge recurrences, which cover architecture findings only (loop_health: 9 total) |
| PROBLEM | **no** | reliability.py's PROBLEM_CANDIDATE is derived and never persisted |
| RCA | **no** | reliability.py explicitly has no root-cause field (L200-208) |
| FIX → REGRESSION TEST | partial | Cards come from alert_actions buttons or findings_bridge. card_acceptance `no_regression_tests_pass` exists, but there is no incident↔card link. |
| MONITOR / KNOWLEDGE / CLOSED | partial | Bridge auto-close covers findings only (50 of 69). The build_loop (ADR-551) MEMORY stage covers cards, not incidents. |

**Verdict: alert-only for ops failures.**

**findings_bridge** is the only machine that turns a recurring condition into exactly one record with a closing criterion. But it reads only architecture_conformance, house_view_gap, loop_retro and tier_curator. **Nothing from agent_health, system_health, self_heal or site_freshness ever becomes a card.** And the agent-health findings it *does* see (B1 CRITICAL) go **to the owner** as owner-decision cards, even though fleet health is not one of the three owner subjects in ADR-285.

**Owner spam, measured.** alert_history.json holds 500 entries (the ring buffer is full) covering 08-24..10-05, at 4–31 messages a day:
- 14 CRIT / 14 recovered flaps
- 12 "Критичная находка петли" ("critical loop finding") owner-decision messages plus 7 "вопрос снят" ("question withdrawn")
- 7 "Self-Heal ❌ bootstrap failed" messages at 5-minute intervals on 09-29

`data/alert_log.json` is a dead predecessor; its last write was 08-24.

**Duplicate health systems** (19, each with its own artifact). Of these, **5 issue a fleet-level verdict** — agent_health, system_health, self_heal, mission_control and reliability — and they disagree right now:
- agent_health: CRITICAL
- system_health: WARNING
- self_heal: healthy=true
- mission_control: CRITICAL overall, with HEALTHY sections

`architecture/health_contracts.json` (11 contracts) is read only by the director scripts.

## 3. Readiness scope bug

- **No 29/29 check carries `ready_for_live`.** golive_status.json has `ready=true`, `go_live_state=gate_passed_owner_decision_pending` and no `ready_for_live` field. The 29 checks cover paper-track data (6), the inventory of imports, existence and keys (~13), track continuity, ops (autopush, telegram today), investment metrics, policy snapshot and evidence. **Site and custody are not covered.**
- **The real verdict says false.** `data/execution_readiness.json` has `ready_for_live:false`, with blockers custody/MPC, external audit and SPA_EXECUTION_MODE (05:15Z). `owner_blockers.json` has open_count 3 (custody, audit, legal). capital_shadow shows every sleeve BLOCKED or NOT_READY.
- **`update_system_briefing.py`** (L216-243, L1144-1150) reads only `golive_status.ready/passed/total`, so it prints "READY — eligible for go-live review". That is ADR-OWN-2026-07-readiness-truth applied to the wrong scope, and ADR-530 already says "29/29 overstates".
- "Track integrity 17/88" comes from `cycle_health.json → evidence_vs_curve`: paper_evidence ≠ equity curve on 17 dates. The GoLive evidence checks still pass on that same data.
- **Corrupted owner-control artifact.** `data/owner_decision_pending.json` has `generated_at = 2041-11-23T19:53:29Z` (mtime 08:04Z, outside agent_health's :36 cadence). That is exactly `artifact_stamp_clock_doors.ANCHOR` (L116, the G97/ADR-562 probe committed 10-05 00:02), so a sandboxed measurement probably leaked a write into prod data/. The leak path is NOT MEASURED.

### Proposed scoped statuses (reuse existing artifacts)

| Scope | Canonical source | Status now | Freshness | Blocking effect |
|---|---|---|---|---|
| INVESTMENT_ENGINE_READINESS | `execution_readiness.json` ∧ `owner_blockers.json`; golive_status is the evidence sub-input; capital_shadow ledger gives per-sleeve status | **NOT_READY** (3 + 3 blockers) | daily 07:15 / 6 h | gates the live cutover; replaces "GoLive READY" |
| STUDIO_OS_HEALTH | `agent_health.json` (+ fleet_parity, self_heal as sub-inputs) | CRITICAL (1 false positive, 0 true critical) | hourly, stale after 90 min | none on money; never mixed into readiness |
| PRODUCT_DATA_HEALTH | `cycle_health.json` (evidence_vs_curve, artifact_integrity) | WARNING 17/88 | 300 s | should gate golive evidence checks |
| PUBLICATION_HEALTH | `site_freshness_report.json` | CRITICAL, PUBLISHER_STUCK | 6 h | public numbers 3 publications behind |
| OWNER_CONTROL_HEALTH | `telegram_bot_capabilities.json` + `owner_decision_pending.json` + `telegram/push_state.json` | DEGRADED / untrusted (2041 stamp; 2 cards only on origin; 1 has no buttons) | 30 s / hourly | owner decisions stall |

Each scope carries the fields scope, status, as_of, source, freshness and blocking_effect; the full set is in A4_register.json → readiness_scopes.

## 4. Recommended Phase-2 actions (not executed)

1. Fix `classify_agent` so an array calendar is classified as weekly. Add a positive control test for it.
2. Feed agent_health and system_health findings into findings_bridge as **agent** inbox cards, not owner-decision cards, keyed per agent and cause. This gives one Problem per recurring cause.
3. Unify the fleet sources (manifest → installer → RETIRED_LABELS). Unload or retire weekly_backup, digest_weekly and tier1_digest as the owner already decided, and remove the stale `.disabled` duplicate.
4. Make the briefing GoLive line read `ready_for_live` and show "29/29 inventory" next to it.
5. Find and fix the probe leak that wrote the 2041 stamp into live data/.
6. Turn PUBLISHER_STUCK into a single card instead of a message every 6 h.
7. Get the owner to restart rtmr_sense.
