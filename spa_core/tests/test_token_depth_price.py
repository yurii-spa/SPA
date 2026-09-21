"""Цена требования ДВУХ различающих токенов — заказ **G62 п. 1** (ADR-440).

Заказ запретил вводить порог, пока цена не названа числом. Эти тесты держат
ровно это: что цена СЧИТАЕТСЯ, что она названа в обеих валютах, что порог НЕ
введён, и что каждое «не измерено» осталось отдельным значением, а не нулём.

Каждый тест — обратная сторона: сцена строится так, чтобы утверждение можно
было опровергнуть, а не подтвердить построением. Литеральных дат и литеральных
pid здесь нет: мера не спрашивает ни часов, ни ОС.
"""

import unittest
from pathlib import Path

from spa_core.monitoring.rule_second_copy_census import (
    DEPTH_INDEPENDENCE_UNMEASURED,
    DEPTH_NAME_ONLY,
    DEPTH_READS_TEXT,
    LABEL_ARTEFACT,
    LABEL_GENUINE,
    LABEL_UNDECIDED,
    TOKEN_DEPTH_UNMEASURED,
    report,
    token_depth_price,
    truth_interval,
)

ROOT = Path(__file__).resolve().parents[2]


def row(*, side="authority", label=LABEL_UNDECIDED, token_count=1,
        named_as="MIN_CASH_PCT", text=".claude/rules/risk-engine.md",
        block_start=1, resolved="spa_core/governance/churn_damper.py",
        value=0.05):
    return {"side": side, "label": label, "token_count": token_count,
            "named_as": named_as, "text": text, "block_start": block_start,
            "resolved": resolved, "value": value, "tokens": ["cash"]}


def precision(rows):
    return {"status": "MEASURED", "rows": rows}


def channel(pairs):
    return {"status": "MEASURED", "pairs": pairs}


class TruthIntervalIsDeclaredOnce(unittest.TestCase):
    """Формула интервала — одно определение на две координаты."""

    def test_empty_population_is_none_not_a_zero_interval(self):
        self.assertIsNone(truth_interval(0, 0, 0))

    def test_bounds_are_genuine_and_genuine_plus_undecided(self):
        span = truth_interval(2, 6, 10)
        self.assertEqual(span["lower"], 0.2)
        self.assertEqual(span["upper"], 0.8)
        self.assertEqual(span["denominator"], 10)

    def test_precision_uses_the_same_helper_not_a_second_copy(self):
        """Вторая копия формулы здесь была бы предметом самой переписи."""
        import inspect

        from spa_core.monitoring import rule_second_copy_census as mod

        body = inspect.getsource(mod.bilingual_name_precision)
        self.assertIn("truth_interval(", body)
        self.assertNotIn('"lower": authority', body)


