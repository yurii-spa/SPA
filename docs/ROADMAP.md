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
9. **Later engines:** traditional markets, volatility / options (scope decided inside RM-EXPAND-01)

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
