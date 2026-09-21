"""Цена ДОПУСКА свидетеля в правило, в валюте пар — заказ **G64 п. 1**.

ADR-441 измерил у кандидата `adr_cited` два числа и прямо сказал, чего НЕ
доказал: что кандидата стои́т ВВЕСТИ. Цена введения платится не в
срабатываниях разметки, а в ПАРАХ — в том, что канал доносит до книг, — и
заказ потребовал именно её: сколько пар прибавляет правило
``GENUINE = W1 и (W2 или W3 или Wк)``, сколько из них приходит из абзацев,
уже давших пару, и как двигается интервал истины — ОБЕ границы.

Эти тесты держат ровно это: что цена считается в парах, что обе границы
меряются (а не объявляются прозой), что прибыток на КОНТРОЛЕ ложен по
построению и не складывается со стороной объявлений, что каждое отсутствие
осталось отдельным значением, и что база сравнения — пары канала — сверяется
с меткой `GENUINE` ПЕРЕСЕЧЕНИЕМ, а не равенством чисел.

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
    ADMISSION_RULE,
    LABEL_ARTEFACT,
    LABEL_GENUINE,
    LABEL_UNDECIDED,
    PARAGRAPH_WITNESSES,
    WITNESS_ADMISSION_UNMEASURED,
    WITNESS_ADR,
    WITNESS_SUBJECT,
    WITNESS_UNIT,
    WITNESS_VALUE,
    report,
    truth_interval,
    witness_admission_price,
)

TEXT = "rules.md"

#: Сцена: три абзаца, начинающиеся строками 1, 4 и 7. Первый называет решение
#: (ADR) и величину с единицей, второй — только решение, третий — ничего из
#: объявленного.
SCENE = "\n".join([
    "порог введён решением ADR-053 и равен 5 %",   # 1
    "менять его вправе только владелец",           # 2
    "",                                            # 3
    "второй абзац о том же, решение ADR-065",      # 4
    "и ни о чём больше",                           # 5
    "",                                            # 6
    "здесь про порядок работы",                    # 7
    "никаких величин и ссылок",                    # 8
])
ADR_UNIT_BLOCK, ADR_BLOCK, PLAIN_BLOCK = 1, 4, 7


def scene_root(body=SCENE, name=TEXT):
    """Одноразовое дерево со сценой; живой репозиторий не трогается."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / name).write_text(body, encoding="utf-8")
    return tmp, root


def row(*, side="authority", label=LABEL_UNDECIDED, block_start=PLAIN_BLOCK,
        named_as="MIN_CASH_PCT", resolved="spa_core/governance/churn_damper.py",
        value=None, text=TEXT):
    return {"side": side, "text": text, "block_start": block_start,
            "named_as": named_as, "resolved": resolved, "value": value,
            "label": label}


def precision(rows):
    return {"status": "MEASURED", "rows": list(rows)}


def channel(pairs):
    return {"status": "MEASURED", "pairs": list(pairs)}


def pair(*, text=TEXT, line=PLAIN_BLOCK, named_as="MIN_CASH_PCT",
         resolved="spa_core/governance/churn_damper.py", value=0.05):
    return {"text": text, "line": line, "named_as": named_as,
            "resolved": resolved, "value": value}


def cand(doc, key):
    return doc["candidates"][key]


class RuleDeclaredBeforeTheMeasure(unittest.TestCase):
    """Правило объявлено ДО замера, и порог им НЕ вводится."""

    def test_rule_names_the_currency_and_both_bounds(self):
        # Валюта и обе границы обязаны быть НАЗВАНЫ в самом правиле: правило,
        # умолчавшее о том, что меряет, подгоняется под исход безнаказанно.
        self.assertIn("пар", ADMISSION_RULE)
        self.assertIn("ОБЕИМИ границами", ADMISSION_RULE)
        self.assertIn("Порог НЕ вводится", ADMISSION_RULE)

    def test_threshold_is_not_applied_in_any_outcome(self):
        tmp, root = scene_root()
        with tmp:
            measured = witness_admission_price(
                root, precision([row()]), channel([]))
            refused = witness_admission_price(root, None, None)
        # Обратная сторона: `applied` ложно И у измеренного исхода, И у
        # отказа. Ветка, теряющая его при отказе, тихо разрешила бы порог.
        self.assertIs(measured["applied"], False)
        self.assertIs(refused["applied"], False)

    def test_the_census_reads_the_coordinate_nowhere_but_the_document(self):
        """Ни один вердикт переписи не зависит от этой координаты."""
        tree = ast.parse(inspect.getsource(mod))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "measure")
        uses = [n for n in ast.walk(fn) if isinstance(n, ast.Name)
                and n.id == "admission_price" and isinstance(n.ctx, ast.Load)]
        # Ровно одно чтение — укладка в документ. Второе означало бы, что цена
        # что-то гейтит, а порога заказ вводить запретил.
        self.assertEqual(len(uses), 1, "цена допуска читается не только в документ")


