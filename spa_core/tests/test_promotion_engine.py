"""
spa_core/tests/test_promotion_engine.py — Тесты для PromotionEngine (MP-366)

Покрытие (70+ тестов):
  - evaluate(): promote / demote / kill / hold (20)
  - MIN_DAYS gate (8)
  - evaluate_all() (10)
  - apply_decisions() cap/floor (15)
  - save_report() (10)
  - edge cases (7)

stdlib only. Атомарные записи. LLM запрещён.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.paper_trading.promotion_engine import (
    ACTION_DEMOTE,
    ACTION_HOLD,
    ACTION_KILL,
    ACTION_PROMOTE,
    ALLOC_CAP,
    ALLOC_FLOOR,
    ALLOC_STEP,
    DEMOTE_SHARPE,
    KILL_CALMAR,
    KILL_DRAWDOWN,
    MIN_DAYS,
    PROMOTE_SHARPE,
    PromotionDecision,
    PromotionEngine,
)


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _metrics(
    sharpe_30d=0.5,
    calmar_30d=0.3,
    max_drawdown_pct=-0.05,
    days_active=30,
) -> dict:
    """Базовые метрики — hold-зона."""
    return {
        "sharpe_30d": sharpe_30d,
        "calmar_30d": calmar_30d,
        "max_drawdown_pct": max_drawdown_pct,
        "days_active": days_active,
    }


def _promote_metrics() -> dict:
    """Метрики, дающие promote."""
    return _metrics(sharpe_30d=1.0, days_active=30)


def _demote_metrics() -> dict:
    """Метрики, дающие demote."""
    return _metrics(sharpe_30d=-0.1, days_active=30)


def _kill_drawdown_metrics() -> dict:
    """Метрики, дающие kill по drawdown."""
    return _metrics(max_drawdown_pct=-0.15, days_active=30)


def _kill_calmar_metrics() -> dict:
    """Метрики, дающие kill по Calmar."""
    return _metrics(calmar_30d=-0.6, days_active=30)


# ─── Тесты evaluate() — promote/demote/kill/hold ──────────────────────────────

class TestEvaluatePromote(unittest.TestCase):
    """20 тестов на promote / demote / kill / hold."""

    def setUp(self):
        self.engine = PromotionEngine()

    # --- Promote (6 тестов) ---

    def test_promote_exact_threshold_plus_epsilon(self):
        """Sharpe чуть выше порога → promote."""
        m = _metrics(sharpe_30d=PROMOTE_SHARPE + 0.001, days_active=30)
        d = self.engine.evaluate("S1", m)
        self.assertEqual(d.action, ACTION_PROMOTE)

    def test_promote_high_sharpe(self):
        """Sharpe = 2.0 → promote."""
        m = _metrics(sharpe_30d=2.0, days_active=30)
        d = self.engine.evaluate("S2", m)
        self.assertEqual(d.action, ACTION_PROMOTE)

    def test_promote_strategy_id_preserved(self):
        """strategy_id передаётся без изменений."""
        m = _promote_metrics()
        d = self.engine.evaluate("S5", m)
        self.assertEqual(d.strategy_id, "S5")

    def test_promote_reason_contains_sharpe(self):
        """reason содержит sharpe значение."""
        m = _metrics(sharpe_30d=1.5, days_active=30)
        d = self.engine.evaluate("S3", m)
        self.assertIn("sharpe_30d", d.reason)

    def test_promote_metrics_stored(self):
        """Метрики хранятся в решении без изменений."""
        m = _promote_metrics()
        d = self.engine.evaluate("S0", m)
        self.assertEqual(d.metrics["sharpe_30d"], m["sharpe_30d"])

    def test_promote_timestamp_present(self):
        """PromotionDecision содержит непустой timestamp."""
        m = _promote_metrics()
        d = self.engine.evaluate("S0", m)
        self.assertTrue(len(d.ts) > 0)

    # --- Demote (5 тестов) ---

    def test_demote_sharpe_below_zero(self):
        """Sharpe = -0.1 → demote."""
        m = _metrics(sharpe_30d=-0.1, days_active=30)
        d = self.engine.evaluate("S1", m)
        self.assertEqual(d.action, ACTION_DEMOTE)

    def test_demote_sharpe_very_negative(self):
        """Sharpe = -3.0 (но нет kill-условий) → demote."""
        m = _metrics(sharpe_30d=-3.0, calmar_30d=0.5,
                     max_drawdown_pct=-0.01, days_active=30)
        d = self.engine.evaluate("S2", m)
        self.assertEqual(d.action, ACTION_DEMOTE)

    def test_demote_reason_contains_keyword(self):
        """reason содержит 'Demote'."""
        m = _demote_metrics()
        d = self.engine.evaluate("S3", m)
        self.assertIn("Demote", d.reason)

    def test_demote_strategy_id_correct(self):
        """strategy_id сохраняется при demote."""
        m = _demote_metrics()
        d = self.engine.evaluate("S7", m)
        self.assertEqual(d.strategy_id, "S7")

    def test_demote_metrics_snapshot(self):
        """Метрики в решении = переданный словарь."""
        m = _demote_metrics()
        d = self.engine.evaluate("S4", m)
        self.assertEqual(d.metrics["calmar_30d"], m["calmar_30d"])

    # --- Kill (6 тестов) ---

    def test_kill_by_drawdown(self):
        """max_drawdown_pct < -0.10 → kill."""
        m = _kill_drawdown_metrics()
        d = self.engine.evaluate("S6", m)
        self.assertEqual(d.action, ACTION_KILL)

    def test_kill_by_calmar(self):
        """calmar_30d < -0.5 → kill."""
        m = _kill_calmar_metrics()
        d = self.engine.evaluate("S4", m)
        self.assertEqual(d.action, ACTION_KILL)

    def test_kill_both_conditions(self):
        """Оба kill-условия → kill."""
        m = _metrics(calmar_30d=-1.0, max_drawdown_pct=-0.20, days_active=30)
        d = self.engine.evaluate("S0", m)
        self.assertEqual(d.action, ACTION_KILL)

    def test_kill_reason_contains_kill(self):
        """reason содержит 'Kill'."""
        m = _kill_drawdown_metrics()
        d = self.engine.evaluate("S1", m)
        self.assertIn("Kill", d.reason)

    def test_kill_priority_over_promote(self):
        """kill-условие имеет приоритет над высоким Sharpe."""
        m = _metrics(sharpe_30d=2.0, max_drawdown_pct=-0.15, days_active=30)
        d = self.engine.evaluate("S2", m)
        self.assertEqual(d.action, ACTION_KILL)

    def test_kill_priority_over_demote(self):
        """kill-условие имеет приоритет над demote."""
        m = _metrics(sharpe_30d=-0.5, calmar_30d=-0.9, days_active=30)
        d = self.engine.evaluate("S3", m)
        self.assertEqual(d.action, ACTION_KILL)

    # --- Hold (3 теста) ---

    def test_hold_sharpe_in_range(self):
        """Sharpe в [0, 0.8] при хорошем drawdown → hold."""
        m = _metrics(sharpe_30d=0.5, days_active=30)
        d = self.engine.evaluate("S0", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_hold_sharpe_exact_zero(self):
        """Sharpe ровно 0.0 → hold (граница demote не включена)."""
        m = _metrics(sharpe_30d=0.0, days_active=30)
        d = self.engine.evaluate("S1", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_hold_sharpe_exact_promote_threshold(self):
        """Sharpe ровно PROMOTE_SHARPE=0.8 → hold (граница promote не включена)."""
        m = _metrics(sharpe_30d=PROMOTE_SHARPE, days_active=30)
        d = self.engine.evaluate("S2", m)
        self.assertEqual(d.action, ACTION_HOLD)


# ─── Тесты MIN_DAYS gate ──────────────────────────────────────────────────────

class TestMinDaysGate(unittest.TestCase):
    """8 тестов на MIN_DAYS gate."""

    def setUp(self):
        self.engine = PromotionEngine()

    def test_zero_days_always_hold(self):
        """0 дней → hold независимо от метрик."""
        m = _metrics(sharpe_30d=2.0, days_active=0)
        d = self.engine.evaluate("S0", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_one_day_hold(self):
        """1 день → hold."""
        m = _metrics(sharpe_30d=2.0, days_active=1)
        d = self.engine.evaluate("S1", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_min_days_minus_one_hold(self):
        """MIN_DAYS - 1 → hold."""
        m = _metrics(sharpe_30d=2.0, days_active=MIN_DAYS - 1)
        d = self.engine.evaluate("S2", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_min_days_exact_not_hold(self):
        """Ровно MIN_DAYS → не hold (если sharpe подходит)."""
        m = _metrics(sharpe_30d=1.0, days_active=MIN_DAYS)
        d = self.engine.evaluate("S3", m)
        self.assertNotEqual(d.action, ACTION_HOLD)

    def test_min_days_gate_kill_conditions_also_blocked(self):
        """До MIN_DAYS kill-условия не применяются → hold."""
        m = _metrics(max_drawdown_pct=-0.50, days_active=MIN_DAYS - 1)
        d = self.engine.evaluate("S4", m)
        self.assertEqual(d.action, ACTION_HOLD)

    def test_min_days_gate_reason_mentions_days(self):
        """reason при hold из-за MIN_DAYS содержит количество дней."""
        days = 5
        m = _metrics(days_active=days)
        d = self.engine.evaluate("S5", m)
        self.assertIn(str(days), d.reason)

    def test_min_days_gate_reason_mentions_min_days(self):
        """reason при hold из-за MIN_DAYS упоминает MIN_DAYS."""
        m = _metrics(days_active=3)
        d = self.engine.evaluate("S6", m)
        self.assertIn(str(MIN_DAYS), d.reason)

    def test_beyond_min_days_can_kill(self):
        """После MIN_DAYS kill работает нормально."""
        m = _metrics(max_drawdown_pct=-0.20, days_active=MIN_DAYS + 1)
        d = self.engine.evaluate("S7", m)
        self.assertEqual(d.action, ACTION_KILL)


# ─── Тесты evaluate_all ──────────────────────────────────────────────────────

class TestEvaluateAll(unittest.TestCase):
    """10 тестов на evaluate_all."""

    def setUp(self):
        self.engine = PromotionEngine()

    def _mixed_metrics_dict(self) -> dict:
        return {
            "S0": _metrics(sharpe_30d=1.0, days_active=30),   # promote
            "S1": _metrics(sharpe_30d=-0.1, days_active=30),  # demote
            "S2": _metrics(max_drawdown_pct=-0.15, days_active=30),  # kill
            "S3": _metrics(sharpe_30d=0.5, days_active=30),   # hold
        }

    def test_returns_list(self):
        """evaluate_all возвращает список."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        self.assertIsInstance(result, list)

    def test_length_matches_input(self):
        """Количество решений = количество стратегий."""
        md = self._mixed_metrics_dict()
        result = self.engine.evaluate_all(md)
        self.assertEqual(len(result), len(md))

    def test_all_decisions_are_promotion_decision(self):
        """Все элементы — PromotionDecision."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        for d in result:
            self.assertIsInstance(d, PromotionDecision)

    def test_strategy_ids_preserved(self):
        """strategy_id из входного dict сохраняются в решениях."""
        md = self._mixed_metrics_dict()
        result = self.engine.evaluate_all(md)
        ids = {d.strategy_id for d in result}
        self.assertEqual(ids, set(md.keys()))

    def test_promote_decision_present(self):
        """В результате есть promote-решение для S0."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        actions = {d.strategy_id: d.action for d in result}
        self.assertEqual(actions["S0"], ACTION_PROMOTE)

    def test_demote_decision_present(self):
        """В результате есть demote-решение для S1."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        actions = {d.strategy_id: d.action for d in result}
        self.assertEqual(actions["S1"], ACTION_DEMOTE)

    def test_kill_decision_present(self):
        """В результате есть kill-решение для S2."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        actions = {d.strategy_id: d.action for d in result}
        self.assertEqual(actions["S2"], ACTION_KILL)

    def test_hold_decision_present(self):
        """В результате есть hold-решение для S3."""
        result = self.engine.evaluate_all(self._mixed_metrics_dict())
        actions = {d.strategy_id: d.action for d in result}
        self.assertEqual(actions["S3"], ACTION_HOLD)

    def test_empty_dict_returns_empty_list(self):
        """Пустой словарь → пустой список."""
        result = self.engine.evaluate_all({})
        self.assertEqual(result, [])

    def test_single_entry(self):
        """Один элемент в словаре → один результат."""
        result = self.engine.evaluate_all({"S0": _promote_metrics()})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].action, ACTION_PROMOTE)


