"""Сторож прибора «меняет ли расширение записи САМО решение» (заказ #540).

Каждый тест ниже воспроизводит НАСТОЯЩУЮ аварию или настоящий класс ошибки, а
не украшает вывод:

* проекция решения (``decision_slice``) собрана так, чтобы поймать ровно тот
  промах, на котором проба #540 объявила поверхность решения нечувствительной:
  имя критерия под ключом ``criterion`` (не ``name``), поле ``observation_days``
  (не ``observed_days``) и обязательное присутствие ``counts``;
* отказ прибора при несработавшем положительном контроле — иначе «ничего не
  изменилось» неотличимо от «мерили не тот путь»;
* три разряда перехода (``scored``/``flipped``/``lost``) разведены: смешать
  «появился вердикт» с «вердикт поменялся» значит ответить на другой вопрос.

Дат-литералов здесь нет намеренно: все даты производятся от инъектированного
якоря, поэтому календарь на вердикт теста не влияет.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import decision_record_verdict_sensitivity as drvs

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock —
# якорь передаётся в код параметром `now`, а все даты записей производятся от него
# арифметикой ниже; ни одна отметка не берётся у стенных часов.


def _day(i: int) -> str:
    return (ANCHOR + timedelta(days=i)).date().isoformat()


def _rec(i: int, *, current, target, rates, verdict="HOLD", cost=10.0,
         turnover=None) -> dict:
    return {
        "schema": "shadow-hist-v2",
        "cycle_date": _day(i),
        "verdict": verdict,
        "current_positions": dict(current),
        "target_positions": dict(target),
        "apy_evidenced_pct": dict(rates),
        "capital_usd": 100_000.0,
        "cost_usd": cost,
        "turnover_usd": turnover,
        "legs": [],
        "gates": {},
    }


class DecisionSliceTest(unittest.TestCase):
    """Проекция обязана нести именно те поля, которые проба #540 промахнула."""

    def setUp(self):
        self.doc = {
            "generated_at": "irrelevant",
            "counts": {"scored": 15, "unchecked": 7},
            "criteria": [{"criterion": "hit_rate", "status": "PASS",
                          "actual": 1.0, "threshold": ">=0.6"}],
            "per_verdict": [{"cycle_date": _day(0), "verdict": "HOLD",
                             "outcome": "hit", "material": True}],
            "hit_rate": 1.0,
            "observation_days": 35,
            "ready_to_arm": False,
        }

    def test_criterion_name_is_read_from_the_key_the_report_uses(self):
        """#540 брала имя ключом `name` и получала None у каждого критерия."""
        sl = drvs.decision_slice(self.doc)
        self.assertEqual([c["criterion"] for c in sl["criteria"]], ["hit_rate"])
        self.assertNotIn(None, [c["criterion"] for c in sl["criteria"]])

    def test_population_field_uses_the_name_the_report_actually_has(self):
        """`observed_days` в отчёте НЕТ — есть `observation_days`."""
        sl = drvs.decision_slice(self.doc)
        self.assertEqual(sl["observation_days"], 35)

    def test_counts_are_part_of_the_decision_slice(self):
        """Поехало именно `counts`; проба #540 его в слепок не клала вовсе."""
        sl = drvs.decision_slice(self.doc)
        self.assertEqual(sl["counts"]["scored"], 15)

    def test_slice_drops_the_clock_but_keeps_everything_else(self):
        sl = drvs.decision_slice(self.doc)
        self.assertNotIn("generated_at", sl)
        self.assertIn("per_day", sl)


class TransitionsTest(unittest.TestCase):
    """«Появился вердикт» и «вердикт переменился» — РАЗНЫЕ ответы заказу."""

    def _slice(self, per_day):
        return {"per_day": per_day, "criteria": [], "counts": {}}

    def test_unchecked_to_scored_is_not_a_flip(self):
        tr = drvs._outcome_transitions(
            self._slice({_day(1): {"outcome": "UNCHECKED"}}),
            self._slice({_day(1): {"outcome": "hit"}}))
        self.assertEqual(len(tr["scored"]), 1)
        self.assertEqual(tr["flipped"], [])

    def test_hit_to_miss_is_a_flip(self):
        tr = drvs._outcome_transitions(
            self._slice({_day(1): {"outcome": "hit"}}),
            self._slice({_day(1): {"outcome": "miss"}}))
        self.assertEqual(len(tr["flipped"]), 1)
        self.assertEqual(tr["scored"], [])

    def test_losing_a_verdict_is_its_own_class(self):
        """Расширение, ОТНИМАЮЩЕЕ вердикт, — отдельная находка, не «переворот»."""
        tr = drvs._outcome_transitions(
            self._slice({_day(1): {"outcome": "hit"}}),
            self._slice({_day(1): {"outcome": "UNCHECKED"}}))
        self.assertEqual(len(tr["lost"]), 1)
        self.assertEqual(tr["flipped"], [])
        self.assertEqual(tr["scored"], [])


