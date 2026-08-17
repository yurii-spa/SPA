"""Формы проводки и доказательства слабее вызова (циклы #255/#265, сведение 17.08).

**Авария, которую эти тесты воспроизводят.** Сканер неподключённых скриптов
(`spa_core/tests/_unwired.py`) решал «подключён ли скрипт» двумя подстроками —
`<имя>.py` и `scripts.<имя>` — без границ слова, и не знал третьей формы вовсе.
Отсюда три разных вранья, замеренных 14.08 (карточка
`inbox-hrapovik-schitaet-upominanie-v-dokstring`), и каждое держало скрипт
«подключённым» молча и навсегда:

1. **докстринг** — проза о коде неотличима от вызова (5 скриптов);
2. **однофамилец** — файл с тем же именем в другом каталоге упоминает САМ СЕБЯ,
   и этого хватает (`spa_core/riskwire/day30_review.py`, `spa_core/audit/ots_anchor.py`);
3. **подстрочная коллизия** — `perf_budget` ⊂ `dfb_perf_budget.py`,
   `scripts.run_backtest` ⊂ `scripts.run_backtest_real`.

**Почему порядок правок обязателен, и он проверяется здесь же.** Отнять
доказательства ДО того, как сканер научится видеть все формы вызова, значит
объявить сиротой живой скрипт: `check_tracker_drift` держался докстрингами, а
зовут его голым `import check_tracker_drift` из `scripts/orchestrator_queue.py`.
Храповик, краснеющий на честной работе, в этом проекте уже признан исходом хуже
пропуска (страж номеров ADR, #183) — поэтому `TestWiringFormsAreSeen` идёт первым
и его мутация красит всё остальное.

**Файл возвращён из `docs/parked/` при сведении двух реализаций сторожа (17.08)** и
дополнен тем, чего в припаркованной версии не было: по одному положительному
контролю НА КАЖДУЮ из пяти форм в отдельности (`TestEachFormAloneIsEnough` —
в дереве стоит РОВНО одно доказательство, и снятие своей формы из детектора красит
свой тест поимённо), проверкой строгости вычитаемого класса
(`TestRegistryIsJudgedByTheSamePatterns` — реестр R&D больше не судится голой
подстрокой) и проверкой согласия двух движков (`TestTwoEnginesAgree`).

Каждая проверка — положительный контроль на синтетическом дереве (корень — вход
функции, а не окружение): снятие своей правки красит свой тест поимённо.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests._unwired import (
    code_without_comments,
    is_wiring,
    registry_recorded_scripts,
    scripts_without_caller,
    scripts_without_caller_by_patterns,
    wiring_patterns,
)

_SCRIPT = "target_script"
_BODY = 'if __name__ == "__main__":\n    print("hi")\n'


def _tree(tmp: pathlib.Path, files: dict) -> pathlib.Path:
    """Мини-репозиторий: скрипт с точкой входа + произвольные файлы вокруг него."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / f"{_SCRIPT}.py").write_text(_BODY, encoding="utf-8")
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


def _orphans(files: dict) -> list:
    with tempfile.TemporaryDirectory() as d:
        return scripts_without_caller(_tree(pathlib.Path(d), files))


class TestWiringFormsAreSeen(unittest.TestCase):
    """Сперва ВИДЕТЬ вызов — иначе строгость превращается в ложную сироту."""

    def test_a_bare_import_is_wiring(self):
        """`import <имя>` по sys.path — форма, которой сканер не видел вовсе.

        Живой пример: `scripts/orchestrator_queue.py` зовёт `check_tracker_drift`
        именно так. Не видеть её значит объявить сиротой ежедневно исполняемый
        скрипт, как только у него отнимут докстринги.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"import sys\nimport {_SCRIPT} as t\nt.main()\n"}))

    def test_a_bare_from_import_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"from {_SCRIPT} import main\nmain()\n"}))

    def test_an_indented_bare_import_is_wiring(self):
        """Импорт внутри функции — та же проводка; отступ её не отменяет."""
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"def go():\n    import {_SCRIPT}\n    return {_SCRIPT}\n"}))

    def test_dash_m_module_form_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "scripts/w.sh": f"#!/bin/bash\npython3 -m scripts.{_SCRIPT} --once\n"}))

    def test_runpy_run_path_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                f'import runpy\nrunpy.run_path("scripts/{_SCRIPT}.py")\n'}))

    def test_a_literal_that_is_not_a_docstring_is_still_wiring(self):
        """Литерал в аргументе — настоящий вызов, и вырезать его нельзя.

        Ровно та ошибка, ради которой докстринг вырезается по `ast`, а не
        регуляркой по кавычкам.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n'}))


