# A6 — Studio OS planning truth + memory (RM-TRUTH-01, Phase 1, read-only)

Mirror: `~/Documents/SPA_mirror` @ `b36acda46` (2026-10-05 04:00). Live state was read from `~/Documents/SPA_Claude/data`, `launchctl list` and local HTTP GETs. Machine-readable outputs are listed below. Supporting work files (generator scripts, the `first.json` first-seen index for 17,343 paths, and the `timeline.md` duplication timeline) are in `rmtruth/work/` and `rmtruth/mem/`.

- `A6_register.json` holds `components` (64), `promises` (56) and `duplicates` (26 clusters).
- `A6_memory_benchmark.json` holds the 39 per-question rows, scores, MemPalace comparison and summary.

> **Read-only incident (disclosed).** One sub-audit opened `spa_core/database/spa.db` in the mirror with sqlite. That created untracked `spa.db-shm` (32 KB) and `spa.db-wal` (0 bytes) on 10-05 at 10:13. I confirmed the WAL was empty and no process held the file, then removed both. `git status` in the mirror is clean again. Nothing else in either repo tree was written. The memory index was built in scratch via `SPA_MEMORY_INDEX`, and I set `PYTHONDONTWRITEBYTECODE=1`.

---

## 1. Planning stores — what is live and what is superseded

| Store | Writer → readers | Live? | Superseded by / proof |
|---|---|---|---|
| `docs/ROADMAP.md` | sessions → `mission_control.py:368`, `context.py:51` | **LIVE** (16 commits 10-01..10-05). Items 1–9 are struck DONE; only "Later engines" is open | Canonical (ADR-527 §8) |
| 8 × `docs/*ROADMAP*.md` (AI1, ATOMIC_MIGRATION, FAMILY_FUND, PHASE2, PRODUCT_REDESIGN_H2, EISENHOWER v1/v2, YIELD_STRATEGY) | none (no non-test reader) | dead | SUPERSEDED in `architecture/memory_truth.json`. None of the files carries a banner in the file itself, although `orphans.py:13` defines a detector for exactly that |
| `MASTER_PLAN_v1.md` (MP-xxx), `GRAND_VISION_v1.md` | none | dead since 06-14 import | **Not marked**, yet CLAUDE.md §"Что это" still names MASTER_PLAN as the financial model |
| `docs/29_backlog.md`, `TOURNAMENT_VERDICT_AND_6MO_BACKLOG.md`, `SITE_UIUX_BACKLOG.md`, `AUDIT_status_backlog_v2.md`, `docs/OWNER_BACKLOG_2026-07-16.md`, `PROGRESS.md`, `CURRENT_STATE.md` | none | orphan | Not superseded formally. CLAUDE.md still sends sessions to `OWNER_BACKLOG_<дата>` and `PROJECT_CONTROL/`. `CURRENT_STATE.md` still has 11 code references |
| `KANBAN.json` | frozen (last written 06-22, last commit 07-04) | **frozen but still read** | Tracker is canonical (memory_truth fact). It still has 44 code references. It feeds `SYSTEM_BRIEFING.md:166` ("Sprint v12.82 · Done 1358"), a GoLive criterion (`readiness_checker.py:356`), and `kanban_metrics.json`, which is rewritten daily from frozen content |
| `nimbalyst-local/tracker/` + `_BOARD.md` | `orchestrator_queue.py`, `owner_queue/`, `build_tracker_board.py` | **LIVE**, 1,193 cards (see breakdown below) | Canonical task store |
| `docs/STATE.md` | sessions | LIVE, 150 lines | The **prod-tree copy** (`SPA_Claude/docs/STATE.md`) is a different, stale 506 KB file last changed 09-02. Mirror STATE.md:12 says "60/30 evidenced" while CLAUDE.md says 100 |
| `docs/decisions/` (514 files, up to ADR-565) | sessions + `adr_number.py` | LIVE | Canonical |
| `docs/adr/` (56 files), `docs/ADR_0NN_*.md` (17 files) | none since 08-27 | dead | memory_truth fact says `docs/decisions` wins. There are **16 number collisions** (see §3) |
| `spa_core/studio_os/build_loop.py` (ADR-551) | derived, no store of its own | LIVE view (used by the Mission Control builder) | — |
| `data/memory/index.db` | manual `build` | **STALE** (10-03 18:38; latest ADR indexed is ADR-551) | see §4 |
| `spa_core/database/spa.db` | none | dead early SQLite | — |

