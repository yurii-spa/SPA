#!/usr/bin/env python3
"""Контроли переписи причин провала (заказ G108 п. 1, ADR-675).

Каждая проверка здесь — обратная сторона НАЗВАННОГО звена: порвав звено, прибор
обязан покраснеть, а не ответить числом. Положительный контроль у набора один и
настоящий: форма записи воспроизводит прогон **5853** (08.10.2026), где у ноги 3.12
`junit-spa_core.xml` есть и несёт 80 провалов фазы `call` плюс 19 `<error>` с
литеральным префиксом `failed on setup with`, а у ноги 3.11 того же прогона записи
нет ВОВСЕ — одна команда, два разных исхода.

Время, номера процессов и git-окружение в предмет не входят: прибор читает XML и
JSONL из `tmp_path`, собственных часов у него нет.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import failure_cause_census as fcc


def junit(cases: list[str], *, suite_attrs: str = "") -> str:
    body = "\n".join(cases)
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<testsuites><testsuite name="pytest" {suite_attrs}>\n{body}\n'
            f'</testsuite></testsuites>\n')


def case(classname: str, name: str, *, tag: str | None = None,
         message: str = "", text: str = "") -> str:
    if tag is None:
        return f'<testcase classname="{classname}" name="{name}" time="0.1"/>'
    safe_msg = (message.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f'<testcase classname="{classname}" name="{name}" time="0.1">'
            f'<{tag} message="{safe_msg}">{safe_text}</{tag}></testcase>')


# Кадры в форме, которую печатает `--tb=short`: «путь:строка: in имя».
REPO_TB = ("spa_core/tests/test_x.py:111: in test_one\n"
           "    self.assertEqual(a, b)\n"
           "E   AssertionError: 'a' != 'b'\n")
DEEP_TB = ("spa_core/tests/test_x.py:270: in _run_step\n"
           "    p = subprocess.run(\n"
           "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/subprocess.py:550: in run\n"
           "    stdout, stderr = process.communicate(input, timeout=timeout)\n"
           "E   Failed: Timeout (>180.0s) from pytest-timeout.\n")
FOREIGN_ONLY_TB = ("/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/subprocess.py:550: in run\n"
                   "E   Failed: Timeout (>180.0s) from pytest-timeout.\n")


class TempTree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path


class PhaseIsReadAndIsNotGuessed(TempTree):
    """Фаза: `<failure>` = call, у `<error>` — литеральный префикс писателя junit."""

    def test_failure_element_is_the_call_phase(self):
        path = self.write("j.xml", junit([
            case("spa_core.tests.test_x", "test_one", tag="failure",
                 message="AssertionError: 'a' != 'b'", text=REPO_TB)]))
        census = fcc.census_from_path(path)
        self.assertEqual(census.by_phase()[fcc.PHASE_CALL], 1)

    def test_the_three_literal_prefixes_of_the_junit_writer(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="error",
                 message='failed on setup with "Failed: Timeout (>180.0s) from pytest-timeout."'),
            case("m", "b", tag="error", message='failed on teardown with "OSError"'),
            case("m", "c", tag="error", message="collection failure"),
        ]))
        phase = fcc.census_from_path(path).by_phase()
        self.assertEqual(phase[fcc.PHASE_SETUP], 1)
        self.assertEqual(phase[fcc.PHASE_TEARDOWN], 1)
        self.assertEqual(phase[fcc.PHASE_COLLECT], 1)

    def test_an_unknown_error_prefix_is_NAMED_not_guessed(self):
        """Порванное звено: префикс не узнан. Догадка здесь была бы хуже молчания."""
        path = self.write("j.xml", junit([
            case("m", "a", tag="error", message="что-то совершенно иное")]))
        phase = fcc.census_from_path(path).by_phase()
        self.assertEqual(phase[fcc.PHASE_UNNAMED], 1)
        self.assertEqual(phase[fcc.PHASE_SETUP], 0)
        self.assertEqual(phase[fcc.PHASE_CALL], 0)


class CauseAndSiteAreClosedSets(TempTree):
    """Два закрытых набора, и сумма каждого равна населению (инв. #17)."""

    def census(self):
        path = self.write("j.xml", junit([
            case("m", "named", tag="failure",
                 message="AssertionError: 'a' != 'b'", text=REPO_TB),
            case("m", "untyped", tag="failure",
                 message="StopIteration", text=REPO_TB),
            case("m", "empty", tag="failure", message="", text=REPO_TB),
            case("m", "foreign", tag="failure",
                 message="Failed: Timeout (>180.0s) from pytest-timeout.",
                 text=FOREIGN_ONLY_TB),
            case("m", "frameless", tag="failure",
                 message="AssertionError: nothing", text="нет ни одного кадра"),
        ]))
        return fcc.census_from_path(path)

    def test_cause_classes_sum_to_the_population(self):
        census = self.census()
        self.assertEqual(sum(census.by_cause_class().values()), census.population)
        self.assertEqual(census.by_cause_class()[fcc.CAUSE_NO_MESSAGE], 1)
        self.assertEqual(census.by_cause_class()[fcc.CAUSE_NO_TYPE], 1)

    def test_site_classes_sum_to_the_population(self):
        census = self.census()
        self.assertEqual(sum(census.by_site_class().values()), census.population)
        self.assertEqual(census.by_site_class()[fcc.SITE_FOREIGN], 1)
        self.assertEqual(census.by_site_class()[fcc.SITE_NONE], 1)

    def test_all_three_identities_hold(self):
        self.assertTrue(self.census().identities_hold())

    def test_the_deepest_REPO_frame_is_the_site_not_the_deepest_frame(self):
        """Порванное звено: место взято у чужого кадра.

        У провала по таймауту глубочайший кадр лежит в `subprocess.py`
        интерпретатора. Назвать местом ЕГО значило бы свести пять разных клиньев
        к одной причине «stdlib» — дефект был бы потерян.
        """
        path = self.write("j.xml", junit([
            case("m", "t", tag="failure",
                 message="Failed: Timeout (>180.0s) from pytest-timeout.", text=DEEP_TB)]))
        failure = fcc.census_from_path(path).failures[0]
        self.assertEqual(failure.site, "spa_core/tests/test_x.py:270")
        self.assertEqual(failure.foreign_frames, 1)


class ForkEdgesAreMeasuredNotDeclared(TempTree):
    """Вилка: слияние занижает, дробление завышает — оба края считаются."""

    def test_the_coarse_key_merges_what_the_exact_key_splits(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "b", tag="failure", message="KeyError: 'verdict'", text=REPO_TB),
        ]))
        fork = fcc.fork_of(fcc.census_from_path(path).call)
        self.assertEqual(fork.cause_groups, 2)     # точный ключ различает имя ключа
        self.assertEqual(fork.coarse_groups, 1)    # грубый — стирает его
        self.assertEqual(fork.lower, 1)            # нижний край слит
        self.assertEqual(fork.upper, 2)            # верхний — различает место

    def test_identical_cause_at_identical_site_is_one_on_BOTH_edges(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "b", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
        ]))
        fork = fcc.fork_of(fcc.census_from_path(path).call)
        self.assertEqual((fork.population, fork.lower, fork.upper), (2, 1, 1))

    def test_a_shared_NAMED_TRACE_merges_two_different_causes(self):
        """Ровно пара прогона 5853: проба и храповик инв. #17 называют одно место."""
        trace = "spa_core/monitoring/reachability_of_the_rest.py:664"
        path = self.write("j.xml", junit([
            case("m", "probe", tag="failure",
                 message=f"AssertionError: 'not_satisfied' != 'satisfied' : новых мест 3: {trace}:ad75c5b8#0",
                 text=REPO_TB),
            case("m", "ratchet", tag="failure",
                 message=f"AssertionError: сигнал or_falsy: НОВЫЕ места класса (3): ['{trace}:ad75c5b8#0']",
                 text=REPO_TB),
        ]))
        fork = fcc.fork_of(fcc.census_from_path(path).call)
        self.assertEqual(fork.cause_groups, 2)
        self.assertEqual(fork.lower, 1)
        self.assertEqual(fork.merged_by_evidence, 1)

    def test_the_trace_edge_does_NOT_come_from_the_frames(self):
        """Порванное звено: след читается из тела элемента, а не из сообщения.

        Кадры несут путь САМОГО теста, и у двух провалов одного файла он общий. Если
        ребро ставить по кадрам, граф склеит всё, что упало в одном файле, и нижний
        край вилки станет единицей на любом наборе — то есть перестанет быть замером.
        """
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "b", tag="failure", message="ValueError: иное", text=REPO_TB),
        ]))
        fork = fcc.fork_of(fcc.census_from_path(path).call)
        self.assertEqual(fork.lower, 2)
        self.assertEqual(fork.merged_by_evidence, 0)

    def test_the_fork_is_computed_over_the_call_phase_only(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "s", tag="error",
                 message='failed on setup with "Failed: Timeout (>180.0s) from pytest-timeout."',
                 text=REPO_TB),
        ]))
        census = fcc.census_from_path(path)
        self.assertEqual(census.population, 2)
        self.assertEqual(fcc.fork_of(census.call).population, 1)


