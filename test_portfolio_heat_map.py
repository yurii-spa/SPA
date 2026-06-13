"""
Unit tests for spa_core.analytics.portfolio_heat_map (MP-597).

Классы:
    TestFormatTvl        (10 тестов) – форматирование $B/$M/$K
    TestColorBucket      (10 тестов) – APY bucket + границы
    TestSizeBucket       (8  тестов) – TVL bucket + границы
    TestMakeCell         (17 тестов) – поля, label, tooltip, emoji, is_eligible
    TestGenerate         (22 тестов) – группировка, avg_apy, total_tvl, сортировка
    TestHeatMapData      (10 тестов) – поля, apy_range, chain_summary
    TestSave             (8  тестов) – атомарная запись, JSON-валидность
    TestToDict           (4  тестов) – ключи, JSON-serializable
    TestNormalization    (4  тестов) – _normalize_chain, _normalize_id, label с дефисами

Итого: 93 теста.

Запуск:
    python3 -m unittest spa_core.tests.test_portfolio_heat_map -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.portfolio_heat_map import (
    HeatMapCell,
    HeatMapData,
    HeatMapGroup,
    PortfolioHeatMapGenerator,
    _normalize_chain,
    _normalize_id,
    SUPPORTED_CHAINS,
    CHAIN_ORDER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_generator_no_file() -> PortfolioHeatMapGenerator:
    """Generator с несуществующим adapter_status.json — load_adapter_data() → {}."""
    with tempfile.TemporaryDirectory() as tmp:
        return PortfolioHeatMapGenerator(os.path.join(tmp, "adapter_status.json"))


def _minimal_adapter_status() -> dict:
    """Минимальный adapter_status.json с двумя адаптерами (ethereum + base)."""
    return {
        "alpha_eth": {
            "adapter_id": "alpha_eth",
            "chain": "ethereum",
            "tier": "T1",
            "apy_pct": 5.0,
            "tvl_usd": 1_000_000_000,
            "risk_score": 0.20,
        },
        "beta_eth": {
            "adapter_id": "beta_eth",
            "chain": "ethereum",
            "tier": "T2",
            "apy_pct": 7.5,
            "tvl_usd": 200_000_000,
            "risk_score": 0.35,
        },
        "gamma_base": {
            "adapter_id": "gamma_base",
            "chain": "base",
            "tier": "T1",
            "apy_pct": 4.5,
            "tvl_usd": 500_000_000,
            "risk_score": 0.22,
        },
    }


def _write_adapter_status(tmp_dir: str, data: dict) -> str:
    """Записывает adapter_status.json в tmp_dir, возвращает путь."""
    path = os.path.join(tmp_dir, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def _make_generator_with_data(data: dict) -> PortfolioHeatMapGenerator:
    """Generator с конкретными данными; tempdir живёт до конца функции — НЕЛЬЗЯ.

    Возвращает кортеж (gen, tmpdir_obj) — caller должен держать tmpdir_obj.
    """
    raise NotImplementedError("Use _setup_gen pattern instead")


# ---------------------------------------------------------------------------
# TestFormatTvl
# ---------------------------------------------------------------------------

class TestFormatTvl(unittest.TestCase):
    """Проверяет format_tvl: граничные значения $B / $M / $K."""

    def setUp(self) -> None:
        self.gen = _make_generator_no_file()

    def test_zero_shows_k(self) -> None:
        result = self.gen.format_tvl(0.0)
        self.assertIn("K", result)
        self.assertIn("$", result)

    def test_thousand_shows_k(self) -> None:
        result = self.gen.format_tvl(1_000)
        self.assertIn("K", result)

    def test_350k(self) -> None:
        result = self.gen.format_tvl(350_000)
        self.assertEqual(result, "$350K")

    def test_999_999_shows_k(self) -> None:
        """Значение чуть ниже 1M → K."""
        result = self.gen.format_tvl(999_999)
        self.assertIn("K", result)
        self.assertNotIn("M", result)

    def test_exactly_1m(self) -> None:
        result = self.gen.format_tvl(1_000_000)
        self.assertIn("M", result)
        self.assertNotIn("B", result)

    def test_1_5m(self) -> None:
        result = self.gen.format_tvl(1_500_000)
        self.assertEqual(result, "$1.5M")

    def test_800m(self) -> None:
        result = self.gen.format_tvl(800_000_000)
        self.assertEqual(result, "$800.0M")

    def test_exactly_1b(self) -> None:
        result = self.gen.format_tvl(1_000_000_000)
        self.assertIn("B", result)
        self.assertNotIn("M", result)

    def test_1_2b(self) -> None:
        result = self.gen.format_tvl(1_200_000_000)
        self.assertEqual(result, "$1.2B")

    def test_2_5b(self) -> None:
        result = self.gen.format_tvl(2_500_000_000)
        self.assertEqual(result, "$2.5B")


# ---------------------------------------------------------------------------
# TestColorBucket
# ---------------------------------------------------------------------------

class TestColorBucket(unittest.TestCase):
    """Проверяет get_color_bucket: каждый bucket и граничные значения."""

    def setUp(self) -> None:
        self.gen = _make_generator_no_file()

    def test_zero_is_low(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(0.0), "low")

    def test_1_pct_is_low(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(1.0), "low")

    def test_3_99_is_low(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(3.99), "low")

    def test_4_0_is_medium(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(4.0), "medium")

    def test_5_5_is_medium(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(5.5), "medium")

    def test_6_99_is_medium(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(6.99), "medium")

    def test_7_0_is_high(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(7.0), "high")

    def test_8_5_is_high(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(8.5), "high")

    def test_9_99_is_high(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(9.99), "high")

    def test_10_0_is_very_high(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(10.0), "very_high")

    # extra — не считается в 10, но полезно
    def test_12_0_is_very_high(self) -> None:
        self.assertEqual(self.gen.get_color_bucket(12.0), "very_high")


# ---------------------------------------------------------------------------
# TestSizeBucket
# ---------------------------------------------------------------------------

class TestSizeBucket(unittest.TestCase):
    """Проверяет get_size_bucket: каждый bucket и граничные значения."""

    def setUp(self) -> None:
        self.gen = _make_generator_no_file()

    def test_zero_is_small(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(0.0), "small")

    def test_50m_is_small(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(50_000_000), "small")

    def test_99_9m_is_small(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(99_900_000), "small")

    def test_100m_is_medium(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(100_000_000), "medium")

    def test_500m_is_medium(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(500_000_000), "medium")

    def test_999m_is_medium(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(999_000_000), "medium")

    def test_1b_is_large(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(1_000_000_000), "large")

    def test_2b_is_large(self) -> None:
        self.assertEqual(self.gen.get_size_bucket(2_000_000_000), "large")


# ---------------------------------------------------------------------------
# TestMakeCell
# ---------------------------------------------------------------------------

class TestMakeCell(unittest.TestCase):
    """Проверяет make_cell: поля dataclass, label-парсинг, tooltip, emoji, is_eligible."""

    def setUp(self) -> None:
        self.gen = _make_generator_no_file()

    def _cell(self, adapter_id: str = "test_adapter", **kwargs):
        defaults = {
            "chain": "ethereum",
            "tier": "T1",
            "apy_pct": 5.0,
            "risk_score": 0.25,
            "tvl_usd": 1_000_000_000,
        }
        defaults.update(kwargs)
        return self.gen.make_cell(adapter_id, defaults)

    # --- Поля dataclass ---
    def test_adapter_id_field(self) -> None:
        self.assertEqual(self._cell("aave_v3").adapter_id, "aave_v3")

    def test_chain_field(self) -> None:
        self.assertEqual(self._cell(chain="arbitrum").chain, "arbitrum")

    def test_tier_field(self) -> None:
        self.assertEqual(self._cell(tier="T2").tier, "T2")

    def test_apy_pct_field(self) -> None:
        self.assertAlmostEqual(self._cell(apy_pct=6.5).apy_pct, 6.5)

    def test_risk_score_field(self) -> None:
        self.assertAlmostEqual(self._cell(risk_score=0.42).risk_score, 0.42)

    def test_tvl_usd_field(self) -> None:
        self.assertAlmostEqual(self._cell(tvl_usd=800_000_000).tvl_usd, 800_000_000)

    # --- Label ---
    def test_label_underscores_to_spaces(self) -> None:
        self.assertEqual(self._cell("aave_v3").label, "Aave V3")

    def test_label_three_parts(self) -> None:
        self.assertEqual(self._cell("aave_v3_base").label, "Aave V3 Base")

    def test_label_hyphens_to_spaces(self) -> None:
        cell = self._cell("compound-v3")
        self.assertEqual(cell.label, "Compound V3")

    def test_label_single_word(self) -> None:
        self.assertEqual(self._cell("compound").label, "Compound")

    # --- chain_emoji ---
    def test_emoji_ethereum(self) -> None:
        self.assertEqual(self._cell(chain="ethereum").chain_emoji, "⚪")

    def test_emoji_arbitrum(self) -> None:
        self.assertEqual(self._cell(chain="arbitrum").chain_emoji, "🔵")

    def test_emoji_base(self) -> None:
        self.assertEqual(self._cell(chain="base").chain_emoji, "🔵")

    def test_emoji_optimism(self) -> None:
        self.assertEqual(self._cell(chain="optimism").chain_emoji, "🔴")

    def test_emoji_polygon(self) -> None:
        self.assertEqual(self._cell(chain="polygon").chain_emoji, "🟣")

    def test_emoji_unknown_chain(self) -> None:
        self.assertEqual(self._cell(chain="solana").chain_emoji, "⚫")

    # --- Tooltip ---
    def test_tooltip_contains_apy(self) -> None:
        cell = self._cell(apy_pct=5.5)
        self.assertIn("5.5%", cell.tooltip)

    def test_tooltip_contains_chain(self) -> None:
        cell = self._cell(chain="arbitrum")
        self.assertIn("arbitrum", cell.tooltip)

    def test_tooltip_contains_tvl(self) -> None:
        cell = self._cell(tvl_usd=1_200_000_000)
        self.assertIn("1.2B", cell.tooltip)

    def test_tooltip_contains_risk(self) -> None:
        cell = self._cell(risk_score=0.35)
        self.assertIn("0.35", cell.tooltip)

    # --- is_eligible ---
    def test_eligible_when_apy_and_tvl_ok(self) -> None:
        cell = self._cell(apy_pct=5.0, tvl_usd=10_000_000)
        self.assertTrue(cell.is_eligible)

    def test_not_eligible_low_tvl(self) -> None:
        cell = self._cell(apy_pct=5.0, tvl_usd=1_000_000)
        self.assertFalse(cell.is_eligible)

    def test_not_eligible_zero_apy(self) -> None:
        cell = self._cell(apy_pct=0.0, tvl_usd=100_000_000)
        self.assertFalse(cell.is_eligible)

    def test_not_eligible_apy_too_high(self) -> None:
        cell = self._cell(apy_pct=35.0, tvl_usd=100_000_000)
        self.assertFalse(cell.is_eligible)

    def test_eligible_at_apy_boundary_min(self) -> None:
        """APY = 1.0% (нижняя граница eligible)."""
        cell = self._cell(apy_pct=1.0, tvl_usd=10_000_000)
        self.assertTrue(cell.is_eligible)

    def test_eligible_at_apy_boundary_max(self) -> None:
        """APY = 30.0% (верхняя граница eligible)."""
        cell = self._cell(apy_pct=30.0, tvl_usd=10_000_000)
        self.assertTrue(cell.is_eligible)

    def test_eligible_at_tvl_boundary(self) -> None:
        """TVL = $5M (точная нижняя граница eligible)."""
        cell = self._cell(apy_pct=5.0, tvl_usd=5_000_000)
        self.assertTrue(cell.is_eligible)


# ---------------------------------------------------------------------------
# TestGenerate
# ---------------------------------------------------------------------------

class TestGenerate(unittest.TestCase):
    """Проверяет generate(): группировка, avg_apy, total_tvl, сортировка."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        data = _minimal_adapter_status()
        path = _write_adapter_status(self._tmpdir.name, data)
        self.gen = PortfolioHeatMapGenerator(path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    # --- Тип результата ---
    def test_returns_heat_map_data(self) -> None:
        hm = self.gen.generate()
        self.assertIsInstance(hm, HeatMapData)

    def test_groups_is_list(self) -> None:
        hm = self.gen.generate()
        self.assertIsInstance(hm.groups, list)

    def test_groups_not_empty(self) -> None:
        hm = self.gen.generate()
        self.assertGreater(len(hm.groups), 0)

    # --- Группировка ---
    def test_group_count(self) -> None:
        """3 адаптера в 3 группах: T1_ethereum, T2_ethereum, T1_base."""
        hm = self.gen.generate()
        group_ids = {g.group_id for g in hm.groups}
        self.assertIn("T1_ethereum", group_ids)
        self.assertIn("T2_ethereum", group_ids)
        self.assertIn("T1_base", group_ids)

    def test_cells_are_heat_map_cell_instances(self) -> None:
        hm = self.gen.generate()
        for g in hm.groups:
            for c in g.cells:
                self.assertIsInstance(c, HeatMapCell)

    def test_group_count_equals_len_cells(self) -> None:
        hm = self.gen.generate()
        for g in hm.groups:
            self.assertEqual(g.count, len(g.cells))

    def test_cells_sorted_desc_by_apy(self) -> None:
        """Ячейки в группе отсортированы по APY убыванию."""
        hm = self.gen.generate()
        for g in hm.groups:
            apys = [c.apy_pct for c in g.cells]
            self.assertEqual(apys, sorted(apys, reverse=True))

    # --- avg_apy ---
    def test_avg_apy_single_cell_group(self) -> None:
        """Группа с одной ячейкой: avg == cell.apy_pct."""
        hm = self.gen.generate()
        for g in hm.groups:
            if g.count == 1:
                self.assertAlmostEqual(g.avg_apy_pct, g.cells[0].apy_pct, places=4)

    def test_avg_apy_computed_correctly(self) -> None:
        """T1_ethereum содержит alpha_eth (5.0%) → avg = 5.0%."""
        hm = self.gen.generate()
        t1_eth = next(g for g in hm.groups if g.group_id == "T1_ethereum")
        self.assertAlmostEqual(t1_eth.avg_apy_pct, 5.0, places=4)

    # --- total_tvl ---
    def test_total_tvl_usd_in_group(self) -> None:
        """T1_ethereum: total_tvl = $1B."""
        hm = self.gen.generate()
        t1_eth = next(g for g in hm.groups if g.group_id == "T1_ethereum")
        self.assertAlmostEqual(t1_eth.total_tvl_usd, 1_000_000_000, places=0)

    def test_total_adapters_matches_cells(self) -> None:
        hm = self.gen.generate()
        total_from_groups = sum(g.count for g in hm.groups)
        self.assertEqual(hm.total_adapters, total_from_groups)

    def test_total_tvl_usd_field(self) -> None:
        hm = self.gen.generate()
        expected = 1_000_000_000 + 200_000_000 + 500_000_000
        self.assertAlmostEqual(hm.tvl_total_usd, expected, places=0)

    # --- Сортировка групп ---
    def test_groups_ethereum_before_base(self) -> None:
        """Ethereum (idx=0) должен стоять раньше base (idx=2)."""
        hm = self.gen.generate()
        chains = [g.chain for g in hm.groups]
        eth_positions = [i for i, c in enumerate(chains) if c == "ethereum"]
        base_positions = [i for i, c in enumerate(chains) if c == "base"]
        self.assertTrue(all(e < b for e in eth_positions for b in base_positions))

    # --- APY range ---
    def test_apy_range_has_min_max_avg(self) -> None:
        hm = self.gen.generate()
        self.assertIn("min", hm.apy_range)
        self.assertIn("max", hm.apy_range)
        self.assertIn("avg", hm.apy_range)

    def test_apy_range_min_lte_max(self) -> None:
        hm = self.gen.generate()
        self.assertLessEqual(hm.apy_range["min"], hm.apy_range["max"])

    def test_apy_range_avg_between_min_max(self) -> None:
        hm = self.gen.generate()
        self.assertGreaterEqual(hm.apy_range["avg"], hm.apy_range["min"])
        self.assertLessEqual(hm.apy_range["avg"], hm.apy_range["max"])

    def test_apy_range_max_is_highest(self) -> None:
        """beta_eth=7.5% — самый высокий APY в fixture."""
        hm = self.gen.generate()
        self.assertAlmostEqual(hm.apy_range["max"], 7.5, places=4)

    # --- chain_summary ---
    def test_chain_summary_contains_ethereum(self) -> None:
        hm = self.gen.generate()
        self.assertIn("ethereum", hm.chain_summary)

    def test_chain_summary_contains_base(self) -> None:
        hm = self.gen.generate()
        self.assertIn("base", hm.chain_summary)

    def test_chain_summary_count_correct(self) -> None:
        """ethereum: 2 адаптера в fixture."""
        hm = self.gen.generate()
        self.assertEqual(hm.chain_summary["ethereum"]["count"], 2)

    def test_chain_summary_has_avg_apy(self) -> None:
        hm = self.gen.generate()
        for info in hm.chain_summary.values():
            self.assertIn("avg_apy", info)

    # --- Empty data ---
    def test_empty_data_no_crash(self) -> None:
        """Несуществующий файл → пустые данные, но не исключение."""
        gen = _make_generator_no_file()
        hm = gen.generate()
        self.assertIsInstance(hm, HeatMapData)
        self.assertEqual(hm.total_adapters, 0)

    def test_empty_data_apy_range_zeros(self) -> None:
        gen = _make_generator_no_file()
        hm = gen.generate()
        self.assertEqual(hm.apy_range, {"min": 0.0, "max": 0.0, "avg": 0.0})

    # --- generated_at ---
    def test_generated_at_is_string(self) -> None:
        hm = self.gen.generate()
        self.assertIsInstance(hm.generated_at, str)
        self.assertGreater(len(hm.generated_at), 0)

    # --- color_legend ---
    def test_color_legend_has_all_buckets(self) -> None:
        hm = self.gen.generate()
        for bucket in ("low", "medium", "high", "very_high"):
            self.assertIn(bucket, hm.color_legend)


# ---------------------------------------------------------------------------
# TestHeatMapData
# ---------------------------------------------------------------------------

class TestHeatMapData(unittest.TestCase):
    """Проверяет корректность полей HeatMapData."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        data = _minimal_adapter_status()
        path = _write_adapter_status(self._tmpdir.name, data)
        self.gen = PortfolioHeatMapGenerator(path)
        self.hm = self.gen.generate()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_generated_at_nonempty(self) -> None:
        self.assertIsInstance(self.hm.generated_at, str)
        self.assertTrue(self.hm.generated_at)

    def test_total_adapters_is_int(self) -> None:
        self.assertIsInstance(self.hm.total_adapters, int)

    def test_total_adapters_positive(self) -> None:
        self.assertGreater(self.hm.total_adapters, 0)

    def test_groups_is_list_of_heat_map_group(self) -> None:
        self.assertIsInstance(self.hm.groups, list)
        for g in self.hm.groups:
            self.assertIsInstance(g, HeatMapGroup)

    def test_apy_range_min_key(self) -> None:
        self.assertIn("min", self.hm.apy_range)

    def test_apy_range_max_key(self) -> None:
        self.assertIn("max", self.hm.apy_range)

    def test_apy_range_avg_key(self) -> None:
        self.assertIn("avg", self.hm.apy_range)

    def test_apy_range_min_lte_max(self) -> None:
        self.assertLessEqual(self.hm.apy_range["min"], self.hm.apy_range["max"])

    def test_tvl_total_usd_nonnegative(self) -> None:
        self.assertGreaterEqual(self.hm.tvl_total_usd, 0.0)

    def test_color_legend_four_keys(self) -> None:
        self.assertEqual(len(self.hm.color_legend), 4)

    def test_chain_summary_is_dict(self) -> None:
        self.assertIsInstance(self.hm.chain_summary, dict)


# ---------------------------------------------------------------------------
# TestSave
# ---------------------------------------------------------------------------

class TestSave(unittest.TestCase):
    """Проверяет атомарную запись save()."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        data = _minimal_adapter_status()
        self._data_path = _write_adapter_status(self._tmpdir.name, data)
        self.gen = PortfolioHeatMapGenerator(self._data_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_save_returns_str_path(self) -> None:
        path = self.gen.save()
        self.assertIsInstance(path, str)

    def test_file_exists_after_save(self) -> None:
        path = self.gen.save()
        self.assertTrue(os.path.exists(path))

    def test_file_is_valid_json(self) -> None:
        path = self.gen.save()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_no_tmp_leftover(self) -> None:
        path = self.gen.save()
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_custom_output_path(self) -> None:
        custom = os.path.join(self._tmpdir.name, "my_heat_map.json")
        returned = self.gen.save(custom)
        self.assertEqual(returned, custom)
        self.assertTrue(os.path.exists(custom))

    def test_saved_json_has_groups_key(self) -> None:
        path = self.gen.save()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("groups", data)

    def test_saved_json_has_generated_at_key(self) -> None:
        path = self.gen.save()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("generated_at", data)

    def test_parent_dir_created_if_missing(self) -> None:
        nested = os.path.join(self._tmpdir.name, "sub", "dir", "heat_map.json")
        path = self.gen.save(nested)
        self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# TestToDict
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):
    """Проверяет to_dict(): все ключи, JSON-serializable."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        data = _minimal_adapter_status()
        path = _write_adapter_status(self._tmpdir.name, data)
        self.gen = PortfolioHeatMapGenerator(path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_returns_dict(self) -> None:
        d = self.gen.to_dict()
        self.assertIsInstance(d, dict)

    def test_has_required_top_level_keys(self) -> None:
        d = self.gen.to_dict()
        for key in ("generated_at", "total_adapters", "groups",
                    "apy_range", "tvl_total_usd", "color_legend", "chain_summary"):
            self.assertIn(key, d, msg=f"Missing key: {key}")

    def test_json_serializable(self) -> None:
        d = self.gen.to_dict()
        serialized = json.dumps(d)  # должно не бросить исключение
        self.assertIsInstance(serialized, str)

    def test_groups_are_list_of_dicts(self) -> None:
        d = self.gen.to_dict()
        self.assertIsInstance(d["groups"], list)
        for g in d["groups"]:
            self.assertIsInstance(g, dict)


# ---------------------------------------------------------------------------
# TestNormalization
# ---------------------------------------------------------------------------

class TestNormalization(unittest.TestCase):
    """Проверяет вспомогательные функции нормализации."""

    def test_normalize_chain_mainnet_to_ethereum(self) -> None:
        self.assertEqual(_normalize_chain("mainnet"), "ethereum")

    def test_normalize_chain_arb_to_arbitrum(self) -> None:
        self.assertEqual(_normalize_chain("arb"), "arbitrum")

    def test_normalize_chain_op_to_optimism(self) -> None:
        self.assertEqual(_normalize_chain("op"), "optimism")

    def test_normalize_id_replaces_hyphens(self) -> None:
        self.assertEqual(_normalize_id("aave-v3-base"), "aave_v3_base")


# ---------------------------------------------------------------------------
# Dedup / Source2 integration tests
# ---------------------------------------------------------------------------

class TestSourceDedup(unittest.TestCase):
    """Проверяет дедупликацию Source1/Source2 и заполнение пробелов."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _gen(self, data: dict) -> PortfolioHeatMapGenerator:
        path = _write_adapter_status(self._tmpdir.name, data)
        return PortfolioHeatMapGenerator(path)

    def test_no_duplicates_when_source1_and_source2_overlap(self) -> None:
        """compound_v3 (Source1, chain=ethereum) перекрывает compound-v3 (Source2)."""
        data = {
            "compound_v3": {
                "chain": "ethereum",
                "tier": "T1",
                "apy_pct": 5.2,
                "tvl_usd": 1_500_000_000,
                "risk_score": 0.28,
            },
            "adapters": [
                {
                    "protocol_key": "compound-v3",
                    "tier": "T1",
                    "chains": ["ethereum"],
                    "mock_apy": {"ethereum": {"USDC": 4.8}},
                }
            ],
        }
        gen = self._gen(data)
        hm = gen.generate()
        ids = [c.adapter_id for g in hm.groups for c in g.cells]
        # Нет двух compound записей на одном chain
        eth_ids = [
            _normalize_id(a) for a in ids
            if "compound" in a.lower()
        ]
        self.assertEqual(len(eth_ids), 1)

    def test_source2_fills_missing_chains(self) -> None:
        """Source2 добавляет arb-цепочку, которой нет в Source1."""
        data = {
            "adapters": [
                {
                    "protocol_key": "test-proto",
                    "tier": "T1",
                    "chains": ["ethereum", "arbitrum"],
                    "mock_apy": {
                        "ethereum": {"USDC": 5.0},
                        "arbitrum": {"USDC": 5.5},
                    },
                }
            ]
        }
        gen = self._gen(data)
        hm = gen.generate()
        chains = {c.chain for g in hm.groups for c in g.cells}
        self.assertIn("ethereum", chains)
        self.assertIn("arbitrum", chains)

    def test_skip_keys_ignored(self) -> None:
        """generated_at, adapters, base_gas_monitor и пр. не попадают в cells."""
        data = {
            "generated_at": "2026-06-13T00:00:00Z",
            "base_gas_monitor": {"status": "OK"},
            "real_adapter": {
                "chain": "ethereum",
                "tier": "T1",
                "apy_pct": 5.0,
                "tvl_usd": 100_000_000,
            },
        }
        gen = self._gen(data)
        hm = gen.generate()
        ids = [c.adapter_id for g in hm.groups for c in g.cells]
        self.assertNotIn("generated_at", ids)
        self.assertNotIn("base_gas_monitor", ids)
        self.assertIn("real_adapter", ids)

    def test_missing_chain_field_skipped(self) -> None:
        """Запись без поля chain не попадает в cells."""
        data = {
            "no_chain_adapter": {
                "tier": "T1",
                "apy_pct": 5.0,
                "tvl_usd": 100_000_000,
                # нет "chain"
            },
            "valid": {
                "chain": "ethereum",
                "tier": "T1",
                "apy_pct": 5.0,
                "tvl_usd": 100_000_000,
            },
        }
        gen = self._gen(data)
        hm = gen.generate()
        ids = [c.adapter_id for g in hm.groups for c in g.cells]
        self.assertNotIn("no_chain_adapter", ids)
        self.assertIn("valid", ids)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
