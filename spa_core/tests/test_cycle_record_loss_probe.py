# -*- coding: utf-8 -*-
"""Контроль пробы `delivery_door_refuses_cycle_record_loss` (цикл #858, ADR-714).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом,
где она зелена на целом контуре и КРАСНА НА КАЖДОМ ПОРВАННОМ ЗВЕНЕ — с названным
звеном, — и где она не проходит подстрокой (ADR-333).

Звенья контура, каждое ломается по одному и на ОДНОРАЗОВОЙ копии пушера:

1. дверь не зовёт проверку записей цикла;
2. проверка молчит вместо отказа (fail-OPEN);
3. проверка отказывает ЧЕМУ УГОДНО (в том числе чистому дописыванию);
4. отказ не называет пропавшие записи;
5. пушера нет вовсе ⇒ третий исход;
6. пары байт аварии нет ни в истории, ни в фикстурах ⇒ третий исход;
7. в паре байт нет той самой потери ⇒ предпосылка НЕ ОБЕСПЕЧЕНА, третий исход.

Живое дерево не трогается: каждое звено ломается в `tempfile.mkdtemp()`, куда
копируются пушер и фикстуры. Времени в тестах нет.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

PROBE = "delivery_door_refuses_cycle_record_loss"
_ROOT = Path(__file__).resolve().parents[2]
_FIX_REL = os.path.join("spa_core", "tests", "fixtures", "cycle_record_loss")


def run(root: str):
    return ca.PROBES[PROBE](None, repo_root=root)


class Scene:
    """Одноразовая копия контура: пушер + фикстуры, живое дерево не тронуто."""

    def __init__(self, with_pusher: bool = True, with_fixtures: bool = True):
        self.dir = tempfile.mkdtemp(prefix="probe_cycle_rec_")
        # Сцена обязана быть НЕ-репозиторием на ЛЮБОМ хосте, а не там, где
        # временный каталог случайно лежит вне чужого `.git`: пустой `.git`
        # внутри делает `git -C <сцена>` отказом детерминированно, и проба
        # уходит на фикстуры по измеримой причине, а не по удаче с хостом
        # (тот же класс, что «личность процесса» в `.claude/rules/deployment.md`).
        os.mkdir(os.path.join(self.dir, ".git"))
        if with_pusher:
            shutil.copy2(_ROOT / "push_to_github.py",
                         os.path.join(self.dir, "push_to_github.py"))
        if with_fixtures:
            dst = os.path.join(self.dir, _FIX_REL)
            shutil.copytree(_ROOT / _FIX_REL, dst)

    @property
    def pusher(self) -> Path:
        return Path(self.dir) / "push_to_github.py"

    def break_link(self, old: str, new: str, where: str) -> None:
        text = self.pusher.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"звено «{where}»: якорь не единственный"
        self.pusher.write_text(text.replace(old, new, 1), encoding="utf-8")

    def mute_section_guard(self) -> None:
        """Погасить ВТОРУЮ единицу смысла карточки (разделы, ADR-729).

        После #874 ту же пару байт аварии 08.10 держат ДВЕ проверки: записи
        цикла и разделы. Тест, который мерит ПЕРВУЮ, обязан гасить вторую —
        иначе отказ приходит от соседа, звено остаётся ненаблюдаемым, и проба
        «зелена» не потому, что проверка цела (урок цикла #873 о сцене, где
        граница заявлена, но не наблюдаема).
        """
        self.break_link(
            '    if allow_overwrite or not is_tracker_card(repo_path):\n'
            '        return ""\n'
            "    if is_generated_tracker_doc(repo_path):",
            '    if True:\n        return ""\n'
            "    if is_generated_tracker_doc(repo_path):",
            "вторая единица смысла (разделы) погашена намеренно")

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

    def test_door_does_not_call_the_guard(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.mute_section_guard()
        # ⚠️ ИНВ. #16, намеренная правка чужого теста (цикл #874, ADR-729).
        # Якорь обновлён: в списке диспетчера за вызовом цикловой записи теперь
        # стои́т ВТОРОЙ вызов (разделы карточки), поэтому прежний хвост `)]`
        # у этой строки больше не стои́т. Разрыв и утверждение те же — дверь
        # перестаёт звать проверку ЗАПИСЕЙ ЦИКЛА.
        scene.break_link(
            "             guard_cycle_record_loss(repo_path, remote_bytes, content_bytes,\n"
            "                                     remote_sha, allow_overwrite=allow_overwrite),",
            "            ", "дверь не зовёт проверку")
        self._red(scene, "ПРОПУСКАЕТ", "дверь не зовёт проверку")

    def test_guard_stays_silent_instead_of_refusing(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.mute_section_guard()
        scene.break_link(
            "    raise CycleRecordLossRefused(\n"
            '        f"{repo_path}: пуш стёр бы {len(nums)} запис(ь/и) ЦИКЛА',
            "    return \"\" if True else RuntimeError(\n"
            '        f"{repo_path}: пуш стёр бы {len(nums)} запис(ь/и) ЦИКЛА',
            "проверка молчит вместо отказа")
        self._red(scene, "ПРОПУСКАЕТ", "проверка молчит вместо отказа")

    def test_guard_refuses_everything(self):
        """Сторож, говорящий «нет» всему, пробу удовлетворять НЕ ДОЛЖЕН."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            '    if allow_overwrite or not is_tracker_card(repo_path):\n        return ""\n'
            "    if remote_sha is None:",
            '    if allow_overwrite or not is_tracker_card(repo_path):\n        return ""\n'
            "    if is_tracker_card(repo_path):\n"
            "        raise CycleRecordLossRefused(\n"
            "            f\"{repo_path}: отказываю всему, и записи называю: #716\")\n"
            "    if remote_sha is None:",
            "проверка отказывает чему угодно")
        self._red(scene, "ЧИСТОМУ ДОПИСЫВАНИЮ", "проверка отказывает чему угодно")

    def test_refusal_does_not_name_the_records(self):
        scene = Scene()
        self.addCleanup(scene.close)
        # ⚠️ ИНВ. #16 (цикл #874): та же строка печаталась и у сторожа разделов,
        # поэтому якорь перестал быть единственным. У разделов она теперь
        # `  ! разделы: …`, и этот якорь снова указывает РОВНО на запись цикла.
        scene.break_link(
            '        f"  ! {shown}{more}\\n"\n'
            '        f"  + появилось взамен: {new_named}\\n"\n'
            '        f"  объём файла: {delta:+d} строк(и) НЕТТО к remote.\\n"',
            '        f"  ! (записи не называем)\\n"',
            "отказ не называет записи")
        self._red(scene, "НЕ НАЗВАЛА", "отказ не называет записи")

    def test_no_pusher_is_the_third_outcome(self):
        scene = Scene(with_pusher=False)
        self.addCleanup(scene.close)
        self._red(scene, "НЕ ИЗМЕРЕНА", "пушера нет", status=ca.UNMEASURED)

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
    """ADR-333: проба меряет ИСХОД двери, а не текст в файлах."""

    def test_the_words_of_the_verdict_in_a_file_do_not_satisfy_it(self):
        scene = Scene()
        self.addCleanup(scene.close)
        (Path(scene.dir) / "DECOY.md").write_text(
            "дверь ОТКАЗЫВАЕТ доставке, стирающей 56 записей цикла\n", encoding="utf-8")
        scene.mute_section_guard()
        scene.break_link(
            "    raise CycleRecordLossRefused(\n"
            '        f"{repo_path}: пуш стёр бы {len(nums)} запис(ь/и) ЦИКЛА',
            "    return \"\" if True else RuntimeError(\n"
            '        f"{repo_path}: пуш стёр бы {len(nums)} запис(ь/и) ЦИКЛА',
            "проверка молчит, а слова вердикта лежат рядом в файле")
        status, _detail = run(scene.dir)
        self.assertEqual(status, ca.NOT_SATISFIED,
                         "проба позеленела от слов в файле, а не от поведения двери")


if __name__ == "__main__":
    unittest.main()
