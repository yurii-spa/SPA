"""Сторож прибора ЗАКАЗА #583 (ADR-362): `origin/main` из python — кэш или сервер.

Каждый тест — положительный контроль: он воспроизводит форму, на которой прибор
УЖЕ ошибался или мог бы ошибиться молча. Проверка, никогда не видевшая настоящей
поломки, — украшение (`.claude/rules/deployment.md`).

Главный из них — :meth:`TestGating.test_shadowed_result_name_is_not_gated`.
Первая редакция прибора объявила `scripts/deploy_site_snapshot.py:120`
ДОКАЗАННО СВЕЖИМ, потому что искала `if <имя>.returncode` где угодно в функции.
Там результат `fetch` связан именем `r`, следующая строка ПЕРЕПРИСВАИВАЕТ `r`
результатом `show`, и проверка на 122-й судит о `show`. Код возврата фетча не
читает никто. Это `asked_not_gated`, выданное за `asked_and_gated`, — то есть
прибор врал в сторону «всё доказано» ровно на той ловушке, которую заказ назвал
заранее.
"""

from __future__ import annotations

import io
import json
import sys
import shutil
import tempfile
import unittest
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from python_git_ref_provenance import (          # noqa: E402
    census, subject_keys, main, ref_candidates, remote_ref, subcommand, DYN, unresolved_keys)

BASELINE = REPO / "scripts" / "python_git_ref_provenance_baseline.json"


class Tree(unittest.TestCase):
    """Синтетическое дерево: ровно те формы, о которых идёт спор."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="c583_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, rel: str, body: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def rows(self, **files):
        for rel, body in files.items():
            self.write(rel.replace("__", "/") + ".py", body)
        return census(self.tmp)["rows"]

    def verdict(self, **files):
        rows = self.rows(**files)
        self.assertTrue(rows, "население пусто — форма не распознана вовсе")
        return rows[0]["verdict"]


HEAD = "import subprocess\n"


class TestGating(Tree):
    """Ось 1: прекращает ли ОТКАЗ спроса путь."""

    def test_shadowed_result_name_is_not_gated(self):
        """Имя результата ПЕРЕПРИСВОЕНО — проверка ниже судит о другом вызове.

        Ровно форма `scripts/deploy_site_snapshot.py` (строки 118/120/122), на
        которой прибор поймал сам себя. Тень имени тише, чем отсутствие
        проверки: проверка есть, она просто не про фетч."""
        self.assertEqual("asked_not_gated", self.verdict(m=HEAD + """
def look(path):
    r = subprocess.run(["git", "fetch", "-q", "origin", "main"],
                       capture_output=True)
    r = subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
    if r.returncode != 0:
        return True
    return r.stdout
"""))

    def test_returncode_checked_before_rebind_is_gated(self):
        """Тот же текст, но проверка стои́т ДО переприсваивания — и это гейт.

        Обратная сторона теста выше: без неё починка могла бы просто перестать
        признавать гейты вовсе, и «предмет не растёт» означало бы «прибор ослеп»."""
        self.assertEqual("asked_and_gated", self.verdict(m=HEAD + """
