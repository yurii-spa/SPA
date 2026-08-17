"""Текст сообщения — не вызов: положительные контроли к храповику (цикл #258).

**Авария, которую эти тесты воспроизводят.** `spa_core/tests/_unwired.py` считал
проводкой ЛЮБОЕ вхождение `<имя>.py` в неотрезанный текст файла — в том числе внутри
строки, которую программа ПЕЧАТАЕТ человеку. Поймано циклом #257 своим же падением:
подсказка шага 0a ``out.append(f"убирать за собой обязан `scripts/reap_stale_worktrees.py
--worktree …`")`` мгновенно объявила уборщик ПОДКЛЮЧЁННЫМ, хотя вызывать его по-прежнему
некому. Одной строки в тексте подсказки хватало, чтобы навсегда снять настоящую сироту с
учёта храповика — молча и без злого умысла.

Это четвёртая форма того же класса: комментарий (#227), докстринг и самоупоминание
однофамильца (#255), теперь — строка-сообщение. Каждый раз лечение одно: **убрать из
числа проводок доказательство слабее вызова**, ничего не отняв у настоящего вызова.

**Почему нельзя просто «не считать литералы»** — и почему в этом файле ДВЕ половины.
Самая частая настоящая форма запуска сама является литералом:
``subprocess.run([PY, str(ROOT / "scripts/x.py")])``. Поэтому чинить надо не «литерал
или нет», а ЧТО в литерале написано: путь целиком — аргумент запуска; путь среди слов —
сообщение. Половина `TestARealCallSurvives` существует ровно затем, чтобы починка не
съела настоящую проводку: без неё «строгость» покрасила бы храповик на честной работе,
как чуть не случилось в #227 с голым импортом.

**Замер на живом дереве 17.08 (цикл #258):** проводкой по одному лишь упоминанию в
тексте держались **8** скриптов — `audit_protocol_blindness`, `build_dd_snapshot`,
`defenses_exercised_report`, `find_defillama_sources`, `findings_to_cards`,
`optimizer_ab`, `verify_dfb_pool`, `verify_riskwire`. Ни один из них не запускает
никто; их единственная «проводка» — help-строка, JSON-подсказка в ответе API или
фраза «Run scripts/… to regenerate».

Каждая проверка ниже — положительный контроль: возврат сканера к прежнему поведению
(снять `_message_literal_spans` из `_python_without_prose`) красит первую половину
поимённо, а вырезание литералов без разбора — вторую.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests._unwired import code_without_comments, scripts_without_caller

_SCRIPT = "target_script"


def _tree(tmp: pathlib.Path, hay_name: str, hay_text: str) -> pathlib.Path:
    """Мини-дерево: один скрипт с точкой входа + один файл, который может его звать."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / f"{_SCRIPT}.py").write_text(
        'if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")
    hay = tmp / "spa_core" / hay_name
    hay.parent.mkdir(parents=True, exist_ok=True)
    hay.write_text(hay_text, encoding="utf-8")
    return tmp


class _Tree(unittest.TestCase):

    def _orphans(self, hay_name: str, hay_text: str) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), hay_name, hay_text))


class TestAMentionInAMessageIsNotWiring(_Tree):
    """Строка, которую программа ПЕЧАТАЕТ, обязана оставлять скрипт неподключённым."""

    def test_the_hint_that_started_it(self):
        """Дословная форма аварии цикла #257: путь внутри f-строки подсказки."""
        orphans = self._orphans(
            "hint.py",
            "def hint(out, wt):\n"
            f'    out.append(f"убирать за собой обязан `scripts/{_SCRIPT}.py '
            '--worktree {wt}`")\n')
        self.assertIn(_SCRIPT, orphans, "текст подсказки засчитан за вызов")

    def test_english_sentence_around_the_path(self):
        """`"Run scripts/x.py to regenerate"` — это инструкция человеку, не запуск."""
        orphans = self._orphans(
            "api.py",
            f'DETAIL = ("Artifact not generated. Run scripts/{_SCRIPT}.py "\n'
            '          "to regenerate it.")\n')
        self.assertIn(_SCRIPT, orphans, "фраза с путём внутри засчитана за вызов")

    def test_argparse_help_text(self):
        """`help=` — витрина для человека; путь в ней никого не запускает."""
        orphans = self._orphans(
            "cli.py",
            "import argparse\np = argparse.ArgumentParser()\n"
            f'p.add_argument("--in", help="JSON-отчёт {_SCRIPT}.py --tier C")\n')
        self.assertIn(_SCRIPT, orphans, "help-строка засчитана за вызов")

    def test_command_line_shown_as_data_in_a_dict(self):
        """`{"reproduce": "python3 scripts/x.py"}` — данные ответа, а не запуск.

        Разница с настоящим `subprocess.run("python3 scripts/x.py", shell=True)`
        не в тексте литерала (он тот же), а в том, КУДА он попадает. Проверка
        закрепляет обе стороны: эта — что данные не проводка, `test_shell_true_…`
        ниже — что тот же текст в аргументе запуска проводкой остаётся.
        """
        orphans = self._orphans(
            "readiness.py",
            "def payload():\n"
            f'    return {{"reproduce": "python3 scripts/{_SCRIPT}.py"}}\n')
        self.assertIn(_SCRIPT, orphans, "командная строка в данных засчитана за вызов")

    def test_fstring_that_is_only_a_path_is_still_a_message(self):
        """f-строка — склейка с подстановкой; у argv каждый элемент отдельным литералом.

        Ослабить эту проверку («f-строка из одного пути — проводка») значит вернуть
        аварию #257 в её исходном виде: подсказка там и была f-строкой.
        """
        orphans = self._orphans(
            "msg.py",
            "def say(out, tail):\n"
            f'    out.append(f"scripts/{_SCRIPT}.py {{tail}}")\n')
        self.assertIn(_SCRIPT, orphans, "f-строка вне запуска засчитана за вызов")


