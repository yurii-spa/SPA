"""Шаг 0a обязан ОТВЕЧАТЬ по осиротевшей регистрации, а не звать её неизмеримой.

Карточка `inbox-shag-0a-obyavlyaet-osirotevshuyu-registr`, замер цикла #323.

Мёртвая регистрация — каталог рабочего дерева, у которого умерла git-привязка. Шаг 0a
печатал про такую строку «**сверять нечего**, но и молчать не о чем» и советовал
`git worktree prune`. Утверждение неверно: в 21 скорлупе уцелело 70 настоящих файлов вне
churn, 51 из них расходился с `origin/main`, и ответ был достижим тремя дешёвыми командами
(`hash-object` · `ls-tree` · `cat-file`). Слепое `prune` стёрло бы последний указатель.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ над этой аварией (правило
`.claude/rules/deployment.md`: проверка, никогда не видевшая настоящей поломки, — украшение),
либо ОБРАТНЫЙ контроль над её лечением: сторож, краснеющий на старой копии, станет фоном за
неделю, и его перестанут читать — а это тот же класс, только медленнее.

Время здесь ВХОДОМ не является намеренно: разбор скорлупы про содержимое, а не про свежесть,
литеральных дат в фикстурах нет вовсе (правило «фиксированная дата — бомба замедленного
действия» соблюдено отсутствием предмета).
"""

import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_undelivered_work.py"


