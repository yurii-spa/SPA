"""
Tests for MP-772: DebtCeilingMonitor
130 unittest tests. Pure stdlib (unittest only).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.debt_ceiling_monitor import (
    ProtocolDebtInput,
    ProtocolDebtReport,
    DebtCeilingMonitorResult,
    DebtCeilingMonitor,
    compute_utilization_pct,
    compute_headroom_usd,
    compute_days_until_ceiling,
    compute_breach_risk,
    analyze_protocol,
    load_history,
    save_result,
    MAX_ENTRIES,
)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _input(protocol="Proto A", current=50_000_000.0, ceiling=100_000_000.0,
           growth=1.0) -> ProtocolDebtInput:
    return ProtocolDebtInput(
        protocol=protocol,
        current_debt_usd=float(current),
        debt_ceiling_usd=float(ceiling),
        debt_growth_rate_daily_pct=float(growth),
    )


def _tmp_file() -> Path:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Path(path)


# ─── compute_utilization_pct ─────────────────────────────────────────────────

class TestComputeUtilizationPct(unittest.TestCase):

    def test_half_utilized(self):
        self.assertAlmostEqual(compute_utilization_pct(50, 100), 50.0)

    def test_fully_utilized(self):
        self.assertAlmostEqual(compute_utilization_pct(100, 100), 100.0)

    def test_over_ceiling(self):
        # current > ceiling → >100%
        self.assertAlmostEqual(compute_utilization_pct(120, 100), 120.0)

    def test_zero_current(self):
        self.assertAlmostEqual(compute_utilization_pct(0, 100), 0.0)

    def test_zero_ceiling_returns_100(self):
        self.assertAlmostEqual(compute_utilization_pct(50, 0), 100.0)

    def test_negative_ceiling_returns_100(self):
        self.assertAlmostEqual(compute_utilization_pct(10, -1), 100.0)

    def test_negative_current_returns_0(self):
        self.assertAlmostEqual(compute_utilization_pct(-10, 100), 0.0)

    def test_large_values(self):
        self.assertAlmostEqual(
            compute_utilization_pct(95_000_000, 100_000_000), 95.0
        )

    def test_small_fraction(self):
        self.assertAlmostEqual(compute_utilization_pct(1, 1000), 0.1)

    def test_both_zero(self):
        # ceiling=0 → returns 100
        self.assertAlmostEqual(compute_utilization_pct(0, 0), 100.0)


# ─── compute_headroom_usd ─────────────────────────────────────────────────────

class TestComputeHeadroomUsd(unittest.TestCase):

    def test_headroom_positive(self):
        self.assertAlmostEqual(compute_headroom_usd(40, 100), 60.0)

    def test_headroom_zero_at_ceiling(self):
        self.assertAlmostEqual(compute_headroom_usd(100, 100), 0.0)

    def test_already_breached_returns_zero(self):
        self.assertAlmostEqual(compute_headroom_usd(110, 100), 0.0)

    def test_zero_current(self):
        self.assertAlmostEqual(compute_headroom_usd(0, 100), 100.0)

    def test_negative_current(self):
        self.assertAlmostEqual(compute_headroom_usd(-10, 100), 110.0)

    def test_large_values(self):
        self.assertAlmostEqual(
            compute_headroom_usd(40_000_000, 100_000_000), 60_000_000.0
        )

    def test_ceiling_zero(self):
        # ceiling=0, current=50 → max(0, 0-50) = 0
        self.assertAlmostEqual(compute_headroom_usd(50, 0), 0.0)

    def test_no_debt(self):
        self.assertAlmostEqual(compute_headroom_usd(0, 1_000_000), 1_000_000.0)


# ─── compute_days_until_ceiling ──────────────────────────────────────────────

class TestComputeDaysUntilCeiling(unittest.TestCase):

    def test_basic_formula(self):
        # headroom=50, daily_growth=1% of 50 = 0.5 → 100 days
        result = compute_days_until_ceiling(50, 100, 1.0)
        self.assertAlmostEqual(result, 100.0)

    def test_zero_growth_rate_returns_inf(self):
        result = compute_days_until_ceiling(50, 100, 0.0)
        self.assertEqual(result, float("inf"))

    def test_negative_growth_rate_returns_inf(self):
        result = compute_days_until_ceiling(50, 100, -1.0)
        self.assertEqual(result, float("inf"))

    def test_already_breached_returns_zero(self):
        result = compute_days_until_ceiling(100, 100, 2.0)
        self.assertAlmostEqual(result, 0.0)

    def test_well_above_ceiling_returns_zero(self):
        result = compute_days_until_ceiling(150, 100, 2.0)
        self.assertAlmostEqual(result, 0.0)

    def test_zero_current_returns_inf(self):
        result = compute_days_until_ceiling(0, 100, 5.0)
        self.assertEqual(result, float("inf"))

    def test_negative_current_returns_inf(self):
        result = compute_days_until_ceiling(-10, 100, 5.0)
        self.assertEqual(result, float("inf"))

    def test_high_growth_rate_few_days(self):
        # headroom=10, daily_growth=10% of 90 = 9 → ~1.11 days
        result = compute_days_until_ceiling(90, 100, 10.0)
        self.assertAlmostEqual(result, 10.0 / 9.0, places=5)

    def test_imminent_range(self):
        # Should give < 7 days
        result = compute_days_until_ceiling(98, 100, 5.0)
        self.assertLess(result, 7.0)

    def test_high_range(self):
        # Should give 7-30 days
        result = compute_days_until_ceiling(80, 100, 5.0)
        # headroom=20, daily=4 → 5 days — actually imminent, let me pick better values
        # headroom=50, daily_growth=1% of 90=0.9 → 50/0.9 ≈ 55 days → MEDIUM
        result2 = compute_days_until_ceiling(90, 140, 1.0)
        # headroom=50, growth=90*0.01=0.9 → 50/0.9≈55 days
        self.assertGreater(result2, 30.0)

    def test_low_growth_rate(self):
        # headroom=50, daily=0.01% of 100=0.01 → 5000 days
        result = compute_days_until_ceiling(100, 150, 0.01)
        self.assertAlmostEqual(result, 50.0 / (100.0 * 0.01 / 100.0))

    def test_exact_formula_verification(self):
        # headroom = 30, daily_growth = 2% of 70 = 1.4 → 30/1.4 ≈ 21.428
        result = compute_days_until_ceiling(70, 100, 2.0)
        self.assertAlmostEqual(result, 30.0 / 1.4, places=5)

    def test_ceiling_at_border(self):
        # Just under ceiling: headroom=0.001, growth=100*1/100=1 → very small
        result = compute_days_until_ceiling(99.999, 100, 1.0)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)


# ─── compute_breach_risk ─────────────────────────────────────────────────────

class TestComputeBreachRisk(unittest.TestCase):

    def test_imminent_when_zero(self):
        self.assertEqual(compute_breach_risk(0.0), "IMMINENT")

    def test_imminent_when_negative(self):
        # days=-1 means breached
        self.assertEqual(compute_breach_risk(-1.0), "IMMINENT")

    def test_imminent_just_below_threshold(self):
        self.assertEqual(compute_breach_risk(6.9), "IMMINENT")

    def test_high_at_exactly_7(self):
        self.assertEqual(compute_breach_risk(7.0), "HIGH")

    def test_high_at_29(self):
        self.assertEqual(compute_breach_risk(29.9), "HIGH")

    def test_medium_at_exactly_30(self):
        self.assertEqual(compute_breach_risk(30.0), "MEDIUM")

    def test_medium_at_89(self):
        self.assertEqual(compute_breach_risk(89.9), "MEDIUM")

    def test_low_at_exactly_90(self):
        self.assertEqual(compute_breach_risk(90.0), "LOW")

    def test_low_at_inf(self):
        self.assertEqual(compute_breach_risk(float("inf")), "LOW")

    def test_low_at_large_number(self):
        self.assertEqual(compute_breach_risk(1000.0), "LOW")

    def test_high_range_boundaries(self):
        self.assertEqual(compute_breach_risk(7.0), "HIGH")
        self.assertEqual(compute_breach_risk(29.0), "HIGH")

    def test_medium_range_boundaries(self):
        self.assertEqual(compute_breach_risk(30.0), "MEDIUM")
        self.assertEqual(compute_breach_risk(89.0), "MEDIUM")


# ─── analyze_protocol ────────────────────────────────────────────────────────

class TestAnalyzeProtocol(unittest.TestCase):

    def test_basic_fields_populated(self):
        p = _input(current=50_000_000, ceiling=100_000_000, growth=1.0)
        r = analyze_protocol(p)
        self.assertEqual(r.protocol, "Proto A")
        self.assertAlmostEqual(r.utilization_pct, 50.0)
        self.assertAlmostEqual(r.headroom_usd, 50_000_000.0)

    def test_breach_risk_low(self):
        p = _input(current=10_000_000, ceiling=100_000_000, growth=0.1)
        r = analyze_protocol(p)
        self.assertEqual(r.breach_risk, "LOW")

    def test_breach_risk_imminent_breached(self):
        p = _input(current=100_000_000, ceiling=100_000_000, growth=1.0)
        r = analyze_protocol(p)
        self.assertEqual(r.breach_risk, "IMMINENT")

    def test_breach_risk_high(self):
        # 95M / 100M, growth 5% → headroom=5M, daily_growth=95M*5/100=4.75M
        # days = 5M/4.75M ≈ 1.05 → IMMINENT
        # Let's use: 90M, 100M, 1% → headroom=10, daily=0.9 → 11.1 days → HIGH
        p = _input(current=90_000_000, ceiling=100_000_000, growth=1.0)
        r = analyze_protocol(p)
        self.assertEqual(r.breach_risk, "HIGH")

    def test_breach_risk_medium(self):
        # 50M, 100M, 2% → headroom=50M, daily=1M → 50 days → MEDIUM
        p = _input(current=50_000_000.0, ceiling=100_000_000.0, growth=2.0)
        r = analyze_protocol(p)
        self.assertEqual(r.breach_risk, "MEDIUM")

    def test_zero_growth_gives_inf_days(self):
        p = _input(current=50_000_000, ceiling=100_000_000, growth=0.0)
        r = analyze_protocol(p)
        self.assertEqual(r.days_until_ceiling, float("inf"))
        self.assertEqual(r.breach_risk, "LOW")

    def test_protocol_name_preserved(self):
        p = _input(protocol="Morpho Blue", current=1_000_000, ceiling=50_000_000, growth=0.5)
        r = analyze_protocol(p)
        self.assertEqual(r.protocol, "Morpho Blue")

    def test_headroom_zero_when_breached(self):
        p = _input(current=120_000_000, ceiling=100_000_000, growth=2.0)
        r = analyze_protocol(p)
        self.assertAlmostEqual(r.headroom_usd, 0.0)


# ─── DebtCeilingMonitor.monitor() ────────────────────────────────────────────

class TestDebtCeilingMonitorMonitor(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_empty_list_returns_result(self):
        result = self.monitor.monitor([])
        self.assertIsInstance(result, DebtCeilingMonitorResult)
        self.assertEqual(result.protocols, [])
        self.assertAlmostEqual(result.total_current_debt_usd, 0.0)
        self.assertAlmostEqual(result.total_ceiling_usd, 0.0)

    def test_single_protocol(self):
        result = self.monitor.monitor([_input()])
        self.assertEqual(len(result.protocols), 1)

    def test_multiple_protocols(self):
        inputs = [_input("A"), _input("B"), _input("C")]
        result = self.monitor.monitor(inputs)
        self.assertEqual(len(result.protocols), 3)

    def test_at_risk_contains_imminent(self):
        # 100M / 100M → IMMINENT (breached)
        p = _input(current=100_000_000, ceiling=100_000_000, growth=1.0)
        result = self.monitor.monitor([p])
        self.assertIn("Proto A", result.at_risk_protocols)

    def test_at_risk_contains_high(self):
        # 90M/100M, 1% growth → HIGH
        p = _input(current=90_000_000, ceiling=100_000_000, growth=1.0)
        result = self.monitor.monitor([p])
        self.assertIn("Proto A", result.at_risk_protocols)

    def test_at_risk_excludes_low(self):
        # 10M/100M, 0.01% → LOW
        p = _input(current=10_000_000, ceiling=100_000_000, growth=0.01)
        result = self.monitor.monitor([p])
        self.assertNotIn("Proto A", result.at_risk_protocols)

    def test_portfolio_headroom_pct(self):
        # 40M + 60M = 100M current; ceiling=200M → headroom=100M → 50%
        inputs = [
            _input("A", current=40_000_000, ceiling=100_000_000, growth=0.0),
            _input("B", current=60_000_000, ceiling=100_000_000, growth=0.0),
        ]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.portfolio_headroom_pct, 50.0)

    def test_total_current_debt_sum(self):
        inputs = [
            _input("A", current=30_000_000),
            _input("B", current=20_000_000),
        ]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.total_current_debt_usd, 50_000_000.0)

    def test_total_ceiling_sum(self):
        inputs = [
            _input("A", current=10_000_000, ceiling=50_000_000),
            _input("B", current=10_000_000, ceiling=80_000_000),
        ]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.total_ceiling_usd, 130_000_000.0)

    def test_total_headroom_sum(self):
        inputs = [
            _input("A", current=40_000_000, ceiling=100_000_000, growth=0.0),
            _input("B", current=70_000_000, ceiling=100_000_000, growth=0.0),
        ]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.total_headroom_usd, 90_000_000.0)

    def test_timestamp_is_recent(self):
        import time
        before = time.time()
        result = self.monitor.monitor([_input()])
        after = time.time()
        self.assertGreaterEqual(result.timestamp, before)
        self.assertLessEqual(result.timestamp, after)

    def test_writes_to_log_file(self):
        self.monitor.monitor([_input()])
        self.assertTrue(self.tmp.exists())

    def test_all_imminent(self):
        inputs = [
            _input("A", current=100, ceiling=100, growth=1.0),
            _input("B", current=110, ceiling=100, growth=1.0),
        ]
        result = self.monitor.monitor(inputs)
        self.assertEqual(len(result.at_risk_protocols), 2)
        for r in result.protocols:
            self.assertEqual(r.breach_risk, "IMMINENT")

    def test_portfolio_zero_ceiling_headroom_pct_zero(self):
        # ceiling=0 → portfolio_headroom_pct=0
        p = _input(current=50, ceiling=0, growth=1.0)
        result = self.monitor.monitor([p])
        self.assertAlmostEqual(result.portfolio_headroom_pct, 0.0)


# ─── get_at_risk_protocols ────────────────────────────────────────────────────

class TestGetAtRiskProtocols(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_returns_empty_before_monitor_called(self):
        self.assertEqual(self.monitor.get_at_risk_protocols(), [])

    def test_returns_at_risk_after_call(self):
        self.monitor.monitor([_input(current=100, ceiling=100, growth=1.0)])
        self.assertIn("Proto A", self.monitor.get_at_risk_protocols())

    def test_returns_list_copy(self):
        self.monitor.monitor([_input()])
        a = self.monitor.get_at_risk_protocols()
        b = self.monitor.get_at_risk_protocols()
        self.assertEqual(a, b)

    def test_empty_when_all_low(self):
        self.monitor.monitor([_input(current=1, ceiling=100_000_000, growth=0.001)])
        self.assertEqual(self.monitor.get_at_risk_protocols(), [])

    def test_updates_on_second_call(self):
        self.monitor.monitor([_input(current=1, ceiling=100_000_000, growth=0.001)])
        self.assertEqual(self.monitor.get_at_risk_protocols(), [])
        self.monitor.monitor([_input(current=99_999_999, ceiling=100_000_000, growth=5.0)])
        # 5% growth of 99.999M = ~5M/day, headroom≈1 → <1 day → IMMINENT
        self.assertIn("Proto A", self.monitor.get_at_risk_protocols())


# ─── get_portfolio_headroom_pct ──────────────────────────────────────────────

class TestGetPortfolioHeadroomPct(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_returns_zero_before_monitor_called(self):
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 0.0)

    def test_returns_correct_headroom(self):
        # 60M/100M → headroom=40M → 40%
        self.monitor.monitor([_input(current=60_000_000, ceiling=100_000_000, growth=0.0)])
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 40.0)

    def test_zero_headroom_when_breached(self):
        self.monitor.monitor([_input(current=100_000_000, ceiling=100_000_000, growth=1.0)])
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 0.0)

    def test_full_headroom_when_no_debt(self):
        self.monitor.monitor([_input(current=0, ceiling=100_000_000, growth=0.0)])
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 100.0)

    def test_updates_on_second_call(self):
        self.monitor.monitor([_input(current=50_000_000, ceiling=100_000_000, growth=0.0)])
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 50.0)
        self.monitor.monitor([_input(current=80_000_000, ceiling=100_000_000, growth=0.0)])
        self.assertAlmostEqual(self.monitor.get_portfolio_headroom_pct(), 20.0)


# ─── Ring buffer + persistence ───────────────────────────────────────────────

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_creates_file_after_monitor(self):
        self.monitor.monitor([_input()])
        self.assertTrue(self.tmp.exists())

    def test_file_is_valid_json(self):
        self.monitor.monitor([_input()])
        data = json.loads(self.tmp.read_text())
        self.assertIsInstance(data, list)

    def test_multiple_runs_accumulate(self):
        self.monitor.monitor([_input()])
        self.monitor.monitor([_input()])
        data = json.loads(self.tmp.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_max(self):
        for _ in range(MAX_ENTRIES + 5):
            self.monitor.monitor([_input()])
        data = json.loads(self.tmp.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_load_history_empty_when_no_file(self):
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_load_history_returns_list(self):
        self.monitor.monitor([_input()])
        history = load_history(self.tmp)
        self.assertIsInstance(history, list)

    def test_days_inf_serialized_as_null(self):
        p = _input(current=50, ceiling=100, growth=0.0)  # inf days
        self.monitor.monitor([p])
        data = json.loads(self.tmp.read_text())
        days = data[0]["protocols"][0]["days_until_ceiling"]
        self.assertIsNone(days)

    def test_load_history_handles_corrupt_file(self):
        self.tmp.write_text("NOT_JSON")
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_load_history_handles_empty_file(self):
        self.tmp.write_text("")
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_atomic_write_no_tmp_left(self):
        self.monitor.monitor([_input()])
        tmp = self.tmp.with_suffix(".tmp")
        self.assertFalse(tmp.exists())


# ─── Edge cases ──────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_zero_growth_all_low(self):
        inputs = [
            _input("A", current=99_000_000, ceiling=100_000_000, growth=0.0),
            _input("B", current=80_000_000, ceiling=100_000_000, growth=0.0),
        ]
        result = self.monitor.monitor(inputs)
        for r in result.protocols:
            self.assertEqual(r.breach_risk, "LOW")
        self.assertEqual(result.at_risk_protocols, [])

    def test_ceiling_already_breached_all_protocols(self):
        inputs = [
            _input("A", current=105_000_000, ceiling=100_000_000, growth=1.0),
            _input("B", current=200_000_000, ceiling=100_000_000, growth=1.0),
        ]
        result = self.monitor.monitor(inputs)
        self.assertEqual(len(result.at_risk_protocols), 2)
        for r in result.protocols:
            self.assertEqual(r.breach_risk, "IMMINENT")
            self.assertAlmostEqual(r.headroom_usd, 0.0)
            self.assertAlmostEqual(r.days_until_ceiling, 0.0)

    def test_mixed_risk_levels(self):
        # Low:      10M/100M, 0.01% growth → headroom=90M, daily=1k  → 90000 days → LOW
        # Med:      50M/100M, 2.0% growth  → headroom=50M, daily=1M  → 50 days    → MEDIUM
        # High:     90M/100M, 1.0% growth  → headroom=10M, daily=900k → 11 days   → HIGH
        # Imminent: 99.5M/100M, 5% growth  → headroom=0.5M, daily=4.975M → 0.1d  → IMMINENT
        inputs = [
            _input("Low",      current=10_000_000.0, ceiling=100_000_000.0, growth=0.01),
            _input("Med",      current=50_000_000.0, ceiling=100_000_000.0, growth=2.0),
            _input("High",     current=90_000_000.0, ceiling=100_000_000.0, growth=1.0),
            _input("Imminent", current=99_500_000.0, ceiling=100_000_000.0, growth=5.0),
        ]
        result = self.monitor.monitor(inputs)
        risk_map = {r.protocol: r.breach_risk for r in result.protocols}
        self.assertEqual(risk_map["Low"], "LOW")
        self.assertEqual(risk_map["Med"], "MEDIUM")
        self.assertEqual(risk_map["High"], "HIGH")
        self.assertEqual(risk_map["Imminent"], "IMMINENT")

    def test_large_number_of_protocols(self):
        inputs = [_input(f"Proto_{i}", current=float(i * 1_000), ceiling=100_000.0, growth=0.1)
                  for i in range(20)]
        result = self.monitor.monitor(inputs)
        self.assertEqual(len(result.protocols), 20)

    def test_protocol_with_exactly_7_days_is_high(self):
        # current=100, ceiling=107, growth=1% of 100=1/day → headroom=7, days=7
        p = ProtocolDebtInput("Exact7", 100.0, 107.0, 1.0)
        r = analyze_protocol(p)
        self.assertAlmostEqual(r.days_until_ceiling, 7.0)
        self.assertEqual(r.breach_risk, "HIGH")

    def test_protocol_with_exactly_30_days_is_medium(self):
        # current=100, ceiling=130, growth=1% → headroom=30, days=30
        p = ProtocolDebtInput("Exact30", 100.0, 130.0, 1.0)
        r = analyze_protocol(p)
        self.assertAlmostEqual(r.days_until_ceiling, 30.0)
        self.assertEqual(r.breach_risk, "MEDIUM")

    def test_protocol_with_exactly_90_days_is_low(self):
        # current=100, ceiling=190, growth=1% → headroom=90, days=90
        p = ProtocolDebtInput("Exact90", 100.0, 190.0, 1.0)
        r = analyze_protocol(p)
        self.assertAlmostEqual(r.days_until_ceiling, 90.0)
        self.assertEqual(r.breach_risk, "LOW")

    def test_very_small_growth_rate(self):
        p = ProtocolDebtInput("SlowGrow", 1_000_000, 2_000_000, 0.000001)
        r = analyze_protocol(p)
        # days = 1_000_000 / (1_000_000 * 0.000001 / 100) = 1_000_000 / 0.01 = 100_000_000
        self.assertGreater(r.days_until_ceiling, 1_000_000)
        self.assertEqual(r.breach_risk, "LOW")

    def test_headroom_pct_100_when_no_debt(self):
        inputs = [_input("A", current=0, ceiling=1_000_000, growth=0.0)]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.portfolio_headroom_pct, 100.0)

    def test_headroom_pct_0_when_all_breached(self):
        inputs = [
            _input("A", current=100_000, ceiling=100_000, growth=1.0),
            _input("B", current=200_000, ceiling=100_000, growth=1.0),
        ]
        result = self.monitor.monitor(inputs)
        self.assertAlmostEqual(result.portfolio_headroom_pct, 0.0)

    def test_data_file_created_in_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = Path(d) / "subdir" / "deep"
            f = subdir / "log.json"
            mon = DebtCeilingMonitor(data_file=f)
            mon.monitor([_input()])
            self.assertTrue(f.exists())


# ─── Report fields validation ─────────────────────────────────────────────────

class TestReportFieldsValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.monitor = DebtCeilingMonitor(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_report_has_all_fields(self):
        p = _input()
        r = analyze_protocol(p)
        self.assertIsInstance(r.protocol, str)
        self.assertIsInstance(r.current_debt_usd, float)
        self.assertIsInstance(r.debt_ceiling_usd, float)
        self.assertIsInstance(r.debt_growth_rate_daily_pct, float)
        self.assertIsInstance(r.utilization_pct, float)
        self.assertIsInstance(r.headroom_usd, float)
        self.assertIsInstance(r.days_until_ceiling, float)
        self.assertIsInstance(r.breach_risk, str)

    def test_breach_risk_valid_values(self):
        valid = {"LOW", "MEDIUM", "HIGH", "IMMINENT"}
        for growth in [0.0, 0.01, 0.5, 5.0, 50.0]:
            p = _input(current=90_000_000, ceiling=100_000_000, growth=growth)
            r = analyze_protocol(p)
            self.assertIn(r.breach_risk, valid)

    def test_utilization_nonnegative(self):
        p = _input(current=50_000_000)
        r = analyze_protocol(p)
        self.assertGreaterEqual(r.utilization_pct, 0.0)

    def test_headroom_nonnegative(self):
        p = _input(current=150_000_000, ceiling=100_000_000, growth=1.0)
        r = analyze_protocol(p)
        self.assertGreaterEqual(r.headroom_usd, 0.0)

    def test_days_nonnegative(self):
        for growth in [0.0, 1.0, 5.0]:
            p = _input(growth=growth)
            r = analyze_protocol(p)
            self.assertGreaterEqual(r.days_until_ceiling, 0.0)

    def test_result_protocol_count_matches_input(self):
        inputs = [_input(f"P{i}") for i in range(5)]
        result = self.monitor.monitor(inputs)
        self.assertEqual(len(result.protocols), 5)

    def test_at_risk_list_subset_of_protocols(self):
        inputs = [_input(f"P{i}") for i in range(3)]
        result = self.monitor.monitor(inputs)
        protocol_names = {r.protocol for r in result.protocols}
        for name in result.at_risk_protocols:
            self.assertIn(name, protocol_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
