"""Кандидаты в третьи свидетели, читающие АБЗАЦ — заказ **G63 п. 1** (ADR-441).

ADR-440 доказал, что кандидат прежнего заказа третьим свидетелем не является:
его вердикт есть функция ИМЕНИ. Форма искомого свидетеля этим названа — читать
АБЗАЦ, — и заказ потребовал объявить кандидатов ДО разметки и замерить у
каждого два числа: решённые `UNDECIDED` и частоту ошибки на КОНТРОЛЕ.

Эти тесты держат ровно это: что кандидаты объявлены заранее, что оба числа
считаются со знаменателем, что порог на частоту НЕ введён, что каждое
отсутствие осталось отдельным значением, а не нулём, и что вердикт
независимости читается вместе с ОХВАТОМ — иначе почти всегда молчащий
свидетель выглядит «читающим имя», которого он не видит вовсе.

Каждый тест — обратная сторона: сцена строится так, чтобы утверждение можно
было опровергнуть, а не подтвердить построением. Литеральных дат и литеральных
pid здесь нет: мера не спрашивает ни часов, ни ОС.
"""

import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as mod
from spa_core.monitoring.rule_second_copy_census import (
    DEPTH_INDEPENDENCE_UNMEASURED,
    DEPTH_NAME_ONLY,
    DEPTH_READS_TEXT,
    LABEL_ARTEFACT,
    LABEL_GENUINE,
    LABEL_UNDECIDED,
    PARAGRAPH_WITNESSES,
    PARAGRAPH_WITNESS_UNMEASURED,
    WITNESS_ADR,
    WITNESS_DIR,
    WITNESS_SUBJECT,
    WITNESS_UNIT,
    WITNESS_VALUE,
    independence_verdict,
    paragraph_at,
    paragraph_witness_price,
    report,
)

TEXT = "rules.md"

#: Сцена: четыре абзаца, начинающиеся строками 1, 4, 7 и 10. Первый называет
#: решение, второй — каталог исполнителя, третий — величину с единицей,
#: четвёртый не называет ничего из объявленного.
SCENE = "\n".join([
    "порог введён решением ADR-053 и живёт у писателя",   # 1
    "менять его вправе только владелец",                  # 2
    "",                                                   # 3
    "величина объявлена в spa_core/governance рядом",      # 4
    "и читается гейтом",                                  # 5
    "",                                                   # 6
    "буфер кэша равен 5 % и ниже не опускается",           # 7
    "это решение владельца",                              # 8
    "",                                                   # 9
    "здесь про порядок работы и больше ни о чём",          # 10
    "никаких величин и ссылок",                           # 11
    "",                                                   # 12
    "второй абзац о том же, решение ADR-065",              # 13
])
ADR_BLOCK, DIR_BLOCK, UNIT_BLOCK, PLAIN_BLOCK = 1, 4, 7, 10
ADR_BLOCK_TWO = 13


