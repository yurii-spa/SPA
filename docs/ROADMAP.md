# Roadmap — the single canonical roadmap

> **This file is THE roadmap.** Every other `docs/*ROADMAP*.md` is historical and marked SUPERSEDED in
> `architecture/memory_truth.json` (ADR-527). Changing the order or adding a top-level item needs the
> owner's directive and a line in `docs/decisions/` — the roadmap is not edited from chat.
> Last confirmed by the owner: **2026-10-01** (directive «THREE DEFI PAPER PORTFOLIOS — STRATEGY MECHANICS, OPERATIONS AND WEBSITE»).
> Latest owner clarification: **2026-10-25** — support the owner's Claude Pro subscription for Studio OS management
> through the official Claude Code CLI; included usage only, no automatic paid continuation (same owner decision below).
> Latest sequencing directive: **2026-10-25** — test management with the existing Claude subscription now;
> defer real local-model probes until the owner has a new Mac mini. No hardware purchase is authorized here.
> Owner priority directive: **2026-10-23** — model-independent workers and architect, P1; bounded verification
> ([owner decision](decisions/ADR-OWN-2026-10-23-model-independent-studio.md)).
> Continuing owner directive: **2026-10-16** «STUDIO-OS-NEXT-01 — next stage of Earn DeFi Studio OS under the ARB plan»
> (ADR-763, item 17). Status words used below are kept apart: **implemented** (code on `origin/main`) · **published**
> (live for the owner or the public) · **owner-verified** (the owner checked the result himself) · **ARB-accepted**.
> An unfinished acceptance is never closed by an agent.

## Closed epics (accepted by the owner)

| Epic | Evidence |
|---|---|
| Trusted Runtime · Immutable / Approved Release · Fleet Acceptance · Real Canary | ADR-500, ADR-516; approved release `4cb68535` |
| Telegram Owner Control Plane · Telegram Intent Routing | ADR-521 (+ amendment); Bridge `b19.6.32`, `b19.6.33` |
| GitHub Credential Audit & Cleanup | `docs/GITHUB_CREDENTIALS.md` |
| Capital Architecture v1 · Trading Research Engine v0 (keeps running, forward paper) | ADR-525, `docs/CAPITAL_ARCHITECTURE.md`, `docs/TRADING_RESEARCH_ENGINE.md` |
| Memory & Context Architecture v1 (MemPalace evaluated: borrow ideas, not a dependency) | ADR-527, `docs/MEMORY_ARCHITECTURE.md` |
| DeFi Architecture Gap Audit | ADR-530, `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` |

## Owner priority update — 2026-10-23

**P1 · STUDIO-OS-MODELS-01 · Model-independent workers and architect.** Owner directive:
[ADR-OWN-2026-10-23](decisions/ADR-OWN-2026-10-23-model-independent-studio.md).
This is the **next bounded Studio OS macro after the current item-17 stage-8 checkpoint**, without waiting for
all technical debt to close. Earlier roadmap entries retain their acceptance status and owner gates.

Scope: portable architect/reviewer context over the existing memory and continuity system; stable roles independent
of vendor/model; one provider contract and explicit per-role routing to qualified cloud/local adapters; bounded
resource use and honest accounting. ChatGPT and Claude Code are current participants, not permanent role definitions.
Start with the existing Claude subscription seam and a fixture-backed second adapter; production/local-model
activation is not approved by this priority change. ADR-423's design deferral is reopened; paid fallback,
hardware purchases and resource limits remain gated. No LLM enters risk/execution/monitoring/kill.

**Owner clarification 2026-10-25:** support the owner's Claude Pro subscription (and compatible Max access) for
architecture review, planning and task preparation through the existing official Claude Code subscription seam.
Reuse the intended login without changing the active implementer's account. Preserve role permissions and owner
authority; included usage only, no automatic API/paid-credit fallback. Shared quota exhaustion pauses the task.
Actual Pro connection and billing safeguards remain unverified; the [owner decision](decisions/ADR-OWN-2026-10-23-model-independent-studio.md)
records acceptance criteria and consequences.

