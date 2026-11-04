"""Прибор класса «ЛИТЕРАЛ СОСЕДА в тесте ЖИВОГО замера» — заказ G907 п. 2.

**Предмет.** Шаг переписи (`spa_core/monitoring/rule_second_copy_census.py`,
ряд `UNMEASURED_*_POPULATION`) сверяет население, ОБЪЯВЛЕННОЕ соседом, со
СВОИМ обходом дерева и при расхождении отказывает fail-CLOSED. Это верное
поведение. Тест, подающий такому шагу соседа ЛИТЕРАЛОМ и ЖИВОЙ корень дерева,
держит снимок населения на день своего написания — и краснеет, когда дерево
дорастает до другого числа. Причина в РОСТЕ ДЕРЕВА, а не в коде.

Замер #1029 (ADR-916): так покраснели ЧЕТЫРЕ имени
``test_document_field_reader.py`` в ТРЁХ разных формах (``AssertionError``
«47 против 26», затем ``KeyError: 'resolved_by_document_step'`` и
``KeyError: 'blind'`` — у отказавшего шага этих ключей нет ВОВСЕ), а пятое имя
того же файла было **ЗЕЛЁНО** на том же отказе, читая поле из ШАПКИ. Это
родня литеральной даты (`.claude/rules/deployment.md`, § «Время в тестах»),
литерального pid (§ «Личность процесса») и счётного потолка (ADR-912): число
живёт в тесте и ни с чем не сверяется, поэтому устаревает МОЛЧА.

**Почему «красен сегодня» мерой класса НЕ ЯВЛЯЕТСЯ** (дословно ADR-897):
литерал, ещё не отъехавший от населения дерева, зелен — и остаётся бомбой.
Поэтому прибор меряет ДИФФЕРЕНЦИАЛЬНО.

**Две сцены, и разница между ними — РОСТ ДЕРЕВА.**

* ``base``  — дерево как есть;
* ``grown`` — в дерево добавлен ОДИН файл со сценой открытого счётчика
  (:data:`SCENE_SOURCE`), который первый шаг цепочки считает ещё одним
  счётчиком, и который уезжает полем, никем не прочитанным, — то есть
  проходит воронку шагов как «неразрешённый».

**Почему перебирается ДЕРЕВО, а не ОБЪЯВЛЕНИЕ соседа.** Сдвиг объявления
ломает и литерал, и паритет: тест, собирающий соседа у ПРОИЗВОДИТЕЛЯ
(лечение ADR-916), краснел бы наравне с бомбой, и прибор мерил бы «зависит
ли вердикт от равенства двух чисел» вместо «устаревает ли число молча». Рост
дерева разделяет их по построению: паритетный тест пересчитывает объявление
тем же обходом и остаётся зелёным, литеральный — краснеет. Это ровно та
авария, которая случилась в #1029, воспроизведённая на один шаг вперёд.

**Канарейка прозрачности сцены — ДО сцен** (урок ADR-898: прибор, возмущающий
не то, что собирался, отвечает о СЕБЕ). Прибор сам зовёт первый шаг цепочки на
обоих деревьях и требует, чтобы население РАЗОШЛОСЬ. Не разошлось ⇒ ответа о
классе НЕ ВЫДАЁТСЯ (``unmeasured``), а кандидаты печатаются как кандидаты.

**Три исхода различимы** (инв. #17): член класса · не член · НЕ ИЗМЕРЕН с
названной причиной. Файл, который не прочитан или не разобран, членом не
является и «чистым» не считается.

**Мерить и переход в ``skipped``** (урок #465): в дифференциальном замере
такой тест не краснеет и не проходит — он ИСЧЕЗАЕТ, и глазами это читается
как «всё в порядке».

Прибор только ЧИТАЕТ дерево замера и НИЧЕГО не чинит. Сцену он пишет в
УКАЗАННОЕ одноразовое дерево и снимает её за собой; дерево доставки под
прибор не отдаётся (`.claude/rules/deployment.md`, § «Байты, которые не
являются кодом», п. 1).

Команды::

    python3 -m spa_core.tests._literal_neighbour_door --surface
    python3 -m spa_core.tests._literal_neighbour_door --canary --tree-root <дерево>
    python3 -m spa_core.tests._literal_neighbour_door --differential --tree-root <дерево>

Коды возврата: 0 — измерено · 1 — найдены члены класса · 2 — НЕ ИЗМЕРЕНО
с названной причиной.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Объявления
# --------------------------------------------------------------------------- #

#: Каталог, в котором ищется поверхность. ``glob``, не ``rglob`` — тот же
#: охват, каким мерят себя храповики набора (замер охвата, не выбор прибора).
CANON_TEST_DIR = "spa_core/tests"

#: Ключ и значение, которыми сосед объявляет себя ИЗМЕРЕННЫМ.
NEIGHBOUR_STATUS_KEY = "status"
NEIGHBOUR_MEASURED = "MEASURED"

#: Куда прибор кладёт сцену роста. Каталог — один из обходимых переписью
#: (``OPEN_COUNTER_DIRS``); имя говорит, что это сцена прибора.
GROWN_REL = "spa_core/monitoring/_literal_neighbour_grown_scene.py"

#: Сцена роста: ОДИН открытый счётчик класса, которого никто не объявлял,
#: уехавший полем документа, и зовущий, который этого поля НЕ ЧИТАЕТ.
#: Форма дословно та, которую ищет ``_counter_target_key`` (``form_get``).
SCENE_SOURCE = '''"""Сцена прибора `_literal_neighbour_door` — РОСТ ДЕРЕВА на один счётчик.

