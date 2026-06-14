#!/usr/bin/env python3
"""Тесты AaveV3PolygonAdapter (spa_core.adapters) — MP-593.

Покрываем:
  TestInit               (15) — константы класса: protocol, tier, risk_score, tvl, chain, etc.
  TestAPY                (14) — get_apy: fallback, JSON override, apy_pct alias, rejection
  TestPeg                (13) — is_peg_healthy: missing/1.0/in-range/boundary/depeg/non-numeric
  TestEligibility        (12) — eligible = peg OK + APY in [MIN, MAX]; все комбинации
  TestYieldInfo          (10) — get_yield_info: apy decimal, tier, risk_score, exit_latency, tvl
  TestSimulateDeposit    (10) — simulate_deposit: zero/negative raises, normal, cumulative, keys
  TestSimulateWithdraw   (10) — simulate_withdraw: error dict on insufficient, normal, keys
  TestAllocate           (10) — allocate: zero/negative raises, cumulative, result keys
  TestWithdraw            (9) — withdraw: zero/negative/over raises, normal, remaining
  TestGetHealth          (11) — get_health: status ok/degraded, required keys, sources
  TestToDict             (10) — to_dict: required keys, peg_healthy, eligible, chain, l2
  TestGasSavings          (9) — get_gas_savings_vs_mainnet: shape, values, chain, immutability
  TestBridgeRisk          (5) — get_bridge_risk_note: non-empty, mentions USDC.e/bridged
  TestRegistry            (2) — ADAPTER_REGISTRY содержит aave_v3_polygon T1

Итого: 140 тестов (≥ 130, все зелёные).

Запуск:
    python3 -m unittest spa_core.tests.test_aave_v3_polygon_adapter -v
    python3 spa_core/tests/test_aave_v3_polygon_adapter.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.aave_v3_polygon_adapter import AaveV3PolygonAdapter

_POOL      = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
_USDC_POLY = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_adapter(
    apy: "float | None" = 5.1,
    usdc_price: "float | None" = None,
    missing_section: bool = False,
    missing_file: bool = False,
) -> AaveV3PolygonAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None          → поле apy отсутствует → fallback
    usdc_price=None   → поле usdc_price отсутствует → peg healthy (default-safe)
    missing_section   → секция aave_v3_polygon полностью отсутствует
    missing_file      → adapter_status.json не существует
    """
    if missing_file:
        return AaveV3PolygonAdapter(data_dir="/nonexistent_spa_test_poly_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if usdc_price is not None:
            section["usdc_price"] = usdc_price
        content = {"aave_v3_polygon": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return AaveV3PolygonAdapter(data_dir=tmp)


def _default() -> AaveV3PolygonAdapter:
    """Адаптер с apy=5.1, без usdc_price (peg healthy, eligible)."""
    return _make_adapter(apy=5.1)


def _no_file() -> AaveV3PolygonAdapter:
    return _make_adapter(missing_file=True)


def _no_section() -> AaveV3PolygonAdapter:
    return _make_adapter(missing_section=True)


def _depeg(price: float) -> AaveV3PolygonAdapter:
    return _make_adapter(apy=5.1, usdc_price=price)


# ─── TestInit ─────────────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):
    """15 тестов — константы и инициализация."""

    def setUp(self):
        self.a = _default()

    def test_protocol(self):
        self.assertEqual(self.a.PROTOCOL, "aave_v3_polygon")

    def test_tier_class(self):
        self.assertEqual(AaveV3PolygonAdapter.TIER, "T1")

    def test_tier_instance(self):
        self.assertEqual(self.a.tier, "T1")

    def test_risk_score(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.RISK_SCORE, 0.27)

    def test_tvl(self):
        self.assertEqual(AaveV3PolygonAdapter.TVL_USD, 800_000_000)

    def test_default_apy(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.DEFAULT_APY_PCT, 5.1)

    def test_peg_tolerance(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.PEG_TOLERANCE, 0.005)

    def test_exit_latency(self):
        self.assertEqual(AaveV3PolygonAdapter.EXIT_LATENCY_HOURS, 0.0)

    def test_t1_cap(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.T1_CAP, 0.40)

    def test_pool_address(self):
        self.assertEqual(AaveV3PolygonAdapter.POOL_ADDRESS, _POOL)

    def test_usdc_address(self):
        self.assertEqual(AaveV3PolygonAdapter.USDC_ADDRESS, _USDC_POLY)

    def test_chain(self):
        self.assertEqual(AaveV3PolygonAdapter.CHAIN, "polygon")

    def test_chain_id(self):
        self.assertEqual(AaveV3PolygonAdapter.CHAIN_ID, 137)

    def test_asset_default(self):
        self.assertEqual(self.a.asset, "USDC")

    def test_allocated_starts_zero(self):
        self.assertEqual(self.a._allocated, 0.0)


# ─── TestAPY ─────────────────────────────────────────────────────────────────

class TestAPY(unittest.TestCase):
    """14 тестов — get_apy, fallback, JSON override."""

    def test_fallback_no_file(self):
        self.assertAlmostEqual(_no_file().get_apy(), 5.1)

    def test_fallback_no_section(self):
        self.assertAlmostEqual(_no_section().get_apy(), 5.1)

    def test_fallback_no_apy_field(self):
        self.assertAlmostEqual(_make_adapter(apy=None).get_apy(), 5.1)

    def test_json_override(self):
        self.assertAlmostEqual(_make_adapter(apy=6.0).get_apy(), 6.0)

    def test_json_override_high(self):
        self.assertAlmostEqual(_make_adapter(apy=10.5).get_apy(), 10.5)

    def test_json_override_low(self):
        self.assertAlmostEqual(_make_adapter(apy=1.5).get_apy(), 1.5)

    def test_get_apy_pct_equals_get_apy(self):
        a = _default()
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_returns_float(self):
        self.assertIsInstance(_default().get_apy(), float)

    def test_bool_apy_ignored(self):
        """bool subclass of int — должен быть отклонён как невалидный APY."""
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"aave_v3_polygon": {"apy": True}}), encoding="utf-8"
        )
        a = AaveV3PolygonAdapter(data_dir=tmp)
        self.assertAlmostEqual(a.get_apy(), 5.1)  # fallback

    def test_string_apy_ignored(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"aave_v3_polygon": {"apy": "5.1"}}), encoding="utf-8"
        )
        a = AaveV3PolygonAdapter(data_dir=tmp)
        self.assertAlmostEqual(a.get_apy(), 5.1)  # fallback

    def test_zero_apy_accepted(self):
        self.assertAlmostEqual(_make_adapter(apy=0.0).get_apy(), 0.0)

    def test_apy_fallback_alias_matches(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.APY_FALLBACK,
                               AaveV3PolygonAdapter.DEFAULT_APY_PCT)

    def test_min_apy_pct(self):
        self.assertAlmostEqual(AaveV3PolygonAdapter.MIN_APY_PCT, 1.0)

    def test_corrupted_json_uses_fallback(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text("NOT JSON", encoding="utf-8")
        a = AaveV3PolygonAdapter(data_dir=tmp)
        self.assertAlmostEqual(a.get_apy(), 5.1)


# ─── TestPeg ─────────────────────────────────────────────────────────────────

class TestPeg(unittest.TestCase):
    """13 тестов — is_peg_healthy."""

    def test_missing_price_is_healthy(self):
        """Отсутствие usdc_price → default-safe → healthy."""
        self.assertTrue(_default().is_peg_healthy())

    def test_exactly_1_0_healthy(self):
        self.assertTrue(_depeg(1.0).is_peg_healthy())

    def test_price_0_995_healthy(self):
        self.assertTrue(_depeg(0.995).is_peg_healthy())

    def test_price_1_005_healthy(self):
        self.assertTrue(_depeg(1.005).is_peg_healthy())

    def test_price_0_994_depeg(self):
        self.assertFalse(_depeg(0.994).is_peg_healthy())

    def test_price_1_006_depeg(self):
        self.assertFalse(_depeg(1.006).is_peg_healthy())

    def test_price_0_90_depeg(self):
        self.assertFalse(_depeg(0.90).is_peg_healthy())

    def test_price_1_10_depeg(self):
        self.assertFalse(_depeg(1.10).is_peg_healthy())

    def test_string_price_treated_healthy(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"aave_v3_polygon": {"usdc_price": "0.90"}}),
            encoding="utf-8",
        )
        self.assertTrue(AaveV3PolygonAdapter(data_dir=tmp).is_peg_healthy())

    def test_bool_price_treated_healthy(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps({"aave_v3_polygon": {"usdc_price": False}}),
            encoding="utf-8",
        )
        self.assertTrue(AaveV3PolygonAdapter(data_dir=tmp).is_peg_healthy())

    def test_no_section_healthy(self):
        self.assertTrue(_no_section().is_peg_healthy())

    def test_no_file_healthy(self):
        self.assertTrue(_no_file().is_peg_healthy())

    def test_boundary_lower_just_outside(self):
        """0.9949 < 0.995 → отклонение 0.0051 > 0.005 → depeg."""
        self.assertFalse(_depeg(0.9949).is_peg_healthy())


