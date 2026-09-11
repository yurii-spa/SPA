"""Приёмка `spa_core/monitoring/shadow_blockade_attribution.py` (ADR-271).

Каждая сцена здесь — положительный контроль на конкретную ошибку, а не
украшение: сторож, ни разу не видевший настоящей поломки, ничего не держит
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

# FROZEN-DATE-OK: injected-clock — единственный литерал даты в файле это
# ``ANCHOR``; все даты фикстур (cycle_date строк истории и ts ходов) выводятся
# из него арифметикой, и он же передаётся измеряемому коду аргументом
# ``attribute(..., now=ANCHOR + ...)``. Календарь хоста на вердикт не влияет.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.monitoring.shadow_blockade_attribution import (
    CAUSE_IMPORTED,
    CAUSE_OWN,
    GATE_PROVENANCE,
    STATUS_CRITICAL,
    STATUS_OK,
    STATUS_UNMEASURED,
    attribute,
)
from spa_core.paper_trading.shadow_trigger_eval import _ALL_GATES

ANCHOR = datetime(2026, 8, 6, tzinfo=timezone.utc)

#: Потолки пинятся явно: вердикт сцены не должен зависеть от того, в каком
#: режиме собран `TriggerParams.for_mode()` на хосте прогона.
PARAMS = dataclasses.replace(
    TriggerParams.for_mode(), max_turnover_per_week=0.25, max_turnover_per_move=0.15)

CAPITAL = 100_000.0
WEEK_BUDGET = 25_000.0


def _day(n: int) -> str:
    return (ANCHOR + timedelta(days=n)).date().isoformat()


def _ts(n: int, hour: int = 6) -> str:
    return (ANCHOR + timedelta(days=n, hours=hour)).isoformat()


def _record(n: int, *, move_usd: float, gates: dict,
            target: dict | None = None) -> dict:
    return {
        "cycle_date": _day(n),
        "capital_usd": CAPITAL,
        "turnover_usd": move_usd,
        "target_positions": target if target is not None else {"aave_v3": 40_000.0},
        "gates": gates,
    }


def _gates(**overrides) -> dict:
    base = {g: True for g in _ALL_GATES}
    base.update(overrides)
    return base


def _trade(n: int, delta_abs: float) -> dict:
    return {"trade_id": f"T{n:03d}", "ts": _ts(n), "type": "rebalance",
            "delta_abs": delta_abs}


class ADayWithoutCapitalIsUnmeasuredNotOneDollar(unittest.TestCase):
    """ADR-344 (инвариант #17): доли дня не считаются по подставленному капиталу.

    Прежде строка без `capital_usd` считалась по ОДНОМУ ДОЛЛАРУ (`or 0.0) or 1.0`),
    и каждая доля — оборот, метание, бюджет недели — выходила в сотни раз больше
    настоящей, оставаясь на вид числом. То же с `turnover_usd`: «оборота нет» и
    «оборот не записан» — разные вещи.
    """

    def _day(self, **over):
        row = {"cycle_date": "2026-08-01", "verdict": "HOLD", "capital_usd": 100_000.0,
               "turnover_usd": 1_000.0, "current_positions": {"a": 1.0},
               "target_positions": {"a": 1.0},
               "gates": {"has_legs": True, "cooldown_ok": True}}
        row.update(over)
        return row

    def _measure(self, rows):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "allocation_rationale_history.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            return attribute(d, now=ANCHOR + timedelta(days=40), params=PARAMS)

    def test_a_row_without_capital_is_counted_unmeasured(self):
        row = self._day(); row.pop("capital_usd")
        doc = self._measure([row])
        self.assertIn("2026-08-01", doc.get("unmeasured_days", []))

    def test_a_row_without_turnover_is_counted_unmeasured(self):
        row = self._day(); row.pop("turnover_usd")
        doc = self._measure([row])
        self.assertIn("2026-08-01", doc.get("unmeasured_days", []))

    def test_a_recorded_zero_turnover_is_a_measurement(self):
        """Обратная сторона: записанный ноль — ответ, и день считается."""
        doc = self._measure([self._day(turnover_usd=0.0)])
        self.assertNotIn("2026-08-01", doc.get("unmeasured_days", []))


class _Fixture:
    """Одноразовый data-каталог. `data/` рабочего дерева не трогается никогда."""

    def __init__(self, records, trades):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        lines = "\n".join(json.dumps(r) for r in records)
        (self.path / "allocation_rationale_history.jsonl").write_text(
            lines + ("\n" if lines else ""), encoding="utf-8")
        if trades is not None:
            (self.path / "trades.json").write_text(
                json.dumps(trades), encoding="utf-8")

    def run(self, **kw):
        return attribute(self.path, now=ANCHOR + timedelta(days=40),
                         params=PARAMS, **kw)

    def close(self):
        self.tmp.cleanup()


def _run(records, trades):
    fx = _Fixture(records, trades)
    try:
        return fx.run()
    finally:
        fx.close()


class ProvenanceMapIsComplete(unittest.TestCase):
    """Храповик: новый гейт без провенанса молча выпал бы из атрибуции."""

    def test_every_gate_of_the_real_evaluator_has_a_provenance(self):
        missing = sorted(g for g in _ALL_GATES if g not in GATE_PROVENANCE)
        self.assertEqual(
            [], missing,
            "гейт(ы) без строки в GATE_PROVENANCE: атрибуция занизила бы ровно "
            "ту величину, ради которой написана")

    def test_the_map_names_no_gate_the_evaluator_does_not_have(self):
        extra = sorted(g for g in GATE_PROVENANCE if g not in _ALL_GATES)
        self.assertEqual([], extra, "провенанс назначен несуществующему гейту")


class BindingSideIsMeasuredNotAssumed(unittest.TestCase):
    """Главный вопрос модуля: чей вход СВЯЗЫВАЕТ названный блокер."""

    def test_own_move_alone_over_the_whole_week_budget_is_blamed_on_the_shadow(self):
        """Авария 2026-09-09: живой оборот $0, ход 35 % капитала.

        Блокада называет `week_turnover_ok` и адресует владельцу дырку. Но
        крутить бюджет не от чего: чужой истории в этот день нет вовсе.
        """
        recs = [_record(n, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False, move_turnover_ok=False))
                for n in range(3)]
        doc = _run(recs, [])          # журнал пуст ⇒ живой оборот $0
        self.assertEqual(STATUS_CRITICAL, doc["status"])
        self.assertEqual(CAUSE_OWN, doc["binding_cause"])
        week = next(r for r in doc["gate_attribution"]
                    if r["gate"] == "week_turnover_ok")
        self.assertEqual(3, week[CAUSE_OWN])
        self.assertEqual(0, week[CAUSE_IMPORTED])
        self.assertTrue(any("СОБСТВЕННЫЙ ход" in f for f in doc["findings"]))

    def test_live_history_alone_over_budget_is_not_blamed_on_the_shadow(self):
        """Обратный контроль: тень предлагает КРОХОТНЫЙ ход, бюджет сожгла книга.

        Без этой сцены модуль мог бы всегда отвечать «виновата тень» — и был бы
        зелёным на аварии, ради которой написан.
        """
        recs = [_record(n, move_usd=1_000.0,
                        gates=_gates(week_turnover_ok=False))
                for n in range(3)]
        trades = [_trade(0, 400_000.0)]        # книга выжгла бюджет сама
        doc = _run(recs, trades)
        week = next(r for r in doc["gate_attribution"]
                    if r["gate"] == "week_turnover_ok")
        self.assertEqual(3, week[CAUSE_IMPORTED])
        self.assertEqual(0, week[CAUSE_OWN])
        self.assertEqual(CAUSE_IMPORTED, doc["binding_cause"])
        self.assertFalse(any("СОБСТВЕННЫЙ ход" in f for f in doc["findings"]),
                         "чужой оборот записан тени в вину")

    def test_neither_side_alone_over_budget_is_joint_not_a_convenient_pick(self):
        recs = [_record(n, move_usd=15_000.0,
                        gates=_gates(week_turnover_ok=False))
                for n in range(3)]
        trades = [_trade(0, 15_000.0)]   # 15k + 15k > 25k, но по отдельности нет
        doc = _run(recs, trades)
        week = next(r for r in doc["gate_attribution"]
                    if r["gate"] == "week_turnover_ok")
        self.assertEqual(3, week["joint"])
        self.assertEqual(0, week[CAUSE_OWN])
        self.assertEqual(0, week[CAUSE_IMPORTED])

    def test_purely_imported_gates_are_never_charged_to_the_shadow(self):
        recs = [_record(n, move_usd=5_000.0,
                        gates=_gates(cooldown_ok=False, min_hold_ok=False))
                for n in range(3)]
        doc = _run(recs, [])
        for name in ("cooldown_ok", "min_hold_ok"):
            row = next(r for r in doc["gate_attribution"] if r["gate"] == name)
            self.assertEqual(3, row[CAUSE_IMPORTED], name)
            self.assertEqual(0, row[CAUSE_OWN], name)


class LookaheadIsClosedAndTheFixIsMeasured(unittest.TestCase):
    """Первая редакция модуля смотрела в будущее — окно писателя без верхней границы."""

    def test_a_trade_after_the_day_does_not_leak_into_that_days_turnover(self):
        recs = [_record(0, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False))]
        trades = [_trade(20, 400_000.0)]      # ход СИЛЬНО ПОЗЖЕ разбираемого дня
        doc = _run(recs, trades)
        day = doc["days"][0]
        self.assertEqual(0.0, day["live_week_turnover_usd"],
                         "оборот будущего засчитан в прошлый день")
        self.assertEqual(400_000.0, day["live_week_turnover_unbounded_usd"])
        self.assertEqual(CAUSE_OWN, day["refused"]["week_turnover_ok"])

    def test_the_control_counts_the_days_the_unbounded_window_would_flip(self):
        recs = [_record(0, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False))]
        trades = [_trade(20, 400_000.0)]
        doc = _run(recs, trades)
        self.assertEqual(1, doc["lookahead_control"]["days_attribution_would_flip"],
                         "поправка объявлена, но её величина не измерена")

    def test_no_future_trades_means_the_control_reports_zero(self):
        recs = [_record(5, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False))]
        trades = [_trade(0, 400_000.0)]       # ход РАНЬШЕ дня — в окно попадает честно
        doc = _run(recs, trades)
        self.assertEqual(0, doc["lookahead_control"]["days_attribution_would_flip"])


class UnmeasuredIsAThirdOutcomeNotAPass(unittest.TestCase):
    """«Не измерено» обязано быть слышно: fail-OPEN тише красного и потому опаснее."""

    def test_missing_trades_journal_is_unmeasured_not_ok(self):
        recs = [_record(n, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False)) for n in range(3)]
        doc = _run(recs, None)                # trades.json не создан
        self.assertEqual(STATUS_UNMEASURED, doc["status"])
        self.assertIn("trades.json", doc["unmeasured_reason"])

    def test_empty_history_is_unmeasured_with_a_named_reason(self):
        doc = _run([], [])
        self.assertEqual(STATUS_UNMEASURED, doc["status"])
        self.assertTrue(doc["unmeasured_reason"])

    def test_the_earliest_third_outcome_still_carries_the_declared_schema(self):
        """Ранний выход не имеет права оставлять артефакт без части схемы.

        Иначе сверка схемы шага 0-офис краснела бы на ЧЕСТНОМ «не измерено» —
        то есть наказывала бы ровно за тот исход, ради которого она нужна, и
        первым же побуждением было бы этот исход убрать.
        """
        declared = ("status", "named_blockers", "binding_cause", "material_days",
                    "gate_attribution", "target_instability", "lookahead_control",
                    "findings")
        for doc, what in ((_run([], []), "пустая история"),
                          (_run([_record(0, move_usd=35_000.0,
                                         gates=_gates(week_turnover_ok=False))], None),
                           "нет журнала ходов")):
            self.assertEqual(STATUS_UNMEASURED, doc["status"], what)
            self.assertEqual([], [k for k in declared if k not in doc], what)

    def test_a_day_carrying_neither_gates_nor_reasons_is_not_counted_as_passed(self):
        good = _record(0, move_usd=35_000.0, gates=_gates(week_turnover_ok=False))
        blind = {"cycle_date": _day(1), "capital_usd": CAPITAL,
                 "turnover_usd": 35_000.0, "target_positions": {"aave_v3": 40_000.0}}
        doc = _run([good, blind], [])
        self.assertIn(_day(1), doc["unmeasured_days"],
                      "молчащая строка прочитана как согласие всех гейтов")

    def test_a_trivial_hold_is_excluded_rather_than_counted_as_a_refusal(self):
        """День, где решать было нечего, не должен разбавлять замер хода.

        Утверждать здесь ``material_days`` бесполезно: это число приходит из
        переиспользованной переписи `arming_blockade`, а не из нашего прохода, и
        мутация нашей ветки его не трогает (замер батареи, M9 выжила). Предмет —
        собственные величины модуля: ``days`` и медиана предложенного хода.
        """
        recs = [_record(0, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False)),
                _record(1, move_usd=0.0, gates=_gates(has_legs=False))]
        doc = _run(recs, [])
        self.assertEqual(1, doc["material_days"])
        self.assertEqual([_day(0)], [r["date"] for r in doc["days"]],
                         "тривиальный HOLD попал в разбор дней")
        self.assertEqual(
            0.35, doc["target_instability"]["proposed_move_frac"]["median"],
            "нулевой ход тривиального HOLD разбавил медиану предложенного хода")


class UpstreamCauseIsNamedSeparately(unittest.TestCase):
    """Неустойчивость цели — отдельная величина, а не пересказ отказа гейта."""

    def test_a_flip_flopping_target_is_reported_as_the_upstream_cause(self):
        targets = [{"aave_v3": 40_000.0}, {"compound_v3": 40_000.0}] * 3
        recs = [_record(n, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False), target=t)
                for n, t in enumerate(targets)]
        doc = _run(recs, [])
        ti = doc["target_instability"]
        self.assertEqual(0.4, ti["day_over_day_churn_frac"]["median"])
        self.assertTrue(any("сама ЦЕЛЬ" in f for f in doc["findings"]))

    def test_a_stable_target_within_the_caps_raises_nothing(self):
        recs = [_record(n, move_usd=5_000.0, gates=_gates(),
                        target={"aave_v3": 40_000.0}) for n in range(4)]
        doc = _run(recs, [])
        self.assertEqual(STATUS_OK, doc["status"])
        self.assertEqual([], doc["findings"])

    def test_target_churn_is_one_sided_like_turnover_not_double_counted(self):
        recs = [_record(0, move_usd=5_000.0, gates=_gates(),
                        target={"aave_v3": 40_000.0}),
                _record(1, move_usd=5_000.0, gates=_gates(),
                        target={"compound_v3": 40_000.0})]
        doc = _run(recs, [])
        # переставили $40k из одного в другой: односторонне это 40 %, а не 80 %
        self.assertEqual(0.4, doc["target_instability"]
                              ["day_over_day_churn_frac"]["median"])


class ReconstructionCarriesItsOwnErrorRate(unittest.TestCase):
    """Подтверждающий инструмент без своей цены ошибки подтверждать не вправе."""

    def test_agreement_with_the_known_gate_state_is_reported(self):
        recs = [_record(n, move_usd=35_000.0,
                        gates=_gates(week_turnover_ok=False)) for n in range(3)]
        doc = _run(recs, [])
        rec = doc["reconstruction_agreement"]
        self.assertEqual(3, rec["days_with_known_gate"])
        self.assertEqual(3, rec["agreed"])

    def test_disagreeing_reconstruction_refuses_instead_of_attributing(self):
        """Гейт записан ПРОЙДЕННЫМ там, где реконструкция говорит «за бюджетом».

        Такое расхождение означает, что восстановленный вход не тот, которым
        судил писатель, — и тогда атрибуция по нему запрещена.
        """
        recs = [_record(n, move_usd=35_000.0, gates=_gates(week_turnover_ok=True))
                for n in range(9)]
        recs.append(_record(9, move_usd=35_000.0,
                            gates=_gates(week_turnover_ok=False)))
        doc = _run(recs, [])
        self.assertEqual(STATUS_UNMEASURED, doc["status"])
        self.assertIn("реконструкция", doc["unmeasured_reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
