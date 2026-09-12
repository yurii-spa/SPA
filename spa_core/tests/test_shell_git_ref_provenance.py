"""Контроли прибора «ссылка — кэш или вопрос к серверу» (ЗАКАЗ #582, ADR-361).

Каждый контроль воспроизводит РЕАЛЬНУЮ форму из нашего набора, а не выдуманную
фикстуру. Главный — `test_reader_inside_a_function_called_after_the_fetch`:
он строит форму `code_sync_from_origin.sh`, где ссылку читают строки ВЫШЕ
`fetch`, а исполняются они ПОЗЖЕ, потому что лежат в теле функции. Мерка по
порядку строк объявила бы там уверенную ЛОЖНУЮ находку, и контроль краснеет
ровно тогда, когда дорога вызовов из прибора исчезает.
"""
from __future__ import annotations

import io
import sys
import json
import shutil
import unittest
import tempfile
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from shell_git_ref_provenance import (             # noqa: E402
    census, subject_keys, main, remote_ref, ref_candidates,
)

BASELINE = REPO / "scripts" / "shell_git_ref_provenance_baseline.json"


def tree(tmp: Path, **files: str) -> Path:
    """Дерево из shell-скриптов. Репозиторий git тут не нужен: прибор читает
    ТЕКСТ скриптов, а не состояние копии, — и это само по себе свойство,
    которое стоит держать (замер не должен зависеть от машины)."""
    root = tmp / "t"
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


def verdicts(root: Path) -> dict:
    return {f"{r['file']}:{r['line']}": r for r in census(root)["rows"]}


class WhatCountsAsProof(unittest.TestCase):
    """Ось 1 — свежесть: спрошено ли значение у сервера на этом пути."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refprov-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_unchecked_fetch_then_reset_is_not_gated(self):
        """Форма `git_autopush.sh`: отказ `fetch` залогирован и проигнорирован.

        Это и есть предмет заказа: при недоступной сети `reset --hard`
        переписывает дерево на ревизию НЕИЗМЕРЕННОГО возраста, и ни один
        код возврата об этом не скажет."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            'if git fetch origin main; then\n'
            '    echo ok\n'
            'else\n'
            '    echo "proceeding with cached remote state"\n'
            'fi\n'
            'git reset --hard origin/main\n')})
        row = verdicts(root)["a.sh:7"]
        self.assertEqual(row["verdict"], "asked_not_gated")
        self.assertTrue(row["mutating"])

    def test_fetch_whose_failure_returns_is_gated(self):
        """Форма `code_sync_from_origin.sh`: `if ! fetch; then … return; fi`."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            "main() {\n"
            '    if ! git fetch origin main -q; then\n'
            '        echo "FETCH FAILED"\n'
            '        return 0\n'
            '    fi\n'
            '    git checkout origin/main -- spa_core\n'
            "}\n"
            'main "$@"\n')})
        row = verdicts(root)["a.sh:7"]
        self.assertEqual(row["verdict"], "asked_and_gated")

    def test_reader_as_right_operand_of_and_is_gated(self):
        """Форма `agent_system_briefing.sh`: `fetch && reset` в подоболочке.

        Здесь сам `fetch` условен, и общее правило господства его отвергло бы —
        верно для вопроса «исполнится ли он», но не для нашего: без него не
        исполнится ЗОВ, а это и требовалось."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            'if [ -d "$M/.git" ]; then\n'
            '    ( cd "$M" \\\n'
            '      && git fetch --quiet origin main \\\n'
            '      && git reset --quiet --hard origin/main ) || true\n'
            'fi\n')})
        row = verdicts(root)["a.sh:5"]
        self.assertEqual(row["verdict"], "asked_and_gated")

    def test_no_fetch_at_all_is_cache_only(self):
        root = tree(self.tmp, **{"a.sh": "#!/bin/bash\ngit reset --hard origin/main\n"})
        row = verdicts(root)["a.sh:2"]
        self.assertEqual(row["verdict"], "cache_only")

    def test_fetch_of_another_branch_does_not_prove_this_ref(self):
        """Негативный контроль: `fetch origin dev` ссылку `origin/main` НЕ пишет.

        Без него прибор отвечал бы «спрошено» на любой `fetch` рядом —
        верный ответ по чужой причине."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            "git fetch origin dev || exit 1\n"
            "git reset --hard origin/main\n")})
        self.assertEqual(verdicts(root)["a.sh:3"]["verdict"], "cache_only")

    def test_ls_remote_is_not_an_updater(self):
        """`ls-remote` спрашивает сервер и НИЧЕГО не пишет в кэш.

        Считать его обновителем значило бы выдать за освежённую ссылку,
        которой он не касался (так устроен `pre_push_check.sh` — он потому и
        верен, что спрашивает сервер НАПРЯМУЮ, а не через кэш)."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            "git ls-remote origin main || exit 1\n"
            "git reset --hard origin/main\n")})
        self.assertEqual(verdicts(root)["a.sh:3"]["verdict"], "cache_only")