# ─── TestEligibility ─────────────────────────────────────────────────────────

class TestEligibility(unittest.TestCase):
    """12 тестов — is_eligible."""

    def test_default_eligible(self):
        self.assertTrue(_default().is_eligible())

    def test_depeg_not_eligible(self):
        self.assertFalse(_depeg(0.90).is_eligible())

    def test_depeg_overrides_good_apy(self):
        a = _make_adapter(apy=5.1, usdc_price=0.90)
        self.assertFalse(a.is_eligible())

    def test_apy_below_min_not_eligible(self):
        a = _make_adapter(apy=0.5)
        self.assertFalse(a.is_eligible())

    def test_apy_above_max_not_eligible(self):
        a = _make_adapter(apy=31.0)
        self.assertFalse(a.is_eligible())

    def test_apy_at_min_eligible(self):
        self.assertTrue(_make_adapter(apy=1.0).is_eligible())

    def test_apy_at_max_eligible(self):
        self.assertTrue(_make_adapter(apy=30.0).is_eligible())

    def test_apy_zero_not_eligible(self):
        self.assertFalse(_make_adapter(apy=0.0).is_eligible())

    def test_good_peg_good_apy_eligible(self):
        a = _make_adapter(apy=5.1, usdc_price=1.001)
        self.assertTrue(a.is_eligible())

    def test_borderline_depeg_not_eligible(self):
        a = _make_adapter(apy=5.1, usdc_price=0.994)
        self.assertFalse(a.is_eligible())

    def test_no_file_uses_fallback_eligible(self):
        """Без файла → apy=5.1 (fallback), peg=True → eligible."""
        self.assertTrue(_no_file().is_eligible())

    def test_eligible_true_means_both_conditions(self):
        a = _default()
        self.assertTrue(a.is_peg_healthy())
        self.assertTrue(a.MIN_APY_PCT <= a.get_apy() <= a.MAX_APY_PCT)
        self.assertTrue(a.is_eligible())


