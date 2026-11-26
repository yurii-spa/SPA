#!/usr/bin/env python3
"""Сколько сторожей закрепляют СЧЁТЧИК там, где предмет — СОСТАВ.

Класс НАЗВАН циклом #1254 (ADR-1109) и оставлен НЕ ИЗМЕРЕННЫМ вслух: «население
класса „сторож закрепляет СЧЁТЧИК там, где предмет — СОСТАВ“ за пределами этой
ловушки НЕ ИЗМЕРЕНО: закрыта одна дверь». Нулём это не считалось, и этот прибор
отвечает ровно на тот вопрос.

**Форма дефекта.** Сторож гоняет настоящую перепись по настоящему корпусу и
закрепляет ЧИСЛО её населения (``assertEqual(census["population"], 35)``). Пока
состав корпуса меняется ОДНОВРЕМЕННО в двух направлениях — один член ушёл, другой
пришёл, — число не двигается, и сторож остаётся ЗЕЛЁНЫМ при подменённом предмете.
Замер #1254 на живом корпусе кромки: переименование одного члена остатка
(``edge_presence_threshold.py``) оставило население **47** и ведра **дословно
30/4/7/6** — прежнее ожидание не заметило бы подмены вовсе.

**Это НЕ про «числа в тестах».** Закреплённое число само по себе не дефект:
``assertEqual(len(doors), 1)`` отвечает на вопрос «дверь ОДНА», и состав тут
совпадает с числом. Предмет узок и назван двумя условиями СРАЗУ:

1. число сверяется с величиной, пришедшей из ИЗМЕРЕНИЯ (зов переписи/прибора, а не
   литерал, набранный в самой сцене), и
2. тот же сторож НЕ закрепляет ИМЁН этой популяции — ни картой, ни множеством.

Ровно вторым условием отличается починка #1254: там рядом с числами встала КАРТА
``CENSUS_100_SCREEN`` («имя → ведро»), и подмена члена стала видна.

**Ноль исключается намеренно, и это не удобство.** ``assertEqual(len(found), 0)``
закрепляет ПУСТОЙ состав, а пустой состав определён своим числом однозначно:
подменить в нём члена нельзя, потому что членов нет. Единица — уже может
(``1 → ушёл один, пришёл другой → 1``), и потому в предмете остаётся.

**Одна строка `assertIn` с ОДНИМ именем закреплением состава НЕ является**, и это
измерено на известном члене, а не решено из удобства: до починки #1254 сторож нёс
``assertIn("edge_downside_parity.py", …)`` при населении 35 — то есть называл ОДНО
имя из тридцати пяти и всё равно пропускал подмену любого из остальных. Считать
такую строку «состав закреплён» значило бы ПОТЕРЯТЬ известного члена, а форма,
теряющая известного члена, класс не сужает, а ПОДМЕНЯЕТ (урок #1218).

**Контроль известного члена идёт В ОБЕ СТОРОНЫ и ДО переписи.** Прибор несёт
побайтово извлечённые тела решающего метода с ОБЕИХ сторон починки #1254
(``spa_core/tests/test_edge_boundary_dataflow_census.py``: до —
``2fb147b7a^``, md5 файла ``f3d992625329910d4a9208576d26cf50``; после —
``2fb147b7a``, md5 файла ``b1fa6899007cbfef42e56aeb9c634ddf``). Форма обязана
назвать первое ЧЛЕНОМ и второе НЕ-ЧЛЕНОМ. Хоть один контроль не сошёлся ⇒ прибор
ОТКАЗЫВАЕТ (код 2) и числа НЕ печатает: при такой форме его число было бы ответом
о поверхности, которой он не видит.

**Три исхода различимы** (инв. #17): член · состав закреплён · **НЕ РАЗОБРАНО** с
названной причиной. Население печатается ВИЛКОЙ (члены … члены + не разобрано +
«состав закреплён у СОСЕДА»), а не одним числом: первая редакция переписи врёт в
сторону находки, и вилка — единственная честная форма, пока второй хоп не измерен.

**Чего прибор НЕ закрывает.** Он видит ОДИН файл и ОДИН хоп: сторож, закрепляющий
состав через общего помощника, числится «не закреплён» и попадает в верхнюю половину
вилки, а не в члены. Охват — ``spa_core/tests/test_*.py`` (``glob``, не ``rglob``) —
это ЗАМЕР охвата соседних храповиков, а не выбор прибора; ``tests/``,
``scripts/tests/``, ``studio_shell/`` в поверхность не входят, и это граница ОХВАТА,
а не замер их пустоты. И он отвечает на вопрос «закреплён ли СОСТАВ», а не «верен ли
он»: карта из выдуманных имён пройдёт.

Коды возврата: 0 — членов нет · 1 — члены НАЗВАНЫ · 2 — НЕ ИЗМЕРЕНО (контроль
известного члена не сошёлся, поверхность не прочитана, разбор не удался).

Прибор только ЧИТАЕТ.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

SURFACE_GLOB = "spa_core/tests/test_*.py"

#: формы `unittest`, которые спрашивают РАВЕНСТВО (а не порядок/вхождение).
_EQ_METHODS = frozenset({
    "assertEqual", "assertEquals", "assertDictEqual", "assertSetEqual",
    "assertListEqual", "assertTupleEqual", "assertCountEqual", "assertMultiLineEqual",
})

# ─────────────────────────────────────────────────────────────────────────────
# Контрольные тела — ПОБАЙТОВО извлечённые куски известного члена, с адресом.
# Обвязка (`import`, `class`, `def`) — МОЯ и названа обвязкой: без неё фрагмент
# не является разбираемым модулем. Решающие строки внутри — чужие байты.
# ─────────────────────────────────────────────────────────────────────────────

_SCAFFOLD_HEAD = (
    "import contextlib\n"
    "import io\n"
    "from pathlib import Path\n"
    "import edge_boundary_dataflow_census as bdc\n"
    # строки 34–35 известного члена, ПОБАЙТОВО — ими задаётся ось «корень от __file__»
    "ROOT = Path(__file__).resolve().parents[2]\n"
    "SCRIPTS = ROOT / \"scripts\"\n"
    "class T:\n"
    "    def test_the_census_screens_the_population_100_published(self):\n"
)

#: `2fb147b7a^:spa_core/tests/test_edge_boundary_dataflow_census.py`, строки 248–260.
_KNOWN_MEMBER_BODY = """
        import edge_split_protocol_diagnostic as spd

        with bdc.corpus_without_self(SCRIPTS) as mirror:
            with contextlib.redirect_stdout(io.StringIO()):
                census = spd.section1_census(Path(mirror))
        self.assertEqual(census["population"], 35)
        buckets = {k: len(v) for k, v in census["buckets"].items()}
        self.assertEqual(buckets["BOUNDARY USED, BUT NEVER AS A SLICE INDEX"], 21)
        self.assertEqual(buckets["RE-RUNS ON THE SLICE"], 6)
        self.assertIn("edge_downside_parity.py",
                      [Path(m).name for m in census["buckets"]["RE-RUNS ON THE SLICE"]],
                      "the 35th module must be the one that was ADDED, not some other module "
                      "that quietly changed bucket while the totals happened to add up")
