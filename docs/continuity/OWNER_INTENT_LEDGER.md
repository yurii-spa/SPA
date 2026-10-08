# OWNER_INTENT_LEDGER — why things exist, across implementation changes

> **Kind:** CURATED (ADR-610). Each entry preserves the owner's INTENT and its lineage; implementations
> may be replaced, intent may not be rewritten to fit them. Quotes are copied from the cited canonical
> file; where no canonical file records the owner's words, the field says **UNKNOWN** — it is not
> reconstructed from memory or chat. This ledger is **not a task store** (tasks: `nimbalyst-local/tracker/`)
> and **not a state store**: live status of every intent is computed in `CURRENT_STATE.md` («Intents»),
> from the decisions listed in `relevant_decisions`. Machine format: one `## <intent_id> · <title>`
> section per intent, fields as `- **field:** value`; the generator refuses a duplicate id or a missing field.

## INT-01 · Director OS — one owner cockpit
- **owner_intent:** one read-only owner cockpit for the whole company, readable in plain Russian from an iPhone, instead of several dashboards that disagree.
- **why_it_matters:** the owner must see what works, what does not and what needs his decision without reading code; several cockpits had drifted apart (ADR-592 «Supersedes (presentation only)»: Director OS `:8788`, Studio Shell `:8778`, dashboard `:8767`).
- **first_known_evidence:** docs/decisions/ADR-492-studio-os-hybrid-shell-cockpit.md (Studio OS hybrid shell cockpit); ADR-552 lists «ADR-469 / ADR-492 / ADR-493 (Director OS …)», but `docs/decisions/ADR-469-*` is an unrelated census ADR — that citation is a number collision, so the earliest Director OS decision file is UNKNOWN.
- **current_implementation:** Mission Control evolved in place = Director OS v2 (`spa_core/studio_os/mission_control.py` + Company Truth computed on read); desktop `127.0.0.1:8790`, phone `https://mc.earn-defi.com` behind Cloudflare Access.
- **current_status:** DELIVERED (ADR-592, 2026-10-06); owner iPhone acceptance through Cloudflare Access NOT YET done by the owner.
- **known_gaps:** owner-facing reasons are plain Russian since 2026-10-07 (ADR-612; technical evidence behind «Технические подробности»), owner card titles are still as written; retired cockpits' LaunchAgents unloading is an owner action (ADR-592).
- **relevant_decisions:** ADR-552, ADR-592, ADR-580, ADR-612
- **superseded_implementations:** Director OS web cockpit `:8788`; Studio Shell `:8778` (ADR-492); repo dashboard `:8767` — presentation superseded by ADR-592.
- **last_verified:** 2026-10-07

## INT-02 · Company Truth — the system knows what it is
- **owner_intent:** RM-TRUTH-01 «система должна знать, что она такое» — one reconciled truth of the company that every surface reads, with UNKNOWN shown honestly.
- **why_it_matters:** numbers on owner surfaces disagreed (APY inversion, «READY 29/29» read as readiness, sandbox writing into production data — ADR-580 «Контекст»).
- **first_known_evidence:** docs/decisions/ADR-580-company-truth-contracts-rm-truth-01.md (owner macro-epic RM-TRUTH-01, 2026-10-05); docs/ROADMAP.md item 10.
- **current_implementation:** `spa_core/studio_os/company_truth.py`, computed on read inside Mission Control only (import ratchet `spa_core/tests/test_company_truth_import_ratchet.py`); contracts C1–C12.
- **current_status:** DELIVERED (Wave 1 `96a935fd`, Wave 2 `688f2c4b`, closeout `e9b73dda`).
- **known_gaps:** see CURRENT_STATE «Technical debt».
- **relevant_decisions:** ADR-580, ADR-592
- **superseded_implementations:** none recorded.
- **last_verified:** 2026-10-07

