"""Unit tests for FraxAdapter — MP-563.

100 тест-кейсов покрывают:
  - Init (10 кейсов)
  - APY reading (14 кейсов)
  - Peg compliance / is_peg_healthy (15 кейсов)
  - Eligibility / is_eligible (10 кейсов)
  - YieldInfo (8 кейсов)
  - vs_morpho_gap (8 кейсов)
  - simulate_deposit (10 кейсов)
  - simulate_withdraw (10 кейсов)
  - get_health / health_check (8 кейсов)
  - to_dict (10 кейсов)
  - Registry / import hygiene (7 кейсов)

Всего: 110 тестов.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Bootstrap: гарантируем что spa_core доступен
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.frax_adapter import FraxAdapter  # noqa: E402
from spa_core.adapters.base_adapter import YieldInfo     # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data_dir(status: dict) -> str:
    """Создаёт tmpdir с adapter_status.json содержащим переданный dict."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "adapter_status.json"), "w", encoding="utf-8") as fh:
        json.dump(status, fh)
    return d


def _adapter_with_status(status_dict: dict, asset: str = "USDC") -> FraxAdapter:
    """Создаёт FraxAdapter с заданным frax-блоком в adapter_status.json."""
    data_dir = _make_data_dir({"frax": status_dict})
    return FraxAdapter(asset=asset, data_dir=data_dir)


def _adapter_no_file(asset: str = "USDC") -> FraxAdapter:
    """FraxAdapter с несуществующим data_dir (симулирует отсутствие файла)."""
    return FraxAdapter(asset=asset, data_dir="/nonexistent_path_spa_test_12345")


def _adapter_empty_status(asset: str = "USDC") -> FraxAdapter:
    """FraxAdapter с пустым frax-блоком в adapter_status.json."""
    data_dir = _make_data_dir({"frax": {}})
    return FraxAdapter(asset=asset, data_dir=data_dir)


def _adapter_default(asset: str = "USDC") -> FraxAdapter:
    """FraxAdapter с DEFAULT APY 7.5% (нет frax.apy в файле)."""
    return _adapter_empty_status(asset)


# ===========================================================================
# TestFraxAdapterInit — 10 тестов
# ===========================================================================
class TestFraxAdapterInit(unittest.TestCase):

    def test_01_default_asset(self):
        a = _adapter_default()
        self.assertEqual(a.asset, "USDC")

    def test_02_custom_asset(self):
        a = _adapter_with_status({"apy": 7.5}, asset="DAI")
        self.assertEqual(a.asset, "DAI")

    def test_03_protocol_constant(self):
        a = _adapter_default()
        self.assertEqual(a.PROTOCOL, "frax")

    def test_04_tier_constant(self):
        a = _adapter_default()
        self.assertEqual(a.TIER, "T2")

    def test_05_tier_instance_attr(self):
        a = _adapter_default()
        self.assertEqual(a.tier, "T2")

    def test_06_risk_score(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.RISK_SCORE, 0.45)

    def test_07_tvl_usd(self):
        a = _adapter_default()
        self.assertEqual(a.TVL_USD, 800_000_000)

    def test_08_peg_tolerance(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.PEG_TOLERANCE, 0.005)

    def test_09_exit_latency(self):
        a = _adapter_default()
        self.assertEqual(a.EXIT_LATENCY_HOURS, 0.0)

    def test_10_allocated_starts_zero(self):
        a = _adapter_default()
        self.assertEqual(a._allocated, 0.0)


