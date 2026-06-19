"""
tests/test_source_pipeline.py — MP-1304 тесты Source Pipeline

Тест-группы:
  TestSourceStateConstants      — константы SourceState (7 тестов)
  TestSourcePipelineDefaults    — дефолтная инициализация (9 тестов)
  TestStrictSources             — strict_sources() (5 тестов)
  TestCanAffectBacktest         — can_affect_backtest() (5 тестов)
  TestSourceSummary             — source_summary() (4 теста)
  TestPromoteSource             — promote_source() мутации (7 тестов)
  TestLoadFromGate              — load_from_gate() (5 тестов)
  TestPersistence               — атомарные записи (5 тестов)
  TestUnknownSource             — неизвестные источники (3 теста)
  TestRS001RS002Sources         — RS-001/RS-002 источники (4 теста)

Итого: 54 теста (≥35 требуемых)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.backtesting.source_pipeline import (
    SourceState,
    SourcePipeline,
    DEFAULT_SOURCES,
    SCHEMA_VERSION,
)

# ─── Path to real gate file ───────────────────────────────────────────────────
_GATE_FILE = os.path.join(_ROOT, "data", "backtest", "pre_paper_backtest_gate.json")


# ══════════════════════════════════════════════════════════════════════════════
# TestSourceStateConstants
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceStateConstants(unittest.TestCase):
    """Константы SourceState."""

    def test_clean_included_value(self) -> None:
        self.assertEqual(SourceState.CLEAN_INCLUDED, "clean_included")

    def test_pending_value(self) -> None:
        self.assertEqual(SourceState.PENDING, "pending")

    def test_research_only_value(self) -> None:
        self.assertEqual(SourceState.RESEARCH_ONLY, "research_only")

    def test_manual_proxy_value(self) -> None:
        self.assertEqual(SourceState.MANUAL_PROXY, "manual_proxy")

    def test_review_value(self) -> None:
        self.assertEqual(SourceState.REVIEW, "review")

    def test_source_needed_value(self) -> None:
        self.assertEqual(SourceState.SOURCE_NEEDED, "source_needed")

    def test_is_valid_all_states(self) -> None:
        for state in [
            SourceState.CLEAN_INCLUDED,
            SourceState.PENDING,
            SourceState.RESEARCH_ONLY,
            SourceState.MANUAL_PROXY,
            SourceState.REVIEW,
            SourceState.SOURCE_NEEDED,
        ]:
            self.assertTrue(SourceState.is_valid(state))


# ══════════════════════════════════════════════════════════════════════════════
# TestSourcePipelineDefaults
# ══════════════════════════════════════════════════════════════════════════════

class TestSourcePipelineDefaults(unittest.TestCase):
    """Дефолтная инициализация SourcePipeline."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_aave_v2_is_clean(self) -> None:
        self.assertEqual(self.pipeline.state("aave_v2_usdc"), SourceState.CLEAN_INCLUDED)

    def test_compound_v2_is_clean(self) -> None:
        self.assertEqual(self.pipeline.state("compound_v2_usdc"), SourceState.CLEAN_INCLUDED)

    def test_morpho_steakhouse_is_pending(self) -> None:
        self.assertEqual(self.pipeline.state("morpho_steakhouse"), SourceState.PENDING)

    def test_maple_is_review(self) -> None:
        self.assertEqual(self.pipeline.state("maple_syrupusdc"), SourceState.REVIEW)

    def test_delta_neutral_is_research_only(self) -> None:
        self.assertEqual(self.pipeline.state("delta_neutral"), SourceState.RESEARCH_ONLY)

    def test_pendle_is_manual_proxy(self) -> None:
        self.assertEqual(self.pipeline.state("pendle_pt_susde"), SourceState.MANUAL_PROXY)

    def test_eth_staking_is_source_needed(self) -> None:
        self.assertEqual(self.pipeline.state("eth_staking"), SourceState.SOURCE_NEEDED)

    def test_all_sources_returns_dict(self) -> None:
        result = self.pipeline.all_sources()
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)

    def test_default_sources_count(self) -> None:
        self.assertEqual(len(self.pipeline.all_sources()), len(DEFAULT_SOURCES))


# ══════════════════════════════════════════════════════════════════════════════
# TestStrictSources
# ══════════════════════════════════════════════════════════════════════════════

