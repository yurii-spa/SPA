#!/usr/bin/env python3
"""Тесты CompoundV3Adapter (spa_core.adapters) — MP-564.

Покрываем:
  TestInit           (14) — константы класса: protocol, tier, risk_score, tvl, peg_tolerance, etc.
  TestAPY            (14) — get_apy: fallback, JSON override, get_apy_pct, bool/str rejection
  TestPeg            (14) — is_peg_healthy: missing/1.0/in-range/boundary/depeg/non-numeric
  TestEligibility    (12) — eligible = peg OK + APY in [MIN, MAX]; все комбинации
  TestYieldInfo      (10) — get_yield_info: apy decimal, tier, risk_score, exit_latency, tvl
  TestAllocate       (10) — allocate: zero/negative raises, normal, cumulative, result keys
  TestSimDeposit     (10) — simulate_deposit: status ok, distinct keys, cumulative
  TestWithdraw       (10) — withdraw: zero/negative/over-balance raises, normal, remaining
  TestSimWithdraw    (10) — simulate_withdraw: error dict on insufficient, normal
  TestHealthCheck    (10) — health_check/get_health: status ok/degraded, keys
  TestToDict         ( 8) — to_dict: required keys, peg_healthy, eligible, protocol
  TestGapMethods     ( 9) — vs_morpho_gap, vs_aave_gap, is_better_than_aave
  TestRegistry       ( 7) — import, ADAPTER_REGISTRY, __all__, BaseAdapter subclass

Итого: 138 тестов.

Запуск:
    python3 -m unittest spa_core.tests.test_compound_v3_adapter -v
    python3 spa_core/tests/test_compound_v3_adapter.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.compound_v3_adapter import CompoundV3Adapter

_COMET = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_adapter(
    apy: float | None = 5.2,
    usdc_price: float | None = None,
    missing_section: bool = False,
    missing_file: bool = False,
) -> CompoundV3Adapter:
    """Создаёт адаптер с временным data_dir.

    apy=None          → поле apy отсутствует (тест fallback)
    usdc_price=None   → поле usdc_price отсутствует (peg считается healthy)
    missing_section   → секция compound_v3_adapter полностью отсутствует
    missing_file      → adapter_status.json не существует
    """
    if missing_file:
        return CompoundV3Adapter(data_dir="/nonexistent_spa_test_compound_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if usdc_price is not None:
            section["usdc_price"] = usdc_price
        content = {"compound_v3_adapter": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return CompoundV3Adapter(data_dir=tmp)


def _default() -> CompoundV3Adapter:
    """Адаптер с apy=5.2, без usdc_price (peg healthy, eligible)."""
    return _make_adapter(apy=5.2)


def _no_file() -> CompoundV3Adapter:
    return _make_adapter(missing_file=True)


def _no_section() -> CompoundV3Adapter:
    return _make_adapter(missing_section=True)


def _depeg(price: float) -> CompoundV3Adapter:
    return _make_adapter(apy=5.2, usdc_price=price)


# ─── TestInit ─────────────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):
    """14 тестов — константы и инициализация."""

    def setUp(self):
        self.a = _default()

    def test_protocol(self):
        self.assertEqual(self.a.PROTOCOL, "compound_v3")

    def test_tier_class(self):
        self.assertEqual(CompoundV3Adapter.TIER, "T1")

    def test_tier_instance(self):
        self.assertEqual(self.a.tier, "T1")

    def test_risk_score(self):
        self.assertAlmostEqual(CompoundV3Adapter.RISK_SCORE, 0.28)

    def test_tvl(self):
        self.assertEqual(CompoundV3Adapter.TVL_USD, 1_500_000_000)

    def test_default_apy(self):
        self.assertAlmostEqual(CompoundV3Adapter.DEFAULT_APY_PCT, 5.2)

    def test_peg_tolerance(self):
        self.assertAlmostEqual(CompoundV3Adapter.PEG_TOLERANCE, 0.005)

    def test_exit_latency(self):
        self.assertEqual(CompoundV3Adapter.EXIT_LATENCY_HOURS, 0.0)

    def test_t1_cap(self):
        self.assertAlmostEqual(CompoundV3Adapter.T1_CAP, 0.40)

    def test_comet_address(self):
        self.assertEqual(CompoundV3Adapter.COMET_ADDRESS, _COMET)

    def test_asset_default(self):
        self.assertEqual(self.a.asset, "USDC")

    def test_chain(self):
        self.assertEqual(CompoundV3Adapter.CHAIN, "ethereum")

    def test_chain_id(self):
        self.assertEqual(CompoundV3Adapter.CHAIN_ID, 1)

    def test_allocated_starts_zero(self):
        self.assertEqual(self.a._allocated, 0.0)


# ─── TestAPY ─────────────────────────────────────────────────────────────────

class TestAPY(unittest.TestCase):
    """14 тестов — get_apy, fallback, JSON override."""

    def test_no_live_data_no_file_returns_none(self):
        # N2: no live feed → honest None, NEVER a fabricated 5.2% (go-live track honesty).
        a = _no_file()
        self.assertIsNone(a.get_apy())

    def test_no_live_data_no_section_returns_none(self):
        a = _no_section()
        self.assertIsNone(a.get_apy())

    def test_no_live_data_no_apy_field_returns_none(self):
        a = _make_adapter(apy=None)
        self.assertIsNone(a.get_apy())

    def test_json_override(self):
        a = _make_adapter(apy=4.8)
        self.assertAlmostEqual(a.get_apy(), 4.8)

    def test_json_override_high(self):
        a = _make_adapter(apy=9.9)
        self.assertAlmostEqual(a.get_apy(), 9.9)

    def test_json_override_low(self):
        a = _make_adapter(apy=1.5)
        self.assertAlmostEqual(a.get_apy(), 1.5)

    def test_get_apy_pct_equals_get_apy(self):
        a = _default()
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_returns_float(self):
        a = _default()
        self.assertIsInstance(a.get_apy(), float)

    def test_bool_apy_ignored(self):
        """bool=True is subclass of int but should be rejected."""
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"apy": True}}), encoding="utf-8"
        )
        a = CompoundV3Adapter(data_dir=tmp)
        self.assertIsNone(a.get_apy())  # N2: invalid → no live data, not fabricated

    def test_string_apy_ignored(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"apy": "5.2"}}), encoding="utf-8"
        )
        a = CompoundV3Adapter(data_dir=tmp)
        self.assertIsNone(a.get_apy())  # N2: invalid → no live data, not fabricated

    def test_zero_apy_accepted(self):
        a = _make_adapter(apy=0.0)
        self.assertAlmostEqual(a.get_apy(), 0.0)

    def test_negative_apy_accepted(self):
        # Adapter reads raw value; eligibility filter is in is_eligible / RiskPolicy
        a = _make_adapter(apy=-1.0)
        self.assertAlmostEqual(a.get_apy(), -1.0)

    def test_integer_apy_converted_to_float(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"apy": 5}}), encoding="utf-8"
        )
        a = CompoundV3Adapter(data_dir=tmp)
        result = a.get_apy()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 5.0)

    def test_apy_fallback_alias(self):
        self.assertAlmostEqual(CompoundV3Adapter.APY_FALLBACK, 5.2)


# ─── TestPeg ─────────────────────────────────────────────────────────────────

class TestPeg(unittest.TestCase):
    """14 тестов — is_peg_healthy."""

    def test_missing_price_is_healthy(self):
        a = _make_adapter(usdc_price=None)
        self.assertTrue(a.is_peg_healthy())

    def test_price_1_0_healthy(self):
        a = _depeg(1.0)
        self.assertTrue(a.is_peg_healthy())

    def test_price_slightly_above_healthy(self):
        a = _depeg(1.001)
        self.assertTrue(a.is_peg_healthy())

    def test_price_slightly_below_healthy(self):
        a = _depeg(0.999)
        self.assertTrue(a.is_peg_healthy())

    def test_exactly_at_tolerance_healthy(self):
        # 1.0 + 0.005 = 1.005 — on the boundary → healthy
        a = _depeg(1.005)
        self.assertTrue(a.is_peg_healthy())

    def test_exactly_at_tolerance_below_healthy(self):
        a = _depeg(0.995)
        self.assertTrue(a.is_peg_healthy())

    def test_just_above_tolerance_unhealthy(self):
        a = _depeg(1.0051)
        self.assertFalse(a.is_peg_healthy())

    def test_just_below_tolerance_unhealthy(self):
        a = _depeg(0.9949)
        self.assertFalse(a.is_peg_healthy())

    def test_severe_depeg_above(self):
        a = _depeg(1.10)
        self.assertFalse(a.is_peg_healthy())

    def test_severe_depeg_below(self):
        a = _depeg(0.90)
        self.assertFalse(a.is_peg_healthy())

    def test_string_price_treated_as_healthy(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"usdc_price": "0.90"}}), encoding="utf-8"
        )
        a = CompoundV3Adapter(data_dir=tmp)
        self.assertTrue(a.is_peg_healthy())

    def test_bool_price_treated_as_healthy(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"usdc_price": False}}), encoding="utf-8"
        )
        a = CompoundV3Adapter(data_dir=tmp)
        self.assertTrue(a.is_peg_healthy())

    def test_missing_section_peg_healthy(self):
        a = _no_section()
        self.assertTrue(a.is_peg_healthy())

    def test_missing_file_peg_healthy(self):
        a = _no_file()
        self.assertTrue(a.is_peg_healthy())


# ─── TestEligibility ─────────────────────────────────────────────────────────

class TestEligibility(unittest.TestCase):
    """12 тестов — is_eligible = peg OK + APY in [MIN, MAX]."""

    def test_default_eligible(self):
        a = _default()
        self.assertTrue(a.is_eligible())

    def test_depeg_not_eligible(self):
        a = _make_adapter(apy=5.2, usdc_price=0.90)
        self.assertFalse(a.is_eligible())

    def test_apy_at_min_boundary_eligible(self):
        a = _make_adapter(apy=CompoundV3Adapter.MIN_APY_PCT)
        self.assertTrue(a.is_eligible())

    def test_apy_at_max_boundary_eligible(self):
        a = _make_adapter(apy=CompoundV3Adapter.MAX_APY_PCT)
        self.assertTrue(a.is_eligible())

    def test_apy_below_min_not_eligible(self):
        a = _make_adapter(apy=0.5)
        self.assertFalse(a.is_eligible())

    def test_apy_above_max_not_eligible(self):
        a = _make_adapter(apy=31.0)
        self.assertFalse(a.is_eligible())

    def test_no_live_data_not_eligible(self):
        # N2: no live APY → fail-closed, NOT eligible (no allocating on a fabricated yield).
        a = _no_file()
        self.assertFalse(a.is_eligible())

    def test_peg_depeg_overrides_valid_apy(self):
        a = _make_adapter(apy=10.0, usdc_price=1.10)
        self.assertFalse(a.is_eligible())

    def test_zero_apy_not_eligible(self):
        a = _make_adapter(apy=0.0)
        self.assertFalse(a.is_eligible())

    def test_negative_apy_not_eligible(self):
        a = _make_adapter(apy=-1.0)
        self.assertFalse(a.is_eligible())

    def test_borderline_depeg_not_eligible(self):
        a = _make_adapter(apy=5.2, usdc_price=0.994)
        self.assertFalse(a.is_eligible())

    def test_returns_bool(self):
        a = _default()
        self.assertIsInstance(a.is_eligible(), bool)


# ─── TestYieldInfo ─────────────────────────────────────────────────────────────

class TestYieldInfo(unittest.TestCase):
    """10 тестов — get_yield_info."""

    def setUp(self):
        self.a = _default()
        self.yi = self.a.get_yield_info()

    def test_returns_yield_info(self):
        self.assertIsInstance(self.yi, YieldInfo)

    def test_apy_is_decimal(self):
        # 5.2% → 0.052
        self.assertAlmostEqual(self.yi.apy, 0.052, places=6)

    def test_apy_decimal_override(self):
        a = _make_adapter(apy=4.8)
        yi = a.get_yield_info()
        self.assertAlmostEqual(yi.apy, 0.048, places=6)

    def test_protocol(self):
        self.assertEqual(self.yi.protocol, "compound_v3")

    def test_asset(self):
        self.assertEqual(self.yi.asset, "USDC")

    def test_tier(self):
        self.assertEqual(self.yi.tier, "T1")

    def test_risk_score(self):
        self.assertAlmostEqual(self.yi.risk_score, 0.28)

    def test_tvl(self):
        self.assertAlmostEqual(self.yi.tvl_usd, 1_500_000_000.0)

    def test_exit_latency(self):
        self.assertEqual(self.yi.exit_latency_hours, 0.0)

    def test_apy_none_when_no_live_data(self):
        # N2: YieldInfo.apy is None when no live feed — orchestrator marks no-live-data.
        a = _no_file()
        yi = a.get_yield_info()
        self.assertIsNone(yi.apy)


# ─── TestAllocate ─────────────────────────────────────────────────────────────

class TestAllocate(unittest.TestCase):
    """10 тестов — allocate()."""

    def setUp(self):
        self.a = _default()

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            self.a.allocate(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.a.allocate(-100)

    def test_normal_status(self):
        r = self.a.allocate(10_000)
        self.assertEqual(r["status"], "allocated")

    def test_normal_protocol(self):
        r = self.a.allocate(10_000)
        self.assertEqual(r["protocol"], "compound_v3")

    def test_capital_returned(self):
        r = self.a.allocate(10_000)
        self.assertAlmostEqual(r["capital_usd"], 10_000)

    def test_cumulative_total(self):
        self.a.allocate(10_000)
        self.a.allocate(5_000)
        self.assertAlmostEqual(self.a._allocated, 15_000)

    def test_total_allocated_in_result(self):
        self.a.allocate(10_000)
        r = self.a.allocate(5_000)
        self.assertAlmostEqual(r["total_allocated_usd"], 15_000)

    def test_annual_yield_computed(self):
        r = self.a.allocate(100_000)
        expected = 100_000 * (5.2 / 100)
        self.assertAlmostEqual(r["annual_yield_usd"], expected, places=2)

    def test_comet_address_in_result(self):
        r = self.a.allocate(1_000)
        self.assertEqual(r["comet_address"], _COMET)

    def test_has_ts(self):
        r = self.a.allocate(1_000)
        self.assertIn("ts", r)
        self.assertIsInstance(r["ts"], float)


# ─── TestSimDeposit ───────────────────────────────────────────────────────────

class TestSimDeposit(unittest.TestCase):
    """10 тестов — simulate_deposit()."""

    def setUp(self):
        self.a = _default()

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            self.a.simulate_deposit(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.a.simulate_deposit(-1)

    def test_status_ok(self):
        r = self.a.simulate_deposit(5_000)
        self.assertEqual(r["status"], "ok")

    def test_protocol_key(self):
        r = self.a.simulate_deposit(5_000)
        self.assertEqual(r["protocol"], "compound_v3")

    def test_amount_returned(self):
        r = self.a.simulate_deposit(5_000)
        self.assertAlmostEqual(r["amount_usd"], 5_000)

    def test_allocated_total(self):
        self.a.simulate_deposit(3_000)
        r = self.a.simulate_deposit(2_000)
        self.assertAlmostEqual(r["allocated_total_usd"], 5_000)

    def test_annual_yield(self):
        r = self.a.simulate_deposit(50_000)
        expected = 50_000 * (5.2 / 100)
        self.assertAlmostEqual(r["annual_yield_usd"], expected, places=2)

    def test_apy_pct_in_result(self):
        r = self.a.simulate_deposit(1_000)
        self.assertAlmostEqual(r["apy_pct"], 5.2)

    def test_comet_address_in_result(self):
        r = self.a.simulate_deposit(1_000)
        self.assertEqual(r["comet_address"], _COMET)

    def test_has_ts(self):
        r = self.a.simulate_deposit(1_000)
        self.assertIn("ts", r)


# ─── TestWithdraw ─────────────────────────────────────────────────────────────

class TestWithdraw(unittest.TestCase):
    """10 тестов — withdraw()."""

    def setUp(self):
        self.a = _default()
        self.a.allocate(20_000)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            self.a.withdraw(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.a.withdraw(-100)

    def test_over_balance_raises(self):
        with self.assertRaises(ValueError):
            self.a.withdraw(30_000)

    def test_normal_status(self):
        r = self.a.withdraw(5_000)
        self.assertEqual(r["status"], "withdrawn")

    def test_amount_returned(self):
        r = self.a.withdraw(5_000)
        self.assertAlmostEqual(r["amount_usd"], 5_000)

    def test_remaining_balance(self):
        self.a.withdraw(5_000)
        self.assertAlmostEqual(self.a._allocated, 15_000)

    def test_remaining_in_result(self):
        r = self.a.withdraw(8_000)
        self.assertAlmostEqual(r["remaining_allocated_usd"], 12_000)

    def test_comet_address_in_result(self):
        r = self.a.withdraw(1_000)
        self.assertEqual(r["comet_address"], _COMET)

    def test_exit_latency_in_result(self):
        r = self.a.withdraw(1_000)
        self.assertEqual(r["exit_latency_hours"], 0.0)

    def test_full_withdrawal_zeroes_balance(self):
        self.a.withdraw(20_000)
        self.assertAlmostEqual(self.a._allocated, 0.0)


# ─── TestSimWithdraw ─────────────────────────────────────────────────────────

class TestSimWithdraw(unittest.TestCase):
    """10 тестов — simulate_withdraw() (error-dict on insufficient)."""

    def setUp(self):
        self.a = _default()
        self.a.simulate_deposit(20_000)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            self.a.simulate_withdraw(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.a.simulate_withdraw(-1)

    def test_insufficient_returns_error(self):
        r = self.a.simulate_withdraw(30_000)
        self.assertEqual(r["status"], "error")

    def test_insufficient_reason(self):
        r = self.a.simulate_withdraw(30_000)
        self.assertEqual(r["reason"], "insufficient_balance")

    def test_insufficient_requested(self):
        r = self.a.simulate_withdraw(30_000)
        self.assertAlmostEqual(r["requested"], 30_000)

    def test_insufficient_available(self):
        r = self.a.simulate_withdraw(30_000)
        self.assertAlmostEqual(r["available"], 20_000)

    def test_normal_status_ok(self):
        r = self.a.simulate_withdraw(5_000)
        self.assertEqual(r["status"], "ok")

    def test_normal_amount_returned(self):
        r = self.a.simulate_withdraw(5_000)
        self.assertAlmostEqual(r["amount_usd"], 5_000)

    def test_normal_remaining(self):
        self.a.simulate_withdraw(5_000)
        self.assertAlmostEqual(self.a._allocated, 15_000)

    def test_full_withdrawal_ok(self):
        r = self.a.simulate_withdraw(20_000)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(self.a._allocated, 0.0)


# ─── TestHealthCheck ─────────────────────────────────────────────────────────

class TestHealthCheck(unittest.TestCase):
    """10 тестов — health_check() and get_health()."""

    def test_ok_for_normal_apy(self):
        a = _default()
        h = a.health_check()
        self.assertEqual(h["status"], "ok")

    def test_degraded_for_zero_apy(self):
        a = _make_adapter(apy=0.0)
        h = a.health_check()
        self.assertEqual(h["status"], "degraded")

    def test_degraded_for_high_apy(self):
        a = _make_adapter(apy=31.0)
        h = a.health_check()
        self.assertEqual(h["status"], "degraded")

    def test_protocol_key(self):
        a = _default()
        h = a.health_check()
        self.assertEqual(h["protocol"], "compound_v3")

    def test_apy_in_result(self):
        a = _default()
        h = a.health_check()
        self.assertAlmostEqual(h["apy_pct"], 5.2)

    def test_tvl_floor_ok(self):
        a = _default()
        h = a.health_check()
        self.assertTrue(h["tvl_floor_ok"])

    def test_apy_range_present(self):
        a = _default()
        h = a.health_check()
        self.assertIn("apy_range", h)
        self.assertEqual(len(h["apy_range"]), 2)

    def test_peg_healthy_in_result(self):
        a = _default()
        h = a.health_check()
        self.assertIn("peg_healthy", h)
        self.assertTrue(h["peg_healthy"])

    def test_get_health_alias(self):
        a = _default()
        self.assertEqual(a.get_health(), a.health_check())

    def test_apy_source_fallback(self):
        a = _no_file()
        h = a.health_check()
        self.assertEqual(h["apy_source"], "fallback")


# ─── TestToDict ──────────────────────────────────────────────────────────────

class TestToDict(unittest.TestCase):
    """8 тестов — to_dict()."""

    def setUp(self):
        self.a = _default()
        self.d = self.a.to_dict()

    def test_protocol(self):
        self.assertEqual(self.d["protocol"], "compound_v3")

    def test_tier(self):
        self.assertEqual(self.d["tier"], "T1")

    def test_peg_healthy_present(self):
        self.assertIn("peg_healthy", self.d)
        self.assertTrue(self.d["peg_healthy"])

    def test_eligible_present(self):
        self.assertIn("eligible", self.d)
        self.assertTrue(self.d["eligible"])

    def test_apy_pct(self):
        self.assertAlmostEqual(self.d["apy_pct"], 5.2)

    def test_risk_score(self):
        self.assertAlmostEqual(self.d["risk_score"], 0.28)

    def test_comet_address(self):
        self.assertEqual(self.d["comet_address"], _COMET)

    def test_strategy_note_present(self):
        self.assertIn("strategy_note", self.d)
        self.assertIsInstance(self.d["strategy_note"], str)


# ─── TestGapMethods ──────────────────────────────────────────────────────────

class TestGapMethods(unittest.TestCase):
    """9 тестов — vs_morpho_gap, vs_aave_gap, is_better_than_aave."""

    def test_vs_morpho_positive_when_morpho_higher(self):
        a = _make_adapter(apy=5.0)
        gap = a.vs_morpho_gap(morpho_apy=6.5)
        self.assertGreater(gap, 0)
        self.assertAlmostEqual(gap, 1.5, places=4)

    def test_vs_morpho_negative_when_compound_higher(self):
        a = _make_adapter(apy=8.0)
        gap = a.vs_morpho_gap(morpho_apy=6.5)
        self.assertLess(gap, 0)

    def test_vs_morpho_zero_equal(self):
        a = _make_adapter(apy=6.5)
        gap = a.vs_morpho_gap(morpho_apy=6.5)
        self.assertAlmostEqual(gap, 0.0, places=6)

    def test_vs_aave_positive_when_compound_higher(self):
        a = _make_adapter(apy=5.2)
        gap = a.vs_aave_gap(aave_apy=4.2)
        self.assertGreater(gap, 0)
        self.assertAlmostEqual(gap, 1.0, places=4)

    def test_vs_aave_negative_when_aave_higher(self):
        a = _make_adapter(apy=3.5)
        gap = a.vs_aave_gap(aave_apy=4.2)
        self.assertLess(gap, 0)

    def test_is_better_than_aave_true(self):
        a = _make_adapter(apy=5.2)
        self.assertTrue(a.is_better_than_aave(aave_apy=4.2))

    def test_is_better_than_aave_false_equal(self):
        a = _make_adapter(apy=4.2)
        self.assertFalse(a.is_better_than_aave(aave_apy=4.2))

    def test_is_better_than_aave_false_less(self):
        a = _make_adapter(apy=3.5)
        self.assertFalse(a.is_better_than_aave(aave_apy=4.2))

    def test_vs_morpho_fallback_no_file(self):
        a = _no_file()
        # Fallback morpho = 6.5, compound = 5.2 → gap = 1.3
        gap = a.vs_morpho_gap()
        self.assertAlmostEqual(gap, 1.3, places=4)


# ─── TestRegistry ─────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    """7 тестов — import, ADAPTER_REGISTRY, BaseAdapter subclass."""

    def test_is_base_adapter_subclass(self):
        self.assertTrue(issubclass(CompoundV3Adapter, BaseAdapter))

    def test_instance_is_base_adapter(self):
        a = _default()
        self.assertIsInstance(a, BaseAdapter)

    def test_in_adapter_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, t, c in ADAPTER_REGISTRY if c is CompoundV3Adapter]
        self.assertIn("compound_v3", keys)

    def test_registry_tier_t1(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for k, t, c in ADAPTER_REGISTRY:
            if c is CompoundV3Adapter:
                self.assertEqual(t, "T1")

    def test_in_all(self):
        from spa_core.adapters import __all__
        self.assertIn("CompoundV3Adapter", __all__)

    def test_importable_from_package(self):
        from spa_core.adapters import CompoundV3Adapter as C
        self.assertIs(C, CompoundV3Adapter)

    def test_module_path(self):
        import spa_core.adapters.compound_v3_adapter as mod
        self.assertTrue(hasattr(mod, "CompoundV3Adapter"))


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
