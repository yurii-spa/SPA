"""
spa_core/tests/test_multi_strategy_and_s1.py — MP-357, MP-358

120+ unittest-кейсов:
  - MultiStrategyRunner: init, run_day, get_rankings, get_active_strategies,
    get_total_yield, get_allocation_map, export_results (атомарность, JSON-формат)
  - S1T1T2BalancedStrategy: init, compute_weighted_apy (формула, fallback),
    simulate_day (yield, positions, history), to_vportfolio_format
  - Registry: paper_trading STRATEGY_REGISTRY, strategies REGISTRY
  - Константы: DEFAULT_APY, TARGET_WEIGHTS, STRATEGY_ID

Правила:
  - stdlib only, никаких внешних зависимостей
  - Все тесты изолированы (tempdir / отдельные инстансы)
  - Комментарии на русском
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# ─── sys.path (позволяет запускать из любого CWD) ─────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемых модулей ──────────────────────────────────────────────
from spa_core.paper_trading.strategy_registry import (
    STRATEGY_REGISTRY,
    StrategyConfig,
    S0_CONSERVATIVE_T1,
    S1_BALANCED,
    S2_MORPHO_HEAVY,
)
from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner
from spa_core.strategies.s1_t1t2_balanced import (
    S1T1T2BalancedStrategy,
    STRATEGY_ID,
    STRATEGY_NAME,
    STRATEGY_RISK_LEVEL,
    DEFAULT_APY,
    TARGET_WEIGHTS,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
    KILL_DRAWDOWN_PCT,
)
from spa_core.strategies.strategy_registry import REGISTRY


# ─── Вспомогательные данные ───────────────────────────────────────────────────

# Стандартная apy_map для большинства тестов
APY_MAP_STD = {"aave_v3": 4.2, "morpho_blue": 6.5, "compound_v3": 4.8}
# APY_MAP с высокими значениями для тестирования yield
APY_MAP_HIGH = {"aave_v3": 10.0, "morpho_blue": 12.0, "compound_v3": 9.0}
# APY_MAP с нулями
APY_MAP_ZERO = {"aave_v3": 0.0, "morpho_blue": 0.0, "compound_v3": 0.0}


def _make_simple_runner(n: int = 2, capital: float = 100_000.0) -> MultiStrategyRunner:
    """Вспомогательная фабрика: раннер из n стратегий."""
    strategies = [S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY][:n]
    return MultiStrategyRunner(strategies, capital=capital)


def _make_killed_config(id: str = "KILL_TEST") -> StrategyConfig:
    """Вспомогательная фабрика: killed StrategyConfig."""
    return StrategyConfig(
        id=id,
        name=f"Killed {id}",
        description="Test killed strategy",
        allocations={"aave_v3": 0.50, "morpho_blue": 0.40},
        tier="T1",
        target_apy_min=2.0,
        target_apy_max=5.0,
        status="killed",
    )


def _make_paused_config(id: str = "PAUSE_TEST") -> StrategyConfig:
    """Вспомогательная фабрика: paused StrategyConfig."""
    return StrategyConfig(
        id=id,
        name=f"Paused {id}",
        description="Test paused strategy",
        allocations={"aave_v3": 0.50, "morpho_blue": 0.40},
        tier="T1",
        target_apy_min=2.0,
        target_apy_max=5.0,
        status="paused",
    )


def _make_promoted_config(id: str = "PROMO_TEST") -> StrategyConfig:
    """Вспомогательная фабрика: promoted StrategyConfig."""
    return StrategyConfig(
        id=id,
        name=f"Promoted {id}",
        description="Test promoted strategy",
        allocations={"aave_v3": 0.50, "morpho_blue": 0.40},
        tier="T1",
        target_apy_min=2.0,
        target_apy_max=5.0,
        status="promoted",
    )


# =============================================================================
# БЛОК 1: MultiStrategyRunner — Инициализация
# =============================================================================

class TestMultiStrategyRunnerInit(unittest.TestCase):

    def test_empty_strategies_creates_runner(self):
        """Пустой список стратегий — runner создаётся без ошибок."""
        runner = MultiStrategyRunner([])
        self.assertIsNotNone(runner)
        self.assertEqual(len(runner._portfolios), 0)

    def test_single_strategy_one_portfolio(self):
        """Одна стратегия → один портфель."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        self.assertEqual(len(runner._portfolios), 1)
        self.assertIn("S0", runner._portfolios)

    def test_two_strategies_two_portfolios(self):
        """Две стратегии → два портфеля."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        self.assertEqual(len(runner._portfolios), 2)
        self.assertIn("S0", runner._portfolios)
        self.assertIn("S1", runner._portfolios)

    def test_three_strategies_three_portfolios(self):
        """Три стратегии → три портфеля."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY])
        self.assertEqual(len(runner._portfolios), 3)

    def test_default_capital_100k(self):
        """Дефолтный капитал — $100K."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        self.assertEqual(runner.capital, 100_000.0)

    def test_custom_capital_applied(self):
        """Кастомный капитал сохраняется в runner и портфеле."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=50_000.0)
        self.assertEqual(runner.capital, 50_000.0)
        vp = runner._portfolios["S0"]
        self.assertAlmostEqual(vp.capital_usd, 50_000.0, places=2)

    def test_portfolio_initial_equity_equals_capital(self):
        """Начальный equity портфеля ≈ капиталу."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=100_000.0)
        vp = runner._portfolios["S0"]
        self.assertAlmostEqual(vp.current_equity, 100_000.0, delta=1.0)

    def test_strategy_status_preserved(self):
        """Статус StrategyConfig переносится в VPortfolio."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        vp = runner._portfolios["S0"]
        self.assertEqual(vp.status, S0_CONSERVATIVE_T1.status)

    def test_last_day_yields_empty_initially(self):
        """_last_day_yields пустой до первого run_day."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        self.assertEqual(runner._last_day_yields, {})

    def test_strategies_index_correct(self):
        """_strategies индекс содержит переданные конфиги."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        self.assertIn("S0", runner._strategies)
        self.assertIn("S1", runner._strategies)
        self.assertIs(runner._strategies["S0"], S0_CONSERVATIVE_T1)


