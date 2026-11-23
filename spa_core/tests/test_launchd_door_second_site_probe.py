# LLM_FORBIDDEN
"""Контроль пробы `launchd_door_has_no_second_site` (ADR-1075, цикл #1219).

Проба объявлена критерием карточки
`inbox-vtoraya-dver-germetichnogo-launchd-pryam`. Предмет карточки — красный
`main` 23.11: `tests/test_kill_switch_eval_path.py` ставил
`threat_reactor._kickstart_cycle` ПРЯМЫМ присваиванием атрибута модуля, подмена
переживала тест, и положительный контроль двери
(`test_the_prod_code_really_does_call_a_mutating_launchctl`) получал ПУСТОЙ
список зовов.

**Почему контроль устроен сценами с ЧУЖОЙ переписью, а не копией дерева.**
Проба спрашивает перепись У ИЗМЕРЯЕМОГО ДЕРЕВА (дочерний процесс,
`PYTHONPATH=<корень>`) — иначе она судила бы чужую дверь своим списком. Значит
сцена обязана быть деревом, а не подменой внутри процесса; настоящее дерево
копировать и дорого, и неверно (сцена должна отличаться РОВНО одним звеном).
Поэтому сцены — крошечные деревья с ОДНИМ модулем переписи, и каждое отличается
от соседнего одним ответом этой переписи либо одним файлом.

Правда ли сама перепись находит сайт — вопрос ДРУГОЙ, и у него свои контроли в
`test_hermetic_launchd_door.py` (посаженный сайт · нечитаемый файл · перечень
атрибутов берётся из двери). Здесь мерится ПРОВОДКА пробы: доходит ли ответ
переписи до вердикта и различимы ли три исхода.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from spa_core.monitoring import card_acceptance as ca

_PROBE = "launchd_door_has_no_second_site"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Крошечная перепись-дублёр: отвечает тем, что в неё положили. Это НЕ копия
#: настоящей переписи и не претендует ею быть — сцена проверяет, доходит ли
#: ответ до вердикта.
_STUB_CENSUS = '''
def door_attrs():
    return frozenset({"_kickstart_cycle", "_kickstart", "_alert", "run"})


def door_module_names():
    return frozenset({"threat_reactor", "catchup_cycle"})


MEASURED_TEST_DIRS = ("tests",)
HITS = __HITS__
UNPARSED = __UNPARSED__


def direct_door_assignments(root, dirs=MEASURED_TEST_DIRS):
    return list(HITS), list(UNPARSED), 7
'''

_DOOR_TEST_TEMPLATE = '''
_WIRED = __WIRED__


def test_the_scene_has_a_door_test():
    assert isinstance(_WIRED, tuple)
'''


def _scene(*, hits: list[str] | None = None,
           unparsed: list[str] | None = None,
           wired: tuple[str, ...] | None = ("tests/test_site.py",),
           site_passes: bool = True,
           with_census: bool = True,
           with_helper: bool = True,
           with_door_test: bool = True,
           door_test_body: str | None = None) -> pathlib.Path:
    """Одноразовое дерево-сцена. Каждый флаг рвёт РОВНО одно звено."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="launchd_probe_scene_"))
    (root / "spa_core" / "tests").mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "spa_core" / "tests" / "__init__.py").write_text("", encoding="utf-8")
    if with_helper:
        source = ""
        if with_census:
            source = (_STUB_CENSUS
                      .replace("__HITS__", repr(hits or []))
                      .replace("__UNPARSED__", repr(unparsed or [])))
        (root / "spa_core" / "tests" / "_hermetic_launchd.py").write_text(
            source, encoding="utf-8")
    if with_door_test:
        body = door_test_body
        if body is None:
            body = _DOOR_TEST_TEMPLATE.replace("__WIRED__", repr(wired or ()))
        (root / "spa_core" / "tests"
         / "test_hermetic_launchd_door.py").write_text(body, encoding="utf-8")
    for name in (wired or ()):
        site = root / name
        site.parent.mkdir(parents=True, exist_ok=True)
        tail = "    assert True\n" if site_passes else "    assert False, 'сцена'\n"
        site.write_text("def test_site():\n" + tail, encoding="utf-8")
    return root


