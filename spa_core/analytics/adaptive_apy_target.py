"""
spa_core/analytics/adaptive_apy_target.py

Adaptive APY target adjustor based on market regime.

Logic:
  For each strategy, APY target is a range [min, max].
  Regime determines where in the range we aim.

  Bear market: aim for min (capital preservation over yield)
  Neutral:     aim for target (as specified)
  Bull:        aim for max (take advantage of high-yield opportunities)

RS-001 specific:
  Bear target: 8% (stable + gold hedge, avoid crypto LP)
  Neutral target: 18.2% (as designed)
  Bull target: 22% (increase GMX exposure in trending market)

RS-002 specific:
  Bear target: SUSPEND (too much IL risk in volatile bear)
  Neutral target: 15% net (conservative LP management)
  Bull target: 20% net (wider ranges possible, less rebalancing)

Usage:
  t = AdaptiveAPYTarget("S20_RS001", current_regime="bear")
  t.current_target()        # 8.0
  t.recommended_action()    # "REDUCE_CRYPTO_EXPOSURE"
  t.is_suspended()          # False
  t.target_range()          # {"bear": 8.0, "neutral": 18.2, "bull": 22.0}

  AdaptiveAPYTarget.for_regime("bull")
  # {"S20_RS001": {"target": 22.0, "action": "INCREASE_GMX_WEIGHT", ...}, ...}

LLM FORBIDDEN in this module.
Stdlib only. No external dependencies.

Sprint v9.44 — MP-1328
Date: 2026-06-19
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ─── Regime definitions ────────────────────────────────────────────────────────

VALID_REGIMES: List[str] = ["bear", "neutral", "bull"]

# Strategy APY configuration per regime
# target=0.0 + action="SUSPEND" means strategy is suspended in that regime
STRATEGIES_APY_CONFIG: Dict[str, Dict[str, Dict]] = {
    "S20_RS001": {
        "bear": {
            "target": 8.0,
            "action": "REDUCE_CRYPTO_EXPOSURE",
            "note": "Capital preservation mode: avoid crypto LP, hold stable + gold hedge",
        },
        "neutral": {
            "target": 18.2,
            "action": "FULL_ALLOCATION",
            "note": "Full allocation as designed; all legs active",
        },
        "bull": {
            "target": 22.0,
            "action": "INCREASE_GMX_WEIGHT",
            "note": "Increase GMX exposure in trending market; widen GMX allocation",
        },
    },
    "S21_RS002": {
        "bear": {
            "target": 0.0,
            "action": "SUSPEND",
            "note": (
                "Suspend: concentrated LP suffers severe IL in volatile bear markets; "
                "net return likely negative"
            ),
        },
        "neutral": {
            "target": 15.0,
            "action": "CONSERVATIVE_RANGES",
            "note": "Conservative LP ranges; minimise rebalancing costs",
        },
        "bull": {
            "target": 20.0,
            "action": "WIDER_RANGES",
            "note": "Wider LP ranges possible in trending upmarket; less rebalancing needed",
        },
    },
}

# ─── Internal helpers ──────────────────────────────────────────────────────────

_SUSPEND_ACTION: str = "SUSPEND"
_SUSPEND_TARGET: float = 0.0


def _validate_strategy(strategy_id: str) -> None:
    """Raise ValueError if strategy_id not in registry."""
    if strategy_id not in STRATEGIES_APY_CONFIG:
        known = ", ".join(STRATEGIES_APY_CONFIG.keys())
        raise ValueError(
            f"Unknown strategy_id '{strategy_id}'. Known: {known}"
        )


def _validate_regime(regime: str) -> None:
    """Raise ValueError if regime not in VALID_REGIMES."""
    if regime not in VALID_REGIMES:
        raise ValueError(
            f"Unknown regime '{regime}'. Valid: {VALID_REGIMES}"
        )


# ─── AdaptiveAPYTarget ────────────────────────────────────────────────────────

class AdaptiveAPYTarget:
    """Adaptive APY target adjustor for research strategies RS-001 and RS-002.

    Adjusts the APY target and recommended action based on the current market
    regime ('bear', 'neutral', 'bull'). Particularly important for RS-001
    (Anti-Crisis) and RS-002 (Cashflow / Concentrated LP).

    Args:
        strategy_id:     One of STRATEGIES_APY_CONFIG keys ("S20_RS001", "S21_RS002").
        current_regime:  Market regime: 'bear', 'neutral', or 'bull'.

    Raises:
        ValueError: if strategy_id or current_regime is unknown.
    """

    def __init__(
        self,
        strategy_id: str,
        current_regime: str = "neutral",
    ) -> None:
        _validate_strategy(strategy_id)
        _validate_regime(current_regime)
        self._strategy_id = strategy_id
        self._current_regime = current_regime
        self._config = STRATEGIES_APY_CONFIG[strategy_id]

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def current_regime(self) -> str:
        return self._current_regime

    # ── Core API ───────────────────────────────────────────────────────────────

    def current_target(self) -> float:
        """Return APY target (%) for the current regime.

        Returns 0.0 if the strategy is suspended in the current regime.

        Returns:
            APY target as a percentage float.
        """
        return self._config[self._current_regime]["target"]

    def recommended_action(self) -> str:
        """Return the action string for the current regime.

        Returns:
            Non-empty action string (e.g., "FULL_ALLOCATION", "SUSPEND").
        """
        action = self._config[self._current_regime]["action"]
        assert action, "action must be non-empty"
        return action

    def target_range(self) -> Dict[str, float]:
        """Return APY targets for all regimes.

        Returns:
            {"bear": float, "neutral": float, "bull": float}
        """
        return {
            regime: self._config[regime]["target"]
            for regime in VALID_REGIMES
        }

    def is_suspended(self) -> bool:
        """Return True if the strategy should be suspended in the current regime.

        A strategy is suspended when its action for the current regime is "SUSPEND".

        Returns:
            bool
        """
        return self._config[self._current_regime]["action"] == _SUSPEND_ACTION

    def regime_note(self) -> str:
        """Return the human-readable note for the current regime."""
        return self._config[self._current_regime].get("note", "")

    # ── Class methods ──────────────────────────────────────────────────────────

    @classmethod
    def for_regime(cls, regime: str) -> Dict[str, Dict]:
        """Return all strategies' targets and actions for a given regime.

        Args:
            regime: One of 'bear', 'neutral', 'bull'.

        Returns:
            {
              strategy_id: {
                "target": float,
                "action": str,
                "suspended": bool,
                "note": str,
              },
              ...
            }

        Raises:
            ValueError: if regime is unknown.
        """
        _validate_regime(regime)
        result: Dict[str, Dict] = {}
        for sid, config in STRATEGIES_APY_CONFIG.items():
            reg_cfg = config[regime]
            result[sid] = {
                "target": reg_cfg["target"],
                "action": reg_cfg["action"],
                "suspended": reg_cfg["action"] == _SUSPEND_ACTION,
                "note": reg_cfg.get("note", ""),
            }
        return result

    def regime_change_impact(
        self,
        from_regime: str,
        to_regime: str,
    ) -> Dict:
        """Show the impact of a regime change on this strategy's APY target.

        Args:
            from_regime: Current/starting regime.
            to_regime:   Target/new regime.

        Returns:
            {
              "strategy_id": str,
              "from_regime": str,
              "to_regime": str,
              "from_target": float,
              "to_target": float,
              "delta": float,           # to_target - from_target
              "required_action": str,   # action for to_regime
              "suspended_in_to": bool,  # True if to_regime suspends strategy
            }

        Raises:
            ValueError: if from_regime or to_regime is unknown.
        """
        _validate_regime(from_regime)
        _validate_regime(to_regime)

        from_target = self._config[from_regime]["target"]
        to_target = self._config[to_regime]["target"]
        required_action = self._config[to_regime]["action"]

        return {
            "strategy_id": self._strategy_id,
            "from_regime": from_regime,
            "to_regime": to_regime,
            "from_target": from_target,
            "to_target": to_target,
            "delta": round(to_target - from_target, 4),
            "required_action": required_action,
            "suspended_in_to": required_action == _SUSPEND_ACTION,
        }
