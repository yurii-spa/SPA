"""spa_core/monitoring/cio_outcome_independence.py — существует ли НЕЗАВИСИМОЕ
наблюдение исхода книги (заказ цикла #517, ТЗ CIO «Portfolio CIO», §5 As-Is).

Цикл #517 ([ADR-255]) показал, что последняя ступень цепи — сверка «намерение
против результата» — сравнивает величину С САМОЙ СОБОЙ: из 12 вызовов сверки вне
тестов ни один не подаёт наблюдённый исход, 11 берут второй аргумент из первого
того же вызова. Естественный вывод «забыли передать переменную» тот цикл
отклонил и оставил заказ:

    «Что считать независимым наблюдением исхода» — измерить, СУЩЕСТВУЕТ ли оно
    сегодня. Есть ли в дереве хоть один источник состояния книги, НЕ
    происходящий от той же цели, — и если нет, то честный ответ «независимого
    наблюдения не существует по построению» является полным и означает, что
    ступень нельзя оживить без ответа владельца, а не без правки кода.

**Замер ловушку заказа ОПРОВЕРГ, и оба раза не в ту сторону, что ожидалось.**
Ожидался пустой ответ («предмета нет, сверку не оживить»). Машинерия
независимого наблюдения в дереве ЕСТЬ: `get_supply_balance` / `get_position`
у исполнительных адаптеров читают `aToken.balanceOf(SPA_WALLET_ADDRESS)` — это
внешняя дверь, ключом к которой служит ЛИЧНОСТЬ НАШЕГО счёта, то есть ровно
«субъект — наша книга, происхождение — вне нашего намерения». Ответ «не
существует» верен, но обоснование у него другое и оно сильнее: независимость
отказывает по ТРЁМ независимо достаточным основаниям, и ни одно не чинится
строкой кода.

Устройство замера — две стороны одного вопроса «та ли это сущность», обе
меряются, ни одна не объявляется:

* **субъект** — источник обязан говорить о НАШЕЙ книге. Меряется тем, читает ли
  он личность нашего счёта (`IDENTITY_TOKENS`). Это и есть разбор ловушки,
  названной заказом: `spa_core/adapters/**` проходят внешнюю дверь и НЕ проходят
  субъекта — они наблюдают ПРОТОКОЛЫ, а не нашу книгу. Утверждение это —
  ЗАМЕР (`control.protocol_observers`), а не фраза в шапке.
* **происхождение** — значение обязано приходить внешней дверью, а не из
  артефакта, который мы же и написали из цели. Меряется разбором до
  неподвижной точки по графу вызовов модуля: помощник, который сам зовёт
  помощника, который зовёт `urlopen`, дверью является.

Три основания отказа, каждое измеряется отдельно (важно: они НЕЗАВИСИМО
достаточны, поэтому починка одного НЕ создаёт независимости):

1. **личности нет** — `SPA_WALLET_ADDRESS` не задан ни одной поверхностью
   доставки (`launchd/*.plist`, `scripts/*.sh`). Ключа нет ⇒ ни один источник не
   привязан к нашей книге;
2. **подстановка вместо отказа** — при отсутствии личности источники возвращают
   не отказ, а МОК (`_MOCK_BALANCES`, `_DRY_RUN_BALANCE`, дефолт `"0x0"` прямо в
   `os.environ.get`). Число того же ТИПА, что настоящее наблюдение, поэтому
   потребитель их не различит. Это класс «не измерено, выданное за ответ»
   (`.claude/rules/deployment.md`) на самой той двери, которая должна была дать
   независимость;
3. **стена инварианта #6** — источники живут в `spa_core/execution/`, который
   владельцу книги (`spa_core/tuner/portfolio_rebalancer.py`, ступень
   `portfolio_state`) импортировать ЗАПРЕЩЕНО. Достижимость меряется обходом
   графа импортов от производителя книги, а не наличием строки в шапке.

**Отсюда полный ответ владельцу:** ступень нельзя оживить правкой кода. Нужны
ДВА решения владельца — ослабить инвариант #6 (или завести наблюдателя вне
`execution/`) И дать системе реальный капитал на цепи, у которого есть что
наблюдать. Пока их нет, `matches_target=true` свидетельством не является, и
подстановка мока сделала бы его ЛОЖНЫМ свидетельством, а не отсутствующим.

ADVISORY. Ничего не соединено, ни один вызов не изменён, капитал не сдвинут.

Состав ступени и производитель книги НЕ дублируются (§3 ТЗ — прямая инструкция
владельца не заводить параллельные модели): берутся из
:data:`spa_core.monitoring.cio_component_map.STAGES`. Ключа нет ⇒ громкий
``UNCHECKED``, а не своя копия таблицы.

CLI::  python3 -m spa_core.monitoring.cio_outcome_independence
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REPORT_REL = "data/cio_outcome_independence.json"

#: Ступень, чей продукт и есть КНИГА. Имя — ключ в ``cio_component_map.STAGES``.
BOOK_STAGE_KEY = "portfolio_state"

#: Корни, в которых ищем источники. ``scripts/`` включён намеренно: наблюдателем
#: мог бы быть и отдельный скрипт, а не модуль пакета.
SCAN_ROOTS = ("spa_core", "scripts")

#: Корень, который владельцу книги импортировать запрещено (инвариант #6
#: CLAUDE.md). ОБЪЯВЛЕНИЕ, а не вывод: запрет живёт в инструкции, из кода его
#: не вывести — «контракт объявляют, не выводят».
FORBIDDEN_FOR_BOOK = "spa_core/execution/"

#: Слова, по которым имя переменной окружения признаётся ЛИЧНОСТЬЮ НАШЕГО СЧЁТА.
#: Объявление с причиной: наблюдение исхода обязано быть привязано к тому, чей
#: это исход. Полный набор просмотренных ключей кладётся в отчёт
#: (``identity.env_keys_addressish``), чтобы выбор был проверяем глазами, а не
#: принимался на веру.
IDENTITY_TOKENS = ("WALLET", "ACCOUNT_ADDRESS", "SAFE_ADDRESS")

#: Ключи, которые ВЫГЛЯДЯТ адресными и потому попадают в отчёт для сверки, даже
#: если личностью не признаны.
ADDRESSISH_TOKENS = ("ADDRESS", "WALLET", "ACCOUNT", "SAFE")

#: Внешние двери stdlib. Инвариант #4 (только stdlib) сужает список до
#: разрешённого: чужого http-клиента в рантайме быть не может.
NETWORK_CALLS = frozenset({
    "urlopen", "urlretrieve", "Request",
    "HTTPConnection", "HTTPSConnection",
    "create_connection", "socket",
})

#: Поверхности, которыми задаётся окружение ПРОДА. Ambient-окружение процесса
#: замера НЕ читается намеренно: вердикт, решаемый переменными той оболочки, из
#: которой запустили, отвечает на свой вопрос, а не на нужный
#: (`.claude/rules/deployment.md`, «Вердикт решает ОКРУЖЕНИЕ»).
ENV_SURFACES = ("launchd", "scripts")

# исходы «что будет, если личности нет»
ABSENT_REFUSES = "REFUSES"        #: raise / return None — отказ
ABSENT_FABRICATES = "FABRICATES"  #: возвращает подставное значение
ABSENT_UNCHECKED = "UNCHECKED"    #: разобрать не вышло — третий исход
ABSENT_IDENTITY_SOURCE = "IDENTITY_SOURCE"  #: сам источник личности, не потребитель


# ─────────────────────────── разбор: общие помощники ─────────────────────────

def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _iter_py(root: Path, sub: str) -> Iterable[Path]:
    base = root / sub
    if not base.is_dir():
        return
    for p in sorted(base.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        if "/test_" in rel or Path(rel).name.startswith("test_"):
            continue
        yield p


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


def _env_reads_full(node: ast.AST) -> list[tuple[str, bool, Any]]:
    """Чтения переменных окружения под узлом: ``(имя ключа, есть ли ДЕФОЛТ)``.

    Дефолт здесь — не деталь: ``os.environ.get("SPA_WALLET_ADDRESS", "0x0")``
    подставляет ЧУЖУЮ личность молча, и отличить такое значение от настоящего
    потребитель не может. Поэтому наличие дефолта меряется, а не игнорируется.
    """
    out: list[tuple[str, bool, Any]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = _call_name(sub)
            if fn in ("get", "getenv") and sub.args:
                # os.environ.get(K) / os.getenv(K); отсекаем dict.get чужих словарей
                target = sub.func.value if isinstance(sub.func, ast.Attribute) else None
                is_env = fn == "getenv" or (
                    isinstance(target, ast.Attribute) and target.attr == "environ"
                ) or (isinstance(target, ast.Name) and target.id == "environ")
                if is_env and isinstance(sub.args[0], ast.Constant) \
                        and isinstance(sub.args[0].value, str):
                    dflt = None
                    if len(sub.args) > 1 and isinstance(sub.args[1], ast.Constant):
                        dflt = sub.args[1].value
                    out.append((sub.args[0].value, len(sub.args) > 1, dflt))
        elif isinstance(sub, ast.Subscript):
            v = sub.value
            is_env = (isinstance(v, ast.Attribute) and v.attr == "environ") or \
                     (isinstance(v, ast.Name) and v.id == "environ")
            if is_env and isinstance(sub.slice, ast.Constant) \
                    and isinstance(sub.slice.value, str):
                out.append((sub.slice.value, False, None))
    return out


def _env_reads(node: ast.AST) -> list[tuple[str, bool]]:
    """Совместимая форма: ``(ключ, есть ли дефолт)``."""
    return [(k, d) for k, d, _ in _env_reads_full(node)]


def _is_identity(key: str) -> bool:
    return any(tok in key.upper() for tok in IDENTITY_TOKENS)


def _is_addressish(key: str) -> bool:
    return any(tok in key.upper() for tok in ADDRESSISH_TOKENS)


# ───────────────── внешняя дверь: разбор ДО НЕПОДВИЖНОЙ ТОЧКИ ────────────────

def _module_call_graph(tree: ast.Module) -> tuple[dict[str, set[str]], set[str]]:
    """``(имя функции → имена, которые она зовёт)`` и множество имён-функций.

    Методы кладутся под своим именем: вызов идёт как ``self._rpc(...)``, и
    разрешается по ``attr``. Тезка из другого класса сольётся с этой — и это
    названо вслух: замер отвечает на «дотягивается ли модуль до сети по цепочке
    вызовов», а не «какой ровно метод какого класса».
    """
    graph: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            called = graph.setdefault(node.name, set())
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    n = _call_name(sub)
                    if n:
                        called.add(n)
    return graph, set(graph)


def _reaches_network(start: str, graph: dict[str, set[str]]) -> bool:
    """Дотягивается ли ``start`` до внешней двери — обход ДО НЕПОДВИЖНОЙ ТОЧКИ.

    Помощник, зовущий помощника, зовущего ``urlopen``, дверью является: мерить
    «есть ли `urlopen` прямо в теле» значило бы дать уверенный неверный ответ на
    любом модуле, у которого http вынесен в приватный метод (а вынесен он
    практически у всех).
    """
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        called = graph.get(cur, set())
        if called & NETWORK_CALLS:
            return True
        stack.extend(c for c in called if c in graph and c not in seen)
    return False


def _module_reaches_network(graph: dict[str, set[str]], tree: ast.Module) -> bool:
    """Есть ли внешняя дверь ГДЕ-ЛИБО в модуле (включая модульный уровень)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in NETWORK_CALLS:
            return True
    return any(_reaches_network(fn, graph) for fn in graph)


