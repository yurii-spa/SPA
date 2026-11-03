#!/usr/bin/env python3
"""ДЕСЯТАЯ дверь семейства «вердикт зависит не от кода»: СОДЕРЖИМОЕ ДЕРЕВА.

Зачем
------------------------------------------------------------------------------
Девять разделов ``.claude/rules/deployment.md`` закрывают двери, через которые в
вердикт попадает свойство ХОСТА (календарь, номер процесса, git-окружение) либо
свойство ДОСТАВКИ (окно прибора, окно доставки, дерево байтов, не-Python, строка
реестра, граница подпроцесса). У всех девяти общее одно: код не менялся ни на байт,
а вердикт сменился.

Десятая дверь ведёт туда же, но её ключ лежит ВНУТРИ репозитория: вердикт теста
бывает свойством СОДЕРЖИМОГО дерева — не кода и не фикстуры, а живых данных, которые
в дереве просто лежат. Предмет найден циклом #1015 на
``test_acceptance_probe_writer``: его последняя проверка читает ЖИВУЮ очередь карточек
и красна ровно тогда, когда ни одна открытая карточка не объявляет пробы. Закрытие
последней такой карточки — законное, желаемое событие — красит набор, и ни одна строка
кода при этом не меняется.

Второй названный член класса иного рода и хуже: ``test_inbox_acceptance_ratchet``
читает очередь ЖИВОГО дерева (``owner_queue.queue.TRACKER_DIR`` указывает на прод, а не
на дерево вызывающего — это сделано намеренно, ADR про карточку-призрак), поэтому его
вердикт есть свойство дерева, которого прогон даже не видит, и он ОДИНАКОВ на любой
ветке.

Что отвечает этот прибор и чего он НЕ отвечает
------------------------------------------------------------------------------
**Поверхность класса НЕ ЕСТЬ класс.** Тест, который НАЗЫВАЕТ очередь, бомбой не
является: половина набора обязана читать дерево — в этом и состоит работа храповика.
Поэтому прибор отвечает на ДВА РАЗНЫХ вопроса, и у каждого свой режим:

``--surface`` (умолчание)
    Разбор AST: какие тест-файлы добираются до НАСТОЯЩЕЙ очереди (а не до своего
    ``tempfile``), и КАКОЙ дверью. Двери объявлены и различимы:

    * ``tree_literal`` — файл называет ``nimbalyst-local`` литералом, то есть читает
      очередь СВОЕГО дерева: вердикт есть свойство содержимого ЭТОГО дерева;
    * ``live_tracker_dir`` — файл берёт ``TRACKER_DIR`` (ввозом или атрибутом), то есть
      читает очередь ЖИВОГО дерева: вердикт есть свойство дерева, которого прогон не
      видит, и он одинаков на любой ветке.

    Рядом считается ось ``seam_present`` — встречается ли в файле шов
    (``--tracker-dir`` / ``SPA_TRACKER_DIR`` / ``tracker_dir=``). Шов в файле
    ОСВОБОЖДЕНИЕМ не является: он живёт в одном вызове и отсутствует в другом (ровно
    так устроен ``test_acceptance_probe_writer``), а разбор идёт по ФАЙЛУ. Поэтому это
    отдельная ось, а не фильтр поверхности.

``--observe --run-root <дерево>``
    **Поверхность, измеренная ПРОГОНОМ, а не разбором.** Разбор AST видит файл, а не
    вызов, и тест, добирающийся до очереди через ОБЩЕГО помощника, он числит вне
    поверхности (та же граница, о которую споткнулся сторож претензии
    ``injected-clock``). Поэтому поверхность AST прогоняется ОДИН раз под слуховым
    крюком (``sys.addaudithook``): крюк записывает, какой nodeid какой дверью ФС
    (``open`` / ``os.listdir`` / ``os.scandir`` / ``os.stat``) коснулся очереди СЦЕНЫ —
    и, ОТДЕЛЬНЫМ счётчиком, очереди ЖИВОГО дерева. Второй счётчик и есть мера двери
    ``live_tracker_dir`` по факту, а не по объявлению: тест, дотянувшийся до прода
    сквозь шов, назван поимённо.

``--differential --run-root <дерево>``
    Замер КЛАССА методом § «GIT-ОКРУЖЕНИЕ в тестах» того же правила. Сначала идёт
    наблюдающий прогон (выше) — он сужает поверхность AST до тех, кто очередь
    ДЕЙСТВИТЕЛЬНО читает; затем ЭТОТ подмножество прогоняется НЕСКОЛЬКО раз, и
    единственное, что меняется между прогонами, — СОДЕРЖИМОЕ очереди в дереве:

    1. ``base`` — содержимое как есть;
    2. ``empty`` — карточек нет вовсе;
    3. ``no_criterion`` — карточки на месте, но ни одна не объявляет машинного
       критерия (``acceptance_probe`` / ``finding_key`` сняты).

    **Тест, у которого от этого меняется вердикт, и есть предмет класса.** Смена
    перемеряется ПОВТОРНЫМ базовым прогоном: не вернулась ⇒ ``unmeasured`` (шумный
    тест), а не находка.

    База для сцен берётся ПРОГОНОМ ПОДМНОЖЕСТВА, а не вырезается из наблюдающего
    прогона всей поверхности: вердикт теста зависит и от соседей по сессии, и
    сравнивать «в полном наборе» со «в подмножестве» значило бы мерить ДВЕ разницы
    сразу, выдавая их сумму за одну.

    Переход в ``skipped`` мерится наравне с ``passed``/``failed`` — урок #465: в
    дифференциальном замере такой тест не краснеет и не проходит, он ИСЧЕЗАЕТ, и
    глазами это читается как «всё в порядке».

Почему шов подменяется в КАЖДОЙ сцене, включая базовую
------------------------------------------------------------------------------
``SPA_TRACKER_DIR`` уводится на очередь ОДНОРАЗОВОГО дерева во ВСЕХ прогонах, иначе
дверь ``live_tracker_dir`` была бы невидима по построению: такой тест отвечал бы о
проде в каждой сцене и вердикта не менял бы НИ РАЗУ — то есть замер докладывал бы о
своей подстановке, а не о классе. Живая очередь при этом не трогается ни одним байтом:
прибор ОТКАЗЫВАЕТ работать, если разрешённый путь очереди ведёт в живое дерево.

Три исхода (инв. #17)
------------------------------------------------------------------------------
Код возврата: **0** — измерено, класс ПУСТ · **1** — измерено, класс НЕ ПУСТ (имена
названы) · **2** — НЕ ИЗМЕРЕНО с названной причиной. Файл, который не прочитан или не
разобран, получает ``unmeasured`` поимённо и НИКОГДА не считается «прошедшим». Сцена,
после которой содержимое очереди не вернулось ПОБАЙТНО, — тоже код 2: дерево, которое
прибор испортил, не вправе отвечать о классе.

Чего прибор НЕ закрывает (названо, а не умолчано)
------------------------------------------------------------------------------
* Разбор AST идёт по ОДНОМУ файлу: тест, добирающийся до очереди через ОБЩЕГО
  помощника, в поверхность AST не попадает. Наблюдающий прогон эту границу СНИМАЕТ
  ТОЛЬКО ВНУТРИ уже отобранных AST-файлов — файл, который AST не назвал, под крюк не
  попадает вовсе, и это остаётся ВЕРХНЕЙ границей сужения, а не полнотой. Прогнать под
  крюком весь набор прибор умеет (``--roots``), и цена этого названа, а не умолчана.
* Слуховой крюк видит ДВЕРЬ ФС, а не намерение: тест, который очередь только
  перечислил и ничего из неё не прочитал, в подмножество попадёт. Это ошибка в сторону
  НАХОДКИ и выбрана намеренно.
* И обратная сторона той же двери, ИЗМЕРЕННАЯ: событие ``os.stat`` интерпретатор не
  поднимает, поэтому касание очереди ТОЛЬКО через ``stat`` (``os.path.isdir``) крюку
  невидимо. Это ошибка в сторону ПРОПУСКА, и она названа здесь, закреплена контролем и
  НЕ закрыта.
* Дифференциальный прогон отвечает о сценах, которые СУЩЕСТВУЮТ: ось содержимого, у
  которой сегодня нет ни одного теста, им не найдётся.
* Содержимое очереди — не единственное содержимое дерева. ``data/``, ``docs/``,
  ``architecture/`` суть такие же оси, и ЗДЕСЬ они не измерены вовсе: прибор мерит ту
  ось, на которой класс найден.
* «Красен сегодня» мерой класса не является и наоборот: тест, чей вердикт СЕГОДНЯ
  зелен при любом содержимом, остаётся предметом класса, если содержимое может его
  перевернуть, — именно поэтому мера дифференциальная, а не «кто красен».

ADVISORY: прибор ЧИТАЕТ дерево, правит СОДЕРЖИМОЕ ОЧЕРЕДИ одноразового дерева на время
сцены и возвращает его побайтно. Ни одного файла набора он не меняет.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Модуль живёт В ПАКЕТЕ (``python3 -m spa_core.tests._tracker_content_door``), поэтому
# корень дерева на ``sys.path`` уже есть. Страховка оставлена намеренно: сверстник
# (`_subprocess_clock_door`) заплатил за её отсутствие молчаливым «НЕ ИЗМЕРЕНО 30 из 30».
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Канонический охват — тот же каталог, который гоняет предписанный прогон и в котором
#: живут оба названных члена класса. Шире мерить можно (`--roots`), но умолчание
#: совпадает с местом находки, а не с удобством.
CANON_ROOTS = ("spa_core/tests", "scripts/tests", "tests")

#: Имя каталога очереди в дереве. Одна копия строки на прибор.
TRACKER_REL = ("nimbalyst-local", "tracker")

#: Поля frontmatter, которые есть МАШИННЫЙ КРИТЕРИЙ карточки (`.claude/rules/acceptance.md`).
CRITERION_FIELDS = ("acceptance_probe", "finding_key")

#: Двери к НАСТОЯЩЕЙ очереди. Порядок — от «своё дерево» к «чужое дерево».
DOOR_TREE_LITERAL = "tree_literal"
DOOR_LIVE_TRACKER_DIR = "live_tracker_dir"

#: Сцены содержимого. `base` обязана идти первой и последней (перемер шума).
SCENE_BASE = "base"
SCENE_EMPTY = "empty"
SCENE_NO_CRITERION = "no_criterion"
SCENES = (SCENE_EMPTY, SCENE_NO_CRITERION)

_VERDICTS = {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS",
             "SUBFAILED", "SUBFAIL"}

#: Схема файла объявления класса (`spa_core/tests/tree_content_class_baseline.json`,
#: ADR-907). Строка живёт У ПИСАТЕЛЯ, а читатель (`test_tree_content_class_ratchet`)
#: её ИМПОРТИРУЕТ: две копии одной схемы и есть то расхождение писателя с читателем,
#: о котором читатель обязан отказать.
DECLARATION_SCHEMA = "tree-content-class/1"


# --------------------------------------------------------------------------- #
# Поверхность
# --------------------------------------------------------------------------- #
@dataclass
class FileSurface:
    """Что прибор увидел в ОДНОМ файле."""

    path: str
    doors: list[str] = field(default_factory=list)
    seam_present: bool = False
    unmeasured: str | None = None

    def as_dict(self) -> dict:
        return {"path": self.path, "doors": sorted(self.doors),
                "seam_present": self.seam_present, "unmeasured": self.unmeasured}


def _string_constants(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _names_tree_tracker(consts: list[str]) -> bool:
    """Файл называет очередь СВОЕГО дерева.

    Совпадение по ``nimbalyst-local`` — и по склеенному пути, и по сегменту: путь в
    наборе собирают и литералом целиком (``"nimbalyst-local/tracker"``), и кусками
    (``os.path.join(_REPO, "nimbalyst-local", "tracker")``).
    """
    return any(TRACKER_REL[0] in s for s in consts)


def _binds_live_tracker_dir(tree: ast.AST) -> bool:
    """Файл берёт ``TRACKER_DIR`` — ввозом или атрибутом чужого модуля."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(a.name == "TRACKER_DIR" for a in node.names):
                return True
        elif isinstance(node, ast.Attribute) and node.attr == "TRACKER_DIR":
            return True
        elif isinstance(node, ast.Name) and node.id == "TRACKER_DIR":
            return True
    return False