"""

#: `2fb147b7a:…` строки 358–382 плюс константа-карта (она живёт на уровне модуля).
_KNOWN_NONMEMBER_CONST = (
    "CENSUS_100_SCREEN = {\n"
    "    'BOUNDARY USED, BUT NEVER AS A SLICE INDEX': ('a.py', 'b.py'),\n"
    "    'RE-RUNS ON THE SLICE': ('c.py', 'd.py'),\n"
    "}\n"
)

_KNOWN_NONMEMBER_BODY = """
        import edge_split_protocol_diagnostic as spd

        with bdc.corpus_without_self(SCRIPTS) as mirror:
            with contextlib.redirect_stdout(io.StringIO()):
                census = spd.section1_census(Path(mirror))
        measured = {k: tuple(sorted(Path(m).name for m in v))
                    for k, v in census["buckets"].items()}
        self.assertEqual(measured, {k: tuple(sorted(v)) for k, v in CENSUS_100_SCREEN.items()},
                         "the edge corpus moved")
        buckets = {k: len(v) for k, v in census["buckets"].items()}
        self.assertEqual(census["population"], 47)
        self.assertEqual(buckets["BOUNDARY USED, BUT NEVER AS A SLICE INDEX"], 30)
        self.assertEqual(buckets["RE-RUNS ON THE SLICE"], 7)
"""



#: ``2fb147b7a^:spa_core/tests/test_edge_boundary_dataflow_census.py``, строка 177 —
#: СОСЕДНЯЯ сцена, из-за которой первая редакция прибора ПОТЕРЯЛА известного члена:
#: словарь ``{"cap": 0.20, "cost": 0.0}`` она зачла за «состав закреплён». Фрагмент
#: держится здесь положительным контролем именно того промаха (правило деплоя,
#: § «Проверка сторожа сторожей»: контроль, не видевший настоящей поломки, —
#: украшение).
_SIBLING_WITNESS = """
    def test_the_probe_shape_is_what_the_registry_claims(self):
        node = object()
        self.assertEqual(bdc._required_kwonly(node), {"cap": 0.20, "cost": 0.0})
