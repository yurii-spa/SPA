"""
spa_core/strategy_lab/strategies/eth_lst_neutral.py — ETH LST Neutral (the SAFE ETH-yield sleeve).

WHY THIS, NOT THE LRT VARIANTS
    Our Lab already proves (variant_n / variant_d, real 2024-06 → 2026-06 window) that RESTAKING
    (LRT) yield DIES in an ETH crash: ezETH fell ~-79% in under an hour on 24-Apr-2024, and our
    variant_n hit its depeg kill in Aug-2024. This strategy offers ETH yield the SAFE way:
    PLAIN STAKING (LSTs — stETH/rETH, NOT LRTs), delta-hedged to beta ≈ 0. LSTs sit much closer
    to their ETH peg than LRTs, so the depeg residual that killed the LRT variants is far smaller
    here — we use a TIGHTER depeg kill (Y) to reflect that.

STRATEGY (delta-neutral to ETH, beta ≈ 0):
    LST spot leg (stETH or rETH) + a short ETH-perp leg sized to the spot (hedge_ratio).
    Income = staking yield + (±) perp funding. The ETH price move in the spot leg is cancelled by
    the short perp (hedge_ratio ≈ 1), so equity barely moves on an ETH swing (beta ≈ 0). The
    surviving residual is the LST/ETH ratio drift — which for an LST is small by construction.

ACCOUNTING (per tick = one day) — identical mechanics to Variant N:
  - LST spot value (USD) = lst_qty * eth_price * lst_eth_ratio  (carries ETH price AND ratio).
  - Short perp price P&L over the tick = -(eth_price_new - eth_price_old) * perp_qty (pure ETH).
  - Net ETH-price exposure ≈ 0; the residual is the LST/ETH ratio drift (depeg).

FUNDING-SIGN CONVENTION
  A SHORT perp RECEIVES funding when funding_rate is POSITIVE (longs pay shorts), PAYS when
  NEGATIVE. Per settlement: pnl += funding_rate * perp_notional. Funding settles
  `funding_settles_per_day` times per tick. Cumulative funding tracked for funding_drag.

KILL CONDITIONS (FAIL-CLOSED — mirror Variant N, tighter depeg)
  (a) funding_rate continuously below `funding_kill_threshold` (X) for ≥ `funding_kill_hours` (N);
  (b) LST depeg: lst_eth_ratio dropped > `lst_depeg_kill_pct` (Y)% below the entry ratio,
      MEASURED ON A SMOOTHED, PERSISTENT signal (see below) — Y is SMALLER than the LRT
      variant's because LSTs are far tighter to peg than LRTs;
  (c) any required market datapoint invalid → triggered=True (never silently continue).

DEPEG SIGNAL SMOOTHING (the FALSE-depeg fix — same root + remedy as Variant N; see
  docs/GLOBAL_AUDIT, memory note "historical-apy-axis-misaligned"):
  DeFiLlama daily /chart points for the LST and for ETH are each the LAST intraday print
  bucketed to the same UTC calendar day; on a volatile crash day those two prints can land at
  different intraday moments, so lst/eth produces a SPURIOUS one-day ratio spike (e.g. stETH
  showed 0.95 → 1.14 → 0.97 in Aug-2024 while the real peg held 0.999–1.001). The TIGHT 1%
  LST kill is especially exposed to this. To keep REAL sustained depegs detectable while
  ignoring 1-day artifacts: evaluate the depeg on a SHORT TRAILING MEDIAN of the ratio
  (`depeg_median_window` ticks — a lone outlier in either direction is rejected) AND require the
  depeg to PERSIST for ≥ `depeg_persist_ticks` consecutive ticks before killing. Both are config
  values (never hardcoded); conservative defaults (window 3, persist 2) apply if a config omits
  them. A 1-day artifact never persists; a real depeg does.

NOTE: the LST price + ratio + staking-APY flow through the SAME snapshot fields the LRT variants
use (lrt_price_usd / lrt_eth_ratio / restaking_apy maps; see data/price_feed.py RATIO_SYMBOLS and
data/restaking_feed.py SELECTORS). For an LST, "restaking_apy" is simply the plain staking APY.

mandate = "neutral", is_advisory = True (advisory until canary, per the SAFE-sleeve mandate).
stdlib-only, deterministic. LLM FORBIDDEN — no model calls anywhere in this file.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import List, Optional

from spa_core.strategy_lab.base import (
    InvalidDataError,
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)

# Hours represented by ONE perp funding observation (a full day's funding per tick).
_HOURS_PER_DAY = 24.0

# Conservative defaults for the depeg-signal smoothing/persistence (used only when a config omits
# the keys). They MUST still let a real sustained depeg through while rejecting a 1-day DeFiLlama
# timestamp-misalignment artifact.
_DEFAULT_DEPEG_MEDIAN_WINDOW = 3   # trailing-median window (ticks) for the depeg signal
_DEFAULT_DEPEG_PERSIST_TICKS = 2   # consecutive breaching ticks required before a kill


def _trailing_median(values: List[float]) -> float:
    """Deterministic median of the (already short) trailing window. Empty → 0.0."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


