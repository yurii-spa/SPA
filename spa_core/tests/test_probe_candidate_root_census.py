#!/usr/bin/env python3
"""spa_core/tests/test_probe_candidate_root_census.py — сторож прибора G1031 п. 2.

# LLM_FORBIDDEN

Что здесь проверяется и почему именно так
-----------------------------------------
Прибор отвечает на вопрос «ЖИВОЙ ли корень у пробы (или у кандидата в пробу)»,
и его ответ опровергает обещание соседнего детектора о СТОРОНЕ своей ошибки.
Поэтому батарея устроена тремя слоями, и ни один не заменяет другие:

1. **ПРОБА О ЖИВОМ ДЕРЕВЕ С ИЗВЕСТНЫМ ЧЛЕНОМ** — `test_known_members_of_both_sides…`.
   Живой зов стои́т в ТЕЛЕ теста, а не в фикстуре: зов из `setUpClass` пробой
   не считается, и первая редакция соседней батареи ровно так сделала новый
   прибор НОВЫМ ЧЛЕНОМ класса, который он мерит (G1031 п. 5).
2. **ПАРЫ В ОБЕ СТОРОНЫ у КАЖДОЙ из трёх дверей** — одноразовая сцена и её
   живой двойник отличаются РОВНО происхождением корня, и вердикты обязаны
   быть ПРОТИВОПОЛОЖНЫМИ. Проверка, зелёная только на целом контуре, не
   отличима от проверки, не смотрящей никуда.
3. **РАСХОЖДЕНИЕ С СОСЕДОМ ПРЕДЪЯВЛЕНО, а не рассказано** — на тех же сценах
   спрашивается и соседний читатель (`is_live_call`), и его «живой» рядом с
   нашим `disposable_root` и есть находка цикла. Сосед зовётся через
   `pcr.kmp`, а НЕ импортом: батарея, назвавшая прибор, становится его
   дверью, и импорт здесь сдвинул бы ответ соседа о САМОМ СЕБЕ (G1031 п. 4).

Литеральных дат и литеральных pid в наборе нет ПО ПОСТРОЕНИЮ: единственный
вход меры — путь дерева и текст двух файлов сцены.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import textwrap
import unittest

import pytest

from spa_core.monitoring import probe_candidate_root_census as pcr

#: Живой замер обеих сторон стои́т ЗАМЕРЕННЫЕ ~110 с (26 пар кандидатов + 150
#: пар зачтённых проб, каждая — разбор батареи и исходника прибора), а общий
#: `--timeout=180` набора НЕ ТРОНУТ (инв. #16): порог объявлен у ЭТОГО класса,
#: как у 25 других объявлений набора. Медленный, но верный замер без такого
#: объявления попадает в род стенных часов на более медленном раннере и
#: читается как дефект кода (G1031 п. 7).
pytestmark = pytest.mark.timeout(600)

_REPO = pathlib.Path(__file__).resolve().parents[2]

_SUBJECT_REL = "spa_core/monitoring/zzz_scene_probe.py"
_BATTERY_REL = "spa_core/tests/test_zzz_scene_probe.py"

#: Прибор сцены: у `run` корень ЖИВОЙ ПО УМОЛЧАНИЮ (это читает соседний
#: `subject_live_default_funcs`), у `measure` — нет. Две функции нужны, чтобы
#: дверь 2 («умолчание, перекрытое явным аргументом») была проверяема, а не
#: предполагаема.
_SUBJECT = """
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def measure(root):
    return {"root": str(root)}


def run(root=None, write=False):
    root = root or REPO_ROOT
    return measure(root)