def look(path):
    r = subprocess.run(["git", "fetch", "-q", "origin", "main"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    r = subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
    return r.stdout
"""))

    def test_unchecked_run_is_not_gated(self):
        """Результат не связан вовсе: при недоступной сети — тишина и кэш."""
        self.assertEqual("asked_not_gated", self.verdict(m=HEAD + """
def look():
    subprocess.run(["git", "fetch", "origin", "main"])
    return subprocess.run(["git", "log", "origin/main"], capture_output=True)
"""))

    def test_check_true_is_gated(self):
        self.assertEqual("asked_and_gated", self.verdict(m=HEAD + """
def look():
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    return subprocess.run(["git", "log", "origin/main"], capture_output=True)
"""))

    def test_check_output_raises_and_is_gated(self):
        self.assertEqual("asked_and_gated", self.verdict(m=HEAD + """
def look():
    subprocess.check_output(["git", "fetch", "origin", "main"])
    return subprocess.run(["git", "log", "origin/main"], capture_output=True)
"""))

    def test_checked_but_only_logged_is_not_gated(self):
        """Код возврата прочитан, но путь НЕ прерван — форма morning_work_digest."""
        self.assertEqual("asked_not_gated", self.verdict(m=HEAD + """
def look(unread):
    got = subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)
    if got.returncode != 0:
        unread.append("fetch не прошёл")
    return subprocess.run(["git", "log", "origin/main"], capture_output=True)
"""))

    def test_no_updater_at_all_is_cache_only(self):
        self.assertEqual("cache_only", self.verdict(m=HEAD + """
def look():
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
"""))

    def test_ls_remote_is_not_an_updater(self):
        """`ls-remote` спрашивает сервер и НИЧЕГО не пишет — ссылку не освежает."""
        self.assertEqual("cache_only", self.verdict(m=HEAD + """
def look():
    subprocess.run(["git", "ls-remote", "origin", "main"], check=True)
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
"""))

    def test_fetch_of_another_branch_does_not_prove_this_ref(self):
        self.assertEqual("cache_only", self.verdict(m=HEAD + """
def look():
    subprocess.run(["git", "fetch", "origin", "release"], check=True)
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
"""))

    def test_fetch_inside_an_if_does_not_dominate(self):
        """Обновитель в теле ветвления исполнится не всегда — значит не господствует."""
        self.assertEqual("cache_only", self.verdict(m=HEAD + """
def look(net):
    if net:
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)
"""))


class TestCallGraph(Tree):
    """Господство считается по ГРАФУ ВЫЗОВОВ, а не по строкам."""

    def test_reader_above_the_fetch_by_lines_but_after_it_in_execution(self):
        """Ловушка №1 заказа; на ней ADR-361 поймал `code_sync_from_origin.sh`.

        Читатель стои́т ВЫШЕ обновителя по строкам и ПОЗЖЕ него по исполнению,
        потому что лежит в теле функции, зовомой после фетча."""
        self.assertEqual("asked_and_gated", self.verdict(m=HEAD + """
def read_it():
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)


def main():
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    return read_it()
"""))

    def test_one_undominated_call_site_breaks_the_proof(self):
        """«Каждый зов господствуем» — значит КАЖДЫЙ, а не первый попавшийся."""
        self.assertEqual("cache_only", self.verdict(m=HEAD + """
def read_it():
    return subprocess.run(["git", "show", "origin/main:x"], capture_output=True)


def main():
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    return read_it()


def other():
    return read_it()