class ThreeOutcomesOfReadingTheRecord(TempTree):
    """Записи нет — это САМ ОТВЕТ, а не ноль провалов (ADR-474, инв. #17)."""

    def test_absent_record_is_NOT_MEASURED_and_says_so(self):
        census = fcc.census_from_path(self.root / "нет-такого.xml")
        self.assertEqual(census.read, fcc.READ_ABSENT)
        self.assertFalse(census.measured)
        text = fcc.format_census(census)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("провалов 0", text)

    def test_unparsable_record_is_NOT_MEASURED(self):
        path = self.write("j.xml", "<testsuite><этонезакрыто")
        self.assertEqual(fcc.census_from_path(path).read, fcc.READ_UNREADABLE)

    def test_a_record_without_a_testsuite_is_NOT_MEASURED(self):
        path = self.write("j.xml", '<?xml version="1.0"?><nothing/>')
        self.assertEqual(fcc.census_from_path(path).read, fcc.READ_NO_SUITE)

    def test_zero_collected_cases_is_NOT_MEASURED_not_clean(self):
        """Пустой набор проходит любую проверку на провалы — это fail-OPEN."""
        path = self.write("j.xml", junit([]))
        self.assertEqual(fcc.census_from_path(path).read, fcc.READ_NO_CASES)

    def test_cases_without_failures_IS_measured_and_equals_zero(self):
        path = self.write("j.xml", junit([case("m", "ok1"), case("m", "ok2")]))
        census = fcc.census_from_path(path)
        self.assertTrue(census.measured)
        self.assertEqual(census.population, 0)
        self.assertIn("измерено и равно нулю", fcc.format_census(census))