def _has_seam(consts: list[str], tree: ast.AST) -> bool:
    """Встречается ли в файле шов подмены очереди.

    ОСВОБОЖДЕНИЕМ это не является (см. докстринг модуля): шов живёт в одном вызове и
    отсутствует в другом, а мерится ФАЙЛ. Ось — отдельная.
    """
    if any("--tracker-dir" in s or "SPA_TRACKER_DIR" in s for s in consts):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "tracker_dir":
            return True
    return False


def measure_surface(repo_root: Path,
                    roots: tuple[str, ...] = CANON_ROOTS) -> dict:
    """Поверхность: какие тест-файлы добираются до НАСТОЯЩЕЙ очереди и какой дверью."""
    files: list[FileSurface] = []
    missing_roots: list[str] = []
    for rel in roots:
        root = repo_root / rel
        if not root.is_dir():
            missing_roots.append(rel)
            continue
        for path in sorted(root.glob("test_*.py")):
            relpath = path.relative_to(repo_root).as_posix()
            try:
                src = path.read_text(encoding="utf-8")
            except OSError as exc:
                files.append(FileSurface(relpath, unmeasured=f"не прочитан: {exc}"))
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                files.append(FileSurface(relpath, unmeasured=f"не разобран: {exc}"))
                continue
            consts = _string_constants(tree)
            doors: list[str] = []
            if _names_tree_tracker(consts):
                doors.append(DOOR_TREE_LITERAL)
            if _binds_live_tracker_dir(tree):
                doors.append(DOOR_LIVE_TRACKER_DIR)
            if not doors:
                continue
            files.append(FileSurface(relpath, doors=doors,
                                     seam_present=_has_seam(consts, tree)))
    on_surface = [f for f in files if f.doors]
    unmeasured = [f for f in files if f.unmeasured]
    return {
        "repo_root": str(repo_root),
        "roots": list(roots),
        "missing_roots": missing_roots,
        "files": [f.as_dict() for f in files],
        "counts": {
            "on_surface": len(on_surface),
            "tree_literal": sum(1 for f in on_surface if DOOR_TREE_LITERAL in f.doors),
            "live_tracker_dir": sum(1 for f in on_surface
                                    if DOOR_LIVE_TRACKER_DIR in f.doors),
            "seam_present": sum(1 for f in on_surface if f.seam_present),
            "unmeasured": len(unmeasured),
        },
    }


