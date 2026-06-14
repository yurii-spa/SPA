"""
MP-1067 tests — ProtocolDeFiYieldBearingStablecoinRiskAnalyzer
Unit tests: python3 -m unittest spa_core.tests.test_protocol_defi_yield_bearing_stablecoin_risk_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_yield_bearing_stablecoin_risk_analyzer import (
    ProtocolDeFiYieldBearingStablecoinRiskAnalyzer,
    _clamp,
    _atomic_write,
    _load_ring_buffer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_input(**overrides):
    """Return a valid base input dict (SOUND category) with optional overrides."""
    inp = {
        "token_name": "TestStable",
        "peg_asset": "USD",
        "current_price_usd": 1.0,
        "apy_pct": 5.0,
        "yield_source": "lending",
        "collateral_ratio_pct": 130.0,
        "collateral_asset": "USDC",
        "collateral_apy_pct": 5.5,
        "redemption_delay_days": 1.0,
        "has_circuit_breaker": True,
        "protocol_tvl_usd": 500_000_000.0,
        "days_since_depeg_event": 0.0,
    }
    inp.update(overrides)
    return inp


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestClampHelper(unittest.TestCase):
    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below_zero(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above_hundred(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_clamp_at_zero(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_at_hundred(self):
        self.assertEqual(_clamp(100.0), 100.0)


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, [{"a": 1}])
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            data = [{"key": "val", "n": 99}]
            _atomic_write(path, data)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_atomic_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sub", "dir", "file.json")
            _atomic_write(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.json")
            _atomic_write(path, [1])
            _atomic_write(path, [2, 3])
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, [2, 3])


class TestLoadRingBuffer(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        result = _load_ring_buffer("/no/such/path/buf.json", 100)
        self.assertEqual(result, [])

    def test_valid_list_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "buf.json")
            _atomic_write(path, [1, 2, 3])
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [1, 2, 3])

    def test_cap_respected(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "buf.json")
            _atomic_write(path, list(range(200)))
            result = _load_ring_buffer(path, 10)
            self.assertEqual(len(result), 10)
            self.assertEqual(result[-1], 199)

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w") as f:
                f.write("!!!!")
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [])

    def test_non_list_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "obj.json")
            _atomic_write(path, {"k": "v"})
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def test_has_depeg_risk_score(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("depeg_risk_score", r)

    def test_has_yield_sustainability_score(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("yield_sustainability_score", r)

    def test_has_collateral_adequacy_score(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("collateral_adequacy_score", r)

    def test_has_composite_risk_score(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("composite_risk_score", r)

    def test_has_risk_label(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("risk_label", r)

    def test_has_module_field(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertEqual(r["module"], "ProtocolDeFiYieldBearingStablecoinRiskAnalyzer")

    def test_has_mp_field(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertEqual(r["mp"], "MP-1067")

    def test_has_timestamp(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn("timestamp", r)

    def test_echoes_token_name(self):
        r = self.az.analyze(_base_input(token_name="sDAI"), write_log=False)
        self.assertEqual(r["token_name"], "sDAI")

    def test_echoes_peg_asset(self):
        r = self.az.analyze(_base_input(peg_asset="EUR"), write_log=False)
        self.assertEqual(r["peg_asset"], "EUR")

    def test_echoes_apy_pct(self):
        r = self.az.analyze(_base_input(apy_pct=8.5), write_log=False)
        self.assertAlmostEqual(r["apy_pct"], 8.5)

    def test_echoes_collateral_ratio(self):
        r = self.az.analyze(_base_input(collateral_ratio_pct=140.0), write_log=False)
        self.assertAlmostEqual(r["collateral_ratio_pct"], 140.0)


# ---------------------------------------------------------------------------
# Score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _check_bounds(self, inp):
        r = self.az.analyze(inp, write_log=False)
        self.assertGreaterEqual(r["depeg_risk_score"], 0.0)
        self.assertLessEqual(r["depeg_risk_score"], 100.0)
        self.assertGreaterEqual(r["yield_sustainability_score"], 0.0)
        self.assertLessEqual(r["yield_sustainability_score"], 100.0)
        self.assertGreaterEqual(r["collateral_adequacy_score"], 0.0)
        self.assertLessEqual(r["collateral_adequacy_score"], 100.0)
        self.assertGreaterEqual(r["composite_risk_score"], 0.0)
        self.assertLessEqual(r["composite_risk_score"], 100.0)

    def test_bounds_safe_token(self):
        self._check_bounds(_base_input(
            yield_source="treasuries", collateral_ratio_pct=200.0,
            apy_pct=4.0, current_price_usd=1.0
        ))

    def test_bounds_risky_token(self):
        self._check_bounds(_base_input(
            yield_source="algo", collateral_ratio_pct=70.0,
            apy_pct=60.0, current_price_usd=0.90,
            has_circuit_breaker=False, days_since_depeg_event=10.0
        ))

    def test_bounds_zero_tvl(self):
        self._check_bounds(_base_input(protocol_tvl_usd=0.0))

    def test_bounds_zero_apy(self):
        self._check_bounds(_base_input(apy_pct=0.0))

    def test_bounds_extreme_collateral_ratio(self):
        self._check_bounds(_base_input(collateral_ratio_pct=1000.0))

    def test_bounds_price_far_above_peg(self):
        self._check_bounds(_base_input(current_price_usd=2.0))

    def test_bounds_price_far_below_peg(self):
        self._check_bounds(_base_input(current_price_usd=0.5))

    def test_bounds_long_redemption_delay(self):
        self._check_bounds(_base_input(redemption_delay_days=90.0))

    def test_bounds_recent_depeg(self):
        self._check_bounds(_base_input(days_since_depeg_event=5.0))


# ---------------------------------------------------------------------------
# Depeg risk score
# ---------------------------------------------------------------------------

class TestDepegRiskScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _depeg(self, **kw):
        return self.az.analyze(_base_input(**kw), write_log=False)["depeg_risk_score"]

    def test_algo_yield_highest_depeg_risk(self):
        algo = self._depeg(yield_source="algo")
        treas = self._depeg(yield_source="treasuries")
        self.assertGreater(algo, treas)

    def test_price_deviation_increases_depeg_risk(self):
        at_peg = self._depeg(current_price_usd=1.0)
        off_peg = self._depeg(current_price_usd=0.95)
        self.assertGreater(off_peg, at_peg)

    def test_undercollateralized_raises_depeg_risk(self):
        over = self._depeg(collateral_ratio_pct=200.0)
        under = self._depeg(collateral_ratio_pct=85.0)
        self.assertGreater(under, over)

    def test_long_redemption_delay_raises_depeg_risk(self):
        short = self._depeg(redemption_delay_days=0.0)
        long_ = self._depeg(redemption_delay_days=60.0)
        self.assertGreater(long_, short)

    def test_small_tvl_raises_depeg_risk(self):
        large = self._depeg(protocol_tvl_usd=500_000_000.0)
        small = self._depeg(protocol_tvl_usd=1_000_000.0)
        self.assertGreater(small, large)

    def test_circuit_breaker_lowers_depeg_risk(self):
        with_cb = self._depeg(has_circuit_breaker=True)
        no_cb = self._depeg(has_circuit_breaker=False)
        self.assertLess(with_cb, no_cb)

    def test_recent_depeg_raises_risk(self):
        no_history = self._depeg(days_since_depeg_event=0.0)
        recent = self._depeg(days_since_depeg_event=30.0)
        self.assertGreater(recent, no_history)

    def test_older_depeg_less_penalty_than_recent(self):
        recent = self._depeg(days_since_depeg_event=30.0)
        old = self._depeg(days_since_depeg_event=400.0)
        self.assertGreater(recent, old)

    def test_lending_greater_depeg_than_treasuries(self):
        lending = self._depeg(yield_source="lending")
        treas = self._depeg(yield_source="treasuries")
        self.assertGreater(lending, treas)

    def test_lending_greater_depeg_than_staking(self):
        # Lending (utilization risk, +20) is riskier than staking (+15) in our model
        lending = self._depeg(yield_source="lending")
        staking = self._depeg(yield_source="staking")
        self.assertGreater(lending, staking)


# ---------------------------------------------------------------------------
# Yield sustainability score
# ---------------------------------------------------------------------------

class TestYieldSustainabilityScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _sustain(self, **kw):
        return self.az.analyze(_base_input(**kw), write_log=False)["yield_sustainability_score"]

    def test_treasuries_most_sustainable(self):
        treas = self._sustain(yield_source="treasuries")
        algo = self._sustain(yield_source="algo")
        self.assertGreater(treas, algo)

    def test_high_apy_lowers_sustainability(self):
        low_apy = self._sustain(apy_pct=4.0)
        high_apy = self._sustain(apy_pct=35.0)
        self.assertGreater(low_apy, high_apy)

    def test_collateral_covers_yield_bonus(self):
        covered = self._sustain(collateral_apy_pct=10.0, apy_pct=5.0)
        not_covered = self._sustain(collateral_apy_pct=1.0, apy_pct=5.0)
        self.assertGreater(covered, not_covered)

    def test_large_tvl_improves_sustainability(self):
        large = self._sustain(protocol_tvl_usd=200_000_000.0)
        small = self._sustain(protocol_tvl_usd=5_000_000.0)
        self.assertGreater(large, small)

    def test_circuit_breaker_improves_sustainability(self):
        with_cb = self._sustain(has_circuit_breaker=True)
        no_cb = self._sustain(has_circuit_breaker=False)
        self.assertGreater(with_cb, no_cb)

    def test_algo_has_low_base_sustainability(self):
        algo = self._sustain(yield_source="algo")
        self.assertLess(algo, 50.0)

    def test_treasuries_has_high_base_sustainability(self):
        treas = self._sustain(yield_source="treasuries", apy_pct=5.0, collateral_apy_pct=5.5)
        self.assertGreater(treas, 50.0)

    def test_partial_col_cover_between_full_and_none(self):
        full = self._sustain(collateral_apy_pct=10.0, apy_pct=5.0)
        partial = self._sustain(collateral_apy_pct=4.1, apy_pct=5.0)  # >= 80% of 5 = 4.0
        none = self._sustain(collateral_apy_pct=1.0, apy_pct=5.0)
        self.assertGreater(full, partial)
        self.assertGreaterEqual(partial, none)


# ---------------------------------------------------------------------------
# Collateral adequacy score
# ---------------------------------------------------------------------------

class TestCollateralAdequacyScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _adequacy(self, **kw):
        return self.az.analyze(_base_input(**kw), write_log=False)["collateral_adequacy_score"]

    def test_higher_collateral_ratio_higher_adequacy(self):
        low = self._adequacy(collateral_ratio_pct=90.0)
        high = self._adequacy(collateral_ratio_pct=200.0)
        self.assertGreater(high, low)

    def test_eth_collateral_premium(self):
        eth = self._adequacy(collateral_asset="ETH")
        usdc = self._adequacy(collateral_asset="USDC")
        self.assertGreaterEqual(eth, usdc)

    def test_premium_assets_score_highest(self):
        for asset in ["ETH", "WETH", "WBTC"]:
            score = self._adequacy(collateral_asset=asset)
            self.assertGreater(score, 0.0)

    def test_algo_collateral_lowest_adequacy(self):
        algo = self._adequacy(collateral_asset="ALGO")
        eth = self._adequacy(collateral_asset="ETH")
        self.assertLess(algo, eth)

    def test_instant_redemption_bonus(self):
        instant = self._adequacy(redemption_delay_days=0.0)
        delayed = self._adequacy(redemption_delay_days=14.0)
        self.assertGreater(instant, delayed)

    def test_very_long_redemption_penalty(self):
        short = self._adequacy(redemption_delay_days=1.0)
        long_ = self._adequacy(redemption_delay_days=60.0)
        self.assertGreater(short, long_)

    def test_circuit_breaker_bonus(self):
        with_cb = self._adequacy(has_circuit_breaker=True)
        no_cb = self._adequacy(has_circuit_breaker=False)
        self.assertGreater(with_cb, no_cb)

    def test_undercollateralized_low_adequacy(self):
        score = self._adequacy(collateral_ratio_pct=70.0)
        self.assertLess(score, 30.0)

    def test_tbills_premium(self):
        tbills = self._adequacy(collateral_asset="T-BILLS", collateral_ratio_pct=150.0)
        self.assertGreater(tbills, 50.0)


# ---------------------------------------------------------------------------
# Composite risk score
# ---------------------------------------------------------------------------

class TestCompositeRiskScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def test_composite_increases_with_algo_yield(self):
        treas = self.az.analyze(_base_input(yield_source="treasuries"), write_log=False)["composite_risk_score"]
        algo = self.az.analyze(_base_input(yield_source="algo"), write_log=False)["composite_risk_score"]
        self.assertGreater(algo, treas)

    def test_composite_increases_with_undercollateralization(self):
        over = self.az.analyze(_base_input(collateral_ratio_pct=200.0), write_log=False)["composite_risk_score"]
        under = self.az.analyze(_base_input(collateral_ratio_pct=70.0), write_log=False)["composite_risk_score"]
        self.assertGreater(under, over)

    def test_composite_in_bounds_for_all_scenarios(self):
        scenarios = [
            _base_input(yield_source="algo", collateral_ratio_pct=60.0, apy_pct=80.0),
            _base_input(yield_source="treasuries", collateral_ratio_pct=300.0, apy_pct=4.0),
            _base_input(yield_source="lending", collateral_ratio_pct=120.0, apy_pct=8.0),
        ]
        for sc in scenarios:
            r = self.az.analyze(sc, write_log=False)["composite_risk_score"]
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 100.0)

    def test_composite_is_weighted_average(self):
        r = self.az.analyze(_base_input(), write_log=False)
        d = r["depeg_risk_score"]
        s = r["yield_sustainability_score"]
        a = r["collateral_adequacy_score"]
        expected = d * 0.40 + (100 - a) * 0.35 + (100 - s) * 0.25
        expected = max(0.0, min(100.0, expected))
        self.assertAlmostEqual(r["composite_risk_score"], round(expected, 4), places=2)


# ---------------------------------------------------------------------------
# Risk labels
# ---------------------------------------------------------------------------

class TestRiskLabels(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _label(self, **kw):
        return self.az.analyze(_base_input(**kw), write_log=False)["risk_label"]

    def test_label_gold_standard(self):
        label = self._label(
            yield_source="treasuries",
            collateral_ratio_pct=200.0,
            collateral_asset="T-BILLS",
            collateral_apy_pct=5.5,
            apy_pct=4.5,
            current_price_usd=1.0,
            redemption_delay_days=0.0,
            has_circuit_breaker=True,
            protocol_tvl_usd=2_000_000_000.0,
            days_since_depeg_event=0.0,
        )
        self.assertEqual(label, "GOLD_STANDARD")

    def test_label_avoid(self):
        label = self._label(
            yield_source="algo",
            collateral_ratio_pct=60.0,
            collateral_asset="ALGO",
            collateral_apy_pct=0.0,
            apy_pct=80.0,
            current_price_usd=0.85,
            redemption_delay_days=60.0,
            has_circuit_breaker=False,
            protocol_tvl_usd=1_000_000.0,
            days_since_depeg_event=15.0,
        )
        self.assertEqual(label, "AVOID")

    def test_label_is_valid_string(self):
        valid = {"GOLD_STANDARD", "SOUND", "MODERATE_RISK", "HIGH_RISK", "AVOID"}
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIn(r["risk_label"], valid)

    def test_all_labels_reachable(self):
        valid = {"GOLD_STANDARD", "SOUND", "MODERATE_RISK", "HIGH_RISK", "AVOID"}
        test_cases = [
            _base_input(yield_source="treasuries", collateral_ratio_pct=200.0,
                        collateral_asset="T-BILLS", collateral_apy_pct=5.5,
                        apy_pct=4.5, redemption_delay_days=0.0, has_circuit_breaker=True,
                        protocol_tvl_usd=2_000_000_000.0),
            _base_input(yield_source="lending", collateral_ratio_pct=130.0, apy_pct=5.0),
            _base_input(yield_source="staking", collateral_ratio_pct=110.0,
                        apy_pct=12.0, days_since_depeg_event=180.0),
            _base_input(yield_source="algo", collateral_ratio_pct=90.0,
                        apy_pct=30.0, days_since_depeg_event=60.0),
            _base_input(yield_source="algo", collateral_ratio_pct=60.0,
                        collateral_asset="ALGO", apy_pct=80.0, current_price_usd=0.85,
                        redemption_delay_days=60.0, has_circuit_breaker=False,
                        protocol_tvl_usd=1_000_000.0, days_since_depeg_event=15.0),
        ]
        seen = set()
        for tc in test_cases:
            r = self.az.analyze(tc, write_log=False)
            seen.add(r["risk_label"])
        self.assertTrue(seen.issubset(valid))
        self.assertGreaterEqual(len(seen), 3)

    def test_sound_category_example(self):
        label = self._label(yield_source="lending", collateral_ratio_pct=140.0,
                            apy_pct=6.0, collateral_apy_pct=6.5)
        valid = {"GOLD_STANDARD", "SOUND", "MODERATE_RISK"}
        self.assertIn(label, valid)

    def test_high_risk_example(self):
        label = self._label(
            yield_source="algo",
            collateral_ratio_pct=90.0,
            apy_pct=25.0,
            days_since_depeg_event=60.0,
            protocol_tvl_usd=5_000_000.0,
        )
        valid = {"HIGH_RISK", "AVOID", "MODERATE_RISK"}
        self.assertIn(label, valid)


# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def test_log_file_created(self):
        self.az.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        self.az.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_appended(self):
        for _ in range(3):
            self.az.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_entry_has_required_fields(self):
        self.az.analyze(_base_input(token_name="sDAI"), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("timestamp", entry)
        self.assertIn("composite_risk_score", entry)
        self.assertIn("risk_label", entry)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.az.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_no_log_when_write_log_false(self):
        self.az.analyze(_base_input(), write_log=False)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        self.assertFalse(os.path.exists(log_path))

    def test_log_token_name_recorded(self):
        self.az.analyze(_base_input(token_name="USDY"), write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["token_name"], "USDY")


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

class TestBatchAnalysis(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def test_batch_returns_list(self):
        results = self.az.analyze_batch([_base_input(), _base_input()], write_log=False)
        self.assertIsInstance(results, list)

    def test_batch_correct_count(self):
        inputs = [_base_input(token_name=f"T{i}") for i in range(6)]
        results = self.az.analyze_batch(inputs, write_log=False)
        self.assertEqual(len(results), 6)

    def test_batch_each_has_label(self):
        results = self.az.analyze_batch([_base_input(), _base_input()], write_log=False)
        for r in results:
            self.assertIn("risk_label", r)

    def test_batch_empty_input(self):
        results = self.az.analyze_batch([], write_log=False)
        self.assertEqual(results, [])

    def test_batch_log_written_once(self):
        inputs = [_base_input() for _ in range(5)]
        self.az.analyze_batch(inputs, write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_batch_log_has_batch_size(self):
        inputs = [_base_input() for _ in range(3)]
        self.az.analyze_batch(inputs, write_log=True)
        log_path = os.path.join(self.td, "yield_bearing_stablecoin_risk_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["batch_size"], 3)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def test_missing_all_fields_no_crash(self):
        r = self.az.analyze({}, write_log=False)
        self.assertIn("risk_label", r)

    def test_unknown_yield_source_no_crash(self):
        r = self.az.analyze(_base_input(yield_source="exotic"), write_log=False)
        self.assertIn("risk_label", r)

    def test_zero_collateral_ratio_no_crash(self):
        r = self.az.analyze(_base_input(collateral_ratio_pct=0.0), write_log=False)
        self.assertGreaterEqual(r["depeg_risk_score"], 0.0)

    def test_very_large_collateral_ratio(self):
        r = self.az.analyze(_base_input(collateral_ratio_pct=10000.0), write_log=False)
        self.assertLessEqual(r["collateral_adequacy_score"], 100.0)

    def test_zero_apy_no_crash(self):
        r = self.az.analyze(_base_input(apy_pct=0.0), write_log=False)
        self.assertIn("composite_risk_score", r)

    def test_very_large_apy(self):
        r = self.az.analyze(_base_input(apy_pct=500.0), write_log=False)
        self.assertLessEqual(r["yield_sustainability_score"], 100.0)

    def test_result_scores_are_floats(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIsInstance(r["depeg_risk_score"], float)
        self.assertIsInstance(r["yield_sustainability_score"], float)
        self.assertIsInstance(r["collateral_adequacy_score"], float)
        self.assertIsInstance(r["composite_risk_score"], float)

    def test_risk_label_is_string(self):
        r = self.az.analyze(_base_input(), write_log=False)
        self.assertIsInstance(r["risk_label"], str)

    def test_custom_data_dir_used(self):
        with tempfile.TemporaryDirectory() as custom_dir:
            az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=custom_dir)
            az.analyze(_base_input(), write_log=True)
            log_path = os.path.join(custom_dir, "yield_bearing_stablecoin_risk_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_zero_days_since_depeg_no_penalty(self):
        no_hist = self.az.analyze(_base_input(days_since_depeg_event=0.0), write_log=False)
        recent = self.az.analyze(_base_input(days_since_depeg_event=30.0), write_log=False)
        self.assertGreater(recent["depeg_risk_score"], no_hist["depeg_risk_score"])


# ---------------------------------------------------------------------------
# Integration / scenario tests
# ---------------------------------------------------------------------------

class TestIntegrationScenarios(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.az = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer(data_dir=self.td)

    def _r(self, **kw):
        return self.az.analyze(_base_input(**kw), write_log=False)

    def test_sdai_like_token_is_not_avoid(self):
        r = self._r(
            token_name="sDAI",
            yield_source="lending",
            collateral_ratio_pct=102.0,
            collateral_apy_pct=5.1,
            apy_pct=5.0,
            redemption_delay_days=0.0,
            has_circuit_breaker=True,
            protocol_tvl_usd=2_000_000_000.0,
        )
        self.assertNotEqual(r["risk_label"], "AVOID")

    def test_usdy_like_token_gold_or_sound(self):
        r = self._r(
            token_name="USDY",
            yield_source="treasuries",
            collateral_ratio_pct=102.0,
            collateral_asset="T-BILLS",
            collateral_apy_pct=5.3,
            apy_pct=5.2,
            redemption_delay_days=2.0,
            has_circuit_breaker=True,
            protocol_tvl_usd=500_000_000.0,
        )
        self.assertIn(r["risk_label"], {"GOLD_STANDARD", "SOUND"})

    def test_algo_depegged_token_is_avoid(self):
        r = self._r(
            token_name="AlgoStable",
            yield_source="algo",
            collateral_ratio_pct=70.0,
            collateral_asset="ALGO",
            collateral_apy_pct=0.0,
            apy_pct=80.0,
            current_price_usd=0.85,
            redemption_delay_days=60.0,
            has_circuit_breaker=False,
            protocol_tvl_usd=1_000_000.0,
            days_since_depeg_event=15.0,
        )
        self.assertEqual(r["risk_label"], "AVOID")

    def test_composite_monotone_with_risk_sources(self):
        safe = self._r(yield_source="treasuries", collateral_ratio_pct=200.0, apy_pct=4.0)
        risky = self._r(yield_source="algo", collateral_ratio_pct=70.0, apy_pct=50.0,
                        protocol_tvl_usd=1_000_000.0)
        self.assertGreater(risky["composite_risk_score"], safe["composite_risk_score"])

    def test_depeg_risk_ordering_by_yield_source(self):
        sources = ["treasuries", "lending", "staking", "algo"]
        scores = [
            self.az.analyze(_base_input(yield_source=s), write_log=False)["depeg_risk_score"]
            for s in sources
        ]
        # treasuries < lending < staking < algo is expected ordering
        self.assertLess(scores[0], scores[3])

    def test_redemption_delay_effect_on_adequacy(self):
        fast = self._r(redemption_delay_days=0.0)
        slow = self._r(redemption_delay_days=45.0)
        self.assertGreater(
            fast["collateral_adequacy_score"],
            slow["collateral_adequacy_score"]
        )

    def test_circuit_breaker_reduces_all_risk_dimensions(self):
        with_cb = self._r(has_circuit_breaker=True)
        no_cb = self._r(has_circuit_breaker=False)
        self.assertLess(with_cb["depeg_risk_score"], no_cb["depeg_risk_score"])
        self.assertGreater(with_cb["collateral_adequacy_score"], no_cb["collateral_adequacy_score"])
        self.assertGreater(with_cb["yield_sustainability_score"], no_cb["yield_sustainability_score"])

    def test_all_five_outputs_present_in_batch_results(self):
        results = self.az.analyze_batch([_base_input(), _base_input()], write_log=False)
        for r in results:
            self.assertIn("depeg_risk_score", r)
            self.assertIn("yield_sustainability_score", r)
            self.assertIn("collateral_adequacy_score", r)
            self.assertIn("composite_risk_score", r)
            self.assertIn("risk_label", r)


if __name__ == "__main__":
    unittest.main()