class StreamIsTheSecondMACHINEDoorToThePhase(TempTree):
    """Префикс прозы проверяется машинным полем `w`, а не принимается на веру."""

    def stream(self, rows: list[dict]) -> Path:
        path = self.root / "stream.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
        return path

    def test_agreement_is_counted(self):
        junit_path = self.write("j.xml", junit([
            case("spa_core.tests.test_x.Klass", "test_one", tag="failure",
                 message="KeyError: 'identity'", text=REPO_TB)]))
        stream = self.stream([{"e": "fail", "w": "call",
                               "n": "spa_core/tests/test_x.py::Klass::test_one"}])
        census = fcc.census_from_path(junit_path, stream=stream)
        self.assertEqual((census.stream_agreed, census.stream_disagreed,
                          census.stream_absent_for), (1, 0, 0))

    def test_a_DISAGREEMENT_is_counted_and_not_silently_overwritten(self):
        """Порванное звено: две двери к фазе отвечают по-разному.

        Прибор обязан НАЗВАТЬ расхождение. Молча предпочесть одну дверь значило бы
        вернуть прозе последнее слово — то, против чего сверка и заведена.
        """
        junit_path = self.write("j.xml", junit([
            case("spa_core.tests.test_x", "test_one", tag="failure",
                 message="KeyError: 'identity'", text=REPO_TB)]))
        stream = self.stream([{"e": "fail", "w": "teardown",
                               "n": "spa_core/tests/test_x.py::test_one"}])
        census = fcc.census_from_path(junit_path, stream=stream)
        self.assertEqual(census.stream_disagreed, 1)
        self.assertEqual(census.by_phase()[fcc.PHASE_CALL], 1)
        self.assertIn("расхождение 1", fcc.format_census(census))

    def test_an_absent_stream_is_NOT_MEASURED_for_the_crosscheck_only(self):
        junit_path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'x'", text=REPO_TB)]))
        census = fcc.census_from_path(junit_path, stream=self.root / "нет.jsonl")
        self.assertTrue(census.measured)                     # перепись цела
        self.assertEqual(census.stream_read, fcc.READ_ABSENT)
        self.assertIn("НЕ ИЗМЕРЕНА", fcc.format_census(census))

    def test_the_name_is_converted_or_the_crosscheck_empties_in_silence(self):
        """Порванное звено: имя потоковой записи не приведено к паре junit.

        Без приведения у КАЖДОГО провала вышло бы «в потоковой записи нет», и
        сверка молча опустела бы при зелёном виде.
        """
        self.assertEqual(fcc._junit_name("spa_core/tests/test_x.py::Klass::test_one"),
                         "spa_core.tests.test_x.Klass::test_one")
        self.assertEqual(fcc._junit_name("spa_core/tests/test_x.py::test_one"),
                         "spa_core.tests.test_x::test_one")


