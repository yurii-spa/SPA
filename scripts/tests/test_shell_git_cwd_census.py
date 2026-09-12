"""Положительные контроли переписи зовов git в shell (ЗАКАЗ #576, ADR-355).

Каждый тест — ловушка, названная заказом заранее, ИЛИ дефект самого прибора,
найденный по дороге. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`), поэтому здесь нет ни одного теста,
написанного «на всякий случай».

Ловушка заказа в одной строке: в shell каталог задаётся не параметром, а
СОСТОЯНИЕМ, и признак «в скрипте есть `cd`» ошибается в ОБЕ стороны.
"""
from __future__ import annotations

import sys
import unittest
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shell_git_cwd_census as sc          # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "shell_git_cwd_census.py"


def parse(text):
    """Разобрать источник ВМЕСТЕ с вложенными подстановками.

    Зов внутри `$(…)` разбирается отдельным источником, и помощник, который их не
    сливает, отвечал бы на свой вопрос, а не на нужный: ровно половина настоящих
    зовов набора спрятана в подстановках."""
    cmds, pending, ranges = sc.parse_commands(text)
    queue = list(pending)
    while queue:
        src, line0 = queue.pop()
        sub_cmds, sub_pending, sub_ranges = sc.parse_commands(src, line0)
        cmds.extend(sub_cmds)
        ranges.extend(sub_ranges)
        queue.extend(sub_pending)
    return cmds, ranges


def git_calls(text):
    return [c for c in parse(text)[0]
            if c["argv"][0] == "git" or c["argv"][0].endswith("/git")]


class LexerSeparatesCallFromMention(unittest.TestCase):
    """ЗОВ и УПОМИНАНИЕ — разные вещи, и греп путает их в обе стороны."""

    def test_git_inside_double_quotes_is_not_a_call(self):
        # `install_git_hooks.sh:84` печатает подсказку про `git commit --no-verify`.
        # Греп засчитывает её зовом; зова там нет.
        self.assertEqual(git_calls('echo "To skip: git commit --no-verify"'), [])

    def test_git_inside_single_quotes_is_not_a_call(self):
        self.assertEqual(git_calls("echo 'git push origin main'"), [])

    def test_git_in_a_comment_is_not_a_call(self):
        self.assertEqual(git_calls("# git reset --hard origin/main\ntrue"), [])

    def test_git_inside_command_substitution_IS_a_call(self):
        # Обратная ошибка грепа: зов, спрятанный в строке. `git_push.sh:30`.
        calls = git_calls('[ -z "$(git ls-files --others)" ] && echo empty')
        self.assertEqual([c["argv"][:2] for c in calls], [["git", "ls-files"]])

    def test_git_inside_parameter_expansion_IS_a_call(self):
        # `secure_git_push.sh:52`: BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
        calls = git_calls('B="${1:-$(git rev-parse --abbrev-ref HEAD)}"')
        self.assertEqual([c["argv"][:2] for c in calls], [["git", "rev-parse"]])

    def test_three_calls_on_one_line_are_three(self):
        """Единица учёта — ЗОВ, а не строка и не файл (требование заказа)."""
        line = ('if git diff --quiet && git diff --cached --quiet '
                '&& [ -z "$(git ls-files --others)" ]; then true; fi')
        self.assertEqual(len(git_calls(line)), 3)

    def test_bang_prefix_does_not_swallow_the_call(self):
        """`if ! git checkout origin/main -- "$P"` — мутирующий зов с путём.

        Пока `!` разбирался как команда, он забирал `git checkout … -- <путь>` себе
        в аргументы, и зов пропадал из переписи МОЛЧА. Это ровно тот зов, ради
        которого написан весь заказ."""
        calls = git_calls('if ! git checkout origin/main -- "$P"; then false; fi')
        self.assertEqual([c["argv"][:2] for c in calls], [["git", "checkout"]])

    def test_env_assignment_prefix_does_not_swallow_the_call(self):
        calls = git_calls('GIT_DIR=/x git status')
        self.assertEqual([c["argv"][:2] for c in calls], [["git", "status"]])


class HeredocBodyIsNotShell(unittest.TestCase):
    """Тело heredoc'а — ЧУЖОЙ язык, и разбор его как shell врёт в обе стороны."""

    SRC = ('main() {\n'
           '    cd "$REPO"\n'
           '    ws() {\n'
           '        "$PY" - <<\'PYEOF\'\n'
           'd = {"note": "git commit -m x"}\n'
           'PYEOF\n'
           '    }\n'
           '    git status\n'
           '}\n')

    def test_word_git_inside_a_heredoc_is_not_a_call(self):
        self.assertEqual([c["argv"][:2] for c in git_calls(self.SRC)],
                         [["git", "status"]])

    def test_braces_inside_a_heredoc_do_not_corrupt_scope(self):
        """`{` питоновского словаря ломал счёт функций: `write_status` никогда не
        закрывалась, и всё, что стояло ниже, приписывалось ей — включая зов из
        `main`. Область — вход дальнейшего доказательства, и врала она молча."""
        call = git_calls(self.SRC)[0]
        self.assertEqual(call["func"], "main")