# ──────────────── что происходит, когда личности НЕТ ─────────────────────────

def _identity_helpers(tree: ast.Module) -> set[str]:
    """Функции модуля, чей ВОЗВРАТ и есть личность нашего счёта.

    Без этого шага замер даёт уверенный неверный ответ на самом населённом
    устройстве дерева: у исполнительных адаптеров чтение вынесено в
    ``_wallet_address()``, а ветка «личности нет» живёт этажом выше, в
    ``get_supply_balance``. Первая редакция искала чтение и ветку В ОДНОЙ
    функции и объявляла ``UNCHECKED`` там, где верный ответ — ``FABRICATES``:
    то есть ЗАНИЖАЛА собственную критическую находку.

    Возврат прослеживается и через ЛОКАЛЬНОЕ ПРИСВАИВАНИЕ (``w = os.getenv(...)``
    … ``return w``): помощник, который сперва отказывает, а потом возвращает
    имя, — обычная форма, и без этого шага «отказ наследуется» измерить нечем.

    Обход — ДО НЕПОДВИЖНОЙ ТОЧКИ: помощник, возвращающий результат помощника,
    личность тоже возвращает.
    """
    direct: set[str] = set()
    returns_call: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local, _ = _binding_sources(node)          # имена, связанные с личностью
        for r in ast.walk(node):
            if not isinstance(r, ast.Return) or r.value is None:
                continue
            if any(_is_identity(k) for k, _ in _env_reads(r.value)):
                direct.add(node.name)
            if isinstance(r.value, ast.Name) and r.value.id in local:
                direct.add(node.name)
            for c in ast.walk(r.value):
                if isinstance(c, ast.Call) and _call_name(c):
                    returns_call.setdefault(node.name, set()).add(_call_name(c))

    changed = True
    while changed:                      # неподвижная точка
        changed = False
        for name, called in returns_call.items():
            if name not in direct and called & direct:
                direct.add(name)
                changed = True
    return direct