# --------------------------------------------------------------------------- #
# Сцены содержимого
# --------------------------------------------------------------------------- #
def _cards(tracker: Path) -> list[Path]:
    return sorted(p for p in tracker.iterdir() if p.is_file() and p.suffix == ".md")


def fingerprint(tracker: Path) -> str:
    """Слепок СОДЕРЖИМОГО очереди: имя + байты, по отсортированному перечню."""
    h = hashlib.sha256()
    for path in sorted(tracker.rglob("*")):
        if not path.is_file():
            continue
        h.update(path.relative_to(tracker).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def apply_scene(tracker: Path, scene: str) -> int:
    """Подменить СОДЕРЖИМОЕ очереди. Возвращает число тронутых файлов."""
    if scene == SCENE_BASE:
        return 0
    if scene == SCENE_EMPTY:
        cards = _cards(tracker)
        for path in cards:
            path.unlink()
        return len(cards)
    if scene == SCENE_NO_CRITERION:
        touched = 0
        for path in _cards(tracker):
            text = path.read_text(encoding="utf-8", errors="replace")
            kept = [ln for ln in text.splitlines(keepends=True)
                    if not any(ln.startswith(f"{fld}:") for fld in CRITERION_FIELDS)]
            new = "".join(kept)
            if new != text:
                path.write_text(new, encoding="utf-8")
                touched += 1
        return touched
    raise ValueError(f"неизвестная сцена: {scene}")


# --------------------------------------------------------------------------- #
# Наблюдающий прогон: поверхность, измеренная ПРОГОНОМ
# --------------------------------------------------------------------------- #
#: Двери ФС, через которые чтение очереди становится ВИДИМЫМ слуховому крюку.
#:
#: ``os.stat`` объявлен, но ЗАМЕР говорит, что на этом интерпретаторе он НЕ
#: ПОДНИМАЕТСЯ: касание, идущее ТОЛЬКО через stat (``os.path.isdir(очередь)``,
#: ``Path(...).exists()``), крюку невидимо, и тест, чей единственный разговор с
#: очередью — такая проверка, в подмножество не попадёт. Дыра ИЗМЕРЕНА и закреплена
#: контролем (`test_tracker_content_door_census.py`), а не умолчана; «измерено и равно
#: нулю» здесь отличается от «не спрашивали» (инв. #17). Имя оставлено в наборе
#: намеренно: если сборка интерпретатора событие поднимает, дыры у неё нет.
WATCHED_EVENTS = ("open", "os.listdir", "os.scandir", "os.stat")


def observer_source() -> str:
    """Плагин pytest, записывающий, какой nodeid коснулся КАКОЙ очереди.

    Крюк ``sys.addaudithook`` снять нельзя — поэтому он живёт только в ДЕТСКОМ
    процессе прибора и ни одного файла набора не трогает. Две цели считаются
    РАЗДЕЛЬНО: очередь сцены (``SPA_TCD_WATCH_SCENE``) и очередь ЖИВОГО дерева
    (``SPA_TCD_WATCH_LIVE``). Второй счётчик и есть мера двери `live_tracker_dir` по
    ФАКТУ: тест, дотянувшийся до прода сквозь шов, назван поимённо.
    """
    return (
        "import json, os, sys\n"
        "_SCENE = os.environ.get('SPA_TCD_WATCH_SCENE') or ''\n"
        "_LIVE = os.environ.get('SPA_TCD_WATCH_LIVE') or ''\n"
        "_OUT = os.environ.get('SPA_TCD_OUT') or ''\n"
        "_EVENTS = frozenset(%r)\n"
        "_cur = ['<сбор и импорт>']\n"
        "_scene_hits = {}\n"
        "_live_hits = {}\n"
        "def _bump(store):\n"
        "    store[_cur[0]] = store.get(_cur[0], 0) + 1\n"
        "def _hook(event, args):\n"
        "    if event not in _EVENTS or not args:\n"
        "        return\n"
        "    try:\n"
        "        s = os.fspath(args[0])\n"
        "    except Exception:\n"
        "        return\n"
        "    if not isinstance(s, str):\n"
        "        return\n"
        "    if _SCENE and _SCENE in s:\n"
        "        _bump(_scene_hits)\n"
        "    if _LIVE and _LIVE in s:\n"
        "        _bump(_live_hits)\n"
        "sys.addaudithook(_hook)\n"
        "def pytest_runtest_logstart(nodeid, location):\n"
        "    _cur[0] = nodeid\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    if not _OUT:\n"
        "        return\n"
        "    with open(_OUT, 'w', encoding='utf-8') as fh:\n"
        "        json.dump({'scene': _scene_hits, 'live': _live_hits}, fh,\n"
        "                  ensure_ascii=False)\n"
    ) % (list(WATCHED_EVENTS),)


def materialise_observer(target: Path) -> Path:
    """Выложить плагин в каталог и вернуть путь к нему."""
    target.mkdir(parents=True, exist_ok=True)
    plugin = target / "tcd_observer.py"
    plugin.write_text(observer_source(), encoding="utf-8")
    return plugin


def observe(tree_root: Path, tracker: Path, files: list[str], *, timeout_s: int,
            workdir: Path) -> dict:
    """Один прогон поверхности под крюком. Возвращает ИЗМЕРЕННУЮ поверхность."""
    plugin = materialise_observer(workdir / "observer")
    out = workdir / "observed.json"
    live = _live_tracker_candidates()
    extra = {
        "SPA_TCD_WATCH_SCENE": str(tracker),
        "SPA_TCD_WATCH_LIVE": str(live[0]) if live else "",
        "SPA_TCD_OUT": str(out),
        "PYTHONPATH": os.pathsep.join(
            [str(plugin.parent)] + ([os.environ["PYTHONPATH"]]
                                    if os.environ.get("PYTHONPATH") else [])),
    }
    outcomes, tail, code = run_pytest(tree_root, tracker, files, timeout_s=timeout_s,
                                      label="наблюдение", env_extra=extra,
                                      plugin=plugin.stem)
    if not out.is_file():
        return {"verdict": "unmeasured",
                "reason": "крюк не оставил отчёта — наблюдение НЕ ИЗМЕРЕНО",
                "tail": tail, "returncode": code}
    try:
        hits = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"verdict": "unmeasured",
                "reason": f"отчёт крюка не разобран: {exc}", "tail": tail}
    scene_nodes = sorted(n for n in hits.get("scene", {}) if "::" in n)
    live_nodes = sorted(n for n in hits.get("live", {}) if "::" in n)
    touched_files, unresolved = _resolve_touched(tree_root, scene_nodes)
    return {
        "verdict": "measured",
        "outcomes": outcomes,
        "returncode": code,
        "nodes_touching_scene": scene_nodes,
        "nodes_touching_live": live_nodes,
        "files_touching_scene": touched_files,
        "files_unresolved": unresolved,
        "import_time_touch": sorted(n for n in hits.get("scene", {}) if "::" not in n),
        "tail": tail if code not in (0, 1) else "",
    }