class SkeletonKeepsTheHeadAndDropsTheDiff(unittest.TestCase):
    def test_only_the_first_line_feeds_the_skeleton(self):
        message = ("AssertionError: 'a' != 'b'\n- a\n? -\n+ b\n"
                   " : подробное сравнение, своё у каждого случая")
        self.assertEqual(fcc.skeleton_of(message), "'a' != 'b'")

    def test_numbers_paths_and_hashes_are_a_kind_not_a_value(self):
        skeleton = fcc.skeleton_of(
            "AssertionError: 125 != 124 в spa_core/x.py при ad75c5b822d6")
        self.assertIn("#", skeleton)
        self.assertIn("<путь>", skeleton)
        self.assertIn("<hash>", skeleton)

    def test_the_exception_type_is_read_off_the_head(self):
        self.assertEqual(fcc.kind_of("KeyError: 'identity'"), "KeyError")
        self.assertEqual(
            fcc.kind_of("spa_core.owner_queue.queue.LifecycleRefused: нет"),
            "spa_core.owner_queue.queue.LifecycleRefused")
        self.assertIsNone(fcc.kind_of("StopIteration"))
        self.assertIsNone(fcc.kind_of(""))

    def test_the_trace_token_needs_a_line_number(self):
        """Имя файла без строки следом не считается: оно склеило бы весь модуль."""
        self.assertEqual(fcc.evidence_of("упало в spa_core/x.py"), frozenset())
        self.assertEqual(fcc.evidence_of("упало в spa_core/x.py:664"),
                         frozenset({"spa_core/x.py:664"}))


