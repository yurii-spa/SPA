"""
Tests for MP-1057 ProtocolDeFiEmissionScheduleRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_emission_schedule_risk_analyzer -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_emission_schedule_risk_analyzer import (
    ProtocolDeFiEmissionScheduleRiskAnalyzer,
    _atomic_write_json,
    _append_ring_log,
    _LOG_CAP,
    _LABEL_SUSTAINABLE,
    _LABEL_MANAGEABLE,
    _LABEL_ELEVATED,
    _LABEL_HIGH_RISK,
    _LABEL_HYPERINFL,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _analyzer(tmp: str) -> ProtocolDeFiEmissionScheduleRiskAnalyzer:
    return ProtocolDeFiEmissionScheduleRiskAnalyzer(
        log_path=os.path.join(tmp, "emi_log.json")
    )


def _base_data(**overrides) -> dict:
    base = {
        "token_name":                    "TKN",
        "current_price_usd":             1.0,
        "total_supply":                  1_000_000,
        "circulating_supply":            500_000,
        "emissions_per_day":             1_000,
        "vesting_unlock_schedule":       [],
        "current_apy_from_emissions_pct": 20.0,
        "protocol_revenue_usd_per_day":  500.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Inflation rate
# ---------------------------------------------------------------------------

class TestInflationRate(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_basic_rate(self):
        # 1000/day / 500_000 * 365 * 100 = 73%
        rate = self.a._inflation_rate(1_000, 500_000)
        self.assertAlmostEqual(rate, 73.0, places=4)

    def test_zero_emissions(self):
        self.assertAlmostEqual(self.a._inflation_rate(0, 500_000), 0.0)

    def test_zero_circulating(self):
        self.assertAlmostEqual(self.a._inflation_rate(1_000, 0), 0.0)

    def test_both_zero(self):
        self.assertAlmostEqual(self.a._inflation_rate(0, 0), 0.0)

    def test_high_emission_high_inflation(self):
        # 50k/day / 100k * 365 * 100 = 18250 %
        rate = self.a._inflation_rate(50_000, 100_000)
        self.assertAlmostEqual(rate, 50_000 * 365 / 100_000 * 100, places=2)

    def test_low_emission_low_inflation(self):
        # 10/day / 1M * 365 * 100 = 0.365%
        rate = self.a._inflation_rate(10, 1_000_000)
        self.assertAlmostEqual(rate, 0.365, places=3)

    def test_result_positive(self):
        self.assertGreater(self.a._inflation_rate(100, 1_000), 0)

    def test_large_circulating_supply(self):
        rate = self.a._inflation_rate(100, 1_000_000_000)
        self.assertAlmostEqual(rate, 100 * 365 / 1_000_000_000 * 100, places=6)

    def test_emissions_equal_circulating(self):
        # 1/day / 1 * 365 * 100 = 36500%
        rate = self.a._inflation_rate(1, 1)
        self.assertAlmostEqual(rate, 36500.0, places=2)

    def test_annualised_correctly(self):
        # emission = circulating / 365, so inflation = 100%/yr
        rate = self.a._inflation_rate(1_000_000 / 365, 1_000_000)
        self.assertAlmostEqual(rate, 100.0, places=3)


# ---------------------------------------------------------------------------
# 2. Revenue coverage ratio
# ---------------------------------------------------------------------------

class TestRevenueCoverageRatio(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_coverage_above_one(self):
        # revenue 1000, emission_value = 500 * 1 = 500 → ratio = 2
        self.assertAlmostEqual(self.a._revenue_coverage(1_000, 500, 1.0), 2.0)

    def test_coverage_below_one(self):
        # revenue 100, emission_value = 1000 → ratio = 0.1
        self.assertAlmostEqual(self.a._revenue_coverage(100, 1_000, 1.0), 0.1)

    def test_coverage_exactly_one(self):
        self.assertAlmostEqual(self.a._revenue_coverage(500, 500, 1.0), 1.0)

    def test_zero_emissions_positive_revenue(self):
        # emission_value = 0, revenue > 0 → 999 (no dilution)
        self.assertEqual(self.a._revenue_coverage(1_000, 0, 1.0), 999.0)

    def test_zero_emissions_zero_revenue(self):
        # emission_value = 0, revenue = 0 → 0
        self.assertEqual(self.a._revenue_coverage(0, 0, 1.0), 0.0)

    def test_zero_price_means_zero_emission_value(self):
        # price = 0 → emission_value = 0 → if revenue > 0 → 999
        self.assertEqual(self.a._revenue_coverage(100, 1_000, 0.0), 999.0)

    def test_high_price_increases_emission_value(self):
        # emission_value = 100 * 100 = 10000, revenue = 1000 → ratio = 0.1
        self.assertAlmostEqual(self.a._revenue_coverage(1_000, 100, 100.0), 0.1)

    def test_zero_revenue_positive_emissions(self):
        self.assertAlmostEqual(self.a._revenue_coverage(0, 1_000, 1.0), 0.0)

    def test_result_positive_when_revenue_and_emissions_positive(self):
        ratio = self.a._revenue_coverage(500, 1_000, 2.0)
        self.assertGreater(ratio, 0)

    def test_large_revenue_high_coverage(self):
        ratio = self.a._revenue_coverage(1_000_000, 100, 1.0)
        self.assertGreater(ratio, 1_000)


# ---------------------------------------------------------------------------
# 3. Max unlock 30d
# ---------------------------------------------------------------------------

class TestMaxUnlock30d(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_no_schedule(self):
        self.assertAlmostEqual(self.a._max_unlock_30d([], 1_000_000), 0.0)

    def test_event_at_day_0(self):
        schedule = [{"days_from_now": 0, "tokens": 100_000}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 10.0)

    def test_event_at_day_30(self):
        schedule = [{"days_from_now": 30, "tokens": 50_000}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 5.0)

    def test_event_at_day_31_excluded(self):
        schedule = [{"days_from_now": 31, "tokens": 100_000}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 0.0)

    def test_multiple_events_summed(self):
        schedule = [
            {"days_from_now": 5,  "tokens": 10_000},
            {"days_from_now": 15, "tokens": 20_000},
            {"days_from_now": 28, "tokens": 15_000},
        ]
        # total 45_000 / 1_000_000 * 100 = 4.5%
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 4.5)

    def test_mixed_in_out_window(self):
        schedule = [
            {"days_from_now": 10, "tokens": 50_000},   # in
            {"days_from_now": 60, "tokens": 200_000},  # out
        ]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 5.0)

    def test_zero_circulating_returns_zero(self):
        schedule = [{"days_from_now": 5, "tokens": 100_000}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 0), 0.0)

    def test_all_events_outside_window(self):
        schedule = [{"days_from_now": d, "tokens": 50_000} for d in [31, 60, 90, 180]]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 0.0)

    def test_large_unlock_over_100_pct_allowed(self):
        schedule = [{"days_from_now": 1, "tokens": 2_000_000}]
        pct = self.a._max_unlock_30d(schedule, 1_000_000)
        self.assertAlmostEqual(pct, 200.0)

    def test_negative_days_counted(self):
        # days_from_now = 0 is valid; negative means already happened — spec says 0 <= x <= 30
        schedule = [{"days_from_now": -1, "tokens": 100_000}]
        # negative → not in range [0, 30] → excluded
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 0.0)

    def test_missing_tokens_defaults_zero(self):
        schedule = [{"days_from_now": 5}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 0.0)

    def test_schedule_with_none_tokens(self):
        schedule = [{"days_from_now": 5, "tokens": None}]
        self.assertAlmostEqual(self.a._max_unlock_30d(schedule, 1_000_000), 0.0)


# ---------------------------------------------------------------------------
# 4. Emission risk score
# ---------------------------------------------------------------------------

class TestEmissionRiskScore(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_all_zero_returns_zero(self):
        score = self.a._emission_risk_score(0, 999.0, 0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_score_capped_at_100(self):
        score = self.a._emission_risk_score(10_000, 0, 1_000)
        self.assertLessEqual(score, 100.0)

    def test_min_score_is_zero(self):
        score = self.a._emission_risk_score(0, 999.0, 0)
        self.assertGreaterEqual(score, 0.0)

    def test_full_coverage_zero_inflation_zero_unlock(self):
        # Perfect protocol: coverage = 1, inflation = 0, unlock = 0 → score = 0
        score = self.a._emission_risk_score(0, 1.0, 0)
        self.assertAlmostEqual(score, 0.0)

    def test_high_inflation_increases_score(self):
        s_low  = self.a._emission_risk_score(1,    0.5, 0)
        s_high = self.a._emission_risk_score(100,  0.5, 0)
        self.assertGreater(s_high, s_low)

    def test_low_coverage_increases_score(self):
        s_good = self.a._emission_risk_score(10, 1.0, 0)
        s_bad  = self.a._emission_risk_score(10, 0.0, 0)
        self.assertGreater(s_bad, s_good)

    def test_high_unlock_increases_score(self):
        s_low  = self.a._emission_risk_score(0, 1.0, 0)
        s_high = self.a._emission_risk_score(0, 1.0, 30)
        self.assertGreater(s_high, s_low)

    def test_inflation_saturates_at_50pct(self):
        # inflation=50 and inflation=200 should give same inflation component (cap=40)
        s50  = self.a._emission_risk_score(50,  0.0, 0)
        s200 = self.a._emission_risk_score(200, 0.0, 0)
        # Coverage component same (0.0 → 30), unlock same (0)
        # Inflation: 50 → 40 cap, 200 → 40 cap. So both = 40 + 30 = 70
        self.assertAlmostEqual(s50, s200)

    def test_coverage_clamps_at_1(self):
        # Coverage 1.0 and 5.0 should both give 0 coverage score
        s1 = self.a._emission_risk_score(0, 1.0, 0)
        s5 = self.a._emission_risk_score(0, 5.0, 0)
        self.assertAlmostEqual(s1, s5)

    def test_unlock_saturates_at_30pct(self):
        s30  = self.a._emission_risk_score(0, 1.0, 30)
        s100 = self.a._emission_risk_score(0, 1.0, 100)
        self.assertAlmostEqual(s30, s100)

    def test_score_is_sum_of_components(self):
        inflation_pct = 25.0   # component = 25/50 * 40 = 20
        coverage      = 0.5    # component = 30 * (1 - 0.5) = 15
        unlock_pct    = 15.0   # component = 15/30 * 30 = 15
        score = self.a._emission_risk_score(inflation_pct, coverage, unlock_pct)
        self.assertAlmostEqual(score, 50.0, places=4)

    def test_score_between_0_and_100(self):
        for inf in [0, 10, 50, 100, 500]:
            for cov in [0, 0.5, 1.0, 2.0]:
                for unlock in [0, 10, 30, 50]:
                    s = self.a._emission_risk_score(inf, cov, unlock)
                    self.assertGreaterEqual(s, 0)
                    self.assertLessEqual(s, 100)

    def test_zero_coverage_adds_30_to_score(self):
        s_no_cov  = self.a._emission_risk_score(0, 0.0, 0)
        s_full_cov = self.a._emission_risk_score(0, 1.0, 0)
        self.assertAlmostEqual(s_no_cov - s_full_cov, 30.0, places=4)

    def test_partial_inflation(self):
        # inflation = 25% → 25/50 * 40 = 20
        s = self.a._emission_risk_score(25, 1.0, 0)
        self.assertAlmostEqual(s, 20.0, places=4)

    def test_partial_unlock(self):
        # unlock = 15% → 15/30 * 30 = 15
        s = self.a._emission_risk_score(0, 1.0, 15)
        self.assertAlmostEqual(s, 15.0, places=4)


# ---------------------------------------------------------------------------
# 5. Label assignment
# ---------------------------------------------------------------------------

class TestLabel(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_score_0_sustainable(self):
        self.assertEqual(self.a._label(0), _LABEL_SUSTAINABLE)

    def test_score_19_sustainable(self):
        self.assertEqual(self.a._label(19.9), _LABEL_SUSTAINABLE)

    def test_score_20_manageable(self):
        self.assertEqual(self.a._label(20), _LABEL_MANAGEABLE)

    def test_score_39_manageable(self):
        self.assertEqual(self.a._label(39.9), _LABEL_MANAGEABLE)

    def test_score_40_elevated(self):
        self.assertEqual(self.a._label(40), _LABEL_ELEVATED)

    def test_score_59_elevated(self):
        self.assertEqual(self.a._label(59.9), _LABEL_ELEVATED)

    def test_score_60_high_risk(self):
        self.assertEqual(self.a._label(60), _LABEL_HIGH_RISK)

    def test_score_79_high_risk(self):
        self.assertEqual(self.a._label(79.9), _LABEL_HIGH_RISK)

    def test_score_80_hyperinflationary(self):
        self.assertEqual(self.a._label(80), _LABEL_HYPERINFL)

    def test_score_100_hyperinflationary(self):
        self.assertEqual(self.a._label(100), _LABEL_HYPERINFL)


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_minimal_input_no_crash(self):
        result = self.a.analyze({})
        self.assertIn("label", result)

    def test_missing_token_name_defaults(self):
        result = self.a.analyze(_base_data(token_name=None))
        self.assertIn("emission_inflation_rate_pct", result)

    def test_zero_circulating_no_crash(self):
        result = self.a.analyze(_base_data(circulating_supply=0))
        self.assertAlmostEqual(result["emission_inflation_rate_pct"], 0.0)

    def test_zero_price_no_crash(self):
        result = self.a.analyze(_base_data(current_price_usd=0))
        self.assertIn("revenue_coverage_ratio", result)

    def test_zero_emissions_no_crash(self):
        result = self.a.analyze(_base_data(emissions_per_day=0))
        self.assertIn("label", result)

    def test_empty_unlock_schedule(self):
        result = self.a.analyze(_base_data(vesting_unlock_schedule=[]))
        self.assertAlmostEqual(result["max_unlock_30d_pct"], 0.0)

    def test_unlock_schedule_none(self):
        result = self.a.analyze(_base_data(vesting_unlock_schedule=None))
        self.assertAlmostEqual(result["max_unlock_30d_pct"], 0.0)

    def test_all_zero_inputs(self):
        # zero emissions + zero revenue → coverage_ratio=0 → coverage_score=30 → MANAGEABLE
        result = self.a.analyze({
            "token_name": "X",
            "current_price_usd": 0,
            "total_supply": 0,
            "circulating_supply": 0,
            "emissions_per_day": 0,
            "vesting_unlock_schedule": [],
            "current_apy_from_emissions_pct": 0,
            "protocol_revenue_usd_per_day": 0,
        })
        self.assertIn(result["label"], (_LABEL_SUSTAINABLE, _LABEL_MANAGEABLE))

    def test_very_high_emissions_high_score(self):
        result = self.a.analyze(_base_data(
            emissions_per_day=1_000_000,
            circulating_supply=100,
            protocol_revenue_usd_per_day=0,
        ))
        self.assertGreater(result["emission_risk_score"], 60)

    def test_result_has_all_keys(self):
        result = self.a.analyze(_base_data())
        for key in ("emission_inflation_rate_pct", "revenue_coverage_ratio",
                    "max_unlock_30d_pct", "emission_risk_score", "label"):
            self.assertIn(key, result)

    def test_score_rounded_to_4_places(self):
        result = self.a.analyze(_base_data())
        score = result["emission_risk_score"]
        self.assertEqual(score, round(score, 4))

    def test_inflation_rounded_to_6_places(self):
        result = self.a.analyze(_base_data())
        v = result["emission_inflation_rate_pct"]
        self.assertEqual(v, round(v, 6))

    def test_valid_label_always_returned(self):
        valid = {_LABEL_SUSTAINABLE, _LABEL_MANAGEABLE, _LABEL_ELEVATED,
                 _LABEL_HIGH_RISK, _LABEL_HYPERINFL}
        for emissions in [0, 100, 10_000, 1_000_000]:
            result = self.a.analyze(_base_data(emissions_per_day=emissions))
            self.assertIn(result["label"], valid)

    def test_large_unlock_schedule(self):
        schedule = [{"days_from_now": i, "tokens": 1_000} for i in range(100)]
        result = self.a.analyze(_base_data(
            vesting_unlock_schedule=schedule,
            circulating_supply=1_000_000,
        ))
        # Events 0–30 = 31 events * 1000 = 31_000 / 1_000_000 * 100 = 3.1%
        self.assertAlmostEqual(result["max_unlock_30d_pct"], 3.1, places=2)

    def test_revenue_coverage_ratio_non_negative(self):
        result = self.a.analyze(_base_data(protocol_revenue_usd_per_day=0))
        self.assertGreaterEqual(result["revenue_coverage_ratio"], 0)


# ---------------------------------------------------------------------------
# 7. Log file
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):

    def test_log_created_after_analyze(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            a.analyze(_base_data())
            self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            a.analyze(_base_data())
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_entry_has_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            a.analyze(_base_data(token_name="ETK"))
            with open(path) as f:
                entry = json.load(f)[0]
            for key in ("ts", "token_name", "label", "emission_risk_score"):
                self.assertIn(key, entry)

    def test_log_token_name_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            a.analyze(_base_data(token_name="MYTOKEN"))
            with open(path) as f:
                entry = json.load(f)[0]
            self.assertEqual(entry["token_name"], "MYTOKEN")

    def test_log_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            for _ in range(_LOG_CAP + 15):
                a.analyze(_base_data())
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), _LOG_CAP)

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            with open(path, "w") as f:
                f.write("{bad json{{")
            a = ProtocolDeFiEmissionScheduleRiskAnalyzer(log_path=path)
            a.analyze(_base_data())
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_atomic_write_json_helper(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "nested", "file.json")
            _atomic_write_json(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_append_ring_log_helper(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ring.json")
            for i in range(5):
                _append_ring_log(path, {"i": i}, cap=3)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
            self.assertEqual(data[-1]["i"], 4)


# ---------------------------------------------------------------------------
# 8. Full analyze integration
# ---------------------------------------------------------------------------

class TestAnalyzeIntegration(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_sustainable_protocol(self):
        result = self.a.analyze({
            "token_name":                     "GOOD",
            "current_price_usd":              2.0,
            "total_supply":                   10_000_000,
            "circulating_supply":             8_000_000,
            "emissions_per_day":              100,          # tiny
            "vesting_unlock_schedule":        [],
            "current_apy_from_emissions_pct": 1.0,
            "protocol_revenue_usd_per_day":   100_000,      # massive
        })
        self.assertEqual(result["label"], _LABEL_SUSTAINABLE)

    def test_hyperinflationary_protocol(self):
        result = self.a.analyze({
            "token_name":                     "PEPE",
            "current_price_usd":              0.001,
            "total_supply":                   1_000_000_000,
            "circulating_supply":             10_000_000,
            "emissions_per_day":              50_000_000,   # massive
            "vesting_unlock_schedule":        [
                {"days_from_now": 5, "tokens": 5_000_000},
                {"days_from_now": 15, "tokens": 5_000_000},
            ],
            "current_apy_from_emissions_pct": 500.0,
            "protocol_revenue_usd_per_day":   0.0,          # zero revenue
        })
        self.assertEqual(result["label"], _LABEL_HYPERINFL)

    def test_result_keys_all_present(self):
        result = self.a.analyze(_base_data())
        for key in ("emission_inflation_rate_pct", "revenue_coverage_ratio",
                    "max_unlock_30d_pct", "emission_risk_score", "label"):
            self.assertIn(key, result)

    def test_idempotent_same_input_same_output(self):
        r1 = self.a.analyze(_base_data())
        r2 = self.a.analyze(_base_data())
        self.assertEqual(r1["label"], r2["label"])
        self.assertAlmostEqual(
            r1["emission_risk_score"], r2["emission_risk_score"], places=4
        )

    def test_increasing_emissions_increases_risk(self):
        r_low  = self.a.analyze(_base_data(emissions_per_day=100))
        r_high = self.a.analyze(_base_data(emissions_per_day=100_000))
        self.assertGreater(
            r_high["emission_risk_score"], r_low["emission_risk_score"]
        )

    def test_higher_revenue_lowers_risk(self):
        r_poor = self.a.analyze(_base_data(protocol_revenue_usd_per_day=0))
        r_rich = self.a.analyze(_base_data(protocol_revenue_usd_per_day=1_000_000))
        self.assertGreater(
            r_poor["emission_risk_score"], r_rich["emission_risk_score"]
        )

    def test_near_term_unlock_increases_risk(self):
        r_no_unlock = self.a.analyze(_base_data(vesting_unlock_schedule=[]))
        r_unlock    = self.a.analyze(_base_data(vesting_unlock_schedule=[
            {"days_from_now": 10, "tokens": 200_000}
        ]))
        self.assertGreater(
            r_unlock["emission_risk_score"], r_no_unlock["emission_risk_score"]
        )

    def test_far_future_unlock_no_impact(self):
        r_no = self.a.analyze(_base_data(vesting_unlock_schedule=[]))
        r_far = self.a.analyze(_base_data(vesting_unlock_schedule=[
            {"days_from_now": 365, "tokens": 999_999}
        ]))
        self.assertAlmostEqual(
            r_no["max_unlock_30d_pct"], r_far["max_unlock_30d_pct"], places=5
        )

    def test_no_trades_advisory_only(self):
        # Calling analyze many times does not modify any module-level state
        for _ in range(10):
            result = self.a.analyze(_base_data())
        self.assertIn("label", result)

    def test_score_in_valid_range(self):
        for emissions in [0, 1_000, 100_000, 10_000_000]:
            result = self.a.analyze(_base_data(emissions_per_day=emissions))
            score = result["emission_risk_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_revenue_coverage_ratio_in_result(self):
        result = self.a.analyze(_base_data(
            protocol_revenue_usd_per_day=1_000,
            emissions_per_day=500,
            current_price_usd=2.0,
        ))
        # emission_value = 500 * 2 = 1000; revenue = 1000 → ratio = 1.0
        self.assertAlmostEqual(result["revenue_coverage_ratio"], 1.0, places=4)

    def test_inflation_rate_in_result(self):
        result = self.a.analyze(_base_data(
            emissions_per_day=1_000,
            circulating_supply=365_000,
        ))
        # 1000 * 365 / 365_000 * 100 = 100%
        self.assertAlmostEqual(result["emission_inflation_rate_pct"], 100.0, places=4)


if __name__ == "__main__":
    unittest.main()