def _resolve_touched(tree_root: Path,
                     nodes: list[str]) -> tuple[list[str], list[str]]:
    """Имя файла теста, приведённое к ПУТИ ОТ КОРНЯ ДЕРЕВА.

    ``--rootdir`` объявлен и в норме имена уже такие; эта дверь — страховка и ТРЕТИЙ
    ИСХОД: файл, которого в дереве по такому имени нет, попадает в ``unresolved``
    поимённо и НИКОГДА не выдаётся за «не касался». Подставить ноль здесь значило бы
    сузить поверхность молча.
    """
    tree_root = tree_root.resolve()
    good: set[str] = set()
    bad: set[str] = set()
    for node in nodes:
        rel = node.split("::", 1)[0]
        parts = Path(rel).parts
        for cut in range(len(parts)):
            candidate = Path(*parts[cut:]).as_posix()
            if (tree_root / candidate).is_file():
                good.add(candidate)
                break
        else:
            bad.add(rel)
    return sorted(good), sorted(bad)


# --------------------------------------------------------------------------- #
# Прогон
# --------------------------------------------------------------------------- #
def parse_outcomes(stdout: str) -> dict[str, str]:
    """Вердикт на nodeid из ``-v`` вывода pytest. ``SKIPPED`` различается намеренно.

    Урок #465: в дифференциальном замере тест, ушедший в ``skipped``, не краснеет и не
    проходит — он ИСЧЕЗАЕТ, и глазами это читается как «всё в порядке».
    """
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "::" in parts[0]:
            verdict = parts[1].rstrip(",")
            if verdict in _VERDICTS:
                out[parts[0]] = verdict
    return out