# ─── TestYieldInfo ────────────────────────────────────────────────────────────

class TestYieldInfo(unittest.TestCase):
    """10 тестов — get_yield_info."""

    def setUp(self):
        self.yi = _default().get_yield_info()

    def test_returns_yield_info_instance(self):
        self.assertIsInstance(self.yi, YieldInfo)

    def test_protocol_key(self):
        self.assertEqual(self.yi.protocol, "aave_v3_polygon")

    def test_asset(self):
        self.assertEqual(self.yi.asset, "USDC")

    def test_apy_is_decimal(self):
        """YieldInfo.apy должен быть десятичной дробью (0.051 для 5.1%)."""
        self.assertAlmostEqual(self.yi.apy, 0.051)

    def test_apy_decimal_range(self):
        self.assertGreater(self.yi.apy, 0)
        self.assertLess(self.yi.apy, 1)

    def test_tvl_matches_constant(self):
        self.assertAlmostEqual(self.yi.tvl_usd, 800_000_000)

    def test_tier_is_t1(self):
        self.assertEqual(self.yi.tier, "T1")

    def test_risk_score(self):
        self.assertAlmostEqual(self.yi.risk_score, 0.27)

    def test_exit_latency(self):
        self.assertEqual(self.yi.exit_latency_hours, 0.0)

    def test_json_override_reflected_in_yield_info(self):
        a = _make_adapter(apy=6.0)
        yi = a.get_yield_info()
        self.assertAlmostEqual(yi.apy, 0.06)


