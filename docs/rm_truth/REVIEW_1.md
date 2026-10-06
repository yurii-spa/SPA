# RM-TRUTH-01 · Independent Architecture Review #1

Reviewer: independent, adversarial, read-only. Measured 2026-10-05 10:25–10:40 CEST (08:25–08:40Z).
Code from `~/Documents/SPA_mirror` @ `b36acda46` (= `git ls-remote` origin/main). Runtime from `~/Documents/SPA_Claude`.
Nothing written outside this file. SQLite opened `-readonly` + `mode=ro` URIs only. One caveat: the read-only open of
`~/Documents/earn-defi/data/earn_defi.db` (WAL mode) may have bumped the mtime of its existing `-shm` file. Content is unchanged.
The public endpoints used were plain GETs (`curl`).

---

## 1. Verdict: **APPROVE_WITH_AMENDMENTS**

The map is mostly right on the facts and right on the main diagnosis: the truth wiring is broken, not the engines. Every
headline incident I re-measured is real. It has five material defects that must be fixed before the contracts are frozen:

1. **INC-1 is wrong about who did it, and so undersells the incident.** The leaker is not "a sandboxed measurement".
   It is the **production agent `com.spa.decision_loop`** (`findings_bridge --run`), which runs the G97 probe on a schedule.
   The leak recurs, the same runner pattern lives in 5 sibling probes, and the guard asserts the wrong thing.
2. **The site_freshness root cause is only half right.** A3 beats A4, but `deploy_site_snapshot` never carries `site_numbers.json`.
   PUBLISHER_STUCK therefore has a second, independent cause: two weekly shelves with two different tacts, and the monitor's operand is the prod-local one.
   Unsticking the publisher would ship **new public numbers**, so it cannot be done blindly.
3. **Backup/DR is mis-framed.** INC-5 is about the wrong agent. The real gaps are: offsite is the same disk (`is_real_remote:false`), and the new
   immutable ledgers (Oracle, Research Factory, Capital Shadow) are **in no backup**.
4. **The inversion is public, not owner-only.** `/api/live/books` and `/admin/portfolio-summary` answer HTTP 200 to anyone.
5. **Six SUPERSEDED labels are wrong or premature.** Each has a live reader or is the only surviving evidence (§3.3).
   A4's proposed `classify_agent` fix would create a fail-OPEN.

---

## 2. Verified claims (independent re-measurement)