# =============================================================================
# БЛОК 2: MultiStrategyRunner — run_day
# =============================================================================

class TestMultiStrategyRunnerRunDay(unittest.TestCase):

    def setUp(self):
        self.runner = MultiStrategyRunner(
            [S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY],
            capital=100_000.0,
        )

    def test_run_day_returns_dict(self):
        """run_day возвращает словарь."""
        result = self.runner.run_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_run_day_keys_are_strategy_ids(self):
        """Ключи результата — id стратегий."""
        result = self.runner.run_day(APY_MAP_STD)
        for sid in result:
            self.assertIn(sid, self.runner._portfolios)

    def test_run_day_positive_apy_positive_yield(self):
        """Положительные APY → положительный yield для каждой стратегии."""
        result = self.runner.run_day(APY_MAP_STD)
        for sid, yield_usd in result.items():
            self.assertGreater(yield_usd, 0.0, f"Стратегия {sid}: yield должен быть > 0")

    def test_run_day_zero_apy_zero_yield(self):
        """Нулевые APY → нулевой yield."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=100_000.0)
        result = runner.run_day(APY_MAP_ZERO)
        for yield_usd in result.values():
            self.assertAlmostEqual(yield_usd, 0.0, places=8)

    def test_run_day_killed_strategy_skipped(self):
        """Killed стратегия не появляется в результате."""
        killed = _make_killed_config("KILL_RD")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, killed])
        result = runner.run_day(APY_MAP_STD)
        self.assertNotIn("KILL_RD", result)
        self.assertIn("S0", result)

    def test_run_day_paused_strategy_skipped(self):
        """Paused стратегия не появляется в результате."""
        paused = _make_paused_config("PAUSE_RD")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, paused])
        result = runner.run_day(APY_MAP_STD)
        self.assertNotIn("PAUSE_RD", result)
        self.assertIn("S0", result)

    def test_run_day_missing_protocol_no_error(self):
        """Отсутствующий протокол в apy_map не вызывает исключение."""
        result = self.runner.run_day({"aave_v3": 4.0})
        self.assertIsInstance(result, dict)

    def test_run_day_empty_apy_map_no_error(self):
        """Пустая apy_map не вызывает исключение."""
        result = self.runner.run_day({})
        self.assertIsInstance(result, dict)

    def test_run_day_increments_days_simulated(self):
        """После run_day счётчик days_simulated = 1."""
        self.runner.run_day(APY_MAP_STD)
        vp = self.runner._portfolios["S0"]
        self.assertEqual(vp.days_simulated, 1)

    def test_run_day_twice_increments_days_to_2(self):
        """Два вызова run_day → days_simulated = 2."""
        self.runner.run_day(APY_MAP_STD)
        self.runner.run_day(APY_MAP_STD)
        vp = self.runner._portfolios["S0"]
        self.assertEqual(vp.days_simulated, 2)

    def test_run_day_updates_last_day_yields(self):
        """_last_day_yields обновляется после run_day."""
        self.runner.run_day(APY_MAP_STD)
        self.assertGreater(len(self.runner._last_day_yields), 0)

    def test_run_day_high_apy_bigger_yield(self):
        """Высокие APY дают больший yield, чем стандартные."""
        runner1 = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=100_000.0)
        runner2 = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=100_000.0)
        r1 = runner1.run_day(APY_MAP_STD)
        r2 = runner2.run_day(APY_MAP_HIGH)
        self.assertGreater(r2["S0"], r1["S0"])

    def test_run_day_empty_runner_returns_empty(self):
        """Пустой runner → пустой результат run_day."""
        runner = MultiStrategyRunner([])
        result = runner.run_day(APY_MAP_STD)
        self.assertEqual(result, {})


# =============================================================================
# БЛОК 3: MultiStrategyRunner — get_rankings
# =============================================================================

class TestMultiStrategyRunnerGetRankings(unittest.TestCase):

    def setUp(self):
        self.strategies = [S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY]
        self.runner = MultiStrategyRunner(self.strategies, capital=100_000.0)
        # Запускаем 5 дней для накопления истории
        for _ in range(5):
            self.runner.run_day(APY_MAP_STD)

    def test_returns_list(self):
        """get_rankings возвращает список."""
        self.assertIsInstance(self.runner.get_rankings(), list)

    def test_length_equals_strategies_count(self):
        """Длина списка = числу стратегий."""
        self.assertEqual(len(self.runner.get_rankings()), 3)

    def test_sorted_by_composite_score_desc(self):
        """Список отсортирован по composite_score убыванию."""
        rankings = self.runner.get_rankings()
        scores = [r["composite_score"] for r in rankings]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_has_rank_field(self):
        """Каждый элемент имеет поле rank."""
        for r in self.runner.get_rankings():
            self.assertIn("rank", r)

    def test_rank_starts_at_1(self):
        """Первый ранг = 1."""
        self.assertEqual(self.runner.get_rankings()[0]["rank"], 1)

    def test_ranks_sequential(self):
        """Ранги последовательны: 1, 2, 3, …"""
        ranks = [r["rank"] for r in self.runner.get_rankings()]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_has_strategy_id(self):
        """Каждый элемент имеет strategy_id."""
        for r in self.runner.get_rankings():
            self.assertIn("strategy_id", r)
            self.assertIsInstance(r["strategy_id"], str)

    def test_has_composite_score(self):
        """Каждый элемент имеет composite_score."""
        for r in self.runner.get_rankings():
            self.assertIn("composite_score", r)

    def test_composite_score_in_0_1_range(self):
        """composite_score ∈ [0, 1]."""
        for r in self.runner.get_rankings():
            self.assertGreaterEqual(r["composite_score"], 0.0)
            self.assertLessEqual(r["composite_score"], 1.0)

    def test_has_net_apy(self):
        """Каждый элемент имеет net_apy."""
        for r in self.runner.get_rankings():
            self.assertIn("net_apy", r)

    def test_has_is_active(self):
        """Каждый элемент имеет is_active."""
        for r in self.runner.get_rankings():
            self.assertIn("is_active", r)
            self.assertIsInstance(r["is_active"], bool)

    def test_has_days_running(self):
        """Каждый элемент имеет days_running."""
        for r in self.runner.get_rankings():
            self.assertIn("days_running", r)
            self.assertIsInstance(r["days_running"], int)

    def test_all_strategy_ids_present(self):
        """Все strategy_id присутствуют в rankings."""
        ids = {r["strategy_id"] for r in self.runner.get_rankings()}
        for s in self.strategies:
            self.assertIn(s.id, ids)

    def test_days_running_equals_simulated(self):
        """days_running в rankings = days_simulated в VPortfolio."""
        for r in self.runner.get_rankings():
            sid = r["strategy_id"]
            vp = self.runner._portfolios[sid]
            self.assertEqual(r["days_running"], vp.days_simulated)

    def test_empty_runner_returns_empty(self):
        """Пустой runner → пустые rankings."""
        runner = MultiStrategyRunner([])
        self.assertEqual(runner.get_rankings(), [])

    def test_single_strategy_rank_1(self):
        """Одна стратегия → ранг 1."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        for _ in range(3):
            runner.run_day(APY_MAP_STD)
        rankings = runner.get_rankings()
        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0]["rank"], 1)