"""


def _scene(root: pathlib.Path, battery_body: str) -> pathlib.Path:
    """Одноразовое дерево из двух файлов: прибор и его батарея."""
    for rel, body in ((_SUBJECT_REL, _SUBJECT), (_BATTERY_REL, battery_body)):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return root


#: Помощник сцены повторяет ФОРМУ настоящего известного члена
#: (`scripts/tests/test_forbidden_reach_census.py::_run`): прибор зовётся ПО
#: ПУТИ, собранному от живого `_REPO`, а измеряемый корень приезжает
#: ПАРАМЕТРОМ. Форма выбрана не для красоты — соседний читатель признаёт
#: помощник дверью ТОЛЬКО если зов внутри него выглядит живым
#: (`_helpers_reaching_instrument` требует `is_live_call`), и помощник
#: `z.measure(root)` без живого элемента дверью у соседа не становится вовсе.
#: Тогда сцена не выражала бы дверь 1 НИ В ОДНУ сторону: оба её конца
#: получили бы `unmeasured`, и зелёный тест означал бы «площадки не видно»,
#: а не «вердикты противоположны» (замер этого цикла — первая редакция
#: сцены именно так и молчала).
_HELPER_HEAD = """
import os
import pathlib
import subprocess
import sys
import tempfile

from spa_core.monitoring import zzz_scene_probe as z

_REPO = pathlib.Path(__file__).resolve().parents[2]


class ThroughHelper:

    def _call(self, root):
        return subprocess.run([sys.executable,
                               os.path.join(_REPO, "spa_core", "monitoring",
                                            "zzz_scene_probe.py"),
                               "--root", root], capture_output=True)
"""

#: Дверь 1 — ГРАНИЦА ПАРАМЕТРА ПОМОЩНИКА. Пара отличается ровно тем, что
#: получает помощник: живой корень либо tempfile-каталог.
_DOOR1_LIVE = _HELPER_HEAD + """
    def test_scene(self):
        assert self._call(str(_REPO))
"""
_DOOR1_DISPOSABLE = _HELPER_HEAD + """
    def test_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert self._call(tmp)
"""

#: Дверь 2 — УМОЛЧАНИЕ ПРИБОРА, ПЕРЕКРЫТОЕ ЯВНЫМ АРГУМЕНТОМ. Живая сторона
#: зовёт `run()` БЕЗ корня (и тогда умолчание прибора действительно живое),
#: одноразовая передаёт корень ЯВНО.
_DOOR2_LIVE = """
from spa_core.monitoring import zzz_scene_probe as z


class DefaultRoot:

    def test_scene(self):
        assert z.run()
"""
_DOOR2_DISPOSABLE = """
import tempfile

from spa_core.monitoring import zzz_scene_probe as z


class DefaultRoot:

    def test_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert z.run(root=str(tmp))
"""

#: Дверь 3 — ГРАНИЦА ФИКСТУРЫ. Одна и та же сцена, и отличие ровно одно: где
#: СТОИТ привязка корня — в `setUp` или в теле теста. Вердикт обязан не
#: зависеть от этого, иначе невидимость фикстуры остаётся дырой.
_DOOR3_IN_FIXTURE = """
import pathlib
import tempfile

from spa_core.monitoring import zzz_scene_probe as z


class FromFixture:

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def test_scene(self):
        assert z.measure(self.root)
"""
_DOOR3_IN_BODY = """
import pathlib
import tempfile

from spa_core.monitoring import zzz_scene_probe as z


class FromBody:

    def test_scene(self):
        _tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(_tmp.name)
        assert z.measure(root)
"""

#: Дверь 2' — корень, взятый у САМОГО ПРИБОРА. Признать его живым можно
#: только ПРОЧИТАВ прибор, и эта сторона доказывает, что прибор читается.
_SUBJECT_CONSTANT = """
import pathlib

from spa_core.monitoring import zzz_scene_probe as z

REPO = pathlib.Path(z.REPO_ROOT)


class SubjectConstant:

    def test_scene(self):
        assert z.measure(str(REPO))
"""

#: Фикстура pytest как корень: имя приезжает ПАРАМЕТРОМ теста, слова
#: `tempfile` в сцене нет ни одного, и соседний перечень одноразовости
#: (регулярное выражение по `tempfile|mkdtemp|…`) его не находит.
_PYTEST_TMP = """
from spa_core.monitoring import zzz_scene_probe as z


