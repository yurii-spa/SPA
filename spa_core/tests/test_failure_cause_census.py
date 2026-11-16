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


class TheEventKeyDoesNotDependOnTheTempDirName(unittest.TestCase):
    """Положительный контроль ADR-1034 — настоящая авария прогонов `ci-control`.

    Сцена дословно воспроизводит замер 16.11 (цикл #1173) на живых артефактах
    43899796397 → 43917851571: ОДИН неизменный тест
    (`scripts/tests/test_shell_git_cd_target_census.py`) дал ДВА события, потому что
    `tempfile` выдал ему разные имена каталога — `cdtarget-dqid9nv` и
    `cdtarget-whcv8ted`. Нормализатор гасил числа, но не сегмент `$TMPDIR`, и дельта
    состава печатала ложное «пришло новое» вместе с ложным «ушло».

    Цена сегодня была нулевая (имя то же, видно глазами) — и ровно поэтому проверка
    нужна: мера, чей ключ зависит от имени временного каталога, со временем начинает
    считать одно событие двумя, НЕ СКАЗАВ, когда это началось.

    Времени, номеров процессов и git-окружения в предмете нет: сцена — две строки.
    """

    #: Дословные сообщения двух прогонов. Различие между ними РОВНО одно — имя,
    #: которое не выбирал никто.
    RUN_A = ("AssertionError: 2 != 1 : талоги "
             "('/tmp/cdtarget-dqid9nv/c1/homeA/Documents/SPA_Claude' ≠ "
             "'/tmp/cdtarget-dqid9nv/c1/ext/SPA_SYNC_REPO')")
    RUN_B = ("AssertionError: 2 != 1 : талоги "
             "('/tmp/cdtarget-whcv8ted/c1/homeA/Documents/SPA_Claude' ≠ "
             "'/tmp/cdtarget-whcv8ted/c1/ext/SPA_SYNC_REPO')")

    def _event(self, message: str) -> tuple[str, str]:
        """Ключ события — та же пара, которой группирует читатель дельты."""
        return (fcc.kind_of(message) or "«тип не назван»", fcc.skeleton_of(message))

    def test_two_runs_with_different_temp_names_are_ONE_event(self):
        """Предмет аварии: ключ обязан совпасть, а не «почти совпасть»."""
        self.assertEqual(self._event(self.RUN_A), self._event(self.RUN_B))
        self.assertEqual(len({self._event(self.RUN_A), self._event(self.RUN_B)}), 1)

    def test_the_random_segment_is_gone_from_the_key_itself(self):
        """Не «ключи равны случайно»: самого имени в ключе больше нет.

        Без этого проверка выше прошла бы и на нормализаторе, который стёр СТРОКУ
        целиком, — а такой «успех» означал бы потерю предмета (см. контроль ниже).
        """
        skeleton = fcc.skeleton_of(self.RUN_A)
        self.assertNotIn("dqid", skeleton)
        self.assertNotIn("cdtarget", skeleton)
        self.assertIn("<врем>", skeleton)

    def test_the_tail_after_the_segment_SURVIVES(self):
        """Отрицательный контроль переусердствования: хвост несёт ПРЕДМЕТ.

        Гасить путь целиком нельзя: различие `homeA` ≠ `ext` и есть то, на что
        жалуется утверждение. Стерев его, прибор склеил бы разные провалы в один —
        занижение, которого у этого модуля не прячут, а печатают вилкой.
        """
        skeleton = fcc.skeleton_of(self.RUN_A)
        self.assertIn("homeA", skeleton)
        self.assertIn("ext", skeleton)
        self.assertIn("SPA_SYNC_REPO", skeleton)

    def test_a_REAL_difference_stays_two_events(self):
        """Второй отрицательный контроль: правка не склеивает всё подряд."""
        one = "AssertionError: талоги ('/tmp/aaa111/c1/homeA' ≠ '/tmp/aaa111/c1/ext')"
        two = "AssertionError: талоги ('/tmp/bbb222/c1/homeA' ≠ '/tmp/bbb222/c1/OTHER')"
        self.assertNotEqual(self._event(one), self._event(two))

    def test_the_step_is_IDEMPOTENT_over_an_already_normalised_skeleton(self):
        """Скелет прошлого прогона читается из артефакта УЖЕ нормализованным.

        Числа в нём заменены родом (`cdtarget-dqid#nv`), поэтому шаг обязан дать тот
        же ключ и на таком тексте — иначе сличение с артефактом предыдущего прогона
        отвечало бы на другой вопрос, чем сличение сырых сообщений. Замер #1173: без
        `#` в классе сегмента ложная дельта на живых артефактах оставалась 2/2, с ним
        упала до 1/1 (единственное уцелевшее расхождение — настоящее, список
        «мёртвых скриптов» вырос на одно имя).
        """
        self.assertEqual(fcc.skeleton_of("AssertionError: в /tmp/cdtarget-dqid#nv/c#/x"),
                         fcc.skeleton_of("AssertionError: в /tmp/cdtarget-whcv#ted/c#/x"))

    def test_the_macos_temp_root_is_named_too(self):
        """`$TMPDIR` на Маке — `/var/folders/<род>/<род>/T/`, и он тоже ничей.

        Иначе один и тот же провал давал бы РАЗНЫЕ события в зависимости от того, где
        его намерили — на раннере или на рабочем Маке, — то есть ключ зависел бы от
        хоста (тот же род, что КАЛЕНДАРЬ и НОМЕР ПРОЦЕССА в `.claude/rules/deployment.md`).
        """
        mac = fcc.skeleton_of(
            "AssertionError: в /var/folders/k2/9xyzabc_1234/T/cdtarget-dqid9nv/c1/homeA")
        linux = fcc.skeleton_of("AssertionError: в /tmp/cdtarget-whcv8ted/c1/homeA")
        self.assertEqual(mac, linux)
        self.assertIn("<врем>", mac)

    def test_a_chosen_path_WITH_an_extension_is_still_a_path(self):
        """Прежнее правило не отменено: файл с расширением остаётся `<путь>`."""
        self.assertEqual(fcc.skeleton_of("AssertionError: нет /tmp/abc123/data/x.json"),
                         "нет <путь>")


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


