"""Формы проводки и доказательства слабее вызова (цикл #255).

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

Каждая проверка — положительный контроль на синтетическом дереве (корень — вход
функции, а не окружение): снятие своей правки красит свой тест поимённо.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests import _unwired
from spa_core.tests._unwired import (
    code_without_comments,
    scripts_without_caller,
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


#: Файлы стога, к которым плоская модель кавычек НЕ подходит (вложенность
#: `$( … )` заводит свой контекст). Перечень ОБЪЯВЛЕН, а не выведен обходом:
#: замер 16.11 (цикл #1174) — из 226 файлов `.sh`/`.yml` ровно ОДИН.
_QUOTE_MODEL_MISFITS = ("scripts/verify_fleet_after_reboot.sh",)


class TestAHashInsideAnOpenShellStringIsNotAComment(unittest.TestCase):
    """ADR-1035: состояние кавычек обязано жить МЕЖДУ физическими строками.

    **Авария, которую воспроизводит первый тест.** Промпт оркестратора —
    одна строка оболочки (`PROMPT="…"`) на двадцать физических; прежняя
    редакция сбрасывала состояние кавычек на каждой строке, поэтому `инв. #16`
    в русской прозе читалось как начало комментария и стирало 66 % МЕСТА
    ОБЪЯВЛЕНИЯ шагов цикла. ОБЯЗАТЕЛЬНЫЙ шаг 1е (`publish_site_numbers`) от
    этого числился «доставленным и мёртвым» — ложная сирота, то есть исход,
    который модульный докстринг `_unwired.py` зовёт хуже пропуска.

    Остальные тесты — ОБРАТНАЯ сторона: правка не имеет права вернуть #227
    («упоминание в комментарии считается проводкой»). Поэтому настоящий
    комментарий обязан по-прежнему НЕ быть доказательством, и каждая форма
    спрошена отдельно.
    """

    def test_the_declaration_after_a_hash_in_an_open_string_survives(self):
        """Предмет ADR-1035: `#` внутри ОТКРЫТОЙ строки — не комментарий.

        **Сцена обязана РАЗЛИЧАТЬ, и первая редакция не различала.** Кавычка
        открывается на ОДНОЙ физической строке, а `#` и объявление лежат на
        ДРУГОЙ — только в этой форме прежняя редакция (сброс состояния на каждой
        строке) стирает объявление. Если `#` и открывающая кавычка стоят на
        одной строке, старый код тоже справляется, и тест становится
        украшением: мутация M1 (цикл #1174) пережила именно такую сцену.
        """
        wrapper = (
            'PROMPT="шаг 1а: разбери очередь; \\\n'
            '  шаг 1д (инв. #16 — молча не ослаблять); '
            'затем python3 scripts/target_script.py --if-due"\n'
            'claude -p "$PROMPT"\n'
        )
        self.assertEqual(_orphans({"scripts/wrapper.sh": wrapper}), [], (
            "объявление шага стёрто `#`-ем из прозы внутри открытой строки: "
            "это ложная сирота, предмет ADR-1035"))

    def test_a_whole_line_comment_is_still_not_wiring(self):
        """#227 остаётся закрытым: комментарий — не вызов."""
        sh = "# scripts/target_script.py больше НЕ подключён\necho hi\n"
        self.assertEqual(_orphans({"scripts/wrapper.sh": sh}), ["target_script"])

    def test_a_trailing_comment_is_still_not_wiring(self):
        """Хвостовой комментарий — тоже комментарий (иначе правка ослабила бы сторожа)."""
        sh = "echo hi   # scripts/target_script.py больше НЕ подключён\n"
        self.assertEqual(_orphans({"scripts/wrapper.sh": sh}), ["target_script"])

    def test_an_apostrophe_inside_a_comment_does_not_open_a_string(self):
        """Иначе `# don't` открыл бы строку до конца файла и снял все комментарии с учёта."""
        sh = ("# don't trust the first line\n"
              "echo hi   # scripts/target_script.py больше НЕ подключён\n")
        self.assertEqual(_orphans({"scripts/wrapper.sh": sh}), ["target_script"])

    def test_a_quote_inside_a_heredoc_body_opens_nothing(self):
        """Тело heredoc — не код оболочки: кавычка в нём ничего не открывает.

        Апостроф в теле обязан быть НЕПАРНЫМ, иначе сцена не различает: при
        парных кавычках состояние сходится и без распознавания heredoc, и
        мутация «heredoc не распознаётся» (M3, цикл #1174) сцену переживает.
        Непарный апостроф без распознавания открывает строку до конца файла,
        хвостовой комментарий перестаёт сниматься — и мёртвый скрипт молча
        числится подключённым.
        """
        sh = ("cat > /tmp/x <<JSON\n"
              "it's data, not code\n"
              "JSON\n"
              "echo hi   # scripts/target_script.py больше НЕ подключён\n")
        self.assertEqual(_orphans({"scripts/wrapper.sh": sh}), ["target_script"])

    def test_a_hash_after_an_opening_quote_on_the_SAME_line_was_already_handled(self):
        """Сторож того, что УЖЕ работало, и он НЕ контроль на ADR-1035.

        Названо вслух, потому что форма обманчива: кавычка открывается на той
        же физической строке, поэтому прежняя редакция эту сцену проходила —
        мутация, воспроизводящая предмет ADR-1035, её НЕ красит (замер M1,
        цикл #1174). Тест ценен как защита от регресса, а не как доказательство
        починки; доказательство — в тесте выше, где кавычка открыта РАНЬШЕ.
        """
        wrapper = (
            'MSG="шаг 1д (ADR-1033, инв. #16); шаг 1е python3 scripts/target_script.py"\n'
            'echo "$MSG"\n'
        )
        self.assertEqual(_orphans({"scripts/wrapper.sh": wrapper}), [])


class TestTheQuoteModelNamesWhereItDoesNotFit(unittest.TestCase):
    """Третий исход (инв. #17): «модель кавычек не подошла» — не ноль и не успех.

    Вложенность `$( … )` заводит внутри себя свой контекст кавычек, и плоская
    модель этого не видит. Ошибается это в сторону СОХРАНЕНИЯ текста (то есть
    пропуска, а не ложной сироты), и цена ИЗМЕРЕНА: на полном дифференциальном
    прогоне 16.11 набор сирот от правки меняется РОВНО на одно имя. Но молчать
    об этом нельзя — поэтому население НАЗВАНО, и у него два сторожа: один
    краснеет на РОСТ, другой — на то, что объявление стало ВЫДУМКОЙ.
    """

    def _misfits(self) -> set:
        root = pathlib.Path(_unwired._ROOT)
        out = set()
        dirs = [root / d for d in _unwired._HAY_DIRS]
        files = [p for d in dirs if d.exists() for p in d.rglob("*")]
        files += list(root.glob("*"))
        for p in files:
            if not (p.is_file() and p.suffix in (".sh", ".yml", ".yaml")):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _unwired._shell_comment_scan(text)[1]:
                out.add(str(p.relative_to(root)))
        return out

    def test_no_NEW_file_where_the_quote_model_does_not_fit(self):
        surplus = sorted(self._misfits() - set(_QUOTE_MODEL_MISFITS))
        self.assertEqual(surplus, [], (
            f"новые файлы, у которых кавычка остаётся НЕЗАКРЫТОЙ: {surplus}. "
            "Комментарии в них перестают сниматься — это пропуск, а не ложная "
            "сирота, но назвать его обязаны. Чинить файл или модель, а НЕ "
            "дописывать имя в _QUOTE_MODEL_MISFITS (инв. #16)"))

    def test_the_declared_misfits_are_not_a_fiction(self):
        """Объявление, переставшее быть правдой, хуже пустого: оно врёт молча."""
        still = self._misfits()
        stale = [n for n in _QUOTE_MODEL_MISFITS if n not in still]
        self.assertEqual(stale, [], (
            f"модель кавычек теперь ПОДХОДИТ к {stale} — убери имя из "
            "_QUOTE_MODEL_MISFITS, иначе объявление становится выдумкой"))


if __name__ == "__main__":
    unittest.main()
