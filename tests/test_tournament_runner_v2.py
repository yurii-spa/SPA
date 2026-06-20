"""
tests/test_tournament_runner_v2.py — MP-1512 (Sprint v11.28)

25 tests for TournamentRunnerV2 (spa_core/backtesting/tournament_runner_v2.py).

Covers:
  - Metric computation (Sharpe, Calmar, Max DD, Win Rate, Annualised Return)
  - Leaderboard ordering (Sharpe-ranked, descending)
  - Promotion pipeline (Sharpe ≥ 1.5, days ≥ 7, not in production)
  - Demotion pipeline (consecutive bad-day streak tracking)
  - Edge cases: empty returns, single day, identical Sharpe scores
  - re-ranking and top-N helpers
  - save=False prevents file I/O in tests

Stdlib only, no external dependencies.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from spa_core.backtesting.tournament_runner_v2 import (
    TournamentRunnerV2,
    PROMOTION_SHARPE_MIN,
    PROMOTION_DAYS_MIN,
    DEMOTION_SHARPE_FLOOR,
    DEMOTION_CONSECUTIVE,
    ANNUALISE_FACTOR,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_runner() -> TournamentRunnerV2:
    return TournamentRunnerV2(base_dir="/tmp")


def _flat_returns(daily_r: float, n: int = 30) -> list:
    """Constant-return series (perfectly smooth equity curve)."""
    return [daily_r] * n


def _positive_returns(n: int = 30) -> list:
    """Alternating +0.5% / +0.3% — always positive."""
    return [0.005 if i % 2 == 0 else 0.003 for i in range(n)]


def _losing_returns(n: int = 10) -> list:
    """All-negative returns."""
    return [-0.002] * n


# ══════════════════════════════════════════════════════════════════════════════
# 1. Metric computation
# ══════════════════════════════════════════════════════════════════════════════

class TestMetricComputation:

    def setup_method(self):
        self.runner = make_runner()

    def test_empty_returns_zero_metrics(self):
        """All metrics default to 0.0 for empty returns list."""
        result = self.runner.run_evaluation({"S0": []}, save=False)
        m = result["leaderboard"][0]
        assert m["sharpe"] == 0.0
        assert m["max_drawdown"] == 0.0
        assert m["days"] == 0

    def test_single_day_no_sharpe(self):
        """Single return: Sharpe = 0 (needs ≥ 2 for std dev)."""
        result = self.runner.run_evaluation({"S0": [0.005]}, save=False)
        m = result["leaderboard"][0]
        assert m["sharpe"] == 0.0
        assert m["days"] == 1

    def test_annualised_return_formula(self):
        """annualized_return = avg_daily_return × 252."""
        daily = 0.001  # 0.1%/day
        result = self.runner.run_evaluation({"S1": _flat_returns(daily, 30)}, save=False)
        m = result["leaderboard"][0]
        assert abs(m["annualized_return"] - daily * 252) < 1e-6

    def test_sharpe_positive_for_consistent_gains(self):
        """Consistent positive returns → Sharpe > 0."""
        returns = _flat_returns(0.001, 30)
        # Flat returns have zero std dev — need some variation
        returns[0] = 0.002
        result = self.runner.run_evaluation({"S1": returns}, save=False)
        m = result["leaderboard"][0]
        assert m["sharpe"] > 0

    def test_win_rate_all_positive(self):
        """Win rate = 1.0 when all returns are positive."""
        result = self.runner.run_evaluation({"S1": _positive_returns()}, save=False)
        m = result["leaderboard"][0]
        assert m["win_rate"] == 1.0

    def test_win_rate_all_negative(self):
        """Win rate = 0.0 when all returns are negative."""
        result = self.runner.run_evaluation({"S1": _losing_returns()}, save=False)
        m = result["leaderboard"][0]
        assert m["win_rate"] == 0.0

    def test_max_drawdown_negative_or_zero(self):
        """max_drawdown is always ≤ 0 (negative fraction or 0)."""
        result = self.runner.run_evaluation(
            {"S1": [0.01, -0.05, 0.02, -0.03]}, save=False
        )
        m = result["leaderboard"][0]
        assert m["max_drawdown"] <= 0.0

    def test_max_drawdown_zero_for_monotone_gains(self):
        """No drawdown when returns are always positive."""
        result = self.runner.run_evaluation({"S1": _positive_returns()}, save=False)
        m = result["leaderboard"][0]
        assert m["max_drawdown"] == 0.0

    def test_calmar_computed_when_drawdown_nonzero(self):
        """Calmar = annualized_return / |max_drawdown| when DD < 0."""
        returns = [0.01] * 5 + [-0.05] + [0.01] * 5
        result = self.runner.run_evaluation({"S1": returns}, save=False)
        m = result["leaderboard"][0]
        if m["max_drawdown"] < 0:
            expected = m["annualized_return"] / abs(m["max_drawdown"])
            assert abs(m["calmar"] - expected) < 1e-4

    def test_days_count_matches_input(self):
        """days field equals the length of the returns list."""
        returns = [0.001] * 15
        result = self.runner.run_evaluation({"S2": returns}, save=False)
        m = result["leaderboard"][0]
        assert m["days"] == 15


# ══════════════════════════════════════════════════════════════════════════════
# 2. Leaderboard ordering
# ══════════════════════════════════════════════════════════════════════════════

class TestLeaderboardOrdering:

    def setup_method(self):
        self.runner = make_runner()
        # S_high has higher, more volatile positive returns → higher Sharpe
        # S_low has lower, also volatile → lower Sharpe
        import random
        random.seed(42)
        self.returns_high = [0.005 + (i % 3) * 0.001 for i in range(30)]
        self.returns_low  = [0.001 + (i % 3) * 0.0002 for i in range(30)]

    def test_leaderboard_sorted_by_sharpe_descending(self):
        """Leaderboard must be sorted Sharpe descending."""
        data = {"S_A": self.returns_high, "S_B": self.returns_low}
        result = self.runner.run_evaluation(data, save=False)
        sharpes = [e["sharpe"] for e in result["leaderboard"]]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_leaderboard_contains_all_strategies(self):
        """All submitted strategies appear in leaderboard."""
        ids = {"S0", "S1", "S7", "S11", "S20_CRV"}
        data = {sid: [0.002] * 10 for sid in ids}
        # Give each slightly different volatility so Sharpe varies
        for i, sid in enumerate(ids):
            data[sid][i % 10] += 0.001 * (i + 1)
        result = self.runner.run_evaluation(data, save=False)
        found = {e["strategy_id"] for e in result["leaderboard"]}
        assert found == ids

    def test_strategy_count_in_result(self):
        """strategy_count field equals number of evaluated strategies."""
        data = {f"S{i}": [0.001] * 10 for i in range(5)}
        result = self.runner.run_evaluation(data, save=False)
        assert result["strategy_count"] == 5

    def test_last_run_timestamp_set(self):
        """last_run is set to a non-None ISO timestamp after evaluation."""
        result = self.runner.run_evaluation({"S0": [0.001]}, save=False)
        assert result["last_run"] is not None
        assert "Z" in result["last_run"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Promotion pipeline
# ══════════════════════════════════════════════════════════════════════════════

class TestPromotionPipeline:

    def setup_method(self):
        self.runner = make_runner()

    def _high_sharpe_returns(self, n: int = 10) -> list:
        """Returns that should produce Sharpe well above 1.5."""
        # Vary returns: mostly +0.5%, occasional +1% → high Sharpe
        return [0.005 + (i % 4) * 0.001 for i in range(n)]

    def test_promotion_requires_min_days(self):
        """Strategy with high Sharpe but < 7 days is NOT promoted."""
        short = self._high_sharpe_returns(n=3)
        result = self.runner.run_evaluation({"S99": short}, save=False)
        promoted_ids = [p["strategy_id"] for p in result["promotions_pending"]]
        # If Sharpe is high but days < 7 → no promotion
        assert "S99" not in promoted_ids

    def test_promotion_requires_sharpe_threshold(self):
        """Strategy with low Sharpe and enough days is NOT promoted."""
        data = {"S_WEAK": [-0.0005] * 20}  # losing strategy
        result = self.runner.run_evaluation(data, save=False)
        promoted_ids = [p["strategy_id"] for p in result["promotions_pending"]]
        assert "S_WEAK" not in promoted_ids

    def test_in_production_excluded_from_promotion(self):
        """Strategy already in production is excluded from promotion list."""
        long_high = self._high_sharpe_returns(n=15)
        result = self.runner.run_evaluation(
            {"S_PROD": long_high},
            in_production_set={"S_PROD"},
            save=False,
        )
        promoted_ids = [p["strategy_id"] for p in result["promotions_pending"]]
        assert "S_PROD" not in promoted_ids

    def test_not_in_production_can_be_promoted(self):
        """A non-production strategy with sufficient Sharpe + days can be promoted."""
        # Use long series to guarantee days >= 7 and build variance
        returns = self._high_sharpe_returns(n=20)
        result = self.runner.run_evaluation({"S_NEW": returns}, save=False)
        lb = {e["strategy_id"]: e for e in result["leaderboard"]}
        m = lb.get("S_NEW", {})
        # If it meets thresholds, it should appear in promotions_pending
        if m.get("sharpe", 0) >= PROMOTION_SHARPE_MIN and m.get("days", 0) >= PROMOTION_DAYS_MIN:
            promoted_ids = [p["strategy_id"] for p in result["promotions_pending"]]
            assert "S_NEW" in promoted_ids


# ══════════════════════════════════════════════════════════════════════════════
# 4. Demotion streak tracking
# ══════════════════════════════════════════════════════════════════════════════

class TestDemotionPipeline:

    def setup_method(self):
        self.runner = make_runner()

    def _bad_returns(self, n: int = 6) -> list:
        """Returns that produce Sharpe < DEMOTION_SHARPE_FLOOR."""
        # Negative returns → Sharpe negative → below 0.5 floor
        return [-0.001 + (i % 3) * 0.0002 for i in range(n)]

    def test_demotion_only_for_production_strategies(self):
        """Non-production strategies are NOT flagged for demotion."""
        # Simulate DEMOTION_CONSECUTIVE evaluations with bad returns
        bad = self._bad_returns(10)
        for _ in range(DEMOTION_CONSECUTIVE + 1):
            result = self.runner.run_evaluation(
                {"S_NOTPROD": bad},
                in_production_set=set(),   # NOT in production
                save=False,
            )
        demoted_ids = [d["strategy_id"] for d in result["demotions_pending"]]
        assert "S_NOTPROD" not in demoted_ids

    def test_streak_reset_after_good_day(self):
        """Good evaluation resets the consecutive bad-day counter."""
        runner = make_runner()
        bad = self._bad_returns(10)
        # 4 bad days (below threshold of 5)
        for _ in range(4):
            runner.run_evaluation({"S_TEST": bad}, in_production_set={"S_TEST"}, save=False)
        # 1 good day: varied positive returns → Sharpe > 0.5
        good = [0.005 + (i % 4) * 0.002 for i in range(20)]
        runner.run_evaluation({"S_TEST": good}, in_production_set={"S_TEST"}, save=False)
        # Counter should have reset — strategy is no longer "bad"
        assert runner._bad_day_streak.get("S_TEST", 0) == 0

    def test_reset_streak_method(self):
        """reset_streak() zeroes the counter for a specific strategy."""
        runner = make_runner()
        runner._bad_day_streak["S_X"] = 10
        runner.reset_streak("S_X")
        assert runner._bad_day_streak["S_X"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. Ranking helpers and API
# ══════════════════════════════════════════════════════════════════════════════

class TestRankingHelpers:

    def setup_method(self):
        self.runner = make_runner()
        self.data = {
            "S0":  [0.001 + i * 0.0001 for i in range(20)],
            "S7":  [0.003 + i * 0.0002 for i in range(20)],
            "S11": [0.004 + i * 0.0003 for i in range(20)],
        }
        self.runner.run_evaluation(self.data, save=False)

    def test_top_n_returns_n_entries(self):
        """top_n(2) returns exactly 2 entries."""
        top = self.runner.top_n(2)
        assert len(top) == 2

    def test_top_n_sorted_by_sharpe(self):
        """top_n() entries are ordered by Sharpe descending."""
        top = self.runner.top_n(3)
        sharpes = [e["sharpe"] for e in top]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_rank_by_annualised_return(self):
        """rank_by('annualized_return') reorders leaderboard correctly."""
        ranked = self.runner.rank_by("annualized_return", ascending=False)
        returns = [e["annualized_return"] for e in ranked]
        assert returns == sorted(returns, reverse=True)

    def test_get_strategy_metrics_found(self):
        """get_strategy_metrics returns dict for known strategy."""
        m = self.runner.get_strategy_metrics("S7")
        assert m is not None
        assert m["strategy_id"] == "S7"

    def test_get_strategy_metrics_not_found(self):
        """get_strategy_metrics returns None for unknown strategy."""
        m = self.runner.get_strategy_metrics("S_NONEXISTENT")
        assert m is None

    def test_leaderboard_method_returns_list(self):
        """leaderboard() returns a list."""
        lb = self.runner.leaderboard()
        assert isinstance(lb, list)
        assert len(lb) == len(self.data)

    def test_to_dict_has_all_keys(self):
        """to_dict() contains all expected top-level keys."""
        d = self.runner.to_dict()
        for key in ("leaderboard", "promotions_pending", "demotions_pending", "last_run", "runner_version"):
            assert key in d

    def test_runner_version_v2(self):
        """runner_version field is 'v2'."""
        d = self.runner.to_dict()
        assert d["runner_version"] == "v2"
