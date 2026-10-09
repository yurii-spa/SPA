"""Дорога импорта есть достижимость, а не ИСПОЛНЕНИЕ — измерено у ТЕСТА (заказ G107 п. 2).

[ADR-529](../../docs/decisions/ADR-529-one-sidedness-of-the-membership-rule-measured-not-declared.md)
измерил односторонность правила принадлежности §49 в сторону ЗАНИЖЕНИЯ: правило
видит 129 пар «тест × поверхность» из 1112 достижимых, а 807 дорог идут через
помощника и в население критерия владельца не входят. И тот же ADR назвал вслух
СВОЮ односторонность — в обратную сторону:

> «ТРОГАЕТ ли тест поверхность на самом деле: дорога импорта есть достижимость,
> а не исполнение. Это главная односторонность в сторону ЗАВЫШЕНИЯ, и она
> единственная такая».

Названо словом и не посчитано ни одним числом. Заказ G107 п. 2 требует числа:
**сколько из 807 находок ведут через модуль, который тест действительно
ИСПОЛНЯЕТ**, — и указывает, ГДЕ мерить: «у теста (какие имена он зовёт), а не у
графа».

Различие «у теста» против «у графа» существенно и не словесное.
[ADR-672](../../docs/decisions/ADR-672-a-membership-rule-that-sees-only-the-direct-import.md)
подошёл к тому же вопросу У ГРАФА — вторым родом дуг (`module_level_only`:
импорты верхнего уровня без охраны). Граф отвечает «исполнилась бы дуга при
импорте файла», и это НЕ тот вопрос: дуга, исполнившаяся на импорте, вводит
модуль в память, а зовёт ли тест его код — у графа не спросишь вовсе. Здесь
спрашивается сам тест: встречается ли имя первого шага дороги в его ЗОВАХ.

## Что мерится и чем

**Правило принадлежности здесь не переписывается ни первым, ни вторым разом.**
Население, поверхности, дороги и первый шаг каждой дороги берутся ЦЕЛИКОМ из
находок соседа ``membership_reach_census.measure``; имена импортов читает тот же
``_imported_modules``, файл по имени находит тот же ``_resolve``, арифметику
относительного импорта делает тот же ``_relative_edges`` (ему передаётся дерево
из ОДНОГО узла — так копия арифметики остаётся одна, ADR-522).

Прибор добавляет к дороге ровно одно — **ЗОВ**:

* **притязание имени.** ``import a.b`` делает зовущим точечное имя ``a.b``;
  ``import a.b as x`` и ``from a.b import c`` — короткие имена ``x`` и ``c``.
  Различие нужно: при ``import a.b`` корнем зова ``a.c.g()`` тоже является
  ``a``, и считать такой зов обращением к ``a/b.py`` значило бы ЗАНИЗИТЬ
  завышение. Поэтому сравниваются точечные ПРИТЯЗАНИЯ, а не корни;
* **зовы файла.** Для каждого ``ast.Call`` восстанавливается точечный путь
  вызываемого (``a.b.f()`` → ``a.b.f``). Цепь, оборванная не-именем
  (``obj[0].f()``), точечного пути не имеет — такой зов в сравнение не входит
  и назван ценой;
* **упоминания файла** — те же точечные пути, но у ЛЮБОГО чтения имени вне
  самих операторов импорта. Имя, переданное аргументом, подменённое
  ``monkeypatch.setattr`` или навешенное декоратором, зовётся КОСВЕННО, и
  объявить такую пару «не зовёт» значило бы выдать неизвестное за ноль.

## Перечень исходов ЗАКРЫТ (инв. #17): сумма = население

* ``first_hop_called_by_the_test`` — притязание первого шага стоит в зове.
  Дорога подтверждена на своём первом звене;
* ``first_hop_only_imported`` — **ОТВЕТ ЗАКАЗА**: имя ввезено и НИ РАЗУ не
  упомянуто вне оператора импорта. Тест не может дотянуться до кода помощника
  через это имя вовсе — это и есть завышение, измеренное числом;
* ``first_hop_used_but_not_called`` — третий исход: имя упомянуто как значение,
  но корнем зова не стои́т. Косвенность возможна, и решение не принимается;
* ``binding_not_declared_by_the_form`` — третий исход: форма ввоза имени не
  объявляет вовсе. Их две, и обе названы в строке находки (``hidden_by``):
  ``from … import *`` и непрозрачный ввоз, чей результат простому имени не
  присвоен (либо возвращает СПЕЦ, а не модуль);
* ``first_hop_not_bound_in_the_test`` — третий исход И СОБСТВЕННЫЙ КОНТРОЛЬ:
  сосед провёл дугу «тест → первый шаг», а разбор узлов импорта имени для неё
  не нашёл. Ноль здесь есть доказательство, что два механизма согласны;
  не ноль — названное расхождение, а не «не зовёт»;
* ``test_file_not_parsed`` — третий исход: файл не прочитан или не разобран.

## Почему ноль ЗАВЫШЕНИЯ был бы НИЖНЕЙ границей с этой стороны

Счёт ``first_hop_only_imported`` ошибается в сторону ЗАНИЖЕНИЯ завышения по
четырём названным причинам, и все четыре печатаются рядом с числом:

1. **меряется ПЕРВОЕ звено дороги, а не вся дорога.** Тест, зовущий помощника,
   не обязан тем самым дойти до поверхности: зов подтверждает первое звено и
   молчит об остальных. Пара с подтверждённым первым звеном вправе оказаться
   завышением на втором;
2. ``first_hop_used_but_not_called`` и ``binding_not_declared_by_the_form`` —
   пары, о которых решение НЕ принято; любая из них вправе быть завышением;
3. зов с оборванной цепью (``obj[0].f()``) точечного пути не имеет;
4. имя, вычисляемое в рантайме (``globals()``, ``importlib``), прибором не
   видно по построению.

И одна причина ошибается в ОБРАТНУЮ сторону, то есть ЗАВЫШАЕТ само завышение:
**ввоз исполняет тело модуля.** Пара, где зова нет, всё же исполнила код
первого шага — самим фактом импорта, если дуга лежит на верхнем уровне без
охраны. Это измеримо, и потому не оставлено словом: ось
``import_time_price`` (вход ``--price-import-time``) спрашивает ВТОРОЙ род графа
соседа (``module_level_only=True``), доходит ли дорога до поверхности на одних
только исполняемых при импорте дугах. Ось не спрошена ⇒ исход ``not_asked``,
и ноль НЕ печатается (урок ADR-673: цена предела, названная числом пар вместо
замера, есть проза).

## ADVISORY

Прибор только ЧИТАЕТ дерево: ни одного теста не запускает, не правит и не
ослабляет (инв. #16); население критерия §49 НЕ расширяет и вердикт его не
меняет — это РЕШЕНИЕ, а не замер (предмет №2 границы ADR-285). RiskPolicy v1.0,
стоп-кран, аллокатор, гейт исполнения, живой трек, ``landing/**`` и флот не
трогаются. LLM запрещён (инв. #3), ввозы — только stdlib (инв. #4).

Артефакта прибор НАМЕРЕННО не производит: читателем служит шаг 0-офис, зовущий
``measure()`` напрямую, — тот же порядок и та же причина, что у ADR-524
(артефакт переписи стал бы её собственным операндом, то есть новым членом
измеряемого класса).

Время, pid, сеть и git-окружение прибор не спрашивает ни у машины, ни у часов:
единственный вход — путь дерева, поэтому мера проверяется фикстурой
(`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import argparse
import ast
import configparser
import fnmatch
import json
import pathlib
import sys

from spa_core.monitoring import membership_reach_census as reach

# ── ось пары. Перечень ЗАКРЫТ: сумма = население (инв. #17) ──────────────────
CALLED = "first_hop_called_by_the_test"
REEXPORTED = "first_hop_reexported_for_the_collector"
ONLY_IMPORTED = "first_hop_only_imported"
USED = "first_hop_used_but_not_called"
HIDDEN = "binding_not_declared_by_the_form"
NO_BINDING = "first_hop_not_bound_in_the_test"
NOT_PARSED = "test_file_not_parsed"

OUTCOMES: tuple[str, ...] = (CALLED, REEXPORTED, ONLY_IMPORTED, USED, HIDDEN,
                             NO_BINDING, NOT_PARSED)

#: Исходы, про которые решение НЕ принято. Цена числа завышения, а не его часть.
UNDECIDED: tuple[str, ...] = (USED, HIDDEN, NO_BINDING, NOT_PARSED)

#: Исходы, при которых код первого шага ИСПОЛНЯЕТСЯ, хотя сам файл его не зовёт.
#: Перечень закрыт и объявлен: зов собирателя — такое же исполнение, как зов
#: файла, и складывать его с «только ввезено» значило бы назвать ложью правду.
EXECUTED_BY_SOMEONE_ELSE: tuple[str, ...] = (REEXPORTED,)

REPO_ROOT = reach.REPO_ROOT

Unmeasured = reach.Unmeasured


# ─────────────────────────── притязания и зовы ───────────────────────────────

def _dotted_of(node: ast.AST) -> str | None:
    """Точечный путь выражения ``a.b.f`` или ``None``, если цепь не из имён.

    ``obj[0].f`` точечного пути не имеет НАМЕРЕННО: выдумать для него имя
    значило бы завести второй способ принадлежности (та же причина, по которой
    сосед не выдумывает имя относительному импорту).
    """
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _claims(node: ast.Import | ast.ImportFrom) -> tuple[frozenset[str], bool]:
    """Притязания имени одного оператора импорта + флаг ``from … import *``.

    ``import a.b`` притязает на ПОЛНОЕ точечное имя: корень ``a`` сам по себе
    притязанием не является, иначе зов ``a.c.g()`` сошёл бы за обращение к
    ``a/b.py``. Корень учитывается ОТДЕЛЬНО и только на ОТРИЦАТЕЛЬНОЙ стороне
    (см. :func:`classify`): «зовёт» требует полного имени, «не упомянут вовсе»
    требует отсутствия и корня.
    """
    if isinstance(node, ast.Import):
        return frozenset(alias.asname or alias.name
                         for alias in node.names), False
    star = any(alias.name == "*" for alias in node.names)
    return frozenset(alias.asname or alias.name
                     for alias in node.names if alias.name != "*"), star


#: Непрозрачные формы импорта, возвращающие САМ МОДУЛЬ, — то есть такие, у
#: которых имя, присвоенное результату, и есть имя модуля.
#:
#: Перечень форм здесь НЕ объявляется второй раз: он берётся у соседа
#: (``_OPAQUE_IMPORTERS``), а это — разбиение его перечня по тому, ЧТО форма
#: возвращает. ``spec_from_file_location``/``find_spec`` возвращают СПЕЦ, а не
#: модуль, поэтому имени модулю они не дают, и считать присвоенное имя именем
#: модуля значило бы выдать спец за модуль. Подмножество закреплено тестом:
#: переименование формы у соседа краснит здесь.
_MODULE_RETURNING: frozenset[str] = frozenset({"import_module", "__import__"})


def _value_calls(expr: ast.expr) -> list[ast.Call]:
    """Зовы, чьё значение МОЖЕТ стать значением присваивания.

    Спуск идёт только через обёртки, которые значение ПРОНОСЯТ насквозь:
    ``a if cond else b``, ``a or b``, ``await a``. Найдено разбором моего же
    вывода, а не рассуждением: `test_autonomy_mandate.py` пишет
    ``mod = importlib.import_module(…) if … else None`` — узел присваивания там
    ``IfExp``, и прежняя редакция объявляла форму «не давшей имени», хотя имя
    у неё есть. Через ``str(…)``, индексы и прочие преобразующие формы спуска
    НЕТ намеренно: там значением становится уже не модуль, и назвать имя
    именем модуля значило бы гадать.
    """
    if isinstance(expr, ast.Call):
        return [expr]
    if isinstance(expr, ast.IfExp):
        return _value_calls(expr.body) + _value_calls(expr.orelse)
    if isinstance(expr, ast.BoolOp):
        return [call for value in expr.values for call in _value_calls(value)]
    if isinstance(expr, ast.Await):
        return _value_calls(expr.value)
    return []


def _opaque_claims(tree: ast.Module, root: pathlib.Path,
                   cache: dict[str, str | None],
                   ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Притязания НЕПРОЗРАЧНОГО импорта: имя, присвоенное результату, по файлу.

    Сосед читает эту форму наравне с оператором импорта (``_opaque_import_names``,
    ADR-468/469: без неё ЖИВОЙ красный architecture-тест выпадал из населения
    молча). Значит и притязание у неё есть — им служит ЦЕЛЬ ПРИСВОЕНИЯ:
    ``ksd = importlib.import_module("scripts.kill_switch_drill")`` делает
    зовущим имя ``ksd``.

    Возвращает два отображения «файл → имена»: присвоенные простому имени и
    формы, которые имени не объявили вовсе (результат не присвоен, цель —
    не простое имя, либо форма возвращает спец). Второе множество есть третий
    исход, а не ноль.
    """
    bound: dict[str, set[str]] = {}
    hidden: dict[str, set[str]] = {}
    assigned: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets = [node.target]
        value = getattr(node, "value", None)
        if not targets or value is None:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            continue
        for call in _value_calls(value):
            assigned[id(call)] = names

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted_names = reach_census_opaque(node)
        if not dotted_names:
            continue
        func = node.func
        form = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        names = assigned.get(id(node), [])
        sink = bound if (names and form in _MODULE_RETURNING) else hidden
        for dotted in dotted_names:
            target = reach._resolve(root, dotted, cache)
            if target is None:
                continue
            sink.setdefault(target, set()).update(names or [dotted])
    return bound, hidden


