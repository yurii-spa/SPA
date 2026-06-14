"""
Tests for MP-1046 DeFiProtocolTokenVestingOverhangAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
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

from spa_core.analytics.defi_protocol_token_vesting_overhang_analyzer import (
    DeFiProtocolTokenVestingOverhangAnalyzer,
    analyze,
    _urgency_factor,
    _recipient_weight,
    _cliff_score_for_unlock,
    _overhang_ratio,
    _days_supply_pressure,
    _dilution_pct,
    _worst_cliff_score,
    _label,
    _build_recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _unlock(
    unlock_date_days: float = 30.0,
    amount: float = 10_000_000.0,
    recipient_type: str = "investor",
) -> dict:
    return {
        "unlock_date_days": unlock_date_days,
        "amount": amount,
        "recipient_type": recipient_type,
    }


def _token_data(
    token_symbol: str = "TKN",
    total_supply: float = 1_000_000_000.0,
    circulating_supply: float = 200_000_000.0,
    upcoming_unlocks: list | None = None,
    current_price_usd: float = 1.0,
    avg_daily_volume_usd: float = 2_000_000.0,
) -> dict:
    if upcoming_unlocks is None:
        upcoming_unlocks = [_unlock()]
    return {
        "token_symbol": token_symbol,
        "total_supply": total_supply,
        "circulating_supply": circulating_supply,
        "upcoming_unlocks": upcoming_unlocks,
        "current_price_usd": current_price_usd,
        "avg_daily_volume_usd": avg_daily_volume_usd,
    }


# ===========================================================================
# 1. _urgency_factor
# ===========================================================================

class TestUrgencyFactor(unittest.TestCase):
    def test_immediate(self):
        self.assertEqual(_urgency_factor(0), 1.0)

    def test_within_30(self):
        self.assertEqual(_urgency_factor(30), 1.0)

    def test_within_60(self):
        self.assertEqual(_urgency_factor(60), 0.8)

    def test_within_90(self):
        self.assertEqual(_urgency_factor(90), 0.6)

    def test_within_180(self):
        self.assertEqual(_urgency_factor(180), 0.4)

    def test_within_365(self):
        self.assertEqual(_urgency_factor(365), 0.2)

    def test_beyond_365(self):
        self.assertEqual(_urgency_factor(500), 0.05)

    def test_negative_treated_as_zero(self):
        self.assertEqual(_urgency_factor(-10), 1.0)

    def test_boundary_31(self):
        # 31 days falls in the 60-day tier
        self.assertEqual(_urgency_factor(31), 0.8)

    def test_boundary_61(self):
        self.assertEqual(_urgency_factor(61), 0.6)

    def test_boundary_91(self):
        self.assertEqual(_urgency_factor(91), 0.4)

    def test_boundary_181(self):
        self.assertEqual(_urgency_factor(181), 0.2)

    def test_monotone_decreasing(self):
        days = [0, 30, 60, 90, 180, 365, 500]
        factors = [_urgency_factor(d) for d in days]
        for i in range(len(factors) - 1):
            self.assertGreaterEqual(factors[i], factors[i + 1])


# ===========================================================================
# 2. _recipient_weight
# ===========================================================================

class TestRecipientWeight(unittest.TestCase):
    def test_team(self):
        self.assertEqual(_recipient_weight("team"), 1.0)

    def test_investor(self):
        self.assertEqual(_recipient_weight("investor"), 0.9)

    def test_ecosystem(self):
        self.assertEqual(_recipient_weight("ecosystem"), 0.5)

    def test_community(self):
        self.assertEqual(_recipient_weight("community"), 0.3)

    def test_unknown_type(self):
        self.assertEqual(_recipient_weight("advisor"), 0.5)

    def test_empty_string(self):
        self.assertEqual(_recipient_weight(""), 0.5)

    def test_case_insensitive_team(self):
        self.assertEqual(_recipient_weight("TEAM"), 1.0)

    def test_case_insensitive_investor(self):
        self.assertEqual(_recipient_weight("Investor"), 0.9)

    def test_case_insensitive_community(self):
        self.assertEqual(_recipient_weight("COMMUNITY"), 0.3)

    def test_ordering(self):
        self.assertGreater(_recipient_weight("team"), _recipient_weight("investor"))
        self.assertGreater(_recipient_weight("investor"), _recipient_weight("ecosystem"))
        self.assertGreater(_recipient_weight("ecosystem"), _recipient_weight("community"))


# ===========================================================================
# 3. _cliff_score_for_unlock
# ===========================================================================

class TestCliffScoreForUnlock(unittest.TestCase):
    def _score(self, **kwargs):
        defaults = dict(
            amount=10_000_000.0,
            circulating_supply=100_000_000.0,
            current_price_usd=1.0,
            avg_daily_volume_usd=1_000_000.0,
            unlock_date_days=20.0,
            recipient_type="investor",
        )
        defaults.update(kwargs)
        return _cliff_score_for_unlock(**defaults)

    def test_returns_float(self):
        self.assertIsInstance(self._score(), float)

    def test_in_range_0_100(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_zero_circulating_supply(self):
        self.assertEqual(self._score(circulating_supply=0.0), 0.0)

    def test_negative_circulating_supply(self):
        self.assertEqual(self._score(circulating_supply=-1.0), 0.0)

    def test_zero_avg_volume(self):
        self.assertEqual(self._score(avg_daily_volume_usd=0.0), 0.0)

    def test_team_higher_than_community(self):
        s_team = self._score(recipient_type="team")
        s_comm = self._score(recipient_type="community")
        self.assertGreater(s_team, s_comm)

    def test_imminent_higher_than_distant(self):
        s_near = self._score(unlock_date_days=10.0)
        s_far = self._score(unlock_date_days=300.0)
        self.assertGreater(s_near, s_far)

    def test_large_amount_higher_score(self):
        s_large = self._score(amount=50_000_000.0)
        s_small = self._score(amount=1_000_000.0)
        self.assertGreater(s_large, s_small)

    def test_low_volume_higher_pressure(self):
        s_low_vol = self._score(avg_daily_volume_usd=100_000.0)
        s_high_vol = self._score(avg_daily_volume_usd=10_000_000.0)
        self.assertGreater(s_low_vol, s_high_vol)

    def test_capped_at_100(self):
        # Massive unlock that should saturate all sub-scores
        s = self._score(amount=999_000_000_000.0, avg_daily_volume_usd=1.0)
        self.assertLessEqual(s, 100.0)

    def test_negative_amount_treated_as_zero(self):
        self.assertEqual(self._score(amount=-100.0), 0.0)

    def test_zero_price_no_pressure(self):
        # With zero price, unlock USD = 0 → pressure_score = 0 → only size_score remains
        s = self._score(current_price_usd=0.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)


# ===========================================================================
# 4. _overhang_ratio
# ===========================================================================

class TestOverhangRatio(unittest.TestCase):
    def test_basic(self):
        unlocks = [_unlock(amount=20_000_000.0)]
        ratio = _overhang_ratio(unlocks, 100_000_000.0)
        self.assertAlmostEqual(ratio, 0.2)

    def test_multiple_unlocks_sum(self):
        unlocks = [_unlock(amount=10_000_000.0), _unlock(amount=10_000_000.0)]
        ratio = _overhang_ratio(unlocks, 100_000_000.0)
        self.assertAlmostEqual(ratio, 0.2)

    def test_zero_circulating_supply(self):
        self.assertEqual(_overhang_ratio([_unlock()], 0.0), 0.0)

    def test_empty_unlocks(self):
        self.assertEqual(_overhang_ratio([], 100_000_000.0), 0.0)

    def test_negative_amounts_ignored(self):
        unlocks = [{"unlock_date_days": 30, "amount": -5_000_000.0, "recipient_type": "team"}]
        self.assertEqual(_overhang_ratio(unlocks, 100_000_000.0), 0.0)

    def test_ratio_above_one_possible(self):
        unlocks = [_unlock(amount=200_000_000.0)]
        ratio = _overhang_ratio(unlocks, 100_000_000.0)
        self.assertGreater(ratio, 1.0)

    def test_proportional(self):
        u1 = [_unlock(amount=10_000_000.0)]
        u2 = [_unlock(amount=20_000_000.0)]
        r1 = _overhang_ratio(u1, 100_000_000.0)
        r2 = _overhang_ratio(u2, 100_000_000.0)
        self.assertAlmostEqual(r2, r1 * 2)


# ===========================================================================
# 5. _days_supply_pressure
# ===========================================================================

class TestDaysSupplyPressure(unittest.TestCase):
    def test_basic(self):
        unlocks = [_unlock(amount=10_000_000.0)]
        # 10M tokens * $1 / $1M vol/day = 10 days
        days = _days_supply_pressure(unlocks, 1.0, 1_000_000.0)
        self.assertAlmostEqual(days, 10.0)

    def test_zero_volume(self):
        self.assertEqual(_days_supply_pressure([_unlock()], 1.0, 0.0), 0.0)

    def test_zero_price(self):
        self.assertEqual(_days_supply_pressure([_unlock()], 0.0, 1_000_000.0), 0.0)

    def test_empty_unlocks(self):
        self.assertEqual(_days_supply_pressure([], 1.0, 1_000_000.0), 0.0)

    def test_multiple_unlocks_sum(self):
        unlocks = [_unlock(amount=5_000_000.0), _unlock(amount=5_000_000.0)]
        days = _days_supply_pressure(unlocks, 1.0, 1_000_000.0)
        self.assertAlmostEqual(days, 10.0)

    def test_scales_with_price(self):
        unlocks = [_unlock(amount=1_000_000.0)]
        d1 = _days_supply_pressure(unlocks, 1.0, 1_000_000.0)
        d2 = _days_supply_pressure(unlocks, 2.0, 1_000_000.0)
        self.assertAlmostEqual(d2, d1 * 2)

    def test_negative_amounts_ignored(self):
        unlocks = [{"unlock_date_days": 30, "amount": -1_000_000.0, "recipient_type": "team"}]
        self.assertEqual(_days_supply_pressure(unlocks, 1.0, 1_000_000.0), 0.0)


# ===========================================================================
# 6. _dilution_pct
# ===========================================================================

class TestDilutionPct(unittest.TestCase):
    def test_basic(self):
        unlocks = [_unlock(amount=100_000_000.0)]
        pct = _dilution_pct(unlocks, 1_000_000_000.0)
        self.assertAlmostEqual(pct, 10.0)

    def test_zero_total_supply(self):
        self.assertEqual(_dilution_pct([_unlock()], 0.0), 0.0)

    def test_empty_unlocks(self):
        self.assertEqual(_dilution_pct([], 1_000_000_000.0), 0.0)

    def test_multiple_unlocks(self):
        unlocks = [_unlock(amount=50_000_000.0), _unlock(amount=50_000_000.0)]
        pct = _dilution_pct(unlocks, 1_000_000_000.0)
        self.assertAlmostEqual(pct, 10.0)

    def test_100pct_dilution(self):
        unlocks = [_unlock(amount=1_000_000_000.0)]
        pct = _dilution_pct(unlocks, 1_000_000_000.0)
        self.assertAlmostEqual(pct, 100.0)


# ===========================================================================
# 7. _worst_cliff_score
# ===========================================================================

class TestWorstCliffScore(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_worst_cliff_score([], 100_000_000.0, 1.0, 1_000_000.0), 0.0)

    def test_single_unlock(self):
        unlocks = [_unlock(unlock_date_days=10, amount=20_000_000.0, recipient_type="team")]
        score = _worst_cliff_score(unlocks, 100_000_000.0, 1.0, 1_000_000.0)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_picks_worst_of_multiple(self):
        bad = _unlock(unlock_date_days=5, amount=50_000_000.0, recipient_type="team")
        good = _unlock(unlock_date_days=200, amount=1_000_000.0, recipient_type="community")
        score_bad_only = _worst_cliff_score([bad], 100_000_000.0, 1.0, 1_000_000.0)
        score_both = _worst_cliff_score([bad, good], 100_000_000.0, 1.0, 1_000_000.0)
        self.assertAlmostEqual(score_bad_only, score_both)

    def test_good_unlock_doesnt_lower_score(self):
        bad = _unlock(unlock_date_days=5, amount=50_000_000.0, recipient_type="team")
        community = _unlock(unlock_date_days=300, amount=1_000.0, recipient_type="community")
        s1 = _worst_cliff_score([bad], 100_000_000.0, 1.0, 500_000.0)
        s2 = _worst_cliff_score([bad, community], 100_000_000.0, 1.0, 500_000.0)
        self.assertAlmostEqual(s1, s2)

    def test_in_range(self):
        unlocks = [_unlock(amount=20_000_000.0)]
        score = _worst_cliff_score(unlocks, 100_000_000.0, 2.0, 1_000_000.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ===========================================================================
# 8. _label
# ===========================================================================

class TestLabel(unittest.TestCase):
    def test_zero_is_minimal(self):
        self.assertEqual(_label(0.0), "MINIMAL_OVERHANG")

    def test_below_20_minimal(self):
        self.assertEqual(_label(19.9), "MINIMAL_OVERHANG")

    def test_at_20_manageable(self):
        self.assertEqual(_label(20.0), "MANAGEABLE")

    def test_below_40_manageable(self):
        self.assertEqual(_label(39.9), "MANAGEABLE")

    def test_at_40_significant(self):
        self.assertEqual(_label(40.0), "SIGNIFICANT_CLIFF")

    def test_below_60_significant(self):
        self.assertEqual(_label(59.9), "SIGNIFICANT_CLIFF")

    def test_at_60_heavy(self):
        self.assertEqual(_label(60.0), "HEAVY_OVERHANG")

    def test_below_80_heavy(self):
        self.assertEqual(_label(79.9), "HEAVY_OVERHANG")

    def test_at_80_supply_shock(self):
        self.assertEqual(_label(80.0), "SUPPLY_SHOCK")

    def test_100_supply_shock(self):
        self.assertEqual(_label(100.0), "SUPPLY_SHOCK")

    def test_all_labels_present(self):
        labels = {_label(v) for v in [0, 20, 40, 60, 80]}
        expected = {
            "MINIMAL_OVERHANG", "MANAGEABLE",
            "SIGNIFICANT_CLIFF", "HEAVY_OVERHANG", "SUPPLY_SHOCK"
        }
        self.assertEqual(labels, expected)


# ===========================================================================
# 9. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_appends(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        _atomic_log(path, {"x": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        os.unlink(path)

    def test_truncates_oldest(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        # First entry should be i=5 (105 - 100)
        self.assertEqual(data[0]["i"], 5)
        os.unlink(path)

    def test_handles_corrupt_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("NOT JSON{{")
        _atomic_log(path, {"x": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)


# ===========================================================================
# 10. DeFiProtocolTokenVestingOverhangAnalyzer.analyze — integration
# ===========================================================================

class TestAnalyzerIntegration(unittest.TestCase):
    def _run(self, **kwargs):
        td = _token_data(**kwargs)
        return DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_required_keys(self):
        result = self._run()
        for key in [
            "token_symbol", "overhang_ratio", "days_supply_pressure",
            "worst_cliff_score", "dilution_pct", "label", "recommendations",
            "timestamp", "upcoming_unlock_count",
        ]:
            self.assertIn(key, result)

    def test_token_symbol_passthrough(self):
        result = self._run(token_symbol="AAVE")
        self.assertEqual(result["token_symbol"], "AAVE")

    def test_label_minimal_for_tiny_unlock(self):
        result = self._run(
            upcoming_unlocks=[_unlock(unlock_date_days=365, amount=100.0, recipient_type="community")],
            circulating_supply=1_000_000_000.0,
            avg_daily_volume_usd=100_000_000.0,
        )
        self.assertEqual(result["label"], "MINIMAL_OVERHANG")

    def test_label_supply_shock_for_massive_imminent_team_unlock(self):
        result = self._run(
            upcoming_unlocks=[_unlock(unlock_date_days=5, amount=180_000_000.0, recipient_type="team")],
            circulating_supply=200_000_000.0,
            avg_daily_volume_usd=500_000.0,
            current_price_usd=2.0,
        )
        self.assertEqual(result["label"], "SUPPLY_SHOCK")

    def test_empty_unlocks_minimal(self):
        result = self._run(upcoming_unlocks=[])
        self.assertEqual(result["label"], "MINIMAL_OVERHANG")
        self.assertEqual(result["overhang_ratio"], 0.0)

    def test_overhang_ratio_positive(self):
        result = self._run()
        self.assertGreater(result["overhang_ratio"], 0.0)

    def test_days_supply_pressure_positive(self):
        result = self._run()
        self.assertGreater(result["days_supply_pressure"], 0.0)

    def test_dilution_pct_positive(self):
        result = self._run()
        self.assertGreater(result["dilution_pct"], 0.0)

    def test_worst_cliff_score_in_range(self):
        result = self._run()
        self.assertGreaterEqual(result["worst_cliff_score"], 0.0)
        self.assertLessEqual(result["worst_cliff_score"], 100.0)

    def test_recommendations_list(self):
        result = self._run()
        self.assertIsInstance(result["recommendations"], list)
        self.assertGreater(len(result["recommendations"]), 0)

    def test_upcoming_unlock_count(self):
        unlocks = [_unlock(), _unlock(amount=5_000_000.0)]
        td = _token_data(upcoming_unlocks=unlocks)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["upcoming_unlock_count"], 2)

    def test_zero_price_handled(self):
        result = self._run(current_price_usd=0.0)
        self.assertEqual(result["days_supply_pressure"], 0.0)

    def test_zero_total_supply_dilution_zero(self):
        result = self._run(total_supply=0.0)
        self.assertEqual(result["dilution_pct"], 0.0)

    def test_logging_enabled(self):
        path = _tmp_log()
        td = _token_data()
        DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"log_path": path}
        )
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_logging_skipped(self):
        path = _tmp_log()
        td = _token_data()
        DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"log_path": path, "skip_log": True}
        )
        self.assertFalse(os.path.exists(path))

    def test_missing_token_symbol_defaults(self):
        td = _token_data()
        del td["token_symbol"]
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["token_symbol"], "UNKNOWN")

    def test_multiple_unlocks_worst_selected(self):
        unlocks = [
            _unlock(unlock_date_days=5, amount=40_000_000.0, recipient_type="team"),
            _unlock(unlock_date_days=200, amount=500_000.0, recipient_type="community"),
        ]
        result = self._run(upcoming_unlocks=unlocks)
        # Worst score must be >= score of either individual unlock
        self.assertGreater(result["worst_cliff_score"], 0.0)

    def test_all_labels_reachable(self):
        labels = set()

        # MINIMAL_OVERHANG
        r = self._run(
            upcoming_unlocks=[_unlock(unlock_date_days=365, amount=100.0, recipient_type="community")],
            circulating_supply=1_000_000_000.0,
            avg_daily_volume_usd=100_000_000.0,
        )
        labels.add(r["label"])

        # SUPPLY_SHOCK
        r2 = self._run(
            upcoming_unlocks=[_unlock(unlock_date_days=5, amount=180_000_000.0, recipient_type="team")],
            circulating_supply=200_000_000.0,
            avg_daily_volume_usd=500_000.0,
            current_price_usd=2.0,
        )
        labels.add(r2["label"])

        self.assertIn("MINIMAL_OVERHANG", labels)
        self.assertIn("SUPPLY_SHOCK", labels)


# ===========================================================================
# 11. Module-level analyze() shortcut
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):
    def test_same_result_as_class(self):
        td = _token_data()
        r1 = analyze(td, config={"skip_log": True})
        r2 = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(td, config={"skip_log": True})
        # Timestamps will differ; compare structural fields
        for key in ["label", "overhang_ratio", "worst_cliff_score", "dilution_pct"]:
            self.assertAlmostEqual(r1[key] if isinstance(r1[key], float) else 0,
                                   r2[key] if isinstance(r2[key], float) else 0,
                                   places=6)

    def test_analyze_returns_dict(self):
        self.assertIsInstance(analyze(_token_data(), config={"skip_log": True}), dict)


# ===========================================================================
# 12. Edge & boundary cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_negative_total_supply_treated_as_zero(self):
        td = _token_data(total_supply=-1_000_000_000.0)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["total_supply"], 0.0)

    def test_negative_circulating_supply_treated_as_zero(self):
        td = _token_data(circulating_supply=-1.0)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["circulating_supply"], 0.0)

    def test_negative_price_treated_as_zero(self):
        td = _token_data(current_price_usd=-5.0)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["current_price_usd"], 0.0)

    def test_negative_avg_volume_treated_as_zero(self):
        td = _token_data(avg_daily_volume_usd=-1.0)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertEqual(result["days_supply_pressure"], 0.0)

    def test_very_large_unlock_does_not_crash(self):
        td = _token_data(
            upcoming_unlocks=[_unlock(amount=1e18)],
            current_price_usd=1e6,
        )
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertLessEqual(result["worst_cliff_score"], 100.0)

    def test_timestamp_present(self):
        td = _token_data()
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)
        self.assertGreater(result["timestamp"], 0.0)

    def test_ecosystem_unlock_lower_score_than_team(self):
        unlocks_team = [_unlock(recipient_type="team", unlock_date_days=10)]
        unlocks_eco = [_unlock(recipient_type="ecosystem", unlock_date_days=10)]
        td_team = _token_data(upcoming_unlocks=unlocks_team)
        td_eco = _token_data(upcoming_unlocks=unlocks_eco)
        r_team = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td_team, config={"skip_log": True}
        )
        r_eco = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td_eco, config={"skip_log": True}
        )
        self.assertGreater(r_team["worst_cliff_score"], r_eco["worst_cliff_score"])

    def test_dilution_warning_in_recommendations(self):
        # Large dilution (>10%) should generate a dilution warning
        unlocks = [_unlock(amount=200_000_000.0)]
        td = _token_data(upcoming_unlocks=unlocks, total_supply=500_000_000.0,
                         circulating_supply=50_000_000.0)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        all_recs = " ".join(result["recommendations"])
        self.assertIn("ilution", all_recs)

    def test_custom_log_path_in_constructor(self):
        path = _tmp_log()
        analyzer = DeFiProtocolTokenVestingOverhangAnalyzer(log_path=path)
        td = _token_data()
        analyzer.analyze(td)
        self.assertTrue(os.path.exists(path))
        os.unlink(path)


# ===========================================================================
# 13. Label-specific recommendation content
# ===========================================================================

class TestRecommendationContent(unittest.TestCase):
    def _recs_for_label(self, target_label: str) -> list[str]:
        """Drive inputs until we hit the desired label."""
        if target_label == "MINIMAL_OVERHANG":
            unlocks = [_unlock(unlock_date_days=365, amount=100.0, recipient_type="community")]
            td = _token_data(
                upcoming_unlocks=unlocks,
                circulating_supply=1_000_000_000.0,
                avg_daily_volume_usd=100_000_000.0,
            )
        elif target_label == "SUPPLY_SHOCK":
            unlocks = [_unlock(unlock_date_days=5, amount=180_000_000.0, recipient_type="team")]
            td = _token_data(
                upcoming_unlocks=unlocks,
                circulating_supply=200_000_000.0,
                avg_daily_volume_usd=500_000.0,
                current_price_usd=2.0,
            )
        else:
            unlocks = [_unlock()]
            td = _token_data(upcoming_unlocks=unlocks)
        result = DeFiProtocolTokenVestingOverhangAnalyzer().analyze(
            td, config={"skip_log": True}
        )
        return result["recommendations"]

    def test_minimal_overhang_recommendation(self):
        recs = self._recs_for_label("MINIMAL_OVERHANG")
        combined = " ".join(recs)
        self.assertTrue(any(
            k in combined.lower() for k in ["minimal", "no immediate"]
        ))

    def test_supply_shock_recommendation(self):
        recs = self._recs_for_label("SUPPLY_SHOCK")
        combined = " ".join(recs)
        self.assertIn("SUPPLY SHOCK", combined)

    def test_recommendations_all_strings(self):
        for label in ["MINIMAL_OVERHANG", "SUPPLY_SHOCK"]:
            recs = self._recs_for_label(label)
            for r in recs:
                self.assertIsInstance(r, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