class TestEachFormAloneIsEnough(unittest.TestCase):
    """По одному контролю НА КАЖДУЮ форму: в дереве стоит РОВНО одно доказательство.

    Смысл разбиения — адресность. В общем тесте «скрипт подключён» отказ любой из
    пяти форм выглядит одинаково, и сведение двух реализаций прошло бы с молча
    потерянной формой. Здесь снятие конкретной формы из `wiring_patterns` /
    `file_references` красит СВОЙ тест и называет её по имени.
    """

    def test_only_file_form_plist(self):
        """`file`: plist называет `<имя>.py` — так подключено большинство агентов."""
        self.assertNotIn(_SCRIPT, _orphans({
            "launchd/com.spa.x.plist":
                f"<plist><string>{_SCRIPT}.py</string></plist>\n"}))

    def test_only_path_form_from_a_namesake(self):
        """`path`: полный `scripts/<имя>.py` — единственное, что засчитывается однофамильцу."""
        self.assertNotIn(_SCRIPT, _orphans({
            f"spa_core/riskwire/{_SCRIPT}.py":
                f'CMD = "scripts/{_SCRIPT}.py"\n'}))

    def test_only_module_form(self):
        """`module`: `scripts.<имя>` — форма модуля в обёртке/workflow."""
        self.assertNotIn(_SCRIPT, _orphans({
            ".github/workflows/w.yml": f"jobs:\n  x:\n    run: scripts.{_SCRIPT}\n"}))

    def test_only_bare_import_form(self):
        """`import`: голый импорт по sys.path — форма, невидимая до цикла #255."""
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"import {_SCRIPT}\n"}))

    def test_only_bare_from_form(self):
        """`from`: `from <имя> import …` — вторая половина той же невидимой формы."""
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"from {_SCRIPT} import main\n"}))

    def test_only_protocol_style_dash_m_bare(self):
        """`-m <имя>` без префикса `scripts.` — запуск модулем из каталога скриптов."""
        self.assertNotIn(_SCRIPT, _orphans({
            "scripts/w.sh": f"#!/bin/bash\npython3 -m {_SCRIPT}\n"}))


class TestEvidenceWeakerThanACallIsNotWiring(unittest.TestCase):
    """И только потом — отнимать доказательства слабее вызова."""

    def test_a_module_docstring_mention_is_not_wiring(self):
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/m.py": f'"""В отличие от scripts/{_SCRIPT}.py, тут всё иначе."""\nx = 1\n'}))

    def test_a_function_docstring_mention_is_not_wiring(self):
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/m.py":
                f'def f():\n    """Раньше звали scripts/{_SCRIPT}.py."""\n    return 1\n'}))

    def test_a_class_docstring_mention_is_not_wiring(self):
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/m.py":
                f'class C:\n    """См. scripts/{_SCRIPT}.py."""\n    pass\n'}))

    def test_a_namesake_mentioning_itself_is_not_wiring(self):
        """Однофамилец в другом каталоге упоминает СЕБЯ, а не скрипт.

        `spa_core/riskwire/day30_review.py` и `spa_core/audit/ots_anchor.py`
        держали одноимённые скрипты «подключёнными», не вызывая их ни разу.
        """
        self.assertIn(_SCRIPT, _orphans({
            f"spa_core/riskwire/{_SCRIPT}.py":
                f"NAME = '{_SCRIPT}.py'\nprint('{_SCRIPT}.py работает')\n"}))

    def test_a_namesake_that_really_calls_the_script_IS_wiring(self):
        """Обратная сторона: строгость к однофамильцу не имеет права съесть вызов."""
        self.assertNotIn(_SCRIPT, _orphans({
            f"spa_core/riskwire/{_SCRIPT}.py":
                f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n'}))

    def test_a_longer_name_containing_this_one_is_not_wiring(self):
        """`perf_budget` ⊂ `dfb_perf_budget.py` — коллизия, а не вызов."""
        self.assertIn(_SCRIPT, _orphans({
            "scripts/dfb_helper.py": f'РЯДОМ = "dfb_{_SCRIPT}.py"\n'}))

    def test_a_longer_module_path_containing_this_one_is_not_wiring(self):
        """`scripts.run_backtest` ⊂ `scripts.run_backtest_real` — та же коллизия."""
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f"from scripts.{_SCRIPT}_real import main\n"}))

    def test_a_longer_name_ending_in_this_one_is_still_wiring_when_exact(self):
        """Ровное имя обязано находиться и рядом с однофамильцем-длиннее.

        Иначе граница слова превратилась бы в новую слепоту: файл, где лежат
        ОБА имени, перестал бы засчитываться за вызов настоящего.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "scripts/w.sh":
                f"#!/bin/bash\npython3 scripts/dfb_{_SCRIPT}.py\n"
                f"python3 scripts/{_SCRIPT}.py\n"}))

    def test_an_import_of_a_namesake_module_is_not_wiring(self):
        """`from spa_core.riskwire import day30_review` — импорт ОДНОФАМИЛЬЦА.

        Текстовое «\\bimport <имя>» назвало бы эту строку проводкой и сняло бы
        мёртвый скрипт с учёта. Разбор `ast` даёт полное dotted-имя, и оно со
        скриптом не совпадает.
        """
        self.assertIn(_SCRIPT, _orphans({
            f"spa_core/riskwire/{_SCRIPT}.py": "X = 1\n",
            "spa_core/caller.py": f"from spa_core.riskwire import {_SCRIPT}\n"}))