class CriteriaStatusTest(unittest.TestCase):
    def test_only_a_status_change_counts_not_a_value_wobble(self):
        """Сдвиг ЧИСЛА критерия взвод не двигает — двигает смена СТАТУСА."""
        base = {"criteria": [{"criterion": "hit_rate", "status": "PASS", "actual": 1.0}]}
        same = {"criteria": [{"criterion": "hit_rate", "status": "PASS", "actual": 0.9}]}
        self.assertEqual(drvs._criteria_status_changes(base, same), [])
        moved = {"criteria": [{"criterion": "hit_rate", "status": "FAIL", "actual": 0.3}]}
        self.assertEqual(len(drvs._criteria_status_changes(base, moved)), 1)


class JudgeRefusesWithoutAPositiveControlTest(unittest.TestCase):
    """Отрицательный результат без сработавшего контроля — НЕ результат."""

    def _doc(self, fired):
        return {
            "findings": [],
            "capability": {"fired": fired, "note": "контроль не поставлен",
                           "day": _day(3), "outcome_before": "hit",
                           "outcome_after": "hit", "advantage_pp_to_flip": 1.0,
                           "forward_days": 7, "hit_rate_before": 1.0,
                           "hit_rate_after": 1.0},
            "rate_spread_observed": {"spread_pp": 5.0},
            "live_path": {"verdict": "journal_is_an_output_here",
                          "verdict_real": "HOLD", "gates_real": {"a": True},
                          "control": {"gates_moved": ["a"]}},
            "replay": {"transitions": {"scored": [], "flipped": [], "lost": []},
                       "criteria_status_changes": [],
                       "base": {"counts": {}}, "wide": {"counts": {}}},
            "prior_claim": {"verdict": "prior_claim_stands"},
        }

    def test_no_flip_in_the_control_means_unmeasured(self):
        doc = self._doc(False)
        drvs._judge(doc)
        self.assertEqual(doc["status"], drvs.STATUS_UNMEASURED)
        self.assertTrue(any(f.startswith("[НЕ ИЗМЕРЕНО]") for f in doc["findings"]))

    def test_a_fired_control_lets_the_negative_answer_stand(self):
        doc = self._doc(True)
        drvs._judge(doc)
        self.assertNotEqual(doc["status"], drvs.STATUS_UNMEASURED)
        self.assertTrue(any("ОТВЕТ ЗАКАЗУ, половина 2" in f for f in doc["findings"]))

    def test_a_real_flip_is_critical_not_a_footnote(self):
        doc = self._doc(True)
        doc["replay"]["transitions"]["flipped"] = [f"{_day(2)}: hit→miss"]
        drvs._judge(doc)
        self.assertEqual(doc["status"], drvs.STATUS_CRITICAL)


class LivePathFailsClosedTest(unittest.TestCase):
    """Контроль на проводку не сработал ⇒ молчание журнала ничего не доказывает."""

    def test_control_that_does_not_move_any_gate_yields_unmeasured(self):
        calls = {"n": 0}

        def fake_verdict(sandbox, rows, inputs, *, trades, now):
            calls["n"] += 1
            return {"decision": "HOLD", "gates": {"g": True}, "reasons": [],
                    "cost_usd": 1.0, "gain_pp": 0.0}

        orig = drvs._writer_verdict
        drvs._writer_verdict = fake_verdict
        try:
            out = drvs.live_path_sensitivity(Path("/nonexistent"), [], [], {}, [],
                                             ANCHOR)
        finally:
            drvs._writer_verdict = orig
        self.assertEqual(out["verdict"], "unmeasured")
        self.assertFalse(out["control"]["fired"])

    def test_a_writer_that_will_not_run_is_named_not_swallowed(self):
        def boom(*a, **k):
            raise RuntimeError("писатель не собрался")

        orig = drvs._writer_verdict
        drvs._writer_verdict = boom
        try:
            out = drvs.live_path_sensitivity(Path("/nonexistent"), [], [], {}, [],
                                             ANCHOR)
        finally:
            drvs._writer_verdict = orig
        self.assertEqual(out["verdict"], "unmeasured")
        self.assertIn("писатель не собрался", out["note"])


