"""Груз доставки — не вызов: положительные контроли к храповику (цикл #259).

**Авария, которую эти тесты воспроизводят.** `spa_core/tests/_unwired.py` считал
проводкой имя скрипта, стоящее в `.sh` в СПИСКЕ ФАЙЛОВ инструмента доставки::

    python3 push_to_github.py \\
      --files \\
        "$REPO_ROOT/scripts/backup_spa_data.py" \\
        "$REPO_ROOT/scripts/restore_spa_data.py" \\
      --message "…"

Пушер не ЗАПУСКАЕТ `restore_spa_data.py` — он его ВЕЗЁТ. Разница ровно та, ради
которой заведён храповик: «доставлен» и «вызывается» — два разных события, и старый
разовый push-скрипт навсегда снимал настоящую сироту с учёта одним лишь тем, что
когда-то её вёз. Молча и без злого умысла — как и четыре предыдущие формы:
комментарий (#227), докстринг и самоупоминание однофамильца (#255),
строка-сообщение (#258).

**Замер на живом дереве 18.08 (цикл #259), откатом самой починки:** сырых сирот
99 до, 102 после; проводкой ТОЛЬКО по грузу держались ТРИ скрипта —
`pat_rotation_helper` (`scripts/push_all_session.sh:123`), `restore_spa_data`
(`scripts/run_cpa_wave9_pushes.sh:58`) и `system_health_check`
(`scripts/run_cpa_wave9_pushes.sh:42`). Ни одного из них не запускает никто; их
файлы — исторические разовые пуш-скрипты. Обратная разность ПУСТА: ни один
подключённый скрипт сиротой не стал.

Третье имя стоит назвать отдельно: `system_health_check` я сперва посчитал
подключённым по эвристике («у него есть доказательство кроме груза»), и эвристика
соврала — соседняя строка `python3 -m unittest tests.test_system_health_check`
называет ТЕСТ-модуль, а не скрипт. Настоящее число дал только буквальный откат
починки на живом дереве. Оценка вместо замера ошиблась на треть.

**Почему в этом файле ДВЕ половины.** Настоящий вызов в оболочке выглядит почти
так же — `python3 \\` и путь продолжением строки, — поэтому правило «одинокий путь
в продолжении = груз» родило бы ЛОЖНУЮ сироту на честной работе. Судится не форма
строки, а ФЛАГ: вырезается только то, что стоит после `--files`/`--file` и до
следующего ключа. Половина `TestARealShellCallSurvives` существует затем, чтобы
строгость не съела настоящую проводку.

Каждая проверка ниже — положительный контроль: возврат сканера к прежнему поведению
(снять `_cut_shell_cargo` из `code_without_comments`) красит первую половину
поимённо, а вырезание всех путей в продолжении строки — вторую.
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
    hay = tmp / "scripts" / hay_name
    hay.write_text(hay_text, encoding="utf-8")
    return tmp


class _Tree(unittest.TestCase):

    def _orphans(self, hay_name: str, hay_text: str) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), hay_name, hay_text))


class TestCargoIsNotWiring(_Tree):
    """Файл, который ВЕЗУТ, обязан оставаться неподключённым."""

    def test_the_form_that_started_it(self):
        """Дословная форма из `scripts/run_cpa_wave9_pushes.sh:58`."""
        orphans = self._orphans(
            "push_wave.sh",
            "#!/bin/bash\n"
            "python3 push_to_github.py \\\n"
            "  --files \\\n"
            f'    "$REPO_ROOT/scripts/{_SCRIPT}.py" \\\n'
            '  --message "Sprint v11.41" \\\n'
            "  2>&1 | tee -a \"$LOG\"\n")
        self.assertIn(_SCRIPT, orphans, "список груза засчитан за вызов")

    def test_cargo_on_one_line(self):
        """`--files a.py b.py --message x` — тот же груз, записанный в строку."""
        orphans = self._orphans(
            "push.sh",
            "#!/bin/bash\n"
            f'python3 push_to_github.py --files scripts/{_SCRIPT}.py --message "x"\n')
        self.assertIn(_SCRIPT, orphans, "груз в одну строку засчитан за вызов")

    def test_absolute_path_in_cargo(self):
        """Форма `scripts/push_all_session.sh:123` — абсолютный путь в списке."""
        orphans = self._orphans(
            "push_all.sh",
            "#!/bin/bash\n"
            "python3 push_to_github.py \\\n"
            "  --files \\\n"
            f"  /Users/x/Documents/SPA_Claude/scripts/{_SCRIPT}.py \\\n"
            '  --message "session"\n')
        self.assertIn(_SCRIPT, orphans, "абсолютный путь груза засчитан за вызов")


class TestARealShellCallSurvives(_Tree):
    """Обратная сторона: строгость не имеет права съесть настоящую проводку."""

    def test_plain_call(self):
        """`python3 scripts/x.py` — самая простая настоящая форма."""
        orphans = self._orphans(
            "w.sh", f"#!/bin/bash\npython3 scripts/{_SCRIPT}.py --once\n")
        self.assertNotIn(_SCRIPT, orphans, "прямой вызов из обёртки потерян")

    def test_call_on_a_continuation_line(self):
        """Путь продолжением строки — ВЫЗОВ, а не груз; отличает только флаг.

        Ослабить эту проверку («одинокий путь в продолжении = груз») значит
        объявить сиротой каждый скрипт, который зовут переносом строки, то есть
        покрасить храповик на честной работе — капкан #227 в чистом виде.
        """
        orphans = self._orphans(
            "w.sh",
            "#!/bin/bash\n"
            "python3 \\\n"
            f"  scripts/{_SCRIPT}.py \\\n"
            "  --verbose\n")
        self.assertNotIn(_SCRIPT, orphans, "вызов с переносом строки съеден")

    def test_call_after_the_cargo_list_ends(self):
        """Ключ после груза ЗАКРЫВАЕТ список: следующий путь снова вызов."""
        orphans = self._orphans(
            "w.sh",
            "#!/bin/bash\n"
            'python3 push_to_github.py --files a.txt --message "x"\n'
            f"python3 scripts/{_SCRIPT}.py\n")
        self.assertNotIn(_SCRIPT, orphans, "груз погасил вызов ниже по файлу")

    def test_cargo_state_does_not_leak_past_the_command(self):
        """Конец логической команды закрывает список даже без ключа."""
        orphans = self._orphans(
            "w.sh",
            "#!/bin/bash\n"
            "python3 push_to_github.py \\\n"
            "  --files a.txt\n"
            f"python3 scripts/{_SCRIPT}.py\n")
        self.assertNotIn(_SCRIPT, orphans, "состояние груза протекло на следующую команду")

    def test_script_that_itself_takes_a_files_flag(self):
        """`--files` у ВЫЗЫВАЕМОГО скрипта: имя стоит ДО флага и уцелело."""
        orphans = self._orphans(
            "w.sh",
            "#!/bin/bash\n"
            f"python3 scripts/{_SCRIPT}.py --files data/golive_status.json\n")
        self.assertNotIn(_SCRIPT, orphans, "собственный --files скрипта съел его вызов")


class TestTheStripperItself(unittest.TestCase):
    """Единица работы — отдельно от обхода дерева."""

    def test_cargo_dropped_call_kept(self):
        out = code_without_comments(
            pathlib.Path("w.sh"),
            "python3 scripts/keep.py\n"
            "python3 push_to_github.py --files scripts/drop.py --message m\n")
        self.assertIn("scripts/keep.py", out)
        self.assertNotIn("scripts/drop.py", out)

    def test_blanking_keeps_line_count_and_length(self):
        """Вырезать «сжатием» значит склеить куски и родить вызов из ничего."""
        text = "python3 push.py --files scripts/drop.py --message m\nb=1\n"
        out = code_without_comments(pathlib.Path("w.sh"), text)
        self.assertEqual(len(out.splitlines()), len(text.splitlines()))
        self.assertEqual([len(x) for x in out.splitlines()],
                         [len(x) for x in text.splitlines()])

    def test_yaml_is_left_alone(self):
        """Правка касается ТОЛЬКО `.sh` — узость измерена, а не забыта.

        В workflow `--files` не встречается инструментом доставки, а гадать про
        роли в YAML без разбора шага значило бы рисковать ложной сиротой на CI.
        """
        text = "      run: python3 push.py --files scripts/drop.py\n"
        out = code_without_comments(pathlib.Path("ci.yml"), text)
        self.assertIn("scripts/drop.py", out)


if __name__ == "__main__":
    unittest.main()