def run_pytest(tree_root: Path, tracker: Path, files: list[str], *,
               timeout_s: int, label: str, env_extra: dict | None = None,
               plugin: str | None = None) -> tuple[dict[str, str], str, int]:
    """Один прогон поверхности в УКАЗАННОМ дереве против УКАЗАННОЙ очереди.

    ``-q`` здесь НЕТ намеренно: он погасил бы ``-v``, вердикты по ``nodeid`` в вывод не
    попали бы вовсе, и пустой разбор был бы прочитан как «вердиктов нет».
    Прогресс печатается в ``stderr`` без буфера — долгий прогон обязан быть ВИДЕН
    (`.claude/rules/deployment.md`, § окна мутационного прибора, п. 8).
    """
    # Корень РЕЗОЛВИТСЯ, а не берётся как дан: ``$TMPDIR`` на macOS есть симлинк
    # (``/var/folders`` → ``/private/var/folders``), и нерезолвленный ``--rootdir``
    # уводил nodeid в ``../../../..`` — то есть ИМЯ файла теста становилось пустым,
    # а поверхность «измеренная прогоном» молча пустела.
    tree_root = tree_root.resolve()
    env = dict(os.environ)
    env["SPA_ENV"] = "ci"
    env["PYTHONHASHSEED"] = "0"
    # Маркер ПЕСОЧНИЦЫ C8(b): ребёнок идёт против ОДНОРАЗОВОГО дерева, и читатель без
    # своего `data_dir` иначе молча уводит чтение в ПРОД через `live_paths`.
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = str(tree_root)
    env["SPA_DATA_DIR"] = str(tree_root / "data")
    # Шов очереди уводится на дерево сцены ВО ВСЕХ прогонах, включая базовый: иначе
    # дверь `live_tracker_dir` невидима по построению (см. докстринг модуля).
    env["SPA_TRACKER_DIR"] = str(tracker)
    env.update(env_extra or {})
    # ``--rootdir`` ОБЪЯВЛЕН, а не угадан: nodeid считается от rootdir, а терминальный
    # отчёт — от каталога вызова, и у одноразового дерева в ``$TMPDIR`` эти два ответа
    # РАСХОДЯТСЯ (``tmpXXXX/tree/t_dep.py::…`` против ``t_dep.py::…``). Без объявления
    # прибор сверял бы ДВА РАЗНЫХ имени одного теста и честно находил бы ноль
    # (та же дверь, что у `live_registry_scene`: дочерний pytest без ``--rootdir``).
    argv = [sys.executable, "-u", "-m", "pytest", "-v", "-p", "no:randomly",
            "--rootdir", str(tree_root), *files]
    if plugin:
        argv[5:5] = ["-p", plugin]
    print(f"[прибор] сцена {label}: файлов {len(files)}", file=sys.stderr, flush=True)
    proc = subprocess.run(argv, cwd=str(tree_root), env=env, capture_output=True,
                          text=True, timeout=timeout_s)
    outcomes = parse_outcomes(proc.stdout)
    print(f"[прибор] сцена {label} завершена: код {proc.returncode}, "
          f"вердиктов {len(outcomes)}", file=sys.stderr, flush=True)
    return outcomes, proc.stdout[-4000:], proc.returncode


def _live_tracker_candidates() -> list[Path]:
    """Пути очереди, которые считаются ЖИВЫМИ и потому неприкосновенными."""
    from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT  # локально: только здесь

    out = [Path(DEFAULT_LIVE_ROOT).joinpath(*TRACKER_REL)]
    env = os.environ.get("SPA_LIVE_ROOT")
    if env:
        out.append(Path(env).joinpath(*TRACKER_REL))
    return out


def refuse_if_live(tracker: Path) -> str | None:
    """Отказ, если сцена собиралась бы править ЖИВУЮ очередь. Причина — строкой."""
    try:
        real = tracker.resolve()
    except OSError as exc:  # pragma: no cover — нечитаемый путь
        return f"путь очереди не резолвится: {exc}"
    for live in _live_tracker_candidates():
        try:
            if real == live.resolve():
                return (f"очередь сцены совпадает с ЖИВОЙ ({real}) — прибор правит "
                        f"содержимое и живое дерево трогать не вправе")
        except OSError:
            continue
    return None


#: Сколько путей печатать в отказе о грязном дереве. Перечень обязан НАЗЫВАТЬ
#: виновника, а не только его число: «дерево грязное» без имени не чинится.
DIRTY_PATHS_SHOWN = 10


def refuse_if_dirty(tree_root: Path, *, runner=None) -> str | None:
    """Отказ, если дерево замера НЕ СОВПАДАЕТ со своей вершиной. Причина — строкой.

    **Зачем это отдельная дверь (замер цикла #1021).** Предмет этого прибора —
    вердикт как свойство СОДЕРЖИМОГО дерева. Значит, содержимое дерева, в котором
    идёт замер, есть ВХОД прибора, а не его обстановка: незакоммиченная правка
    мерящей сессии попадает в БАЗОВУЮ сцену и меняет СОСТАВ класса.

    Это не рассуждение, а измеренный случай. Сироты циклов #1019/#1020 мерили класс
    в дереве, где лежала их собственная правка карточки
    (`status: new` → `in-progress`), и их замер назвал членом класса
    `test_tracker_board_matches_cards::test_live_board_matches_live_cards` с
    направлением ``FAILED→PASSED``: тест был красен ОТ ИХ ПРАВКИ (доска говорит
    `new`, карточка — `in-progress`), а на пустой очереди краснеть переставал.
    Замер #1018 того же класса этого имени не назвал вовсе. Иначе говоря, два
    «воспроизведённых» замера расходились составом по причине, не имеющей
    отношения ни к коду, ни к `origin/main`.

    Поэтому: грязное дерево ⇒ **НЕ ИЗМЕРЕНО** с НАЗВАННЫМИ путями, а не ответ о
    классе. Невозможность спросить git — тот же третий исход, а не разрешение
    (инв. #17): «git не ответил» и «дерево чисто» суть разные утверждения.

    Осознанный обход — ``--allow-dirty-tree``, и он ПЕЧАТАЕТСЯ: мерить класс на
    заведомо правленом дереве бывает нужно (сторона «ПОСЛЕ» у ещё не доставленной
    правки — ровно так мерили #1017/#1018), но тогда это объявленный вход замера, а
    не его молчаливое свойство.

    ``runner`` инъектируется контролем: вопрос к git есть дверь к ОКРУЖЕНИЮ, и
    контроль, спрашивающий настоящий git, мерил бы состояние машины, а не проводку.
    """
    if runner is None:
        def runner(cmd: list[str]):  # noqa: ANN202 — локальная дверь к подпроцессу
            return subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    # `core.quotepath=false` — чтобы НЕРУССКИЙ путь не приехал восьмеричными
    # escape-последовательностями: отказ обязан НАЗЫВАТЬ виновника читаемо.
    cmd = ["git", "-C", str(tree_root), "-c", "core.quotepath=false",
           "status", "--porcelain"]
    try:
        proc = runner(cmd)
    except Exception as exc:  # noqa: BLE001 — третий исход, а не разрешение
        return (f"НЕ ИЗМЕРЕНО: не удалось спросить git о чистоте дерева {tree_root}: "
                f"{type(exc).__name__}: {exc}")
    if proc.returncode != 0:
        return (f"НЕ ИЗМЕРЕНО: git ответил кодом {proc.returncode} о чистоте дерева "
                f"{tree_root}: {(proc.stderr or '').strip()[:300]}")
    dirty = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if dirty:
        shown = ", ".join(ln.strip() for ln in dirty[:DIRTY_PATHS_SHOWN])
        more = f" … ещё {len(dirty) - DIRTY_PATHS_SHOWN}" if len(dirty) > DIRTY_PATHS_SHOWN else ""
        return (f"дерево замера НЕ ЧИСТО ({len(dirty)} путь(ей)): {shown}{more}. "
                f"Содержимое дерева есть ВХОД этого прибора: правка мерящей сессии "
                f"попадает в базовую сцену и меняет СОСТАВ класса (замер #1021). "
                f"Осознанно мерить правленое дерево — `--allow-dirty-tree`")
    return None


