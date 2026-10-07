# ARCHITECT_DECISION_INDEX — generated index over canonical decisions (not a decision store)

> Generated 2026-10-07T04:08:01Z by ADR-610's generator from `docs/decisions/`. The class is declared per topic and OVERRIDDEN by the canon: a cited ADR that is superseded, not accepted, missing or ambiguous cannot stay CURRENT. Read the cited ADR in full before acting; this table is navigation.

## CURRENT

| Topic | Decision | Cited ADR (status · effective) | Note |
|---|---|---|---|
| three-world-model | Three worlds: CAPITAL / STUDIO OS / EARN DEFI PRODUCT | [ADR-592](../../docs/decisions/ADR-592-director-os-v2-mission-control.md) ACCEPTED · 2026-10-05<br>[ADR-580](../../docs/decisions/ADR-580-company-truth-contracts-rm-truth-01.md) ACCEPTED · 2026-10-05 | ADR-592 §6 information architecture; ADR-580 contracts C1–C12 per domain. |
| owner-boundary | The owner decides exactly three subjects: real money, public numbers/naming/legal, irreversible actions | [ADR-285](../../docs/decisions/ADR-285-owner-decision-boundary-by-subject.md) ACCEPTED · 2026-09-09 | Everything else the agent decides and records in the journal. |
| rm-truth-contracts | RM-TRUTH-01 contracts C1–C12 (one writer, typed numbers, scoped readiness, one owner queue, Problem store, DR coverage) | [ADR-580](../../docs/decisions/ADR-580-company-truth-contracts-rm-truth-01.md) ACCEPTED · 2026-10-05 | Frozen after independent review; map in docs/rm_truth/. |
| director-os-read-model | Director OS v2 = Mission Control; Company Truth computed on read — a read model, not an authority | [ADR-592](../../docs/decisions/ADR-592-director-os-v2-mission-control.md) ACCEPTED · 2026-10-05 | No agent or gate reads Company Truth (import ratchet). |
| mission-control-v1 | Owner Remote / Mission Control v1 — read-only, loopback :8790, phone via Cloudflare Access | [ADR-552](../../docs/decisions/ADR-552-owner-remote-mission-control-v1.md) ACCEPTED · 2026-10-03 | Evolved in place into Director OS v2 (ADR-592). |
| trading-lab-canonical | Trading Research Engine v0 is the ONLY active Trading Lab line | [ADR-590](../../docs/decisions/ADR-590-canonical-trading-research-lineage.md) ACCEPTED · 2026-10-05<br>[ADR-525](../../docs/decisions/ADR-525-capital-architecture-v1-and-trading-research-engine.md) ACCEPTED · 2026-09-30 | Research/paper only; forward clocks immutable. |
| oracle-cio | Oracle = Chief Investment Officer: advisory/paper cross-sleeve recommendation; executes nothing | [ADR-554](../../docs/decisions/ADR-554-investment-cio-capital-allocation-v1.md) ACCEPTED · 2026-10-04 | Display name Oracle since 2026-10-04 («Штирлиц» before). |
| sherlock-research | Sherlock = Head of Research: deterministic evidence and paper admission; no capital authority | [ADR-564](../../docs/decisions/ADR-564-research-evidence-and-paper-admission.md) ACCEPTED · 2026-10-04 | Curated facts count only after content-hash-bound review. |
| research-factory | Research Factory v1: capital universe by economic mechanism, RESEARCH → PAPER → CIO_ELIGIBLE | [ADR-560](../../docs/decisions/ADR-560-research-factory-capital-universe-expansion.md) ACCEPTED · 2026-10-04 | No candidate is live-authorized. |
| shadow-execution | Shadow execution; automated live execution PROHIBITED; a real-capital pilot is owner-gated | [ADR-556](../../docs/decisions/ADR-556-shadow-execution-and-pilot-readiness.md) ACCEPTED · 2026-10-04 | Unsigned intents, keyless quorum simulation. |
| three-paper-portfolios | Conservative / Balanced / Aggressive = three PAPER portfolios with different mechanics | [ADR-533](../../docs/decisions/ADR-533-three-defi-paper-portfolios.md) ACCEPTED · 2026-10-01<br>[ADR-548](../../docs/decisions/ADR-548-three-portfolios-owner-gate-applied.md) ACCEPTED · 2026-10-03 | docs/ROADMAP.md item 3 cites ADR-537 for the owner gate; the gate decision itself is ADR-548. |
| public-internal-naming | Public tiers Conservative/Balanced/Aggressive; Conservative = the evidenced book; naming is owner subject №2 | [ADR-593](../../docs/decisions/ADR-593-conservative-is-the-evidenced-book-backfill.md) ACCEPTED · 2026-07-11<br>[ADR-285](../../docs/decisions/ADR-285-owner-decision-boundary-by-subject.md) ACCEPTED · 2026-09-09 | Alt names Preserve/Core/Max Yield are «owner choice #6» (landing/src/lib/tier_bands.json); Core is ambiguous. |
| published-rate-rounds-down | The published yield rate rounds DOWN | [ADR-563](../../docs/decisions/ADR-563-published-rate-rounds-down.md) ACCEPTED · 2026-10-04 | Owner option 1, 2026-10-04. |
| single-roadmap-and-memory-v1 | Memory & Context Architecture v1; docs/ROADMAP.md is the single roadmap | [ADR-527](../../docs/decisions/ADR-527-memory-and-context-architecture-v1.md) ACCEPTED · 2026-10-01 | Five memory layers; chat is never canonical. |
| memory-hybrid | Memory = HYBRID_BORROW_COMPONENTS (stdlib FTS5 + two borrowed ideas) | [ADR-591](../../docs/decisions/ADR-591-memory-hybrid-borrow-components.md) ACCEPTED · 2026-10-05<br>[ADR-527](../../docs/decisions/ADR-527-memory-and-context-architecture-v1.md) ACCEPTED · 2026-10-01 | — |
| backup-offsite | DR: typed archive classes FULL / CRITICAL (never chosen by age across classes) + verified off-device copy to iCloud Drive | [ADR-580](../../docs/decisions/ADR-580-company-truth-contracts-rm-truth-01.md) ACCEPTED · 2026-10-05<br>[ADR-611](../../docs/decisions/ADR-611-backup-archive-classes.md) ACCEPTED · 2026-10-07 | C10 DR coverage; ADR-611 archive classes; commits 1c5445d3 (iCloud default) and fe0534b5 (CIO *.json.gz). Upload to Apple servers is NOT_MEASURED from the Mac. |
| telegram-capital-readonly | Telegram Capital surface /capital /btc /lab /oracle /sherlock — read-only, same readers as Mission Control; Director OS reasons in plain Russian | [ADR-612](../../docs/decisions/ADR-612-telegram-capital-surface-and-plain-owner-language.md) ACCEPTED · 2026-10-07<br>[ADR-521](../../docs/decisions/ADR-521-telegram-owner-control-plane.md) ACCEPTED · 2026-09-30 | Delivered 2026-10-07 (2b8887cb). nav-only buttons, no act: verb; free-text money orders refused before the classifier; REAL CAPITAL $0, no execution. |
| strict-promotion-guard | Guarded promotion only: push_to_github.py --expected-base <sha>, STOP on drift, no --allow-overwrite, no force | [ADR-610](../../docs/decisions/ADR-610-arb-continuity.md) ACCEPTED · 2026-10-07 | Owner decisions 2026-10-06 (no --allow-overwrite; fix the guard); review trail docs/rm_truth/REVIEW_PUSHER_FIX_*.md. |
| arb-continuity | ARB continuity: curated context + intent ledger + generated, freshness-checked CURRENT_STATE | [ADR-610](../../docs/decisions/ADR-610-arb-continuity.md) ACCEPTED · 2026-10-07 | Generated files are DERIVED (authority 0), never a second state store. |