class NarrowingLosesTheTruePairs(unittest.TestCase):
    """Сужение W1 удаляет население, а не решает его."""

    def scene(self):
        return precision([
            row(label=LABEL_GENUINE, token_count=1, named_as="CASH_BUFFER_PCT"),
            row(label=LABEL_GENUINE, token_count=1, named_as="MAX_CAPITAL_PCT",
                block_start=2),
            row(label=LABEL_ARTEFACT, token_count=2, named_as="KILL_DRAWDOWN",
                block_start=3),
            row(label=LABEL_UNDECIDED, token_count=1, named_as="APY_FLOOR",
                block_start=4),
        ])

    def test_every_single_token_hit_disappears(self):
        doc = token_depth_price(self.scene())
        side = doc["sides"]["authority"]
        self.assertEqual(side["as_filter"]["lost"][LABEL_GENUINE], 2)
        self.assertEqual(side["as_filter"]["lost"][LABEL_UNDECIDED], 1)
        self.assertEqual(side["as_filter"]["lost"][LABEL_ARTEFACT], 0)
        self.assertEqual(side["as_filter"]["survive"]["labelled"], 1)

    def test_narrowing_resolves_no_undecided_at_all(self):
        doc = token_depth_price(self.scene())
        self.assertEqual(
            doc["sides"]["authority"]["as_filter"]["resolved_undecided"], 0)

    def test_false_share_gets_worse_while_the_interval_gets_narrower(self):
        """Ловушка названа числом: узость берётся из убыли знаменателя."""
        doc = token_depth_price(self.scene())
        side = doc["sides"]["authority"]
        was = side["before"]
        now = side["as_filter"]["survive"]
        self.assertLess(was["false_share"], now["false_share"])
        width_before = was["interval"]["upper"] - was["interval"]["lower"]
        width_after = now["interval"]["upper"] - now["interval"]["lower"]
        self.assertLess(width_after, width_before)
        self.assertEqual(now["interval"]["lower"], 0.0)
        self.assertLess(now["interval"]["denominator"],
                        was["interval"]["denominator"])

    def test_a_scene_where_narrowing_helps_is_reported_as_helping(self):
        """Обратная сторона: мера не запрограммирована на плохой ответ."""
        doc = token_depth_price(precision([
            row(label=LABEL_ARTEFACT, token_count=1, named_as="APY_FLOOR"),
            row(label=LABEL_GENUINE, token_count=2, named_as="KILL_DRAWDOWN",
                block_start=2),
        ]))
        side = doc["sides"]["authority"]
        self.assertEqual(side["as_filter"]["lost"][LABEL_GENUINE], 0)
        self.assertEqual(side["as_filter"]["lost"][LABEL_ARTEFACT], 1)
        self.assertLess(side["as_filter"]["survive"]["false_share"],
                        side["before"]["false_share"])

    def test_the_threshold_is_never_applied(self):
        self.assertIs(token_depth_price(self.scene())["applied"], False)


class WitnessReadingIsADifferentQuestion(unittest.TestCase):
    """Второе прочтение кандидата: улика, а не фильтр."""

    def test_deep_undecided_becomes_genuine_and_population_stays(self):
        doc = token_depth_price(precision([
            row(label=LABEL_UNDECIDED, token_count=2, named_as="KILL_DRAWDOWN"),
            row(label=LABEL_UNDECIDED, token_count=1, named_as="APY_FLOOR",
                block_start=2),
        ]))
        side = doc["sides"]["authority"]
        self.assertEqual(side["as_witness"]["resolved_undecided"], 1)
        self.assertEqual(side["as_witness"][LABEL_GENUINE], 1)
        self.assertEqual(side["as_witness"]["labelled"],
                         side["before"]["labelled"])

    def test_artefact_is_untouched_because_w1_failed(self):
        doc = token_depth_price(precision([
            row(label=LABEL_ARTEFACT, token_count=2, named_as="KILL_DRAWDOWN"),
        ]))
        side = doc["sides"]["authority"]
        self.assertEqual(side["as_witness"][LABEL_ARTEFACT], 1)
        self.assertEqual(side["as_witness"][LABEL_GENUINE], 0)
        self.assertEqual(side["as_witness"]["resolved_undecided"], 0)

    def test_moved_rows_name_the_rows_that_changed_label(self):
        doc = token_depth_price(precision([
            row(label=LABEL_UNDECIDED, token_count=2, named_as="KILL_DRAWDOWN"),
        ]))
        self.assertEqual([r["named_as"] for r in doc["moved_rows"]],
                         ["KILL_DRAWDOWN"])
        self.assertEqual(doc["moved_rows"][0]["from"], LABEL_UNDECIDED)
        self.assertEqual(doc["moved_rows"][0]["to"], LABEL_GENUINE)


