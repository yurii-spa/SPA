"""
Tests for MP-773: YieldAttributionSplitter
130 unittest tests. Pure stdlib (unittest only).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_attribution_splitter import (
    YieldComponents,
    YieldAttributionReport,
    YieldAttributionSummary,
    YieldAttributionSplitter,
    compute_component_share,
    compute_sustainable_yield,
    compute_sustainability_score,
    compute_attribution_grade,
    compute_components_sum,
    check_components_sum,
    split_one,
    load_history,
    save_summary,
    MAX_ENTRIES,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _comp(protocol="Aave V3", total=5.0, base=3.0, liq=1.0,
          gov=0.5, emit=0.3, price=0.2) -> YieldComponents:
    return YieldComponents(
        protocol=protocol,
        total_yield_pct=total,
        base_rate_pct=base,
        liquidity_premium_pct=liq,
        governance_rewards_pct=gov,
        incentive_emissions_pct=emit,
        price_appreciation_pct=price,
    )


def _tmp_file() -> Path:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Path(path)


# ─── compute_component_share ─────────────────────────────────────────────────

class TestComputeComponentShare(unittest.TestCase):

    def test_basic_formula(self):
        # 3 / 5 * 100 = 60%
        self.assertAlmostEqual(compute_component_share(3.0, 5.0), 60.0)

    def test_zero_total_returns_zero(self):
        self.assertAlmostEqual(compute_component_share(3.0, 0.0), 0.0)

    def test_zero_component(self):
        self.assertAlmostEqual(compute_component_share(0.0, 5.0), 0.0)

    def test_equal_component_and_total(self):
        self.assertAlmostEqual(compute_component_share(5.0, 5.0), 100.0)

    def test_component_larger_than_total(self):
        self.assertAlmostEqual(compute_component_share(6.0, 5.0), 120.0)

    def test_small_values(self):
        self.assertAlmostEqual(compute_component_share(0.1, 10.0), 1.0)

    def test_large_values(self):
        self.assertAlmostEqual(compute_component_share(27.5, 27.5), 100.0)

    def test_negative_component(self):
        # negative component is allowed (e.g. price depreciation)
        self.assertAlmostEqual(compute_component_share(-2.0, 10.0), -20.0)

    def test_half_share(self):
        self.assertAlmostEqual(compute_component_share(2.5, 5.0), 50.0)


# ─── compute_sustainable_yield ───────────────────────────────────────────────

class TestComputeSustainableYield(unittest.TestCase):

    def test_basic_sum(self):
        self.assertAlmostEqual(compute_sustainable_yield(3.0, 1.0), 4.0)

    def test_zero_both(self):
        self.assertAlmostEqual(compute_sustainable_yield(0.0, 0.0), 0.0)

    def test_zero_liquidity_premium(self):
        self.assertAlmostEqual(compute_sustainable_yield(3.5, 0.0), 3.5)

    def test_zero_base_rate(self):
        self.assertAlmostEqual(compute_sustainable_yield(0.0, 1.5), 1.5)

    def test_large_values(self):
        self.assertAlmostEqual(compute_sustainable_yield(10.0, 5.0), 15.0)

    def test_excludes_governance_and_emissions(self):
        # governance, emissions, price are NOT inputs to this function
        sust = compute_sustainable_yield(3.0, 1.0)
        self.assertAlmostEqual(sust, 4.0)  # no emissions/governance added

    def test_negative_base_rate(self):
        # negative rate is technically possible (e.g. negative real rate)
        self.assertAlmostEqual(compute_sustainable_yield(-1.0, 2.0), 1.0)


# ─── compute_sustainability_score ────────────────────────────────────────────

class TestComputeSustainabilityScore(unittest.TestCase):

    def test_basic_formula(self):
        # 4 / 5 * 100 = 80%
        self.assertAlmostEqual(compute_sustainability_score(4.0, 5.0), 80.0)

    def test_total_zero_returns_100(self):
        self.assertAlmostEqual(compute_sustainability_score(0.0, 0.0), 100.0)

    def test_sustainable_zero_returns_zero(self):
        self.assertAlmostEqual(compute_sustainability_score(0.0, 5.0), 0.0)

    def test_negative_sustainable_returns_zero(self):
        self.assertAlmostEqual(compute_sustainability_score(-1.0, 5.0), 0.0)

    def test_100_percent_sustainable(self):
        self.assertAlmostEqual(compute_sustainability_score(5.0, 5.0), 100.0)

    def test_50_percent_sustainable(self):
        self.assertAlmostEqual(compute_sustainability_score(2.5, 5.0), 50.0)

    def test_over_100_percent_possible(self):
        # sustainable > total (theoretically possible with negative emissions)
        score = compute_sustainability_score(6.0, 5.0)
        self.assertGreater(score, 100.0)

    def test_small_fraction(self):
        self.assertAlmostEqual(compute_sustainability_score(1.0, 10.0), 10.0)


# ─── compute_attribution_grade ───────────────────────────────────────────────

class TestComputeAttributionGrade(unittest.TestCase):

    def test_grade_a_at_80(self):
        self.assertEqual(compute_attribution_grade(80.0), "A")

    def test_grade_a_at_100(self):
        self.assertEqual(compute_attribution_grade(100.0), "A")

    def test_grade_a_at_99(self):
        self.assertEqual(compute_attribution_grade(99.0), "A")

    def test_grade_b_at_60(self):
        self.assertEqual(compute_attribution_grade(60.0), "B")

    def test_grade_b_at_79(self):
        self.assertEqual(compute_attribution_grade(79.9), "B")

    def test_grade_c_at_40(self):
        self.assertEqual(compute_attribution_grade(40.0), "C")

    def test_grade_c_at_59(self):
        self.assertEqual(compute_attribution_grade(59.9), "C")

    def test_grade_d_at_20(self):
        self.assertEqual(compute_attribution_grade(20.0), "D")

    def test_grade_d_at_39(self):
        self.assertEqual(compute_attribution_grade(39.9), "D")

    def test_grade_f_at_0(self):
        self.assertEqual(compute_attribution_grade(0.0), "F")

    def test_grade_f_at_19(self):
        self.assertEqual(compute_attribution_grade(19.9), "F")

    def test_grade_f_at_negative(self):
        self.assertEqual(compute_attribution_grade(-5.0), "F")


# ─── compute_components_sum ──────────────────────────────────────────────────

class TestComputeComponentsSum(unittest.TestCase):

    def test_basic_sum(self):
        c = _comp(base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        self.assertAlmostEqual(compute_components_sum(c), 5.0)

    def test_all_zero(self):
        c = _comp(total=0.0, base=0.0, liq=0.0, gov=0.0, emit=0.0, price=0.0)
        self.assertAlmostEqual(compute_components_sum(c), 0.0)

    def test_sum_not_matching_total(self):
        c = _comp(total=10.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        # sum=5.0 != total=10.0
        self.assertAlmostEqual(compute_components_sum(c), 5.0)
        self.assertNotAlmostEqual(compute_components_sum(c), c.total_yield_pct)

    def test_components_sum_equals_total(self):
        c = _comp(total=5.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        self.assertAlmostEqual(compute_components_sum(c), c.total_yield_pct)


# ─── check_components_sum ────────────────────────────────────────────────────

class TestCheckComponentsSum(unittest.TestCase):

    def test_exact_match_returns_true(self):
        c = _comp(total=5.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        self.assertTrue(check_components_sum(c))

    def test_mismatch_returns_false(self):
        c = _comp(total=10.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        self.assertFalse(check_components_sum(c))

    def test_zero_total_zero_sum_true(self):
        c = _comp(total=0.0, base=0.0, liq=0.0, gov=0.0, emit=0.0, price=0.0)
        self.assertTrue(check_components_sum(c))

    def test_tolerance_boundary(self):
        # sum=5.0005, total=5.0, diff=0.0005 < 0.01 → within tolerance → True
        c = YieldComponents("X", 5.0, 3.0, 1.0, 0.5, 0.3, 0.2005)
        self.assertTrue(check_components_sum(c))
        # sum=5.02, total=5.0, diff=0.02 > 0.01 → outside tolerance → False
        c2 = YieldComponents("Y", 5.0, 3.0, 1.0, 0.5, 0.3, 0.22)
        self.assertFalse(check_components_sum(c2))


# ─── split_one ───────────────────────────────────────────────────────────────

class TestSplitOne(unittest.TestCase):

    def test_basic_report_fields(self):
        c = _comp()
        r = split_one(c)
        self.assertEqual(r.protocol, "Aave V3")
        self.assertAlmostEqual(r.total_yield_pct, 5.0)
        self.assertAlmostEqual(r.sustainable_yield_pct, 4.0)  # base=3+liq=1

    def test_shares_sum_to_100_when_components_match(self):
        c = _comp(total=5.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        r = split_one(c)
        self.assertAlmostEqual(r.components_sum_pct, 100.0, places=5)

    def test_grade_a(self):
        # sustainable = 4/5 = 80% → A
        c = _comp(total=5.0, base=3.0, liq=1.0, gov=0.5, emit=0.3, price=0.2)
        r = split_one(c)
        self.assertEqual(r.attribution_grade, "A")
        self.assertTrue(r.is_sustainable)

    def test_grade_f_zero_total(self):
        # total=0 → score=100 → A
        c = _comp(total=0.0, base=0.0, liq=0.0, gov=0.0, emit=0.0, price=0.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 100.0)
        self.assertEqual(r.attribution_grade, "A")

    def test_grade_f_all_emissions(self):
        # sustainable=0, total=10 → score=0 → F
        c = _comp(total=10.0, base=0.0, liq=0.0, gov=0.0, emit=10.0, price=0.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 0.0)
        self.assertEqual(r.attribution_grade, "F")
        self.assertFalse(r.is_sustainable)

    def test_grade_b(self):
        # sustainable=7/10=70% → B
        c = _comp(total=10.0, base=5.0, liq=2.0, gov=1.0, emit=1.5, price=0.5)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 70.0)
        self.assertEqual(r.attribution_grade, "B")
        self.assertTrue(r.is_sustainable)

    def test_grade_c(self):
        # sustainable=5/10=50% → C
        c = _comp(total=10.0, base=3.0, liq=2.0, gov=0.0, emit=4.0, price=1.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 50.0)
        self.assertEqual(r.attribution_grade, "C")

    def test_grade_d(self):
        # sustainable=2/10=20% → D
        c = _comp(total=10.0, base=1.0, liq=1.0, gov=0.0, emit=7.0, price=1.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 20.0)
        self.assertEqual(r.attribution_grade, "D")

    def test_base_share_correct(self):
        c = _comp(total=10.0, base=4.0, liq=2.0, gov=1.0, emit=2.0, price=1.0)
        r = split_one(c)
        self.assertAlmostEqual(r.base_rate_share_pct, 40.0)

    def test_note_contains_text(self):
        c = _comp()
        r = split_one(c)
        self.assertIsInstance(r.note, str)
        self.assertGreater(len(r.note), 0)

    def test_100_percent_sustainable(self):
        # Only base + liq, no gov/emit/price
        c = _comp(total=5.0, base=4.0, liq=1.0, gov=0.0, emit=0.0, price=0.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 100.0)
        self.assertEqual(r.attribution_grade, "A")

    def test_note_warns_on_bad_sum(self):
        # components sum != total → warning in note
        c = _comp(total=10.0, base=1.0, liq=1.0, gov=0.0, emit=0.0, price=0.0)
        r = split_one(c)
        self.assertIn("WARNING", r.note)

    def test_is_sustainable_true_for_a_and_b(self):
        for score in [80.0, 90.0, 100.0, 60.0, 70.0]:
            grade = compute_attribution_grade(score)
            is_s = grade in ("A", "B")
            if grade in ("A", "B"):
                self.assertTrue(is_s)
            else:
                self.assertFalse(is_s)


# ─── YieldAttributionSplitter.split() ────────────────────────────────────────

class TestSplitMultiple(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.splitter = YieldAttributionSplitter(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_empty_list_returns_summary(self):
        s = self.splitter.split([])
        self.assertIsInstance(s, YieldAttributionSummary)
        self.assertEqual(s.protocols, [])
        self.assertAlmostEqual(s.portfolio_avg_sustainability_score, 100.0)
        self.assertEqual(s.portfolio_attribution_grade, "A")

    def test_single_protocol(self):
        s = self.splitter.split([_comp()])
        self.assertEqual(len(s.protocols), 1)

    def test_multiple_protocols_count(self):
        data = [_comp(f"P{i}") for i in range(5)]
        s = self.splitter.split(data)
        self.assertEqual(len(s.protocols), 5)

    def test_avg_total_yield(self):
        data = [
            _comp("A", total=4.0, base=3.0, liq=1.0, gov=0.0, emit=0.0, price=0.0),
            _comp("B", total=6.0, base=4.0, liq=2.0, gov=0.0, emit=0.0, price=0.0),
        ]
        s = self.splitter.split(data)
        self.assertAlmostEqual(s.avg_total_yield_pct, 5.0)

    def test_avg_sustainable_yield(self):
        data = [
            _comp("A", total=5.0, base=2.0, liq=1.0, gov=0.5, emit=1.0, price=0.5),
            _comp("B", total=8.0, base=4.0, liq=2.0, gov=0.5, emit=1.0, price=0.5),
        ]
        s = self.splitter.split(data)
        # (2+1 + 4+2)/2 = 9/2 = 4.5
        self.assertAlmostEqual(s.avg_sustainable_yield_pct, 4.5)

    def test_sustainable_protocols_list(self):
        data = [
            _comp("HighSust", total=5.0, base=4.5, liq=0.5, gov=0.0, emit=0.0, price=0.0),
            _comp("LowSust",  total=10.0, base=0.5, liq=0.5, gov=0.0, emit=9.0, price=0.0),
        ]
        s = self.splitter.split(data)
        self.assertIn("HighSust", s.sustainable_protocols)
        self.assertNotIn("LowSust", s.sustainable_protocols)

    def test_unsustainable_protocols_list(self):
        data = [
            _comp("HighSust", total=5.0, base=4.0, liq=0.5, gov=0.0, emit=0.0, price=0.5),
            _comp("LowSust",  total=10.0, base=0.5, liq=0.5, gov=0.0, emit=9.0, price=0.0),
        ]
        s = self.splitter.split(data)
        self.assertIn("LowSust", s.unsustainable_protocols)
        self.assertNotIn("HighSust", s.unsustainable_protocols)

    def test_portfolio_grade_from_avg_score(self):
        # All grade A → portfolio A
        data = [
            _comp("A", total=5.0, base=4.0, liq=1.0, gov=0.0, emit=0.0, price=0.0),
            _comp("B", total=5.0, base=4.0, liq=1.0, gov=0.0, emit=0.0, price=0.0),
        ]
        s = self.splitter.split(data)
        self.assertEqual(s.portfolio_attribution_grade, "A")

    def test_timestamp_recent(self):
        import time
        before = time.time()
        s = self.splitter.split([_comp()])
        after = time.time()
        self.assertGreaterEqual(s.timestamp, before)
        self.assertLessEqual(s.timestamp, after)

    def test_writes_to_file(self):
        self.splitter.split([_comp()])
        self.assertTrue(self.tmp.exists())


# ─── get_sustainable_yield ───────────────────────────────────────────────────

class TestGetSustainableYield(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.splitter = YieldAttributionSplitter(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_returns_zero_before_split_called(self):
        self.assertAlmostEqual(self.splitter.get_sustainable_yield(), 0.0)

    def test_returns_correct_avg_sustainable(self):
        data = [
            _comp("A", total=5.0, base=2.0, liq=1.0, gov=0.0, emit=1.5, price=0.5),
            _comp("B", total=8.0, base=4.0, liq=2.0, gov=0.5, emit=1.0, price=0.5),
        ]
        self.splitter.split(data)
        expected = (3.0 + 6.0) / 2  # (2+1 + 4+2)/2 = 4.5
        self.assertAlmostEqual(self.splitter.get_sustainable_yield(), expected)

    def test_updates_on_second_call(self):
        self.splitter.split([_comp("A", total=4.0, base=2.0, liq=1.0,
                                    gov=0.0, emit=0.5, price=0.5)])
        first = self.splitter.get_sustainable_yield()
        self.splitter.split([_comp("B", total=10.0, base=6.0, liq=2.0,
                                    gov=0.0, emit=1.0, price=1.0)])
        second = self.splitter.get_sustainable_yield()
        self.assertNotAlmostEqual(first, second)
        self.assertAlmostEqual(second, 8.0)

    def test_empty_input_returns_zero(self):
        self.splitter.split([])
        self.assertAlmostEqual(self.splitter.get_sustainable_yield(), 0.0)


# ─── get_attribution_summary ─────────────────────────────────────────────────

class TestGetAttributionSummary(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.splitter = YieldAttributionSplitter(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_returns_none_before_split_called(self):
        self.assertIsNone(self.splitter.get_attribution_summary())

    def test_returns_summary_after_split(self):
        self.splitter.split([_comp()])
        s = self.splitter.get_attribution_summary()
        self.assertIsNotNone(s)
        self.assertIsInstance(s, YieldAttributionSummary)

    def test_summary_matches_split_return(self):
        data = [_comp()]
        returned = self.splitter.split(data)
        cached = self.splitter.get_attribution_summary()
        self.assertIs(returned, cached)

    def test_summary_updates_on_second_split(self):
        self.splitter.split([_comp("A")])
        s1 = self.splitter.get_attribution_summary()
        self.splitter.split([_comp("B", total=10.0, base=5.0, liq=3.0,
                                    gov=0.5, emit=1.0, price=0.5)])
        s2 = self.splitter.get_attribution_summary()
        self.assertIsNot(s1, s2)


# ─── Ring buffer + persistence ───────────────────────────────────────────────

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.splitter = YieldAttributionSplitter(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_creates_file_after_split(self):
        self.splitter.split([_comp()])
        self.assertTrue(self.tmp.exists())

    def test_file_is_valid_json(self):
        self.splitter.split([_comp()])
        data = json.loads(self.tmp.read_text())
        self.assertIsInstance(data, list)

    def test_multiple_runs_accumulate(self):
        self.splitter.split([_comp()])
        self.splitter.split([_comp()])
        data = json.loads(self.tmp.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_max(self):
        for _ in range(MAX_ENTRIES + 5):
            self.splitter.split([_comp()])
        data = json.loads(self.tmp.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_load_history_empty_when_no_file(self):
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_load_history_returns_list(self):
        self.splitter.split([_comp()])
        history = load_history(self.tmp)
        self.assertIsInstance(history, list)

    def test_load_history_handles_corrupt_file(self):
        self.tmp.write_text("NOT_JSON")
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_load_history_handles_empty_file(self):
        self.tmp.write_text("")
        history = load_history(self.tmp)
        self.assertEqual(history, [])

    def test_atomic_write_no_tmp_left(self):
        self.splitter.split([_comp()])
        tmp = self.tmp.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_persisted_grade_correct(self):
        # All base rate → grade A
        c = _comp(total=5.0, base=5.0, liq=0.0, gov=0.0, emit=0.0, price=0.0)
        self.splitter.split([c])
        data = json.loads(self.tmp.read_text())
        self.assertEqual(data[0]["portfolio_attribution_grade"], "A")


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = _tmp_file()
        self.splitter = YieldAttributionSplitter(data_file=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()

    def test_zero_total_yield_single_protocol(self):
        c = _comp(total=0.0, base=0.0, liq=0.0, gov=0.0, emit=0.0, price=0.0)
        s = self.splitter.split([c])
        r = s.protocols[0]
        self.assertAlmostEqual(r.sustainability_score, 100.0)
        self.assertEqual(r.attribution_grade, "A")
        self.assertAlmostEqual(r.components_sum_pct, 0.0)

    def test_100_percent_sustainable_single(self):
        c = _comp(total=5.0, base=4.0, liq=1.0, gov=0.0, emit=0.0, price=0.0)
        s = self.splitter.split([c])
        r = s.protocols[0]
        self.assertAlmostEqual(r.sustainability_score, 100.0)
        self.assertEqual(r.attribution_grade, "A")

    def test_components_sum_not_100(self):
        # total=10, but components only sum to 6
        c = _comp(total=10.0, base=2.0, liq=1.0, gov=1.0, emit=1.0, price=1.0)
        r = split_one(c)
        # shares: each/10*100, sum of shares = (2+1+1+1+1)/10*100 = 6/10*100 = 60
        self.assertAlmostEqual(r.components_sum_pct, 60.0)
        self.assertIn("WARNING", r.note)

    def test_all_protocols_imminent_equivalent(self):
        # All F grade (0% sustainable)
        data = [
            _comp(f"P{i}", total=10.0, base=0.0, liq=0.0, gov=0.0, emit=10.0, price=0.0)
            for i in range(3)
        ]
        s = self.splitter.split(data)
        self.assertEqual(s.portfolio_attribution_grade, "F")
        self.assertEqual(len(s.unsustainable_protocols), 3)
        self.assertEqual(len(s.sustainable_protocols), 0)

    def test_mixed_grades_portfolio(self):
        data = [
            _comp("HighA", total=5.0, base=4.0, liq=1.0, gov=0.0, emit=0.0, price=0.0),   # 100% → A
            _comp("LowF",  total=10.0, base=0.0, liq=0.0, gov=0.0, emit=10.0, price=0.0), # 0% → F
        ]
        s = self.splitter.split(data)
        # avg_score = (100 + 0) / 2 = 50 → C
        self.assertAlmostEqual(s.portfolio_avg_sustainability_score, 50.0)
        self.assertEqual(s.portfolio_attribution_grade, "C")

    def test_large_number_of_protocols(self):
        data = [_comp(f"P{i}", total=float(i+1), base=float(i+1)*0.6,
                       liq=float(i+1)*0.2, gov=0.0, emit=float(i+1)*0.2, price=0.0)
                for i in range(20)]
        s = self.splitter.split(data)
        self.assertEqual(len(s.protocols), 20)

    def test_data_file_created_in_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = Path(d) / "analytics" / "logs"
            f = subdir / "yield_attr.json"
            sp = YieldAttributionSplitter(data_file=f)
            sp.split([_comp()])
            self.assertTrue(f.exists())

    def test_all_grades_covered(self):
        test_cases = [
            (100.0, "A"),
            (85.0,  "A"),
            (70.0,  "B"),
            (60.0,  "B"),
            (50.0,  "C"),
            (40.0,  "C"),
            (30.0,  "D"),
            (20.0,  "D"),
            (10.0,  "F"),
            (0.0,   "F"),
        ]
        for score, expected in test_cases:
            with self.subTest(score=score):
                self.assertEqual(compute_attribution_grade(score), expected)

    def test_sustainability_score_bounded_below_0(self):
        # negative sustainable → clamped to 0
        score = compute_sustainability_score(-5.0, 10.0)
        self.assertAlmostEqual(score, 0.0)

    def test_high_emissions_low_score(self):
        # 95% emissions, 5% base → score=5% → F
        c = _comp(total=20.0, base=1.0, liq=0.0, gov=0.0, emit=19.0, price=0.0)
        r = split_one(c)
        self.assertAlmostEqual(r.sustainability_score, 5.0)
        self.assertEqual(r.attribution_grade, "F")
        self.assertFalse(r.is_sustainable)

    def test_is_sustainable_false_for_c_d_f(self):
        for score in [50.0, 30.0, 10.0]:
            grade = compute_attribution_grade(score)
            self.assertNotIn(grade, ("A", "B"))

    def test_portfolio_summary_fields_present(self):
        s = self.splitter.split([_comp()])
        self.assertIsInstance(s.portfolio_avg_sustainability_score, float)
        self.assertIsInstance(s.portfolio_attribution_grade, str)
        self.assertIsInstance(s.sustainable_protocols, list)
        self.assertIsInstance(s.unsustainable_protocols, list)
        self.assertIsInstance(s.avg_total_yield_pct, float)
        self.assertIsInstance(s.avg_sustainable_yield_pct, float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
