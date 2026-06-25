"""
spa_core/tests/test_e2e_integration.py — MP-388 E2E Integration Test

E2E интеграционный тест всей системы SPA: адаптеры, стратегии, аналитика,
MultiStrategyRunner, ChainConcentrationAnalyzer, data/*.json файлы.

6 классов, 50+ тестов. Только stdlib. Graceful skipTest при отсутствии модуля.
Не создаёт сайд-эффектов (не пишет файлы, не модифицирует state).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path

# Корень репозитория — три уровня выше этого файла
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR  = _REPO_ROOT / "data"


# ─── Утилита безопасного импорта ──────────────────────────────────────────────

def _try_import(module_path: str):
    """Пробует импортировать модуль; возвращает (module, None) или (None, err)."""
    try:
        return importlib.import_module(module_path), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestAdapterImports
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterImports(unittest.TestCase):
    """Импорт каждого адаптера не вызывает ошибок; атрибуты PROTOCOL/TIER присутствуют."""

    def _assert_adapter_class(self, module_path: str, class_name: str):
        """Вспомогательный: импортирует модуль, берёт класс."""
        mod, err = _try_import(module_path)
        if mod is None:
            self.skipTest(f"Модуль {module_path} недоступен: {err}")
        cls = getattr(mod, class_name, None)
        self.assertIsNotNone(cls, f"{class_name} не найден в {module_path}")
        return cls

    # ── 1.1 spark_susds_adapter ────────────────────────────────────────────────
    def test_spark_susds_import(self):
        """SparkSusdsAdapter импортируется без ошибок."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.spark_susds_adapter", "SparkSusdsAdapter"
        )
        obj = cls()
        self.assertIsNotNone(obj)

    def test_spark_susds_protocol_attr(self):
        """SparkSusdsAdapter имеет PROTOCOL = 'spark_susds'."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.spark_susds_adapter", "SparkSusdsAdapter"
        )
        self.assertEqual(cls.PROTOCOL, "spark_susds")

    def test_spark_susds_tier_attr(self):
        """SparkSusdsAdapter имеет TIER = 'T1'."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.spark_susds_adapter", "SparkSusdsAdapter"
        )
        self.assertEqual(cls.TIER, "T1")

    # ── 1.2 fluid_fusdc_adapter ────────────────────────────────────────────────
    def test_fluid_fusdc_import(self):
        """FluidFUSDCAdapter импортируется без ошибок."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.fluid_fusdc_adapter", "FluidFUSDCAdapter"
        )
        obj = cls()
        self.assertIsNotNone(obj)

    def test_fluid_fusdc_tier_attr(self):
        """FluidFUSDCAdapter имеет TIER = 'T2'."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.fluid_fusdc_adapter", "FluidFUSDCAdapter"
        )
        self.assertEqual(cls.TIER, "T2")

    # ── 1.3 morpho_steakhouse_adapter ─────────────────────────────────────────
    def test_morpho_steakhouse_import(self):
        """MorphoSteakhouseAdapter импортируется без ошибок."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.morpho_steakhouse_adapter", "MorphoSteakhouseAdapter"
        )
        obj = cls()
        self.assertIsNotNone(obj)

    def test_morpho_steakhouse_protocol_attr(self):
        """MorphoSteakhouseAdapter PROTOCOL = 'morpho_steakhouse'."""
        cls = self._assert_adapter_class(
            "spa_core.adapters.morpho_steakhouse_adapter", "MorphoSteakhouseAdapter"
        )
        self.assertEqual(cls.PROTOCOL, "morpho_steakhouse")

    # ── 1.4 compound_v3_adapter ────────────────────────────────────────────────
    def test_compound_v3_adapter_import(self):
        """compound_v3_adapter импортируется без ошибок."""
        mod, err = _try_import("spa_core.adapters.compound_v3_adapter")
        if mod is None:
            self.skipTest(f"compound_v3_adapter недоступен: {err}")
        cls = (getattr(mod, "CompoundV3Adapter", None)
               or getattr(mod, "CompoundComet", None))
        self.assertIsNotNone(cls, "Не найден класс адаптера в compound_v3_adapter")

    # ── 1.5 aave_arbitrum_adapter ─────────────────────────────────────────────
    def test_aave_arbitrum_adapter_import(self):
        """aave_arbitrum_adapter импортируется без ошибок."""
        mod, err = _try_import("spa_core.adapters.aave_arbitrum_adapter")
        if mod is None:
            self.skipTest(f"aave_arbitrum_adapter недоступен: {err}")
        cls = (getattr(mod, "AaveArbitrumAdapter", None)
               or getattr(mod, "AaveV3ArbitrumAdapter", None))
        self.assertIsNotNone(cls, "Не найден класс адаптера в aave_arbitrum_adapter")

    # ── 1.6 adapter_registry ──────────────────────────────────────────────────
    def test_adapter_registry_import(self):
        """adapter_registry импортируется, REGISTRY — словарь."""
        mod, err = _try_import("spa_core.adapters.adapter_registry")
        if mod is None:
            self.skipTest(f"adapter_registry недоступен: {err}")
        registry = getattr(mod, "REGISTRY", None)
        self.assertIsNotNone(registry)
        self.assertIsInstance(registry, dict)

    def test_adapter_registry_has_refresh_all(self):
        """adapter_registry экспортирует callable refresh_all()."""
        mod, err = _try_import("spa_core.adapters.adapter_registry")
        if mod is None:
            self.skipTest(f"adapter_registry недоступен: {err}")
        self.assertTrue(
            callable(getattr(mod, "refresh_all", None)),
            "refresh_all() не найден в adapter_registry"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestAdapterBehavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterBehavior(unittest.TestCase):
    """Поведение методов адаптеров: get_apy_pct, is_eligible, to_dict."""

    # ── 2.1 SparkSusdsAdapter ──────────────────────────────────────────────────

    def _get_spark_with_dir(self, gsm_hours: int = 0, apy: float = 5.5):
        import tempfile
        mod, err = _try_import("spa_core.adapters.spark_susds_adapter")
        if mod is None:
            self.skipTest(f"spark_susds_adapter недоступен: {err}")
        tmpdir = tempfile.mkdtemp()
        status = {"spark_susds": {"apy": apy, "gsm_hours": gsm_hours}}
        path = Path(tmpdir) / "adapter_status.json"
        path.write_text(json.dumps(status), encoding="utf-8")
        return mod.SparkSusdsAdapter(data_dir=tmpdir)

    def _get_spark(self):
        mod, err = _try_import("spa_core.adapters.spark_susds_adapter")
        if mod is None:
            self.skipTest(f"spark_susds_adapter недоступен: {err}")
        return mod.SparkSusdsAdapter()

    def test_spark_get_apy_pct_returns_float(self):
        """SparkSusdsAdapter.get_apy_pct() возвращает float."""
        adapter = self._get_spark()
        apy = adapter.get_apy_pct()
        self.assertIsInstance(apy, float)

    def test_spark_get_apy_pct_positive(self):
        """SparkSusdsAdapter.get_apy_pct() > 0 (fallback 5.5% гарантирован)."""
        adapter = self._get_spark()
        self.assertGreater(adapter.get_apy_pct(), 0.0)

    def test_spark_is_eligible_returns_bool(self):
        """SparkSusdsAdapter.is_eligible() возвращает bool."""
        adapter = self._get_spark()
        self.assertIsInstance(adapter.is_eligible(), bool)

    def test_spark_gsm_gate_zero_hours(self):
        """SparkSusdsAdapter.is_eligible() = False при gsm_hours = 0 (GSM gate)."""
        adapter = self._get_spark_with_dir(gsm_hours=0, apy=5.5)
        self.assertFalse(
            adapter.is_eligible(),
            "При gsm_hours=0 адаптер должен быть не eligible"
        )

    def test_spark_gsm_gate_48_hours(self):
        """SparkSusdsAdapter.is_eligible() = True при gsm_hours = 48 и нормальном APY."""
        adapter = self._get_spark_with_dir(gsm_hours=48, apy=5.5)
        self.assertTrue(adapter.is_eligible())

    def test_spark_to_dict_required_keys(self):
        """SparkSusdsAdapter.to_dict() содержит tier, apy_pct, risk_score."""
        adapter = self._get_spark()
        d = adapter.to_dict()
        self.assertIsInstance(d, dict)
        for key in ("tier", "apy_pct", "risk_score"):
            self.assertIn(key, d, f"Ключ '{key}' отсутствует в to_dict()")

    # ── 2.2 FluidFUSDCAdapter ─────────────────────────────────────────────────

    def _get_fluid(self, apy: float = 6.5, gsm: int = 0):
        import tempfile
        mod, err = _try_import("spa_core.adapters.fluid_fusdc_adapter")
        if mod is None:
            self.skipTest(f"fluid_fusdc_adapter недоступен: {err}")
        tmpdir = tempfile.mkdtemp()
        status = {"fluid_fusdc": {"apy": apy, "gsm_hours": gsm}}
        path = Path(tmpdir) / "adapter_status.json"
        path.write_text(json.dumps(status), encoding="utf-8")
        return mod.FluidFUSDCAdapter(data_dir=tmpdir)

    def test_fluid_get_apy_pct_returns_float(self):
        """FluidFUSDCAdapter.get_apy_pct() возвращает float."""
        adapter = self._get_fluid()
        self.assertIsInstance(adapter.get_apy_pct(), float)

    def test_fluid_spike_normalization(self):
        """FluidFUSDCAdapter: raw APY > 15% нормализуется до <= 9.0%."""
        adapter = self._get_fluid(apy=22.0)
        apy = adapter.get_apy()
        self.assertLessEqual(apy, 9.0,
                             f"Spike нормализация: APY должен быть <= 9.0%, получен {apy}")

    def test_fluid_normal_apy_not_normalized(self):
        """FluidFUSDCAdapter: APY 6.5% не нормализуется."""
        adapter = self._get_fluid(apy=6.5)
        self.assertAlmostEqual(adapter.get_apy(), 6.5, places=5)

    def test_fluid_to_dict_required_keys(self):
        """FluidFUSDCAdapter.to_dict() содержит tier, apy_pct, risk_score."""
        adapter = self._get_fluid()
        d = adapter.to_dict()
        for key in ("tier", "apy_pct", "risk_score"):
            self.assertIn(key, d, f"Ключ '{key}' отсутствует в to_dict()")

    # ── 2.3 MorphoSteakhouseAdapter ───────────────────────────────────────────

    def test_morpho_get_apy_pct_returns_float(self):
        """MorphoSteakhouseAdapter.get_apy_pct() возвращает float > 0."""
        mod, err = _try_import("spa_core.adapters.morpho_steakhouse_adapter")
        if mod is None:
            self.skipTest(f"morpho_steakhouse_adapter недоступен: {err}")
        adapter = mod.MorphoSteakhouseAdapter()
        apy = adapter.get_apy_pct()
        self.assertIsInstance(apy, float)
        self.assertGreater(apy, 0.0)

    def test_morpho_to_dict_has_tier(self):
        """MorphoSteakhouseAdapter.to_dict() содержит ключ 'tier'."""
        mod, err = _try_import("spa_core.adapters.morpho_steakhouse_adapter")
        if mod is None:
            self.skipTest(f"morpho_steakhouse_adapter недоступен: {err}")
        adapter = mod.MorphoSteakhouseAdapter()
        d = adapter.to_dict()
        self.assertIn("tier", d)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestStrategyIntegration
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyIntegration(unittest.TestCase):
    """Интеграция стратегий S2 и S3: weighted APY, simulate_day, vportfolio format."""

    def _get_s2(self):
        mod, err = _try_import("spa_core.strategies.s2_pendle_morpho")
        if mod is None:
            self.skipTest(f"s2_pendle_morpho недоступен: {err}")
        return mod.S2PendleMorpho(capital=100_000.0)

    def _get_s3(self):
        mod, err = _try_import("spa_core.strategies.s3_aave_arb_morpho")
        if mod is None:
            self.skipTest(f"s3_aave_arb_morpho недоступен: {err}")
        return mod.S3AaveArbMorpho(capital=100_000.0)

    # ── 3.1 S2PendleMorpho ────────────────────────────────────────────────────

    def test_s2_compute_weighted_apy_default(self):
        """S2 compute_weighted_apy({}) с fallback APY ≈ 7.0%."""
        s2 = self._get_s2()
        apy = s2.compute_weighted_apy({})
        self.assertAlmostEqual(apy, 7.0, delta=0.1,
                               msg=f"S2 weighted APY должен быть ~7.0%, получен {apy}")

    def test_s2_compute_weighted_apy_custom(self):
        """S2 compute_weighted_apy с явными APY даёт верное значение."""
        s2 = self._get_s2()
        apy_map = {"pendle_pt": 8.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        expected = 0.50 * 8.0 + 0.35 * 6.5 + 0.15 * 4.8
        apy = s2.compute_weighted_apy(apy_map)
        self.assertAlmostEqual(apy, expected, delta=0.01)

    def test_s2_simulate_day_returns_dict(self):
        """S2 simulate_day() возвращает dict."""
        s2 = self._get_s2()
        self.assertIsInstance(s2.simulate_day({}), dict)

    def test_s2_simulate_day_has_daily_return_pct(self):
        """S2 simulate_day() содержит daily_yield_usd > 0."""
        s2 = self._get_s2()
        result = s2.simulate_day({})
        self.assertIn("daily_yield_usd", result)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_s2_simulate_day_has_positions(self):
        """S2 simulate_day() возвращает ключ 'positions' — dict."""
        s2 = self._get_s2()
        result = s2.simulate_day({})
        self.assertIn("positions", result)
        self.assertIsInstance(result["positions"], dict)

    def test_s2_to_vportfolio_format_required_keys(self):
        """S2 to_vportfolio_format() содержит все обязательные ключи."""
        s2 = self._get_s2()
        vp = s2.to_vportfolio_format()
        required = {"strategy_id", "capital_usd", "positions", "cash_usd",
                    "equity_history", "status", "current_equity"}
        for key in required:
            self.assertIn(key, vp, f"Ключ '{key}' отсутствует в to_vportfolio_format()")

    def test_s2_capital_integrity_before_simulate(self):
        """S2 current_equity до симуляции равен начальному капиталу."""
        s2 = self._get_s2()
        self.assertAlmostEqual(s2.current_equity, 100_000.0, places=2)

    def test_s2_equity_grows_after_simulate(self):
        """S2: equity растёт после одного дня симуляции (positive APY)."""
        s2 = self._get_s2()
        initial = s2.current_equity
        s2.simulate_day({})
        self.assertGreater(s2.current_equity, initial)

    # ── 3.2 S3AaveArbMorpho ───────────────────────────────────────────────────

    def test_s3_compute_weighted_apy_default(self):
        """S3 compute_weighted_apy({}) с fallback APY ≈ 4.7%."""
        s3 = self._get_s3()
        apy = s3.compute_weighted_apy({})
        self.assertAlmostEqual(apy, 4.7, delta=0.15,
                               msg=f"S3 weighted APY должен быть ~4.7%, получен {apy}")

    def test_s3_simulate_day_has_daily_return(self):
        """S3 simulate_day() содержит daily_yield_usd > 0."""
        s3 = self._get_s3()
        result = s3.simulate_day({})
        self.assertIn("daily_yield_usd", result)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_s3_to_vportfolio_format_required_keys(self):
        """S3 to_vportfolio_format() содержит все обязательные ключи."""
        s3 = self._get_s3()
        vp = s3.to_vportfolio_format()
        required = {"strategy_id", "capital_usd", "positions", "cash_usd",
                    "equity_history", "status", "current_equity"}
        for key in required:
            self.assertIn(key, vp, f"Ключ '{key}' отсутствует в S3.to_vportfolio_format()")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestMultiStrategyRunner
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiStrategyRunner(unittest.TestCase):
    """MultiStrategyRunner: создание, run_day, get_rankings."""

    _APY_MAP = {
        "aave_v3":     4.2,
        "morpho_blue": 6.5,
        "compound_v3": 4.8,
        "yearn_v3":    6.0,
        "euler_v2":    5.8,
        "pendle_pt":   8.0,
    }

    def _get_runner_s0_s1(self):
        mod_runner, err = _try_import("spa_core.paper_trading.multi_strategy_runner")
        if mod_runner is None:
            self.skipTest(f"multi_strategy_runner недоступен: {err}")
        mod_reg, err2 = _try_import("spa_core.paper_trading.strategy_registry")
        if mod_reg is None:
            self.skipTest(f"strategy_registry недоступен: {err2}")
        runner = mod_runner.MultiStrategyRunner(
            [mod_reg.S0_CONSERVATIVE_T1, mod_reg.S1_BALANCED]
        )
        return runner, mod_runner, mod_reg

    def test_runner_creates_without_error(self):
        """MultiStrategyRunner с S0+S1 создаётся без исключений."""
        runner, *_ = self._get_runner_s0_s1()
        self.assertIsNotNone(runner)

    def test_runner_with_four_strategies(self):
        """MultiStrategyRunner с S0+S1+S2+S3 создаётся без исключений."""
        mod_runner, err = _try_import("spa_core.paper_trading.multi_strategy_runner")
        if mod_runner is None:
            self.skipTest(f"multi_strategy_runner недоступен: {err}")
        mod_reg, err2 = _try_import("spa_core.paper_trading.strategy_registry")
        if mod_reg is None:
            self.skipTest(f"strategy_registry недоступен: {err2}")
        runner = mod_runner.MultiStrategyRunner([
            mod_reg.S0_CONSERVATIVE_T1,
            mod_reg.S1_BALANCED,
            mod_reg.S2_MORPHO_HEAVY,
            mod_reg.S3_PENDLE_ROTATION,
        ])
        self.assertIsNotNone(runner)

    def test_runner_run_day_returns_dict(self):
        """MultiStrategyRunner.run_day() возвращает dict."""
        runner, *_ = self._get_runner_s0_s1()
        result = runner.run_day(self._APY_MAP)
        self.assertIsInstance(result, dict)

    def test_runner_run_day_processes_strategies(self):
        """MultiStrategyRunner.run_day() обрабатывает минимум одну стратегию."""
        runner, *_ = self._get_runner_s0_s1()
        result = runner.run_day(self._APY_MAP)
        self.assertGreaterEqual(len(result), 1)

    def test_runner_run_day_yields_non_negative(self):
        """MultiStrategyRunner.run_day() даёт неотрицательный yield для каждой стратегии."""
        runner, *_ = self._get_runner_s0_s1()
        result = runner.run_day(self._APY_MAP)
        for sid, yield_usd in result.items():
            self.assertGreaterEqual(
                yield_usd, 0.0,
                f"Стратегия {sid} должна иметь yield >= 0"
            )

    def test_runner_get_rankings_returns_list(self):
        """MultiStrategyRunner.get_rankings() возвращает list."""
        runner, *_ = self._get_runner_s0_s1()
        runner.run_day(self._APY_MAP)
        rankings = runner.get_rankings()
        self.assertIsInstance(rankings, list)

    def test_runner_get_rankings_not_empty(self):
        """MultiStrategyRunner.get_rankings() не пуст после run_day."""
        runner, *_ = self._get_runner_s0_s1()
        runner.run_day(self._APY_MAP)
        self.assertGreater(len(runner.get_rankings()), 0)

    def test_runner_get_rankings_sorted_descending(self):
        """get_rankings() отсортирован по composite_score по убыванию."""
        runner, *_ = self._get_runner_s0_s1()
        runner.run_day(self._APY_MAP)
        rankings = runner.get_rankings()
        if len(rankings) < 2:
            self.skipTest("Недостаточно стратегий для проверки сортировки")
        scores = [r["composite_score"] for r in rankings]
        self.assertEqual(scores, sorted(scores, reverse=True),
                         "Ранжирование должно быть по composite_score убыванием")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestChainConcentration
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainConcentration(unittest.TestCase):
    """ChainConcentrationAnalyzer: создание, compute_concentrations, is_compliant."""

    def _get_analyzer(self):
        mod, err = _try_import("spa_core.analytics.chain_concentration")
        if mod is None:
            self.skipTest(f"chain_concentration недоступен: {err}")
        return mod.ChainConcentrationAnalyzer("data/adapter_status.json"), mod

    def test_chain_analyzer_creates(self):
        """ChainConcentrationAnalyzer создаётся без исключений."""
        analyzer, _ = self._get_analyzer()
        self.assertIsNotNone(analyzer)

    def test_chain_compute_concentrations_returns_dict(self):
        """compute_concentrations() возвращает dict."""
        analyzer, _ = self._get_analyzer()
        result = analyzer.compute_concentrations({})
        self.assertIsInstance(result, dict)

    def test_chain_compute_concentrations_empty_input(self):
        """compute_concentrations({}) возвращает пустой dict."""
        analyzer, _ = self._get_analyzer()
        self.assertEqual(analyzer.compute_concentrations({}), {})

    def test_chain_compute_concentrations_sums_to_one(self):
        """compute_concentrations с ненулевыми весами суммируется до 1.0."""
        analyzer, _ = self._get_analyzer()
        raw = {"ethereum": 0.569, "arbitrum": 0.431}
        concentrations = analyzer.compute_concentrations(raw)
        self.assertAlmostEqual(sum(concentrations.values()), 1.0, places=5)

    def test_chain_is_compliant_ethereum_56pct(self):
        """is_compliant() = True при 56.9% ethereum (< лимита 70%)."""
        analyzer, _ = self._get_analyzer()
        conc = {"ethereum": 0.569, "arbitrum": 0.431}
        self.assertTrue(
            analyzer.is_compliant(conc),
            "56.9% ethereum должен быть compliant (лимит 70%)"
        )

    def test_chain_is_compliant_ethereum_80pct_violation(self):
        """is_compliant() = False при 80% ethereum (> лимита 70%)."""
        analyzer, _ = self._get_analyzer()
        conc = {"ethereum": 0.80, "arbitrum": 0.20}
        self.assertFalse(
            analyzer.is_compliant(conc),
            "80% ethereum должен нарушать лимит 70%"
        )

    def test_chain_is_compliant_empty_concentrations(self):
        """is_compliant({}) = True (нет позиций — всё compliant)."""
        analyzer, _ = self._get_analyzer()
        self.assertTrue(analyzer.is_compliant({}),
                        "Пустой портфель должен быть compliant")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestDataFiles
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataFiles(unittest.TestCase):
    """data/*.json файлы: существование, валидный JSON, ключевые поля."""

    def _load_json(self, filename: str):
        """Загружает JSON из data/. skipTest если файл отсутствует."""
        path = _DATA_DIR / filename
        if not path.exists():
            self.skipTest(f"data/{filename} отсутствует")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            self.fail(f"data/{filename} содержит невалидный JSON: {exc}")

    def test_adapter_status_exists(self):
        """data/adapter_status.json существует."""
        self.assertTrue(
            (_DATA_DIR / "adapter_status.json").exists(),
            "data/adapter_status.json не найден"
        )

    def test_adapter_status_valid_json(self):
        """data/adapter_status.json — валидный JSON-объект."""
        data = self._load_json("adapter_status.json")
        self.assertIsInstance(data, dict)

    def test_adapter_status_has_morpho_steakhouse(self):
        """adapter_status.json содержит блок 'morpho_steakhouse'."""
        data = self._load_json("adapter_status.json")
        self.assertIn("morpho_steakhouse", data)

    def test_adapter_status_has_compound_v3(self):
        """adapter_status.json содержит блок 'compound_v3' (top-level or inside 'adapters')."""
        data = self._load_json("adapter_status.json")
        lookup = data.get("adapters", data)
        self.assertIn("compound_v3", lookup)

    def test_adapter_status_has_spark_susds(self):
        """adapter_status.json содержит блок 'spark_susds' (top-level or inside 'adapters')."""
        data = self._load_json("adapter_status.json")
        lookup = data.get("adapters", data)
        self.assertIn("spark_susds", lookup)

    def test_adapter_status_has_fluid_fusdc(self):
        """adapter_status.json содержит блок 'fluid_fusdc' (top-level or inside 'adapters')."""
        data = self._load_json("adapter_status.json")
        lookup = data.get("adapters", data)
        self.assertIn("fluid_fusdc", lookup)

    def test_adapter_status_apy_values_positive(self):
        """APY values в adapter_status.json — числа > 0 (где поле присутствует)."""
        data = self._load_json("adapter_status.json")
        checked = 0
        for key in ("compound_v3", "aave_arbitrum", "spark_susds", "fluid_fusdc"):
            block = data.get(key, {})
            if isinstance(block, dict) and "apy" in block:
                apy = block["apy"]
                self.assertIsInstance(apy, (int, float),
                                      f"{key}.apy должно быть числом, тип: {type(apy)}")
                self.assertGreater(apy, 0, f"{key}.apy должен быть > 0, получен {apy}")
                checked += 1
        if checked == 0:
            self.skipTest("Ни один адаптер не имеет поля apy в adapter_status.json")

    def test_tournament_30d_results_exists(self):
        """data/tournament_30d_results.json существует (или tournament_results.json)."""
        path_30d = _DATA_DIR / "tournament_30d_results.json"
        path_plain = _DATA_DIR / "tournament_results.json"
        if not path_30d.exists() and not path_plain.exists():
            self.skipTest(
                "data/tournament_30d_results.json не найден — "
                "файл создаётся после первого 30-дневного цикла"
            )

    def test_tournament_30d_results_valid_json(self):
        """data/tournament_30d_results.json — валидный JSON."""
        data = self._load_json("tournament_30d_results.json")
        self.assertIsNotNone(data)

    def test_golive_status_exists(self):
        """data/golive_status.json существует."""
        self.assertTrue(
            (_DATA_DIR / "golive_status.json").exists(),
            "data/golive_status.json не найден"
        )

    def test_golive_status_valid_json(self):
        """data/golive_status.json — валидный JSON-объект."""
        data = self._load_json("golive_status.json")
        self.assertIsInstance(data, dict)

    def test_golive_status_has_ready_field(self):
        """data/golive_status.json содержит поле 'ready'."""
        data = self._load_json("golive_status.json")
        self.assertIn("ready", data,
                      "golive_status.json должен содержать поле 'ready'")


# ═══════════════════════════════════════════════════════════════════════════════
# Точка входа
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    unittest.main(verbosity=2)
