# -*- coding: utf-8 -*-
"""Контроль пробы `delivery_door_refuses_card_section_loss` (цикл #874, ADR-729).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом,
где она зелена на целом контуре и КРАСНА НА КАЖДОМ ПОРВАННОМ ЗВЕНЕ — с названным
звеном, — и где она не проходит подстрокой (ADR-333).

Звенья контура, каждое ломается по одному и на ОДНОРАЗОВОЙ копии пушера:

1. дверь не зовёт проверку разделов карточки;
2. проверка молчит вместо отказа (fail-OPEN);
3. ВТОРАЯ улика не спрашивается — отказ наступает и на выросшей карточке
   (а это форма КАЖДОГО цикла: `--allow-overwrite` ежедневно есть лазейка под рукой);
4. «пропал, но файл вырос» замолчано вместо того, чтобы быть НАЗВАННЫМ (инв. #17);
5. отказ не называет пропавшие разделы;
6. производная доска не исключена (её заголовки несут живой счётчик);
7. мера разделов есть, а перечня производных индексов нет;
8. пушера нет вовсе ⇒ третий исход;
9. пары байт нет ни в истории, ни в фикстурах ⇒ третий исход;
10. в паре нет той потери ⇒ предпосылка НЕ ОБЕСПЕЧЕНА, третий исход;
11. сцену видит и ПРЕЖНЯЯ мера (записи цикла) ⇒ НОВЫЙ класс ею не измерить.

Живое дерево не трогается: каждое звено ломается в `tempfile.mkdtemp()`, куда
копируются пушер и фикстуры. Времени в тестах нет.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

PROBE = "delivery_door_refuses_card_section_loss"
_ROOT = Path(__file__).resolve().parents[2]
_FIX_REL = os.path.join("spa_core", "tests", "fixtures", "card_section_loss")


def run(root: str):
    return ca.PROBES[PROBE](None, repo_root=root)


class Scene:
    """Одноразовая копия контура: пушер + фикстуры, живое дерево не тронуто."""

    def __init__(self, with_pusher: bool = True, with_fixtures: bool = True):
        self.dir = tempfile.mkdtemp(prefix="probe_card_sec_")
        # Сцена обязана быть НЕ-репозиторием на ЛЮБОМ хосте: пустой `.git`
        # внутри делает `git -C <сцена>` отказом детерминированно, и проба
        # уходит на фикстуры по измеримой причине, а не по удаче с хостом
        # (тот же класс, что «личность процесса» в `.claude/rules/deployment.md`).
        os.mkdir(os.path.join(self.dir, ".git"))
        if with_pusher:
            shutil.copy2(_ROOT / "push_to_github.py",
                         os.path.join(self.dir, "push_to_github.py"))
        if with_fixtures:
            shutil.copytree(_ROOT / _FIX_REL, os.path.join(self.dir, _FIX_REL))

    @property
    def pusher(self) -> Path:
        return Path(self.dir) / "push_to_github.py"

    def break_link(self, old: str, new: str, where: str) -> None:
        text = self.pusher.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"звено «{where}»: якорь не единственный"
        self.pusher.write_text(text.replace(old, new, 1), encoding="utf-8")

    def drop_block(self, start: str, end: str) -> None:
        """Снять блок правки целиком — воспроизвести состояние ДО неё."""
        text = self.pusher.read_text(encoding="utf-8")
        i, j = text.find(start), text.find(end)
        assert 0 < i < j, "границы блока правки не найдены"
        self.pusher.write_text(text[:i] + text[j:], encoding="utf-8")

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
        self.assertIn("Источник пары", detail)
        self.assertIn("фикстуры", detail, "в одноразовой копии истории git нет — "
                                          "проба обязана назвать, что взяла фикстуры")

    def test_the_old_measure_is_silent_on_this_scene(self):
        """Зелёный обязан означать «виден НОВЫЙ класс», а не «виден хоть какой-то»."""
        scene = Scene()
        self.addCleanup(scene.close)
        _status, detail = run(scene.dir)
        self.assertIn("Прежняя мера", detail)


class TheNameOfTheBoardMatchesItsGenerator(unittest.TestCase):
    """Исключение производного индекса объявлено ОДНИМ именем, а не двумя копиями.

    Пушер исключает доску по БАЗОВОМУ ИМЕНИ, а имя это рождается в генераторе
    (`scripts/build_tracker_board.py`, `OUT`). Разойдись они — исключение
    перестанет совпадать с тем, что генератор пишет, и сторож либо начнёт
    краснеть на каждой перегенерации, либо замолчит на настоящей карточке.
    Сверяем литерал пушера с литералом генератора, а не с третьей копией из
    головы.
    """

    def test_pusher_excludes_exactly_what_the_generator_writes(self):
        import importlib.util as ilu
        import re

        spec = ilu.spec_from_file_location("_pusher_board", _ROOT / "push_to_github.py")
        pusher = ilu.module_from_spec(spec)
        spec.loader.exec_module(pusher)
        gen = (_ROOT / "scripts" / "build_tracker_board.py").read_text(encoding="utf-8")
        match = re.search(r'^OUT\s*=\s*TRACKER\s*/\s*"([^"]+)"', gen, re.M)
        self.assertIsNotNone(match, "у генератора доски нет объявления `OUT` — имя "
                                    "исключения сверить НЕЧЕМ (это не «совпало»)")
        self.assertEqual(tuple(pusher.GENERATED_TRACKER_DOCS), (match.group(1),))
        self.assertTrue(pusher.is_generated_tracker_doc(
            f"nimbalyst-local/tracker/{match.group(1)}"))
        self.assertFalse(pusher.is_generated_tracker_doc(
            "nimbalyst-local/tracker/inbox-ordinary-card.md"))


class EachBrokenLinkIsRed(unittest.TestCase):

    def _red(self, scene: Scene, expect: str, where: str, status=None):
        got, detail = run(scene.dir)
        self.assertEqual(got, status or ca.NOT_SATISFIED,
                         f"звено «{where}» порвано, а проба ответила {got}: {detail}")
        self.assertIn(expect, detail, f"звено «{where}»: вердикт не назвал причину")

    def test_door_does_not_call_the_guard(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            "             guard_card_section_loss(repo_path, remote_bytes, content_bytes,\n"
            "                                     remote_sha, allow_overwrite=allow_overwrite)]",
            "             ]", "дверь не зовёт проверку")
        self._red(scene, "ПРОПУСКАЕТ", "дверь не зовёт проверку")

    def test_guard_stays_silent_instead_of_refusing(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            "    raise CardSectionLossRefused(\n"
            '        f"{repo_path}: пуш стёр бы {len(lost)} раздел(ов) карточки',
            '    return "" if True else RuntimeError(\n'
            '        f"{repo_path}: пуш стёр бы {len(lost)} раздел(ов) карточки',
            "проверка молчит вместо отказа")
        self._red(scene, "ПРОПУСКАЕТ", "проверка молчит вместо отказа")

    def test_the_second_clue_is_not_asked(self):
        """Отказ без второй улики краснеет на КАЖДОМ цикле — это лазейка, не защита."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link("    if delta >= 0:\n", "    if False:\n",
                         "вторая улика (усадка) не спрашивается")
        self._red(scene, "лазейку под рукой", "вторая улика не спрашивается")

    def test_guard_refuses_everything(self):
        """Сторож, говорящий «нет» всему, пробу удовлетворять НЕ ДОЛЖЕН.

        Отказ намеренно НЕСЁТ В СЕБЕ текст remote — то есть проходит и проверку
        «отказ назвал пропавшие разделы». Отличить защиту от «нет всему» можно
        только ОБРАТНОЙ стороной: чистое дописывание обязано пройти.
        """
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            '    if is_generated_tracker_doc(repo_path):\n'
            '        return ""                        # производный индекс',
            '    if is_tracker_card(repo_path) and remote_bytes:\n'
            '        raise CardSectionLossRefused(\n'
            '            f"{repo_path}: отказываю всему, и разделы называю: "\n'
            '            + remote_bytes.decode("utf-8", "replace")[:4000])\n'
            '    if is_generated_tracker_doc(repo_path):\n'
            '        return ""                        # производный индекс',
            "сторож отказывает чему угодно")
        self._red(scene, "ЧИСТОМУ ДОПИСЫВАНИЮ", "сторож отказывает чему угодно")

    def test_guard_cries_loss_when_there_is_none(self):
        """Нота на КАЖДОМ пуше — не защита, а шум: её перестанут читать.

        Ломается ветка «терять нечего»: сторож начинает говорить о потере там,
        где её нет. Отказа при этом нет, поэтому ловит это звено ровно проверка
        «на чистом дописывании дверь МОЛЧИТ», а не разбор исключения.
        """
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            '    if not lost:\n        if not renamed:\n            return ""',
            '    if not lost:\n        if not renamed:\n'
            '            return f"🔎 {repo_path}: скажу о потере на всякий случай"',
            "сторож говорит о потере, когда терять нечего")
        self._red(scene, "не молчит", "сторож говорит о потере, когда терять нечего")

    def test_growth_case_is_silenced_instead_of_named(self):
        """«Не блокирует» не значит «не называть» (инв. #17)."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            '        return (f"🔎 {repo_path}: разделов с remote (sha {remote_sha[:8]}) '
            'не найдено в "',
            '        return "" if True else (f"🔎 {repo_path}: разделов не найдено в "',
            "исход «пропал, но вырос» замолчан")
        self._red(scene, "ПРОМОЛЧАЛА", "исход «пропал, но вырос» замолчан")

    def test_refusal_does_not_name_the_sections(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            '        f"  ! разделы: {shown}{more}\\n"\n'
            '        f"  + появилось взамен: {new_named}\\n"\n'
            '        f"Так 07.10 `2427751a6` унёс разделы с ШЕСТИ карточек ВЛАДЕЛЬЦА (у "',
            '        f"  ! (разделы не называем)\\n"\n'
            '        f"Так 07.10 `2427751a6` унёс разделы с ШЕСТИ карточек ВЛАДЕЛЬЦА (у "',
            "отказ не называет разделы")
        self._red(scene, "НЕ НАЗВАЛА", "отказ не называет разделы")

    def test_generated_board_is_not_excluded(self):
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            "    if is_generated_tracker_doc(repo_path):\n"
            '        return ""                        # производный индекс',
            '    if False:\n        return ""                        # производный индекс',
            "производная доска не исключена")
        # Снятое исключение даёт ОТКАЗ на доске (а не ноту) — проба обязана
        # назвать именно это: доска краснела бы на каждой перегенерации.
        self._red(scene, "производной доске", "производная доска не исключена")

    def test_the_list_of_generated_docs_is_gone(self):
        """Мера разделов есть, а перечня исключений нет — отказ на каждой доске."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link('GENERATED_TRACKER_DOCS = ("_BOARD.md",)',
                         '_GENERATED_TRACKER_DOCS_RENAMED = ("_BOARD.md",)',
                         "перечня производных индексов нет")
        got, detail = run(scene.dir)
        self.assertIn(got, (ca.NOT_SATISFIED, ca.UNMEASURED), detail)
        self.assertNotEqual(got, ca.SATISFIED, detail)

    def test_a_pusher_without_the_measure_passes_the_loss(self):
        """Состояние ЧИСТОЙ ВЕРШИНЫ: меры разделов нет ⇒ дверь потерю ПРОПУСКАЕТ.

        Это положительный контроль пробы на состоянии ДО правки, и он обязан
        быть `not_satisfied`, а НЕ `unmeasured`: дверь зовётся, пара измерима,
        дефект виден прямо. Объявить тут «не измерено» значило бы спрятать
        измеримый дефект за третьим исходом (урок цикла #465). Замер на
        НАСТОЯЩЕЙ вершине `600396578` дал дословно этот вердикт.
        """
        scene = Scene()
        self.addCleanup(scene.close)
        scene.drop_block("# КАРТОЧКА БЕЗ ЗАПИСЕЙ ЦИКЛА",
                         "def guard_content_loss(repo_path: str")
        scene.break_link(
            "             guard_card_section_loss(repo_path, remote_bytes, content_bytes,\n"
            "                                     remote_sha, allow_overwrite=allow_overwrite)]",
            "             ]", "правки нет вовсе — состояние чистой вершины")
        self._red(scene, "меры разделов у пушера НЕТ ВОВСЕ", "меры разделов нет")

    def test_a_crashing_door_is_not_counted_as_a_refusal(self):
        """Поломка защитой не является: исключение вне класса отказов ≠ отказ."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link("CARD_SECTION_RE = re.compile",
                         "_CARD_SECTION_RE_RENAMED = re.compile",
                         "дверь падает вместо вердикта")
        self._red(scene, "УПАЛА, а не отказала", "дверь падает вместо вердикта")

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
        shutil.copy2(fix / "owner_2427751a6_before.md", fix / "owner_2427751a6_after.md")
        self._red(scene, "предпосылка пробы НЕ ОБЕСПЕЧЕНА", "в паре нет потери",
                  status=ca.UNMEASURED)

    def test_a_scene_the_old_measure_already_sees_is_the_third_outcome(self):
        """Зелёный от ПРЕЖНЕЙ меры не есть зелёный за новый класс."""
        scene = Scene()
        self.addCleanup(scene.close)
        scene.break_link(
            'CYCLE_RECORD_RE = re.compile(\n'
            '    "^#{2,4}[ \\t]*(?:ЦИКЛ|Цикл|цикл)[ \\t]*#(?P<id>\\\\d+)".encode("utf-8"), re.M)',
            'CYCLE_RECORD_RE = re.compile(rb"^#{2,4}[ \\t]+\\S.*$", re.M)',
            "прежняя мера видит ту же сцену")
        self._red(scene, "ПРЕЖНЯЯ мера", "прежняя мера видит ту же сцену",
                  status=ca.UNMEASURED)


class NotBySubstring(unittest.TestCase):
    """ADR-333: проба меряет ИСХОД двери, а не текст в файлах."""

    def test_the_words_of_the_verdict_in_a_file_do_not_satisfy_it(self):
        scene = Scene()
        self.addCleanup(scene.close)
        (Path(scene.dir) / "DECOY.md").write_text(
            "дверь ОТКАЗЫВАЕТ доставке, стирающей 4 разделов карточки владельца\n",
            encoding="utf-8")
        scene.break_link(
            "    raise CardSectionLossRefused(\n"
            '        f"{repo_path}: пуш стёр бы {len(lost)} раздел(ов) карточки',
            '    return "" if True else RuntimeError(\n'
            '        f"{repo_path}: пуш стёр бы {len(lost)} раздел(ов) карточки',
            "проверка молчит, а слова вердикта лежат рядом в файле")
        status, _detail = run(scene.dir)
        self.assertEqual(status, ca.NOT_SATISFIED,
                         "проба позеленела от слов в файле, а не от поведения двери")


if __name__ == "__main__":
    unittest.main()
