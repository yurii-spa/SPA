"""
spa_core/strategy_lab/strategies/baselines.py — the production engines wrapped as
Strategy-Lab baselines.

These are NOT new candidates. They are thin adapters around the SPA engines that already
run in production (Engine A stable base book, Engine B HY/carry sleeve, Engine C LP sleeve)
plus the risk-free RWA floor benchmark. Wrapping them as `Strategy` subclasses lets the
shared harness compare new candidates (Variant N / Variant D) against the REAL baselines on
EQUAL FOOTING: same capital convention, same per-tick interface, same StrategyMetrics set.

What each wrapper reproduces (the real engines are NOT modified):

  - EngineA  : the stable base book accrues daily yield at the stable blended APY.
               Source: market.defi_apy (a blended/representative stable APY the harness
               supplies), with the config rwa_floor rate as the offline fallback.
               No price exposure (stable book) → zero market volatility.

  - EngineB  : HY / carry sleeve. Reproduces sleeve_yield's accrual:
               hy_target_apy_pct() (median of the high-yield band, capped at policy ceiling)
               when its live file (data/apy_ranking.json) is readable; else the HY band in
               market.defi_apy; else the sleeve_yield HY_FLOOR.

  - EngineC  : LP sleeve. Reproduces sleeve_yield's lp_target_apy_pct() accrual; LP fee yield
               only. Impermanent loss is NOT modelled in v1 — consistent with the documented
               gap in sleeve_yield (il_drawdown == 0 until a price feed is wired).

  - RWAFloor : the risk-free benchmark. Accrues at config rwa_floor_apy_pct with ZERO
               volatility and ZERO drawdown. This is the floor every other strategy must beat
               on a risk-adjusted basis.

All accrual uses spa_core.paper_trading.sleeve_yield.daily_yield (equity * apy/100 / 365),
the SAME compounding formula the real sleeves use — so a baseline here earns exactly what the
production engine earns at the same APY.

Offline safety: sleeve_yield.hy_target_apy_pct() / lp_target_apy_pct() read a live JSON file
that may be absent in CI/sandbox. They already fail-closed internally (return their floor on
any read error), but to make the data source explicit and testable we additionally wrap their
use in a try/except → config/market fallback. No exception from a live-file read can break a
deterministic backtest.

stdlib only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import (
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)
from spa_core.strategy_lab import config as lab_config

# Reuse the REAL sleeve-yield accrual + APY producers (do NOT reimplement them).
from spa_core.paper_trading import sleeve_yield


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_median(vals: List[float]) -> Optional[float]:
    """Median of a list of positive floats, or None if empty. stdlib-only (no statistics
    import needed for this tiny helper; deterministic)."""
    clean = sorted(v for v in vals if isinstance(v, (int, float)) and v > 0)
    n = len(clean)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return float(clean[mid])
    return (clean[mid - 1] + clean[mid]) / 2.0


class _BaselineBase(Strategy):
    """Shared scaffolding for the four baselines.

    Each baseline holds a SINGLE synthetic notional position (kind depends on the sleeve)
    whose notional == current equity. step() grows that notional by the daily yield at the
    sleeve's APY; equity() therefore equals the accrued book value. No price exposure for the
    stable baselines, so notional is the whole story.

    kill_check is the drawdown stop from the canonical risk limits (risk_limits()/policy),
    fail-CLOSED: any internal error or invalid drawdown → triggered=True.
    """

    is_advisory: bool = False  # these ARE the production baselines (overridden by RWAFloor)
    mandate: str = "stable"
    _kind: str = "lending"      # Position.kind for this sleeve

    def __init__(self) -> None:
        self._capital: float = 0.0       # starting capital (high-water reference baseline)
        self._equity: float = 0.0        # current accrued book value
        self._peak: float = 0.0          # running peak equity (for drawdown)
        self._cfg: dict = {}
        self._days: int = 0              # ticks accrued (for live APY partial)
        self._killed: bool = False

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = float(capital)
        self._equity = float(capital)
        self._peak = float(capital)
        self._cfg = dict(config or {})
        self._days = 0
        self._killed = False

    def positions(self) -> List[Position]:
        return [
            Position(
                asset=self.id,
                kind=self._kind,
                notional_usd=round(self._equity, 6),
                qty=0.0,
                entry_price=None,
                meta={"baseline": True, "mandate": self.mandate},
            )
        ]

    def equity(self) -> float:
        return round(self._equity, 6)

    # ── per-tick APY (subclasses override) ──────────────────────────────────────
    def _apy_pct(self, market: MarketSnapshot) -> float:
        """Return the APY (%) to accrue at this tick. Subclass-specific."""
        raise NotImplementedError

    def step(self, market: MarketSnapshot) -> None:
        """Advance one day: accrue daily yield at the sleeve APY. Deterministic given the
        same market input + prior state. Once killed, the book is flat (no further accrual)."""
        if self._killed:
            return
        apy = self._apy_pct(market)
        # Same compounding formula the real sleeves use.
        gain = sleeve_yield.daily_yield(self._equity, apy)
        self._equity += gain
        if self._equity > self._peak:
            self._peak = self._equity
        self._days += 1

    # ── metrics (live partials) ─────────────────────────────────────────────────
    def _drawdown_pct(self) -> float:
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - self._equity) / self._peak * 100.0)

    def metrics(self) -> StrategyMetrics:
        # Realised net APY since init, annualised from the accrued days (live partial).
        net_apy = None
        if self._capital > 0 and self._days > 0:
            total_return = (self._equity / self._capital) - 1.0
            net_apy = total_return * (365.0 / self._days) * 100.0
        return StrategyMetrics(
            net_apy_pct=round(net_apy, 6) if net_apy is not None else None,
            max_drawdown_pct=round(self._drawdown_pct(), 6),
            volatility_pct=0.0,        # stable baselines carry no price vol in v1
            beta_to_eth=0.0,
            extra={
                "id": self.id,
                "capital_usd": round(self._capital, 2),
                "equity_usd": round(self._equity, 2),
                "days": self._days,
                "killed": self._killed,
            },
        )

    # ── kill-check: drawdown stop from canonical risk limits, fail-CLOSED ────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        try:
            limits = lab_config.risk_limits()
            stop_frac = float(limits["max_drawdown_stop"])  # e.g. 0.05
            dd_frac = self._drawdown_pct() / 100.0
            if dd_frac >= stop_frac:
                self._killed = True
                return KillResult(
                    triggered=True,
                    reason=(
                        f"drawdown {dd_frac:.4%} ≥ risk-policy stop {stop_frac:.2%}"
                    ),
                    ts=_now_iso(),
                )
            return KillResult(triggered=False, reason="", ts=_now_iso())
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED on any internal error
            self._killed = True
            return KillResult(
                triggered=True,
                reason=f"kill_check error (fail-closed): {exc}",
                ts=_now_iso(),
            )


# ──────────────────────────────────────────────────────────────────────────────
# Engine A — stable base book
# ──────────────────────────────────────────────────────────────────────────────
class EngineA(_BaselineBase):
    """The production stable base book. Accrues at the stable blended APY the harness
    supplies via market.defi_apy (a blended/representative stable rate); falls back to the
    config rwa_floor rate when no blended APY is present (offline-safe)."""

    id = "engine_a"
    name = "Engine A — Stable base book"
    is_advisory = False
    mandate = "stable"
    _kind = "lending"

    def _apy_pct(self, market: MarketSnapshot) -> float:
        # Blended/representative stable APY supplied by the caller in market.defi_apy.
        # Convention: defi_apy values are decimals (per MarketSnapshot docstring) → ×100 to %.
        vals_decimal = [
            float(v) for v in (market.defi_apy or {}).values()
            if isinstance(v, (int, float)) and v > 0
        ]
        med = _safe_median(vals_decimal)
        if med is not None:
            return med * 100.0
        # Offline fallback: the risk-free stable rate from config (NOT a silent zero).
        try:
            return float(lab_config.rwa_floor_apy_pct())
        except Exception:  # noqa: BLE001 — last-resort fallback uses config block value
            return float(self._cfg.get("apy_pct", 4.5))


# ──────────────────────────────────────────────────────────────────────────────
# Engine B — HY / carry sleeve
# ──────────────────────────────────────────────────────────────────────────────
class EngineB(_BaselineBase):
    """HY / carry sleeve. Reproduces sleeve_yield's HY accrual:
        1) sleeve_yield.hy_target_apy_pct() when its live file reads cleanly;
        2) else the HY band (≥ HY_BAND_MIN%) of market.defi_apy;
        3) else sleeve_yield.HY_FLOOR (conservative).
    """

    id = "engine_b"
    name = "Engine B — HY / carry sleeve"
    is_advisory = False
    mandate = "stable"
    _kind = "lending"

    def _apy_pct(self, market: MarketSnapshot) -> float:
        # 1) Reuse the REAL producer. It is internally fail-closed, but we still guard the
        #    call so an unexpected raise from the live-file read can never break a backtest.
        try:
            live = sleeve_yield.hy_target_apy_pct()
            # hy_target_apy_pct() returns HY_FLOOR when there's no live data. If the harness
            # supplied a market HY band, prefer that (deterministic backtest input) over the
            # generic floor; otherwise accept the producer's value.
            band = [
                float(v) * 100.0 for v in (market.defi_apy or {}).values()
                if isinstance(v, (int, float)) and float(v) * 100.0 >= sleeve_yield.HY_BAND_MIN
            ]
            band_med = _safe_median(band)
            if band_med is not None and abs(live - sleeve_yield.HY_FLOOR) < 1e-9:
                return min(sleeve_yield.APY_CAP, band_med)
            return live
        except Exception:  # noqa: BLE001 — fall through to market band / floor
            pass
        # 2) market HY band
        band = [
            float(v) * 100.0 for v in (market.defi_apy or {}).values()
            if isinstance(v, (int, float)) and float(v) * 100.0 >= sleeve_yield.HY_BAND_MIN
        ]
        band_med = _safe_median(band)
        if band_med is not None:
            return min(sleeve_yield.APY_CAP, band_med)
        # 3) conservative floor
        return float(sleeve_yield.HY_FLOOR)


# ──────────────────────────────────────────────────────────────────────────────
# Engine C — LP sleeve
# ──────────────────────────────────────────────────────────────────────────────
class EngineC(_BaselineBase):
    """LP sleeve. Reproduces sleeve_yield's LP accrual via lp_target_apy_pct(); falls back to
    the market LP-band median, then sleeve_yield.LP_FLOOR.

    v1 gap (consistent with sleeve_yield): impermanent loss is NOT modelled — LP fee yield
    only. il_drawdown is 0 until a price feed is wired. Documented, not silent.
    """

    id = "engine_c"
    name = "Engine C — LP sleeve"
    is_advisory = False
    mandate = "stable"
    _kind = "lp"

    def _apy_pct(self, market: MarketSnapshot) -> float:
        # 1) Reuse the REAL producer (guarded for offline safety).
        try:
            live = sleeve_yield.lp_target_apy_pct()
            # If the harness supplied a market LP band and the producer only had its floor,
            # prefer the deterministic market input.
            vals = [
                float(v) * 100.0 for v in (market.defi_apy or {}).values()
                if isinstance(v, (int, float)) and v > 0
            ]
            med = _safe_median(vals)
            if med is not None and abs(live - sleeve_yield.LP_FLOOR) < 1e-9:
                return min(sleeve_yield.APY_CAP, med)
            return live
        except Exception:  # noqa: BLE001 — fall through to market band / floor
            pass
        # 2) market band
        vals = [
            float(v) * 100.0 for v in (market.defi_apy or {}).values()
            if isinstance(v, (int, float)) and v > 0
        ]
        med = _safe_median(vals)
        if med is not None:
            return min(sleeve_yield.APY_CAP, med)
        # 3) conservative floor
        return float(sleeve_yield.LP_FLOOR)

    def metrics(self) -> StrategyMetrics:
        m = super().metrics()
        # Make the v1 IL gap observable in the comparison output.
        m.extra["il_drawdown_pct"] = 0.0
        m.extra["il_modeled"] = False
        return m


# ──────────────────────────────────────────────────────────────────────────────
# RWA Floor — risk-free benchmark
# ──────────────────────────────────────────────────────────────────────────────
class RWAFloor(_BaselineBase):
    """The risk-free RWA benchmark. Accrues at config rwa_floor_apy_pct with ZERO volatility
    and ZERO drawdown — it is the floor every other strategy must beat risk-adjusted.

    It never accrues a loss, so its peak always equals its equity → drawdown is always 0 and
    the drawdown-stop kill never triggers (other than the fail-closed error path)."""

    id = "rwa_floor"
    name = "RWA Floor — risk-free benchmark"
    is_advisory = True   # a benchmark, not a tradeable production sleeve
    mandate = "stable"
    _kind = "cash"

    def _apy_pct(self, market: MarketSnapshot) -> float:
        # Risk-free: ALWAYS the config floor, independent of market (zero volatility).
        try:
            return float(lab_config.rwa_floor_apy_pct())
        except Exception:  # noqa: BLE001 — config block value as last resort
            return float(self._cfg.get("apy_pct", 4.5))


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────
def build_baselines(config: Optional[dict] = None) -> Dict[str, Strategy]:
    """Build the four production baselines, each initialised at its configured capital.

    Args:
        config: optional full lab config dict (as returned by config.load_config()). If None,
                the SSOT config is loaded from disk. Per-strategy capital is read from each
                strategy's config block ('capital_usd'); fail-CLOSED if the block is missing.

    Returns:
        {id: Strategy} for engine_a, engine_b, engine_c, rwa_floor.
    """
    cfg = config if config is not None else lab_config.load_config()
    strategies_cfg = cfg.get("strategies", {})

    classes = (EngineA, EngineB, EngineC, RWAFloor)
    out: Dict[str, Strategy] = {}
    for cls in classes:
        block = strategies_cfg.get(cls.id)
        if not isinstance(block, dict):
            raise lab_config.ConfigError(
                f"baselines: missing strategy config block for {cls.id!r}"
            )
        if "capital_usd" not in block:
            raise lab_config.ConfigError(
                f"baselines: strategy {cls.id!r} missing required 'capital_usd'"
            )
        capital = float(block["capital_usd"])
        strat = cls()
        strat.init(capital, block)
        out[cls.id] = strat
    return out