class PriorClaimRecheckTest(unittest.TestCase):
    """Утверждение #540 опровергается ТОЛЬКО расхождением с замером."""

    def test_identical_snapshot_plus_grown_population_refutes_the_claim(self):
        def fake_probe(spec, root):
            return 2, {"criteria": [[None, "PASS", 35]], "observed_days": None}

        import spa_core.monitoring.decision_journal_coverage as djc
        orig = djc._reader_probe
        djc._reader_probe = fake_probe
        try:
            with TemporaryDirectory() as td:
                out = drvs.prior_claim_recheck(
                    Path(td), [], [],
                    {"counts": {"scored": 15, "unchecked": 7}},
                    {"counts": {"scored": 20, "unchecked": 2}})
        finally:
            djc._reader_probe = orig
        self.assertEqual(out["verdict"], "prior_claim_refuted")
        joined = " ".join(out["reasons_it_stayed_silent"])
        self.assertIn("criterion", joined)
        self.assertIn("observation_days", joined)
        self.assertIn("counts", joined)

    def test_identical_snapshot_with_unchanged_population_leaves_it_standing(self):
        def fake_probe(spec, root):
            return 2, {"criteria": [[None, "PASS", 35]], "observed_days": None}

        import spa_core.monitoring.decision_journal_coverage as djc
        orig = djc._reader_probe
        djc._reader_probe = fake_probe
        try:
            with TemporaryDirectory() as td:
                out = drvs.prior_claim_recheck(
                    Path(td), [], [], {"counts": {"scored": 15}},
                    {"counts": {"scored": 15}})
        finally:
            djc._reader_probe = orig
        self.assertEqual(out["verdict"], "prior_claim_stands")


class CapabilityControlTest(unittest.TestCase):
    """Контроль обязан РАБОТАТЬ на настоящем реплее, а не только в отчёте."""

    def _journal(self):
        rates = {"a": 3.0, "b": 3.0}
        rows = [_rec(0, current={"a": 50_000.0}, target={"b": 50_000.0},
                     rates=rates, cost=10.0, turnover=50_000.0)]
        for i in range(1, 9):
            rows.append(_rec(i, current={"b": 50_000.0}, target={"b": 50_000.0},
                             rates=rates, cost=0.0, turnover=0.0))
        return rows

    def test_control_flips_a_real_hit_into_a_miss_through_the_real_replay(self):
        from spa_core.paper_trading.shadow_trigger_eval import evaluate_window

        rows = self._journal()
        with TemporaryDirectory() as td:
            sandbox = Path(td)
            drvs._write_journal(rows, sandbox / drvs.HISTORY_FILENAME)
            base = drvs._replay(sandbox, rows, "base")
            day0 = next(r for r in base["per_verdict"]
                        if r["cycle_date"] == _day(0))
            self.assertEqual(day0["outcome"], "hit")  # предпосылка контроля
            out = drvs.capability_control(sandbox, rows, base)
        self.assertTrue(out["fired"], out)
        self.assertEqual(out["outcome_after"], "miss")
        self.assertIsNotNone(out["advantage_pp_to_flip"])
        self.assertTrue(callable(evaluate_window))

    def test_a_day_the_control_cannot_flip_is_reported_as_NOT_fired(self):
        """Мутация «fired=True всегда» пережила первую редакцию этих тестов.

        Проверять надо не только сработавший контроль, но и НЕсработавший при
        живых данных: иначе поле `fired` можно захардкодить, и прибор объявит
        отрицательный результат состоятельным, ничего не показав. Здесь ход
        заведомо не окупается ни при какой ставке контроля — честный ответ
        `fired=False`.
        """
        rates = {"a": 3.0, "b": 3.0}
        rows = [_rec(0, current={"a": 50_000.0}, target={"b": 50_000.0},
                     rates=rates, cost=1e9, turnover=50_000.0)]
        for i in range(1, 9):
            rows.append(_rec(i, current={"b": 50_000.0}, target={"b": 50_000.0},
                             rates=rates, cost=0.0, turnover=0.0))
        with TemporaryDirectory() as td:
            sandbox = Path(td)
            drvs._write_journal(rows, sandbox / drvs.HISTORY_FILENAME)
            base = drvs._replay(sandbox, rows, "base")
            day0 = next(r for r in base["per_verdict"]
                        if r["cycle_date"] == _day(0))
            self.assertEqual(day0["outcome"], "hit")  # предпосылка контроля
            out = drvs.capability_control(sandbox, rows, base)
        self.assertFalse(out["fired"], out)
        self.assertEqual(out["outcome_after"], "hit")

    def test_no_scoreable_day_is_a_named_refusal_not_a_silent_pass(self):
        with TemporaryDirectory() as td:
            out = drvs.capability_control(Path(td), [], {"per_verdict": []})
        self.assertFalse(out["fired"])
        self.assertIn("не на чем", out["note"])


