"""Рецидив обязан быть НАЗВАН, а не только посчитан (ADR-066, цикл #410).

Замер 28.08: обязательный шаг 0-офис печатал «🔴 РЕЦИДИВ: 5 находок ВЕРНУЛИСЬ
после закрытия — по производителю это системная причина, а не случайность» и
требовал действия, по которому действовать было НЕЧЕМ: `loop_health` складывал
`recurrences` в одно число и выбрасывал ключи. На живом состоянии все 5
рецидивов оказались ОДНИМ классом (`gap:opportunity_unnamed:*`), причём три из
них — без живой карточки; из отчёта это было неизвлекаемо, поэтому строка
возвращалась каждый цикл нетронутой.

Каждый тест здесь — положительный контроль: на коде без правки он краснеет.
Время — вход (`now=`), литеральных дат нет (правило .claude/rules/deployment.md).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring.loop_health import compute

_NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc)


def _state(**findings) -> dict:
    return {"findings": findings}


def _f(recurrences=0, status="observed", card=None):
    return {"first_seen": None, "carded_at": None, "closed_at": None,
            "recurrences": recurrences, "status": status, "card": card}


class TestRecurrenceIsNamed(unittest.TestCase):
    def _compute(self, state):
        return compute(state, lambda card: "new", _NOW)

    def test_recurring_findings_are_listed_by_key(self):
        r = self._compute(_state(**{
            "gap:opportunity_unnamed:spark_susds": _f(2),
            "gap:opportunity_unnamed:aave_v3": _f(1, status="closed", card="/x.md"),
            "quiet:one": _f(0),
        }))
        keys = [x["key"] for x in r["recurring_findings"]]
        self.assertEqual(keys, ["gap:opportunity_unnamed:spark_susds",
                                "gap:opportunity_unnamed:aave_v3"],
                         "рецидивы обязаны быть названы поимённо и по убыванию")
        self.assertEqual(r["recurrences_total"], 3, "сумма не должна разъехаться с деталью")

    def test_single_systemic_cause_is_collapsed_to_one_class(self):
        r = self._compute(_state(**{
            "gap:opportunity_unnamed:spark_susds": _f(2),
            "gap:opportunity_unnamed:morpho_steakhouse": _f(1),
            "gap:opportunity_unnamed:aave_v3": _f(1),
            "gap:opportunity_unnamed:fluid_fusdc": _f(1),
        }))
        self.assertEqual(r["recurrences_by_class"], {"gap:opportunity_unnamed": 5},
                         "пять рецидивов одного класса — ОДНА причина, а не пять")

    def test_classes_are_ordered_by_weight(self):
        r = self._compute(_state(**{
            "a:one": _f(1),
            "b:x": _f(3),
            "b:y": _f(1),
        }))
        self.assertEqual(list(r["recurrences_by_class"].items()),
                         [("b", 4), ("a", 1)], "класс с большим весом идёт первым")

    def test_recurrence_without_a_live_card_is_visible(self):
        r = self._compute(_state(**{
            "gap:x": _f(1, status="observed", card=None),
            "gap:y": _f(1, status="closed", card="/some/card.md"),
        }))
        carded = {x["key"]: x["carded"] for x in r["recurring_findings"]}
        self.assertEqual(carded, {"gap:x": False, "gap:y": True},
                         "«вернулось и карточки нет» — самый острый случай, он обязан быть виден")

    def test_no_recurrence_means_empty_not_missing(self):
        r = self._compute(_state(**{"quiet:one": _f(0)}))
        self.assertEqual(r["recurrences_total"], 0)
        self.assertEqual(r["recurring_findings"], [], "пусто — это список, а не отсутствие поля")
        self.assertEqual(r["recurrences_by_class"], {})

    def test_keyless_finding_does_not_crash_the_rollup(self):
        r = self._compute(_state(**{"nocolonkey": _f(2)}))
        self.assertEqual(r["recurrences_by_class"], {"nocolonkey": 2},
                         "ключ без ':' — свой собственный класс, а не падение")


class TestOfficeStepPrintsTheNames(unittest.TestCase):
    """Эффект в ЧИТАТЕЛЕ: голое число возвращалось каждый цикл нетронутым."""

    def _render(self, doc):
        import importlib.util
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_cor_under_test", root / "scripts" / "consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return "\n".join(mod._summarize_json("loop_health.json", doc))

    def _doc(self, **over):
        doc = {"open_cards": 0, "recurrences_total": 5,
               "cards_fate": {"new": 0, "in_progress": 0, "done_by_human": 1,
                              "auto_closed": 20, "unreadable": 0},
               "latency_finding_to_card": {"median_h": 6.0, "max_h": 6.0, "n": 27},
               "latency_card_to_close": {"median_h": 12.0, "max_h": 66.0, "n": 22},
               "recurrences_by_class": {"gap:opportunity_unnamed": 5},
               "recurring_findings": [
                   {"key": "gap:opportunity_unnamed:spark_susds", "recurrences": 2,
                    "status": "observed", "carded": False},
                   {"key": "gap:opportunity_unnamed:aave_v3", "recurrences": 1,
                    "status": "closed", "carded": True}],
               "note": ""}
        doc.update(over)
        return doc

    def test_the_recurring_keys_reach_the_orchestrator(self):
        txt = self._render(self._doc())
        self.assertIn("gap:opportunity_unnamed:spark_susds", txt,
                      "имя вернувшейся находки обязано доехать до читателя")

    def test_one_class_is_stated_as_one_cause(self):
        txt = self._render(self._doc())
        self.assertIn("причина ОДНА", txt)
        self.assertIn("gap:opportunity_unnamed", txt)

    def test_uncarded_recurrence_is_flagged_red(self):
        txt = self._render(self._doc())
        self.assertIn("карточки СЕЙЧАС НЕТ", txt,
                      "рецидив без живой карточки — то, ради чего строку вообще читают")

    def test_old_format_report_says_unmeasured_not_silence(self):
        doc = self._doc()
        doc.pop("recurring_findings")
        doc.pop("recurrences_by_class")
        txt = self._render(doc)
        self.assertIn("ЧТО именно вернулось", txt,
                      "отчёт старого образца обязан сказать «не измерено», а не молчать")

    def test_zero_recurrence_prints_no_detail_at_all(self):
        txt = self._render(self._doc(recurrences_total=0))
        self.assertNotIn("причина ОДНА", txt)
        self.assertNotIn("РЕЦИДИВ", txt)


if __name__ == "__main__":
    unittest.main()
