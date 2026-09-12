"""ADR-353: база стража перезаписи — это HEAD, а не то, что видел автор.

Каждый тест здесь — форма настоящей аварии, а не выдумка. `6322d0d56` унёс
20 строк проводки ADR-343, `5fb2ab5a` откатил починку ADR-347; общий механизм
записан в моей же памяти как рецепт: `git reset --mixed origin/main` двигает
HEAD и индекс, НЕ трогая рабочее дерево — и после него устаревшая копия
выглядит свежей для ОБОИХ стражей.

Отрицательные контроли не менее важны положительных: страж, который краснеет
на обычной работе, будет отключён первым же циклом, которому он помешает.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from spa_core.monitoring.push_base_provenance import (  # noqa: E402
    BASED_ON_OLDER, CONSISTENT_WITH_HEAD, UNEXPLAINED, UNMEASURED,
    base_provenance, describe)


def _pusher():
    spec = importlib.util.spec_from_file_location(
        "pusher_under_test", REPO / "push_to_github.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pusher_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _out(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                          stdout=subprocess.PIPE).stdout.decode().strip()


class _RepoFixture(unittest.TestCase):
    """Настоящий git-репозиторий: провенанс базы нечем мерить на подделке."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.origin = self.root / "origin"
        self.origin.mkdir()
        _git(["init", "-q"], self.origin)
        _git(["config", "user.email", "t@t.t"], self.origin)
        _git(["config", "user.name", "t"], self.origin)
        self.addCleanup(self._tmp.cleanup)

    def _commit(self, text: str, message: str) -> str:
        (self.origin / "mod.py").write_text(text)
        _git(["add", "-A"], self.origin)
        _git(["commit", "-qm", message], self.origin)
        return _out(["rev-parse", "HEAD"], self.origin)

    def _clone(self) -> Path:
        work = self.root / "work"
        _git(["clone", "-q", str(self.origin), str(work)], self.root)
        _git(["config", "user.email", "t@t.t"], work)
        _git(["config", "user.name", "t"], work)
        return work

    def _remote_sha(self, work: Path) -> str:
        return _out(["rev-parse", "origin/main:mod.py"], work)


class TestTheAccident(_RepoFixture):
    """`git reset --mixed` — устаревшая копия выглядит свежей для обоих стражей."""

    def _stage_accident(self):
        """Форма обвала: чужая проводка на origin, наша правка на СТАРОЙ копии."""
        c1 = self._commit("line1\nWIRING_A = 1\nline3\n", "c1")
        self._commit("line1\nWIRING_A = 1\nWIRING_NEW = 3\nline3\n",
                     "c2: чужая сессия доставила проводку")
        work = self._clone()
        # копия автора взята ДО c2 …
        _git(["checkout", "-q", c1, "--", "."], work)
        # … и автор кладёт на неё свою правку, чужой строки не видя
        (work / "mod.py").write_text("line1\nWIRING_A = 1\nline3\nMY_EDIT = 9\n")
        # рецепт из журнала: двигаем HEAD, пока страж не замолчит
        _git(["fetch", "-q", "origin"], work)
        _git(["reset", "--mixed", "origin/main"], work)
        return work, c1

    def test_head_moved_but_the_copy_did_not_follow(self):
        work, c1 = self._stage_accident()
        r = base_provenance(work, "mod.py", (work / "mod.py").read_bytes())
        self.assertEqual(BASED_ON_OLDER, r["verdict"])
        self.assertEqual(c1, r["candidate"], "предок назван не тот")
        self.assertIn(b"WIRING_NEW = 3", r["missing"])

    def test_the_pusher_refuses_the_accident_instead_of_reporting_safe(self):
        """До ADR-353 здесь был вердикт `safe` и ПУСТАЯ нота."""
        work, _ = self._stage_accident()
        pusher = _pusher()
        local = (work / "mod.py").read_bytes()

        verdict = pusher.divergence_verdict(work / "mod.py", "mod.py",
                                            self._remote_sha(work), "main")
        self.assertEqual(pusher.DIVERGENCE_SAFE, verdict["state"],
                         "предпосылка теста: расхождение считается безопасным")

        with self.assertRaises(pusher.StaleBaseRefused) as caught:
            pusher.guard_overwrite("PAT", "o/r", "main", "mod.py", work / "mod.py",
                                   local, self._remote_sha(work))
        self.assertIn("WIRING_NEW = 3", str(caught.exception),
                      "отказ обязан НАЗВАТЬ пропадающую строку, а не только отказать")

    def test_allow_overwrite_does_not_lift_this_refusal(self):
        """Общая лазейка была под рукой — ею обвал и кончился."""
        work, _ = self._stage_accident()
        pusher = _pusher()
        with self.assertRaises(pusher.StaleBaseRefused):
            pusher.guard_overwrite("PAT", "o/r", "main", "mod.py", work / "mod.py",
                                   (work / "mod.py").read_bytes(),
                                   self._remote_sha(work), allow_overwrite=True)

    def test_the_named_bypass_lifts_it_but_not_the_note(self):
        work, _ = self._stage_accident()
        pusher = _pusher()
        _, note = pusher.guard_overwrite(
            "PAT", "o/r", "main", "mod.py", work / "mod.py",
            (work / "mod.py").read_bytes(), self._remote_sha(work),
            allow_stale_base=True)
        self.assertIn("WIRING_NEW = 3", note,
                      "осознанная отдача снимает отказ, но не немоту")


