"""Приёмка прибора «смещён ли hit_rate систематически» (заказ #541, ADR-299).

Каждый тест здесь — положительный контроль на конкретное свойство прибора, а не
украшение: набор писался так, чтобы мутация по координате в
`spa_core/monitoring/hit_rate_selection_bias.py` краснила хотя бы один тест.

Время инъектировано: `measure(..., now=)` принимает часы, и ни одна проверка не
судит о свежести по стенным часам.
FROZEN-DATE-OK: injected-clock — даты дней журнала суть ИМЕНА строк фикстуры
(ключ сортировки `load_history`), а единственные часы прибора приходят
параметром `now=` в `measure`/`run`; ни одно утверждение набора не зависит от
текущей даты.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — часы прибора приходят параметром: FIXED_NOW
# (и второй литерал в test_clock_is_an_input) передаются в measure(..., now=)
# и run(..., now=), поэтому ни одно утверждение набора не зависит от календаря.
# Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА строк журнала: по ним
# load_history сортирует и разрешает повтор дня, свежестью они не являются.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import hit_rate_selection_bias as hrsb
from spa_core.paper_trading import shadow_trigger_eval as ste

#: Часы прибора — вход, а не окружение (правило `.claude/rules/deployment.md`).
FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _day(date: str, *, verdict: str = "HOLD", cost: float = 50.0,
         apys: dict | None = None, current: dict | None = None,
         target: dict | None = None, turnover: float = 20_000.0) -> dict:
    """Одна строка журнала решений в форме настоящего писателя."""
    return {
        "cycle_date": date,
        "verdict": verdict,
        "schema": "shadow-hist-v2",
        "capital_usd": 100_000.0,
        "cost_usd": cost,
        "turnover_usd": turnover,
        "current_positions": current if current is not None else {"aave_v3": 20_000.0},
        "target_positions": target if target is not None else {"compound_v3": 20_000.0},
        "apy_evidenced_pct": apys if apys is not None else {},
    }


def _write(data_dir: Path, rows: list[dict]) -> None:
    (data_dir / "allocation_rationale_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _cost_evidence(data_dir: Path, *, measured: bool = True,
                   ratio: float | None = 0.3973) -> None:
    doc = {
        "generated_at": "2026-09-09T19:19:09+00:00",
        "observed_gas": {"measured": measured,
                         "reason": None if measured else "фидов газа нет"},
        "substitution": {"gas_usd_charged": 48.15, "gas_usd_observed": 0.1601,
                         "gas_ratio_charged_over_observed": 300.7},
    }
    if ratio is not None:
        doc["substitution"]["cost_ratio_observed_over_charged"] = ratio
    (data_dir / hrsb.COST_EVIDENCE_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8")


def _window(days: int = 12, *, apy: float = 4.0, cost: float = 50.0,
            verdict: str = "HOLD") -> list[dict]:
    """Окно, у которого forward-дни ОЦЕНИВАЮТСЯ (обе ноги имеют ставку)."""
    apys = {"aave_v3": apy, "compound_v3": apy + 1.0}
    return [_day(f"2026-08-{d:02d}", verdict=verdict, cost=cost, apys=apys)
            for d in range(1, days + 1)]


class ParityControl(unittest.TestCase):
    """Нулевое возмущение обязано воспроизвести настоящий `_evaluate_verdict`."""

    def test_zero_perturbation_reproduces_the_real_evaluator(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertTrue(doc["parity_control"]["passed"], doc["parity_control"])
        self.assertEqual(doc["parity_control"]["mismatched"], [])
        self.assertGreater(doc["parity_control"]["days"], 0,
                           "паритет, проверенный на нуле дней, ничего не доказывает")

    def test_a_broken_recount_makes_the_instrument_refuse(self):
        """Контроль на САМ контроль: разошёлся пересчёт ⇒ UNMEASURED, не «ок»."""
        original = hrsb._outcome_for
        try:
            hrsb._outcome_for = lambda verdict, net: "miss"  # noqa: ARG005
            with TemporaryDirectory() as td:
                dd = Path(td)
                _write(dd, _window())
                _cost_evidence(dd)
                doc = hrsb.measure(dd, now=FIXED_NOW)
        finally:
            hrsb._outcome_for = original
        self.assertFalse(doc["parity_control"]["passed"])
        self.assertEqual(doc["status"], hrsb.STATUS_UNMEASURED)
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))
        # и ни одного вердикта о смещении при непройденном паритете
        self.assertNotIn("hit_rate_interval", doc)


class AxisACapability(unittest.TestCase):
    """Ноль оси A принимается ТОЛЬКО при сработавшем контроле способности."""

    def test_capability_control_fires_on_a_normal_window(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        cap = doc["axis_a_horizon"]["capability_control"]
        self.assertTrue(cap["passed"], "положительный не был возможен ⇒ ноль вакуумен")
        self.assertTrue(cap["flipped_days"])

    def test_extrapolation_is_actually_applied(self):
        """Убийца мутации «ось A не экстраполирует».

        Прежние два теста мутацию ПЕРЕЖИЛИ: на обычном окне ось A и без
        экстраполяции даёт NO_SHIFT, а контроль способности переворачивает день
        множителем выгоды независимо от неё. Значит ни один из них не спрашивал
        «умножили ли на horizon/checked». Здесь окно построено так, что ответ
        решает исход: выгода одного оценённого forward-дня меньше издержки, а
        та же ставка на полном горизонте её перекрывает.
        """
        priced = {"aave_v3": 0.0, "compound_v3": 10.0}
        rows = [_day("2026-08-01", cost=20.0, apys=priced),
                _day("2026-08-02", cost=20.0, apys=priced)]
        rows += [_day(f"2026-08-{d:02d}", cost=20.0, apys={})
                 for d in range(3, 9)]
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, rows)
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertEqual(doc["hit_rate_as_is"], 1.0)
        axis = doc["axis_a_horizon"]
        self.assertEqual(axis["status"], hrsb.AXIS_SHIFTS,
                         "экстраполяция не применена: день, обязанный "
                         "перевернуться на полном горизонте, не перевернулся")
        self.assertIn("2026-08-01", axis["flipped_days"])
        self.assertLess(axis["hit_rate"], doc["hit_rate_as_is"])

    def test_axis_is_unmeasured_when_no_day_can_be_flipped(self):
        """Способность недостижима ⇒ ось UNMEASURED, а не «смещения нет»."""
        original = hrsb._CAPABILITY_BENEFIT_MULTIPLIER
        try:
            hrsb._CAPABILITY_BENEFIT_MULTIPLIER = 1.0  # ничего не переворачивает
            with TemporaryDirectory() as td:
                dd = Path(td)
                _write(dd, _window())
                _cost_evidence(dd)
                doc = hrsb.measure(dd, now=FIXED_NOW)
        finally:
            hrsb._CAPABILITY_BENEFIT_MULTIPLIER = original
        self.assertEqual(doc["axis_a_horizon"]["status"], hrsb.AXIS_UNMEASURED)
        self.assertEqual(doc["status"], hrsb.STATUS_UNMEASURED)


class AxisBProvenance(unittest.TestCase):
    """Поправку стоимости прибор БЕРЁТ измеренной или не берёт вовсе."""

    def _measure(self, **kw):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd, **kw)
            return hrsb.measure(dd, now=FIXED_NOW)

    def test_ratio_is_read_from_the_evidence_artifact(self):
        doc = self._measure()
        self.assertEqual(doc["axis_b_cost"]["provenance"]["cost_ratio"], 0.3973)
        self.assertEqual(doc["axis_b_cost"]["provenance"]["basis"], "gas_only",
                         "модель слиппеджа не имеет права попасть в наблюдение")

    def test_missing_artifact_is_unmeasured_not_a_guess(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            doc = hrsb.measure(dd, now=FIXED_NOW)
        ax = doc["axis_b_cost"]
        self.assertEqual(ax["status"], hrsb.AXIS_UNMEASURED)
        self.assertIsNone(ax["hit_rate"])
        self.assertIn("reason", ax["provenance"])

    def test_unmeasured_gas_is_unmeasured_with_the_producers_reason(self):
        doc = self._measure(measured=False)
        ax = doc["axis_b_cost"]
        self.assertEqual(ax["status"], hrsb.AXIS_UNMEASURED)
        self.assertIn("фидов газа нет", ax["provenance"]["reason"])

    def test_ratio_outside_the_unit_interval_is_refused(self):
        doc = self._measure(ratio=1.9)
        self.assertEqual(doc["axis_b_cost"]["status"], hrsb.AXIS_UNMEASURED)

    def test_absent_ratio_key_is_refused(self):
        doc = self._measure(ratio=None)
        self.assertEqual(doc["axis_b_cost"]["status"], hrsb.AXIS_UNMEASURED)


class AxisCIsABound(unittest.TestCase):
    """Ось C — ГРАНИЦА, и прибор обязан называть её границей."""

    def test_axis_c_declares_itself_a_bound(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            # день без forward-ставок ⇒ UNCHECKED, попадает в ось C
            rows = _window(8) + [_day("2026-08-20", apys={})]
            _write(dd, rows)
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        ax = doc["axis_c_selection"]
        self.assertEqual(ax["kind"], "BOUND")
        self.assertIn("НЕ ИЗМЕРЕНЫ", ax["note"])
        self.assertGreaterEqual(ax["excluded_unchecked"], 1)

    def test_excluded_days_lower_the_rate_they_are_added_to(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window(8) + [_day("2026-08-20", apys={})])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertLess(doc["axis_c_selection"]["hit_rate"], doc["hit_rate_as_is"])


class CriterionVerdict(unittest.TestCase):
    """Вердикт зависит от того, лежит ли порог ВНУТРИ интервала поправок."""

    def test_threshold_inside_the_interval_is_critical(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            # много дней без вердикта ⇒ граница оси C уезжает под порог
            _write(dd, _window(6) + [_day(f"2026-08-2{d}", apys={})
                                     for d in range(0, 6)])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertTrue(doc["hit_rate_interval"]["threshold_inside_interval"])
        self.assertEqual(doc["status"], hrsb.STATUS_CRITICAL)
        self.assertTrue(any(f.startswith("[CRITICAL]") for f in doc["findings"]))

    def test_threshold_outside_the_interval_is_not_critical(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window(12))          # без UNCHECKED-дней вовсе
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertFalse(doc["hit_rate_interval"]["threshold_inside_interval"])
        self.assertEqual(doc["status"], hrsb.STATUS_WARNING)

    def test_the_interval_spans_every_defensible_correction(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window(6) + [_day(f"2026-08-2{d}", apys={})
                                     for d in range(0, 6)])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        iv = doc["hit_rate_interval"]
        for value in (doc["hit_rate_as_is"], doc["axis_a_horizon"]["hit_rate"],
                      doc["axis_c_selection"]["hit_rate"],
                      doc["combined"]["hit_rate_with_unchecked_as_miss"]):
            self.assertGreaterEqual(value, iv["low"])
            self.assertLessEqual(value, iv["high"])


class DirectionClaimIsScoped(unittest.TestCase):
    """«Систематически» держится на том, что окно сплошь HOLD, — и это меряется."""

    def test_all_hold_window_reports_uniform_direction(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertTrue(doc["direction_is_uniform"])
        self.assertTrue(any("[МЕХАНИЗМ]" in f for f in doc["findings"]))

    def test_a_single_act_narrows_the_claim(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            rows = _window(10)
            rows.append(_day("2026-08-11", verdict="ACT",
                             apys={"aave_v3": 4.0, "compound_v3": 5.0}))
            _write(dd, rows)
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertFalse(doc["direction_is_uniform"])
        self.assertIn("ACT", doc["verdict_mix"])
        self.assertFalse(any("[МЕХАНИЗМ]" in f for f in doc["findings"]),
                         "утверждение о единой сто́роне не имеет права пережить ACT")


class EmptyAndDegenerate(unittest.TestCase):
    def test_empty_journal_invents_nothing(self):
        with TemporaryDirectory() as td:
            doc = hrsb.measure(Path(td), now=FIXED_NOW)
        self.assertEqual(doc["status"], hrsb.STATUS_UNMEASURED)
        self.assertEqual(doc["journal_rows"], 0)
        self.assertNotIn("hit_rate_as_is", doc)

    def test_journal_without_a_single_scored_day_is_unmeasured(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, [_day(f"2026-08-0{d}", apys={}) for d in range(1, 5)])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        self.assertEqual(doc["status"], hrsb.STATUS_UNMEASURED)
        self.assertNotIn("hit_rate_interval", doc)


class RunShapeAndDeterminism(unittest.TestCase):
    def test_run_writes_the_artifact_and_shapes_counts(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            _write(root / "data", _window(6) + [_day(f"2026-08-2{d}", apys={})
                                                for d in range(0, 6)])
            _cost_evidence(root / "data")
            doc = hrsb.run(root=str(root), now=FIXED_NOW)
            written = json.loads(
                (root / "data" / hrsb.OUTPUT_FILENAME).read_text())
        self.assertEqual(doc["overall"], doc["status"])
        self.assertGreaterEqual(doc["counts"]["critical"], 1)
        self.assertEqual(written["version"], hrsb.VERSION)
        self.assertEqual(written["mode"], "ADVISORY")

    def test_unmeasured_is_counted_separately_from_clean(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            _write(root / "data", _window())      # без артефакта стоимости
            doc = hrsb.run(root=str(root), now=FIXED_NOW, write=False)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1,
                                "молчание прибора не имеет права выглядеть чистым прогоном")

    def test_same_inputs_give_the_same_document(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd)
            a = hrsb.measure(dd, now=FIXED_NOW)
            b = hrsb.measure(dd, now=FIXED_NOW)
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))

    def test_clock_is_an_input(self):
        other = datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window())
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=other)
        self.assertEqual(doc["generated_at"], other.isoformat())


class ReportSurfacesTheControls(unittest.TestCase):
    """Контроль обязан стоять НА ВИДУ: без него ноль читается как доказательство."""

    def test_report_names_every_axis_and_its_control(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window(6) + [_day(f"2026-08-2{d}", apys={})
                                     for d in range(0, 6)])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
        lines = hrsb.format_report(doc)
        text = "\n".join(lines)
        for token in ("ось A", "ось B", "ось C", "ГРАНИЦА, не оценка",
                      "конъюнкция", "ADVISORY"):
            self.assertIn(token, text)
        # Утверждение о контроле обязано опираться на СТРОКУ ОСИ. Прежняя
        # редакция искала слова по всему отчёту и мутацию «строка оси молчит
        # про контроль» ПЕРЕЖИЛА: те же слова стоя́т в находке [КОНТРОЛЬ],
        # которой мутация не касалась, — утверждение удовлетворялось ДРУГИМ
        # источником.
        axis_lines = [ln for ln in lines if ln.strip().startswith("ось ")]
        self.assertEqual(len(axis_lines), 3, axis_lines)
        for ln in axis_lines:
            self.assertRegex(
                ln, r"контроль способности сработал|КОНТРОЛЬ НЕ СРАБОТАЛ",
                f"строка оси молчит про свой контроль: {ln!r}")

    def test_failed_parity_is_shouted_in_the_report(self):
        doc = {"status": hrsb.STATUS_UNMEASURED, "journal_rows": 3,
               "population": {}, "parity_control": {"passed": False},
               "findings": []}
        text = "\n".join(hrsb.format_report(doc))
        self.assertIn("контроль паритета не прошёл", text)


class ReusesTheRealEvaluator(unittest.TestCase):
    """Прибор обязан судить ТЕМ ЖЕ кодом, что и приёмка взвода."""

    def test_scored_population_matches_shadow_trigger_eval(self):
        with TemporaryDirectory() as td:
            dd = Path(td)
            _write(dd, _window(8) + [_day("2026-08-20", apys={})])
            _cost_evidence(dd)
            doc = hrsb.measure(dd, now=FIXED_NOW)
            real = ste.evaluate_window(dd, write=False)
        self.assertEqual(doc["population"]["scored"], real["counts"]["scored"])
        self.assertEqual(doc["population"]["unchecked"], real["counts"]["unchecked"])
        self.assertEqual(doc["hit_rate_as_is"], real["hit_rate"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
