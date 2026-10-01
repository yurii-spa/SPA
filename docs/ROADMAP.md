# Roadmap — the single canonical roadmap

> **This file is THE roadmap.** Every other `docs/*ROADMAP*.md` is historical and marked SUPERSEDED in
> `architecture/memory_truth.json` (ADR-527). Changing the order or adding a top-level item needs the
> owner's directive and a line in `docs/decisions/` — the roadmap is not edited from chat.
> Last confirmed by the owner: **2026-10-01** (directive «MEMORY & CONTEXT ARCHITECTURE v1»).

## Closed epics (accepted by the owner)

| Epic | Evidence |
|---|---|
| Trusted Runtime · Immutable / Approved Release · Fleet Acceptance · Real Canary | ADR-500, ADR-516; approved release `4cb68535` |
| Telegram Owner Control Plane · Telegram Intent Routing | ADR-521 (+ amendment); Bridge `b19.6.32`, `b19.6.33` |
| GitHub Credential Audit & Cleanup | `docs/GITHUB_CREDENTIALS.md` |
| Capital Architecture v1 · Trading Research Engine v0 (keeps running, forward paper) | ADR-525, `docs/CAPITAL_ARCHITECTURE.md`, `docs/TRADING_RESEARCH_ENGINE.md` |

## Order of the next epics

1. **Memory & Context Architecture v1** — includes the MemPalace evaluation (ADR-527, `docs/MEMORY_ARCHITECTURE.md`).
2. **DeFi Architecture Gap Audit** — next; not started.
3. **DeFi Engine vNext**
4. **Build Loop / remaining workflow gaps**
5. **Owner Remote / Mission Control evolution**
6. **Capital Allocator / Portfolio CIO** (cross-engine allocation; see `docs/CAPITAL_ARCHITECTURE.md`)
7. **Limited real-capital pilots** — owner-gated (real money, CLAUDE.md subject №1)
8. **Later engines:** traditional markets, RWA / stable yield, volatility / options

## Standing constraints

Real capital, exchange orders, leverage, production risk limits, public yield numbers and irreversible
actions stay owner-gated (CLAUDE.md «Граница „решай сам“ / „спроси меня“», ADR-285). Research and paper
engines (Trading Research Engine) keep running across epics; their evidence is never reset.