def _load():
    spec = importlib.util.spec_from_file_location("cuw_orphan", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cuw = _load()


def _run(cwd, *args, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return subprocess.run(["git", "-C", str(cwd), *args], input=stdin,
                          capture_output=True, text=True, env=env, check=True)


class OrphanShellBase(unittest.TestCase):
    """Настоящий git-репозиторий: проверка живёт на плумбинге, подделка её не проверит."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir(parents=True)
        _run(self.root, "init", "-q", "-b", "main")
        (self.root / "kept.txt").write_text("на базе\n")
        _run(self.root, "add", "-A")
        _run(self.root, "commit", "-qm", "base")
        self.base = "main"
        self.shell = Path(self._tmp.name) / "shell"
        self.shell.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        p = self.shell / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def scan(self):
        dead = [{"path": str(self.shell), "prunable": True, "reason": "фикстура"}]
        rows = cuw.orphan_registration_scan(self.root, self.base, dead)
        self.assertEqual(len(rows), 1)
        return rows[0]


class UndeliveredIsFound(OrphanShellBase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: содержимого нет в репо ⇒ находка, а не «сверять нечего»."""

    def test_content_unknown_to_the_object_database_is_a_finding(self):
        self.put("docs/STATE.md", "работа, которой не было ни в одном коммите\n")
        row = self.scan()
        self.assertEqual([f["path"] for f in row["undelivered"]], ["docs/STATE.md"])
        self.assertEqual(row["stale"], 0)
        self.assertEqual(row["delivered"], 0)
        self.assertEqual(row["unchecked"], [])

    def test_finding_says_whether_the_name_itself_exists_on_base(self):
        """«имя есть, содержимое чужое» и «имени нет вовсе» — РАЗНЫЕ подсказки поднимающему."""
        self.put("kept.txt", "то же имя, другое содержимое\n")
        self.put("new_file.md", "имени на базе нет вовсе\n")
        row = self.scan()
        by_path = {f["path"]: f["on_base"] for f in row["undelivered"]}
        self.assertEqual(by_path, {"kept.txt": True, "new_file.md": False})

class EndToEndOnARealBrokenWorktree(unittest.TestCase):
    """Сквозной прогон СКРИПТА на настоящей осиротевшей регистрации.

    Три предыдущих класса меряют функцию; этот меряет то, что увидит цикл, — включая КОД
    ВОЗВРАТА. Разница не педантизм: находка, не поднявшая код, для обязательного шага 0a
    неотличима от её отсутствия, а мимо такой находки цикл #232 уже проходил (ADR-085).
    Регистрация ломается ровно так, как ломается в жизни: `.git`-файл внутри дерева исчез,
    служебная запись в `.git/worktrees/` осталась."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir(parents=True)
        _run(self.root, "init", "-q", "-b", "main")
        (self.root / "kept.txt").write_text("на базе\n")
        _run(self.root, "add", "-A")
        _run(self.root, "commit", "-qm", "base")
        self.shell = Path(self._tmp.name) / "shell"
        _run(self.root, "worktree", "add", "-q", "--detach", str(self.shell), "main")
        self.log = Path(self._tmp.name) / "empty.jsonl"
        self.log.write_text("")

    def tearDown(self):
        self._tmp.cleanup()

    def _break_binding(self):
        (self.shell / ".git").unlink()
        out = _run(self.root, "worktree", "list", "--porcelain").stdout
        if "prunable" not in out:
            self.skipTest(f"эта версия git не считает регистрацию prunable: {out!r}")

    def _run_script(self):
        p = subprocess.run(
            ["python3", str(_SCRIPT), "--root", str(self.root), "--base", "main",
             "--log", str(self.log)],
            capture_output=True, text=True,
            env={**os.environ, "SPA_ENV": "ci"})
        return p.returncode, p.stdout + p.stderr

    def test_undelivered_file_in_a_broken_registration_returns_code_1(self):
        (self.shell / "docs").mkdir()
        (self.shell / "docs" / "STATE.md").write_text("работа, которой нет ни в одном коммите\n")
        self._break_binding()
        rc, text = self._run_script()
        self.assertEqual(rc, 1, text)
        self.assertIn("docs/STATE.md", text)
        self.assertIn("НЕДОСТАВЛЕННОЕ", text)
        self.assertNotIn("сверять нечего", text)

    def test_shell_holding_only_delivered_files_stays_code_0(self):
        """ОБРАТНЫЙ КОНТРОЛЬ сквозного пути: скорлупа без потерь код не поднимает."""
        self._break_binding()
        rc, text = self._run_script()
        self.assertEqual(rc, 0, text)
        self.assertIn("цена снятия НОЛЬ", text)


class StaleCopyIsNotAFinding(OrphanShellBase):
    """ОБРАТНЫЙ КОНТРОЛЬ: старая копия — не находка. Сторож-фон хуже отсутствующего."""

    def test_previously_committed_content_is_a_stale_copy(self):
        """Ровно этим оказались ВСЕ 51 расхождения замера #323."""
        (self.root / "kept.txt").write_text("вторая версия\n")
        _run(self.root, "add", "-A")
        _run(self.root, "commit", "-qm", "second")
        self.put("kept.txt", "на базе\n")          # содержимое ПЕРВОГО коммита
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["stale"], 1)
        self.assertEqual(row["unchecked"], [])

    def test_content_identical_to_base_is_delivered(self):
        self.put("kept.txt", "на базе\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["delivered"], 1)
        self.assertEqual(row["stale"], 0)

    def test_non_ascii_path_is_delivered_not_counted_as_a_stale_copy(self):
        """`core.quotePath` по умолчанию экранирует не-ASCII имя в выводе `ls-tree`.

        Обход файловой системы даёт то же имя СЫРЫМ ⇒ ключи не совпадают ⇒ доставленный
        файл считается «старой копией». Находкой это не станет (блоб в базе есть), но число
        в отчёте будет врать, а отчёт здесь ровно для того, чтобы по нему решали, можно ли
        снимать скорлупу. В репозитории такие имена есть — например, `docs/journal/`."""
        name = "docs/журнал.md"
        (self.root / "docs").mkdir()
        (self.root / name).write_text("русское имя\n")
        _run(self.root, "add", "-A")
        _run(self.root, "commit", "-qm", "non-ascii")
        # Пропуск меряется ТОЛЬКО нормализацией ФС (macOS NFD и т.п.), поэтому имя читается
        # с уже снятым экранированием. Первая версия этого теста спрашивала git БЕЗ
        # `core.quotePath=false` — и экранированный ответ, то есть сам проверяемый дефект,
        # читался как «ФС переименовала файл»: тест скипался ровно там, где обязан краснеть.
        stored = _run(self.root, "-c", "core.quotePath=false",
                      "ls-tree", "-r", "--name-only", "main").stdout
        if name not in stored:
            self.skipTest(f"файловая система изменила имя при записи: {stored!r}")
        self.put(name, "русское имя\n")
        row = self.scan()
        self.assertEqual(row["delivered"], 1)
        self.assertEqual(row["stale"], 0)
        self.assertEqual(row["undelivered"], [])

    def test_churn_paths_are_filtered_and_counted_not_silently_dropped(self):
        """Отсев обязан быть ВИДЕН числом: «не считаем» ≠ «не видим»."""
        self.put("data/alert_log.json", "{}\n")
        self.put("spa_core/database/spa.db", "двоичный мусор\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["files"], 0)
        self.assertEqual(row["churn"], 2)

    def test_service_caches_are_not_work(self):
        self.put("__pycache__/x.pyc", "кеш\n")
        self.put("landing/node_modules/pkg/index.js", "зависимость\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["files"], 0)
        self.assertGreaterEqual(row["skipped_dirs"], 2)

    def test_no_dead_registration_means_no_rows_and_no_git_calls(self):
        def refuse(*a, **k):                       # вызов git тут был бы лишней работой
            raise AssertionError("git не должен вызываться без осиротевших регистраций")
        self.assertEqual(cuw.orphan_registration_scan(self.root, self.base, [], git=refuse), [])


class FailClosedNotFailOpen(OrphanShellBase):
    """«Не смог измерить» ни в одной ветке не сворачивается в «поднимать нечего» (инв. #2)."""

    def _fake(self, broken, rc=128, out="", err="сломано"):
        """Ломает ИМЕННО названную подкоманду.

        Совпадение по вхождению, а не по `args[0]`: вызов может нести `-c <настройка>`
        перед подкомандой (так читается дерево базы), и матчер по первому слову молча
        перестал бы что-либо ломать — тест позеленел бы, ничего не проверяя."""
        real = cuw._git
        self.assertIn(broken, {"ls-tree", "hash-object", "cat-file"})

        def fake(cwd, *args, stdin=None):
            if broken in args:
                return rc, out, err
            return real(cwd, *args, stdin=stdin)
        return fake

    def _scan(self, git):
        dead = [{"path": str(self.shell), "prunable": True, "reason": "фикстура"}]
        return cuw.orphan_registration_scan(self.root, self.base, dead, git=git)[0]

    def test_ls_tree_failure_is_unchecked(self):
        self.put("a.md", "нечто\n")
        row = self._scan(self._fake("ls-tree"))
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])

    def test_hash_object_failure_is_unchecked(self):
        self.put("a.md", "нечто\n")
        row = self._scan(self._fake("hash-object"))
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])

    def test_hash_object_short_answer_is_unchecked_not_partial(self):
        """Хешей меньше, чем файлов, — молчаливая потеря файла, а не «часть измерена»."""
        self.put("a.md", "первый\n")
        self.put("b.md", "второй\n")
        real = cuw._git

        def short(cwd, *args, stdin=None):
            if args[:1] == ("hash-object",):
                rc, out, err = real(cwd, *args, stdin=stdin)
                return rc, out.split()[0] + "\n", err     # ровно один хеш на два файла
            return real(cwd, *args, stdin=stdin)
        row = self._scan(short)
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])

    def test_batch_check_failure_is_unchecked(self):
        self.put("a.md", "нечто, чего нет в репо\n")
        row = self._scan(self._fake("cat-file"))
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])

    def test_batch_check_unknown_verdict_is_unchecked(self):
        """Ответ, который не 'blob' и не 'missing', — не повод угадывать в любую сторону."""
        self.put("a.md", "нечто, чего нет в репо\n")
        real = cuw._git

        def weird(cwd, *args, stdin=None):
            if args[:2] == ("cat-file", "--batch-check"):
                return 0, "\n".join("нечто странное" for _ in stdin.split()) + "\n", ""
            return real(cwd, *args, stdin=stdin)
        row = self._scan(weird)
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])

    def test_unreadable_subdirectory_is_unchecked_not_empty(self):
        """`os.walk` глотает ошибки по умолчанию: непрочитанный каталог читался бы как пустой."""
        self.put("secret/inside.md", "нечто\n")
        d = self.shell / "secret"
        os.chmod(d, 0o000)
        try:
            if os.access(d, os.R_OK):              # под root права не ограничивают
                self.skipTest("каталог читается несмотря на chmod 000 (запуск под root)")
            row = self.scan()
            self.assertTrue(row["unchecked"])
            self.assertEqual(row["files"], 0)
            self.assertEqual(row["undelivered"], [])
        finally:
            os.chmod(d, 0o755)

    def test_churn_rule_unreadable_is_unchecked(self):
        """Без правила отсева работу от churn не отделить — и это НЕ «нет работы»."""
        self.put("a.md", "нечто\n")
        orig = cuw.churn_rule
        cuw.churn_rule = lambda: (None, "правило отсева не прочитано")
        try:
            row = self.scan()
        finally:
            cuw.churn_rule = orig
        self.assertTrue(row["unchecked"])
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["files"], 0)