class TestOrdinaryWorkIsNotDisturbed(_RepoFixture):
    """Страж, краснеющий на обычной работе, будет отключён первым же циклом."""

    def test_adding_a_line_on_a_fresh_copy_is_silent(self):
        self._commit("a\nb\n", "c1")
        work = self._clone()
        (work / "mod.py").write_text("a\nb\nMINE\n")
        r = base_provenance(work, "mod.py", (work / "mod.py").read_bytes())
        self.assertEqual(CONSISTENT_WITH_HEAD, r["verdict"])
        self.assertEqual("", describe(r, "mod.py"), "тишина, когда терять нечего")

    def test_deleting_part_of_a_commit_is_unexplained_not_a_refusal(self):
        """Осознанное удаление ЧАСТИ добавленного — не старая копия."""
        self._commit("a\n", "c1")
        self._commit("a\nADDED_1\nADDED_2\nADDED_3\n", "c2")
        work = self._clone()
        (work / "mod.py").write_text("a\nADDED_1\nADDED_3\n")
        r = base_provenance(work, "mod.py", (work / "mod.py").read_bytes())
        self.assertEqual(UNEXPLAINED, r["verdict"])
        self.assertNotEqual("", describe(r, "mod.py"),
                            "«не измерено» обязано быть СКАЗАНО, а не проглочено")
        pusher = _pusher()
        _, note = pusher.guard_overwrite("PAT", "o/r", "main", "mod.py",
                                         work / "mod.py",
                                         (work / "mod.py").read_bytes(),
                                         self._remote_sha(work))
        self.assertIn("НЕ ИЗМЕРЕН", note)

    def test_a_brand_new_file_is_not_a_finding(self):
        self._commit("a\n", "c1")
        work = self._clone()
        (work / "new.py").write_text("fresh\n")
        r = base_provenance(work, "new.py", b"fresh\n")
        self.assertEqual(CONSISTENT_WITH_HEAD, r["verdict"])


class TestTheThirdOutcome(_RepoFixture):
    """Инвариант #17: «нечем померить» отличимо и от «чисто», и от находки."""

    def test_outside_a_git_repo_is_unmeasured_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as plain:
            r = base_provenance(plain, "mod.py", b"x\n")
        self.assertEqual(UNMEASURED, r["verdict"])
        self.assertTrue(r["reason"], "причина обязана быть названа")
        self.assertIn("НЕ ИЗМЕРЕН", describe(r, "mod.py"))

    def test_unmeasured_does_not_refuse_the_push(self):
        """Исторические пути доставки пушат не из worktree ветки доставки."""
        self._commit("a\n", "c1")
        work = self._clone()
        pusher = _pusher()
        with tempfile.TemporaryDirectory() as plain:
            note = pusher.guard_stale_base("mod.py", Path(plain) / "mod.py", b"x\n")
        self.assertIn("НЕ ИЗМЕРЕН", note)

    def test_exhausting_the_ancestor_ceiling_says_so_instead_of_finding_nothing(self):
        self._commit("a\nKEEP\n", "c1")
        for i in range(3):
            self._commit(f"a\nKEEP\n{'X' * (i + 1)}\n", f"c{i + 2}")
        work = self._clone()
        (work / "mod.py").write_text("a\n")
        r = base_provenance(work, "mod.py", b"a\n", ancestor_limit=1)
        self.assertEqual(UNEXPLAINED, r["verdict"])
        self.assertIn("потолок", r["reason"],
                      "исчерпанный потолок — не «предка нет»")