class PriceIsCountedInPairs(unittest.TestCase):
    """Прибыток считается в парах и только у стороны объявлений."""

    def test_added_equals_undecided_rows_where_the_candidate_fires(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK),          # ADR назван -> прибывает
                row(block_start=PLAIN_BLOCK),        # ничего не названо
            ]), channel([]))
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["added"], 1)
        # Обратная сторона на той же сцене: кандидат, которого абзац не
        # называет, не прибавляет ничего — иначе прибыток был бы свойством
        # прохода, а не свидетеля.
        self.assertEqual(cand(doc, WITNESS_UNIT)["sides"]["authority"]["added"], 0)

    def test_genuine_and_artefact_rows_never_arrive(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, label=LABEL_GENUINE),
                row(block_start=ADR_BLOCK, label=LABEL_ARTEFACT),
            ]), channel([]))
            moved = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, label=LABEL_UNDECIDED),
            ]), channel([]))
        # `GENUINE` уже в правиле, `ARTEFACT` снят ещё W1 — прибыть может
        # только `UNDECIDED`, и обратная сторона показывает, что на той же
        # сцене он прибывает.
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["added"], 0)
        self.assertEqual(cand(moved, WITNESS_ADR)["sides"]["authority"]["added"], 1)

    def test_control_arrivals_are_counted_apart_from_authority(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, side="authority"),
                row(block_start=ADR_BLOCK, side="control"),
                row(block_start=ADR_BLOCK, side="control"),
            ]), channel([]))
        sides = cand(doc, WITNESS_ADR)["sides"]
        # Два числа, два знаменателя. Сложить их значило бы выдать ложный по
        # построению прибыток контроля за прибыток книгам.
        self.assertEqual(sides["authority"]["added"], 1)
        self.assertEqual(sides["control"]["added"], 2)
        self.assertEqual(sides["authority"]["labelled"], 1)
        self.assertEqual(sides["control"]["labelled"], 2)


