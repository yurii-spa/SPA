"""ADR-1080 · читатель очереди НАЗЫВАЕТ дерево трекера, о котором ответил.

ПРЕМИСА (замер 2026-11-23, цикл #1226, воспроизводима двумя командами из worktree,
байт-идентичного `origin/main`):

| чтение | stderr |
|---|---|
| `orchestrator_queue.py list` БЕЗ флага | «трекер ЭТОГО дерева РАСХОДИТСЯ … 752 карточки ЕСТЬ НА ORIGIN, В ДЕРЕВЕ НЕТ» |
| то же с `--tracker-dir <этот worktree>/nimbalyst-local/tracker` | ПУСТО, находок 0 |

Оба утверждения первой строки о «этом дереве» ложны: в моём дереве карточек 1681 и
расхождений ноль, а 938/752 — это ПРОД-копия, куда умолчание
`spa_core.owner_queue.queue._resolve_tracker_dir()` уводит прибор НАМЕРЕННО (`live_root()`,
чтобы вопрос владельцу пережил worktree — карточка-призрак 22.08). Решение верное,
молчание о нём — нет. И совет «работайте из worktree от origin/main» был НЕИСПОЛНИМ: я
уже был в таком worktree, перенос сессии ответа не меняет ни на карточку. Меняет его
`--tracker-dir`, которого совет не называл.

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО, в обе стороны:

* три исхода двери различимы (инв. #17) — дерево кода · ДРУГОЕ дерево · НЕ ИЗМЕРЕНО;
* читатель, у которого измеренный трекер ЧУЖОЙ, печатает ПУТЬ и ИСПОЛНИМЫЙ рычаг;
* читатель, у которого он СВОЙ, рычага НЕ предлагает — штамп «ДРУГОГО дерева» на чём
  угодно бесполезен так же, как молчание (контроль в обратную сторону);
* указательного местоимения «этого дерева» в читателе больше нет ни одного.

ВРЕМЯ И ЛИЧНОСТЬ: ни стенных часов, ни номеров процессов здесь нет вовсе — предмет не
про свежесть. Имя ветки сцены — ВХОД (`git init -b`), потому что `init.defaultBranch` на
`ubuntu-latest` даёт `master`, и фикстура, назвавшая потом `main`, была бы зелена на Маке
и красна в CI (`.claude/rules/deployment.md` § GIT-ОКРУЖЕНИЕ).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402

#: Имя ветки сцены — ВХОД, а не умолчание хоста.
SCENE_REF = "scene-main"


def _load_reader():
    """Читатель очереди — ТОГО дерева, что и этот тест (своя копия, не чья-то)."""
    path = _REPO_ROOT / "scripts" / "orchestrator_queue.py"
    spec = importlib.util.spec_from_file_location("_oq_tree_named", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=60)


def _card(name: str, status: str = "new") -> str:
    return ("---\ntype: inbox\n"
            f"status: {status}\n"
            f'title: "{name}"\n'
            "---\n\nтело\n")


class TheDoorDistinguishesThreeOutcomes(unittest.TestCase):
    """Инв. #17 у самой двери: «моё» · «чужое» · НЕ ИЗМЕРЕНО — три разных ответа."""

    def _report(self, tracker: str) -> drift.Report:
        return drift.Report(ref="origin/main", ref_sha="deadbeef1",
                            tracker_dir=tracker, tree_count=1, origin_count=2)

    def test_the_tree_of_the_running_code_is_named_as_such(self):
        tracker = str(_REPO_ROOT / "nimbalyst-local" / "tracker")
        got = drift.measured_tree(self._report(tracker), code_tracker=tracker)
        self.assertEqual(got.kind, drift.TREE_CODE)
        self.assertIn(tracker, got.line())
        # Рычага у «своего» дерева нет: предлагать флаг туда, где он ничего не меняет,
        # значит звать к действию без последствия.
        self.assertNotIn("--tracker-dir", got.line())

    def test_another_tree_is_named_WITH_an_executable_lever(self):
        got = drift.measured_tree(self._report("/elsewhere/nimbalyst-local/tracker"),
                                  code_tracker="/mine/nimbalyst-local/tracker")
        self.assertEqual(got.kind, drift.TREE_OTHER)
        line = got.line()
        self.assertIn("/elsewhere/nimbalyst-local/tracker", line)
        self.assertIn("/mine/nimbalyst-local/tracker", line)
        # Исполнимый рычаг — ЧАСТЬ ответа. Это и есть предмет находки #1226.
        self.assertIn("--tracker-dir /mine/nimbalyst-local/tracker", line)
        self.assertIn("НЕ МЕНЯЕТ", line)

    def test_a_report_without_a_tracker_dir_is_UNMEASURED_not_a_guess(self):
        got = drift.measured_tree(self._report(""), code_tracker="/mine/t")
        self.assertEqual(got.kind, drift.TREE_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", got.line())
        self.assertTrue(got.reason, "третий исход обязан НАЗЫВАТЬ причину")
        self.assertEqual(got.lever, "", "рычага у неизмеренного исхода быть не может")

    def test_a_caller_that_names_no_tree_of_its_own_gets_UNMEASURED(self):
        """Умолчания у `code_tracker` нет — и это закрывает выжившую мутацию M10.

        `_CODE_TRACKER_DIR = None` у читателя прошло мимо первого круга: дверь падала на
        `_REPO_ROOT` ПРИБОРА, а он в сцене — то же дерево, и подстановка была неотличима
        от правды. Теперь «не назвал» это третий исход, а не тихий ответ о чужом дереве.
        """
        for empty in (None, "", "   "):
            with self.subTest(code_tracker=empty):
                got = drift.measured_tree(self._report("/elsewhere/t"),
                                          code_tracker=empty)
                self.assertEqual(got.kind, drift.TREE_UNMEASURED)
                self.assertIn("НЕ НАЗВАЛ", got.reason)

    def test_the_three_kinds_are_three_distinct_values(self):
        self.assertEqual(3, len({drift.TREE_CODE, drift.TREE_OTHER,
                                 drift.TREE_UNMEASURED}))


class TheReaderNamesTheTrackerItMeasured(unittest.TestCase):
    """Исход мерится У ЧИТАТЕЛЯ: настоящий `cmd_list` на одноразовой сцене."""

    def setUp(self):
        self.reader = _load_reader()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "repo"
        self.tracker = root / drift.TRACKER_REL
        self.tracker.mkdir(parents=True)
        r = _git(Path(self._tmp.name), "init", "-q", "-b", SCENE_REF, str(root))
        if r.returncode != 0:
            self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git init дал {r.returncode}: "
                      f"{r.stderr.strip()}")
        (self.tracker / "inbox-scene-a.md").write_text(_card("сцена A"),
                                                       encoding="utf-8")
        for args in (("add", "-A"),
                     ("-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "-m", "сцена")):
            r = _git(root, *args)
            if r.returncode != 0:
                self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {args[0]} дал "
                          f"{r.returncode}: {r.stderr.strip()}")
        # Карточка, которой на ref НЕТ: это и даёт находку `undelivered`, то есть
        # НЕПУСТУЮ сверку — иначе шапку расхождения не печатает никто и мерить нечего.
        (self.tracker / "inbox-scene-b.md").write_text(_card("сцена B"),
                                                       encoding="utf-8")

    def _ask(self):
        out, err = io.StringIO(), io.StringIO()
        argv = ["list", "--tracker-dir", str(self.tracker), "--ref", SCENE_REF, "--json"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.reader.cmd_list(self.reader.build_parser().parse_args(argv))
        return json.loads(out.getvalue() or "[]"), err.getvalue()

    def test_a_foreign_measured_tracker_is_named_with_its_path_and_the_lever(self):
        cards, err = self._ask()
        self.assertTrue(cards, "предпосылка НЕ ОБЕСПЕЧЕНА: сцена не дала ни карточки")
        self.assertIn(str(self.tracker.resolve()), err,
                      "читатель не назвал ПУТЬ измеренного трекера")
        self.assertIn("--tracker-dir", err,
                      "читатель не назвал исполнимый рычаг")
        self.assertNotIn("этого дерева", err,
                         "указательное местоимение вернулось вместо пути")

    def test_when_the_measured_tracker_IS_the_code_tree_no_lever_is_offered(self):
        # Различающая сцена. Без неё выжила бы мутация «штамповать „ДРУГОГО дерева“
        # всегда»: набор упавших имён не изменился бы (дословно урок #1202/#1217).
        # Подмена закрывается с ВОЗВРАТОМ — подмена, пережившая сцену, вредит СОСЕДУ
        # (`.claude/rules/deployment.md` § СОСЕД ПО ПРОЦЕССУ).
        was = self.reader._CODE_TRACKER_DIR
        self.reader._CODE_TRACKER_DIR = str(self.tracker)
        self.addCleanup(setattr, self.reader, "_CODE_TRACKER_DIR", was)
        cards, err = self._ask()
        self.assertTrue(cards, "предпосылка НЕ ОБЕСПЕЧЕНА: сцена не дала ни карточки")
        self.assertIn("ДЕРЕВА ЗАПУЩЕННОГО КОДА", err)
        self.assertNotIn("--tracker-dir", err,
                         "рычаг предложен туда, где он ничего не меняет")

    def test_the_two_scenes_give_DIFFERENT_answers(self):
        """Дискриминация прямым сравнением: одна сцена — один ответ, другая — другой."""
        _, foreign = self._ask()
        was = self.reader._CODE_TRACKER_DIR
        self.reader._CODE_TRACKER_DIR = str(self.tracker)
        self.addCleanup(setattr, self.reader, "_CODE_TRACKER_DIR", was)
        _, mine = self._ask()
        self.assertNotEqual(foreign, mine,
                            "читатель отвечает ОДИНАКОВО о своём и о чужом дереве")


class TheNoteIsPrintedEvenWhenNothingDiverges(unittest.TestCase):
    """Умолчание ПЕЧАТАЕТСЯ — и на ЧИСТОЙ сверке тоже.

    Без этой сцены выживала бы мутация «печатать строку только под находками»: на чистой
    сверке молчание читается как «ответ про моё дерево», и это ровно та молчаливая
    подстановка, которую запрещает `.claude/rules/deployment.md` («ВЫБОР ПЕЧАТАЕТСЯ»).
    """

    def setUp(self):
        self.reader = _load_reader()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "repo"
        self.tracker = root / drift.TRACKER_REL
        self.tracker.mkdir(parents=True)
        r = _git(Path(self._tmp.name), "init", "-q", "-b", SCENE_REF, str(root))
        if r.returncode != 0:
            self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git init дал {r.returncode}")
        (self.tracker / "inbox-clean.md").write_text(_card("чистая сцена"),
                                                     encoding="utf-8")
        for args in (("add", "-A"),
                     ("-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "-m", "чисто")):
            r = _git(root, *args)
            if r.returncode != 0:
                self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {args[0]} дал "
                          f"{r.returncode}: {r.stderr.strip()}")

    def test_a_clean_comparison_still_names_the_measured_tracker(self):
        out, err = io.StringIO(), io.StringIO()
        argv = ["list", "--tracker-dir", str(self.tracker), "--ref", SCENE_REF, "--json"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.reader.cmd_list(self.reader.build_parser().parse_args(argv))
        text = err.getvalue()
        self.assertNotIn("РАСХОДИТСЯ", text,
                         "предпосылка НЕ ОБЕСПЕЧЕНА: сцена не чиста")
        self.assertIn(str(self.tracker.resolve()), text,
                      "на чистой сверке читатель НЕ назвал измеренный трекер")


class TheHiddenCardAdviceIsExecutable(unittest.TestCase):
    """Совет у «скрытых» карточек зависит от ТОГО ЖЕ вопроса — и он один из двух.

    Это отдельный класс, а не ещё один `assertIn` к шапке: строка рычага и строка
    совета — ДВА утверждения, и мутация, снявшая второе, в шапке не видна (рычаг там
    остаётся). Проверяется ИМЕННО строка совета.
    """

    def setUp(self):
        self.reader = _load_reader()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "repo"
        self.root, self.tracker = root, root / drift.TRACKER_REL
        self.tracker.mkdir(parents=True)
        r = _git(Path(self._tmp.name), "init", "-q", "-b", SCENE_REF, str(root))
        if r.returncode != 0:
            self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git init дал {r.returncode}")
        # Карточка есть на ref и НЕТ в дереве ⇒ класс `hidden`, ради которого и писался
        # совет. Удаляем ПОСЛЕ коммита: иначе на ref её не будет тоже.
        (self.tracker / "inbox-hidden.md").write_text(_card("скрытая"),
                                                      encoding="utf-8")
        (self.tracker / "inbox-kept.md").write_text(_card("остаётся"),
                                                    encoding="utf-8")
        for args in (("add", "-A"),
                     ("-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "-m", "сцена")):
            r = _git(root, *args)
            if r.returncode != 0:
                self.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {args[0]} дал "
                          f"{r.returncode}: {r.stderr.strip()}")
        (self.tracker / "inbox-hidden.md").unlink()

    def _advice_line(self):
        out, err = io.StringIO(), io.StringIO()
        argv = ["list", "--tracker-dir", str(self.tracker), "--ref", SCENE_REF, "--json"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.reader.cmd_list(self.reader.build_parser().parse_args(argv))
        lines = [ln for ln in err.getvalue().splitlines() if "ЕСТЬ НА ORIGIN" in ln]
        if not lines:
            self.fail("предпосылка НЕ ОБЕСПЕЧЕНА: сцена не дала класса `hidden`")
        return lines[0]

    def test_a_foreign_tracker_gets_the_flag_not_a_relocation(self):
        line = self._advice_line()
        self.assertIn("--tracker-dir", line)
        self.assertIn("НЕ ИЗМЕНИТ", line)
        self.assertNotIn("работайте из worktree", line,
                         "неисполнимый совет вернулся на чужое дерево")

    def test_the_code_tree_gets_the_relocation_advice_which_IS_executable_there(self):
        was = self.reader._CODE_TRACKER_DIR
        self.reader._CODE_TRACKER_DIR = str(self.tracker)
        self.addCleanup(setattr, self.reader, "_CODE_TRACKER_DIR", was)
        line = self._advice_line()
        self.assertIn(f"работайте из worktree от {SCENE_REF}", line)
        self.assertNotIn("--tracker-dir", line)


class TheOldIndicativePronounIsGone(unittest.TestCase):
    """Положительный контроль на саму аварию: фразы «трекер этого дерева» больше нет."""

    def test_the_reader_source_no_longer_calls_a_foreign_tracker_this_tree(self):
        src = (_REPO_ROOT / "scripts" / "orchestrator_queue.py").read_text(
            encoding="utf-8")
        self.assertNotIn("трекер этого дерева", src)

    def test_the_door_lives_in_the_instrument_not_in_the_reader(self):
        # Вторая копия одной мерки расходится молча (ADR-220): дверь ОДНА, у прибора.
        self.assertTrue(hasattr(drift, "measured_tree"))
        src = (_REPO_ROOT / "scripts" / "orchestrator_queue.py").read_text(
            encoding="utf-8")
        self.assertIn("drift.measured_tree(", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
