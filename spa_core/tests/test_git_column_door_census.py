"""Контроль прибора `scripts/git_column_door_census.py` (ADR-932, заказ G919 п. 5).

Прибор отвечает на вопрос, который цикл #1044 НАЗВАЛ и не сосчитал: сколько
читателей вывода git разбирают его ПО ФИКСИРОВАННОЙ КОЛОНКЕ, и у скольких из
них дверь, отдавшая вывод, этот вывод `.strip()`-ает.

**Каждая сцена здесь — настоящая авария или настоящий невиновный.** Сцена
«бомба» воспроизводит форму дефекта 05.11 дословно (общая дверь
`(proc.stdout or "").strip()` в одном модуле, срез `line[3:]` в другом); сцены
«безопасно» воспроизводят формы, которые в дереве ЖИВУТ и бомбами не являются,
— иначе прибор изготавливал бы находки вместо того, чтобы их мерить.

**Проверка в обе стороны и порознь на каждое звено.** Снятие ЛЮБОГО из трёх
звеньев бомбы (стрижка · срез по колонке · отсутствие якоря) обязано менять
вердикт — и каждое снимается отдельной сценой, а не все разом.

Время, номера процессов и git-окружение хоста ни одна сцена не спрашивает:
прибор разбирает AST файлов, которые сцена кладёт сама.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CENSUS = _ROOT / "scripts" / "git_column_door_census.py"


def _load():
    """Ввезти прибор по пути. Не ввезён ⇒ громкий отказ, а не скип."""
    if not _CENSUS.exists():
        raise AssertionError(f"прибора нет по пути {_CENSUS}")
    spec = importlib.util.spec_from_file_location("gcd_census", _CENSUS)
    mod = importlib.util.module_from_spec(spec)
    # Регистрация ДО исполнения: `@dataclass` спрашивает модуль у `sys.modules`
    # по `__module__`, и без записи получает `None` — ошибка ввоза, не прибора.
    sys.modules["gcd_census"] = mod
    spec.loader.exec_module(mod)
    return mod


gcd = _load()


# ── материал сцен ────────────────────────────────────────────────────────────
#
# Дверь-СТРИЖКА дословно той формы, что живёт в
# `spa_core/monitoring/acceptance_tree_lineage._git` и породила аварию.
DOOR_STRIPS = '''
import subprocess


def _git(repo, *args):
    """(код, вывод). Вывод стрижётся — ровно как у двери аварии 05.11."""
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "").strip()
'''

DOOR_PLAIN = '''
import subprocess


def _git(repo, *args):
    """(код, вывод). Вывод НЕ стрижётся."""
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout
'''

DOOR_UNRESOLVED = '''
import subprocess


def _git(repo, *args):
    """Дверь, чья стрижка статически не разрешается: вывод уходит помощнику."""
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, _shape(proc)


def _shape(proc):
    return proc.stdout
'''

# Читатель-БОМБА: срез по колонке без якоря — форма `orphan_sweep` до починки.
READER_COLUMN = '''
from door import _git


def worktree_door(tree):
    code, out = _git(tree, "status", "--porcelain")
    outside = []
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        outside.append(path)
    return outside
'''

# Читатель с ЯКОРЕМ: форма `system_health_monitor` и `reap_stale_worktrees`.
READER_ANCHORED = '''
from door import _git


def untracked(tree):
    code, out = _git(tree, "status", "--porcelain")
    return [line[3:] for line in out.splitlines() if line.startswith("??")]
'''

# Читатель БЕЗ колонки: регулярка, берущая буквы состояния ЖАДНО — образец
# починки, живущий в `orphan_sweep._porcelain_path`.
READER_REGEX = '''
import re

from door import _git

_RE = re.compile(r"^[ MADRCU?!T]{1,2} (.+)$")


def worktree_door(tree):
    code, out = _git(tree, "status", "--porcelain")
    paths = []
    for line in out.splitlines():
        m = _RE.match(line)
        if m:
            paths.append(m.group(1))
    return paths
'''


def _scene(door_src: str, reader_src: str, *, extra: dict | None = None):
    """Одноразовое дерево с подкаталогом `spa_core/`: дверь + читатель."""
    tmp = tempfile.mkdtemp(prefix="gcd_scene_")
    root = pathlib.Path(tmp)
    pkg = root / "spa_core"
    pkg.mkdir()
    (pkg / "door.py").write_text(door_src, encoding="utf-8")
    (pkg / "reader.py").write_text(reader_src, encoding="utf-8")
    for rel, body in (extra or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def _verdicts(root: pathlib.Path):
    census = gcd.measure(root, ("spa_core",))
    return census, [f.verdict for f in census.findings]


_LIVE: list = []


def _live_census():
    """Замер ЖИВОГО дерева — ОДИН раз на процесс.

    Замер стои́т единицы минут (обход идёт до неподвижной точки засева), а
    спрашивают о нём две проверки. Мерить дважды значило бы платить цену
    дважды за один и тот же ответ; кэш держится в списке, чтобы `None` был
    отличим от «ещё не мерили».
    """
    if not _LIVE:
        _LIVE.append(gcd.measure(_ROOT))
    return _LIVE[0]


class TestTheBombIsFound(unittest.TestCase):
    """Положительный контроль: прибор обязан УВИДЕТЬ аварию 05.11."""

    def test_stripping_door_plus_unanchored_column_is_a_bomb(self):
        root = _scene(DOOR_STRIPS, READER_COLUMN)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB],
                         f"сцена аварии обязана дать БОМБУ, вышло {verdicts}; "
                         f"{[f.as_dict() for f in census.findings]}")
        bomb = census.bombs[0]
        self.assertEqual(bomb.column, "[3:]")
        self.assertTrue(bomb.door.endswith("::_git"), bomb.door)
        self.assertIsNone(bomb.anchor)

    def test_the_cli_answers_the_bomb_with_code_three(self):
        root = _scene(DOOR_STRIPS, READER_COLUMN)
        code = gcd.main(["--root", str(root), "--subtree", "spa_core"])
        self.assertEqual(code, 3, "непустой предмет обязан дать код 3")


class TestEachLinkRemovedChangesTheVerdict(unittest.TestCase):
    """Три звена бомбы снимаются ПОРОЗНЬ, и каждое меняет вердикт."""

    def test_without_the_strip_the_same_reader_is_safe(self):
        root = _scene(DOOR_PLAIN, READER_COLUMN)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_SAFE], verdicts)
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 0)

    def test_with_an_anchor_the_stripping_door_is_safe(self):
        root = _scene(DOOR_STRIPS, READER_ANCHORED)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_SAFE], verdicts)
        self.assertEqual(census.safe[0].anchor, "'??'")

    def test_without_a_column_read_the_site_is_not_in_the_surface(self):
        root = _scene(DOOR_STRIPS, READER_REGEX)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [],
                         "жадная регулярка колонкой не является — поверхности нет")
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 0)


class TestTheThirdOutcomeIsItsOwn(unittest.TestCase):
    """«Не измерено» не складывается ни в бомбу, ни в безопасно (инв. #17)."""

    def test_unresolved_door_gives_unmeasured_not_safe(self):
        root = _scene(DOOR_UNRESOLVED, READER_COLUMN)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_UNMEASURED], verdicts)
        self.assertIn("не разрешилось", census.unmeasured[0].reason)

    def test_unmeasured_surface_gives_code_two_not_zero(self):
        root = _scene(DOOR_UNRESOLVED, READER_COLUMN)
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 2,
                         "«не измерено» обязано отличаться от «чисто»")

    def test_a_root_without_the_declared_subtree_is_unmeasured(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="gcd_empty_"))
        self.assertEqual(gcd.main(["--root", str(tmp), "--subtree", "spa_core"]), 2)

    def test_an_unparsable_module_is_named_not_skipped(self):
        root = _scene(DOOR_STRIPS, READER_COLUMN,
                      extra={"spa_core/broken.py": "def f(:\n"})
        census = gcd.measure(root, ("spa_core",))
        self.assertEqual([m for m, _ in census.unparsed], ["spa_core/broken.py"])
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 3,
                         "бомба важнее неразобранного модуля, но оба названы")