class CdIsASignNotAVerdict(unittest.TestCase):
    """«В скрипте есть `cd`» ошибается в обе стороны — обе стороны здесь."""

    def _source_of(self, text, plists=None, callers=None):
        cmds, ranges = parse(text)
        cds = [c for c in cmds if c["argv"][0] in ("cd", "pushd")]
        call = [c for c in cmds if c["argv"][0] == "git"][0]
        call["file"] = "probe.sh"
        invs = [c for c in cmds if c["argv"][0] not in ("cd", "pushd", "git")]
        return sc.cwd_source(call, cds, plists or {}, callers or {}, invs)[0]

    def test_cd_AFTER_the_call_does_not_count(self):
        self.assertEqual(self._source_of('git status\ncd /tmp\n'), "ambient")

    def test_cd_in_an_unexecuted_branch_is_not_proven(self):
        src = 'if [ -d /x ]; then cd /x; fi\ngit status\n'
        self.assertEqual(self._source_of(src), "unproven_cd")

    def test_cd_as_right_operand_of_and_is_not_proven(self):
        """`[ -d x ] && cd x` каталог гарантированно НЕ меняет."""
        self.assertEqual(self._source_of('[ -d /x ] && cd /x\ngit status\n'),
                         "unproven_cd")

    def test_cd_or_exit_IS_proven(self):
        """`cd "$REPO" || exit 1` — условен ВЫХОД, а не `cd`. Обратный контроль к
        предыдущему: без него правило «есть `&&`/`||` ⇒ не доказано» сняло бы с
        учёта самый частый в наборе способ сменить каталог."""
        self.assertEqual(self._source_of('cd "$REPO" || exit 1\ngit status\n'),
                         "self")

    def test_cd_as_the_CONDITION_of_if_IS_proven(self):
        """`if ! cd "$REPO_DIR"; then …` — условие исполняется ВСЕГДА.

        Пока условие считалось телом ветки, все 19 зовов `git_autopush.sh` (среди
        них `reset --hard`, `rebase`, `push`) числились «`cd` не доказан». Ни один
        из них не стал от этого безопаснее или опаснее — врал прибор."""
        src = 'if ! cd "$REPO_DIR"; then exit 1; fi\ngit status\n'
        self.assertEqual(self._source_of(src), "self")

    def test_cd_as_the_condition_of_ELIF_is_NOT_proven(self):
        """Обратный контроль к предыдущему: условие `elif` исполняется, только
        если прошлая ветка не сошлась. Уравнять его с `if` значило бы изготовить
        доказательство из ничего — та же ошибка, но в другую сторону."""
        src = 'if false; then true; elif cd /x; then true; fi\ngit status\n'
        self.assertEqual(self._source_of(src), "unproven_cd")

    def test_cd_in_the_BODY_after_a_condition_is_still_a_branch(self):
        """И третий контроль — что поправка не размыла границу: `cd` в ТЕЛЕ
        остаётся ветвью, иначе первый контроль этого класса умер бы молча."""
        src = 'if [ -d /x ]; then cd /x; fi\ngit status\n'
        self.assertEqual(self._source_of(src), "unproven_cd")

    def test_absence_of_cd_is_not_ambient_when_launchd_sets_the_directory(self):
        """Вторая сторона ловушки, названная заказом дословно: отсутствие `cd` НЕ
        означает ambient — обёртку мог позвать launchd с `WorkingDirectory`."""
        plists = {"probe.sh": [{"plist": "x.plist", "wd": "/repo", "installed": True}]}
        self.assertEqual(self._source_of('git status\n', plists=plists), "plist")

    def test_launchd_without_working_directory_is_its_own_outcome(self):
        plists = {"probe.sh": [{"plist": "x.plist", "wd": None, "installed": True}]}
        self.assertEqual(self._source_of('git status\n', plists=plists), "plist_no_wd")

    def test_caller_that_sets_cwd_makes_the_call_determined(self):
        callers = {"probe.sh": [{"caller": "w.sh", "line": 9,
                                 "sets_cwd": True, "is_test": False}]}
        self.assertEqual(self._source_of('git status\n', callers=callers), "wrapper")

    def test_a_TEST_that_mentions_the_script_is_not_a_wrapper(self):
        """Классификация по ИМЕНИ ошибается в обе стороны — дефект, который
        ADR-354 нашёл у себя и который воспроизвёлся здесь до первой проверки:
        `code_sync_from_origin.sh` упоминают девять тест-файлов, и ни один его не
        запускает. Тест задаёт каталог сам и про прод не свидетельствует."""
        callers = {"probe.sh": [{"caller": "t.py", "line": 3,
                                 "sets_cwd": True, "is_test": True}]}
        self.assertEqual(self._source_of('git status\n', callers=callers), "ambient")