# =============================================================================
# БЛОК 4: MultiStrategyRunner — get_active_strategies
# =============================================================================

class TestMultiStrategyRunnerGetActive(unittest.TestCase):

    def test_all_active_returns_all(self):
        """Все стратегии активны → get_active_strategies возвращает все."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        active = runner.get_active_strategies()
        self.assertEqual(len(active), 2)

    def test_killed_excluded(self):
        """Killed стратегия исключается из активных."""
        killed = _make_killed_config("K_ACT")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, killed])
        ids = [s.id for s in runner.get_active_strategies()]
        self.assertIn("S0", ids)
        self.assertNotIn("K_ACT", ids)

    def test_paused_excluded(self):
        """Paused стратегия исключается из активных."""
        paused = _make_paused_config("P_ACT")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, paused])
        ids = [s.id for s in runner.get_active_strategies()]
        self.assertNotIn("P_ACT", ids)
        self.assertIn("S0", ids)

    def test_promoted_included(self):
        """Promoted стратегия входит в активные."""
        promoted = _make_promoted_config("PR_ACT")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, promoted])
        ids = [s.id for s in runner.get_active_strategies()]
        self.assertIn("PR_ACT", ids)

    def test_empty_runner_empty_active(self):
        """Пустой runner → пустой список активных."""
        runner = MultiStrategyRunner([])
        self.assertEqual(runner.get_active_strategies(), [])

    def test_all_killed_returns_empty(self):
        """Все killed → пустой список активных."""
        k1 = _make_killed_config("K1_ACT")
        k2 = _make_killed_config("K2_ACT")
        runner = MultiStrategyRunner([k1, k2])
        self.assertEqual(runner.get_active_strategies(), [])


# =============================================================================
# БЛОК 5: MultiStrategyRunner — get_total_yield
# =============================================================================

class TestMultiStrategyRunnerGetTotalYield(unittest.TestCase):

    def test_zero_before_run_day(self):
        """Yield = 0.0 до первого run_day."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        self.assertEqual(runner.get_total_yield(), 0.0)

    def test_positive_after_run_day(self):
        """Yield > 0 после run_day с позитивными APY."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day(APY_MAP_STD)
        self.assertGreater(runner.get_total_yield(), 0.0)

    def test_total_equals_sum_of_active_yields(self):
        """Общий yield = сумма yield активных стратегий из run_day."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        day_result = runner.run_day(APY_MAP_STD)
        expected = sum(day_result.values())
        self.assertAlmostEqual(runner.get_total_yield(), expected, places=8)

    def test_killed_excluded_from_total(self):
        """Yield killed стратегии не включается в total (она не участвовала в run_day)."""
        killed = _make_killed_config("K_YIELD")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, killed])
        runner.run_day(APY_MAP_STD)
        # KILL_YIELD не участвовал в run_day, только S0
        total = runner.get_total_yield()
        self.assertGreater(total, 0.0)
        # Убедимся, что killed не в _last_day_yields
        self.assertNotIn("K_YIELD", runner._last_day_yields)

    def test_zero_apy_zero_total(self):
        """Нулевые APY → нулевой total_yield."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=100_000.0)
        runner.run_day(APY_MAP_ZERO)
        self.assertAlmostEqual(runner.get_total_yield(), 0.0, places=8)


# =============================================================================
# БЛОК 6: MultiStrategyRunner — get_allocation_map
# =============================================================================

class TestMultiStrategyRunnerAllocationMap(unittest.TestCase):

    def test_empty_runner_empty_map(self):
        """Нет стратегий → пустой allocation_map."""
        runner = MultiStrategyRunner([])
        self.assertEqual(runner.get_allocation_map(), {})

    def test_all_killed_empty_map(self):
        """Все killed → пустой allocation_map."""
        k1 = _make_killed_config("K1_AM")
        k2 = _make_killed_config("K2_AM")
        runner = MultiStrategyRunner([k1, k2])
        self.assertEqual(runner.get_allocation_map(), {})

    def test_single_active_full_allocation(self):
        """Одна активная стратегия → 100% аллокация."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        alloc = runner.get_allocation_map()
        self.assertIn("S0", alloc)
        self.assertAlmostEqual(alloc["S0"], 1.0, places=9)

    def test_two_strategies_equal_split(self):
        """Две активные → 50/50."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        alloc = runner.get_allocation_map()
        self.assertAlmostEqual(alloc["S0"], 0.5, places=9)
        self.assertAlmostEqual(alloc["S1"], 0.5, places=9)

    def test_three_strategies_equal_split(self):
        """Три активные → 1/3 каждой."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY])
        alloc = runner.get_allocation_map()
        for sid in ["S0", "S1", "S2"]:
            self.assertAlmostEqual(alloc[sid], 1.0 / 3.0, places=9)

    def test_sum_equals_one(self):
        """Сумма всех аллокаций = 1.0."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED, S2_MORPHO_HEAVY])
        alloc = runner.get_allocation_map()
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)

    def test_killed_excluded_from_allocation(self):
        """Killed стратегия не получает аллокации."""
        killed = _make_killed_config("K_MAP")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, killed])
        alloc = runner.get_allocation_map()
        self.assertNotIn("K_MAP", alloc)
        self.assertIn("S0", alloc)
        self.assertAlmostEqual(alloc["S0"], 1.0, places=9)

    def test_promoted_included_in_allocation(self):
        """Promoted стратегия получает аллокацию."""
        promoted = _make_promoted_config("PR_MAP")
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, promoted])
        alloc = runner.get_allocation_map()
        self.assertIn("PR_MAP", alloc)
        self.assertAlmostEqual(alloc["PR_MAP"], 0.5, places=9)


# =============================================================================
# БЛОК 7: MultiStrategyRunner — export_results
# =============================================================================

class TestMultiStrategyRunnerExportResults(unittest.TestCase):

    def setUp(self):
        self.runner = MultiStrategyRunner(
            [S0_CONSERVATIVE_T1, S1_BALANCED], capital=100_000.0
        )
        for _ in range(3):
            self.runner.run_day(APY_MAP_STD)

    def _export_and_load(self, runner=None) -> dict:
        """Вспомогательный метод: экспорт во tmpdir и загрузка JSON."""
        r = runner or self.runner
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ranking.json"
            r.export_results(path)
            with open(path, "r") as f:
                return json.load(f)

    def test_creates_file(self):
        """export_results создаёт файл на диске."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ranking.json"
            self.runner.export_results(path)
            self.assertTrue(path.exists())

    def test_valid_json(self):
        """Экспортированный файл — валидный JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ranking.json"
            self.runner.export_results(path)
            with open(path, "r") as f:
                doc = json.load(f)
            self.assertIsInstance(doc, dict)

    def test_has_timestamp(self):
        """JSON содержит поле timestamp (строка ISO)."""
        doc = self._export_and_load()
        self.assertIn("timestamp", doc)
        self.assertIsInstance(doc["timestamp"], str)
        # Должно содержать дату
        self.assertIn("2026", doc["timestamp"])

    def test_has_strategies_list(self):
        """JSON содержит список strategies."""
        doc = self._export_and_load()
        self.assertIn("strategies", doc)
        self.assertIsInstance(doc["strategies"], list)

    def test_strategies_count_correct(self):
        """Число стратегий в JSON = 2 (столько передали)."""
        doc = self._export_and_load()
        self.assertEqual(len(doc["strategies"]), 2)

    def test_has_total_active(self):
        """JSON содержит поле total_active (int)."""
        doc = self._export_and_load()
        self.assertIn("total_active", doc)
        self.assertIsInstance(doc["total_active"], int)

    def test_total_active_correct(self):
        """total_active = 2 (обе стратегии активны)."""
        doc = self._export_and_load()
        self.assertEqual(doc["total_active"], 2)

    def test_has_weighted_apy(self):
        """JSON содержит поле weighted_apy."""
        doc = self._export_and_load()
        self.assertIn("weighted_apy", doc)
        self.assertIsInstance(doc["weighted_apy"], float)

    def test_no_tmp_files_after_write(self):
        """После атомарной записи не остаётся .tmp-файлов."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ranking.json"
            self.runner.export_results(path)
            tmp_files = list(Path(tmpdir).glob(".tmp_*"))
            self.assertEqual(len(tmp_files), 0, f"Найдены tmp-файлы: {tmp_files}")

    def test_strategy_entry_has_rank(self):
        """Каждая запись стратегии имеет поле rank."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("rank", s)

    def test_strategy_entry_has_composite_score(self):
        """Каждая запись стратегии имеет composite_score."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("composite_score", s)

    def test_strategy_entry_has_strategy_id(self):
        """Каждая запись стратегии имеет strategy_id."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("strategy_id", s)

    def test_strategy_entry_has_net_apy(self):
        """Каждая запись стратегии имеет net_apy."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("net_apy", s)

    def test_strategy_entry_has_is_active(self):
        """Каждая запись стратегии имеет is_active (bool)."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("is_active", s)
            self.assertIsInstance(s["is_active"], bool)

    def test_strategy_entry_has_days_running(self):
        """Каждая запись стратегии имеет days_running (int)."""
        doc = self._export_and_load()
        for s in doc["strategies"]:
            self.assertIn("days_running", s)
            self.assertIsInstance(s["days_running"], int)

    def test_ranks_sorted_ascending(self):
        """Стратегии в JSON упорядочены по rank возрастанию."""
        doc = self._export_and_load()
        ranks = [s["rank"] for s in doc["strategies"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_accepts_string_path(self):
        """export_results принимает строку как путь."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path_str = os.path.join(tmpdir, "ranking.json")
            self.runner.export_results(path_str)
            self.assertTrue(os.path.exists(path_str))

    def test_creates_parent_dir(self):
        """export_results создаёт родительскую директорию при необходимости."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "sub" / "deep" / "ranking.json"
            self.runner.export_results(nested)
            self.assertTrue(nested.exists())

    def test_overwrite_existing_file(self):
        """export_results перезаписывает существующий файл (атомарно)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ranking.json"
            self.runner.export_results(path)
            # Второй вызов не должен падать
            self.runner.run_day(APY_MAP_STD)
            self.runner.export_results(path)
            with open(path, "r") as f:
                doc = json.load(f)
            self.assertIn("strategies", doc)


