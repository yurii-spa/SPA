"""Приёмка прибора «цена ЗНАКА критерия №3» (заказ #607/G20, ADR-388).

Каждый тест здесь — либо ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (сцена, на которой прибор обязан
сказать «да», рядом со сценой, на которой он обязан сказать «нет»), либо сторож
притязания, которое прибор произносит о себе вслух. Притязание без сторожа уже
однажды оказалось ложным ([ADR-387]: «этот прибор только читает» не краснело ни
на одном тесте, а судья писал в каталог, который прибор обещал не трогать).

Часы инъектируются. FROZEN-DATE-OK: injected-clock — все даты происходят от
_NOW/_ANCHOR и подаются в measure(now=)/run(now=); стенных часов в файле нет.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import criterion_sign_price as C
from spa_core.paper_trading import shadow_trigger_eval as ste

_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
_ANCHOR = _NOW - timedelta(days=60)

#: Все гейты, которые прибор считает снимаемыми — берутся у судьи, как и в коде.
_GATES = sorted(g for g in ste._ALL_GATES if g != "has_legs")

#: Причина отказа → гейт: обратное отображение судьи. Сцены пишутся ПРИЧИНАМИ,
#: а не полем `gates`, ровно потому, что так выглядят 24 из 41 живых строк.
_REASON_OF = {gate: reason for reason, gate in ste.GATE_BY_REASON_PREFIX.items()}


def _day(offset: int) -> str:
    return (_ANCHOR + timedelta(days=offset)).date().isoformat()


def _record(offset: int, *, refused=(), current=None, target=None,
            cost_usd=None, apy=None, verdict="HOLD", capital=100_000.0) -> dict:
    """Одна строка журнала решений в той форме, в какой её читает судья."""
    rec = {
        "schema": "shadow-hist-v2",
        "cycle_date": _day(offset),
        "generated_at": (_ANCHOR + timedelta(days=offset)).isoformat(),
        "verdict": verdict,
        "capital_usd": capital,
        "current_positions": dict(current or {}),
        "target_positions": dict(target or {}),
        "apy_evidenced_pct": dict(apy or {}),
        "reasons": [_REASON_OF[g] for g in refused],
    }
    if cost_usd is not None:
        rec["cost_usd"] = cost_usd
    return rec


class _Scene:
    """Одноразовый каталог данных: живое `data/` этими тестами не касается."""

    def __init__(self, records):
        self.dir = Path(tempfile.mkdtemp(prefix="csp_test_"))
        (self.dir / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _move_scene(*, moves):
    """Сцена из ходов A→B с заданной ставкой вперёд и ценой.

    ``moves`` — список ``(refused_gates, delta_usd, apy_a, apy_b, cost_usd)``.
    За каждым днём хода идут семь дней-носителей ставки, чтобы горизонт судьи
    был полон: иначе счёт считался бы по обрезанному окну и сцена мерила бы
    пробелы вперёд вместо того, ради чего написана.
    """
    records = []
    offset = 0
    for refused, delta, apy_a, apy_b, cost in moves:
        apy = {"a": apy_a, "b": apy_b}
        records.append(_record(
            offset, refused=refused,
            current={"a": 50_000.0, "b": 0.0},
            target={"a": 50_000.0 - delta, "b": delta},
            cost_usd=cost, apy=apy))
        for k in range(1, 8):
            records.append(_record(offset + k, apy=apy))
        offset += 8
    return _Scene(records)


class GateSubsetEnumeration(unittest.TestCase):
    """(а) — перебор состояний гейтов и минимальный ДОСТАТОЧНЫЙ набор."""

    def test_enumeration_covers_every_subset(self):
        out = C.enumerate_gate_subsets([], _GATES)
        self.assertEqual(out["subsets_enumerated"], 2 ** len(_GATES))
        self.assertEqual(out["subsets_possible"], 2 ** len(_GATES))

    def test_a_sufficient_set_is_found_and_reported_minimal(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: прибыльный день, который МОЖНО взять отдельно."""
        days = [
            {"date": "d1", "refused": frozenset({"cooldown_ok"}), "net_usd": 40.0},
            {"date": "d2", "refused": frozenset({"gain_above_band", "min_hold_ok"}),
             "net_usd": -100.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertTrue(out["any_subset_closes_criterion"])
        self.assertEqual(out["minimal_sufficient_sets"], [["cooldown_ok"]])
        self.assertEqual(out["act_days_to_criterion"], 1)

    def test_no_sufficient_set_when_every_day_loses(self):
        """ОБРАТНАЯ СЦЕНА того же контроля: один знак изменён — ответ обязан пропасть."""
        days = [
            {"date": "d1", "refused": frozenset({"cooldown_ok"}), "net_usd": -40.0},
            {"date": "d2", "refused": frozenset({"gain_above_band"}), "net_usd": -1.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertFalse(out["any_subset_closes_criterion"])
        self.assertEqual(out["minimal_sufficient_sets"], [])
        self.assertEqual(out["act_days_to_criterion"], 0)

    def test_superset_of_a_sufficient_set_is_not_reported_as_a_second_answer(self):
        """Достаточных наборов много, МИНИМАЛЬНЫЙ один — иначе 2^k копий одного ответа."""
        days = [{"date": "d1", "refused": frozenset({"cooldown_ok"}),
                 "net_usd": 40.0}]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertEqual(out["minimal_sufficient_sets"], [["cooldown_ok"]])
        self.assertGreater(out["sufficient_subsets"], 1)

    def test_act_days_currency_never_counts_a_losing_bundle(self):
        """Валюта — ACT-дни ПРИ ПОЛОЖИТЕЛЬНОМ счёте.

        Набор, дающий больше дней ценой отрицательного счёта, критерий не
        закрывает; считать его значило бы растить число ровно тогда, когда
        ответ ухудшается.
        """
        days = [
            {"date": "d1", "refused": frozenset({"cooldown_ok"}), "net_usd": 10.0},
            {"date": "d2", "refused": frozenset({"cooldown_ok", "min_hold_ok"}),
             "net_usd": -500.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertEqual(out["act_days_to_criterion"], 1)
        self.assertEqual(out["full_lift"]["act_days"], 2)
        self.assertLess(out["full_lift"]["net_usd"], 0.0)

    def test_a_net_of_exactly_zero_does_NOT_close_the_criterion(self):
        """Мандат владельца говорит `> 0`, а не `>= 0` — граница закреплена.

        Батарея мутаций цикла #607 показала, что подмена `net > 0.0` на
        `net >= 0.0` не краснела ни на одном тесте: ни одна сцена не ставила счёт
        РОВНО в ноль. Ход, окупившийся копейка в копейку, критерий не закрывает.
        """
        days = [{"date": "d1", "refused": frozenset({"cooldown_ok"}),
                 "net_usd": 0.0}]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertFalse(out["any_subset_closes_criterion"])
        self.assertEqual(out["act_days_to_criterion"], 0)
        self.assertEqual(out["days_with_positive_net"], 0)

    def test_a_net_between_zero_and_one_DOES_close_the_criterion(self):
        """Второе плечо той же границы: порог — НОЛЬ, а не единица."""
        days = [{"date": "d1", "refused": frozenset({"cooldown_ok"}),
                 "net_usd": 0.5}]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertTrue(out["any_subset_closes_criterion"])
        self.assertEqual(out["days_with_positive_net"], 1)

    def test_best_subset_is_the_BEST_by_net_and_not_the_worst(self):
        """`best_subset_by_net` — заголовочное число ADR; сравнение закреплено.

        Батарея: подмена `net > best` на `net < best` не краснела — ни одна сцена
        не различала лучший набор и худший, и отчёт мог бы печатать самый
        убыточный набор под словом «лучший».
        """
        days = [
            {"date": "bad", "refused": frozenset({"cooldown_ok"}),
             "net_usd": -500.0},
            {"date": "mild", "refused": frozenset({"min_hold_ok"}),
             "net_usd": -1.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertEqual(out["best_subset_by_net"]["gates_lifted"], ["min_hold_ok"])
        self.assertEqual(out["best_subset_by_net"]["net_usd"], -1.0)
        self.assertEqual(out["best_subset_by_net"]["dates"], ["mild"])

    def test_positive_day_counter_counts_PROFIT_and_not_loss(self):
        """`days_with_positive_net` печатается в заголовке — направление закреплено."""
        days = [
            {"date": "win", "refused": frozenset({"cooldown_ok"}), "net_usd": 7.0},
            {"date": "lose1", "refused": frozenset({"min_hold_ok"}), "net_usd": -7.0},
            {"date": "lose2", "refused": frozenset({"cooldown_ok"}), "net_usd": -8.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertEqual(out["days_with_positive_net"], 1)
        self.assertEqual(out["scorable_days"], 3)

    def test_full_lift_admits_even_a_day_that_refused_EVERY_gate(self):
        """«Полное снятие» значит ВСЕ дни — включая тот, у кого отказали все гейты.

        Батарея: подмена `refused <= full` на `refused < full` не краснела, потому
        что ни в одной сцене не было дня с полным набором отказов. На таком дне
        строгое включение молча выбросило бы его из «полного снятия».
        """
        days = [
            {"date": "all", "refused": frozenset(_GATES), "net_usd": -3.0},
            {"date": "one", "refused": frozenset({"cooldown_ok"}), "net_usd": -1.0},
        ]
        out = C.enumerate_gate_subsets(days, _GATES)
        self.assertEqual(out["full_lift"]["act_days"], 2)
        self.assertEqual(out["full_lift"]["net_usd"], -4.0)

    def test_full_lift_net_bps_uses_the_capital_given(self):
        days = [{"date": "d1", "refused": frozenset(), "net_usd": -100.0}]
        out = C.enumerate_gate_subsets(days, _GATES, capital_usd=100_000.0)
        self.assertEqual(out["full_lift"]["net_bps"], -10.0)
        blind = C.enumerate_gate_subsets(days, _GATES, capital_usd=None)
        self.assertIsNone(blind["full_lift"]["net_bps"])


class Domination(unittest.TestCase):
    """Почему прибыльный день не всегда можно взять — и кем он задавлен."""

    def test_positive_day_whose_refusals_contain_a_losers_is_dominated(self):
        days = [
            {"date": "win", "refused": frozenset({"cooldown_ok", "min_hold_ok"}),
             "net_usd": 5.0},
            {"date": "lose", "refused": frozenset({"cooldown_ok"}),
             "net_usd": -50.0},
        ]
        dom = C.dominated_positive_days(days)
        self.assertEqual(dom["positive_days"], 1)
        self.assertEqual(dom["dominated"], 1)
        self.assertEqual(dom["rows"][0]["dominated_by"], ["lose"])
        self.assertFalse(dom["rows"][0]["isolatable"])
        # И тот же факт, увиденный перебором: набора нет ни одного.
        self.assertFalse(
            C.enumerate_gate_subsets(days, _GATES)["any_subset_closes_criterion"])

    def test_positive_day_with_disjoint_refusals_is_isolatable(self):
        """ОБРАТНАЯ СЦЕНА: те же дни, но наборы не вложены — день берётся отдельно."""
        days = [
            {"date": "win", "refused": frozenset({"min_hold_ok"}), "net_usd": 5.0},
            {"date": "lose", "refused": frozenset({"cooldown_ok"}), "net_usd": -50.0},
        ]
        dom = C.dominated_positive_days(days)
        self.assertEqual(dom["dominated"], 0)
        self.assertTrue(dom["rows"][0]["isolatable"])
        self.assertTrue(
            C.enumerate_gate_subsets(days, _GATES)["any_subset_closes_criterion"])


class ScorableDaysComeFromTheRealJudge(unittest.TestCase):
    """Вердикт, счёт и гейты берутся у соседа — своей копии правила нет."""

    def test_trivial_and_unchecked_days_are_not_in_the_population(self):
        scene = _Scene([
            # ход без существенного оборота ⇒ тривиальный HOLD, решать нечего
            _record(0, refused=("cooldown_ok",), current={"a": 50.0},
                    target={"a": 40.0, "b": 10.0}, cost_usd=1.0,
                    apy={"a": 5.0, "b": 9.0}),
            # ход существенный, но ставки вперёд нет ⇒ UNCHECKED у судьи
            _record(1, refused=("cooldown_ok",), current={"a": 50_000.0},
                    target={"a": 20_000.0, "b": 30_000.0}, cost_usd=40.0),
            _record(2),
        ])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        self.assertEqual(days, [])
        self.assertEqual(ctx["counts"]["scored"], 0)

    def test_a_scored_day_carries_the_judges_own_numbers(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        days, _ = C.scorable_days(scene.dir)
        self.assertEqual(len(days), 1)
        judged = ste.evaluate_window(scene.dir, write=False)
        row = next(r for r in judged["per_verdict"]
                   if r["cycle_date"] == days[0]["date"])
        self.assertAlmostEqual(days[0]["net_usd"], row["net_usd"])
        self.assertAlmostEqual(days[0]["cost_usd"], row["cost_usd_used"])
        self.assertEqual(days[0]["refused"], frozenset({"cooldown_ok"}))

    def test_a_day_without_gates_or_reasons_is_named_not_assumed_clean(self):
        """«Гейты не записаны» ≠ «ни один не отказал» (инв. #17)."""
        records = []
        rec = _record(0, current={"a": 50_000.0},
                      target={"a": 20_000.0, "b": 30_000.0}, cost_usd=40.0,
                      apy={"a": 3.0, "b": 9.0})
        rec.pop("reasons")
        records.append(rec)
        for k in range(1, 8):
            records.append(_record(k, apy={"a": 3.0, "b": 9.0}))
        scene = _Scene(records)
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        self.assertEqual(days, [])
        self.assertEqual(ctx["unmeasured_gate_days"], [_day(0)])

    def test_a_day_missing_a_required_number_is_named_not_counted_as_zero(self):
        """Пропавшая величина дня — третий исход, а НЕ ноль в сумме критерия.

        `row.get("net_usd") or 0.0` склеил бы «поля нет» с «поле равно нулю»
        (инв. #17), и день без счёта вошёл бы в перебор нулём — молча и в сторону
        нормы. Сцена подменяет судью так, чтобы у оценённого дня не стало
        `net_usd`: день обязан ИСЧЕЗНУТЬ из населения и быть НАЗВАН.
        """
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        healthy, _ = C.scorable_days(scene.dir)
        self.assertEqual(len(healthy), 1)

        real = ste.evaluate_window

        def crippled(data_dir, **kwargs):
            doc = real(data_dir, **kwargs)
            for row in doc["per_verdict"]:
                row.pop("net_usd", None)
            return doc

        ste.evaluate_window = crippled
        try:
            days, ctx = C.scorable_days(scene.dir)
        finally:
            ste.evaluate_window = real
        self.assertEqual(days, [])
        self.assertEqual([d["date"] for d in ctx["unmeasured_field_days"]],
                         [healthy[0]["date"]])
        self.assertIn("net_usd", ctx["unmeasured_field_days"][0]["missing"])

    def test_a_measured_zero_is_kept_as_a_value_not_read_as_absence(self):
        """ОБРАТНОЕ ПЛЕЧО: ноль, который ИЗМЕРЕН, обязан остаться днём населения."""
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        real = ste.evaluate_window

        def zeroed(data_dir, **kwargs):
            doc = real(data_dir, **kwargs)
            for row in doc["per_verdict"]:
                if row.get("outcome") in ("hit", "miss") and not row.get("trivial"):
                    row["net_usd"] = 0.0
                    row["benefit_usd_over_checked_days"] = 0.0
            return doc

        ste.evaluate_window = zeroed
        try:
            days, ctx = C.scorable_days(scene.dir)
        finally:
            ste.evaluate_window = real
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["net_usd"], 0.0)
        self.assertEqual(ctx["unmeasured_field_days"], [])

    def test_gate_names_are_taken_from_the_judge_not_a_second_copy(self):
        self.assertEqual(set(C._gate_names()), set(ste._ALL_GATES) - {"has_legs"})


class Decomposition(unittest.TestCase):
    """(б) — счёт на НАЗВАННЫЕ слагаемые."""

    def test_net_is_benefit_minus_cost_on_every_day(self):
        scene = _move_scene(moves=[
            (("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0),
            (("min_hold_ok",), 20_000.0, 4.0, 4.2, 90.0),
        ])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        parts = C.decompose(days, horizon_days=ctx["horizon_days"])
        self.assertEqual(len(parts["per_day"]), 2)
        for row in parts["per_day"]:
            self.assertAlmostEqual(
                row["net_usd"],
                round(row["benefit_usd_observed"] - row["cost_usd_charged"], 2),
                places=2)
        self.assertAlmostEqual(
            parts["totals"]["net_usd"],
            round(parts["totals"]["benefit_usd_observed"]
                  - parts["totals"]["cost_usd_charged"], 2), places=2)

    def test_assumption_share_is_zero_when_every_day_records_its_cost(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        cost = C.decompose(days, horizon_days=ctx["horizon_days"])["cost"]
        self.assertEqual(cost["days_with_recorded_cost"], 1)
        self.assertEqual(cost["days_on_assumption"], 0)
        self.assertEqual(cost["assumption_share_of_charged_cost"], 0.0)

    def test_assumption_share_is_one_when_no_day_records_its_cost(self):
        """ОБРАТНАЯ СЦЕНА: та же сцена без `cost_usd` — доля обязана стать единицей."""
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, None)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        cost = C.decompose(days, horizon_days=ctx["horizon_days"])["cost"]
        self.assertEqual(cost["days_with_recorded_cost"], 0)
        self.assertEqual(cost["days_on_assumption"], 1)
        self.assertEqual(cost["assumption_share_of_charged_cost"], 1.0)

    def test_conservative_label_fails_when_recorded_cost_runs_higher(self):
        """Притязание судьи «CONSERVATIVE» проверяемо — и обе стороны меряются."""
        dear = 2.0 * ste.ASSUMED_COST_BPS_OF_TURNOVER / 10_000.0 * 30_000.0
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, dear)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        cost = C.decompose(days, horizon_days=ctx["horizon_days"])["cost"]
        self.assertFalse(cost["label_conservative_holds"])
        self.assertEqual(cost["days_costlier_than_assumption"], 1)

    def test_conservative_label_holds_when_recorded_cost_runs_lower(self):
        cheap = 0.5 * ste.ASSUMED_COST_BPS_OF_TURNOVER / 10_000.0 * 30_000.0
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, cheap)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        cost = C.decompose(days, horizon_days=ctx["horizon_days"])["cost"]
        self.assertTrue(cost["label_conservative_holds"])
        self.assertEqual(cost["days_costlier_than_assumption"], 0)

    def test_gate_payback_horizon_is_imported_never_a_literal(self):
        from spa_core.allocator.rebalance_economics import TriggerParams
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        hz = C.decompose(days, horizon_days=ctx["horizon_days"])["horizon"]
        self.assertEqual(hz["gate_max_payback_days"],
                         float(TriggerParams().max_payback_days))
        self.assertEqual(hz["judge_horizon_days"], ste.DEFAULT_HORIZON_DAYS)

    def test_breakeven_is_none_when_the_move_loses_money_every_day(self):
        """Ход в ХУДШУЮ ставку не «окупается за много дней» — он не окупается вовсе."""
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 9.0, 1.0, 40.0)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        parts = C.decompose(days, horizon_days=ctx["horizon_days"])
        self.assertIsNone(parts["per_day"][0]["breakeven_horizon_days"])
        self.assertEqual(parts["horizon"]["days_never_breakeven"], 1)

    def test_full_horizon_benefit_is_labelled_an_assumption_and_kept_apart(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        parts = C.decompose(days, horizon_days=ctx["horizon_days"])
        row = parts["per_day"][0]
        self.assertIn("ASSUMPTION_net_usd_at_full_horizon", row)
        # Слагаемое-допущение НЕ входит в счёт: итог равен наблюдённому.
        self.assertAlmostEqual(parts["totals"]["net_usd"], row["net_usd"], places=2)


class Differential(unittest.TestCase):
    """(в) — ACT-дни до критерия под каждым названным входом."""

    def setUp(self):
        # Ход, который при полной цене убыточен, а при десятой части — прибылен.
        self.scene = _move_scene(moves=[
            (("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(self.scene.close)

    def test_cheaper_cost_returns_act_days_and_the_flip_is_bracketed(self):
        out = C.differential(self.scene.dir,
                             horizon_days=ste.DEFAULT_HORIZON_DAYS, gates=_GATES)
        self.assertEqual(out["by_input"]["cost"]["max_act_days_to_criterion"], 1)
        flip = out["flip_factors"]["cost"]
        self.assertTrue(flip["measured"])
        self.assertTrue(flip["monotonicity_control"]["holds"])
        self.assertLess(flip["flip_factor"], 1.0)

    def test_every_variant_names_its_input_and_its_factor(self):
        out = C.differential(self.scene.dir,
                             horizon_days=ste.DEFAULT_HORIZON_DAYS, gates=_GATES)
        self.assertEqual({r["input"] for r in out["rows"]},
                         {"horizon", "cost", "benefit"})
        for row in out["rows"]:
            self.assertIn("how", row)
            self.assertIn("variant", row)

    def test_recorded_zero_is_a_price_and_a_dropped_record_is_not(self):
        """Две величины — ДВА исхода, и обе стороны меряются одной сценой.

        Прежняя редакция этого теста закрепляла ОБРАТНОЕ («ноль цены через данные
        НЕДОСТИЖИМ») и была верным положительным контролем ветки
        ``cost_rec is not None and cost_rec > 0.0``. Ветку снял ЯВНЫЙ ответ владельца
        2026-09-15 (ADR-392 решение 1, вариант 1 → ADR-393): записанный ноль означает
        «ход измерен и бесплатен», а допущение остаётся только для «цену не записали».
        Тест поэтому не ослаблен, а ПЕРЕВЁРНУТ — и в новой форме он краснеет ровно при
        возврате старой ветки, чего от него и требует порядок владельца (инв. #16:
        изменение намеренное, обосновано здесь и записано в журнал цикла #611).
        """
        out = C.differential(self.scene.dir,
                             horizon_days=ste.DEFAULT_HORIZON_DAYS, gates=_GATES)
        dropped = next(r for r in out["rows"] if r["variant"] == "cost: запись убрана")
        zeroed = C._perturbed_dir(self.scene.dir, C._scale_cost(0.0))
        try:
            days, _ = C.scorable_days(zeroed)
            self.assertEqual(len(days), 1)
            # ПЕРВОЕ ПЛЕЧО: ноль ЗАПИСАН ⇒ он и есть цена.
            self.assertEqual(days[0]["cost_source"], "recorded")
            self.assertEqual(days[0]["cost_usd"], 0.0)
        finally:
            shutil.rmtree(zeroed, ignore_errors=True)
        without = C._perturbed_dir(self.scene.dir, C._drop_cost)
        try:
            days, _ = C.scorable_days(without)
            self.assertEqual(len(days), 1)
            # ВТОРОЕ ПЛЕЧО: записи НЕТ ⇒ платится допущение, и оно не ноль.
            self.assertNotEqual(days[0]["cost_source"], "recorded")
            self.assertGreater(days[0]["cost_usd"], 0.0)
        finally:
            shutil.rmtree(without, ignore_errors=True)
        self.assertIsNotNone(dropped["best_net_usd"])

    def test_sensitivity_control_does_not_bind_when_the_baseline_already_closes(self):
        """ОБРАТНОЕ ПЛЕЧО того же контроля: неизменный ПОЛОЖИТЕЛЬНЫЙ ответ — не отказ.

        Рычаг, доносящий возмущение до судьи, доказан самим фактом закрытия
        критерия. Отказывать здесь значило бы молчать ровно на том исходе, ради
        которого прибор написан.
        """
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 40.0, 1.0)])
        self.addCleanup(scene.close)
        out = C.differential(scene.dir, horizon_days=ste.DEFAULT_HORIZON_DAYS,
                             gates=_GATES)
        self.assertFalse(out["sensitivity_control"]["answer_varies"])
        self.assertFalse(out["sensitivity_control"]["binding"])
        self.assertTrue(out["sensitivity_control"]["holds"])
        self.assertNotEqual(C.measure(scene.dir, now=_NOW)["status"],
                            C.STATUS_UNMEASURED)

    def test_sensitivity_control_refuses_when_no_perturbation_moves_the_answer(self):
        """Прибор, чей ответ не двигается ни от чего, мерит себя, а не мир.

        Сцена: ход в ХУДШУЮ ставку. Ни дешевле, ни дольше, ни выше ставка его
        прибыльным не делают — ответ ноль ВЕЗДЕ, и прибор обязан сказать
        «НЕ ИЗМЕРЕНО», а не выдать этот ноль за замер.
        """
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 9.0, 1.0, 40.0)])
        self.addCleanup(scene.close)
        out = C.differential(scene.dir, horizon_days=ste.DEFAULT_HORIZON_DAYS,
                             gates=_GATES)
        self.assertFalse(out["sensitivity_control"]["answer_varies"])
        doc = C.measure(scene.dir, now=_NOW)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("не доходит", doc["unmeasured_reason"])

    def test_flip_is_withdrawn_when_the_sweep_contradicts_the_bisection(self):
        """Деление пополам законно только на монотонной функции — и это СВЕРЯЕТСЯ."""
        flip = {"measured": True, "flip_factor": 0.5, "resolution": 1e-6,
                "direction": "closes_below"}
        rows = [{"variant": "cost x0.1", "factor": 0.1, "closes_positively": False},
                {"variant": "cost x0.9", "factor": 0.9, "closes_positively": True}]
        C._check_flip_against_sweep(flip, rows)
        self.assertFalse(flip["measured"])
        self.assertIsNone(flip["flip_factor"])
        self.assertEqual(flip["monotonicity_control"]["disagreed"],
                         ["cost x0.1", "cost x0.9"])

    def test_flip_survives_a_sweep_that_agrees(self):
        flip = {"measured": True, "flip_factor": 0.5, "resolution": 1e-6,
                "direction": "closes_below"}
        rows = [{"variant": "cost x0.1", "factor": 0.1, "closes_positively": True},
                {"variant": "cost x0.9", "factor": 0.9, "closes_positively": False}]
        C._check_flip_against_sweep(flip, rows)
        self.assertTrue(flip["measured"])
        self.assertTrue(flip["monotonicity_control"]["holds"])

    def test_the_flip_is_narrowed_by_the_bisection_and_not_by_the_bracket(self):
        """Точность перелома — утверждение, и оно закреплено.

        Батарея: подмена `_BISECT_STEPS = 24` на `0` не краснела — перелом
        вырождался в середину исходной скобки, а тесты проверяли только «найден».
        Число, которое ADR печатает с пятью знаками, обязано быть СУЖЕНО.
        """
        flip = C._bisect_flip(self.scene.dir, make_mutate=C._scale_cost,
                              bracket=C.COST_BISECT_BRACKET, rising=False,
                              horizon_days=ste.DEFAULT_HORIZON_DAYS, gates=_GATES)
        self.assertTrue(flip["measured"])
        width = C.COST_BISECT_BRACKET[1] - C.COST_BISECT_BRACKET[0]
        self.assertLess(flip["resolution"], width / 1000.0,
                        "скобка обязана сужаться делением пополам, а не оставаться "
                        "исходной: иначе напечатанный перелом есть её середина")
        midpoint = sum(C.COST_BISECT_BRACKET) / 2.0
        self.assertNotAlmostEqual(flip["flip_factor"], midpoint, places=3)

    def test_bisection_refuses_outside_its_bracket_instead_of_naming_an_edge(self):
        out = C._bisect_flip(self.scene.dir, make_mutate=C._scale_cost,
                             bracket=(0.9, 1.0), rising=False,
                             horizon_days=ste.DEFAULT_HORIZON_DAYS, gates=_GATES)
        self.assertFalse(out["measured"])
        self.assertIsNone(out["flip_factor"])
        self.assertIn("перелом не найден", out["reason"])


class ReadOnly(unittest.TestCase):
    """Притязание «прибор только ЧИТАЕТ» — со сторожем, а не на слово."""

    def test_measure_writes_nothing_into_the_data_dir(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        before = {p.name: p.stat().st_mtime_ns for p in scene.dir.iterdir()}
        C.measure(scene.dir, now=_NOW)
        after = {p.name: p.stat().st_mtime_ns for p in scene.dir.iterdir()}
        self.assertEqual(before, after,
                         "measure() обязан читать: любой новый или тронутый файл "
                         "здесь означает, что судья зовётся без write=False")
        self.assertNotIn(C.OUTPUT_FILENAME, after)

    def test_perturbed_copy_is_removed_after_the_differential(self):
        # Свой корень для временных каталогов, а не общий: перечислять общий
        # значило бы мерить чужой мусор (и стои́ть секунды на машине, где рядом
        # лежат чужие деревья) — вердикт стал бы функцией соседей.
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        tmp_root = Path(tempfile.mkdtemp(prefix="csp_tmproot_"))
        self.addCleanup(shutil.rmtree, tmp_root, True)
        previous = tempfile.tempdir
        tempfile.tempdir = str(tmp_root)
        try:
            self.assertEqual(list(tmp_root.iterdir()), [])
            C.differential(scene.dir, horizon_days=ste.DEFAULT_HORIZON_DAYS,
                           gates=_GATES)
            self.assertEqual(list(tmp_root.iterdir()), [],
                             "возмущённые копии обязаны убираться за собой")
        finally:
            tempfile.tempdir = previous

    def test_perturbed_copy_does_not_touch_the_source(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 40.0)])
        self.addCleanup(scene.close)
        src = scene.dir / "allocation_rationale_history.jsonl"
        before = src.read_bytes()
        tmp = C._perturbed_dir(scene.dir, C._scale_cost(0.1))
        try:
            self.assertEqual(src.read_bytes(), before)
            self.assertNotEqual(
                (tmp / "allocation_rationale_history.jsonl").read_bytes(), before)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_writes_exactly_its_own_artifact_and_nothing_else(self):
        root = Path(tempfile.mkdtemp(prefix="csp_root_"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "data").mkdir()
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        for p in scene.dir.iterdir():
            shutil.copy2(p, root / "data" / p.name)
        before = {p.name for p in (root / "data").iterdir()}
        C.run(root=str(root), now=_NOW)
        after = {p.name for p in (root / "data").iterdir()}
        self.assertEqual(after - before, {C.OUTPUT_FILENAME})


class ThirdOutcome(unittest.TestCase):
    """Отсутствие наблюдения — САМОСТОЯТЕЛЬНЫЙ исход, не ноль и не «чисто» (инв. #17)."""

    def test_empty_history_is_unmeasured_not_a_clean_pass(self):
        scene = _Scene([])
        self.addCleanup(scene.close)
        doc = C.measure(scene.dir, now=_NOW)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("перебирать нечего", doc["unmeasured_reason"])
        self.assertIn("НЕ следует", doc["unmeasured_reason"])

    def test_missing_directory_is_unmeasured_not_a_crash_and_not_a_zero(self):
        doc = C.measure(Path(tempfile.gettempdir()) / "csp_absent_dir", now=_NOW)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertTrue(doc["unmeasured_reason"])

    def test_unmeasured_exit_code_is_two_not_zero_and_not_one(self):
        scene = _Scene([])
        self.addCleanup(scene.close)
        self.assertEqual(
            C.main(["--data-dir", str(scene.dir), "--no-write"]), 2)

    def test_critical_exits_one_and_a_closing_criterion_exits_zero(self):
        shut = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(shut.close)
        self.assertEqual(C.main(["--data-dir", str(shut.dir), "--no-write"]), 1)
        open_ = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 40.0, 1.0)])
        self.addCleanup(open_.close)
        doc = C.measure(open_.dir, now=_NOW)
        self.assertTrue(doc["gate_subsets"]["any_subset_closes_criterion"])
        self.assertEqual(C.main(["--data-dir", str(open_.dir), "--no-write"]), 0)


class Findings(unittest.TestCase):
    """Каждая находка обязана появляться и ИСЧЕЗАТЬ по своему поводу."""

    def test_no_state_closes_finding_appears_and_disappears(self):
        shut = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(shut.close)
        keys = {f["key"] for f in C.measure(shut.dir, now=_NOW)["findings"]}
        self.assertIn("no_gate_state_closes_criterion", keys)

        open_ = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 40.0, 1.0)])
        self.addCleanup(open_.close)
        keys2 = {f["key"] for f in C.measure(open_.dir, now=_NOW)["findings"]}
        self.assertNotIn("no_gate_state_closes_criterion", keys2)

    def test_horizon_mismatch_finding_needs_BOTH_halves_of_its_claim(self):
        """Находка о двух горизонтах — про РАСХОЖДЕНИЕ, а не про «всё плохо».

        Она обязана молчать, когда ни один день не окупается и в горизонт гейта:
        тогда расхождение горизонтов ничего не объясняет, и называть его значило
        бы обвинить исправное место.
        """
        never = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 9.0, 1.0, 40.0)])
        self.addCleanup(never.close)
        days, ctx = C.scorable_days(never.dir)
        parts = C.decompose(days, horizon_days=ctx["horizon_days"])
        self.assertEqual(parts["horizon"]["days_breakeven_within_gate_payback"], 0)
        keys = {f["key"] for f in C._findings(
            C.enumerate_gate_subsets(days, _GATES), parts,
            {"rows": [], "by_input": {}})}
        self.assertNotIn("judge_and_gate_stand_on_different_horizons", keys)

    def test_horizon_mismatch_finding_fires_when_the_gate_would_have_allowed_it(self):
        """Ход, окупающийся за ~15 дн.: гейт (30 дн.) доволен, судья (7 дн.) нет."""
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 80.0)])
        self.addCleanup(scene.close)
        days, ctx = C.scorable_days(scene.dir)
        parts = C.decompose(days, horizon_days=ctx["horizon_days"])
        self.assertEqual(parts["horizon"]["days_breakeven_within_judge_horizon"], 0)
        self.assertEqual(parts["horizon"]["days_breakeven_within_gate_payback"], 1)
        keys = {f["key"] for f in C._findings(
            C.enumerate_gate_subsets(days, _GATES), parts,
            {"rows": [], "by_input": {}})}
        self.assertIn("judge_and_gate_stand_on_different_horizons", keys)

    def test_dominated_positive_day_finding_names_its_dominators(self):
        days = [
            {"date": "win", "refused": frozenset({"cooldown_ok", "min_hold_ok"}),
             "net_usd": 5.0},
            {"date": "lose", "refused": frozenset({"cooldown_ok"}),
             "net_usd": -50.0},
        ]
        found = C._findings(C.enumerate_gate_subsets(days, _GATES),
                            {"cost": {}, "horizon": {}, "per_day": []},
                            {"rows": [], "by_input": {}})
        row = next(f for f in found if f["key"] == "positive_days_are_dominated")
        self.assertIn("lose", row["text"])
        self.assertIn("win", row["text"])

    def test_variant_finding_requires_a_positive_day_that_still_does_not_close(self):
        base = {"gates": _GATES, "subsets_possible": 512, "scorable_days": 1,
                "days_with_positive_net": 0, "any_subset_closes_criterion": True,
                "sufficient_subsets": 1, "minimal_sufficient_sets": [["cooldown_ok"]],
                "best_subset_by_net": {"gates_lifted": [], "act_days": 0,
                                       "net_usd": 0.0},
                "best_positive_subset": None, "act_days_to_criterion": 1,
                "full_lift": {"gates_lifted": [], "act_days": 1, "net_usd": 1.0,
                              "net_bps": None},
                "domination": {"positive_days": 0, "dominated": 0, "isolatable": 0,
                               "rows": []}}
        fires = {"rows": [{"variant": "apy x5", "positive_days": 2,
                           "closes_positively": False,
                           "dominated_positive_days": 2}], "by_input": {}}
        quiet = {"rows": [{"variant": "apy x5", "positive_days": 2,
                           "closes_positively": True,
                           "dominated_positive_days": 2}], "by_input": {}}
        parts = {"cost": {}, "horizon": {}, "per_day": []}
        self.assertIn("positive_day_appears_but_criterion_stays_shut",
                      {f["key"] for f in C._findings(base, parts, fires)})
        self.assertNotIn("positive_day_appears_but_criterion_stays_shut",
                         {f["key"] for f in C._findings(base, parts, quiet)})