class BothBoundsAreMeasured(unittest.TestCase):
    """Обе границы интервала МЕРЯЮТСЯ, а не объявляются прозой."""

    def test_lower_moves_and_upper_stays_and_both_are_measured(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK),
                row(block_start=PLAIN_BLOCK),
                row(block_start=PLAIN_BLOCK, label=LABEL_ARTEFACT),
            ]), channel([]))
        side = cand(doc, WITNESS_ADR)["sides"]["authority"]
        self.assertEqual(side["interval_before"],
                         truth_interval(0, 2, 3))
        self.assertEqual(side["interval_after"],
                         truth_interval(1, 1, 3))
        # Обе стороны утверждения: нижняя ОБЯЗАНА тронуться (иначе тест
        # вырожден и молчал бы при любой поломке), верхняя — остаться.
        self.assertIs(side["lower_bound_moved"], True)
        self.assertIs(side["upper_bound_moved"], False)

    def test_a_candidate_that_adds_nothing_moves_neither_bound(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=PLAIN_BLOCK),
            ]), channel([]))
        side = cand(doc, WITNESS_ADR)["sides"]["authority"]
        self.assertIs(side["lower_bound_moved"], False)
        self.assertIs(side["upper_bound_moved"], False)
        self.assertEqual(side["interval_before"], side["interval_after"])

    def test_the_counts_behind_the_bounds_are_published_too(self):
        """Интервал — производное; сами числа «до» и «после» обязаны стоять."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK),
                row(block_start=PLAIN_BLOCK),
                row(block_start=PLAIN_BLOCK, label=LABEL_ARTEFACT),
            ]), channel([]))
        side = cand(doc, WITNESS_ADR)["sides"]["authority"]
        self.assertEqual(side["genuine_before"], 0)
        self.assertEqual(side["genuine_after"], 1)
        self.assertEqual(side["undecided_before"], 2)
        self.assertEqual(side["undecided_after"], 1)
        self.assertEqual(side["artefact"], 1)
        # Обратная сторона: у кандидата, который не прибавляет, те же четыре
        # числа стоят на месте — иначе «после» было бы свойством печати.
        silent = cand(doc, WITNESS_UNIT)["sides"]["authority"]
        self.assertEqual(silent["genuine_after"], silent["genuine_before"])
        self.assertEqual(silent["undecided_after"], silent["undecided_before"])

    def test_the_invariant_note_stands_beside_the_numbers_not_instead(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK)]), channel([]))
        side = cand(doc, WITNESS_ADR)["sides"]["authority"]
        self.assertIn("ОПРЕДЕЛЕНИЯ", side["upper_bound_note"])
        # Записка не заменяет замер: обе границы обязаны быть ЧИСЛАМИ рядом.
        self.assertIsNotNone(side["interval_before"])
        self.assertIsNotNone(side["interval_after"])


class ProvenanceOfTheAddedPairs(unittest.TestCase):
    """Из каких абзацев прибыли пары — и это ТРЕТИЙ ИСХОД, если пар нет."""

    def test_a_paragraph_that_already_pays_is_told_apart(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
                row(block_start=ADR_UNIT_BLOCK, named_as="B"),
            ]), channel([pair(line=ADR_BLOCK, named_as="OTHER")]))
        prov = cand(doc, WITNESS_ADR)["pair_provenance"]
        self.assertEqual(prov["added"], 2)
        self.assertEqual(prov["from_paragraph_already_paying"], 1)
        self.assertEqual(prov["from_paragraph_silent_until_now"], 1)
        self.assertEqual(prov["paragraphs_added"], 2)
        self.assertEqual(prov["paragraphs_new_to_books"], 1)

    def test_paragraphs_are_counted_as_paragraphs_not_as_hits(self):
        """Два прибывших из ОДНОГО абзаца — это один абзац, а не два."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
                row(block_start=ADR_BLOCK, named_as="B"),
            ]), channel([]))
        prov = cand(doc, WITNESS_ADR)["pair_provenance"]
        self.assertEqual(prov["added"], 2)
        self.assertEqual(prov["paragraphs_added"], 1)
        self.assertEqual(prov["paragraphs_new_to_books"], 1)
        # Обратная сторона: те же две строки из РАЗНЫХ абзацев дают два.
        tmp2, root2 = scene_root()
        with tmp2:
            spread = witness_admission_price(root2, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
                row(block_start=ADR_UNIT_BLOCK, named_as="B"),
            ]), channel([]))
        self.assertEqual(
            cand(spread, WITNESS_ADR)["pair_provenance"]["paragraphs_added"], 2)

    def test_moving_the_pair_elsewhere_flips_the_verdict(self):
        """Обратная сторона: та же сцена, пара в другом абзаце."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
            ]), channel([pair(line=PLAIN_BLOCK, named_as="OTHER")]))
        prov = cand(doc, WITNESS_ADR)["pair_provenance"]
        self.assertEqual(prov["from_paragraph_already_paying"], 0)
        self.assertEqual(prov["from_paragraph_silent_until_now"], 1)

    def test_absent_pairs_are_a_third_outcome_not_a_zero(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK)]), None)
        prov = cand(doc, WITNESS_ADR)["pair_provenance"]
        self.assertEqual(prov["status"], WITNESS_ADMISSION_UNMEASURED)
        self.assertNotIn("from_paragraph_already_paying", prov)
        self.assertIn("НЕ «не платит ни один»", prov["reason"])
        # Прибыток при этом ИЗМЕРЕН: отказ локален и не гасит соседний вопрос.
        self.assertEqual(prov["added"], 1)
        self.assertEqual(doc["status"], "MEASURED")

    def test_an_empty_pair_list_is_measured_and_not_refused(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([row()]), channel([]))
        # Пустой перечень пар — это ИЗМЕРЕННЫЙ ноль, в отличие от отсутствия
        # перечня. Слить их значило бы совершить дефект самой переписи.
        self.assertEqual(doc["pairs_today"]["status"], "MEASURED")
        self.assertEqual(doc["pairs_today"]["pairs"], 0)


class TheBaseOfComparisonIsMeasuredNotAssumed(unittest.TestCase):
    """Пары канала и метка `GENUINE` сверяются ПЕРЕСЕЧЕНИЕМ, а не числом."""

    def test_equal_counts_with_different_sets_are_reported_as_such(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A", label=LABEL_GENUINE),
            ]), channel([pair(line=ADR_BLOCK, named_as="B")]))
        today = doc["pairs_today"]
        self.assertEqual(today["pairs"], 1)
        self.assertEqual(today["genuine_overlap"], 0)
        self.assertEqual(len(today["pairs_not_genuine"]), 1)
        self.assertEqual(len(today["genuine_not_pairs"]), 1)

    def test_identical_coordinates_do_overlap(self):
        """Обратная сторона: те же координаты обязаны пересечься."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A", label=LABEL_GENUINE),
            ]), channel([pair(line=ADR_BLOCK, named_as="A")]))
        self.assertEqual(doc["pairs_today"]["genuine_overlap"], 1)
        self.assertEqual(doc["pairs_today"]["pairs_not_genuine"], [])
        self.assertEqual(doc["pairs_today"]["genuine_not_pairs"], [])

    def test_only_genuine_rows_enter_the_genuine_side_of_the_overlap(self):
        """Метка проверяется: иначе «GENUINE» вобрал бы всё население."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A", label=LABEL_UNDECIDED),
                row(block_start=ADR_BLOCK, named_as="B", label=LABEL_ARTEFACT),
            ]), channel([pair(line=ADR_BLOCK, named_as="A"),
                         pair(line=ADR_BLOCK, named_as="B")]))
        today = doc["pairs_today"]
        self.assertEqual(today["genuine_overlap"], 0)
        self.assertEqual(len(today["pairs_not_genuine"]), 2)
        # Обратная сторона на той же сцене: та же координата с меткой
        # `GENUINE` пересекается.
        with scene_root()[0] as _:
            pass
        tmp2, root2 = scene_root()
        with tmp2:
            doc2 = witness_admission_price(root2, precision([
                row(block_start=ADR_BLOCK, named_as="A", label=LABEL_GENUINE),
            ]), channel([pair(line=ADR_BLOCK, named_as="A")]))
        self.assertEqual(doc2["pairs_today"]["genuine_overlap"], 1)

    def test_a_pair_arriving_that_is_already_a_pair_is_a_contradiction(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
            ]), channel([pair(line=ADR_BLOCK, named_as="A")]))
        # `UNDECIDED` означает «без W3», а пара канала — ровно W3. Пересечение
        # обязано быть пустым, и поэтому оно МЕРЯЕТСЯ, а не предполагается.
        self.assertEqual(len(cand(doc, WITNESS_ADR)["already_a_pair"]), 1)

    def test_the_ordinary_case_has_no_contradiction(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, named_as="A"),
            ]), channel([pair(line=ADR_BLOCK, named_as="B")]))
        self.assertEqual(cand(doc, WITNESS_ADR)["already_a_pair"], [])


class IncumbentsAreZeroByConstruction(unittest.TestCase):

    def test_incumbent_witnesses_add_nothing_and_say_why(self):
        """Согласованная разметка: `UNDECIDED` и есть «без W2 и без W3»."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, value=0.99,
                    resolved="spa_core/governance/churn_damper.py"),
            ]), channel([]))
        for key in (WITNESS_SUBJECT, WITNESS_VALUE):
            with self.subTest(key=key):
                self.assertEqual(cand(doc, key)["sides"]["authority"]["added"], 0)
                self.assertIn("ПО ОПРЕДЕЛЕНИЮ",
                              cand(doc, key)["structural_zero"])
                self.assertEqual(cand(doc, key)["contradicts_marking"], [])
        # Обратная сторона: у кандидата этой записки НЕТ, иначе «ноль по
        # построению» стал бы оправданием любого нуля; и он на той же сцене
        # прибавляет — иначе ноль был бы свойством сцены, а не определения.
        self.assertIsNone(cand(doc, WITNESS_ADR)["structural_zero"])
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["added"], 1)

    def test_an_incumbent_firing_on_undecided_is_a_loud_contradiction(self):
        """Ожидание «ноль по построению» ОПРОВЕРЖИМО, и опровержение кричит."""
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                # Строка помечена `UNDECIDED`, а величина имени в абзаце СТОИ́Т:
                # разметка и мера спорят об одной и той же строке.
                row(block_start=ADR_UNIT_BLOCK, value=5.0),
            ]), channel([]))
        cell = cand(doc, WITNESS_VALUE)
        self.assertEqual(len(cell["contradicts_marking"]), 1)
        body = "\n".join(report({"rows": [], "classified": 0,
                                 "witness_admission_price": doc}))
        self.assertIn("ноль по построению ОПРОВЕРГНУТ замером", body)


