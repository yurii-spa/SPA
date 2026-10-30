"""ADR-789 · ADR-872 — контроль пробы приёмки `publication_gate_refuses_an_unsigned_shelf_by_its_own_code`.

Правило `.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом, где
она зелена на целом контуре и красна на КАЖДОМ порванном звене — с названным звеном, — и где
она НЕ проходит подстрокой. Проба, никогда не видевшая настоящей поломки, есть украшение.

Поломка, которую эта проба видела: 17.10 ADR-772 поставил отказ по окну мутационного прибора
перед воротами публикации, а сцена объявленного сторожа предмета лежала ВНЕ любого рабочего
дерева ⇒ сторож шесть суток мерил не свой предмет, и красный на `main` говорил не о том, что
на нём написано. Звено «сцена не есть рабочее дерево» ниже воспроизводит её дословно.

ADR-872 добавил ТРЕТЬЮ сцену и ДВА её звена. Поломка, которую видела третья сцена: до неё
исход **FAIL** ворот публикации («витрина схемно-верна, но НЕ ПОДПИСАНА владельцем») не мерила
НИ ОДНА проба — сцена заглушки обрывает ворота раньше, на разборе дат, и ADR-871 назвал это
границей вслух. Пока граница стояла, вердикт `satisfied` НЕ ВЛЁК «FAIL измерен»; теперь влечёт.
"""
# Литеральных якорей времени в этом файле нет ВООБСЕ, поэтому и освобождения
# `FROZEN-DATE-OK` здесь нет: пометка без якоря сама есть неверное утверждение, и сторож
# `test_injected_clock_claim.py` назвал её, когда я поставил её по инерции. Отметку окна
# прибора принимает входом (`now=`) соседний файл сцены, а не этот.
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.monitoring import card_acceptance as ca

PROBE_NAME = "publication_gate_refuses_an_unsigned_shelf_by_its_own_code"
GUARD_NODE = "spa_core/tests/test_publication_truth.py::BothPushersRunThePublicationGate"


class TheProbeIsRegisteredUnderItsOwnName(unittest.TestCase):

    def test_the_registry_knows_it(self):
        self.assertIn(PROBE_NAME, ca.PROBES)


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):

    def test_all_three_doors_scenes_and_the_guard(self):
        state, detail = ca.PROBES[PROBE_NAME](None)
        self.assertEqual(state, ca.SATISFIED, detail)
        # Вердикт обязан НАЗЫВАТЬ все три исхода ворот и сторожа: «satisfied» без них
        # нечем поверить.
        #
        # НАМЕРЕННОЕ изменение набора токенов, с обоснованием (инв. #16). Ушёл токен
        # «НАЗВАННАЯ ГРАНИЦА»: он требовал, чтобы проба ПРИЗНАВАЛАСЬ в неизмеренном
        # исходе FAIL, и был верен ровно до ADR-872, который этот исход ИЗМЕРИЛ третьей
        # сценой. Требовать признание дальше значило бы требовать обратно сам пробел.
        # Взамен пришли токены, которых прежняя проба дать НЕ МОГЛА: «ТРИ сцены» и
        # дословная развязка трёх исходов «FAIL → 3, НЕ ИЗМЕРЕНО → 13, окно прибора →
        # 10». Требование СТРОЖЕ прежнего: прежний набор зеленел и на двух сценах.
        for token in ("ТРИ сцены", "КОД ИСХОДА ворот", "код 10",
                      "FAIL → 3", "НЕ ИЗМЕРЕНО → 13", "окно прибора → 10",
                      "рабочее дерево", GUARD_NODE):
            self.assertIn(token, detail)


