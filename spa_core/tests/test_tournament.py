"""
Tests for backtesting.tournament — StrategyTournament.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.data_loader import generate_synthetic_history
from backtesting.tournament import StrategyTournament, TournamentResult


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def small_history():
    """10-day synthetic history — fast but covers both strategies."""
    return generate_synthetic_history(days=10, seed=42)


@pytest.fixture(scope="module")
def tournament_result(small_history):
    """Run the tournament once and reuse the result across tests."""
    t = StrategyTournament()
    return t.run(small_history, capital=100_000)


# ─── Basic structure ──────────────────────────────────────────────────────────

class TestTournamentResultType:

    def test_returns_tournament_result(self, tournament_result):
        """run() must return a TournamentResult instance."""
        assert isinstance(tournament_result, TournamentResult)

    def test_winner_is_valid_strategy(self, tournament_result):
        """winner must be one of the strategy names."""
        valid = {"v1_passive", "v2_aggressive", "v3_pendle_focused"}
        assert tournament_result.winner in valid, (
            f"Winner '{tournament_result.winner}' not in {valid}"
        )

    def test_scores_keys_match_strategies(self, tournament_result):
        """scores dict must have an entry for every strategy."""
        t = StrategyTournament()
        for name in t.strategies:
            assert name in tournament_result.scores, (
                f"Missing score for strategy '{name}'"
            )

    def test_metrics_keys_match_strategies(self, tournament_result):
        """metrics dict must have an entry for every strategy."""
        t = StrategyTournament()
        for name in t.strategies:
            assert name in tournament_result.metrics, (
                f"Missing metrics for strategy '{name}'"
            )


# ─── Score validity ───────────────────────────────────────────────────────────

class TestScoreValidity:

    def test_scores_between_0_and_1(self, tournament_result):
        """All composite scores must be in [0, 1]."""
        for name, score in tournament_result.scores.items():
            assert 0.0 <= score <= 1.0, (
                f"Score for '{name}' out of range: {score}"
            )

    def test_winner_has_highest_score(self, tournament_result):
        """The declared winner must have the highest composite score."""
        winner  = tournament_result.winner
        max_score = max(tournament_result.scores.values())
        assert tournament_result.scores[winner] == max_score, (
            f"Winner '{winner}' score {tournament_result.scores[winner]} "
            f"is not the maximum {max_score}"
        )


# ─── Confidence ───────────────────────────────────────────────────────────────

class TestConfidence:

    def test_confidence_is_valid(self, tournament_result):
        """confidence must be one of HIGH / MEDIUM / LOW."""
        assert tournament_result.confidence in {"HIGH", "MEDIUM", "LOW"}, (
            f"Unexpected confidence: '{tournament_result.confidence}'"
        )


# ─── Recommendation ──────────────────────────────────────────────────────────

class TestRecommendation:

    def test_recommendation_is_string(self, tournament_result):
        assert isinstance(tournament_result.recommendation, str)

    def test_recommendation_mentions_winner(self, tournament_result):
        """Recommendation text must reference the winning strategy name."""
        assert tournament_result.winner in tournament_result.recommendation, (
            f"Winner '{tournament_result.winner}' not mentioned in "
            f"recommendation: '{tournament_result.recommendation}'"
        )

    def test_recommendation_nonempty(self, tournament_result):
        assert len(tournament_result.recommendation) > 10


# ─── Robustness ───────────────────────────────────────────────────────────────

class TestRobustness:

    def test_empty_history_does_not_crash(self):
        """Tournament must not crash on empty historical data."""
        t = StrategyTournament()
        result = t.run([], capital=100_000)
        assert isinstance(result, TournamentResult)
        assert result.winner in {"v1_passive", "v2_aggressive", "v3_pendle_focused"}

    def test_single_day_history_does_not_crash(self):
        """A single-day dataset should not crash the tournament."""
        hist = generate_synthetic_history(days=1, seed=7)
        t = StrategyTournament()
        result = t.run(hist, capital=100_000)
        assert isinstance(result, TournamentResult)

    def test_custom_strategies_list(self):
        """Tournament should work with a single-item strategies list."""
        hist = generate_synthetic_history(days=5, seed=1)
        t = StrategyTournament(strategies=["v1_passive"])
        result = t.run(hist)
        assert result.winner == "v1_passive"
        assert "v1_passive" in result.scores

    def test_scores_are_float(self, tournament_result):
        """All score values must be plain Python floats."""
        for name, score in tournament_result.scores.items():
            assert isinstance(score, float), (
                f"Score for '{name}' is not float: {type(score)}"
            )

    def test_metrics_contain_sharpe(self, tournament_result):
        """Each strategy's metrics dict must have a sharpe_ratio key."""
        for name, m in tournament_result.metrics.items():
            assert "sharpe_ratio" in m, (
                f"sharpe_ratio missing from metrics['{name}']"
            )


# ─── IDEA-006: v3_pendle_focused integration ──────────────────────────────────

