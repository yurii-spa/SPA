#!/usr/bin/env python3
"""Тесты StrategySelector + shadow→allocator feedback loop (SPA-V408).

Сетевых вызовов нет; всё работает во временном каталоге. pytest в репо не
установлен, поэтому тесты на ``unittest`` (stdlib)::

    python3 -m unittest spa_core.tests.test_strategy_selector -v
    python3 spa_core/tests/test_strategy_selector.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.strategy_selector import (
    StrategySelector,
    confidence_for,
)
from spa_core.allocator.allocator import StrategyAllocator


# ─── helpers ────────────────────────────────────────────────────────────────


def write_comparison(path: Path, strategies: list[dict]) -> None:
    doc = {
        "updated_at": "2026-06-10T00:00:00+00:00",
        "strategies": strategies,
        "best_strategy": strategies[0]["name"] if strategies else None,
        "days_running": max((s.get("days_running", 0) for s in strategies), default=0),
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


def strat(name, sortino, sharpe=None, days=30) -> dict:
    return {
        "name": name,
        "label": name,
        "sortino": sortino,
        "sharpe": sharpe,
        "days_running": days,
    }


def write_portfolio(strategies_dir: Path, name: str, positions: dict) -> None:
    strategies_dir.mkdir(parents=True, exist_ok=True)
    equity = sum(positions.values()) + 1000.0  # +cash buffer
    (strategies_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "initial_capital": 100000.0,
                "cash": 1000.0,
                "positions": positions,
                "equity": equity,
            }
        ),
        encoding="utf-8",
    )


# ─── confidence_for ─────────────────────────────────────────────────────────


class TestConfidence(unittest.TestCase):
    def test_high_medium_low_none_thresholds(self):
        self.assertEqual(confidence_for(30, 1.2), "high")
        self.assertEqual(confidence_for(45, 1.2), "high")
        self.assertEqual(confidence_for(15, 1.2), "medium")
        self.assertEqual(confidence_for(29, 1.2), "medium")
        self.assertEqual(confidence_for(7, 1.2), "low")
        self.assertEqual(confidence_for(14, 1.2), "low")
        self.assertIsNone(confidence_for(6, 1.2))  # < 7 days
        self.assertIsNone(confidence_for(30, None))  # no sortino


# ─── StrategySelector ───────────────────────────────────────────────────────


class TestStrategySelector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cmp = self.dir / "strategy_shadow_comparison.json"
        self.strat_dir = self.dir / "strategies"

    def tearDown(self):
        self.tmp.cleanup()

    def _selector(self) -> StrategySelector:
        return StrategySelector(comparison_path=self.cmp, strategies_dir=self.strat_dir)

    # 1
    def test_selects_highest_sortino(self):
        write_comparison(
            self.cmp,
            [
                strat("s1_concentration", 1.50, sharpe=1.0, days=30),
                strat("s2_momentum", 0.80, sharpe=2.0, days=30),
                strat("s0_baseline", 1.20, sharpe=1.5, days=30),
            ],
        )
        write_portfolio(self.strat_dir, "s1_concentration", {"aave_v3": 50000.0})
        best = self._selector().select_best()
        self.assertIsNotNone(best)
        self.assertEqual(best["strategy_id"], "s1_concentration")
        self.assertEqual(best["sortino"], 1.50)
        self.assertEqual(best["confidence"], "high")

    # 2
    def test_returns_none_when_file_missing(self):
        # cmp файл не создан
        self.assertIsNone(self._selector().select_best())
        self.assertIsNone(self._selector().get_allocation_weights_for_best())

    # 3
    def test_returns_none_when_all_sortino_null(self):
        write_comparison(
            self.cmp,
            [
                strat("s0_baseline", None, days=30),
                strat("s1_concentration", None, days=30),
            ],
        )
        self.assertIsNone(self._selector().select_best())

    # 4
    def test_returns_none_when_low_confidence_only(self):
        # все стратегии < 7 дней → не кандидаты вовсе
        write_comparison(
            self.cmp,
            [
                strat("s1_concentration", 2.0, days=3),
                strat("s2_momentum", 1.5, days=5),
            ],
        )
        self.assertIsNone(self._selector().select_best())

    # 5
    def test_returns_none_when_only_low_band_7_to_14(self):
        # 7..14 дней → confidence "low" → НЕ selectable → None
        write_comparison(
            self.cmp,
            [
                strat("s1_concentration", 3.0, days=10),
                strat("s2_momentum", 2.0, days=12),
            ],
        )
        self.assertIsNone(self._selector().select_best())

    # 6
    def test_tiebreak_by_sharpe(self):
        # одинаковый Sortino → выигрывает больший Sharpe
        write_comparison(
            self.cmp,
            [
                strat("s_low_sharpe", 1.0, sharpe=0.5, days=30),
                strat("s_high_sharpe", 1.0, sharpe=1.9, days=30),
            ],
        )
        write_portfolio(self.strat_dir, "s_high_sharpe", {"aave_v3": 40000.0})
        best = self._selector().select_best()
        self.assertEqual(best["strategy_id"], "s_high_sharpe")

    # 7
    def test_skips_low_picks_medium(self):
        # лучший по Sortino — low confidence (12д); selectable только medium (20д)
        write_comparison(
            self.cmp,
            [
                strat("s_low", 9.0, days=12),
                strat("s_medium", 1.1, days=20),
            ],
        )
        write_portfolio(self.strat_dir, "s_medium", {"morpho_blue": 30000.0})
        best = self._selector().select_best()
        self.assertEqual(best["strategy_id"], "s_medium")
        self.assertEqual(best["confidence"], "medium")

    # 8
    def test_allocation_weights_normalized(self):
        write_comparison(self.cmp, [strat("s1_concentration", 1.5, days=30)])
        write_portfolio(
            self.strat_dir,
            "s1_concentration",
            {"maple": 20000.0, "euler_v2": 20000.0, "morpho_blue": 10000.0},
        )
        w = self._selector().get_allocation_weights_for_best()
        self.assertIsNotNone(w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        # 20/20/10 из 50 → 0.4/0.4/0.2
        self.assertAlmostEqual(w["maple"], 0.4, places=9)
        self.assertAlmostEqual(w["euler_v2"], 0.4, places=9)
        self.assertAlmostEqual(w["morpho_blue"], 0.2, places=9)

    # 9
    def test_weights_none_when_portfolio_missing(self):
        # стратегия выбрана, но её portfolio-файла нет → weights None / {}
        write_comparison(self.cmp, [strat("s_ghost", 1.5, days=30)])
        sel = self._selector()
        best = sel.select_best()
        self.assertIsNotNone(best)
        self.assertEqual(best["allocation_weights"], {})
        self.assertIsNone(sel.get_allocation_weights_for_best())

    # 10
    def test_inf_sentinel_sortino_ranks_top(self):
        # comparator пишет 999.0 для +inf Sortino — должен ранжироваться выше
        write_comparison(
            self.cmp,
            [
                strat("s_normal", 2.0, days=30),
                strat("s_inf", 999.0, days=30),
            ],
        )
        write_portfolio(self.strat_dir, "s_inf", {"aave_v3": 10000.0})
        best = self._selector().select_best()
        self.assertEqual(best["strategy_id"], "s_inf")

    # 11
    def test_corrupt_comparison_returns_none(self):
        self.cmp.write_text("{ this is not json", encoding="utf-8")
        self.assertIsNone(self._selector().select_best())

    # 12
    def test_reason_and_selected_at_present(self):
        write_comparison(self.cmp, [strat("s1_concentration", 1.234, days=35)])
        write_portfolio(self.strat_dir, "s1_concentration", {"aave_v3": 10000.0})
        best = self._selector().select_best()
        self.assertIn("Sortino", best["reason"])
        self.assertIn("N=35", best["reason"])
        self.assertIsInstance(best["selected_at"], str)
        self.assertTrue(best["selected_at"])

    # 13
    def test_negative_and_zero_positions_dropped(self):
        write_comparison(self.cmp, [strat("s1", 1.5, days=30)])
        write_portfolio(
            self.strat_dir,
            "s1",
            {"good": 30000.0, "zero": 0.0, "neg": -5000.0},
        )
        w = self._selector().get_allocation_weights_for_best()
        self.assertEqual(set(w), {"good"})
        self.assertAlmostEqual(w["good"], 1.0, places=9)


# ─── allocator integration (SPA-V408) ───────────────────────────────────────


class TestAllocatorStrategyLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.status = self.dir / "adapter_orchestrator_status.json"
        self.cmp = self.dir / "strategy_shadow_comparison.json"
        self.strat_dir = self.dir / "strategies"
        self.risk = self.dir / "risk_scores.json"
        self._write_status()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_status(self):
        adapters = [
            {"protocol": "morpho_blue", "apy_pct": 8.3, "tvl_usd": 0.0, "tier": "T2", "status": "ok"},
            {"protocol": "yearn_v3", "apy_pct": 7.2, "tvl_usd": 0.0, "tier": "T2", "status": "ok"},
            {"protocol": "euler_v2", "apy_pct": 9.1, "tvl_usd": 0.0, "tier": "T2", "status": "ok"},
            {"protocol": "maple", "apy_pct": 10.5, "tvl_usd": 0.0, "tier": "T2", "status": "ok"},
        ]
        self.status.write_text(json.dumps({"adapters": adapters}), encoding="utf-8")

    def _allocator(self, **kw):
        return StrategyAllocator(
            status_path=self.status,
            risk_scores_path=self.risk,
            comparison_path=self.cmp,
            strategies_dir=self.strat_dir,
            **kw,
        )

    # 14
    def test_strategy_loop_in_allocator_output(self):
        write_comparison(self.cmp, [strat("s1_concentration", 1.5, days=30)])
        write_portfolio(self.strat_dir, "s1_concentration",
                        {"maple": 30000.0, "euler_v2": 30000.0})
        res = self._allocator().allocate()
        self.assertTrue(res.strategy_loop_active)
        self.assertEqual(res.selected_strategy_id, "s1_concentration")
        self.assertEqual(res.strategy_confidence, "high")

    # 15
    def test_fallback_to_risk_adjusted_when_no_strategy(self):
        # нет comparison-файла → fallback на сконфигурированную модель
        res = self._allocator().allocate()
        self.assertFalse(res.strategy_loop_active)
        self.assertIsNone(res.selected_strategy_id)
        self.assertEqual(res.model_used, "risk_adjusted")

    # 16
    def test_fallback_when_only_low_confidence(self):
        write_comparison(self.cmp, [strat("s1_concentration", 9.0, days=10)])
        write_portfolio(self.strat_dir, "s1_concentration", {"maple": 30000.0})
        res = self._allocator().allocate()
        self.assertFalse(res.strategy_loop_active)

    # 17
    def test_caps_applied_over_strategy_weights(self):
        # стратегия концентрирует 100% в одном T2-пуле → cap 0.20 должен сработать
        write_comparison(self.cmp, [strat("s_concentrated", 2.0, days=30)])
        write_portfolio(self.strat_dir, "s_concentrated", {"maple": 100000.0})
        res = self._allocator().allocate()
        self.assertTrue(res.strategy_loop_active)
        for p, w in res.target_weights.items():
            self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9)
        # maple не может держать больше 20% несмотря на 100% в стратегии
        self.assertLessEqual(res.target_weights["maple"], 0.20 + 1e-9)

    # 18
    def test_strategy_loop_can_be_disabled(self):
        write_comparison(self.cmp, [strat("s1_concentration", 1.5, days=30)])
        write_portfolio(self.strat_dir, "s1_concentration", {"maple": 30000.0})
        res = self._allocator(strategy_loop_enabled=False).allocate()
        self.assertFalse(res.strategy_loop_active)

    # 19
    def test_risk_grade_d_exclusion_over_strategy(self):
        # стратегия держит maple, но risk-grade D → maple исключён (вес 0)
        write_comparison(self.cmp, [strat("s1", 2.0, days=30)])
        write_portfolio(self.strat_dir, "s1",
                        {"maple": 50000.0, "euler_v2": 50000.0})
        self.risk.write_text(
            json.dumps({"scores": [{"slug": "maple", "grade": "D"}]}),
            encoding="utf-8",
        )
        res = self._allocator().allocate()
        self.assertTrue(res.strategy_loop_active)
        # maple исключён риском поверх весов стратегии
        self.assertEqual(res.target_weights.get("maple", 0.0), 0.0)
        self.assertTrue(res.risk_model_applied)

    # 20
    def test_strategy_weights_only_for_active_adapters(self):
        # стратегия держит пул, которого нет в снимке оркестратора → игнор
        write_comparison(self.cmp, [strat("s1", 1.5, days=30)])
        write_portfolio(self.strat_dir, "s1",
                        {"maple": 30000.0, "ghost_pool": 70000.0})
        res = self._allocator().allocate()
        self.assertTrue(res.strategy_loop_active)
        self.assertNotIn("ghost_pool", res.target_weights)

    # 21
    def test_weights_sum_within_caps_and_le_one(self):
        write_comparison(self.cmp, [strat("s1", 1.5, days=30)])
        write_portfolio(self.strat_dir, "s1",
                        {"maple": 25000.0, "euler_v2": 25000.0,
                         "morpho_blue": 25000.0, "yearn_v3": 25000.0})
        res = self._allocator().allocate()
        self.assertLessEqual(sum(res.target_weights.values()), 1.0 + 1e-9)
        for w in res.target_weights.values():
            self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