class TestARealCallSurvives(_Tree):
    """Обратная сторона: строгость не имеет права съесть настоящую проводку."""

    def test_argv_element(self):
        """`subprocess.run(["python3", "scripts/x.py"])` — самая частая форма запуска."""
        orphans = self._orphans(
            "runner.py",
            "import subprocess\n"
            f'subprocess.run(["python3", "scripts/{_SCRIPT}.py"], check=True)\n')
        self.assertNotIn(_SCRIPT, orphans, "argv-литерал перестал быть вызовом")

    def test_path_built_from_parts(self):
        """`ROOT / "scripts" / "x.py"` — путь, собранный по кусочкам, тоже вызов."""
        orphans = self._orphans(
            "paths.py",
            "import pathlib\nROOT = pathlib.Path('.')\n"
            f'GUARD = ROOT / "scripts" / "{_SCRIPT}.py"\n')
        self.assertNotIn(_SCRIPT, orphans, "сборка пути перестала быть вызовом")

    def test_dash_m_module_form(self):
        """`[PY, "-m", "scripts.x"]` — запуск модулем."""
        orphans = self._orphans(
            "runner.py",
            "import subprocess\n"
            f'subprocess.run(["python3", "-m", "scripts.{_SCRIPT}"])\n')
        self.assertNotIn(_SCRIPT, orphans, "форма -m scripts.<имя> потеряна")

    def test_shell_true_command_line(self):
        """`subprocess.run(f"python3 scripts/x.py --once", shell=True)` — тоже запуск.

        Здесь литерал НЕ является голым путём и даже собран f-строкой — и всё же
        исполняется. Отличает его только место: аргумент запуска. Уберут это
        исключение — живой скрипт станет ложной сиротой, то есть база вырастет
        на честной работе.
        """
        orphans = self._orphans(
            "runner.py",
            "import subprocess\nflag = '--once'\n"
            f'subprocess.run(f"python3 scripts/{_SCRIPT}.py {{flag}}", shell=True)\n')
        self.assertNotIn(_SCRIPT, orphans, "командная строка в subprocess.run потеряна")

    def test_importlib_spec_from_file_location(self):
        """Динамический импорт по пути — проводка (так зовут генераторы)."""
        orphans = self._orphans(
            "loader.py",
            "import importlib.util\n"
            f'spec = importlib.util.spec_from_file_location("t", "scripts/{_SCRIPT}.py")\n')
        self.assertNotIn(_SCRIPT, orphans, "spec_from_file_location потерян")

    def test_bare_import_by_syspath(self):
        """Голый `import <имя>` разбирается `ast` и вырезанием прозы не задевается."""
        orphans = self._orphans("caller.py", f"import {_SCRIPT}\n")
        self.assertNotIn(_SCRIPT, orphans, "голый импорт потерян")

    def test_shell_message_is_left_alone(self):
        """Правка касается ТОЛЬКО `.py`: в `.sh` разбора ролей нет, и его не выдумывают.

        Оболочка сюда не входит намеренно — узость измерена, а не забыта: тронуть
        `.sh` без разбора команды значило бы гадать, что такое «сообщение», и рисковать
        ложной сиротой на `echo`-строке, которая на деле часть конвейера.
        """
        orphans = self._orphans(
            "w.sh", f'#!/bin/bash\necho "см. scripts/{_SCRIPT}.py"\n')
        self.assertNotIn(_SCRIPT, orphans, "правка расползлась на .sh молча")


class TestTheStripperItself(unittest.TestCase):
    """Единица работы — отдельно от обхода дерева."""

    def test_path_literal_kept_message_literal_dropped(self):
        out = code_without_comments(
            pathlib.Path("x.py"),
            'a = "scripts/keep.py"\nb = "смотри scripts/drop.py и запусти"\n')
        self.assertIn("scripts/keep.py", out)
        self.assertNotIn("scripts/drop.py", out)

    def test_blanking_keeps_line_count_and_length(self):
        """Вырезать «сжатием» значит склеить соседние куски и родить вызов из ничего."""
        text = 'a = "текст drop.py текст"\nb = 1\n'
        out = code_without_comments(pathlib.Path("x.py"), text)
        self.assertEqual(len(out.splitlines()), len(text.splitlines()))
        self.assertEqual([len(x) for x in out.splitlines()],
                         [len(x) for x in text.splitlines()])


if __name__ == "__main__":
    unittest.main()