| # | Claim (map/slice) | Verdict | My evidence |
|---|---|---|---|
| 1 | INC-1: G97 probe calls producers without `SPA_DATA_DIR` → `live_data_dir()` writes to prod; `owner_decision_pending.json` stamped 2041 | **CONFIRMED + STRONGER** | `artifact_stamp_clock_doors.run_arm` (L432-445) sets FAKE_WALL/ANCHOR/INJECT/TREE/PYTHONPATH and **no** `SPA_DATA_DIR`/`SPA_LIVE_ROOT`. `owner_decision_pending.run()` L1237 → `live_data_dir(_REPO_ROOT)` → `~/Documents/SPA_Claude/data` because that dir exists (`live_paths.py:58-81`). **Process evidence:** pid 63060 `…/spa_g97_box_qw6rsjkh/tree/spa_core/monitoring/_artifact_stamp_clock_probe.py` started **10:04:20**; prod file mtime **10:04:22**. Its parent is pid 26001 `python3 -m spa_core.monitoring.findings_bridge --run`, launched by `agent_template.sh decision_loop` (launchd) at 07:24. The probe's own `answer.json`: of 50 producers called, exactly 2 did not write into the sandbox tree, and one of them is `owner_decision_pending` (prod mtime matches). The plan has **99** producers, including `investment_os/outcomes.jsonl` (the other non-tree writer; prod mtime 09:19, so not hit this run). `grep 2041- data/**/*.json*` → only that one file. **Self-healed** at 10:37:01 by agent_health (`generated_at` back to 08:36Z), so the corruption lasted 33 min. During it, the bot/MC saw `oldest_pending_age_h=132780`. The probe was still running at 10:37 |
| 2 | `classify_agent` ignores array `StartCalendarInterval` → false CRIT on `novel_edge_rnd` | **CONFIRMED** (fix proposal REFUTED) | `agent_health_monitor.py:495-524` handles only `dict`. The plist is `[{Weekday:2,…},{Weekday:5,…}]`. agent_health 07:36Z gives `category:'daily'`, CRITICAL "log stale 3.2d (>2.2d)", last_exit 0. Prod copy is byte-identical to the mirror. **But** `com.spa.aggressive_lab` also has an array (4×/day: 0/6/12/18h). A4's proposed rule "array ⇒ weekly" would make a 6-hourly agent weekly (fail-OPEN). The fix must classify by the **tightest** entry |
| 3 | `deploy_site_snapshot` → `ModuleNotFoundError: spa_core` since 10-02 | **CONFIRMED** | `logs/daily_cycle_2026100{2..5}.log`: "generator FAILED — not deploying" each day, traceback in `generate_track_snapshot.py`. 10-01: "pushed fresh snapshot". The in-function import `from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL` sits under a script-path launch. Prod = mirror |
| 4 | site_freshness blames CF Pages wrongly (A3) vs "fix outside repo: CF Pages build" (A4) | **A3 wins, but PARTLY** | Report text: "Лекарство вне этого репозитория — сборка Cloudflare Pages". The operand is the **prod-local** shelf (`landing/src/data/site_numbers.json` is `??` untracked in prod, `measured_at 2026-10-04`, next 10-12). The origin shelf is `2026-10-01`, next **10-08**, so it is **within tact**. The live site serves 10-01/10-02 data, which is exactly origin. "3 publications passed" is false against origin. **A4 is refuted.** **A3 is incomplete:** `deploy_site_snapshot.py` ships only `track_snapshot.json` (L38, L185-187). It never carries the shelf. The 10-04 shelf comes from orchestrator step (1е) in the prod tree, and that step has no delivery of its own. So there are **two shelves with two tacts** (duplicate truth), and fixing the import alone will not clear PUBLISHER_STUCK |
| 5 | `books_summary` inverted ladder C 4.15 / B −4.36 / A 1.36 | **CONFIRMED + PUBLIC** | `GET https://api.earn-defi.com/api/live/books` (no auth) → 4.1483 / −4.3571 / 1.3612, `start_date 2026-06-22` on all three. `https://earn-defi.com/admin/portfolio-summary/` → **HTTP 200** (noindex only). It is publicly reachable, so this is not only an owner surface |
| 6 | `/api/health-public.ytd_apy_pct` = single-day rate | **CONFIRMED** | Live: `ytd_apy_pct 4.2224`, `paper_apy_pct None`, `max_drawdown_pct None`. Cycle log: `sqlite_hook … apy=4.22%` (a day rate) |
| 7 | golive_status has no `ready_for_live`; execution_readiness says false; brief prints READY | **CONFIRMED + extra** | golive: `ready True, 29/29, go_live_state gate_passed_owner_decision_pending`, no `ready_for_live` key. execution_readiness: `ready_for_live False`. owner_blockers: open 3. SYSTEM_BRIEFING L9/20: "✅ READY — 29/29". **Extra:** GoLive criterion **C013** (`golive/readiness_checker.py:356-365`) PASSes from `KANBAN.json.sprint_completed`, a file frozen since 07-17. A dead file holds a readiness check green forever (fake DONE). **Extra 2:** the public home page also shows "Go-live progress 29/29" (A3 row 6 "MATCH"), so the scope confusion is **public** too |
| 8 | Owner queue origin 11 vs prod 12; prod-only closures 13 | **PARTLY** | 11 vs 12 confirmed. The only diff is `owner-decision-utochnenie-po-zametke-prikaz-vladeltsa-u` (prod). A naive `^status:` grep says 12, because `inbox-ochered-…` has 3 `status:` lines (frontmatter = ingested). That is a parser trap for any counter. Prod-only closures (prod `owner-done/accepted`, origin `ingested`): **17** by my count, not 13. Four of the 17 are "Критичная находка петли" fleet cards the owner had to accept, which is ADR-285 leakage. `owner_decision_pending` itself reports 2 origin cards whose **text differs** in prod (own-optimum, pyat-protsentov), so the drift runs both ways |
| 9 | Trading Research Engine: no forward-clock reset | **CONFIRMED** | `evidence.db` (ro): 138 candidates, **1** distinct `registered_at_ms` (1790803372716 = 2026-09-30 21:22:52Z). Ticks seq 1..429 contiguous, 429 rows, `ok=0` count 0, max inter-tick gap 15.5 min. 8 no-update/no-delete triggers on all 4 tables |
| 10 | paper_evidence holes (88 rows vs 104 days) | **CONFIRMED, understated** | 88 rows, all `S7`, dates 06-10..10-05. **12 rows are pre-anchor** (06-10..06-21), so evidence covers only **76 of 104** evidenced days (73%). The gaps against the curve are exactly 06-22..06-29 and 08-03..08-22 (28 days) |
| 11 | tier1 BACKTEST labelled `kind: замер` | **CONFIRMED + drifting** | Origin shelf `packages.conservative.apy 3.7 kind замер, annualisation "compound from evidenced anchor"`. Prod-local shelf: **5.4**, same label. Source `_tier_packages()` ← `tier1_packages.blended_net_apy_pct` (3.709 today, regenerated daily 04:30Z). The "backtest" moves 3.7↔5.4 week to week and would ship as "замер" with the next shelf |
| 12 | weekly_backup invisible, archives probably truncated | **PARTLY / mis-framed** | Loaded (`launchctl` last exit 1). 10-03 log "Backup FAILED with exit code 1". Archives 2.8/2.8/2.8/3.7/**1.5**/**2.5** GB. agent_health RETIRED_LABELS L222-229 retires it **on purpose** ("redundant with daily_backup + dr_offsite_copy"). The real finding is that the stated replacement does not replace it: `dr_offsite_status.json` `dest ~/spa_offsite_backups`, **`is_real_remote: false`** (same disk). The broad daily archive `spa_state_2026-10-05.tar.gz` (722 members) has `trading_research/evidence.db` and `paper_evidence.json` but **no** `investment_cio/ledger.jsonl`, `research_factory/ledger.jsonl`, `capital_shadow/*` or `trading_research/market.db`. The failing weekly tar was the only coverage of those ledgers |
| 13 | Memory index stale (newest ADR-551) | **CONFIRMED** | `data/memory/index.db` (ro) manifest `built_at` = 2026-10-03 18:38:56. Newest indexed `ADR-551`. Present on origin: ADR-552…565. There is no launchd agent for memory (`ls LaunchAgents | grep memory` is empty) |
| 14 | ADR number collisions "16" | **PARTLY** | Normalised filename numbers duplicated across `docs/`, `docs/adr`, `docs/decisions`: **11** (021 029 030 031 032 048 050 053 067 073 145). I could not reproduce 16. CLAUDE.md's "5" is wrong either way. `docs/decisions/ADR-034*` absent: confirmed |
| 15 | Capital Shadow counterparty gate hard-coded "no" | **PARTLY** | `readiness.py:195-197` returns **GATE_UNKNOWN** "no counterparty-risk source (none exists)". That is fail-CLOSED, not "no". The literal is stale: `spa_core/research_factory/counterparty_registry.py` exists. Wiring it would **loosen** a live-capital gate, so it is owner subject #1 or needs an ADR. It is not a REPAIR to do autonomously |
| 16 | earn-defi engine in INCIDENT since 09-19 | **CONFIRMED** | `system_state.system_mode=INCIDENT`, `paper_start_date 2026-09-02`. `nav_daily` max date **2026-10-03** (2 days behind today; whether this is cadence or a gap is NOT MEASURED) |