class EveryAbsenceIsItsOwnValue(unittest.TestCase):
    """Пять отказов разведены отдельными причинами (инв. #17)."""

    def test_each_refusal_names_its_own_reason(self):
        tmp, root = scene_root()
        cases = {
            "нет координаты": (None, "перепись собрана без"),
            "отказ соседа": ({"status": "X"}, "ОТКАЗАЛА"),
            "нет населения": ({"status": "MEASURED", "rows": None},
                              "размечены и не записаны"),
            "не перечень": ({"status": "MEASURED", "rows": {}},
                            "а не перечень"),
            "пусто": ({"status": "MEASURED", "rows": []},
                      "НЕ «цена нулевая»"),
        }
        with tmp:
            for name, (arg, needle) in cases.items():
                with self.subTest(case=name):
                    doc = witness_admission_price(root, arg, channel([]))
                    self.assertEqual(doc["status"], WITNESS_ADMISSION_UNMEASURED)
                    self.assertIn(needle, doc["reason"])
                    self.assertIn("rule", doc)

    def test_reasons_are_all_different(self):
        tmp, root = scene_root()
        args = [None, {"status": "X"}, {"status": "MEASURED", "rows": None},
                {"status": "MEASURED", "rows": {}},
                {"status": "MEASURED", "rows": []}]
        with tmp:
            reasons = {witness_admission_price(root, a, channel([]))["reason"]
                       for a in args}
        # Пять причин, а не одно «не измерено» на всех: они чинятся в разных
        # местах, и слить их значило бы отдать читателю меньше, чем известно.
        self.assertEqual(len(reasons), 5)

    def test_a_label_outside_the_declared_three_is_named(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                {**row(), "label": "СВОЯ"}]), channel([]))
        self.assertEqual(doc["status"], WITNESS_ADMISSION_UNMEASURED)
        self.assertIn("метки из объявленных трёх", doc["reason"])
        self.assertEqual(len(doc["unreadable"]), 1)

    def test_an_unresolvable_paragraph_does_not_arrive(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=999),
                row(block_start=ADR_BLOCK),
            ]), channel([]))
        # Неразрешённый абзац назван причиной и НЕ прибывает; соседняя строка
        # той же сцены прибывает — иначе тест не отличил бы отказ от нуля.
        self.assertEqual(len(doc["unresolved"]), 1)
        self.assertIn("не разрешается", doc["unresolved"][0]["reason"])
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["added"], 1)
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["unaskable"], 1)

    def test_a_side_outside_the_declared_two_is_unmeasured_not_zero(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, side="сторона-3"),
            ]), channel([]))
        side = cand(doc, WITNESS_ADR)["sides"]["сторона-3"]
        self.assertEqual(side["status"], WITNESS_ADMISSION_UNMEASURED)
        self.assertNotIn("added", side)
        self.assertIn("не из объявленных двух", side["reason"])

    def test_a_witness_that_cannot_be_asked_is_not_counted_as_silent(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK, resolved=""),
            ]), channel([]))
        # У W2 исполнитель не записан — вопрос неприменим; у `adr_cited`
        # применим и на той же строке. Обратная сторона держит различие.
        self.assertEqual(cand(doc, WITNESS_SUBJECT)["sides"]["authority"]["unaskable"], 1)
        self.assertEqual(cand(doc, WITNESS_ADR)["sides"]["authority"]["unaskable"], 0)