"""

def known_member_source() -> str:
    """Разбираемый модуль с телом ИЗВЕСТНОГО ЧЛЕНА (до починки #1254).

    Вместе с ним идёт СОСЕДНЯЯ сцена-свидетель: без неё контроль зеленел на
    форме, которая на сквозном замере известного члена ТЕРЯЛА.
    """
    return _SCAFFOLD_HEAD + _KNOWN_MEMBER_BODY + _SIBLING_WITNESS


def known_nonmember_source() -> str:
    """Разбираемый модуль с телом ИЗВЕСТНОГО НЕ-ЧЛЕНА (после починки #1254)."""
    head = _SCAFFOLD_HEAD.replace("class T:", _KNOWN_NONMEMBER_CONST + "class T:")
    return head + _KNOWN_NONMEMBER_BODY + _SIBLING_WITNESS


# ─────────────────────────────────────────────────────────────────────────────
# Разбор
# ─────────────────────────────────────────────────────────────────────────────


def _element_str_literals(node: ast.AST) -> int:
    """Строковые литералы в позиции ЭЛЕМЕНТА или ЗНАЧЕНИЯ — не КЛЮЧА.

    Различие измерено на известном члене, а не выбрано: в его файле стои́т
    ``assertEqual(bdc._required_kwonly(node), {"cap": 0.20, "cost": 0.0})`` —
    словарь, где строки суть КЛЮЧИ, а значения числа. Считать его «контейнером
    имён» значило бы объявить состав закреплённым там, где закреплены два порога,
    и ровно так первая редакция прибора ПОТЕРЯЛА известного члена.
    """
    if isinstance(node, ast.Constant):
        return 1 if isinstance(node.value, str) else 0
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return sum(_element_str_literals(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return sum(_element_str_literals(v) for v in node.values if v is not None)
    if isinstance(node, ast.Call):
        return sum(_element_str_literals(a) for a in node.args)
    return 0


def _is_name_container(node: ast.AST) -> bool:
    """Контейнер ИМЁН: множество/список/кортеж/словарь с ≥2 именами-значениями.

    Два, а не одно: одно имя рядом с числом — это ``assertIn`` известного члена
    (``assertIn("edge_downside_parity.py", …)`` при населении 35), и состав им не
    закреплён — он называет одного из тридцати пяти.
    """
    if isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
        return _element_str_literals(node) >= 2
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in {"set", "frozenset", "dict", "sorted", "tuple", "list"}:
        return any(_is_name_container(a) for a in node.args)
    return False


def name_pins(tree: ast.Module) -> set[str]:
    """Имена констант уровня МОДУЛЯ, значение которых есть контейнер имён."""
    pins: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if node.value is None or not _is_name_container(node.value):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                pins.add(t.id)
    return pins


def call_derived(fn: ast.AST) -> set[str]:
    """Локальные имена, чьё значение ПРОИСХОДИТ от зова — до неподвижной точки.

    Контейнер, набранный в самой сцене, происхождением от зова НЕ является: ровно
    на этом различии стоит первое условие предмета.
    """
    derived: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            if value is None:
                continue
            if not _reaches_call(value, derived):
                continue
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id not in derived:
                        derived.add(sub.id)
                        changed = True
    return derived


def _reaches_call(node: ast.AST, derived: set[str]) -> bool:
    """Выражение ДОХОДИТ до измерения: несёт зов либо ссылается на имя от зова."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            return True
        if isinstance(sub, ast.Name) and sub.id in derived:
            return True
    return False


def _int_literal(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return node.value
    return None


#: зовы, которые СТРУКТУРНО считают МОЩНОСТЬ коллекции.
_CARDINALITY_CALLS = frozenset({"len"})
#: зовы ``pathlib``, перечисляющие каталог однозначно — владелец неважен.
_PATH_CORPUS_CALLS = frozenset({"glob", "rglob", "iterdir"})
#: зовы ``os``, где ИМЯ без владельца лжёт. ``ast.walk`` — обход СИНТАКСИЧЕСКОГО
#: дерева и каталогов не перечисляет вовсе; первая редакция зачла его за
#: перечисление и объявила предметом две сцены, где никакого корпуса нет.
#: Дословно урок #1218: имя метода мерой НЕ является.
_OS_CORPUS_CALLS = frozenset({"walk", "listdir", "scandir"})
#: свободные функции перечисления.
_FREE_CORPUS_CALLS = frozenset({"glob", "iglob"})


def _cardinality_source(node: ast.AST, card_names: set[str]) -> ast.AST | bool | None:
    """Выражение КОЛЛЕКЦИИ, чью мощность считает ``node``; ``None`` — не мощность.

    Возврат ``True`` означает «источник уже проверен при РЕГИСТРАЦИИ имени»
    (контейнер мощностей вроде ``buckets = {k: len(v) for k, v in census[…]}``).
    Мощность доказывается ФОРМОЙ: ``len(x)`` · ``x.count(…)`` · ``sum(1 for …)``.
    Ключ, НАЗВАННЫЙ счётчиком (``census["population"]``), сюда НЕ входит — имя
    мерой не является (урок #1218: совпадение по имени дало 195 ложных файлов
    из 653), и такие строки живут в отдельном ведре.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _CARDINALITY_CALLS and node.args:
            return node.args[0]
        if isinstance(func, ast.Attribute) and func.attr == "count":
            return func.value
        if isinstance(func, ast.Name) and func.id == "sum" and node.args \
                and isinstance(node.args[0], ast.GeneratorExp):
            gen = node.args[0]
            return gen.generators[0].iter if gen.generators else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id in card_names:
        return True
    if isinstance(node, ast.Name) and node.id in card_names:
        return True
    return None


def _measured_cardinality(node: ast.AST, derived: set[str],
                          card_names: set[str]) -> bool:
    """Мощность ИЗМЕРЕННОЙ коллекции: и форма мощности, и источник от зова."""
    src = _cardinality_source(node, card_names)
    if src is None:
        return False
    if src is True:
        return True
    return _reaches_call(src, derived)


def cardinality_names(fn: ast.AST, derived: set[str]) -> set[str]:
    """Имена, чьё значение есть мощность ИЗМЕРЕННОЙ коллекции или их контейнер.

    Источник проверяется ЗДЕСЬ, один раз: контейнер, набранный литералом в самой
    сцене, измерением не является, и подписка по нему мощностью измеренного тоже.
    """
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            carries = _measured_cardinality(value, derived, names)
            if isinstance(value, ast.DictComp):
                carries = carries or (
                    _cardinality_source(value.value, names) is not None
                    and bool(value.generators)
                    and _reaches_call(value.generators[0].iter, derived))
            elif isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
                carries = carries or (
                    _cardinality_source(value.elt, names) is not None
                    and bool(value.generators)
                    and _reaches_call(value.generators[0].iter, derived))
            elif isinstance(value, ast.Dict):
                carries = carries or any(
                    v is not None and _measured_cardinality(v, derived, names)
                    for v in value.values)
            if not carries:
                continue
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id not in names:
                        names.add(sub.id)
                        changed = True
    return names


#: ключи и поля, НАЗВАННЫЕ счётчиком. Это ведро «по имени», а не доказательство.
_COUNTER_KEY_HINTS = ("population", "count", "total", "size", "num")


def _is_counter_by_name(node: ast.AST) -> bool:
    key = None
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
            and isinstance(node.slice.value, str):
        key = node.slice.value
    elif isinstance(node, ast.Attribute):
        key = node.attr
    if key is None:
        return False
    low = key.lower()
    return any(h in low for h in _COUNTER_KEY_HINTS)


def _equality_pairs(fn: ast.AST) -> list[tuple[int, ast.AST, ast.AST]]:
    """Все утверждения о РАВЕНСТВЕ внутри сцены: (строка, левое, правое)."""
    out: list[tuple[int, ast.AST, ast.AST]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _EQ_METHODS and len(node.args) >= 2:
            out.append((node.lineno, node.args[0], node.args[1]))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _EQ_METHODS and len(node.args) >= 2:
            out.append((node.lineno, node.args[0], node.args[1]))
        elif isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) \
                and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq):
            out.append((node.lineno, node.test.left, node.test.comparators[0]))
    return out


def count_pins(fn: ast.AST, derived: set[str], pins: set[str] | None = None) -> dict:
    """Закрепления ЧИСЛА измеренной популяции, разделённые по РОДУ доказательства.

    ``structural`` — мощность доказана ФОРМОЙ выражения. ``by_key_name`` — только
    названием ключа; в члены это не идёт. Ноль исключён: пустой состав определён
    своим числом однозначно, подменять в нём нечего.
    """
    pins = pins or set()
    card_names = cardinality_names(fn, derived)
    structural, by_name = [], []
    for lineno, left, right in _equality_pairs(fn):
        for num_side, other in ((left, right), (right, left)):
            value = _int_literal(num_side)
            if value is None or value == 0:
                continue
            if _int_literal(other) is not None:
                continue  # число против числа — это не популяция
            if not _reaches_call(other, derived):
                continue
            if _measured_cardinality(other, derived, card_names):
                structural.append({"line": lineno, "value": value,
                                   "filter_pins": _filter_pins_identity(fn, pins)})
            elif _is_counter_by_name(other):
                by_name.append({"line": lineno, "value": value})
            break
    return {"structural": structural, "by_key_name": by_name}


def _filter_pins_identity(node: ast.AST, pins: set[str]) -> bool:
    """Отобрана ли коллекция по НАЗВАННОЙ личности — тогда состав закреплён фильтром.

    ``[n for n in ast.walk(body) if n.func.attr == "run" and n.func.value.id == STAGE_KEY]``
    закрепляет состав САМИМ отбором: подменишь члена — и фильтр перестанет его
    находить, то есть число двинется. Считать такую сцену слепой значило бы
    назвать предметом ровно тот случай, против которого класс написан.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            continue
        for gen in sub.generators:
            for cond in gen.ifs:
                for cmp_node in ast.walk(cond):
                    if not isinstance(cmp_node, ast.Compare):
                        continue
                    if not any(isinstance(op, (ast.Eq, ast.In)) for op in cmp_node.ops):
                        continue
                    for side in [cmp_node.left, *cmp_node.comparators]:
                        if isinstance(side, ast.Constant) and isinstance(side.value, str):
                            return True
                        if isinstance(side, ast.Name) and side.id in pins:
                            return True
                        if isinstance(side, ast.Name) and side.id.isupper():
                            return True
    return False


def composition_pins(fn: ast.AST, derived: set[str], pins: set[str]) -> list[int]:
    """Закрепления СОСТАВА: измеренное против контейнера имён либо против карты."""
    lines = []
    for lineno, left, right in _equality_pairs(fn):
        for expected, measured in ((left, right), (right, left)):
            names_side = _is_name_container(expected) or any(
                isinstance(s, ast.Name) and s.id in pins for s in ast.walk(expected))
            if not names_side:
                continue
            if _reaches_call(measured, derived):
                lines.append(lineno)
                break
    return lines


def _imported_modules(tree: ast.Module, fn: ast.AST) -> dict[str, str]:
    """Отображение «локальное имя → имя модуля» из ввозов модуля И самой сцены."""
    out: dict[str, str] = {}
    for node in list(ast.walk(tree)) + list(ast.walk(fn)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def _module_path(repo_root: Path, dotted: str) -> Path | None:
    """Файл модуля по точечному имени. Не нашли ⇒ None (хоп НЕ РАЗРЕШЁН)."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        rel = Path(*parts[:cut])
        for cand in (repo_root / rel.with_suffix(".py"),
                     repo_root / "scripts" / rel.with_suffix(".py"),
                     repo_root / rel / "__init__.py"):
            if cand.is_file():
                return cand
    return None


def repo_rooted_names(tree: ast.Module) -> set[str]:
    """Имена уровня МОДУЛЯ, значение которых происходит от ``__file__``.

    Это решающая ось класса: корпус РЕПОЗИТОРИЯ растёт сам (новый модуль пришёл,
    старый ушёл), и именно над ним счётчик слепнет. Одноразовое дерево сцены
    растёт ровно на то, что сцена в него положила, — подменить там члена молча
    нельзя. Первая редакция прибора эту ось не задавала вовсе и объявляла
    предметом сцены вида ``create_card(..., tracker_dir=tmp_path)``, где корень
    перечисления есть ФИКСТУРА ``tmp_path``, а не корпус.
    """
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not _mentions_repo_root(value, names):
                continue
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id not in names:
                        names.add(sub.id)
                        changed = True
    return names


def _mentions_repo_root(node: ast.AST, repo_names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and (sub.id == "__file__" or sub.id in repo_names):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "__file__":
            return True
    return False


def scene_repo_names(fn: ast.AST, repo_names: set[str]) -> set[str]:
    """Локальные имена сцены, происходящие от корня репозитория."""
    local = set(repo_names)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            else:
                continue
            if not _mentions_repo_root(value, local):
                continue
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id not in local:
                        local.add(sub.id)
                        changed = True
    return local


def _owner_root(node: ast.AST) -> str | None:
    """Самое левое ИМЯ цепочки владельцев: у ``ast.walk`` — ``ast``, у ``os.walk`` — ``os``."""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _enumerates_corpus(node: ast.AST) -> bool:
    """Перечисляет ли выражение КАТАЛОГ — с вопросом о ВЛАДЕЛЬЦЕ, не только об имени."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute):
            if func.attr in _PATH_CORPUS_CALLS:
                return True
            if func.attr in _OS_CORPUS_CALLS and _owner_root(func) in {"os", "shutil"}:
                return True
        elif isinstance(func, ast.Name) and func.id in _FREE_CORPUS_CALLS:
            return True
    return False


#: формы, которыми сцена СТРОИТ популяцию сама (одноразовое дерево, свои файлы).
_DISPOSABLE_CALLS = frozenset({
    "TemporaryDirectory", "mkdtemp", "mkstemp", "NamedTemporaryFile",
    "write_text", "write_bytes", "mkdir", "touch", "makedirs", "copytree",
})


_FIXTURE_METHODS = frozenset({"setUp", "setUpClass", "setup_method", "setup_class"})


def disposable_fixture_classes(tree: ast.Module) -> dict[str, str]:
    """Классы, чья ФИКСТУРА строит одноразовое дерево — по имени класса.

    Замер показал, почему функции недостаточно: сцена
    ``test_alert_actions.py::test_same_button_twice_does_not_create_a_second_card``
    перечисляет каталог и закрепляет ``1``, но каталог этот — одноразовый, и
    создаёт его ``setUp``, а не сам метод. Спрашивать только тело метода значило
    бы объявить предметом её собственную фикстуру.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and item.name in _FIXTURE_METHODS:
                why = builds_own_population(item)
                if why is not None:
                    out[node.name] = f"фикстура {node.name}.{item.name}: {why}"
                    break
    return out


def _enclosing_classes(tree: ast.Module) -> dict[int, str]:
    """Отображение «строка функции → имя объемлющего класса» (один уровень)."""
    out: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in ast.walk(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(item.lineno, node.name)
    return out


def builds_own_population(fn: ast.AST) -> str | None:
    """Сцена сама СОЗДАЁТ перечисляемое — тогда это её фикстура, а не корпус.

    Различие несущее, и первая редакция прибора без него ответила «предмет 100»,
    где заметная часть была одноразовыми сценами: такая сцена кладёт в своё
    дерево ровно столько файлов, сколько положила, и её ``len(files) == 1``
    закрепляет не популяцию мира, а собственную фикстуру — подменить в ней члена
    молча нельзя, потому что состав задан тут же, в этих же строках.
    """
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in _DISPOSABLE_CALLS:
            return f"сцена строит популяцию сама: {name}(…)"
        if name in _OS_CORPUS_CALLS and isinstance(func, ast.Attribute) \
                and _owner_root(func) == "shutil":
            return "сцена строит популяцию сама: shutil.copytree(…)"
    return None


def corpus_backing(repo_root: Path, tree: ast.Module, fn: ast.AST,
                   cache: dict, repo_names: set[str] | None = None) -> dict:
    """Опирается ли популяция сцены на КОРПУС (перечисление файлов) — один хоп.

    Своя сцена смотрится целиком; за её пределами делается РОВНО ОДИН хоп в
    функцию ввезённого модуля. Второй хоп НЕ ИЗМЕРЯЕТСЯ и нулём не считается —
    та же граница, что у сторожа притязания ``injected-clock``.
    """
    local_repo = scene_repo_names(fn, repo_names or set())
    if not _mentions_repo_root(fn, local_repo):
        return {"state": "not_repo_rooted",
                "via": "корень перечисления НЕ происходит от __file__ — "
                       "это фикстура сцены, а не корпус репозитория"}
    if _enumerates_corpus(fn):
        return {"state": "corpus", "via": "своя сцена перечисляет каталог репозитория"}
    imports = _imported_modules(tree, fn)
    unresolved = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not isinstance(owner, ast.Name) or owner.id not in imports:
            continue
        dotted = imports[owner.id]
        # Модуль стандартной библиотеки помощником корпуса быть не может, и
        # «не нашли его в дереве» причиной НЕ является: `ast`, `math`, `datetime`
        # не перечисляют репозиторий. Вопрос задаётся `sys.stdlib_module_names`,
        # то есть самому интерпретатору, а не списку из головы.
        if dotted.split(".")[0] in sys.stdlib_module_names:
            continue
        path = cache.get(("path", dotted), ...)
        if path is ...:
            path = _module_path(repo_root, dotted)
            cache[("path", dotted)] = path
        if path is None:
            unresolved.append(f"модуль {dotted} в дереве не найден")
            continue
        key = ("tree", str(path))
        helper = cache.get(key, ...)
        if helper is ...:
            try:
                helper = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                helper = None
                unresolved.append(f"{path.name}: {exc}")
            cache[key] = helper
        if helper is None:
            continue
        wanted = node.func.attr
        # КЛАСС получателем тоже является: перечислять каталог он может в
        # `__init__`. Спрашивать только `FunctionDef` значило бы объявить хоп
        # неразрешённым там, где получатель найден (замер: 2 сцены из 5).
        target = next((n for n in ast.walk(helper)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef))
                       and n.name == wanted), None)
        if target is None:
            unresolved.append(f"{path.name}: получатель {wanted} не найден")
            continue
        if _enumerates_corpus(target):
            return {"state": "corpus",
                    "via": f"{path.name}:{wanted} перечисляет каталог (один хоп)"}
    if unresolved:
        return {"state": "unresolved", "via": "; ".join(sorted(set(unresolved))[:3])}
    return {"state": "not_corpus", "via": "перечисления каталога не найдено за один хоп"}


def classify_module(source: str, label: str, repo_root: Path | None = None,
                    cache: dict | None = None) -> dict:
    """Вердикт по ОДНОМУ модулю: члены, закрепления состава, НЕ РАЗОБРАНО."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"module": label, "state": "unmeasured",
                "reason": f"разбор не удался: {exc.msg} (строка {exc.lineno})"}
    cache = {} if cache is None else cache
    pins = name_pins(tree)
    disposable_classes = disposable_fixture_classes(tree)
    enclosing = _enclosing_classes(tree)
    repo_names = repo_rooted_names(tree)
    functions = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    module_comp_lines: list[int] = []
    scenes: list[dict] = []
    by_name_only: list[dict] = []
    filtered: list[dict] = []
    for fn in functions:
        derived = call_derived(fn)
        comp = composition_pins(fn, derived, pins)
        module_comp_lines.extend(comp)
        pinned = count_pins(fn, derived, pins)
        if pinned["structural"] and all(c["filter_pins"] for c in pinned["structural"]):
            # Состав закреплён САМИМ отбором: это не слепота, а другая её форма
            # охраны — сцена идёт в «состав закреплён», а не в предмет.
            filtered.append({"function": fn.name, "line": fn.lineno,
                             "counts": pinned["structural"]})
        elif pinned["structural"]:
            own = builds_own_population(fn)
            if own is None:
                owner_class = enclosing.get(fn.lineno)
                own = disposable_classes.get(owner_class) if owner_class else None
            if own is not None:
                backing = {"state": "disposable", "via": own}
            elif repo_root is None:
                backing = {"state": "unresolved", "via": "дерево прибору не названо"}
            else:
                backing = corpus_backing(repo_root, tree, fn, cache, repo_names)
            scenes.append({"function": fn.name, "line": fn.lineno,
                           "counts": pinned["structural"],
                           "composition_lines": comp, "backing": backing})
        elif pinned["by_key_name"]:
            by_name_only.append({"function": fn.name, "line": fn.lineno,
                                 "counts": pinned["by_key_name"]})
    # Демоушен — ТОЛЬКО по СВОЕЙ сцене, и это ЗАМЕР, а не вкус: пин в чужом методе
    # над ЧУЖОЙ популяцией эту сцену не охраняет. Первая редакция снимала предмет
    # и по соседу — и на сквозном контроле ПОТЕРЯЛА известного члена (его сосед
    # закреплял два порога, а не состав корпуса). Форма, теряющая известного члена,
    # класс не сужает, а ПОДМЕНЯЕТ (урок #1218), поэтому «у соседа» осталось
    # отдельным НАБЛЮДЕНИЕМ и предмета не снимает.
    members, same, elsewhere = [], [], []
    for scene in scenes:
        if scene["composition_lines"]:
            same.append(scene)
        else:
            members.append(scene)
            if module_comp_lines:
                elsewhere.append(scene)
    return {"module": label, "state": "parsed", "name_pins": sorted(pins),
            "members": members, "names_pinned_same_scene": same,
            "names_pinned_elsewhere": elsewhere, "by_key_name_only": by_name_only,
            "composition_pinned_by_filter": filtered}


def self_check(repo_root: Path | None = None) -> dict:
    """Контроль ИЗВЕСТНОГО члена в ОБЕ стороны. Не сошлось ⇒ числа не печатаются.

    Дерево ПЕРЕДАЁТСЯ, чтобы контроль прогонял и ось «корень от ``__file__``», и
    хоп в помощника — иначе он зеленел бы, не тронув две оси из четырёх. Хоп не
    разрешился (помощника в дереве нет) ⇒ сцена остаётся членом, и это НАЗВАНО:
    контроль отвечает «форма не потеряла известного члена», а не «все оси тронуты».
    """
    root = repo_root or Path(__file__).resolve().parents[1]
    before = classify_module(known_member_source(), "known-member@2fb147b7a^", root, {})
    after = classify_module(known_nonmember_source(), "known-nonmember@2fb147b7a", root, {})
    problems = []
    if before.get("state") != "parsed" or not before.get("members"):
        problems.append("известный ЧЛЕН (до починки #1254) членом НЕ назван")
    if after.get("state") != "parsed" or after.get("members"):
        problems.append("известный НЕ-ЧЛЕН (после починки #1254) назван членом")
    if after.get("state") == "parsed" and not after.get("names_pinned_same_scene"):
        problems.append("у известного НЕ-ЧЛЕНА закрепление СОСТАВА не найдено")
    return {"ok": not problems, "problems": problems,
            "before": before, "after": after}


def census(repo_root: Path) -> dict:
    files = sorted(repo_root.glob(SURFACE_GLOB))
    if not files:
        return {"state": "unmeasured",
                "reason": f"поверхность пуста: {SURFACE_GLOB} в {repo_root} не дал файлов"}
    cache: dict = {}
    rows, unmeasured = [], []
    for path in files:
        rel = str(path.relative_to(repo_root))
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured.append({"module": rel, "reason": f"файл не прочитан: {exc}"})
            continue
        verdict = classify_module(source, rel, repo_root, cache)
        if verdict["state"] != "parsed":
            unmeasured.append({"module": verdict["module"], "reason": verdict["reason"]})
            continue
        rows.append(verdict)

    corpus, local, unresolved, disposable, not_rooted = [], [], [], [], []
    bucket = {"corpus": corpus, "unresolved": unresolved,
              "disposable": disposable, "not_corpus": local,
              "not_repo_rooted": not_rooted}
    for row in rows:
        for scene in row["members"]:
            item = {"module": row["module"], **scene}
            bucket[scene["backing"]["state"]].append(item)
    pinned = sum(len(r["names_pinned_same_scene"]) for r in rows)
    elsewhere = sum(len(r["names_pinned_elsewhere"]) for r in rows)
    by_name = sum(len(r["by_key_name_only"]) for r in rows)
    by_filter = sum(len(r["composition_pinned_by_filter"]) for r in rows)
    return {
        "state": "measured", "scanned": len(files),
        "subject": corpus,
        "members_not_corpus": local,
        "members_backing_unresolved": unresolved,
        "members_disposable_scene": disposable,
        "members_not_repo_rooted": not_rooted,
        "names_pinned_same_scene": pinned,
        "names_pinned_elsewhere": elsewhere,
        "by_key_name_only": by_name,
        "composition_pinned_by_filter": by_filter,
        "unmeasured": unmeasured,
        "fork": [len(corpus), len(corpus) + len(unresolved) + len(unmeasured)],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".",
                    help="дерево, о котором отвечает перепись (умолчание ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-check", action="store_true",
                    help="только контроль известного члена, без переписи")
    args = ap.parse_args(argv)

    root = Path(args.repo_root).resolve()
    check = self_check(root)
    if not check["ok"]:
        payload = {"state": "unmeasured", "reason": "контроль известного члена НЕ СОШЁЛСЯ",
                   "problems": check["problems"]}
        print(json.dumps(payload, ensure_ascii=False, indent=1) if args.json else
              "❌ НЕ ИЗМЕРЕНО: контроль известного члена НЕ СОШЁЛСЯ — числа НЕ печатаю\n   "
              + "\n   ".join(check["problems"]), file=sys.stderr)
        return 2
    if args.self_check:
        print("✅ контроль известного члена сошёлся В ОБЕ СТОРОНЫ "
              "(до починки #1254 — ЧЛЕН, после — состав закреплён)")
        return 0

    result = census(root)
    result["repo_root"] = str(root)
    result["repo_root_source"] = "НАЗВАН входом" if args.repo_root != "." else "УМОЛЧАНИЕ (.)"
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"дерево: {root}  ({result['repo_root_source']})")
        if result["state"] != "measured":
            print(f"❌ НЕ ИЗМЕРЕНО: {result['reason']}", file=sys.stderr)
            return 2
        print(f"поверхность: {SURFACE_GLOB} — файлов {result['scanned']}")
        print("ПРЕДМЕТ (популяция опирается на КОРПУС, состав НЕ закреплён): "
              f"{len(result['subject'])}")
        print(f"  мощность закреплена, корпуса за один хоп НЕ НАЙДЕНО: "
              f"{len(result['members_not_corpus'])}")
        print(f"  одноразовая сцена строит популяцию сама: "
              f"{len(result['members_disposable_scene'])}")
        print(f"  корень перечисления НЕ от __file__ (фикстура, не корпус): "
              f"{len(result['members_not_repo_rooted'])}")
        print(f"  хоп НЕ РАЗРЕШЁН (нулём не считается): "
              f"{len(result['members_backing_unresolved'])}")
        print(f"  состав закреплён в той же сцене: {result['names_pinned_same_scene']}"
              f"  ·  у соседа по модулю: {result['names_pinned_elsewhere']}")
        print(f"  состав закреплён ФИЛЬТРОМ отбора: "
              f"{result['composition_pinned_by_filter']}")
        print(f"  только по ИМЕНИ ключа (доказательством НЕ является): "
              f"{result['by_key_name_only']}")
        print(f"  НЕ РАЗОБРАНО файлов: {len(result['unmeasured'])}")
        print(f"население ПРЕДМЕТА — ВИЛКА {result['fork'][0]} … {result['fork'][1]}")
        for item in result["subject"]:
            print(f"  ПРЕДМЕТ {item['module']}::{item['function']}:"
                  f"{item['counts'][0]['line']} (={item['counts'][0]['value']}) — "
                  f"{item['backing']['via']}")
        for row in result["unmeasured"]:
            print(f"  НЕ РАЗОБРАНО {row['module']} — {row['reason']}")
    if result["unmeasured"]:
        return 2
    return 1 if result["subject"] else 0


def _guarded(argv: list[str] | None = None) -> int:
    """Неожиданное исключение — ТРЕТИЙ исход (код 2), а не код 1.

    Код 1 означает «члены НАЗВАНЫ». Падение с кодом 1 выдало бы «не измерено» за
    находку, то есть ровно подмену исхода, против которой написан инв. #17.
    """
    try:
        return main(argv)
    except Exception as exc:  # noqa: BLE001 — третий исход обязан быть различим
        print(f"❌ НЕ ИЗМЕРЕНО: прибор упал — {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_guarded())
