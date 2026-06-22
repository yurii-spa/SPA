"""
Tests for MP-666: StablecoinRiskAssessor
Run: python3 -m unittest spa_core.tests.test_stablecoin_risk_assessor -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.stablecoin_risk_assessor import (
    StablecoinInput,
    StablecoinRisk,
    StablecoinRiskAssessor,
    MAX_ENTRIES,
)


def _make_input(
    symbol="USDC",
    current_price=1.0,
    peg_target=1.0,
    collateral_ratio=1.0,
    is_algorithmic=False,
    audit_count=3,
    market_cap_usd=50_000_000_000,
    capital_exposure_usd=10_000.0,
):
    return StablecoinInput(
        symbol=symbol,
        current_price=current_price,
        peg_target=peg_target,
        collateral_ratio=collateral_ratio,
        is_algorithmic=is_algorithmic,
        audit_count=audit_count,
        market_cap_usd=market_cap_usd,
        capital_exposure_usd=capital_exposure_usd,
    )


def _assessor(tmp_dir=None):
    if tmp_dir:
        return StablecoinRiskAssessor(data_file=Path(tmp_dir) / "test_log.json")
    return StablecoinRiskAssessor()


# ---------------------------------------------------------------------------
# 1. _deviation_pct
# ---------------------------------------------------------------------------
class TestDeviationPct(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_target_zero_returns_zero(self):
        self.assertEqual(self.a._deviation_pct(1.0, 0), 0.0)

    def test_negative_target_returns_zero(self):
        self.assertEqual(self.a._deviation_pct(1.0, -1.0), 0.0)

    def test_perfect_peg_zero(self):
        self.assertEqual(self.a._deviation_pct(1.0, 1.0), 0.0)

    def test_half_percent_deviation(self):
        result = self.a._deviation_pct(1.005, 1.0)
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_half_percent_negative(self):
        result = self.a._deviation_pct(0.995, 1.0)
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_one_percent_deviation(self):
        result = self.a._deviation_pct(1.01, 1.0)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_five_percent_deviation(self):
        result = self.a._deviation_pct(0.95, 1.0)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_ten_percent_deviation(self):
        result = self.a._deviation_pct(0.90, 1.0)
        self.assertAlmostEqual(result, 10.0, places=4)

    def test_symmetry_above_and_below(self):
        self.assertAlmostEqual(
            self.a._deviation_pct(1.02, 1.0),
            self.a._deviation_pct(0.98, 1.0),
            places=4,
        )

    def test_returns_float(self):
        self.assertIsInstance(self.a._deviation_pct(1.0, 1.0), float)

    def test_exact_boundary_005(self):
        # 0.5% = boundary of ON_PEG
        result = self.a._deviation_pct(1.005, 1.0)
        self.assertAlmostEqual(result, 0.5, places=3)


# ---------------------------------------------------------------------------
# 2. _peg_status
# ---------------------------------------------------------------------------
class TestPegStatus(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_on_peg_zero(self):
        self.assertEqual(self.a._peg_status(0.0), "ON_PEG")

    def test_on_peg_below_05(self):
        self.assertEqual(self.a._peg_status(0.4), "ON_PEG")

    def test_on_peg_at_boundary_05(self):
        self.assertEqual(self.a._peg_status(0.5), "ON_PEG")

    def test_soft_depeg_just_above_05(self):
        self.assertEqual(self.a._peg_status(0.51), "SOFT_DEPEG")

    def test_soft_depeg_at_1pct(self):
        self.assertEqual(self.a._peg_status(1.0), "SOFT_DEPEG")

    def test_soft_depeg_at_boundary_2(self):
        self.assertEqual(self.a._peg_status(2.0), "SOFT_DEPEG")

    def test_hard_depeg_just_above_2(self):
        self.assertEqual(self.a._peg_status(2.01), "HARD_DEPEG")

    def test_hard_depeg_at_3pct(self):
        self.assertEqual(self.a._peg_status(3.0), "HARD_DEPEG")

    def test_hard_depeg_at_boundary_5(self):
        self.assertEqual(self.a._peg_status(5.0), "HARD_DEPEG")

    def test_crisis_just_above_5(self):
        self.assertEqual(self.a._peg_status(5.01), "CRISIS")

    def test_crisis_at_10(self):
        self.assertEqual(self.a._peg_status(10.0), "CRISIS")

    def test_crisis_extreme(self):
        self.assertEqual(self.a._peg_status(99.0), "CRISIS")


# ---------------------------------------------------------------------------
# 3. _collateral_score
# ---------------------------------------------------------------------------
class TestCollateralScore(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_ratio_200_gives_100(self):
        self.assertAlmostEqual(self.a._collateral_score(2.0), 100.0)

    def test_ratio_above_200_still_100(self):
        self.assertAlmostEqual(self.a._collateral_score(3.0), 100.0)

    def test_ratio_150_gives_80(self):
        self.assertAlmostEqual(self.a._collateral_score(1.5), 80.0, places=4)

    def test_ratio_120_gives_60(self):
        self.assertAlmostEqual(self.a._collateral_score(1.2), 60.0, places=4)

    def test_ratio_100_gives_40(self):
        self.assertAlmostEqual(self.a._collateral_score(1.0), 40.0, places=4)

    def test_ratio_zero_gives_zero(self):
        self.assertAlmostEqual(self.a._collateral_score(0.0), 0.0)

    def test_ratio_below_1_proportional(self):
        # ratio=0.5 → 0.5 * 40 = 20
        self.assertAlmostEqual(self.a._collateral_score(0.5), 20.0, places=4)

    def test_ratio_175_between_150_and_200(self):
        # 1.75 → 80 + 20*(1.75-1.5)/0.5 = 80 + 10 = 90
        self.assertAlmostEqual(self.a._collateral_score(1.75), 90.0, places=4)

    def test_ratio_135_between_120_and_150(self):
        # 1.35 → 60 + 20*(1.35-1.2)/0.3 = 60 + 10 = 70
        self.assertAlmostEqual(self.a._collateral_score(1.35), 70.0, places=4)

    def test_ratio_110_between_100_and_120(self):
        # 1.10 → 40 + 20*(1.10-1.0)/0.2 = 40 + 10 = 50
        self.assertAlmostEqual(self.a._collateral_score(1.10), 50.0, places=4)

    def test_never_negative(self):
        self.assertGreaterEqual(self.a._collateral_score(-5.0), 0.0)


# ---------------------------------------------------------------------------
# 4. _algo_risk_score
# ---------------------------------------------------------------------------
class TestAlgoRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_not_algo_returns_90(self):
        self.assertEqual(self.a._algo_risk_score(False, 1.0), 90.0)

    def test_not_algo_high_collateral_still_90(self):
        self.assertEqual(self.a._algo_risk_score(False, 2.0), 90.0)

    def test_algo_high_collateral_returns_60(self):
        self.assertEqual(self.a._algo_risk_score(True, 1.5), 60.0)

    def test_algo_high_collateral_above_15_returns_60(self):
        self.assertEqual(self.a._algo_risk_score(True, 2.0), 60.0)

    def test_pure_algo_low_collateral_returns_20(self):
        self.assertEqual(self.a._algo_risk_score(True, 1.0), 20.0)

    def test_pure_algo_zero_collateral_returns_20(self):
        self.assertEqual(self.a._algo_risk_score(True, 0.0), 20.0)

    def test_algo_just_below_15_returns_20(self):
        self.assertEqual(self.a._algo_risk_score(True, 1.49), 20.0)


# ---------------------------------------------------------------------------
# 5. _audit_score
# ---------------------------------------------------------------------------
class TestAuditScore(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_zero_audits_gives_0(self):
        self.assertEqual(self.a._audit_score(0), 0.0)

    def test_one_audit_gives_25(self):
        self.assertEqual(self.a._audit_score(1), 25.0)

    def test_two_audits_gives_50(self):
        self.assertEqual(self.a._audit_score(2), 50.0)

    def test_three_audits_gives_75(self):
        self.assertEqual(self.a._audit_score(3), 75.0)

    def test_four_audits_gives_100(self):
        self.assertEqual(self.a._audit_score(4), 100.0)

    def test_five_audits_gives_100(self):
        self.assertEqual(self.a._audit_score(5), 100.0)

    def test_ten_audits_gives_100(self):
        self.assertEqual(self.a._audit_score(10), 100.0)


# ---------------------------------------------------------------------------
# 6. _size_score
# ---------------------------------------------------------------------------
class TestSizeScore(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_50b_gives_100(self):
        self.assertEqual(self.a._size_score(50_000_000_000), 100.0)

    def test_10b_exact_gives_100(self):
        self.assertEqual(self.a._size_score(10_000_000_000), 100.0)

    def test_5b_gives_80(self):
        self.assertEqual(self.a._size_score(5_000_000_000), 80.0)

    def test_1b_exact_gives_80(self):
        self.assertEqual(self.a._size_score(1_000_000_000), 80.0)

    def test_500m_gives_50(self):
        self.assertEqual(self.a._size_score(500_000_000), 50.0)

    def test_100m_exact_gives_50(self):
        self.assertEqual(self.a._size_score(100_000_000), 50.0)

    def test_50m_gives_20(self):
        self.assertEqual(self.a._size_score(50_000_000), 20.0)

    def test_10m_exact_gives_20(self):
        self.assertEqual(self.a._size_score(10_000_000), 20.0)

    def test_5m_gives_0(self):
        self.assertEqual(self.a._size_score(5_000_000), 0.0)

    def test_zero_gives_0(self):
        self.assertEqual(self.a._size_score(0), 0.0)


# ---------------------------------------------------------------------------
# 7. _recommendation
# ---------------------------------------------------------------------------
class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_hard_depeg_exits(self):
        self.assertEqual(self.a._recommendation("A", "HARD_DEPEG"), "EXIT")

    def test_crisis_exits(self):
        self.assertEqual(self.a._recommendation("B", "CRISIS"), "EXIT")

    def test_grade_d_reduces(self):
        self.assertEqual(self.a._recommendation("D", "ON_PEG"), "REDUCE")

    def test_soft_depeg_reduces(self):
        self.assertEqual(self.a._recommendation("A", "SOFT_DEPEG"), "REDUCE")

    def test_grade_a_on_peg_holds(self):
        self.assertEqual(self.a._recommendation("A", "ON_PEG"), "HOLD")

    def test_grade_b_on_peg_holds(self):
        self.assertEqual(self.a._recommendation("B", "ON_PEG"), "HOLD")

    def test_grade_c_on_peg_holds(self):
        self.assertEqual(self.a._recommendation("C", "ON_PEG"), "HOLD")

    def test_hard_depeg_overrides_grade_a(self):
        # Even grade A → EXIT when HARD_DEPEG
        self.assertEqual(self.a._recommendation("A", "HARD_DEPEG"), "EXIT")

    def test_crisis_overrides_grade_b(self):
        self.assertEqual(self.a._recommendation("B", "CRISIS"), "EXIT")


# ---------------------------------------------------------------------------
# 8. assess — integration
# ---------------------------------------------------------------------------
class TestAssess(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def _usdc_like(self):
        return _make_input(
            symbol="USDC",
            current_price=1.0,
            peg_target=1.0,
            collateral_ratio=2.0,
            is_algorithmic=False,
            audit_count=5,
            market_cap_usd=50_000_000_000,
            capital_exposure_usd=10_000.0,
        )

    def test_usdc_like_grade_a(self):
        r = self.a.assess(self._usdc_like())
        self.assertEqual(r.risk_grade, "A")

    def test_usdc_like_hold(self):
        r = self.a.assess(self._usdc_like())
        self.assertEqual(r.recommendation, "HOLD")

    def test_usdc_like_on_peg(self):
        r = self.a.assess(self._usdc_like())
        self.assertEqual(r.peg_status, "ON_PEG")

    def test_algo_crisis_exit(self):
        # TerraUST-like: algo, $0.94 price (6% depeg > 5% → CRISIS)
        inp = _make_input(
            symbol="UST",
            current_price=0.94,
            peg_target=1.0,
            collateral_ratio=1.0,
            is_algorithmic=True,
            audit_count=1,
            market_cap_usd=5_000_000_000,
            capital_exposure_usd=10_000.0,
        )
        r = self.a.assess(inp)
        self.assertEqual(r.peg_status, "CRISIS")
        self.assertEqual(r.recommendation, "EXIT")

    def test_exposure_at_risk_calculation(self):
        # 1% deviation, $100k exposure → $1000 at risk
        inp = _make_input(
            current_price=1.01,
            peg_target=1.0,
            capital_exposure_usd=100_000.0,
            collateral_ratio=1.5,
            audit_count=3,
            market_cap_usd=1_000_000_000,
        )
        r = self.a.assess(inp)
        expected = round(100_000.0 * (r.deviation_pct / 100), 4)
        self.assertAlmostEqual(r.exposure_at_risk_usd, expected, places=4)

    def test_composite_clamped_max_100(self):
        r = self.a.assess(self._usdc_like())
        self.assertLessEqual(r.composite_risk_score, 100.0)

    def test_composite_clamped_min_0(self):
        inp = _make_input(
            current_price=0.5,
            peg_target=1.0,
            collateral_ratio=0.0,
            is_algorithmic=True,
            audit_count=0,
            market_cap_usd=0,
        )
        r = self.a.assess(inp)
        self.assertGreaterEqual(r.composite_risk_score, 0.0)

    def test_deviation_stored_correctly(self):
        inp = _make_input(current_price=0.98, peg_target=1.0)
        r = self.a.assess(inp)
        self.assertAlmostEqual(r.deviation_pct, 2.0, places=2)

    def test_symbol_preserved(self):
        inp = _make_input(symbol="DAI")
        r = self.a.assess(inp)
        self.assertEqual(r.symbol, "DAI")

    def test_price_rounded_to_6(self):
        inp = _make_input(current_price=1.0000001)
        r = self.a.assess(inp)
        # rounded to 6 decimals
        self.assertEqual(r.current_price, round(1.0000001, 6))

    def test_soft_depeg_gives_reduce(self):
        inp = _make_input(current_price=0.99, peg_target=1.0)  # 1% dev → SOFT_DEPEG
        r = self.a.assess(inp)
        self.assertEqual(r.peg_status, "SOFT_DEPEG")
        self.assertEqual(r.recommendation, "REDUCE")

    def test_hard_depeg_gives_exit(self):
        inp = _make_input(current_price=0.97, peg_target=1.0)  # 3% dev → HARD_DEPEG
        r = self.a.assess(inp)
        self.assertEqual(r.peg_status, "HARD_DEPEG")
        self.assertEqual(r.recommendation, "EXIT")

    def test_zero_exposure_gives_zero_at_risk(self):
        inp = _make_input(capital_exposure_usd=0.0, current_price=0.95, peg_target=1.0)
        r = self.a.assess(inp)
        self.assertEqual(r.exposure_at_risk_usd, 0.0)

    def test_assess_returns_stablecoin_risk(self):
        r = self.a.assess(self._usdc_like())
        self.assertIsInstance(r, StablecoinRisk)


# ---------------------------------------------------------------------------
# 9. assess_batch
# ---------------------------------------------------------------------------
class TestAssessBatch(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.a.assess_batch([]), [])

    def test_batch_length_matches_input(self):
        inputs = [_make_input(symbol=f"S{i}") for i in range(5)]
        results = self.a.assess_batch(inputs)
        self.assertEqual(len(results), 5)

    def test_batch_preserves_order(self):
        inputs = [_make_input(symbol=s) for s in ("USDC", "DAI", "FRAX")]
        results = self.a.assess_batch(inputs)
        self.assertEqual([r.symbol for r in results], ["USDC", "DAI", "FRAX"])

    def test_batch_single_item(self):
        results = self.a.assess_batch([_make_input()])
        self.assertEqual(len(results), 1)


# ---------------------------------------------------------------------------
# 10. crisis_alerts
# ---------------------------------------------------------------------------
class TestCrisisAlerts(unittest.TestCase):
    def setUp(self):
        self.a = StablecoinRiskAssessor()

    def _make_result(self, peg_status, symbol="X"):
        inp = _make_input(symbol=symbol)
        r = self.a.assess(inp)
        # Override peg_status to simulate desired state
        object.__setattr__(r, "peg_status", peg_status)
        return r

    def _quick_result(self, price, symbol="X"):
        inp = _make_input(symbol=symbol, current_price=price, peg_target=1.0,
                          collateral_ratio=1.0, audit_count=0,
                          market_cap_usd=1_000_000, capital_exposure_usd=1000.0)
        return self.a.assess(inp)

    def test_filters_hard_depeg(self):
        r = self._quick_result(0.97)  # 3% → HARD_DEPEG
        alerts = self.a.crisis_alerts([r])
        self.assertEqual(len(alerts), 1)

    def test_filters_crisis(self):
        r = self._quick_result(0.90)  # 10% → CRISIS
        alerts = self.a.crisis_alerts([r])
        self.assertEqual(len(alerts), 1)

    def test_excludes_on_peg(self):
        r = self._quick_result(1.0)
        alerts = self.a.crisis_alerts([r])
        self.assertEqual(len(alerts), 0)

    def test_excludes_soft_depeg(self):
        r = self._quick_result(0.99)  # 1% → SOFT_DEPEG
        alerts = self.a.crisis_alerts([r])
        self.assertEqual(len(alerts), 0)

    def test_empty_input(self):
        self.assertEqual(self.a.crisis_alerts([]), [])

    def test_mixed_returns_only_alerts(self):
        results = [
            self._quick_result(1.0),    # ON_PEG
            self._quick_result(0.97),   # HARD_DEPEG
            self._quick_result(0.90),   # CRISIS
            self._quick_result(0.99),   # SOFT_DEPEG
        ]
        alerts = self.a.crisis_alerts(results)
        self.assertEqual(len(alerts), 2)


# ---------------------------------------------------------------------------
# 11. save_results + load_history
# ---------------------------------------------------------------------------
class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = StablecoinRiskAssessor(data_file=Path(self.tmp) / "log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.a.load_history(), [])

    def test_save_creates_file(self):
        r = self.a.assess(_make_input())
        self.a.save_results([r])
        self.assertTrue(self.a.data_file.exists())

    def test_save_and_reload(self):
        r = self.a.assess(_make_input(symbol="USDC"))
        self.a.save_results([r])
        history = self.a.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["symbol"], "USDC")

    def test_atomic_write_no_tmp_left(self):
        r = self.a.assess(_make_input())
        self.a.save_results([r])
        tmp_path = self.a.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_ring_buffer_100(self):
        inp = _make_input()
        r = self.a.assess(inp)
        # Write 110 entries in batches of 10 — should stay at 100
        for _ in range(11):
            self.a.save_results([r] * 10)
        history = self.a.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_history_is_list_of_dicts(self):
        r = self.a.assess(_make_input())
        self.a.save_results([r])
        history = self.a.load_history()
        self.assertIsInstance(history, list)
        self.assertIsInstance(history[0], dict)

    def test_history_entry_has_required_keys(self):
        r = self.a.assess(_make_input())
        self.a.save_results([r])
        entry = self.a.load_history()[0]
        for key in ("timestamp", "symbol", "deviation_pct", "peg_status",
                    "composite_risk_score", "risk_grade"):
            self.assertIn(key, entry)

    def test_save_empty_list(self):
        self.a.save_results([])
        self.assertEqual(self.a.load_history(), [])

    def test_accumulates_across_calls(self):
        r1 = self.a.assess(_make_input(symbol="A"))
        r2 = self.a.assess(_make_input(symbol="B"))
        self.a.save_results([r1])
        self.a.save_results([r2])
        history = self.a.load_history()
        self.assertEqual(len(history), 2)

    def test_corrupted_file_returns_empty_list(self):
        self.a.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.a.data_file.write_text("INVALID JSON {{")
        result = self.a.load_history()
        self.assertEqual(result, [])

    def test_save_results_multiple_items(self):
        inputs = [_make_input(symbol=s) for s in ("A", "B", "C")]
        results = self.a.assess_batch(inputs)
        self.a.save_results(results)
        history = self.a.load_history()
        self.assertEqual(len(history), 3)


if __name__ == "__main__":
    unittest.main()