class ExecutionOrderNotLineOrder(unittest.TestCase):
    """Дорога вызовов — без неё прибор изготавливает ложную находку."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refprov-ord-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_reader_inside_a_function_called_after_the_fetch(self):
        """Ссылка читается СТРОКОЙ ВЫШЕ `fetch`, а исполняется ПОЗЖЕ него.

        Ровно `code_sync_from_origin.sh`: читатели на 118/146/148, `fetch` на
        176, и всё же читатели свежи — их зовёт `main` после 176-й. Мерка по
        номеру строки объявила бы здесь `cache_only`: уверенная ложь того
        самого класса, ради которого написана вся цепь."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            "main() {\n"
            "    look() {\n"
            "        git ls-tree -r --name-only origin/main -- CLAUDE.md\n"
            "    }\n"
            '    if ! git fetch origin main -q; then\n'
            "        return 0\n"
            "    fi\n"
            "    look\n"
            "}\n"
            'main "$@"\n')})
        row = verdicts(root)["a.sh:4"]
        self.assertEqual(row["verdict"], "asked_and_gated")
        self.assertIn("look()", row["why"])


class RemoteIdentityAxis(unittest.TestCase):
    """Ось 2 — о каком удалённом говорит зов; в вердикт не входит."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refprov-basis-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_url_literal_travels(self):
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            'URL="https://github.com/yurii-spa/SPA.git"\n'
            'git fetch "$URL" main:refs/remotes/origin/main || exit 1\n'
            "git reset --hard origin/main\n")})
        row = verdicts(root)["a.sh:4"]
        self.assertEqual(row["basis"], "by_url")
        self.assertEqual(row["verdict"], "asked_and_gated")

    def test_remote_name_is_config_not_code(self):
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            "git fetch origin main || exit 1\n"
            "git reset --hard origin/main\n")})
        self.assertEqual(verdicts(root)["a.sh:3"]["basis"], "by_config")

    def test_unresolved_variable_is_not_measured(self):
        """Имя удалённого из внешней переменной — третий исход, не догадка."""
        root = tree(self.tmp, **{"a.sh": (
            "#!/bin/bash\n"
            'git fetch "$SOMEWHERE" main:refs/remotes/origin/main || exit 1\n'
            "git reset --hard origin/main\n")})
        self.assertEqual(verdicts(root)["a.sh:3"]["basis"], "by_var")


class RefParsing(unittest.TestCase):
    """Формы аргумента, все три — из нашего набора."""

    def test_rev_path_form(self):
        self.assertEqual(
            remote_ref(ref_candidates("origin/main:docs/X.md")[0], {"origin"}),
            ("origin", "main"))

    def test_range_form(self):
        got = [remote_ref(c, {"origin"}) for c in ref_candidates("HEAD..origin/main")]
        self.assertIn(("origin", "main"), got)

    def test_a_path_with_a_slash_is_not_a_ref(self):
        """Иначе прибор объявил бы ссылкой любой `spa_core/tests`."""
        self.assertIsNone(remote_ref("spa_core/tests", {"origin"}))

    def test_refs_remotes_form_needs_no_remote_list(self):
        self.assertEqual(remote_ref("refs/remotes/upstream/dev", set()),
                         ("upstream", "dev"))


class RatchetAndThirdOutcome(unittest.TestCase):
    """Сторож сторожа: база, её отсутствие и «не измерено»."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refprov-ratchet-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_real_tree_matches_the_frozen_baseline(self):
        rc, _out, _err = self.run_main(["--root", str(REPO),
                                        "--baseline", str(BASELINE)])
        self.assertEqual(rc, 0, "предмет вырос — чинить код, а не базу")

    def test_empty_baseline_names_every_subject_call(self):
        """Положительный контроль САМОГО храповика: с пустой базой он обязан
        назвать поимённо весь предмет, а не промолчать."""
        empty = self.tmp / "empty.json"
        empty.write_text(json.dumps({"subject": []}), encoding="utf-8")
        rc, out, err = self.run_main(["--root", str(REPO), "--baseline", str(empty)])
        self.assertEqual(rc, 3)
        frozen = json.loads(BASELINE.read_text("utf-8"))["subject"]
        for key in frozen:
            self.assertIn(key, out + err)

    def test_missing_baseline_is_unmeasured_not_clean(self):
        rc, out, err = self.run_main(["--root", str(REPO),
                                      "--baseline", str(self.tmp / "нет.json")])
        self.assertEqual(rc, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", out + err)

    def test_tree_without_shell_scripts_refuses_loudly(self):
        """Пустое население — «не измерено», а НЕ «чисто». Прибор, отвечающий
        зелёным на дереве, где мерить нечего, — тот самый fail-OPEN."""
        empty_tree = self.tmp / "nosh"
        empty_tree.mkdir()
        rc, out, err = self.run_main(["--root", str(empty_tree)])
        self.assertEqual(rc, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", out + err)

    def test_a_new_ungated_reader_in_the_real_tree_grows_the_subject(self):
        """Контроль на СТОРОЖА: подсаженный в настоящее дерево зов обязан
        покраснеть поимённо. Контроль, никогда не видевший роста, — украшение."""
        copy = self.tmp / "repo"
        shutil.copytree(REPO / "scripts", copy / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (copy / "scripts" / "zz_probe.sh").write_text(
            "#!/bin/bash\ngit reset --hard origin/main\n", encoding="utf-8")
        rc, out, err = self.run_main(["--root", str(copy), "--baseline", str(BASELINE)])
        self.assertEqual(rc, 3)
        self.assertIn("scripts/zz_probe.sh:2", out + err)


class JsonIsExactlyOneDocument(unittest.TestCase):
    """Дефект приборов ADR-356 и ADR-360, воспроизведённый дважды: `--json`
    печатал документ, а следом человеческую строку. Здесь закреплено заранее."""

    def test_stdout_parses_whole(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(["--root", str(REPO), "--json", "--baseline", str(BASELINE)])
        doc = json.loads(out.getvalue())          # упадёт, если строка прилипла
        self.assertEqual(sorted(doc["by_verdict"]),
                         ["asked_and_gated", "asked_not_gated", "cache_only",
                          "unmeasured"])
        self.assertIn("храповик", err.getvalue())   # вердикт — в stderr, не в документе


class TheAnswerToTheOrder(unittest.TestCase):
    """Сам ответ заказа, закреплённый как свойство дерева.

    Две оси на этом населении РАСХОДЯТСЯ: там, где личность удалённого
    путешествует (URL в зове), свежесть не доказана, и наоборот. Если однажды
    появится зов, доказанный по обеим осям, этот контроль покраснеет — и это
    верно: ответ заказа изменится, и его надо будет переписать сознательно."""

    def test_no_call_is_proven_on_both_axes(self):
        rows = census(REPO)["rows"]
        both = [f"{r['file']}:{r['line']}" for r in rows
                if r["verdict"] == "asked_and_gated" and r["basis"] == "by_url"]
        self.assertEqual(both, [],
                         "появился зов, доказанный по обеим осям — обнови ADR-361")
        self.assertTrue(rows, "население пусто — это не «чисто», а «не измерено»")

    def test_every_mutating_reader_is_classified(self):
        rows = census(REPO)["rows"]
        mut = [r for r in rows if r["mutating"]]
        self.assertTrue(mut)
        for r in mut:
            self.assertIn(r["verdict"], ("asked_and_gated", "asked_not_gated",
                                         "cache_only", "unmeasured"))

    def test_subject_is_the_freshness_axis_only(self):
        rows = census(REPO)["rows"]
        keys = subject_keys(rows)
        gated = {f"{r['file']}:{r['line']}" for r in rows
                 if r["verdict"] == "asked_and_gated"}
        self.assertFalse(set(keys) & gated,
                         "в предмет попал зов с доказанной свежестью")


if __name__ == "__main__":
    unittest.main()