# =============================================================================
# БЛОК 8: S1T1T2BalancedStrategy — Инициализация
# =============================================================================

class TestS1Init(unittest.TestCase):

    def test_default_capital(self):
        """Дефолтный капитал — $100K."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s.capital, 100_000.0)

    def test_custom_capital(self):
        """Кастомный капитал применяется."""
        s = S1T1T2BalancedStrategy(capital=50_000.0)
        self.assertEqual(s.capital, 50_000.0)

    def test_strategy_id_value(self):
        """strategy_id == 's1_t1t2_balanced'."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s.strategy_id, "s1_t1t2_balanced")
        self.assertEqual(s.strategy_id, STRATEGY_ID)

    def test_risk_level_low(self):
        """risk_level == 'LOW'."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s.risk_level, "LOW")
        self.assertEqual(s.risk_level, STRATEGY_RISK_LEVEL)

    def test_initial_positions_non_empty(self):
        """Начальные позиции не пустые (три протокола)."""
        s = S1T1T2BalancedStrategy()
        self.assertGreater(len(s._positions), 0)

    def test_initial_positions_three_protocols(self):
        """Начальные позиции: три протокола (aave, morpho, compound)."""
        s = S1T1T2BalancedStrategy()
        for proto in ["aave_v3", "morpho_blue", "compound_v3"]:
            self.assertIn(proto, s._positions)

    def test_initial_positions_sum_to_capital(self):
        """Сумма начальных позиций = капиталу (TARGET_WEIGHTS суммируются к 1.0)."""
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        total = sum(s._positions.values())
        self.assertAlmostEqual(total, 100_000.0, places=4)

    def test_days_simulated_zero(self):
        """Начальный счётчик дней = 0."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s._days_simulated, 0)

    def test_total_yield_zero(self):
        """Начальный total_yield_usd = 0."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s._total_yield_usd, 0.0)

    def test_equity_history_empty(self):
        """Начальная equity_history пустая."""
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s._equity_history, [])

    def test_current_equity_equals_capital(self):
        """current_equity после init = capital."""
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        self.assertAlmostEqual(s.current_equity, 100_000.0, places=4)


# =============================================================================
# БЛОК 9: S1T1T2BalancedStrategy — compute_weighted_apy
# =============================================================================

class TestS1WeightedApy(unittest.TestCase):

    def setUp(self):
        self.s = S1T1T2BalancedStrategy()

    def test_default_apy_equals_5_24(self):
        """С DEFAULT_APY weighted_apy = 0.4*4.2 + 0.4*6.5 + 0.2*4.8 = 5.24%."""
        result = self.s.compute_weighted_apy(DEFAULT_APY)
        expected = 0.4 * 4.2 + 0.4 * 6.5 + 0.2 * 4.8
        self.assertAlmostEqual(result, expected, places=6)

    def test_exact_value_is_5_24(self):
        """Конкретная проверка числа: 5.24%."""
        self.assertAlmostEqual(self.s.compute_weighted_apy(DEFAULT_APY), 5.24, places=6)

    def test_custom_apy_map_formula(self):
        """Формула корректно применяется к произвольным APY."""
        apy_map = {"aave_v3": 5.0, "morpho_blue": 8.0, "compound_v3": 6.0}
        expected = 0.4 * 5.0 + 0.4 * 8.0 + 0.2 * 6.0  # = 2.0 + 3.2 + 1.2 = 6.4
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), expected, places=6)

    def test_missing_protocol_uses_default(self):
        """Отсутствующий в apy_map протокол → дефолтный APY."""
        apy_map = {"aave_v3": 5.0}   # morpho и compound не переданы
        expected = 0.4 * 5.0 + 0.4 * DEFAULT_APY["morpho_blue"] + 0.2 * DEFAULT_APY["compound_v3"]
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), expected, places=6)

    def test_equal_apy_preserves_value(self):
        """Все APY одинаковы → weighted_apy = этому значению."""
        apy_map = {"aave_v3": 10.0, "morpho_blue": 10.0, "compound_v3": 10.0}
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), 10.0, places=6)

    def test_zero_apy_returns_zero(self):
        """Все APY = 0 → weighted_apy = 0."""
        self.assertAlmostEqual(self.s.compute_weighted_apy(APY_MAP_ZERO), 0.0, places=6)

    def test_empty_apy_map_uses_all_defaults(self):
        """Пустая apy_map → weighted_apy из дефолтов = 5.24%."""
        result = self.s.compute_weighted_apy({})
        expected = 0.4 * DEFAULT_APY["aave_v3"] + 0.4 * DEFAULT_APY["morpho_blue"] + 0.2 * DEFAULT_APY["compound_v3"]
        self.assertAlmostEqual(result, expected, places=6)

    def test_weights_sum_to_one(self):
        """TARGET_WEIGHTS суммируются к 1.0."""
        self.assertAlmostEqual(sum(TARGET_WEIGHTS.values()), 1.0, places=9)

    def test_aave_weight_is_40pct(self):
        """Вес Aave V3 = 40%."""
        self.assertAlmostEqual(TARGET_WEIGHTS["aave_v3"], 0.40, places=9)

    def test_morpho_weight_is_40pct(self):
        """Вес Morpho Blue = 40%."""
        self.assertAlmostEqual(TARGET_WEIGHTS["morpho_blue"], 0.40, places=9)

    def test_compound_weight_is_20pct(self):
        """Вес Compound V3 = 20%."""
        self.assertAlmostEqual(TARGET_WEIGHTS["compound_v3"], 0.20, places=9)


# =============================================================================
# БЛОК 10: S1T1T2BalancedStrategy — simulate_day
# =============================================================================

class TestS1SimulateDay(unittest.TestCase):

    def setUp(self):
        self.s = S1T1T2BalancedStrategy(capital=100_000.0)

    def test_returns_dict(self):
        """simulate_day возвращает словарь."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_has_daily_yield_usd(self):
        """Результат содержит daily_yield_usd."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("daily_yield_usd", result)

    def test_positive_yield_with_positive_apy(self):
        """Положительные APY → daily_yield_usd > 0."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_zero_yield_with_zero_apy(self):
        """Нулевые APY → daily_yield_usd = 0."""
        result = self.s.simulate_day(APY_MAP_ZERO)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_has_positions(self):
        """Результат содержит positions (dict)."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("positions", result)
        self.assertIsInstance(result["positions"], dict)

    def test_has_weighted_apy(self):
        """Результат содержит weighted_apy."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("weighted_apy", result)

    def test_positions_grow_after_simulate(self):
        """После simulate_day стоимость позиций растёт."""
        before = sum(self.s._positions.values())
        self.s.simulate_day(APY_MAP_STD)
        after = sum(self.s._positions.values())
        self.assertGreater(after, before)

    def test_days_simulated_increments(self):
        """simulate_day увеличивает _days_simulated на 1."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(self.s._days_simulated, 1)

    def test_multiple_calls_accumulate_yield(self):
        """Несколько вызовов накапливают _total_yield_usd."""
        self.s.simulate_day(APY_MAP_STD)
        y1 = self.s._total_yield_usd
        self.s.simulate_day(APY_MAP_STD)
        y2 = self.s._total_yield_usd
        self.assertGreater(y2, y1)

    def test_fallback_apy_when_empty_map(self):
        """Пустая apy_map → используются DEFAULT_APY → тот же yield, что и с DEFAULT_APY."""
        s_default = S1T1T2BalancedStrategy(capital=100_000.0)
        s_empty   = S1T1T2BalancedStrategy(capital=100_000.0)
        r_default = s_default.simulate_day(DEFAULT_APY)
        r_empty   = s_empty.simulate_day({})
        self.assertAlmostEqual(r_default["daily_yield_usd"], r_empty["daily_yield_usd"], places=6)

    def test_higher_apy_higher_yield(self):
        """Более высокие APY дают больший yield."""
        s_low  = S1T1T2BalancedStrategy(capital=100_000.0)
        s_high = S1T1T2BalancedStrategy(capital=100_000.0)
        r_low  = s_low.simulate_day({"aave_v3": 1.0, "morpho_blue": 1.0, "compound_v3": 1.0})
        r_high = s_high.simulate_day(APY_MAP_HIGH)
        self.assertGreater(r_high["daily_yield_usd"], r_low["daily_yield_usd"])

    def test_equity_history_grows(self):
        """Каждый вызов simulate_day добавляет точку в _equity_history."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 1)
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 2)

    def test_yield_formula_exact(self):
        """Проверяем точную формулу: yield = Σ pos * apy/100/365 для каждой позиции."""
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        expected = 0.0
        for proto, weight in TARGET_WEIGHTS.items():
            pos = 100_000.0 * weight
            apy = APY_MAP_STD[proto]
            expected += pos * apy / 100.0 / 365.0
        result = s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["daily_yield_usd"], expected, places=4)

    def test_equity_history_entry_has_required_fields(self):
        """Запись в _equity_history содержит обязательные поля."""
        self.s.simulate_day(APY_MAP_STD)
        entry = self.s._equity_history[0]
        for field in ["day", "equity", "daily_yield_usd", "weighted_apy"]:
            self.assertIn(field, entry)