class TestTheDoorIsFoundByEveryNameItTravelsUnder(unittest.TestCase):
    """Дверь приходит к читателю тремя именами, и все три живут в дереве."""

    def test_door_as_a_parameter_default_is_resolved(self):
        """Форма `scripts/reap_stale_worktrees.py`: `def f(x, git=_git)`.

        Первая редакция прибора искала только собственное имя двери и этот
        читатель НЕ НАШЛА — то есть ошибалась в сторону ПУСТОГО предмета.
        """
        reader = '''
from door import _git


def work_paths(tree, git=_git):
    rc, status = git(tree, "status", "--porcelain")
    return {ln[3:] for ln in status.splitlines() if ln}
'''
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB], verdicts)

    def test_door_reached_through_an_index_into_a_split_list(self):
        """Форма `scripts/memory_backup.py`: `ents = out.split("\\0")`; `e = ents[i]`."""
        reader = '''
from door import _git


def uncommitted(tree):
    rc, out = _git(tree, "status", "--porcelain=v1", "-z")
    ents, res, i = out.split("\\0"), [], 0
    while i < len(ents):
        e = ents[i]
        i += 1
        if not e:
            continue
        st, path = e[:2], e[3:]
        res.append((st, path))
    return res
'''
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertTrue(census.bombs,
                        f"срез по индексу разрезанного списка обязан попасть в "
                        f"поверхность; вышло {[f.as_dict() for f in census.findings]}")

    def test_a_non_git_door_is_not_the_subject(self):
        """Дверь, не запускающая git, предметом не является."""
        door = '''
import subprocess


def _ls(repo, *args):
    proc = subprocess.run(["ls", str(repo), *args], capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "").strip()
'''
        reader = '''
from door import _ls


def names(tree):
    code, out = _ls(tree)
    return [line[3:] for line in out.splitlines()]
'''
        root = _scene(door, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [], "предмет — вывод git, а не любой подпроцесс")


