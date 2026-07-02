"""
spa_core/strategy_lab/strategies/advisory_yield_sleeve.py — generic ADVISORY paper sleeve.

A single parameterized sleeve used to give the fundable 8-12% research candidates
(PT-sUSDe, PT-USDe, Maple syrupUSDC, Centrifuge DROP) a forward ADVISORY paper record in the
Strategy-Lab paper harness — WITHOUT any capital, WITHOUT touching the go-live track, and WITHOUT
inventing a live feed.

Honesty (why this is an offline-literal sleeve, not a live-feed one):
  There is NO live strategy_lab feed for these underlyings (Pendle PT implied rate / Maple / Centrifuge
  are not in rwa_feed's tokenized-T-bill allowlist). So this sleeve accrues at a COMMITTED, SOURCED
  literal `apy_pct` carried in its config block — clearly an advisory offline rate, as-of the sourced
  date, NOT a live-tracked yield. It is the honest low-risk path: a deterministic forward paper curve
  that says "IF this candidate accrued at its sourced rate, here is the track" — it is NOT a claim of
  realized live yield. Each block documents `apy_source` + `apy_as_of`. The decision + full DD live in
  data/strategy_candidates/*.candidate.md + docs/decision_index.md (source of truth).

Distinct from rwa_sleeve: rwa_sleeve reads the LIVE rwa_feed floor; this reads a config literal.
Distinct from the go-live track: like every strategy_lab sleeve it writes ONLY under
data/strategy_lab_paper/<id>_{state,series}.json — never equity_curve_daily / golive_status /
paper_evidence_history / trades / RiskPolicy.

Accrual uses spa_core.paper_trading.sleeve_yield.daily_yield (equity * apy/100 / 365) — the SAME
compounding every real sleeve uses. Kill: a fail-CLOSED sleeve-level drawdown stop from the config
block (these carry real risk, so the stop is meaningful, unlike the T-bill floor sleeve).

stdlib only, deterministic. LLM FORBIDDEN. IS_ADVISORY.
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
from spa_core.paper_trading import sleeve_yield

# Sane band for the accrual rate. A configured advisory rate outside this band is treated as bad
# config → fail-CLOSED (we never accrue at an absurd/fabricated rate). Covers the fundable 8-12%
# band with margin; anything ≥15% is refused at the sleeve level.
MIN_SANE_APY_PCT = 0.0
MAX_SANE_APY_PCT = 15.0
DEFAULT_DRAWDOWN_STOP_PCT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdvisoryYieldSleeve(Strategy):
    """Generic advisory sleeve accruing at a COMMITTED SOURCED literal `apy_pct` from its config
    block. Instantiate with a stable id/name/tier, then init(capital, config_block).

    Identity is set per-instance (this class is reused for several sleeves). is_advisory=True.
    Lifecycle mirrors rwa_sleeve: init() seeds the book; step() accrues one day at the sourced
    advisory rate; metrics() reports the realized partial; kill_check() is the fail-closed
    sleeve-level drawdown stop."""

    is_advisory = True

    def __init__(self, sleeve_id: str, name: str, tier: str = "T2", mandate: str = "stable") -> None:
        # Per-instance identity (this class backs multiple sleeves).
        self.id = str(sleeve_id)
        self.name = str(name)
        self.tier = str(tier)
        self.mandate = str(mandate)
        self._kind = "lending"      # Position.kind: a supplied/credit-like book
        self._capital: float = 0.0
        self._equity: float = 0.0
        self._peak: float = 0.0
        self._cfg: dict = {}
        self._days: int = 0
        self._killed: bool = False
        self._apy: float = 0.0
        self._stop_frac: float = DEFAULT_DRAWDOWN_STOP_PCT / 100.0

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = float(capital)
        self._equity = float(capital)
        self._peak = float(capital)
        self._cfg = dict(config or {})
        self._days = 0
        self._killed = False
        # The sourced advisory accrual rate (committed literal, not a live feed). Validated on read.
        try:
            self._apy = float(self._cfg["apy_pct"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{self.id}: config missing/invalid apy_pct — fail-closed") from exc
        stop_pct = self._cfg.get("drawdown_stop_pct", DEFAULT_DRAWDOWN_STOP_PCT)
        try:
            self._stop_frac = float(stop_pct) / 100.0
        except (TypeError, ValueError):
            self._stop_frac = DEFAULT_DRAWDOWN_STOP_PCT / 100.0

    def positions(self) -> List[Position]:
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
                    "advisory": True,
                    "apy_source": self._cfg.get("apy_source", "requires verification"),
                    "apy_as_of": self._cfg.get("apy_as_of", "requires verification"),
                },
            )
        ]

    def equity(self) -> float:
        return round(self._equity, 6)

    # ── per-tick accrual rate (the SOURCED advisory literal) ──────────────────────
    def _apy_pct(self) -> float:
        """The sourced advisory APY (%) to accrue at, from the config literal. FAIL-CLOSED: an
        out-of-band rate raises so the harness safe-holds — we never accrue at an absurd rate."""
        apy = float(self._apy)
        if not (MIN_SANE_APY_PCT <= apy <= MAX_SANE_APY_PCT):
            raise ValueError(
                f"{self.id}: advisory rate {apy!r}% outside sane band "
                f"[{MIN_SANE_APY_PCT}, {MAX_SANE_APY_PCT}] — fail-closed"
            )
        return apy

    def step(self, market: MarketSnapshot) -> None:
        """Advance one day: accrue at the sourced advisory rate. Deterministic given the config +
        prior state (no market/network dependency). Once killed, the book is flat."""
        if self._killed:
            return
        apy = self._apy_pct()  # raises on bad config → fail-closed at the harness
        gain = sleeve_yield.daily_yield(self._equity, apy)
        self._equity += gain
        if self._equity > self._peak:
            self._peak = self._equity
        self._days += 1

    # ── metrics ───────────────────────────────────────────────────────────────────
    def _drawdown_pct(self) -> float:
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - self._equity) / self._peak * 100.0)

    def metrics(self) -> StrategyMetrics:
        net_apy = None
        if self._capital > 0 and self._days > 0:
            total_return = (self._equity / self._capital) - 1.0
            net_apy = total_return * (365.0 / self._days) * 100.0
        return StrategyMetrics(
            net_apy_pct=round(net_apy, 6) if net_apy is not None else None,
            max_drawdown_pct=round(self._drawdown_pct(), 6),
            volatility_pct=0.0,   # accrual-only advisory model (no modelled price vol in v1)
            beta_to_eth=0.0,
            extra={
                "id": self.id,
                "tier": self.tier,
                "advisory": True,
                "sourced_apy_pct": round(self._apy, 6),
                "apy_source": self._cfg.get("apy_source", "requires verification"),
                "apy_as_of": self._cfg.get("apy_as_of", "requires verification"),
                "candidate_ref": self._cfg.get("candidate_ref", ""),
                "capital_usd": round(self._capital, 2),
                "equity_usd": round(self._equity, 2),
                "days": self._days,
                "killed": self._killed,
                "drawdown_stop_pct": round(self._stop_frac * 100.0, 6),
                "note": "advisory offline-rate paper track — NOT a realized live yield; see candidate_ref",
            },
        )

    # ── kill-check: sleeve drawdown stop, fail-CLOSED ─────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        try:
            dd_frac = self._drawdown_pct() / 100.0
            if dd_frac >= self._stop_frac:
                self._killed = True
                return KillResult(
                    triggered=True,
                    reason=f"{self.id} drawdown {dd_frac:.4%} ≥ sleeve stop {self._stop_frac:.2%}",
                    ts=_now_iso(),
                )
            return KillResult(triggered=False, reason="", ts=_now_iso())
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED on any internal error
            self._killed = True
            return KillResult(
                triggered=True,
                reason=f"{self.id} kill_check error (fail-closed): {exc}",
                ts=_now_iso(),
            )
