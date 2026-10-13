# -*- coding: utf-8 -*-
"""Контроль пробы `drift_names_direction_of_record_loss` (цикл #859, ADR-715).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом,
где она зелена на целом контуре и КРАСНА НА КАЖДОМ ПОРВАННОМ ЗВЕНЕ — с названным
звеном, — и где она не проходит подстрокой (ADR-333).

Звенья контура, каждое ломается по одному и на ОДНОРАЗОВОЙ копии прибора:

1. прибора нет вовсе ⇒ третий исход;
2. у прибора нет оси памяти (`record_memory`) — ровно состояние origin/main до #859;
3. ось видит потерю 56 записей и НЕ считает её расхождением (fail-OPEN);
4. ось объявляет расхождение ЧЕМУ УГОДНО, включая чистую приписку к телу;
5. ось называет расхождение, но НЕ называет пропавшие номера;
6. пары байт аварии нет ни в истории, ни в фикстурах ⇒ третий исход;
7. в паре байт нет той самой потери ⇒ предпосылка НЕ ОБЕСПЕЧЕНА, третий исход.

Живое дерево не трогается: каждое звено ломается в `tempfile.mkdtemp()`, куда
копируются прибор, его сосед по разбору карточки и фикстуры. Времени в тестах нет.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

PROBE = "drift_names_direction_of_record_loss"
_ROOT = Path(__file__).resolve().parents[2]
_FIX_REL = os.path.join("spa_core", "tests", "fixtures", "cycle_record_loss")


def run(root: str):
    return ca.PROBES[PROBE](None, repo_root=root)


class Scene:
    """Одноразовая копия контура: прибор + фикстуры, живое дерево не тронуто."""

    def __init__(self, with_tool: bool = True, with_fixtures: bool = True):
        self.dir = tempfile.mkdtemp(prefix="probe_drift_mem_")
        os.mkdir(os.path.join(self.dir, "scripts"))
        # Сцена обязана быть НЕ-репозиторием на ЛЮБОМ хосте, а не там, где
        # временный каталог случайно лежит вне чужого `.git`: пустой `.git`
        # внутри делает `git -C <сцена>` отказом детерминированно, и проба
        # уходит на фикстуры по измеримой причине, а не по удаче с хостом
        # (тот же класс, что «личность процесса» в `.claude/rules/deployment.md`).
        os.mkdir(os.path.join(self.dir, ".git"))
        if with_tool:
            for name in ("check_tracker_drift.py", "check_card_claim.py"):
                shutil.copy2(_ROOT / "scripts" / name,
                             os.path.join(self.dir, "scripts", name))
        if with_fixtures:
            shutil.copytree(_ROOT / _FIX_REL, os.path.join(self.dir, _FIX_REL))

    @property
    def tool(self) -> Path:
        return Path(self.dir) / "scripts" / "check_tracker_drift.py"

    def break_link(self, old: str, new: str, where: str) -> None:
        text = self.tool.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"звено «{where}»: якорь не единственный"
        self.tool.write_text(text.replace(old, new, 1), encoding="utf-8")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class WholeCircuit(unittest.TestCase):

    def test_probe_is_registered(self):
        self.assertIn(PROBE, ca.PROBES)

    def test_green_on_the_whole_circuit(self):
        scene = Scene()
        self.addCleanup(scene.close)
        status, detail = run(scene.dir)
        self.assertEqual(status, ca.SATISFIED, detail)

    def test_the_source_of_the_pair_is_named(self):
        """Зелёный на фикстуре не должен читаться как зелёный на истории (инв. #17)."""
        scene = Scene()
        self.addCleanup(scene.close)
        _status, detail = run(scene.dir)
        self.assertIn("источник пары", detail)
        self.assertIn("фикстуры", detail, "в одноразовой копии истории git нет — "
                                          "проба обязана назвать, что взяла фикстуры")


class EachBrokenLinkIsRed(unittest.TestCase):

    def _red(self, scene: Scene, expect: str, where: str, status=None):
        got, detail = run(scene.dir)
        self.assertEqual(got, status or ca.NOT_SATISFIED,
                         f"звено «{where}» порвано, а проба ответила {got}: {detail}")
        self.assertIn(expect, detail, f"звено «{where}»: вердикт не назвал причину")

    def test_no_tool_is_the_third_outcome(self):
        scene = Scene(with_tool=False)
        self.addCleanup(scene.close)
        self._red(scene, "НЕ ИЗМЕРЕН", "прибора нет", status=ca.UNMEASURED)

    def test_no_memory_axis_at_all(self):
        """Состояние origin/main до #859: ось памяти у прибора отсутствует."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link("def record_memory(", "def record_memory_DISABLED(",
                         "оси памяти нет")
        self._red(scene, "нет оси памяти", "оси памяти нет")

    def test_axis_sees_the_loss_and_calls_it_no_divergence(self):
        """fail-OPEN: числа верные, вердикт успокоительный."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link("        return RecordMemory(MEMORY_FORKED,",
                         "        return RecordMemory(MEMORY_EQUAL,",
                         "ось не считает потерю расхождением")
        self._red(scene, "не считает потерю", "ось не считает потерю расхождением")

    def test_axis_declares_divergence_on_everything(self):
        """Ось, говорящая «потеря» всему, пробу удовлетворять НЕ ДОЛЖНА."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link("    return RecordMemory(MEMORY_EQUAL,\n"
                         '                        f"набор номеров записей цикла совпал',
                         "    return RecordMemory(MEMORY_TREE_POORER,\n"
                         '                        f"набор номеров записей цикла совпал',
                         "ось объявляет расхождение всему")
        self._red(scene, "ЧИСТОЙ ПРИПИСКЕ", "ось объявляет расхождение всему")

    def test_axis_does_not_name_the_missing_numbers(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link('    shown = ", ".join(one(k) for k in keys[:cap])',
                         '    shown = "(номера не называем)"',
                         "номера не называются")
        self._red(scene, "НЕ НАЗВАЛ", "номера не называются")

    def test_no_pair_of_bytes_is_the_third_outcome(self):
        scene = Scene(with_fixtures=False)
        self.addCleanup(scene.close)
        self._red(scene, "НЕ ИЗМЕРЕН", "пары байт нет", status=ca.UNMEASURED)

    def test_a_pair_without_the_loss_is_the_third_outcome(self):
        """Предпосылка НЕ ОБЕСПЕЧЕНА — это не «выполнено» и не «не выполнено»."""
        scene = Scene()
        self.addCleanup(scene.close)
        fix = Path(scene.dir) / _FIX_REL
        shutil.copy2(fix / "order_359ce9406_before.md", fix / "order_359ce9406_after.md")
        self._red(scene, "предпосылка пробы НЕ ОБЕСПЕЧЕНА", "в паре нет потери",
                  status=ca.UNMEASURED)


class NotBySubstring(unittest.TestCase):
    """ADR-333: проба меряет ИСХОД прибора, а не текст в файлах."""

    def test_the_words_of_the_verdict_in_a_file_do_not_satisfy_it(self):
        scene = Scene()
        self.addCleanup(scene.close)
        (Path(scene.dir) / "DECOY.md").write_text(
            "прибор НАЗЫВАЕТ направление потери: `records_forked`, дереву не хватает "
            "56 записей (поимённо)\n", encoding="utf-8")
        scene.break_link("        return RecordMemory(MEMORY_FORKED,",
                         "        return RecordMemory(MEMORY_EQUAL,",
                         "ось молчит, а слова вердикта лежат рядом в файле")
        status, _detail = run(scene.dir)
        self.assertEqual(status, ca.NOT_SATISFIED,
                         "проба позеленела от слов в файле, а не от поведения прибора")


if __name__ == "__main__":
    unittest.main()
