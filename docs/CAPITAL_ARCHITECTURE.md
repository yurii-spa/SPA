# Capital Architecture v1

> Living document. Decision record: [ADR-525](decisions/ADR-525-capital-architecture-v1-and-trading-research-engine.md).
> Accepted by the owner's directive of 2026-09-30. Changes to this hierarchy need a new ADR.

## The hierarchy

```
CAPITAL
├── DeFi                         SPA yield engine (spa_core/…, RiskPolicy v1.0, two-tier kill switch)
│   ├── Conservative             live paper track (the $100k book)            docs/THREE_TIER_YIELD_PRODUCT.md
│   ├── Balanced                 hy_cycle paper book
│   └── Aggressive               lp_cycle / aggressive_lab paper books
├── Trading                      Trading Research Engine (spa_core/trading_research) — RESEARCH / PAPER
│   ├── Crypto Spot              exec model spot_long (cash → asset → cash)
│   ├── Crypto Futures           exec model perp_ls_1x (paper only: funding, margin, liquidation modelled)
│   └── Future: Equities / Traditional Markets
├── Cash / Treasury              the cash buffer of each book; earn-defi stable leg (docs/03 there)
├── Market Neutral / Basis       delta-neutral sleeves in strategy_lab / aggressive_lab (paper, advisory)
└── Future Engines
    ├── RWA / Stable Yield       rwa_backstop desk (advisory)
    └── Volatility / Options     not started
```

The **earn-defi BTC Signal Engine** (`~/Documents/earn-defi`, MVRV-cycle BTC/USDT allocator with its
own NAV and kill conditions, ADR-286) belongs under **Trading → Crypto Spot** as a separate product
engine; it keeps its own repository, ledger and risk gate.

## Who owns what — the boundary that must not move

| | Owns | Never owns |
|---|---|---|
| **Studio OS** (control plane: `spa_core/studio_os`, Bridge, owner_remote) | tasks, evidence of work, experiments as work items, approvals, memory, releases, the read-only Director report | signals, strategies, market data, positions, execution models, financial risk state |
| **Investment engines** (DeFi yield engine, Trading Research Engine, earn-defi) | their signals, strategy definitions, market data, paper (later live) positions, execution models, financial risk state | owner approvals, task state |

Studio OS reads an engine's published status (`data/trading_research/status.json`, the paper-track
files) and renders it; it never writes financial state. Mutable engine state lives in the runtime
`data/` directory — never inside an immutable software release.

## Capital Allocator / Portfolio CIO

The top-level coordinator that recommends weights across the branches above — **built as ADVISORY / PAPER**
(ADR-554, `spa_core/investment_cio`, role `chief_investment_officer`, display name «Oracle» — formerly «Штирлиц»). It consumes each engine's
published, evidence-backed metrics, abstains when evidence is insufficient, and writes an immutable
recommendation ledger; it never executes and no engine reads it. Turning a recommendation into capital
movement is a separate owner decision (real money, subject №1).

## Permission boundaries (unchanged, restated)

| Zone | Examples |
|---|---|
| GREEN — autonomous | research, backtests, paper simulation, reports |
| YELLOW — owner review | promoting a strategy to CHAMPION_CANDIDATE / SHADOW, configuration changes with product impact |
| RED — owner only, outside any engine | real capital movement, exchange orders, live API trading, leverage activation, production risk limits, withdrawal permissions, secrets, production activation with real money |
