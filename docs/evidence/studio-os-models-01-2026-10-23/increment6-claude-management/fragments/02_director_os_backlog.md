# Excerpt: docs/ROADMAP.md lines 270–307 — Director OS backlog (at aaec91755, unchanged)

## Director OS backlog — the 34 items of 2026-10-15, reconciled 2026-10-16 (ADR-763)

Source: `ROADMAP_ITEMS_FOR_ARCHITECT_2026-10-15.md` (15.10 handover attachment, outside the repo). This section is
part of THIS roadmap, not a second one; it adds no cards. Owner = who decides; «agent» = Claude Code executor;
acceptance is a machine check where one exists. Priority В/С/Н as in the source. Note: the source's item 1 and 4
cite «п. 31 (история трека)» — it means item 32; item 31 is VoiceOver.

**Done (no new work):** 10 = duplicate of 29 (one methodology, `track_period_view`, released `0dc759eb2`) · 28 Wave 2
published `0dc759eb2` (remaining residue moved to item 15 debt) · 29 one methodology done (Oracle's own method stays
separate and labelled; aligning it is an optional owner decision, Н).

**Duplicates (tracked under their twin):** 22 → 2 · 14 → 30 · 10 → 29.

| # | Item | Status | Depends on | Owner | Acceptance | Next step |
|---|---|---|---|---|---|---|
| 23 | Voice intake, first real iPhone send | published, not owner-verified | — | owner (test) / agent | one card per send, visible status in the cockpit | STUDIO-OS-NEXT-01 package 4: phone script |
| 24 | Who processes `cockpit-voice` cards, feedback | not built | 23 | agent | card leaves `new` with a reason; owner sees the outcome | package 4 |
| 25 | Long/English voice, retry when Mac busy | not built | 24 | agent | retry keeps the text; no duplicate card | package 4 (re-send/failure only) |
| 30 / 14 | ADR-762 version-bound answer; answer from cockpit | proposed | owner decision | owner (mechanism) / agent (candidate) | candidate: CAS under one lock, replay-safe, journal + recovery, kill-switch for writes | package 5 candidate, not wired live |
| 16 | «Проверить ещё раз» (read-only) then «Исправить» | not decided | ADR-760 pattern | owner per action | one ADR per action; read-only first | package 5 after ADR-762 candidate |
| 32 | Package value history by day | no data in canon | — | agent | `capital.package_values` series with measured_at, read-only from `data/defi_engine/` | package 5 |
| 1 | Week balance tile | no data | 32 | agent | tile = value − value 7 d ago with both dates | after 32 |
| 4 | Combined annual figure | too early (owner: wait until all packages have 30 days) | 32, ~2026-11-01 | owner | rule in `owner_view` | after 32 + 30 days |
| 11 | Package costs measured, not modelled | no data | — | agent | journal of simulated actual costs | package 5 «financial evidence» |
| 17 | Health tile beyond 5 groups; plain warning reasons | not built | — | agent | every warning has a plain reason + source | package 5 «plain reasons» |
| 5 | Infrastructure plan (Mac resources, costs) | partial | package 2 | agent | RAM / swap / disk / top consumers with times | package 2 feeds it |
| 27 | Restart long-lived agents after delivery | partial (named, not restarted) | — | owner (restarts) | procedure with owner confirmation | later |
| 15 | Off-subject owner questions in the queue | queue defect (ADR-285) | — | agent | `needs-owner` holds only the three subjects | later |
| 20 | Agents section (read-only) | not built, data exists | — | agent | section over `agent_health` | later |
| 19 | Throughput («Мощность») | no data | — | agent | cycles/cards/closures per day from the journal | later |
| 12 / 13 | Strategy readiness stages; Trading screen | not built | ADR for criteria | owner (criteria) / agent | readiness criterion ADR; screen | later |
| 6 | Live «what is happening now» lines | no data | — | agent | last action per agent with time | later |
| 3 | Claude load tile | no data, «100 %» undefined | — | owner (definition) | source + definition | later |
| 2 | Product progress tile | no data | machine status per roadmap item | agent | each item has a probe | later |
| 9 | Real money | owner subject №1 | GoLive, legal | owner | — | not in scope |
| 26 | Cockpit without the Mac | not decided | — | owner | — | later |
| 7, 8, 18, 21, 31, 33, 34 | Search · notifications in cockpit · incident history · repositories · VoiceOver · policies · company memory section | low priority (Н) | — | owner (8, 31, 33) / agent | — | later |