class ExitCodeOfTheCLI(TempTree):
    def test_measured_record_returns_zero(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'x'", text=REPO_TB)]))
        self.assertEqual(fcc.main([str(path)]), 0)

    def test_one_absent_record_among_good_ones_returns_two(self):
        """«Часть измерена» не есть «измерено»: код возврата обязан это нести."""
        good = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'x'", text=REPO_TB)]))
        self.assertEqual(fcc.main([str(good), str(self.root / "нет.xml")]), 2)

    def test_json_payload_carries_both_edges_of_the_fork(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "b", tag="failure", message="KeyError: 'verdict'", text=REPO_TB)]))
        payload = fcc.as_json(fcc.census_from_path(path))
        self.assertEqual(payload["call"]["defects_not_less_than"], 1)
        self.assertEqual(payload["call"]["defects_not_more_than"], 2)
        self.assertTrue(payload["identities_hold"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TheIdentityIsFalsifiable(unittest.TestCase):
    """Контроль на само тождество: род вне объявленного перечня обязан КРАСНИТЬ.

    Порванное звено: сумма считается по значениям счётчика, а не по перечню имён.
    Такое «тождество» держится всегда — и новая фаза, которой нет в `PHASES`,
    пропадала бы из печатаемой строки молча, при зелёном виде.
    """

    def _census(self, phase: str) -> fcc.Census:
        failure = fcc.Failure(
            classname="m", name="a", tag="failure", phase=phase,
            message="KeyError: 'x'", kind="KeyError", skeleton="'x'", coarse="'…'",
            site="spa_core/x.py:1", frames=1, foreign_frames=0,
            evidence=frozenset(),
        )
        return fcc.Census(
            read=fcc.READ_OK, reason="стенд", path="стенд", collected=1,
            failures=(failure,), stream_agreed=0, stream_disagreed=0,
            stream_absent_for=0, stream_read=None,
        )

    def test_a_declared_phase_holds_the_identity(self):
        self.assertTrue(self._census(fcc.PHASE_CALL).identities_hold())

    def test_a_phase_outside_the_declared_set_breaks_the_identity(self):
        self.assertFalse(self._census("фаза, которой нет в перечне").identities_hold())


class ErrorTextIsNotAFrame(TempTree):
    """Кадры ЧУЖОГО прогона внутри текста исключения местом не являются.

    Порванное звено: строка, помеченная `E`, разбирается как кадр. Тестов, которые
    гоняют дочерний pytest и судят по его выводу, в наборе много — их сообщение
    несёт кадры чужой сессии, и место провала уехало бы туда.
    """

    CHILD_RUN_TB = ("spa_core/tests/test_x.py:111: in test_one\n"
                    "    self.assertIn('ok', out)\n"
                    "E   AssertionError: дочерний прогон упал:\n"
                    "E     spa_core/other.py:999: in helper\n"
                    "E         raise ValueError\n")

    def test_the_site_is_the_own_frame_not_the_embedded_one(self):
        mine, foreign = fcc.frames_of(self.CHILD_RUN_TB)
        self.assertEqual(mine, [("spa_core/tests/test_x.py", 111)])
        self.assertEqual(foreign, 0)

    def test_the_census_reads_the_same_site(self):
        path = self.write("j.xml", junit([
            case("m", "a", tag="failure",
                 message="AssertionError: дочерний прогон упал", text=self.CHILD_RUN_TB)]))
        self.assertEqual(fcc.census_from_path(path).failures[0].site,
                         "spa_core/tests/test_x.py:111")


class StreamSilenceIsNotAgreement(TempTree):
    """Провал, которого нет в потоковой записи, — третий исход, а не согласие.

    Порванное звено: «в потоковой записи нет» засчитывается согласием. Тогда
    сверка показывала бы полное согласие на записи, которая не видела НИ ОДНОГО
    из провалов, — то есть зелёный ответ на свой вопрос вместо нужного.
    """

    def test_a_failure_missing_from_the_stream_is_counted_separately(self):
        junit_path = self.write("j.xml", junit([
            case("spa_core.tests.test_x", "test_one", tag="failure",
                 message="KeyError: 'a'", text=REPO_TB),
            case("spa_core.tests.test_x", "test_two", tag="failure",
                 message="KeyError: 'b'", text=REPO_TB),
        ]))
        stream = self.root / "stream.jsonl"
        stream.write_text(json.dumps(
            {"e": "fail", "w": "call", "n": "spa_core/tests/test_x.py::test_one"}) + "\n",
            encoding="utf-8")
        census = fcc.census_from_path(junit_path, stream=stream)
        self.assertEqual((census.stream_agreed, census.stream_disagreed,
                          census.stream_absent_for), (1, 0, 1))
        self.assertIn("в потоковой записи нет 1", fcc.format_census(census))