class ReportAndSchema(unittest.TestCase):
    """Артефакт и его печать — то, что увидит шаг 0-офис."""

    def test_report_prints_all_three_parts_of_the_order(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        text = "\n".join(C.format_report(C.measure(scene.dir, now=_NOW)))
        for marker in ("(а)", "(б)", "(в)", "[КОНТРОЛЬ]", "НЕ ДОКЛАДЫВАЕТ",
                       "ADVISORY"):
            self.assertIn(marker, text)

    def test_report_of_an_unmeasured_doc_says_so_and_prints_no_numbers(self):
        scene = _Scene([])
        self.addCleanup(scene.close)
        lines = C.format_report(C.measure(scene.dir, now=_NOW))
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0] + lines[1])
        self.assertNotIn("(а)", "\n".join(lines))

    def test_doc_carries_every_key_the_office_step_declares(self):
        from scripts.consume_office_reports import _READ_SCHEMA
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        doc = C.measure(scene.dir, now=_NOW)
        for key in _READ_SCHEMA[C.OUTPUT_FILENAME]:
            self.assertIn(key, doc)

    def test_generated_at_is_the_injected_clock(self):
        scene = _move_scene(moves=[(("cooldown_ok",), 30_000.0, 3.0, 9.0, 200.0)])
        self.addCleanup(scene.close)
        self.assertEqual(C.measure(scene.dir, now=_NOW)["generated_at"],
                         _NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