# ===========================================================================
# TestFraxAdapterAPY — 14 тестов
# ===========================================================================
class TestFraxAdapterAPY(unittest.TestCase):

    def test_11_default_apy_fallback(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_12_apy_from_status(self):
        a = _adapter_with_status({"apy": 9.2})
        self.assertAlmostEqual(a.get_apy(), 9.2)

    def test_13_apy_from_status_integer(self):
        a = _adapter_with_status({"apy": 8})
        self.assertAlmostEqual(a.get_apy(), 8.0)

    def test_14_apy_no_file_fallback(self):
        a = _adapter_no_file()
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_15_apy_none_in_status_fallback(self):
        a = _adapter_with_status({"apy": None})
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_16_apy_string_in_status_fallback(self):
        a = _adapter_with_status({"apy": "high"})
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_17_apy_bool_in_status_fallback(self):
        a = _adapter_with_status({"apy": True})
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_18_get_apy_pct_equals_get_apy(self):
        a = _adapter_with_status({"apy": 10.0})
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_19_default_apy_pct_constant(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.DEFAULT_APY_PCT, 7.5)

    def test_20_min_apy_constant(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.MIN_APY_PCT, 3.0)

    def test_21_max_apy_constant(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.MAX_APY_PCT, 15.0)

    def test_22_apy_zero_in_status_read_as_zero(self):
        # 0.0 is a valid float, не bool — должен читаться (даже если ниже MIN_APY)
        a = _adapter_with_status({"apy": 0.0})
        self.assertAlmostEqual(a.get_apy(), 0.0)

    def test_23_apy_negative_read_as_is(self):
        a = _adapter_with_status({"apy": -1.0})
        self.assertAlmostEqual(a.get_apy(), -1.0)

    def test_24_apy_large_value(self):
        a = _adapter_with_status({"apy": 100.0})
        self.assertAlmostEqual(a.get_apy(), 100.0)


# ===========================================================================
# TestFraxAdapterPeg — 15 тестов
# ===========================================================================
class TestFraxAdapterPeg(unittest.TestCase):

    def _peg_adapter(self, frax_price) -> FraxAdapter:
        return _adapter_with_status({"frax_price": frax_price})

    def test_25_peg_healthy_nominal(self):
        a = self._peg_adapter(1.0)
        self.assertTrue(a.is_peg_healthy())

    def test_26_peg_healthy_no_price_field(self):
        # Отсутствие поля → safe-default healthy
        a = _adapter_empty_status()
        self.assertTrue(a.is_peg_healthy())

    def test_27_peg_healthy_at_upper_boundary(self):
        # |1.005 - 1.0| = 0.005 ≤ 0.005 → healthy
        a = self._peg_adapter(1.005)
        self.assertTrue(a.is_peg_healthy())

    def test_28_peg_healthy_at_lower_boundary(self):
        # |0.995 - 1.0| = 0.005 ≤ 0.005 → healthy
        a = self._peg_adapter(0.995)
        self.assertTrue(a.is_peg_healthy())

    def test_29_peg_broken_above(self):
        # |1.006 - 1.0| = 0.006 > 0.005 → NOT healthy
        a = self._peg_adapter(1.006)
        self.assertFalse(a.is_peg_healthy())

    def test_30_peg_broken_below(self):
        # |0.994 - 1.0| = 0.006 > 0.005 → NOT healthy
        a = self._peg_adapter(0.994)
        self.assertFalse(a.is_peg_healthy())

    def test_31_peg_string_price_safe_healthy(self):
        a = self._peg_adapter("1.001")
        self.assertTrue(a.is_peg_healthy())

    def test_32_peg_bool_price_safe_healthy(self):
        # bool является подклассом int, но мы его отфильтровываем
        a = self._peg_adapter(True)
        self.assertTrue(a.is_peg_healthy())

    def test_33_peg_none_price_safe_healthy(self):
        a = self._peg_adapter(None)
        self.assertTrue(a.is_peg_healthy())

    def test_34_peg_large_depeg(self):
        a = self._peg_adapter(0.90)
        self.assertFalse(a.is_peg_healthy())

    def test_35_peg_no_file_safe_healthy(self):
        a = _adapter_no_file()
        self.assertTrue(a.is_peg_healthy())

    def test_36_peg_slightly_above_1(self):
        a = self._peg_adapter(1.002)
        self.assertTrue(a.is_peg_healthy())

    def test_37_peg_slightly_below_1(self):
        a = self._peg_adapter(0.998)
        self.assertTrue(a.is_peg_healthy())

    def test_38_peg_exactly_outside_upper(self):
        # 1.0051 > 1.005 → NOT healthy
        a = self._peg_adapter(1.0051)
        self.assertFalse(a.is_peg_healthy())

    def test_39_peg_tolerance_constant(self):
        self.assertAlmostEqual(FraxAdapter.PEG_TOLERANCE, 0.005)


# ===========================================================================
# TestFraxAdapterEligibility — 10 тестов
# ===========================================================================
class TestFraxAdapterEligibility(unittest.TestCase):

    def test_40_eligible_nominal(self):
        a = _adapter_with_status({"apy": 7.5, "frax_price": 1.0})
        self.assertTrue(a.is_eligible())

    def test_41_not_eligible_peg_broken(self):
        a = _adapter_with_status({"apy": 7.5, "frax_price": 0.990})
        self.assertFalse(a.is_eligible())

    def test_42_not_eligible_apy_too_low(self):
        a = _adapter_with_status({"apy": 1.0, "frax_price": 1.0})
        self.assertFalse(a.is_eligible())

    def test_43_not_eligible_apy_too_high(self):
        a = _adapter_with_status({"apy": 20.0, "frax_price": 1.0})
        self.assertFalse(a.is_eligible())

    def test_44_eligible_at_min_boundary(self):
        a = _adapter_with_status({"apy": 3.0, "frax_price": 1.0})
        self.assertTrue(a.is_eligible())

    def test_45_eligible_at_max_boundary(self):
        a = _adapter_with_status({"apy": 15.0, "frax_price": 1.0})
        self.assertTrue(a.is_eligible())

    def test_46_not_eligible_just_below_min(self):
        a = _adapter_with_status({"apy": 2.99, "frax_price": 1.0})
        self.assertFalse(a.is_eligible())

    def test_47_not_eligible_just_above_max(self):
        a = _adapter_with_status({"apy": 15.01, "frax_price": 1.0})
        self.assertFalse(a.is_eligible())

    def test_48_eligible_fallback_apy(self):
        # DEFAULT_APY = 7.5, peg отсутствует → safe healthy → eligible
        a = _adapter_empty_status()
        self.assertTrue(a.is_eligible())

    def test_49_not_eligible_peg_only(self):
        # peg broken, apy ok
        a = _adapter_with_status({"apy": 8.0, "frax_price": 0.993})
        self.assertFalse(a.is_eligible())


# ===========================================================================
# TestFraxAdapterYieldInfo — 8 тестов
# ===========================================================================
class TestFraxAdapterYieldInfo(unittest.TestCase):

    def test_50_yield_info_type(self):
        a = _adapter_default()
        yi = a.get_yield_info()
        self.assertIsInstance(yi, YieldInfo)

    def test_51_yield_info_protocol(self):
        a = _adapter_default()
        self.assertEqual(a.get_yield_info().protocol, "frax")

    def test_52_yield_info_apy_decimal(self):
        a = _adapter_with_status({"apy": 7.5})
        yi = a.get_yield_info()
        self.assertAlmostEqual(yi.apy, 0.075)

    def test_53_yield_info_tvl(self):
        a = _adapter_default()
        self.assertEqual(a.get_yield_info().tvl_usd, 800_000_000)

    def test_54_yield_info_tier(self):
        a = _adapter_default()
        self.assertEqual(a.get_yield_info().tier, "T2")

    def test_55_yield_info_risk_score(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.get_yield_info().risk_score, 0.45)

    def test_56_yield_info_exit_latency(self):
        a = _adapter_default()
        self.assertEqual(a.get_yield_info().exit_latency_hours, 0.0)

    def test_57_yield_info_asset(self):
        a = _adapter_with_status({"apy": 7.5}, asset="DAI")
        self.assertEqual(a.get_yield_info().asset, "DAI")


# ===========================================================================
# TestFraxAdapterVsMorphoGap — 8 тестов
# ===========================================================================
class TestFraxAdapterVsMorphoGap(unittest.TestCase):

    def test_58_vs_morpho_default(self):
        a = _adapter_with_status({"apy": 7.5})
        # 6.5 - 7.5 = -1.0
        self.assertAlmostEqual(a.vs_morpho_gap(), -1.0)

    def test_59_vs_morpho_frax_lower(self):
        a = _adapter_with_status({"apy": 5.0})
        # 6.5 - 5.0 = 1.5
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.5)

    def test_60_vs_morpho_equal(self):
        a = _adapter_with_status({"apy": 6.5})
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_61_vs_morpho_custom_morpho_apy(self):
        a = _adapter_with_status({"apy": 8.0})
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=10.0), 2.0)

    def test_62_vs_morpho_fallback_apy(self):
        a = _adapter_default()
        # 6.5 - 7.5 = -1.0
        self.assertAlmostEqual(a.vs_morpho_gap(), -1.0)

    def test_63_vs_morpho_returns_float(self):
        a = _adapter_default()
        self.assertIsInstance(a.vs_morpho_gap(), float)

    def test_64_vs_morpho_zero_morpho_apy(self):
        a = _adapter_with_status({"apy": 7.5})
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=0.0), -7.5)

    def test_65_vs_morpho_high_frax(self):
        a = _adapter_with_status({"apy": 12.0})
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=6.5), -5.5)


