"""Три доказательства СЛАБЕЕ вызова — и каждое отнято отдельно.

Цикл #227 снял слепоту к комментариям и измерил обратную сторону: «подключёнными»
скрипты держались ещё **тремя** разными способами, ни один из которых вызовом не
является. Здесь у каждого свой класс тестов, потому что у каждого своя цена ошибки
и своя мутация:

1. **Докстринг.** Прозаическое упоминание `scripts/<имя>.py` внутри `\"\"\"…\"\"\"` по
   последствиям равно комментарию. Литералы сканер хранит НАМЕРЕННО (в литерале
   живёт настоящий вызов), поэтому отличить прозу от вызова может только `ast`.
2. **Однофамилец.** Файл с тем же именем вне `scripts/` упоминает сам себя — и
   этого хватало, чтобы скрипт числился вызванным (`spa_core/riskwire/day30_review.py`
   «держал» `scripts/day30_review.py`, ни разу его не позвав).
3. **Подстрочная коллизия.** `perf_budget` — подстрока `dfb_perf_budget`, и упоминание
   ВТОРОГО снимало с учёта ПЕРВЫЙ.

**Порядок неслучаен.** Сначала сканер научился видеть все формы вызова
(`test_unwired_call_forms.py`), и только потом у него отняли эти три. Обратный
порядок дал бы ложную сироту — предупреждение цикла #227 дословно.

Мутации, красящие этот файл поимённо: вернуть `_docstring_spans` → `[]` · убрать
режим `qualified_only` · убрать границы `_NAME` из `_text_patterns`.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests._unwired import code_without_comments, scripts_without_caller

_SCRIPT = "target_script"


def _tree(tmp: pathlib.Path, files: dict) -> pathlib.Path:
    """Дерево: скрипт с точкой входа + произвольные возможные вызывающие."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / f"{_SCRIPT}.py").write_text(
        'if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


class _Base(unittest.TestCase):

    def _orphans(self, files: dict) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), files))

    def assertWired(self, files: dict, msg: str):
        self.assertNotIn(_SCRIPT, self._orphans(files), msg)

    def assertOrphan(self, files: dict, msg: str):
        self.assertIn(_SCRIPT, self._orphans(files), msg)


class TestADocstringIsNotACall(_Base):
    """Слепота №1: докстринг держал 5 скриптов (замер 14.08)."""

    def test_module_docstring(self):
        self.assertOrphan(
            {"spa_core/m.py": f'"""СГЕНЕРИРОВАНО scripts/{_SCRIPT}.py — не править."""\nx = 1\n'},
            "упоминание в докстринге модуля засчитано за вызов")

    def test_function_docstring(self):
        self.assertOrphan(
            {"spa_core/m.py": f'def f():\n    """см. scripts/{_SCRIPT}.py"""\n    return 1\n'},
            "упоминание в докстринге функции засчитано за вызов")

    def test_class_docstring(self):
        self.assertOrphan(
            {"spa_core/m.py": f'class C:\n    """в отличие от {_SCRIPT}.py"""\n    x = 1\n'},
            "упоминание в докстринге класса засчитано за вызов")

    def test_a_docstring_command_example_is_not_wiring(self):
        """«Как перегенерировать» в шапке сгенерированного файла — рецепт, не вызов.

        Ровно так `scripts/audit_tier_c_wiring_feasibility.py` числился подключённым:
        шапка `spa_core/analytics/_protocol_key_coverage.py` объясняла, какой командой
        файл перегенерировать. Команду набирает ЧЕЛОВЕК; кода, который её исполняет,
        в дереве нет.
        """
        self.assertOrphan(
            {"spa_core/gen.py": ('"""СГЕНЕРИРОВАНО; перегенерация:\n'
                                 f'    python3 scripts/{_SCRIPT}.py --tier B\n"""\n'
                                 "DATA = {}\n")},
            "пример команды в докстринге засчитан за вызов")

    def test_a_NON_docstring_literal_is_still_a_call(self):
        """Обратная сторона: строгость не имеет права съесть настоящий вызов."""
        self.assertWired(
            {"spa_core/r.py": ('"""Запускалка."""\nimport subprocess\n'
                               f'subprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n')},
            "вызов из обычного литерала съеден вместе с докстрингом")

    def test_code_after_a_cyrillic_docstring_survives(self):
        """Смещения `ast` — в БАЙТАХ; на русском докстринге путаница режет по живому.

        Если считать байтовое смещение символьным, конец русского докстринга уедет
        вправо и вырежет кусок следующего кода — молча и в середине строки. Здесь
        вызов стоит сразу за длинным русским докстрингом и обязан уцелеть.
        """
        self.assertWired(
            {"spa_core/r.py": ('"""Очень длинный русский докстринг про сторожей и '
                               'проводку, специально длиннее своей же байтовой '
                               'записи."""\n'
                               f'CMD = "scripts/{_SCRIPT}.py"\n')},
            "байтовые смещения ast приняты за символьные — вырезан живой код")

    def test_the_stripper_itself(self):
        out = code_without_comments(
            pathlib.Path("x.py"),
            '"""см. scripts/drop.py"""\nCMD = "scripts/keep.py"  # scripts/also_drop.py\n')
        self.assertIn("scripts/keep.py", out)
        self.assertNotIn("scripts/drop.py", out)
        self.assertNotIn("scripts/also_drop.py", out)