class IndependenceIsMeasuredNotAsserted(unittest.TestCase):
    """Третий свидетель обязан читать АБЗАЦ; кандидат читает ИМЯ."""

    def test_one_name_in_two_paragraphs_gives_the_same_verdict(self):
        doc = token_depth_price(precision([
            row(named_as="KILL_DRAWDOWN", token_count=2, block_start=1),
            row(named_as="KILL_DRAWDOWN", token_count=2, block_start=9,
                text=".claude/rules/site-numbers.md"),
        ]))
        ind = doc["independence"]
        self.assertEqual(ind["verdict"], DEPTH_NAME_ONLY)
        self.assertEqual(ind["names_in_two_paragraphs"], 1)
        self.assertEqual(ind["names_whose_verdict_varies"], 0)

    def test_a_name_whose_verdict_varies_flips_the_answer(self):
        """Обратная сторона: если бы кандидат читал текст, мера сказала бы это."""
        doc = token_depth_price(precision([
            row(named_as="KILL_DRAWDOWN", token_count=2, block_start=1),
            row(named_as="KILL_DRAWDOWN", token_count=1, block_start=9,
                text=".claude/rules/site-numbers.md"),
        ]))
        self.assertEqual(doc["independence"]["verdict"], DEPTH_READS_TEXT)
        self.assertEqual(doc["independence"]["names_whose_verdict_varies"], 1)

    def test_no_repeated_name_is_unmeasured_not_independent(self):
        """Вырожденная проверка обязана молчать, а не зеленеть."""
        doc = token_depth_price(precision([
            row(named_as="CASH_BUFFER_PCT"),
            row(named_as="APY_FLOOR", block_start=2),
        ]))
        self.assertEqual(doc["independence"]["verdict"],
                         DEPTH_INDEPENDENCE_UNMEASURED)
        self.assertEqual(doc["independence"]["names_in_two_paragraphs"], 0)
        self.assertIn("вырожден", doc["independence"]["reason"].lower())

    def test_same_name_in_the_same_paragraph_twice_is_not_two_paragraphs(self):
        doc = token_depth_price(precision([
            row(named_as="KILL_DRAWDOWN", token_count=2, block_start=1),
            row(named_as="KILL_DRAWDOWN", token_count=2, block_start=1,
                resolved="spa_core/other.py"),
        ]))
        self.assertEqual(doc["independence"]["verdict"],
                         DEPTH_INDEPENDENCE_UNMEASURED)


class PriceInPairsAsksTheLabellingNotTheRuleAgain(unittest.TestCase):
    """Валюта книг: пары, подтверждённые величиной."""

    def test_pair_is_lost_when_its_row_is_shallow(self):
        rows = [row(label=LABEL_GENUINE, named_as="_MIN_CASH_PCT",
                    token_count=1)]
        doc = token_depth_price(precision(rows), channel([
            {"text": ".claude/rules/risk-engine.md",
             "named_as": "_MIN_CASH_PCT",
             "resolved": "spa_core/governance/churn_damper.py", "value": 0.05},
        ]))
        price = doc["price_in_pairs"]
        self.assertEqual(price["status"], "MEASURED")
        self.assertEqual([p["named_as"] for p in price["lost"]],
                         ["_MIN_CASH_PCT"])
        self.assertEqual(price["kept"], [])

    def test_pair_is_kept_when_its_row_is_deep(self):
        rows = [row(label=LABEL_ARTEFACT, named_as="KILL_DRAWDOWN",
                    token_count=2, resolved="spa_core/a.py")]
        doc = token_depth_price(precision(rows), channel([
            {"text": ".claude/rules/risk-engine.md",
             "named_as": "KILL_DRAWDOWN", "resolved": "spa_core/a.py",
             "value": None},
        ]))
        self.assertEqual([p["named_as"] for p in doc["price_in_pairs"]["kept"]],
                         ["KILL_DRAWDOWN"])
        self.assertEqual(doc["price_in_pairs"]["lost"], [])

    def test_pair_absent_from_the_labelling_is_unmatched_not_kept(self):
        doc = token_depth_price(precision([row()]), channel([
            {"text": "docs/other.md", "named_as": "STRANGER",
             "resolved": "spa_core/x.py", "value": 1},
        ]))
        price = doc["price_in_pairs"]
        self.assertEqual(price["kept"], [])
        self.assertEqual(price["lost"], [])
        self.assertEqual([p["named_as"] for p in price["unmatched"]],
                         ["STRANGER"])

    def test_two_different_token_counts_for_one_pair_is_unmatched(self):
        rows = [row(named_as="X", token_count=1, resolved="spa_core/a.py"),
                row(named_as="X", token_count=2, resolved="spa_core/a.py",
                    block_start=7)]
        doc = token_depth_price(precision(rows), channel([
            {"text": ".claude/rules/risk-engine.md", "named_as": "X",
             "resolved": "spa_core/a.py", "value": 1},
        ]))
        unmatched = doc["price_in_pairs"]["unmatched"]
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["token_counts"], [1, 2])

    def test_no_channel_is_unmeasured_not_zero_price(self):
        doc = token_depth_price(precision([row()]))
        self.assertEqual(doc["price_in_pairs"]["status"],
                         TOKEN_DEPTH_UNMEASURED)
        self.assertNotIn("lost", doc["price_in_pairs"])

    def test_empty_pair_list_is_unmeasured_not_zero_price(self):
        doc = token_depth_price(precision([row()]), channel([]))
        self.assertEqual(doc["price_in_pairs"]["status"],
                         TOKEN_DEPTH_UNMEASURED)