# ===========================================================================
# TestFraxAdapterSimulateDeposit — 10 тестов
# ===========================================================================
class TestFraxAdapterSimulateDeposit(unittest.TestCase):

    def test_66_deposit_returns_ok(self):
        a = _adapter_default()
        result = a.simulate_deposit(1000.0)
        self.assertEqual(result["status"], "ok")

    def test_67_deposit_amount_in_result(self):
        a = _adapter_default()
        result = a.simulate_deposit(5000.0)
        self.assertAlmostEqual(result["amount"], 5000.0)

    def test_68_deposit_increments_allocated(self):
        a = _adapter_default()
        a.simulate_deposit(3000.0)
        self.assertAlmostEqual(a._allocated, 3000.0)

    def test_69_deposit_cumulative(self):
        a = _adapter_default()
        a.simulate_deposit(1000.0)
        a.simulate_deposit(2000.0)
        self.assertAlmostEqual(a._allocated, 3000.0)

    def test_70_deposit_allocated_total_in_result(self):
        a = _adapter_default()
        a.simulate_deposit(500.0)
        result = a.simulate_deposit(500.0)
        self.assertAlmostEqual(result["allocated_total"], 1000.0)

    def test_71_deposit_protocol_in_result(self):
        a = _adapter_default()
        result = a.simulate_deposit(100.0)
        self.assertEqual(result["protocol"], "frax")

    def test_72_deposit_vault_in_result(self):
        a = _adapter_default()
        result = a.simulate_deposit(100.0)
        self.assertIn("vault", result)
        self.assertTrue(result["vault"].startswith("0x"))

    def test_73_deposit_zero_raises(self):
        a = _adapter_default()
        with self.assertRaises(ValueError):
            a.simulate_deposit(0.0)

    def test_74_deposit_negative_raises(self):
        a = _adapter_default()
        with self.assertRaises(ValueError):
            a.simulate_deposit(-500.0)

    def test_75_deposit_apy_pct_in_result(self):
        a = _adapter_with_status({"apy": 8.0})
        result = a.simulate_deposit(100.0)
        self.assertAlmostEqual(result["apy_pct"], 8.0)


