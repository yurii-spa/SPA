#!/usr/bin/env python3
"""scripts/tests/test_lint_forbidden_imports.py — сторож гейта запрещённых импортов.

Каждый тест — положительный контроль: он краснеет на ПРЕЖНЕМ поведении
(подстрока в инлайн-шаге `ci-lite.yml`) либо на порванном звене нового.
Авария, которую воспроизводит набор: с 07.09.2026 `SPA CI-Lite` на `main`
КРАСЕН на `spa_core/monitoring/cio_architecture_constraints.py` — сторож
инварианта #3 держит ОБРАЗЕЦ нарушения строковым литералом, а подстрочная
проверка не умеет отличить код от образца кода.

Пары «в обе стороны» обязательны: проверка, которая только зеленеет на
чистом дереве, украшение — она не отличима от проверки, не смотрящей никуда.
"""
# LLM_FORBIDDEN
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import lint_forbidden_imports as linter  # noqa: E402


def _write(root: str, rel: str, body: str) -> str:
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body))
    return full


def _substring_instrument(src: str) -> list[str]:
    """ПРЕЖНИЙ прибор из ci-lite.yml, дословно. Живёт здесь затем, чтобы
    разница двух приборов была ИЗМЕРЕНА тестом, а не заявлена прозой."""
    libs = ["anthropic", "openai", "langchain", "numpy", "pandas", "requests", "aiohttp"]
    return [lib for lib in libs if f"import {lib}" in src or f"from {lib}" in src]


class _Tree(unittest.TestCase):
    """Одноразовое дерево с пятью доменными каталогами."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        for domain in linter.DOMAINS:
            os.makedirs(os.path.join(self.root, domain), exist_ok=True)
        # каждый домен обязан быть непустым, иначе осмотрено ноль файлов
        for domain in linter.DOMAINS:
            _write(self.root, f"{domain}/_ok.py", "import json\n")

    def tearDown(self):
        self._td.cleanup()

    def run_cli(self, *extra):
        proc = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "lint_forbidden_imports.py"),
             "--root", self.root, *extra],
            capture_output=True, text=True, timeout=120,
        )
        return proc


# ── 1. Настоящий импорт ловится в КАЖДОЙ форме ───────────────────────────────

class TestRealImportsAreCaught(_Tree):

    def test_plain_import(self):
        _write(self.root, "spa_core/risk/x.py", "import anthropic\n")
        self.assertEqual(self.run_cli().returncode, 1)

    def test_from_import(self):
        _write(self.root, "spa_core/execution/x.py", "from openai import Client\n")
        self.assertEqual(self.run_cli().returncode, 1)

    def test_import_as(self):
        _write(self.root, "spa_core/monitoring/x.py", "import numpy as np\n")
        self.assertEqual(self.run_cli().returncode, 1)

    def test_submodule_import(self):
        _write(self.root, "spa_core/allocator/x.py", "import anthropic.types\n")
        self.assertEqual(self.run_cli().returncode, 1)

    def test_import_inside_function_is_still_an_import(self):
        _write(self.root, "spa_core/adapters/x.py",
               "def f():\n    import pandas\n    return pandas\n")
        self.assertEqual(self.run_cli().returncode, 1)

    def test_dynamic_door_is_caught_and_substring_never_saw_it(self):
        """Динамический ввоз — ЧИСТАЯ прибавка: прежний прибор его не видел."""
        src = 'import importlib\nm = importlib.import_module("anthropic")\n'
        _write(self.root, "spa_core/risk/x.py", src)
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(_substring_instrument(src), [],
                         "прежняя подстрока обязана быть слепа к этой двери — "
                         "иначе прибавка не измерена")

    def test_dunder_import_call(self):
        _write(self.root, "spa_core/risk/x.py", '__import__("openai")\n')
        self.assertEqual(self.run_cli().returncode, 1)


# ── 2. Ложные срабатывания сняты — и это ЗАМЕР, а не утверждение ─────────────

class TestSampleOfCodeIsNotCode(_Tree):

    SAMPLE = 'SAMPLES = {"sdk_import": "import anthropic\\n\\n\\ndef ask(q):\\n    return anthropic.go(q)\\n"}\n'

    def test_incident_23_09_sample_in_a_string_is_clean(self):
        """Авария 23.09: сторож инв. #3 краснил CI-Lite собственным образцом."""
        _write(self.root, "spa_core/monitoring/cio_architecture_constraints.py", self.SAMPLE)
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_the_old_instrument_WOULD_have_reddened_on_it(self):
        """Обратная половина: без неё «ложное срабатывание снято» недоказуемо."""
        self.assertEqual(_substring_instrument(self.SAMPLE), ["anthropic"])

    def test_comment_mentioning_the_ban_is_clean(self):
        _write(self.root, "spa_core/risk/x.py", "# запрещено: import numpy\nimport json\n")
        self.assertEqual(self.run_cli().returncode, 0)

    def test_relative_import_is_clean(self):
        _write(self.root, "spa_core/adapters/x.py", "from . import config\n")
        self.assertEqual(self.run_cli().returncode, 0)

    def test_relative_submodule_named_like_a_library_is_clean(self):
        """`from .requests import get` — СВОЙ модуль пакета, а не библиотека.
        Тест существует потому, что без него защита от относительного импорта
        не проверялась ничем: `from . import config` даёт пустое имя модуля и
        отсеивается сравнением корней, а не веткой `node.level` (замер мутацией)."""
        _write(self.root, "spa_core/adapters/x.py", "from .requests import get\n")
        self.assertEqual(self.run_cli().returncode, 0)

    def test_lookalike_name_is_not_a_root(self):
        """`requestsomething` — не `requests`; корень сравнивается по точке."""
        _write(self.root, "spa_core/risk/x.py", "import requestsomething\n")
        self.assertEqual(self.run_cli().returncode, 0)