def _identity_attrs(tree: ast.Module) -> set[str]:
    """Атрибуты экземпляра, в которые кладётся личность.

    ``self._wallet_address = os.environ.get(...)`` в ``__init__``, а проверка
    ``if not self._wallet_address`` — в другом методе: личность течёт между
    методами через атрибут, и замер, глядящий только внутрь одной функции,
    объявляет потребителя несуществующим. Ровно эта форма живёт в
    `spa_core/execution/wallet.py`.

    Область — МОДУЛЬ, а не класс: одноимённый атрибут разных классов одного
    файла сольётся. Сказано вслух — вопрос замера «течёт ли личность в этот
    атрибут», а не «какого ровно класса этот атрибут».
    """
    attrs: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(_is_identity(k) for k, _ in _env_reads(value)):
            continue
        for t in targets:
            if isinstance(t, ast.Attribute):
                attrs.add(t.attr)
    return attrs


def _binding_of_identity(fn: ast.AST, helpers: frozenset[str] | set[str] = frozenset()) -> set[str]:
    """Имена, в которые кладётся личность — прямым чтением ИЛИ через помощника."""
    return _binding_sources(fn, helpers)[0]


def _binding_sources(fn: ast.AST,
                     helpers: frozenset[str] | set[str] = frozenset()
                     ) -> tuple[set[str], set[str]]:
    """``(имена личности, имена помощников, из которых она пришла)``.

    Связывается ТОЛЬКО чтение личности. Первая редакция брала любое чтение
    окружения, поэтому `_live_supply`, читающий `SPA_EXECUTION_MODE`, попадал в
    потребители личности и выходил ложным ``UNCHECKED``: прибор объявлял
    неизмеренным то, что вообще не было его предметом.

    Цели присваивания разбираются все: имя, АТРИБУТ (``self._wallet_address``)
    и кортеж. На атрибуте прибор был слеп, и `spa_core/execution/wallet.py`
    выходил «чтение не связано с именем» при совершенно обычном
    ``self._wallet_address = os.environ.get(...)``.

    Второе поле нужно, чтобы отличить «ветки нет, потому что никто не
    проверяет» от «ветки нет, потому что помощник УЖЕ отказал».
    """
    names: set[str] = set()
    used: set[str] = set()

    def _targets(tgt: ast.AST) -> set[str]:
        if isinstance(tgt, ast.Name):
            return {tgt.id}
        if isinstance(tgt, ast.Attribute):
            return {tgt.attr}
        if isinstance(tgt, (ast.Tuple, ast.List)):
            out: set[str] = set()
            for el in tgt.elts:
                out |= _targets(el)
            return out
        return set()

    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assign):
            targets, value = sub.targets, sub.value
        elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
            targets, value = [sub.target], sub.value
        else:
            continue
        from_env = any(_is_identity(k) for k, _ in _env_reads(value))
        via = {_call_name(c) for c in ast.walk(value)
               if isinstance(c, ast.Call) and _call_name(c) in helpers}
        if from_env or via:
            used |= via
            for tgt in targets:
                names |= _targets(tgt)
    return names, used