class EthLstNeutral(Strategy):
    """ETH LST Neutral — delta-neutral PLAIN-STAKING LST (stETH/rETH) + short ETH perp (β ≈ 0).

    The SAFE ETH-yield sleeve: staking yield with the ETH price hedged out, using LSTs (tight to
    peg) rather than the LRTs that died in the crashes the existing variants reproduce."""

    id = "eth_lst_neutral"
    name = "ETH LST Neutral (delta-neutral stETH/rETH + perp short)"
    is_advisory = True
    mandate = "neutral"

    def __init__(self) -> None:
        # config-sourced thresholds (filled in init(); never hardcoded)
        self._lst_symbol: str = ""
        self._hedge_ratio: float = 0.0
        self._funding_kill_threshold: float = 0.0
        self._funding_kill_hours: float = 0.0
        self._lst_depeg_kill_pct: float = 0.0
        self._depeg_median_window: int = _DEFAULT_DEPEG_MEDIAN_WINDOW
        self._depeg_persist_ticks: int = _DEFAULT_DEPEG_PERSIST_TICKS
        self._funding_settles_per_day: int = 0
        self._gas_usd: float = 0.0
        self._slippage_bps: float = 0.0
        self._rebalance_bps: float = 0.0  # drift band before a hedge rebalance is forced

        # book state
        self._capital: float = 0.0
        self._equity: float = 0.0
        self._cash: float = 0.0  # accrued staking/funding/costs (USD), not price-exposed

        # LST spot leg
        self._lst_qty: float = 0.0          # units of LST held
        self._lst_entry_eth: float = 0.0    # ETH price at entry
        self._lst_entry_ratio: float = 0.0  # LST/ETH ratio at entry (the "peg" reference)

        # short ETH perp leg
        self._perp_qty: float = 0.0         # ETH units shorted (positive magnitude)
        self._perp_notional_entry: float = 0.0
        self._mark_eth: float = 0.0         # last ETH price the perp was marked at

        # running trackers
        self._cum_funding: float = 0.0      # cumulative funding P&L (USD); + = received
        self._cum_staking: float = 0.0      # cumulative staking yield (USD)
        self._perp_pnl: float = 0.0         # cumulative short-perp PRICE P&L (USD)
        self._sub_threshold_hours: float = 0.0  # consecutive hours funding < kill threshold
        self._ratio_window: List[float] = []    # trailing raw ratios (for the depeg median signal)
        self._depeg_streak: int = 0             # consecutive ticks the SMOOTHED depeg breached Y
        self._initialised = False
        self._killed = False
        self._kill_reason = ""

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        if config is None:
            raise InvalidDataError("eth_lst_neutral: config block is required")
        self._capital = float(capital)
        if self._capital <= 0:
            raise InvalidDataError(
                f"eth_lst_neutral: capital must be positive, got {capital!r}"
            )

        self._lst_symbol = str(config["lst_symbol"])
        self._hedge_ratio = float(config["hedge_ratio"])
        self._funding_kill_threshold = float(config["funding_kill_threshold"])
        self._funding_kill_hours = float(config["funding_kill_hours"])
        self._lst_depeg_kill_pct = float(config["lst_depeg_kill_pct"])
        # Depeg-signal smoothing/persistence (config-sourced; conservative defaults if omitted).
        self._depeg_median_window = max(
            1, int(config.get("depeg_median_window", _DEFAULT_DEPEG_MEDIAN_WINDOW))
        )
        self._depeg_persist_ticks = max(
            1, int(config.get("depeg_persist_ticks", _DEFAULT_DEPEG_PERSIST_TICKS))
        )

        # global-block params (cost + funding cadence) — passed through the same config dict
        self._funding_settles_per_day = int(config["funding_settles_per_day"])
        self._gas_usd = float(config["gas_usd_per_rebalance"])
        self._slippage_bps = float(config["slippage_bps"])
        self._rebalance_bps = float(config["rebalance_bps"])

        self._equity = self._capital
        self._cash = 0.0
        self._initialised = True
        # Legs open lazily on the first step() once we have a real ETH price + ratio.

    def _open_legs(self, eth_price: float, ratio: float) -> None:
        """Open the LST spot + short ETH perp legs from the first valid market tick."""
        lst_notional = self._capital
        lst_unit_price = eth_price * ratio  # USD per LST unit
        self._lst_qty = lst_notional / lst_unit_price
        self._lst_entry_eth = eth_price
        self._lst_entry_ratio = ratio

        self._perp_notional_entry = self._capital * self._hedge_ratio
        self._perp_qty = self._perp_notional_entry / eth_price  # ETH units shorted
        self._mark_eth = eth_price

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if not self._initialised:
            raise InvalidDataError("EthLstNeutral.step before init")
        if self._killed:
            return  # safe-hold: once killed we stop trading/accruing

        # Required datapoints — fail-CLOSED. A missing one is a safe-hold (kill), no fabrication.
        # The LST flows through the same snapshot maps as the LRTs (lrt_price/lrt_ratio/restaking).
        try:
            eth_price = market.require("eth_price")
            ratio = market.require("lrt_ratio", self._lst_symbol)
            staking_apy = market.require("restaking_apy", self._lst_symbol)
            funding = market.require("funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return

        first_tick = self._lst_qty == 0.0
        if first_tick:
            self._open_legs(eth_price, ratio)

        # 1) staking yield on the CURRENT LST notional (daily fraction of decimal annual APY).
        #    No points: LST plain staking is contractual yield only (the SAFE path).
        lst_value = self._lst_qty * eth_price * ratio
        staking_usd = lst_value * (staking_apy / 365.0)
        self._cash += staking_usd
        self._cum_staking += staking_usd

        # 2) perp funding — settle N times this tick on the current perp notional. A SHORT
        #    RECEIVES funding when funding_rate is POSITIVE, PAYS when negative.
        per_settle = funding * self._perp_notional_entry
        tick_funding = per_settle * self._funding_settles_per_day
        self._cash += tick_funding
        self._cum_funding += tick_funding

        # 3) mark-to-market the short perp INCREMENTALLY vs the last mark (pure ETH move).
        if not first_tick:
            self._perp_pnl += -(eth_price - self._mark_eth) * self._perp_qty
        self._mark_eth = eth_price

        # 4) rebalance the hedge if spot/perp notional drift exceeds the band (charge cost).
        target = lst_value * self._hedge_ratio
        band = self._perp_notional_entry * (self._rebalance_bps / 10_000.0)
        if (
            not first_tick
            and self._perp_notional_entry > 0
            and abs(target - self._perp_notional_entry) > band
        ):
            delta = abs(target - self._perp_notional_entry)
            cost = self._gas_usd + delta * (self._slippage_bps / 10_000.0)
            self._cash -= cost
            self._perp_notional_entry = target
            self._perp_qty = target / eth_price

        # equity invariant: LST spot value (ETH price + depeg) + cumulative short-perp price P&L
        # (pure ETH, cancels the spot's ETH-price move) + cash (staking+funding−costs).
        # Net ETH-price exposure ≈ 0; surviving residual is the LST/ETH ratio drift (small).
        self._equity = round(lst_value + self._perp_pnl + self._cash, 2)

    # ── inspection ───────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        if not self._initialised or self._lst_qty == 0.0:
            return [Position(asset="cash", kind="cash", notional_usd=round(self._capital, 2))]
        return [
            Position(
                asset=self._lst_symbol,
                kind="spot",  # plain-staked LST spot (NOT 'lrt' — this is the safe path)
                notional_usd=round(self._lst_qty * self._mark_eth * self._lst_entry_ratio, 2),
                qty=self._lst_qty,
                entry_price=self._lst_entry_eth * self._lst_entry_ratio,
                meta={"entry_ratio": self._lst_entry_ratio, "kind_detail": "lst"},
            ),
            Position(
                asset="eth_perp",
                kind="perp_short",
                notional_usd=round(self._perp_notional_entry, 2),
                qty=self._perp_qty,
                entry_price=self._lst_entry_eth,
                meta={"cum_funding_usd": round(self._cum_funding, 2)},
            ),
        ]

    def equity(self) -> float:
        return round(self._equity, 2)

    # ── kill check (FAIL-CLOSED) ───────────────────────────────────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        ts = getattr(market, "date", "")
        if self._killed:
            return KillResult(triggered=True, reason=self._kill_reason or "killed", ts=ts)

        # (c) required datapoints — fail-closed on any invalid one.
        try:
            ratio = market.require("lrt_ratio", self._lst_symbol)
            funding = market.require("funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (a) funding continuously sub-threshold for ≥ N hours (each tick = a full day).
        if self._funding_settles_per_day > 0:
            hours_this_tick = _HOURS_PER_DAY
        else:
            hours_this_tick = 0.0
        if funding < self._funding_kill_threshold:
            self._sub_threshold_hours += hours_this_tick
        else:
            self._sub_threshold_hours = 0.0  # streak resets when funding recovers
        if self._sub_threshold_hours >= self._funding_kill_hours:
            self._killed = True
            self._kill_reason = (
                f"funding < {self._funding_kill_threshold} for "
                f"{self._sub_threshold_hours:.0f}h ≥ {self._funding_kill_hours:.0f}h"
            )
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (b) LST depeg vs entry/peg ratio — TIGHTER threshold than the LRT variant, but on a
        #     SMOOTHED, PERSISTENT signal so a 1-day DeFiLlama timestamp-misalignment artifact
        #     (a lone ratio spike up or down) does NOT trip the tight kill, while a real
        #     SUSTAINED depeg still does.
        #       1) append this tick's raw ratio to a short trailing window (median rejects a
        #          single outlier in either direction);
        #       2) measure the drop on the trailing MEDIAN, not the raw point;
        #       3) require the median-drop to PERSIST for ≥ depeg_persist_ticks consecutive ticks.
        self._ratio_window.append(ratio)
        if len(self._ratio_window) > self._depeg_median_window:
            self._ratio_window = self._ratio_window[-self._depeg_median_window :]
        if self._lst_entry_ratio > 0:
            smoothed = _trailing_median(self._ratio_window)
            drop_pct = (self._lst_entry_ratio - smoothed) / self._lst_entry_ratio * 100.0
            if drop_pct > self._lst_depeg_kill_pct:
                self._depeg_streak += 1
            else:
                self._depeg_streak = 0  # streak resets when the smoothed peg recovers
            if self._depeg_streak >= self._depeg_persist_ticks:
                self._killed = True
                self._kill_reason = (
                    f"LST depeg {drop_pct:.2f}% > {self._lst_depeg_kill_pct:.2f}% "
                    f"for {self._depeg_streak} ticks ≥ {self._depeg_persist_ticks} "
                    f"(entry ratio {self._lst_entry_ratio:.5f} → median {smoothed:.5f})"
                )
                return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        return KillResult(triggered=False, reason="", ts=ts)

    # ── metrics (live partials) ─────────────────────────────────────────────────────────────
    def metrics(self) -> StrategyMetrics:
        net_pnl = self._equity - self._capital if self._capital else 0.0
        net_apy_pct: Optional[float] = None
        funding_drag_pct: Optional[float] = None
        if self._capital:
            net_apy_pct = round(net_pnl / self._capital * 100.0, 4)
            funding_drag_pct = round(self._cum_funding / self._capital * 100.0, 4)
        return StrategyMetrics(
            net_apy_pct=net_apy_pct,
            beta_to_eth=0.0,                 # delta-neutral by construction
            funding_drag_pct=funding_drag_pct,
            extra={
                "cum_funding_usd": round(self._cum_funding, 2),
                "cum_staking_usd": round(self._cum_staking, 2),
                "cash_usd": round(self._cash, 2),
                "equity_usd": round(self._equity, 2),
                "sub_threshold_hours": self._sub_threshold_hours,
                "depeg_streak": self._depeg_streak,
                "killed": self._killed,
                "kill_reason": self._kill_reason,
                "lst_symbol": self._lst_symbol,
            },
        )