class TestTheFileIsNotAtTheRepoRoot(_RepoFixture):
    """#574: оба НАСТОЯЩИХ обвала лежат в подкаталогах, а контроли — в корне.

    `HEAD:<путь>` git разбирает от КОРНЯ репозитория, а pathspec у `rev-list` —
    от ТЕКУЩЕГО каталога. Страж зовёт прибор с `Path(abs_path).parent`, то есть
    из каталога файла: база читалась верно, перечисление предков молча возвращало
    пусто, и ноль предков складывался в «ни один предок не объясняет». Тот же
    обвал в корне давал отказ, он же в `spa_core/monitoring/` — пуш.
    """

    def _commit_at(self, rel: str, text: str, message: str) -> str:
        f = self.origin / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        _git(["add", "-A"], self.origin)
        _git(["commit", "-qm", message], self.origin)
        return _out(["rev-parse", "HEAD"], self.origin)

    def test_the_same_accident_in_a_subdirectory_is_still_refused(self):
        rel = "spa_core/monitoring/mod.py"
        c1 = self._commit_at(rel, "line1\nWIRING_A = 1\nline3\n", "c1")
        self._commit_at(rel, "line1\nWIRING_A = 1\nWIRING_NEW = 3\nline3\n",
                        "c2: чужая сессия доставила проводку")
        work = self._clone()
        _git(["checkout", "-q", c1, "--", "."], work)
        (work / rel).write_text("line1\nWIRING_A = 1\nline3\nMY_EDIT = 9\n")
        _git(["fetch", "-q", "origin"], work)
        _git(["reset", "--mixed", "origin/main"], work)

        # ИМЕННО так зовёт страж — из каталога ФАЙЛА, а не из корня репозитория
        r = base_provenance((work / rel).parent, rel, (work / rel).read_bytes())
        self.assertEqual(BASED_ON_OLDER, r["verdict"],
                         "подкаталог не смеет менять вердикт: путь — не предмет замера")
        self.assertEqual(c1, r["candidate"])

    def test_the_ancestor_listing_is_not_silently_empty_from_a_subdirectory(self):
        """Ноль предков обязан означать «их нет», а не «спросили не про то»."""
        rel = "scripts/agent_orchestrator.sh"
        self._commit_at(rel, "a\nKEEP\n", "c1")
        self._commit_at(rel, "a\nKEEP\nLATER\n", "c2")
        work = self._clone()
        r = base_provenance((work / rel).parent, rel, b"a\n")
        self.assertNotIn("из 0 предков", r["reason"],
                         "перечисление предков вернулось пустым — спросили не про тот путь")


class TestABoundedWindowIsNotAStaleBase(_RepoFixture):
    """#574: полная прокрутка окна побайтово похожа на устаревшую копию.

    У катящегося журнала (последние N записей) из базы пропадают ровно те
    строки, которые она набрала одним коммитом, — разность совпадает точь-в-точь.
    Замер на живом хост-дереве: 21 отказ, из них 20 — этого рода. Отличает их
    вторая половина собственного утверждения вердикта: если копия ОБЪЯСНЯЕТСЯ
    предком, блоб предка лежит в ней целиком.
    """

    def _rolling(self, first: int) -> str:
        return "\n".join(f"entry {i}" for i in range(first, first + 5)) + "\n"

    def test_a_rotated_log_is_not_refused(self):
        self._commit(self._rolling(0), "c1: окно 0..4")
        self._commit(self._rolling(5), "c2: окно 5..9")
        work = self._clone()
        (work / "mod.py").write_text(self._rolling(10))   # окно прокрутилось ещё раз
        r = base_provenance(work, "mod.py", (work / "mod.py").read_bytes())
        self.assertNotEqual(BASED_ON_OLDER, r["verdict"],
                            "прокрутка окна — не устаревшая база: блоба предка в копии нет вовсе")

    def test_the_genuine_stale_base_on_the_same_fixture_is_still_refused(self):
        """Обратный контроль: без него первый тест гасил бы стража целиком."""
        c1 = self._commit(self._rolling(0), "c1: окно 0..4")
        self._commit(self._rolling(0) + "entry 5\n", "c2: чужая сессия дописала")
        work = self._clone()
        _git(["checkout", "-q", c1, "--", "."], work)
        (work / "mod.py").write_text(self._rolling(0) + "MY_EDIT\n")
        _git(["fetch", "-q", "origin"], work)
        _git(["reset", "--mixed", "origin/main"], work)
        r = base_provenance(work, "mod.py", (work / "mod.py").read_bytes())
        self.assertEqual(BASED_ON_OLDER, r["verdict"],
                         "копия СОДЕРЖИТ блоб предка и теряет чужую строку — это обвал")
        self.assertEqual(c1, r["candidate"])