def differential(tree_root: Path, files: list[str], *, timeout_s: int,
                 scenes: tuple[str, ...] = SCENES,
                 allow_dirty: bool = False) -> dict:
    """База → сцены содержимого → перемер базы. Смена вердикта = КАНДИДАТ класса."""
    tree_root = tree_root.resolve()
    tracker = tree_root.joinpath(*TRACKER_REL)
    if not tracker.is_dir():
        return {"verdict": "unmeasured",
                "reason": f"в дереве нет очереди: {tracker}"}
    refusal = refuse_if_live(tracker)
    if refusal:
        return {"verdict": "unmeasured", "reason": refusal}
    if not allow_dirty:
        dirty = refuse_if_dirty(tree_root)
        if dirty:
            return {"verdict": "unmeasured", "reason": dirty}
    if not files:
        return {"verdict": "unmeasured", "reason": "поверхность пуста — мерить нечего"}

    workdir = Path(tempfile.mkdtemp(prefix="tracker_content_door_"))
    backup = workdir / "tracker_backup"
    try:
        shutil.copytree(tracker, backup)
        before = fingerprint(tracker)

        # Ступень 1: ПОВЕРХНОСТЬ ПРОГОНОМ. Сужает поверхность AST до тех, кто очередь
        # действительно читает; без неё сцены гоняли бы сотню файлов по полчаса каждый,
        # и цена замера была бы его единственным результатом.
        obs = observe(tree_root, tracker, files, timeout_s=timeout_s, workdir=workdir)
        if obs["verdict"] == "unmeasured":
            return {"verdict": "unmeasured", "reason": obs["reason"],
                    "observe": obs}
        if obs["files_unresolved"]:
            return {"verdict": "unmeasured", "observe": obs,
                    "reason": ("крюк назвал файлы, которых в дереве нет: "
                               + ", ".join(obs["files_unresolved"]))}
        subset = obs["files_touching_scene"]
        if not subset:
            return {"verdict": "measured", "class_empty": True, "candidates": [],
                    "observe": obs, "subset": [],
                    "reason": "ни один тест поверхности не коснулся очереди в прогоне"}

        base, base_tail, base_code = run_pytest(tree_root, tracker, subset,
                                                timeout_s=timeout_s, label=SCENE_BASE)
        if not base:
            return {"verdict": "unmeasured",
                    "reason": "базовый прогон не дал ни одного вердикта по nodeid",
                    "tail": base_tail, "returncode": base_code, "observe": obs}
        files = subset

        changed: dict[str, dict] = {}
        scene_report: list[dict] = []
        for scene in scenes:
            touched = apply_scene(tracker, scene)
            got, tail, code = run_pytest(tree_root, tracker, files,
                                         timeout_s=timeout_s, label=scene)
            _restore(tracker, backup)
            after = fingerprint(tracker)
            if after != before:
                return {"verdict": "unmeasured",
                        "reason": (f"после сцены «{scene}» содержимое очереди не вернулось "
                                   f"ПОБАЙТНО ({before[:12]} против {after[:12]})")}
            diff = {node: {"base": base[node], scene: got.get(node, "ОТСУТСТВУЕТ")}
                    for node in base
                    if got.get(node, "ОТСУТСТВУЕТ") != base[node]}
            appeared = sorted(set(got) - set(base))
            scene_report.append({"scene": scene, "cards_touched": touched,
                                 "returncode": code, "verdicts": len(got),
                                 "changed": len(diff), "appeared": appeared,
                                 "tail": tail if diff or code != base_code else ""})
            for node, pair in diff.items():
                changed.setdefault(node, {"base": base[node], "scenes": {}})
                changed[node]["scenes"][scene] = pair[scene]

        if not changed:
            return {"verdict": "measured", "class_empty": True, "candidates": [],
                    "base_verdicts": len(base), "scenes": scene_report,
                    "observe": obs, "subset": subset}

        # Перемер ШУМА: вердикт кандидата обязан ВЕРНУТЬСЯ на базовом содержимом.
        recheck, recheck_tail, _ = run_pytest(tree_root, tracker, files,
                                              timeout_s=timeout_s,
                                              label=f"{SCENE_BASE}-перемер")
        candidates: list[dict] = []
        noisy: list[dict] = []
        for node, rec in sorted(changed.items()):
            again = recheck.get(node, "ОТСУТСТВУЕТ")
            row = {"nodeid": node, "base": rec["base"], "scenes": rec["scenes"],
                   "base_again": again}
            (candidates if again == rec["base"] else noisy).append(row)
        return {"verdict": "measured", "class_empty": not candidates,
                "candidates": candidates, "noisy": noisy,
                "base_verdicts": len(base), "scenes": scene_report,
                "observe": obs, "subset": subset,
                "recheck_tail": "" if not noisy else recheck_tail}
    finally:
        try:
            _restore(tracker, backup)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _restore(tracker: Path, backup: Path) -> None:
    if not backup.is_dir():
        return
    shutil.rmtree(tracker, ignore_errors=True)
    shutil.copytree(backup, tracker)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_surface(res: dict) -> None:
    c = res["counts"]
    print(f"поверхность класса «вердикт есть свойство СОДЕРЖИМОГО дерева» "
          f"(корни {', '.join(res['roots'])}):")
    print(f"  файлов на поверхности: {c['on_surface']}")
    print(f"    дверь своего дерева ({DOOR_TREE_LITERAL}): {c['tree_literal']}")
    print(f"    дверь ЖИВОГО дерева ({DOOR_LIVE_TRACKER_DIR}): {c['live_tracker_dir']}")
    print(f"  ось «шов в файле встречается» (НЕ освобождение): {c['seam_present']}")
    print(f"  НЕ ИЗМЕРЕНО файлов: {c['unmeasured']}")
    if res["missing_roots"]:
        print(f"  НЕ ИЗМЕРЕНО корней (нет в дереве): {', '.join(res['missing_roots'])}")
    for f in res["files"]:
        if f["unmeasured"]:
            print(f"  [НЕ ИЗМЕРЕНО] {f['path']}: {f['unmeasured']}")
        else:
            print(f"  [{'+'.join(f['doors'])}{', шов' if f['seam_present'] else ''}] "
                  f"{f['path']}")