class DominanceIsProvedNotGuessed(unittest.TestCase):

    def test_cd_at_the_top_of_the_same_function_dominates(self):
        src = 'main() {\n    cd "$REPO"\n    git status\n}\nmain\n'
        cmds, _ = parse(src)
        cds = [c for c in cmds if c["argv"][0] == "cd"]
        call = [c for c in cmds if c["argv"][0] == "git"][0]
        got, why = sc.dominating_cd(cds, call, cmds)
        self.assertIsNotNone(got)
        self.assertIn("той же области", why)

    def test_cd_reaches_a_call_through_the_in_file_call_graph(self):
        """Форма `code_sync_from_origin.sh`: `cd` наверху `main`, а путь читает
        функция, которую `main` зовёт ниже. Без этой дороги все три зова файла
        объявлялись «обёрткой» — вердикт верный, причина ЧУЖАЯ, и держался он на
        постороннем файле, который завтра переименуют."""
        src = ('helper() {\n    git ls-tree -r --name-only origin/main -- CLAUDE.md\n}\n'
               'main() {\n    cd "$REPO"\n    helper\n}\nmain\n')
        path = _write(self, src)
        calls, cds, err = sc.collect_calls(path, path.parent)
        self.assertIsNone(err)
        got, why = sc.dominating_cd(cds, calls[0], sc._INVOCATIONS[path.name])
        self.assertIsNotNone(got, "дорога через граф зовов не сошлась")
        self.assertIn("зовётся строкой", why)

    def test_a_function_definition_is_not_an_invocation(self):
        """Определение стои́т там, где его написали, а не там, где функцию зовут.
        Пока `name() {` считалось зовом, вторая дорога мерила лишнюю точку."""
        cmds, _ = parse('helper() {\n    true\n}\nhelper\n')
        sites = [c for c in cmds if c["argv"][0] == "helper"]
        self.assertEqual([c["line"] for c in sites], [4])

    def test_a_function_never_invoked_in_the_file_stays_unproven(self):
        src = 'cd /repo\nhelper() {\n    git status\n}\n'
        path = _write(self, src)
        calls, cds, err = sc.collect_calls(path, path.parent)
        self.assertIsNone(err)
        got, _ = sc.dominating_cd(cds, calls[0], sc._INVOCATIONS[path.name])
        self.assertIsNone(got, "функция, которую в файле не зовут, доказана быть не может")


class SubshellHasItsOwnDirectory(unittest.TestCase):
    """`cd` внутри `( … )` не переживает закрывающую скобку."""

    def test_subshell_cd_does_not_dominate_a_call_after_it(self):
        """Идиома `SCRIPT_DIR="$( cd "$(dirname …)" && pwd )"` живёт в наборе
        (`auto_push.sh:6`, `diagnose_push.sh:36`). Пока подоболочки не считались,
        этот `cd` объявлялся господствующим НАД ВСЕМ, что ниже по файлу, и любой
        зов такого скрипта получал бы «каталог задан сам» — вердикт, который
        прибор выдумал, а не измерил."""
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "probe.sh").write_text(
            'SCRIPT_DIR="$( cd /x && pwd )"\ngit rev-list HEAD -- P.txt\n')
        r = sc.census(repo, observe=False)
        call = [c for c in r["calls"] if c["file"].endswith("probe.sh")][0]
        self.assertNotEqual(call["cwd_source"], "self",
                            "`cd` из подоболочки объявлен господствующим")
        self.assertIn(call["cwd_source"], sc.UNDETERMINED)

    def test_cd_inside_a_subshell_DOES_serve_calls_inside_it(self):
        """Обратный контроль: внутри своей подоболочки `cd` работает как обычно,
        иначе поправка просто запретила бы целый рабочий способ."""
        src = '( cd /repo\n  git status\n)\n'
        cmds, _ = parse(src)
        cds = [c for c in cmds if c["argv"][0] == "cd"]
        call = [c for c in cmds if c["argv"][0] == "git"][0]
        self.assertEqual(cds[0]["scope"], call["scope"])
        self.assertIsNotNone(sc.dominating_cd(cds, call, cmds)[0])

    def test_an_undetermined_directory_is_still_observed(self):
        """«`cd` есть, но не доказан» обязан ПОПАДАТЬ в предмет наблюдения.

        Иначе слепой зов прячется в третьем исходе и не меряется никогда — то есть
        «не доказано» складывается в «в порядке» (инвариант #17 наизнанку)."""
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "probe.sh").write_text(
            'if [ -d /x ]; then cd /x; fi\ngit rev-list HEAD -- P.txt\n')
        r = sc.census(repo, observe=True)
        subj = [c for c in r["subject"] if c["file"].endswith("probe.sh")]
        self.assertEqual(len(subj), 1, "зов с недоказанным каталогом выпал из предмета")
        self.assertEqual(subj[0]["cwd_source"], "unproven_cd")
        self.assertEqual(len([c for c in r["blind"] if c["file"].endswith("probe.sh")]), 1)