---

## 3. Errors & omissions

### 3.1 Errors in the map
- **§6 INC-1:** the culprit is a scheduled production agent (`decision_loop`/`findings_bridge`), not a sandbox session. Status
  "path proven by reading code" can be upgraded to "proven by process + mtime". It is self-healing hourly, but it recurs every time the
  probe is due.
  **Blast radius:** 99 producers per run. Today only producers whose path resolves through `live_data_dir` leak. The guard
  `assert_disposable_tree` checks that the **tree** is disposable, **not where the writes land**. Five sibling probe harnesses
  (`python_reader_clock_doors`, `entrypoint_import_probe`, `absent_path_probe`, `copy_independence_probe`, `vacuous_guard_probe`) also
  contain zero `SPA_DATA_DIR`/`SPA_LIVE_ROOT` references. A G27 `_http_reader_probe` was running in the same box at 10:30.
- **§2 / §6 INC-3:** "site_freshness кричит PUBLISHER_STUCK **поэтому**" is causally wrong (see claim 4). There are two defects:
  - (a) the daily snapshot publisher is broken;
  - (b) the weekly shelf is built in prod with its own tact and has no delivery path; the monitor compares the visitor against an undelivered file.
- **§4 OWNER_CONTROL_HEALTH "испорчен (2041)"** is now stale (healed 08:36Z). The durable defect is the leak, not the file.
- **§2 "Core":** the map is right that Core→Balanced (ADR-125 "пакет Core"). But "Core" has **three** live meanings:
  - (1) 06-19 site flagship;
  - (2) ADR-125 Balanced;
  - (3) `scripts/tier_paper_rollup.py` "Core (~6%) = the LIVE go-live track", i.e. Conservative.

  In addition, tier_paper_rollup defines Balanced/Aggressive as **aggressive_lab blends**, a third definition of those books. It is written daily (06:01) and has no reader.
  **A6 is wrong** that choosing a naming set is an open owner subject #2: the owner decided on 2026-07-11 (`ADR-OWN-2026-07-owner-decisions-batch.md:25`).
  The open owner question is only whether legacy names survive anywhere public. The map should state the slice disagreement and this resolution explicitly.