class AbsenceIsItsOwnValue(unittest.TestCase):
    """Инв. #17: пять разных «не измерено», и ни одно не есть ноль."""

    def reasons(self):
        return {
            "no_precision": token_depth_price(None),
            "precision_unmeasured": token_depth_price({"status": "X"}),
            "no_rows": token_depth_price({"status": "MEASURED", "rows": []}),
            "rows_absent": token_depth_price({"status": "MEASURED"}),
            "rows_wrong_form": token_depth_price({"status": "MEASURED",
                                                  "rows": {"a": 1}}),
            "shallow_depth": token_depth_price(precision([row()]), depth=1),
        }

    def test_every_absence_refuses_with_its_own_reason(self):
        docs = self.reasons()
        for key, doc in docs.items():
            with self.subTest(key=key):
                self.assertEqual(doc["status"], TOKEN_DEPTH_UNMEASURED)
                self.assertTrue(doc["reason"].strip())
                self.assertNotIn("sides", doc)
        self.assertEqual(len({d["reason"] for d in docs.values()}), len(docs))

    def test_rows_absent_says_counted_and_not_recorded(self):
        """«Не записано» и «форма не та» — разные утверждения о канале."""
        doc = token_depth_price({"status": "MEASURED"})
        self.assertIn("не записаны", doc["reason"])
        other = token_depth_price({"status": "MEASURED", "rows": {"a": 1}})
        self.assertIn("форму", other["reason"])

    def test_empty_population_is_not_called_a_zero_price(self):
        doc = token_depth_price({"status": "MEASURED", "rows": []})
        self.assertIn("НЕ «цена нулевая»", doc["reason"])

    def test_every_boolean_depth_is_refused_by_the_ordinary_threshold(self):
        """Отдельной ветки про `bool` нет: оба его значения ниже двух."""
        for value in (True, False):
            with self.subTest(depth=value):
                doc = token_depth_price(precision([row()]), depth=value)
                self.assertEqual(doc["status"], TOKEN_DEPTH_UNMEASURED)
                self.assertIn("не строже действующего", doc["reason"])

    def test_rows_without_a_token_count_are_named_not_counted(self):
        broken = row()
        broken.pop("token_count")
        doc = token_depth_price(precision([row(token_count=2), broken]))
        self.assertEqual(doc["status"], "MEASURED")
        self.assertEqual(len(doc["unreadable"]), 1)
        self.assertEqual(doc["sides"]["authority"]["before"]["labelled"], 1)

    def test_a_label_outside_the_declared_three_is_named_not_counted(self):
        doc = token_depth_price(precision([row(label="SOMETHING_ELSE"),
                                           row(token_count=2, block_start=2)]))
        self.assertEqual(len(doc["unreadable"]), 1)
        self.assertIn("не из объявленных", doc["unreadable"][0]["reason"])

    def test_all_rows_unreadable_is_unmeasured_not_an_empty_answer(self):
        broken = row()
        broken.pop("token_count")
        doc = token_depth_price(precision([broken]))
        self.assertEqual(doc["status"], TOKEN_DEPTH_UNMEASURED)
        self.assertEqual(len(doc["unreadable"]), 1)

    def test_rule_is_carried_even_when_nothing_could_be_measured(self):
        for doc in self.reasons().values():
            self.assertIn("ДВУМЯ способами", doc["rule"])


