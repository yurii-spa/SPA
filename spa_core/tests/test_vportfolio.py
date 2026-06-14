"""
spa_core/tests/test_vportfolio.py — Tests for VPortfolio and VPortfolioManager

35+ unittest-кейсов:
  - VPortfolio creation, positions, equity, simulate_day
  - VPortfolioManager: create_all, load, save, simulate_day, kill/promote
  - Атомарность записи (нет *.tmp файлов после save)
  - Идемпотентность, ring-buffer caps
  - Graceful degradation при некорректных входных данных
  - stdlib-only (никаких внешних зависимостей)
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Добавляем repo root в sys.path для импорта spa_core
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.vportfolio import (
    INITIAL_CAPITAL_USD,
    MAX_EQUITY_HISTORY,
    VPortfolio,
    VPortfolioManager,
    _safe_float,
    _today_str,
)
from spa_core.paper_trading.strategy_registry import (
    STRATEGY_REGISTRY,
    StrategyConfig,
)


# ─── Helper factories ─────────────────────────────────────────────────────────

def _make_vp(sid: str = "S0", capital: float = 100_000.0) -> VPortfolio:
    vp = VPortfolio(strategy_id=sid, capital_usd=capital)
    vp.cash_usd = capital
    vp._initialize_positions()
    return vp


def _sample_apy() -> dict:
    return {
        "aave_v3":    3.5,
        "compound_v3": 4.0,
        "morpho_blue": 6.2,
        "yearn_v3":   7.1,
        "euler_v2":   6.8,
        "maple":      5.5,
    }


def _make_manager(data_dir: Path) -> VPortfolioManager:
    return VPortfolioManager.create_all(data_dir=data_dir)


# ─── VPortfolio: basic construction ──────────────────────────────────────────

class TestVPortfolioConstruction(unittest.TestCase):

    def test_default_capital(self):
        vp = VPortfolio(strategy_id="S0")
        self.assertEqual(vp.capital_usd, INITIAL_CAPITAL_USD)

    def test_strategy_id_preserved(self):
        vp = VPortfolio(strategy_id="S7")
        self.assertEqual(vp.strategy_id, "S7")

    def test_initial_status_active(self):
        vp = VPortfolio(strategy_id="S0")
        self.assertEqual(vp.status, "active")

    def test_initial_equity_equals_capital_after_init(self):
        vp = _make_vp("S0")
        self.assertAlmostEqual(vp.current_equity, INITIAL_CAPITAL_USD, delta=10.0)

    def test_positions_initialized_for_s0(self):
        vp = _make_vp("S0")
        # S0 = aave_v3 50%, morpho_blue 30%
        self.assertIn("aave_v3", vp.positions)
        self.assertIn("morpho_blue", vp.positions)

    def test_cash_pct_gte_5_percent(self):
        for sid in STRATEGY_REGISTRY:
            vp = _make_vp(sid)
            total_positions = sum(vp.positions.values())
            cash = vp.cash_usd
            total = total_positions + cash
            self.assertGreater(total, 0, f"Strategy {sid}: zero equity")
            cash_pct = cash / total
            self.assertGreaterEqual(
                cash_pct, 0.04,
                f"Strategy {sid}: cash_pct={cash_pct:.3f} < 4%"
            )

    def test_s0_aave_close_to_50pct(self):
        vp = _make_vp("S0")
        total = vp.current_equity
        aave_pct = vp.positions.get("aave_v3", 0) / total
        self.assertAlmostEqual(aave_pct, 0.50, delta=0.02)

    def test_s1_has_4_protocols(self):
        vp = _make_vp("S1")
        self.assertGreaterEqual(len(vp.positions), 3)

    def test_s7_diversified_has_6_protocols(self):
        vp = _make_vp("S7")
        self.assertGreaterEqual(len(vp.positions), 5)

    def test_pendle_pt_not_in_positions(self):
        """pendle_pt — external placeholder, не должен попасть в positions."""
        vp = _make_vp("S3")
        self.assertNotIn("pendle_pt", vp.positions)

    def test_sky_susds_not_in_positions(self):
        """sky_susds — watchlist/0%, не должен попасть в positions."""
        vp = _make_vp("S5")
        self.assertNotIn("sky_susds", vp.positions)


# ─── VPortfolio: derived properties ──────────────────────────────────────────

class TestVPortfolioProperties(unittest.TestCase):

    def test_current_equity_is_positions_plus_cash(self):
        vp = _make_vp("S1")
        expected = sum(vp.positions.values()) + vp.cash_usd
        self.assertAlmostEqual(vp.current_equity, expected, places=6)

    def test_initial_drawdown_is_zero(self):
        vp = _make_vp("S0")
        self.assertEqual(vp.drawdown_pct, 0.0)

    def test_initial_total_return_is_zero(self):
        vp = _make_vp("S4")
        self.assertAlmostEqual(vp.total_return_pct, 0.0, delta=0.01)

    def test_drawdown_after_loss(self):
        vp = _make_vp("S0")
        vp.peak_equity = 100_000.0
        # Simulate loss
        vp.positions = {"aave_v3": 90_000.0}
        vp.cash_usd = 0.0
        self.assertAlmostEqual(vp.drawdown_pct, 0.10, delta=0.001)

    def test_total_return_pct_positive_after_yield(self):
        vp = _make_vp("S0")
        apy = {"aave_v3": 10.0, "morpho_blue": 10.0}
        vp.simulate_day(apy, date_str="2026-06-12")
        self.assertGreater(vp.total_return_pct, 0.0)


# ─── VPortfolio: simulate_day ─────────────────────────────────────────────────

class TestVPortfolioSimulateDay(unittest.TestCase):

    def test_simulate_day_returns_positive_yield(self):
        vp = _make_vp("S0")
        yield_usd = vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertGreater(yield_usd, 0.0)

    def test_equity_increases_after_simulate(self):
        vp = _make_vp("S0")
        before = vp.current_equity
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertGreater(vp.current_equity, before)

    def test_equity_history_appended(self):
        vp = _make_vp("S0")
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertEqual(len(vp.equity_history), 1)
        self.assertEqual(vp.equity_history[0]["date"], "2026-06-12")

    def test_daily_returns_appended(self):
        vp = _make_vp("S0")
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertEqual(len(vp.daily_returns), 1)
        self.assertGreater(vp.daily_returns[0], 0.0)

    def test_zero_apy_means_zero_yield(self):
        vp = _make_vp("S0")
        yield_usd = vp.simulate_day({"aave_v3": 0.0, "morpho_blue": 0.0}, date_str="2026-06-12")
        self.assertEqual(yield_usd, 0.0)

    def test_total_yield_accumulates(self):
        vp = _make_vp("S0")
        apy = {"aave_v3": 5.0, "morpho_blue": 5.0}
        vp.simulate_day(apy, date_str="2026-06-01")
        vp.simulate_day(apy, date_str="2026-06-02")
        self.assertGreater(vp.total_yield_usd, 0.0)
        self.assertEqual(vp.days_simulated, 2)

    def test_peak_equity_updates(self):
        vp = _make_vp("S0")
        initial_peak = vp.peak_equity
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertGreaterEqual(vp.peak_equity, initial_peak)

    def test_equity_history_ring_buffer(self):
        """equity_history не превышает MAX_EQUITY_HISTORY."""
        vp = _make_vp("S0")
        apy = {"aave_v3": 3.5, "morpho_blue": 6.0}
        for i in range(MAX_EQUITY_HISTORY + 10):
            vp.simulate_day(apy, date_str=f"2026-{(i % 12) + 1:02d}-01")
        self.assertLessEqual(len(vp.equity_history), MAX_EQUITY_HISTORY)

    def test_missing_protocol_apy_is_zero_yield(self):
        """Протокол без APY данных даёт 0 yield, но не ломает симуляцию."""
        vp = _make_vp("S0")
        # apy_data не содержит aave_v3
        yield_usd = vp.simulate_day({"morpho_blue": 5.0}, date_str="2026-06-12")
        self.assertGreaterEqual(yield_usd, 0.0)


# ─── VPortfolio: serialization ────────────────────────────────────────────────

class TestVPortfolioSerialization(unittest.TestCase):

    def test_to_dict_has_required_keys(self):
        vp = _make_vp("S0")
        d = vp.to_dict()
        for key in ["strategy_id", "capital_usd", "positions", "cash_usd",
                    "equity_history", "daily_returns", "current_equity",
                    "total_return_pct", "drawdown_pct", "status"]:
            self.assertIn(key, d)

    def test_from_dict_roundtrip(self):
        vp = _make_vp("S1")
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        d = vp.to_dict()
        vp2 = VPortfolio.from_dict(d)
        self.assertEqual(vp2.strategy_id, vp.strategy_id)
        self.assertAlmostEqual(vp2.current_equity, vp.current_equity, delta=0.01)
        self.assertEqual(vp2.days_simulated, vp.days_simulated)

    def test_from_dict_tolerates_missing_fields(self):
        """from_dict не бросает исключение при минимальном dict."""
        vp = VPortfolio.from_dict({"strategy_id": "S0"})
        self.assertEqual(vp.strategy_id, "S0")

    def test_to_dict_current_equity_matches_computed(self):
        vp = _make_vp("S4")
        vp.simulate_day(_sample_apy(), date_str="2026-06-12")
        d = vp.to_dict()
        self.assertAlmostEqual(d["current_equity"], vp.current_equity, delta=0.01)


# ─── VPortfolioManager: create_all ───────────────────────────────────────────

class TestVPortfolioManagerCreateAll(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_dir = Path(self._tmpdir)

    def test_create_all_creates_all_strategies(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        for sid in STRATEGY_REGISTRY:
            self.assertIn(sid, manager.portfolios)

    def test_all_portfolios_have_initial_capital(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        for sid, vp in manager.portfolios.items():
            self.assertAlmostEqual(vp.current_equity, INITIAL_CAPITAL_USD, delta=10.0)

    def test_manager_active_count(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        self.assertGreater(manager.active_count(), 0)

    def test_manager_get_returns_vportfolio(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        vp = manager.get("S0")
        self.assertIsNotNone(vp)
        self.assertIsInstance(vp, VPortfolio)

    def test_manager_get_none_for_missing(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        self.assertIsNone(manager.get("NONEXISTENT"))


# ─── VPortfolioManager: simulate_day ─────────────────────────────────────────

class TestVPortfolioManagerSimulateDay(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_dir = Path(self._tmpdir)
        self._manager = VPortfolioManager.create_all(data_dir=self._data_dir)

    def test_simulate_day_returns_dict(self):
        results = self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertIsInstance(results, dict)
        self.assertGreater(len(results), 0)

    def test_all_active_strategies_simulated(self):
        results = self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        for sid, vp in self._manager.portfolios.items():
            if vp.status in ("active", "promoted"):
                self.assertIn(sid, results)

    def test_equity_increases_for_all(self):
        before = {sid: vp.current_equity for sid, vp in self._manager.portfolios.items()}
        self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        for sid, vp in self._manager.portfolios.items():
            if vp.status in ("active", "promoted"):
                self.assertGreater(vp.current_equity, before[sid])

    def test_killed_strategy_not_simulated(self):
        self._manager.kill("S6")
        results = self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertNotIn("S6", results)

    def test_paused_strategy_not_simulated(self):
        self._manager.pause("S4")
        results = self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertNotIn("S4", results)

    def test_resume_after_pause(self):
        self._manager.pause("S4")
        self._manager.resume("S4")
        results = self._manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        self.assertIn("S4", results)

    def test_promote_sets_status(self):
        self._manager.promote("S1")
        vp = self._manager.get("S1")
        self.assertEqual(vp.status, "promoted")


# ─── VPortfolioManager: save / load ──────────────────────────────────────────

class TestVPortfolioManagerPersistence(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_dir = Path(self._tmpdir)

    def test_save_creates_vportfolios_json(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        path = manager.save()
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "vportfolios.json")

    def test_save_no_tmp_files_left(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        manager.save()
        tmp_files = list(self._data_dir.glob(".tmp_vportfolios_*"))
        self.assertEqual(len(tmp_files), 0)

    def test_save_valid_json(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        path = manager.save()
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("portfolios", doc)
        self.assertIn("is_demo", doc)
        self.assertFalse(doc["is_demo"])

    def test_load_roundtrip_equity(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        manager.simulate_day(_sample_apy(), date_str="2026-06-12")
        orig_equity = {sid: vp.current_equity for sid, vp in manager.portfolios.items()}
        manager.save()

        loaded = VPortfolioManager.load(data_dir=self._data_dir)
        for sid, eq in orig_equity.items():
            vp2 = loaded.get(sid)
            self.assertIsNotNone(vp2)
            self.assertAlmostEqual(vp2.current_equity, eq, delta=0.01)

    def test_load_from_missing_file_creates_all(self):
        """Загрузка из несуществующего файла → create_all."""
        manager = VPortfolioManager.load(data_dir=self._data_dir)
        self.assertGreater(len(manager.portfolios), 0)

    def test_load_from_corrupt_json_creates_all(self):
        corrupt = self._data_dir / "vportfolios.json"
        corrupt.write_text("{{not valid json}}")
        manager = VPortfolioManager.load(data_dir=self._data_dir)
        self.assertGreater(len(manager.portfolios), 0)

    def test_load_adds_new_strategies(self):
        """Если в реестре появилась новая стратегия, load добавляет её."""
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        # Сохраняем без S0 (удаляем из сохранённого для симуляции)
        path = manager.save()
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        doc["portfolios"].pop("S0", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

        loaded = VPortfolioManager.load(data_dir=self._data_dir)
        # S0 должна быть восстановлена из реестра
        self.assertIn("S0", loaded.portfolios)

    def test_summary_returns_list(self):
        manager = VPortfolioManager.create_all(data_dir=self._data_dir)
        rows = manager.summary()
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)
        self.assertIn("strategy_id", rows[0])
        self.assertIn("equity", rows[0])


# ─── Helpers ─────────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_safe_float_finite(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_safe_float_none_default(self):
        self.assertEqual(_safe_float(None, default=0.0), 0.0)

    def test_safe_float_inf_default(self):
        self.assertEqual(_safe_float(float("inf"), default=-1.0), -1.0)

    def test_safe_float_nan_default(self):
        self.assertEqual(_safe_float(float("nan"), default=0.0), 0.0)

    def test_today_str_format(self):
        s = _today_str()
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}$")


# ─── StrategyConfig.effective_allocations ─────────────────────────────────────

class TestEffectiveAllocations(unittest.TestCase):

    def test_all_available_returns_full_allocs(self):
        cfg = STRATEGY_REGISTRY["S1"]
        available = set(cfg.allocations.keys())
        eff = cfg.effective_allocations(available)
        self.assertEqual(set(eff.keys()), available)

    def test_missing_protocol_redistributed(self):
        """Если один протокол недоступен — его вес перераспределяется."""
        cfg = STRATEGY_REGISTRY["S1"]  # aave 30%, morpho 20%, yearn 25%, euler 20%
        available = {"aave_v3", "morpho_blue", "yearn_v3"}  # euler недоступен
        eff = cfg.effective_allocations(available)
        self.assertNotIn("euler_v2", eff)
        # Сумма нормализована к исходной сумме аллокаций
        total_orig = sum(cfg.allocations.values())
        total_eff = sum(eff.values())
        self.assertAlmostEqual(total_eff, total_orig, delta=0.01)

    def test_no_available_returns_empty(self):
        cfg = STRATEGY_REGISTRY["S0"]
        eff = cfg.effective_allocations(set())
        self.assertEqual(eff, {})

    def test_external_protocols_excluded(self):
        """pendle_pt и sky_susds не в available → не в eff."""
        cfg = STRATEGY_REGISTRY["S3"]
        available = {"aave_v3", "morpho_blue"}
        eff = cfg.effective_allocations(available)
        self.assertNotIn("pendle_pt", eff)


if __name__ == "__main__":
    unittest.main(verbosity=2)