## INT-03 · Trading Lab — a real directional research engine
- **owner_intent:** owner directive «CAPITAL ARCHITECTURE v1 + TRADING RESEARCH ENGINE v0» (2026-09-30): SPA needs a directional price-trading research engine with honest out-of-sample and forward evidence.
- **why_it_matters:** the audit found «SPA had **no directional price-trading engine**» (ADR-525 «Context»); the only BTC engine (earn-defi) had a single family, daily data, no OOS/walk-forward.
- **first_known_evidence:** docs/decisions/ADR-525-capital-architecture-v1-and-trading-research-engine.md
- **current_implementation:** `spa_core/trading_research/` (agent `com.spa.trading_research`), canonical Trading Lab line per ADR-590; read model `spa_core.trading_research.read_model.trading_lab_view`.
- **current_status:** RUNNING (research/paper only); live state in CURRENT_STATE «Trading Lab».
- **known_gaps:** ROBUST needs ≥30 forward days and ≥5 forward trades (`docs/TRADING_RESEARCH_ENGINE.md`); champions appear only after that.
- **relevant_decisions:** ADR-525, ADR-590
- **superseded_implementations:** `research/btc_cycle`, `btc_nav` = SUPERSEDED_HISTORY (ADR-590); earn-defi BTC Signal Engine = SEPARATE_PRODUCT, not superseded (ADR-590).
- **last_verified:** 2026-10-07

## INT-04 · Broad indicator research
- **owner_intent:** UNKNOWN in the owner's own recorded words; the canonical implementation of the intent is the broad candidate universe of ADR-525 §2 (many public-domain indicator families researched in parallel instead of one family).
- **why_it_matters:** a single family (earn-defi MVRV) gives no comparison and no out-of-sample discipline (ADR-525 «Context»).
- **first_known_evidence:** docs/TRADING_RESEARCH_ENGINE.md («v0 universe: **138 candidates** — 10 public-domain families …»).
- **current_implementation:** `strategies.registry()` grids in `spa_core/trading_research/`; adding a candidate is a grid line.
- **current_status:** RUNNING; candidate and forward counts in CURRENT_STATE «Trading Lab».
- **known_gaps:** families beyond v0 are not decided; traditional markets / options are «Later engines» in docs/ROADMAP.md.
- **relevant_decisions:** ADR-525, ADR-590
- **superseded_implementations:** none recorded.
- **last_verified:** 2026-10-07

## INT-05 · Forward-paper time is a scarce resource
- **owner_intent:** research and paper engines keep running across epics and their evidence is never reset (docs/ROADMAP.md «Standing constraints»: «Research and paper engines (Trading Research Engine) keep running across epics; their evidence is never reset.»).
- **why_it_matters:** a forward bar that closed cannot be observed again; lost or rewritten forward time cannot be bought back.
- **first_known_evidence:** docs/ROADMAP.md «Standing constraints»; docs/decisions/ADR-580-company-truth-contracts-rm-truth-01.md C7 («Forward-часы неизменны»).
- **current_implementation:** append-only hash-chained `evidence.db`; refusal to reopen `forward_start` or backfill (ADR-590 C7); daily DR archive carries the evidence ledgers (ADR-580 C10, `scripts/daily_backup.py`).
- **current_status:** ENFORCED in code (ADR-590).
- **known_gaps:** off-device upload to Apple servers is NOT_MEASURED from the Mac (see backup architecture).
- **relevant_decisions:** ADR-580, ADR-590
- **superseded_implementations:** none recorded.
- **last_verified:** 2026-10-07