def _ask(root: pathlib.Path) -> tuple[str, str]:
    try:
        return ca.PROBES[_PROBE](None, repo_root=str(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


class LaunchdDoorSecondSiteProbe(unittest.TestCase):

    # ── целый контур: НАСТОЯЩЕЕ дерево ──────────────────────────────────────
    def test_the_whole_contour_on_the_real_tree_is_satisfied(self):
        verdict, detail = ca.PROBES[_PROBE](None, repo_root=str(_REPO_ROOT))
        self.assertEqual(ca.SATISFIED, verdict, detail)
        self.assertIn("НОЛЬ", detail, "вердикт не называет, ЧТО измерено")
        self.assertIn("со-прогон", detail, "вердикт молчит о втором исходе")

    # ── первый исход: перепись НАЗВАЛА сайт ─────────────────────────────────
    def test_a_named_second_site_is_refused_and_the_site_is_printed(self):
        verdict, detail = _ask(_scene(
            hits=["tests/test_polluter.py:288 _tr._kickstart_cycle"]))
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("test_polluter.py:288", detail,
                      "отказ не называет сайт — чинить нечего")
        self.assertIn("closed(", detail, "отказ не называет лечение")

    def test_the_refusal_is_NOT_by_substring(self):
        """Сцена несёт ВСЕ слова зелёного вердикта и всё равно отказана.

        Иначе проба проходила бы по тексту дерева, а не по его ответу.
        """
        verdict, detail = _ask(_scene(
            hits=["tests/test_polluter.py:1 _tr._alert"],
            door_test_body=(
                "# дверь ОДНА и переживает соседа: со-прогон зелён, НОЛЬ\n"
                "# прямых присваиваний, _hermetic_launchd.closed()\n"
                '_WIRED = ("tests/test_site.py",)\n'
                "\n"
                "def test_the_scene_has_a_door_test():\n"
                "    assert isinstance(_WIRED, tuple)\n")))
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("_alert", detail)

    # ── третий исход: НЕ ИЗМЕРЕНО, и каждая причина СВОЯ ────────────────────
    def test_an_absent_helper_is_a_named_third_outcome(self):
        root = _scene(with_helper=False)
        expected = str(root / "spa_core" / "tests" / "_hermetic_launchd.py")
        verdict, detail = _ask(root)
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("НЕ ИЗМЕРЕНО", detail)
        self.assertIn(expected, detail, "причина не называет путь, которого нет")

    def test_an_absent_door_test_is_a_named_third_outcome(self):
        root = _scene(with_door_test=False)
        expected = str(root / "spa_core" / "tests" / "test_hermetic_launchd_door.py")
        verdict, detail = _ask(root)
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn(expected, detail)

    def test_a_census_that_cannot_be_imported_is_unmeasured_not_clean(self):
        """Перепись есть по пути, но ничего не отдаёт ⇒ НЕ ИЗМЕРЕНО.

        Подставить здесь «находок нет» значило бы выдать неизмеренное за
        чистое — ровно инв. #17.
        """
        verdict, detail = _ask(_scene(with_census=False))
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("перепись", detail)

    def test_unparsed_files_are_unmeasured_even_with_zero_hits(self):
        verdict, detail = _ask(_scene(
            hits=[], unparsed=["tests/test_broken.py: SyntaxError: x"]))
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("чистотой не является", detail)
        self.assertIn("test_broken.py", detail)

    def test_a_missing_WIRED_list_is_unmeasured_not_zero_sites(self):
        verdict, detail = _ask(_scene(door_test_body="def test_x():\n    pass\n"))
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("_WIRED", detail)

    def test_a_declared_site_absent_from_the_tree_is_unmeasured(self):
        root = _scene(wired=("tests/test_site.py",))
        (root / "tests" / "test_site.py").unlink()
        verdict, detail = _ask(root)
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("tests/test_site.py", detail)

    # ── второй исход: со-прогон НЕ зелён ────────────────────────────────────
    def test_a_red_corun_is_refused_and_not_unmeasured(self):
        verdict, detail = _ask(_scene(site_passes=False))
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("со-прогон", detail)

    def test_the_same_scene_with_a_GREEN_corun_is_satisfied(self):
        """Обратная половина предыдущего: красноту даёт ПРОГОН, а не сцена."""
        verdict, detail = _ask(_scene(site_passes=True))
        self.assertEqual(ca.SATISFIED, verdict, detail)

    # ── различитель: красен ИМЕННО тест двери, а не сайт ────────────────────
    #
    # Добавлено циклом #1220 по выжившей мутации («тест двери ВЫПАЛ из
    # со-прогона»). Прежние две сцены красили СЕБЯ сайтом, поэтому со-прогон был
    # красен и без теста двери — мутация не меняла набор упавших имён и выживала.
    # Авария, которую проба обязана ловить, устроена ИНАЧЕ: сайт зелен сам по
    # себе, а красен сосед, у которого сайт выбил дверь.
    _DOOR_TEST_IS_THE_RED_ONE = (
        '_WIRED = ("tests/test_site.py",)\n'
        "\n"
        "def test_the_door_itself_is_red_in_this_scene():\n"
        "    assert False, 'сцена: красен ИМЕННО тест двери, сайт зелен'\n")

    def test_a_corun_red_only_in_the_DOOR_test_is_refused(self):
        """Сайт зелен, красен тест двери ⇒ отказ. Убери дверь из со-прогона — и
        проба объявит `satisfied` на той самой аварии, ради которой написана."""
        verdict, detail = _ask(_scene(
            site_passes=True, door_test_body=self._DOOR_TEST_IS_THE_RED_ONE))
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("со-прогон", detail)
        self.assertIn("test_the_door_itself_is_red_in_this_scene", detail,
                      "отказ не называет, КТО покраснел в со-прогоне")

    def test_the_same_scene_with_a_GREEN_door_test_is_satisfied(self):
        """Обратная половина: та же форма сцены, дверь зелена ⇒ `satisfied`."""
        verdict, detail = _ask(_scene(
            site_passes=True,
            door_test_body=self._DOOR_TEST_IS_THE_RED_ONE.replace(
                "    assert False, 'сцена: красен ИМЕННО тест двери, сайт зелен'",
                "    assert True")))
        self.assertEqual(ca.SATISFIED, verdict, detail)

    # ── реестр и объявление ─────────────────────────────────────────────────
    def test_the_probe_is_registered_under_the_name_the_card_declares(self):
        self.assertIn(_PROBE, ca.PROBES)
        card = (_REPO_ROOT / "nimbalyst-local" / "tracker"
                / "inbox-vtoraya-dver-germetichnogo-launchd-pryam.md")
        self.assertTrue(card.exists(), f"карточка не найдена: {card}")
        self.assertIn(f"acceptance_probe: {_PROBE}",
                      card.read_text(encoding="utf-8"),
                      "карточка объявляет ДРУГОЙ критерий")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