def reach_census_opaque(call: ast.Call) -> set[str]:
    """Имена модулей непрозрачного импорта — ОДНОЙ копией, у соседа.

    Отдельная обёртка существует затем, чтобы разбор формы не появился здесь
    вторым написанием: перечень форм, позиция аргумента и требование литерала
    остаются там, где их завёл ADR-529.
    """
    from spa_core.monitoring.no_regression_census import _opaque_import_names

    return _opaque_import_names(call)


def _covers(claim: str, dotted: str) -> bool:
    """Покрывает ли притязание точечный путь — по ГРАНИЦЕ имени, не подстрокой.

    ``risk`` не вправе покрывать ``riskwire`` — та же граница, что у
    ``_matches`` соседа, и та же причина.
    """
    return dotted == claim or dotted.startswith(claim + ".")


def _call_and_reference_paths(tree: ast.Module) -> tuple[frozenset[str],
                                                         frozenset[str], int]:
    """Точечные пути ЗОВОВ, точечные пути УПОМИНАНИЙ и число оборванных зовов.

    Упоминания собираются вне самих операторов импорта: ``alias`` не является
    ``ast.Name``, но узел импорта целиком из обхода исключается явно — чтобы
    «имя встречается в файле» не означало «имя встречается в своём же импорте».
    """
    calls: set[str] = set()
    references: set[str] = set()
    broken_calls = 0

    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                # Сам оператор импорта из обхода исключён: иначе «имя
                # встречается в файле» означало бы «имя встречается в своём же
                # импорте», и ни одна пара не стала бы `only_imported`.
                continue
            if isinstance(child, ast.Call):
                dotted = _dotted_of(child.func)
                if dotted is None:
                    broken_calls += 1
                else:
                    calls.add(dotted)
            if isinstance(child, (ast.Name, ast.Attribute)) and isinstance(
                    child.ctx, ast.Load):
                # ЧИТАЕТСЯ, а не присваивается. Различие найдено собственной
                # батареей: цель присваивания ``h = import_module(…)`` — это
                # ``ast.Store``, и считать её упоминанием значило бы объявить
                # «решения нет» о паре, где имя не используется НИ РАЗУ, то
                # есть ЗАНИЗИТЬ ответ заказа на целую форму ввоза.
                dotted = _dotted_of(child)
                if dotted is not None:
                    references.add(dotted)
            stack.append(child)

    return frozenset(calls), frozenset(references), broken_calls