## INT-06 · DeFi product strategies — three paper portfolios
- **owner_intent:** «Conservative, Balanced and Aggressive are three separate PAPER portfolios. They must: differ by investment MECHANIC, not only by protocol tier; each carry its own version, accounting, limits and observable state; be shown truthfully on the site and in the Director; keep their history and the explanation of every decision.» (ADR-533 «Owner requirement»).
- **why_it_matters:** a three-tier product is only honest if the tiers are different strategies with separate evidence.
- **first_known_evidence:** docs/decisions/ADR-533-three-defi-paper-portfolios.md
- **current_implementation:** Conservative = main cycle_runner lending book under RiskPolicy v1.0; Balanced = fixed-rate PT to maturity; Aggressive = SIMULATED sUSDe/PYUSD loop (ADR-533); owner gate applied (ADR-548).
- **current_status:** RUNNING on paper; Balanced/Aggressive accumulating history (reportable after 30 periods) — see CURRENT_STATE «DeFi paper».
- **known_gaps:** money-path bindings (tier labels, Conservative 3 % budget wording, RTMR coverage) wait for the owner (ADR-532/533, docs/ROADMAP.md item 3).
- **relevant_decisions:** ADR-533, ADR-548, ADR-593
- **superseded_implementations:** sleeve-econ-v1 accounting (39 rows, DISTORTED, kept for audit — ADR-531).
- **last_verified:** 2026-10-07

## INT-07 · Public product semantics — numbers the visitor can trust
- **owner_intent:** «все цифры на сайте должны браться консолидированно с одного и того же места» (owner idea 2026-09-10, `.claude/rules/site-numbers.md`); every user-visible percentage has exactly two decimals, ROUND_HALF_UP, locale-aware «4,89 %» / «4.89%» (ADR-660, owner 2026-10-08 — supersedes the presentation-only round-down of ADR-563, owner option 1, 2026-10-04); Conservative is the evidenced book (ADR-593, owner 2026-07-11); public numbers, tier naming and legal wording are owner subject №2 (ADR-285).
- **why_it_matters:** a public yield number is a promise to a visitor; overstatement violates invariant #8.
- **first_known_evidence:** docs/decisions/ADR-593-conservative-is-the-evidenced-book-backfill.md (decision 2026-07-11); `.claude/rules/site-numbers.md`.
- **current_implementation:** one shelf `landing/src/data/site_numbers.json` built from two sources (track snapshot, constitution); typed metrics (ADR-580 C2); weekly publication cadence (ADR-357 п. 5).
- **current_status:** publication candidate `rmtruth/pubtruth` waits for the owner (Owner Gate).
- **known_gaps:** public alt names Preserve / Core / Max Yield vs primary Conservative / Balanced / Aggressive: primary chosen 2026-07-11, alt set is «owner choice #6» (`landing/src/lib/tier_bands.json` `_note`); Core is ambiguous (`architecture/memory_aliases.json`).
- **relevant_decisions:** ADR-660, ADR-563, ADR-593, ADR-285, ADR-580
- **superseded_implementations:** hand-printed rates on pages (16 literals of «~3,3 %», `.claude/rules/site-numbers.md`); one-decimal round-down `floorTo` presentation (ADR-563, superseded by ADR-660 2026-10-08; site switch waits for the owner publication gate).
- **last_verified:** 2026-10-07

## INT-08 · Telegram Owner Control
- **owner_intent:** the owner asked for the two Telegram bots «to be mapped from evidence and given distinct responsibilities» (ADR-521 «Context»): Bridge bot = Studio OS owner control plane, SPA bot = product surface.
- **why_it_matters:** the owner works from the phone; a bot must never be a path to money or to silently overwrite a manual safety latch (ADR-521 Context item 3).
- **first_known_evidence:** docs/decisions/ADR-521-telegram-owner-control-plane.md (owner directive «Telegram / Owner Control Plane», 2026-09-30).
- **current_implementation:** SPA bot `com.spa.telegram_bot`; Bridge bot `com.studiobridge.telegram` (separate repo `studio_bridge`).
- **current_status:** DELIVERED (docs/ROADMAP.md «Closed epics»; Bridge `b19.6.32`, `b19.6.33`).
- **known_gaps:** none for read-only Capital: `/capital /btc /lab /oracle /sherlock` delivered 2026-10-07 (ADR-612, `2b8887cb`) — read-only, same readers as Mission Control, money-order phrases refused. Voice phrases are not routed to the Capital screens (ADR-612 remainder).
- **relevant_decisions:** ADR-521, ADR-612
- **superseded_implementations:** OpenClaw Telegram gateway — REMOVED / RETIRED (ADR-599), never a dependency of either bot.
- **last_verified:** 2026-10-07