class RateSpreadTest(unittest.TestCase):
    def test_spread_is_measured_over_everything_the_journal_saw(self):
        rows = [_rec(0, current={}, target={}, rates={"a": 2.0}),
                _rec(1, current={}, target={}, rates={"b": 9.5})]
        out = drvs.rate_spread(rows)
        self.assertEqual(out["min_pp"], 2.0)
        self.assertEqual(out["max_pp"], 9.5)
        self.assertEqual(out["spread_pp"], 7.5)

    def test_an_empty_journal_gives_none_not_zero(self):
        """Ноль разброса и «разброс не наблюдался» — разные утверждения."""
        out = drvs.rate_spread([])
        self.assertIsNone(out["spread_pp"])


class MeasureRefusesOnAnEmptyJournalTest(unittest.TestCase):
    def test_empty_journal_is_unmeasured_with_a_named_reason(self):
        with TemporaryDirectory() as td:
            doc = drvs.measure(Path(td), now=ANCHOR)
        self.assertEqual(doc["status"], drvs.STATUS_UNMEASURED)
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))


class RunCountsTest(unittest.TestCase):
    def test_unchecked_is_counted_separately_from_zero(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            doc = drvs.run(root=str(root), now=ANCHOR, write=False)
        self.assertEqual(doc["overall"], drvs.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)


class WiringAtBirthTest(unittest.TestCase):
    """Прибор без обязанного читателя — ровно дефект, ради которого ADR-066.

    Проверяются ТРИ места, а не два: объявление продукта в мосте, производящий
    вызов и обе записи манифеста. Именно на второй записи (`produces[]` паспорта
    агента) краснел парити-тест B7, и именно её пропускала каждая новая перепись.
    """

    ROOT = Path(__file__).resolve().parents[2]

    def test_the_bridge_declares_the_product_and_calls_the_producer(self):
        src = (self.ROOT / "spa_core/monitoring/findings_bridge.py").read_text(
            encoding="utf-8")
        self.assertIn(f"data/{drvs.OUTPUT_FILENAME}", src)
        self.assertIn("decision_record_verdict_sensitivity", src)
        self.assertIn("decision_record_verdict_sensitivity.run(root=args.root)", src)

    def test_the_office_step_is_obliged_to_read_it(self):
        """ТРИ места, спрошенные ПОРОЗНЬ, а не одно вхождение имени.

        Первая редакция этого теста искала имя модуля во всём файле и пережила
        мутацию «убрать запись `_PRODUCER`»: остальные два вхождения держали её
        зелёной. Ровно так артефакт и остаётся без обязанного читателя — все
        нужные строки «вроде бы есть».
        """
        src = (self.ROOT / "scripts/consume_office_reports.py").read_text(
            encoding="utf-8")
        producer = "spa_core/monitoring/decision_record_verdict_sensitivity.py"
        self.assertIn(producer, src, "нет записи в карте производителей")
        self.assertIn(f'"{drvs.OUTPUT_FILENAME}": ("status"', src,
                      "нет объявления схемы чтения")
        self.assertIn(f'elif name == "{drvs.OUTPUT_FILENAME}":', src,
                      "нет именованного блока отрисовки")

    def test_the_manifest_carries_both_entries_not_one(self):
        manifest = json.loads(
            (self.ROOT / "architecture/manifest.json").read_text(encoding="utf-8"))
        blob = json.dumps(manifest, ensure_ascii=False)
        self.assertGreaterEqual(blob.count(f"data/{drvs.OUTPUT_FILENAME}"), 2,
                                "манифест должен нести и artifacts[], и produces[]")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