class TheProbeIsRedOnEachBrokenLink(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и вердикт обязан назвать именно его."""

    def test_a_scene_outside_a_working_tree_reddens_it(self):
        """Звено 1 — предпосылка сцены. Это дословная авария 17.10–23.10."""
        state, detail = ca.PROBES[PROBE_NAME](None, scene_outside_a_tree=True)
        self.assertEqual(state, ca.NOT_SATISFIED, detail)
        self.assertIn("а не кодом ворот публикации", detail)

    def test_a_door_that_is_not_on_disk_is_unmeasured_not_clean(self):
        """Звено 2 — население дверей. Отсутствие двери есть ТРЕТИЙ исход (инв. #17)."""
        state, detail = ca.PROBES[PROBE_NAME](None, pushers=("push_to_github.py",
                                                            "no_such_door.py"))
        self.assertEqual(state, ca.UNMEASURED, detail)
        self.assertIn("no_such_door.py", detail)

    def test_an_empty_population_of_doors_is_unmeasured(self):
        """Звено 3 — пустое население. Ноль сравнений не есть «ослаблений ноль» (ADR-468)."""
        state, detail = ca.PROBES[PROBE_NAME](None, pushers=())
        self.assertEqual(state, ca.UNMEASURED, detail)

    def test_a_door_that_does_not_refuse_with_the_gates_code_reddens_it(self):
        """Звено 4 — проба НЕ проходит подстрокой: она требует ИСХОДА запуска.
        Подставлен существующий файл репозитория, который дверью доставки не является, —
        и проба обязана сказать, каким кодом он ответил вместо кода ворот."""
        state, detail = ca.PROBES[PROBE_NAME](
            None, pushers=("scripts/verify_publication.py",))
        self.assertEqual(state, ca.NOT_SATISFIED, detail)
        self.assertIn("а не кодом ворот публикации", detail)

    def test_a_red_guard_reddens_it_even_when_the_subject_itself_holds(self):
        """Звено 5 — САМО открытие ADR-789: предмет и его сторож суть два утверждения.
        Двери отказывают верно (звенья 1–2 зелены), а сторож красен — и проба обязана
        сказать `not_satisfied`, а не зачесть предмет за сторожа."""
        d = pathlib.Path(tempfile.mkdtemp(prefix="probe_guard_red_"))
        self.addCleanup(__import__("shutil").rmtree, d, ignore_errors=True)
        stand = d / "test_stand_in_guard.py"
        stand.write_text(
            "def test_the_guard_of_this_subject_is_red():\n"
            "    assert False, 'стенд: сторож предмета красен'\n", encoding="utf-8")
        state, detail = ca.PROBES[PROBE_NAME](None, guard_test=str(stand))
        self.assertEqual(state, ca.NOT_SATISFIED, detail)
        self.assertIn("сторож", detail)

    def test_a_conscious_bypass_of_the_window_removes_half_the_measurement_and_it_says_so(self):
        """Звено 7 — нога про окно прибора. Без этого контроля она была бы НЕВИДИМА
        мутациям: итоговая строка вердикта называет «код 10» сама по себе, и снятая нога
        сверялась бы СО СВОЕЙ ЖЕ строкой (класс «строки контракта сверяются сами с собой»).
        Здесь обход объявлен входом, дверь идёт дальше к воротам публикации, и проба обязана
        сказать, что второй половины замера больше нет."""
        state, detail = ca.PROBES[PROBE_NAME](None, window_bypass=True)
        self.assertEqual(state, ca.NOT_SATISFIED, detail)
        self.assertIn("а не 10", detail)

    def test_a_stub_shelf_on_the_third_scene_is_unmeasured_not_clean(self):
        """Звено 8 (ADR-872) — предпосылка ТРЕТЬЕЙ сцены. Положи на неё ту же заглушку,
        что на первой, и ворота обрываются на разборе дат: исход FAIL этой сценой НЕ
        ИЗМЕРЕН. Проба обязана сказать `unmeasured` с причиной, а не зачесть сцену
        зелёной — иначе «не измерено» снова стало бы неотличимо от «измерено и чисто»
        (инв. #17), то есть вернулся бы предмет ADR-871 на шаг глубже."""
        state, detail = ca.PROBES[PROBE_NAME](None, fail_scene_shelf_stub=True)
        self.assertEqual(state, ca.UNMEASURED, detail)
        self.assertIn("сцена FAIL НЕ ПОДНЯТА", detail)

    def test_the_door_must_tell_FAIL_from_NOT_MEASURED_on_the_third_scene(self):
        """Звено 9 (ADR-872) — РАЗЛИЧИМОСТЬ исходов У ДВЕРИ, и это главное звено третьей
        сцены. Опубликованная витрина подменена несуществующим путём ⇒ ворота отвечают
        «НЕ ИЗМЕРЕНО»; контроль всё равно зовёт дверь и ждёт от неё код FAIL. Исправная
        дверь отвечает 13 ⇒ `not_satisfied`.

        Почему без этого звена третья нога была бы украшением: сведи дверь оба исхода в
        ОДИН код (дословно дефект ADR-869/871) — и этот контроль ПОЗЕЛЕНЕЕТ, а значит
        покраснеет здесь. Проверка, которая краснеет, когда предмет цел, и зеленеет,
        когда предмет сломан, — единственная форма, которой не хватало прежней ноге:
        её итоговая строка называла «код 10» сама по себе и сверялась СО СВОЕЙ ЖЕ
        строкой."""
        state, detail = ca.PROBES[PROBE_NAME](None, fail_scene_published_unreadable=True)
        self.assertEqual(state, ca.NOT_SATISFIED, detail)
        self.assertIn("а не 3 — кодом исхода FAIL", detail)

    def test_a_guard_node_that_matches_nothing_is_unmeasured(self):
        """Звено 6 — «сторожа не нашли» не выдаётся за «сторож зелёный»: ноль собранных
        тестов есть НЕ ИЗМЕРЕНО, и ровно этим зеленел `pyflakes`-храповик (#465)."""
        state, detail = ca.PROBES[PROBE_NAME](
            None, guard_test=GUARD_NODE + "::no_such_test_name")
        self.assertEqual(state, ca.UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕНО", detail)


if __name__ == "__main__":
    unittest.main()
