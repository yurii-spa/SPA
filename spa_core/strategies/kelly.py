"""S4 — Half-Kelly (edge-over-risk-free position sizing)."""
from __future__ import annotations

from .base import active_pools


class HalfKellyStrategy:
    """Size positions by a simplified Half-Kelly rule.

    With risk-free rate ``rf = 4.0%`` and unit odds:

        edge          = apy_pct - rf
        kelly_fraction = min(edge / (edge + odds), 0.25)   # odds = 1.0
        weight         = 0.5 * kelly_fraction              # Half-Kelly

    Pools with ``edge <= 0`` get weight 0. Weights are *not* renormalised — the
    rule is intentionally conservative and leaves the remainder in cash.
    """

    name = "s4_kelly"
    label = "Half-Kelly"
    risk_level = "medium"

    RISK_FREE_PCT = 4.0
    ODDS = 1.0
    MAX_KELLY_FRACTION = 0.25

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}

        weights: dict[str, float] = {}
        for p in pools:
            edge = p["apy_pct"] - self.RISK_FREE_PCT
            if edge <= 0:
                continue
            kelly = edge / (edge + self.ODDS)
            kelly = min(kelly, self.MAX_KELLY_FRACTION)
            w = 0.5 * kelly
            if w > 0:
                weights[p["pool_id"]] = w
        return weights
