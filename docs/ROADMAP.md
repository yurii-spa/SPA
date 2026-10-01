# Roadmap — the single canonical roadmap

> **This file is THE roadmap.** Every other `docs/*ROADMAP*.md` is historical and marked SUPERSEDED in
> `architecture/memory_truth.json` (ADR-527). Changing the order or adding a top-level item needs the
> owner's directive and a line in `docs/decisions/` — the roadmap is not edited from chat.
> Last confirmed by the owner: **2026-10-01** (directive «DEFI ENGINE vNEXT — PHASE 0»).

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
3. **DeFi Engine vNext** — Phase 0 (P0 safety & data-integrity repair) done, ADR-531; **Phase 1 Foundation** next, not started (protocol- vs strategy-risk model, one APY contract, one tier authority, position passport, exit/liquidity model, loss budgets, monitoring coverage). Input: `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` §J/§K.
4. **Build Loop / remaining workflow gaps**
5. **Owner Remote / Mission Control evolution**
6. **Capital Allocator / Portfolio CIO** (cross-engine allocation; see `docs/CAPITAL_ARCHITECTURE.md`)
7. **Limited real-capital pilots** — owner-gated (real money, CLAUDE.md subject №1)
8. **Later engines:** traditional markets, RWA / stable yield, volatility / options

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