Файл существует только внутри дифференциального замера и снимается за ним.
Ни один рантайм его не импортирует; он здесь ради того, чтобы перепись
нашла на один открытый счётчик больше.
"""

from __future__ import annotations


def writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"grown_scene_counts": counts}


def caller(rows):
    doc = writer(rows)
    return len(doc)
'''

#: Куда прибор кладёт БОМБУ положительного контроля.
BOMB_REL = "spa_core/tests/test_literal_neighbour_positive_control.py"

#: Бомба: литерал населения, снятый у ПРОИЗВОДИТЕЛЯ на БАЗОВОМ дереве и
#: вписанный в тест числом. На базовом дереве она зелена, на выросшем обязана
#: покраснеть — иначе «членов 0» есть свойство ПРИБОРА, а не набора.
BOMB_SOURCE = '''"""Положительный контроль прибора `_literal_neighbour_door` — БОМБА.

Файл существует только внутри прогона контроля и снимается за ним. Литерал
{declared} снят у производителя на БАЗОВОМ дереве: это ровно та форма, которой
покраснели четыре имени `test_document_field_reader.py` в цикле #1029.
"""

from pathlib import Path

from spa_core.monitoring.rule_second_copy_census import (
    STEP_GAP_CONTAINER, container_counter_field_step)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_bomb_is_green_until_the_tree_grows():
    out = container_counter_field_step(
        REPO_ROOT, {{"status": "MEASURED",
                    "unresolved_reasons": {{STEP_GAP_CONTAINER: {declared}}}}})
    assert out["status"] == "MEASURED", out.get("reason")
'''

#: Двери поверхности.
DOOR_LITERAL_LIVE = "literal_neighbour_on_a_live_root"
DOOR_LITERAL_SCENE = "literal_neighbour_on_its_own_scene"
DOOR_PRODUCER = "neighbour_from_the_producer"

#: Вердикты pytest, которые прибор различает. ``SKIPPED`` — намеренно.
_VERDICTS = ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS")

#: Первый шаг цепочки — им же меряется канарейка.
CANARY_STEP = "open_class_counter_census"


# --------------------------------------------------------------------------- #
# Поверхность: разбор AST
# --------------------------------------------------------------------------- #

@dataclass
class FileSurface:
    """Один тест-файл поверхности."""

    path: str
    doors: list[str] = field(default_factory=list)
    sites: list[dict] = field(default_factory=list)
    unmeasured: Optional[str] = None

    def as_dict(self) -> dict:
        out: dict = {"file": self.path}
        if self.unmeasured:
            out["unmeasured"] = self.unmeasured
            return out
        out["doors"] = list(self.doors)
        out["sites"] = list(self.sites)
        return out


def _src(node: ast.AST) -> str:
    """Исходник узла — через ``ast.unparse``; не вышло ⇒ пустая строка.

    Пустая строка НЕ совпадает ни с одним признаком ниже: «не разобрали» не
    имеет права совпасть с «признака нет» (инв. #17), и поэтому признаки
    спрашиваются у узла, а не у строки, везде, где это возможно.
    """
    try:
        return ast.unparse(node)
    except Exception:                                    # pragma: no cover
        return ""


def _is_live_root_expr(node: ast.AST) -> bool:
    """Выражение, дающее корень ЖИВОГО дерева: ``Path(__file__)…parents[N]``."""
    text = _src(node)
    return "__file__" in text and ("parents" in text or ".parent" in text)


def _targets(node) -> list:
    return (node.targets if isinstance(node, ast.Assign) else [node.target])


def _scope_statements(scope: ast.AST):
    """Узлы ЭТОЙ области видимости, НЕ заходя во вложенные определения.

    Без этой границы имя, связанное с живым корнем в ЧУЖОЙ функции, утекало
    бы на сцены соседки: замер 04.11 — `root = Path(C.__file__)…parents[2]`
    в одной функции и `root = _scene(tmp_path, …)` в трёх других, и прибор
    насчитал бы ТРИ ложные площадки на `tmp_path`. Это ровно тот класс, о
    котором сам прибор и докладывает: признак, спрошенный не у того, о ком
    отвечают.
    """
    stack = list(getattr(scope, "body", []) or [])
    while stack:
        cur = stack.pop()
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            continue
        yield cur
        stack.extend(ast.iter_child_nodes(cur))


def _nested_scopes(scope: ast.AST):
    """Вложенные определения ЭТОЙ области — следующий слой видимости."""
    stack = list(getattr(scope, "body", []) or [])
    while stack:
        cur = stack.pop()
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            yield cur
            continue
        stack.extend(ast.iter_child_nodes(cur))


def live_root_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Имена МОДУЛЬНОЙ области, связанные с живым корнем, и его производители.

    Имена локальных областей здесь НЕ собираются намеренно: их собирает
    :func:`file_surface` по областям видимости (см. `_scope_statements`).
    """
    names: set[str] = set()
    makers: set[str] = set()
    for node in _scope_statements(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None or not _is_live_root_expr(value):
                continue
            for tgt in _targets(node):
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            arity = (len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs))
            if arity:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None \
                        and _is_live_root_expr(sub.value):
                    makers.add(node.name)
                    break
    return names, makers


def _dict_is_measured_neighbour(node: ast.Dict) -> bool:
    """Словарь-литерал, объявляющий себя ИЗМЕРЕННЫМ соседом."""
    for key, value in zip(node.keys, node.values):
        if (isinstance(key, ast.Constant) and key.value == NEIGHBOUR_STATUS_KEY
                and isinstance(value, ast.Constant)
                and value.value == NEIGHBOUR_MEASURED):
            return True
    return False


def _int_literals(node: ast.AST) -> list[int]:
    """Целые ЛИТЕРАЛЫ внутри узла. ``bool`` целым здесь не считается."""
    out: list[int] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, int) \
                and not isinstance(sub.value, bool):
            out.append(int(sub.value))
    return out