**Execution order, owner directive 2026-10-25:** next test the existing Claude subscription path on one useful
management/architecture task through `memory arch-review`, using a fresh context package and the current
intended login. Reuse accepted components; this is not a new adapter project. Local Ollama inference and real
weight-copy preparation are deferred until the owner's new Mac mini is available and a bounded launch is
explicitly authorized. Preserve the accepted probe preparation (`5a0d497f0`, ARB follow-up in
`increment5-plan/ARB_REVIEW_2026-10-25_a2bdf7c09.md`); a second real provider is not a prerequisite for this
Claude management test. Canonical model assignments remain null; no production delivery is implied.

**Status:** the first safe architecture-review slice is ARB-accepted in candidate `393faa72d` (portable context,
provider contract and `memory arch-review`); production delivery is not claimed. The overall MODELS-01 macro,
an actual Pro-profile connection and qualification of a second real provider remain open. Acceptance is scoped
to the tested task, revision and evidence; it never transfers to every model or to production by implication.

**Management test 2026-10-25:** one real `memory arch-review` call completed on the observed Max profile
(115.951 s, one attempt; `increment6-claude-management/run/`). ARB accepts evidence that the existing
management call path works for this scenario; its proposal is a draft requiring review. The supplied
handover/backlog contained stale implementation statuses. See
`docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/ARB_REVIEW.md` before choosing work
from that answer. No automatic execution or actual Pro-profile qualification is established.

**Voice checkpoint, ARB 2026-10-25:** notification wording accepted in candidate `33b3219ac`
(CI 40209078724: 135106 passed, 2 known §49 failures, 719 skipped, 12/12; no new failed node IDs versus
`5a0d497f0`). Ordinary requests without a declared check still remain `no_probe`. Next bounded connection:
prepare a reviewable plan and acceptance proposal from an ordinary request through the existing architect
seam; do not make the owner choose internal test names. This is a candidate preparation path, not permission
to dispatch live work. Evidence and scope: `evidence/studio-os-next-01-2026-10-16/voice_owner_check_2026-10-25/ARB_REVIEW.md`.

**Task-prep checkpoint, ARB 2026-10-26 (R1/R2/U1 follow-up):** R2 concurrent preparation and U1 owner-facing
presentation accepted in the candidate scope. Original R1 source/card-change cases fixed; one code-identity
case remains: two commits changing the same file produce the same path list, so stale work is reused.
Candidate `e289dcd1c`, CI 40295468694: 135178 passed, two previous §49 failures, 719 skipped, 12/12; no new
failed IDs. RED, not NO_REGRESSION. Earlier screenshot cropping was a capture artifact, not measured overflow.
Next bounded package: bind freshness/reuse to actual code identity and finish a concrete delivery proposal
(root/revision/sources, builder environment, preservation of newer code, justified restart if any).
No new model call or broad audit. One final CI against e289dcd1c; no deployment or execution in this package.
Decision: `evidence/studio-os-next-01-2026-10-16/record_prep_preview_20261026T084330Z/ARB_REVIEW_2026-10-26.md`.

**Verification efficiency:** bound work to the actual change, reuse traceable evidence, and batch the required
full CI on a stable candidate. No repeated whole-system/AI audit by default; no removal of mandatory checks and
no introduction of the unapproved two-tier test scheme. Read results from already running jobs rather than
starting duplicates. Full rationale, increments, acceptance and constraints are in the owner directive above.

## Order of the next epics

