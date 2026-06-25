"""
strategy_lab/base.py — the keystone contract for the Strategy Lab.

Every strategy (new candidates AND wrapped baselines) implements the `Strategy` ABC, so they
are interchangeable across the shared backtest harness and the live paper-trading service.
Adding a new strategy = one new class implementing this interface + one config block. The
harness never changes.

stdlib only, deterministic. No risk LIMITS live here (those are in spa_core.risk.policy);
only the abstract kill-check hook, which each strategy fills from its config thresholds.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class InvalidDataError(ValueError):
    """Raised by the data layer when an API response fails schema validation or a required
    field is missing/empty. Fail-CLOSED: callers must NOT substitute a silent default."""


# ──────────────────────────────────────────────────────────────────────────────
# Market data contract — what step()/kill_check() receive each tick.
# The data layer (strategy_lab/data/) produces these; backtest feeds historical
# snapshots, paper-trading feeds live ones. SAME shape for both (one source of truth).
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class MarketSnapshot:
    """One point-in-time market state. Fields may be None when a feed had no valid datapoint
    for this date; `gaps` lists those field names. Strategies MUST check validity (use
    require()/get()) rather than assume a value — there are no silent defaults."""

    date: str  # ISO date "YYYY-MM-DD"
    eth_price_usd: Optional[float] = None
    funding_rate_8h: Optional[float] = None          # ETH perp funding per 8h interval (decimal, e.g. 0.0001)
    lrt_price_usd: Dict[str, float] = field(default_factory=dict)     # {"eeth": 3450.0, "ezeth": ...}
    lrt_eth_ratio: Dict[str, float] = field(default_factory=dict)     # {"eeth": 1.03} — for depeg detection
    restaking_apy: Dict[str, float] = field(default_factory=dict)     # {"eeth": 0.032} decimal annual
    defi_apy: Dict[str, float] = field(default_factory=dict)          # {protocol: apy_decimal}
    # — BTC sleeve fields (parallel to the ETH ones; for btc_neutral / btc_lending_sleeve) —
    btc_price_usd: Optional[float] = None            # BTC reference price (WBTC via DeFiLlama coins)
    btc_funding_rate_8h: Optional[float] = None      # BTC perp (BTCUSDT) funding per 8h (5-venue median)
    btc_wrapper_price_usd: Dict[str, float] = field(default_factory=dict)  # {"tbtc": 64000.0, "cbbtc": ...}
    btc_wrapper_ratio: Dict[str, float] = field(default_factory=dict)      # {"tbtc": 0.999} wrapper/BTC (depeg)
    btc_lending_apy: Dict[str, float] = field(default_factory=dict)        # {"tbtc": 0.004} decimal annual (the floor)
    gaps: set = field(default_factory=set)            # names of fields that were invalid/missing
    ff_filled: set = field(default_factory=set)       # names that were forward-filled (within limit)

    # — accessors: every getter returns (value, valid) so strategies handle gaps explicitly —
    def get_eth_price(self) -> Tuple[Optional[float], bool]:
        return self.eth_price_usd, self.eth_price_usd is not None

    def get_funding(self) -> Tuple[Optional[float], bool]:
        return self.funding_rate_8h, self.funding_rate_8h is not None

    def get_lrt_price(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.lrt_price_usd.get(symbol)
        return v, v is not None

    def get_lrt_ratio(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.lrt_eth_ratio.get(symbol)
        return v, v is not None

    def get_restaking_apy(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.restaking_apy.get(symbol)
        return v, v is not None

    def get_defi_apy(self, protocol: str) -> Tuple[Optional[float], bool]:
        v = self.defi_apy.get(protocol)
        return v, v is not None

    # — BTC accessors (parallel to the ETH ones) —
    def get_btc_price(self) -> Tuple[Optional[float], bool]:
        return self.btc_price_usd, self.btc_price_usd is not None

    def get_btc_funding(self) -> Tuple[Optional[float], bool]:
        return self.btc_funding_rate_8h, self.btc_funding_rate_8h is not None

    def get_btc_wrapper_price(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.btc_wrapper_price_usd.get(symbol)
        return v, v is not None

    def get_btc_wrapper_ratio(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.btc_wrapper_ratio.get(symbol)
        return v, v is not None

    def get_btc_lending_apy(self, symbol: str) -> Tuple[Optional[float], bool]:
        v = self.btc_lending_apy.get(symbol)
        return v, v is not None

    def require(self, getter_name: str, *args):
        """Return a value or raise InvalidDataError (fail-closed). e.g. require('eth_price')."""
        fn = getattr(self, "get_" + getter_name, None)
        if fn is None:
            raise InvalidDataError(f"unknown field {getter_name!r}")
        val, ok = fn(*args)
        if not ok:
            raise InvalidDataError(f"{getter_name}{args or ''} missing/invalid on {self.date}")
        return val


# ──────────────────────────────────────────────────────────────────────────────
# Position + result/metric/kill dataclasses
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Position:
    """A virtual position leg. `kind` ∈ {lending, lp, lrt, spot, perp_short, perp_long, cash}."""
    asset: str
    kind: str
    notional_usd: float
    qty: float = 0.0
    entry_price: Optional[float] = None
    meta: Dict = field(default_factory=dict)


@dataclass
class KillResult:
    triggered: bool
    reason: str = ""
    ts: str = ""


@dataclass
class StrategyMetrics:
    """Standard comparison set across all strategies. Filled by metrics.py from the equity
    + event series; strategies may also expose live partials via metrics()."""
    net_apy_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    volatility_pct: Optional[float] = None
    beta_to_eth: Optional[float] = None              # ~0 for Variant N, ~1 for Variant D
    funding_drag_pct: Optional[float] = None         # cumulative funding cost as % (Variant N)
    corr_to_stable_blend: Optional[float] = None     # correlation to the stable yield benchmark
    tail_eth_down20_funding_flip_pct: Optional[float] = None  # P&L in the joint stress scenario
    beats_rwa_floor: Optional[bool] = None           # risk-adjusted vs the RWA risk-free floor
    extra: Dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# The Strategy interface — all strategies (candidates + wrapped baselines) implement this.
# ──────────────────────────────────────────────────────────────────────────────
class Strategy(abc.ABC):
    """Pluggable strategy. The harness calls: init() once, then step(snapshot) per tick
    (which accrues yield, settles funding, rebalances) and kill_check(snapshot) per tick;
    metrics() any time; positions() to inspect state.

    Identity attributes (set by subclass): id, name, is_advisory, mandate
    ('stable' | 'neutral' | 'directional')."""

    id: str = "base"
    name: str = "Base"
    is_advisory: bool = True          # all new candidates are advisory until go-live
    mandate: str = "stable"

    @abc.abstractmethod
    def init(self, capital: float, config: dict) -> None:
        """Initialise virtual book with starting capital and the strategy's config block
        (thresholds X/Y/Z/N etc. — from the SSOT config, never hardcoded)."""

    @abc.abstractmethod
    def positions(self) -> List[Position]:
        """Current virtual positions."""

    @abc.abstractmethod
    def step(self, market: MarketSnapshot) -> None:
        """Advance one tick: accrue yield, settle funding, rebalance as needed. Must be
        deterministic given the same market input and prior state."""

    @abc.abstractmethod
    def metrics(self) -> StrategyMetrics:
        """Current standard metrics (partials allowed live; full set computed by metrics.py)."""

    @abc.abstractmethod
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        """Evaluate kill conditions. FAIL-CLOSED: on invalid data or an internal error the
        strategy must return triggered=True (safe state), never silently continue."""

    # — shared helpers (not abstract) —
    def equity(self) -> float:
        """Total virtual equity = sum of position notionals (override if a strategy tracks
        equity differently)."""
        return round(sum(p.notional_usd for p in self.positions()), 2)