- **§1 paper_evidence** should read "76/104 evidenced days covered", not "88 vs 104".
- **§3 "13 закрытий только в проде"** should read **17**.
- **§3 "16 коллизий"** should read **11** (by filename), unless the map names its method.
- **KANBAN.json "заморожен с 06-22"**: the prod copy mtime is 07-17. The point (frozen and still read) stands.

### 3.2 Omissions (categories not covered or under-covered)
1. **API server as a public truth surface.** Unauthenticated public endpoints serve:
   - inverted or legacy numbers: `/api/live/books`, `/api/health-public` (day rate, null DD);
   - a backtest that is 101 days stale: `/api/strategy-lab`;
   - a second target ladder: `/api/tier1/packages`.

   `apiserver` runs code 0.9 days stale. The map treats the API only as a pipe. It needs its own row in §5, with `PUBLIC_API_HEALTH` as a scope or as part of PUBLICATION_HEALTH.
2. **Backups/DR as a domain.** There is no off-host copy (`is_real_remote:false`). The new immutable ledgers (ADR-554/556/560/564) are in no archive.
   Prod-only tracker state is backed up only by the failing weekly tar: 47 undelivered cards, 17 prod-only owner closures, and the untracked prod shelf.
   This is the biggest **lost-paper-data** risk in the system, and the map has no DR row.
3. **Adapter fake fallbacks in the daily cycle.** `apy_evidencer` (cycle log 10-05) lists 8 adapters with `apy_source='fallback'`, among them `pendle_yt_susde 14.0`, `ethena_susde 12.0`, `aerodrome 8.5` and `frax 7.5`.
   These are literal fallback APYs produced every day, against `.claude/rules/adapters.md` "Никаких fake-fallback'ов". The map only mentions gold's 8%.
   They are labelled L0 and `_fundable()` should exclude them. Who else reads `apy_ranking.json` with them is NOT MEASURED.
4. **Kill-switch runtime state.** `kill_switch_status.json` is `CLEAR_PARTIAL` (red_flags fallback, per A2 §… L217-218). That is absent from the map.
   The map also has no row stating which kill-switch governs Balanced/Aggressive, which sit outside RiskPolicy with stops of −8% and −25%.
5. **CMO/publishing and family fund** (A6 L74, L82): 44 approved drafts, 0 published (`mark_published` has no caller); `app.earn-defi.com` returns 404.
   These are "fake DONE" class findings that the map dropped.
6. **earn-defi as a product**, not only as a BTC engine. Its own launchd jobs exit non-zero (daily=2, monitor=2, drill=2), the fire drill FAILs 5/6, and NAV stops at 10-03.
7. **decision_loop itself.** It has run for over 3 h per invocation, its log is 3.8–4.0 GB, and it is the INC-1 writer.
   C6 proposes to load **more** work into this same agent (findings_bridge). The map should flag its runtime as a reliability risk before using it as the Problem-store.
8. **Owner-queue parser trap:** cards with several `status:` lines (inbox-ochered-… has 3). Any surface counting by grep instead of frontmatter will disagree.
   This is one more mechanism behind "11 / 12 / 6".
9. **Audit concurrency.** Phase 1 measured prod while `decision_loop` was writing into prod (08:04Z, inside the 08:00–08:45Z audit window).
   No slice notes that live writers, including a probe with a fake clock, ran during measurement. Any value read 08:04–08:36Z from `owner_decision_pending.json` is tainted (A4/A5 OWNER_CONTROL figures).