"""))


class TestDoors(Tree):
    """Дверь к git: в python зова с литералом почти нет."""

    def test_vararg_wrapper_is_a_door(self):
        """`def _git(cwd, *args)` — самая частая дверь дерева.

        Первая редакция брала параметры без `vararg` и ТЕРЯЛА
        `check_undelivered_work.py` и `adr_number.py` — двух крупнейших
        потребителей ссылки. Ошибка в сторону занижения населения."""
        rows = self.rows(m=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def look(root):
    return _git(root, "show", "origin/main:x")
""")
        self.assertEqual(1, len(rows))
        self.assertEqual("show", rows[0]["sub"])

    def test_argparse_default_reaches_the_call(self):
        """`ap.add_argument("--base", default=DEFAULT_BASE)` → `args.base`."""
        rows = self.rows(m=HEAD + """
import argparse
DEFAULT_BASE = "origin/main"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args()
    return _git(".", "show", args.base + ":x")
""")
        self.assertEqual(1, len(rows), "умолчание argparse не доехало до зова")

    def test_attribute_of_a_random_object_is_not_a_namespace(self):
        """Разрешается только имя, ЗАМЕРЕННО связанное с `parse_args()`."""
        self.assertEqual([], self.rows(m=HEAD + """
import argparse


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def main(cfg):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    return _git(".", "show", cfg.base + ":x")
"""))

    def test_injected_door_parameter(self):
        """`def f(root, git=_git)` — дверь видна только в СИГНАТУРЕ."""
        rows = self.rows(m=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def look(root, base_ref="origin/main", git=_git):
    return git(root, "show", f"{base_ref}:INDEX.md")
""")
        self.assertEqual(1, len(rows))

    def test_imported_door_from_a_sibling_module(self):
        """`from check_undelivered_work import _git` — форма `adr_number.py`."""
        rows = self.rows(
            lib=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)
""",
            user="""
from lib import _git


def look(root, base_ref="origin/main", git=_git):
    return git(root, "show", f"{base_ref}:INDEX.md")
""")
        self.assertEqual(1, len(rows))
        self.assertEqual("user.py", rows[0]["file"])

    def test_param_value_inherited_from_the_caller(self):
        """Параметр БЕЗ умолчания: значение приезжает от вызывающего.

        Форма `adr_number._origin_index(root, base_ref, git=_git)`. Без этого
        прохода чтение реестра ADR — того самого, который решает, занят ли номер
        решения на origin, — терялось целиком."""
        rows = self.rows(m=HEAD + """
DEFAULT_BASE = "origin/main"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def _origin_index(root, base_ref, git=_git):
    return git(root, "show", f"{base_ref}:INDEX.md")


def taken(root, base_ref=DEFAULT_BASE):
    return _origin_index(root, base_ref)
""")
        self.assertEqual(1, len(rows))
        self.assertEqual("show", rows[0]["sub"])

    def test_disagreeing_callers_leave_the_name_unbound(self):
        """Разные вызывающие передают разное ⇒ не связывать, а не угадывать."""
        self.assertEqual([], self.rows(m=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def read(root, base_ref):
    return _git(root, "show", f"{base_ref}:INDEX.md")


def a(root):
    return read(root, "origin/main")


def b(root):
    return read(root, "HEAD")
"""))

    def test_wrapper_call_site_is_not_counted_twice(self):
        """Обёртка над дверью лишь передаёт ссылку вниз — это ТО ЖЕ чтение."""
        rep = census(self.tmp) if False else None
        for rel, body in {"m.py": HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def inner(root, base_ref="origin/main"):
    return _git(root, "show", f"{base_ref}:x")


def outer(root):
    return inner(root, "origin/main")


def outermost(root):
    return outer(root)
"""}.items():
            self.write(rel, body)
        rep = census(self.tmp)
        self.assertEqual(1, len(rep["rows"]), "одно чтение посчитано дважды")
        self.assertGreaterEqual(len(rep["outer"]), 1,
                                "внешние обёртки обязаны быть СОСЧИТАНЫ, а не "
                                "выброшены молча")

    def test_unresolvable_argument_mapping_is_unmeasured_not_clean(self):
        """`**kwargs` у зова двери: третий исход, а не тишина."""
        rows = self.rows(m=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def look(root, **kw):
    return _git(*kw["argv"])
""")
        self.assertEqual(["unmeasured"], [r["verdict"] for r in rows])


class TestRefShapes(Tree):
    """Что считается remote-tracking ссылкой, а что нет."""

    def test_a_path_with_a_slash_is_not_a_ref(self):
        self.assertIsNone(remote_ref("docs/STATE.md", {"origin"}))

    def test_unknown_remote_name_is_not_a_ref(self):
        self.assertIsNone(remote_ref("somebody/main", {"origin"}))

    def test_refs_remotes_form_needs_no_remote_list(self):
        self.assertEqual(("weird", "main"),
                         remote_ref("refs/remotes/weird/main", set()))

    def test_rev_path_and_range_forms(self):
        self.assertIn("origin/main", ref_candidates("origin/main:docs/X.md"))
        self.assertIn("origin/main", ref_candidates("HEAD..origin/main"))

    def test_subcommand_skips_dash_c_argument(self):
        """`-C <путь>` съедает следующий токен — иначе путь станет подкомандой."""
        self.assertEqual("show", subcommand(["git", "-C", "/tmp/x", "show"]))

    def test_mutating_is_tri_state(self):
        """Неразрешённая подкоманда — НЕ «не мутирует» (инвариант #17)."""
        rows = self.rows(m=HEAD + """
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def look(root, sub, base_ref="origin/main"):
    return _git(root, sub, base_ref)
""")
        self.assertEqual(1, len(rows))
        self.assertIsNone(rows[0]["mutating"])


class TestRatchet(unittest.TestCase):
    """Храповик и три исхода CLI."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="c583r_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    @staticmethod
    def run_main(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_real_tree_matches_the_frozen_baseline(self):
        rc, out, err = self.run_main(["--root", str(REPO), "--json",
                                      "--baseline", str(BASELINE)])
        self.assertEqual(0, rc, err)

    def test_missing_baseline_is_unmeasured_not_clean(self):
        rc, out, err = self.run_main(["--root", str(REPO), "--json",
                                      "--baseline", str(self.tmp / "нет.json")])
        self.assertEqual(2, rc)
        self.assertIn("НЕ ИЗМЕРЕНО", out + err)

    def test_empty_baseline_names_every_subject_call(self):
        empty = self.tmp / "empty.json"
        # Схема ОБЯЗАТЕЛЬНА (v2): без неё прибор верно отвечает НЕ ИЗМЕРЕНО, а не
        # «храповик вырос» — сравнение по разным осям личности невыразимо.
        import python_git_ref_provenance as P
        empty.write_text(json.dumps({"schema": P.BASELINE_SCHEMA, "subject": []}),
                         encoding="utf-8")
        rc, out, err = self.run_main(["--root", str(REPO), "--json",
                                      "--baseline", str(empty)])
        self.assertEqual(3, rc)
        self.assertIn("ХРАПОВИК", out + err)

    def test_tree_without_python_refuses_loudly(self):
        """Нечего мерить ⇒ код 2 с причиной, а не «чисто»."""
        (self.tmp / "пусто").mkdir()
        rc, out, err = self.run_main(["--root", str(self.tmp), "--json"])
        self.assertEqual(2, rc)
        self.assertIn("НЕ ИЗМЕРЕНО", out + err)

    def test_a_new_ungated_reader_grows_the_subject(self):
        """Положительный контроль храповика: новый зов обязан покраснить."""
        copy = self.tmp / "repo"
        (copy / "scripts").mkdir(parents=True)
        shutil.copy(REPO / "scripts" / "python_git_ref_provenance.py",
                    copy / "scripts")
        (copy / "новый.py").write_text(
            "import subprocess\n"
            "def look():\n"
            "    return subprocess.run(['git', 'show', 'origin/main:x'])\n",
            encoding="utf-8")
        rc, out, err = self.run_main(["--root", str(copy), "--json",
                                      "--baseline", str(BASELINE)])
        self.assertEqual(3, rc)
        self.assertIn("новый.py", out + err)

    def test_json_is_exactly_one_document(self):
        """`--json` печатает РОВНО один документ; человеческие строки — в stderr."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(["--root", str(REPO), "--json", "--baseline", str(BASELINE)])
        json.loads(out.getvalue())          # упадёт, если документов два

    def test_subject_is_the_freshness_axis_only(self):
        """Ось ЛИЧНОСТИ в предмет храповика НЕ входит — как в ADR-361.

        Личность находки с 21.09 семантическая (`файл::функция::подкоманда:ссылка`),
        поэтому ожидание записано в ней; ось `basis` по-прежнему не участвует.
        """
        rows = [{"file": "a.py", "line": 1, "func": "f", "sub": "diff",
                 "ref": "origin/main", "verdict": "asked_and_gated",
                 "basis": "by_config"},
                {"file": "b.py", "line": 2, "func": "g", "sub": "show",
                 "ref": "origin/main", "verdict": "cache_only",
                 "basis": "by_url"}]
        self.assertEqual(["b.py::g::show:origin/main"], subject_keys(rows))

    # ── четыре требования к семантической личности (решение ARB §1B) ──────────
    def _row(self, line, func="_acquire", sub="diff", ref="origin/main",
             verdict="cache_only", file="scripts/check_owner_gate.py"):
        return {"file": file, "line": line, "func": func, "sub": sub,
                "ref": ref, "verdict": verdict, "basis": "by_config"}

    def test_the_same_call_moved_by_lines_keeps_its_identity(self):
        """Главный контроль миграции: посторонний сдвиг строк НЕ рождает находку.

        Воспроизводит настоящую аварию 21.09: база несла :238 и :244, прибор нашёл
        :242 и :248, и прежний храповик объявил рост предмета на два зова, хотя
        новых зовов не появилось.
        """
        before = subject_keys([self._row(238), self._row(244, sub="show")])
        after = subject_keys([self._row(242), self._row(248, sub="show")])
        self.assertEqual(before, after, "сдвиг строк изменил личность находки")

    def test_a_new_semantic_call_gets_a_new_identity(self):
        old = subject_keys([self._row(242)])
        new = subject_keys([self._row(242), self._row(300, func="_other")])
        self.assertEqual(len(new) - len(old), 1)
        self.assertNotIn("scripts/check_owner_gate.py::_other::diff:origin/main", old)

    def test_a_deleted_call_disappears(self):
        self.assertEqual([], subject_keys([]))

    def test_changed_call_purpose_changes_the_identity(self):
        """`diff` и `show` — разные назначения, значит разные личности."""
        a = subject_keys([self._row(242, sub="diff")])
        b = subject_keys([self._row(242, sub="show")])
        self.assertNotEqual(a, b)

    def test_unresolved_calls_are_a_third_outcome_not_the_subject(self):
        """Неразобранный зов не «безопасен» и не «читает кэш» — он НЕ ИЗМЕРЕН."""
        rows = [self._row(192, func="drift", sub=None, ref=None,
                          verdict="unmeasured", file="s.py"),
                self._row(193, func="drift", sub=None, ref=None,
                          verdict="unmeasured", file="s.py")]
        self.assertEqual([], subject_keys(rows), "неразобранное попало в предмет")
        self.assertEqual(2, len(unresolved_keys(rows)),
                         "три соседних зова слиплись бы в одну личность без номера")

    def test_a_baseline_without_the_schema_is_unmeasured_not_clean(self):
        """Старая база (адреса строк) обязана давать НЕ ИЗМЕРЕНО, а не вердикт."""
        old = self.tmp / "v1.json"
        old.write_text(json.dumps({"subject": ["scripts/x.py:1"]}), encoding="utf-8")
        rc, out, err = self.run_main(["--root", str(REPO), "--json",
                                      "--baseline", str(old)])
        self.assertEqual(2, rc)
        self.assertIn("НЕ ИЗМЕРЕНО", out + err)

    def test_prescreen_does_not_change_the_answer(self):
        """Отбор модулей — ради времени, а не ради сокрытия.

        Контроль на оптимизацию: прибор отбрасывает модуль, в тексте которого нет
        ни `git`, ни `origin`. Если такой модуль всё же мог бы нести чтение,
        «быстрее» означало бы «меряем меньше и молчим об этом»."""
        import python_git_ref_provenance as P
        rep = P.census(REPO)
        self.assertGreater(rep["screened_out"], 0)
        for m in rep.get("rows", []):
            src = (REPO / m["file"]).read_text(encoding="utf-8", errors="replace")
            self.assertTrue(any(w in src for w in P.PRESCREEN),
                            f"{m['file']} прошёл бы отбор мимо")


if __name__ == "__main__":
    unittest.main()

class RegistryGovernance(unittest.TestCase):
    """Разделы базы С ПРИЧИНОЙ не являются автоматическим сливом.

    Замер 2026-09-21 (проверка реестра ARB §2б): прибор читал только КЛЮЧИ
    словарей `admitted_after_migration` и `unresolved` и принимал запись с ПУСТОЙ
    причиной молча — то есть любую новую находку можно было «принять», ничего не
    объяснив. Причина не достраивается и не выводится: пустая причина неотличима
    от недосмотра, поэтому исход — НЕ ИЗМЕРЕНО (код 2), а не вердикт.
    """

    def setUp(self):
        import python_git_ref_provenance as P
        self.P = P
        self.tmp = Path(tempfile.mkdtemp(prefix="reg-gov-"))
        self.real = json.loads(BASELINE.read_text(encoding="utf-8"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, doc):
        b = self.tmp / "b.json"
        b.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = self.P.main(["--root", str(REPO), "--json", "--baseline", str(b)])
        return rc, buf.getvalue()

    def test_an_intact_baseline_passes(self):
        """Положительный контроль: без него все отказы ниже истинны по построению."""
        rc, _ = self._run(self.real)
        self.assertEqual(0, rc)

    def test_an_empty_admitted_reason_is_unmeasured_not_pass(self):
        doc = json.loads(json.dumps(self.real))
        doc["admitted_after_migration"]["scripts/fake.py::f::diff:origin/main"] = ""
        rc, out = self._run(doc)
        self.assertEqual(2, rc, "пустая причина принята как вердикт")
        self.assertIn("без названной причины", out)
        self.assertIn("scripts/fake.py::f::diff:origin/main", out)

    def test_an_empty_unresolved_reason_is_unmeasured_not_pass(self):
        doc = json.loads(json.dumps(self.real))
        doc["unresolved"]["scripts/fake.py::g::show:origin/main"] = "   "
        rc, out = self._run(doc)
        self.assertEqual(2, rc, "причина из пробелов принята как вердикт")
        self.assertIn("без названной причины", out)

    def test_a_non_string_reason_is_unmeasured_not_pass(self):
        doc = json.loads(json.dumps(self.real))
        doc["unresolved"]["scripts/fake.py::h::show:origin/main"] = None
        rc, _ = self._run(doc)
        self.assertEqual(2, rc)

    def test_the_instrument_never_writes_the_baseline(self):
        """Слива нет ПО ПОСТРОЕНИЮ: прибор базу только читает."""
        src = (REPO / "scripts" / "python_git_ref_provenance.py").read_text(encoding="utf-8")
        self.assertNotIn("--write", src)
        for bad in ("baseline.write_text", "bp.write_text"):
            self.assertNotIn(bad, src)


class RegistryReactsToTheCensus(unittest.TestCase):
    """Реагирует ли РЕЕСТР на новую личность — независимо от полноты цензуса.

    Вопрос узкий и потому отвечаемый: если цензус выдал новую НЕРАЗОБРАННУЮ
    личность, краснеет ли храповик и названа ли она. Цензус подменяется, потому
    что его полнота — отдельный предмет (см. запись о слепом пятне динамического
    argv), и проверять реестр через неё значило бы мерить два свойства одной
    пробой.
    """

    def setUp(self):
        import python_git_ref_provenance as P
        self.P = P
        self.real_census = P.census

    def tearDown(self):
        self.P.census = self.real_census

    def _run_with(self, extra=(), drop=()):
        real = self.real_census
        def fake(root):
            rep = real(root)
            rows = [r for r in rep["rows"] if self.P.semantic_key(r) not in drop]
            rep = dict(rep)
            rep["rows"] = rows + list(extra)
            return rep
        self.P.census = fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = self.P.main(["--root", str(REPO), "--json", "--baseline", str(BASELINE)])
        return rc, buf.getvalue()

    _NEW = {"file": "scripts/synthetic_probe.py", "line": 1, "func": "reader",
            "sub": None, "ref": None, "verdict": "unmeasured", "basis": "by_var",
            "mutating": False, "why": "синтетическая строка цензуса"}

    def test_a_new_unresolved_identity_turns_the_ratchet_red_and_is_named(self):
        rc, out = self._run_with(extra=[self._NEW])
        self.assertEqual(3, rc, "новая неразобранная личность не покраснила храповик")
        self.assertIn("scripts/synthetic_probe.py::reader::None:None#1", out)

    def test_removing_an_unresolved_identity_reduces_the_debt(self):
        frozen = json.loads(BASELINE.read_text(encoding="utf-8"))
        first = sorted(frozen.get("unresolved") or {})[0].rsplit("#", 1)[0]
        rc, out = self._run_with(drop={first})
        self.assertEqual(0, rc)
        self.assertIn("сократил", out, "сокращение долга не объявлено")

    def test_the_unchanged_census_is_green(self):
        """Контроль: обе сцены выше меняют вердикт, а не воспроизводят общий фон."""
        rc, _ = self._run_with()
        self.assertEqual(0, rc)