# =============================================================================
# БЛОК 11: S1T1T2BalancedStrategy — to_vportfolio_format
# =============================================================================

class TestS1VPortfolioFormat(unittest.TestCase):

    def setUp(self):
        self.s = S1T1T2BalancedStrategy(capital=100_000.0)
        self.s.simulate_day(APY_MAP_STD)

    def test_has_strategy_id(self):
        """to_vportfolio_format содержит strategy_id = STRATEGY_ID."""
        d = self.s.to_vportfolio_format()
        self.assertEqual(d["strategy_id"], STRATEGY_ID)

    def test_has_capital_usd(self):
        """to_vportfolio_format содержит capital_usd = 100K."""
        d = self.s.to_vportfolio_format()
        self.assertIn("capital_usd", d)
        self.assertAlmostEqual(d["capital_usd"], 100_000.0, places=2)

    def test_has_positions(self):
        """to_vportfolio_format содержит positions (непустой dict)."""
        d = self.s.to_vportfolio_format()
        self.assertIn("positions", d)
        self.assertIsInstance(d["positions"], dict)
        self.assertGreater(len(d["positions"]), 0)

    def test_positions_three_protocols(self):
        """positions содержит три протокола."""
        d = self.s.to_vportfolio_format()
        for proto in ["aave_v3", "morpho_blue", "compound_v3"]:
            self.assertIn(proto, d["positions"])

    def test_has_cash_usd(self):
        """to_vportfolio_format содержит cash_usd."""
        d = self.s.to_vportfolio_format()
        self.assertIn("cash_usd", d)

    def test_has_days_simulated(self):
        """to_vportfolio_format содержит days_simulated = 1."""
        d = self.s.to_vportfolio_format()
        self.assertIn("days_simulated", d)
        self.assertEqual(d["days_simulated"], 1)

    def test_has_total_yield_usd_positive(self):
        """to_vportfolio_format содержит total_yield_usd > 0 после simulate_day."""
        d = self.s.to_vportfolio_format()
        self.assertIn("total_yield_usd", d)
        self.assertGreater(d["total_yield_usd"], 0.0)

    def test_has_status_active(self):
        """to_vportfolio_format содержит status = 'active'."""
        d = self.s.to_vportfolio_format()
        self.assertIn("status", d)
        self.assertEqual(d["status"], "active")

    def test_has_current_equity_grown(self):
        """to_vportfolio_format содержит current_equity > initial capital (yield начислен)."""
        d = self.s.to_vportfolio_format()
        self.assertIn("current_equity", d)
        self.assertGreater(d["current_equity"], 100_000.0)

    def test_has_peak_equity(self):
        """to_vportfolio_format содержит peak_equity."""
        d = self.s.to_vportfolio_format()
        self.assertIn("peak_equity", d)

    def test_has_total_return_pct(self):
        """to_vportfolio_format содержит total_return_pct."""
        d = self.s.to_vportfolio_format()
        self.assertIn("total_return_pct", d)
        self.assertGreater(d["total_return_pct"], 0.0)

    def test_vportfolio_format_serializable(self):
        """to_vportfolio_format возвращает JSON-сериализуемый dict."""
        d = self.s.to_vportfolio_format()
        # Должно сериализоваться без ошибок
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)