class ASessionDeathIsAKindOfItsOwn(TempTree):
    """Обморок САМОЙ сессии (ADR-892) — РОД, а не провал теста с безымянной фазой.

    Положительный контроль настоящий: форма записи и хвост трассы воспроизводят шард 7
    контрольного прогона **41318580149** (`9ebe92509`, 01.11), где pytest упал в своей
    же отрисовке провала (`exit 3`), не дописав `<testcase>` тесту, под которым это
    случилось. До ADR-892 эта запись получала `phase_unnamed` и садилась среди провалов
    тестов, а «тип не назван» у неё читалось как «причину не нашли».
    """

    #: Хвост трассы — дословный из прогона. ГОЛОВА тела это кадры pluggy, то есть не
    #: причина; потому `exception_tail` и берёт последнюю строку, а не первую.
    TAIL = "TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'"
    BODY = ("Traceback (most recent call last):\n"
            "  File \"/opt/hostedtoolcache/Python/3.11.17/x64/lib/python3.11/"
            "site-packages/_pytest/main.py\", line 330, in wrap_session\n"
            "    session.exitstatus = doit(config, session) or 0\n"
            "  File \"/opt/hostedtoolcache/Python/3.11.17/x64/lib/python3.11/"
            "site-packages/_pytest/_code/code.py\", line 214, in lineno\n"
            "    return self._rawentry.tb_lineno - 1\n"
            f"{TAIL}\n")
    VICTIM = ("spa_core/tests/test_run_identity_key_price.py::BatteryHoleTests::"
              "test_the_instrument_excludes_itself_by_naming_the_reason")

    def record(self) -> Path:
        return self.write("j.xml", junit([
            case("spa_core.tests.test_x.Klass", "test_one", tag="failure",
                 message="KeyError: 'identity'", text=REPO_TB),
            case("pytest", "internal", tag="error", message="internal error",
                 text=self.BODY)]))

    def stream(self, *, mark: bool) -> Path:
        path = self.root / "stream.jsonl"
        rows = [{"e": "fail", "w": "call",
                 "n": "spa_core/tests/test_x.py::Klass::test_one"},
                {"e": "fail", "w": ("internal" if mark else "call"), "n": self.VICTIM}]
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
        return path

    def test_the_phase_of_a_session_death_is_named_not_unnamed(self):
        census = fcc.census_from_path(self.record())
        death = census.session_record
        self.assertIsNotNone(death, "запись `pytest::internal` не опознана вовсе")
        self.assertEqual(death.phase, fcc.PHASE_SESSION)
        self.assertEqual(census.by_phase().get(fcc.PHASE_SESSION), 1)
        self.assertEqual(census.by_phase().get(fcc.PHASE_UNNAMED, 0), 0,
                         "обморок сел среди провалов с безымянной фазой")
        self.assertIn(fcc.PHASE_SESSION, fcc.PHASES,
                      "род вне ОБЪЯВЛЕННОГО перечня исчезает из печатаемой строки молча")

    def test_the_exception_type_comes_from_the_tail_not_the_message(self):
        """`message` обморока есть литерал `internal error` и типа не несёт ВОВСЕ."""
        death = fcc.census_from_path(self.record()).session_record
        self.assertEqual(death.message, "internal error")
        self.assertIsNone(fcc.kind_of(death.message))
        self.assertEqual(death.kind, "TypeError")
        self.assertIn("unsupported operand", death.skeleton)

    def test_the_death_is_printed_as_its_own_kind(self):
        printed = fcc.format_census(fcc.census_from_path(self.record()))
        self.assertIn("ОБМОРОК СЕССИИ", printed)
        self.assertIn("TypeError", printed)

    def test_the_victim_is_named_by_the_machine_mark_only(self):
        marked = fcc.census_from_path(self.record(), stream=self.stream(mark=True))
        self.assertEqual(list(marked.session_victims),
                         [fcc.junit_name(self.VICTIM)])
        plain = fcc.census_from_path(self.record(), stream=self.stream(mark=False))
        self.assertEqual(list(plain.session_victims), [],
                         "жертва опознана без машинной метки — это догадка")

    def test_the_death_is_out_of_the_phase_agreement(self):
        """Потоковой строки у обморока НЕТ по построению — это не дыра записи."""
        census = fcc.census_from_path(self.record(), stream=self.stream(mark=True))
        self.assertEqual(census.stream_absent_for, 0)
        self.assertEqual(census.stream_agreed, 1)

    def test_victims_are_unmeasured_without_a_stream_rather_than_zero(self):
        census = fcc.census_from_path(self.record())
        self.assertIsNone(census.stream_read)
        self.assertEqual(list(census.session_victims), [])
        self.assertIn("НЕ СПРОШЕНЫ", fcc.format_census(census))

    def test_the_death_does_not_enter_the_defect_fork(self):
        census = fcc.census_from_path(self.record())
        self.assertEqual(fcc.fork_of(census.call).population, 1,
                         "обморок инструмента попал в вилку дефектов набора")
        self.assertTrue(census.identities_hold())