class TestTheWiringItself(_RepoFixture):
    """Проверка проводки поведением: подстрока пережила бы любое расплетение."""

    def test_the_safe_path_of_guard_overwrite_consults_the_instrument(self):
        """Мутация: убрать зов из ветки SAFE — и этот тест обязан покраснеть."""
        c1 = self._commit("a\nGONE\n", "c1")
        self._commit("a\nGONE\nLATER\n", "c2")
        work = self._clone()
        _git(["checkout", "-q", c1, "--", "."], work)
        _git(["fetch", "-q", "origin"], work)
        _git(["reset", "--mixed", "origin/main"], work)
        pusher = _pusher()
        # ветка SAFE — и без прибора она молчала бы
        self.assertEqual(
            pusher.DIVERGENCE_SAFE,
            pusher.divergence_verdict(work / "mod.py", "mod.py",
                                      self._remote_sha(work), "main")["state"])
        with self.assertRaises(pusher.StaleBaseRefused):
            pusher.guard_overwrite("PAT", "o/r", "main", "mod.py", work / "mod.py",
                                   (work / "mod.py").read_bytes(),
                                   self._remote_sha(work))

    def test_the_consents_survive_a_retry(self):
        """«Половина инъекции» — та же бомба: повтор терял согласия автора.

        До #573 обе ветки повтора `push_file` и пере-сборка `build_entries` после
        409 передавали ОДИН `allow_overwrite`, а `allow_name_loss` молча падал к
        умолчанию. Направление было безопасным (страж строже, не мягче), поэтому
        аварии отсюда не случилось — но путь ровно тот, где рядом пишет
        параллельная сессия.
        """
        import ast
        tree = ast.parse((REPO / "push_to_github.py").read_text())
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for caller, callee in (("push_file", "push_file"),
                               ("batch_push", "build_entries")):
            calls = [n for n in ast.walk(funcs[caller])
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == callee]
            self.assertTrue(calls, f"{caller} не зовёт {callee}")
            for call in calls:
                carried = {kw.arg for kw in call.keywords} | {
                    a.id for a in call.args if isinstance(a, ast.Name)}
                for flag in ("allow_name_loss", "allow_stale_base"):
                    self.assertIn(flag, carried,
                                  f"{caller} → {callee}: согласие {flag} не пережило вызов")

    def test_the_cli_flag_reaches_the_guard(self):
        """«Параметр есть» зелено и при оборванной проводке — проверяем связь."""
        import ast
        src = (REPO / "push_to_github.py").read_text()
        tree = ast.parse(src)
        funcs = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        for name in ("push_file", "batch_push", "build_entries", "guard_overwrite"):
            self.assertIn(name, funcs)
            args = [a.arg for a in funcs[name].args.args]
            self.assertIn("allow_stale_base", args,
                          f"{name} не принимает флаг — проводка оборвана")
        # и он не просто принят, а ПЕРЕДАН дальше
        passed = {kw.arg for n in ast.walk(funcs["guard_overwrite"])
                  if isinstance(n, ast.Call) for kw in n.keywords}
        self.assertIn("allow_stale_base", passed,
                      "guard_overwrite принял флаг и не передал его стражу")


if __name__ == "__main__":
    unittest.main()