class ReportSpeaksAtBodyLevel(unittest.TestCase):
    """Секция не вложена в `else` соседней координаты (урок #655)."""

    def doc(self, depth_doc, precision_doc=None):
        return {"status": "CLEAN", "rows": [], "peer_rows": [],
                "counts": {}, "scanned": 0, "classified": 0,
                "bilingual_name_precision": precision_doc,
                "token_depth_price": depth_doc}

    def lines(self, doc):
        return [l for l in report(doc) if "ДВУХ ТОКЕНОВ" in l]

    def test_section_speaks_when_the_neighbour_is_unmeasured(self):
        measured = token_depth_price(precision([
            row(label=LABEL_GENUINE, token_count=1),
            row(label=LABEL_ARTEFACT, token_count=2, block_start=2),
        ]))
        lines = self.lines(self.doc(measured, {"status": "X", "reason": "нет"}))
        self.assertTrue(any("СУЖЕНИЕ" in l for l in lines))
        self.assertTrue(any("ТРЕТИЙ СВИДЕТЕЛЬ" in l for l in lines))

    def test_missing_coordinate_is_announced_not_skipped(self):
        lines = self.lines(self.doc(None))
        self.assertTrue(lines)
        self.assertIn("НЕ ИЗМЕРЕНА", lines[0])

    def test_refusal_reason_reaches_the_reader(self):
        lines = self.lines(self.doc(token_depth_price(None)))
        self.assertTrue(any("не измерена" in l or "НЕ ИЗМЕРЕНА" in l
                            for l in lines))
        self.assertTrue(any("цену считать не от чего" in l for l in lines))

    def test_price_in_pairs_names_each_lost_pair_by_name(self):
        rows = [row(label=LABEL_GENUINE, named_as="_MIN_CASH_PCT")]
        measured = token_depth_price(precision(rows), channel([
            {"text": ".claude/rules/risk-engine.md",
             "named_as": "_MIN_CASH_PCT",
             "resolved": "spa_core/governance/churn_damper.py", "value": 0.05},
        ]))
        lines = self.lines(self.doc(measured))
        self.assertTrue(any("ПОТЕРЯННАЯ ПАРА" in l and "_MIN_CASH_PCT" in l
                            for l in lines))

    def test_unmeasured_price_in_pairs_says_so_instead_of_printing_zero(self):
        measured = token_depth_price(precision([row()]))
        lines = self.lines(self.doc(measured))
        self.assertTrue(any("В ПАРАХ] НЕ ИЗМЕРЕНА" in l for l in lines))

    def test_side_absent_from_the_labelling_is_announced(self):
        measured = token_depth_price(precision([row(side="authority")]))
        lines = self.lines(self.doc(measured))
        self.assertTrue(any("control] НЕ ИЗМЕРЕНО" in l for l in lines))


class WiredIntoTheProducer(unittest.TestCase):
    """Проводка: координата считается прогоном и печатается отчётом."""

    def test_measure_calls_the_coordinate_with_the_channel(self):
        import inspect

        from spa_core.monitoring import rule_second_copy_census as mod

        body = inspect.getsource(mod.measure)
        self.assertIn("token_depth_price(name_precision, name_channel_doc)",
                      body)
        self.assertIn('"token_depth_price": depth_price', body)

    def test_report_reads_the_key_through_observed(self):
        import inspect

        from spa_core.monitoring import rule_second_copy_census as mod

        body = inspect.getsource(mod.report)
        self.assertIn('observed(doc, "token_depth_price", kind=dict)', body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