# ── ADR-910 (цикл #1024, заказ G901 п. 1) ────────────────────────────────────
# Положительный контроль у класса ОДИН и настоящий: два живых прогона
# контрольного набора — 41707593049 (`7cb79c8c6`) и 41653552215 (`76c050ab4`).
# Оба дали `failed=65`, то есть нетто-число НЕ ИЗМЕНИЛОСЬ, а по ИМЕНАМ дельта
# есть: одно имя пришло, одно ушло, и ОБА лежат в роде стенных часов. Дефектная
# часть в обоих прогонах — 61 имя, симметричная разность ПУСТА в обе стороны.
# До ADR-910 род стоял ВНУТРИ вилки (`population=65`, `upper=65`), и лотерея
# загрузки машины читалась как четыре поломки кода.

#: Дословное сообщение, которое печатает САМ pytest-timeout в фазе `call`. Литерал
#: ЧУЖОГО кода, снятый с живого артефакта прогона 41707593049 (все четыре жертвы
#: несут его байт в байт, `kind=Failed`, `phase=call`).
TIMEOUT_CALL = "Failed: Timeout (>180.0s) from pytest-timeout."
#: Та же фраза под ДВОЙНОЙ обёрткой писателя junit — фаза `setup`.
TIMEOUT_SETUP = ('failed on setup with '
                 '"Failed: Timeout (>180.0s) from pytest-timeout."')