# =============================================================================
# БЛОК 12: Реестр paper_trading STRATEGY_REGISTRY
# =============================================================================

class TestPaperTradingRegistry(unittest.TestCase):

    def test_s0_in_registry(self):
        """S0 существует в STRATEGY_REGISTRY."""
        self.assertIn("S0", STRATEGY_REGISTRY)

    def test_s1_in_registry(self):
        """S1 существует в STRATEGY_REGISTRY (Balanced T1+T2)."""
        self.assertIn("S1", STRATEGY_REGISTRY)

    def test_s1_tier_is_t1_t2(self):
        """S1 в paper_trading имеет tier T1+T2."""
        s1 = STRATEGY_REGISTRY["S1"]
        self.assertEqual(s1.tier, "T1+T2")

    def test_s1_target_apy_min_lte_6(self):
        """S1 target_apy_min ≤ 6.0%."""
        s1 = STRATEGY_REGISTRY["S1"]
        self.assertLessEqual(s1.target_apy_min, 6.0)

    def test_s1_target_apy_max_gte_7(self):
        """S1 target_apy_max ≥ 7.0%."""
        s1 = STRATEGY_REGISTRY["S1"]
        self.assertGreaterEqual(s1.target_apy_max, 7.0)

    def test_s1_allocations_sum_valid(self):
        """S1 allocations sum ≤ 1.0."""
        s1 = STRATEGY_REGISTRY["S1"]
        total = sum(s1.allocations.values())
        self.assertLessEqual(total, 1.0 + 1e-9)

    def test_s1_has_aave_allocation(self):
        """S1 имеет аллокацию Aave V3."""
        s1 = STRATEGY_REGISTRY["S1"]
        self.assertIn("aave_v3", s1.allocations)
        self.assertGreater(s1.allocations["aave_v3"], 0.0)


