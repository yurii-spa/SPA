"""Проба приёмки `office_hollow_counter_means_harm` — контроль в обе стороны.

ADR-683, карточка `inbox-ofis-zovet-artefakt-prochitannym-vholost`.

Правило `.claude/rules/acceptance.md` п. 3 (ADR-333): новая проба регистрируется
ТОЛЬКО с тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном
звене — с названным звеном, — и где она НЕ проходит подстрокой. Батарея ниже —
ровно это; сцены одноразовые (`mkdtemp`), живое дерево не трогается.

Литеральных дат здесь нет вовсе: моменты сцены проба получает входом сама
(`now` объявлен внутри пробы и уведён в 2035 год), а вердикт пробы от календаря
машины не зависит — это проверяется отдельным тестом ниже.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest

from spa_core.monitoring import artifact_stamp_clock_doors as doors
from spa_core.monitoring import card_acceptance as ca

PROBE = "office_hollow_counter_means_harm"
OFFICE_REL = os.path.join("scripts", "consume_office_reports.py")
REPO = pathlib.Path(doors._ROOT)


def _run():
    return ca.PROBES[PROBE](None)


class _SceneBase(unittest.TestCase):
    """Сцена: одноразовое дерево с ОДНИМ файлом — исходником шага 0-офис.

    Подменяется `card_acceptance.REPO_ROOT`, потому что именно его читает проба.
    Живое дерево при этом не меняется ни на байт.
    """

    def _with_office(self, text: str):
        box = tempfile.mkdtemp(prefix="c821_probe_")
        self.addCleanup(shutil.rmtree, box, True)
        path = pathlib.Path(box) / OFFICE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        old = ca.REPO_ROOT
        ca.REPO_ROOT = box
        self.addCleanup(lambda: setattr(ca, "REPO_ROOT", old))
        return box

    @staticmethod
    def _office_source() -> str:
        return (REPO / OFFICE_REL).read_text(encoding="utf-8")

    @staticmethod
    def _cut_branch(src: str) -> str:
        head = src.index(f'    elif name == "{doors.ARTIFACT}":')
        tail = src.index("    elif name == ", head + 10)
        return src[:head] + src[tail:]


class TheProbeIsGreenOnTheWholeContour(_SceneBase):

    def test_the_live_tree_satisfies_the_probe(self):
        verdict, why = _run()
        self.assertEqual(verdict, ca.SATISFIED, why)
        # Вердикт обязан НАЗЫВАТЬ все четыре звена, иначе «satisfied» нечем
        # поверить: читатель увидит слово, а не замер.
        for token in ("вхолостую", "кусается", "дорога одна", "схема"):
            self.assertIn(token, why)

    def test_the_verdict_does_not_depend_on_the_wall_clock(self):
        """Проба о часах, судящая по стенным часам, — тот же дефект (ADR-562).

        Момент объявлен ВНУТРИ пробы и уведён от календаря; поэтому два зова
        в разные секунды обязаны давать один вердикт, а отметка сцены никогда
        не «протухает» сама.
        """
        self.assertEqual(_run()[0], _run()[0])


class TheProbeIsRedOnEachBrokenLink(_SceneBase):

    def test_link_1_the_branch_is_gone_so_the_read_is_hollow(self):
        self._with_office(self._cut_branch(self._office_source()))
        verdict, why = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 1", why)
        self.assertIn("ВХОЛОСТУЮ", why)

    def test_link_3_a_second_road_of_rendering_returns(self):
        """Предмет карточки дословно: дорог было ДВЕ, и счёт значил оба исхода."""
        src = self._office_source()
        # Вторая дорога ровно той формы, что была снята: зов отрисовщика по
        # имени в хвосте шага.
        src += "\n\ndef _second_road(data, now):\n    return _ascd_report(data, now=now)\n"
        self._with_office(src)
        verdict, why = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 3", why)
        self.assertIn("дорог отрисовки 2", why)

    def test_link_4_the_declared_schema_carries_an_invented_key(self):
        src = self._office_source().replace(
            f'"{doors.ARTIFACT}": ("adr", "order"',
            f'"{doors.ARTIFACT}": ("vydumannyi_klyuch", "order"', 1)
        self._with_office(src)
        verdict, why = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 4", why)
        self.assertIn("vydumannyi_klyuch", why)

    def test_link_4_the_artifact_is_not_declared_in_the_schema_at_all(self):
        src = self._office_source().replace(
            f'    "{doors.ARTIFACT}": ("adr", "order", "applied", "counts",',
            '    "nezanyatoe_imya.json": ("adr", "order", "applied", "counts",', 1)
        self._with_office(src)
        verdict, why = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 4", why)


class TheProbeDoesNotPassBySubstring(_SceneBase):
    """ADR-333: проба, проходящая по упоминанию имени, измеряет текст, не исход."""

    def test_merely_naming_the_artifact_in_a_comment_is_not_enough(self):
        src = self._cut_branch(self._office_source())
        src += (f"\n\n# {doors.ARTIFACT} — упомянут и только: ветки нет,\n"
                f"# `elif name == \"{doors.ARTIFACT}\"` здесь лишь текст.\n")
        self._with_office(src)
        verdict, why = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 1", why)


class TheProbeKeepsTheThirdOutcome(_SceneBase):
    """«Не измерено» никогда не выдаётся ни за «чисто», ни за находку (инв. #17)."""

    def test_no_office_source_is_unmeasured_not_clean(self):
        box = tempfile.mkdtemp(prefix="c821_probe_empty_")
        self.addCleanup(shutil.rmtree, box, True)
        old = ca.REPO_ROOT
        ca.REPO_ROOT = box
        self.addCleanup(lambda: setattr(ca, "REPO_ROOT", old))
        verdict, why = _run()
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕН", why)

    def test_an_unloadable_office_source_is_unmeasured(self):
        self._with_office("def broken(:\n")
        verdict, why = _run()
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕН", why)

    def test_the_probe_refuses_an_argument_it_cannot_honour(self):
        verdict, why = ca.PROBES[PROBE]("data/x.json")
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)


class TheProbeIsRegisteredSoTheQueueCanDeclareIt(unittest.TestCase):
    """Проба без регистрации измерять нечего не сможет: очередь берёт имена
    из реестра `PROBES`, а не из модуля."""

    def test_the_name_is_in_the_registry(self):
        self.assertIn(PROBE, ca.PROBES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