## EXPERIMENTAL

| Topic | Decision | Cited ADR (status · effective) | Note |
|---|---|---|---|
| aggressive-simulated-loop | Aggressive = SIMULATED sUSDe/PYUSD loop (paper experiment, refused for live) | [ADR-533](../../docs/decisions/ADR-533-three-defi-paper-portfolios.md) ACCEPTED · 2026-10-01 | Evidence level L2 until a 30-period paper record exists. |

## SUPERSEDED

| Topic | Decision | Cited ADR (status · effective) | Note |
|---|---|---|---|
| director-os-v1-cockpits | Director OS :8788, Studio Shell :8778, repo dashboard :8767 as owner cockpits | [ADR-592](../../docs/decisions/ADR-592-director-os-v2-mission-control.md) ACCEPTED · 2026-10-05 | Presentation superseded by ADR-592; unloading their agents is an owner action. |
| older-btc-engines | research/btc_cycle and btc_nav (older SPA BTC systems) | [ADR-590](../../docs/decisions/ADR-590-canonical-trading-research-lineage.md) ACCEPTED · 2026-10-05 | SUPERSEDED_HISTORY; the earn-defi BTC Signal Engine is a SEPARATE_PRODUCT, not superseded. |
| openclaw | OpenClaw third-party AI gateway (Telegram + local model, shell access) (REMOVED_RETIRED) | [ADR-599](../../docs/decisions/ADR-599-openclaw-removed.md) ACCEPTED · 2026-10-07 | Removed by explicit owner decision 2026-10-07; no SPA component depended on it. |

## REJECTED

| Topic | Decision | Cited ADR (status · effective) | Note |
|---|---|---|---|
| mempalace-dependency | MemPalace as a runtime dependency | [ADR-591](../../docs/decisions/ADR-591-memory-hybrid-borrow-components.md) ACCEPTED · 2026-10-05<br>[ADR-527](../../docs/decisions/ADR-527-memory-and-context-architecture-v1.md) ACCEPTED · 2026-10-01 | Rejected on measurement (top-5 12/51 vs 31/51, 81 dependencies, stdlib invariant #4). |