class TestTheStripperAndThePatterns(unittest.TestCase):
    """Единицы работы — отдельно от обхода дерева."""

    def test_docstring_goes_but_the_call_literal_stays(self):
        out = code_without_comments(
            pathlib.Path("x.py"),
            '"""см. scripts/drop.py"""\nrun("scripts/keep.py")\n')
        self.assertNotIn("scripts/drop.py", out)
        self.assertIn("scripts/keep.py", out)

    def test_line_numbers_survive_the_stripper(self):
        """Затирать пробелами, а не вырезать: строки не имеют права склеиваться.

        Склейка уже однажды порвала `from scripts.<имя> import …` пополам и
        сделала живой скрипт сиротой (#227).
        """
        src = '"""трёх\nстрочный\nдокстринг"""\nfrom scripts.x import main\n'
        out = code_without_comments(pathlib.Path("x.py"), src)
        self.assertEqual(len(out.splitlines()), len(src.splitlines()))
        self.assertIn("from scripts.x import main", out)

    def test_a_broken_python_file_keeps_its_docstrings_and_says_so(self):
        """Неразобравшийся файл — СЛАБЕЕ, и это названо, а не спрятано.

        `ast` на битом синтаксисе не работает; комментарии с такого файла всё
        равно снимаются запасным путём, а докстринги остаются. Проверка
        закрепляет именно это поведение, чтобы оно не изменилось молча.
        """
        out = code_without_comments(
            pathlib.Path("x.py"), 'def f(:\n    pass\n"""см. scripts/drop.py"""\n')
        self.assertIn("scripts/drop.py", out)

    def test_patterns_have_boundaries_on_both_sides(self):
        pats = wiring_patterns("perf_budget")
        self.assertIsNone(pats["file"].search("scripts/dfb_perf_budget.py"))
        self.assertIsNotNone(pats["file"].search("scripts/perf_budget.py"))
        self.assertIsNone(pats["module"].search("scripts.perf_budget_real"))
        self.assertIsNotNone(pats["module"].search("scripts.perf_budget "))

    def test_all_five_forms_exist_and_each_matches_only_its_own(self):
        """Пять форм — и ни одна не подменяет другую.

        Проверка адресная: пропажа любой формы при будущей правке красит эту
        строку с её именем, а не общее «что-то не находится».
        """
        pats = wiring_patterns("perf_budget")
        self.assertEqual(sorted(pats), ["file", "from", "import", "module", "path"])
        self.assertIsNotNone(pats["path"].search("python3 scripts/perf_budget.py"))
        self.assertIsNone(pats["path"].search("python3 tools/perf_budget.py"))
        self.assertIsNotNone(pats["import"].search("    import perf_budget\n"))
        self.assertIsNone(pats["import"].search("    import perf_budget_real\n"))
        self.assertIsNone(pats["import"].search("    import spa_core.perf_budget\n"))
        self.assertIsNotNone(pats["from"].search("from perf_budget import main\n"))
        self.assertIsNone(pats["from"].search("from perf_budget_real import main\n"))

    def test_the_namesake_rule_lives_in_is_wiring(self):
        """`is_wiring` судит однофамильца строже — отдельно от обхода дерева."""
        script = pathlib.Path("scripts/perf_budget.py")
        pats = wiring_patterns("perf_budget")
        namesake = pathlib.Path("spa_core/riskwire/perf_budget.py")
        stranger = pathlib.Path("spa_core/riskwire/other.py")
        self.assertFalse(is_wiring(namesake, 'N = "perf_budget.py"\n', script, pats))
        self.assertTrue(is_wiring(namesake, 'N = "scripts/perf_budget.py"\n', script, pats))
        self.assertTrue(is_wiring(stranger, 'N = "perf_budget.py"\n', script, pats))

    def test_the_cheap_cutoff_cannot_change_a_verdict(self):
        """Отсечка первой строкой обязана быть ТОЧНОЙ, а не приблизительной.

        Имя скрипта входит в каждую из пяти форм, значит файл без подстроки имени
        не может содержать ни одной из них — отсечка не имеет права ни добавить
        сироту, ни отнять. Цена отсечки измерена на живом дереве 17.08: 18.2 с
        против 231.0 с без неё (в 12.7 раза), вердикт тот же. Здесь закреплена
        именно неизменность вердикта — на синтетическом дереве, чтобы проверка
        стоила миллисекунды.
        """
        files = {
            "spa_core/caller.py": f"import {_SCRIPT}\n",
            "spa_core/prose.py": f'"""про scripts/{_SCRIPT}.py"""\n',
            "scripts/dfb_helper.py": f'РЯДОМ = "dfb_{_SCRIPT}.py"\n',
        }
        with tempfile.TemporaryDirectory() as d:
            root = _tree(pathlib.Path(d), files)
            self.assertEqual(
                scripts_without_caller_by_patterns(root, cheap_cutoff=True),
                scripts_without_caller_by_patterns(root, cheap_cutoff=False))


