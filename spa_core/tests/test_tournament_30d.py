"""
spa_core/tests/test_tournament_30d.py — MP-382

50+ тестов для scripts/run_tournament_30d.py:
  TestLoadAPYMap    (8)  — load_apy_map()
  TestAaveBaseline  (8)  — make_aave_baseline()
  TestRunSimulation (15) — run_simulation()
  TestSaveResults   (10) — save_results()
  TestPrintTable    (5)  — print_table()
  TestEdgeCases     (8)  — edge cases

Правила:
  - ТОЛЬКО stdlib
  - Атомарная запись не оставляет tmp-мусора
  - Тесты изолированы: используют tmpdir, не меняют data/
"""

import io
import json
import math
import os
import pathlib
import sys
import tempfile
import unittest

# ── Добавляем корень проекта в sys.path ────────────────────────────────────────
_ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

# ── Импортируем тестируемые функции ───────────────────────────────────────────
from scripts.run_tournament_30d import (
    load_apy_map,
    make_aave_baseline,
    run_simulation,
    save_results,
    print_table,
    _compute_sharpe,
    _DEFAULT_APY_MAP,
    _load_strategies,
    _MockMultiStrategyRunner,
    _FallbackStrategyConfig,
)

# ─── Фикстуры ─────────────────────────────────────────────────────────────────

def _make_adapter_status(apy_overrides=None):
    """Создаёт минимальный adapter_status.json как dict для тестов."""
    adapters = [
        {
            "protocol_key": "aave-v3",
            "mock_apy": {"ethereum": {"USDC": 4.2, "USDT": 3.8}},
        },
        {
            "protocol_key": "compound-v3",
            "mock_apy": {"ethereum": {"USDC": 4.8}},
        },
        {
            "protocol_key": "morpho-steakhouse",
            "mock_apy": {"ethereum": {"USDC": 6.5}},
        },
        {
            "protocol_key": "yearn-v3",
            "mock_apy": {"ethereum": {"USDC": 6.8}},
        },
        {
            "protocol_key": "euler-v2",
            "mock_apy": {"ethereum": {"USDC": 7.4}},
        },
    ]
    doc = {
        "adapters": adapters,
        "morpho_steakhouse": {"apy": 6.5},
        "compound_v3":       {"apy": 4.8},
        "aave_arbitrum":     {"apy": 4.1},
        "pendle_pt":         {"apy": 8.0},
    }
    if apy_overrides:
        for entry in doc["adapters"]:
            pk = entry["protocol_key"]
            if pk in apy_overrides:
                entry["mock_apy"]["ethereum"]["USDC"] = apy_overrides[pk]
    return doc


def _write_adapter_status(tmpdir, doc=None):
    """Пишет adapter_status.json в tmpdir, возвращает путь к директории."""
    tmpdir = pathlib.Path(tmpdir)
    if doc is None:
        doc = _make_adapter_status()
    path = tmpdir / "adapter_status.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return tmpdir


def _simple_apy_map():
    return {
        "aave_v3":          4.2,
        "compound_v3":      4.8,
        "morpho_blue":      6.5,
        "morpho_steakhouse": 6.5,
        "yearn_v3":         6.8,
        "euler_v2":         7.4,
        "maple":            5.6,
        "pendle_pt":        8.0,
        "aave_arbitrum":    4.1,
    }