def _print_observe(obs: dict) -> None:
    if obs["verdict"] == "unmeasured":
        print(f"НЕ ИЗМЕРЕНО (наблюдение): {obs['reason']}")
        return
    print("поверхность, ИЗМЕРЕННАЯ ПРОГОНОМ (слуховой крюк):")
    print(f"  вердиктов в наблюдающем прогоне: {len(obs['outcomes'])}")
    print(f"  коснулись очереди СЦЕНЫ: тестов {len(obs['nodes_touching_scene'])}, "
          f"файлов {len(obs['files_touching_scene'])}")
    for rel in obs.get("files_unresolved", []):
        print(f"  [НЕ ИЗМЕРЕНО] крюк назвал файл, которого в дереве нет: {rel}")
    print(f"  коснулись очереди ЖИВОГО дерева (сквозь шов): "
          f"{len(obs['nodes_touching_live'])}")
    for node in obs["nodes_touching_live"]:
        print(f"    [ДОТЯНУЛСЯ ДО ПРОДА] {node}")
    if obs["import_time_touch"]:
        print(f"  касания ВНЕ теста (сбор/импорт): {len(obs['import_time_touch'])} — "
              f"{', '.join(obs['import_time_touch'])}")
    for f in obs["files_touching_scene"]:
        print(f"  [ЧИТАЕТ ОЧЕРЕДЬ] {f}")


def _print_differential(res: dict) -> None:
    if res["verdict"] == "unmeasured":
        print(f"НЕ ИЗМЕРЕНО: {res['reason']}")
        if res.get("observe"):
            _print_observe(res["observe"])
        return
    if res.get("observe"):
        _print_observe(res["observe"])
        print()
    print(f"дифференциальный замер по подмножеству ({len(res.get('subset', []))} "
          f"файл(ов)): вердиктов на базе {res.get('base_verdicts', 0)}")
    for s in res.get("scenes", []):
        print(f"  сцена {s['scene']}: тронуто карточек {s['cards_touched']}, "
              f"вердиктов {s['verdicts']}, сменили вердикт {s['changed']}, "
              f"код {s['returncode']}")
    for row in res.get("noisy", []):
        print(f"  [НЕ ИЗМЕРЕНО, шум] {row['nodeid']}: база {row['base']} → "
              f"{row['scenes']} → перемер базы {row['base_again']}")
    if res["class_empty"]:
        print("класс ПУСТ по этой оси: ни один вердикт не изменился от содержимого очереди")
        return
    print(f"КЛАСС НЕ ПУСТ: {len(res['candidates'])} предмет(ов)")
    for row in res["candidates"]:
        scenes = ", ".join(f"{k}={v}" for k, v in sorted(row["scenes"].items()))
        print(f"  [ПРЕДМЕТ] {row['nodeid']}: база {row['base']} → {scenes}")