# ── 3. Третий исход отделён от «чисто» и от «нарушение» ──────────────────────

class TestThirdOutcome(_Tree):

    def test_unparseable_file_is_not_measured(self):
        _write(self.root, "spa_core/risk/broken.py", "def f(:\n")
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)

    def test_missing_domain_directory_is_not_measured(self):
        import shutil
        shutil.rmtree(os.path.join(self.root, "spa_core/adapters"))
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("каталога нет", proc.stdout)

    def test_zero_files_scanned_is_not_a_clean_pass(self):
        for domain in linter.DOMAINS:
            os.remove(os.path.join(self.root, domain, "_ok.py"))
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("осмотрено ноль файлов", proc.stdout)

    def test_unmeasured_wins_over_a_violation(self):
        """Нечитаемый сосед не имеет права превратиться в «нарушений нет»
        и не имеет права спрятаться за найденным нарушением."""
        _write(self.root, "spa_core/risk/broken.py", "def f(:\n")
        _write(self.root, "spa_core/risk/real.py", "import anthropic\n")
        self.assertEqual(self.run_cli().returncode, 2)


# ── 4. База может только убывать ─────────────────────────────────────────────

class TestBaseline(_Tree):

    def _baseline(self, known: dict):
        os.makedirs(os.path.join(self.root, "scripts"), exist_ok=True)
        with open(os.path.join(self.root, linter.BASELINE_REL), "w", encoding="utf-8") as fh:
            json.dump({"known": known}, fh)

    def test_known_violation_does_not_redden(self):
        _write(self.root, "spa_core/adapters/x.py", "import requests\n")
        self._baseline({"spa_core/adapters/x.py::requests": "известно, карточка заведена"})
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("ИЗВЕСТНОЕ", proc.stdout)

    def test_baseline_covers_exactly_one_pair_and_nothing_else(self):
        """Запись базы не имеет права накрыть ДРУГУЮ библиотеку в том же файле."""
        _write(self.root, "spa_core/adapters/x.py", "import requests\nimport numpy\n")
        self._baseline({"spa_core/adapters/x.py::requests": "известно"})
        self.assertEqual(self.run_cli().returncode, 1)

    def test_baseline_does_not_cover_the_same_lib_elsewhere(self):
        _write(self.root, "spa_core/adapters/x.py", "import requests\n")
        _write(self.root, "spa_core/risk/y.py", "import requests\n")
        self._baseline({"spa_core/adapters/x.py::requests": "известно"})
        self.assertEqual(self.run_cli().returncode, 1)

    def test_stale_entry_is_named(self):
        self._baseline({"spa_core/risk/gone.py::numpy": "давно починено"})
        proc = self.run_cli()
        self.assertIn("БАЗА УБЫЛА", proc.stdout)

    def test_broken_baseline_file_is_not_measured(self):
        os.makedirs(os.path.join(self.root, "scripts"), exist_ok=True)
        with open(os.path.join(self.root, linter.BASELINE_REL), "w", encoding="utf-8") as fh:
            fh.write("{не json")
        self.assertEqual(self.run_cli().returncode, 2)


# ── 5. Живое дерево: прибор ИЗМЕРЯЕТ его, а база не протухла ────────────────

class TestRealRepository(unittest.TestCase):

    def test_repo_is_measured_and_clean_outside_the_baseline(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "lint_forbidden_imports.py"),
             "--root", _REPO, "--json"],
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertGreater(doc["scanned_files"], 100,
                           "осмотрено подозрительно мало файлов — прибор смотрит не туда")
        self.assertEqual(doc["unmeasured"], [])
        self.assertEqual([v for v in doc["violations"] if not v["known"]], [])

    def test_baseline_has_no_stale_entries(self):
        """База обязана УБЫВАТЬ вместе с реальностью: починил — удали запись.
        Без этого теста база тихо превращается в вечный список исключений."""
        proc = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "lint_forbidden_imports.py"),
             "--root", _REPO, "--json"],
            capture_output=True, text=True, timeout=300,
        )
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["stale_baseline"], [],
                         "нарушения больше нет — удалить запись из базы")

    def test_ci_lite_calls_this_instrument_and_keeps_no_copy_of_the_rule(self):
        """Прибор, которого никто не зовёт, — отчёт без читателя (класс ADR-333)."""
        with open(os.path.join(_REPO, ".github/workflows/ci-lite.yml"),
                  encoding="utf-8") as fh:
            wf = fh.read()
        self.assertIn("python3 scripts/lint_forbidden_imports.py", wf)
        self.assertNotIn("FORBIDDEN_LIBS", wf,
                         "инлайн-копия правила вернулась в workflow — правило снова в двух местах")


if __name__ == "__main__":
    unittest.main(verbosity=2)
