"""
Tests for MP-870: ProtocolInsiderActivityMonitor
Run: python3 -m unittest spa_core.tests.test_protocol_insider_activity_monitor -v

≥ 65 tests covering:
- _token_dump_score() all tiers + boundaries
- _wallet_movement_score() all tiers + treasury bonus + cap
- _anomaly_score() tx tiers + dump recency + cap + 999 days
- _correlation_score() all 5 cases
- _risk_label() all 5 labels
- _build_red_flags() each flag condition
- _build_recommendation() all 5 labels
- analyze() full pipeline: empty, single, multi-protocol
- Edge cases: mcap=0, days_since_dump=999
- Log ring-buffer behaviour
- flagged_protocols filter
- average_risk_score calculation
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tempfile
from spa_core.analytics.protocol_insider_activity_monitor import (
    MAX_ENTRIES,
    _anomaly_score,
    _append_log,
    _build_recommendation,
    _build_red_flags,
    _correlation_score,
    _risk_label,
    _token_dump_score,
    _wallet_movement_score,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(**overrides) -> dict:
    """Return a clean baseline protocol dict."""
    base = {
        "name": "TestProto",
        "team_wallet_outflows_30d_usd": 0.0,
        "team_token_holdings_pct": 20.0,
        "governance_token_sales_30d_usd": 0.0,
        "governance_token_mcap_usd": 10_000_000.0,
        "unusual_tx_count_7d": 0,
        "treasury_to_team_transfers_30d_usd": 0.0,
        "days_since_last_team_dump": 999,
        "token_price_change_30d_pct": 5.0,
    }
    base.update(overrides)
    return base


def _tmp_log(td: str) -> Path:
    return Path(td) / "test_insider_log.json"


# ===========================================================================
# _token_dump_score
# ===========================================================================

class TestTokenDumpScore(unittest.TestCase):

    def test_zero_sales_zero_score(self):
        self.assertEqual(_token_dump_score(0.0, 10_000_000.0), 0)

    def test_tiny_sales_zero_score(self):
        # 0.05% → < 0.1 → 0
        self.assertEqual(_token_dump_score(5_000.0, 10_000_000.0), 0)

    def test_point1_pct_score_4(self):
        # exactly 0.1% → 4
        self.assertEqual(_token_dump_score(10_000.0, 10_000_000.0), 4)

    def test_just_below_0_5_pct_score_4(self):
        # 0.49% → 4
        self.assertEqual(_token_dump_score(49_000.0, 10_000_000.0), 4)

    def test_0_5_pct_score_10(self):
        self.assertEqual(_token_dump_score(50_000.0, 10_000_000.0), 10)

    def test_just_below_1_pct_score_10(self):
        self.assertEqual(_token_dump_score(99_000.0, 10_000_000.0), 10)

    def test_1_pct_score_18(self):
        self.assertEqual(_token_dump_score(100_000.0, 10_000_000.0), 18)

    def test_just_below_2_pct_score_18(self):
        self.assertEqual(_token_dump_score(199_000.0, 10_000_000.0), 18)

    def test_2_pct_score_25(self):
        self.assertEqual(_token_dump_score(200_000.0, 10_000_000.0), 25)

    def test_5_pct_score_30(self):
        self.assertEqual(_token_dump_score(500_000.0, 10_000_000.0), 30)

    def test_above_5_pct_score_30(self):
        self.assertEqual(_token_dump_score(1_000_000.0, 10_000_000.0), 30)

    def test_zero_mcap_score_zero(self):
        self.assertEqual(_token_dump_score(1_000_000.0, 0.0), 0)

    def test_score_max_is_30(self):
        self.assertLessEqual(_token_dump_score(999_000_000.0, 10_000_000.0), 30)


# ===========================================================================
# _wallet_movement_score
# ===========================================================================

class TestWalletMovementScore(unittest.TestCase):

    def test_zero_outflow_zero_score(self):
        self.assertEqual(_wallet_movement_score(0.0, 10_000_000.0, 0.0), 0)

    def test_small_outflow_zero_score(self):
        # 0.4% < 0.5 → 0
        self.assertEqual(_wallet_movement_score(40_000.0, 10_000_000.0, 0.0), 0)

    def test_0_5_pct_outflow_score_5(self):
        self.assertEqual(_wallet_movement_score(50_000.0, 10_000_000.0, 0.0), 5)

    def test_1_pct_outflow_score_10(self):
        self.assertEqual(_wallet_movement_score(100_000.0, 10_000_000.0, 0.0), 10)

    def test_2_pct_outflow_score_15(self):
        self.assertEqual(_wallet_movement_score(200_000.0, 10_000_000.0, 0.0), 15)

    def test_5_pct_outflow_score_20(self):
        self.assertEqual(_wallet_movement_score(500_000.0, 10_000_000.0, 0.0), 20)

    def test_treasury_bonus_0_1_pct(self):
        # base score 0 + bonus +1 (0.1%)
        score = _wallet_movement_score(0.0, 10_000_000.0, 10_000.0)
        self.assertEqual(score, 1)

    def test_treasury_bonus_0_5_pct(self):
        # base 0 + bonus +3
        score = _wallet_movement_score(0.0, 10_000_000.0, 50_000.0)
        self.assertEqual(score, 3)

    def test_treasury_bonus_1_pct(self):
        # base 0 + bonus +5
        score = _wallet_movement_score(0.0, 10_000_000.0, 100_000.0)
        self.assertEqual(score, 5)

    def test_cap_at_25(self):
        # max base 20 + max bonus 5 = 25
        score = _wallet_movement_score(5_000_000.0, 10_000_000.0, 5_000_000.0)
        self.assertEqual(score, 25)

    def test_zero_mcap_returns_zero(self):
        self.assertEqual(_wallet_movement_score(999_999.0, 0.0, 999_999.0), 0)

    def test_combined_outflow_and_treasury_caps_at_25(self):
        score = _wallet_movement_score(10_000_000.0, 10_000_000.0, 10_000_000.0)
        self.assertLessEqual(score, 25)


# ===========================================================================
# _anomaly_score
# ===========================================================================

class TestAnomalyScore(unittest.TestCase):

    def test_zero_tx_no_dump_score_zero(self):
        self.assertEqual(_anomaly_score(0, 999), 0)

    def test_1_tx_no_dump_zero(self):
        self.assertEqual(_anomaly_score(1, 999), 0)

    def test_2_tx_score_3(self):
        self.assertEqual(_anomaly_score(2, 999), 3)

    def test_5_tx_score_6(self):
        self.assertEqual(_anomaly_score(5, 999), 6)

    def test_10_tx_score_10(self):
        self.assertEqual(_anomaly_score(10, 999), 10)

    def test_20_tx_score_15(self):
        self.assertEqual(_anomaly_score(20, 999), 15)

    def test_above_20_tx_still_15_base(self):
        self.assertEqual(_anomaly_score(50, 999), 15)

    def test_dump_7_days_bonus_10(self):
        self.assertEqual(_anomaly_score(0, 7), 10)

    def test_dump_30_days_bonus_7(self):
        self.assertEqual(_anomaly_score(0, 30), 7)

    def test_dump_31_days_bonus_4(self):
        self.assertEqual(_anomaly_score(0, 31), 4)

    def test_dump_90_days_bonus_4(self):
        self.assertEqual(_anomaly_score(0, 90), 4)

    def test_dump_91_days_bonus_2(self):
        self.assertEqual(_anomaly_score(0, 91), 2)

    def test_dump_180_days_bonus_2(self):
        self.assertEqual(_anomaly_score(0, 180), 2)

    def test_dump_181_days_bonus_0(self):
        self.assertEqual(_anomaly_score(0, 181), 0)

    def test_dump_999_bonus_0(self):
        self.assertEqual(_anomaly_score(0, 999), 0)

    def test_cap_at_25(self):
        # max tx 15 + max dump bonus 10 = 25
        score = _anomaly_score(20, 7)
        self.assertEqual(score, 25)

    def test_never_exceeds_25(self):
        score = _anomaly_score(100, 1)
        self.assertLessEqual(score, 25)


# ===========================================================================
# _correlation_score
# ===========================================================================

class TestCorrelationScore(unittest.TestCase):

    def test_big_drop_with_dump_score_20(self):
        # price -30%, dump_score=10, wallet=0
        self.assertEqual(_correlation_score(-30.0, 10, 0), 20)

    def test_big_drop_wallet_only_score_20(self):
        # price -30%, dump=0, wallet>10
        self.assertEqual(_correlation_score(-30.0, 0, 11), 20)

    def test_big_drop_no_signals_score_0(self):
        # price -30% but dump=0 and wallet=0
        self.assertEqual(_correlation_score(-30.0, 0, 0), 0)

    def test_minus_15_pct_with_dump_score_15(self):
        self.assertEqual(_correlation_score(-15.0, 5, 0), 15)

    def test_minus_15_no_dump_score_0(self):
        self.assertEqual(_correlation_score(-15.0, 0, 0), 0)

    def test_minus_5_with_dump_score_8(self):
        self.assertEqual(_correlation_score(-5.0, 1, 0), 8)

    def test_minus_5_no_dump_score_0(self):
        self.assertEqual(_correlation_score(-5.0, 0, 5), 0)

    def test_positive_price_selling_into_pump_score_5(self):
        self.assertEqual(_correlation_score(10.0, 20, 0), 5)

    def test_positive_price_low_dump_score_0(self):
        self.assertEqual(_correlation_score(10.0, 10, 0), 0)

    def test_neutral_price_score_0(self):
        self.assertEqual(_correlation_score(0.0, 0, 0), 0)

    def test_exactly_minus30_with_dump_score_20(self):
        self.assertEqual(_correlation_score(-30.0, 1, 0), 20)

    def test_minus_29_with_dump_score_15(self):
        # -29% → not <= -30, but <= -15 and dump>0
        self.assertEqual(_correlation_score(-29.0, 5, 0), 15)


# ===========================================================================
# _risk_label
# ===========================================================================

class TestRiskLabel(unittest.TestCase):

    def test_0_is_clean(self):
        self.assertEqual(_risk_label(0), "CLEAN")

    def test_14_is_clean(self):
        self.assertEqual(_risk_label(14), "CLEAN")

    def test_15_is_watch(self):
        self.assertEqual(_risk_label(15), "WATCH")

    def test_34_is_watch(self):
        self.assertEqual(_risk_label(34), "WATCH")

    def test_35_is_suspicious(self):
        self.assertEqual(_risk_label(35), "SUSPICIOUS")

    def test_54_is_suspicious(self):
        self.assertEqual(_risk_label(54), "SUSPICIOUS")

    def test_55_is_red_flag(self):
        self.assertEqual(_risk_label(55), "RED_FLAG")

    def test_74_is_red_flag(self):
        self.assertEqual(_risk_label(74), "RED_FLAG")

    def test_75_is_exit(self):
        self.assertEqual(_risk_label(75), "EXIT")

    def test_100_is_exit(self):
        self.assertEqual(_risk_label(100), "EXIT")


# ===========================================================================
# _build_red_flags
# ===========================================================================

class TestBuildRedFlags(unittest.TestCase):

    def _flags(self, **overrides):
        defaults = dict(
            name="P",
            governance_token_sales_30d_usd=0.0,
            governance_token_mcap_usd=10_000_000.0,
            treasury_to_team_transfers_30d_usd=0.0,
            unusual_tx_count_7d=0,
            days_since_last_team_dump=999,
            token_price_change_30d_pct=0.0,
            dump_score=0,
            team_token_holdings_pct=30.0,
            team_wallet_outflows_30d_usd=0.0,
        )
        defaults.update(overrides)
        return _build_red_flags(**defaults)

    def test_no_flags_returns_default_message(self):
        flags = self._flags()
        self.assertEqual(flags, ["No significant red flags detected"])

    def test_significant_sales_flag(self):
        # > 1% of mcap
        flags = self._flags(
            governance_token_sales_30d_usd=200_000.0,
            dump_score=25,
        )
        self.assertIn("Significant governance token sales", flags)

    def test_large_treasury_transfer_flag(self):
        flags = self._flags(treasury_to_team_transfers_30d_usd=150_000.0)
        self.assertIn("Large treasury-to-team transfers", flags)

    def test_treasury_just_above_100k(self):
        flags = self._flags(treasury_to_team_transfers_30d_usd=100_001.0)
        self.assertIn("Large treasury-to-team transfers", flags)

    def test_treasury_exactly_100k_no_flag(self):
        flags = self._flags(treasury_to_team_transfers_30d_usd=100_000.0)
        self.assertNotIn("Large treasury-to-team transfers", flags)

    def test_high_anomalous_tx_flag(self):
        flags = self._flags(unusual_tx_count_7d=10)
        self.assertIn("High anomalous transaction count", flags)

    def test_9_tx_no_flag(self):
        flags = self._flags(unusual_tx_count_7d=9)
        self.assertNotIn("High anomalous transaction count", flags)

    def test_recent_dump_flag(self):
        flags = self._flags(days_since_last_team_dump=15)
        self.assertIn("Recent team token dump", flags)

    def test_31_days_no_recent_dump_flag(self):
        flags = self._flags(days_since_last_team_dump=31)
        self.assertNotIn("Recent team token dump", flags)

    def test_selling_during_decline_flag(self):
        flags = self._flags(token_price_change_30d_pct=-25.0, dump_score=15)
        self.assertIn("Selling during price decline", flags)

    def test_decline_low_dump_no_flag(self):
        flags = self._flags(token_price_change_30d_pct=-25.0, dump_score=5)
        self.assertNotIn("Selling during price decline", flags)

    def test_team_reducing_position_flag(self):
        flags = self._flags(
            team_token_holdings_pct=3.0,
            team_wallet_outflows_30d_usd=100_000.0,
        )
        self.assertIn("Team reducing remaining position", flags)

    def test_multiple_flags_can_fire(self):
        flags = self._flags(
            governance_token_sales_30d_usd=200_000.0,
            dump_score=25,
            treasury_to_team_transfers_30d_usd=200_000.0,
            unusual_tx_count_7d=15,
            days_since_last_team_dump=10,
        )
        self.assertGreater(len(flags), 1)


# ===========================================================================
# _build_recommendation
# ===========================================================================

class TestBuildRecommendation(unittest.TestCase):

    def test_exit_message(self):
        rec = _build_recommendation("Aave", "EXIT")
        self.assertIn("EXIT", rec)
        self.assertIn("Aave", rec)

    def test_red_flag_message(self):
        rec = _build_recommendation("Compound", "RED_FLAG")
        self.assertIn("HIGH RISK", rec)
        self.assertIn("Compound", rec)

    def test_suspicious_message(self):
        rec = _build_recommendation("Euler", "SUSPICIOUS")
        self.assertIn("Suspicious", rec)
        self.assertIn("Euler", rec)

    def test_watch_message(self):
        rec = _build_recommendation("Morpho", "WATCH")
        self.assertIn("Minor signals", rec)
        self.assertIn("Morpho", rec)

    def test_clean_message(self):
        rec = _build_recommendation("Yearn", "CLEAN")
        self.assertIn("Yearn", rec)
        self.assertIn("no significant", rec.lower())


# ===========================================================================
# analyze(): empty
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_none_most_suspicious(self):
        self.assertIsNone(analyze([])["most_suspicious"])

    def test_empty_none_cleanest(self):
        self.assertIsNone(analyze([])["cleanest_protocol"])

    def test_empty_no_flagged(self):
        self.assertEqual(analyze([])["flagged_protocols"], [])

    def test_empty_protocols_list(self):
        self.assertEqual(analyze([])["protocols"], [])

    def test_empty_average_score_zero(self):
        self.assertAlmostEqual(analyze([])["average_risk_score"], 0.0)

    def test_empty_has_timestamp(self):
        t0 = time.time()
        res = analyze([])
        self.assertGreaterEqual(res["timestamp"], t0)


# ===========================================================================
# analyze(): single protocol
# ===========================================================================

class TestAnalyzeSingleProtocol(unittest.TestCase):

    def test_clean_protocol_label(self):
        res = analyze([_proto()])
        self.assertEqual(res["protocols"][0]["risk_label"], "CLEAN")

    def test_clean_not_flagged(self):
        res = analyze([_proto()])
        self.assertEqual(res["flagged_protocols"], [])

    def test_single_best_equals_worst(self):
        res = analyze([_proto(name="Solo")])
        self.assertEqual(res["most_suspicious"], "Solo")
        self.assertEqual(res["cleanest_protocol"], "Solo")

    def test_exit_protocol_in_flagged(self):
        p = _proto(
            name="Rug",
            governance_token_sales_30d_usd=1_000_000.0,
            governance_token_mcap_usd=5_000_000.0,   # 20% dump → score 30
            team_wallet_outflows_30d_usd=5_000_000.0, # 100% outflow → 20
            unusual_tx_count_7d=20,                    # → 15
            days_since_last_team_dump=5,               # → +10
            token_price_change_30d_pct=-40.0,          # corr → 20
            treasury_to_team_transfers_30d_usd=500_000.0,
        )
        res = analyze([p])
        self.assertIn("Rug", res["flagged_protocols"])

    def test_average_score_single(self):
        res = analyze([_proto()])
        self.assertAlmostEqual(
            res["average_risk_score"],
            float(res["protocols"][0]["insider_risk_score"]),
        )

    def test_outflow_intensity_zero_mcap(self):
        res = analyze([_proto(governance_token_mcap_usd=0.0,
                               team_wallet_outflows_30d_usd=50_000.0)])
        self.assertAlmostEqual(res["protocols"][0]["outflow_intensity_pct"], 0.0)

    def test_outflow_intensity_calculation(self):
        res = analyze([_proto(
            governance_token_mcap_usd=1_000_000.0,
            team_wallet_outflows_30d_usd=50_000.0,
        )])
        self.assertAlmostEqual(res["protocols"][0]["outflow_intensity_pct"], 5.0)


# ===========================================================================
# analyze(): multi-protocol
# ===========================================================================

class TestAnalyzeMultiProtocol(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            _proto(name="Clean", days_since_last_team_dump=999,
                   governance_token_sales_30d_usd=0.0,
                   team_wallet_outflows_30d_usd=0.0, unusual_tx_count_7d=0),
            _proto(name="Suspicious",
                   governance_token_sales_30d_usd=200_000.0,
                   governance_token_mcap_usd=10_000_000.0,
                   unusual_tx_count_7d=12,
                   days_since_last_team_dump=20,
                   token_price_change_30d_pct=-25.0),
            _proto(name="Watch",
                   unusual_tx_count_7d=3,
                   days_since_last_team_dump=60),
        ]
        self.res = analyze(self.protocols)

    def test_most_suspicious_is_suspicious(self):
        self.assertEqual(self.res["most_suspicious"], "Suspicious")

    def test_cleanest_is_clean(self):
        self.assertEqual(self.res["cleanest_protocol"], "Clean")

    def test_suspicious_in_flagged(self):
        self.assertIn("Suspicious", self.res["flagged_protocols"])

    def test_clean_not_in_flagged(self):
        self.assertNotIn("Clean", self.res["flagged_protocols"])

    def test_protocols_list_length(self):
        self.assertEqual(len(self.res["protocols"]), 3)

    def test_average_score_computed(self):
        scores = [p["insider_risk_score"] for p in self.res["protocols"]]
        expected = sum(scores) / len(scores)
        self.assertAlmostEqual(self.res["average_risk_score"], expected, places=4)

    def test_score_capped_at_100(self):
        for p in self.res["protocols"]:
            self.assertLessEqual(p["insider_risk_score"], 100)

    def test_score_non_negative(self):
        for p in self.res["protocols"]:
            self.assertGreaterEqual(p["insider_risk_score"], 0)


# ===========================================================================
# _append_log ring-buffer
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"x": 1}, lf)
            self.assertTrue(lf.exists())

    def test_valid_json_after_write(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"v": 1}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_accumulates_entries(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(5):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(MAX_ENTRIES + 10):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(MAX_ENTRIES + 5):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(data[-1]["i"], MAX_ENTRIES + 4)

    def test_no_tmp_file_remains(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"v": 1}, lf)
            self.assertFalse(Path(str(lf) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