# =============================================================================
# БЛОК 13: Реестр strategies REGISTRY
# =============================================================================

class TestStrategiesRegistry(unittest.TestCase):

    def test_s1_t1t2_balanced_registered(self):
        """'s1_t1t2_balanced' зарегистрирован в REGISTRY."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta, "s1_t1t2_balanced не найден в REGISTRY")

    def test_s1_risk_tier_is_t2(self):
        """S1 T1+T2 Balanced имеет risk_tier='T2' (смешанный)."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")

    def test_s1_target_apy_min(self):
        """target_apy_min соответствует TARGET_APY_MIN = 6.0."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertAlmostEqual(meta.target_apy_min, TARGET_APY_MIN, places=4)

    def test_s1_target_apy_max(self):
        """target_apy_max соответствует TARGET_APY_MAX = 8.0."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertAlmostEqual(meta.target_apy_max, TARGET_APY_MAX, places=4)

    def test_s1_enabled(self):
        """S1 стратегия включена (enabled=True)."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertTrue(meta.enabled)

    def test_s1_type_lending(self):
        """S1 type = 'lending'."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.type, "lending")

    def test_s1_in_as_list(self):
        """s1_t1t2_balanced присутствует в REGISTRY.as_list()."""
        ids = [m.id for m in REGISTRY.as_list()]
        self.assertIn("s1_t1t2_balanced", ids)

    def test_s1_handler_class(self):
        """handler_class = 'S1T1T2BalancedStrategy'."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "S1T1T2BalancedStrategy")

    def test_s1_has_s1_tag(self):
        """Тег 's1' присутствует в тегах стратегии."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertIn("s1", meta.tags)

    def test_s1_apy_min_less_than_max(self):
        """target_apy_min < target_apy_max (валидный диапазон)."""
        meta = REGISTRY.get("s1_t1t2_balanced")
        self.assertIsNotNone(meta)
        self.assertLess(meta.target_apy_min, meta.target_apy_max)