### 3.3 Wrongly or prematurely marked SUPERSEDED (UNKNOWN_PURPOSE / removal risk)
| Component | Why the label is wrong | Correct action |
|---|---|---|
| `store:KANBAN.json` | Still **read** by GoLive criterion C013 and by the briefing | RECONNECT the readers first; then supersede |
| `store:PROJECT_CONTROL/` | CLAUDE.md line 4 still names `PROJECT_CONTROL/00_START_HERE.md` as the topology entry point | KEEP until CLAUDE.md is changed (that is an instruction change, not a doc archive) |
| `store:docs/OWNER_BACKLOG_2026-07-16.md` | The CLAUDE.md session protocol reads `OWNER_BACKLOG_<date>`. "Superseded by de-facto ADR registry" is unproven item by item; only item 5 is proven superseded (ADR-548 8b) | ARCHIVE_AFTER_CARRYOVER, with a per-item ADR mapping |
| `weekly_backup` | `superseded_by: None`. Its stated successor (daily + offsite) does not cover what it covered | REPAIR or replace coverage **before** unload |
| `CAP-RESEARCH-BTCCYCLE` | It is the only record of the owner's original indicator results (ADR-102: k=1.0 36.1%/−43.4%, etc.). The code is superseded; the **evidence is not** | ARCHIVE_AS_EVIDENCE (preserve numbers + provenance; mark "champion files never delivered") |
| `legacy_strategy_registries` | `paper_evidence.json` rows carry `S7`, which resolves via `paper_trading/strategy_registry.py:266` | Keep until the S7 mislabel is migrated; otherwise 88 evidence rows lose their meaning |

---

## 4. Contract amendments (C1–C9)

The direction is right. Three contracts as written risk making Director OS / Company Truth a second engine, memory or source of truth (C1, C4, C6).
Amendments:

