"""
spa_core/backtesting/demotion_engine.py — MP-1513 Demotion Engine

Strategy demotion engine — safely removes underperforming strategies from production.
Follows ADR-023 promotion/demotion policy.
======================================================================================

Demotion is a safety mechanism: strategies that fail performance or risk thresholds
are flagged for removal from the production allocation set. Demotion does NOT itself
modify any allocator, risk engine, or execution component — it is advisory only.
The Owner must confirm a demotion before any live capital is affected.

Three-tier verdict system:
  KEEP   — strategy is performing within acceptable bounds
  WARN   — strategy is underperforming (streak building); Owner should monitor
  DEMOTE — strategy should be removed from production (immediate or streak-based)

Trigger matrix (ADR-023):

  Trigger                    Threshold          Mode
  ─────────────────────────────────────────────────────
  drawdown_above             > 8%               IMMEDIATE DEMOTE
  sharpe_below (consecutive) Sharpe < 0.5       after 5 consecutive bad evaluations → DEMOTE
                                                 after 2 consecutive bad evaluations → WARN
  apy_below (consecutive)    daily_apy < 2%/252 after 7 consecutive bad evaluations → DEMOTE

Constraints:
  - Extends BaseAnalytics (spa_core/base.py) — atomic save, stdlib only
  - LLM FORBIDDEN in this module
  - No external dependencies
  - Advisory only — never touches allocator/risk/execution
  - approved=False from RiskPolicy cannot be overridden by this engine

ADR: ADR-023 (promotion/demotion policy)
Date: 2026-06-20 (MP-1513, Sprint v11.29)
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics
from spa_core.utils.errors import GateError


# ─── Demotion triggers (ADR-023) ──────────────────────────────────────────────

DEMOTION_TRIGGERS: Dict[str, object] = {
    "sharpe_below":    0.5,       # Sharpe < 0.5 counts as a "bad" evaluation
    "drawdown_above":  0.08,      # Drawdown > 8% → IMMEDIATE DEMOTE
    "apy_below":       0.02,      # Annual APY < 2% (daily: /252) → slow demote
}

# Consecutive-bad-day thresholds
SHARPE_WARN_CONSECUTIVE:  int = 2   # → WARN after 2 bad Sharpe evaluations
SHARPE_DEMOTE_CONSECUTIVE: int = 5  # → DEMOTE after 5 bad Sharpe evaluations
APY_DEMOTE_CONSECUTIVE:    int = 7  # → DEMOTE after 7 below-APY evaluations

# Verdicts
VERDICT_KEEP:   str = "KEEP"
VERDICT_WARN:   str = "WARN"
VERDICT_DEMOTE: str = "DEMOTE"

OUTPUT_PATH = "data/demotion_engine.json"


# ─── DemotionEngine ───────────────────────────────────────────────────────────

class DemotionEngine(BaseAnalytics):
    """
    Manages safe demotion of underperforming strategies from production.

    State:
        demotion_checks:    Per-strategy consecutive-bad-day counters.
        demotions_executed: History of confirmed demotions (advisory log).

    Usage:
        engine = DemotionEngine(base_dir=".")

        verdict, reason = engine.check_strategy("S7", {
            "sharpe": 1.8,
            "max_drawdown": 0.02,
            "daily_apy": 0.0004,
        })
        # verdict ∈ {"KEEP", "WARN", "DEMOTE"}

        # Bulk evaluation
        results = engine.evaluate_all(strategy_metrics_dict)

        # Mark as demoted (advisory record)
        engine.record_demotion("S7", reason="drawdown breach")
    """

    OUTPUT_PATH = OUTPUT_PATH

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._data: dict = {
            "demotion_checks": {},   # {strategy_id: {consecutive_bad_sharpe, consecutive_bad_apy}}
            "demotions_executed": [],
        }

    # ── Main verdict API ───────────────────────────────────────────────────────

    def check_strategy(self, strategy_id: str, metrics: dict) -> Tuple[str, str]:
        """
        Evaluates a single strategy and returns a demotion verdict.

        Metrics dict keys (all optional; missing keys use safe defaults):
          - max_drawdown:  float, positive fraction (e.g. 0.03 = 3% DD). Default 0.
          - sharpe:        float. Default 1.0 (safe value).
          - daily_apy:     float, daily return fraction. Default safe positive.

        Returns:
            (verdict: str, reason: str)
            verdict ∈ {"KEEP", "WARN", "DEMOTE"}
        """
        checks = self._data["demotion_checks"].setdefault(
            strategy_id,
            {"consecutive_bad_sharpe": 0, "consecutive_bad_apy": 0},
        )

        # ── Gate 1: Immediate drawdown check ──────────────────────────────────
        max_dd = float(metrics.get("max_drawdown", 0.0) or 0.0)
        # Accept both positive and negative conventions
        if max_dd < 0:
            max_dd = abs(max_dd)
        if max_dd > float(DEMOTION_TRIGGERS["drawdown_above"]):
            return (
                VERDICT_DEMOTE,
                f"Drawdown {max_dd*100:.2f}% exceeds immediate-demote threshold "
                f"{DEMOTION_TRIGGERS['drawdown_above']*100:.0f}%",
            )

        # ── Gate 2: Consecutive bad Sharpe ────────────────────────────────────
        sharpe = float(metrics.get("sharpe", 1.0) or 1.0)
        sharpe_bad = sharpe < float(DEMOTION_TRIGGERS["sharpe_below"])
        if sharpe_bad:
            checks["consecutive_bad_sharpe"] += 1
        else:
            checks["consecutive_bad_sharpe"] = 0

        streak_sharpe = checks["consecutive_bad_sharpe"]
        if streak_sharpe >= SHARPE_DEMOTE_CONSECUTIVE:
            return (
                VERDICT_DEMOTE,
                f"Sharpe {sharpe:.2f} < {DEMOTION_TRIGGERS['sharpe_below']} "
                f"for {streak_sharpe} consecutive evaluations "
                f"(threshold: {SHARPE_DEMOTE_CONSECUTIVE})",
            )
        if streak_sharpe >= SHARPE_WARN_CONSECUTIVE:
            return (
                VERDICT_WARN,
                f"Sharpe {sharpe:.2f} below floor for {streak_sharpe} consecutive days "
                f"(DEMOTE at {SHARPE_DEMOTE_CONSECUTIVE})",
            )

        # ── Gate 3: Consecutive below-APY ─────────────────────────────────────
        daily_apy = float(metrics.get("daily_apy", 1.0) or 1.0)
        apy_floor_daily = float(DEMOTION_TRIGGERS["apy_below"]) / 252.0
        apy_bad = daily_apy < apy_floor_daily
        if apy_bad:
            checks["consecutive_bad_apy"] += 1
        else:
            checks["consecutive_bad_apy"] = 0

        streak_apy = checks["consecutive_bad_apy"]
        if streak_apy >= APY_DEMOTE_CONSECUTIVE:
            return (
                VERDICT_DEMOTE,
                f"Daily APY {daily_apy*100:.4f}% < annual floor "
                f"{DEMOTION_TRIGGERS['apy_below']*100:.0f}%/252 "
                f"for {streak_apy} consecutive evaluations "
                f"(threshold: {APY_DEMOTE_CONSECUTIVE})",
            )

        return VERDICT_KEEP, "All demotion gates passed"

    def evaluate_all(
        self,
        strategy_metrics: Dict[str, dict],
    ) -> Dict[str, Tuple[str, str]]:
        """
        Evaluates all strategies in the dict and returns verdicts.

        Args:
            strategy_metrics: {strategy_id: metrics_dict}

        Returns:
            {strategy_id: (verdict, reason)}
        """
        results: Dict[str, Tuple[str, str]] = {}
        for sid, metrics in strategy_metrics.items():
            results[sid] = self.check_strategy(sid, metrics)
        return results

    def demote_candidates(
        self,
        strategy_metrics: Dict[str, dict],
    ) -> List[str]:
        """
        Returns list of strategy IDs with DEMOTE verdict.

        Convenience wrapper around evaluate_all.

        Args:
            strategy_metrics: {strategy_id: metrics_dict}

        Returns:
            List of strategy IDs flagged for demotion.
        """
        verdicts = self.evaluate_all(strategy_metrics)
        return [sid for sid, (v, _) in verdicts.items() if v == VERDICT_DEMOTE]

    # ── State management ───────────────────────────────────────────────────────

    def record_demotion(self, strategy_id: str, reason: str = "") -> None:
        """
        Records a confirmed demotion in the advisory log.

        This is a read-only advisory record — it does NOT modify any
        allocator, risk engine, or execution component.

        Args:
            strategy_id: Strategy to mark as demoted.
            reason:      Human-readable reason for the demotion.
        """
        entry = {
            "strategy_id": strategy_id,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "reason": reason,
        }
        self._data["demotions_executed"].append(entry)

    def reset_strategy(self, strategy_id: str) -> None:
        """
        Resets all consecutive-bad-day counters for a strategy.

        Call after a demotion is confirmed and the strategy has been removed.

        Args:
            strategy_id: Strategy whose counters should be cleared.
        """
        self._data["demotion_checks"].pop(strategy_id, None)

    def get_streak(self, strategy_id: str) -> dict:
        """
        Returns the current consecutive-bad-day counters for a strategy.

        Args:
            strategy_id: Strategy to query.

        Returns:
            dict with keys: consecutive_bad_sharpe, consecutive_bad_apy.
            Returns zeroed dict if strategy has no recorded checks.
        """
        return dict(
            self._data["demotion_checks"].get(
                strategy_id,
                {"consecutive_bad_sharpe": 0, "consecutive_bad_apy": 0},
            )
        )

    def demotions_history(self) -> List[dict]:
        """Returns the full advisory demotions log."""
        return list(self._data.get("demotions_executed", []))

    def to_dict(self) -> dict:
        """Returns current engine state as JSON-serialisable dict."""
        return dict(self._data)
