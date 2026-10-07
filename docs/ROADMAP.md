# Roadmap — the single canonical roadmap

> **This file is THE roadmap.** Every other `docs/*ROADMAP*.md` is historical and marked SUPERSEDED in
> `architecture/memory_truth.json` (ADR-527). Changing the order or adding a top-level item needs the
> owner's directive and a line in `docs/decisions/` — the roadmap is not edited from chat.
> Last confirmed by the owner: **2026-10-01** (directive «THREE DEFI PAPER PORTFOLIOS — STRATEGY MECHANICS, OPERATIONS AND WEBSITE»).

## Closed epics (accepted by the owner)

| Epic | Evidence |
|---|---|
| Trusted Runtime · Immutable / Approved Release · Fleet Acceptance · Real Canary | ADR-500, ADR-516; approved release `4cb68535` |
| Telegram Owner Control Plane · Telegram Intent Routing | ADR-521 (+ amendment); Bridge `b19.6.32`, `b19.6.33` |
| GitHub Credential Audit & Cleanup | `docs/GITHUB_CREDENTIALS.md` |
| Capital Architecture v1 · Trading Research Engine v0 (keeps running, forward paper) | ADR-525, `docs/CAPITAL_ARCHITECTURE.md`, `docs/TRADING_RESEARCH_ENGINE.md` |
| Memory & Context Architecture v1 (MemPalace evaluated: borrow ideas, not a dependency) | ADR-527, `docs/MEMORY_ARCHITECTURE.md` |
| DeFi Architecture Gap Audit | ADR-530, `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` |

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
    ledger. Next safe action: ARB review of the ARB-CONTINUITY-01 closeout, then the owner gates.
12. **PRODUCT-TRUTH-02 · Reproducible publication & public product truth** — infrastructure delivered
    2026-10-07 (ADR-630, `b39ff06e`; independent reviews CLOSED): one product mapping (Conservative / Balanced /
    Aggressive per ADR-OWN-2026-07; Preserve / Core / Max Yield historical names only), one publication cadence
    (from the published shelf), typed shelf `site_numbers/2` with provenance, fail-closed
    `scripts/verify_publication.py` on every push path, owner approval bound to the shelf sha, Director profile
    mapping, freshness monitor judges the published shelf. Origin DOES rebuild the live site (verified).
    PUBLISHED 2026-10-07 by owner decision (one adjustment: unsourced bank ~0.4 % / T-bills ~3.4 % comparison removed):
    pages `0fd8c24e` live and verified page by page; owner-gate fix live — daily snapshot published again under
    ADR-116 (`b53416d3`, 106 days). First typed shelf `site_numbers/2` (measured 2026-10-07, Conservative 4.8943 %
    REALIZED_PAPER → ~4.8 % shown, ADR-563 floor) waits only for the owner's own signature in the card
    `owner-decision-podpisat-publikatsiyu-nedelnoi-vitriny-c` (agents never record an owner answer, inv. #14); unsigned,
    the regular weekly step builds and asks again on its due date. Remaining debt: «RWA floor ~3.4 %» on /yield-lab,
    /how-we-think and the academy has no source/date (same class, not in the package).
13. **Later engines:** traditional markets, volatility / options (scope decided inside RM-EXPAND-01)

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