1. ~~Memory & Context Architecture v1~~ — done (ADR-527).
2. ~~DeFi Architecture Gap Audit~~ — done (ADR-530).
3. ~~DeFi Engine vNext~~ — done: three paper portfolios closed through the owner gate 2026-10-03 (ADR-537). Phase 0 done (ADR-531); Phase 1 foundation done (ADR-532, derived `defi_engine`); **three paper portfolios with distinct mechanics running** (ADR-533: Conservative lending under RiskPolicy · Balanced fixed-rate PT to maturity · Aggressive SIMULATED sUSDe/PYUSD loop). Open, owner-gated: money-path bindings (tier labels, Conservative 3 % budget wording/trigger, RTMR coverage) — ADR-532/533; public wording of the strategy pages is published through the owner gate.
4. ~~Build Loop / remaining workflow gaps~~ — done (ADR-551: card lifecycle with evidenced closing, lineage, provenance, orphans, resource guard).
5. ~~Owner Remote / Mission Control v1~~ — done 2026-10-04 (ADR-552): `https://mc.earn-defi.com` behind Cloudflare Access → protected listener :8792; desktop on `127.0.0.1:8790`.
6. ~~Capital Allocator / Portfolio CIO v1 (RM-CAP)~~ — DONE 2026-10-04 (ADR-554): Investment CIO «Oracle» (display name; «Штирлиц» until 2026-10-04) (`role_id` `chief_investment_officer`), ADVISORY / PAPER cross-sleeve recommendation + immutable decision ledger + forward outcomes; executes nothing. Its own next step is evidence, not code: Balanced/Aggressive reach 30 valid periods ~2026-11-01.
7. ~~RM-LIVE-01 · Shadow execution + limited capital pilot readiness~~ — DONE 2026-10-04 (ADR-556): `spa_core/capital_shadow`
   (agent `com.spa.capital_shadow`, 09:45) — unsigned intents, keyless 2-of-N quorum simulation, hash-chained shadow
   ledger, forward reconciliation, sticky incidents, readiness verdict; Mission Control «Live Readiness/Shadow» (no
   buttons). Verdict: no sleeve is ready — DeFi Conservative/Balanced/Aggressive **BLOCKED** (kill switch
   CLEAR_PARTIAL ≠ CLEAR), cash/trading/basis **NOT_READY**. Real capital $0; automated live execution PROHIBITED; no real
   transaction or order was submitted. **A limited real-capital pilot has NOT happened** — it remains owner-gated
   (real money, CLAUDE.md subject №1: custody, counterparty source, off-host anchor, GoLive/live admission, pilot
   amount, kill switch CLEAR) and is not part of RM-LIVE-01.
8. ~~RM-EXPAND-01 · Capital universe expansion + Research Factory v1~~ — DONE 2026-10-04 (ADR-560): `spa_core/research_factory`
   (agent `com.spa.research_factory`, 09:05) — candidates grouped by economic mechanism and keyed by the held instrument,
   cells with state + source root, four return kinds kept apart, first counterparty-risk model (no blended rating,
   UNKNOWN never safe), lifecycle RESEARCH → PAPER → CIO_ELIGIBLE, forward evidence only when the upstream advanced.
   Domains: cash/treasury, market-neutral/basis (repaired, not re-built), RWA/stable yield, DeFi discovery; trading
   research projected read-only; equities and options ARCHITECTURE_ONLY. First production run: 49 candidates,
   PAPER_ACTIVE 0, CIO_ELIGIBLE 0. Oracle (CIO display name) sees the universe, cannot allocate it. Real capital $0;
   no candidate is live-authorized; no real-money pilot has started. No further epic is started automatically.
9. ~~RM-EVIDENCE-01 · Research evidence + paper admission v1~~ — DONE 2026-10-05 (ADR-564): Sherlock
   (`head_of_research`, no capital authority) admits candidates to paper only through deterministic gates — evidence
   bundles, counterparty roles, 12 grades, independent-source groups, Paper Admission v2 (20 gates, UNKNOWN fails
   closed), immutable decisions with replay, paper accounting with no zero-fee defaults, pauses that do not mature.
   Curated facts count only after an independent review bound to their content hash (30 of 43 usable). Result on
   production data: 73 candidates, PAPER_ACTIVE 0, CIO_ELIGIBLE 0 — the blockers are named evidence gaps, not code.
   Oracle still allocates only CIO_ELIGIBLE candidates on paper; RiskPolicy and cio-policy-v1 unchanged. Real capital
   $0; no real-money pilot, no COO epic and no new asset-class expansion has started. No further epic is started
   automatically.