Tracker breakdown (1,193 cards):
- inbox: 637
- agent: 252
- owner-decision: 235 (218 ingested, 10 needs-owner)
- own: 69

`own-*` and `owner-decision-*` are two prefixes for one type.

**Verdict.** After ADR-527 the planning truth is three stores: ROADMAP, the tracker and the ADR registry, with STATE as the summary. Three defects remain:
1. Nine plan/backlog files are not marked SUPERSEDED, and CLAUDE.md still points sessions at some of them.
2. KANBAN.json is frozen but still feeds the briefing and a GoLive criterion.
3. The prod tree's STATE.md is a different, stale file.

## 2. Material owner promises (56)

Counts:

| Status | Count |
|---|---|
| DONE_AND_VISIBLE | 18 |
| PARTIAL | 13 |
| DONE_BUT_DISCONNECTED | 7 |
| NOT_STARTED | 6 |
| SUPERSEDED | 5 |
| BROKEN | 4 |
| UNKNOWN | 3 |

Full evidence per item is in `A6_register.json → promises`. "DONE" means owner-usable or visible, not merely that code exists.

- **DONE_AND_VISIBLE (selection):**
  - Telegram owner control plane: two bots, ADR-521.
  - Mission Control: GET `:8790` returned 200 (I checked), and `mc.earn-defi.com` sits behind Cloudflare Access.
  - Trading Research Engine v0: 138 candidates, 5 in forward paper.
  - Oracle CIO (ADR-554), capital_shadow (ADR-556) and Research Factory (ADR-560). Their agents are loaded in `launchctl` with exit 0.
  - Three paper portfolios plus the `/packages` page.
  - One-source site numbers.
  - Two-tier kill-switch.
  - Self-heal (ADR-084).
  - The $100k paper track (anchor 2026-06-22).
- **BROKEN:**
  - DeFi Checkup: `checkup.earn-defi.com` → **404** (I re-checked), yet the homepage still advertises it.
  - earn-defi BTC Signal Engine: its jobs fail.
  - Yield source discovery: 38 days stale.
  - Yield-improvement rebalance trigger: "optimum" lost to doing nothing 6 times, 12 flip-flops.
- **DONE_BUT_DISCONNECTED:**
  - CMO editorial: 44 approved drafts, 0 published, because `mark_published` has no caller.
  - Sherlock (ADR-564): only aggregate counts reach the owner.
  - Leverage Guardian.
  - Threat reactor.
  - DeFi gap-audit P0s.
- **NOT_STARTED:**
  - Go-live / real-capital pilot: $0. GoLive 29/29 is an inventory, and the 07-15→08-01 target was missed.
  - Money-path bindings A–D.
  - Family-fund cabinet: `app.earn-defi.com` → 404.
  - Offsite backup.
  - BTC capital-cycle machine (docs/15, docs/36 at L2; ADR-102 "реализация НЕ начинается").
- **SUPERSEDED:**
  - SPA `btc_nav` (ADR-118). ADR-525:14 says it was "never installed". Its plist exists in `launchd/` but it is **not loaded**, and there is no `data/btc*`. This corrects the duplicate-hunt note that called it live.
  - Director OS web cockpit: see the Director OS finding below.
  - "No product work until yield".
  - Balanced/Aggressive track counted from 08-23.
  - MASTER_PLAN phases 3–4.
- **PARTIAL:**
  - "90 % working": analytics at 230/671 = 34 %, flat since 09-15. ADR-190 says there is "no engineering path".
  - Investment OS: 12 of 16 analysts live.
  - Aggressive tier: 4/30 valid periods since the 10-02 re-versioning.
  - Novel-edge R&D: it runs, but no idea has reached forward paper.
  - Memory (§4).
  - Build Loop resource guard: exit 1.