- **C1 (one address per value)** — Amend:
  - The entity→canon table lives in the **existing** `architecture/provenance.json` (or `memory_truth.json`), not in a new file or in MC.
  - "Second active source = red test" ships as a **ratchet with a decreasing baseline**, the house pattern. A hard red on day one would turn ~26 clusters red and teach people to pad the baseline (inv. #16).
  - A "source" is defined as a **writer**, not a file. Mirror copies with `source`+`as_of` are derivatives.
  - Two writers to one day (own-32) is a C1 violation by definition.
- **C2 (typed numbers)** — Amend:
  - Do not invent a parallel vocabulary. Extend the existing `kind` field of `site_numbers.json` (`замер`/`решение`) and `.claude/rules/site-numbers.md`, whose "третьего не дано" needs an ADR to admit BACKTEST/TARGET/MODELLED.
  - Add the mandatory fields `window_days`, `annualisation` and `reportable` (maturity gate, `reportable_after`). Two of the three inversion mechanisms were short-window and maturity problems, not type problems.
  - Comparisons and orderings are allowed only within the same type **and** the same reportability.
  - `null` is mandatory below maturity (inv. #17).
- **C3 (scoped readiness)** — Amend:
  - (a) Add **PUBLIC_SURFACE** coverage: the public "Go-live progress 29/29" is the same scope confusion. Its wording is owner subject #2.
  - (b) Rename the golive artifact's headline semantics to "inventory 29/29" internally (autonomous).
  - (c) Any criterion that reads a frozen file (C013/KANBAN) must be UNKNOWN, not PASS.
  - (d) OWNER_CONTROL_HEALTH must flag future-dated stamps (`generated_at > now + skew`) as CORRUPT. That detector would have caught INC-1 in minutes.
- **C4 (Company Truth = derived model)** — Amend to forbid a store:
  - Computed **on read** inside the existing Mission Control bundle.
  - No persistent file is cited as a source.
  - **No agent or gate may import or read it** (enforced by an import-ratchet test, like the `spa_core/execution` ban).
  - Every value carries `canon=<path>` so the reader goes to the canon, not to Company Truth.

  Without this, C4 recreates Director OS.
- **C5 (one owner queue = origin)** — Amend:
  - The prod→origin carrier is the **reverse direction of the existing `first_delivery.py`**, not a new service.
  - Define a status lattice (`needs-owner < owner-answered < ingested < owner-done/accepted`) so the carrier resolves the 17 conflicting closures deterministically and never moves a card backwards.
  - `subject:` frontmatter is classified by **one** shared function; MC `risk_class()` and Director `SUBJECT_HINTS` are deleted in favour of it. Missing subject ⇒ UNKNOWN ⇒ returned to the agent.
  - Counters parse frontmatter only (multi-`status:` trap).
- **C6 (Problem-store)** — Amend:
  - Key = (`agent`, `cause_code`).
  - The closing criterion is a `card_acceptance` probe (ADR-208), set at creation.
  - An RCA field is **required to close**.
  - Alert edge-state links to the Problem id so a recurrence increments instead of re-alerting the owner.
  - Fleet findings route to **agent** cards (ADR-285).
  - Before adding inputs, bound `findings_bridge`'s runtime and log (now 3 h+ / 3.8 GB), or run the Problem ingestion as a separate light step. Do not grow the agent that caused INC-1.
- **C7 (forward clocks immutable)** — Amend:
  - Backtests must exclude any bar at or after `forward_start` from OOS (A1 D2).
  - The `forward_bars` +1 defect is fixed in the **reader**; the ledger is not rewritten.
  - Positive control: a test that tries an UPDATE/DELETE and a re-registration and expects refusal.
- **C8 (sandbox never writes prod)** — Necessary, not sufficient. Amend:
  - (a) Enforce at the **destination**. `live_paths.live_data_dir()/live_root()` must refuse (raise) to resolve to the default prod tree when a sandbox marker is set (e.g. the probe's `TREE_ENV`, or a generic `SPA_SANDBOX=1`).
  - (b) Every `*_doors`/`*_probe` harness sets `SPA_DATA_DIR=<tree>/data` and `SPA_LIVE_ROOT=<tree>`.
  - (c) Positive control: replay INC-1 (`owner_decision_pending.run(now=ANCHOR)` under the harness env) and assert that the prod-path mtime is unchanged.
  - (d) Add a detector for future-dated stamps in prod `data/`.
- **C9 (Director OS v2 = Mission Control)** — Amend:
  - Carry over Director's subject triage and provenance (its "6 real / 11 defects" verdict is the more honest one).
  - Freeze `director_build`/`director_server`: they are undeclared in the installer and hold a 4.8 GB bundle.
  - Restate the doctrine ("reads, derives, never a second backlog/memory/truth") as an **accepted ADR on origin**. Its only text today is a PROPOSED off-origin worktree draft, and "ADR-469" now points elsewhere.
- **New C10 (DR coverage)**:
  - Every append-only ledger declared in `architecture/*` must be in the daily archive, checked by a test that compares the declared ledgers with the archive members.
  - "offsite" means `is_real_remote:true`. Until then DR is reported as `SAME_HOST`, never as green.
- **New C11 (one fleet definition)**:
  - `architecture/manifest.json` is the canon. The installer, RETIRED_LABELS, the registry and self_heal derive from it.
  - The parity test is a ratchet.
  - "Retired" means unloaded **and** recorded. A retired-but-loaded agent is a C11 violation, not a silent state.
- **New C12 (publication sequencing)**:
  - A shelf/snapshot may be delivered only if it passes C2 checks; publication has one tact (origin's).
  - Prod-local shelves are build artefacts, never monitor operands.

---

## 5. Remediation split

### Autonomous (outside ADR-285's three subjects; journal entry, no owner card)
1. **INC-1 fix (C8 a–d)**: patch the harnesses and `live_paths`, add the positive-control test, add the future-stamp detector. No manual edit of prod `data/` is needed: the producer rewrites the file hourly.
   (Killing the running pid 63060 or restarting decision_loop is an action on a prod agent; deployment.md p.6 makes it the owner's.)
2. `classify_agent`: classify by the **tightest** calendar entry, plus tests for both the novel_edge_rnd (weekly) and aggressive_lab (6-hourly) positive controls.
3. `deploy_site_snapshot` import fix (module run / sys.path), plus the ADR-148-class test.
   **Sequencing:** ship it only after (5), and after confirming that `check_owner_gate`/`safe_site_push` inspects `landing/src/data/*.json` number deltas. The next delivery changes public values: days 100→104, and `packages` 3.7→5.4 "замер".
4. site_freshness: compare against the **origin** shelf, name the producer leg in the remedy text, and emit one card, not a message every 6 h.
5. `generate_track_snapshot._sleeve_paper_track`: null below `reportable_after`. Relabel `packages.*` to a backtest kind in the JSON (not rendered by any page; A2 grep), under a site-numbers rule ADR.
6. `books_summary` / `/api/live/books` / Telegram "📚 Пакеты": v2-only, current experiment, maturity-gated (null → "accumulating"). This **applies already-approved ADR-531/548**; it does not decide a new public number.
7. `/api/health-public` and `/api/ssot/facts`: expose the canonical `paper_apy_pct` and the drawdown from the snapshot instead of the day rate and the frozen tear_sheet. The canonical 4.9% is already the owner-approved public hero, so this repairs a pipeline. Apply the ADR-563 floor.
8. Briefing: print `ready_for_live` + "inventory 29/29" separately (internal surface); make C013 UNKNOWN on a frozen file.
9. Owner queue: the reverse carrier (C5), the shared subject classifier, frontmatter-only counters, the option-grammar parser.
   Return the 7 queue-defect cards to the agent with a recorded reason (ADR-285 obliges the agent). Never set `owner-done` (inv. #14).
10. Memory: schedule the index rebuild (with a launchd declaration through the gate); add `docs/adr`, MASTER_PLAN, OWNER_BACKLOG and aliases.
11. Daily backup: add the new ledgers and `market.db` to the archive (C10 test). This only adds coverage.
12. Fleet canon unification in code/config (C11). Fix the register's wrong SUPERSEDED labels (§3.3). Backfill the ADR for "Conservative = evidenced book" (it records a past owner decision; it does not change one).

### Owner (one of the three subjects, or a physical action)
- **#1 money:** wiring `counterparty_registry` into Capital Shadow (it loosens a live gate); the pre-trade re-check thresholds; anything that touches the evidence-vs-curve two-writer fix on the main track **if** it rewrites history.
- **#2 public numbers/labels/legal:**
  - the public "Go-live progress 29/29" wording;
  - the `/packages` "Worst drawdown … realized to date" label over a backtest DD;
  - "Join early-access…";
  - the monotone-ladder expectation;
  - the second target ladder on `/api/tier1/packages`;
  - the hard-coded per-protocol APYs on `/strategies/balanced`;
  - any residual public legacy names.
- **#3 irreversible / external:**
  - Rotate the OpenClaw token and decide OpenClaw's purpose (INC-2).
  - Choose an off-host DR destination (an external account).
  - Lift the earn-defi INCIDENT (owner-reserved by its own decision).
  - Any **history realignment** of `paper_evidence` (forward-only fixes are autonomous).
  - Deleting worktrees, the 4.8 GB Director bundle, or Director OS itself.
- **Prod-agent actions (deployment.md p.6):**
  - Unload `weekly_backup`, `:8767 dashboard`, `digest_weekly` and `tier1_digest`. For weekly_backup, only after C10 coverage exists.
  - Restart `rtmr_sense`.
  - Fix or relocate `mission_tick`, whose plist lives outside the repo.

---

## 6. Risks

1. **INC-1 recurs.** `findings_bridge` re-runs the G97 probe on its tact. Until C8 ships, every run can stamp prod artifacts with fake clocks.
   The worst exposure is the append-only `investment_os/outcomes.jsonl`, which is in the plan: a fake-clock row there is **permanent**, because the hourly overwrite does not heal append-only files.
   Highest priority.
2. **Publisher unsticking ships unreviewed public numbers.** It would ship the prod-local shelf (5.4 "замер"; B/A statuses flip to `paper_test_running`) unless sequenced behind the C2/C12 checks.
3. **DR is single-host.** Losing the Mac mini loses the immutable research ledgers, the prod-only owner closures and the untracked shelf. Retiring weekly_backup per the register would remove the only coverage that exists.
4. **Contract drift into a second truth.** C4/C9 without the read-only import ban would rebuild Director OS under a new name. That is the exact failure the doctrine forbids.
5. **Ratchet explosion.** C1/C2 as hard red tests on day one would train baseline padding (inv. #16). Use decreasing baselines.
6. **Wrong fix of a false alarm.** "Array ⇒ weekly" hides real staleness on aggressive_lab. Every reliability fix needs controls in both directions.
7. **Audit taint.** Owner-control values read 08:04–08:36Z were produced by a fake-clock probe. Phase 2 should re-measure OWNER_CONTROL figures before acting on them.
8. **Removal of UNKNOWN_PURPOSE items.** `tier_paper_rollup` (written daily, no reader, conflicting B/A definition) is a duplicate-truth hazard. It should be RECONNECT-or-ARCHIVE by ADR, not deleted.
   LOGOS, OpenClaw and mission_tick stay owner-confirmed.