def _is_absence_test(test: ast.AST, names: set[str]) -> bool:
    """Проверяет ли условие ОТСУТСТВИЕ личности (а не её наличие).

    Различение обязательное. Первая редакция брала ЛЮБОЙ ``if``, упоминающий
    имя, и на `scripts/golive_preflight.py` объявила подстановкой ветку
    ``if safe_addr and safe_addr.startswith("0x")`` — то есть ветку НАЛИЧИЯ,
    где возврат совершенно уместен. Ложная находка той же природы, что и
    пропуск: у вопроса «та ли это ветка» два направления ошибки.
    """
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return any((isinstance(n, ast.Name) and n.id in names)
                   or (isinstance(n, ast.Attribute) and n.attr in names)
                   for n in ast.walk(test.operand))
    left = test.left if isinstance(test, ast.Compare) else None
    left_name = left.id if isinstance(left, ast.Name) else (
        left.attr if isinstance(left, ast.Attribute) else None)
    if isinstance(test, ast.Compare) and left_name in names and len(test.ops) == 1:
        op, cmp = test.ops[0], test.comparators[0]
        if isinstance(op, (ast.Is, ast.Eq)) and isinstance(cmp, ast.Constant) \
                and (cmp.value is None or cmp.value == "" or cmp.value == 0):
            return True
    if isinstance(test, ast.BoolOp):
        return any(_is_absence_test(v, names) for v in test.values)
    return False


def _absent_identity_outcome(fn: ast.AST, names: set[str],
                             is_helper: bool = False,
                             via_helpers: frozenset[str] | set[str] = frozenset(),
                             helper_outcomes: Optional[dict[str, str]] = None,
                             ) -> tuple[str, str]:
    """Классифицировать ветку «личности нет»: отказ или подстановка.

    Возврат ``(исход, пояснение)``. Разобрать не вышло ⇒ третий исход
    ``UNCHECKED``, а не молчаливое «значит, отказывает».
    """
    helper_outcomes = helper_outcomes or {}

    # (1) ДЕФОЛТ прямо в чтении. Подстановкой является только ПРАВДОПОДОБНЫЙ
    #     дефолт: `"0x0"` притворяется адресом и проходит любую проверку
    #     `if not wallet`. Пустая строка / None / 0 — наоборот, МЕТКА ОТСУТСТВИЯ:
    #     она заставляет вызывающего проверить, а не подменяет личность.
    for key, has_default, default in _env_reads_full(fn):
        if _is_identity(key) and has_default and default:
            return (ABSENT_FABRICATES,
                    f"личность подставлена правдоподобным дефолтом `{default!r}` прямо "
                    f"в чтении `{key}` — ветки «личности нет» не существует, а значение "
                    "проходит проверку на пустоту")

    if names:
        for node in ast.walk(fn):
            if not isinstance(node, ast.If) or not _is_absence_test(node.test, names):
                continue
            body = ast.Module(body=node.body, type_ignores=[])
            if any(isinstance(s, ast.Raise) for s in ast.walk(body)):
                return (ABSENT_REFUSES, "ветка «личности нет» поднимает исключение")
            for r in (n for n in ast.walk(body) if isinstance(n, ast.Return)):
                if r.value is None or (isinstance(r.value, ast.Constant)
                                       and r.value.value is None):
                    return (ABSENT_REFUSES, "ветка «личности нет» возвращает None")
                atoms = sorted({n.id for n in ast.walk(r.value) if isinstance(n, ast.Name)} |
                               {a.attr for a in ast.walk(r.value) if isinstance(a, ast.Attribute)})
                return (ABSENT_FABRICATES,
                        "ветка «личности нет» ВОЗВРАЩАЕТ значение "
                        f"({', '.join(atoms) or 'литерал'}) — потребитель не отличит его "
                        "от настоящего наблюдения")

    # (2) ветки нет. Это НЕ автоматически «не измерено»: если личность пришла от
    #     помощника, который сам отказывает, потребитель наследует его отказ.
    inherited = sorted(h for h in via_helpers
                       if helper_outcomes.get(h) == ABSENT_REFUSES)
    if inherited:
        return (ABSENT_REFUSES,
                f"своей ветки нет, но личность приходит от `{inherited[0]}`, который "
                "при отсутствии ОТКАЗЫВАЕТ — отказ наследуется")
    if is_helper:
        return (ABSENT_IDENTITY_SOURCE,
                "это САМ источник личности (возвращает прочитанный ключ); ветка "
                "«личности нет» решается у ПОТРЕБИТЕЛЯ, и там она и меряется")
    if not names:
        return (ABSENT_UNCHECKED, "чтение личности не связано с именем — разбор ветки невозможен")
    return (ABSENT_UNCHECKED, "ветки, проверяющей личность, в функции не найдено")


