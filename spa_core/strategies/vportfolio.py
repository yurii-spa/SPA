"""
spa_core.strategies.vportfolio — a virtual $100K portfolio for shadow testing.

One :class:`VirtualPortfolio` per strategy. Each ``step`` accrues daily yield on
the currently-held positions (APY -> daily, mark-to-market), then rebalances to
the strategy's target weights. State is persisted atomically to
``data/strategies/{name}.json``.

Stdlib only. No execution, no real capital.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import _as_float
from spa_core.utils.atomic import atomic_save

#: equity_curve is a ring buffer of at most this many most-recent points.
EQUITY_CURVE_MAX = 90

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data" / "strategies"


class VirtualPortfolio:
    """A self-contained paper portfolio that compounds APY yield over steps."""

    def __init__(self, name: str, capital: float = 100_000.0):
        self.name = str(name)
        self.initial_capital = float(capital)
        self.cash = float(capital)
        # pool_id -> position value in USD
        self.positions: dict[str, float] = {}
        # ring buffer of {ts, equity, positions}
        self.equity_curve: list[dict] = []
        self.last_ts: str | None = None

    # ----------------------------------------------------------------- equity
    @property
    def equity(self) -> float:
        """Current mark-to-market portfolio value (cash + all positions)."""
        return self.cash + sum(self.positions.values())

    # ------------------------------------------------------------------- step
    def step(self, snapshot: dict, weights: dict[str, float], ts: str) -> float:
        """Advance the portfolio one simulation step.

        1. Accrue one day of yield on every currently-held position using the
           pool's APY from ``snapshot`` (``daily = usd * apy/100 / 365``).
        2. Rebalance to ``weights`` (fractions of total equity); the
           unallocated remainder is held as cash.
        3. Append a point to the equity curve (ring-buffered to
           :data:`EQUITY_CURVE_MAX`).

        Returns the total yield (USD) accrued this step.
        """
        apy_by_pool = self._apy_map(snapshot)

        # 1. Yield accrual on existing positions (reinvested into the position).
        yield_today = 0.0
        for pool_id, usd in list(self.positions.items()):
            apy = apy_by_pool.get(pool_id, 0.0)
            daily = usd * (apy / 100.0) / 365.0
            if daily:
                self.positions[pool_id] = usd + daily
                yield_today += daily

        # 2. Rebalance to target weights against the (now grown) equity.
        equity = self.equity
        new_positions: dict[str, float] = {}
        allocated = 0.0
        for pool_id, w in (weights or {}).items():
            wf = _as_float(w)
            if wf is None or wf <= 0:
                continue
            usd = equity * wf
            if usd <= 0:
                continue
            new_positions[pool_id] = usd
            allocated += usd
        # Floating-point guard: never let allocation exceed equity.
        if allocated > equity:
            scale = equity / allocated
            new_positions = {k: v * scale for k, v in new_positions.items()}
            allocated = equity
        self.positions = new_positions
        self.cash = equity - allocated

        # 3. Record equity-curve point (ring buffer).
        self.last_ts = ts
        self.equity_curve.append(
            {
                "ts": ts,
                "equity": round(self.equity, 6),
                "positions": {k: round(v, 6) for k, v in self.positions.items()},
            }
        )
        if len(self.equity_curve) > EQUITY_CURVE_MAX:
            self.equity_curve = self.equity_curve[-EQUITY_CURVE_MAX:]

        return yield_today

    @staticmethod
    def _apy_map(snapshot: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        for ad in (snapshot or {}).get("adapters", []) or []:
            if isinstance(ad, dict) and ad.get("protocol"):
                apy = _as_float(ad.get("apy_pct"))
                if apy is not None:
                    out[str(ad["protocol"])] = apy
        return out

    # ------------------------------------------------------------ (de)serialize
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 6),
            "positions": {k: round(v, 6) for k, v in self.positions.items()},
            "equity": round(self.equity, 6),
            "last_ts": self.last_ts,
            "equity_curve": self.equity_curve,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VirtualPortfolio":
        vp = cls(
            name=data.get("name", "unknown"),
            capital=float(data.get("initial_capital", 100_000.0)),
        )
        vp.cash = float(data.get("cash", vp.initial_capital))
        vp.positions = {
            str(k): float(v)
            for k, v in (data.get("positions") or {}).items()
            if _as_float(v) is not None
        }
        vp.equity_curve = list(data.get("equity_curve") or [])[-EQUITY_CURVE_MAX:]
        vp.last_ts = data.get("last_ts")
        return vp

    # ------------------------------------------------------------- persistence
    def path(self) -> Path:
        return _DATA_DIR / f"{self.name}.json"

    def save(self, path: str | os.PathLike | None = None) -> Path:
        """Atomically persist the portfolio (tmp file + ``os.replace``)."""
        target = Path(path) if path is not None else self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(self.to_dict(), str(target))
        return target

    @classmethod
    def load(cls, name: str, path: str | os.PathLike | None = None) -> "VirtualPortfolio":
        """Load a persisted portfolio, or return a fresh one if none exists."""
        target = Path(path) if path is not None else (_DATA_DIR / f"{name}.json")
        if not target.exists():
            return cls(name=name)
        try:
            with open(target, "r", encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except (OSError, ValueError):
            return cls(name=name)