# --------------------------------------------------------------------------- #
# Объявление класса: проекция ЗАМЕРА, а не список из головы
# --------------------------------------------------------------------------- #
def declaration_from_measurement(doc: dict, *, sha: str, minutes_per_side: int,
                                 instrument: str) -> dict:
    """ЗАМЕР (`--differential --json`) → документ объявления класса (ADR-907).

    Зачем это код, а не руки. ADR-905 опубликовал СЧЁТЧИКИ и не опубликовал ИМЕНА,
    поэтому сторону «ДО» нельзя было взять иначе как повторным прогоном, и цикл
    #1018 заплатил ~1 ч 25 мин ДВАЖДЫ. Объявление, набранное руками, вернуло бы
    ту же беду с другой стороны: имя без замера неотличимо от имени из головы, а
    сторож объявления по построению не умеет перемерять класс. Поэтому писатель
    один, и он ЗАПОЛНЯЕТ поле ``measured_in`` сам — из того же документа, из
    которого берёт имя.

    Отказывает (``ValueError``) на всём, что сделало бы объявление ложным:

    * замер не состоялся (``verdict != "measured"``) — объявлять нечего;
    * в замере есть ШУМ: имя, чей вердикт не вернулся на перемере базы, членом
      класса не является, и тихо выбросить его значило бы объявить замер чище,
      чем он есть;
    * класс ПУСТ — «пустое объявление» и «класс пуст» суть разные утверждения
      (второе доказывается прибором и записывается решением, а не пустым файлом);
    * не названы sha дерева замера, цена стороны или прибор — ровно те три поля,
      незнание которых и стои́ло #1018 второго прогона.

    Дверь к очереди берётся из ПОВЕРХНОСТИ того же замера: она отвечает на вопрос
    «чьё содержимое переворачивает вердикт» — своего дерева (``tree_literal``) или
    дерева, которого прогон даже не видит (``live_tracker_dir``).
    """
    if doc.get("verdict") != "measured":
        raise ValueError(
            f"НЕ ИЗМЕРЕНО: замер не состоялся (verdict={doc.get('verdict')!r}) — "
            f"объявлять нечего: {doc.get('reason')}")
    noisy = doc.get("noisy") or []
    if noisy:
        raise ValueError(
            "НЕ ИЗМЕРЕНО: в замере ШУМ — вердикт не вернулся на перемере базы у "
            f"{len(noisy)} имён ({', '.join(sorted(r.get('nodeid', '?') for r in noisy))}); "
            "шумное имя членом класса не является, и выбросить его молча нельзя")
    candidates = doc.get("candidates") or []
    if not candidates:
        raise ValueError(
            "НЕ ИЗМЕРЕНО: класс ПУСТ по этому замеру — «класс пуст» записывается "
            "решением, а не пустым файлом объявления")
    if not sha:
        raise ValueError("НЕ ИЗМЕРЕНО: не названа sha дерева замера")
    if not minutes_per_side:
        raise ValueError("НЕ ИЗМЕРЕНО: не названа цена стороны замера в минутах")
    if not instrument:
        raise ValueError("НЕ ИЗМЕРЕНО: не назван прибор")

    doors: dict[str, list[str]] = {}
    for f in (doc.get("surface") or {}).get("files", []):
        doors[f.get("path", "")] = f.get("doors") or []

    members = []
    for row in sorted(candidates, key=lambda r: r["nodeid"]):
        nodeid = row["nodeid"]
        rel = nodeid.split("::", 1)[0]
        member_doors = doors.get(rel) or []
        members.append({
            "nodeid": nodeid,
            "base": row["base"],
            "scenes": dict(sorted(row["scenes"].items())),
            # Дверь — свойство ФАЙЛА, поэтому их может быть и две; пустой список
            # значил бы «поверхность о файле молчит», и это не то же, что «двери нет».
            "door": ", ".join(sorted(member_doors)) or "НЕ ИЗМЕРЕНО: поверхность о файле молчит",
            "measured_in": (f"{instrument} на {sha}: база {doc.get('base_verdicts')} "
                            f"вердиктов, сцены "
                            + ", ".join(f"{s['scene']}={s['changed']}"
                                        for s in doc.get("scenes", []))
                            + f", шум {len(noisy)}"),
        })

    return {
        "schema": DECLARATION_SCHEMA,
        "upper_bound": len(members),
        "instrument": instrument,
        "wall_clock_minutes_per_side": int(minutes_per_side),
        "measured_on_sha": sha,
        "members": members,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", action="store_true",
                    help="разбор AST: поверхность класса (умолчание)")
    ap.add_argument("--observe", action="store_true",
                    help="поверхность ПРОГОНОМ: кто действительно читает очередь")
    ap.add_argument("--differential", action="store_true",
                    help="замер класса: прогон поверхности по сценам содержимого")
    ap.add_argument("--run-root", default=None,
                    help="ОДНОРАЗОВОЕ дерево для дифференциального прогона "
                         "(обязательно; живое дерево прибор трогать отказывается)")
    ap.add_argument("--roots", default=None,
                    help="через запятую: каталоги поверхности (умолчание — канон)")
    ap.add_argument("--timeout", type=int, default=3600, help="предел одного прогона, с")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--emit-declaration", default=None, metavar="ЗАМЕР.json",
                    help="превратить вывод `--differential --json` в файл объявления "
                         "класса (ADR-907); требует --measured-on-sha и "
                         "--minutes-per-side")
    ap.add_argument("--measured-on-sha", default=None,
                    help="sha дерева, на котором снят замер (часть объявления)")
    ap.add_argument("--minutes-per-side", type=int, default=None,
                    help="цена ОДНОЙ стороны замера в минутах (часть объявления)")
    ap.add_argument("--out", default=None,
                    help="куда писать объявление (умолчание — stdout)")
    ap.add_argument("--allow-dirty-tree", action="store_true",
                    help="осознанно мерить ПРАВЛЕНОЕ дерево (сторона «ПОСЛЕ» ещё не "
                         "доставленной правки); обход ПЕЧАТАЕТСЯ")
    args = ap.parse_args(argv)

    roots = tuple(r.strip() for r in args.roots.split(",")) if args.roots else CANON_ROOTS

    if args.emit_declaration:
        measurement = Path(args.emit_declaration)
        try:
            raw = measurement.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"НЕ ИЗМЕРЕНО: замер не прочитан: {measurement}: {exc}", file=sys.stderr)
            return 2
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"НЕ ИЗМЕРЕНО: замер не разбирается: {measurement}: {exc}",
                  file=sys.stderr)
            return 2
        try:
            decl = declaration_from_measurement(
                doc, sha=args.measured_on_sha or "",
                minutes_per_side=args.minutes_per_side or 0,
                instrument="python3 -m spa_core.tests._tracker_content_door --differential")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        text = json.dumps(decl, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"объявление записано: {args.out} — членов {len(decl['members'])}, "
                  f"граница {decl['upper_bound']}, sha {decl['measured_on_sha']}")
        else:
            print(text, end="")
        return 0

    if args.observe and not args.differential:
        if not args.run_root:
            print("НЕ ИЗМЕРЕНО: --observe требует --run-root (одноразовое дерево)",
                  file=sys.stderr)
            return 2
        tree = Path(args.run_root).resolve()
        if not tree.is_dir():
            print(f"НЕ ИЗМЕРЕНО: дерева нет: {tree}", file=sys.stderr)
            return 2
        tracker = tree.joinpath(*TRACKER_REL)
        refusal = refuse_if_live(tracker)
        if refusal:
            print(f"НЕ ИЗМЕРЕНО: {refusal}", file=sys.stderr)
            return 2
        surface = measure_surface(tree, roots)
        files = [f["path"] for f in surface["files"] if f["doors"]]
        workdir = Path(tempfile.mkdtemp(prefix="tracker_content_observe_"))
        try:
            obs = observe(tree, tracker, files, timeout_s=args.timeout, workdir=workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        obs["surface"] = surface
        if args.json:
            print(json.dumps(obs, ensure_ascii=False, indent=2))
        else:
            _print_surface(surface)
            print()
            _print_observe(obs)
        if obs["verdict"] == "unmeasured":
            return 2
        return 0 if not obs["files_touching_scene"] else 1

    if args.differential:
        if not args.run_root:
            print("НЕ ИЗМЕРЕНО: --differential требует --run-root (одноразовое дерево)",
                  file=sys.stderr)
            return 2
        tree = Path(args.run_root).resolve()
        if not tree.is_dir():
            print(f"НЕ ИЗМЕРЕНО: дерева нет: {tree}", file=sys.stderr)
            return 2
        if args.allow_dirty_tree:
            print("ОБХОД: --allow-dirty-tree — дерево замера может быть правленым, "
                  "и его содержимое объявлено ВХОДОМ замера", file=sys.stderr)
        surface = measure_surface(tree, roots)
        files = [f["path"] for f in surface["files"] if f["doors"]]
        res = differential(tree, files, timeout_s=args.timeout,
                           allow_dirty=args.allow_dirty_tree)
        res["surface"] = surface
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            _print_surface(surface)
            print()
            _print_differential(res)
        if res["verdict"] == "unmeasured":
            return 2
        return 0 if res["class_empty"] else 1

    res = measure_surface(REPO_ROOT, roots)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_surface(res)
    if res["counts"]["unmeasured"] or res["missing_roots"]:
        return 2
    return 0 if res["counts"]["on_surface"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
