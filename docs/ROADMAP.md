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
6. ~~Capital Allocator / Portfolio CIO v1~~ — done 2026-10-04 (ADR-554): Investment CIO «Штирлиц» (`role_id` `chief_investment_officer`), ADVISORY / PAPER cross-sleeve recommendation + immutable decision ledger + forward outcomes; executes nothing. Its own next step is evidence, not code: Balanced/Aggressive reach 30 valid periods ~2026-11-01.
7. **RM-LIVE-01 · Shadow execution + limited capital pilot readiness** — ACTIVE (started 2026-10-04): the boundary
   between a CIO recommendation and any future real-capital action — unsigned intents, simulation, shadow
   execution, reconciliation, readiness verdict. Real capital stays $0; automated live execution is prohibited.
   **Limited real-capital pilots themselves** remain owner-gated (real money, CLAUDE.md subject №1) and are NOT part
   of RM-LIVE-01.
8. **Later engines:** traditional markets, RWA / stable yield, volatility / options

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