# =============================================================================
# БЛОК 14: Константы S1
# =============================================================================

class TestS1Constants(unittest.TestCase):

    def test_strategy_id_value(self):
        """STRATEGY_ID = 's1_t1t2_balanced'."""
        self.assertEqual(STRATEGY_ID, "s1_t1t2_balanced")

    def test_strategy_name_value(self):
        """STRATEGY_NAME = 'S1 T1+T2 Balanced'."""
        self.assertEqual(STRATEGY_NAME, "S1 T1+T2 Balanced")

    def test_risk_level_low(self):
        """STRATEGY_RISK_LEVEL = 'LOW'."""
        self.assertEqual(STRATEGY_RISK_LEVEL, "LOW")

    def test_default_apy_aave(self):
        """DEFAULT_APY['aave_v3'] = 4.2."""
        self.assertAlmostEqual(DEFAULT_APY["aave_v3"], 4.2, places=4)

    def test_default_apy_morpho(self):
        """DEFAULT_APY['morpho_blue'] = 6.5."""
        self.assertAlmostEqual(DEFAULT_APY["morpho_blue"], 6.5, places=4)

    def test_default_apy_compound(self):
        """DEFAULT_APY['compound_v3'] = 4.8."""
        self.assertAlmostEqual(DEFAULT_APY["compound_v3"], 4.8, places=4)

    def test_target_apy_min(self):
        """TARGET_APY_MIN = 6.0."""
        self.assertAlmostEqual(TARGET_APY_MIN, 6.0, places=4)

    def test_target_apy_max(self):
        """TARGET_APY_MAX = 8.0."""
        self.assertAlmostEqual(TARGET_APY_MAX, 8.0, places=4)

    def test_kill_drawdown_pct(self):
        """KILL_DRAWDOWN_PCT = 0.05."""
        self.assertAlmostEqual(KILL_DRAWDOWN_PCT, 0.05, places=6)

    def test_default_apy_all_positive(self):
        """Все DEFAULT_APY > 0."""
        for proto, apy in DEFAULT_APY.items():
            self.assertGreater(apy, 0.0, f"DEFAULT_APY['{proto}'] должен быть > 0")

    def test_target_weights_aave(self):
        """TARGET_WEIGHTS['aave_v3'] = 0.40."""
        self.assertAlmostEqual(TARGET_WEIGHTS["aave_v3"], 0.40, places=9)

    def test_target_weights_morpho(self):
        """TARGET_WEIGHTS['morpho_blue'] = 0.40."""
        self.assertAlmostEqual(TARGET_WEIGHTS["morpho_blue"], 0.40, places=9)

    def test_target_weights_compound(self):
        """TARGET_WEIGHTS['compound_v3'] = 0.20."""
        self.assertAlmostEqual(TARGET_WEIGHTS["compound_v3"], 0.20, places=9)


# ─── Точка входа ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