## INT-09 · Autonomous self-healing without spamming the owner
- **owner_intent:** «… не слать мне спама… займись основательно, а не так, как ты её чинишь уже третий раз» (owner voice note 2026-08-13, quoted in ADR-084 «Жалоба»): routine self-repair must not call the owner.
- **why_it_matters:** repeated fix-break-notify loops cost the owner attention and hide real incidents.
- **first_known_evidence:** docs/decisions/ADR-084-routine-selfheal-does-not-call-the-owner.md
- **current_implementation:** self-heal status `data/self_heal_status.json`; Problem store (one Problem per recurring (agent, cause_code), RCA required — ADR-580 C6).
- **current_status:** RUNNING; open Problems in CURRENT_STATE «Active problems».
- **known_gaps:** Problems without RCA stay open by design.
- **relevant_decisions:** ADR-084, ADR-580
- **superseded_implementations:** per-alert notification loop (ADR-077 notification route, changed by ADR-084).
- **last_verified:** 2026-10-07

## INT-10 · Memory — the «Milla Jovovich» idea
- **owner_intent:** UNKNOWN in canonical files: the owner refers to the memory idea by the name of MemPalace's co-creator (ARB-CONTINUITY-01 directive, 2026-10-07, chat — not a canonical file). The recorded canonical intent is ADR-527's: a new session must reconstruct the project from current, sourced files, not from stale ones.
- **why_it_matters:** «A new session reconstructed the project from stale sources» (ADR-527 «Context»).
- **first_known_evidence:** docs/decisions/ADR-527-memory-and-context-architecture-v1.md (2026-10-01).
- **current_implementation:** stdlib FTS5 memory `spa_core/studio_os/memory/` (assembler, truth semantics, passports, lineage); this continuity layer (ADR-610) as the session entry point.
- **current_status:** DELIVERED; index freshness ratchet live (ADR-591 A1).
- **known_gaps:** ADR-591 A6–A9 (temporal fact validity, git first-seen, held-out set) are future work.
- **relevant_decisions:** ADR-527, ADR-591, ADR-610
- **superseded_implementations:** Context Pack «recent decisions» returning the oldest rows (ADR-527 «Context»).
- **last_verified:** 2026-10-07

## INT-11 · MemPalace evaluation
- **owner_intent:** evaluate MemPalace honestly before adopting it (ADR-527 §7, ADR-591).
- **why_it_matters:** a memory dependency must win on the project's own questions and respect stdlib-only runtime (invariant #4).
- **first_known_evidence:** docs/decisions/ADR-527-memory-and-context-architecture-v1.md §7 («option **C — borrow ideas**, not a dependency»).
- **current_implementation:** HYBRID_BORROW_COMPONENTS — two MemPalace ideas re-implemented in stdlib (ADR-591); no MemPalace package in runtime.
- **current_status:** DECIDED — dependency REJECTED (top-5 12/51 vs 31/51, 81 dependencies — ADR-591).
- **known_gaps:** none open.
- **relevant_decisions:** ADR-527, ADR-591
- **superseded_implementations:** none (MemPalace was never integrated).
- **last_verified:** 2026-10-07