- **UNKNOWN:**
  - Whether the per-move $ cap is enforced.
  - The notification rule for applications.
  - The tier-name pair Preserve/Core/Max Yield vs Conservative/Balanced/Aggressive. Both naming systems coexist (`DEFI_ARCHITECTURE_GAP_AUDIT.md:43`, `SITE_DESIGN_SYSTEM.md:369-371`). Choosing one is owner subject #2.

**Director OS finding.** Origin ADR-492:26 cites "Director OS doctrine (ADR-469)".
- That doctrine exists only in the off-origin worktree `~/studio-os-scratch/v03`, with status `DECISION_PROPOSED` (09-24).
- Origin's own ADR-469 is an unrelated "writer-harm" ADR.
- `com.spa.director_server` (:8788) is still running (pid 1702, HTTP 200) with a 09-20 publish stamp, in parallel with Mission Control :8790.
- ADR-552:15 calls it a duplicate. Recommendation: SUPERSEDE.

## 3. Duplication across the four months (25 clusters + 1 found by A6; timeline in `work/timeline.md`)

Git history starts on 2026-06-14, so a 06-14 date means "on or before".

| Concept | Times built | Canonical now (proof) | Action |
|---|---|---|---|
| **Owner cockpit** | 7 | `director_report` + `mission_server` (ADR-552 Phase-0) | SUPERSEDE the rest (`director_server`, `com.spa.dashboard`) |
| "Mission Control" name | 2 codebases 5 days apart | `studio_os/mission_control.py` | Rename `studio_shell`'s |
| **BTC engines** | 4 | **No ADR names a canonical engine** | Owner/ADR needed |
| **Readiness / go-live gates** | ~12 | `golive_checker` + `capital_shadow/readiness` | MERGE; delete 5 zero-importer variants |
| Adapter registries | 6 (36/22/8 entries …) | `ADAPTER_REGISTRY` | MERGE |
| Agent registries | manifest 107 agents · `agent_registry.json` 80 · SYSTEM_MAP "58" | `architecture/manifest.json` | Generate the others from it |
| **Memory systems** | 3 generations in repo + Claude auto-memory + Company Memory repo | `studio_os/memory` | Mark the old ones SUPERSEDED |
| Roadmaps / plans | 11 | `docs/ROADMAP.md` | Mark MASTER_PLAN / GRAND_VISION |
| "Current state" docs | 5 | `STATE.md` + `SYSTEM_BRIEFING` | SUPERSEDE |
| Owner queues | tracker, KANBAN, OWNER_BACKLOG, inbox/, Telegram `/task`, two card prefixes | tracker via `owner_queue` | SUPERSEDE |
| **ADR registries** | 3 locations, **16 number collisions** (CLAUDE.md says 5) | `docs/decisions` | MERGE / renumber |
| Tournaments, health monitors, Telegram senders, push tools, digests, HTTP servers, tier calculators, risk scorers, strategy registries, plist dirs | 3–13 each | see `duplicates.json` | MERGE |

Details for the starred rows:
- **Owner cockpit, built 7 times:**
  - cabinet 06-18
  - `com.spa.dashboard` 06-24
  - landing `/admin` 07-09
  - `director_server` 09-20
  - `studio_shell` 09-28
  - `owner_remote` 09-28
  - `mission_server` 10-03
- **BTC engines, 4 efforts:**
  - `research/btc_cycle`, archived
  - `btc_nav`, never loaded
  - earn-defi engine (09-04), broken
  - `trading_research` (09-30), live
- **Memory systems:** root `MEMORY.md` / `MEMORY_FACTS.md` (06-14), `memory/` (06-20), `studio_os/memory` (10-01).
- **ADR collisions:** 002, 008–011, 021, 029–032, 048, 050, 053, 067, 073, 145. A6 adds three more:
  - ADR-067 has **two files inside `docs/decisions`**.
  - ADR-469 collides between origin and the shadow worktree.
  - The kill-switch "ADR-034" cited by CLAUDE.md has no file. `docs/adr/ADR-034` is atomic-write, and `INDEX.md:11` says "Superseded by ADR-048".

