"""Ось РОДА рядом с кандидатом недельной переписи (заказ **G113 п. 1**).

Заказ дословно: «``list_identity_census`` печатает кандидату длину и население;
рода у него нет, а решение о дописывании имени принимается по всем трём.
Проводка обязана быть проверена не наличием вызова, а произведённым документом —
то есть прогоном стендов, и это отдельная работа, а не строчка.»

## Что здесь мерится и чего здесь НЕ мерится

Правило рода живёт у себя (``identity_field_kind``, ADR-539) и своей батареей
накрыто. Здесь предмет другой — **свод**: берёт ли перепись род у признака тем
же населением, в том же порядке, с теми же тремя исходами, и доезжает ли он до
ЧИТАТЕЛЯ (шаг 0-офис). Поэтому сцены — одноразовые деревья с НАСТОЯЩИМИ
производителями: подменять признак целиком значило бы проверить свой стенд.

У каждой проверки есть обратная сторона с НАЗВАННЫМ звеном: порви звено — и она
краснеет. Проверка, никогда не видевшая поломки, — украшение
(``.claude/rules/deployment.md``).

Литеральных дат в файле нет вовсе, часы нигде не читаются: род есть утверждение
о КОДЕ, а не о времени, поэтому вердикт не зависит ни от календаря хоста, ни от
длительности прогона.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import identity_field_kind as field_kind
from spa_core.monitoring import candidate_denominator as cand_denom
from spa_core.monitoring import list_identity_census as census
from spa_core.tests._freshness import ts

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
ARTIFACT_REL = "data/list_identity_census.json"

#: Производитель, у которого род КАЖДОГО имени разный и названный. Это не
#: выдумка стенда: все три формы сняты с живого кода (ADR-539 перечисляет их
#: поимённо), и именно по ним признак отвечает.
PRODUCER = '''\
import datetime as dt


def build(items, record):
    doc = {
        "alpha": dt.datetime.now(dt.timezone.utc).isoformat(),
        "beta": record["name"],
        "gamma": len(items),
        "delta": 300,
    }
    return doc
'''


def _tree(**files: str) -> Path:
    """Одноразовое дерево с производителями. Живое дерево не читается.

    ОБА объявленных признаком корня (``spa_core``, ``scripts``) создаются
    всегда, даже пустыми: отсутствие корня — собственный третий исход признака
    («каталога нет в дереве»), и сцена, забывшая второй корень, мерила бы его
    вместо нечитаемого файла. Замер: без этой строки «не разобрано» равнялось
    единице на ЧИСТОМ дереве.
    """
    root = Path(tempfile.mkdtemp(prefix="spa_g113_kind_"))
    for declared in field_kind.DEFAULT_ROOTS:
        (root / declared).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _row(axis: dict, field: str) -> dict:
    return next(r for r in axis["rows"] if r["field"] == field)


def _office():
    spec = importlib.util.spec_from_file_location("_office_kind_axis", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class KindIsAskedOfTheProducersCode(unittest.TestCase):
    """Род — утверждение о КОДЕ, и свод везёт именно его, а не ярлык «есть»."""

    def setUp(self):
        self.root = _tree(**{"spa_core/p.py": PRODUCER})
        self.freq = {"alpha": 2, "beta": 3, "gamma": 4, "delta": 5}
        self.strength = {"alpha": 11, "beta": 9, "gamma": 7, "delta": 5}
        self.axis = census.kind_axis(self.freq, self.strength, self.root)

    def test_the_axis_is_measured_and_names_its_denominator(self):
        self.assertEqual(self.axis["status"], "MEASURED")
        self.assertEqual(self.axis["names"], 4)
        self.assertGreater(self.axis["files_parsed"], 0)

    def test_the_clock_axis_separates_a_wall_clock_field_from_a_copied_one(self):
        self.assertEqual(_row(self.axis, "alpha")["clock_verdict"],
                         field_kind.WALL_CLOCK)
        self.assertEqual(_row(self.axis, "beta")["clock_verdict"],
                         field_kind.NOT_DERIVED)

    def test_the_arithmetic_axis_separates_a_count_from_a_constant(self):
        self.assertEqual(_row(self.axis, "gamma")["arithmetic_verdict"],
                         field_kind.ARITH_DERIVED)
        self.assertEqual(_row(self.axis, "delta")["arithmetic_verdict"],
                         field_kind.NOT_ARITH)

    def test_positive_control_remove_the_clock_and_the_verdict_flips(self):
        """Обратная сторона: свод не штампует род, он его СПРАШИВАЕТ."""
        plain = PRODUCER.replace('dt.datetime.now(dt.timezone.utc).isoformat()',
                                 'record["stamp"]')
        axis = census.kind_axis(self.freq, self.strength,
                                _tree(**{"spa_core/p.py": plain}))
        self.assertEqual(_row(axis, "alpha")["clock_verdict"],
                         field_kind.NOT_DERIVED)

    def test_positive_control_remove_the_count_and_arithmetic_goes_quiet(self):
        plain = PRODUCER.replace("len(items)", 'record["n"]')
        axis = census.kind_axis(self.freq, self.strength,
                                _tree(**{"spa_core/p.py": plain}))
        self.assertEqual(_row(axis, "gamma")["arithmetic_verdict"],
                         field_kind.NOT_ARITH)

    def test_all_three_numbers_live_in_one_row(self):
        """Решение принимается по ТРЁМ числам — значит они и лежат вместе."""
        row = _row(self.axis, "alpha")
        self.assertEqual((row["population"], row["max_length"]), (2, 11))
        self.assertIn("clock_verdict", row)
        self.assertIn("arithmetic_verdict", row)

    def test_a_candidate_without_a_measured_length_says_so(self):
        axis = census.kind_axis({"alpha": 2}, {}, self.root)
        row = _row(axis, "alpha")
        self.assertIsNone(row["max_length"])
        self.assertTrue(row["max_length_unmeasured"])
        self.assertIn("НЕ ИЗМЕРЕНА", "\n".join(census.kind_axis_report(axis)))


class ThreeOutcomesOfTheFoldAreDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» бывает трёх разных видов, и ни один не ноль."""

    def test_no_candidates_is_its_own_outcome(self):
        axis = census.kind_axis({}, {}, _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("кандидатов нет", axis["reason"])
        self.assertNotIn("rows", axis)

    def test_no_tree_is_a_different_outcome_with_a_different_reason(self):
        axis = census.kind_axis({"alpha": 1}, {"alpha": 3})
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("дерево не названо", axis["reason"])
        empty = census.kind_axis({}, {}, _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertNotEqual(axis["reason"], empty["reason"],
                            "два разных «не измерено» звучат одинаково — "
                            "читатель не отличит отсутствие кандидатов от "
                            "отсутствия дерева")

    def test_a_tree_with_nothing_to_parse_is_not_four_zeroes(self):
        """Дерево названо и пусто ⇒ НЕ ИЗМЕРЕНО, а не «род чист у всех»."""
        axis = census.kind_axis({"alpha": 1}, {"alpha": 3},
                                _tree(**{"readme.md": "нет кода"}))
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("ни один файл дерева не разобран", axis["reason"])
        self.assertNotIn("by_clock_verdict", axis)

    def test_a_name_no_producer_writes_is_unmeasured_not_clean(self):
        axis = census.kind_axis({"nobody_writes_this": 2}, {},
                                _tree(**{"spa_core/p.py": PRODUCER}))
        row = _row(axis, "nobody_writes_this")
        self.assertEqual(row["clock_verdict"], field_kind.UNMEASURED)
        self.assertEqual(axis["by_clock_verdict"][field_kind.NOT_DERIVED], 0,
                         "«производителя не нашли» сложено в «чисто»")
        # Причина пришпилена ДОСЛОВНО: защитный хвост `or ""` у чтения причины,
        # обращённый в `and ""`, отдаёт пусто при НЕПУСТОМ входе, и причина
        # подменяется безымянной — проверка «причины непусты» это пропускала.
        self.assertEqual(axis["clock_unmeasured_causes"],
                         {"производитель поля не найден в дереве": 1})
        self.assertIn("НЕ ИЗМЕРЕНО: производитель поля не найден в дереве: "
                      "1 имён(и)", "\n".join(census.kind_axis_report(axis)))

    def test_the_tree_being_unreadable_is_named_not_swallowed(self):
        """Обратная сторона: отказ чтения дерева обязан быть НАЗВАН."""
        real = field_kind.census

        def _boom(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            raise OSError("дерево не читается")

        field_kind.census = _boom
        try:
            axis = census.kind_axis({"alpha": 1}, {"alpha": 3}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("OSError", axis["reason"])


class TheLabelHidesDisagreementSoItIsCountedApart(unittest.TestCase):
    """Вердикт имени выбран СТАРШИНСТВОМ — расхождение площадок отдельно."""

    #: Два производителя одного имени: у первого стенные часы, у второго —
    #: переписанное значение. Старшинство объявит имя стенным, и ярлык скроет,
    #: что род у площадок разный.
    TWO_PRODUCERS = {
        "spa_core/a.py": ('import datetime as dt\n\n\n'
                          'def a():\n'
                          '    return {"omega": dt.datetime.now().isoformat()}\n'),
        "spa_core/b.py": ('def b(record):\n'
                          '    return {"omega": record["omega"]}\n'),
    }

    def test_disagreement_is_found_and_the_label_is_the_strongest(self):
        axis = census.kind_axis({"omega": 4}, {"omega": 12},
                                _tree(**self.TWO_PRODUCERS))
        row = _row(axis, "omega")
        self.assertEqual(row["clock_verdict"], field_kind.WALL_CLOCK)
        self.assertTrue(row["kinds_disagree"])
        self.assertEqual(axis["disagreeing_names"], ["omega"])
        self.assertIn("РОД РАСХОДИТСЯ", "\n".join(census.kind_axis_report(axis)))

    def test_positive_control_one_kind_means_no_disagreement(self):
        only = {"spa_core/b.py": self.TWO_PRODUCERS["spa_core/b.py"]}
        axis = census.kind_axis({"omega": 4}, {"omega": 12}, _tree(**only))
        self.assertFalse(_row(axis, "omega")["kinds_disagree"])
        self.assertEqual(axis["disagreeing_names"], [])
        # ДОСЛОВНО и целиком: сообщение третьего исхода тоже содержит «не
        # расходится» (в кавычках «род нигде не расходится»), и проверка по
        # этой подстроке приняла бы «не измерено» за «измерено и ровно»
        # (ADR-333: проверка по подстроке не годится).
        self.assertIn("РАСХОЖДЕНИЕ ПЛОЩАДОК: ни у одного имени род у разных "
                      "производителей не расходится",
                      "\n".join(census.kind_axis_report(axis)))

    def test_a_missing_site_counter_is_a_third_outcome_not_agreement(self):
        """Счётчика площадок нет ⇒ судить НЕЧЕМ, и это не «не расходится»."""
        real = field_kind.census

        def _without_counters(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 7, "files_unmeasured": {},
                    "fields": {n: {"verdict": field_kind.NOT_DERIVED,
                                   "arithmetic_verdict": field_kind.NOT_ARITH,
                                   "why_unmeasured": ""} for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _without_counters
        try:
            axis = census.kind_axis({"omega": 4}, {"omega": 12}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertIsNone(_row(axis, "omega")["kinds_disagree"])
        self.assertEqual(axis["disagreement_unmeasured"], ["omega"])
        self.assertEqual(axis["disagreeing_names"], [])
        self.assertIn("расхождение площадок нечем судить",
                      "\n".join(census.kind_axis_report(axis)))

    def test_a_name_the_instrument_never_answered_about_does_not_vanish(self):
        """Расхождение свода с признаком обязано быть ВИДНО, а не исчезнуть."""
        real = field_kind.census

        def _forgets_a_name(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 7, "files_unmeasured": {}, "fields": {},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _forgets_a_name
        try:
            axis = census.kind_axis({"omega": 4}, {"omega": 12}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["names"], 1)
        self.assertEqual(len(axis["rows"]), 1)
        self.assertEqual(_row(axis, "omega")["clock_verdict"],
                         field_kind.UNMEASURED)
        self.assertIn("не вернул строку", _row(axis, "omega")["why_unmeasured"])


class TheEnumerationIsClosedAndTheSumIsPrinted(unittest.TestCase):
    """Перечень исходов закрыт: сумма обязана равняться числу кандидатов."""

    def setUp(self):
        self.root = _tree(**{"spa_core/p.py": PRODUCER})
        self.axis = census.kind_axis(
            {"alpha": 1, "beta": 1, "gamma": 1, "delta": 1, "ghost": 1},
            {"alpha": 5, "beta": 4, "gamma": 3, "delta": 2}, self.root)

    def test_both_axes_sum_to_the_number_of_candidates(self):
        for key in ("by_clock_verdict", "by_arithmetic_verdict"):
            self.assertEqual(sum(self.axis[key].values()), self.axis["names"],
                             f"{key}: сумма перечня разошлась с населением")

    def test_the_sum_is_printed_beside_the_enumeration(self):
        text = "\n".join(census.kind_axis_report(self.axis))
        self.assertIn(f"сумма 5 из 5", text)

    def test_an_unexpected_verdict_gets_its_own_key_and_stays_in_the_sum(self):
        """Признак завёл новый исход ⇒ он ВИДЕН, а не растворён в прежних."""
        real = field_kind.census

        def _new_verdict(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 3, "files_unmeasured": {},
                    "fields": {n: {"verdict": "kind_nobody_declared",
                                   "arithmetic_verdict": "arith_nobody_declared",
                                   "wall_clock_count": 0,
                                   "clock_named_read_count": 0,
                                   "not_derived_count": 1,
                                   "why_unmeasured": ""} for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _new_verdict
        try:
            axis = census.kind_axis({"omega": 1}, {"omega": 3}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["by_clock_verdict"]["kind_nobody_declared"], 1)
        self.assertEqual(sum(axis["by_clock_verdict"].values()), 1)
        # И на ВТОРОЙ оси тоже: умолчание счётчика достижимо только у вердикта
        # ВНЕ объявленного перечня, и сцена, звавшая объявленный, оставляла
        # половину проводки непроверенной.
        self.assertEqual(axis["by_arithmetic_verdict"]["arith_nobody_declared"], 1)
        self.assertEqual(sum(axis["by_arithmetic_verdict"].values()), 1)


class OrderOfTheTwoListsIsOneRule(unittest.TestCase):
    """Перечень кандидатов и строки рода укорачиваются ОДНИМ правилом."""

    FREQ = {"alpha": 9, "beta": 1}
    #: `alpha` чаще, `beta` подпирается ДЛИННЕЙШИМ списком. Сила свидетельства —
    #: длина (ADR-410), поэтому голова обоих перечней обязана быть `beta`.
    STRENGTH = {"alpha": 3, "beta": 210}

    def test_the_rows_follow_the_length_order_not_the_frequency(self):
        axis = census.kind_axis(self.FREQ, self.STRENGTH,
                                _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual([r["field"] for r in axis["rows"]], ["beta", "alpha"])

    def test_the_rule_has_exactly_one_copy(self):
        self.assertEqual([n for n, _ in census._ranked_by_length(
            self.FREQ, self.STRENGTH)], ["beta", "alpha"])

    def test_shortening_keeps_the_same_head_as_the_candidate_list(self):
        axis = census.kind_axis(self.FREQ, self.STRENGTH,
                                _tree(**{"spa_core/p.py": PRODUCER}))
        lines = census.kind_axis_report(axis, max_rows=1)
        body = "\n".join(lines)
        self.assertIn("beta×1", body)
        self.assertNotIn("alpha×9", body)
        self.assertIn("ещё 1", body)


class TheFoldInstallsNoGate(unittest.TestCase):
    """Правило «род ⇒ годность» отвергнуто ЗАМЕРОМ — и везётся в документ."""

    def test_the_pin_of_public_names_covers_the_kind_axis_too(self):
        for name in ("kind_gate", "admit_by_kind", "reject_by_kind",
                     "fit_by_kind"):
            self.assertIn(name, census._NO_GATE_NAMES)
        public = {name for name in dir(census) if not name.startswith("_")}
        self.assertEqual(public & set(census._NO_GATE_NAMES), set())

    def test_the_pin_is_pinned_itself_by_its_whole_composition(self):
        """Состав пина — ДОСЛОВНО: иначе из него тихо вынут имя.

        Сосед проверяет пересечение публичных имён с пином, и мутант,
        подменивший ИМЯ ВНУТРИ пина, это пересечение не меняет — запрет
        просто перестаёт существовать, оставаясь на вид целым. Поэтому состав
        сверяется с литералами (тот же приём, что у `list_day_axis`), и ни
        одно имя из него не исчезнет молча.
        """
        self.assertEqual(set(census._NO_GATE_NAMES), {
            "apply_threshold", "chosen_pair", "reject_field", "is_fit",
            "admit_field", "unfit_for_identity", "threshold_gate",
            "kind_gate", "admit_by_kind", "reject_by_kind", "fit_by_kind",
            # Заказ G115 п. 3 (ADR-695): имена гейта по РАЗНИЦЕ знаменателя.
            # Правка пина намеренна и УСИЛИВАЕТ запрет (инв. #16) — тем же
            # порядком, каким его усилил ADR-694 строкой ниже.
            "denominator_gate", "admit_by_denominator",
            "reject_by_denominator", "fit_by_denominator",
            "admit_by_presence", "reject_by_presence",
            # Заказ G114 п. 1 (ADR-694): имена гейта по ЧИСЛУ ЧИТАТЕЛЕЙ.
            # Правка этого пина намеренна и УСИЛИВАЕТ запрет (инв. #16): состав
            # сверяется дословно, поэтому новые запрещённые имена обязаны
            # приехать сюда — иначе пин перестал бы быть полным, а проверка
            # соседа (пересечение с публичными именами) этого не заметила бы:
            # она краснеет только на имени, УЖЕ стоящем в пине.
            "readers_gate", "admit_by_readers", "reject_by_readers",
            "fit_by_readers"})

    def test_the_fold_takes_no_argument_that_would_select_a_kind(self):
        params = set(inspect.signature(census.kind_axis).parameters)
        self.assertEqual(params, {"freq", "strength", "tree_root"})

    def test_it_adds_no_name_to_the_identity_fields(self):
        before = tuple(census.probe.IDENTITY_FIELDS)
        census.kind_axis({"alpha": 1}, {"alpha": 3},
                         _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual(tuple(census.probe.IDENTITY_FIELDS), before)

    def test_the_refusal_travels_into_the_document_and_is_printed(self):
        axis = census.kind_axis({"alpha": 1}, {"alpha": 3},
                                _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual(axis["fitness_rule"]["verdict"], "REFUSED")
        self.assertIn("ГЕЙТА НЕТ", "\n".join(census.kind_axis_report(axis)))

    def test_positive_control_a_missing_refusal_is_said_aloud(self):
        """Вердикта правила нет ⇒ сказано вслух: иначе ось читается гейтом."""
        axis = census.kind_axis({"alpha": 1}, {"alpha": 3},
                                _tree(**{"spa_core/p.py": PRODUCER}))
        axis.pop("fitness_rule")
        text = "\n".join(census.kind_axis_report(axis))
        self.assertIn("ГЕЙТА НЕТ · НЕ ИЗМЕРЕНО", text)


class TheFoldIsWiredIntoTheCensusAndItsReader(unittest.TestCase):
    """Проводка мерится ИСХОДОМ: документ, отчёт, объявленная форма."""

    ROWS = {
        "m.one": {"lists": [{"coord": ".items", "n": 9, "outcome":
                             "unnamed_candidate_outside",
                             "candidates": ["alpha"]}]},
    }

    def test_tally_without_a_tree_refuses_instead_of_inventing_a_kind(self):
        counts = census.tally(self.ROWS)
        self.assertEqual(counts["candidate_kind"]["status"], "UNMEASURED")
        self.assertIn("дерево не названо", counts["candidate_kind"]["reason"])

    def test_tally_with_a_tree_measures_the_kind_of_the_candidate(self):
        counts = census.tally(self.ROWS,
                              tree_root=_tree(**{"spa_core/p.py": PRODUCER}))
        axis = counts["candidate_kind"]
        self.assertEqual(axis["status"], "MEASURED")
        self.assertEqual(_row(axis, "alpha")["clock_verdict"],
                         field_kind.WALL_CLOCK)

    def test_measure_hands_the_tree_to_the_fold(self):
        """Звено `measure → tally → kind_axis` мерится ПРОИЗВЕДЁННЫМ документом.

        Зонд и стенды подменены НАМЕРЕННО: их работа — другой вопрос (и она
        измерена прогоном всего населения в ADR-693). Здесь предмет один —
        доезжает ли ДЕРЕВО до оси рода; порви проброс, и ось скажет «дерево не
        названо» при названном дереве.
        """
        root = _tree(**{"spa_core/p.py": PRODUCER})
        real = (census.population, census.build_stands, census.run_probe)
        census.population = lambda tree: (["m.one"], {"python_branch": 1})
        census.build_stands = lambda data_dir, tmp: ({"s1": str(tmp),
                                                      "day": "-",
                                                      "donor_day": "-"}, "")
        census.run_probe = lambda names, stand, tree_root, moment: (
            {"__modules__": self.ROWS}, "")
        try:
            doc = census.measure(root / "data", root)
        finally:
            (census.population, census.build_stands,
             census.run_probe) = real
        self.assertEqual(doc["counts"]["candidate_kind"]["status"], "MEASURED")
        self.assertGreater(doc["counts"]["candidate_kind"]["files_parsed"], 0)

    def test_the_office_declares_the_section_as_read(self):
        declared = _office()._READ_SCHEMA["list_identity_census.json"]
        self.assertIn("counts.candidate_kind", declared)

    def test_the_office_prints_the_kind_beside_the_candidate(self):
        """ADR-333: проводка проверяется ВЫЗОВОМ на живом документе."""
        office = _office()
        doc = self._doc()
        lines = office._summarize_json(ARTIFACT_REL, doc, root=str(REPO),
                                       artifact_root=str(REPO))
        text = "\n".join(lines)
        # РАЗЛИЧИМОСТЬ сцены, а не только исход (урок #786): «alpha×2» печатает
        # и строка КАНДИДАТА, и строка рода, а «[РОД]» стои́т и в сообщении
        # «СТАРОГО ОБРАЗЦА». Мутант, подменивший КЛЮЧ чтения раздела, обе
        # проверки проходил — поэтому сцена требует того, что печатает ТОЛЬКО
        # измеренный раздел, и прямо отрицает сообщение об отсутствии.
        self.assertIn("[РОД] ось ЧАСОВ:", text)
        self.assertIn("род: wall_clock_derived / not_arithmetic", text)
        self.assertNotIn("СТАРОГО ОБРАЗЦА", text)
        self.assertLess(text.index("[НАХОДКА]"), text.index("[РОД]"),
                        "род напечатан не рядом с кандидатом")
        self.assertFalse(any(l.startswith(office._HOLLOW_MARK) for l in lines))

    def test_a_document_without_the_section_is_called_old_not_empty(self):
        """Обратная сторона: отсутствие раздела — ОБРАЗЕЦ, а не «родов ноль»."""
        office = _office()
        doc = self._doc()
        doc["counts"].pop("candidate_kind")
        lines = office._summarize_json(ARTIFACT_REL, doc, root=str(REPO),
                                       artifact_root=str(REPO))
        # Предмет сцены — РАЗДЕЛ РОДА, поэтому и мерится он, а не «всё, что
        # напечатано после него». Прежняя редакция резала отчёт по метке
        # `[РОД]` и смотрела ХВОСТ — то есть заодно утверждала, что НИ ОДИН
        # сосед ниже не печатает `alpha×2`. Утверждение это ложно и к предмету
        # не относится: ось ЧИТАТЕЛЕЙ (G114 п. 1) печатает имя кандидата со
        # своим числом ровно так же, как ось РОДА, и встала она ниже. Правка
        # СУЖАЕТ сцену до её предмета и потому проверку УСИЛИВАЕТ: раздел рода
        # теперь обязан назвать себя СТАРЫМ ОБРАЗЦОМ сам, а не «где-нибудь в
        # отчёте» (инв. #16 — намеренно, с обоснованием).
        kind = "\n".join(line for line in lines if "[РОД]" in line)
        self.assertIn("СТАРОГО ОБРАЗЦА", kind)
        self.assertNotIn("alpha×2", kind)

    @staticmethod
    def _doc() -> dict:
        axis = census.kind_axis(
            {"alpha": 2}, {"alpha": 11},
            _tree(**{"spa_core/p.py": PRODUCER}))
        # Заказ G114 пп. 1, 2 (ADR-694). Раздел читателей добавлен в фикстуру
        # по тому же правилу, что и раздел дня до него: шаг 0-офис сверяет
        # mtime ПРОИЗВОДИТЕЛЯ с датой отчёта и на документе без объявленного
        # раздела печатает «отчёт СТАРОГО ОБРАЗЦА» — верно, но предмет ЭТОЙ
        # сцены (род рядом с кандидатом) тогда заслоняется чужим сообщением.
        # Значение считает НАСТОЯЩАЯ ось, а не словарь из головы: фикстура
        # остаётся произведённым документом.
        readers = census.reader_axis(
            {"alpha": 2}, {"alpha": 11},
            {"alpha": {"readers": ["m.one"], "nameless": 0}},
            census.threshold_grid({"alpha": 2}, {"alpha": 11}))
        # Заказ G115 п. 3 (ADR-695). Раздел разницы добавлен в фикстуру по тому
        # же правилу и ровно по той же причине, что раздел читателей над ним:
        # шаг 0-офис сверяет mtime ПРОИЗВОДИТЕЛЯ с датой отчёта и на документе
        # без объявленного раздела печатает «отчёт СТАРОГО ОБРАЗЦА» — верно, но
        # предмет ЭТОЙ сцены (род рядом с кандидатом) тогда заслоняется чужим
        # сообщением, и `assertNotIn("СТАРОГО ОБРАЗЦА")` краснеет не о роде. Ни
        # одно утверждение сцены не ослаблено: добавлено ЗНАЧЕНИЕ, посчитанное
        # НАСТОЯЩИМ прибором, а не словарь из головы.
        denominator = cand_denom.tally(
            [{"outcome": "unnamed_candidate_outside", "n": 9, "module": "m.one",
              "coord": ".items", cand_denom.COMPOSITION_KEY: {"alpha": ""}}],
            {"alpha": 2})
        return {
            "schema": census.SCHEMA, "status": "FINDING",
            # Отметка и раздел дня — чтобы тревога о ФОРМЕ не заслоняла предмет
            # сцены своим «возраст НЕ ИЗМЕРЕН»: предмет здесь род, а не возраст.
            # Отметка ОТНОСИТЕЛЬНАЯ (`_freshness.ts`): литеральная дата здесь
            # была бы бомбой замедленного действия — она выпала бы из окна
            # свежести от хода календаря, а не от кода, и храповик замороженных
            # дат верно покраснел на ней в широком прогоне этого же цикла.
            # Часы инъектировать некуда: отметку читает чужой шаг 0-офис.
            "generated_at": ts(hours_ago=1),
            "reason": "списков без личности с годным полем ВНЕ списка имён: 1",
            "advisory": "прибор только ЧИТАЕТ",
            "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                           "entry": "spa_core/monitoring/findings_bridge.py",
                           "inside_tree": True, "doors_agree": True,
                           "read_by": "sys.modules['__main__'].__file__"},
            "counts": {
                "lists_total": 3, "outcomes": {"unnamed_candidate_outside": 1},
                "singletons": 0, "scalar_lists_multi": 0,
                "denominator_of_finding": 1,
                "candidate_fields_outside": {"alpha": 2},
                "candidate_field_strength": {"alpha": 11},
                "finding_rows": [{"module": "m.one", "coord": ".items",
                                  "n": 9, "candidates": ["alpha"]}],
                "truncated_readers": [], "unmeasured_causes": {},
                "readers_measured": 1, "named_fields": {},
                "day_axis": {"lists_seen": 1, "answered_yes": 0,
                             "denominator_of_finding": 1, "outcomes": {},
                             "axis_fields": {}, "axis_field_readers": {},
                             "axis_field_strength": {}, "refusal_reasons": {},
                             "unmeasured_causes": {}, "series_rows": []},
                "candidate_kind": copy.deepcopy(axis),
                "candidate_reader_axis": copy.deepcopy(readers),
                "candidate_denominator": copy.deepcopy(denominator),
            },
        }


class TheContractOfTheDocumentIsPinnedVerbatim(unittest.TestCase):
    """Имена ключей и значения исходов пришпилены ДОСЛОВНО (урок #832).

    Сверка документа САМ С СОБОЙ (``row["clock_verdict"] == axis.KEY``)
    переживает переименование ключа: сравниваются две мутировавшие вместе
    половины. Поэтому состав ключей здесь — литералы, и мутант, подменивший
    имя, краснеет.
    """

    AXIS_KEYS = {"status", "names", "files_parsed", "files_unmeasured",
                 "by_clock_verdict", "by_arithmetic_verdict",
                 "clock_unmeasured_causes", "disagreeing_names",
                 "disagreement_unmeasured", "rows", "fitness_rule",
                 "what_it_does_not_prove"}
    ROW_KEYS = {"field", "population", "max_length", "max_length_unmeasured",
                "clock_verdict", "arithmetic_verdict", "producer_sites",
                "kinds_disagree", "why_unmeasured"}

    def setUp(self):
        self.axis = census.kind_axis({"alpha": 2}, {"alpha": 11},
                                     _tree(**{"spa_core/p.py": PRODUCER}))

    def test_the_axis_carries_exactly_these_keys(self):
        self.assertEqual(set(self.axis), self.AXIS_KEYS)

    def test_a_row_carries_exactly_these_keys(self):
        self.assertEqual(set(self.axis["rows"][0]), self.ROW_KEYS)

    def test_the_site_counters_are_named_by_the_verdicts_themselves(self):
        self.assertEqual(set(self.axis["rows"][0]["producer_sites"]),
                         {"wall_clock_derived", "clock_named_read",
                          "not_derived"})

    def test_both_enumerations_carry_exactly_the_declared_outcomes(self):
        self.assertEqual(set(self.axis["by_clock_verdict"]),
                         {"not_derived", "wall_clock_derived",
                          "clock_named_read", "unmeasured"})
        self.assertEqual(set(self.axis["by_arithmetic_verdict"]),
                         {"not_arithmetic", "arithmetic_derived",
                          "arithmetic_formatted", "unmeasured"})

    def test_the_one_sidedness_is_carried_as_three_named_items(self):
        said = self.axis["what_it_does_not_prove"]
        self.assertEqual(len(said), 3)
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in said))

    def test_the_counts_key_of_the_census_is_named_candidate_kind(self):
        counts = census.tally({"m.one": {"lists": []}})
        self.assertIn("candidate_kind", counts)


class TheReportLinesAreTheClaimNotTheirDecoration(unittest.TestCase):
    """Строки отчёта пришпилены ЦЕЛИКОМ там, где они и есть утверждение."""

    def setUp(self):
        self.axis = census.kind_axis({"alpha": 2}, {"alpha": 11},
                                     _tree(**{"spa_core/p.py": PRODUCER}))
        self.text = "\n".join(census.kind_axis_report(self.axis))

    def test_the_header_prints_all_three_of_its_numbers(self):
        self.assertIn("кандидатов, у которых спрошен род: 1 · файлов дерева "
                      "разобрано 1, не разобрано 0", self.text)

    def test_each_axis_prints_its_enumeration_and_its_sum(self):
        self.assertIn("ось ЧАСОВ: clock_named_read: 0 · not_derived: 0 · "
                      "unmeasured: 0 · wall_clock_derived: 1 "
                      "(перечень закрыт, сумма 1 из 1)", self.text)
        self.assertIn("ось АРИФМЕТИКИ: arithmetic_derived: 0 · "
                      "arithmetic_formatted: 0 · not_arithmetic: 1 · "
                      "unmeasured: 0 (перечень закрыт, сумма 1 из 1)",
                      self.text)

    def test_the_row_prints_the_triple_in_one_line(self):
        self.assertIn("   alpha×2 (макс. длина 11, род: wall_clock_derived / "
                      "not_arithmetic)", self.text)

    def test_the_refusal_line_names_the_verdict_and_the_reason(self):
        self.assertIn("ГЕЙТА НЕТ: правило «род ⇒ годность» — REFUSED (", self.text)
        self.assertIn(census.field_kind.FITNESS_RULE["why"], self.text)

    def test_the_unmeasured_axis_prints_its_own_reason(self):
        axis = census.kind_axis({"alpha": 1}, {"alpha": 3})
        self.assertEqual(census.kind_axis_report(axis),
                         [f"НЕ ИЗМЕРЕНО: {axis['reason']}"])

    def test_a_disagreeing_name_is_printed_with_its_count_and_names(self):
        two = {"spa_core/a.py": ('import datetime as dt\n\n\n'
                                 'def a():\n'
                                 '    return {"omega": dt.datetime.now().isoformat()}\n'),
               "spa_core/b.py": ('def b(record):\n'
                                 '    return {"omega": record["omega"]}\n')}
        axis = census.kind_axis({"omega": 4}, {"omega": 12}, _tree(**two))
        self.assertIn("РАСХОЖДЕНИЕ ПЛОЩАДОК: у 1 имён род РАЗНЫЙ у разных "
                      "производителей (omega) — ярлык имени выбран старшинством "
                      "и это скрывает", "\n".join(census.kind_axis_report(axis)))


class AnUnreadableFileIsCountedNotSwallowed(unittest.TestCase):
    """Файл, который признак не разобрал, обязан быть ЧИСЛОМ в документе."""

    #: Синтаксически битый производитель. Это не выдумка стенда: признак сам
    #: отвечает на такой файл причиной, и свод обязан эту причину СОСЧИТАТЬ.
    BROKEN = "def broken(:\n    return {'alpha': 1}\n"

    def test_the_number_of_unparsed_files_reaches_the_document(self):
        axis = census.kind_axis(
            {"alpha": 2}, {"alpha": 11},
            _tree(**{"spa_core/p.py": PRODUCER, "spa_core/bad.py": self.BROKEN}))
        self.assertEqual(axis["files_parsed"], 1)
        self.assertEqual(axis["files_unmeasured"], 1)
        self.assertIn("разобрано 1, не разобрано 1",
                      "\n".join(census.kind_axis_report(axis)))

    def test_positive_control_a_whole_tree_counts_zero_unparsed(self):
        axis = census.kind_axis({"alpha": 2}, {"alpha": 11},
                                _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual(axis["files_unmeasured"], 0)

    def test_an_unparsed_file_is_counted_even_when_nothing_was_parsed(self):
        """Третий исход «дерево не разобрано» тоже везёт своё число."""
        axis = census.kind_axis({"alpha": 2}, {"alpha": 11},
                                _tree(**{"spa_core/bad.py": self.BROKEN}))
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertEqual(axis["files_unmeasured"], 1)

    def test_an_instrument_that_never_says_how_many_files_it_read(self):
        """Признак не назвал числа разобранных файлов ⇒ свод ОТКАЗЫВАЕТ."""
        real = field_kind.census

        def _mute(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_unmeasured": {}, "fields": {}, "fitness_rule": {}}

        field_kind.census = _mute
        try:
            axis = census.kind_axis({"alpha": 1}, {"alpha": 3}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertEqual(axis["reason"],
                         "признак рода не сказал, сколько файлов разобрал — "
                         "судить о родах по такому ответу нельзя")


class PartlyMissingCountersAreNotAgreement(unittest.TestCase):
    """ОДНОГО потерянного счётчика достаточно, чтобы судить было нечем.

    Сцена с ТРЕМЯ потерянными счётчиками не различает «хоть один» и «все» —
    ровно на этом выжил мутант ``any → all``. Здесь потерян ОДИН из трёх.
    """

    @staticmethod
    def _with(counters: dict):
        def _stub(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 5, "files_unmeasured": {},
                    "fields": {n: dict(counters,
                                       verdict=field_kind.WALL_CLOCK,
                                       arithmetic_verdict=field_kind.NOT_ARITH,
                                       why_unmeasured="") for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}
        return _stub

    def _axis(self, counters: dict) -> dict:
        real = field_kind.census
        field_kind.census = self._with(counters)
        try:
            return census.kind_axis({"omega": 2}, {"omega": 5}, Path("/tmp"))
        finally:
            field_kind.census = real

    def test_one_missing_counter_out_of_three_is_already_unmeasured(self):
        axis = self._axis({"wall_clock_count": 1, "clock_named_read_count": 2})
        self.assertIsNone(_row(axis, "omega")["kinds_disagree"])
        self.assertEqual(axis["disagreement_unmeasured"], ["omega"])

    def test_positive_control_all_three_present_is_judged(self):
        axis = self._axis({"wall_clock_count": 1, "clock_named_read_count": 2,
                           "not_derived_count": 0})
        self.assertTrue(_row(axis, "omega")["kinds_disagree"])
        self.assertEqual(axis["disagreement_unmeasured"], [])


class TheOrderRuleIsMeasuredOnEveryOneOfItsKeys(unittest.TestCase):
    """У правила порядка ТРИ ключа, и каждый мерится своей сценой."""

    def test_an_unmeasured_length_sinks_below_every_measured_one(self):
        # Первый ключ правила: «длина не измерена» — отдельная группа в хвосте,
        # а не слабейшая из измеренных.
        self.assertEqual(
            [n for n, _ in census._ranked_by_length(
                {"short": 1, "none": 9}, {"short": 2})],
            ["short", "none"])

    def test_within_one_length_the_population_decides(self):
        self.assertEqual(
            [n for n, _ in census._ranked_by_length(
                {"rare": 1, "often": 9}, {"rare": 7, "often": 7})],
            ["often", "rare"])

    def test_within_one_coordinate_the_name_decides_and_nothing_is_dropped(self):
        self.assertEqual(
            [n for n, _ in census._ranked_by_length(
                {"b": 3, "a": 3}, {"a": 4, "b": 4})], ["a", "b"])

    def test_a_measured_zero_length_is_not_an_unmeasured_one(self):
        """Инв. #17 у самого правила порядка: 0 измеренный ≠ длины нет.

        Сцена не выдумана, а ровно та, на которой первый ключ правила и
        становится наблюдаемым: при НЕНУЛЕВОЙ длине второй ключ (`-length`)
        отрицателен и порядок держит сам, поэтому мутант, стёрший флаг, на
        обычном населении эквивалентен. Измеренный ноль — единственное место,
        где флаг делает работу, и инвариант требует именно его различать.
        """
        self.assertEqual(
            [n for n, _ in census._ranked_by_length(
                {"zero": 1, "none": 1}, {"zero": 0})],
            ["zero", "none"])

    def test_two_unmeasured_names_keep_their_own_order_and_stay(self):
        self.assertEqual(
            [n for n, _ in census._ranked_by_length({"y": 1, "x": 1}, {})],
            ["x", "y"])

    def test_the_rows_of_the_axis_follow_the_same_three_keys(self):
        axis = census.kind_axis({"short": 1, "none": 9}, {"short": 2},
                                _tree(**{"spa_core/p.py": PRODUCER}))
        self.assertEqual([r["field"] for r in axis["rows"]], ["short", "none"])


class ThirdOutcomeMessagesOfTheReportArePinnedVerbatim(unittest.TestCase):
    """Сообщения третьих исходов — ДОСЛОВНО (урок #819).

    Проверка по слову приняла бы любую переписанную причину, а причина тут и
    есть весь ответ: она отличает «не измерено» от «измерено и ноль».
    """

    def setUp(self):
        self.axis = census.kind_axis({"alpha": 2}, {"alpha": 11},
                                     _tree(**{"spa_core/p.py": PRODUCER}))

    def test_rows_missing_from_a_measured_axis(self):
        axis = dict(self.axis)
        axis.pop("rows")
        self.assertIn("НЕ ИЗМЕРЕНО: перечня строк у оси нет вовсе, а кандидаты "
                      "есть — это не «родов ноль»",
                      census.kind_axis_report(axis))

    def test_the_list_of_disagreeing_names_missing_altogether(self):
        axis = dict(self.axis)
        axis.pop("disagreeing_names")
        self.assertIn("НЕ ИЗМЕРЕНО: перечня имён с расхождением площадок нет "
                      "вовсе — это не «род нигде не расходится»",
                      census.kind_axis_report(axis))

    def test_a_row_whose_disagreement_is_unmeasured_says_so_in_its_line(self):
        axis = copy.deepcopy(self.axis)
        axis["rows"][0]["kinds_disagree"] = None
        line = next(l for l in census.kind_axis_report(axis)
                    if l.startswith("   alpha"))
        self.assertTrue(line.endswith(" · расхождение площадок НЕ ИЗМЕРЕНО"),
                        f"строка ряда не называет третий исход: {line}")

    def test_the_number_of_unparsed_files_missing_altogether(self):
        """Инв. #17 у ЧИСЛА: перечня неразобранных нет ⇒ не «разобрано всё».

        Храповик класса (`test_absent_observation_ratchet`) верно покраснел на
        первой редакции этих строк: `… or {}` печатал «не разобрано 0» на
        ответе, который об этом не сказал ни слова. Чинён ПИСАТЕЛЬ, в базу
        храповика не дописано ничего.
        """
        real = field_kind.census

        def _no_list(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 9,
                    "fields": {n: {"verdict": field_kind.NOT_DERIVED,
                                   "arithmetic_verdict": field_kind.NOT_ARITH,
                                   "wall_clock_count": 0,
                                   "clock_named_read_count": 0,
                                   "not_derived_count": 1,
                                   "why_unmeasured": ""} for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _no_list
        try:
            axis = census.kind_axis({"omega": 1}, {"omega": 3}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertIsNone(axis["files_unmeasured"])
        self.assertIn("файлов дерева разобрано 9, не разобрано НЕ ИЗМЕРЕНО",
                      "\n".join(census.kind_axis_report(axis)))

    def test_the_list_of_blind_names_missing_altogether(self):
        axis = dict(self.axis)
        axis.pop("disagreement_unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНО: перечня имён, у которых расхождение "
                      "площадок нечем судить, в документе нет вовсе — это не "
                      "«таких имён ноль»", census.kind_axis_report(axis))

    def test_the_list_of_unmeasured_causes_missing_altogether(self):
        axis = dict(self.axis)
        axis.pop("clock_unmeasured_causes")
        self.assertIn("НЕ ИЗМЕРЕНО: перечня причин у имён без измеренного рода "
                      "в документе нет — их отсутствие не есть «род измерен у "
                      "всех»", census.kind_axis_report(axis))

    def test_an_unmeasured_cause_without_a_reason_is_still_named(self):
        """Признак сказал «не измерено» и не назвал причину ⇒ она НАЗВАНА нами.

        Защитный хвост `or "причина не названа"` достижим только отсюда, и без
        этой сцены безымянная причина уходила бы в документ пустой строкой —
        то есть «не измерено» без причины, что инв. #17 и запрещает.
        """
        real = field_kind.census

        def _mute_reason(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 3, "files_unmeasured": {},
                    "fields": {n: {"verdict": field_kind.UNMEASURED,
                                   "arithmetic_verdict": field_kind.UNMEASURED,
                                   "wall_clock_count": 0,
                                   "clock_named_read_count": 0,
                                   "not_derived_count": 0,
                                   "why_unmeasured": ""} for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _mute_reason
        try:
            axis = census.kind_axis({"omega": 1}, {"omega": 3}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["clock_unmeasured_causes"],
                         {"причина не названа": 1})
        self.assertIn("НЕ ИЗМЕРЕНО: причина не названа: 1 имён(и)",
                      census.kind_axis_report(axis))


class TwoNamesAreNeededToSeeASeparator(unittest.TestCase):
    """Перечень из ОДНОГО имени разделителя не печатает — и не проверяет.

    Сцена с одним именем прошла бы при любом разделителе, включая стёртый:
    склейка перечня тогда отвечала бы на свой вопрос мимо нужного.
    """

    TWO_DISAGREEING = {
        "spa_core/a.py": ('import datetime as dt\n\n\n'
                          'def a():\n'
                          '    return {"omega": dt.datetime.now().isoformat(),\n'
                          '            "sigma": dt.datetime.now().isoformat()}\n'),
        "spa_core/b.py": ('def b(record):\n'
                          '    return {"omega": record["omega"],\n'
                          '            "sigma": record["sigma"]}\n'),
    }

    def test_two_disagreeing_names_are_joined_by_the_separator(self):
        axis = census.kind_axis({"omega": 4, "sigma": 4},
                                {"omega": 12, "sigma": 11},
                                _tree(**self.TWO_DISAGREEING))
        self.assertEqual(axis["disagreeing_names"], ["omega", "sigma"])
        self.assertIn("РАСХОЖДЕНИЕ ПЛОЩАДОК: у 2 имён род РАЗНЫЙ у разных "
                      "производителей (omega, sigma) — ярлык имени выбран "
                      "старшинством и это скрывает",
                      "\n".join(census.kind_axis_report(axis)))

    def test_two_blind_names_are_joined_by_the_separator_too(self):
        real = field_kind.census

        def _no_counters(names, tree_root, roots=field_kind.DEFAULT_ROOTS):
            return {"files_parsed": 4, "files_unmeasured": {},
                    "fields": {n: {"verdict": field_kind.NOT_DERIVED,
                                   "arithmetic_verdict": field_kind.NOT_ARITH,
                                   "why_unmeasured": ""} for n in names},
                    "fitness_rule": {"verdict": "REFUSED", "why": "-"}}

        field_kind.census = _no_counters
        try:
            axis = census.kind_axis({"omega": 2, "sigma": 2},
                                    {"omega": 9, "sigma": 8}, Path("/tmp"))
        finally:
            field_kind.census = real
        self.assertEqual(axis["disagreement_unmeasured"], ["omega", "sigma"])
        self.assertIn("НЕ ИЗМЕРЕНО: расхождение площадок нечем судить у 2 имён "
                      "(omega, sigma) — счётчика площадок признак не дал",
                      "\n".join(census.kind_axis_report(axis)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