## INT-12 · RM-TRUTH-01 — company truth reconciliation
- **owner_intent:** «MACRO EPIC — FRESH SESSION REQUIRED, RM-TRUTH-01 v2 COMPANY TRUTH RECONCILIATION + DIRECTOR OS RECOVERY» (docs/ROADMAP.md item 10): a forensic read-only map first, then contracts, waves with independent reviews; no historical paper data reset.
- **why_it_matters:** see INT-02; plus the owner's cards existed only on the production Mac, and an unused shell-capable agent (OpenClaw) was still installed.
- **first_known_evidence:** docs/ROADMAP.md item 10; docs/rm_truth/MASTER_CURRENT_STATE_MAP.md
- **current_implementation:** ADR-580 contracts; ADR-590 Trading Lab canon; ADR-591 memory; ADR-592 Director OS v2; ADR-593 backfill; ADR-599 OpenClaw removed; daily archive + iCloud off-device copy (commits `1c5445d3`, `fe0534b5`).
- **current_status:** DONE 2026-10-07, remaining Owner Gates listed in docs/ROADMAP.md item 10.
- **known_gaps:** see docs/ROADMAP.md item 10 «Remaining debt».
- **relevant_decisions:** ADR-580, ADR-590, ADR-591, ADR-592, ADR-593, ADR-599
- **superseded_implementations:** none.
- **last_verified:** 2026-10-07

## INT-13 · ARB continuity — architecture survives a fresh session
- **owner_intent:** ARB-CONTINUITY-01 (owner directive 2026-10-07): a completely fresh AI session (no chat history) must recover the architecture, the current state and the owner's intent from canonical files, detect stale context, and never operate from it silently.
- **why_it_matters:** AI sessions are workers, not memory; every new ChatGPT/Claude session otherwise re-learns the company from chat or from stale summaries.
- **first_known_evidence:** docs/decisions/ADR-610-arb-continuity.md; candidate prepared by ChatGPT Work 2026-10-06 (outside the repo).
- **current_implementation:** `docs/continuity/` (this ledger, ARCHITECT_CONTEXT, BOOTSTRAP, schema) + generator `spa_core/studio_os/memory/continuity.py` (generated CURRENT_STATE, ARCHITECT_DECISION_INDEX, state.json).
- **current_status:** IN PROGRESS (docs/ROADMAP.md item 11).
- **known_gaps:** an independent LLM fresh-session run is a separate acceptance step (`FRESH_SESSION_PROMPT.md`).
- **relevant_decisions:** ADR-610, ADR-527
- **superseded_implementations:** root `CURRENT_STATE.md` as the session entry point (kept as legacy history; ADR-610).
- **last_verified:** 2026-10-07

## INT-14 · Owner presentation policy — how numbers and times are shown to the owner
- **owner_intent:** «All user-visible percentages must show exactly TWO digits after the decimal separator. Rounding: ROUND_HALF_UP at the third decimal digit.» and «Default Owner-facing timezone: Europe/Madrid» (owner assignment «Presentation Policy + P1 Truth & Safety Recovery», 2026-10-08, sections A and B; recorded in ADR-660).
- **why_it_matters:** one measurement printed as 4,8 / 4,9 / 4,8943 % on three surfaces read as three different numbers; UTC times made the owner convert every timestamp in his head.
- **first_known_evidence:** docs/decisions/ADR-660-owner-presentation-policy-pct-two-decimals-madrid-time.md (owner decision 2026-10-08).
- **current_implementation:** Python `spa_core/utils/presentation.py` (`fmt_pct`, `fmt_owner_time`), JS `landing/src/lib/site_numbers.js::fmtPct2`; Director OS (`company_truth.py`, `director_report.py`, `mission_ui/app.js`) and Telegram owner surfaces switched.
- **current_status:** owner surfaces DELIVERED in the change that introduced ADR-660; public-site switch PREPARED, waits for the owner publication gate (public numbers = ADR-285 subject №2).
- **known_gaps:** remaining owner-facing formatters outside Director OS / Telegram (PDF / monthly reports, `spa_core/reporting/pdf_*`, `monthly_report`) still use their own precision; the site keeps ADR-563's one-decimal round-down until publication is approved.
- **relevant_decisions:** ADR-660, ADR-563, ADR-285
- **superseded_implementations:** ADR-563 presentation-only round-down (`floorTo`, `floor_pct` for display); per-module `"%.Nf"` percentage formatting in Director OS / Telegram; «HH:MM UTC» owner-facing timestamps.
- **last_verified:** 2026-10-08