class TheWallclockRodIsNamedAndNotAFork(TempTree):
    """Род стенных часов: выведен из вилки, НАЗВАН поимённо, тождество держится."""

    #: Объявление рода ОКРУЖЕНИЯ (ADR-915) здесь ПУСТО и при этом ПРОЧИТАНО: сцены
    #: этого класса про род ЧАСОВ, и вердикт их обязан не зависеть от содержимого
    #: боевого `ci_only_red_class_baseline.json` (десятая дверь семейства, ADR-905 —
    #: «вердикт как свойство СОДЕРЖИМОГО дерева»). Инъекция входом, не подменой
    #: модуля: боевой путь при этом не трогается ни одним вызовом.
    EMPTY_ENV = fcc.EnvDeclaration(read=fcc.ENV_READ_OK, path="<сцена>",
                                   reason="сцена: объявление пусто", names=frozenset())

    def fork(self, cases):
        return fcc.fork_of(
            fcc.census_from_path(self.write("j.xml", junit(cases))).call,
            env=self.EMPTY_ENV)

    def test_the_timeout_does_not_enter_the_defect_fork(self):
        """Предмет ADR-910: четыре часовых провала стояли среди дефектов кода."""
        fork = self.fork([
            case("m", "defect", tag="failure", message="KeyError: 'identity'",
                 text=REPO_TB),
            case("m", "slow", tag="failure", message=TIMEOUT_CALL, text=DEEP_TB),
        ])
        self.assertEqual(fork.population, 1,
                         "обморок по стенным часам попал в вилку дефектов набора")
        self.assertEqual(fork.wallclock_timeouts, 1)
        self.assertEqual(fork.upper, 1, "верхний край вилки всё ещё считает род часов")

    def test_the_rod_is_named_by_nodeid_not_merely_counted(self):
        """Счётчик без имён не даёт починить: ротацию видно только по именам."""
        fork = self.fork([case("m", "slow", tag="failure", message=TIMEOUT_CALL,
                               text=DEEP_TB)])
        self.assertEqual(list(fork.wallclock_names), ["m::slow"])

    def test_the_accounting_identity_holds(self):
        """`population + wallclock + окружение == given` — род не вправе исчезнуть.

        Тождество РАСШИРЕНО третьим слагаемым (ADR-915, инв. #16 — намеренно и с
        обоснованием): родов, выведенных из вилки, стало два, и прежняя форма
        `population + wallclock == given` после второго вычитания стала бы ЛОЖНОЙ
        там, где он срабатывает. Проверка от этого только усиливается — она
        перестаёт быть слепой к пропаже второго рода.
        """
        fork = self.fork([
            case("m", "defect", tag="failure", message="KeyError: 'identity'",
                 text=REPO_TB),
            case("m", "slow1", tag="failure", message=TIMEOUT_CALL, text=DEEP_TB),
            case("m", "slow2", tag="failure", message=TIMEOUT_CALL, text=DEEP_TB),
        ])
        self.assertEqual(fork.given, 3)
        self.assertEqual(fork.population + fork.wallclock_timeouts
                         + fork.runner_environment, fork.given)
        self.assertTrue(fork.accounting_holds)

    def test_a_set_WITHOUT_the_rod_is_left_exactly_as_before(self):
        """Обратная сторона: без рода вилка не двигается ни на единицу."""
        cases = [
            case("m", "a", tag="failure", message="KeyError: 'identity'", text=REPO_TB),
            case("m", "b", tag="failure", message="KeyError: 'verdict'", text=REPO_TB),
        ]
        fork = self.fork(cases)
        self.assertEqual((fork.population, fork.lower, fork.upper), (2, 1, 2))
        self.assertEqual(fork.wallclock_timeouts, 0)
        self.assertEqual(list(fork.wallclock_names), [])
        self.assertEqual(fork.population, fork.given)

    def test_the_rule_is_EQUALITY_and_not_a_substring(self):
        """Порванное звено, и самое дорогое: правило вхождения ОСЛАБИЛО бы вердикт.

        Тест, чей предмет — сам сторож зависаний, цитирует фразу производителя
        внутри своего же утверждения. Правило «фраза встречается» вынесло бы
        НАСТОЯЩИЙ дефект из вилки, прикрывшись усилением (инв. #16, ADR-333).
        """
        fork = self.fork([
            case("m", "quoting", tag="failure",
                 message=("AssertionError: сторож обязан печатать "
                          "'Failed: Timeout (>180.0s) from pytest-timeout.', "
                          "а напечатал иное"),
                 text=REPO_TB)])
        self.assertEqual(fork.wallclock_timeouts, 0,
                         "цитата фразы объявлена родом часов — дефект вынесен из вилки")
        self.assertEqual(fork.population, 1)

    def test_the_DOUBLE_wrapper_of_the_junit_writer_is_unwrapped(self):
        """Порванное звено: фаза `setup` оборачивает фразу ДВАЖДЫ.

        `<error>`-префикс писателя junit плюс голова `Failed:` самого pytest. Мера,
        снявшая одну обёртку из двух, назвала бы настоящий срок дефектом кода.
        """
        self.assertEqual(fcc.timeout_rod_of(TIMEOUT_SETUP), fcc.ROD_TIMEOUT)
        self.assertEqual(fcc.timeout_rod_of(TIMEOUT_CALL), fcc.ROD_TIMEOUT)

    def test_an_absent_message_is_UNMEASURED_and_STAYS_in_the_fork(self):
        """Третий исход (инв. #17), и он fail-CLOSED.

        Сообщения нет ⇒ род НЕ ОТВЕЧЕН. Выносить такой провал из вилки значило бы
        дать «не измерено» работать оправданием, поэтому он остаётся дефектом и
        при этом СЧИТАЕТСЯ отдельно.
        """
        self.assertEqual(fcc.timeout_rod_of(""), fcc.ROD_UNMEASURED)
        fork = self.fork([case("m", "silent", tag="failure", message="",
                               text=REPO_TB)])
        self.assertEqual(fork.rod_unmeasured, 1)
        self.assertEqual(fork.population, 1, "«род не измерен» вынесло провал из вилки")
        self.assertEqual(fork.wallclock_timeouts, 0)

    def test_the_rod_class_set_is_closed(self):
        self.assertEqual(fcc.ROD_CLASSES,
                         (fcc.ROD_TIMEOUT, fcc.ROD_NONE, fcc.ROD_UNMEASURED))

    def test_the_rod_is_PRINTED_even_when_it_is_the_whole_red_set(self):
        """Порванное звено: ранний возврат по нулевой вилке съедал печать рода.

        Набор, у которого ВСЕ провалы фазы `call` суть род часов, даёт
        `population == 0`. Строка «провалов нет» без печати рода прочиталась бы
        как зелёная фаза — то есть четыре часовых обморока исчезли бы совсем.
        """
        census = fcc.census_from_path(self.write("j.xml", junit([
            case("m", "slow", tag="failure", message=TIMEOUT_CALL, text=DEEP_TB)])))
        out = fcc.format_census(census)
        self.assertEqual(fcc.fork_of(census.call).population, 0)
        self.assertIn("ОБМОРОК ПО СТЕННЫМ ЧАСАМ", out)
        self.assertIn("m::slow", out)

    def test_the_absence_of_the_rod_is_printed_as_MEASURED_ZERO(self):
        """Обратная сторона печати: «нет рода» сказано словом, а не молчанием."""
        census = fcc.census_from_path(self.write("j.xml", junit([
            case("m", "a", tag="failure", message="KeyError: 'identity'",
                 text=REPO_TB)])))
        out = fcc.format_census(census)
        self.assertIn("обморока по стенным часам нет — измерено и равно нулю", out)
        self.assertNotIn("ОБМОРОК ПО СТЕННЫМ ЧАСАМ", out)