class TheAccidentIsFound(unittest.TestCase):
    """Настоящая авария #574 в shell-обличье: прибор обязан на ней краснеть."""

    def test_ambient_call_carrying_a_cwd_path_is_the_subject_and_is_blind(self):
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "probe.sh").write_text(
            '#!/bin/bash\n# каталог не задан ничем\ngit rev-list HEAD -- P.txt\n')
        r = sc.census(repo, observe=True)
        subj = [c for c in r["subject"] if c["file"].endswith("probe.sh")]
        self.assertEqual(len(subj), 1, "зов не попал в предмет")
        self.assertEqual(subj[0]["cwd_source"], "ambient")
        blind = [c for c in r["blind"] if c["file"].endswith("probe.sh")]
        self.assertEqual(len(blind), 1, "наблюдение не назвало зов слепым")

    def test_the_same_call_with_a_proven_cd_is_NOT_the_subject(self):
        """Обратный контроль. Без него предыдущий тест доказывал бы только, что
        прибор умеет краснеть, — а не что он краснеет ПО ДЕЛУ."""
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "probe.sh").write_text(
            '#!/bin/bash\ncd "$REPO" || exit 1\ngit rev-list HEAD -- P.txt\n')
        r = sc.census(repo, observe=False)
        self.assertEqual([c for c in r["subject"] if c["file"].endswith("probe.sh")], [])

    def test_call_without_a_path_is_not_in_the_class_even_when_ambient(self):
        """«Каталог не задан» само по себе не дефект: предмет класса — зов,
        несущий ПУТЬ от каталога запуска."""
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "probe.sh").write_text('#!/bin/bash\ngit rev-parse HEAD\n')
        r = sc.census(repo, observe=False)
        self.assertEqual([c for c in r["subject"] if c["file"].endswith("probe.sh")], [])


class AbsenceOfMeasurementIsItsOwnOutcome(unittest.TestCase):
    """Инвариант #17: «не измерено» никогда не выдаётся за «чисто»."""

    def test_not_a_repository_refuses_with_code_2(self):
        repo = _repo(self, git=False)
        self.assertEqual(sc.main(["--root", str(repo)]), 2)

    def test_unreadable_script_is_named_and_reddens(self):
        repo = _repo(self)
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        bad = repo / "scripts" / "broken.sh"
        bad.write_bytes(b"\xff\xfe\x00garbage\n")
        r = sc.census(repo, observe=False)
        self.assertTrue(any("broken.sh" in u for u in r["unread"]),
                        "нечитаемый файл обязан быть НАЗВАН, а не пропущен молча")
        self.assertEqual(sc.main(["--root", str(repo), "--no-observe"]), 2)

    def test_network_subcommand_is_never_declared_insensitive(self):
        """Прибор в сеть не ходит, поэтому про `fetch`/`push` он обязан говорить
        «не измерено», а не «устойчив»: одинаковый отказ из двух каталогов — это
        отсутствие ответа, а не ответ."""
        verdict, why = sc.observe_sensitivity(
            ["git", "fetch", "origin", "main"], {"pathspec": []}, Path("/nonexistent"),
            {}, Path("/nonexistent"))
        self.assertEqual(verdict, "unmeasured")
        self.assertIn("сеть", why)


class TheInstrumentRunsAsAProgram(unittest.TestCase):

    def test_exit_code_zero_on_the_real_repository(self):
        """Проводка: прибор обязан ИСПОЛНЯТЬСЯ, а не только импортироваться."""
        root = Path(__file__).resolve().parents[2]
        res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                              "--no-observe"], capture_output=True, timeout=600)
        self.assertIn(res.returncode, (0, 3),
                      f"прибор не исполнился: {res.stderr.decode()[:400]}")
        self.assertIn("НАСЕЛЕНИЕ ПО ИСТОЧНИКУ", res.stdout.decode())


# ───────────────────────────── вспомогательное ─────────────────────────────

def _repo(case, git=True):
    import tempfile
    td = tempfile.mkdtemp(prefix="shcensus-t-")
    case.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
    root = Path(td)
    if git:
        (root / ".git").mkdir()
    return root


def _write(case, text):
    root = _repo(case)
    p = root / "probe.sh"
    p.write_text(text)
    return p


if __name__ == "__main__":
    unittest.main()