class NoSecondCopyOfTheRule(unittest.TestCase):
    """Мера зовёт объявленные один раз правила, а не переписывает их."""

    def _fn(self):
        tree = ast.parse(inspect.getsource(mod))
        return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                    and n.name == "witness_admission_price")

    def test_the_interval_is_asked_of_the_single_declaration(self):
        called = {n.func.id for n in ast.walk(self._fn())
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("truth_interval", {*called, *{
            n.func.id for n in ast.walk(ast.parse(inspect.getsource(
                mod._admission_side))) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)}})

    def test_the_candidates_are_asked_of_the_single_declaration(self):
        src = ast.dump(self._fn())
        self.assertIn("PARAGRAPH_WITNESSES", src)
        # Своих регулярных выражений у меры быть не должно: вердикт кандидата
        # спрашивается пробой, а вторая копия пробы и есть предмет переписи.
        self.assertNotIn("re.compile", inspect.getsource(
            mod.witness_admission_price))

    def test_the_two_names_of_one_coordinate_are_reconciled_once(self):
        """`line` у пары и `block_start` у строки — одно число, одна свёртка."""
        same = mod._pair_key({"text": TEXT, "line": 5, "named_as": "A",
                              "resolved": "x.py"}, line_field="line")
        other = mod._pair_key({"text": TEXT, "block_start": 5, "named_as": "A",
                               "resolved": "x.py"}, line_field="block_start")
        self.assertEqual(same, other)
        # Обратная сторона: каждое поле координаты обязано различать. Имя
        # исполнителя здесь не украшение — одно имя объявляют РАЗНЫЕ модули,
        # и склеить их значило бы посчитать две пары за одну.
        for changed in ({"line": 6}, {"named_as": "B"}, {"resolved": "y.py"},
                        {"text": "other.md"}):
            with self.subTest(changed=changed):
                self.assertNotEqual(same, mod._pair_key(
                    {"text": TEXT, "line": 5, "named_as": "A",
                     "resolved": "x.py", **changed}, line_field="line"))