# Пустой отчёт нужной формы — рендер читает много ключей, а предмет теста один.
_EMPTY_REPORT = {
    "base_ref": "main", "base_sha": "0" * 40, "entries_checked": 0, "sessions_active": 0,
    "sessions_checked": 0, "grace_hours": 3.0, "findings": [], "card_findings": [],
    "fresh": [], "stale_copies": [], "reaped": [], "nowhere": [], "by_design": [],
    "card_closed": [], "deleted_on_origin": [], "on_branch": [],
    "branches_with_owner_work": [], "branches_code_only": [], "unmeasured": [],
    "dead_worktrees": [], "orphan_registrations": [], "within_grace": [], "exit_code": 0,
}


class RenderTellsTheCostOfPruning(unittest.TestCase):
    """Совет `git worktree prune` обязан идти с ИЗМЕРЕННОЙ ценой, а не сам по себе."""

    def _render(self, row):
        return cuw.render({**_EMPTY_REPORT,
                           "dead_worktrees": [{"path": row["path"], "prunable": True,
                                               "reason": "git пометил регистрацию prunable"}],
                           "orphan_registrations": [row]})

    def _row(self, **kw):
        base = {"path": "/tmp/shell", "files": 0, "skipped_dirs": 0, "churn": 0,
                "delivered": 0, "stale": 0, "undelivered": [], "unchecked": []}
        base.update(kw)
        return base

    def test_zero_cost_shell_says_so_explicitly(self):
        text = self._render(self._row(files=70, delivered=19, stale=51))
        self.assertIn("цена снятия НОЛЬ", text)
        self.assertNotIn("сверять нечего", text)

    def test_shell_with_undelivered_says_do_not_prune(self):
        text = self._render(self._row(
            files=1, undelivered=[{"path": "docs/STATE.md", "sha": "a" * 40, "on_base": True}]))
        self.assertIn("снимать НЕЛЬЗЯ", text)
        self.assertIn("docs/STATE.md", text)

    def test_unchecked_shell_never_reads_as_zero_cost(self):
        text = self._render(self._row(unchecked=["git не отработал"]))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("цена снятия НОЛЬ", text)

    def test_long_finding_list_names_what_it_truncated(self):
        """Тихо срезанное покрытие читается как «показано всё» — молчаливых потолков нет."""
        many = [{"path": f"f{i}.md", "sha": "b" * 40, "on_base": False} for i in range(25)]
        text = self._render(self._row(files=25, undelivered=many))
        self.assertIn("и ещё 5", text)
        self.assertIn("orphan_registrations", text)


if __name__ == "__main__":
    unittest.main()
