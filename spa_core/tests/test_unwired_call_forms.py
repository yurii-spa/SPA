"""Сканер обязан видеть ВСЕ формы вызова — иначе он рождает ЛОЖНУЮ сироту.

**Почему этот файл появился раньше правок, отнимающих доказательства.** Цикл #227,
сняв слепоту к комментариям, померил обратную сторону и остановился с прямым
предупреждением: чинить остальное В ЛОБ опаснее, чем оставить. Пример живой и
проверяемый — `scripts/check_tracker_drift.py` подключён строкой
``import check_tracker_drift as drift`` (`scripts/orchestrator_queue.py:198`), а сканер
искал только `<имя>.py` и `scripts.<имя>` и голого импорта НЕ ВИДЕЛ. Скрипт держался
случайным упоминанием в докстринге чужого модуля. Снять докстринги первыми — значит
объявить мёртвым скрипт, который исполняется каждый день: храповик покраснел бы на
ЧЕСТНОЙ работе, а это в проекте уже признано исходом хуже пропуска (страж номеров
ADR, #183).

Поэтому порядок обратный: сначала ЭТОТ файл (все формы вызова), потом
`test_unwired_weak_evidence.py` (отнятые доказательства).

Каждая проверка ниже — положительный контроль на синтетическом дереве (корень —
вход функции). Мутация «убрать разбор импортов» (`imported_modules` → `set()`) красит
первые четыре поимённо; мутация «вернуть подстрочный поиск» красит `TestRealRepo`.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests._unwired import (
    imported_modules,
    scripts_without_caller,
)

_SCRIPT = "target_script"


def _tree(tmp: pathlib.Path, hay_name: str, hay_text: str) -> pathlib.Path:
    """Мини-дерево: один скрипт с точкой входа + один возможный вызывающий."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / f"{_SCRIPT}.py").write_text(
        'if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")
    hay = tmp / "spa_core" / hay_name
    hay.parent.mkdir(parents=True, exist_ok=True)
    hay.write_text(hay_text, encoding="utf-8")
    return tmp


class _Base(unittest.TestCase):

    def _orphans(self, hay_name: str, hay_text: str) -> list:
        with tempfile.TemporaryDirectory() as d:
            return scripts_without_caller(_tree(pathlib.Path(d), hay_name, hay_text))

    def assertWired(self, hay_name: str, hay_text: str, msg: str):
        self.assertNotIn(_SCRIPT, self._orphans(hay_name, hay_text), msg)


class TestEveryCallFormIsSeen(_Base):
    """Настоящая проводка обязана распознаваться во ВСЕХ живых формах."""

    def test_bare_import_by_sys_path(self):
        """Форма из `orchestrator_queue.py:198` — ровно та, что грозила ложной сиротой."""
        self.assertWired(
            "caller.py",
            "import sys\nsys.path.insert(0, 'scripts')\n"
            f"import {_SCRIPT} as drift\n",
            "голый `import <имя>` не засчитан за вызов — это и есть ложная сирота")

    def test_bare_from_import(self):
        self.assertWired("caller.py", f"from {_SCRIPT} import main\n",
                         "`from <имя> import …` не засчитан за вызов")

    def test_package_import(self):
        self.assertWired("caller.py", f"from scripts.{_SCRIPT} import main\n",
                         "`from scripts.<имя> import …` потерян")

    def test_import_inside_a_function(self):
        """Отложенный импорт — самая частая форма проводки сторожей в этом репо."""
        self.assertWired(
            "caller.py",
            f"def check():\n    import {_SCRIPT} as d\n    return d.analyze()\n",
            "импорт внутри функции не найден — `ast.walk` обязан идти вглубь")

    def test_dash_m_module_run(self):
        self.assertWired("w.sh", f"#!/bin/bash\npython3 -m scripts.{_SCRIPT} --once\n",
                         "`-m scripts.<имя>` потерян")

    def test_dash_m_bare_module_run(self):
        self.assertWired("w.sh", f"#!/bin/bash\npython3 -m {_SCRIPT}\n",
                         "`-m <имя>` потерян")

    def test_plist_module_argument(self):
        self.assertWired(
            "a.plist",
            "<plist><dict><key>ProgramArguments</key><array><string>-m</string>"
            f"<string>scripts.{_SCRIPT}</string></array></dict></plist>\n",
            "аргумент plist'а в форме модуля потерян")

    def test_path_call_from_a_wrapper(self):
        self.assertWired("w.sh", f"#!/bin/bash\npython3 scripts/{_SCRIPT}.py --once\n",
                         "вызов по пути из обёртки потерян")

    def test_relative_path_call(self):
        self.assertWired("w.sh", f'#!/bin/bash\npython3 "$DIR/../scripts/{_SCRIPT}.py"\n',
                         "вызов по относительному пути потерян")

    def test_string_literal_call(self):
        self.assertWired(
            "runner.py",
            f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n',
            "вызов из строкового литерала потерян")


class TestImportParsingTellsNamesakesApart(unittest.TestCase):
    """Единица работы отдельно: разбор импортов обязан различать однофамильцев.

    Текстовый поиск `\\bimport day30_review` не отличает настоящий
    ``import day30_review`` (проводка скрипта) от ``from spa_core.riskwire import
    day30_review`` (импорт ОДНОФАМИЛЬЦА, к скрипту отношения не имеющего). Разбор
    через `ast` отличает — и это единственная причина, по которой правило
    однофамильца вообще можно было включить.
    """

    def test_a_bare_import_is_the_module_itself(self):
        self.assertIn("day30_review", imported_modules("import day30_review\n"))

    def test_a_package_import_is_NOT_the_bare_name(self):
        mods = imported_modules("from spa_core.riskwire import day30_review\n")
        self.assertIn("spa_core.riskwire.day30_review", mods)
        self.assertNotIn("day30_review", mods,
                         "импорт однофамильца из пакета выдан за импорт скрипта")

    def test_a_relative_import_never_reaches_scripts(self):
        self.assertEqual(imported_modules("from . import day30_review\n"), set())

    def test_a_broken_file_yields_nothing_rather_than_guessing(self):
        self.assertEqual(imported_modules("def f(:\n"), set())


class TestRealRepo(unittest.TestCase):
    """Синтетика не заменяет факта: живой случай из карточки, на настоящем дереве."""

    def test_check_tracker_drift_is_seen_as_wired(self):
        """Тот самый скрипт, ради которого порядок работ обязан быть обратным.

        Он подключён ЖИВЫМ `import check_tracker_drift` — и после снятия
        докстринго-слепоты только эта форма его и держит. Тест краснеет, если
        разбор импортов из сканера уберут.
        """
        self.assertNotIn("check_tracker_drift", scripts_without_caller(),
                         "живой ежедневный сторож объявлен сиротой — сканер разучился "
                         "видеть голый импорт")


if __name__ == "__main__":
    unittest.main()