Pattern: **most duplication was created in the 06-14…06-26 mass-generation period**, which produced dead modules with zero importers. The **owner cockpit** is the one concept that kept being rebuilt late, with 4 new surfaces between 09-20 and 10-03.

## 4. Memory

### Current system (ADR-527, 2026-10-01)

**What it is:**
- Code: `spa_core/studio_os/memory`, 10 modules, 1,275 lines, stdlib SQLite FTS5.
- Six roots: SPA_mirror, studio_bridge, earn-defi, Company Memory, Claude auto-memory, and the v03 shadow worktree.
- An allow-list of sources (`sources.py`).
- A truth registry, `architecture/memory_truth.json`, with SUPERSEDED overrides and semantic facts.
- Its own benchmark, `architecture/memory_benchmark.json`: 12 questions × 3 phrasings plus held-out phrasings.

**Who uses it:**
- Sessions, through the CLAUDE.md instruction.
- No launchd agent and no code consumer outside its own package.

**Prior MemPalace review** (ADR-527:54, 66–97; STATE.md:76; journal W40:2191):
- Verdict: **option C — borrow ideas, not a dependency.**
- Numbers on its own 12-question set:

| System | Own phrasings | Held-out phrasings |
|---|---|---|
| Memory v1, first measurement | 0.939 | 0.848 (the clean number) |
| Memory v1 after fixes | 0.97 | 0.909 (held-out had been seen — the ADR says so) |
| MemPalace, minilm model | 0.273 | 0.152 |
| MemPalace, multilingual embeddinggemma | 0.485 | — |

- The multilingual MemPalace build took 32 minutes and needs 374 MB of palace plus 796 MB of model. chromadb and onnxruntime break the stdlib-only invariant.
- I re-ran the built-in bench here: own 0.97, held-out 0.97 (p50 about 250 ms). The held-out set is no longer unseen.

### Independent benchmark (this audit)

**Setup:**
- 39 queries over 30 history questions in 14 required areas (BTC, Indicator Trading, Director OS, three domains, old and new tier names, superseded decisions, paper-track history, agent purpose, incidents, Telegram, roadmap, Oracle, Sherlock, product profile, plus memory, Family fund, 90 %, self-heal and a trap question).
- Language split: 28 Russian, 11 English. Nine questions were asked in both languages.
- Ground truth for each question is verified from files and quoted in its row.
- The package was graded automatically on five dimensions, 0–2 each, against expected sources and key facts.

**Results (memory v1, fresh index):**
- **Overall score: 0.744.**
- By dimension:

| Dimension | Score |
|---|---|
| Correctness | 0.73 |
| Completeness | 0.68 |
| Temporal | 0.70 |
| Supersession | 0.70 |
| Provenance | 0.89 |

- An expected source was in the top 5 for 24 of 38 queries, and anywhere in the package for 29.
- Latency: p50 0.55 s in-process, about 1 s cold from the CLI. Index build: 5.5 s.

**Russian vs English:**
- Aggregate scores are equal (0.742 vs 0.750).
- Proper-noun questions diverge. Telegram roles scored 1/8 in Russian vs 8/8 in English. Sherlock scored 3/8 vs 8/8.
- "Оракул/Штирлиц" misses ADR-554 in both languages.
- "Почему не взяли MemPalace" misses ADR-527.

**MemPalace, same questions:**
- It was queried offline from the review session's existing isolated venv and palace (corpus dated 10-01), copied to scratch. **Nothing was installed.**
- On the fair subset of 35 questions whose sources existed on 10-01: **10/35 in the top 5, against 22/35 for memory v1.** p50 latency was 1.15 s.
- This confirms the prior verdict.