def _mock_branch_before_door(fn: ast.AST) -> Optional[str]:
    """Возврат мока в ветке режима-заглушки ДО любой внешней двери.

    ``if self.dry_run: return mock`` — по умолчанию ``dry_run=True``, поэтому
    это не редкий край, а ОБЫЧНЫЙ путь. Возврат — имя проверяемого признака.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        flags = {a.attr for a in ast.walk(node.test) if isinstance(a, ast.Attribute)} | \
                {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if not (flags & {"dry_run", "DRY_RUN"}):
            continue
        for s in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(s, ast.Return) and s.value is not None:
                if not (isinstance(s.value, ast.Constant) and s.value.value is None):
                    return "dry_run"
    return None


# ──────────────────────────── граф импортов ──────────────────────────────────

def _dotted(rel: str) -> str:
    p = rel[:-3] if rel.endswith(".py") else rel
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


def _imports_of(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # относительный импорт — вне вопроса о стене
                continue
            if node.module:
                out.add(node.module)
                for a in node.names:
                    out.add(f"{node.module}.{a.name}")
    return out


def _reachable_modules(start: str, edges: dict[str, set[str]]) -> set[str]:
    """Модули, достижимые от ``start`` по импортам — до неподвижной точки."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(m for m in edges.get(cur, set()) if m not in seen)
    return seen


# ─────────────────────────────── замеры ──────────────────────────────────────

def measure_book(root: Path) -> dict[str, Any]:
    """Производитель книги — из объявленной карты ступеней, НЕ своей копией."""
    try:
        from spa_core.monitoring.cio_component_map import STAGES
    except Exception as exc:                                   # pragma: no cover
        return {"verdict": "UNCHECKED", "reason": f"карта ступеней не читается: {exc}"}
    stage = next((s for s in STAGES if s.key == BOOK_STAGE_KEY), None)
    if stage is None:
        return {"verdict": "UNCHECKED",
                "reason": f"в карте ступеней нет ключа `{BOOK_STAGE_KEY}` — "
                          "объявление устарело, своей копии таблицы здесь нет"}
    module_rel = stage.module
    if not (root / module_rel).is_file():
        return {"verdict": "UNCHECKED",
                "reason": f"производитель книги `{module_rel}` в дереве не найден"}
    return {"verdict": "DECLARED", "module": module_rel, "product": stage.product,
            "dotted": _dotted(module_rel)}


def measure_identity_surface(root: Path) -> dict[str, Any]:
    """Задана ли личность нашего счёта поверхностями ДОСТАВКИ (не ambient)."""
    found: list[dict[str, str]] = []
    scanned = 0
    for sub in ENV_SURFACES:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in (".plist", ".sh", ".bash"):
                continue
            scanned += 1
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                for tok in IDENTITY_TOKENS:
                    if tok in line.upper() and "=" in line or (tok in line.upper() and "<key>" in line):
                        found.append({"file": p.relative_to(root).as_posix(),
                                      "line": line.strip()[:200]})
                        break
    return {"surfaces": list(ENV_SURFACES), "files_scanned": scanned,
            "assignments": found, "configured": bool(found),
            "note": ("ambient-окружение процесса замера НЕ читается: вердикт, "
                     "решаемый переменными запускающей оболочки, отвечает не на "
                     "тот вопрос")}