# ===========================================================================
# TestFraxAdapterSimulateWithdraw — 10 тестов
# ===========================================================================
class TestFraxAdapterSimulateWithdraw(unittest.TestCase):

    def test_76_withdraw_ok(self):
        a = _adapter_default()
        a.simulate_deposit(5000.0)
        result = a.simulate_withdraw(2000.0)
        self.assertEqual(result["status"], "ok")

    def test_77_withdraw_decrements_allocated(self):
        a = _adapter_default()
        a.simulate_deposit(5000.0)
        a.simulate_withdraw(3000.0)
        self.assertAlmostEqual(a._allocated, 2000.0)

    def test_78_withdraw_full_balance(self):
        a = _adapter_default()
        a.simulate_deposit(1000.0)
        result = a.simulate_withdraw(1000.0)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(a._allocated, 0.0)

    def test_79_withdraw_remaining_in_result(self):
        a = _adapter_default()
        a.simulate_deposit(3000.0)
        result = a.simulate_withdraw(1000.0)
        self.assertAlmostEqual(result["allocated_remaining"], 2000.0)

    def test_80_withdraw_insufficient_balance(self):
        a = _adapter_default()
        a.simulate_deposit(500.0)
        result = a.simulate_withdraw(1000.0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "insufficient_balance")

    def test_81_withdraw_insufficient_requested_field(self):
        a = _adapter_default()
        a.simulate_deposit(100.0)
        result = a.simulate_withdraw(200.0)
        self.assertAlmostEqual(result["requested"], 200.0)
        self.assertAlmostEqual(result["available"], 100.0)

    def test_82_withdraw_zero_raises(self):
        a = _adapter_default()
        with self.assertRaises(ValueError):
            a.simulate_withdraw(0.0)

    def test_83_withdraw_negative_raises(self):
        a = _adapter_default()
        with self.assertRaises(ValueError):
            a.simulate_withdraw(-100.0)

    def test_84_withdraw_from_empty_is_error(self):
        a = _adapter_default()
        result = a.simulate_withdraw(1.0)
        self.assertEqual(result["status"], "error")

    def test_85_withdraw_protocol_in_result(self):
        a = _adapter_default()
        a.simulate_deposit(1000.0)
        result = a.simulate_withdraw(500.0)
        self.assertEqual(result["protocol"], "frax")