10. ~~RM-TRUTH-01 · Company truth reconciliation + Director OS recovery~~ — DONE 2026-10-07 (ADR-580): owner
    directive 2026-10-05 «MACRO EPIC — FRESH SESSION REQUIRED»; accepted as delivered in the owner directive
    ARB-CONTINUITY-01 §0 (2026-10-07). Wave 1 `96a935fd`, Wave 2 `688f2c4b` (Trading Lab canon ADR-590, memory
    ADR-591, Director OS v2 ADR-592, Conservative backfill ADR-593), OpenClaw removed (ADR-599), owner cards
    carried to origin `2427751a`, long-lived services restarted, off-device DR copy to iCloud `1c5445d3` +
    `fe0534b5`, closeout `e9b73dda`. Map: `docs/rm_truth/`. Real capital $0; no historical paper data reset.
    Owner gates: publish or reject the publication candidate `rmtruth/pubtruth` (subject №2); clear the earn-defi
    INCIDENT by hand (earn-defi ADR-006 K3); LOGOS — legal/business choice on Polymarket access or KILL; turn on
    iCloud Advanced Data Protection; optional Codex sign-out/sign-in; open the cockpit on iPhone through
    Cloudflare Access. Remaining debt: daily site publication blocked by the owner-gate false refusal (ADR-630;
    corrected 07.10 — origin DOES rebuild the live site, the «snapshot from 07-31» was a wrong-ref reading);
    LOGOS log rotation and failure alert (patch prepared, live apply is the owner's);
    truncated weekly archives unverified; upload of the iCloud copy to Apple servers NOT_MEASURED. Closed since
    (ARB-CONTINUITY-01): archive classes (ADR-611), Telegram read-only Capital commands and plain-language
    readiness reasons (ADR-612).
11. **ARB-CONTINUITY-01 · Architecture continuity + owner control & recovery hardening** — in progress: delivered, awaiting ARB review (owner
    directive 2026-10-07, autonomous overnight macro-epic; ADR-610): a fresh AI session recovers the company from
    `docs/continuity/` (curated ARCHITECT_CONTEXT, OWNER_INTENT_LEDGER, BOOTSTRAP; generated, freshness-checked
    CURRENT_STATE and ARCHITECT_DECISION_INDEX). Delivered 2026-10-07 with independent reviews: wave A continuity
    (ADR-610, `4794f185`), wave B backup archive classes FULL vs CRITICAL (ADR-611, `53c5a59e`; first FULL copy to
    iCloud complete, restore drill ALL OK), wave C read-only Telegram Capital commands /capital /btc /lab /oracle
    /sherlock + plain-Russian Director reasons (ADR-612, `2b8887cb`). Real capital $0; no live execution. Owner
    gates: the six RM-TRUTH-01 gates above are frozen, not executed; plus applying the prepared LOGOS reliability
    patch to the live project. Wave D `b58f63b1`: observation times on the runtime cells; production
    `continuity check` = CONTEXT_FRESH (05:43Z 07.10); fresh-session run 2 PASS (34 correct, 2 honest UNKNOWN,
    0 wrong; `docs/continuity/acceptance/2026-10-07-fresh-session.md`). Remaining debt: no writer yet for the
    origin/main test-health record (`data/ci/origin_main/`, section shows NOT_MEASURED); shelf `next_publication`
    vs site freshness monitor disagree (10-08 vs 10-12); Sherlock reader falls back to the wall clock on an empty
    ledger. Next safe action: ARB review of the ARB-CONTINUITY-01 closeout, then the owner gates; current execution work is item 17 (STUDIO-OS-NEXT-01, ADR-763).
12. **PRODUCT-TRUTH-02 · Reproducible publication & public product truth** — infrastructure delivered
    2026-10-07 (ADR-630, `b39ff06e`; independent reviews CLOSED): one product mapping (Conservative / Balanced /
    Aggressive per ADR-OWN-2026-07; Preserve / Core / Max Yield historical names only), one publication cadence
    (from the published shelf), typed shelf `site_numbers/2` with provenance, fail-closed
    `scripts/verify_publication.py` on every push path, owner approval bound to the shelf sha, Director profile
    mapping, freshness monitor judges the published shelf. Origin DOES rebuild the live site (verified).
    PUBLISHED 2026-10-07 by owner decision (one adjustment: unsourced bank ~0.4 % / T-bills ~3.4 % comparison removed):
    pages `0fd8c24e` live and verified page by page; owner-gate fix live — daily snapshot published again under
    ADR-116 (`b53416d3`, 106 days). First typed shelf `site_numbers/2` (measured 2026-10-07, Conservative 4.8943 %
    REALIZED_PAPER → ~4.8 % shown, ADR-563 floor) (history, dated 2026-10-07 — superseded as the public headline by the Wave 2 period return, item 15) waited for the owner's own signature in the card
    `owner-decision-podpisat-publikatsiyu-nedelnoi-vitriny-c` (agents never record an owner answer, inv. #14); unsigned,
    the regular weekly step builds and asks again on its due date. Remaining debt: «RWA floor ~3.4 %» on /yield-lab,
    /how-we-think and the academy has no source/date (same class, not in the package).
13. **CAPITAL-SOURCES-01 · Trading Alpha sleeve + portfolio of return sources** — delivered 2026-10-07 in waves
    A–D with independent reviews (ADR-640, ADR-641; `9b09e7d0`, `02bd142f`, `e62469d1`): Capital Sources = the
    Oracle sleeve contract extended (DEFI_YIELD / TRADING_ALPHA / MARKET_NEUTRAL_BASIS / TREASURY_CASH); Trading Alpha =
    causal PAPER sleeve derived from the canonical Trading Lab (no new engine); Oracle consumes all sources
    (net only, recommendation-only); causal paper portfolio; 10–15 % research question answered NO on current
    evidence. Remaining: 30 days of forward evidence, an execution-cost model (8 unknown components), cross-asset
    data (BTC only), first ledger line with the view at the Oracle run of 2026-10-08.
14. **PRODUCT-UX-01 · Earn DeFi product experience** — DONE 2026-10-07: published by owner decision (`424479ce`,
    follow-up `625d3261`; change record CR-UX01-001): «Earn DeFi», 6-item IA, 5-block home, identical-row comparison,
    measured-first hierarchy, plain-language risk, one live-capital statement, FAQ without unsourced rates; live
    pages verified against the canonical shelf (history, dated 2026-10-07: 4.8 % = 4.8943 floored under ADR-563, since replaced by
    ADR-660 two decimals and the Wave 2 period return, item 15) and at
    375/390/430 px without horizontal scroll. No benchmark introduced (separate future decision). Debt: deep pages
    (FAQ, research desks) still partly internal vocabulary; no public changelog / factsheet.
15. **P1 TRUTH & SAFETY RECOVERY · Wave 1 + Wave 2 (site truth)** — published (ADR-660, ADR-661; ARB acceptance not recorded).
    **Wave 1** (owner-approved 2026-10-08): two-decimal percentages ROUND_HALF_UP + Europe/Madrid owner time (ADR-660,
    replaces the ADR-563 round-down); public API no longer exposes service names/pids/paths (ADR-661); NAV proof subtracts
    paid costs; funnel admin shows «not measured since 2026-10-07» instead of zeros — implemented + published `6f0c7a2b8`,
    `c33b20dad`, `e32ed8b5e`, `bbfcc9724` (API restarted by owner permission). **Wave 2** (owner-approved and signed in
    Telegram SPA Monitor 2026-10-15 21:40 Madrid, shelf 2026-10-15 sha256 `b276af9f…`): implemented + published `0dc759eb2`;
    17 public claims corrected (register `W2_P1_REGISTER.md` of the 15.10 handover). **One return methodology** for site,
    API, cockpit and Telegram: `spa_core/paper_trading/track_period_return.py` + `spa_core/reporting/compound_apy.track_period_view`
    — primary metric = paper period return (as of 2026-10-15: +1.51 % for 22.06–15.10.2026, NAV $100,150.66 → $101,662.57),
    secondary «estimated annual equivalent» 4.87 % ACT/365 labelled «estimate, not a forecast»; Oracle's per-day APY
    (`defi_engine/apy_contract.py`) unchanged and labelled «different method». Verified by the agent live (11 pages × 2
    locales); owner-verified: publication signed; post-publication check by the owner not recorded. Remaining debt: track
    history not declared proven (`anchor_coverage` not measured, `allocation_policy_bounds` has no writer, `schema_sanity`
    fails on 87 old `*.tmp` in `data/`); P2/P3 site residue (brand «SPA», 2.00 % dashboard level not from the constitution,
    «35 adapters» vs registry 36, BTC-engine pages owned by the earn-defi repo); next weekly shelf 2026-10-22 needs a new
    signature if its content changes.
16. **DIRECTOR-OS-UX-02…04 · owner cockpit on the owner's mockup + voice intake** — published 2026-10-15, **awaiting ARB**
    (cards `inbox-pult-ux-02-b…e` stay `in-progress` until ARB closes them; card A `new`). Implemented + published
    `2df987cec` (owner-approved): five sections on the owner's «SPA Director OS» mockup, dark only, «в разработке» with a
    reason where data is missing, deterministic `spa_core/studio_os/owner_view.py` over Company Truth (ADR-762 part 1).
    **Voice / text intake** (ADR-760, Accepted 2026-10-15): implemented + published `a3e3b38c6` + iPhone fix `fd2650660` —
    the cockpit's only write action, a new inbox card. Owner-verified 2026-10-15: Access login, microphone, transcription;
    **not yet verified: a real «Отправить» from the iPhone**, keyboard at phone width, VoiceOver. **ADR-690 → ADR-762**:
    the cockpit ADR was renumbered at release (number collision; `ADR-690` belongs to an unrelated ADR); ADR-762 stays
    **proposed** — its version-bound confirmation part (full decision object, `decision_version`, compare-and-swap, one
    answer per version) is not implemented and changes the confirmation mechanism, so it needs a separate owner decision.
17. **STUDIO-OS-NEXT-01 · next stage of Studio OS under the ARB plan** — implemented; candidate handed to ARB 2026-10-18, NOT ARB-accepted (owner directive 2026-10-16, ADR-763).
    Packages in order: (1) this roadmap + the 34-item reconciliation below; (2) Mac resources and cockpit build speed
    (`findings_bridge` ~5 GB RSS and swap 92.9 % before the 2026-10-15 reboot, `mission_build` 17–22 min, stale
    `director_*` names in `architecture/resource_policy.json`, RAM/swap/disk told apart in alerts); (3) backup coverage
    table, gaps closed in a candidate with a restore drill, then a PREPARED (not executed) decision to retire
    `com.spa.weekly_backup` with rollback; (4) voice path to exactly one card and a plain status for the owner,
    re-send and connection failure; (5) ADR-762 version-bound confirmation in a separate candidate (not wired into the
    live confirmation mechanism), then package value history, plain reasons for warnings, read-only check buttons,
    financial evidence. Real capital $0; no limit or tolerance changes; no new markets; nothing deleted.
    Status 2026-10-16 (each claim with its level): (2) resources — implemented + live-verified: cockpit build
    1175 s → 14 s in production, CORRUPT cells 0, findings_bridge census peak 7.25 GB → 224 MB, frozen-data
    equivalence 0 differing fields (`cc98a1ba`); (3) backups — implemented, restore-drilled in scratch and into a
    clean clone (`2e173313`, `5bc89182`), first nightly run with the new sets not yet observed; iCloud upload to
    Apple NOT MEASURED; `weekly_backup` stays loaded; (4) voice — implemented (`c7e3b6c0`), page + «Мои записи»
    live; server part waits for an owner-permitted `mission_server` restart; real iPhone send NOT owner-verified;
    ARB Telegram card — agent_health judges by success receipts + boot window, live run CRIT 3 → 0, intake no
    longer re-processes accepted tasks (`ef317cbd`, `68d21f88`), probe `agent_health_reboot_false_alarm_closed`
    satisfied; (5) ADR-762 — local candidate branch `candidate/adr762-version-bound`, flag OFF, not wired.
    Not ARB-accepted yet. Update 2026-10-16 05:00Z (ARB round 3): `mission_server` restarted twice with owner permission
    (voice server part + «new identical note = new card» live; iPhone NOT owner-verified); intake keeps a durable notice
    outbox before its stamp (`86fd4e06`); `data/` coverage — 15 necessary subtrees in FULL, scheduled 03:30Z backup and
    restore verified (`f3931465`); ranking_tie repeats fixed (`39dc0192`, sandbox 455 s → 5 s, log 179 MB → 4 KB; live
    run pending); ARB Telegram card — deadlines for first runs, swarm_health/site_freshness monitor fixes,
    RETIRED_LABELS per owner decision own-31, 19 false cards closed with RCA (`cb7aad13`). Evidence:
    `docs/evidence/studio-os-next-01-2026-10-16/`. Next small task: `inbox-skvoznoi-put-iz-pulta-golos-kartochka-is`.
    Update 2026-10-16 16:00Z (ARB round 4): first live cockpit task completed end to end (record → card → claimed
    executor → probe-verified done → one notice → «Мои записи» done_verified; `d5d72f07`, intake wake fix, 3rd
    owner-permitted `mission_server` restart); findings_bridge log growth ~110× lower live; site_freshness live OK;
    full-CI verdict still NOT obtained (suite exceeds the GitHub job limit; push runs cancelled). Owner item: iPhone check.
    Boundary (ARB round 5): the live demo record was submitted by the agent and the agent itself took the card as
    executor — the integration works, AUTONOMY is NOT proven yet; provenance labelled the agent's record an owner note
    (wrong). In progress: sharded CI control run with per-test results; automatic executor selection; provenance
    (channel / established author / authority); recovery from a lost intake wake-up.
    Update 2026-10-17 00:41Z: AUTONOMY PROVEN on one safe read-only task — an agent record was picked by the standard
    hourly cycle (`cycle-9596`, cockpit_dispatch), verified by its declared probe and closed with one correctly
    attributed notice; no manual executor assignment. Bounds: latency = cycle (~1 h), only tasks with a declared probe.
    Update 2026-10-18 (handover): candidate `b47b637a1`; full sharded CI verdict restored (ADR-768) — run #14 on the
    candidate: population 134 982, 58 failed, 0 error, 0 not obtained, 0 new, 0 own regressions (fixed 11 vs #13). CI
    restoration is DONE; suite repair is NOT (58 red, each with cause · impact · owner · verification and a card —
    `docs/evidence/studio-os-next-01-2026-10-16/residual_run14.md`). Also: census `rule_second_copy_census` 405 s → 36 s
    byte-identical; API portfolio read leaves the live DB byte-identical and reads a consistent SQLite+WAL snapshot
    (live-verified). Owner items open: iPhone voice send (not verified), ADR-762 (OFF), `weekly_backup` (stays ON),
    two-tier test idea (not promoted), restart of long-runners started before the candidate. Real capital $0.
    Update 2026-10-22 (stabilisation candidate, local branch `integ/studio-os-next-01-stab` on `62fe88b48`, NOT pushed,
    NOT ARB-accepted): phantom repair consolidated, `--apply` still REFUSED until one shared tracker lock exists;
    publication gate proven offline (existing network_guard in every child + loopback recording proxy); root/data
    stage population by AST (110); §49 producer PREPARED, not installed, not running; residual on Mac 33 → 24 red of 56,
    0 new. Full verdict INCOMPLETE (ci-control needs the SHA on GitHub; push not permitted). Journal 2026-W43.
    Update 2026-10-22 (stage 2, same branch, still NOT pushed, NOT ARB-accepted): push BLOCKED — Cloudflare Pages
    builds and publishes a preview of every pushed branch (owner setting); §49 producer run isolation — CORRECTED:
    PARTIAL, not proven (ARB reproduced sqlite/shell/dir_fd bypasses of the Python hook); now a Seatbelt write
    boundary with a pre-run self-check, production run BLOCKED in code; producer not installed; G16 deadline
    loss found and closed; residual on Mac 13 red of 56, 0 new. Full Linux verdict INCOMPLETE. Journal 2026-W43.
    Update 2026-10-22 (stage 3, still NOT pushed): Cloudflare unchanged — exclusion authorised but no dashboard
    session/API access (owner sign-in needed); git provenance 26→8 keys, side-store door, office tells designed from
    active, two orphans wired, G16 sweep 1320→497 s. Full Linux verdict INCOMPLETE. Journal 2026-W43.
    Update 2026-10-22 (stage 4): Cloudflare preview excluded for this branch only (owner sign-in; production
    untouched); branch pushed; full Linux CI: base 62fe88b48 RED complete, f4b098b7a INCOMPLETE (shard crash),
    d12e1ebca RED complete (28 failed, 2 new vs base, 43 fixed); fixes from those results; NOT ARB-accepted.
    Final measured 2026-10-23: ab17e71cf full CI RED complete — 8 failed, 0 new vs base, 61 fixed; the 8 are
    pre-existing and wait for ARB/owner decisions (producer install, two control rules, live board, orphans).
    Stage 5 (ARB 23.10): §49 read from completed CI records (code ready, NOT delivered; producer unassigned),
    snapshot→shelf→page projection, R&D carve-out by class on a restored 13.08 cohort, board rebuilt from tree,
    step_time_drift wired into ci_control compare; live_registry_scene_census needs an isolated CI (ARB package).
    Stage 6 measured 2026-10-23: 0026e0fe9 full CI (run 39889880442) RED complete 12/12 — 3 failed, 0 new vs base,
    66 fixed; left: §49 producer tick ×2 (install = ARB/owner) and live_registry_scene_census (isolated CI). NOT ARB-accepted.
    Stage 7 measured 2026-10-23: code 3f2482d22 full CI (run 39913698521) RED complete 12/12 — 135 588 cases, 3 failed,
    0 new vs base; §49 record checked case by case + bound to the named revision; G16 green refusal = budget, not
    re-entry; census workflow on the integ branch. Handover: `HANDOVER_2026-10-23_STAGE7.md`. NOT ARB-accepted.
    Stage 8 measured 2026-10-23: code 3c40ed137 full CI (run 39935715615) RED complete 12/12 — 135 651 cases, 3 failed,
    1 new vs base (test_investor_report, cause not established, backlog B-9); workflow step = wiring for the orphan ratchet;
    census skips bookkeeping docs; §49 variant A (report_dir) + server revision pinned in a temp clone; connection package
    ready, NOT installed. Handover: `HANDOVER_2026-10-23_STAGE8.md`. NOT ARB-accepted.
    After ARB stage-8 review: B-9 cause proven and fixed (CI 40026699075 on 3da13e7bf), B-10 order defect and an
    evidence-name ambiguity fixed next; first STUDIO-OS-MODELS-01 slice (role-pack) demonstrated. NOT ARB-accepted.
    STUDIO-OS-MODELS-01 increment 2 (c60ad6d6a): provider contract + role configuration (Claude CLI adapter and a test
    adapter, explicit selection, refusals, bounded attempts, reported-only usage); production routing off. NOT ARB-accepted.
    Increment 3 (ef5ed5f27): memory.answer.ask moved onto the contract (explicit subscription Claude, deadline via
    claude_run_with_timeout, no reverse import). Increment 2 accepted by ARB as a prepared contract (86d9c662a).
    Increment 3 + B-11 ARB-accepted on 30ca5abc4 (production routing off; no general NO_REGRESSION). Increment 4 in
    progress: one command for a safe architecture review through a chosen provider.
    Increment 4 + B-12 ARB-accepted on 393faa72d (no production delivery claimed; no second real provider; CI RED on
    the two §49 producer tests; no NO_REGRESSION). Local-probe preparation later accepted on `5a0d497f0`;
    real local inference/weight copies DEFERRED by the owner on 25.10 until a new Mac mini and separate launch
    authorization. The Claude management call has already completed; current next step is recorded in the
    25.10 voice checkpoint above, not another local-probe or management-call rerun.
    Handover: `HANDOVER_FOR_ARB_FINAL.md`, `START_HERE.md` in the same folder.
18. **Later engines:** traditional markets, volatility / options (scope decided inside RM-EXPAND-01)

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
| 23 | Voice intake, first real iPhone send | published, not owner-verified; corrected phone script ready 25.10 | — | owner (test) / agent | one card per submission ID, visible status in the cockpit | owner check using voice_owner_check_2026-10-25/OWNER_SCRIPT.md |
| 24 | Who processes `cockpit-voice` cards, feedback | existing path checked on temporary data; ordinary live requests remain no_probe; notification fix accepted in candidate; task-prep result contract and timeout accepted; record concurrency and mobile presentation accepted; actual code-identity binding remains open | 23 for live owner acceptance | agent | useful preparation before execution; truthful reason/outcome; no unverified done | close code-version freshness/reuse case; finish concrete delivery proposal; one final CI; no live execution |
| 25 | Long/English voice, retry when Mac busy | same-ID retry covered by existing temporary tests; new input after confirmed success is a new submission; full iPhone retry/audio UX unverified | 24 | agent | preserved retry keeps the text and original card; new intent stays distinct | keep existing implementation; owner phone check first, later bounded long/English/failure checks |
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

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
