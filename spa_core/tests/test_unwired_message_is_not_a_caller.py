"""Путь в ТЕКСТЕ ДЛЯ ЧЕЛОВЕКА — не проводка; путь в ЗАПУСКЕ — проводка (цикл #278).

**Авария, которую эти тесты воспроизводят.** Сканер неподключённых скриптов
(`spa_core/tests/_unwired.py`) считал проводкой любую подстроку `<имя>.py` в файле
каталогов `scripts/`·`spa_core/`·`launchd/`·`.github/`, не отличая ВЫЗОВ от
УПОМИНАНИЯ в тексте сообщения, которое скрипт печатает человеку.

Найдено циклом #257 своим же падением: шаг 0a получил строку-подсказку «убирать за
собой обязан `scripts/reap_stale_worktrees.py --worktree …`» — и храповик тут же
объявил уборщик ПОДКЛЮЧЁННЫМ, хотя вызывать его по-прежнему некому. Карточка
`inbox-hrapovik-nepodklyuchennyh-skriptov-schit-2`.

**Почему это четвёртый случай одного класса и почему он опаснее трёх прежних.**
Комментарий (#227), докстринг и однофамилец (#255) — доказательства слабее вызова, и
каждое снималось отдельным циклом. Текст сообщения — четвёртая форма: чтобы навсегда
снять НАСТОЯЩИЙ мёртвый скрипт с учёта, достаточно один раз назвать его имя в тексте
любой подсказки. Молча и без злого умысла.

**Почему «литерал вообще не доказательство» — неверная починка.**
`subprocess.run(["python3", "scripts/x.py"])` — настоящий вызов, и живёт он именно в
литерале. Поэтому решает ФОРМА литерала (цельный путь-токен) и КОНТЕКСТ
(аргументы запускателя), а не догадка о смысле. `TestLaunchFormsSurvive` идёт первым:
если сканер разучился видеть вызов, строгость превращается в ложную сироту, а
храповик, краснеющий на честной работе, в этом проекте признан исходом хуже пропуска
(#183, #255).

Каждая проверка — положительный контроль на синтетическом дереве (корень — вход
функции, а не окружение): снятие правки в `_unwired.py` красит свой тест поимённо.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests._unwired import code_without_comments, scripts_without_caller

_SCRIPT = "target_script"
_BODY = 'if __name__ == "__main__":\n    print("hi")\n'


def _tree(tmp: pathlib.Path, files: dict) -> pathlib.Path:
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


class TestLaunchFormsSurvive(unittest.TestCase):
    """Сперва ВИДЕТЬ запуск — иначе строгость к прозе съест живой скрипт."""

    def test_a_bare_path_token_in_a_list_is_wiring(self):
        """`subprocess.run(["python3", "scripts/x.py"])` — самая частая форма вызова."""
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                f'import subprocess\nsubprocess.run(["python3", "scripts/{_SCRIPT}.py"])\n'}))

    def test_a_command_string_with_flags_inside_a_launcher_is_wiring(self):
        """Команда с пробелами и флагами — тоже вызов, если она В ЗАПУСКАТЕЛЕ.

        Ровно эта форма отличает «текст с пробелами» от «сообщения»: пробел сам по
        себе прозы не доказывает, доказывает КОНТЕКСТ.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                "import subprocess\n"
                f'subprocess.run("python3 scripts/{_SCRIPT}.py --once", shell=True)\n'}))

    def test_an_fstring_command_inside_a_launcher_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                "import subprocess\nPY = 'python3'\n"
                f'subprocess.run(f"{{PY}} scripts/{_SCRIPT}.py --once", shell=True)\n'}))

    def test_a_path_built_by_operators_is_wiring(self):
        """`ROOT / "scripts" / "x.py"` — цельный токен, запускателя рядом нет."""
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                "import pathlib\nROOT = pathlib.Path('/x')\n"
                f'TOOL = ROOT / "scripts" / "{_SCRIPT}.py"\n'}))

    def test_a_path_built_by_os_path_join_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                f'import os\nTOOL = os.path.join("scripts", "{_SCRIPT}.py")\n'}))

    def test_runpy_run_path_is_wiring(self):
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py":
                f'import runpy\nrunpy.run_path("scripts/{_SCRIPT}.py")\n'}))

    def test_a_message_in_a_shell_wrapper_is_STILL_wiring(self):
        """Граница правки названа вслух: разбор контекста есть только у `.py`.

        В `.sh` нет `ast`, отличить `echo "запусти scripts/x.py"` от вызова нечем, и
        обрезка по `#` намеренно не трогает кавычки (иначе съест настоящий вызов,
        `test_a_hash_inside_quotes_is_not_a_comment`). Слепота остаётся — но она
        ЗАКРЕПЛЕНА тестом, а не забыта: если однажды `.sh` начнут разбирать, этот
        тест покраснеет и потребует решения, а не тихо изменит поведение.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "scripts/w.sh": f'#!/bin/bash\necho "запусти scripts/{_SCRIPT}.py сам"\n'}))

    def test_a_whitespace_free_path_in_a_message_is_STILL_wiring(self):
        """Вторая названная граница: `print("scripts/x.py")` по-прежнему проводка.

        Цельный путь-токен сохраняется НЕЗАВИСИМО от того, где он лежит: отличить
        `print(path)` от `Popen(path)` формой литерала нельзя, а перечислить всех
        писателей сообщений — нельзя тем более (`out.append`, `lines.append`,
        `return "…"`). Ошибка направлена в безопасную сторону: скрипт остаётся под
        наблюдением храповика. Закреплено, чтобы не изменилось молча.
        """
        self.assertNotIn(_SCRIPT, _orphans({
            "spa_core/caller.py": f'print("scripts/{_SCRIPT}.py")\n'}))


class TestAMessageIsNotWiring(unittest.TestCase):
    """И только потом — отнимать четвёртое доказательство слабее вызова."""

    def test_the_step_0a_hint_verbatim_is_not_wiring(self):
        """Дословно та строка, на которой класс был найден (цикл #257).

        Настоящая авария, а не её пересказ: `out.append("… `scripts/x.py --worktree
        <путь> --apply` …")` в `scripts/check_undelivered_work.py` снимала уборщик с
        учёта навсегда.
        """
        self.assertIn(_SCRIPT, _orphans({
            "scripts/check_undelivered_work.py":
                "def render(out):\n"
                '    out.append("      Дефект здесь — САМО снятие: убирать за собой обязан "\n'
                f'               "`scripts/{_SCRIPT}.py --worktree <путь> --apply` "\n'
                '               "(меряет, архивирует, оставляет квитанцию).")\n'}))

    def test_a_printed_recipe_is_not_wiring(self):
        """«Протестируй: python3 scripts/x.py --dry-run» — совет человеку."""
        self.assertIn(_SCRIPT, _orphans({
            "scripts/helper.py":
                f'print("  4. Протестируй: python3 scripts/{_SCRIPT}.py --dry-run")\n'}))

    def test_an_fstring_message_is_not_wiring(self):
        """f-строка судится ЦЕЛИКОМ: одно сообщение — одно решение."""
        self.assertIn(_SCRIPT, _orphans({
            "scripts/helper.py":
                "def report(lines, who):\n"
                f'    lines.append(f"{{who}}: обнови через scripts/{_SCRIPT}.py --apply")\n'}))

    def test_an_argparse_epilog_with_examples_is_not_wiring(self):
        """`epilog=` с примерами запуска — документация, а не запуск."""
        self.assertIn(_SCRIPT, _orphans({
            "scripts/helper.py":
                "import argparse\n"
                "argparse.ArgumentParser(\n"
                f'    epilog="Примеры:\\n  python3 scripts/{_SCRIPT}.py --date 2026-06-13\\n")\n'}))

    def test_an_error_message_telling_the_operator_to_run_it_is_not_wiring(self):
        """Форма `optimizer_ab`: «артефакта нет — Run scripts/x.py»."""
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/api/routers/optimizer.py":
                "def detail():\n"
                f'    return "Artifact not yet generated. Run scripts/{_SCRIPT}.py first."\n'}))

    def test_a_documented_command_served_by_the_api_is_not_wiring(self):
        """Форма `verify_riskwire`: значение поля `verify_with` в ответе API.

        Третья сторона запускает верификатор САМА, на своей машине; наш процесс его
        не зовёт ни разу.
        """
        self.assertIn(_SCRIPT, _orphans({
            "spa_core/api/routers/proof.py":
                "def payload(files):\n"
                '    return {"verify_with": '
                f'"python3 scripts/{_SCRIPT}.py " + " ".join(files)}}\n'}))

    def test_a_generated_file_header_is_not_wiring(self):
        """Форма `audit_protocol_blindness`: шапка, которую скрипт ВПИСЫВАЕТ в файл."""
        self.assertIn(_SCRIPT, _orphans({
            "scripts/generator.py":
                'HEADER = """_coverage.py — разметка модулей.\n\n'
                f'СГЕНЕРИРОВАНО scripts/{_SCRIPT}.py — не править руками.\n"""\n'}))