class TestV3Integration:
    """
    Tests for IDEA-006 / sprint v2.3: v3_pendle_focused is part of the
    default tournament and the go-live tournament criterion accepts v3 wins.
    """

    def test_tournament_includes_v3(self):
        """Default StrategyTournament() must include all three strategies."""
        t = StrategyTournament()
        assert "v1_passive"        in t.strategies
        assert "v2_aggressive"     in t.strategies
        assert "v3_pendle_focused" in t.strategies
        assert len(t.strategies) == 3

    def test_tournament_runs_three_strategies(self, small_history):
        """Tournament must produce scores and metrics for all 3 strategies."""
        result = StrategyTournament().run(small_history, capital=100_000)
        for name in ("v1_passive", "v2_aggressive", "v3_pendle_focused"):
            assert name in result.scores,  f"score missing for {name}"
            assert name in result.metrics, f"metrics missing for {name}"

    def test_recommendation_mentions_runner_up_for_three_way(self, small_history):
        """In a 3-way tournament the recommendation should mention runner-up."""
        result = StrategyTournament().run(small_history, capital=100_000)
        # When winner is determined, recommendation should mention 'vs' or 'also'
        # in 3-way mode (only one strategy is missing from the comparison header).
        rec = result.recommendation
        if len(result.scores) >= 3:
            assert ("vs " in rec or "also ahead of" in rec), (
                f"3-way recommendation missing runner-up tag: '{rec}'"
            )


class TestCheckTournamentWinner:
    """
    Tests for golive.checklist.check_tournament_winner — go-live criterion #10.
    Updated for IDEA-006 to accept v3_pendle_focused as a valid winner.
    """

    def test_v3_wins_is_pass(self):
        """winner=v3_pendle_focused must produce PASS regardless of confidence."""
        from golive.checklist import check_tournament_winner
        data = {
            "winner": "v3_pendle_focused",
            "confidence": "HIGH",
            "scores": {
                "v1_passive":        0.40,
                "v2_aggressive":     0.30,
                "v3_pendle_focused": 0.80,
            },
        }
        result = check_tournament_winner(data)
        assert result["status"] == "PASS", result
        assert "v3_pendle_focused" in result["note"]
        assert result["value"]["v3_score"] == 0.80

    def test_v1_wins_is_pass(self):
        """winner=v1_passive remains PASS (backwards-compatible)."""
        from golive.checklist import check_tournament_winner
        data = {
            "winner": "v1_passive",
            "confidence": "MEDIUM",
            "scores": {
                "v1_passive":        0.70,
                "v2_aggressive":     0.50,
                "v3_pendle_focused": 0.40,
            },
        }
        result = check_tournament_winner(data)
        assert result["status"] == "PASS"

    def test_v2_wins_low_confidence_is_warn(self):
        """winner=v2_aggressive with LOW confidence → WARN, not FAIL."""
        from golive.checklist import check_tournament_winner
        data = {
            "winner": "v2_aggressive",
            "confidence": "LOW",
            "scores": {
                "v1_passive":        0.51,
                "v2_aggressive":     0.55,
                "v3_pendle_focused": 0.50,
            },
        }
        result = check_tournament_winner(data)
        # Top-two tied within 0.001? No: 0.55 - 0.51 = 0.04 > 0.001.
        # So this should trip the LOW-confidence WARN branch.
        assert result["status"] == "WARN", result
        assert "LOW confidence" in result["note"]

    def test_v2_wins_high_confidence_is_fail(self):
        """winner=v2_aggressive with HIGH confidence → FAIL."""
        from golive.checklist import check_tournament_winner
        data = {
            "winner": "v2_aggressive",
            "confidence": "HIGH",
            "scores": {
                "v1_passive":        0.30,
                "v2_aggressive":     0.80,
                "v3_pendle_focused": 0.20,
            },
        }
        result = check_tournament_winner(data)
        assert result["status"] == "FAIL", result

    def test_top_two_tied_is_pass(self):
        """If top-two scores are within 0.001 the criterion is PASS even if
        v2_aggressive is technically the winner."""
        from golive.checklist import check_tournament_winner
        data = {
            "winner": "v2_aggressive",
            "confidence": "LOW",
            "scores": {
                "v1_passive":        0.5005,
                "v2_aggressive":     0.5009,  # gap = 0.0004 < 0.001
                "v3_pendle_focused": 0.40,
            },
        }
        result = check_tournament_winner(data)
        assert result["status"] == "PASS", result
        assert "TIED" in result["note"]

    def test_backwards_compat_no_v3_in_scores(self):
        """Legacy tournament_results.json with only v1+v2 must still work."""
        from golive.checklist import check_tournament_winner
        # Legacy data — no v3 score, v1 winning
        data = {
            "winner": "v1_passive",
            "confidence": "MEDIUM",
            "scores": {"v1_passive": 0.60, "v2_aggressive": 0.40},
        }
        result = check_tournament_winner(data)
        assert result["status"] == "PASS"
        # v3_score should default to 0.0 in the value dict
        assert result["value"]["v3_score"] == 0.0

    def test_missing_winner_is_warn(self):
        """Empty/missing winner field → WARN with 'unavailable' note."""
        from golive.checklist import check_tournament_winner
        result = check_tournament_winner({})
        assert result["status"] == "WARN"
        assert result["value"] == "unavailable"
