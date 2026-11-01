"""Положительный контроль ПРОБЫ `ci_red_census_names_the_population` (ADR-888).

`.claude/rules/acceptance.md` §3: новая проба регистрируется только с тестом, где она
**зелена на целом контуре** и **красна на КАЖДОМ порванном звене** — с названным звеном.
Проба, никогда не видевшая настоящей поломки, есть украшение.

Звенья здесь — настоящие: каждая сцена это ОДНОРАЗОВАЯ КОПИЯ читателя вердикта
(`scripts/ci_control_verdict.py`) с ровно одной снятой половиной, и проба гоняется на ней
через свой параметр `repo_root`. Живое дерево не трогается ни одной сценой: правка идёт в
копию, а `spa_core` подставляется ссылкой — иначе копия не ввезлась бы вовсе и проба
ответила бы `unmeasured`, то есть тест мерил бы свою сцену, а не пробу.

ТРЕТИЙ ИСХОД у пробы проверяется ОТДЕЛЬНО (инв. #17): дерево без читателя обязано дать
`unmeasured`, а НЕ «не выполнено» — иначе «прибора нет» стало бы неотличимо от «прибор
врёт», и починка выбиралась бы вслепую.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, SATISFIED, UNMEASURED,
                                                 PROBES)

_REPO = Path(__file__).resolve().parent.parent.parent
_PROBE = PROBES["ci_red_census_names_the_population"]
_READER = Path("scripts") / "ci_control_verdict.py"


class _Scene:
    """Одноразовое дерево с ОДНИМ порванным звеном. Живое дерево не трогается."""

    def __init__(self, test: unittest.TestCase, *, swap=None, drop_reader=False):
        self.root = Path(tempfile.mkdtemp(prefix="spa_c1003_red_census_"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "scripts").mkdir(parents=True)
        if not drop_reader:
            src = (_REPO / _READER).read_text(encoding="utf-8")
            if swap is not None:
                old, new = swap
                assert src.count(old) == 1, (
                    f"якорь звена не найден ровно один раз ({src.count(old)}): "
                    f"сцена НЕ ОБЕСПЕЧЕНА, и судить по ней о пробе нельзя")
                src = src.replace(old, new, 1)
            (self.root / _READER).write_text(src, encoding="utf-8")
        os.symlink(_REPO / "spa_core", self.root / "spa_core")

    def verdict(self):
        return _PROBE(None, repo_root=str(self.root))


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):
    """Целый контур — ЖИВОЕ дерево, а не копия: зелёный на копии не есть зелёный здесь."""

    def test_the_real_tree_satisfies_the_probe(self):
        status, detail = _PROBE(None)
        self.assertEqual(status, SATISFIED, detail)
        self.assertIn("население красного НАЗВАНО", detail)

    def test_an_untouched_copy_is_green_too_so_the_scenes_are_fair(self):
        """Обратная половина сцен: копия БЕЗ правки обязана быть зелёной, иначе
        каждая красная сцена ниже доказывала бы лишь то, что копия не работает."""
        status, detail = _Scene(self).verdict()
        self.assertEqual(status, SATISFIED, detail)


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Каждая сцена — своё звено, и у каждого отказа СВОИ слова."""

    def test_a_document_without_the_census_at_all(self):
        status, detail = _Scene(self, swap=(
            '        "red_census": rep["red_census"],\n', "")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не несёт ВОВСЕ", detail)

    def test_the_third_outcome_collapsed_into_a_measured_zero(self):
        """Дословный fail-OPEN инв. #17: «красное не названо» выдано за «красного нет»."""
        # Якорь обновлён под ADR-891: третий исход переписи теперь несёт и СВОЮ
        # причину для оси причин (у неё нет НОСИТЕЛЯ без перечня падений). Звено то же —
        # «unmeasured выдан за measured с нулём», — и утверждение не ослаблено.
        status, detail = _Scene(self, swap=(
            '        return {"status": "unmeasured", "why": why,\n',
            '        return {"status": "measured", "named": 0, "why": why,\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("третьего исхода", detail)

    def test_the_third_outcome_without_a_reason(self):
        status, detail = _Scene(self, swap=(
            '        why = (f"перечня `failures` у отчёта нет (там '
            '{type(raw).__name__}) — "\n               f"это НЕ «красного нет»")\n',
            '        why = ""\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ПРИЧИНЫ", detail)

    def test_the_population_disagreeing_with_the_scene(self):
        status, detail = _Scene(self, swap=(
            '        "subjects_multi": len(multi),\n',
            '        "subjects_multi": len(files),\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("разошлась со сценой", detail)

    def test_the_worst_file_not_named(self):
        status, detail = _Scene(self, swap=(
            '        "worst": [[f, c] for f, c in files.most_common(WORST_FILES)],\n',
            '        "worst": [],\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("худший файл не НАЗВАН", detail)

    def test_the_census_never_reaches_the_rendered_lines(self):
        """Предмет заказа: шаг 0-офис читает СТРОКИ, а не документ.

        Звено здесь — ЕДИНСТВЕННАЯ копия правила отрисовки (`census_line`), и это не
        стилистика. Первая редакция сцены снимала отдельную СТРОКУ отчёта и проба
        оставалась зелёной — ВЕРНО: перепись приезжала вторым носителем, самой
        находкой о красном наборе. Носителей два, копия правила одна, поэтому
        порванным звеном является копия, а не один из носителей.
        """
        status, detail = _Scene(self, swap=(
            '    return (f"перепись: названных {cen.get(\'named\')} в '
            '{cen.get(\'files\')} файл(ах) — "\n',
            '    return (f"упавших {cen.get(\'named\')}"  # имён не называем\n'
            '            f""\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ОТРИСОВАННЫХ строках", detail)

    def test_the_cross_check_compares_the_naming_with_itself(self):
        status, detail = _Scene(self, swap=(
            '    cross = (sum(1 for v in non_passed.values() if v in RED_OUTCOMES)\n',
            '    cross = (0\n')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("cross_named", detail)


class TheProbeKeepsItsOwnThirdOutcome(unittest.TestCase):
    """«Прибора нет» и «прибор врёт» чинятся разным, и слить их нельзя."""

    def test_a_tree_without_the_reader_is_unmeasured_not_unsatisfied(self):
        status, detail = _Scene(self, drop_reader=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕН", detail)

    def test_an_unimportable_reader_is_unmeasured_too(self):
        status, detail = _Scene(self, swap=(
            "from __future__ import annotations\n",
            "from __future__ import annotations\nraise RuntimeError('сцена')\n")).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("не ввезён", detail)


if __name__ == "__main__":
    unittest.main()
