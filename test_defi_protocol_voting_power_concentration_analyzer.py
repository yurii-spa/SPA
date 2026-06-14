"""
Tests for MP-1096 DeFiProtocolVotingPowerConcentrationAnalyzer
≥110 unittest tests — pure stdlib, no third-party dependencies.

Run:
    python3 -m unittest spa_core.tests.test_defi_protocol_voting_power_concentration_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_voting_power_concentration_analyzer import (
    DeFiProtocolVotingPowerConcentrationAnalyzer,
    analyze,
    _clamp,
    _herfindahl_index,
    _effective_control_pct,
    _quorum_achievability_score,
    _governance_risk_score,
    _governance_label,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    """Return a path to a temp file that doesn't yet exist (for log tests)."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_params(**overrides) -> dict:
    p = {
        "protocol_name": "TestProtocol",
        "top1_voting_power_pct": 10.0,
        "top5_voting_power_pct": 25.0,
        "top10_voting_power_pct": 40.0,
        "total_token_supply": 1_000_000.0,
        "circulating_supply": 800_000.0,
        "dao_treasury_pct": 15.0,
        "team_vesting_pct": 8.0,
        "quorum_threshold_pct": 30.0,
    }
    p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Tests: _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):

    def test_clamp_middle(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_lo(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_hi(self):
        self.assertEqual(_clamp(110.0), 100.0)

    def test_clamp_exact_zero(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_exact_hundred(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_clamp_custom_bounds(self):
        self.assertEqual(_clamp(50.0, 0.0, 10.0), 10.0)

    def test_clamp_negative_custom_lo(self):
        self.assertEqual(_clamp(-50.0, -100.0, 0.0), -50.0)


# ---------------------------------------------------------------------------
# Tests: _herfindahl_index
# ---------------------------------------------------------------------------

class TestHerfindahlIndex(unittest.TestCase):

    def test_zero_all(self):
        """All zero shares → HHI == 0."""
        self.assertEqual(_herfindahl_index(0.0, 0.0, 0.0), 0.0)

    def test_one_holder_100pct(self):
        """Single holder owns 100% → HHI = 10000."""
        hhi = _herfindahl_index(100.0, 100.0, 100.0)
        self.assertAlmostEqual(hhi, 10000.0, places=1)

    def test_equal_split_top10(self):
        """10 holders each 10% → sum of 10*100 = 1000."""
        # top1=10, top5=50, top10=100
        hhi = _herfindahl_index(10.0, 50.0, 100.0)
        # share_1 = 10^2 = 100
        # share_2_5 each = (50-10)/4 = 10 → 4*100 = 400
        # share_6_10 each = (100-50)/5 = 10 → 5*100 = 500
        self.assertAlmostEqual(hhi, 1000.0, places=4)

    def test_top5_equals_top10(self):
        """Holders 6-10 own nothing → no contribution from that bucket."""
        hhi = _herfindahl_index(20.0, 60.0, 60.0)
        # s1=20^2=400, 4*(10^2)=400, 5*(0^2)=0
        self.assertAlmostEqual(hhi, 800.0, places=4)

    def test_top1_equals_top5(self):
        """Holders 2-5 own nothing."""
        hhi = _herfindahl_index(40.0, 40.0, 80.0)
        # s1=40^2=1600, 4*(0^2)=0, 5*(8^2)=320
        self.assertAlmostEqual(hhi, 1920.0, places=4)

    def test_negative_bracket_clamped(self):
        """top5 < top1 should not produce negative HHI components."""
        hhi = _herfindahl_index(30.0, 20.0, 50.0)
        self.assertGreaterEqual(hhi, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_herfindahl_index(10.0, 30.0, 50.0), float)

    def test_symmetric_buckets(self):
        """Verify algebra: top1=0, top5=20, top10=30 → 4*(5^2)+5*(2^2)."""
        hhi = _herfindahl_index(0.0, 20.0, 30.0)
        expected = 4 * (5.0 ** 2) + 5 * (2.0 ** 2)
        self.assertAlmostEqual(hhi, expected, places=4)

    def test_large_top1(self):
        """Dominant single holder, rest negligible."""
        hhi = _herfindahl_index(80.0, 85.0, 90.0)
        self.assertGreater(hhi, 6000.0)

    def test_result_rounded_to_4dp(self):
        """Result should be rounded to 4 decimal places."""
        hhi = _herfindahl_index(11.1, 33.3, 55.5)
        self.assertEqual(hhi, round(hhi, 4))


# ---------------------------------------------------------------------------
# Tests: _effective_control_pct
# ---------------------------------------------------------------------------

class TestEffectiveControlPct(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_effective_control_pct(30.0, 20.0), 50.0)

    def test_capped_at_100(self):
        self.assertEqual(_effective_control_pct(80.0, 40.0), 100.0)

    def test_zero(self):
        self.assertEqual(_effective_control_pct(0.0, 0.0), 0.0)

    def test_top1_only(self):
        self.assertAlmostEqual(_effective_control_pct(25.0, 0.0), 25.0)

    def test_team_only(self):
        self.assertAlmostEqual(_effective_control_pct(0.0, 15.0), 15.0)

    def test_returns_float(self):
        self.assertIsInstance(_effective_control_pct(10.0, 10.0), float)

    def test_exact_100(self):
        self.assertEqual(_effective_control_pct(50.0, 50.0), 100.0)

    def test_large_values_capped(self):
        self.assertEqual(_effective_control_pct(100.0, 100.0), 100.0)

    def test_rounded_to_4dp(self):
        v = _effective_control_pct(33.333, 11.111)
        self.assertEqual(v, round(v, 4))


# ---------------------------------------------------------------------------
# Tests: _quorum_achievability_score
# ---------------------------------------------------------------------------

class TestQuorumAchievabilityScore(unittest.TestCase):

    def test_zero_quorum_returns_100(self):
        self.assertEqual(_quorum_achievability_score(50.0, 0.0), 100)

    def test_top10_equals_quorum_returns_100(self):
        self.assertEqual(_quorum_achievability_score(40.0, 40.0), 100)

    def test_top10_exceeds_quorum_returns_100(self):
        self.assertEqual(_quorum_achievability_score(80.0, 50.0), 100)

    def test_top10_is_half_quorum_returns_50(self):
        self.assertEqual(_quorum_achievability_score(25.0, 50.0), 50)

    def test_top10_zero_returns_0(self):
        self.assertEqual(_quorum_achievability_score(0.0, 50.0), 0)

    def test_returns_int(self):
        self.assertIsInstance(_quorum_achievability_score(30.0, 40.0), int)

    def test_high_quorum_low_concentration(self):
        score = _quorum_achievability_score(20.0, 80.0)
        self.assertLessEqual(score, 30)

    def test_low_quorum_high_concentration(self):
        score = _quorum_achievability_score(90.0, 10.0)
        self.assertEqual(score, 100)

    def test_negative_quorum_treated_as_zero(self):
        self.assertEqual(_quorum_achievability_score(50.0, -1.0), 100)

    def test_score_in_range(self):
        for top10 in [0, 10, 25, 50, 75, 100]:
            for q in [5, 10, 25, 50, 75]:
                s = _quorum_achievability_score(float(top10), float(q))
                self.assertGreaterEqual(s, 0)
                self.assertLessEqual(s, 100)


# ---------------------------------------------------------------------------
# Tests: _governance_risk_score
# ---------------------------------------------------------------------------

class TestGovernanceRiskScore(unittest.TestCase):

    def test_all_zero(self):
        self.assertEqual(_governance_risk_score(0.0, 0.0, 0.0), 0)

    def test_all_100(self):
        self.assertEqual(_governance_risk_score(100.0, 100.0, 100.0), 100)

    def test_returns_int(self):
        self.assertIsInstance(_governance_risk_score(50.0, 30.0, 20.0), int)

    def test_in_range(self):
        for t5 in [0, 20, 40, 60, 80, 100]:
            for t1 in [0, 10, 30, 50]:
                for tv in [0, 10, 20]:
                    s = _governance_risk_score(float(t5), float(t1), float(tv))
                    self.assertGreaterEqual(s, 0)
                    self.assertLessEqual(s, 100)

    def test_higher_top5_increases_risk(self):
        s_low = _governance_risk_score(10.0, 5.0, 5.0)
        s_high = _governance_risk_score(80.0, 5.0, 5.0)
        self.assertGreater(s_high, s_low)

    def test_higher_top1_increases_risk(self):
        s_low = _governance_risk_score(30.0, 5.0, 5.0)
        s_high = _governance_risk_score(30.0, 50.0, 5.0)
        self.assertGreater(s_high, s_low)

    def test_higher_team_increases_risk(self):
        s_low = _governance_risk_score(30.0, 10.0, 5.0)
        s_high = _governance_risk_score(30.0, 10.0, 50.0)
        self.assertGreater(s_high, s_low)

    def test_negative_inputs_clamped_to_zero(self):
        self.assertEqual(_governance_risk_score(-50.0, -50.0, -50.0), 0)

    def test_over_100_inputs_clamped(self):
        self.assertEqual(_governance_risk_score(200.0, 200.0, 200.0), 100)

    def test_known_value(self):
        # top5=60, top1=30, team=20
        # 0.55*60 + 0.25*30 + 0.20*20 = 33+7.5+4 = 44.5 → round-half-to-even → 44
        s = _governance_risk_score(60.0, 30.0, 20.0)
        self.assertEqual(s, 44)

    def test_weights_sum_to_100(self):
        # With all inputs = 100 → risk = 100
        self.assertEqual(_governance_risk_score(100.0, 100.0, 100.0), 100)


# ---------------------------------------------------------------------------
# Tests: _governance_label
# ---------------------------------------------------------------------------

class TestGovernanceLabel(unittest.TestCase):

    def test_below_20_decentralized(self):
        self.assertEqual(_governance_label(0.0), "DECENTRALIZED")
        self.assertEqual(_governance_label(10.0), "DECENTRALIZED")
        self.assertEqual(_governance_label(19.9), "DECENTRALIZED")

    def test_exactly_20_moderately_concentrated(self):
        self.assertEqual(_governance_label(20.0), "MODERATELY_CONCENTRATED")

    def test_between_20_35_moderately_concentrated(self):
        self.assertEqual(_governance_label(25.0), "MODERATELY_CONCENTRATED")
        self.assertEqual(_governance_label(34.9), "MODERATELY_CONCENTRATED")

    def test_exactly_35_concentrated(self):
        self.assertEqual(_governance_label(35.0), "CONCENTRATED")

    def test_between_35_51_concentrated(self):
        self.assertEqual(_governance_label(40.0), "CONCENTRATED")
        self.assertEqual(_governance_label(50.9), "CONCENTRATED")

    def test_exactly_51_highly_concentrated(self):
        self.assertEqual(_governance_label(51.0), "HIGHLY_CONCENTRATED")

    def test_between_51_70_highly_concentrated(self):
        self.assertEqual(_governance_label(60.0), "HIGHLY_CONCENTRATED")
        self.assertEqual(_governance_label(70.0), "HIGHLY_CONCENTRATED")

    def test_above_70_governance_cartel(self):
        self.assertEqual(_governance_label(70.1), "GOVERNANCE_CARTEL")
        self.assertEqual(_governance_label(80.0), "GOVERNANCE_CARTEL")
        self.assertEqual(_governance_label(100.0), "GOVERNANCE_CARTEL")

    def test_returns_string(self):
        self.assertIsInstance(_governance_label(50.0), str)

    def test_all_five_labels_reachable(self):
        labels = {_governance_label(v) for v in [5, 25, 42, 60, 85]}
        expected = {
            "DECENTRALIZED",
            "MODERATELY_CONCENTRATED",
            "CONCENTRATED",
            "HIGHLY_CONCENTRATED",
            "GOVERNANCE_CARTEL",
        }
        self.assertEqual(labels, expected)


# ---------------------------------------------------------------------------
# Tests: _atomic_log
# ---------------------------------------------------------------------------

class TestAtomicLog(unittest.TestCase):

    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"test": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_appends_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["n"], 1)
        self.assertEqual(data[1]["n"], 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(120):
            _atomic_log(path, {"i": i}, log_cap=100)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 119)
        os.unlink(path)

    def test_recovers_corrupt_file(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("NOT JSON {{{{")
        _atomic_log(path, {"k": "v"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_output_is_valid_json(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(path)


# ---------------------------------------------------------------------------
# Tests: DeFiProtocolVotingPowerConcentrationAnalyzer
# ---------------------------------------------------------------------------

class TestAnalyzerOutputStructure(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolVotingPowerConcentrationAnalyzer(
            log_path=_tmp_log()
        )
        self.params = _base_params()

    def tearDown(self):
        log = self.analyzer._log_path
        if os.path.exists(log):
            os.unlink(log)

    def test_returns_dict(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r, dict)

    def test_required_keys_present(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        required = {
            "protocol_name",
            "top1_voting_power_pct",
            "top5_voting_power_pct",
            "top10_voting_power_pct",
            "total_token_supply",
            "circulating_supply",
            "dao_treasury_pct",
            "team_vesting_pct",
            "quorum_threshold_pct",
            "herfindahl_index",
            "effective_control_pct",
            "quorum_achievability_score",
            "governance_risk_score",
            "governance_label",
            "timestamp",
        }
        self.assertTrue(required.issubset(r.keys()))

    def test_herfindahl_index_is_float(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r["herfindahl_index"], float)

    def test_effective_control_pct_is_float(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r["effective_control_pct"], float)

    def test_quorum_achievability_score_is_int(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r["quorum_achievability_score"], int)

    def test_governance_risk_score_is_int(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r["governance_risk_score"], int)

    def test_governance_label_is_str(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertIsInstance(r["governance_label"], str)

    def test_timestamp_present_and_positive(self):
        r = self.analyzer.analyze(self.params, {"skip_log": True})
        self.assertGreater(r["timestamp"], 0)

    def test_protocol_name_preserved(self):
        r = self.analyzer.analyze(
            _base_params(protocol_name="AaveV3"), {"skip_log": True}
        )
        self.assertEqual(r["protocol_name"], "AaveV3")


class TestAnalyzerLabels(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def _label(self, top5):
        return self.a.analyze(
            _base_params(top5_voting_power_pct=top5), {"skip_log": True}
        )["governance_label"]

    def test_label_decentralized_at_0(self):
        self.assertEqual(self._label(0.0), "DECENTRALIZED")

    def test_label_decentralized_at_10(self):
        self.assertEqual(self._label(10.0), "DECENTRALIZED")

    def test_label_decentralized_at_19_9(self):
        self.assertEqual(self._label(19.9), "DECENTRALIZED")

    def test_label_moderately_concentrated_at_20(self):
        self.assertEqual(self._label(20.0), "MODERATELY_CONCENTRATED")

    def test_label_moderately_concentrated_at_27(self):
        self.assertEqual(self._label(27.0), "MODERATELY_CONCENTRATED")

    def test_label_moderately_concentrated_at_34_9(self):
        self.assertEqual(self._label(34.9), "MODERATELY_CONCENTRATED")

    def test_label_concentrated_at_35(self):
        self.assertEqual(self._label(35.0), "CONCENTRATED")

    def test_label_concentrated_at_43(self):
        self.assertEqual(self._label(43.0), "CONCENTRATED")

    def test_label_concentrated_at_50_9(self):
        self.assertEqual(self._label(50.9), "CONCENTRATED")

    def test_label_highly_concentrated_at_51(self):
        self.assertEqual(self._label(51.0), "HIGHLY_CONCENTRATED")

    def test_label_highly_concentrated_at_60(self):
        self.assertEqual(self._label(60.0), "HIGHLY_CONCENTRATED")

    def test_label_highly_concentrated_at_70(self):
        self.assertEqual(self._label(70.0), "HIGHLY_CONCENTRATED")

    def test_label_governance_cartel_at_70_1(self):
        self.assertEqual(self._label(70.1), "GOVERNANCE_CARTEL")

    def test_label_governance_cartel_at_85(self):
        self.assertEqual(self._label(85.0), "GOVERNANCE_CARTEL")

    def test_label_governance_cartel_at_100(self):
        self.assertEqual(self._label(100.0), "GOVERNANCE_CARTEL")


class TestAnalyzerHHI(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_hhi_increases_with_concentration(self):
        r_low = self.a.analyze(
            _base_params(
                top1_voting_power_pct=5.0,
                top5_voting_power_pct=15.0,
                top10_voting_power_pct=25.0,
            ),
            {"skip_log": True},
        )
        r_high = self.a.analyze(
            _base_params(
                top1_voting_power_pct=40.0,
                top5_voting_power_pct=70.0,
                top10_voting_power_pct=85.0,
            ),
            {"skip_log": True},
        )
        self.assertGreater(r_high["herfindahl_index"], r_low["herfindahl_index"])

    def test_hhi_non_negative(self):
        r = self.a.analyze(_base_params(), {"skip_log": True})
        self.assertGreaterEqual(r["herfindahl_index"], 0.0)

    def test_hhi_at_most_10000(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=100.0,
                top5_voting_power_pct=100.0,
                top10_voting_power_pct=100.0,
            ),
            {"skip_log": True},
        )
        self.assertLessEqual(r["herfindahl_index"], 10000.0)

    def test_hhi_zero_inputs(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=0.0,
                top5_voting_power_pct=0.0,
                top10_voting_power_pct=0.0,
            ),
            {"skip_log": True},
        )
        self.assertEqual(r["herfindahl_index"], 0.0)


class TestAnalyzerEffectiveControl(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_effective_control_combines_top1_and_team(self):
        r = self.a.analyze(
            _base_params(top1_voting_power_pct=20.0, team_vesting_pct=15.0),
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["effective_control_pct"], 35.0)

    def test_effective_control_capped_at_100(self):
        r = self.a.analyze(
            _base_params(top1_voting_power_pct=70.0, team_vesting_pct=50.0),
            {"skip_log": True},
        )
        self.assertEqual(r["effective_control_pct"], 100.0)

    def test_effective_control_zero(self):
        r = self.a.analyze(
            _base_params(top1_voting_power_pct=0.0, team_vesting_pct=0.0),
            {"skip_log": True},
        )
        self.assertEqual(r["effective_control_pct"], 0.0)


class TestAnalyzerQuorumScore(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_quorum_score_100_when_top10_exceeds_threshold(self):
        r = self.a.analyze(
            _base_params(top10_voting_power_pct=60.0, quorum_threshold_pct=40.0),
            {"skip_log": True},
        )
        self.assertEqual(r["quorum_achievability_score"], 100)

    def test_quorum_score_low_when_top10_far_below_threshold(self):
        r = self.a.analyze(
            _base_params(top10_voting_power_pct=10.0, quorum_threshold_pct=80.0),
            {"skip_log": True},
        )
        self.assertLessEqual(r["quorum_achievability_score"], 20)

    def test_quorum_score_in_range(self):
        r = self.a.analyze(_base_params(), {"skip_log": True})
        s = r["quorum_achievability_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)


class TestAnalyzerRiskScore(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_risk_score_in_range(self):
        r = self.a.analyze(_base_params(), {"skip_log": True})
        s = r["governance_risk_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_cartel_has_high_risk(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=60.0,
                top5_voting_power_pct=80.0,
                team_vesting_pct=30.0,
            ),
            {"skip_log": True},
        )
        self.assertGreater(r["governance_risk_score"], 60)

    def test_decentralized_has_low_risk(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=2.0,
                top5_voting_power_pct=5.0,
                team_vesting_pct=2.0,
            ),
            {"skip_log": True},
        )
        self.assertLess(r["governance_risk_score"], 20)


class TestAnalyzerEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_negative_pct_inputs_clamped(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=-10.0,
                top5_voting_power_pct=-20.0,
                top10_voting_power_pct=-30.0,
                team_vesting_pct=-5.0,
            ),
            {"skip_log": True},
        )
        self.assertGreaterEqual(r["herfindahl_index"], 0.0)
        self.assertGreaterEqual(r["effective_control_pct"], 0.0)
        self.assertEqual(r["governance_label"], "DECENTRALIZED")

    def test_over_100_pct_inputs_clamped(self):
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=150.0,
                top5_voting_power_pct=200.0,
                team_vesting_pct=120.0,
            ),
            {"skip_log": True},
        )
        self.assertLessEqual(r["herfindahl_index"], 10000.0)
        self.assertLessEqual(r["effective_control_pct"], 100.0)
        self.assertLessEqual(r["governance_risk_score"], 100)

    def test_missing_protocol_name_defaults_unknown(self):
        p = _base_params()
        del p["protocol_name"]
        r = self.a.analyze(p, {"skip_log": True})
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_all_zero_inputs(self):
        r = self.a.analyze(
            {
                "protocol_name": "Zero",
                "top1_voting_power_pct": 0.0,
                "top5_voting_power_pct": 0.0,
                "top10_voting_power_pct": 0.0,
                "total_token_supply": 0.0,
                "circulating_supply": 0.0,
                "dao_treasury_pct": 0.0,
                "team_vesting_pct": 0.0,
                "quorum_threshold_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["herfindahl_index"], 0.0)
        self.assertEqual(r["effective_control_pct"], 0.0)
        self.assertEqual(r["governance_label"], "DECENTRALIZED")

    def test_string_numeric_inputs_coerced(self):
        p = _base_params()
        p["top5_voting_power_pct"] = "25.0"
        r = self.a.analyze(p, {"skip_log": True})
        self.assertIsInstance(r["top5_voting_power_pct"], float)

    def test_quorum_zero_gives_score_100(self):
        r = self.a.analyze(
            _base_params(quorum_threshold_pct=0.0), {"skip_log": True}
        )
        self.assertEqual(r["quorum_achievability_score"], 100)

    def test_total_supply_and_circulating_passed_through(self):
        r = self.a.analyze(
            _base_params(total_token_supply=5_000_000.0, circulating_supply=3_000_000.0),
            {"skip_log": True},
        )
        self.assertEqual(r["total_token_supply"], 5_000_000.0)
        self.assertEqual(r["circulating_supply"], 3_000_000.0)

    def test_dao_treasury_passed_through(self):
        r = self.a.analyze(_base_params(dao_treasury_pct=20.0), {"skip_log": True})
        self.assertEqual(r["dao_treasury_pct"], 20.0)


class TestAnalyzerLogging(unittest.TestCase):

    def test_log_written_by_default(self):
        log = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log)
        a.analyze(_base_params())
        self.assertTrue(os.path.exists(log))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_skip_log_prevents_write(self):
        log = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log)
        a.analyze(_base_params(), {"skip_log": True})
        self.assertFalse(os.path.exists(log))

    def test_log_ring_buffer_trimmed(self):
        log = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log, log_cap=10)
        for _ in range(15):
            a.analyze(_base_params())
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)
        os.unlink(log)

    def test_log_entry_has_protocol_name(self):
        log = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log)
        a.analyze(_base_params(protocol_name="CompoundV3"))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "CompoundV3")
        os.unlink(log)

    def test_log_entry_has_governance_label(self):
        log = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log)
        a.analyze(_base_params(top5_voting_power_pct=80.0))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["governance_label"], "GOVERNANCE_CARTEL")
        os.unlink(log)

    def test_log_override_via_config(self):
        log1 = _tmp_log()
        log2 = _tmp_log()
        a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=log1)
        a.analyze(_base_params(), {"log_path": log2})
        self.assertFalse(os.path.exists(log1))
        self.assertTrue(os.path.exists(log2))
        os.unlink(log2)


# ---------------------------------------------------------------------------
# Tests: module-level analyze() function
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(_base_params(), {"skip_log": True})
        self.assertIsInstance(r, dict)

    def test_has_governance_label(self):
        r = analyze(_base_params(top5_voting_power_pct=80.0), {"skip_log": True})
        self.assertEqual(r["governance_label"], "GOVERNANCE_CARTEL")

    def test_delegates_to_analyzer(self):
        r = analyze(
            _base_params(top5_voting_power_pct=5.0), {"skip_log": True}
        )
        self.assertEqual(r["governance_label"], "DECENTRALIZED")


# ---------------------------------------------------------------------------
# Tests: Known-value integration scenarios
# ---------------------------------------------------------------------------

class TestKnownValueScenarios(unittest.TestCase):

    def setUp(self):
        self.a = DeFiProtocolVotingPowerConcentrationAnalyzer(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.a._log_path):
            os.unlink(self.a._log_path)

    def test_aave_like_profile(self):
        """Realistic Aave-like governance distribution."""
        r = self.a.analyze(
            {
                "protocol_name": "Aave",
                "top1_voting_power_pct": 12.0,
                "top5_voting_power_pct": 38.0,
                "top10_voting_power_pct": 55.0,
                "total_token_supply": 16_000_000.0,
                "circulating_supply": 14_500_000.0,
                "dao_treasury_pct": 15.0,
                "team_vesting_pct": 10.0,
                "quorum_threshold_pct": 40.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["governance_label"], "CONCENTRATED")
        self.assertAlmostEqual(r["effective_control_pct"], 22.0)
        self.assertGreater(r["governance_risk_score"], 25)

    def test_highly_concentrated_profile(self):
        """VC-heavy protocol with majority held by insiders."""
        r = self.a.analyze(
            {
                "protocol_name": "VCProtocol",
                "top1_voting_power_pct": 35.0,
                "top5_voting_power_pct": 65.0,
                "top10_voting_power_pct": 75.0,
                "total_token_supply": 100_000_000.0,
                "circulating_supply": 20_000_000.0,
                "dao_treasury_pct": 10.0,
                "team_vesting_pct": 25.0,
                "quorum_threshold_pct": 50.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["governance_label"], "HIGHLY_CONCENTRATED")
        self.assertGreater(r["governance_risk_score"], 40)

    def test_true_cartel_profile(self):
        r = self.a.analyze(
            {
                "protocol_name": "CartellDeFi",
                "top1_voting_power_pct": 55.0,
                "top5_voting_power_pct": 85.0,
                "top10_voting_power_pct": 92.0,
                "total_token_supply": 10_000_000.0,
                "circulating_supply": 2_000_000.0,
                "dao_treasury_pct": 5.0,
                "team_vesting_pct": 40.0,
                "quorum_threshold_pct": 10.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["governance_label"], "GOVERNANCE_CARTEL")
        self.assertEqual(r["quorum_achievability_score"], 100)
        self.assertGreater(r["governance_risk_score"], 60)

    def test_fully_decentralized_profile(self):
        r = self.a.analyze(
            {
                "protocol_name": "DecentDAO",
                "top1_voting_power_pct": 1.5,
                "top5_voting_power_pct": 6.0,
                "top10_voting_power_pct": 11.0,
                "total_token_supply": 500_000_000.0,
                "circulating_supply": 450_000_000.0,
                "dao_treasury_pct": 30.0,
                "team_vesting_pct": 2.0,
                "quorum_threshold_pct": 15.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["governance_label"], "DECENTRALIZED")
        self.assertLess(r["governance_risk_score"], 15)

    def test_hhi_known_value_equal_split(self):
        """10 equal 10% holders → HHI = 10*(10^2) = 1000."""
        r = self.a.analyze(
            _base_params(
                top1_voting_power_pct=10.0,
                top5_voting_power_pct=50.0,
                top10_voting_power_pct=100.0,
            ),
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["herfindahl_index"], 1000.0, places=2)

    def test_effective_control_35pct(self):
        r = self.a.analyze(
            _base_params(top1_voting_power_pct=20.0, team_vesting_pct=15.0),
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["effective_control_pct"], 35.0)

    def test_quorum_half_achievable(self):
        r = self.a.analyze(
            _base_params(top10_voting_power_pct=25.0, quorum_threshold_pct=50.0),
            {"skip_log": True},
        )
        self.assertEqual(r["quorum_achievability_score"], 50)


if __name__ == "__main__":
    unittest.main()