def measure_sources(root: Path) -> dict[str, Any]:
    """Кандидаты в независимые наблюдатели и разбор каждого."""
    candidates: list[dict[str, Any]] = []
    protocol_observers: list[str] = []
    addressish: set[str] = set()
    env_keys: set[str] = set()
    unmeasured: list[str] = []
    edges: dict[str, set[str]] = {}

    for sub in SCAN_ROOTS:
        for path in _iter_py(root, sub):
            rel = path.relative_to(root).as_posix()
            tree = _parse(path)
            if tree is None:
                unmeasured.append(rel)
                continue
            edges[_dotted(rel)] = _imports_of(tree)

            reads = _env_reads(tree)
            for key, _ in reads:
                env_keys.add(key)
                if _is_addressish(key):
                    addressish.add(key)
            identity_keys = sorted({k for k, _ in reads if _is_identity(k)})

            graph, _ = _module_call_graph(tree)
            door = _module_reaches_network(graph, tree)

            if not identity_keys:
                if door and rel.startswith("spa_core/adapters/"):
                    protocol_observers.append(rel)
                continue

            helpers = _identity_helpers(tree)
            attrs = _identity_attrs(tree)

            def _names_of(n: ast.AST) -> set[str]:
                own, _ = _binding_sources(n, helpers)
                # атрибут считается личностью у ТОГО, кто его проверяет
                used_attrs = {a.attr for a in ast.walk(n)
                              if isinstance(a, ast.Attribute) and a.attr in attrs}
                return own | used_attrs

            fns = [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and (any(_is_identity(k) for k, _ in _env_reads(n)) or _names_of(n))]
            # ДВА прохода: сперва сами источники личности, потом потребители —
            # иначе «отказ наследуется» измерить нечем.
            helper_outcomes: dict[str, str] = {}
            for fn in fns:
                if fn.name not in helpers:
                    continue
                hn, hv = _names_of(fn), _binding_sources(fn, helpers)[1]
                helper_outcomes[fn.name] = _absent_identity_outcome(
                    fn, hn, is_helper=True, via_helpers=hv)[0]

            per_fn: list[dict[str, Any]] = []
            for fn in fns:
                names, via = _names_of(fn), _binding_sources(fn, helpers)[1]
                outcome, why = _absent_identity_outcome(
                    fn, names, is_helper=fn.name in helpers,
                    via_helpers=via, helper_outcomes=helper_outcomes)
                per_fn.append({
                    "function": fn.name,
                    "reaches_network": _reaches_network(fn.name, graph),
                    "absent_identity": outcome,
                    "absent_identity_why": why,
                    "mock_branch": _mock_branch_before_door(fn),
                })
            candidates.append({
                "module": rel,
                "dotted": _dotted(rel),
                "identity_keys": identity_keys,
                "external_door": door,
                "walled_off": rel.startswith(FORBIDDEN_FOR_BOOK),
                "functions": per_fn,
            })

    return {"candidates": candidates, "protocol_observers": protocol_observers,
            "env_keys_total": len(env_keys),
            "env_keys_addressish": sorted(addressish),
            "identity_tokens": list(IDENTITY_TOKENS),
            "unmeasured_files": unmeasured, "import_edges": edges}