class TestRegistryIsJudgedByTheSamePatterns(unittest.TestCase):
    """Вычитаемый класс обязан быть НЕ СЛАБЕЕ самого измерения.

    До сведения 17.08 реестр R&D судился голой подстрокой (`m.name in text`) —
    ровно та подстрочная коллизия, от которой обход дерева уже был защищён. Дыра,
    переехавшая из измерения в поблажку, столь же молчалива: запись про
    `dfb_<имя>.py` вывела бы из-под храповика ЧУЖОЙ `<имя>`.
    """

    def _registry(self, body: str) -> set:
        with tempfile.TemporaryDirectory() as d:
            root = _tree(pathlib.Path(d), {})
            reg = root / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md"
            reg.parent.mkdir(parents=True, exist_ok=True)
            reg.write_text(body, encoding="utf-8")
            return registry_recorded_scripts(root)

    def test_an_exact_registry_entry_exempts(self):
        self.assertIn(_SCRIPT, self._registry(f"| замер | scripts/{_SCRIPT}.py | 2026-08 |\n"))

    def test_a_substring_registry_entry_does_not_exempt(self):
        self.assertNotIn(_SCRIPT, self._registry(f"| замер | scripts/dfb_{_SCRIPT}.py |\n"))

    def test_a_longer_module_entry_does_not_exempt(self):
        self.assertNotIn(_SCRIPT, self._registry(f"см. scripts.{_SCRIPT}_real\n"))


class TestTwoEnginesAgree(unittest.TestCase):
    """Два движка об одном дереве обязаны говорить одно и то же.

    Сторож три недели жил в двух реализациях, и разошлись они молча — каждая
    знала свои формы. После сведения обе живут рядом: одиночный проход
    (`scripts_without_caller`, движок по умолчанию) и перебор шаблонами
    (`scripts_without_caller_by_patterns`). Расхождение здесь называет имена,
    вместо того чтобы одна из версий тихо победила.
    """

    def test_the_two_engines_agree_on_a_synthetic_tree(self):
        files = {
            "spa_core/caller.py": f"import {_SCRIPT}\n",
            "spa_core/prose.py": f'"""про scripts/{_SCRIPT}.py"""\n',
            f"spa_core/riskwire/{_SCRIPT}.py": f"NAME = '{_SCRIPT}.py'\n",
            "launchd/com.spa.x.plist": "<plist><string>other.py</string></plist>\n",
            "scripts/second.py": 'if __name__ == "__main__":\n    pass\n',
        }
        with tempfile.TemporaryDirectory() as d:
            root = _tree(pathlib.Path(d), files)
            self.assertEqual(scripts_without_caller(root),
                             scripts_without_caller_by_patterns(root))

    def test_the_two_engines_agree_on_the_live_tree(self):
        """Живое дерево — единственное место, где расхождение уже случалось.

        Синтетика проверяет форму, но разошлись версии на настоящем репозитории.
        Прогон дорогой (десятки секунд), и это осознанная цена: дешевле он не
        отвечает на тот вопрос, ради которого заведён.
        """
        self.assertEqual(scripts_without_caller(), scripts_without_caller_by_patterns())


if __name__ == "__main__":
    unittest.main()