# ─── TestSimulateDeposit ──────────────────────────────────────────────────────

class TestSimulateDeposit(unittest.TestCase):
    """10 тестов — simulate_deposit."""

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _default().simulate_deposit(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _default().simulate_deposit(-100)

    def test_status_ok(self):
        r = _default().simulate_deposit(1000)
        self.assertEqual(r["status"], "ok")

    def test_protocol_key(self):
        r = _default().simulate_deposit(1000)
        self.assertEqual(r["protocol"], "aave_v3_polygon")

    def test_amount_usd_in_result(self):
        r = _default().simulate_deposit(5000)
        self.assertAlmostEqual(r["amount_usd"], 5000)

    def test_allocated_total_updated(self):
        a = _default()
        a.simulate_deposit(3000)
        r = a.simulate_deposit(2000)
        self.assertAlmostEqual(r["allocated_total_usd"], 5000)

    def test_annual_yield_computed(self):
        a = _default()
        r = a.simulate_deposit(10000)
        expected = round(10000 * 0.051, 4)
        self.assertAlmostEqual(r["annual_yield_usd"], expected)

    def test_chain_in_result(self):
        r = _default().simulate_deposit(1000)
        self.assertEqual(r["chain"], "polygon")

    def test_pool_address_in_result(self):
        r = _default().simulate_deposit(1000)
        self.assertEqual(r["pool_address"], _POOL)

    def test_ts_present(self):
        r = _default().simulate_deposit(1000)
        self.assertIn("ts", r)


# ─── TestSimulateWithdraw ─────────────────────────────────────────────────────

class TestSimulateWithdraw(unittest.TestCase):
    """10 тестов — simulate_withdraw."""

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _default().simulate_withdraw(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _default().simulate_withdraw(-50)

    def test_insufficient_returns_error_dict(self):
        a = _default()
        r = a.simulate_withdraw(1000)
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["reason"], "insufficient_balance")

    def test_insufficient_includes_requested(self):
        a = _default()
        r = a.simulate_withdraw(500)
        self.assertAlmostEqual(r["requested"], 500)

    def test_insufficient_available_is_zero(self):
        a = _default()
        r = a.simulate_withdraw(100)
        self.assertAlmostEqual(r["available"], 0.0)

    def test_normal_withdraw_status_ok(self):
        a = _default()
        a.simulate_deposit(5000)
        r = a.simulate_withdraw(2000)
        self.assertEqual(r["status"], "ok")

    def test_normal_withdraw_remaining(self):
        a = _default()
        a.simulate_deposit(5000)
        r = a.simulate_withdraw(2000)
        self.assertAlmostEqual(r["allocated_remaining"], 3000)

    def test_protocol_key_in_result(self):
        a = _default()
        a.simulate_deposit(1000)
        r = a.simulate_withdraw(500)
        self.assertEqual(r["protocol"], "aave_v3_polygon")

    def test_exit_latency_in_ok_result(self):
        a = _default()
        a.simulate_deposit(1000)
        r = a.simulate_withdraw(500)
        self.assertEqual(r["exit_latency_hours"], 0.0)

    def test_full_withdrawal_leaves_zero(self):
        a = _default()
        a.simulate_deposit(1000)
        r = a.simulate_withdraw(1000)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["allocated_remaining"], 0.0)


# ─── TestAllocate ─────────────────────────────────────────────────────────────