class TheSectionSpeaksInEveryOutcome(unittest.TestCase):

    def test_the_section_is_printed_when_the_coordinate_is_absent(self):
        lines = report({"rows": [], "classified": 0})
        self.assertTrue(any("[ЦЕНА ДОПУСКА] НЕ ИЗМЕРЕНА" in line
                            for line in lines))

    def test_the_section_names_the_refusal_reason(self):
        doc = {"rows": [], "classified": 0,
               "witness_admission_price": {
                   "status": WITNESS_ADMISSION_UNMEASURED,
                   "reason": "своя причина"}}
        self.assertTrue(any("своя причина" in line for line in report(doc)))

    def test_the_measured_section_names_both_sides_and_both_bounds(self):
        tmp, root = scene_root()
        with tmp:
            price = witness_admission_price(root, precision([
                row(block_start=ADR_BLOCK),
                row(block_start=ADR_BLOCK, side="control"),
            ]), channel([pair(line=ADR_BLOCK, named_as="OTHER")]))
        lines = report({"rows": [], "classified": 0,
                        "witness_admission_price": price})
        body = "\n".join(lines)
        self.assertIn("[ЦЕНА ДОПУСКА · КНИГИ СЕГОДНЯ]", body)
        self.assertIn("ИНТЕРВАЛ объявления", body)
        self.assertIn("ИНТЕРВАЛ контроль", body)
        self.assertIn("ложных ПО ПОСТРОЕНИЮ", body)
        self.assertIn("порог введён: НЕТ", body)

    def test_a_moved_upper_bound_is_called_a_contradiction(self):
        """Расхождение с ожиданием обязано КРИЧАТЬ, а не молчать."""
        price = {
            "status": "MEASURED", "applied": False, "rule": ADMISSION_RULE,
            "pairs_today": {"status": "MEASURED", "pairs": 0, "paragraphs": 0},
            "candidates": {WITNESS_ADR: {
                "incumbent": False, "reads": "абзац",
                "admitted_rule": "GENUINE = W1 и (W2 или W3 или `adr_cited`)",
                "pair_provenance": {"status": "MEASURED", "added": 1,
                                    "paragraphs_added": 1,
                                    "from_paragraph_already_paying": 0,
                                    "from_paragraph_silent_until_now": 1,
                                    "paragraphs_new_to_books": 1},
                "sides": {"authority": {
                    "status": "MEASURED", "added": 1,
                    "interval_before": truth_interval(0, 1, 1),
                    "interval_after": truth_interval(1, 1, 2),
                    "lower_bound_moved": True, "upper_bound_moved": True,
                    "upper_bound_note": "…"}},
                "structural_zero": None, "already_a_pair": [], "examples": []}},
        }
        body = "\n".join(report({"rows": [], "classified": 0,
                                 "witness_admission_price": price}))
        self.assertIn("ПРОТИВОРЕЧИЕ ОПРЕДЕЛЕНИЮ", body)