def scene_root(body=SCENE, name=TEXT):
    """Одноразовое дерево со сценой; живой репозиторий не трогается."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / name).write_text(body, encoding="utf-8")
    return tmp, root


def row(*, side="authority", label=LABEL_UNDECIDED, block_start=PLAIN_BLOCK,
        named_as="MIN_CASH_PCT", resolved="spa_core/governance/churn_damper.py",
        value=None, text=TEXT):
    return {"side": side, "label": label, "text": text,
            "block_start": block_start, "named_as": named_as,
            "resolved": resolved, "value": value}


def precision(rows):
    return {"status": "MEASURED", "rows": rows}


def measure(rows, body=SCENE):
    tmp, root = scene_root(body)
    try:
        return paragraph_witness_price(root, precision(rows))
    finally:
        tmp.cleanup()


def cand(doc, key):
    return doc["candidates"][key]


class ParagraphIsResolvedByOneCopy(unittest.TestCase):
    """Координата абзаца разрешается ОДНИМ помощником на две координаты."""

    def test_block_is_returned_with_no_reason(self):
        tmp, root = scene_root()
        try:
            block, why = paragraph_at(root, TEXT, ADR_BLOCK, {})
        finally:
            tmp.cleanup()
        self.assertIsNone(why)
        self.assertEqual(block[0][0], ADR_BLOCK)

    def test_unreadable_file_names_the_exception_not_the_missing_block(self):
        tmp, root = scene_root()
        try:
            _, why = paragraph_at(root, "нет-такого.md", 1, {})
        finally:
            tmp.cleanup()
        self.assertIn("Error", why)
        self.assertNotIn("абзаца, начинающегося", why)

    def test_missing_block_is_a_different_reason_than_an_unreadable_file(self):
        tmp, root = scene_root()
        try:
            _, why = paragraph_at(root, TEXT, 999, {})
        finally:
            tmp.cleanup()
        self.assertIn("абзаца, начинающегося строкой 999", why)

    def test_a_coordinate_that_is_not_a_line_number_says_so(self):
        """Форма координаты решается ДО обращения к диску."""
        tmp, root = scene_root()
        try:
            _, why = paragraph_at(root, TEXT, None, {})
            _, why_bool = paragraph_at(root, TEXT, True, {})
        finally:
            tmp.cleanup()
        self.assertIn("NoneType", why)
        self.assertIn("не номером строки", why)
        # `True` равно единице и иначе притворилось бы абзацем строки 1.
        self.assertIn("bool", why_bool)

    def test_cache_is_reused_so_the_file_is_read_once(self):
        tmp, root = scene_root()
        cache = {}
        paragraph_at(root, TEXT, ADR_BLOCK, cache)
        (root / TEXT).unlink()
        block, why = paragraph_at(root, TEXT, ADR_BLOCK, cache)
        tmp.cleanup()
        self.assertIsNone(why)
        self.assertEqual(block[0][0], ADR_BLOCK)

    def test_precision_delegates_instead_of_keeping_a_second_copy(self):
        body = inspect.getsource(mod.bilingual_name_precision)
        self.assertIn("paragraph_at(", body)
        self.assertNotIn("declaring_paragraphs(body)", body)


class IndependenceIsDeclaredOnce(unittest.TestCase):
    """Проверка «меняется ли вердикт вместе с абзацем» — одна на две меры."""

    def test_no_repeated_name_is_degenerate_not_green(self):
        doc = independence_verdict({"A": [{"text": "a", "block_start": 1,
                                           "v": True}]}, lambda r: r["v"])
        self.assertEqual(doc["verdict"], DEPTH_INDEPENDENCE_UNMEASURED)
        self.assertIn("ВЫРОЖДЕНА", doc["reason"])

    def test_same_verdict_in_two_paragraphs_reads_the_name(self):
        doc = independence_verdict(
            {"A": [{"text": "a", "block_start": 1, "v": True},
                   {"text": "a", "block_start": 9, "v": True}]},
            lambda r: r["v"])
        self.assertEqual(doc["verdict"], DEPTH_NAME_ONLY)
        self.assertEqual(doc["names_whose_verdict_varies"], 0)

    def test_a_verdict_that_changes_with_the_paragraph_is_named_so(self):
        doc = independence_verdict(
            {"A": [{"text": "a", "block_start": 1, "v": True},
                   {"text": "a", "block_start": 9, "v": False}]},
            lambda r: r["v"])
        self.assertEqual(doc["verdict"], DEPTH_READS_TEXT)
        self.assertEqual(doc["varying_examples"], ["A"])

    def test_two_hits_in_the_SAME_paragraph_are_not_a_repeat(self):
        doc = independence_verdict(
            {"A": [{"text": "a", "block_start": 1, "v": True},
                   {"text": "a", "block_start": 1, "v": False}]},
            lambda r: r["v"])
        self.assertEqual(doc["verdict"], DEPTH_INDEPENDENCE_UNMEASURED)

    def test_token_depth_delegates_instead_of_keeping_a_second_copy(self):
        body = inspect.getsource(mod.token_depth_price)
        self.assertIn("independence_verdict(", body)
        self.assertNotIn("names_in_two_paragraphs\": 0", body)


class EveryAbsenceIsItsOwnValue(unittest.TestCase):
    """Пять отсутствий — пять причин, и ни одна не выдаётся за ноль."""

    def _reasons(self):
        tmp, root = scene_root()
        try:
            return [paragraph_witness_price(root, arg)["reason"] for arg in (
                None, {"status": "X"}, {"status": "MEASURED"},
                {"status": "MEASURED", "rows": {}},
                {"status": "MEASURED", "rows": []})]
        finally:
            tmp.cleanup()

    def test_all_five_absences_are_unmeasured(self):
        tmp, root = scene_root()
        try:
            for arg in (None, {"status": "X"}, {"status": "MEASURED"},
                        {"status": "MEASURED", "rows": {}},
                        {"status": "MEASURED", "rows": []}):
                doc = paragraph_witness_price(root, arg)
                self.assertEqual(doc["status"], PARAGRAPH_WITNESS_UNMEASURED)
                self.assertFalse(doc["applied"])
        finally:
            tmp.cleanup()

    def test_the_five_reasons_are_distinct_words_not_one_text(self):
        reasons = self._reasons()
        self.assertEqual(len(set(reasons)), 5)

    def test_empty_population_is_not_read_as_no_errors(self):
        reasons = self._reasons()
        self.assertIn("НЕ «ошибок ноль»", reasons[-1])

    def test_nothing_survived_w1_is_its_own_reason(self):
        doc = measure([row(label=LABEL_ARTEFACT)])
        self.assertEqual(doc["status"], PARAGRAPH_WITNESS_UNMEASURED)
        self.assertIn("`ARTEFACT`", doc["reason"])
        self.assertEqual(doc["artefact_skipped"], {"authority": 1})

    def test_a_label_outside_the_declared_three_is_named_not_dropped(self):
        doc = measure([row(label="СТРАННО"), row(block_start=ADR_BLOCK)])
        self.assertEqual(doc["status"], "MEASURED")
        self.assertEqual(len(doc["unreadable"]), 1)
        self.assertIn("не из объявленных трёх", doc["unreadable"][0]["reason"])

    def test_an_unresolvable_paragraph_is_named_not_counted(self):
        doc = measure([row(block_start=999), row(block_start=ADR_BLOCK)])
        self.assertEqual(len(doc["unresolved"]), 1)
        self.assertEqual(doc["undecided_population"], 1)


class PopulationIsDeclaredBeforeTheMarkup(unittest.TestCase):
    """Кого спрашивают, решено правилом, а не увиденным исходом."""

    def test_artefact_is_skipped_by_rule_and_counted_out_loud(self):
        doc = measure([row(label=LABEL_ARTEFACT), row(block_start=ADR_BLOCK)])
        self.assertEqual(doc["artefact_skipped"], {"authority": 1})
        self.assertEqual(doc["population"], {"authority": 1})

    def test_undecided_of_the_control_side_is_not_counted_as_undecided(self):
        doc = measure([row(side="control", block_start=ADR_BLOCK)])
        self.assertEqual(doc["undecided_population"], 0)
        self.assertEqual(doc["control_population"], 1)

    def test_genuine_rows_join_the_control_denominator_but_not_undecided(self):
        doc = measure([row(label=LABEL_GENUINE, side="control",
                           block_start=ADR_BLOCK)])
        self.assertEqual(cand(doc, WITNESS_ADR)["error_rate_on_control"]
                         ["askable"], 1)
        self.assertEqual(doc["undecided_population"], 0)

    def test_paragraph_counts_stand_next_to_hit_counts(self):
        """«Решает 33» при одном абзаце и при двадцати — разные утверждения."""
        doc = measure([row(block_start=ADR_BLOCK, named_as="A"),
                       row(block_start=ADR_BLOCK, named_as="B")])
        got = cand(doc, WITNESS_ADR)["resolves_undecided"]
        self.assertEqual(got["fired"], 2)
        self.assertEqual(got["paragraphs"], 1)
        self.assertEqual(doc["undecided_paragraphs"], 1)

    def test_every_declared_candidate_is_measured_not_only_the_new_ones(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertEqual(set(doc["candidates"]),
                         {c["key"] for c in PARAGRAPH_WITNESSES})
        self.assertEqual({c["key"] for c in PARAGRAPH_WITNESSES
                          if c["incumbent"]},
                         {WITNESS_SUBJECT, WITNESS_VALUE})


class CandidatesReadTheParagraph(unittest.TestCase):
    """Каждый кандидат срабатывает на своём и молчит на чужом."""

    def test_adr_fires_only_where_a_decision_is_cited(self):
        fired = measure([row(block_start=ADR_BLOCK)])
        silent = measure([row(block_start=PLAIN_BLOCK)])
        self.assertEqual(cand(fired, WITNESS_ADR)["resolves_undecided"]
                         ["fired"], 1)
        self.assertEqual(cand(silent, WITNESS_ADR)["resolves_undecided"]
                         ["fired"], 0)

    def test_adr_reads_the_reference_form_not_the_three_letters(self):
        doc = measure([row(block_start=1)],
                      body="слово adrenaline и никакого решения\n\n")
        self.assertEqual(cand(doc, WITNESS_ADR)["resolves_undecided"]
                         ["fired"], 0)

    def test_executor_directory_fires_but_the_file_stem_alone_does_not(self):
        by_dir = measure([row(block_start=DIR_BLOCK)])
        by_stem = measure([row(block_start=1)],
                          body="величина живёт в churn_damper и всё\n\n")
        self.assertEqual(cand(by_dir, WITNESS_DIR)["resolves_undecided"]
                         ["fired"], 1)
        self.assertEqual(cand(by_stem, WITNESS_DIR)["resolves_undecided"]
                         ["fired"], 0)
        # Основа файла — это уже действующий W2, и он на той же сцене сработал:
        # кандидат каталога не пересказывает его другими словами.
        self.assertEqual(cand(by_stem, WITNESS_SUBJECT)["reach"]
                         ["authority"]["fired"], 1)

    def test_unit_needs_a_number_with_a_unit_not_a_bare_number(self):
        with_unit = measure([row(block_start=UNIT_BLOCK)])
        bare = measure([row(block_start=1)], body="здесь просто 5 и ничего\n\n")
        self.assertEqual(cand(with_unit, WITNESS_UNIT)["resolves_undecided"]
                         ["fired"], 1)
        self.assertEqual(cand(bare, WITNESS_UNIT)["resolves_undecided"]
                         ["fired"], 0)

    def test_unit_does_not_fire_on_a_word_that_merely_starts_with_it(self):
        """`5 много` не есть «5 млн»: единица обязана кончаться границей."""
        doc = measure([row(block_start=1)], body="их стало 5 много раз\n\n")
        self.assertEqual(cand(doc, WITNESS_UNIT)["resolves_undecided"]
                         ["fired"], 0)

    def test_the_incumbent_value_witness_is_asked_by_the_same_reading(self):
        doc = measure([row(side="control", label=LABEL_GENUINE,
                           block_start=UNIT_BLOCK, value=0.05)])
        self.assertEqual(cand(doc, WITNESS_VALUE)["error_rate_on_control"]
                         ["fired"], 1)

    def test_a_value_the_paragraph_does_not_name_leaves_the_witness_silent(self):
        doc = measure([row(side="control", label=LABEL_GENUINE,
                           block_start=UNIT_BLOCK, value=0.41)])
        err = cand(doc, WITNESS_VALUE)["error_rate_on_control"]
        self.assertEqual((err["fired"], err["askable"]), (0, 1))


class AbsentAnswerIsNotASilentNo(unittest.TestCase):
    """«Спросить не у чего» — третий исход, а не «свидетель промолчал»."""

    def test_a_row_without_an_executor_cannot_be_asked_about_the_directory(self):
        doc = measure([row(block_start=ADR_BLOCK, resolved=None)])
        got = cand(doc, WITNESS_DIR)["resolves_undecided"]
        self.assertEqual((got["fired"], got["askable"], got["unaskable"]),
                         (0, 0, 1))
        self.assertEqual(got["status"], PARAGRAPH_WITNESS_UNMEASURED)

    def test_an_executor_without_a_directory_is_a_different_reason(self):
        doc = measure([row(block_start=ADR_BLOCK, resolved="main.py"),
                       row(block_start=ADR_BLOCK, resolved=None,
                           named_as="OTHER")])
        reasons = cand(doc, WITNESS_DIR)["unaskable_reasons"]
        self.assertEqual(len(reasons), 2)
        self.assertEqual(sum(reasons.values()), 2)

    def test_a_row_without_a_value_cannot_be_asked_about_the_value(self):
        doc = measure([row(block_start=UNIT_BLOCK, value=None)])
        got = cand(doc, WITNESS_VALUE)["resolves_undecided"]
        self.assertEqual((got["fired"], got["askable"], got["unaskable"]),
                         (0, 0, 1))

    def test_unaskable_is_counted_in_neither_fired_nor_silent(self):
        doc = measure([row(block_start=UNIT_BLOCK, value=None)])
        reach = cand(doc, WITNESS_VALUE)["reach"]["authority"]
        self.assertEqual(reach, {"fired": 0, "silent": 0, "unaskable": 1})

    def test_unaskable_control_rows_stay_out_of_the_error_denominator(self):
        """Иначе частота ошибки МОЛЧА занижается делением на чужие строки.

        Дыру нашла батарея мутаций: «не спросили» в знаменателе не меняло ни
        одного вердикта набора, а у действующего W3 таких строк 84 из 147 —
        ошибка 11/63 превратилась бы в 11/147 и выглядела бы вдвое меньше.
        """
        doc = measure([row(side="control", label=LABEL_GENUINE,
                           block_start=UNIT_BLOCK, value=0.05, named_as="A"),
                       row(side="control", label=LABEL_GENUINE,
                           block_start=PLAIN_BLOCK, value=0.41, named_as="B"),
                       row(side="control", label=LABEL_GENUINE,
                           block_start=UNIT_BLOCK, value=None, named_as="C")])
        err = cand(doc, WITNESS_VALUE)["error_rate_on_control"]
        self.assertEqual((err["fired"], err["askable"], err["unaskable"]),
                         (1, 2, 1))
        self.assertEqual(err["share"], 0.5)

    def test_an_unaskable_row_does_not_enter_the_independence_population(self):
        doc = measure([row(block_start=ADR_BLOCK, value=None, named_as="A"),
                       row(block_start=UNIT_BLOCK, value=None, named_as="A")])
        self.assertEqual(cand(doc, WITNESS_VALUE)["independence"]["verdict"],
                         DEPTH_INDEPENDENCE_UNMEASURED)
        self.assertEqual(cand(doc, WITNESS_ADR)["independence"]["verdict"],
                         DEPTH_READS_TEXT)


class RatesCarryTheirDenominator(unittest.TestCase):
    """Доля без знаменателя — не число, а впечатление."""

    def test_share_is_fired_over_askable(self):
        doc = measure([row(block_start=ADR_BLOCK, named_as="A"),
                       row(block_start=PLAIN_BLOCK, named_as="B")])
        got = cand(doc, WITNESS_ADR)["resolves_undecided"]
        self.assertEqual(got["share"], 0.5)
        self.assertEqual(got["askable"], 2)

    def test_error_rate_is_measured_on_the_control_side_only(self):
        doc = measure([row(side="control", block_start=ADR_BLOCK),
                       row(side="authority", block_start=ADR_BLOCK)])
        err = cand(doc, WITNESS_ADR)["error_rate_on_control"]
        self.assertEqual((err["fired"], err["askable"]), (1, 1))

    def test_without_a_control_the_error_rate_is_unmeasured_not_zero(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        err = cand(doc, WITNESS_ADR)["error_rate_on_control"]
        self.assertEqual(err["status"], PARAGRAPH_WITNESS_UNMEASURED)
        self.assertIsNone(err["share"])
        self.assertIn("НЕ «ошибок ноль»", err["reason"])

    def test_without_undecided_the_resolving_share_is_unmeasured_not_zero(self):
        doc = measure([row(side="control", block_start=ADR_BLOCK)])
        got = cand(doc, WITNESS_ADR)["resolves_undecided"]
        self.assertEqual(got["status"], PARAGRAPH_WITNESS_UNMEASURED)
        self.assertIn("не на тот вопрос", got["reason"])


class AdmissionIsMeasuredNotJudged(unittest.TestCase):
    """В правило пускает ИЗМЕРЕННОСТЬ частоты, а не её величина."""

    def test_a_candidate_without_a_measured_error_rate_is_not_admissible(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertFalse(cand(doc, WITNESS_ADR)["admissible_to_rule"])
        self.assertIn("НЕ измерена", cand(doc, WITNESS_ADR)["admissibility"])

    def test_a_candidate_wrong_on_every_control_row_stays_admissible(self):
        """Порога на саму частоту нет — иначе он был бы выбран по исходу."""
        doc = measure([row(side="control", block_start=ADR_BLOCK),
                       row(side="control", block_start=ADR_BLOCK,
                           named_as="B")])
        entry = cand(doc, WITNESS_ADR)
        self.assertEqual(entry["error_rate_on_control"]["share"], 1.0)
        self.assertTrue(entry["admissible_to_rule"])

    def test_the_coordinate_changes_no_verdict_of_the_census(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertFalse(doc["applied"])

    def test_the_rule_is_declared_before_the_markup_with_every_candidate(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        declared = {item["key"] for item in doc["declared"]}
        self.assertEqual(declared, set(doc["candidates"]))
        for item in doc["declared"]:
            self.assertTrue(item["declared"] and item["reads"])

    def test_the_rule_names_the_ban_on_a_threshold_over_the_rate(self):
        self.assertIn("порога на саму частоту правило НЕ", mod.WITNESS_RULE)


class StructuralZeroIsNotAMeasurement(unittest.TestCase):
    """Ноль по построению и измеренный ноль обязаны читаться по-разному."""

    def test_incumbents_carry_the_structural_zero_and_candidates_do_not(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertIsNotNone(cand(doc, WITNESS_SUBJECT)["structural_zero"])
        self.assertIsNotNone(cand(doc, WITNESS_VALUE)["structural_zero"])
        self.assertIsNone(cand(doc, WITNESS_ADR)["structural_zero"])

    def test_an_incumbent_firing_on_undecided_is_a_named_contradiction(self):
        """Разметка и эта мера спорят ⇒ спор называется, а не усредняется."""
        doc = measure([row(block_start=1)],
                      body="величина живёт в churn_damper и всё\n\n")
        self.assertEqual(len(cand(doc, WITNESS_SUBJECT)["contradictions"]), 1)
        self.assertIn("ПРОТИВОРЕЧИЕ", "\n".join(report(
            {"paragraph_witness_price": doc})))

    def test_a_quiet_incumbent_leaves_the_contradiction_list_empty(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertEqual(cand(doc, WITNESS_SUBJECT)["contradictions"], [])


class IndependenceIsReadWithTheReach(unittest.TestCase):
    """Постоянный вердикт и отсутствие различительной силы выглядят одинаково."""

    def test_an_always_silent_candidate_is_not_called_a_name_reader(self):
        doc = measure([row(block_start=PLAIN_BLOCK, named_as="A"),
                       row(block_start=UNIT_BLOCK, named_as="A")])
        entry = cand(doc, WITNESS_ADR)
        self.assertEqual(entry["independence"]["verdict"], DEPTH_NAME_ONLY)
        self.assertIn("постоянен сам ответ", entry["independence_reading"])
        self.assertIn("имени не видит", entry["independence_reading"])

    def test_a_candidate_constant_on_repeats_but_not_everywhere_is_named_so(self):
        """Имя «A» — два РАЗНЫХ абзаца и один вердикт; «B» — вердикт обратный.

        Кандидат здесь не молчит всегда и не срабатывает всегда, поэтому
        объяснение «постоянен сам ответ» неприменимо, а различительной силы на
        повторах всё равно нет — и это ДРУГОЕ утверждение, чем «читает имя».
        """
        doc = measure([row(block_start=ADR_BLOCK, named_as="A"),
                       row(block_start=ADR_BLOCK_TWO, named_as="A"),
                       row(block_start=PLAIN_BLOCK, named_as="B")])
        entry = cand(doc, WITNESS_ADR)
        self.assertEqual(entry["independence"]["verdict"], DEPTH_NAME_ONLY)
        self.assertEqual(entry["reach"]["authority"],
                         {"fired": 2, "silent": 1, "unaskable": 0})
        self.assertIn("на ЭТОМ населении", entry["independence_reading"])
        self.assertNotIn("постоянен сам ответ", entry["independence_reading"])

    def test_a_varying_candidate_is_reported_as_distinguishing(self):
        doc = measure([row(block_start=ADR_BLOCK, named_as="A"),
                       row(block_start=PLAIN_BLOCK, named_as="A")])
        entry = cand(doc, WITNESS_ADR)
        self.assertEqual(entry["independence"]["verdict"], DEPTH_READS_TEXT)
        self.assertIn("различает", entry["independence_reading"])

    def test_without_repeats_the_reading_says_degenerate(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        self.assertIn("вырождено",
                      cand(doc, WITNESS_ADR)["independence_reading"])


class TheSectionSpeaksWhereItMatters(unittest.TestCase):
    """Секция отчёта не вложена в чужую ветку и молчанием не отвечает."""

    def test_a_census_without_the_coordinate_says_not_measured(self):
        self.assertIn("[СВИДЕТЕЛИ АБЗАЦА] НЕ ИЗМЕРЕНЫ — перепись собрана без",
                      "\n".join(report({})))

    def test_a_refusal_of_the_coordinate_is_printed_with_its_reason(self):
        lines = "\n".join(report({"paragraph_witness_price": {
            "status": PARAGRAPH_WITNESS_UNMEASURED, "reason": "ПРИЧИНА"}}))
        self.assertIn("[СВИДЕТЕЛИ АБЗАЦА] НЕ ИЗМЕРЕНЫ: ПРИЧИНА", lines)

    def test_the_section_speaks_even_when_the_neighbour_coordinate_is_silent(self):
        """Вложенная в `else` соседа, она молчала бы там, где нужнее всего."""
        doc = measure([row(block_start=ADR_BLOCK)])
        lines = "\n".join(report({"paragraph_witness_price": doc}))
        self.assertIn("[СВИДЕТЕЛИ АБЗАЦА · ПРАВИЛО]", lines)
        self.assertIn("[СВИДЕТЕЛЬ · adr_cited]", lines)

    def test_every_candidate_gets_a_line_of_its_own(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        lines = "\n".join(report({"paragraph_witness_price": doc}))
        for key in doc["candidates"]:
            self.assertIn(f"[СВИДЕТЕЛЬ · {key}]", lines)

    def test_an_unmeasured_rate_is_printed_as_such_not_as_zero(self):
        doc = measure([row(block_start=ADR_BLOCK)])
        lines = "\n".join(report({"paragraph_witness_price": doc}))
        self.assertIn("частота ошибки на контроле НЕ ИЗМЕРЕНА", lines)

    def test_unresolved_and_unreadable_rows_are_printed_by_name(self):
        doc = measure([row(block_start=999, named_as="ПРОПАЛА"),
                       row(label="СТРАННО", named_as="КРИВАЯ"),
                       row(block_start=ADR_BLOCK)])
        lines = "\n".join(report({"paragraph_witness_price": doc}))
        self.assertIn("ПРОПАЛА", lines)
        self.assertIn("КРИВАЯ", lines)


class TheCoordinateIsWiredIntoTheCensus(unittest.TestCase):
    """Проводка проверяется формой ВЫЗОВА, а не наличием слова в тексте."""

    def _measure_tree(self):
        return ast.parse(inspect.getsource(mod.measure)).body[0]

    def test_measure_calls_the_coordinate_and_binds_its_result(self):
        names = {
            node.targets[0].id
            for node in ast.walk(self._measure_tree())
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "paragraph_witness_price"
            and isinstance(node.targets[0], ast.Name)}
        self.assertEqual(len(names), 1)
        self.bound = names.pop()

    def test_the_bound_result_is_what_lands_under_the_artifact_key(self):
        self.test_measure_calls_the_coordinate_and_binds_its_result()
        found = [
            value.id
            for node in ast.walk(self._measure_tree())
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant)
            and key.value == "paragraph_witness_price"
            and isinstance(value, ast.Name)]
        self.assertEqual(found, [self.bound])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
