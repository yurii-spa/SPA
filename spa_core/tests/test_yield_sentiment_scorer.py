"""
Tests for YieldSentimentScorer (MP-726)
========================================
≥ 65 test cases covering all signals, scoring, classification,
positioning, persistence, ring-buffer, and edge cases.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_sentiment_scorer import (
    SentimentReport,
    _SIGNAL_WEIGHTS,
    compute_signals,
    load_history,
    save_results,
    score_sentiment,
    trend_comparison,
    weights_sum,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bullish_report(data_dir=None) -> SentimentReport:
    """All signals bullish."""
    return score_sentiment(
        total_tvl_usd=100_000_000_000,
        tvl_7d_change_pct=8.0,
        tvl_30d_change_pct=15.0,
        avg_top10_apy=8.0,
        apy_7d_change_pct=7.0,
        new_protocol_launches_30d=7,
        stablecoin_dominance_pct=25.0,
        data_dir=data_dir,
    )


def _bearish_report(data_dir=None) -> SentimentReport:
    """All signals bearish."""
    return score_sentiment(
        total_tvl_usd=20_000_000_000,
        tvl_7d_change_pct=-8.0,
        tvl_30d_change_pct=-15.0,
        avg_top10_apy=2.0,
        apy_7d_change_pct=-7.0,
        new_protocol_launches_30d=1,
        stablecoin_dominance_pct=65.0,
        data_dir=data_dir,
    )


def _neutral_report(data_dir=None) -> SentimentReport:
    """All signals neutral."""
    return score_sentiment(
        total_tvl_usd=40_000_000_000,
        tvl_7d_change_pct=0.0,
        tvl_30d_change_pct=0.0,
        avg_top10_apy=5.0,
        apy_7d_change_pct=0.0,
        new_protocol_launches_30d=3,
        stablecoin_dominance_pct=45.0,
        data_dir=data_dir,
    )


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        total = weights_sum()
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_five_signals_defined(self):
        self.assertEqual(len(_SIGNAL_WEIGHTS), 5)

    def test_all_weights_positive(self):
        for k, v in _SIGNAL_WEIGHTS.items():
            self.assertGreater(v, 0, msg=f"Weight for {k} must be positive")


# ---------------------------------------------------------------------------
# Individual signal direction tests
# ---------------------------------------------------------------------------

class TestTVL7DSignal(unittest.TestCase):
    def _get_signal(self, tvl_7d):
        sigs = compute_signals(tvl_7d, 0.0, 0.0, 3, 45.0)
        return next(s for s in sigs if s.signal_name == "TVL_7D")

    def test_tvl_7d_bullish(self):
        sig = self._get_signal(8.0)
        self.assertEqual(sig.direction, "BULLISH")

    def test_tvl_7d_bearish(self):
        sig = self._get_signal(-8.0)
        self.assertEqual(sig.direction, "BEARISH")

    def test_tvl_7d_neutral_positive(self):
        sig = self._get_signal(2.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_tvl_7d_neutral_zero(self):
        sig = self._get_signal(0.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_tvl_7d_neutral_negative(self):
        sig = self._get_signal(-3.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_tvl_7d_boundary_exactly_5(self):
        sig = self._get_signal(5.0)
        self.assertEqual(sig.direction, "NEUTRAL")  # > 5 required

    def test_tvl_7d_boundary_above_5(self):
        sig = self._get_signal(5.01)
        self.assertEqual(sig.direction, "BULLISH")

    def test_tvl_7d_contribution_bullish(self):
        sig = self._get_signal(8.0)
        self.assertGreater(sig.contribution, 0)

    def test_tvl_7d_contribution_bearish(self):
        sig = self._get_signal(-8.0)
        self.assertLess(sig.contribution, 0)

    def test_tvl_7d_contribution_neutral(self):
        sig = self._get_signal(0.0)
        self.assertAlmostEqual(sig.contribution, 0.0)


class TestTVL30DSignal(unittest.TestCase):
    def _get_signal(self, tvl_30d):
        sigs = compute_signals(0.0, tvl_30d, 0.0, 3, 45.0)
        return next(s for s in sigs if s.signal_name == "TVL_30D")

    def test_tvl_30d_bullish(self):
        sig = self._get_signal(15.0)
        self.assertEqual(sig.direction, "BULLISH")

    def test_tvl_30d_bearish(self):
        sig = self._get_signal(-15.0)
        self.assertEqual(sig.direction, "BEARISH")

    def test_tvl_30d_neutral(self):
        sig = self._get_signal(0.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_tvl_30d_boundary_exactly_10(self):
        sig = self._get_signal(10.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_tvl_30d_boundary_above_10(self):
        sig = self._get_signal(10.01)
        self.assertEqual(sig.direction, "BULLISH")

    def test_tvl_30d_weight(self):
        sig = self._get_signal(15.0)
        self.assertAlmostEqual(sig.weight, 0.20)


class TestYieldExpansionSignal(unittest.TestCase):
    def _get_signal(self, apy_7d):
        sigs = compute_signals(0.0, 0.0, apy_7d, 3, 45.0)
        return next(s for s in sigs if s.signal_name == "YIELD_EXPANSION")

    def test_yield_expansion_bullish(self):
        sig = self._get_signal(7.0)
        self.assertEqual(sig.direction, "BULLISH")

    def test_yield_expansion_bearish(self):
        sig = self._get_signal(-7.0)
        self.assertEqual(sig.direction, "BEARISH")

    def test_yield_expansion_neutral(self):
        sig = self._get_signal(0.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_yield_expansion_boundary_5(self):
        sig = self._get_signal(5.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_yield_expansion_boundary_above_5(self):
        sig = self._get_signal(5.01)
        self.assertEqual(sig.direction, "BULLISH")

    def test_yield_expansion_weight(self):
        sig = self._get_signal(7.0)
        self.assertAlmostEqual(sig.weight, 0.25)


class TestActivitySignal(unittest.TestCase):
    def _get_signal(self, launches):
        sigs = compute_signals(0.0, 0.0, 0.0, launches, 45.0)
        return next(s for s in sigs if s.signal_name == "ACTIVITY")

    def test_activity_bullish(self):
        sig = self._get_signal(7)
        self.assertEqual(sig.direction, "BULLISH")

    def test_activity_bearish(self):
        sig = self._get_signal(1)
        self.assertEqual(sig.direction, "BEARISH")

    def test_activity_neutral(self):
        sig = self._get_signal(3)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_activity_boundary_exactly_5(self):
        sig = self._get_signal(5)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_activity_boundary_above_5(self):
        sig = self._get_signal(6)
        self.assertEqual(sig.direction, "BULLISH")

    def test_activity_boundary_exactly_2(self):
        sig = self._get_signal(2)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_activity_boundary_below_2(self):
        sig = self._get_signal(1)
        self.assertEqual(sig.direction, "BEARISH")

    def test_activity_weight(self):
        sig = self._get_signal(7)
        self.assertAlmostEqual(sig.weight, 0.15)


class TestStablecoinFlightSignal(unittest.TestCase):
    def _get_signal(self, stab_dom):
        sigs = compute_signals(0.0, 0.0, 0.0, 3, stab_dom)
        return next(s for s in sigs if s.signal_name == "STABLECOIN_FLIGHT")

    def test_stablecoin_bearish(self):
        sig = self._get_signal(65.0)
        self.assertEqual(sig.direction, "BEARISH")

    def test_stablecoin_bullish(self):
        sig = self._get_signal(25.0)
        self.assertEqual(sig.direction, "BULLISH")

    def test_stablecoin_neutral(self):
        sig = self._get_signal(45.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_stablecoin_boundary_exactly_60(self):
        sig = self._get_signal(60.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_stablecoin_boundary_above_60(self):
        sig = self._get_signal(60.01)
        self.assertEqual(sig.direction, "BEARISH")

    def test_stablecoin_boundary_exactly_30(self):
        sig = self._get_signal(30.0)
        self.assertEqual(sig.direction, "NEUTRAL")

    def test_stablecoin_boundary_below_30(self):
        sig = self._get_signal(29.99)
        self.assertEqual(sig.direction, "BULLISH")

    def test_stablecoin_contribution_bearish(self):
        sig = self._get_signal(65.0)
        self.assertLess(sig.contribution, 0)


# ---------------------------------------------------------------------------
# Score and classification tests
# ---------------------------------------------------------------------------

class TestScoreClassification(unittest.TestCase):
    def test_all_bullish_score_very_bullish(self):
        r = _bullish_report()
        self.assertGreater(r.normalized_score, 60)
        self.assertEqual(r.sentiment, "VERY_BULLISH")

    def test_all_bearish_score_very_bearish(self):
        r = _bearish_report()
        self.assertLess(r.normalized_score, -60)
        self.assertEqual(r.sentiment, "VERY_BEARISH")

    def test_all_neutral_score_zero(self):
        r = _neutral_report()
        self.assertAlmostEqual(r.normalized_score, 0.0)
        self.assertEqual(r.sentiment, "NEUTRAL")

    def test_raw_score_equals_sum_contributions_times_100(self):
        r = _bullish_report()
        expected = sum(s.contribution for s in r.signals) * 100
        self.assertAlmostEqual(r.raw_score, expected, places=6)

    def test_normalized_score_clamped_max(self):
        r = _bullish_report()
        self.assertLessEqual(r.normalized_score, 100.0)

    def test_normalized_score_clamped_min(self):
        r = _bearish_report()
        self.assertGreaterEqual(r.normalized_score, -100.0)

    def test_five_signals_returned(self):
        r = _bullish_report()
        self.assertEqual(len(r.signals), 5)

    def test_signal_names(self):
        r = _bullish_report()
        names = {s.signal_name for s in r.signals}
        self.assertEqual(names, set(_SIGNAL_WEIGHTS.keys()))


class TestSentimentBoundaries(unittest.TestCase):
    def _score_report(self, tvl7, tvl30, apy7, launches, stab):
        return score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=tvl7,
            tvl_30d_change_pct=tvl30,
            avg_top10_apy=5.0,
            apy_7d_change_pct=apy7,
            new_protocol_launches_30d=launches,
            stablecoin_dominance_pct=stab,
        )

    def test_sentiment_bullish_boundary(self):
        # Score just above 20 → BULLISH
        r = score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=6.0,   # bullish (+0.25)
            tvl_30d_change_pct=0.0,
            avg_top10_apy=5.0,
            apy_7d_change_pct=0.0,
            new_protocol_launches_30d=3,
            stablecoin_dominance_pct=45.0,
        )
        # Only TVL_7D bullish → score = 0.25*100 = 25 → BULLISH
        self.assertEqual(r.sentiment, "BULLISH")

    def test_sentiment_bearish_boundary(self):
        r = score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=-6.0,
            tvl_30d_change_pct=0.0,
            avg_top10_apy=5.0,
            apy_7d_change_pct=0.0,
            new_protocol_launches_30d=3,
            stablecoin_dominance_pct=45.0,
        )
        self.assertEqual(r.sentiment, "BEARISH")


# ---------------------------------------------------------------------------
# Confidence tests
# ---------------------------------------------------------------------------

class TestConfidence(unittest.TestCase):
    def test_confidence_high_very_bullish(self):
        r = _bullish_report()
        self.assertEqual(r.confidence, "HIGH")

    def test_confidence_high_very_bearish(self):
        r = _bearish_report()
        self.assertEqual(r.confidence, "HIGH")

    def test_confidence_low_all_neutral(self):
        r = _neutral_report()
        self.assertEqual(r.confidence, "LOW")

    def test_confidence_medium_range(self):
        # Score ~35 → MEDIUM
        r = score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=6.0,     # bullish +0.25
            tvl_30d_change_pct=11.0,   # bullish +0.20
            avg_top10_apy=5.0,
            apy_7d_change_pct=0.0,     # neutral 0
            new_protocol_launches_30d=3,  # neutral 0
            stablecoin_dominance_pct=45.0,  # neutral 0
        )
        # score = (0.25 + 0.20) * 100 = 45 → MEDIUM
        self.assertEqual(r.confidence, "MEDIUM")


# ---------------------------------------------------------------------------
# Recommended risk % and positioning tests
# ---------------------------------------------------------------------------

class TestRiskAndPositioning(unittest.TestCase):
    def test_risk_very_bullish(self):
        r = _bullish_report()
        self.assertAlmostEqual(r.recommended_risk_pct, 90.0)

    def test_risk_very_bearish(self):
        r = _bearish_report()
        self.assertAlmostEqual(r.recommended_risk_pct, 20.0)

    def test_risk_neutral(self):
        r = _neutral_report()
        self.assertAlmostEqual(r.recommended_risk_pct, 55.0)

    def test_positioning_fully_deployed(self):
        r = _bullish_report()
        self.assertEqual(r.positioning_label, "FULLY_DEPLOYED")

    def test_positioning_very_defensive(self):
        r = _bearish_report()
        self.assertEqual(r.positioning_label, "VERY_DEFENSIVE")

    def test_positioning_balanced(self):
        r = _neutral_report()
        self.assertEqual(r.positioning_label, "BALANCED")

    def test_positioning_mostly_deployed(self):
        # sentiment BULLISH → risk 75% → MOSTLY_DEPLOYED
        r = score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=6.0,
            tvl_30d_change_pct=11.0,
            avg_top10_apy=5.0,
            apy_7d_change_pct=0.0,
            new_protocol_launches_30d=3,
            stablecoin_dominance_pct=45.0,
        )
        self.assertEqual(r.positioning_label, "MOSTLY_DEPLOYED")

    def test_positioning_defensive(self):
        # sentiment BEARISH → risk 35% → DEFENSIVE
        r = score_sentiment(
            total_tvl_usd=1e9,
            tvl_7d_change_pct=-6.0,
            tvl_30d_change_pct=-11.0,
            avg_top10_apy=5.0,
            apy_7d_change_pct=0.0,
            new_protocol_launches_30d=3,
            stablecoin_dominance_pct=45.0,
        )
        self.assertEqual(r.positioning_label, "DEFENSIVE")


# ---------------------------------------------------------------------------
# Market notes tests
# ---------------------------------------------------------------------------

class TestMarketNotes(unittest.TestCase):
    def test_notes_non_empty(self):
        r = _bullish_report()
        self.assertGreater(len(r.market_notes), 0)

    def test_notes_non_empty_bearish(self):
        r = _bearish_report()
        self.assertGreater(len(r.market_notes), 0)

    def test_notes_non_empty_neutral(self):
        r = _neutral_report()
        self.assertGreater(len(r.market_notes), 0)

    def test_notes_are_strings(self):
        r = _bullish_report()
        for note in r.market_notes:
            self.assertIsInstance(note, str)

    def test_notes_contain_sentiment(self):
        r = _bullish_report()
        combined = " ".join(r.market_notes)
        self.assertIn("VERY_BULLISH", combined)


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        r = _bullish_report(data_dir=self._data_dir)
        save_results(r, data_dir=self._data_dir)
        log_path = self._data_dir / "yield_sentiment_log.json"
        self.assertTrue(log_path.exists())

    def test_save_load_round_trip(self):
        r = _bullish_report(data_dir=self._data_dir)
        save_results(r, data_dir=self._data_dir)
        history = load_history(data_dir=self._data_dir)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["sentiment"], "VERY_BULLISH")

    def test_save_appends_multiple(self):
        for _ in range(3):
            r = _neutral_report(data_dir=self._data_dir)
            save_results(r, data_dir=self._data_dir)
        history = load_history(data_dir=self._data_dir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            r = _neutral_report(data_dir=self._data_dir)
            save_results(r, data_dir=self._data_dir)
        history = load_history(data_dir=self._data_dir)
        self.assertLessEqual(len(history), 100)
        self.assertEqual(len(history), 100)

    def test_load_returns_empty_when_no_file(self):
        history = load_history(data_dir=self._data_dir)
        self.assertEqual(history, [])

    def test_saved_to_field_correct(self):
        r = _bullish_report(data_dir=self._data_dir)
        self.assertIn("yield_sentiment_log.json", r.saved_to)

    def test_save_returns_path_string(self):
        r = _bullish_report(data_dir=self._data_dir)
        path = save_results(r, data_dir=self._data_dir)
        self.assertIsInstance(path, str)
        self.assertIn("yield_sentiment_log.json", path)

    def test_saved_data_has_signals(self):
        r = _bullish_report(data_dir=self._data_dir)
        save_results(r, data_dir=self._data_dir)
        history = load_history(data_dir=self._data_dir)
        self.assertIn("signals", history[0])
        self.assertEqual(len(history[0]["signals"]), 5)


# ---------------------------------------------------------------------------
# Trend comparison tests
# ---------------------------------------------------------------------------

class TestTrendComparison(unittest.TestCase):
    def test_trend_empty_returns_error(self):
        result = trend_comparison([])
        self.assertIn("error", result)

    def test_trend_single_report(self):
        r = _bullish_report()
        result = trend_comparison([r])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["latest_sentiment"], "VERY_BULLISH")

    def test_trend_two_reports(self):
        r1 = _bearish_report()
        r2 = _bullish_report()
        result = trend_comparison([r1, r2])
        self.assertEqual(result["earliest_sentiment"], "VERY_BEARISH")
        self.assertEqual(result["latest_sentiment"], "VERY_BULLISH")
        self.assertGreater(result["score_delta"], 0)

    def test_trend_history_list(self):
        reports = [_neutral_report(), _bullish_report(), _bearish_report()]
        result = trend_comparison(reports)
        self.assertEqual(len(result["sentiment_history"]), 3)


# ---------------------------------------------------------------------------
# Dataclass field tests
# ---------------------------------------------------------------------------

class TestDataclassFields(unittest.TestCase):
    def test_report_has_timestamp(self):
        r = _bullish_report()
        self.assertTrue(hasattr(r, "timestamp"))
        self.assertIsNotNone(r.timestamp)

    def test_signal_dataclass_fields(self):
        sigs = compute_signals(6.0, 11.0, 6.0, 7, 25.0)
        for sig in sigs:
            self.assertIsInstance(sig.signal_name, str)
            self.assertIsInstance(sig.value, float)
            self.assertIn(sig.direction, ("BULLISH", "BEARISH", "NEUTRAL"))
            self.assertIsInstance(sig.weight, float)
            self.assertIsInstance(sig.contribution, float)

    def test_contributions_match_direction_times_weight(self):
        sigs = compute_signals(8.0, 15.0, 7.0, 7, 25.0)
        for sig in sigs:
            expected_score = 1.0 if sig.direction == "BULLISH" else (
                -1.0 if sig.direction == "BEARISH" else 0.0)
            self.assertAlmostEqual(
                sig.contribution, expected_score * sig.weight, places=10)


if __name__ == "__main__":
    unittest.main()