class TheCoordinateIsWiredIntoTheCensus(unittest.TestCase):

    def test_measure_calls_it_and_puts_it_in_the_document(self):
        tree = ast.parse(inspect.getsource(mod))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "measure")
        calls = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)}
        self.assertIn("witness_admission_price", calls)
        keys = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)
                and isinstance(n.value, str)}
        self.assertIn("witness_admission_price", keys)

    def test_the_candidates_are_declared_in_the_document_itself(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([row()]), channel([]))
            refused = witness_admission_price(root, None, None)
        for got in (doc, refused):
            with self.subTest(status=got["status"]):
                self.assertEqual({c["key"] for c in got["declared"]},
                                 {c["key"] for c in PARAGRAPH_WITNESSES})
        # Объявление обязано пережить и отказ: кандидаты названы ДО замера,
        # и отказ не есть повод умолчать, кого собирались мерить.
        self.assertTrue(all("incumbent" in c for c in doc["declared"]))

    def test_the_census_feeds_it_the_marking_and_not_an_emptiness(self):
        """Проводка проверяется АРГУМЕНТОМ вызова, а не именем в тексте.

        Подстрочная проверка «имя функции встречается в `measure`» пережила бы
        любую распайку: вызов остался бы, а кормили бы его пустотой. Поэтому
        спрашивается ТОЖДЕСТВО: первым после дерева идёт ровно то имя, которым
        связан результат соседней разметки, вторым — сам канал.
        """
        tree = ast.parse(inspect.getsource(mod))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "measure")
        call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "witness_admission_price")
        args = [a.id if isinstance(a, ast.Name) else type(a).__name__
                for a in call.args]
        self.assertEqual(args[0], "root")
        self.assertEqual(len(call.args), 3, "мера зовётся не тремя доводами")
        precision_name, channel_name = args[1], args[2]
        bound = {t.id for a in ast.walk(fn) if isinstance(a, ast.Assign)
                 and isinstance(a.value, ast.Call)
                 and isinstance(a.value.func, ast.Name)
                 and a.value.func.id == "bilingual_name_precision"
                 for t in a.targets if isinstance(t, ast.Name)}
        # Первый довод — РЕЗУЛЬТАТ соседней разметки, а не что-нибудь ещё.
        self.assertIn(precision_name, bound)
        # Второй — канал имени, тот же, что кормит разметку: два довода из
        # разных источников означали бы, что мера судит о разных замерах.
        feeds = {a.id for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name)
                 and c.func.id == "bilingual_name_precision"
                 for a in c.args if isinstance(a, ast.Name)}
        self.assertIn(channel_name, feeds)

    def test_every_declared_candidate_gets_a_price(self):
        tmp, root = scene_root()
        with tmp:
            doc = witness_admission_price(root, precision([row()]), channel([]))
        # Меряются ВСЕ объявленные, а не один названный заказом: выбрать
        # кандидата по увиденному исходу и есть запрет G62.
        self.assertEqual(set(doc["candidates"]),
                         {c["key"] for c in PARAGRAPH_WITNESSES})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