class TestRstripIsNotTheSubject(unittest.TestCase):
    """`rstrip` трогает ХВОСТ строки; колонка живёт в её ГОЛОВЕ."""

    def test_rstrip_door_with_a_column_read_is_safe(self):
        door = DOOR_STRIPS.replace('(proc.stdout or "").strip()',
                                   '(proc.stdout or "").rstrip()')
        root = _scene(door, READER_COLUMN)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_SAFE], verdicts)


class TestStripAtTheReadSiteCountsToo(unittest.TestCase):
    """Стрижка КАЖДОЙ строки перед срезом хуже стрижки вывода, не лучше."""

    def test_per_line_strip_before_the_column_is_a_bomb(self):
        reader = '''
from door import _git


def worktree_door(tree):
    code, out = _git(tree, "status", "--porcelain")
    return [line.strip()[3:] for line in out.splitlines() if line]
'''
        root = _scene(DOOR_PLAIN, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB], verdicts)


class TestTheDoorCrossesTheFunctionBoundary(unittest.TestCase):
    """Срез живёт не в той функции, что зовёт дверь — ФОРМА АВАРИИ #1044.

    Сцены написаны циклом #1047 по ЖИВОМУ положительному контролю: в отдельном
    дереве `_porcelain_path` вернули к срезу `line[3:]` (ровно авария 05.11), и
    первая редакция прибора ответила «предмет ПУСТ», не заметив ничего. Причина
    — прибор разбирал ОДНУ функцию, а у `orphan_sweep` между дверью и срезом ДВА
    хопа: вывод уходит параметром `status_out`, строка — параметром `line`.
    «0» описывал ОХВАТ прибора, а не дерево; сторож вакуума (поверхность ≥ 3 и
    стригущие двери > 0) был при этом ЗЕЛЁН — он мерил ровно те срезы, что
    прибор умел видеть, то есть сам себя.
    """

    def test_text_passed_as_a_parameter_reaches_the_callee(self):
        """Хоп первый: вывод уходит ПАРАМЕТРОМ, обход и срез — у получателя."""
        reader = (
            "from door import _git\n\n\n"
            "def axis(status_out):\n"
            "    return [ln[3:] for ln in status_out.splitlines() if ln]\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return axis(out)\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB],
                         f"текст, ушедший параметром, обязан довезти дверь: {verdicts}")
        self.assertEqual(census.bombs[0].func, "axis")

    def test_a_single_line_passed_as_a_parameter_reaches_the_callee(self):
        """Хоп второй: ОДНА строка уходит параметром — форма `_porcelain_path`."""
        reader = (
            "from door import _git\n\n\n"
            "def _path(line):\n"
            "    return line[3:]\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [_path(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB],
                         f"строка, ушедшая параметром, обязана довезти дверь: {verdicts}")
        self.assertEqual(census.bombs[0].func, "_path")

    def test_both_hops_at_once_is_the_accidents_own_shape(self):
        """ДВА хопа подряд — дословно `_git` → `_worktree_axis` → `_porcelain_path`."""
        reader = (
            "from door import _git\n\n\n"
            "def _path(line):\n"
            "    return line[3:]\n\n\n"
            "def axis(status_out):\n"
            "    out = []\n"
            "    for ln in status_out.splitlines():\n"
            "        if not ln.strip():\n"
            "            continue\n"
            "        out.append(_path(ln))\n"
            "    return out\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return axis(out)\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB], verdicts)
        self.assertEqual(census.bombs[0].func, "_path")
        self.assertGreaterEqual(census.propagation_rounds, 2,
                                "два хопа нельзя засеять за один круг — число "
                                "кругов есть ЗАМЕР, а не украшение")

    def test_the_anchor_still_saves_across_the_boundary(self):
        """Снятие звена «нет якоря» ЗА границей функции меняет вердикт."""
        reader = (
            "from door import _git\n\n\n"
            "def _path(line):\n"
            "    if not line.startswith(\"??\"):\n"
            "        return None\n"
            "    return line[3:]\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [_path(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_SAFE], verdicts)
        self.assertEqual(census.safe[0].anchor, "'??'")

    def test_a_plain_door_across_the_boundary_is_safe(self):
        """Снятие звена «дверь стрижёт» ЗА границей функции меняет вердикт."""
        reader = (
            "from door import _git\n\n\n"
            "def _path(line):\n"
            "    return line[3:]\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [_path(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_PLAIN, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_SAFE], verdicts)
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 0)

    def test_a_bound_call_offsets_self_and_seeds_the_right_parameter(self):
        """Зов через точку сдвигает позиции на `self` — засеять надо ВТОРОЙ слот.

        Не знать этого значило бы засеять `self`, а строку НЕ засеять, то есть
        промахнуться В СТОРОНУ ПУСТОГО предмета.
        """
        reader = (
            "from door import _git\n\n\n"
            "class Sweep:\n"
            "    def _path(self, line):\n"
            "        return line[3:]\n\n"
            "    def run(self, tree):\n"
            "        rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "        return [self._path(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB], verdicts)
        self.assertEqual(census.bombs[0].func, "_path")

    def test_two_functions_of_one_name_are_NOT_seeded(self):
        """Одноимённые определения в модуле не разрешаются ВОВСЕ.

        Засеять угаданного получателя хуже «не измерено»: ответ о стрижке
        достался бы ЧУЖОЙ функции. Получатель при этом НАЗЫВАЕТСЯ.
        """
        reader = (
            "from door import _git\n\n\n"
            "def _path(line):\n"
            "    return line[3:]\n\n\n"
            "def _path(line):          # noqa: F811 — ровно предмет сцены\n"
            "    return line\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [_path(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [], f"угаданный получатель запрещён: {verdicts}")
        self.assertTrue(any("_path" in u for u in census.propagation_unresolved),
                        f"неразрешённый получатель обязан быть НАЗВАН, вышло "
                        f"{census.propagation_unresolved}")

    def test_a_receiver_outside_the_tree_is_named_not_silently_dropped(self):
        """Получатель, которого в дереве нет, — названный третий исход."""
        reader = (
            "import shlex\n\n"
            "from door import _git\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [shlex.split(ln) for ln in out.splitlines() if ln]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [])
        self.assertTrue(census.propagation_unresolved,
                        "передача чужому получателю обязана попасть в перечень")

    def test_a_whole_list_of_lines_passed_on_is_a_DECLARED_border(self):
        """Список строк, переданный ЦЕЛИКОМ, прибор не прослеживает — и говорит это.

        Сцена закрепляет ОБЪЯВЛЕННУЮ ГРАНИЦУ, а не умение: закрой её однажды —
        и тест обязан покраснеть, заставив переписать границу, а не тихо
        разойтись с ней.
        """
        reader = (
            "from door import _git\n\n\n"
            "def axis(lines):\n"
            "    return [ln[3:] for ln in lines]\n\n\n"
            "def sweep(tree):\n"
            "    rc, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return axis(out.splitlines())\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(
            verdicts, [],
            "граница объявлена в докстринге `propagations()`: список строк, "
            f"переданный целиком, НЕ прослеживается. Вышло {verdicts} — значит "
            "умение появилось, и границу надо переписать, а не ждать")


class TestTheLiveAnswerIsNotVacuous(unittest.TestCase):
    """Замер живого дерева: предмет пуст, И поверхность НЕ пуста.

    «Бомб ноль» на пустой поверхности было бы вакуумом — тем самым дефектом, что
    нашёлся у места приёмки §49: совпади значение, зелёное ничего не значило бы.
    Поэтому проверка требует ОБА числа.
    """

    def test_the_live_tree_has_a_measured_non_empty_surface(self):
        census = _live_census()
        self.assertGreaterEqual(
            len(census.findings), 3,
            "поверхность живого дерева пуста — прибор перестал что-либо мерить")
        self.assertEqual(
            census.bombs, [],
            "предмет класса НЕПУСТ: "
            + "; ".join(f"{f.module}:{f.lineno} {f.reason}" for f in census.bombs))

    def test_the_live_tree_declares_stripping_doors(self):
        """Половина A в дереве СУЩЕСТВУЕТ — иначе вопрос был бы беспредметен."""
        census = _live_census()
        self.assertGreater(sum(1 for d in census.doors if d.strips is True), 0,
                           "стригущих дверей не найдено — мера половины A мертва")


class TestAnAnchorMustActuallyAnchor(unittest.TestCase):
    """Якорь, сам начинающийся с пробела, якорем НЕ является — он и ломается."""

    def test_a_whitespace_leading_prefix_is_not_an_anchor(self):
        reader = (
            "from door import _git\n\n\n"
            "def changed(tree):\n"
            "    code, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [ln[3:] for ln in out.splitlines() if ln.startswith(\" M\")]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB],
                         f"префикс \" M\" стрижку не переживает ⇒ якорем не является; {verdicts}")

    def test_a_mixed_prefix_tuple_is_not_an_anchor(self):
        """Один негодный литерал в кортеже отменяет якорь целиком."""
        reader = (
            "from door import _git\n\n\n"
            "def changed(tree):\n"
            "    code, out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [ln[3:] for ln in out.splitlines()\n"
            "            if ln.startswith((\"??\", \" M\"))]\n"
        )
        root = _scene(DOOR_STRIPS, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_BOMB], verdicts)

class TestADoorThatReturnsNothingIsUnmeasured(unittest.TestCase):
    """Дверь БЕЗ возврата значения — отдельная ветка «не измерено».

    Мутант «объявить такую дверь НЕстригущей» ВЫЖИЛ в первом прогоне контроля,
    и выжил верно: сцены у этой ветки не было. Выживший мутант прячет половину
    двери (урок G918 п. 7) — сцена дописана, а не мутация снята.
    """

    def test_a_git_door_without_a_valued_return_is_not_called_safe(self):
        door = (
            "import subprocess\n\n\n"
            "def _git(repo, *args):\n"
            "    \"\"\"Зовёт git и НИЧЕГО не возвращает.\"\"\"\n"
            "    subprocess.run([\"git\", \"-C\", str(repo), *args])\n"
        )
        reader = (
            "from door import _git\n\n\n"
            "def paths(tree):\n"
            "    out = _git(tree, \"status\", \"--porcelain\")\n"
            "    return [ln[3:] for ln in out.splitlines() if ln]\n"
        )
        root = _scene(door, reader)
        census, verdicts = _verdicts(root)
        self.assertEqual(verdicts, [gcd.VERDICT_UNMEASURED],
                         f"дверь без возврата значения обязана дать «не измерено»; {verdicts}")
        self.assertEqual(gcd.main(["--root", str(root), "--subtree", "spa_core"]), 2)

if __name__ == "__main__":        # pragma: no cover
    unittest.main()