# ===========================================================================
# TestFraxAdapterGetHealth — 8 тестов
# ===========================================================================
class TestFraxAdapterGetHealth(unittest.TestCase):

    def test_86_health_ok_nominal(self):
        a = _adapter_with_status({"apy": 7.5})
        self.assertEqual(a.get_health(), "ok")

    def test_87_health_degraded_apy_too_low(self):
        a = _adapter_with_status({"apy": 1.0})
        self.assertEqual(a.get_health(), "degraded")

    def test_88_health_degraded_apy_too_high(self):
        a = _adapter_with_status({"apy": 20.0})
        self.assertEqual(a.get_health(), "degraded")

    def test_89_health_ok_at_min(self):
        a = _adapter_with_status({"apy": 3.0})
        self.assertEqual(a.get_health(), "ok")

    def test_90_health_ok_at_max(self):
        a = _adapter_with_status({"apy": 15.0})
        self.assertEqual(a.get_health(), "ok")

    def test_91_health_check_alias(self):
        a = _adapter_with_status({"apy": 7.5})
        self.assertEqual(a.health_check(), a.get_health())

    def test_92_health_ok_fallback(self):
        # DEFAULT_APY_PCT = 7.5 ∈ [3.0, 15.0]
        a = _adapter_default()
        self.assertEqual(a.get_health(), "ok")

    def test_93_health_returns_string(self):
        a = _adapter_default()
        result = a.get_health()
        self.assertIsInstance(result, str)
        self.assertIn(result, ("ok", "degraded"))


# ===========================================================================
# TestFraxAdapterToDict — 10 тестов
# ===========================================================================
class TestFraxAdapterToDict(unittest.TestCase):

    def test_94_to_dict_returns_dict(self):
        a = _adapter_default()
        self.assertIsInstance(a.to_dict(), dict)

    def test_95_to_dict_protocol(self):
        a = _adapter_default()
        self.assertEqual(a.to_dict()["protocol"], "frax")

    def test_96_to_dict_tier(self):
        a = _adapter_default()
        self.assertEqual(a.to_dict()["tier"], "T2")

    def test_97_to_dict_risk_score(self):
        a = _adapter_default()
        self.assertAlmostEqual(a.to_dict()["risk_score"], 0.45)

    def test_98_to_dict_tvl_usd(self):
        a = _adapter_default()
        self.assertEqual(a.to_dict()["tvl_usd"], 800_000_000)

    def test_99_to_dict_peg_healthy(self):
        a = _adapter_default()
        self.assertIn("peg_healthy", a.to_dict())

    def test_100_to_dict_eligible(self):
        a = _adapter_default()
        self.assertIn("eligible", a.to_dict())

    def test_101_to_dict_allocated(self):
        a = _adapter_default()
        a.simulate_deposit(500.0)
        self.assertAlmostEqual(a.to_dict()["allocated"], 500.0)

    def test_102_to_dict_health_key(self):
        a = _adapter_default()
        self.assertIn("health", a.to_dict())

    def test_103_to_dict_apy_pct(self):
        a = _adapter_with_status({"apy": 9.0})
        self.assertAlmostEqual(a.to_dict()["apy_pct"], 9.0)


# ===========================================================================
# TestFraxAdapterRegistry — 7 тестов
# ===========================================================================
class TestFraxAdapterRegistry(unittest.TestCase):

    def test_104_registry_contains_frax(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [entry[0] for entry in ADAPTER_REGISTRY]
        self.assertIn("frax", keys)

    def test_105_registry_frax_tier(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "frax":
                self.assertEqual(tier, "T2")
                break

    def test_106_registry_frax_class(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "frax":
                self.assertIs(cls, FraxAdapter)
                break

    def test_107_import_in_all(self):
        from spa_core.adapters import __all__
        self.assertIn("FraxAdapter", __all__)

    def test_108_direct_import(self):
        from spa_core.adapters import FraxAdapter as FA
        self.assertIs(FA, FraxAdapter)

    def test_109_no_stdlib_violation(self):
        """Проверяем что frax_adapter.py не импортирует запрещённые внешние модули."""
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "adapters" / "frax_adapter.py"
        source = path.read_text(encoding="utf-8")
        forbidden = ["requests", "web3", "numpy", "pandas", "scipy",
                     "openai", "anthropic", "aiohttp", "httpx"]
        for lib in forbidden:
            self.assertNotIn(f"import {lib}", source, msg=f"Forbidden import: {lib}")

    def test_110_no_execution_import(self):
        """Проверяем отсутствие запрещённых доменных импортов."""
        path = Path(__file__).resolve().parents[1] / "adapters" / "frax_adapter.py"
        source = path.read_text(encoding="utf-8")
        for forbidden in ["from spa_core.execution", "import execution",
                          "from spa_core.risk", "import monitoring"]:
            self.assertNotIn(forbidden, source, msg=f"Forbidden domain import: {forbidden}")


# ===========================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