class TestStrictSources(unittest.TestCase):
    """strict_sources() — только CLEAN_INCLUDED."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_strict_sources_returns_list(self) -> None:
        result = self.pipeline.strict_sources()
        self.assertIsInstance(result, list)

    def test_strict_sources_all_clean_included(self) -> None:
        """Каждый элемент strict_sources() должен иметь состояние CLEAN_INCLUDED."""
        for src in self.pipeline.strict_sources():
            self.assertEqual(self.pipeline.state(src), SourceState.CLEAN_INCLUDED)

    def test_strict_sources_contains_aave_v2(self) -> None:
        self.assertIn("aave_v2_usdc", self.pipeline.strict_sources())

    def test_strict_sources_excludes_pending(self) -> None:
        """PENDING не должен быть в strict_sources()."""
        for src in self.pipeline.strict_sources():
            self.assertNotEqual(self.pipeline.state(src), SourceState.PENDING)

    def test_is_strict_eligible_for_clean(self) -> None:
        self.assertTrue(self.pipeline.is_strict_eligible("aave_v2_usdc"))


# ══════════════════════════════════════════════════════════════════════════════
# TestCanAffectBacktest
# ══════════════════════════════════════════════════════════════════════════════

class TestCanAffectBacktest(unittest.TestCase):
    """can_affect_backtest() — только CLEAN_INCLUDED = True."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_clean_included_can_affect(self) -> None:
        self.assertTrue(self.pipeline.can_affect_backtest("aave_v2_usdc"))

    def test_pending_cannot_affect(self) -> None:
        self.assertFalse(self.pipeline.can_affect_backtest("morpho_steakhouse"))

    def test_research_only_cannot_affect(self) -> None:
        self.assertFalse(self.pipeline.can_affect_backtest("delta_neutral"))

    def test_manual_proxy_cannot_affect(self) -> None:
        self.assertFalse(self.pipeline.can_affect_backtest("pendle_pt_susde"))

    def test_source_needed_cannot_affect(self) -> None:
        self.assertFalse(self.pipeline.can_affect_backtest("btc_yield"))


# ══════════════════════════════════════════════════════════════════════════════
# TestSourceSummary
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceSummary(unittest.TestCase):
    """source_summary() — counts по состояниям."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_summary_returns_dict(self) -> None:
        self.assertIsInstance(self.pipeline.source_summary(), dict)

    def test_summary_clean_included_count(self) -> None:
        """По умолчанию: 8 CLEAN_INCLUDED."""
        summary = self.pipeline.source_summary()
        self.assertEqual(summary.get(SourceState.CLEAN_INCLUDED, 0), 8)

    def test_summary_total_equals_source_count(self) -> None:
        summary = self.pipeline.source_summary()
        total = sum(summary.values())
        self.assertEqual(total, len(DEFAULT_SOURCES))

    def test_summary_pending_count(self) -> None:
        """По умолчанию: 3 PENDING (morpho_steakhouse, yearn_v3_yvusdc, euler_v2_usdc)."""
        summary = self.pipeline.source_summary()
        self.assertEqual(summary.get(SourceState.PENDING, 0), 3)


# ══════════════════════════════════════════════════════════════════════════════
# TestPromoteSource
# ══════════════════════════════════════════════════════════════════════════════

class TestPromoteSource(unittest.TestCase):
    """promote_source() мутации и персистентность."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_promote_changes_state(self) -> None:
        self.pipeline.promote_source("morpho_steakhouse", SourceState.CLEAN_INCLUDED, "test")
        self.assertEqual(self.pipeline.state("morpho_steakhouse"), SourceState.CLEAN_INCLUDED)

    def test_promote_persists_to_disk(self) -> None:
        self.pipeline.promote_source("morpho_steakhouse", SourceState.CLEAN_INCLUDED, "test")
        p2 = SourcePipeline(data_dir=self._tmpdir)
        self.assertEqual(p2.state("morpho_steakhouse"), SourceState.CLEAN_INCLUDED)

    def test_promote_invalid_state_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.promote_source("aave_v2_usdc", "INVALID_STATE", "bad")

    def test_promote_updates_strict_sources_list(self) -> None:
        """После promote в CLEAN_INCLUDED → источник появляется в strict_sources()."""
        self.pipeline.promote_source("morpho_steakhouse", SourceState.CLEAN_INCLUDED, "test")
        self.assertIn("morpho_steakhouse", self.pipeline.strict_sources())

    def test_promote_removes_from_pending(self) -> None:
        self.pipeline.promote_source("morpho_steakhouse", SourceState.CLEAN_INCLUDED, "test")
        self.assertNotIn("morpho_steakhouse", self.pipeline.pending_sources())

    def test_demote_clean_to_pending(self) -> None:
        self.pipeline.promote_source("aave_v2_usdc", SourceState.PENDING, "test demote")
        self.assertEqual(self.pipeline.state("aave_v2_usdc"), SourceState.PENDING)
        self.assertFalse(self.pipeline.can_affect_backtest("aave_v2_usdc"))

    def test_promote_new_source(self) -> None:
        """Новый источник, не существующий в DEFAULT_SOURCES."""
        self.pipeline.promote_source("new_protocol_xyz", SourceState.PENDING, "new")
        self.assertEqual(self.pipeline.state("new_protocol_xyz"), SourceState.PENDING)