class TestANamesakeDoesNotWireItself(_Base):
    """Слепота №2: однофамилец из другого каталога держал 2 скрипта."""

    def test_a_namesake_module_mentioning_itself_is_not_wiring(self):
        self.assertOrphan(
            {f"spa_core/riskwire/{_SCRIPT}.py":
                f'CMD = "{_SCRIPT}.py --write"\nDOC = "смотри {_SCRIPT}.py"\n'},
            "однофамилец подключил скрипт собственным именем")

    def test_a_namesake_that_really_calls_the_script_IS_wiring(self):
        """Правило запрещает самоупоминание, а не настоящий вызов от однофамильца."""
        self.assertWired(
            {f"spa_core/riskwire/{_SCRIPT}.py":
                f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n'},
            "однофамильцу запретили звать скрипт по полному пути — это уже не правило, "
            "а слепота в другую сторону")

    def test_a_namesake_importing_the_script_package_IS_wiring(self):
        self.assertWired(
            {f"spa_core/riskwire/{_SCRIPT}.py": f"from scripts.{_SCRIPT} import main\n"},
            "однофамильцу запретили импортировать scripts.<имя>")

    def test_importing_a_namesake_module_is_NOT_wiring_the_script(self):
        """`from spa_core.riskwire import <имя>` — импорт МОДУЛЯ, а не скрипта."""
        self.assertOrphan(
            {f"spa_core/riskwire/{_SCRIPT}.py": "def main():\n    return 0\n",
             "spa_core/caller.py": f"from spa_core.riskwire import {_SCRIPT}\n"},
            "импорт однофамильца засчитан за вызов скрипта")


class TestASubstringIsNotAName(_Base):
    """Слепота №3: `perf_budget` находился внутри `dfb_perf_budget`."""

    def test_a_longer_name_containing_the_stem_is_not_wiring(self):
        self.assertOrphan(
            {"spa_core/w.sh": f"#!/bin/bash\npython3 scripts/dfb_{_SCRIPT}.py\n"},
            "имя-надмножество (`dfb_<имя>.py`) засчитано за вызов `<имя>.py`")

    def test_a_suffixed_name_is_not_wiring(self):
        self.assertOrphan(
            {"spa_core/w.sh": f"#!/bin/bash\npython3 scripts/{_SCRIPT}_real.py\n"},
            "имя с суффиксом (`<имя>_real.py`) засчитано за вызов `<имя>.py`")

    def test_a_suffixed_module_import_is_not_wiring(self):
        self.assertOrphan(
            {"spa_core/c.py": f"from scripts.{_SCRIPT}_tier1 import main\n"},
            "импорт `scripts.<имя>_tier1` засчитан за вызов `<имя>`")

    def test_the_exact_name_after_a_slash_IS_wiring(self):
        """Граница не имеет права съесть нормальный путь."""
        self.assertWired(
            {"spa_core/w.sh": f"#!/bin/bash\npython3 /opt/spa/scripts/{_SCRIPT}.py\n"},
            "граница имени съела вызов по абсолютному пути")


if __name__ == "__main__":
    unittest.main()