# ─── Тесты apply_decisions cap/floor ─────────────────────────────────────────

class TestApplyDecisions(unittest.TestCase):
    """15 тестов на apply_decisions cap/floor."""

    def setUp(self):
        self.engine = PromotionEngine()

    def _decision(self, sid, action) -> PromotionDecision:
        return PromotionDecision(
            strategy_id=sid,
            action=action,
            reason="test",
            metrics={},
        )

    # --- Promote (+5%, cap 30%) ---

    def test_promote_increases_allocation(self):
        """promote добавляет 5% к аллокации."""
        allocs = {"S0": 0.10}
        d = self._decision("S0", ACTION_PROMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S0"], 0.15, places=6)

    def test_promote_cap_at_30_percent(self):
        """promote не превышает 30% (cap)."""
        allocs = {"S0": 0.28}
        d = self._decision("S0", ACTION_PROMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S0"], ALLOC_CAP, places=6)

    def test_promote_at_cap_stays(self):
        """Уже на cap 30% → остаётся 30%."""
        allocs = {"S0": 0.30}
        d = self._decision("S0", ACTION_PROMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S0"], ALLOC_CAP, places=6)

    def test_promote_above_cap_clamped(self):
        """Аллокация выше cap → после promote всё равно cap."""
        allocs = {"S0": 0.35}   # превышает cap
        d = self._decision("S0", ACTION_PROMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S0"], ALLOC_CAP, places=6)

    # --- Demote (-5%, floor 0%) ---

    def test_demote_decreases_allocation(self):
        """demote уменьшает на 5%."""
        allocs = {"S1": 0.20}
        d = self._decision("S1", ACTION_DEMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S1"], 0.15, places=6)

    def test_demote_floor_at_zero(self):
        """demote не опускает ниже 0% (floor)."""
        allocs = {"S1": 0.02}
        d = self._decision("S1", ACTION_DEMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S1"], ALLOC_FLOOR, places=6)

    def test_demote_at_floor_stays(self):
        """Уже 0% → после demote остаётся 0%."""
        allocs = {"S1": 0.0}
        d = self._decision("S1", ACTION_DEMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S1"], ALLOC_FLOOR, places=6)

    def test_demote_exact_step(self):
        """Аллокация = ALLOC_STEP → floor после demote."""
        allocs = {"S2": ALLOC_STEP}
        d = self._decision("S2", ACTION_DEMOTE)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S2"], ALLOC_FLOOR, places=6)

    # --- Kill (→ 0%) ---

    def test_kill_sets_to_zero(self):
        """kill обнуляет аллокацию."""
        allocs = {"S3": 0.25}
        d = self._decision("S3", ACTION_KILL)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S3"], 0.0, places=6)

    def test_kill_already_zero_stays_zero(self):
        """kill при нулевой аллокации → 0."""
        allocs = {"S3": 0.0}
        d = self._decision("S3", ACTION_KILL)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S3"], 0.0, places=6)

    # --- Hold ---

    def test_hold_unchanged(self):
        """hold не меняет аллокацию."""
        allocs = {"S4": 0.18}
        d = self._decision("S4", ACTION_HOLD)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S4"], 0.18, places=6)

    # --- Прочие проверки ---

    def test_other_strategies_untouched(self):
        """Стратегии без решений не изменяются."""
        allocs = {"S0": 0.20, "S1": 0.15, "S2": 0.10}
        d = self._decision("S0", ACTION_KILL)
        result = self.engine.apply_decisions([d], allocs)
        self.assertAlmostEqual(result["S1"], 0.15, places=6)
        self.assertAlmostEqual(result["S2"], 0.10, places=6)

    def test_missing_strategy_added_with_zero(self):
        """Стратегия из decisions, отсутствующая в map, добавляется с 0."""
        allocs = {}
        d = self._decision("S5", ACTION_PROMOTE)
        result = self.engine.apply_decisions([d], allocs)
        # 0 + 5% = 5%
        self.assertAlmostEqual(result["S5"], ALLOC_STEP, places=6)

    def test_multiple_decisions_applied(self):
        """Несколько решений применяются все."""
        allocs = {"S0": 0.20, "S1": 0.15}
        decisions = [
            self._decision("S0", ACTION_PROMOTE),
            self._decision("S1", ACTION_KILL),
        ]
        result = self.engine.apply_decisions(decisions, allocs)
        self.assertAlmostEqual(result["S0"], 0.25, places=6)
        self.assertAlmostEqual(result["S1"], 0.0, places=6)

    def test_empty_decisions_unchanged(self):
        """Пустой список решений → аллокации не меняются."""
        allocs = {"S0": 0.30, "S1": 0.20}
        result = self.engine.apply_decisions([], allocs)
        self.assertEqual(result, allocs)


# ─── Тесты save_report ────────────────────────────────────────────────────────

class TestSaveReport(unittest.TestCase):
    """10 тестов на save_report."""

    def setUp(self):
        self.engine = PromotionEngine()
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _sample_decisions(self) -> list:
        return [
            PromotionDecision("S0", ACTION_PROMOTE, "test promote", {}),
            PromotionDecision("S1", ACTION_KILL, "test kill", {}),
        ]

    def test_file_created(self):
        """save_report создаёт файл."""
        p = Path(self.tmp_dir)
        self.engine.save_report(self._sample_decisions(), p)
        self.assertTrue((p / "promotion_report.json").exists())

    def test_returns_path(self):
        """save_report возвращает Path к файлу."""
        p = Path(self.tmp_dir)
        result = self.engine.save_report(self._sample_decisions(), p)
        self.assertIsInstance(result, Path)
        self.assertTrue(result.exists())

    def test_valid_json(self):
        """Файл содержит валидный JSON."""
        p = Path(self.tmp_dir)
        out = self.engine.save_report(self._sample_decisions(), p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_json_has_decisions_key(self):
        """JSON содержит ключ 'decisions'."""
        p = Path(self.tmp_dir)
        out = self.engine.save_report(self._sample_decisions(), p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("decisions", data)

    def test_json_decisions_count(self):
        """Количество decisions в JSON совпадает с входными."""
        decisions = self._sample_decisions()
        p = Path(self.tmp_dir)
        out = self.engine.save_report(decisions, p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["decisions"]), len(decisions))

    def test_json_has_generated_at(self):
        """JSON содержит ключ 'generated_at'."""
        p = Path(self.tmp_dir)
        out = self.engine.save_report(self._sample_decisions(), p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("generated_at", data)

    def test_json_has_thresholds(self):
        """JSON содержит ключ 'thresholds' с константами."""
        p = Path(self.tmp_dir)
        out = self.engine.save_report(self._sample_decisions(), p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("thresholds", data)
        self.assertIn("PROMOTE_SHARPE", data["thresholds"])

    def test_atomic_write_no_tmp_leftover(self):
        """Tmp-файлы не остаются после записи."""
        p = Path(self.tmp_dir)
        self.engine.save_report(self._sample_decisions(), p)
        tmp_files = [
            f for f in os.listdir(self.tmp_dir)
            if f.startswith(".tmp_promotion_report_")
        ]
        self.assertEqual(len(tmp_files), 0)

    def test_empty_decisions_saves_ok(self):
        """Пустой список решений сохраняется без ошибок."""
        p = Path(self.tmp_dir)
        out = self.engine.save_report([], p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["decisions"], [])

    def test_overwrite_existing_file(self):
        """Повторный save_report перезаписывает файл."""
        p = Path(self.tmp_dir)
        self.engine.save_report(self._sample_decisions(), p)
        # Второй вызов с другими данными
        single = [PromotionDecision("S9", ACTION_HOLD, "hold", {})]
        out = self.engine.save_report(single, p)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["decisions"]), 1)
        self.assertEqual(data["decisions"][0]["strategy_id"], "S9")


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """7 edge-case тестов."""

    def setUp(self):
        self.engine = PromotionEngine()

    def test_none_sharpe_no_promote(self):
        """sharpe_30d = None → не promote."""
        m = _metrics(sharpe_30d=None, days_active=30)
        d = self.engine.evaluate("S0", m)
        self.assertNotEqual(d.action, ACTION_PROMOTE)

    def test_none_sharpe_no_demote(self):
        """sharpe_30d = None → не demote."""
        m = _metrics(sharpe_30d=None, days_active=30)
        d = self.engine.evaluate("S0", m)
        self.assertNotEqual(d.action, ACTION_DEMOTE)

    def test_none_calmar_no_kill(self):
        """calmar_30d = None → kill не срабатывает только по calmar."""
        m = _metrics(calmar_30d=None, max_drawdown_pct=-0.01, days_active=30)
        d = self.engine.evaluate("S1", m)
        self.assertNotEqual(d.action, ACTION_KILL)

    def test_drawdown_exactly_at_kill_threshold_not_killed(self):
        """drawdown ровно на KILL_DRAWDOWN=-0.10 → не kill (< строго)."""
        m = _metrics(max_drawdown_pct=KILL_DRAWDOWN, days_active=30)
        d = self.engine.evaluate("S2", m)
        # Граничное: ровно -0.10 не должно давать kill (условие строгое <)
        self.assertNotEqual(d.action, ACTION_KILL)

    def test_to_dict_contains_all_fields(self):
        """PromotionDecision.to_dict() содержит все ключи."""
        pd = PromotionDecision("S0", ACTION_HOLD, "reason", {"k": "v"})
        d = pd.to_dict()
        for key in ("strategy_id", "action", "reason", "metrics", "ts"):
            self.assertIn(key, d)

    def test_original_alloc_map_not_mutated(self):
        """apply_decisions не изменяет оригинальный allocation_map."""
        allocs = {"S0": 0.20}
        original_copy = dict(allocs)
        d = PromotionDecision("S0", ACTION_KILL, "kill", {})
        self.engine.apply_decisions([d], allocs)
        self.assertEqual(allocs, original_copy)

    def test_evaluate_unknown_strategy_id(self):
        """Незнакомый strategy_id обрабатывается без исключений."""
        m = _promote_metrics()
        d = self.engine.evaluate("UNKNOWN_XYZ", m)
        self.assertIn(d.action, {ACTION_PROMOTE, ACTION_DEMOTE, ACTION_KILL, ACTION_HOLD})


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
