"""
spa_core/strategy_lab/strategies/rwa_sleeve.py — the T1 RWA cash-floor SLEEVE.

This is an ACTUAL allocatable strategy (NOT the benchmark). It is the real cash floor a
portfolio parks idle capital in: it HOLDS tokenized US-Treasury funds (BlackRock BUIDL,
Circle/Hashnote USYC, Ondo USDY/OUSG, …) and accrues at the LIVE tokenized-T-bill yield from
spa_core.strategy_lab.data.rwa_feed (TVL-weighted across the issuer pools, ~$15B market at
~3.3–3.5%). Tokenized-T-bill NAV is stable (1.00, interest-bearing), so the sleeve has zero
price volatility and no meaningful drawdown — the lowest-risk, T1 home for cash.

Distinction from the RWAFloor BENCHMARK (strategies/baselines.py):
  - RWAFloor   : a zero-vol REFERENCE row. is_advisory, mandate=stable, kind="cash". It is the
                 line every other strategy must beat risk-adjusted; it is NOT something you hold.
  - RwaSleeve  : the REALIZED floor — an allocatable T1 sleeve that actually holds the tokenized
                 T-bills. By construction it lands right AT the floor (it IS the floor, realized),
                 with the best risk-adjusted profile among the low-risk options (zero drawdown,
                 zero vol, a real ~3.4% yield). Honest framing: this is the cash floor, not a
                 yield play — it does not try to beat the floor, it banks it.

Both read the SAME live rate via lab_config.rwa_floor_apy_pct() (rwa_feed, cached, fail-safe to
the committed literal) so the sleeve earns exactly the floor the harness compares against. The
tiny realized gap vs the benchmark row is the honest cost of holding (none modelled in v1 — the
sleeve holds NAV-stable funds with negligible friction), so it sits beats-floor borderline.

Accrual uses spa_core.paper_trading.sleeve_yield.daily_yield (equity * apy/100 / 365), the SAME
compounding formula every real sleeve uses.

Risk / kill: T1 means lowest risk. kill_check() essentially NEVER kills on normal data (T-bill
NAV does not draw down), EXCEPT a config drawdown stop — and it is FAIL-CLOSED: any internal
error or invalid data → triggered=True (safe-hold). The drawdown stop comes from the strategy's
own config block (rwa_sleeve.drawdown_stop_pct), independent of the portfolio-wide risk policy,
so the floor sleeve has a tight, explicit stop of its own.

stdlib only, deterministic. LLM FORBIDDEN. T1 tier, IS_ADVISORY.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from spa_core.strategy_lab.base import (
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)
from spa_core.strategy_lab import config as lab_config

# Reuse the REAL sleeve-yield accrual (do NOT reimplement the compounding).
from spa_core.paper_trading import sleeve_yield

# Tokenized US-Treasury funds this sleeve parks cash in (the real holdings behind the floor).
TBILL_HOLDINGS = ("BUIDL", "USYC", "USDY", "OUSG")
# Default per-sleeve drawdown stop (fraction). T-bill NAV is stable so this should never trip on
# real data; it exists as an explicit, fail-closed safety stop for the sleeve.
DEFAULT_DRAWDOWN_STOP_PCT = 1.0
# Sane band for the accrual rate. A live tokenized-T-bill yield outside this band is treated as
# bad data → fail-CLOSED (we never accrue at a fabricated/absurd rate).
MIN_SANE_APY_PCT = 0.0
MAX_SANE_APY_PCT = 12.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RwaSleeve(Strategy):
    """T1 RWA cash-floor sleeve: holds tokenized T-bills, accrues at the LIVE rwa_feed rate.

    Identity: id="rwa_sleeve", mandate="stable", is_advisory=True, tier="T1".

    Lifecycle: init() sets the book; step() accrues one day's yield at the live floor rate with
    ZERO price vol; metrics() reports the realized floor; kill_check() is the fail-closed
    sleeve-level drawdown stop (never trips on normal T-bill data)."""

    id = "rwa_sleeve"
    name = "RWA Sleeve — tokenized T-bill cash floor (T1)"
    is_advisory = True   # advisory until go-live (per repo rule #10)
    mandate = "stable"
    tier = "T1"          # lowest-risk tier — tokenized US Treasuries

    _kind = "cash"       # Position.kind: NAV-stable cash-equivalent

    def __init__(self) -> None:
        self._capital: float = 0.0   # starting capital (high-water reference)
        self._equity: float = 0.0    # current accrued book value
        self._peak: float = 0.0      # running peak equity (for drawdown)
        self._cfg: dict = {}
        self._days: int = 0          # ticks accrued (for realized-APY partial)
        self._killed: bool = False
        self._stop_frac: float = DEFAULT_DRAWDOWN_STOP_PCT / 100.0

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = float(capital)
        self._equity = float(capital)
        self._peak = float(capital)
        self._cfg = dict(config or {})
        self._days = 0
        self._killed = False
        # Sleeve-level drawdown stop from the config block (explicit, not the portfolio policy).
        stop_pct = self._cfg.get("drawdown_stop_pct", DEFAULT_DRAWDOWN_STOP_PCT)
        try:
            self._stop_frac = float(stop_pct) / 100.0
        except (TypeError, ValueError):
            self._stop_frac = DEFAULT_DRAWDOWN_STOP_PCT / 100.0

    def positions(self) -> List[Position]:
        # A single NAV-stable cash-equivalent position spread across the tokenized-T-bill funds.
        return [
            Position(
                asset=self.id,
                kind=self._kind,
                notional_usd=round(self._equity, 6),
                qty=0.0,
                entry_price=None,
                meta={
                    "sleeve": True,
                    "tier": self.tier,
                    "mandate": self.mandate,
                    "holdings": list(TBILL_HOLDINGS),
                    "nav_stable": True,
                },
            )
        ]

    def equity(self) -> float:
        return round(self._equity, 6)

    # ── per-tick accrual rate (the LIVE tokenized-T-bill floor) ───────────────────
    def _apy_pct(self) -> float:
        """The APY (%) to accrue at: the LIVE tokenized-T-bill floor from rwa_feed via config
        (TVL-weighted, cached, fail-safe to the committed literal). FAIL-CLOSED: an out-of-band
        rate raises ValueError so step()'s caller (harness) safe-holds — we never accrue at a
        fabricated/absurd rate. The config block's own apy_pct is a last-resort offline value."""
        apy = float(lab_config.rwa_floor_apy_pct())
        if not (MIN_SANE_APY_PCT <= apy <= MAX_SANE_APY_PCT):
            raise ValueError(
                f"rwa_sleeve: live floor {apy!r}% outside sane band "
                f"[{MIN_SANE_APY_PCT}, {MAX_SANE_APY_PCT}] — fail-closed"
            )
        return apy

    def step(self, market: MarketSnapshot) -> None:
        """Advance one day: accrue daily yield at the live tokenized-T-bill floor. Zero price
        vol (T-bill NAV is stable) so the notional simply grows by the accrual. Deterministic
        given the same live rate + prior state. Once killed, the book is flat (no further
        accrual). FAIL-CLOSED: a bad/out-of-band rate raises (harness latches the kill)."""
        if self._killed:
            return
        apy = self._apy_pct()  # raises on bad data → fail-closed safe-hold at the harness
        gain = sleeve_yield.daily_yield(self._equity, apy)
        self._equity += gain
        if self._equity > self._peak:
            self._peak = self._equity
        self._days += 1

    # ── metrics (live partials) ───────────────────────────────────────────────────
    def _drawdown_pct(self) -> float:
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - self._equity) / self._peak * 100.0)

    def metrics(self) -> StrategyMetrics:
        # Realized net APY since init, annualised from accrued days (live partial). This sits at
        # the floor by construction (the sleeve banks the floor, it does not try to beat it).
        net_apy = None
        if self._capital > 0 and self._days > 0:
            total_return = (self._equity / self._capital) - 1.0
            net_apy = total_return * (365.0 / self._days) * 100.0
        return StrategyMetrics(
            net_apy_pct=round(net_apy, 6) if net_apy is not None else None,
            max_drawdown_pct=round(self._drawdown_pct(), 6),
            volatility_pct=0.0,   # NAV-stable T-bills carry no price vol
            beta_to_eth=0.0,      # no crypto-price exposure
            extra={
                "id": self.id,
                "tier": self.tier,
                "is_floor_realized": True,   # this IS the floor, held for real
                "capital_usd": round(self._capital, 2),
                "equity_usd": round(self._equity, 2),
                "days": self._days,
                "killed": self._killed,
                "holdings": list(TBILL_HOLDINGS),
                "drawdown_stop_pct": round(self._stop_frac * 100.0, 6),
            },
        )

    # ── kill-check: sleeve drawdown stop, fail-CLOSED ─────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        """T1 sleeve: essentially never kills on normal data (T-bill NAV does not draw down).
        Trips ONLY if the sleeve drawdown exceeds its config stop. FAIL-CLOSED: any internal
        error → triggered=True (safe state)."""
        try:
            dd_frac = self._drawdown_pct() / 100.0
            if dd_frac >= self._stop_frac:
                self._killed = True
                return KillResult(
                    triggered=True,
                    reason=(
                        f"rwa_sleeve drawdown {dd_frac:.4%} ≥ sleeve stop "
                        f"{self._stop_frac:.2%}"
                    ),
                    ts=_now_iso(),
                )
            return KillResult(triggered=False, reason="", ts=_now_iso())
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED on any internal error
            self._killed = True
            return KillResult(
                triggered=True,
                reason=f"rwa_sleeve kill_check error (fail-closed): {exc}",
                ts=_now_iso(),
            )
