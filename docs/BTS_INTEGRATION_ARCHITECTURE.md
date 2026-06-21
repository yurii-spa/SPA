# BTS Integration Architecture — Basis Trade System for SPA

**Status:** Phase 1–3 COMPLETE (Feed + Strategy + Monitor implemented & tested; Phase 4 Dashboard pending)
**Author:** SPA Systems Architecture
**Date:** 2026-06-21 (updated 2026-06-21)
**Target capital:** $100K (paper trading first, go-live gated by tournament confidence)
**Scope:** Promote `basis_trade_analyzer.py` from an isolated advisory calculator into a
fully-wired SPA subsystem: live data feed → tournament strategy → monitor agent →
Telegram alerts → dashboard, with BTS-specific risk rules and exit logic.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Data Architecture](#2-data-architecture)
3. [Component Design](#3-component-design)
4. [Sprint Plan](#4-sprint-plan)
5. [Integration Points](#5-integration-points)
6. [Risk Considerations](#6-risk-considerations)
7. [Success Metrics](#7-success-metrics)
8. [Appendix: SPA Conventions This Design Obeys](#8-appendix-spa-conventions-this-design-obeys)

---

## Implementation Status (2026-06-21)

| Phase | Status | Tests |
|---|---|---|
| Phase 1 — Feed (`perp_funding_feed.py`) | COMPLETE | pass |
| Phase 2 — Strategy (`s_basis.py`) | COMPLETE | pass |
| Phase 3 — Monitor (`bts_monitor.py`, `bts_exit_monitor.py`) | COMPLETE | pass |
| Phase 4 — Dashboard Basis tab | PENDING | — |

**Total BTS tests:** 212 across 4 test files + 69 agent_health tests — all green.

`agent_health_monitor.py` fix (2026-06-21): `CAT_ALWAYS_ON` servers with nonzero last
exit code now escalate to CRITICAL (not WARNING) regardless of whether launchd restarted
the process. Install BTS LaunchAgents via `bash scripts/install_bts_agents.command`.

---

## 1. Executive Summary

### 1.1 What BTS is today

`spa_core/analytics/basis_trade_analyzer.py` (164 lines) is a pure, read-only calculator.
It takes a manually-constructed `BasisTradeInput` (asset, spot yield, perp funding,
execution cost, capital) and produces a `BasisTradeResult` with `gross_spread_bps`,
`net_spread_bps`, an `edge_quality` tier (EXCELLENT/GOOD/MARGINAL/UNATTRACTIVE) and a
`recommended_action` (ENTER/MONITOR/SKIP). It writes a ring-buffer log to
`data/basis_trade_log.json`. It is not connected to anything: funding rates are typed in
by hand, the analyzer never runs on a schedule, the tournament never sees it, no alert
fires, and the dashboard never shows it.

### 1.2 What BTS becomes — the full story

A **basis trade** in SPA's stablecoin context is a delta-neutral structure that harvests
the perpetual-futures funding rate while remaining market-neutral. The two canonical
framings:

- **Synthetic / packaged** — hold a yield-bearing stablecoin whose yield *is* the basis
  (Ethena `sUSDe`: long staked ETH/BTC spot + short perp, packaged into an ERC-4626 token).
  SPA already models this as strategy **S8** (`S8_DELTA_NEUTRAL_SUSDE`).
- **Explicit / unbundled** — long a stablecoin lending leg (USDC on Aave) plus a short
  ETH/BTC perp on Hyperliquid, sized delta-neutral. The funding rate is the income; the
  lending APY is the cash carry on the collateral.

BTS-as-a-subsystem turns the analyzer into the **brain** of a recurring pipeline:

```
   Hyperliquid REST  ──┐
   (perp funding)      ├──> perp_funding_feed.py ──> data/perp_funding_rates.json
   adapter_status.json ┘                                        │
                                                                ▼
   data/perp_funding_rates.json ──> S_BASIS strategy ──> tournament slot in cycle_runner
                                          │                     │
                                          ▼                     ▼
                            BasisTradeAnalyzer (reused)   data/strategy_*.json
                                          │
   bts_monitor.py (every 15 min) ─────────┤
        │                                 ▼
        ├──> data/basis_trade_opportunities.json (top-5 ranked)
        ├──> Telegram alert on NEW EXCELLENT opportunity
        └──> bts_exit_monitor.py ──> data/bts_exit_signals.json (active-trade exits)
                                          │
                                          ▼
              /api/live/data/basis_trade_opportunities.json  ──> Dashboard "Basis" tab
```

### 1.3 Design pillars (non-negotiable, from CLAUDE.md / RULES.md)

| Pillar | Rule |
| --- | --- |
| **Stdlib only** | No `requests`/`httpx`. Use `urllib.request` like `defi_llama_feed.py`. |
| **Never raises** | Every public method is fail-safe; errors are logged, caller gets `None`/empty. |
| **Never mocks live data** | If Hyperliquid is unreachable, write nothing / return `None`. No hardcoded funding. |
| **Atomic writes** | `tmp + os.replace`, or the centralized `spa_core.utils.atomic.atomic_save`. |
| **Ring buffers** | History files capped (e.g. 96 snapshots = 24h @ 15-min). |
| **Read-only vs. capital** | BTS never imports `spa_core/execution/`. Paper simulation only until go-live. |
| **Decimal APY convention** | Feeds/strategies use decimals (`0.085` = 8.5%); display layer multiplies by 100. |
| **Fail-closed gates** | Risk-rule violations BLOCK allocation, not silently trim (except over-deploy). |

### 1.4 Headline decisions

1. **Funding source = Hyperliquid** `https://api.hyperliquid.xyz/info` (no auth, on-chain
   perp DEX). Primary assets: ETH, BTC, SOL. The feed normalizes Hyperliquid's hourly
   funding into `funding_rate_8h` and `funding_rate_annual`.
2. **S_BASIS reuses `BasisTradeAnalyzer`** unchanged — it remains the pure math core. The
   strategy is a thin wrapper that *feeds it live data*. This keeps the 100% test coverage
   of the analyzer intact and isolates I/O from math.
3. **BTS rides the existing tournament loop.** No new scheduler for the strategy: it runs
   inside `cycle_runner.py` alongside S0–S65 via the `MultiStrategyRunner`. Go-live uses
   the existing confidence machinery: **confidence > 0.75 sustained for 7+ days**.
4. **`bts_monitor` is a separate 15-min agent** (like `peg_monitor`), distinct from the
   daily cycle, so opportunity scanning and alerting happen at higher frequency than
   rebalancing.
5. **Zero API code changes.** `data/basis_trade_opportunities.json` is served for free by
   the existing generic passthrough `GET /api/live/data/{filename}.json`
   (`server.py:893`). We only add a dashboard panel.
6. **agent_health auto-discovers BTS.** `agent_health_monitor.py` globs `com.spa.*.plist`,
   so `com.spa.bts-monitor.plist` is monitored the moment it lands in `~/Library/LaunchAgents/`.

---

## 2. Data Architecture

### 2.1 New / modified data files

| File | Writer | Reader(s) | Cadence | Ring buffer |
| --- | --- | --- | --- | --- |
| `data/perp_funding_rates.json` | `perp_funding_feed.py` | S_BASIS, bts_monitor, bts_exit_monitor, dashboard | 15 min | latest snapshot + 7-day history |
| `data/basis_trade_opportunities.json` | `bts_monitor.py` | dashboard, alert dedup | 15 min | top-5 (no history; see history file) |
| `data/basis_trade_opportunities_history.json` | `bts_monitor.py` | dashboard chart | 15 min | 96 snapshots (24h) |
| `data/bts_exit_signals.json` | `bts_exit_monitor.py` | cycle_runner, dashboard, alerts | per cycle + 15 min | latest + 50 events |
| `data/bts_active_trades.json` | cycle_runner (paper) | bts_exit_monitor, dashboard | per cycle | current positions, no history |
| `data/basis_trade_log.json` *(existing)* | `BasisTradeAnalyzer.save_results` | dashboard history | on analyze | 100 entries (unchanged) |
| `data/bts_monitor_status.json` | `bts_monitor.py` | agent_health_monitor | 15 min | latest only (heartbeat) |

All writes are atomic. All readers are fail-safe (`{}` / `[]` / `None` on any error).

### 2.2 Schema: `data/perp_funding_rates.json`

```json
{
  "schema_version": 1,
  "source": "perp_funding_feed",
  "venue": "hyperliquid",
  "generated_at": "2026-06-21T10:30:00+00:00",
  "stale": false,
  "rates": {
    "ETH": {
      "asset": "ETH",
      "funding_rate_1h": 0.0000125,
      "funding_rate_8h": 0.0001,
      "funding_rate_annual": 0.1095,
      "open_interest_usd": 412000000.0,
      "mark_price": 3120.5,
      "premium": 0.00012,
      "timestamp": "2026-06-21T10:30:00+00:00"
    },
    "BTC": { "...": "..." },
    "SOL": { "...": "..." }
  },
  "history": [
    {
      "generated_at": "2026-06-21T10:15:00+00:00",
      "ETH": 0.1095, "BTC": 0.082, "SOL": 0.156
    }
  ]
}
```

- `funding_rate_annual` is the canonical field S_BASIS consumes (a **decimal**: `0.1095`
  = 10.95% annualized). Conversion: `annual = funding_rate_1h * 24 * 365`
  (Hyperliquid funding is charged hourly).
- `history` is a 7-day ring buffer of `{generated_at, <ASSET>: annual_rate}` rows
  (672 entries @ 15-min). This powers the dashboard rolling chart with one cheap read.
- `stale: true` is set if the last successful fetch is older than `STALE_AFTER_S`
  (default 3600 s). Downstream consumers treat stale data as "no signal".

### 2.3 Schema: `data/basis_trade_opportunities.json`

```json
{
  "schema_version": 1,
  "source": "bts_monitor",
  "generated_at": "2026-06-21T10:30:00+00:00",
  "funding_data_stale": false,
  "opportunities": [
    {
      "asset": "ETH",
      "structure": "explicit_long_usdc_short_eth_perp",
      "spot_yield_annual": 0.031,
      "perp_funding_annual": 0.1095,
      "gross_spread_bps": 140.5,
      "net_spread_bps": 125.5,
      "annual_pnl_usd": 2510.0,
      "edge_quality": "EXCELLENT",
      "recommended_action": "ENTER",
      "open_interest_usd": 412000000.0,
      "capital_usd": 20000.0
    }
  ],
  "summary": {
    "total_scanned": 4,
    "excellent": 1,
    "good": 1,
    "best_asset": "ETH",
    "best_net_spread_bps": 125.5
  }
}
```

`opportunities` is sorted by `net_spread_bps` descending and truncated to top-5 — produced
directly by `BasisTradeAnalyzer.top_opportunities(results, n=5)`.

### 2.4 Schema: `data/bts_exit_signals.json`

```json
{
  "schema_version": 1,
  "source": "bts_exit_monitor",
  "generated_at": "2026-06-21T10:30:00+00:00",
  "active": [
    {
      "asset": "ETH",
      "entry_net_spread_bps": 125.5,
      "current_net_spread_bps": 8.2,
      "current_funding_annual": -0.012,
      "margin_buffer_pct": 0.31,
      "exit_signal": true,
      "exit_reasons": ["funding_negative", "net_spread_below_floor"],
      "severity": "HIGH"
    }
  ],
  "events": [
    {"timestamp": "...", "asset": "ETH", "reason": "funding_negative", "action": "EXIT"}
  ],
  "kill_switch_active": false
}
```

### 2.5 Schema: `data/bts_monitor_status.json` (heartbeat for agent_health)

```json
{
  "schema_version": 1,
  "agent": "com.spa.bts-monitor",
  "last_run": "2026-06-21T10:30:00+00:00",
  "status": "ok",
  "opportunities_found": 4,
  "excellent_count": 1,
  "funding_feed_age_minutes": 2.1,
  "errors": []
}
```

### 2.6 Data flow diagram (sequence)

```
[LaunchAgent com.spa.perp-funding-feed, */15 min]
  perp_funding_feed.PerpFundingFeed.run()
      → GET api.hyperliquid.xyz/info (metaAndAssetCtxs)
      → normalize → data/perp_funding_rates.json (+ history ring)

[LaunchAgent com.spa.bts-monitor, */15 min, offset +2 min]
  bts_monitor.BTSMonitor.run()
      → read perp_funding_rates.json + adapter_status.json
      → build BasisTradeInput per asset
      → BasisTradeAnalyzer.analyze_batch() → top_opportunities(5)
      → write basis_trade_opportunities.json (+ history)
      → diff vs previous → NEW EXCELLENT? → AlertDispatcher (Telegram)
      → write bts_monitor_status.json (heartbeat)
      → bts_exit_monitor.BTSExitMonitor.run() → bts_exit_signals.json

[LaunchAgent com.spa.daily_cycle, 08:00]
  cycle_runner.run()
      → MultiStrategyRunner includes S_BASIS (reads perp_funding_rates.json)
      → tournament ranks S_BASIS vs S0..S65
      → bts_exit_monitor consulted before holding active basis positions

[FastAPI server, always-on]
  GET /api/live/data/basis_trade_opportunities.json  (generic passthrough — no new code)
  GET /api/live/data/perp_funding_rates.json
  GET /api/live/data/bts_exit_signals.json
      → Dashboard "Basis" tab
```

---

## 3. Component Design

### 3.1 `spa_core/feeds/perp_funding_feed.py` (NEW)

Mirrors the structure of `defi_llama_feed.py`: stdlib-only, retry/backoff with rotating
User-Agents, cached, never-raises. This is the **only** module that talks to Hyperliquid.

**Hyperliquid API contract** (POST, JSON body, no auth):

- URL: `https://api.hyperliquid.xyz/info`
- Body `{"type": "metaAndAssetCtxs"}` returns `[meta, assetCtxs]` where `meta.universe`
  is the ordered list of coins and `assetCtxs[i]` carries `funding` (hourly rate as a
  string), `openInterest`, `markPx`, `premium`, `oraclePx`.
- Index alignment: `assetCtxs[i]` corresponds to `meta.universe[i]`.

```python
# Module constants
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
TRACKED_ASSETS = ("ETH", "BTC", "SOL")
DATA_FILE = Path("data/perp_funding_rates.json")
HISTORY_MAX = 672          # 7 days @ 15-min
STALE_AFTER_S = 3600
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
HOURS_PER_YEAR = 24 * 365  # 8760

@dataclass
class PerpFundingRate:
    asset: str
    funding_rate_1h: float          # decimal, e.g. 0.0000125
    funding_rate_8h: float          # 1h * 8
    funding_rate_annual: float      # 1h * 8760  (decimal)
    open_interest_usd: float
    mark_price: float
    premium: float
    timestamp: str                  # ISO UTC

    def to_dict(self) -> dict: ...

class PerpFundingFeed:
    def __init__(self,
                 info_url: str = HYPERLIQUID_INFO_URL,
                 assets: tuple[str, ...] = TRACKED_ASSETS,
                 data_file: Path = DATA_FILE,
                 timeout: int = REQUEST_TIMEOUT,
                 enabled: bool = True) -> None: ...

    # ── network (stdlib urllib, POST) ──
    def _post_info(self, body: dict) -> Optional[bytes]:
        """POST {type:...} to Hyperliquid with retry/backoff. None on failure. Never raises."""

    def _fetch_meta_and_ctxs(self) -> Optional[tuple[list, list]]:
        """Return (universe, assetCtxs) or None."""

    # ── normalization ──
    @staticmethod
    def _annualize(funding_1h: float) -> float:
        return round(funding_1h * HOURS_PER_YEAR, 8)

    def _normalize(self, universe: list, ctxs: list) -> list[PerpFundingRate]:
        """Map tracked assets → PerpFundingRate. Skips any asset missing/malformed."""

    # ── public ──
    def fetch(self) -> Optional[list[PerpFundingRate]]:
        """Live fetch + normalize. None if Hyperliquid unreachable. Never raises."""

    def get_rate(self, asset: str) -> Optional[float]:
        """Live funding_rate_annual (decimal) for one asset, or None.
        Reads from disk cache first (within freshness window) to avoid hammering the API."""

    def run(self) -> dict:
        """Fetch → write data/perp_funding_rates.json (+ history ring) atomically.
        Returns the written payload (or last good payload tagged stale=True on failure).
        This is the LaunchAgent entrypoint."""

    def load(self) -> dict:
        """Read data/perp_funding_rates.json, {} on error. Sets stale flag by age."""

# Module-level convenience (matches defi_llama_feed.get_apy pattern)
_SINGLETON: Optional[PerpFundingFeed] = None
def get_funding_annual(asset: str) -> Optional[float]: ...
```

**CLI:** `python3 -m spa_core.feeds.perp_funding_feed --run` (writes file),
`--show` (prints current snapshot read-only).

**Failure semantics:** if all retries fail, `run()` re-reads the last good file, sets
`stale=True`, keeps the history intact, and returns it. It never writes fabricated rates.

### 3.2 `spa_core/strategies/s_basis.py` (NEW) — tournament strategy

The strategy is a thin wrapper. It does **no math** — it builds `BasisTradeInput`s from
live data and delegates to `BasisTradeAnalyzer`.

```python
from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer, BasisTradeInput, BasisTradeResult,
)
from spa_core.feeds.perp_funding_feed import PerpFundingFeed

# Execution cost assumptions (round-trip bps) per structure.
DEFAULT_EXEC_COST_BPS = 15.0    # taker fees + slippage + 1 funding flip
MIN_NET_SPREAD_BPS_ENTER = 50.0 # GOOD or better
MIN_OPEN_INTEREST_USD = 50_000_000.0  # liquidity floor for the perp leg

@dataclass
class BasisSignal:
    asset: str
    structure: str                 # "synthetic_susde" | "explicit_long_usdc_short_perp"
    net_spread_bps: float
    edge_quality: str
    recommended_action: str
    target_weight: float           # fraction of S_BASIS sleeve [0,1]
    annual_pnl_usd: float

class SBasisStrategy:
    """Live basis-trade strategy for the SPA tournament.

    Reads perp_funding_rates.json + adapter_status.json, computes delta-neutral
    net spread per asset via BasisTradeAnalyzer, and returns an allocation signal.
    PAPER SIMULATION ONLY. Never imports execution/.
    """
    def __init__(self,
                 funding_feed: PerpFundingFeed | None = None,
                 analyzer: BasisTradeAnalyzer | None = None,
                 data_dir: Path = Path("data")) -> None: ...

    def _spot_yield_for(self, asset: str, adapter_status: dict) -> float:
        """Cash-carry leg yield (decimal). For explicit structure this is the USDC
        lending APY (e.g. aave_v3). For synthetic it is the sUSDe APY. Falls back to
        the best live T1 stablecoin APY if no direct match."""

    def evaluate(self) -> list[BasisSignal]:
        """Build BasisTradeInput per tracked asset → analyze_batch → rank.
        Returns [] if funding data is stale or no asset clears liquidity/edge floors."""

    def allocate(self, sleeve_capital_usd: float) -> dict[str, float]:
        """Convert signals to {leg_key: usd}. Delta-neutral: equal notional on
        long (USDC lend) and short (perp hedge) legs. Honors BTS risk caps
        (see §6). Returns {} when no ENTER signal → sleeve goes to T1 safe harbor."""

    def to_strategy_config(self) -> "StrategyConfig":
        """Adapter to the tournament's StrategyConfig dataclass (see §3.3)."""
```

**Delta-neutral framing for SPA's stablecoin mandate.** The default `structure` is
`explicit_long_usdc_short_perp`:

- Long leg: USDC lending on Aave (`aave_v3`) → cash carry `spot_yield_annual`.
- Short leg: ETH/BTC perp on Hyperliquid → harvests `funding_rate_annual` when positive.
- Net market exposure ≈ 0 (the perp short offsets nothing on the spot side because the
  collateral is a stablecoin — the "delta-neutral" property comes from the perp itself
  being funded by longs paying shorts; SPA captures funding without directional risk).

The synthetic `synthetic_susde` structure simply maps to the existing S8 sUSDe path and is
included so S_BASIS can rank both framings and the tournament picks the better one.

### 3.3 Tournament wiring — `StrategyConfig` slot

S_BASIS joins the registry exactly like S8–S13. Add to
`spa_core/paper_trading/strategy_registry.py`:

```python
S_BASIS = StrategyConfig(
    id="S_BASIS",
    name="Live Basis Trade (Funding Harvest)",
    description=(
        "Delta-neutral basis trade: long USDC lending cash-carry + short ETH/BTC "
        "perp on Hyperliquid, harvesting positive funding. Live funding via "
        "perp_funding_feed. ENTER only when net spread >= 50bps (GOOD+) AND "
        "funding positive AND perp OI >= $50M. Max 20% portfolio. "
        "Inactive (0%) when funding negative or stale → capital to T1 safe harbor. "
        "PAPER SIMULATION ONLY via SBasisStrategy."
    ),
    allocations={                 # nominal sleeve split; runtime overrides via allocate()
        "usdc_lend_leg":   0.50,  # long cash-carry (Aave USDC)
        "perp_short_leg":  0.50,  # short perp notional hedge
    },
    tier="T2",
    target_apy_min=0.0,           # 0% when inactive
    target_apy_max=24.0,
    kill_drawdown_pct=0.05,
    status="active",
    gate_condition=lambda apy_map: apy_map.get("perp_funding_eth", 0.0) >= 0.0,
    strategy_class="SBasisStrategy",
)
```

Then register it in `cycle_runner.py` in the same `MultiStrategyRunner` import block that
already wires S2–S13 (around `cycle_runner.py:1790–1900`):

```python
# ── BTS: S_BASIS Live Basis Trade ──────────────────────────────────────
try:
    from spa_core.paper_trading.strategy_registry import S_BASIS as _ms_sbasis
    from spa_core.strategies.s_basis import SBasisStrategy
    _ms_strategies.append(_ms_sbasis)   # joins S0..S65 in the tournament
    log.info("S_BASIS registered in tournament")
except ImportError as _sb_exc:
    log.warning("S_BASIS unavailable (%s) — tournament continues without it", _sb_exc)
```

The tournament evaluator (`tournament_evaluator.py`) and `PromotionEngine`
(`MP-373`) then score S_BASIS automatically. **Go-live rule:** S_BASIS may steer real
allocation only after the existing promotion machinery records **confidence > 0.75 for 7
consecutive days** — identical to every other strategy. No special-casing.

### 3.4 `spa_core/monitoring/bts_monitor.py` (NEW) — 15-min scanner + alerts

Built on the `peg_monitor.py` template: dataclass report, `AlertDispatcher` lazy-init with
1h dedup cooldown, atomic history ring, `format_telegram_message()`, fail-safe everywhere.

```python
DATA_DIR = Path("data")
OPP_FILE = DATA_DIR / "basis_trade_opportunities.json"
OPP_HISTORY_FILE = DATA_DIR / "basis_trade_opportunities_history.json"
STATUS_FILE = DATA_DIR / "bts_monitor_status.json"
HISTORY_MAX = 96               # 24h @ 15-min
EXCELLENT_BPS = 100.0
ALERT_COOLDOWN_S = 3600

@dataclass
class BTSOpportunity:
    asset: str
    structure: str
    spot_yield_annual: float
    perp_funding_annual: float
    gross_spread_bps: float
    net_spread_bps: float
    annual_pnl_usd: float
    edge_quality: str
    recommended_action: str
    open_interest_usd: float
    capital_usd: float
    def to_dict(self) -> dict: ...

class BTSMonitor:
    def __init__(self,
                 data_dir: Path = DATA_DIR,
                 use_alert_dispatcher: bool = True,
                 funding_feed: PerpFundingFeed | None = None,
                 strategy: "SBasisStrategy | None" = None) -> None: ...

    def _get_dispatcher(self): ...                 # lazy AlertDispatcher, dedup 1h

    def scan(self) -> list[BTSOpportunity]:
        """Read funding + adapter status → SBasisStrategy.evaluate() →
        BasisTradeAnalyzer.top_opportunities(5). Empty list on stale data."""

    def _load_previous_excellent(self) -> set[str]:
        """Assets that were EXCELLENT in the last opportunities snapshot."""

    def _detect_new_excellent(self, current: list[BTSOpportunity]) -> list[BTSOpportunity]:
        """EXCELLENT now (>=100bps net) that were NOT EXCELLENT 15 min ago."""

    def _create_alerts(self, new_excellent: list[BTSOpportunity]) -> int:
        """One AlertLevel.WARNING (BTS opportunity is good news, not a fault) per
        new EXCELLENT asset, deduped 1h. Falls back to log if dispatcher down."""

    def format_telegram_message(self) -> str:
        """<=1500 chars. Header + top opportunities table + best_net_spread."""

    def _save_opportunities(self, opps: list[BTSOpportunity], stale: bool) -> None:
        """Atomic write of basis_trade_opportunities.json + push to history ring."""

    def _save_status(self, opps, errors) -> None:
        """Atomic write of bts_monitor_status.json heartbeat (agent_health reads it)."""

    def run(self) -> dict:
        """LaunchAgent entrypoint: scan → save → alert-on-new-EXCELLENT → heartbeat →
        invoke BTSExitMonitor. Always returns a report dict (fail-safe)."""
```

**Alerting rule (from spec):** alert fires only on a *transition* into EXCELLENT — an asset
that is `>=100bps net` now and was not in the previous snapshot's EXCELLENT set. This,
combined with the 1h dedup, prevents alert spam from launchd re-runs every 15 min. Dedup
state persists via `AlertDispatcher`'s `alert_dispatcher_dedup.json` (the same fix applied
to peg_monitor).

### 3.5 `spa_core/analytics/bts_exit_monitor.py` (NEW) — exit logic

Lives in `analytics/` (like `basis_trade_analyzer.py`) because it is advisory math over
positions; it emits exit *signals*, it does not unwind anything (paper). It reads the
current paper positions and the live funding, then emits `data/bts_exit_signals.json`.

```python
DATA_DIR = Path("data")
ACTIVE_FILE = DATA_DIR / "bts_active_trades.json"
EXIT_FILE = DATA_DIR / "bts_exit_signals.json"
KILL_SWITCH_FILE = DATA_DIR / "kill_switch_status.json"   # reuses MP-108 kill-switch
EVENTS_MAX = 50

# Exit thresholds
FUNDING_NEGATIVE_FLOOR = 0.0       # any negative annual funding triggers
NET_SPREAD_FLOOR_BPS = 10.0        # below this the trade is no longer worth carry
MARGIN_BUFFER_MIN = 0.20           # 20% liquidation buffer on the short perp leg
FUNDING_REVERSAL_ANNUAL = -0.05    # hard exit if annual funding < -5%

@dataclass
class BTSExitDecision:
    asset: str
    entry_net_spread_bps: float
    current_net_spread_bps: float
    current_funding_annual: float
    margin_buffer_pct: float
    exit_signal: bool
    exit_reasons: list[str]        # subset of: funding_negative, funding_reversal,
                                   # net_spread_below_floor, margin_buffer_low, kill_switch
    severity: str                  # "LOW" | "MEDIUM" | "HIGH"
    def to_dict(self) -> dict: ...

class BTSExitMonitor:
    def __init__(self, data_dir: Path = DATA_DIR,
                 funding_feed: PerpFundingFeed | None = None) -> None: ...

    def _kill_switch_active(self) -> bool:
        """Read kill_switch_status.json (MP-108). True → exit ALL basis trades."""

    def evaluate_position(self, position: dict, funding_annual: float) -> BTSExitDecision:
        """Apply all exit conditions to one active basis trade."""

    def run(self) -> dict:
        """Read active trades + live funding → evaluate each → write bts_exit_signals.json
        (+ events ring). Returns report. Fail-safe. Called by bts_monitor.run() and
        consulted by cycle_runner before holding basis positions."""
```

**Exit conditions (OR-combined → `exit_signal=True`):**

| Condition | Threshold | Reason code | Severity |
| --- | --- | --- | --- |
| Funding turned negative | `funding_annual < 0` | `funding_negative` | MEDIUM |
| Funding reversal (hard) | `funding_annual < -5%` | `funding_reversal` | HIGH |
| Net spread collapsed | `net_spread_bps < 10` | `net_spread_below_floor` | MEDIUM |
| Liquidation buffer low | `margin_buffer_pct < 20%` | `margin_buffer_low` | HIGH |
| Manual / global kill | `kill_switch_status.active` | `kill_switch` | HIGH |

### 3.6 LaunchAgents (NEW plists, copy the sky_monitor template)

`scripts/com.spa.perp-funding-feed.plist`:

```xml
<key>Label</key><string>com.spa.perp-funding-feed</string>
<key>ProgramArguments</key>
<array>
  <string>/Users/yuriikulieshov/miniconda3/bin/python3</string>
  <string>-m</string><string>spa_core.feeds.perp_funding_feed</string>
  <string>--run</string>
</array>
<key>WorkingDirectory</key><string>/Users/yuriikulieshov/Documents/SPA_Claude</string>
<key>StartInterval</key><integer>900</integer>   <!-- every 15 min -->
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>/tmp/spa_perp_funding_feed.log</string>
<key>StandardErrorPath</key><string>/tmp/spa_perp_funding_feed_err.log</string>
```

`scripts/com.spa.bts-monitor.plist` — identical shape, `Label = com.spa.bts-monitor`,
`spa_core.monitoring.bts_monitor`, `StartInterval 900`, logs to `/tmp/spa_bts_monitor*.log`.

> **Ordering:** the feed runs at `RunAtLoad` and every 900 s; bts-monitor also every 900 s.
> Because both use `StartInterval` (not a calendar), they drift independently. The monitor
> reads whatever the feed last wrote and uses the `stale` flag — it does not require strict
> ordering. (If tighter coupling is ever wanted, `bts_monitor.run()` can call
> `PerpFundingFeed.run()` itself at the top; the design allows either.)

**Install (matches repo convention):**

```bash
cp scripts/com.spa.perp-funding-feed.plist ~/Library/LaunchAgents/
cp scripts/com.spa.bts-monitor.plist        ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spa.perp-funding-feed.plist
launchctl load ~/Library/LaunchAgents/com.spa.bts-monitor.plist
```

### 3.7 Dashboard "Basis" tab (modify `index.html` + dashboard renderer)

Add a tab/panel that reads three live endpoints (all already served):

- `GET /api/live/data/basis_trade_opportunities.json`
- `GET /api/live/data/perp_funding_rates.json`
- `GET /api/live/data/bts_exit_signals.json`

Panel contents:

1. **Opportunities table** — `asset | spot_yield | perp_funding | net_spread_bps |
   edge_quality | action`, colored by `edge_quality`
   (EXCELLENT=green, GOOD=teal, MARGINAL=amber, UNATTRACTIVE=gray).
2. **Funding chart** — rolling 7-day `funding_rate_annual` for ETH & BTC, sourced from
   `perp_funding_rates.json.history` (one read, no extra endpoint).
3. **Active trades + exits** — current basis positions from `bts_active_trades.json` and
   any `bts_exit_signals.json.active[*].exit_signal == true` rows flagged red with reasons.
4. **Summary chips** — best asset, best net spread (bps), count of EXCELLENT/GOOD,
   `funding_data_stale` warning badge.

Implementation note: follow the existing renderer's `dataBase` pattern — the dashboard
already points at `/api/live/data` for live mode, so the new panel just adds three fetches
and a render function; **no FastAPI change**.

---

## 4. Sprint Plan

Four phases, each independently shippable and testable. Each task lists exact file paths.
Test convention: `tests/test_<module>.py`, stdlib `unittest`, mock network with fixtures.

### Phase 1 — Data Feed (Feed)

**Goal:** live funding rates on disk every 15 min.

| Task | Files |
| --- | --- |
| 1.1 Implement `PerpFundingFeed` (POST `metaAndAssetCtxs`, normalize, annualize, ring history) | `spa_core/feeds/perp_funding_feed.py` |
| 1.2 Atomic write + `stale` flag + last-good fallback | (same) |
| 1.3 Module-level `get_funding_annual(asset)` singleton | (same) |
| 1.4 CLI `--run` / `--show` | (same) |
| 1.5 Unit tests: normalization, annualization (`1h*8760`), stale detection, fail-safe on HTTP error, ring-buffer cap | `tests/test_perp_funding_feed.py` |
| 1.6 LaunchAgent | `scripts/com.spa.perp-funding-feed.plist` |
| 1.7 Smoke: live fetch writes valid `data/perp_funding_rates.json` | manual / `--run` |

**Exit criteria:** `data/perp_funding_rates.json` has live ETH/BTC/SOL annual rates;
tests green; agent loads.

### Phase 2 — Strategy (S_BASIS in tournament)

**Goal:** S_BASIS ranks against S0–S65; reuses analyzer; no execution import.

| Task | Files |
| --- | --- |
| 2.1 Implement `SBasisStrategy` (evaluate/allocate, reuse `BasisTradeAnalyzer`) | `spa_core/strategies/s_basis.py` |
| 2.2 Add `S_BASIS` `StrategyConfig` to registry | `spa_core/paper_trading/strategy_registry.py` |
| 2.3 Register S_BASIS in `MultiStrategyRunner` block | `spa_core/paper_trading/cycle_runner.py` (~L1790–1900) |
| 2.4 Spot-yield resolver from `adapter_status.json` (USDC lending leg) | `spa_core/strategies/s_basis.py` |
| 2.5 Risk caps in `allocate()` (max 20% sleeve, liquidity floor, venue cap) | (same) |
| 2.6 Unit tests: ENTER/MONITOR/SKIP mapping from live inputs, stale → empty, gate inactive when funding negative, allocate respects caps | `tests/test_s_basis.py` |
| 2.7 Integration test: cycle_runner includes S_BASIS, tournament emits a score | `tests/test_cycle_runner_sbasis.py` |

**Exit criteria:** a full cycle run logs S_BASIS in the tournament ranking; advisory-only
(does not steer allocation until promotion confidence ≥ 0.75 × 7 days).

### Phase 3 — Monitor + Alerts (Monitor)

**Goal:** 15-min opportunity scan, top-5 file, Telegram on new EXCELLENT, exit signals.

| Task | Files |
| --- | --- |
| 3.1 Implement `BTSMonitor.scan/run` (reuse `SBasisStrategy` + `top_opportunities`) | `spa_core/monitoring/bts_monitor.py` |
| 3.2 New-EXCELLENT diff + `AlertDispatcher` (1h dedup) + `format_telegram_message` | (same) |
| 3.3 Heartbeat `bts_monitor_status.json` | (same) |
| 3.4 Implement `BTSExitMonitor` (5 exit conditions, kill-switch read) | `spa_core/analytics/bts_exit_monitor.py` |
| 3.5 Wire exit monitor into `bts_monitor.run()` and consult in `cycle_runner` | both |
| 3.6 LaunchAgent | `scripts/com.spa.bts-monitor.plist` |
| 3.7 Unit tests: top-5 ranking, new-EXCELLENT transition (no spam on re-run), each exit condition, kill-switch override, fail-safe | `tests/test_bts_monitor.py`, `tests/test_bts_exit_monitor.py` |
| 3.8 Confirm `agent_health_monitor` auto-discovers `com.spa.bts-monitor` | `tests/test_agent_health_monitor.py` (extend) |

**Exit criteria:** monitor writes `basis_trade_opportunities.json` every 15 min; a forced
EXCELLENT opportunity sends exactly one Telegram alert; `agent_health` shows the agent.

### Phase 4 — Dashboard (Dashboard)

**Goal:** Basis tab live on earn-defi.com.

| Task | Files |
| --- | --- |
| 4.1 Add "Basis" tab/panel markup | `index.html` (or dashboard template path in repo) |
| 4.2 Opportunities table renderer (color by edge_quality) | dashboard JS |
| 4.3 7-day funding chart from `perp_funding_rates.json.history` | dashboard JS |
| 4.4 Active trades + exit-signal rows from `bts_exit_signals.json` | dashboard JS |
| 4.5 Stale-data badge + summary chips | dashboard JS |
| 4.6 Verify GitHub Actions deploy renders the panel (Cloudflare Pages) | CI |

**Exit criteria:** Basis tab renders live data via `/api/live/data/*`; no FastAPI change
needed (generic passthrough already serves the files).

---

## 5. Integration Points

| Existing SPA component | How BTS connects | Change required |
| --- | --- | --- |
| `cycle_runner.py` MultiStrategyRunner | Register `S_BASIS` in the S2–S13 import block | +~8 lines |
| `strategy_registry.py` | Add `S_BASIS` `StrategyConfig` | +1 config |
| `tournament_evaluator.py` / `PromotionEngine` (MP-373) | Scores & promotes S_BASIS automatically | none |
| `BasisTradeAnalyzer` (`analytics/basis_trade_analyzer.py`) | Reused unchanged as the math core | none |
| `defi_llama_feed.py` pattern | `perp_funding_feed.py` clones its resilience model | new file, same shape |
| `adapter_status.json` | S_BASIS reads USDC lending APY for the cash-carry leg | read-only |
| `AlertDispatcher` / `telegram_client.py` | BTSMonitor dispatches new-EXCELLENT alerts | none (reuse) |
| `kill_switch_status.json` (MP-108) | BTSExitMonitor honors the global kill switch | read-only |
| `agent_health_monitor.py` | Auto-discovers `com.spa.bts-monitor.plist` via glob; reads `bts_monitor_status.json` heartbeat | none (auto) |
| FastAPI `server.py:893` generic passthrough | Serves `basis_trade_opportunities.json`, `perp_funding_rates.json`, `bts_exit_signals.json` for free | none |
| Dashboard `dataBase=/api/live/data` | New Basis panel adds 3 fetches | dashboard only |
| LaunchAgents (`scripts/*.plist`) | 2 new plists (feed + monitor) | new files |
| `spa_core/utils/atomic.atomic_save` | All BTS writers use it | reuse |

**Key insight:** the only files that require modification (not creation) are
`strategy_registry.py`, `cycle_runner.py`, and the dashboard markup/JS. Everything else is
additive, and the API/health/alert infrastructure absorbs BTS with zero changes.

---

## 6. Risk Considerations

### 6.1 BTS-specific allocation rules (enforced in `SBasisStrategy.allocate()`)

| Rule | Value | Enforcement |
| --- | --- | --- |
| Max portfolio in basis trades | **20%** of total capital ($20K of $100K) | hard cap; separate from the stablecoin concentration limit so it does not double-count |
| Per-venue counterparty cap | **50%** of BTS sleeve on any single venue (Hyperliquid) | with only one perp venue today this effectively caps the explicit structure at 10% of portfolio until a second venue is added |
| Perp liquidity floor | perp `open_interest_usd >= $50M` | assets below floor are skipped (no signal) |
| Min entry edge | `net_spread_bps >= 50` (GOOD+) | `MONITOR`/`SKIP` never allocate |

These are checked *in addition to* the deterministic `RiskPolicy` gate
(`spa_core/risk/policy.py`) that every paper trade already passes through in
`cycle_runner` (concentration caps, T2 total, TVL floor, drawdown kill-switch).

### 6.2 Funding-rate reversal

Funding flips negative when shorts crowd in (shorts pay longs). The exit monitor treats any
negative annual funding as a `MEDIUM` exit and `< -5%` as a `HIGH` hard exit
(`FUNDING_REVERSAL_ANNUAL`). S_BASIS's `gate_condition` also refuses *new* entries while
funding is negative, so a reversal both blocks fresh allocation and signals unwind of
existing carry.

### 6.3 Liquidation buffer on the short perp leg

The short perp must maintain `margin_buffer_pct >= 20%`. In paper mode this is computed
from notional and assumed initial margin; in any future live mode it must read the actual
account margin from Hyperliquid before this subsystem is allowed near real capital.
`margin_buffer_low` is a `HIGH`-severity exit.

### 6.4 Data-staleness / source risk

Hyperliquid is a single source. If it is unreachable, `perp_funding_feed` writes
`stale=true` and keeps the last good snapshot; S_BASIS and BTSMonitor treat stale data as
**no signal** (empty opportunities, no allocation). The system fails to *cash/T1 safe
harbor*, never to a fabricated rate. A second venue (Binance/Bybit funding, or
on-chain dYdX) is a recommended follow-up to remove the single-source dependency before
go-live.

### 6.5 Go-live gating

BTS stays advisory until the standard promotion path clears it: **confidence > 0.75 for 7+
consecutive days** in the tournament, the same bar as S0–S65. No code path lets S_BASIS
move real capital before then. Even after promotion, the 20% cap, venue cap, exit monitor,
and global kill switch remain in force.

### 6.6 No execution coupling

Per RULES.md, none of the new modules import `spa_core/execution/` (wallet/router/signer).
BTS is simulation-and-advisory end to end in this design; turning on real perp execution is
a separate, explicitly-gated project (would require a Hyperliquid signer in `execution/`
and its own ADR).

---

## 7. Success Metrics

**Phase-level (functional):**

- F1: `data/perp_funding_rates.json` refreshes every 15 min with live ETH/BTC/SOL annual
  rates; `funding_feed_age_minutes < 20` in the heartbeat ≥ 95% of the time.
- F2: S_BASIS appears in the tournament ranking on every cycle (`strategy_*.json` shows an
  `S_BASIS` row with a composite score).
- F3: `bts_monitor` writes `basis_trade_opportunities.json` every 15 min; a forced
  EXCELLENT opportunity produces **exactly one** Telegram alert (no spam over repeated
  runs, verified against the 1h dedup).
- F4: `agent_health_monitor` lists `com.spa.bts-monitor` and `com.spa.perp-funding-feed`
  as healthy; stale heartbeat surfaces as a WARNING.
- F5: Basis tab on earn-defi.com renders the opportunities table, the 7-day funding chart,
  and any active exit signals.

**Subsystem-level (quality):**

- Q1: `perp_funding_feed`, `s_basis`, `bts_monitor`, `bts_exit_monitor` each ship with a
  test suite; all green; coverage ≥ existing analyzer (100%).
- Q2: Zero new external dependencies (stdlib-only confirmed by CI lint MP-309).
- Q3: Kill-switch test proves all basis positions emit `exit_signal=True` when
  `kill_switch_status.active` is set.
- Q4: Staleness test proves no allocation and no fabricated rate when Hyperliquid is down.

**Outcome-level (is it actually working as a strategy):**

- O1: Over a 7-day paper window, S_BASIS's realized net spread tracks the analyzer's
  predicted `net_spread_bps` within tolerance (predicted vs. paper, like MP-140's
  Spearman backtest-vs-paper check).
- O2: When funding goes negative in the window, the exit monitor fires and the paper sleeve
  rotates to T1 within one cycle — i.e. BTS captures funding in positive regimes and avoids
  bleed in negative ones.
- O3: S_BASIS reaches promotion confidence > 0.75 for 7 days *only* in genuinely favorable
  funding regimes — confirming the gate is honest, not over-fit.

---

## 8. Appendix: SPA Conventions This Design Obeys

Verified against the existing codebase while designing:

- **`defi_llama_feed.py`** — `perp_funding_feed.py` copies its `_fetch_with_retry`
  (3 attempts, exponential backoff 1/2/4 s, rotating User-Agents), gzip handling,
  module-level singleton + convenience function, and "return `None`, never fabricate"
  contract. Difference: Hyperliquid needs **POST** with a JSON body, not GET.
- **`peg_monitor.py`** — `bts_monitor.py` copies its dataclass-report shape,
  `AlertDispatcher` lazy-init with `suppress_duplicates=True, cooldown_seconds=3600`
  (the exact fix that stopped 15-min alert spam), atomic history ring buffer, and
  `format_telegram_message()` ≤1500 chars.
- **`telegram_client.py`** — alerts route through `AlertDispatcher` → Telegram; credentials
  come from Keychain (`TELEGRAM_BOT_TOKEN_SPA`/`TELEGRAM_CHAT_ID_SPA`), never files.
- **`cycle_runner.py`** — S_BASIS slots into the existing `MultiStrategyRunner` block
  (S2–S13 pattern, ~L1790–1900) and is scored by `tournament_evaluator`/`PromotionEngine`;
  advisory-only under ADR-033 `strategy_loop_mode` until promoted.
- **`strategy_registry.py`** — `S_BASIS` is a standard `StrategyConfig` with `gate_condition`,
  `kill_drawdown_pct`, `tier="T2"`, mirroring `S8_DELTA_NEUTRAL_SUSDE`.
- **`server.py:893`** — `/api/live/data/{filename}.json` generic passthrough serves the new
  files with no API change (traversal-safe, no-cache headers already set).
- **`agent_health_monitor.py`** — globs `com.spa.*.plist`; new agents are monitored
  automatically; `bts_monitor_status.json` provides the heartbeat it reads.
- **`scripts/com.spa.sky_monitor.plist`** — template for both new plists (miniconda python,
  `WorkingDirectory`, `-m` module invocation, `/tmp` logs).
- **`spa_core/utils/atomic.atomic_save`** — used by every BTS writer for atomic JSON.
- **MP-108 kill switch** — `bts_exit_monitor` reads `kill_switch_status.json` to honor the
  global stop.

---

*End of BTS_INTEGRATION_ARCHITECTURE.md*