**Defects found (the reasons for REPAIR):**
1. **Live index is stale and nothing rebuilds it.**
   - The prod index `data/memory/index.db` was built 10-03 at 18:38. Its newest ADR is ADR-551.
   - So ADR-552…565 (Mission Control, Oracle, capital_shadow, Research Factory, Sherlock) are **invisible to every session that follows CLAUDE.md**.
   - `daily_backup.sh` only runs `memory_backup.py`, and `search()` never checks freshness.
2. **The sufficiency verdict is word coverage, not answer coverage.**
   - It returned SUFFICIENT on 28 of 39 queries.
   - That includes the **trap question** (Solana mainnet 2024, which never happened) and 8 queries where the expected source was not retrieved at all (Oracle, Sherlock-RU, Telegram-RU, MemPalace, ADR collisions, PAT leak).
   - This contradicts the doctrine "no evidence ⇒ UNKNOWN". The ADR's own trap result was measured at the LLM answer stage, not by this verdict.
3. **Coverage gaps in the allow-list.**
   - Not indexed: `docs/adr/` (56 ADRs), `MASTER_PLAN_v1.md`, `OWNER_BACKLOG_*`, the `docs/NN_*` design docs (BTC docs 15/36), `TOURNAMENT_VERDICT`, `SYSTEM_MAP`.
   - The shadow-root pattern is only `ADR-47[1-5]`, so the Director OS doctrine is unreachable.
   - The tier-target question (H21) got through only via secondary docs.
4. **No git-history layer** for "when did X first appear or get renamed". `lineage()` covers ADR→commit only.
5. **"Indicator Trading" is a term that exists nowhere in any repo** (rg finds 0 hits). Memory correctly returned PARTIAL, pointing at ADR-525 and the Trading Research Engine.

### Recommendation: **HYBRID_BORROW_COMPONENTS — keep the current stdlib memory as the core and repair it**

Do not integrate MemPalace. It is 2.2× worse on retrieval, slower, breaks invariant #4, and its default model silently stays English-only.

Borrow, without new dependencies:
- (a) A **staleness gate and scheduled rebuild.** Compare `sources_digest` on every query and rebuild nightly, or when the digest differs.
- (b) An **answer-level sufficiency check.** The verdict should require that a top-k CANONICAL chunk contains the question's named entities. Add a trap-question set to CI.
- (c) An **entity / alias layer**, MemPalace's "entities.json" idea: Oracle ↔ Штирлиц ↔ chief_investment_officer, Шерлок ↔ Sherlock ↔ head_of_research, Preserve ↔ Conservative, Телеграм ↔ Telegram. This fixes the Russian proper-noun misses.
- (d) **Allow-list expansion:**
  - `docs/adr` and `docs/ADR_0NN`, with number-collision disambiguation;
  - `MASTER_PLAN`, `OWNER_BACKLOG`, `docs/NN_*`, `TOURNAMENT_VERDICT`, all as status-flagged history;
  - shadow `ADR-469`.
- (e) A small **git first-seen / rename layer** built from `git log --diff-filter=A`.

Semantic embeddings are optional later, and only if a stdlib-compatible path exists.

## 5. Top actions for Phase 2 (not executed — read-only phase)

1. **REPAIR memory:** schedule the index rebuild, fix sufficiency, add the alias layer, expand the allow-list.
2. **SUPERSEDE in `memory_truth.json`:** MASTER_PLAN, GRAND_VISION, CURRENT_STATE, PROGRESS, OWNER_BACKLOG, root `MEMORY*.md`, `docs/adr`, KANBAN-derived metrics. Fix the CLAUDE.md pointers and the "5 collisions" claim (the measured number is 16 or more).
3. **RECONNECT:** the briefing and GoLive criterion off KANBAN.json; CMO publish; Sherlock to the owner surface; the DeFi Checkup homepage link (owner subject #2).
4. **SUPERSEDE `com.spa.director_server`:** it duplicates Mission Control. Rename `studio_shell`'s "Mission Control".
5. **Owner decisions** (subject #2 / an ADR):
   - the canonical BTC engine (4 efforts);
   - tier naming Preserve/Core/Max Yield vs Conservative/Balanced/Aggressive;
   - the public dashboard sprawl (8 pages).