def measure_reachability(book: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    """Дотягивается ли производитель книги до кандидата по графу импортов."""
    if book.get("verdict") != "DECLARED":
        return {"verdict": ABSENT_UNCHECKED, "reason": "производитель книги не определён"}
    reach = _reachable_modules(book["dotted"], sources["import_edges"])
    hits = []
    for c in sources["candidates"]:
        if c["dotted"] in reach or any(r.startswith(c["dotted"] + ".") for r in reach):
            hits.append(c["module"])
    return {"verdict": "MEASURED", "modules_reachable": len(reach),
            "candidates_reachable": hits}


def measure(root: Path) -> dict[str, Any]:
    book = measure_book(root)
    sources = measure_sources(root)
    identity = measure_identity_surface(root)
    reach = measure_reachability(book, sources)
    return {"book": book, "sources": sources, "identity": identity, "reachability": reach}


# ──────────────────────────── вердикт по кандидату ───────────────────────────

def judge(meas: dict[str, Any]) -> dict[str, Any]:
    """Независим ли хоть один кандидат. Основания НЕЗАВИСИМО достаточны."""
    identity_configured = meas["identity"]["configured"]
    reachable = set(meas["reachability"].get("candidates_reachable") or [])
    verdicts: list[dict[str, Any]] = []

    for c in meas["sources"]["candidates"]:
        grounds: list[str] = []
        if not c["external_door"]:
            grounds.append("внешней двери нет — значение не приходит извне")
        if not identity_configured:
            grounds.append("личность нашего счёта не задана ни одной поверхностью доставки")
        if c["walled_off"]:
            grounds.append(f"живёт в `{FORBIDDEN_FOR_BOOK}` — инвариант #6 запрещает "
                           "владельцу книги его импортировать")
        elif c["module"] not in reachable:
            grounds.append("производитель книги до него не дотягивается по импортам")
        fabricating = [f["function"] for f in c["functions"]
                       if f["absent_identity"] == ABSENT_FABRICATES]
        unchecked = [f["function"] for f in c["functions"]
                     if f["absent_identity"] == ABSENT_UNCHECKED]
        if fabricating:
            grounds.append("без личности ПОДСТАВЛЯЕТ значение вместо отказа: "
                           + ", ".join(sorted(fabricating)))
        verdicts.append({
            "module": c["module"],
            "independent": not grounds,
            "grounds_against": grounds,
            "fabricating_functions": sorted(fabricating),
            "unchecked_functions": sorted(unchecked),
        })

    any_independent = any(v["independent"] for v in verdicts)
    return {"any_independent": any_independent,
            "verdict": "INDEPENDENT_OBSERVATION_EXISTS" if any_independent
                       else "NO_INDEPENDENT_OBSERVATION",
            "per_candidate": verdicts}


# ────────────────────────── положительный контроль ───────────────────────────

_CTL_INDEPENDENT = '''
import os, urllib.request

def get_supply_balance(asset):
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        raise RuntimeError("no identity")
    return _rpc(wallet)

def _rpc(wallet):
    return urllib.request.urlopen("https://rpc/" + wallet)
'''

_CTL_FABRICATES = '''
import os, urllib.request

MOCK = {"USDC": 40000.0}

def get_supply_balance(asset):
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        return MOCK[asset]
    return _rpc(wallet)

def _rpc(wallet):
    return urllib.request.urlopen("https://rpc/" + wallet)
'''

_CTL_NO_DOOR = '''
import os, json

def get_supply_balance(asset):
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        raise RuntimeError("no identity")
    return json.loads(open("data/current_positions.json").read())
'''

_CTL_PROTOCOL_ONLY = '''
import urllib.request

def fetch():
    return urllib.request.urlopen("https://api.llama.fi/pools")
'''


def positive_control(tmp: Optional[Path] = None) -> dict[str, Any]:
    """Пять половин, из них ДВЕ ОБРАТНЫЕ.

    Контроль, который умеет только «находить», проходит и у прибора, который
    находит ВСЕГДА — поэтому обратные половины здесь обязательны: наблюдатель
    протоколов кандидатом стать НЕ должен, а честный отказ без личности НЕ
    должен считаться подстановкой.
    """
    import tempfile

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(tmp or td)

        def _one(name: str, src: str, where: str) -> dict[str, Any]:
            d = base / name
            (d / Path(where).parent).mkdir(parents=True, exist_ok=True)
            (d / where).write_text(src)
            return measure_sources(d)

        # 1. настоящий независимый наблюдатель распознаётся кандидатом
        m = _one("indep", _CTL_INDEPENDENT, "spa_core/execution/probe.py")
        c = m["candidates"]
        checks.append({"name": "independent_source_is_a_candidate",
                       "ok": len(c) == 1 and c[0]["external_door"] is True
                            and c[0]["functions"][0]["absent_identity"] == ABSENT_REFUSES})

        # 2. подстановка вместо отказа распознаётся
        m = _one("fab", _CTL_FABRICATES, "spa_core/execution/probe.py")
        c = m["candidates"]
        checks.append({"name": "fabricating_source_is_named",
                       "ok": len(c) == 1
                            and c[0]["functions"][0]["absent_identity"] == ABSENT_FABRICATES})

        # 3. ОБРАТНАЯ: наблюдатель протоколов кандидатом НЕ становится
        m = _one("proto", _CTL_PROTOCOL_ONLY, "spa_core/adapters/probe.py")
        checks.append({"name": "protocol_observer_is_not_a_candidate",
                       "ok": m["candidates"] == []
                            and m["protocol_observers"] == ["spa_core/adapters/probe.py"]})

        # 4. ОБРАТНАЯ: отсутствие внешней двери не выдаётся за наблюдение
        m = _one("nodoor", _CTL_NO_DOOR, "spa_core/execution/probe.py")
        c = m["candidates"]
        checks.append({"name": "no_door_is_not_an_observation",
                       "ok": len(c) == 1 and c[0]["external_door"] is False})

        # 5. дверь ЗА ЦЕПОЧКОЙ помощников видна (неподвижная точка)
        m = _one("indep2", _CTL_INDEPENDENT, "spa_core/execution/probe.py")
        c = m["candidates"]
        checks.append({"name": "door_behind_helper_chain_is_seen",
                       "ok": len(c) == 1 and c[0]["functions"][0]["reaches_network"] is True})

    return {"checks": checks, "passed": all(x["ok"] for x in checks)}


# ─────────────────────────────── находки ─────────────────────────────────────

def _findings(meas: dict[str, Any], judged: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    book, src, ident = meas["book"], meas["sources"], meas["identity"]

    if book.get("verdict") != "DECLARED":
        out.append({"severity": "unchecked", "code": "BOOK_UNCHECKED",
                    "text": f"производитель книги не определён: {book.get('reason')}"})
    if src["unmeasured_files"]:
        out.append({"severity": "unchecked", "code": "PARSE_UNCHECKED",
                    "text": f"не разобрано файлов: {len(src['unmeasured_files'])} "
                            f"(напр. {src['unmeasured_files'][0]}) — «не измерено» "
                            "названо, а не засчитано в норму"})

    n_cand = len(src["candidates"])
    if not judged["any_independent"]:
        out.append({"severity": "critical", "code": "NO_INDEPENDENT_OBSERVATION",
                    "text": ("независимого наблюдения исхода книги НЕ существует "
                             f"сегодня: кандидатов {n_cand}, независимых 0. "
                             "Сверка «намерение против результата» (ADR-255) не "
                             "может быть оживлена правкой кода")})

    fabricating = sorted({v["module"] for v in judged["per_candidate"]
                          if v["fabricating_functions"]})
    if fabricating:
        out.append({"severity": "critical", "code": "IDENTITY_ABSENT_FABRICATES",
                    "text": ("без личности счёта источник ПОДСТАВЛЯЕТ значение вместо "
                             f"отказа — {len(fabricating)} модул(ь/я/ей): "
                             + ", ".join(fabricating)
                             + ". Подстановка того же ТИПА, что настоящее наблюдение, "
                               "поэтому соединить сверку с таким источником значило бы "
                               "получить ЛОЖНОЕ свидетельство, а не отсутствующее")})

    if not ident["configured"]:
        out.append({"severity": "warn", "code": "IDENTITY_NOT_CONFIGURED",
                    "text": ("личность нашего счёта не задана ни одной поверхностью "
                             f"доставки ({', '.join(ident['surfaces'])}; файлов "
                             f"просмотрено {ident['files_scanned']}) — привязать "
                             "наблюдение к нашей книге нечем")})

    walled = sorted({c["module"] for c in src["candidates"] if c["walled_off"]})
    if walled:
        out.append({"severity": "warn", "code": "WALLED_OFF_BY_INVARIANT_6",
                    "text": (f"{len(walled)} кандидат(ов) живут в `{FORBIDDEN_FOR_BOOK}` — "
                             "владельцу книги их импортировать запрещено инвариантом #6; "
                             "стена не обходится кодом, это решение владельца")})

    unchecked_fns = sorted({v["module"] for v in judged["per_candidate"]
                            if v["unchecked_functions"]})
    if unchecked_fns:
        out.append({"severity": "unchecked", "code": "ABSENT_BRANCH_UNCHECKED",
                    "text": ("ветка «личности нет» не разобрана у "
                             f"{len(unchecked_fns)} модул(я/ей): "
                             + ", ".join(unchecked_fns[:5]))})

    out.append({"severity": "info", "code": "PROTOCOL_OBSERVERS_MEASURED",
                "text": (f"ловушка заказа проверена ЗАМЕРОМ: {len(src['protocol_observers'])} "
                         "адаптер(ов) проходят внешнюю дверь и НЕ проходят субъекта "
                         "(наблюдают протоколы, а не нашу книгу) — кандидатами они "
                         "не стали")})
    return out


# ─────────────────────────────── сборка ──────────────────────────────────────

def run(root: str | Path | None = None, *, write: bool = True,
        now: datetime | None = None) -> dict[str, Any]:
    """Собрать отчёт. ``now`` — ВХОД, а не окружение."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    ts = (now or datetime.now(timezone.utc)).isoformat()

    control = positive_control()
    meas = measure(root)
    judged = judge(meas)
    findings = _findings(meas, judged)

    counts = {sev: sum(1 for f in findings if f["severity"] == sev)
              for sev in ("critical", "warn", "info", "unchecked")}
    if not control["passed"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["warn"]:
        overall = "WARN"
    else:
        overall = "OK"

    src = meas["sources"]
    doc = {
        "schema": "cio_outcome_independence/v1",
        "generated_at": ts,
        "overall": overall,
        "counts": counts,
        "positive_control": control,
        "verdict": judged["verdict"],
        "book": meas["book"],
        "identity": meas["identity"],
        "reachability": meas["reachability"],
        "candidates": [
            {k: v for k, v in c.items() if k != "import_edges"}
            for c in src["candidates"]
        ],
        "per_candidate_verdict": judged["per_candidate"],
        "control": {
            "protocol_observers": src["protocol_observers"],
            "env_keys_total": src["env_keys_total"],
            "env_keys_addressish": src["env_keys_addressish"],
            "identity_tokens": src["identity_tokens"],
        },
        "unmeasured_files": src["unmeasured_files"],
        "findings": findings,
        "advisory": ("ADVISORY: ничего не соединено, ни один вызов не изменён, "
                     "капитал не сдвинут. Оживить ступень сверки нельзя правкой "
                     "кода: нужны ДВА решения владельца — наблюдатель вне "
                     "`spa_core/execution/` (либо ослабление инварианта #6) И "
                     "реальный капитал на цепи, у которого есть что наблюдать."),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(root) / REPORT_REL))
    return doc


def main() -> int:
    doc = run(root=os.environ.get("SPA_ROOT") or None)
    print(f"cio_outcome_independence: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"unchecked={doc['counts']['unchecked']}) · вердикт: {doc['verdict']} · "
          f"кандидатов {len(doc['candidates'])}, независимых "
          f"{sum(1 for v in doc['per_candidate_verdict'] if v['independent'])}")
    for f in doc["findings"]:
        print(f"  [{f['severity'].upper()}] {f['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