#: Умолчание pytest для имён, которые он СОБИРАЕТ и зовёт сам.
#: Используется только когда `pytest.ini` своего `python_functions` не объявляет;
#: что именно сработало, печатается рядом с числом (`collector_rule.source`).
_PYTEST_DEFAULT_FUNCTIONS: tuple[str, ...] = ("test*",)


def collector_rule(repo_root: str) -> dict:
    """Какие имена зовёт САМ pytest — прочитано у конфигурации, а не угадано.

    Нужно отдельным исходом: файл-пересылка (``from … import test_x``) имени
    не зовёт НИ РАЗУ, и у теста это правда — но зовёт его СОБИРАТЕЛЬ, и назвать
    такую пару «код не исполняется» значило бы напечатать ложь. Правило взято
    у ``pytest.ini``; не объявлено там ⇒ умолчание pytest, и источник назван.
    Файл есть, но не прочитан ⇒ ``unmeasured``: решение по таким парам не
    принимается вовсе, а не подменяется умолчанием.
    """
    ini = pathlib.Path(repo_root) / "pytest.ini"
    if not ini.is_file():
        return {"state": "default", "source": "файла pytest.ini нет ⇒ умолчание pytest",
                "patterns": list(_PYTEST_DEFAULT_FUNCTIONS)}
    try:
        parser = configparser.ConfigParser()
        parser.read_string(ini.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        return {"state": "unmeasured",
                "why": f"pytest.ini не разобран: {type(exc).__name__}: {exc}"}
    for section in ("pytest", "tool:pytest"):
        if parser.has_option(section, "python_functions"):
            raw = parser.get(section, "python_functions").split()
            if raw:  # пустое объявление не есть объявление: иначе «собирается
                     # НИЧЕГО» встало бы на место умолчания pytest
                return {"state": "declared",
                        "source": f"pytest.ini [{section}] python_functions",
                        "patterns": raw}
    return {"state": "default",
            "source": "pytest.ini без python_functions ⇒ умолчание pytest",
            "patterns": list(_PYTEST_DEFAULT_FUNCTIONS)}


def _module_scope_imports(tree: ast.Module) -> frozenset[int]:
    """Операторы импорта, чьё имя попадает в НАМЕСТНОЕ пространство модуля.

    Собиратель видит только такие: имя, ввезённое внутри функции или класса,
    в пространство модуля не попадает и собран быть не может. Отбор идёт по
    ВЛОЖЕННОСТИ в ``FunctionDef``/``ClassDef``, а не по ``tree.body``: импорт
    под модульным ``try``/``if`` имя модулю всё-таки даёт.
    """
    out: set[int] = set()

    def walk(node: ast.AST, inside: bool) -> None:
        for child in ast.iter_child_nodes(node):
            nested = inside or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            if isinstance(child, (ast.Import, ast.ImportFrom)) and not inside:
                out.add(id(child))
            walk(child, nested)

    walk(tree, False)
    return frozenset(out)


def _import_nodes(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Все операторы импорта файла, включая лежащие внутри функций и под охраной.

    Сосед строит дугу по ПОЛНОМУ дереву (род графа по умолчанию), поэтому и
    притязания собираются по полному: сузить здесь значило бы сравнивать два
    разных населения.
    """
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))]


def _node_targets(node: ast.Import | ast.ImportFrom, rel: str,
                  root: pathlib.Path, cache: dict[str, str | None]) -> set[str]:
    """Файлы дерева, которые ввозит ОДИН оператор импорта.

    Обе половины механизма взяты у соседа ОДНОЙ копией (ADR-522): имена читает
    ``_imported_modules``, файл по имени находит ``_resolve``, арифметику
    относительного импорта делает ``_relative_edges``. Узел подаётся соседу
    деревом из одного оператора — так копия арифметики остаётся одна.
    """
    one = ast.Module(body=[node], type_ignores=[])
    if isinstance(node, ast.ImportFrom) and node.level:
        return set(reach._relative_edges(one, rel, root))
    out: set[str] = set()
    for dotted in reach._imported_modules(one):
        target = reach._resolve(root, dotted, cache)
        if target is not None:
            out.add(target)
    return out


def classify(tree: ast.Module, rel: str, first_hop: str, root: pathlib.Path,
             cache: dict[str, str | None],
             collector: dict | None = None) -> tuple[str, dict]:
    """Исход ОДНОЙ пары: зовёт ли тест ``rel`` первый шаг дороги ``first_hop``.

    Порядок решений несимметричен НАМЕРЕННО, и это главное свойство меры:

    * «ЗОВЁТ» требует ПОЛНОГО точечного притязания — ``import a.b`` плюс зов
      ``a.c.g()`` обращением к ``a/b.py`` не является;
    * «зовёт СОБИРАТЕЛЬ» проверяется ДО «только ввезено»: файл-пересылка имени
      не зовёт, и это правда у теста, — но код исполняется, и сложить такую
      пару с настоящим завышением значило бы напечатать ложь;
    * «только ввезено» требует, чтобы не встретилось ни притязание, ни его
      КОРЕНЬ: при ``import a.b`` имя ``a``, переданное в ``getattr(a, "b")``,
      делает решение неизвестным, а объявить неизвестное нулём и значило бы
      повторить дефект, против которого написан заказ.

    ``collector`` — ВХОД (вердикт :func:`collector_rule`). Не подан ⇒ правило
    собирателя не спрошено, и пары, которые могли бы оказаться пересылкой,
    уходят в ``binding_not_declared_by_the_form`` с названной причиной: подмена
    умолчанием была бы тем же, чем ноль вместо «не измерено».
    """
    calls, references, broken_calls = _call_and_reference_paths(tree)
    module_scope = _module_scope_imports(tree)
    claims: set[str] = set()
    hidden_forms: set[str] = set()
    scope_claims: set[str] = set()
    for node in _import_nodes(tree):
        if first_hop not in _node_targets(node, rel, root, cache):
            continue
        node_claims, node_star = _claims(node)
        claims |= node_claims
        if id(node) in module_scope:
            scope_claims |= node_claims
        if node_star:
            hidden_forms.add("star_import")
    opaque_bound, opaque_hidden = _opaque_claims(tree, root, cache)
    claims |= opaque_bound.get(first_hop, set())
    if first_hop in opaque_hidden:
        hidden_forms.add("opaque_import_without_a_name")

    roots = {claim.split(".")[0] for claim in claims}
    evidence: dict = {"claims": sorted(claims), "broken_calls": broken_calls}
    if hidden_forms:
        evidence["hidden_by"] = sorted(hidden_forms)

    hit = sorted(claim for claim in claims
                 if any(_covers(claim, dotted) for dotted in calls))
    if hit:
        evidence["called_as"] = hit
        return CALLED, evidence
    seen = sorted(stem for stem in claims | roots
                  if any(_covers(stem, dotted) for dotted in references))
    if seen:
        evidence["used_as"] = seen
        return USED, evidence
    if hidden_forms:
        return HIDDEN, evidence
    if not claims:
        return NO_BINDING, evidence
    # Притязание есть, зова и упоминания нет. Остался один вопрос: не зовёт ли
    # имя СОБИРАТЕЛЬ. Он зовёт только то, что лежит в пространстве МОДУЛЯ.
    if scope_claims:
        if collector is None or collector.get("state") == "unmeasured":
            evidence["hidden_by"] = sorted(
                set(evidence.get("hidden_by", []))
                | {"collector_rule_not_measured"})
            return HIDDEN, evidence
        patterns = tuple(collector.get("patterns") or ())
        collected = sorted(name for name in scope_claims
                           if any(fnmatch.fnmatchcase(name, pat)
                                  for pat in patterns))
        if collected and set(collected) == scope_claims:
            evidence["collected_as"] = collected
            evidence["collector_source"] = collector.get("source")
            return REEXPORTED, evidence
    return ONLY_IMPORTED, evidence


# ──────────────────────────── цена: ввоз исполняет ───────────────────────────

def _import_time_price(repo_root: str, pairs: list[tuple[str, str]],
                       max_depth: int) -> dict:
    """Доходит ли дорога до поверхности на дугах, исполняемых САМИМ импортом.

    Ось спрашивается ТОЛЬКО по просьбе (``--price-import-time``): второй граф
    стои́т десятки секунд, а шаг 0-офис зовёт прибор каждый цикл. Не спрошена ⇒
    ``not_asked``, и ноль не печатается (урок ADR-673).

    Второй род графа берётся у соседа (``module_level_only=True``, ADR-672) —
    своего правила «что исполняется при импорте» здесь не появляется.
    """
    if not pairs:
        return {"state": "no_pairs_to_price"}
    try:
        graph = reach.build_graph(repo_root, module_level_only=True)
    except Unmeasured as exc:
        return {"state": "unmeasured", "why": str(exc)}
    runs = 0
    does_not = 0
    for surface in sorted({surface for _, surface in pairs}):
        spec = reach.DECLARED_SURFACES[surface]
        dist, _ = reach.reverse_bfs(
            graph,
            [rel for rel, names in graph["declares"].items()
             if reach._matches(set(names), spec["modules"])],  # type: ignore[arg-type]
        )
        for rel, pair_surface in pairs:
            if pair_surface != surface:
                continue
            depth = dist.get(rel)
            # Глубина 0 во ВТОРОМ роде графа означает, что сам тест объявляет
            # поверхность импортом ВЕРХНЕГО уровня — тогда её код исполняется
            # ввозом тем более, и отсекать такую пару значило бы ответить «не
            # исполняется» о паре, которая исполняется наверняка. Дефект нашёл
            # мутационный замер (#811): у соседа пара может быть глубины 1
            # через помощника и при этом глубины 0 на одних импортных дугах.
            if depth is not None and depth <= max_depth:
                runs += 1
            else:
                does_not += 1
    return {
        "state": "asked",
        "priced_pairs": len(pairs),
        "road_runs_at_import_time": runs,
        "road_does_not_run_at_import_time": does_not,
    }


# ──────────────────────────────── перепись ───────────────────────────────────

def measure(repo_root: str = REPO_ROOT, reach_doc: dict | None = None,
            max_depth: int = reach.MAX_DEPTH,
            price_import_time: bool = False) -> dict:
    """Перепись «зовёт ли тест помощника, через которого дотягивается до поверхности».

    ``reach_doc`` — ВХОД: находки соседа подаются готовыми, поэтому прибор
    проверяется фикстурой, а не живым деревом, и население не считается здесь
    второй раз.
    """
    root = pathlib.Path(repo_root)
    if reach_doc is None:
        reach_doc = reach.measure(repo_root, max_depth=max_depth)
    if reach_doc.get("unmeasured_reason"):
        return _unmeasured(f"сосед не измерил: {reach_doc['unmeasured_reason']}",
                           max_depth)
    findings = [row for row in reach_doc.get("findings", ())
                if row.get("depth", 0) > 0]
    if not findings:
        # Пустое население печаталось бы как «все нули», то есть как «завышения
        # нет», — это fail-OPEN тише красного теста (урок `pyflakes`, #465).
        return _unmeasured("у соседа ни одной находки через помощника: нулевое "
                           "население не есть «завышения нет»", max_depth)

    collector = collector_rule(repo_root)
    counts = {name: 0 for name in OUTCOMES}
    rows: list[dict] = []
    cache: dict[str, str | None] = {}
    trees: dict[str, ast.Module | None] = {}
    unparsed_why: dict[str, str] = {}
    broken_call_files: set[str] = set()

    for row in findings:
        rel = row["file"]
        chain = row.get("chain") or []
        if len(chain) < 2:
            # Дорога глубины ≥1 обязана нести первый шаг. Нет — это НЕ ИЗМЕРЕНО
            # у соседа, а не «не зовёт».
            counts[NO_BINDING] += 1
            rows.append({"file": rel, "surface": row["surface"],
                         "depth": row.get("depth"), "first_hop": None,
                         "outcome": NO_BINDING,
                         "why": "у находки соседа нет первого шага дороги"})
            continue
        first_hop = chain[1]
        if rel not in trees:
            try:
                trees[rel] = ast.parse((root / rel).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
                trees[rel] = None
                unparsed_why[rel] = f"{type(exc).__name__}: {exc}"
        tree = trees[rel]
        if tree is None:
            # Исход считается у КАЖДОЙ пары этого файла, а не один раз на файл:
            # население — пары, и «посчитать файл» значило бы разойтись сумме с
            # населением на втором же вхождении (инв. #17).
            counts[NOT_PARSED] += 1
            rows.append({"file": rel, "surface": row["surface"],
                         "depth": row.get("depth"), "first_hop": first_hop,
                         "outcome": NOT_PARSED, "why": unparsed_why[rel]})
            continue
        outcome, evidence = classify(tree, rel, first_hop, root, cache,
                                     collector)
        counts[outcome] += 1
        if evidence["broken_calls"]:
            broken_call_files.add(rel)
        rows.append({"file": rel, "surface": row["surface"],
                     "depth": row.get("depth"), "first_hop": first_hop,
                     "outcome": outcome, **{k: v for k, v in evidence.items()
                                            if k != "broken_calls"}})

    priced = [(r["file"], r["surface"]) for r in rows
              if r["outcome"] in UNDECIDED or r["outcome"] == ONLY_IMPORTED]
    price = (_import_time_price(repo_root, priced, max_depth)
             if price_import_time else {"state": "not_asked"})

    return {
        "population": len(findings),
        "max_depth": max_depth,
        "counts": counts,
        "sum_of_counts": sum(counts.values()),
        "rows": rows,
        "per_surface": _per_surface(rows),
        "import_time_price": price,
        "collector_rule": collector,
        "broken_call_files": sorted(broken_call_files),
        "binder_agrees_with_the_graph": counts[NO_BINDING] == 0,
        "unmeasured_reason": "",
    }


def _unmeasured(why: str, max_depth: int) -> dict:
    return {
        "population": 0,
        "max_depth": max_depth,
        "counts": {name: 0 for name in OUTCOMES},
        "sum_of_counts": 0,
        "rows": [],
        "per_surface": {},
        "import_time_price": {"state": "not_asked"},
        "collector_rule": {"state": "not_asked"},
        "broken_call_files": [],
        "binder_agrees_with_the_graph": None,
        "unmeasured_reason": why,
    }


def _per_surface(rows: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        local = out.setdefault(row["surface"], {name: 0 for name in OUTCOMES})
        local[row["outcome"]] += 1
    return out


def verdict(doc: dict) -> str:
    if doc.get("unmeasured_reason") or not doc.get("population"):
        return "unmeasured"
    if not doc.get("binder_agrees_with_the_graph"):
        # Разошедшиеся механизмы делают число завышения непригодным: часть пар
        # не классифицирована вовсе, и объявить остаток ответом нельзя.
        return "binder_disagrees_with_the_graph"
    return ("overstatement_measured" if doc["counts"][ONLY_IMPORTED]
            else "no_overstatement_found")


EXIT_CODES = {
    "unmeasured": 2,
    "binder_disagrees_with_the_graph": 2,
    "overstatement_measured": 1,
    "no_overstatement_found": 0,
}


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if doc.get("unmeasured_reason"):
        return ("НЕ ИЗМЕРЕНО: зовёт ли тест помощника — "
                f"{doc['unmeasured_reason']}")
    counts = doc["counts"]
    undecided = sum(counts[name] for name in UNDECIDED)
    lines = [
        f"дорога есть достижимость, а не исполнение (заказ G107 п. 2): население "
        f"{doc['population']} находок(и) соседа «через помощника», предел глубины "
        f"{doc['max_depth']} (ВЫБОР соседа, не свойство дерева)",
        "  " + " · ".join(f"{name} {counts[name]}" for name in OUTCOMES),
    ]
    elsewhere = sum(counts[name] for name in EXECUTED_BY_SOMEONE_ELSE)
    share = (f"{counts[ONLY_IMPORTED] / doc['population'] * 100:.1f} %"
             if doc["population"] else "НЕ ИЗМЕРЕНО")
    lines.append(
        f"  ОТВЕТ заказа: тест ЗОВЁТ первый шаг дороги в {counts[CALLED]} находках; "
        f"в {counts[ONLY_IMPORTED]} ({share}) имя ввезено и НИ РАЗУ не упомянуто "
        f"вне импорта — это завышение, измеренное числом; решение НЕ принято по "
        f"{undecided} парам; код исполняет НЕ файл, а собиратель, в {elsewhere}")
    lines.append(
        f"  ВИЛКА завышения: НЕ МЕНЬШЕ {counts[ONLY_IMPORTED]} и НЕ БОЛЬШЕ "
        f"{counts[ONLY_IMPORTED] + undecided} из {doc['population']} — верхний край "
        "есть сумма с парами без решения, и назвать одно число вместо вилки значило "
        "бы выдать неизвестное за ноль либо за находку")
    lines.append("  по поверхностям: " + " · ".join(
        f"{s}: зовёт {d[CALLED]}, только ввезено {d[ONLY_IMPORTED]}, "
        f"решения нет {sum(d[n] for n in UNDECIDED)}, зовёт собиратель "
        f"{sum(d[n] for n in EXECUTED_BY_SOMEONE_ELSE)}"
        for s, d in sorted(doc["per_surface"].items())))
    rule = doc.get("collector_rule") or {"state": "not_asked"}
    if rule["state"] == "unmeasured":
        lines.append(f"  [НЕ ИЗМЕРЕНО] правило собирателя: {rule['why']} — пары, "
                     "которые могли бы оказаться пересылкой, ушли в «форма имени не "
                     "объявляет», а не в завышение")
    elif rule["state"] == "not_asked":
        lines.append("  [НЕ ИЗМЕРЕНО] правило собирателя не спрошено")
    else:
        lines.append(f"  правило собирателя: {', '.join(rule['patterns'])} "
                     f"({rule['source']})")
    if doc["sum_of_counts"] != doc["population"]:
        lines.append(f"  [НЕ ИЗМЕРЕНО] сумма исходов {doc['sum_of_counts']} ≠ "
                     f"население {doc['population']} — перечень исходов НЕ закрыт")
    if doc.get("binder_agrees_with_the_graph"):
        lines.append("  КОНТРОЛЬ: разбор узлов импорта нашёл имя для КАЖДОЙ дуги "
                     "соседа (0 пар без притязания) ⇒ два механизма согласны")
    else:
        lines.append(f"  [КОНТРОЛЬ РАСХОДИТСЯ] у {counts[NO_BINDING]} пар(ы) сосед "
                     "провёл дугу, а разбор узлов имени не нашёл: число завышения "
                     "непригодно, пока расхождение не названо")
    price = doc["import_time_price"]
    if price["state"] == "not_asked":
        lines.append("  цена «ввоз исполняет тело модуля»: НЕ СПРОШЕНА "
                     "(`--price-import-time`) — ноль здесь не печатается")
    elif price["state"] == "asked":
        lines.append(
            f"  цена «ввоз исполняет тело модуля»: из {price['priced_pairs']} "
            f"пар(ы) без зова дорога доходит до поверхности на одних только "
            f"исполняемых при импорте дугах у {price['road_runs_at_import_time']}; "
            f"не доходит у {price['road_does_not_run_at_import_time']} — у этих "
            "код поверхности не исполняется ВОВСЕ")
    else:
        lines.append(f"  [НЕ ИЗМЕРЕНО] цена «ввоз исполняет тело модуля»: "
                     f"{price.get('why', price['state'])}")
    for row in [r for r in doc["rows"] if r["outcome"] == ONLY_IMPORTED][:10]:
        lines.append(f"  [{ONLY_IMPORTED}] {row['file']} → {row['surface']} "
                     f"(глубина {row['depth']}) первый шаг {row['first_hop']}, "
                     f"притязание {', '.join(row.get('claims') or ['—'])}")
    extra = counts[ONLY_IMPORTED] - 10
    if extra > 0:
        lines.append(f"  … ещё {extra} находок(и) того же вида (полный перечень — `--json`)")
    lines.append(
        f"  НИЖНЯЯ ГРАНИЦА с этой стороны: {counts[ONLY_IMPORTED]} есть НИЖНЯЯ "
        f"граница завышения, и у неё три названные цены — меряется ПЕРВОЕ звено "
        f"дороги, а не вся дорога · пар без решения {undecided} · имя, вычисляемое "
        "в рантайме (`globals()`, не-литерал в `import_module`), не видно по "
        "построению. Зов с оборванной цепью "
        f"(замер: {len(doc['broken_call_files'])} файл(ов)) ценой НЕ является: "
        "дотянуться до притязания нельзя, не упомянув его имени, а упоминание "
        "уводит пару в «упомянут, но не зовётся»")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: правоту тестов · доходит ли зов первого шага ДО "
                 "поверхности · исполняется ли тело модуля при ввозе (это отдельная "
                 "ось, см. выше) · верность перечня поверхностей (он объявлен соседом)")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ, население критерия §49 НЕ расширяет")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Односторонность §49 в сторону ЗАВЫШЕНИЯ — измерена У ТЕСТА "
                    "(заказ G107 п. 2)")
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--max-depth", type=int, default=reach.MAX_DEPTH)
    parser.add_argument("--price-import-time", action="store_true",
                        help="спросить ВТОРОЙ род графа соседа: исполняется ли "
                             "дорога самим фактом импорта. Не спрошено ⇒ "
                             "`not_asked`, а не ноль")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    doc = measure(args.root, max_depth=args.max_depth,
                  price_import_time=args.price_import_time)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(doc))
    return EXIT_CODES[verdict(doc)]


if __name__ == "__main__":
    sys.exit(main())
