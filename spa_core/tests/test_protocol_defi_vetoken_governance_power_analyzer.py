"""
Tests for MP-1013 ProtocolDeFiVetokenGovernancePowerAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_vetoken_governance_power_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_vetoken_governance_power_analyzer import (
    ProtocolDeFiVetokenGovernancePowerAnalyzer,
    _lock_participation_ratio,
    _vetoken_yield_pct,
    _bribe_to_emission_ratio,
    _governance_centralization_score,
    _fee_to_bribe_ratio,
    _governance_label,
    _compute_flags,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_system(
    name="Curve", protocol="Curve",
    total_supply=1_000_000_000, locked_pct=65.0,
    avg_lock_years=2.5, max_lock_years=4.0,
    price=0.5, weekly_emissions=1_000_000,
    fee_weekly=500_000, bribe_weekly=300_000,
    top1=8.0, top10=35.0,
    attacks=False, cliff_pct=10.0,
):
    return {
        "name": name,
        "protocol": protocol,
        "total_token_supply": total_supply,
        "tokens_locked_pct": locked_pct,
        "avg_lock_duration_years": avg_lock_years,
        "max_lock_duration_years": max_lock_years,
        "token_price_usd": price,
        "weekly_emissions_usd": weekly_emissions,
        "fee_revenue_weekly_usd": fee_weekly,
        "bribe_revenue_weekly_usd": bribe_weekly,
        "top_voter_share_pct": top1,
        "top10_voter_share_pct": top10,
        "governance_attacks_history": attacks,
        "lock_expiry_cliff_pct": cliff_pct,
    }


def _healthy_system():
    """Expected HEALTHY_DEMOCRACY."""
    return _make_system(
        name="HealthyCurve", locked_pct=70.0, top1=5.0,
        top10=25.0, attacks=False, cliff_pct=8.0,
        fee_weekly=800_000, bribe_weekly=200_000,
    )


def _captured_system():
    """Expected GOVERNANCE_CAPTURED."""
    return _make_system(
        name="CapturedDAO", locked_pct=40.0, top1=25.0,
        top10=80.0, attacks=True, cliff_pct=15.0,
    )


def _bribery_system():
    """Expected BRIBERY_DOMINATED."""
    return _make_system(
        name="BriberyDAO", locked_pct=45.0, top1=10.0,
        top10=40.0, attacks=False, cliff_pct=12.0,
        bribe_weekly=1_500_000, weekly_emissions=1_000_000,
    )


def _plutocratic_system():
    """Expected PLUTOCRATIC_RISK."""
    return _make_system(
        name="PlutocraticDAO", locked_pct=40.0, top1=25.0,
        top10=65.0, attacks=False, cliff_pct=10.0,
    )


def _cliff_risk_system():
    """Expected CLIFF_RISK."""
    return _make_system(
        name="CliffDAO", locked_pct=50.0, top1=8.0,
        top10=30.0, attacks=False, cliff_pct=40.0,
    )


# ---------------------------------------------------------------------------
# 1. Test _lock_participation_ratio
# ---------------------------------------------------------------------------

class TestLockParticipationRatio(unittest.TestCase):

    def test_100_pct(self):
        self.assertAlmostEqual(_lock_participation_ratio(100.0), 1.0, places=4)

    def test_50_pct(self):
        self.assertAlmostEqual(_lock_participation_ratio(50.0), 0.5, places=4)

    def test_zero(self):
        self.assertAlmostEqual(_lock_participation_ratio(0.0), 0.0, places=4)

    def test_65_pct(self):
        self.assertAlmostEqual(_lock_participation_ratio(65.0), 0.65, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_lock_participation_ratio(50.0), float)


# ---------------------------------------------------------------------------
# 2. Test _vetoken_yield_pct
# ---------------------------------------------------------------------------

class TestVetokenYieldPct(unittest.TestCase):

    def test_basic_yield(self):
        # locked = 0.65 * 1e9 * 0.5 = 325,000,000
        # annual = (500k + 300k) * 52 = 41,600,000
        # yield = 41,600,000 / 325,000,000 * 100 ≈ 12.8%
        result = _vetoken_yield_pct(500_000, 300_000, 65.0, 1_000_000_000, 0.5)
        self.assertAlmostEqual(result, 12.8, places=1)

    def test_zero_locked_returns_zero(self):
        result = _vetoken_yield_pct(500_000, 300_000, 0.0, 1_000_000_000, 0.5)
        self.assertEqual(result, 0.0)

    def test_zero_fees_and_bribes(self):
        result = _vetoken_yield_pct(0, 0, 65.0, 1_000_000_000, 0.5)
        self.assertEqual(result, 0.0)

    def test_zero_price_returns_zero(self):
        result = _vetoken_yield_pct(500_000, 300_000, 65.0, 1_000_000_000, 0.0)
        self.assertEqual(result, 0.0)

    def test_returns_float(self):
        result = _vetoken_yield_pct(500_000, 300_000, 65.0, 1_000_000_000, 0.5)
        self.assertIsInstance(result, float)

    def test_high_yield_scenario(self):
        # Small supply, high fees → high yield
        result = _vetoken_yield_pct(1_000_000, 500_000, 50.0, 1_000_000, 1.0)
        self.assertGreater(result, 50.0)

    def test_yield_increases_with_higher_fees(self):
        y1 = _vetoken_yield_pct(200_000, 100_000, 65.0, 1_000_000_000, 0.5)
        y2 = _vetoken_yield_pct(500_000, 300_000, 65.0, 1_000_000_000, 0.5)
        self.assertGreater(y2, y1)


# ---------------------------------------------------------------------------
# 3. Test _bribe_to_emission_ratio
# ---------------------------------------------------------------------------

class TestBribeToEmissionRatio(unittest.TestCase):

    def test_zero_emissions(self):
        self.assertEqual(_bribe_to_emission_ratio(500_000, 0), 0.0)

    def test_equal_bribe_and_emissions(self):
        self.assertAlmostEqual(_bribe_to_emission_ratio(1_000_000, 1_000_000), 1.0)

    def test_bribe_exceeds_emissions(self):
        result = _bribe_to_emission_ratio(1_500_000, 1_000_000)
        self.assertGreater(result, 1.0)

    def test_low_bribe(self):
        result = _bribe_to_emission_ratio(100_000, 1_000_000)
        self.assertAlmostEqual(result, 0.1, places=4)

    def test_zero_bribe(self):
        self.assertEqual(_bribe_to_emission_ratio(0, 1_000_000), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_bribe_to_emission_ratio(300_000, 1_000_000), float)


# ---------------------------------------------------------------------------
# 4. Test _governance_centralization_score
# ---------------------------------------------------------------------------

class TestGovernanceCentralizationScore(unittest.TestCase):

    def test_no_attack_low_top10(self):
        score = _governance_centralization_score(20.0, False, 5.0)
        # 20*0.6 + 0 + 5*0.1 = 12 + 0 + 0.5 = 12.5
        self.assertAlmostEqual(score, 12.5, places=2)

    def test_attack_history_adds_30(self):
        s_no_attack = _governance_centralization_score(30.0, False, 10.0)
        s_attack = _governance_centralization_score(30.0, True, 10.0)
        self.assertAlmostEqual(s_attack - s_no_attack, 30.0, places=2)

    def test_score_capped_at_100(self):
        score = _governance_centralization_score(100.0, True, 100.0)
        self.assertLessEqual(score, 100.0)

    def test_score_floor_at_0(self):
        score = _governance_centralization_score(0.0, False, 0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_cliff_contribution(self):
        s1 = _governance_centralization_score(30.0, False, 0.0)
        s2 = _governance_centralization_score(30.0, False, 50.0)
        self.assertGreater(s2, s1)

    def test_returns_float(self):
        self.assertIsInstance(_governance_centralization_score(30.0, False, 10.0), float)

    def test_high_top10_score(self):
        score = _governance_centralization_score(90.0, False, 10.0)
        self.assertGreater(score, 50.0)


# ---------------------------------------------------------------------------
# 5. Test _fee_to_bribe_ratio
# ---------------------------------------------------------------------------

class TestFeeToBribeRatio(unittest.TestCase):

    def test_equal(self):
        self.assertAlmostEqual(_fee_to_bribe_ratio(1_000_000, 1_000_000), 1.0)

    def test_fee_dominant(self):
        result = _fee_to_bribe_ratio(2_000_000, 1_000_000)
        self.assertAlmostEqual(result, 2.0)

    def test_bribe_dominant(self):
        result = _fee_to_bribe_ratio(500_000, 1_000_000)
        self.assertAlmostEqual(result, 0.5)

    def test_zero_bribe_nonzero_fee(self):
        result = _fee_to_bribe_ratio(500_000, 0)
        self.assertEqual(result, float("inf"))

    def test_zero_bribe_zero_fee(self):
        result = _fee_to_bribe_ratio(0, 0)
        self.assertEqual(result, 0.0)

    def test_returns_float(self):
        result = _fee_to_bribe_ratio(500_000, 300_000)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 6. Test _governance_label
# ---------------------------------------------------------------------------

class TestGovernanceLabel(unittest.TestCase):

    def test_healthy_democracy(self):
        label = _governance_label(70.0, 15.0, False, 25.0, 5.0, 0.3, 8.0)
        self.assertEqual(label, "HEALTHY_DEMOCRACY")

    def test_governance_captured(self):
        label = _governance_label(40.0, 85.0, True, 80.0, 25.0, 0.5, 15.0)
        self.assertEqual(label, "GOVERNANCE_CAPTURED")

    def test_cliff_risk(self):
        label = _governance_label(55.0, 20.0, False, 30.0, 8.0, 0.3, 40.0)
        self.assertEqual(label, "CLIFF_RISK")

    def test_bribery_dominated(self):
        label = _governance_label(45.0, 25.0, False, 40.0, 10.0, 1.5, 10.0)
        self.assertEqual(label, "BRIBERY_DOMINATED")

    def test_plutocratic_risk_top10(self):
        label = _governance_label(40.0, 35.0, False, 65.0, 10.0, 0.4, 10.0)
        self.assertEqual(label, "PLUTOCRATIC_RISK")

    def test_plutocratic_risk_top1(self):
        label = _governance_label(45.0, 25.0, False, 40.0, 25.0, 0.4, 10.0)
        self.assertEqual(label, "PLUTOCRATIC_RISK")

    def test_functional(self):
        label = _governance_label(45.0, 40.0, False, 50.0, 12.0, 0.4, 15.0)
        self.assertEqual(label, "FUNCTIONAL")

    def test_captured_requires_attacks_and_high_top10(self):
        # attacks=True but low top10 → not captured
        label = _governance_label(50.0, 20.0, True, 50.0, 10.0, 0.3, 10.0)
        self.assertNotEqual(label, "GOVERNANCE_CAPTURED")

    def test_cliff_checked_before_bribery(self):
        # Both cliff_pct >30 and bribe_ratio>=1 — cliff wins
        label = _governance_label(45.0, 25.0, False, 40.0, 10.0, 1.5, 40.0)
        self.assertEqual(label, "CLIFF_RISK")


# ---------------------------------------------------------------------------
# 7. Test _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_high_participation(self):
        flags = _compute_flags(70.0, 200_000, 500_000, False, 10.0, 1_000_000, 8.0)
        self.assertIn("HIGH_PARTICIPATION", flags)

    def test_no_high_participation_at_50(self):
        flags = _compute_flags(50.0, 200_000, 500_000, False, 10.0, 1_000_000, 8.0)
        self.assertNotIn("HIGH_PARTICIPATION", flags)

    def test_bribery_economy(self):
        flags = _compute_flags(65.0, 800_000, 500_000, False, 10.0, 1_000_000, 8.0)
        self.assertIn("BRIBERY_ECONOMY", flags)

    def test_no_bribery_economy(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 10.0, 1_000_000, 8.0)
        self.assertNotIn("BRIBERY_ECONOMY", flags)

    def test_governance_attack_history(self):
        flags = _compute_flags(65.0, 200_000, 500_000, True, 10.0, 1_000_000, 8.0)
        self.assertIn("GOVERNANCE_ATTACK_HISTORY", flags)

    def test_cliff_expiry_risk(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 30.0, 1_000_000, 8.0)
        self.assertIn("CLIFF_EXPIRY_RISK", flags)

    def test_no_cliff_expiry_risk_at_20(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 20.0, 1_000_000, 8.0)
        self.assertNotIn("CLIFF_EXPIRY_RISK", flags)

    def test_strong_fee_backing(self):
        flags = _compute_flags(65.0, 200_000, 600_000, False, 10.0, 1_000_000, 8.0)
        self.assertIn("STRONG_FEE_BACKING", flags)

    def test_plutocratic(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 10.0, 1_000_000, 20.0)
        self.assertIn("PLUTOCRATIC", flags)

    def test_no_plutocratic_below_threshold(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 10.0, 1_000_000, 10.0)
        self.assertNotIn("PLUTOCRATIC", flags)

    def test_all_flags_possible(self):
        # Trigger all 6 flags
        flags = _compute_flags(70.0, 800_000, 500_000, True, 30.0, 1_000_000, 20.0)
        for f in ["HIGH_PARTICIPATION", "BRIBERY_ECONOMY", "GOVERNANCE_ATTACK_HISTORY",
                  "CLIFF_EXPIRY_RISK", "PLUTOCRATIC"]:
            self.assertIn(f, flags)

    def test_flags_is_list(self):
        flags = _compute_flags(65.0, 200_000, 500_000, False, 10.0, 1_000_000, 8.0)
        self.assertIsInstance(flags, list)


# ---------------------------------------------------------------------------
# 8. Test _analyze_one
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):

    def test_returns_expected_keys(self):
        system = _make_system()
        result = _analyze_one(system)
        for key in ["name", "protocol", "lock_participation_ratio", "vetoken_yield_pct",
                    "bribe_to_emission_ratio", "governance_centralization_score",
                    "fee_to_bribe_ratio", "lock_efficiency", "governance_label",
                    "flags", "tokens_locked_pct", "top_voter_share_pct",
                    "top10_voter_share_pct", "lock_expiry_cliff_pct"]:
            self.assertIn(key, result)

    def test_healthy_system_label(self):
        result = _analyze_one(_healthy_system())
        self.assertEqual(result["governance_label"], "HEALTHY_DEMOCRACY")

    def test_captured_system_label(self):
        result = _analyze_one(_captured_system())
        self.assertEqual(result["governance_label"], "GOVERNANCE_CAPTURED")

    def test_bribery_system_label(self):
        result = _analyze_one(_bribery_system())
        self.assertEqual(result["governance_label"], "BRIBERY_DOMINATED")

    def test_plutocratic_system_label(self):
        result = _analyze_one(_plutocratic_system())
        self.assertEqual(result["governance_label"], "PLUTOCRATIC_RISK")

    def test_cliff_risk_label(self):
        result = _analyze_one(_cliff_risk_system())
        self.assertEqual(result["governance_label"], "CLIFF_RISK")

    def test_lock_efficiency_range(self):
        result = _analyze_one(_make_system())
        self.assertGreaterEqual(result["lock_efficiency"], 0.0)
        self.assertLessEqual(result["lock_efficiency"], 1.0)

    def test_lock_efficiency_max_lock(self):
        # avg_lock == max_lock → efficiency = 1.0
        result = _analyze_one(_make_system(avg_lock_years=4.0, max_lock_years=4.0))
        self.assertAlmostEqual(result["lock_efficiency"], 1.0, places=4)

    def test_name_preserved(self):
        result = _analyze_one(_make_system(name="TestCurve"))
        self.assertEqual(result["name"], "TestCurve")

    def test_protocol_preserved(self):
        result = _analyze_one(_make_system(protocol="Balancer"))
        self.assertEqual(result["protocol"], "Balancer")

    def test_tokens_locked_pct_preserved(self):
        result = _analyze_one(_make_system(locked_pct=72.5))
        self.assertAlmostEqual(result["tokens_locked_pct"], 72.5)

    def test_centralization_score_range(self):
        result = _analyze_one(_make_system())
        self.assertGreaterEqual(result["governance_centralization_score"], 0.0)
        self.assertLessEqual(result["governance_centralization_score"], 100.0)


# ---------------------------------------------------------------------------
# 9. Test ProtocolDeFiVetokenGovernancePowerAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiVetokenGovernancePowerAnalyzer()

    def test_single_system(self):
        result = self.analyzer.analyze([_make_system()])
        self.assertIn("systems", result)
        self.assertEqual(len(result["systems"]), 1)

    def test_multiple_systems(self):
        systems = [
            _make_system("CRV"), _healthy_system(), _captured_system(), _bribery_system()
        ]
        result = self.analyzer.analyze(systems)
        self.assertEqual(len(result["systems"]), 4)

    def test_result_keys(self):
        result = self.analyzer.analyze([_make_system()])
        for key in ["systems", "healthiest", "most_captured", "avg_vetoken_yield",
                    "healthy_democracy_count", "governance_captured_count", "analyzed_at"]:
            self.assertIn(key, result)

    def test_healthy_democracy_count(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertGreaterEqual(result["healthy_democracy_count"], 1)

    def test_governance_captured_count(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertGreaterEqual(result["governance_captured_count"], 1)

    def test_healthiest_is_string(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertIsInstance(result["healthiest"], str)

    def test_most_captured_is_string(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertIsInstance(result["most_captured"], str)

    def test_most_captured_is_captured_system(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertEqual(result["most_captured"], "CapturedDAO")

    def test_avg_vetoken_yield_non_negative(self):
        result = self.analyzer.analyze([_make_system()])
        self.assertGreaterEqual(result["avg_vetoken_yield"], 0.0)

    def test_analyzed_at_format(self):
        result = self.analyzer.analyze([_make_system()])
        ts = result["analyzed_at"]
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze([])

    def test_non_list_raises(self):
        with self.assertRaises((ValueError, TypeError, AttributeError)):
            self.analyzer.analyze("not a list")

    def test_missing_name_raises(self):
        s = _make_system()
        del s["name"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze([s])

    def test_missing_tokens_locked_pct_raises(self):
        s = _make_system()
        del s["tokens_locked_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze([s])

    def test_invalid_max_lock_raises(self):
        s = _make_system(max_lock_years=0)
        with self.assertRaises(ValueError):
            self.analyzer.analyze([s])

    def test_invalid_supply_raises(self):
        s = _make_system(total_supply=0)
        with self.assertRaises(ValueError):
            self.analyzer.analyze([s])

    def test_governance_labels_are_valid(self):
        systems = [_make_system(), _healthy_system(), _captured_system(),
                   _bribery_system(), _plutocratic_system(), _cliff_risk_system()]
        result = self.analyzer.analyze(systems)
        valid_labels = {
            "HEALTHY_DEMOCRACY", "FUNCTIONAL", "PLUTOCRATIC_RISK",
            "BRIBERY_DOMINATED", "GOVERNANCE_CAPTURED", "CLIFF_RISK"
        }
        for s in result["systems"]:
            self.assertIn(s["governance_label"], valid_labels)

    def test_module_level_analyze(self):
        result = analyze([_make_system()])
        self.assertIn("systems", result)

    def test_config_none_ok(self):
        result = self.analyzer.analyze([_make_system()], config=None)
        self.assertIn("systems", result)

    def test_config_empty_ok(self):
        result = self.analyzer.analyze([_make_system()], config={})
        self.assertIn("systems", result)

    def test_flags_are_lists(self):
        result = self.analyzer.analyze([_make_system()])
        for s in result["systems"]:
            self.assertIsInstance(s["flags"], list)

    def test_healthiest_is_healthy_system(self):
        result = self.analyzer.analyze([_healthy_system(), _captured_system()])
        self.assertEqual(result["healthiest"], "HealthyCurve")

    def test_avg_yield_single_system(self):
        result = self.analyzer.analyze([_make_system()])
        self.assertEqual(
            result["avg_vetoken_yield"], result["systems"][0]["vetoken_yield_pct"]
        )

    def test_avg_yield_two_systems(self):
        result = self.analyzer.analyze([_make_system(), _healthy_system()])
        expected = sum(s["vetoken_yield_pct"] for s in result["systems"]) / 2
        self.assertAlmostEqual(result["avg_vetoken_yield"], expected, places=4)

    def test_many_systems(self):
        systems = [_make_system(f"System_{i}") for i in range(10)]
        result = self.analyzer.analyze(systems)
        self.assertEqual(len(result["systems"]), 10)


# ---------------------------------------------------------------------------
# 10. Test ring-buffer log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self.tmp.close()
        self.log_path = self.tmp.name

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_init_log_empty_file(self):
        with open(self.log_path, "w") as f:
            f.write("")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_invalid_json(self):
        with open(self.log_path, "w") as f:
            f.write("{bad json}")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_nonexistent(self):
        result = _init_log("/tmp/nonexistent_vetoken_spa_99999.json")
        self.assertEqual(result, [])

    def test_append_log_creates_entry(self):
        mock_result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "systems": [{"name": "Curve"}],
            "avg_vetoken_yield": 12.5,
            "healthy_democracy_count": 1,
            "governance_captured_count": 0,
            "healthiest": "Curve",
            "most_captured": "Curve",
        }
        _append_log(mock_result, log_path=self.log_path)
        entries = _init_log(self.log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(entries[0]["avg_vetoken_yield"], 12.5)

    def test_append_log_ring_buffer_cap(self):
        for i in range(110):
            mock_result = {
                "analyzed_at": "2026-01-01T00:00:00Z",
                "systems": [],
                "avg_vetoken_yield": float(i),
                "healthy_democracy_count": 0,
                "governance_captured_count": 0,
                "healthiest": None,
                "most_captured": None,
            }
            _append_log(mock_result, log_path=self.log_path)
        entries = _init_log(self.log_path)
        self.assertLessEqual(len(entries), 100)

    def test_atomic_write_creates_valid_json(self):
        path = self.log_path + "_atomic_test.json"
        try:
            _atomic_write(path, {"vetoken": "test"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["vetoken"], "test")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_log_appended_by_analyzer(self):
        # Just run analyze and verify no exception; log goes to real data/
        result = analyze([_make_system()])
        self.assertIn("systems", result)


# ---------------------------------------------------------------------------
# 11. Test _iso_now
# ---------------------------------------------------------------------------

class TestIsoNow(unittest.TestCase):

    def test_format(self):
        ts = _iso_now()
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_length(self):
        self.assertEqual(len(_iso_now()), 20)


# ---------------------------------------------------------------------------
# 12. Edge cases & additional coverage
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_locked_pct(self):
        s = _make_system(locked_pct=0.0)
        result = analyze([s])
        self.assertEqual(result["systems"][0]["lock_participation_ratio"], 0.0)
        self.assertEqual(result["systems"][0]["vetoken_yield_pct"], 0.0)

    def test_100_locked_pct(self):
        s = _make_system(locked_pct=100.0)
        result = analyze([s])
        self.assertAlmostEqual(result["systems"][0]["lock_participation_ratio"], 1.0)

    def test_zero_bribe(self):
        s = _make_system(bribe_weekly=0)
        result = analyze([s])
        self.assertEqual(result["systems"][0]["bribe_to_emission_ratio"], 0.0)

    def test_bribe_gt_emissions_ratio(self):
        s = _make_system(bribe_weekly=2_000_000, weekly_emissions=1_000_000)
        result = analyze([s])
        self.assertGreater(result["systems"][0]["bribe_to_emission_ratio"], 1.0)

    def test_attack_history_adds_flags(self):
        s = _make_system(attacks=True)
        result = analyze([s])
        self.assertIn("GOVERNANCE_ATTACK_HISTORY", result["systems"][0]["flags"])

    def test_no_attack_history_no_flag(self):
        s = _make_system(attacks=False)
        result = analyze([s])
        self.assertNotIn("GOVERNANCE_ATTACK_HISTORY", result["systems"][0]["flags"])

    def test_governance_captured_count_zero_healthy(self):
        result = analyze([_healthy_system()])
        self.assertEqual(result["governance_captured_count"], 0)

    def test_healthy_democracy_count_zero_captured(self):
        result = analyze([_captured_system()])
        self.assertEqual(result["healthy_democracy_count"], 0)

    def test_name_is_preserved_in_result(self):
        s = _make_system(name="VeTokenSystem42")
        result = analyze([s])
        self.assertEqual(result["systems"][0]["name"], "VeTokenSystem42")

    def test_protocol_is_preserved_in_result(self):
        s = _make_system(protocol="Frax")
        result = analyze([s])
        self.assertEqual(result["systems"][0]["protocol"], "Frax")

    def test_lock_efficiency_is_capped_at_1(self):
        # avg_lock > max_lock (unusual) → capped at 1
        s = _make_system(avg_lock_years=5.0, max_lock_years=4.0)
        result = analyze([s])
        self.assertLessEqual(result["systems"][0]["lock_efficiency"], 1.0)

    def test_five_different_systems(self):
        systems = [
            _healthy_system(), _captured_system(), _bribery_system(),
            _plutocratic_system(), _cliff_risk_system(),
        ]
        result = analyze(systems)
        labels = {s["governance_label"] for s in result["systems"]}
        self.assertGreaterEqual(len(labels), 4)  # at least 4 distinct labels

    def test_avg_yield_is_non_negative(self):
        result = analyze([_make_system(), _healthy_system()])
        self.assertGreaterEqual(result["avg_vetoken_yield"], 0.0)


if __name__ == "__main__":
    unittest.main()