class TestTheStripperItself(unittest.TestCase):
    """Единица работы — отдельно от обхода дерева."""

    def test_the_message_goes_and_the_launch_stays_in_one_file(self):
        """Обе стороны на ОДНОМ входе: иначе проверка ловит только полполоса."""
        out = code_without_comments(pathlib.Path("x.py"), (
            "import subprocess\n"
            'print("совет: python3 scripts/drop.py --flag")\n'
            'subprocess.run("python3 scripts/keep.py --flag", shell=True)\n'
            'subprocess.run(["python3", "scripts/keep_too.py"])\n'))
        self.assertNotIn("scripts/drop.py", out)
        self.assertIn("scripts/keep.py", out)
        self.assertIn("scripts/keep_too.py", out)

    def test_line_numbers_survive_a_multiline_message(self):
        """Затирать пробелами, а не вырезать: строки не имеют права склеиваться.

        Склейка уже однажды порвала `from scripts.<имя> import …` пополам и сделала
        живой скрипт сиротой (#227). Многострочное сообщение — тот же капкан.
        """
        src = ('MSG = """первая scripts/drop.py\nвторая строка\nтретья"""\n'
               "from scripts.keep import main\n")
        out = code_without_comments(pathlib.Path("x.py"), src)
        self.assertEqual(len(out.splitlines()), len(src.splitlines()))
        self.assertNotIn("scripts/drop.py", out)
        self.assertIn("from scripts.keep import main", out)

    def test_an_fstring_is_judged_WHOLE_and_not_chunk_by_chunk(self):
        """Кусок f-строки — не самостоятельный литерал, и здесь это ВИДНО.

        Проверка добавлена циклом #280 по своей же мутации: разбор f-строки по
        кускам (вместо `JoinedStr` целиком) не покраснил НИ ОДНОГО теста #278 —
        свойство было объявлено в докстринге и не закреплено ничем. Своя мутация,
        не покрасившая ни одной проверки, — это и есть украшение, которого
        требует не допускать правило доставки.

        Дискриминирующий вход: подстановка и перевод строки режут сообщение так,
        что `scripts/drop.py` оказывается в куске БЕЗ пробелов. Целиком — это
        по-прежнему одно сообщение (путь исчезает); по кускам — «цельный
        путь-токен», который сохраняется, и мёртвый скрипт молча числится
        подключённым. То есть ровно та авария, ради которой писан весь файл.
        """
        src = 'name = "x"\nprint(f"запусти это:\\n  {name}\\nscripts/drop.py")\n'
        out = code_without_comments(pathlib.Path("x.py"), src)
        self.assertNotIn("scripts/drop.py", out)

    def test_a_docstring_that_is_a_bare_token_is_still_dropped(self):
        """Докстринг остаётся прозой, даже когда пробелов в нём нет.

        Без отдельного правила о докстрингах `\"\"\"x.py\"\"\"` прошёл бы как цельный
        путь-токен: два правила не заменяют друг друга.
        """
        out = code_without_comments(pathlib.Path("x.py"), '"""scripts/drop.py"""\nx = 1\n')
        self.assertNotIn("scripts/drop.py", out)

    def test_a_broken_python_file_keeps_its_messages_and_says_so(self):
        """Неразобравшийся файл — СЛАБЕЕ, и это названо, а не спрятано."""
        out = code_without_comments(
            pathlib.Path("x.py"), 'def f(:\n    pass\nprint("см. scripts/drop.py тут")\n')
        self.assertIn("scripts/drop.py", out)


if __name__ == "__main__":
    unittest.main()
