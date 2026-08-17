"""Комментарий — не вызов: положительные контроли к храповику (цикл #227).

**Авария, которую эти тесты воспроизводят.** `spa_core/tests/_unwired.py` решал
«подключён ли скрипт» поиском ПОДСТРОКИ его имени по коду и не отличал вызов от
упоминания. Значит любое упоминание имени в комментарии молча и навсегда снимало
скрипт с учёта храповика. Поймано на себе (цикл #205): разбор в шапке
`scripts/run_health_check.py` назвал `run_daily_simulation` — и комментарий,
объяснявший, что скрипт НЕ подключён, сделал его «подключённым».

Замер 14.08 на живом дереве: слепота к комментариям держала «подключённым»
`daily_paper_report` (списан этим же циклом — агент отключён с 21.06, вызывающего
нет, класс схлопнут в один дневной дайджест). Слепота к ДОКСТРИНГАМ стоила ещё
8 скриптов; 15.08 (цикл #228) она закрыта вместе с двумя соседними — но только
ПОСЛЕ того, как сканер научился видеть все формы вызова. Разбор — в
`test_unwired_call_forms.py` и `test_unwired_weak_evidence.py`.

Каждая проверка ниже — положительный контроль: возврат текстового поиска в
`code_without_comments` (вернуть `return text` первой строкой) красит их поимённо.
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


class TestAMentionInACommentIsNotWiring(unittest.TestCase):
    """Упоминание в комментарии обязано ОСТАВЛЯТЬ скрипт неподключённым."""

    def _orphans(self, hay_name: str, hay_text: str) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), hay_name, hay_text))

    def test_python_comment(self):
        orphans = self._orphans("m.py", f"# см. scripts/{_SCRIPT}.py — он НЕ подключён\nx = 1\n")
        self.assertIn(_SCRIPT, orphans, "комментарий в .py засчитан за вызов")

    def test_shell_comment(self):
        orphans = self._orphans("w.sh", f"#!/bin/bash\n# когда-то звали {_SCRIPT}.py\necho ok\n")
        self.assertIn(_SCRIPT, orphans, "комментарий в .sh засчитан за вызов")

    def test_yaml_comment(self):
        orphans = self._orphans("ci.yml", f"jobs:\n  # раньше: python3 scripts/{_SCRIPT}.py\n  a: b\n")
        self.assertIn(_SCRIPT, orphans, "комментарий в .yml засчитан за вызов")

    def test_plist_xml_comment(self):
        orphans = self._orphans(
            "a.plist",
            f"<plist><dict>\n<!-- отключено: scripts/{_SCRIPT}.py -->\n</dict></plist>\n")
        self.assertIn(_SCRIPT, orphans, "XML-комментарий в .plist засчитан за вызов")

    def test_a_python_file_that_does_not_parse_still_loses_its_comments(self):
        """Битый файл не имеет права вернуть сканер к слепоте молча."""
        orphans = self._orphans(
            "broken.py", f"def f(:\n    pass\n# упоминание scripts/{_SCRIPT}.py\n")
        self.assertIn(_SCRIPT, orphans,
                      "на неразобравшемся .py сканер вернулся к сырому тексту")


class TestARealCallIsStillACall(unittest.TestCase):
    """Обратная сторона: строгость не имеет права съесть настоящую проводку."""

    def _orphans(self, hay_name: str, hay_text: str) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), hay_name, hay_text))

    def test_string_literal_in_python_is_a_call(self):
        orphans = self._orphans(
            "runner.py",
            f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n')
        self.assertNotIn(_SCRIPT, orphans, "настоящий вызов из строкового литерала потерян")

    def test_module_import_form_is_a_call(self):
        orphans = self._orphans("caller.py", f"from scripts.{_SCRIPT} import main\n")
        self.assertNotIn(_SCRIPT, orphans, "импорт scripts.<stem> потерян")

    def test_shell_call_is_a_call(self):
        orphans = self._orphans("w.sh", f"#!/bin/bash\npython3 scripts/{_SCRIPT}.py --once\n")
        self.assertNotIn(_SCRIPT, orphans, "вызов из обёртки потерян")

    def test_hash_inside_quotes_is_not_a_comment(self):
        """`#` в кавычках — часть строки; обрезать по нему значит съесть вызов.

        `#` стоит ДО имени скрипта намеренно: если обрезать строку по первому
        `#` без учёта кавычек, вызов уедет вместе с хвостом и живой скрипт
        окажется сиротой. Слабая редакция этой проверки (вызов до `#`) мутацию
        не ловила — усилено в том же цикле.
        """
        orphans = self._orphans(
            "w.sh", f'#!/bin/bash\necho "tag #1: python3 scripts/{_SCRIPT}.py"\n')
        self.assertNotIn(_SCRIPT, orphans, "обрезка по # съела вызов внутри кавычек")

    def test_plist_program_argument_is_a_call(self):
        orphans = self._orphans(
            "a.plist",
            f"<plist><dict><key>ProgramArguments</key><array>"
            f"<string>scripts/{_SCRIPT}.py</string></array></dict></plist>\n")
        self.assertNotIn(_SCRIPT, orphans, "аргумент plist'а потерян")


class TestTheStripperItself(unittest.TestCase):
    """Единица работы — отдельно от обхода дерева."""

    def test_python_keeps_strings_and_drops_comments(self):
        out = code_without_comments(
            pathlib.Path("x.py"), 'a = "scripts/keep.py"  # scripts/drop.py\n')
        self.assertIn("scripts/keep.py", out)
        self.assertNotIn("scripts/drop.py", out)

    def test_unknown_suffix_is_returned_as_is(self):
        text = "# scripts/drop.py"
        self.assertEqual(code_without_comments(pathlib.Path("x.md"), text), text)

    def test_the_docstring_gap_is_CLOSED(self):
        """Пробел, названный этим же файлом 14.08, закрыт циклом #228.

        **Намеренная правка чужого теста (инв. #16), обоснование здесь и в
        `docs/journal/2026-W33.md`.** На месте этой проверки стоял
        `test_a_docstring_mention_still_counts_KNOWN_GAP`, и его собственный
        докстринг предписывал: «когда пробел закроют, ЭТОТ тест обязан
        покраснеть — и его надо будет снять вместе с правкой». Ровно это и
        сделано: проверка не ослаблена, а РАЗВЁРНУТА — теперь она требует
        противоположного и краснеет, если докстринго-слепоту вернут.

        Разбор самой слепоты и её соседок — `test_unwired_weak_evidence.py`.
        """
        out = code_without_comments(pathlib.Path("x.py"), '"""см. scripts/drop.py"""\n')
        self.assertNotIn("scripts/drop.py", out,
                         "докстринг снова считается проводкой — слепота вернулась")


if __name__ == "__main__":
    unittest.main()
