#!/usr/bin/env python3
"""ГРОМКОСТЬ индексирующего чтения ЗА ГРАНИЦЕЙ СВОЕЙ ФУНКЦИИ — тоже измерима.

# LLM_FORBIDDEN

**Что это закрывает.** ADR-949 измерил громкость 78 индексирующих чтений `x[k]`
производного имени и объявил СВОЮ границу дословно:

> Подъём кончается на границе области связывания (`FunctionDef`/`Lambda`/`Module`),
> и `x[k]`, громкий внутри своей функции, может быть заглушён `try` у ВЫЗЫВАЮЩЕГО.
> Население ЭТОЙ формы прибором НЕ ИЗМЕРЕНО.

Заказ G938 п. 2 назвал эту границу крупнейшей объявленной дырой класса и велел
закрыть её ТЕМ ЖЕ порядком: **контроль на известном члене → население → только
потом род.** Ошибка обязана идти в сторону `unmeasured`, а НЕ в сторону `loud`:
«громко» снимает чтение с приоритета, и снять его неверно дороже, чем оставить.

**Контроль НАЙДЕН на настоящем члене дерева, а не только на сценах.**
`spa_core/monitoring/reachability_of_the_rest.py` объявляет `_cross`, внутри
которого лежит громкое `cross[…]`, и зовёт её на строке 395 из тела
`try: … except Exception` — причём код сам говорит вслух, ЗАЧЕМ:

    # Перехват живёт ТОЛЬКО в контроле — в замере
    # тот же `KeyError` остаётся громким по построению (ADR-469).

То есть громкость чтения есть свойство ПУТИ, а не самого чтения, и путей у одного
чтения бывает несколько. Прибор отвечает про ХУДШИЙ путь: нашёлся глушитель хоть на
одном — «пустота замечена громко» утверждать уже нельзя.

**Три исхода** (инв. #17), и `loud` здесь ТРЕБУЕТ ДОКАЗАТЕЛЬСТВА, а не достаётся
умолчанием:

| исход | что значит |
|---|---|
| `silenced` | в замыкании звавших НАЗВАН глушитель: вызов стои́т в теле `try` с ловящим обработчиком |
| `loud` | замыкание звавших ПЕРЕЧИСЛЕНО ПОЛНОСТЬЮ, оборвано на точке входа, и глушителя нет НИ НА ОДНОМ пути |
| `unmeasured` | замыкание перечислить нечем (одноимённый непривязанный вызов · звавшего в дереве нет вовсе · метод · предел подъёма · неразобранный род обработчика · охрана у звавшего · имя добывается строкой) |

**Почему «звавшего в дереве нет вовсе» — это `unmeasured`, а не `loud`.** Функция,
которую не зовёт ни одна строка дерева, зовётся ИЗВНЕ — каркасом (обработчик
маршрута FastAPI), планировщиком, чужим процессом, — и этот звавший обычно как раз
ловит всё. Назвать такую функцию громкой значило бы ошибиться в опасную сторону.

**Привязка вызова — к ОБЪЯВЛЯЮЩЕМУ МОДУЛЮ, а не к голому имени** (дословный урок
ADR-941/942). Голое имя сливает незнакомцев: `measure` в дереве зовут 2374 раза, и
почти все эти вызовы — ЧУЖИЕ `measure`. Поэтому у каждого вызова спрашивается, к
чьему объявлению он привязан, и ответов ТРИ: `ours` · `other` · `unknown`; хотя бы
один `unknown` на имя делает исход `unmeasured`.

**Чего прибор НЕ считает глушителем у звавшего и почему.** ОХРАНА (`if NAME:`)
глушителем у звавшего не является и не является отсутствием глушителя: над пустым
перечнем вызов просто не случится, пустота останется незамеченной ТИХО, — но связать
охраняемое имя звавшего с НАШИМ перечнем нечем, и потому это `unmeasured`, а не
исход в любую из двух сторон. Внутри области связывания охрана считается глушителем
(ADR-949) — там имя то же самое, и это ДРУГОЙ вопрос, а не то же самое послабее.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from spa_core.monitoring import declared_collection_census as census_mod
from spa_core.tests import _empty_collection_harm as harm
from spa_core.tests import _subscript_silencer as sil

#: Сколько уровней звавших прибор проходит. ВЫБОР, а не свойство дерева; исчерпание
#: предела — ТРЕТИЙ исход, а не `loud`.
CALLER_HOPS = 6

#: Исходы вопроса. «Не измерено» ни за один из двух не выдаётся (инв. #17).
OUTCOMES: Tuple[str, ...] = ("loud", "silenced", "unmeasured")

#: Роды глушителя У ЗВАВШЕГО. Охрана сюда НЕ входит — см. докстринг модуля.
#: `with` — менеджер контекста, ГЛОТАЮЩИЙ исключение (`pytest.raises`,
#: `assertRaises`, `contextlib.suppress`): он ловит не хуже `except`, и не спросить
#: про него значило бы назвать такое чтение `loud`, то есть ошибиться в ОПАСНУЮ
#: сторону.
SILENCER_KINDS: Tuple[str, ...] = ("try", "with")

#: Менеджеры контекста, ГЛОТАЮЩИЕ названный род исключения.
SWALLOWING_MANAGERS: Tuple[str, ...] = (
    "raises", "assertRaises", "assertRaisesRegex", "suppress",
)

#: Декораторы, НЕ меняющие ни звавшего, ни судьбу исключения. Всё остальное делает
#: замыкание НЕперечислимым: `@router.get` означает, что функцию зовёт КАРКАС, и
#: восемь вызовов из тестов полным набором звавших не являются (замер 08.11:
#: `_public_view` выходил `loud` ровно на этом, и это ошибка в опасную сторону).
TRANSPARENT_DECORATORS = frozenset({
    "property", "staticmethod", "classmethod", "cached_property", "override",
    "final", "abstractmethod", "wraps", "lru_cache", "cache", "dataclass",
})

#: Чем оборвано замыкание, когда исход `loud`. Считаются ОТДЕЛЬНО.
ENTRY_KINDS: Tuple[str, ...] = ("module_level", "pytest_test")

#: Привязка одного вызова к объявлению.
OURS, OTHER, UNKNOWN = "ours", "other", "unknown"

#: Формы, которыми имя добывается СТРОКОЙ. Присутствие имени в такой форме делает
#: замыкание неперечислимым: вызов есть, а синтаксического вызова нет.
DYNAMIC_LOOKUPS: Tuple[str, ...] = ("getattr", "globals", "vars", "eval", "exec")


#: `try` и `try/except*` — один вопрос. Вторая форма появилась в 3.11; её
#: отсутствие в разборе означало бы молчаливое `loud` на группе исключений.
TRY_NODES: Tuple[type, ...] = ((ast.Try, ast.TryStar) if hasattr(ast, "TryStar")
                               else (ast.Try,))


def _swallowing_with(node: ast.AST) -> Optional[Tuple[str, Optional[str], str]]:
    """Вердикт, если ``with`` ГЛОТАЕТ род исключения, иначе ``None``.

    ``None`` означает «этот `with` ничего не глотает» — подъём продолжается. Род,
    собранный выражением, даёт ТРЕТИЙ исход, а не «не глотает».
    """
    for item in getattr(node, "items", []):
        expr = item.context_expr
        if not isinstance(expr, ast.Call):
            continue
        fn = expr.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name not in SWALLOWING_MANAGERS:
            continue
        if not expr.args:
            return ("unmeasured", None,
                    f"`with …{name}()` без названного рода — глотает или нет, "
                    "из формы не следует")
        caught: List[str] = []
        for arg in expr.args:
            if isinstance(arg, ast.Name):
                caught.append(arg.id)
            elif isinstance(arg, ast.Attribute):
                caught.append(arg.attr)
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                continue          # `match=` строкой — не род
            else:
                return ("unmeasured", None,
                        f"род у `with …{name}(…)` НЕ РАЗОБРАН")
        if set(caught) & sil.SILENCING_EXCEPTIONS:
            return ("silenced", "with",
                    f"вызов в теле `with …{name}({sorted(caught)})` — глотает")
    return None


def module_of(rel: str) -> str:
    """Точечное имя модуля по пути файла. ``pkg/__init__.py`` → ``pkg``."""
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def reader_files(root: Path) -> List[Path]:
    """Поверхность поиска звавших — ТА ЖЕ дверь, что у переписи.

    Своего перечня каталогов здесь нет намеренно: разойдись он с
    ``census_mod.READER_ROOTS``, и прибор отвечал бы про ДРУГОЕ дерево, чем ось.
    """
    return census_mod._iter_py_files(root, census_mod.READER_ROOTS)


class ModuleFacts:
    """Что нужно знать о модуле, чтобы привязать его вызовы к объявлениям."""

    __slots__ = ("rel", "module", "tree", "index", "module_defs",
                 "imported", "aliases", "calls", "dynamic_names", "reason")

    def __init__(self, rel: str, tree: Optional[ast.Module], reason: Optional[str]):
        self.rel = rel
        self.module = module_of(rel)
        self.tree = tree
        self.reason = reason
        self.index: Dict[int, ast.AST] = {}
        self.module_defs: Set[str] = set()
        self.imported: Dict[str, Tuple[str, str]] = {}
        self.aliases: Dict[str, str] = {}
        self.calls: List[ast.Call] = []
        self.dynamic_names: Set[str] = set()
        if tree is not None:
            self._collect()

    def _collect(self) -> None:
        tree = self.tree
        assert tree is not None
        self.index = harm._parents(tree)
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.module_defs.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        self.module_defs.add(tgt.id)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    local = alias.asname or alias.name
                    self.imported[local] = (base, alias.name)
                    # `from pkg import mod as a` неотличимо от `from pkg import name`
                    # без импорта пакета — поэтому ОБА прочтения живут рядом.
                    self.aliases[local] = f"{base}.{alias.name}" if base else alias.name
                    self.module_defs.add(local)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    self.aliases[local] = (alias.name if alias.asname
                                           else alias.name.split(".")[0])
                    self.module_defs.add(local)
            elif isinstance(node, ast.Call):
                self.calls.append(node)
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
                if name in DYNAMIC_LOOKUPS:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            self.dynamic_names.add(arg.value)
            elif isinstance(node, ast.Subscript):
                # `globals()["имя"]` — индексация, а не аргумент вызова.
                sl = node.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str) \
                        and isinstance(node.value, ast.Call):
                    fn = node.value.func
                    nm = (fn.id if isinstance(fn, ast.Name)
                          else fn.attr if isinstance(fn, ast.Attribute) else None)
                    if nm in DYNAMIC_LOOKUPS:
                        self.dynamic_names.add(sl.value)


def load_surface(root: Path) -> Tuple[Dict[str, ModuleFacts], Dict[str, str]]:
    """Факты по каждому файлу поверхности. Второе — НЕПРОЧИТАННЫЕ, с причиной."""
    facts: Dict[str, ModuleFacts] = {}
    unread: Dict[str, str] = {}
    for path in reader_files(root):
        rel = path.relative_to(root).as_posix()
        tree, why = census_mod._parse(path)
        facts[rel] = ModuleFacts(rel, tree, why)
        if tree is None:
            unread[rel] = why or "причина не названа"
    return facts, unread


def _dotted(node: ast.expr) -> Optional[str]:
    """Точечное имя у цепочки ``a.b.c``, либо ``None``."""
    parts: List[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _locally_bound(call: ast.Call, name: str, facts: ModuleFacts) -> bool:
    """Связано ли ``name`` ВНУТРИ области, где стои́т вызов (параметр, присваивание)."""
    cur: Optional[ast.AST] = facts.index.get(id(call))
    for _hop in range(census_mod.SCOPE_DEPTH):
        if cur is None:
            return False
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = cur.args
            for group in (args.posonlyargs, args.args, args.kwonlyargs):
                if any(a.arg == name for a in group):
                    return True
            for solo in (args.vararg, args.kwarg):
                if solo is not None and solo.arg == name:
                    return True
            if not isinstance(cur, ast.Lambda):
                for node in ast.walk(cur):
                    if isinstance(node, ast.Name) and node.id == name \
                            and isinstance(node.ctx, ast.Store):
                        return True
            return False
        cur = facts.index.get(id(cur))
    return False


def binding_of(call: ast.Call, facts: ModuleFacts,
               target_rel: str, fname: str, is_method: bool) -> str:
    """К чьему объявлению привязан вызов: :data:`OURS` · :data:`OTHER` · :data:`UNKNOWN`."""
    target_mod = module_of(target_rel)
    fn = call.func
    if isinstance(fn, ast.Name):
        local = fn.id
        imported = facts.imported.get(local)
        if imported is not None:
            return OURS if imported == (target_mod, fname) else OTHER
        if local != fname:
            return OTHER
        if facts.rel == target_rel:
            # Своё объявление — если его не затенило локальное связывание.
            return UNKNOWN if _locally_bound(call, local, facts) else OURS
        if local in facts.module_defs:
            return OTHER          # у модуля СВОЁ объявление этого имени
        if _locally_bound(call, local, facts):
            return UNKNOWN        # параметр или локальная переменная
        return OTHER              # встроенное имя либо вообще не связано
    if isinstance(fn, ast.Attribute):
        if fn.attr != fname:
            return OTHER
        dotted = _dotted(fn.value)
        if dotted is not None:
            head, _, _rest = dotted.partition(".")
            resolved = facts.aliases.get(head)
            whole = (dotted if resolved is None
                     else (resolved + dotted[len(head):]))
            if resolved is not None or dotted.startswith(("spa_core.", "scripts.")):
                return OURS if whole == target_mod else OTHER
            return UNKNOWN if is_method else OTHER
        return UNKNOWN if is_method else OTHER
    return OTHER


def enclosing_callable(node: ast.AST, facts: ModuleFacts
                       ) -> Tuple[Optional[ast.AST], bool]:
    """Ближайшая объемлющая вызываемая область и признак «это метод»."""
    cur: Optional[ast.AST] = facts.index.get(id(node))
    in_class = False
    for _hop in range(census_mod.SCOPE_DEPTH):
        if cur is None:
            return None, False
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = facts.index.get(id(cur))
            while isinstance(owner, (ast.If, ast.Try, ast.With, ast.AsyncWith)):
                owner = facts.index.get(id(owner))
            in_class = isinstance(owner, ast.ClassDef)
            return cur, in_class
        if isinstance(cur, ast.Lambda):
            return cur, False
        if isinstance(cur, ast.Module):
            return None, False
        cur = facts.index.get(id(cur))
    return None, False


def silencer_at_site(call: ast.Call, facts: ModuleFacts
                     ) -> Tuple[str, Optional[str], str]:
    """Глушитель вокруг ОДНОГО вызова: ``(вердикт, род, причина)``.

    Вердикт — `silenced` · `unmeasured` · `none`. `none` означает «на этом участке
    глушителя нет», а НЕ «громко»: решение о громкости принимает замыкание.
    """
    arg_names = {a.id for a in call.args if isinstance(a, ast.Name)}
    arg_names |= {kw.value.id for kw in call.keywords
                  if isinstance(kw.value, ast.Name)}
    child: ast.AST = call
    cur: Optional[ast.AST] = facts.index.get(id(call))
    for _hop in range(sil.CLIMB_DEPTH):
        if cur is None:
            return "unmeasured", None, "подъём вышел за разбор — область не найдена"
        if isinstance(cur, (ast.With, ast.AsyncWith)) \
                and any(harm._contains(stmt, child) for stmt in cur.body):
            verdict = _swallowing_with(cur)
            if verdict is not None:
                return verdict
        if isinstance(cur, TRY_NODES) \
                and any(harm._contains(stmt, child) for stmt in cur.body):
            for handler in cur.handlers:
                caught = sil.handler_catches(handler)
                if caught is None:
                    return ("unmeasured", None,
                            "род ловимого исключения у звавшего НЕ РАЗОБРАН")
                if sil.BARE in caught or (set(caught) & sil.SILENCING_EXCEPTIONS):
                    return ("silenced", "try",
                            f"вызов в теле `try`, обработчик ловит {sorted(caught)}")
        if isinstance(cur, ast.If) \
                and any(harm._contains(stmt, child) for stmt in cur.body):
            for name in sorted(arg_names):
                why = sil._guard_silences(cur.test, name)
                if why is not None:
                    return ("unmeasured", None,
                            f"охрана у звавшего ({why}) — связать охраняемое имя "
                            "`" + name + "` с НАШИМ перечнем нечем")
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.Lambda, ast.Module)):
            return "none", None, "глушителя вокруг вызова нет"
        child, cur = cur, facts.index.get(id(cur))
    return "unmeasured", None, f"подъём длиннее предела ({sil.CLIMB_DEPTH})"


def call_sites(fname: str, target_rel: str, is_method: bool,
               facts: Dict[str, ModuleFacts]
               ) -> Tuple[List[Tuple[str, ast.Call]], List[str], List[str]]:
    """Вызовы, привязанные к объявлению. Второе — НЕПРИВЯЗАННЫЕ, третье — строковые."""
    ours: List[Tuple[str, ast.Call]] = []
    unknown: List[str] = []
    dynamic: List[str] = []
    for rel, mod in facts.items():
        if mod.tree is None:
            continue
        if fname in mod.dynamic_names:
            dynamic.append(rel)
        for call in mod.calls:
            verdict = binding_of(call, mod, target_rel, fname, is_method)
            if verdict == OURS:
                ours.append((rel, call))
            elif verdict == UNKNOWN:
                unknown.append(f"{rel}:{call.lineno}")
    return ours, unknown, dynamic


def opaque_decorator(func: ast.AST) -> Optional[str]:
    """Имя декоратора, из-за которого замыкание звавших НЕперечислимо, либо ``None``."""
    for dec in getattr(func, "decorator_list", []):
        node = dec.func if isinstance(dec, ast.Call) else dec
        name = (node.id if isinstance(node, ast.Name)
                else node.attr if isinstance(node, ast.Attribute) else None)
        if name is None:
            return "<декоратор выражением>"
        if name not in TRANSPARENT_DECORATORS:
            return name
    return None


def _is_pytest_test(func: ast.AST, rel: str) -> bool:
    name = getattr(func, "name", "")
    return name.startswith("test_") and ("tests/" in rel or "/test_" in f"/{rel}")


def _decorator_of(rel: str, name: str,
                  facts: Dict[str, ModuleFacts]) -> Optional[str]:
    """Опаковый декоратор у объявления ``name`` в модуле ``rel``, либо ``None``."""
    mod = facts.get(rel)
    if mod is None or mod.tree is None:
        return None
    for node in ast.walk(mod.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            opaque = opaque_decorator(node)
            if opaque is not None:
                return opaque
    return None


def loudness_through_callers(target_rel: str, fname: str, is_method: bool,
                             facts: Dict[str, ModuleFacts]
                             ) -> Dict[str, Any]:
    """Громкость чтения с учётом замыкания звавших. Три исхода :data:`OUTCOMES`.

    **Порядок вопросов не косметический: ГЛУШИТЕЛЬ спрашивается ПЕРВЫМ.**
    Найденный глушитель есть ДОКАЗАТЕЛЬСТВО по одному пути, и никакая неполнота
    замыкания его не отменяет: декоратор, непривязанный однофамилец и предел
    подъёма мешают доказать `loud`, а не опровергнуть `silenced`. Обратный порядок
    (так была написана первая редакция) понижал НАЙДЕННЫЙ глушитель
    `open_class_counter_census` до `unmeasured` — то есть терял находку.

    Поэтому препятствия СОБИРАЮТСЯ, а не прерывают обход: сначала пройдены все
    достижимые привязанные пути в поиске глушителя, и только потом, если его нет,
    препятствия решают между `loud` и `unmeasured`.
    """
    frontier: List[Tuple[str, str, bool]] = [(target_rel, fname, is_method)]
    seen: Set[Tuple[str, str]] = set()
    entries: Dict[str, int] = {kind: 0 for kind in ENTRY_KINDS}
    blockers: List[str] = []
    revisited = 0
    for hop in range(CALLER_HOPS):
        nxt: List[Tuple[str, str, bool]] = []
        for rel, name, method in frontier:
            if (rel, name) in seen:
                revisited += 1
                continue
            seen.add((rel, name))
            ours, unknown, dynamic = call_sites(name, rel, method, facts)

            # ─── ПЕРВЫМ делом глушитель: доказательство по одному пути ───
            pending: List[Tuple[str, ast.Call]] = []
            for site_rel, call in ours:
                verdict, kind, why = silencer_at_site(call, facts[site_rel])
                if verdict == "silenced":
                    return {"loudness": "silenced", "silencer": kind, "entry": None,
                            "hops": hop, "why": f"{site_rel}:{call.lineno} — {why}"}
                if verdict == "unmeasured":
                    blockers.append(f"{site_rel}:{call.lineno} — {why}")
                    continue
                pending.append((site_rel, call))

            # ─── и только потом препятствия полноте ───
            if dynamic:
                blockers.append(f"имя `{name}` добывается СТРОКОЙ в {len(dynamic)} "
                                f"файл(ах) ({dynamic[0]}) — замыкание неперечислимо")
            if unknown:
                blockers.append(f"одноимённых вызовов `{name}`, не привязанных к "
                                f"объявляющему модулю: {len(unknown)} ({unknown[0]})")
            if not ours:
                blockers.append(f"`{name}` не зовёт ни одна строка поверхности — "
                                "звавший ВНЕ дерева (каркас, точка входа)")
            opaque = _decorator_of(rel, name, facts)
            if opaque is not None:
                blockers.append(f"`{name}` несёт декоратор `@{opaque}` — звавший "
                                "назначается ИМ (каркас, планировщик)")

            for site_rel, call in pending:
                encl, encl_method = enclosing_callable(call, facts[site_rel])
                if encl is None:
                    entries["module_level"] += 1
                    continue
                if _is_pytest_test(encl, site_rel):
                    entries["pytest_test"] += 1
                    continue
                encl_name = getattr(encl, "name", None)
                if encl_name is None:
                    blockers.append(f"{site_rel}:{call.lineno} — вызов внутри "
                                    "`lambda`: у области нет имени")
                    continue
                nxt.append((site_rel, encl_name, encl_method))
        if not nxt:
            if blockers:
                # Названы ВСЕ препятствия, а не первое: порядок обхода не есть
                # свойство дерева, и «причина», зависящая от него, читалась бы как
                # полная, будучи произвольной.
                named = " · ".join(dict.fromkeys(blockers))
                return {"loudness": "unmeasured", "silencer": None, "entry": None,
                        "hops": hop, "blockers": len(blockers),
                        "why": (f"глушителя не найдено, но замыкание НЕ полно "
                                f"({len(blockers)} препятств.): {named}")}
            if sum(entries.values()) == 0:
                return {"loudness": "unmeasured", "silencer": None, "entry": None,
                        "hops": hop,
                        "why": ("замыкание звавших замкнулось в ЦИКЛ и не дошло ни "
                                f"до одной точки входа (повторных узлов {revisited})")}
            return {"loudness": "loud", "silencer": None, "entry": dict(entries),
                    "hops": hop,
                    "why": ("замыкание звавших ПЕРЕЧИСЛЕНО и оборвано на точках "
                            f"входа {dict(entries)} — глушителя нет ни на одном пути")}
        frontier = nxt
    return {"loudness": "unmeasured", "silencer": None, "entry": None,
            "hops": CALLER_HOPS,
            "why": f"замыкание звавших длиннее предела ({CALLER_HOPS})"}


def _subscript_at(facts: ModuleFacts, name: str, lineno: int) -> Optional[ast.Subscript]:
    if facts.tree is None:
        return None
    for node in ast.walk(facts.tree):
        if isinstance(node, ast.Subscript) and node.lineno == lineno \
                and isinstance(node.value, ast.Name) and node.value.id == name:
            return node
    return None


def caller_reads(root: Optional[Path] = None) -> Dict[str, Any]:
    """Громкость ЗА границей своей функции у каждого `loud`-чтения ADR-949.

    Вход берётся ЕДИНСТВЕННОЙ дверью :func:`_subscript_silencer.subscript_reads` —
    своей копии замера здесь нет, и расхождение с ADR-949 стало бы видно сразу.
    """
    root = root or harm.REPO_ROOT
    base = sil.subscript_reads(root)
    facts, unread = load_surface(root)
    tally = {outcome: 0 for outcome in OUTCOMES}
    kinds = {kind: 0 for kind in SILENCER_KINDS}
    entries = {kind: 0 for kind in ENTRY_KINDS}
    rows: List[Dict[str, Any]] = []
    for row in base["rows"]:
        if row["loudness"] != "loud":
            continue
        rel, name, lineno = row["module"], row["name"], row["lineno"]
        mod = facts.get(rel)
        if mod is None or mod.tree is None:
            tally["unmeasured"] += 1
            rows.append({**row, "loudness": "unmeasured", "silencer": None,
                         "why": (f"модуль чтения `{rel}` вне поверхности звавших "
                                 "либо НЕ ПРОЧИТАН")})
            continue
        sub = _subscript_at(mod, name, lineno)
        if sub is None:
            tally["unmeasured"] += 1
            rows.append({**row, "loudness": "unmeasured", "silencer": None,
                         "why": "чтение не найдено повторным разбором"})
            continue
        encl, is_method = enclosing_callable(sub, mod)
        encl_name = getattr(encl, "name", None) if encl is not None else None
        if encl_name is None:
            tally["unmeasured"] += 1
            rows.append({**row, "loudness": "unmeasured", "silencer": None,
                         "why": ("чтение вне именованной функции — звавшего спросить "
                                 "нечем")})
            continue
        verdict = loudness_through_callers(rel, encl_name, is_method, facts)
        tally[verdict["loudness"]] += 1
        if verdict["silencer"] is not None:
            kinds[verdict["silencer"]] += 1
        for kind, count in (verdict.get("entry") or {}).items():
            entries[kind] += count
        rows.append({**row, "func": encl_name, "is_method": is_method,
                     "loudness": verdict["loudness"],
                     "silencer": verdict["silencer"],
                     "hops": verdict["hops"], "why": verdict["why"]})
    return {"tally": tally, "silencer_kinds": kinds, "entries": entries,
            "rows": rows, "input_tally": base["tally"],
            "scope": {**base["scope"],
                      "reader_roots": list(census_mod.READER_ROOTS),
                      "reader_files": len(facts),
                      "caller_hops": CALLER_HOPS},
            "unread_readers": unread}