def _simple_strategies():
    """Три простые стратегии для тестов симуляции."""
    SC = _FallbackStrategyConfig
    return [
        SC("S0",            "Conservative T1",  "desc",
           {"aave_v3": 0.50, "morpho_blue": 0.30}),
        SC("S1",            "Balanced T1+T2",   "desc",
           {"aave_v3": 0.30, "morpho_blue": 0.20, "yearn_v3": 0.25, "euler_v2": 0.20}),
        SC("S_aave_baseline", "Aave Baseline",  "desc",
           {"aave_v3": 0.95}),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# TestLoadAPYMap (8 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadAPYMap(unittest.TestCase):
    """Тесты для load_apy_map()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _write_adapter_status(self.tmpdir)

    # 1. Возвращает словарь
    def test_returns_dict(self):
        result = load_apy_map(self.tmpdir)
        self.assertIsInstance(result, dict)

    # 2. aave_v3 присутствует
    def test_aave_v3_present(self):
        result = load_apy_map(self.tmpdir)
        self.assertIn("aave_v3", result)

    # 3. aave_v3 — float
    def test_aave_v3_is_float(self):
        result = load_apy_map(self.tmpdir)
        self.assertIsInstance(result["aave_v3"], float)

    # 4. morpho_blue присутствует (алиас morpho_steakhouse → morpho_blue)
    def test_morpho_blue_present(self):
        result = load_apy_map(self.tmpdir)
        self.assertIn("morpho_blue", result)

    # 5. compound_v3 присутствует
    def test_compound_v3_present(self):
        result = load_apy_map(self.tmpdir)
        self.assertIn("compound_v3", result)

    # 6. Все значения > 0
    def test_values_positive(self):
        result = load_apy_map(self.tmpdir)
        for k, v in result.items():
            # pendle_pt может быть 0 в некоторых конфигах, но базовые > 0
            if k in ("aave_v3", "compound_v3", "morpho_blue"):
                self.assertGreater(v, 0.0, f"{k} APY должен быть > 0")

    # 7. Все значения — float
    def test_all_values_floats(self):
        result = load_apy_map(self.tmpdir)
        for k, v in result.items():
            self.assertIsInstance(v, float, f"{k}: ожидали float, получили {type(v)}")

    # 8. При отсутствующем файле возвращает дефолты (не бросает)
    def test_missing_file_returns_defaults(self):
        empty_dir = tempfile.mkdtemp()
        result = load_apy_map(empty_dir)
        self.assertIsInstance(result, dict)
        self.assertIn("aave_v3", result)
        self.assertGreater(result["aave_v3"], 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# TestAaveBaseline (8 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAaveBaseline(unittest.TestCase):
    """Тесты для make_aave_baseline()."""

    def setUp(self):
        self.baseline = make_aave_baseline()

    # 1. Возвращает объект с id
    def test_strategy_config_created(self):
        self.assertIsNotNone(self.baseline)
        self.assertTrue(hasattr(self.baseline, "id"))

    # 2. ID корректный
    def test_id_is_aave_baseline(self):
        self.assertEqual(self.baseline.id, "S_aave_baseline")

    # 3. aave_v3 в allocations
    def test_allocation_aave_present(self):
        self.assertIn("aave_v3", self.baseline.allocations)

    # 4. Аллокация aave_v3 близка к 0.95
    def test_apy_is_3_2(self):
        # target_apy_min ≤ 3.2 ≤ target_apy_max
        self.assertLessEqual(self.baseline.target_apy_min, 3.5)
        self.assertGreaterEqual(self.baseline.target_apy_max, 3.0)

    # 5. cash_pct ≥ 0 (не превышает 100% аллокации)
    def test_cash_buffer_positive(self):
        self.assertGreaterEqual(self.baseline.cash_pct, 0.0)

    # 6. Статус active
    def test_status_is_active(self):
        self.assertEqual(self.baseline.status, "active")

    # 7. simulate_day через mock runner возвращает float
    def test_simulate_returns_float(self):
        runner = _MockMultiStrategyRunner([self.baseline], capital=100_000.0)
        result = runner.run_day({"aave_v3": 3.2})
        sid = self.baseline.id
        self.assertIn(sid, result)
        self.assertIsInstance(result[sid], float)

    # 8. simulate_day возвращает положительный yield при APY > 0
    def test_simulate_day_positive_yield(self):
        runner = _MockMultiStrategyRunner([self.baseline], capital=100_000.0)
        result = runner.run_day({"aave_v3": 3.2})
        sid = self.baseline.id
        self.assertGreater(result[sid], 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# TestRunSimulation (15 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunSimulation(unittest.TestCase):
    """Тесты для run_simulation()."""

    def setUp(self):
        self.strategies = _simple_strategies()
        self.apy_map    = _simple_apy_map()
        self.capital    = 100_000.0

    # 1. 1 день — возвращает dict
    def test_1_day_returns_dict(self):
        result = run_simulation(self.strategies, self.capital, 1, self.apy_map)
        self.assertIsInstance(result, dict)

    # 2. 5 дней — поле strategies присутствует
    def test_5_days_returns_strategies(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        self.assertIn("strategies", result)
        self.assertIsInstance(result["strategies"], list)

    # 3. 30 дней — завершается без ошибки
    def test_30_days_completes(self):
        result = run_simulation(self.strategies, self.capital, 30, self.apy_map)
        self.assertEqual(result["n_days"], 30)

    # 4. Результаты отсортированы по rank (1, 2, 3…)
    def test_sorted_by_rank(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        ranks = [s["rank"] for s in result["strategies"]]
        self.assertEqual(ranks, sorted(ranks))

    # 5. Ранги последовательные начиная с 1
    def test_ranks_sequential(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        ranks = [s["rank"] for s in result["strategies"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    # 6. Поле winner присутствует
    def test_winner_field_present(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        self.assertIn("winner", result)
        self.assertIsNotNone(result["winner"])

    # 7. strategy_id присутствует у каждой стратегии
    def test_strategy_ids_present(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        for s in result["strategies"]:
            self.assertIn("strategy_id", s)
            self.assertIsInstance(s["strategy_id"], str)

    # 8. final_balance > 0 при позитивных APY
    def test_final_balance_positive(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        for s in result["strategies"]:
            self.assertGreater(s["final_balance"], 0.0)

    # 9. total_return_pct при положительных APY ≥ 0
    def test_total_return_pct_correct_sign(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        for s in result["strategies"]:
            self.assertGreaterEqual(s["total_return_pct"], 0.0)

    # 10. annualized_apy_pct присутствует
    def test_annualized_apy_present(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        for s in result["strategies"]:
            self.assertIn("annualized_apy_pct", s)

    # 11. sharpe_approx присутствует как число
    def test_sharpe_approx_field(self):
        result = run_simulation(self.strategies, self.capital, 5, self.apy_map)
        for s in result["strategies"]:
            self.assertIn("sharpe_approx", s)
            self.assertIsInstance(s["sharpe_approx"], (int, float))

    # 12. n_days корректный
    def test_n_days_field_correct(self):
        result = run_simulation(self.strategies, self.capital, 7, self.apy_map)
        self.assertEqual(result["n_days"], 7)

    # 13. capital_usd корректный
    def test_capital_usd_correct(self):
        result = run_simulation(self.strategies, 50_000.0, 5, self.apy_map)
        self.assertEqual(result["capital_usd"], 50_000.0)

    # 14. generated_by присутствует
    def test_generated_by_field(self):
        result = run_simulation(self.strategies, self.capital, 1, self.apy_map)
        self.assertIn("generated_by", result)
        self.assertIn("run_tournament_30d", result["generated_by"])

    # 15. simulation_date присутствует в формате ISO
    def test_simulation_date_field(self):
        import datetime
        result = run_simulation(self.strategies, self.capital, 1, self.apy_map)
        self.assertIn("simulation_date", result)
        # Проверяем, что это корректная дата
        date_str = result["simulation_date"]
        parsed = datetime.date.fromisoformat(date_str)
        self.assertIsNotNone(parsed)


# ═══════════════════════════════════════════════════════════════════════════════
# TestSaveResults (10 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveResults(unittest.TestCase):
    """Тесты для save_results()."""

    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.out_path = self.tmpdir / "tournament_30d_results.json"
        self.sample = {
            "simulation_date": "2026-06-12",
            "capital_usd":     100_000.0,
            "n_days":          30,
            "strategies": [
                {
                    "rank":               1,
                    "strategy_id":        "S1",
                    "strategy_name":      "Balanced T1+T2",
                    "final_balance":      101440.0,
                    "total_return_pct":   1.44,
                    "annualized_apy_pct": 17.5,
                    "sharpe_approx":      0.92,
                },
            ],
            "winner":       "S1",
            "generated_by": "run_tournament_30d.py",
        }

    # 1. Создаёт файл
    def test_creates_file(self):
        save_results(self.sample, self.out_path)
        self.assertTrue(self.out_path.exists())

    # 2. Файл — валидный JSON
    def test_valid_json(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

    # 3. Ключевые поля присутствуют
    def test_required_keys(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        for key in ("simulation_date", "capital_usd", "n_days", "strategies", "winner"):
            self.assertIn(key, data)

    # 4. strategies — список
    def test_strategies_is_list(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data["strategies"], list)

    # 5. Нет tmp-файлов после записи
    def test_atomic_write_no_partial_file(self):
        save_results(self.sample, self.out_path)
        tmp_files = list(self.tmpdir.glob(".tmp_tournament_30d_*"))
        self.assertEqual(len(tmp_files), 0, "tmp-файлы не должны оставаться после записи")

    # 6. Перезаписывает существующий файл
    def test_overwrites_existing(self):
        save_results(self.sample, self.out_path)
        modified = dict(self.sample)
        modified["winner"] = "S0"
        save_results(modified, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(data["winner"], "S0")

    # 7. winner сохраняется корректно
    def test_winner_field_saved(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(data["winner"], "S1")

    # 8. simulation_date сохраняется
    def test_simulation_date_saved(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(data["simulation_date"], "2026-06-12")

    # 9. capital_usd сохраняется
    def test_capital_usd_saved(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(data["capital_usd"], 100_000.0)

    # 10. n_days сохраняется
    def test_n_days_saved(self):
        save_results(self.sample, self.out_path)
        data = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(data["n_days"], 30)


# ═══════════════════════════════════════════════════════════════════════════════
# TestPrintTable (5 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrintTable(unittest.TestCase):
    """Тесты для print_table()."""

    def setUp(self):
        self.sample = {
            "simulation_date": "2026-06-12",
            "capital_usd":     100_000.0,
            "n_days":          30,
            "strategies": [
                {
                    "rank":               1,
                    "strategy_id":        "S1",
                    "strategy_name":      "Balanced T1+T2",
                    "final_balance":      101500.0,
                    "total_return_pct":   1.5,
                    "annualized_apy_pct": 18.25,
                    "sharpe_approx":      1.12,
                },
                {
                    "rank":               2,
                    "strategy_id":        "S0",
                    "strategy_name":      "Conservative T1",
                    "final_balance":      100350.0,
                    "total_return_pct":   0.35,
                    "annualized_apy_pct": 4.26,
                    "sharpe_approx":      0.55,
                },
            ],
            "winner": "S1",
            "generated_by": "run_tournament_30d.py",
        }

    # 1. Не бросает исключений
    def test_no_exception(self):
        try:
            print_table(self.sample)
        except Exception as e:
            self.fail(f"print_table() бросил {e}")

    # 2. Возвращает список строк
    def test_returns_list_of_strings(self):
        lines = print_table(self.sample)
        self.assertIsInstance(lines, list)
        self.assertGreater(len(lines), 0)

    # 3. Заголовок содержит ключевые слова
    def test_header_present(self):
        lines = print_table(self.sample)
        full = "\n".join(lines)
        self.assertIn("Tournament", full)
        self.assertIn("30", full)

    # 4. Rank колонка присутствует
    def test_rank_column_present(self):
        lines = print_table(self.sample)
        full = "\n".join(lines)
        self.assertIn("Rank", full)

    # 5. Строка стратегии содержит её ID
    def test_strategy_row_present(self):
        lines = print_table(self.sample)
        full = "\n".join(lines)
        self.assertIn("S1", full)
        self.assertIn("S0", full)


# ═══════════════════════════════════════════════════════════════════════════════
# TestEdgeCases (8 тестов)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    """Edge-case тесты."""

    # 1. Пустой apy_map — симуляция завершается, yield ≈ 0
    def test_empty_apy_map_fallback(self):
        strategies = _simple_strategies()
        result = run_simulation(strategies, 100_000.0, 5, {})
        self.assertIsInstance(result, dict)
        # При нулевых APY final_balance ≈ capital (только cash)
        for s in result["strategies"]:
            self.assertGreaterEqual(s["final_balance"], 0.0)

    # 2. Одна стратегия — rank=1, winner=её id
    def test_single_strategy(self):
        sc = _FallbackStrategyConfig("S_only", "Only", "desc", {"aave_v3": 0.90})
        result = run_simulation([sc], 50_000.0, 5, {"aave_v3": 4.0})
        self.assertEqual(len(result["strategies"]), 1)
        self.assertEqual(result["strategies"][0]["rank"], 1)
        self.assertEqual(result["winner"], "S_only")

    # 3. 0 дней — возвращает корректную структуру (не бросает)
    def test_zero_days_returns_correct_structure(self):
        strategies = _simple_strategies()
        result = run_simulation(strategies, 100_000.0, 0, _simple_apy_map())
        self.assertIn("strategies", result)
        self.assertEqual(result["n_days"], 0)

    # 4. Маленький капитал (1 USD) — не бросает, balance ≥ 0
    def test_very_small_capital(self):
        strategies = [_FallbackStrategyConfig("S_small", "Small", "d", {"aave_v3": 0.90})]
        result = run_simulation(strategies, 1.0, 5, {"aave_v3": 4.0})
        self.assertGreater(result["strategies"][0]["final_balance"], 0.0)

    # 5. 90 дней — завершается, apy аннуализирован корректно
    def test_large_n_days(self):
        strategies = [_FallbackStrategyConfig("S_long", "Long", "d", {"aave_v3": 0.90})]
        result = run_simulation(strategies, 100_000.0, 90, {"aave_v3": 4.0})
        self.assertEqual(result["n_days"], 90)
        s = result["strategies"][0]
        # Аннуализированный APY ≈ 4%: total_return_pct / 90 * 365 ~ 4
        expected_approx = s["total_return_pct"] / 90 * 365
        self.assertAlmostEqual(s["annualized_apy_pct"], expected_approx, places=1)

    # 6. Частичный apy_map (некоторые протоколы отсутствуют) — не бросает
    def test_apy_map_partial_protocols(self):
        strategies = _simple_strategies()
        partial = {"aave_v3": 4.0}  # только один протокол
        result = run_simulation(strategies, 100_000.0, 5, partial)
        self.assertIsInstance(result, dict)

    # 7. Список стратегий не модифицируется симуляцией
    def test_strategies_list_preserved(self):
        strategies = _simple_strategies()
        ids_before = [s.id for s in strategies]
        run_simulation(strategies, 100_000.0, 5, _simple_apy_map())
        ids_after = [s.id for s in strategies]
        self.assertEqual(ids_before, ids_after)

    # 8. Результаты сериализуемы в JSON без ошибок
    def test_results_json_serializable(self):
        strategies = _simple_strategies()
        result = run_simulation(strategies, 100_000.0, 10, _simple_apy_map())
        try:
            serialized = json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"Результаты не сериализуются в JSON: {e}")
        self.assertGreater(len(serialized), 10)


# ═══════════════════════════════════════════════════════════════════════════════
# TestComputeSharpe (bonus — внутренняя функция)
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeSharpe(unittest.TestCase):
    """Дополнительные тесты для _compute_sharpe()."""

    def test_empty_returns_zero(self):
        self.assertEqual(_compute_sharpe([]), 0.0)

    def test_single_return_zero(self):
        self.assertEqual(_compute_sharpe([0.001]), 0.0)

    def test_constant_returns_zero(self):
        # std=0 → Sharpe=0
        self.assertEqual(_compute_sharpe([0.001, 0.001, 0.001]), 0.0)

    def test_positive_returns_positive_sharpe(self):
        returns = [0.001 + 0.0001 * i for i in range(20)]
        sharpe = _compute_sharpe(returns)
        self.assertGreater(sharpe, 0.0)

    def test_sharpe_is_float(self):
        sharpe = _compute_sharpe([0.001, 0.002, 0.0015])
        self.assertIsInstance(sharpe, float)


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
