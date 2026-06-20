"""
tests/test_demotion_engine.py — MP-1513 (Sprint v11.29)

20 tests for DemotionEngine (spa_core/backtesting/demotion_engine.py).

Covers:
  - Immediate drawdown DEMOTE (> 8%)
  - Sharpe consecutive-bad streak: KEEP → WARN → DEMOTE
  - APY consecutive-bad streak → DEMOTE after 7 evals
  - Streak reset on good evaluation
  - reset_strategy clears counters
  - record_demotion writes to history
  - evaluate_all bulk interface
  - demote_candidates helper
  - Negative drawdown convention accepted (abs value used)
  - Missing metrics keys handled safely
  - Multiple strategies independently tracked

Stdlib only, no external dependencies.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from spa_core.backtesting.demotion_engine import (
    DemotionEngine,
    VERDICT_KEEP,
    VERDICT_WARN,
    VERDICT_DEMOTE,
    DEMOTION_TRIGGERS,
    SHARPE_WARN_CONSECUTIVE,
    SHARPE_DEMOTE_CONSECUTIVE,
    APY_DEMOTE_CONSECUTIVE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_engine() -> DemotionEngine:
    return DemotionEngine(base_dir="/tmp")


def good_metrics() -> dict:
    """Metrics that pass all demotion gates."""
    return {
        "max_drawdown": 0.02,      # 2%, well below 8%
        "sharpe": 1.8,             # above 0.5 floor
        "daily_apy": 0.0004,       # ~10% annual, above 2%/252 floor
    }


def bad_sharpe_metrics() -> dict:
    """Metrics with Sharpe below the demotion floor."""
    return {
        "max_drawdown": 0.01,
        "sharpe": 0.3,             # < 0.5 floor
        "daily_apy": 0.0004,
    }


def bad_apy_metrics() -> dict:
    """Metrics with daily APY below the demotion floor (2%/252 ≈ 0.0000794)."""
    return {
        "max_drawdown": 0.01,
        "sharpe": 0.8,             # above floor — only APY is bad
        "daily_apy": 0.00005,      # way below 2%/252
    }


def dd_breach_metrics() -> dict:
    """Metrics with drawdown exceeding the immediate-demote threshold."""
    return {
        "max_drawdown": 0.09,      # 9% > 8% threshold
        "sharpe": 1.2,
        "daily_apy": 0.0004,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Immediate drawdown gate
# ══════════════════════════════════════════════════════════════════════════════

class TestDrawdownGate:

    def test_immediate_demote_on_dd_breach(self):
        """Drawdown > 8% triggers IMMEDIATE DEMOTE regardless of streak."""
        eng = make_engine()
        verdict, reason = eng.check_strategy("S1", dd_breach_metrics())
        assert verdict == VERDICT_DEMOTE
        assert "drawdown" in reason.lower() or "%" in reason

    def test_keep_on_dd_below_threshold(self):
        """Drawdown well below 8% does not trigger demotion."""
        eng = make_engine()
        verdict, _ = eng.check_strategy("S1", good_metrics())
        assert verdict == VERDICT_KEEP

    def test_dd_exactly_at_threshold_is_safe(self):
        """Drawdown exactly at threshold (not strictly above) → KEEP."""
        eng = make_engine()
        metrics = good_metrics()
        metrics["max_drawdown"] = float(DEMOTION_TRIGGERS["drawdown_above"])
        verdict, _ = eng.check_strategy("S1", metrics)
        assert verdict == VERDICT_KEEP

    def test_negative_dd_convention_accepted(self):
        """Drawdown expressed as negative fraction (e.g. -0.09) is handled correctly."""
        eng = make_engine()
        metrics = good_metrics()
        metrics["max_drawdown"] = -0.09   # negative convention
        verdict, _ = eng.check_strategy("S1", metrics)
        assert verdict == VERDICT_DEMOTE


# ══════════════════════════════════════════════════════════════════════════════
# 2. Sharpe consecutive-bad streak
# ══════════════════════════════════════════════════════════════════════════════

class TestSharpeStreak:

    def test_single_bad_sharpe_is_keep(self):
        """1 bad Sharpe day → KEEP (streak < WARN threshold)."""
        eng = make_engine()
        verdict, _ = eng.check_strategy("S1", bad_sharpe_metrics())
        assert verdict == VERDICT_KEEP

    def test_warn_after_consecutive_bad_sharpe(self):
        """SHARPE_WARN_CONSECUTIVE bad days → WARN."""
        eng = make_engine()
        for _ in range(SHARPE_WARN_CONSECUTIVE - 1):
            eng.check_strategy("S1", bad_sharpe_metrics())
        verdict, _ = eng.check_strategy("S1", bad_sharpe_metrics())
        assert verdict == VERDICT_WARN

    def test_demote_after_max_bad_sharpe_streak(self):
        """SHARPE_DEMOTE_CONSECUTIVE bad days → DEMOTE."""
        eng = make_engine()
        for _ in range(SHARPE_DEMOTE_CONSECUTIVE - 1):
            eng.check_strategy("S1", bad_sharpe_metrics())
        verdict, _ = eng.check_strategy("S1", bad_sharpe_metrics())
        assert verdict == VERDICT_DEMOTE

    def test_good_sharpe_resets_streak(self):
        """Good Sharpe evaluation resets the consecutive-bad counter."""
        eng = make_engine()
        for _ in range(SHARPE_WARN_CONSECUTIVE):
            eng.check_strategy("S1", bad_sharpe_metrics())
        eng.check_strategy("S1", good_metrics())
        streak = eng.get_streak("S1")["consecutive_bad_sharpe"]
        assert streak == 0

    def test_sharpe_streak_is_independent_per_strategy(self):
        """Streak counts are tracked separately per strategy."""
        eng = make_engine()
        for _ in range(SHARPE_DEMOTE_CONSECUTIVE):
            eng.check_strategy("S1", bad_sharpe_metrics())
        # S2 should still be clean
        verdict, _ = eng.check_strategy("S2", bad_sharpe_metrics())
        assert verdict == VERDICT_KEEP   # only 1 bad day for S2


# ══════════════════════════════════════════════════════════════════════════════
# 3. APY consecutive-bad streak
# ══════════════════════════════════════════════════════════════════════════════

class TestAPYStreak:

    def test_single_bad_apy_is_keep(self):
        """1 bad daily APY → KEEP."""
        eng = make_engine()
        verdict, _ = eng.check_strategy("S1", bad_apy_metrics())
        assert verdict == VERDICT_KEEP

    def test_demote_after_apy_streak(self):
        """APY_DEMOTE_CONSECUTIVE consecutive below-APY evaluations → DEMOTE."""
        eng = make_engine()
        for _ in range(APY_DEMOTE_CONSECUTIVE - 1):
            eng.check_strategy("S1", bad_apy_metrics())
        verdict, _ = eng.check_strategy("S1", bad_apy_metrics())
        assert verdict == VERDICT_DEMOTE

    def test_good_apy_resets_streak(self):
        """Good APY resets the consecutive-bad-APY counter."""
        eng = make_engine()
        for _ in range(3):
            eng.check_strategy("S1", bad_apy_metrics())
        eng.check_strategy("S1", good_metrics())
        streak = eng.get_streak("S1")["consecutive_bad_apy"]
        assert streak == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. Missing/default metrics handling
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingMetrics:

    def test_empty_metrics_dict_is_keep(self):
        """Empty metrics dict uses safe defaults → KEEP."""
        eng = make_engine()
        verdict, _ = eng.check_strategy("S1", {})
        assert verdict == VERDICT_KEEP

    def test_none_values_default_safe(self):
        """None values in metrics use safe defaults → no false alarms."""
        eng = make_engine()
        verdict, _ = eng.check_strategy("S1", {"max_drawdown": None, "sharpe": None, "daily_apy": None})
        assert verdict == VERDICT_KEEP


# ══════════════════════════════════════════════════════════════════════════════
# 5. State management
# ══════════════════════════════════════════════════════════════════════════════

class TestStateManagement:

    def test_reset_strategy_clears_counters(self):
        """reset_strategy removes all streak info for the strategy."""
        eng = make_engine()
        for _ in range(3):
            eng.check_strategy("S1", bad_sharpe_metrics())
        eng.reset_strategy("S1")
        streak = eng.get_streak("S1")
        assert streak["consecutive_bad_sharpe"] == 0
        assert streak["consecutive_bad_apy"] == 0

    def test_record_demotion_writes_to_history(self):
        """record_demotion appends an entry to demotions_executed."""
        eng = make_engine()
        assert len(eng.demotions_history()) == 0
        eng.record_demotion("S1", reason="drawdown breach")
        history = eng.demotions_history()
        assert len(history) == 1
        assert history[0]["strategy_id"] == "S1"
        assert "drawdown" in history[0]["reason"]

    def test_record_multiple_demotions(self):
        """Multiple demotions accumulate in history."""
        eng = make_engine()
        eng.record_demotion("S1", reason="sharpe streak")
        eng.record_demotion("S2", reason="drawdown")
        assert len(eng.demotions_history()) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 6. Bulk interface
# ══════════════════════════════════════════════════════════════════════════════

class TestBulkInterface:

    def test_evaluate_all_returns_verdicts_for_all(self):
        """evaluate_all returns a verdict for every submitted strategy."""
        eng = make_engine()
        strategies = {"S1": good_metrics(), "S2": dd_breach_metrics(), "S7": bad_sharpe_metrics()}
        results = eng.evaluate_all(strategies)
        assert set(results.keys()) == {"S1", "S2", "S7"}

    def test_evaluate_all_correct_verdicts(self):
        """evaluate_all produces correct verdicts per strategy."""
        eng = make_engine()
        results = eng.evaluate_all({
            "GOOD": good_metrics(),
            "DD":   dd_breach_metrics(),
        })
        assert results["GOOD"][0] == VERDICT_KEEP
        assert results["DD"][0] == VERDICT_DEMOTE

    def test_demote_candidates_filters_demote(self):
        """demote_candidates returns only strategy IDs with DEMOTE verdict."""
        eng = make_engine()
        candidates = eng.demote_candidates({
            "S_KEEP":   good_metrics(),
            "S_DEMOTE": dd_breach_metrics(),
        })
        assert "S_DEMOTE" in candidates
        assert "S_KEEP" not in candidates

    def test_to_dict_contains_expected_keys(self):
        """to_dict returns dict with demotion_checks and demotions_executed."""
        eng = make_engine()
        d = eng.to_dict()
        assert "demotion_checks" in d
        assert "demotions_executed" in d