@dataclass
class Helper:
    """Локальная функция, возвращающая соседа."""

    name: str
    literal_defaults: list[int]
    literal_in_body: list[int]
    from_producer: bool


def neighbour_helpers(tree: ast.Module) -> dict[str, Helper]:
    """Локальные производители соседа — и чем они его набирают."""
    out: dict[str, Helper] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        measured = False
        literal_in_body: list[int] = []
        from_producer = False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and sub.value is not None:
                if isinstance(sub.value, ast.Dict) and \
                        _dict_is_measured_neighbour(sub.value):
                    measured = True
                    literal_in_body.extend(_int_literals(sub.value))
                elif isinstance(sub.value, ast.Call):
                    callee = _src(sub.value.func)
                    if callee.endswith("_step") or "census" in callee \
                            or callee.endswith("_harm"):
                        from_producer = True
        if not (measured or from_producer):
            continue
        defaults = [d for d in (node.args.defaults or []) if d is not None]
        defaults += [d for d in (node.args.kw_defaults or []) if d is not None]
        literal_defaults: list[int] = []
        for dflt in defaults:
            literal_defaults.extend(_int_literals(dflt))
        out[node.name] = Helper(node.name, literal_defaults, literal_in_body,
                                from_producer)
    return out


def literal_neighbour_names(scope: ast.AST,
                            helpers: dict[str, Helper]) -> dict[str, list[int]]:
    """Имена, которым присвоен сосед-ЛИТЕРАЛ, и числа, которые он объявил.

    Без этого шага прибор видел бы только соседа, НАБРАННОГО В САМОМ ВЫЗОВЕ,
    и файл, где сосед сперва лёг в переменную, остался бы вне поверхности —
    то есть «не спрашивали» читалось бы как «признака нет».
    """
    out: dict[str, list[int]] = {}
    for node in _scope_statements(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        numbers = _neighbour_literal_numbers(value, helpers, names={})
        if not numbers:
            continue
        for tgt in _targets(node):
            if isinstance(tgt, ast.Name):
                out[tgt.id] = list(numbers)
    return out


def scope_live_root_names(scope: ast.AST,
                          makers: Optional[set[str]] = None) -> set[str]:
    """Имена ЭТОЙ области, связанные с живым корнем.

    Корень, добытый ПОМОЩНИКОМ (``root = _repo_root()``), — тот же живой
    корень: спрашивать только про ``__file__`` в правой части значило бы
    считать признаком форму записи, а не предмет.
    """
    out: set[str] = set()
    for node in _scope_statements(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) \
                or node.value is None:
            continue
        value = node.value
        live = _is_live_root_expr(value) or (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and bool(makers) and value.func.id in makers)
        if not live:
            continue
        for tgt in _targets(node):
            if isinstance(tgt, ast.Name):
                out.add(tgt.id)
    return out


def _neighbour_literal_numbers(node: ast.AST,
                               helpers: dict[str, Helper],
                               names: Optional[dict[str, list[int]]] = None,
                               ) -> Optional[list[int]]:
    """Числа, которыми выражение ОБЪЯВЛЯЕТ население соседа, либо ``None``.

    ``None`` значит «это выражение соседа литералом не объявляет» — в том
    числе когда сосед собран у производителя. Пустой список значит «сосед
    есть, числа нет» (например ``{"status": "MEASURED"}``): такой тест
    проверяет ОТКАЗ и литерала населения не несёт.
    """
    if isinstance(node, ast.Name) and names and node.id in names:
        return list(names[node.id])
    if isinstance(node, ast.Dict) and _dict_is_measured_neighbour(node):
        return _int_literals(node)
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        helper = helpers.get(name) if name else None
        if helper is None or helper.from_producer:
            return None
        supplied: list[int] = []
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            supplied.extend(_int_literals(arg))
        if supplied:
            return supplied
        # Вызов без аргументов — население объявляют УМОЛЧАНИЯ помощника.
        return list(helper.literal_defaults) or list(helper.literal_in_body)
    return None


def file_surface(relpath: str, src: str) -> FileSurface:
    """Поверхность одного файла. Не разобрался ⇒ НЕ ИЗМЕРЕН, а не «чист»."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return FileSurface(relpath, unmeasured=f"не разобран: {exc}")
    names, makers = live_root_names(tree)
    helpers = neighbour_helpers(tree)
    sites: list[dict] = []
    doors: set[str] = set()
    if any(h.from_producer for h in helpers.values()):
        doors.add(DOOR_PRODUCER)

    def examine(call: ast.Call, live_names: set[str],
                bound: dict[str, list[int]]) -> None:
        args = list(call.args) + [kw.value for kw in call.keywords]
        if len(args) < 2:
            return
        live = False
        for arg in args:
            if isinstance(arg, ast.Name) and arg.id in live_names:
                live = True
            elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) \
                    and arg.func.id in makers:
                live = True
            elif _is_live_root_expr(arg):
                live = True
        numbers: Optional[list[int]] = None
        for arg in args:
            got = _neighbour_literal_numbers(arg, helpers, names=bound)
            if got is not None:
                numbers = (numbers or []) + got
        # ``None`` — соседа в вызове нет; пустой список — сосед БЕЗ числа,
        # то есть проверка отказа шага, а не снимок населения.
        if not numbers:
            return
        door = DOOR_LITERAL_LIVE if live else DOOR_LITERAL_SCENE
        doors.add(door)
        sites.append({"line": call.lineno, "callee": _src(call.func),
                      "declared": numbers, "door": door})

    def visit(scope: ast.AST, live_names: set[str],
              bound: dict[str, list[int]]) -> None:
        here_live = live_names | scope_live_root_names(scope, makers)
        here_bound = {**bound, **literal_neighbour_names(scope, helpers)}
        for node in _scope_statements(scope):
            if isinstance(node, ast.Call):
                examine(node, here_live, here_bound)
        for nested in _nested_scopes(scope):
            visit(nested, here_live, here_bound)

    visit(tree, names, {})
    return FileSurface(relpath, sorted(doors), sites)


def measure_surface(repo_root: Path, test_dir: str = CANON_TEST_DIR) -> dict:
    """Поверхность: какие тест-файлы кормят шаг ЛИТЕРАЛОМ на ЖИВОМ корне."""
    base = repo_root / test_dir
    if not base.is_dir():
        return {"status": "UNMEASURED",
                "unmeasured_class": "test_dir_absent",
                "reason": f"каталога {test_dir} нет в дереве {repo_root}"}
    files: list[FileSurface] = []
    for path in sorted(base.glob("test_*.py")):
        relpath = path.relative_to(repo_root).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            files.append(FileSurface(relpath, unmeasured=f"не прочитан: {exc}"))
            continue
        surf = file_surface(relpath, src)
        if surf.unmeasured or surf.doors:
            files.append(surf)
    on_live = [f for f in files if DOOR_LITERAL_LIVE in f.doors]
    unmeasured = [f for f in files if f.unmeasured]
    return {
        "status": "MEASURED",
        "repo_root": str(repo_root),
        "test_dir": test_dir,
        "files": [f.as_dict() for f in files],
        "surface_files": [f.path for f in on_live],
        "counts": {
            "on_live_root": len(on_live),
            "scene_only": sum(1 for f in files
                              if DOOR_LITERAL_SCENE in f.doors
                              and DOOR_LITERAL_LIVE not in f.doors),
            "producer_present": sum(1 for f in on_live
                                    if DOOR_PRODUCER in f.doors),
            "sites_on_live_root": sum(len([s for s in f.sites
                                           if s["door"] == DOOR_LITERAL_LIVE])
                                      for f in on_live),
            "unmeasured": len(unmeasured),
        },
    }


# --------------------------------------------------------------------------- #
# Сцена роста
# --------------------------------------------------------------------------- #

def apply_scene(tree_root: Path, scene: str) -> Optional[Path]:
    """Поставить сцену. ``base`` ничего не пишет и возвращает ``None``."""
    if scene == "base":
        return None
    if scene != "grown":
        raise ValueError(f"неизвестная сцена: {scene}")
    target = tree_root / GROWN_REL
    if target.exists():
        raise RuntimeError(f"сцена уже стоит: {target} — второй прогон в том "
                           f"же дереве затёр бы её и снять было бы нечем")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SCENE_SOURCE, encoding="utf-8")
    return target


def drop_scene(tree_root: Path) -> bool:
    """Снять сцену. ``False`` значит «её там не было»."""
    target = tree_root / GROWN_REL
    if not target.exists():
        return False
    target.unlink()
    return True


# --------------------------------------------------------------------------- #
# Канарейка: сцена ОБЯЗАНА сдвинуть население, иначе прибор мерит себя
# --------------------------------------------------------------------------- #

_CANARY_SOURCE = '''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from spa_core.monitoring import rule_second_copy_census as census
out = getattr(census, sys.argv[2])(Path(sys.argv[1]).resolve())
print(json.dumps({"status": out.get("status"),
                  "counters_total": out.get("counters_total"),
                  "open_to_an_unnamed_class": out.get("open_to_an_unnamed_class"),
                  "files_scanned": out.get("files_scanned"),
                  "unmeasured_class": out.get("unmeasured_class"),
                  "reason": out.get("reason")}, ensure_ascii=False))
'''

#: Поле, которым первый шаг объявляет население воронки. Канарейка требует
#: сдвига ИМЕННО его: по нему сверяются соседи дальше по цепочке.
CANARY_FIELD = "open_to_an_unnamed_class"


def _canary_once(tree_root: Path, *, timeout_s: int) -> dict:
    """Один зов первого шага В ОТДЕЛЬНОМ процессе — против дерева сцены."""
    proc = subprocess.run(
        [sys.executable, "-u", "-c", _CANARY_SOURCE, str(tree_root), CANARY_STEP],
        cwd=str(tree_root), capture_output=True, text=True, timeout=timeout_s,
        env={**os.environ, "SPA_ENV": "ci", "PYTHONHASHSEED": "0"})
    if proc.returncode != 0:
        return {"unmeasured": f"шаг не ответил, код {proc.returncode}: "
                              f"{proc.stderr[-400:]}"}
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return {"unmeasured": "шаг не напечатал ничего"}
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError as exc:
        return {"unmeasured": f"ответ шага не разобран: {exc}"}


def canary(tree_root: Path, *, timeout_s: int = 900) -> dict:
    """Прозрачность сцены: население ОБЯЗАНО разойтись между сценами.

    Не разошлось ⇒ прибор возмущает НЕ ТО, что собирался, и о классе молчит.
    """
    tree_root = tree_root.resolve()
    if drop_scene(tree_root):
        pass                      # наследство прошлого прогона снято молча
    base = _canary_once(tree_root, timeout_s=timeout_s)
    if "unmeasured" in base:
        return {"status": "UNMEASURED", "side": "base", **base}
    apply_scene(tree_root, "grown")
    try:
        grown = _canary_once(tree_root, timeout_s=timeout_s)
    finally:
        drop_scene(tree_root)
    if "unmeasured" in grown:
        return {"status": "UNMEASURED", "side": "grown", **grown}
    if base.get("status") != "MEASURED" or grown.get("status") != "MEASURED":
        return {"status": "UNMEASURED", "base": base, "grown": grown,
                "reason": "шаг сам не измерен — сравнивать нечего"}
    before, after = base.get(CANARY_FIELD), grown.get(CANARY_FIELD)
    if not isinstance(before, int) or not isinstance(after, int):
        return {"status": "UNMEASURED", "base": base, "grown": grown,
                "reason": (f"шаг не назвал поле {CANARY_FIELD} числом — "
                           f"сдвиг населения мерить нечем")}
    delta = after - before
    return {"status": "MEASURED" if delta > 0 else "UNMEASURED",
            "field": CANARY_FIELD,
            "base_sites": before, "grown_sites": after,
            "delta": delta,
            "reason": (None if delta > 0 else
                       "сцена НЕ сдвинула население первого шага: прибор "
                       "возмущает не то, что собирался (урок ADR-898)")}


# --------------------------------------------------------------------------- #
# Прогон
# --------------------------------------------------------------------------- #

_DECLARED_SOURCE = '''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from spa_core.monitoring import rule_second_copy_census as census
root = Path(sys.argv[1]).resolve()
step = census.escaped_counter_one_step(
    root, census.open_counter_reader_harm(
        root, census.open_class_counter_census(root)))
print(json.dumps({"status": step.get("status"),
                  "declared": (step.get("unresolved_reasons") or {}).get(
                      census.STEP_GAP_CONTAINER),
                  "unmeasured_class": step.get("unmeasured_class"),
                  "reason": step.get("reason")}, ensure_ascii=False))
'''


def live_declared_population(tree_root: Path, *, timeout_s: int = 900) -> dict:
    """Население шага «уехал полем», снятое у ПРОИЗВОДИТЕЛЯ на этом дереве.

    Это то самое число, которое бомба положительного контроля вписывает в себя
    литералом. Своего обхода прибор для него не держит: сверять паритет с
    собственной выдумкой — дословный дефект ADR-913.
    """
    proc = subprocess.run(
        [sys.executable, "-u", "-c", _DECLARED_SOURCE, str(tree_root)],
        cwd=str(tree_root), capture_output=True, text=True, timeout=timeout_s,
        env={**os.environ, "SPA_ENV": "ci", "PYTHONHASHSEED": "0"})
    if proc.returncode != 0:
        return {"unmeasured": f"цепочка не ответила, код {proc.returncode}: "
                              f"{proc.stderr[-400:]}"}
    lines = (proc.stdout or "").strip().splitlines()
    if not lines:
        return {"unmeasured": "цепочка не напечатала ничего"}
    try:
        out = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {"unmeasured": f"ответ цепочки не разобран: {exc}"}
    if out.get("status") != "MEASURED" or not isinstance(out.get("declared"), int):
        return {"unmeasured": (f"цепочка сама не измерена либо не назвала "
                               f"население числом: {out}")}
    return out


def positive_control(tree_root: Path, *, timeout_s: int = 7200) -> dict:
    """Пайплайн обязан НАХОДИТЬ члена — иначе «членов 0» есть ответ о приборе.

    Бомба собирается с населением СЕГОДНЯШНЕГО базового дерева и прогоняется
    тем же дифференциалом. Она обязана быть ЗЕЛЕНОЙ на базовом дереве и
    КРАСНОЙ на выросшем. Не покраснела ⇒ рост дерева до этого шага НЕ ДОХОДИТ,
    и ответ о классе выдавать нельзя (третий исход, инв. #17).
    """
    tree_root = tree_root.resolve()
    drop_scene(tree_root)
    declared = live_declared_population(tree_root, timeout_s=timeout_s)
    if "unmeasured" in declared:
        return {"status": "UNMEASURED", "reason": declared["unmeasured"]}
    bomb = tree_root / BOMB_REL
    if bomb.exists():
        return {"status": "UNMEASURED",
                "reason": f"бомба уже лежит в дереве: {bomb}"}
    bomb.parent.mkdir(parents=True, exist_ok=True)
    bomb.write_text(BOMB_SOURCE.format(declared=declared["declared"]),
                    encoding="utf-8")
    try:
        res = differential(tree_root, [BOMB_REL], timeout_s=timeout_s)
    finally:
        bomb.unlink(missing_ok=True)
    if res.get("status") != "MEASURED":
        return {"status": "UNMEASURED", "declared": declared["declared"],
                "reason": f"дифференциал бомбы не измерен: {res.get('reason')}"}
    flips = [c for c in res["changed"]
             if c["base"] == "PASSED" and c["grown"] in ("FAILED", "ERROR")]
    return {"status": "MEASURED" if flips else "NOT_SATISFIED",
            "declared": declared["declared"],
            "changed": res["changed"],
            "canary": res.get("canary"),
            "reason": (None if flips else
                       "бомба НЕ покраснела на выросшем дереве: рост до этого "
                       "шага не доходит, и ответ о классе выдавать нельзя")}


def parse_outcomes(stdout: str) -> dict[str, str]:
    """Вердикт на nodeid из ``-v``-вывода. ``SKIPPED`` различается намеренно."""
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "::" in parts[0]:
            verdict = parts[1].rstrip(",")
            if verdict in _VERDICTS:
                out[parts[0]] = verdict
    return out


def run_pytest(tree_root: Path, files: list[str], *, timeout_s: int,
               label: str) -> tuple[dict[str, str], str, int]:
    """Один прогон поверхности в УКАЗАННОМ дереве.

    ``-q`` здесь НЕТ намеренно: он погасил бы ``-v``, вердикты по ``nodeid``
    в вывод не попали бы вовсе, и пустой разбор читался бы как «вердиктов
    нет». ``--rootdir`` ОБЪЯВЛЕН: nodeid считается от него, и без объявления
    прибор сверял бы ДВА РАЗНЫХ имени одного теста (дверь `live_registry_scene`).
    """
    tree_root = tree_root.resolve()
    env = dict(os.environ)
    env["SPA_ENV"] = "ci"
    env["PYTHONHASHSEED"] = "0"
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = str(tree_root)
    env["SPA_DATA_DIR"] = str(tree_root / "data")
    argv = [sys.executable, "-u", "-m", "pytest", "-v", "-p", "no:randomly",
            "--rootdir", str(tree_root), *files]
    print(f"[прибор] сцена {label}: файлов {len(files)}", file=sys.stderr,
          flush=True)
    started = time.time()
    proc = subprocess.run(argv, cwd=str(tree_root), env=env,
                          capture_output=True, text=True, timeout=timeout_s)
    outcomes = parse_outcomes(proc.stdout)
    print(f"[прибор] сцена {label} завершена за {time.time() - started:.0f}с: "
          f"код {proc.returncode}, вердиктов {len(outcomes)}",
          file=sys.stderr, flush=True)
    return outcomes, proc.stdout[-6000:], proc.returncode


def differential(tree_root: Path, files: list[str], *, timeout_s: int,
                 skip_canary: bool = False, runner=None,
                 canary_fn=None) -> dict:
    """Два прогона одной поверхности: дерево как есть и дерево, ВЫРОСШЕЕ на один.

    Член класса — тот, у кого МЕНЯЕТСЯ вердикт. Исчезновение имени и переход
    в ``skipped`` считаются сменой вердикта наравне с покраснением.
    """
    tree_root = tree_root.resolve()
    head = {"tree_root": str(tree_root), "files": list(files),
            "scene": GROWN_REL}
    if not files:
        return {**head, "status": "UNMEASURED",
                "reason": "поверхность пуста — мерить нечего"}
    run = runner or run_pytest
    if not skip_canary:
        can = (canary_fn or canary)(tree_root, timeout_s=timeout_s)
        head["canary"] = can
        if can.get("status") != "MEASURED":
            return {**head, "status": "UNMEASURED",
                    "reason": f"канарейка сцены: {can.get('reason')}"}
    drop_scene(tree_root)
    base, base_tail, base_rc = run(tree_root, files,
                                   timeout_s=timeout_s, label="base")
    apply_scene(tree_root, "grown")
    try:
        grown, grown_tail, grown_rc = run(tree_root, files,
                                          timeout_s=timeout_s, label="grown")
    finally:
        drop_scene(tree_root)
    names = sorted(set(base) | set(grown))
    changed: list[dict] = []
    for name in names:
        before = base.get(name, "ABSENT")
        after = grown.get(name, "ABSENT")
        if before != after:
            changed.append({"nodeid": name, "base": before, "grown": after})
    members = sorted({c["nodeid"].split("::")[0] for c in changed})
    return {
        **head,
        "status": "MEASURED",
        "base": {"verdicts": len(base), "rc": base_rc, "tail": base_tail},
        "grown": {"verdicts": len(grown), "rc": grown_rc, "tail": grown_tail},
        "changed": changed,
        "member_files": members,
        "counts": {"names_seen": len(names), "changed": len(changed),
                   "member_files": len(members),
                   "to_skipped": sum(1 for c in changed
                                     if c["grown"] == "SKIPPED"),
                   "vanished": sum(1 for c in changed
                                   if c["grown"] == "ABSENT")},
    }


# --------------------------------------------------------------------------- #
# Печать
# --------------------------------------------------------------------------- #

def _print_surface(res: dict) -> None:
    if res.get("status") != "MEASURED":
        print(f"❌ НЕ ИЗМЕРЕНО: {res.get('reason')}")
        return
    cnt = res["counts"]
    print(f"поверхность класса «литерал соседа на ЖИВОМ корне» "
          f"({res['test_dir']} в {res['repo_root']}):")
    print(f"  на ЖИВОМ корне: {cnt['on_live_root']} файл(ов), "
          f"площадок {cnt['sites_on_live_root']}")
    print(f"  литерал только на СВОЕЙ сцене (не предмет): {cnt['scene_only']}")
    print(f"  из них несут и ПРОИЗВОДИТЕЛЯ соседа: {cnt['producer_present']}")
    print(f"  НЕ ИЗМЕРЕНО (не прочитан / не разобран): {cnt['unmeasured']}")
    for row in res["files"]:
        if row.get("unmeasured"):
            print(f"  [НЕ ИЗМЕРЕНО] {row['file']}: {row['unmeasured']}")
            continue
        if DOOR_LITERAL_LIVE not in row.get("doors", []):
            continue
        live = [s for s in row["sites"] if s["door"] == DOOR_LITERAL_LIVE]
        mark = "+произв." if DOOR_PRODUCER in row["doors"] else ""
        print(f"  [{len(live):2d} площ.] {row['file']} {mark}")
        for site in live[:6]:
            print(f"        :{site['line']} {site['callee']}"
                  f"({site['declared']})")


def _print_differential(res: dict) -> None:
    if res.get("status") != "MEASURED":
        print(f"❌ КЛАСС НЕ ИЗМЕРЕН: {res.get('reason')}")
        can = res.get("canary") or {}
        if can:
            print(f"   канарейка: {json.dumps(can, ensure_ascii=False)}")
        return
    cnt = res["counts"]
    can = res.get("canary") or {}
    print(f"дифференциальный замер (дерево {res['tree_root']}):")
    if can:
        print(f"  канарейка сцены: население первого шага "
              f"{can.get('base_sites')} → {can.get('grown_sites')} "
              f"(сдвиг {can.get('delta')})")
    print(f"  имён в обоих прогонах: {cnt['names_seen']}, "
          f"СМЕНИЛИ вердикт: {cnt['changed']} "
          f"(в skipped {cnt['to_skipped']}, исчезли {cnt['vanished']})")
    print(f"  ЧЛЕНОВ КЛАССА (файлов): {cnt['member_files']}")
    for row in res["changed"]:
        print(f"    {row['base']:>8} → {row['grown']:<8} {row['nodeid']}")


# --------------------------------------------------------------------------- #
# Объявление
# --------------------------------------------------------------------------- #

def declaration_from_measurement(surface: dict, diff: dict, *, sha: str,
                                 measured_at: str,
                                 positive_control: Optional[dict] = None) -> dict:
    """Объявление класса ИМЕНАМИ — то, что читает сторож.

    Объявление несёт и ПОВЕРХНОСТЬ, и ЧЛЕНОВ: «кандидат» и «член» — разные
    числа, и слить их значило бы выдать вилку за замер.
    """
    members = [{"nodeid": c["nodeid"],
                "file": c["nodeid"].split("::")[0],
                "base": c["base"], "grown": c["grown"],
                "measured_in": f"{sha} · сцена {GROWN_REL}"}
               for c in (diff.get("changed") or [])]
    return {
        "order": "G907.2",
        "sha": sha,
        "measured_at": measured_at,
        "tree_root": diff.get("tree_root"),
        "scene": GROWN_REL,
        "canary": {k: v for k, v in (diff.get("canary") or {}).items()
                   if k in ("base_sites", "grown_sites", "delta")},
        # Чем доказано, что «членов 0» есть ответ о НАБОРЕ, а не о приборе.
        "positive_control": {
            "status": (positive_control or {}).get("status"),
            "declared": (positive_control or {}).get("declared"),
            "flipped": [c["nodeid"] for c in (positive_control or {}).get(
                "changed") or []],
        },
        "surface_files": list(surface.get("surface_files") or []),
        "surface_count": int((surface.get("counts") or {}).get("on_live_root", 0)),
        # Что РЕАЛЬНО прогнано. Совпадать с поверхностью не обязано: правило
        # поверхности уточнялось ПОСЛЕ запуска прогона, и надмножество
        # прогнанного — замер, а не описка. Молчаливое равенство двух полей
        # сделало бы «прогнали другое» неотличимым от «прогнали это».
        "differential_files": list(diff.get("files") or []),
        "member_files": list(diff.get("member_files") or []),
        "members": members,
        "member_count": len(members),
        # Потолок живёт ТОЛЬКО здесь: вторая его копия в коде и есть тот
        # счётный потолок, который устаревает НА ДЕНЬ ДОСТАВКИ (ADR-912).
        "upper_bound": len(members),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", action="store_true",
                    help="разобрать поверхность (AST, дешево)")
    ap.add_argument("--canary", action="store_true",
                    help="спросить, сдвигает ли сцена население первого шага")
    ap.add_argument("--differential", action="store_true",
                    help="прогнать поверхность ДВАЖДЫ: как есть и в выросшем дереве")
    ap.add_argument("--positive-control", action="store_true",
                    help="собрать БОМБУ с населением дерева и потребовать, "
                         "чтобы дифференциал её НАШЁЛ")
    ap.add_argument("--repo-root", default=None,
                    help="дерево, у которого спрашивается ПОВЕРХНОСТЬ")
    ap.add_argument("--tree-root", default=None,
                    help="ОДНОРАЗОВОЕ дерево, в котором идут прогоны и сцена")
    ap.add_argument("--files", nargs="*", default=None,
                    help="поверхность вручную (иначе берётся у --surface)")
    ap.add_argument("--timeout-s", type=int, default=7200)
    ap.add_argument("--skip-canary", action="store_true",
                    help="не спрашивать канарейку (только для контролей прибора)")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--declare", default=None,
                    help="записать объявление класса в указанный файл")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root()
    out: dict = {}
    rc = 0

    if args.surface or args.differential or args.declare:
        surface = measure_surface(repo_root)
        out["surface"] = surface
        if args.surface and not args.as_json:
            _print_surface(surface)
        if surface.get("status") != "MEASURED":
            if args.as_json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    else:
        surface = {}

    if args.canary and not args.differential:
        tree = Path(args.tree_root or repo_root)
        can = canary(tree, timeout_s=args.timeout_s)
        out["canary"] = can
        if not args.as_json:
            print(f"канарейка сцены ({tree}): {json.dumps(can, ensure_ascii=False)}")
        if can.get("status") != "MEASURED":
            rc = 2

    if args.positive_control:
        if not args.tree_root:
            print("❌ НЕ ИЗМЕРЕНО: --positive-control требует --tree-root")
            return 2
        pc = positive_control(Path(args.tree_root), timeout_s=args.timeout_s)
        out["positive_control"] = pc
        if not args.as_json:
            print(f"положительный контроль пайплайна: {pc.get('status')} "
                  f"(литерал {pc.get('declared')})")
            for row in pc.get("changed") or []:
                print(f"    {row['base']:>8} → {row['grown']:<8} {row['nodeid']}")
            if pc.get("reason"):
                print(f"    причина: {pc['reason']}")
        if pc.get("status") != "MEASURED":
            rc = 2

    if args.differential:
        if not args.tree_root:
            print("❌ НЕ ИЗМЕРЕНО: --differential требует --tree-root "
                  "(одноразовое дерево; дерево доставки под прибор не отдаётся)")
            return 2
        files = args.files if args.files else list(surface.get("surface_files") or [])
        diff = differential(Path(args.tree_root), files,
                            timeout_s=args.timeout_s,
                            skip_canary=args.skip_canary)
        out["differential"] = diff
        if not args.as_json:
            _print_differential(diff)
        if diff.get("status") != "MEASURED":
            rc = 2
        elif diff["counts"]["member_files"]:
            rc = 1

    if args.declare:
        diff = out.get("differential") or {}
        if diff.get("status") != "MEASURED":
            print("❌ объявление НЕ записано: дифференциальный замер не измерен")
            return 2
        pc = out.get("positive_control") or {}
        if pc.get("status") != "MEASURED":
            # Объявление без доказанной находчивости пайплайна утверждало бы
            # «членов 0» о НАБОРЕ, не умея отличить это от «прибор слеп».
            print("❌ объявление НЕ записано: положительный контроль пайплайна "
                  f"не пройден ({pc.get('status')}: {pc.get('reason')}) — "
                  "звать с --positive-control")
            return 2
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root),
                             capture_output=True, text=True).stdout.strip()
        doc = declaration_from_measurement(
            surface, diff, sha=sha, positive_control=pc,
            measured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        Path(args.declare).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"объявление записано: {args.declare}")

    if args.as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    if not (args.surface or args.canary or args.differential or args.declare
            or args.positive_control):
        ap.print_help()
        return 2
    return rc


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