def test_scene(tmp_path):
    assert z.run(root=str(tmp_path))
"""


def _verdict(battery_body: str) -> pcr.Row:
    with tempfile.TemporaryDirectory() as tmp:
        root = _scene(pathlib.Path(tmp), battery_body)
        return pcr.root_origin(root, _SUBJECT_REL, _BATTERY_REL, "test_scene")


class TheThreeDoorsAnswerInBothDirections(unittest.TestCase):
    """У каждой двери — пара сцен, и вердикты ПРОТИВОПОЛОЖНЫ."""

    def test_door1_helper_parameter_boundary(self):
        self.assertEqual(pcr.LIVE_ROOT, _verdict(_DOOR1_LIVE).outcome)
        row = _verdict(_DOOR1_DISPOSABLE)
        self.assertEqual(pcr.DISPOSABLE_ROOT, row.outcome, row.reason)
        self.assertEqual([pcr.SITE_HELPER], [s.kind for s in row.sites])

    def test_door2_instrument_default_overridden_by_an_explicit_root(self):
        live = _verdict(_DOOR2_LIVE)
        self.assertEqual(pcr.LIVE_ROOT, live.outcome, live.reason)
        row = _verdict(_DOOR2_DISPOSABLE)
        self.assertEqual(pcr.DISPOSABLE_ROOT, row.outcome, row.reason)

    def test_door3_the_verdict_does_not_depend_on_where_the_binding_sits(self):
        in_fixture = _verdict(_DOOR3_IN_FIXTURE)
        in_body = _verdict(_DOOR3_IN_BODY)
        self.assertEqual(pcr.DISPOSABLE_ROOT, in_body.outcome, in_body.reason)
        self.assertEqual(
            in_body.outcome, in_fixture.outcome,
            "привязка корня, стоящая в `setUp`, обязана читаться так же, как в "
            f"теле теста: {in_fixture.reason}")

    def test_a_root_taken_from_the_instruments_own_constant_is_live(self):
        row = _verdict(_SUBJECT_CONSTANT)
        self.assertEqual(pcr.LIVE_ROOT, row.outcome, row.reason)

    def test_a_pytest_tmp_fixture_is_a_disposable_root(self):
        row = _verdict(_PYTEST_TMP)
        self.assertEqual(pcr.DISPOSABLE_ROOT, row.outcome, row.reason)


class TheNeighbourIsAskedOnTheSameScenes(unittest.TestCase):
    """Расхождение с соседом ПРЕДЪЯВЛЕНО, а не рассказано.

    Сосед зовётся через `pcr.kmp` — импорт его имени сюда сделал бы эту
    батарею его дверью (G1031 п. 4).
    """

    def _neighbour_calls_it_live(self, battery_body: str) -> bool:
        kmp = pcr.kmp
        ast = pcr.ast
        tree = ast.parse(textwrap.dedent(battery_body).lstrip("\n"))
        mods, funcs = kmp.battery_bindings(tree, kmp.subject_keys(_SUBJECT_REL))
        path_strs = frozenset({_SUBJECT_REL,
                               pathlib.PurePath(_SUBJECT_REL).name})
        live_defaults = kmp.subject_live_default_funcs(
            textwrap.dedent(_SUBJECT).lstrip("\n"))
        makers = kmp.helpers_making_disposable(tree)
        mod_disposable = kmp.disposable_names(tree, makers=makers)
        mod_live = kmp.live_root_names(tree, disposable=mod_disposable)
        for fn, outer_live, outer_disposable in kmp._test_scopes(
                tree, mod_live, mod_disposable, makers):
            if fn.name != "test_scene":
                continue
            disposable = kmp.disposable_names(fn, outer_disposable, makers)
            live = kmp.live_root_names(fn, outer_live, disposable)
            helpers = kmp._helpers_reaching_instrument(
                tree, mods, funcs, path_strs, mod_live, live_defaults,
                mod_disposable, makers)
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                if kmp.is_instrument_call(call, mods, funcs, path_strs) \
                        and kmp.is_live_call(call, live, live_defaults, disposable):
                    return True
                # Второе условие — НЕ украшение и не наша добавка: сосед
                # засевает «живой ответ» ЛЮБЫМ зовом помощника из `helpers`
                # (`_tainted_by_live_answer`, строка `_calls_name(call,
                # helpers)`), НЕ спрашивая, какой корень помощнику передали.
                # Спросить соседа только о прямом зове значило бы спросить его
                # о более узком вопросе, чем он сам себе задаёт, — и дверь 1
                # тогда «закрыта» лишь в нашей модели соседа.
                if kmp._calls_name(call, helpers):
                    return True
        return False

    def test_the_neighbour_credits_a_helper_whatever_root_it_was_given(self):
        """Дверь 1 у соседа ОТКРЫТА — предъявлено, а не рассказано.

        Пара сцен отличается РОВНО происхождением корня, который получает
        помощник; у соседа вердикт ОДИН И ТОТ ЖЕ на обеих, у нас —
        противоположный. Это и есть форма настоящего известного члена
        (`scripts/forbidden_reach_census.py`).
        """
        self.assertTrue(
            self._neighbour_calls_it_live(_DOOR1_DISPOSABLE),
            "сосед перестал зачитывать помощника при ОДНОРАЗОВОМ корне — "
            "дверь 1 закрыта, и тогда расхождение надо перемерить, а не "
            "утверждать по памяти")
        self.assertTrue(self._neighbour_calls_it_live(_DOOR1_LIVE))
        self.assertEqual(pcr.DISPOSABLE_ROOT, _verdict(_DOOR1_DISPOSABLE).outcome)
        self.assertEqual(pcr.LIVE_ROOT, _verdict(_DOOR1_LIVE).outcome)

    def test_the_neighbour_calls_an_explicit_disposable_root_live(self):
        """Дверь 2 у соседа ОТКРЫТА — это и есть находка, а не наше мнение.

        Сцена — `run(root=str(tmp_path))`, то есть ФОРМА настоящего известного
        члена (`artifact_stamp_clock_doors`): одноразовость приезжает
        ФИКСТУРОЙ pytest, и перечень одноразовости соседа (регулярное
        выражение по словам `tempfile`/`mkdtemp`) её не находит ни одним
        словом. Со сценой на `tempfile.TemporaryDirectory` этот тест был
        КРАСЕН и был прав: там сосед отвечает «одноразовый» верно, и
        расхождения нет — то есть прежняя сцена предъявляла не ту дверь,
        которую называла (замер этого цикла).
        """
        self.assertTrue(
            self._neighbour_calls_it_live(_PYTEST_TMP),
            "сосед перестал звать живым зов с ЯВНЫМ одноразовым корнем из "
            "фикстуры pytest — дверь 2 закрыта, и тогда расхождение надо "
            "перемерить, а не утверждать по памяти")
        self.assertEqual(pcr.DISPOSABLE_ROOT, _verdict(_PYTEST_TMP).outcome)

    def test_the_neighbour_agrees_where_the_root_is_honestly_live(self):
        """Обратная сторона: на живой сцене расхождения нет ни одного."""
        self.assertTrue(self._neighbour_calls_it_live(_DOOR2_LIVE))
        self.assertEqual(pcr.LIVE_ROOT, _verdict(_DOOR2_LIVE).outcome)

    def test_the_neighbour_sees_the_tempfile_word_and_then_agrees(self):
        """Калибровка НЕ-члена: там, где слово `tempfile` в сцене ЕСТЬ, сосед
        отвечает так же, как мы, и расхождение не выдумывается."""
        self.assertFalse(self._neighbour_calls_it_live(_DOOR2_DISPOSABLE))
        self.assertEqual(pcr.DISPOSABLE_ROOT, _verdict(_DOOR2_DISPOSABLE).outcome)


class TheThirdOutcomeIsNamed(unittest.TestCase):
    """«Не измерено» отделено от обоих ответов и несёт ПРИЧИНУ (инв. #17)."""

    def test_an_absent_test_is_unmeasured_not_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(pathlib.Path(tmp), _DOOR1_LIVE)
            row = pcr.root_origin(root, _SUBJECT_REL, _BATTERY_REL, "test_absent")
        self.assertEqual(pcr.UNMEASURED, row.outcome)
        self.assertIn("test_absent", row.reason or "")

    def test_an_unparsable_battery_is_unmeasured_with_the_exception_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(pathlib.Path(tmp), "def test_scene(:\n    pass\n")
            row = pcr.root_origin(root, _SUBJECT_REL, _BATTERY_REL, "test_scene")
        self.assertEqual(pcr.UNMEASURED, row.outcome)
        self.assertIn("SyntaxError", row.reason or "")

    def test_an_absent_battery_is_unmeasured_not_a_clean_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = pcr.root_origin(pathlib.Path(tmp), _SUBJECT_REL, _BATTERY_REL,
                                  "test_scene")
        self.assertEqual(pcr.UNMEASURED, row.outcome)
        self.assertIn("Error", row.reason or "")

    def test_an_empty_input_is_a_refusal_not_a_zero(self):
        with self.assertRaises(pcr.Refused):
            pcr.measure(_REPO, [])


class TheCensusIsClosedAndCalibrated(unittest.TestCase):
    """Замер на ЖИВОМ дереве: известные члены обеих сторон и замкнутость осей."""

    def test_known_members_of_both_sides_are_on_the_live_tree(self):
        """ПРОБА прибора: живой зов — В ТЕЛЕ теста, член назван ОБЪЯВЛЕНИЕМ.

        Имя члена не печатается литералом нарочно: перечень берётся у
        объявления (`KNOWN_*`), а не копией рядом, — сильнейшая из форм, и
        ровно она не даёт объявлению и проверке разойтись.

        Вердикт спрашивается у ТОЙ батареи, в которой названный тест ЕСТЬ, и
        это не удобство, а предмет: батарей у прибора бывает несколько
        (`scripts/forbidden_reach_census.py` их две), и пара «прибор × чужая
        батарея × тест» честно отвечает `unmeasured` — теста там нет. Свёртка
        `by_subject` такую пару смешивает с настоящим ответом и даёт
        `unmeasured` на известном члене, то есть калибровка краснеет НЕ от
        формы прибора, а от своего же перечня пар (замер этого цикла). Пар, в
        которых тест НАЙДЕН, обязана быть РОВНО ОДНА — иначе предпосылка не
        обеспечена, и тест падает ГРОМКО, а не судит по первой попавшейся.
        """
        for side, expected in ((pcr.KNOWN_DISPOSABLE_ROOT, pcr.DISPOSABLE_ROOT),
                               (pcr.KNOWN_LIVE_ROOT, pcr.LIVE_ROOT)):
            for (subject, test), why in sorted(side.items()):
                batteries = list(pcr.kmp.batteries_of(_REPO, [subject])[0]
                                 .get(subject, {}))
                self.assertTrue(batteries,
                                f"{subject}: батарей не найдено ВОВСЕ — "
                                "предпосылка калибровки не обеспечена")
                rows = [pcr.root_origin(_REPO, subject, battery, test)
                        for battery in batteries]
                found = [r for r in rows if r.sites]
                self.assertEqual(
                    1, len(found),
                    f"{subject}::{test}: площадки зова найдены в "
                    f"{len(found)} батаре(ях) из {len(batteries)} "
                    f"({[r.battery for r in found]}) — ожидалась ровно одна; "
                    "о происхождении корня при такой предпосылке отвечать "
                    "нечем")
                self.assertEqual(expected, found[0].outcome,
                                 f"{subject}::{test} ({found[0].battery}): "
                                 f"{why} — прибор дал `{found[0].outcome}`: "
                                 f"{found[0].reason}")
        pairs = [(subject, found_battery, test)
                 for side in (pcr.KNOWN_DISPOSABLE_ROOT, pcr.KNOWN_LIVE_ROOT)
                 for (subject, test) in side
                 for found_battery in pcr.kmp.batteries_of(_REPO, [subject])[0]
                 .get(subject, {})]
        got = pcr.measure(_REPO, pairs, pairs_source="KNOWN_* обеих сторон")
        self.assertGreaterEqual(pcr.calibration_seen(got),
                                len(pcr.KNOWN_DISPOSABLE_ROOT)
                                + len(pcr.KNOWN_LIVE_ROOT))

    def test_the_outcome_axis_is_closed_and_sums_to_the_population(self):
        declared = pathlib.Path(
            _REPO / "spa_core/tests/known_member_probe_baseline.json")
        subjects = json.loads(declared.read_text(encoding="utf-8"))["members"]
        pairs, source = pcr.pairs_from_cause_census(_REPO, subjects)
        got = pcr.calibrated_measure(_REPO, pairs, pairs_source=source,
                                     side=pcr.SIDE_CANDIDATES)
        self.assertEqual(sorted(got.counts), sorted(pcr.OUTCOMES))
        self.assertEqual(got.population, sum(got.counts.values()))
        self.assertEqual(got.population, len(got.rows))
        self.assertEqual(len(pcr.by_subject(got)),
                         sum(pcr.subject_counts(got).values()))

    def test_the_pairs_come_from_the_neighbour_and_not_from_a_copy(self):
        """Перечень — ОТВЕТ соседа. Копия перечня была бы вторым объявлением.

        Имя прибора берётся у ОБЪЯВЛЕНИЯ (`KNOWN_DISPOSABLE_ROOT`), а не
        печатается литералом: батарея, назвавшая путь прибора СТРОКОЙ,
        становится его слабой дверью и сдвигает ответ соседа о нём самом
        (G1031 п. 4). Здесь это уже случилось и было измерено: литерал
        `scripts/forbidden_reach_census.py` делал ЭТУ батарею второй батареей
        того прибора, и калибровка краснела на паре «прибор × эта батарея ×
        тест, которого в ней нет».
        """
        subject = sorted(pcr.KNOWN_DISPOSABLE_ROOT)[0][0]
        pairs, source = pcr.pairs_from_cause_census(_REPO, [subject])
        self.assertIn("probe_absence_cause_census", source)
        self.assertEqual([subject], [p[0] for p in pairs])

    def test_the_exit_code_follows_the_subject_axis_not_the_pair_axis(self):
        """Код возврата сверяется с ОСЬЮ ПРИБОРОВ, а не с состоянием дерева.

        Утверждать «код 1» значило бы покраснеть от ПОЧИНКИ находок — то есть
        запретить тот исход, которого заказ и добивается.
        """
        declared = pathlib.Path(
            _REPO / "spa_core/tests/known_member_probe_baseline.json")
        subjects = json.loads(declared.read_text(encoding="utf-8"))["members"]
        pairs, source = pcr.pairs_from_cause_census(_REPO, subjects)
        got = pcr.measure(_REPO, pairs, pairs_source=source,
                          side=pcr.SIDE_CANDIDATES)
        subj = pcr.subject_counts(got)
        expected = (pcr.RC_FINDING if subj[pcr.DISPOSABLE_ROOT]
                    else pcr.RC_UNMEASURED if subj[pcr.UNMEASURED]
                    else pcr.RC_CLEAN)
        self.assertEqual(expected, pcr.report(["--side", pcr.SIDE_CANDIDATES]))

    def test_an_unreadable_declaration_is_code_two_not_a_clean_run(self):
        self.assertEqual(pcr.RC_UNMEASURED,
                         pcr.report(["--subjects", "/nonexistent/declaration.json"]))


if __name__ == "__main__":
    unittest.main()