class TestAllocate(unittest.TestCase):
    """10 тестов — allocate (backward-compat alias)."""

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _default().allocate(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _default().allocate(-1)

    def test_status_allocated(self):
        r = _default().allocate(1000)
        self.assertEqual(r["status"], "allocated")

    def test_capital_usd_key(self):
        r = _default().allocate(2000)
        self.assertAlmostEqual(r["capital_usd"], 2000)

    def test_cumulative_total(self):
        a = _default()
        a.allocate(1000)
        r = a.allocate(500)
        self.assertAlmostEqual(r["total_allocated_usd"], 1500)

    def test_annual_yield(self):
        r = _default().allocate(10000)
        expected = round(10000 * 0.051, 4)
        self.assertAlmostEqual(r["annual_yield_usd"], expected)

    def test_chain_in_result(self):
        self.assertEqual(_default().allocate(1000)["chain"], "polygon")

    def test_chain_id_in_result(self):
        self.assertEqual(_default().allocate(1000)["chain_id"], 137)

    def test_gas_cost_l2(self):
        r = _default().allocate(1000)
        self.assertAlmostEqual(r["gas_cost_usd"], 0.001)

    def test_pool_address_in_result(self):
        self.assertEqual(_default().allocate(1000)["pool_address"], _POOL)


# ─── TestWithdraw ─────────────────────────────────────────────────────────────

class TestWithdraw(unittest.TestCase):
    """9 тестов — withdraw (raises on over-balance)."""

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _default().withdraw(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _default().withdraw(-10)

    def test_over_balance_raises(self):
        with self.assertRaises(ValueError):
            _default().withdraw(999)  # nothing allocated

    def test_status_withdrawn(self):
        a = _default()
        a.allocate(5000)
        r = a.withdraw(2000)
        self.assertEqual(r["status"], "withdrawn")

    def test_remaining_correct(self):
        a = _default()
        a.allocate(5000)
        r = a.withdraw(1500)
        self.assertAlmostEqual(r["remaining_allocated_usd"], 3500)

    def test_amount_usd_in_result(self):
        a = _default()
        a.allocate(3000)
        r = a.withdraw(1000)
        self.assertAlmostEqual(r["amount_usd"], 1000)

    def test_chain_in_result(self):
        a = _default()
        a.allocate(1000)
        r = a.withdraw(500)
        self.assertEqual(r["chain"], "polygon")

    def test_exit_latency_in_result(self):
        a = _default()
        a.allocate(1000)
        r = a.withdraw(500)
        self.assertEqual(r["exit_latency_hours"], 0.0)

    def test_full_withdrawal(self):
        a = _default()
        a.allocate(2000)
        r = a.withdraw(2000)
        self.assertAlmostEqual(r["remaining_allocated_usd"], 0.0)


# ─── TestGetHealth ────────────────────────────────────────────────────────────

class TestGetHealth(unittest.TestCase):
    """11 тестов — get_health."""

    def test_status_ok_normal(self):
        self.assertEqual(_default().get_health()["status"], "ok")

    def test_status_degraded_below_min(self):
        self.assertEqual(_make_adapter(apy=0.5).get_health()["status"], "degraded")

    def test_status_degraded_above_max(self):
        self.assertEqual(_make_adapter(apy=35.0).get_health()["status"], "degraded")

    def test_apy_pct_present(self):
        h = _default().get_health()
        self.assertIn("apy_pct", h)
        self.assertAlmostEqual(h["apy_pct"], 5.1)

    def test_apy_in_range_true(self):
        self.assertTrue(_default().get_health()["apy_in_range"])

    def test_apy_in_range_false(self):
        self.assertFalse(_make_adapter(apy=0.1).get_health()["apy_in_range"])

    def test_tvl_floor_ok(self):
        self.assertTrue(_default().get_health()["tvl_floor_ok"])

    def test_peg_healthy_in_result(self):
        self.assertIn("peg_healthy", _default().get_health())

    def test_eligible_in_result(self):
        self.assertIn("eligible", _default().get_health())

    def test_apy_source_fallback(self):
        self.assertEqual(_no_file().get_health()["apy_source"], "fallback")

    def test_apy_source_adapter_status(self):
        self.assertEqual(_default().get_health()["apy_source"], "adapter_status")


# ─── TestToDict ───────────────────────────────────────────────────────────────

class TestToDict(unittest.TestCase):
    """10 тестов — to_dict."""

    def setUp(self):
        self.d = _default().to_dict()

    def test_protocol_key(self):
        self.assertEqual(self.d["protocol"], "aave_v3_polygon")

    def test_tier(self):
        self.assertEqual(self.d["tier"], "T1")

    def test_chain(self):
        self.assertEqual(self.d["chain"], "polygon")

    def test_chain_id(self):
        self.assertEqual(self.d["chain_id"], 137)

    def test_peg_healthy_present(self):
        self.assertIn("peg_healthy", self.d)

    def test_eligible_present(self):
        self.assertIn("eligible", self.d)

    def test_l2_advantages_present(self):
        self.assertIn("l2_advantages", self.d)

    def test_bridge_risk_note_present(self):
        self.assertIn("bridge_risk_note", self.d)

    def test_tvl_usd(self):
        self.assertAlmostEqual(self.d["tvl_usd"], 800_000_000)

    def test_pool_address(self):
        self.assertEqual(self.d["pool_address"], _POOL)


# ─── TestGasSavings ──────────────────────────────────────────────────────────

class TestGasSavings(unittest.TestCase):
    """9 тестов — get_gas_savings_vs_mainnet."""

    def setUp(self):
        self.g = _default().get_gas_savings_vs_mainnet()

    def test_returns_dict(self):
        self.assertIsInstance(self.g, dict)

    def test_savings_pct_value(self):
        self.assertAlmostEqual(self.g["savings_pct"], 90.0)

    def test_chain_is_polygon(self):
        self.assertEqual(self.g["chain"], "polygon")

    def test_gas_l2_usd(self):
        self.assertAlmostEqual(self.g["gas_l2_usd"], 0.001)

    def test_gas_mainnet_usd(self):
        self.assertAlmostEqual(self.g["gas_mainnet_usd"], 0.10)

    def test_finality_minutes_present(self):
        self.assertIn("finality_minutes", self.g)

    def test_finality_minutes_value(self):
        self.assertEqual(self.g["finality_minutes"], 2)

    def test_mainnet_bridge_exit_days(self):
        self.assertIn("mainnet_bridge_exit_days", self.g)

    def test_independent_copies(self):
        """Метод возвращает новый dict каждый раз — мутация не ломает следующий вызов."""
        a = _default()
        g1 = a.get_gas_savings_vs_mainnet()
        g1["savings_pct"] = 0
        g2 = a.get_gas_savings_vs_mainnet()
        self.assertAlmostEqual(g2["savings_pct"], 90.0)


# ─── TestBridgeRisk ──────────────────────────────────────────────────────────

class TestBridgeRisk(unittest.TestCase):
    """5 тестов — get_bridge_risk_note (USDC.e / bridged)."""

    def setUp(self):
        self.note = _default().get_bridge_risk_note()

    def test_returns_string(self):
        self.assertIsInstance(self.note, str)

    def test_non_empty(self):
        self.assertTrue(len(self.note) > 0)

    def test_mentions_usdc_e(self):
        self.assertIn("USDC.e", self.note)

    def test_mentions_bridged(self):
        self.assertIn("bridged", self.note.lower())

    def test_independent_calls_same_content(self):
        """Повторный вызов возвращает ту же строку."""
        a = _default()
        note1 = a.get_bridge_risk_note()
        note2 = a.get_bridge_risk_note()
        self.assertEqual(note1, note2)


# ─── TestRegistry ─────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    """2 теста — ADAPTER_REGISTRY содержит aave_v3_polygon T1."""

    def test_registry_contains_aave_v3_polygon(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, _t, _cls in ADAPTER_REGISTRY]
        self.assertIn("aave_v3_polygon", keys)

    def test_registry_tier_is_t1(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "aave_v3_polygon":
                self.assertEqual(tier, "T1")
                return
        self.fail("aave_v3_polygon not found in ADAPTER_REGISTRY")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
