"""Подсчёт карточек обязан называть свой источник (ADR-152).

Авария 27.08. Владелец попросил замерить, движется ли бэклог. Замер сняли с ЛОКАЛЬНОГО
дерева: 525 карточек, 237 `done`. На origin в тот же момент — 719 и 379. Разница в 142
карточки не работа за день, а разрыв копий: `nimbalyst-local/` не синхронизируется с
origin никогда (пишется локально, merge затёр бы незапушенное).

Вечерний замер сняли уже с origin — и сравнить с утренним стало нельзя. Ответа на простой
вопрос «сдвинулся ли бэклог» не получилось вовсе; пришлось восстанавливать состояние из
истории git.

Ключевое: **ADR-152 про ровно эту слепоту был написан за несколько часов до, тем же
автором.** Значит правило, которое надо ПОМНИТЬ, не работает. Работает только проверка,
которая называет источник САМА — как приёмка, научившаяся говорить «измерено из worktree»
и после этого трижды поймавшая своего же автора.

Поэтому тесты ниже проверяют не подсчёт (он тривиален), а невозможность получить число
БЕЗ источника.
"""
from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tracker_counts.py"


def _mod():
    spec = importlib.util.spec_from_file_location("tracker_counts", str(_SCRIPT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestSourceIsAlwaysNamed(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_local_counts_warn_that_they_do_not_reflect_origin(self):
        """Сердце аварии: локальное число без предупреждения ввело владельца в заблуждение."""
        with mock.patch.object(self.m, "_git", return_value="1154"):
            note = self.m.source_note(local=True)
        self.assertIn("ЛОКАЛЬНОЕ", note)
        self.assertIn("НЕ отражают origin", note)
        self.assertIn("1154", note, "отставание обязано быть НАЗВАНО числом")

    def test_origin_counts_name_the_commit(self):
        """Источник-истина тоже обязан быть опознаваем — иначе два замера не сравнить."""
        with mock.patch.object(self.m, "_git", return_value="8a67f95a3"):
            note = self.m.source_note(local=False)
        self.assertIn("origin/main", note)
        self.assertIn("8a67f95a3", note)

    def test_unmeasurable_lag_is_UNCHECKED_not_silence(self):
        """«Git не ответил» ≠ «отставания нет» (инвариант #17)."""
        with mock.patch.object(self.m, "_git", return_value=""):
            note = self.m.source_note(local=True)
        self.assertIn("НЕ ИЗМЕРЕНО", note)

    def test_the_default_mode_is_origin_not_local(self):
        """Умолчание обязано быть истиной: ошибиться должно быть ТРУДНЕЕ, чем не ошибиться."""
        src = _SCRIPT.read_text(encoding="utf-8")
        # Заказ #567 / ADR-338. Прежняя редакция утверждала СТРУКТУРУ зова
        # ПОДСТРОКОЙ её текста (`'ap.add_argument("--local"'`), а вся claim
        # «требует ЯВНОГО флага» держится на `action="store_true"`, который
        # лежит ЗА концом литерала: снятие его оставляло проверку ЗЕЛЁНОЙ —
        # замерено возмущением соседа. Проверка РАСШИРЕНА, не ослаблена.
        local = [
            node for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--local"
        ]
        self.assertEqual(len(local), 1,
                         "локальный режим обязан объявляться ровно одним флагом")
        action = {kw.arg: getattr(kw.value, "value", None)
                  for kw in local[0].keywords}.get("action")
        self.assertEqual(action, "store_true",
                         "локальный режим обязан требовать ЯВНОГО флага: без "
                         "store_true у --local появляется значение, и режим "
                         "перестаёт быть явным")
        self.assertNotIn('ap.add_argument("--origin"', src,
                         "origin не может быть опциональным — это умолчание")


class TestCountingItself(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_status_is_read_from_frontmatter(self):
        self.assertEqual(self.m._status_of("---\nstatus: backlog\n---\n"), "backlog")

    def test_a_card_without_status_is_named_not_dropped(self):
        """Молча выброшенная карточка исказила бы итог — она обязана попасть в свой класс."""
        self.assertEqual(self.m._status_of("# карточка без статуса"), "нет-статуса")


if __name__ == "__main__":
    unittest.main()


class BatchReadAndMovement(unittest.TestCase):
    """11.09: чтение одним `git cat-file --batch` и движение бэклога на одном ref.

    Сцена — настоящий git-репозиторий во временном каталоге: вопрос в том, что
    отвечает git, и подмена git'а ответила бы на свой вопрос.
    """

    def _repo(self):
        import subprocess
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"}

        def git(*a, when=None):
            e = dict(env)
            if when:
                e["GIT_AUTHOR_DATE"] = e["GIT_COMMITTER_DATE"] = when
            subprocess.run(["git", *a], cwd=root, env=e, check=True, capture_output=True)

        git("init", "-q")
        tr = root / "nimbalyst-local" / "tracker"
        tr.mkdir(parents=True)
        (tr / "a.md").write_text("---\nstatus: new\n---\n", encoding="utf-8")
        (tr / "b.md").write_text("---\nstatus: backlog\n---\n", encoding="utf-8")
        (tr / "_BOARD.md").write_text("status: done\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "old", when="2020-01-01T00:00:00+00:00")
        (tr / "a.md").write_text("---\nstatus: done\n---\n", encoding="utf-8")
        (tr / "c.md").write_text("нет статуса\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "new")
        m = _mod()
        m.ROOT = str(root)
        return m

    def test_the_batch_reads_what_git_show_reads(self):
        m = self._repo()
        c, ids = m.counts_ref("HEAD")
        self.assertEqual(dict(c), {"done": 1, "backlog": 1, "нет-статуса": 1})
        self.assertNotIn("_BOARD", sum(ids.values(), []), "индекс доски — не карточка")

    def test_a_path_missing_on_the_ref_reads_as_empty(self):
        m = self._repo()
        got = m._show_many("HEAD", ["nimbalyst-local/tracker/a.md", "nimbalyst-local/tracker/zzz.md"])
        self.assertIn("status: done", got["nimbalyst-local/tracker/a.md"])
        self.assertEqual(got["nimbalyst-local/tracker/zzz.md"], "")

    def test_movement_compares_one_ref_at_two_moments(self):
        m = self._repo()
        mv = m.movement(24, ref="HEAD")
        self.assertEqual(mv["now"].get("done"), 1)
        self.assertEqual(mv["before"], {"new": 1, "backlog": 1})
        self.assertIn("HEAD @", mv["source"])

    def test_history_shorter_than_the_window_is_None_not_zero(self):
        """Нет точки «до» ⇒ None: ноль изобразил бы «бэклог не двигался»."""
        m = self._repo()
        import subprocess
        subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=m.ROOT, check=True)
        self.assertIsNone(m.movement(24 * 365 * 20, ref="HEAD")["before"])


class BriefingBacklogSection(unittest.TestCase):
    """Секции брифинга вызываются без изоляции — отказ счётчика обязан остаться в секции."""

    def _briefing(self):
        spec = importlib.util.spec_from_file_location(
            "_briefing_backlog", str(Path(__file__).resolve().parents[2] / "scripts"
                                     / "update_system_briefing.py"))
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        return b

    def test_a_missing_counter_is_UNCHECKED_not_a_crash(self):
        import tempfile
        b = self._briefing()
        with tempfile.TemporaryDirectory() as d:
            b.PROJECT_ROOT = d
            out = b.build_backlog_movement_section()
        self.assertIn("НЕ ИЗМЕРЕНО", out)

    def test_the_section_names_its_source(self):
        b = self._briefing()
        fake = {"source": "origin/main @ abc (коммит x)", "hours": 24,
                "now": {"done": 5, "new": 2, "backlog": 1}, "before": {"done": 3, "new": 2},
                "before_ref": "def"}
        with mock.patch.object(importlib.util, "spec_from_file_location",
                               wraps=importlib.util.spec_from_file_location):
            import types
            tc = types.SimpleNamespace(movement=lambda hours: fake)
            real_mod = importlib.util.module_from_spec
            with mock.patch.object(importlib.util, "module_from_spec",
                                   side_effect=lambda spec: tc if spec.name == "_tracker_counts" else real_mod(spec)):
                with mock.patch.object(type(importlib.util.spec_from_file_location(
                        "x", __file__).loader), "exec_module", lambda self, m: None):
                    out = b.build_backlog_movement_section()
        self.assertIn("origin/main @ abc", out)
        self.assertIn("done **+2**", out)
        self.assertIn("очередь **+1**", out)

    def test_no_point_before_the_window_is_UNCHECKED_not_zero(self):
        b = self._briefing()
        import types
        fake = {"source": "s", "hours": 24, "now": {"done": 1}, "before": None, "before_ref": None}
        real_mod = importlib.util.module_from_spec
        with mock.patch.object(importlib.util, "module_from_spec",
                               side_effect=lambda spec: types.SimpleNamespace(movement=lambda hours: fake)
                               if spec.name == "_tracker_counts" else real_mod(spec)):
            with mock.patch.object(type(importlib.util.spec_from_file_location(
                    "x", __file__).loader), "exec_module", lambda self, m: None):
                out = b.build_backlog_movement_section()
        self.assertIn("за 24 ч: **НЕ ИЗМЕРЕНО**", out)