# ══════════════════════════════════════════════════════════════════════════════
# TestLoadFromGate
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadFromGate(unittest.TestCase):
    """load_from_gate() — загрузка из реального файла."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_gate_file_exists(self) -> None:
        """Реальный gate-файл должен существовать."""
        self.assertTrue(os.path.exists(_GATE_FILE), f"Gate file missing: {_GATE_FILE}")

    def test_load_from_gate_no_error(self) -> None:
        """load_from_gate() не должен бросать исключений."""
        self.pipeline.load_from_gate(_GATE_FILE)  # should not raise

    def test_load_from_gate_updates_delta_neutral(self) -> None:
        """delta_neutral в gate → RESEARCH_ONLY."""
        self.pipeline.load_from_gate(_GATE_FILE)
        state = self.pipeline.state("delta_neutral")
        # gate status is "model_only" → maps to RESEARCH_ONLY
        self.assertEqual(state, SourceState.RESEARCH_ONLY)

    def test_load_from_nonexistent_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.pipeline.load_from_gate("/nonexistent/path/gate.json")

    def test_load_from_synthetic_gate(self) -> None:
        """Синтетический gate-файл обновляет состояние."""
        synthetic_gate = {
            "research_exclusions": [
                {
                    "protocol_id": "some_new_protocol",
                    "current_status": "pending",
                    "reason": "test synthetic",
                }
            ]
        }
        gate_path = os.path.join(self._tmpdir, "synthetic_gate.json")
        with open(gate_path, "w") as fh:
            json.dump(synthetic_gate, fh)
        self.pipeline.load_from_gate(gate_path)
        self.assertEqual(self.pipeline.state("some_new_protocol"), SourceState.PENDING)


# ══════════════════════════════════════════════════════════════════════════════
# TestPersistence
# ══════════════════════════════════════════════════════════════════════════════

class TestPersistence(unittest.TestCase):
    """Атомарные записи и перезагрузка."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_creates_file(self) -> None:
        p = SourcePipeline(data_dir=self._tmpdir)
        p.save()
        path = Path(self._tmpdir) / "source_pipeline.json"
        self.assertTrue(path.exists())

    def test_saved_file_is_valid_json(self) -> None:
        p = SourcePipeline(data_dir=self._tmpdir)
        p.save()
        path = Path(self._tmpdir) / "source_pipeline.json"
        with open(path, "r") as fh:
            data = json.load(fh)
        self.assertIn("sources", data)

    def test_schema_version_in_file(self) -> None:
        p = SourcePipeline(data_dir=self._tmpdir)
        p.save()
        path = Path(self._tmpdir) / "source_pipeline.json"
        with open(path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)

    def test_reload_preserves_state(self) -> None:
        p1 = SourcePipeline(data_dir=self._tmpdir)
        p1.promote_source("morpho_steakhouse", SourceState.CLEAN_INCLUDED, "test")
        p2 = SourcePipeline(data_dir=self._tmpdir)
        self.assertEqual(p2.state("morpho_steakhouse"), SourceState.CLEAN_INCLUDED)

    def test_no_tmp_files_left_after_save(self) -> None:
        """После атомарного write не должно оставаться tmp-файлов."""
        p = SourcePipeline(data_dir=self._tmpdir)
        p.save()
        tmp_files = [f for f in os.listdir(self._tmpdir) if f.startswith(".source_pipeline_tmp_")]
        self.assertEqual(len(tmp_files), 0)


# ══════════════════════════════════════════════════════════════════════════════
# TestUnknownSource
# ══════════════════════════════════════════════════════════════════════════════

class TestUnknownSource(unittest.TestCase):
    """Неизвестные источники → SOURCE_NEEDED по умолчанию."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_unknown_source_state(self) -> None:
        self.assertEqual(self.pipeline.state("totally_unknown_xyz"), SourceState.SOURCE_NEEDED)

    def test_unknown_source_not_strict(self) -> None:
        self.assertFalse(self.pipeline.is_strict_eligible("totally_unknown_xyz"))

    def test_unknown_source_cannot_affect_backtest(self) -> None:
        self.assertFalse(self.pipeline.can_affect_backtest("totally_unknown_xyz"))


# ══════════════════════════════════════════════════════════════════════════════
# TestRS001RS002Sources
# ══════════════════════════════════════════════════════════════════════════════

class TestRS001RS002Sources(unittest.TestCase):
    """RS-001 и RS-002 источники не в strict backtest."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.pipeline = SourcePipeline(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_gmx_btc_source_needed(self) -> None:
        """RS-001: gmx_btc = SOURCE_NEEDED."""
        self.assertEqual(self.pipeline.state("gmx_btc"), SourceState.SOURCE_NEEDED)

    def test_btc_usd_conc_liq_source_needed(self) -> None:
        """RS-002: btc_usd_conc_liq = SOURCE_NEEDED."""
        self.assertEqual(self.pipeline.state("btc_usd_conc_liq"), SourceState.SOURCE_NEEDED)

    def test_rs002_sources_not_in_strict(self) -> None:
        """btc_usd_conc_liq, rwa_conc_liq, trader_losses_vault не в strict."""
        strict = self.pipeline.strict_sources()
        for src in ["btc_usd_conc_liq", "rwa_conc_liq", "trader_losses_vault"]:
            self.assertNotIn(src, strict)

    def test_rs002_cannot_affect_backtest(self) -> None:
        for src in ["btc_usd_conc_liq", "rwa_conc_liq", "trader_losses_vault"]:
            self.assertFalse(self.pipeline.can_affect_backtest(src))


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
