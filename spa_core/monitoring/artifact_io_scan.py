"""artifact_io_scan.py — кто ПИШЕТ и кто ЧИТАЕТ артефакт, по коду, а не по объявлению.

Зачем. ADR-158 поручил назначение сроков годности двум ролям, и обеим нужен один и тот же
вход: для артефакта — его писатель и его читатели. В манифесте это объявлено только у 25
артефактов из 89 найденных кандидатов; у остальных не объявлено ничего, а квитанции
потребления (`consumption_receipts`) пишутся только теми потребителями, кого уже
инструментировали. Значит связь надо ВЫВЕСТИ из кода.

Почему не поиском по строке. Первый (сырой) замер 28.08 искал литерал имени файла в тексте
модуля и выдал `KANBAN.json` как продукт `system_health_evening`, хотя тот его ЧИТАЕТ. Поиск
по вхождению не отличает запись от чтения, а перепутанные стороны дают перепутанный срок:
читателю назначили бы срок писателя. Поэтому здесь разбор синтаксиса (`ast`), а не текста.

Почему нужна таблица констант. Пути почти никогда не стоят в вызове литералом: реальные
вызовы выглядят как `atomic_save(doc, str(Path(data_dir) / STATUS_FILENAME))`. Без разрешения
имён модульного уровня разбор увидел бы вызов записи и НИ ОДНОГО имени файла — то есть тихо
вернул бы пусто там, где связь есть.

Fail-CLOSED: имя файла, которое не удалось разрешить, не относится ни к записи, ни к чтению —
оно просто не попадает в ответ. Догадок здесь нет: неразрешённое имя честнее отсутствия.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
from pathlib import Path

WRITE = "write"
READ = "read"

#: Вызовы, которые ЗАПИСЫВАЮТ артефакт. `atomic_save(data, path)` — путь ВТОРЫМ
#: аргументом (инвариант #5: прямой `open(..., "w")` на state-файлы запрещён, но
#: он встречается в не-state коде, поэтому учитывается тоже).
_WRITERS = {"atomic_save": 1, "atomic_save_text": 1, "write_text": 0, "dump": 1}
#: Вызовы, которые ЧИТАЮТ. `json.load(open(p))` разбирается через вложенный `open`.
_READERS = {"read_text": 0, "load": 0, "loads": 0, "open": 0, "_read_json": 0, "atomic_load": 0}

#: Помощники записи, у которых путь стоит на РАЗНОЙ позиции у разных авторов
#: (`_atomic_write_json(path, obj)` в одном модуле и `(data, path)` в другом),
#: поэтому просматриваются ВСЕ аргументы.
#:
#: Замер 2026-08-28: этих имён во флоте больше, чем канонического `atomic_save` —
#: `_atomic_write(` 656 вызовов, `_write_json(` 530, `_atomic_write_json(` 331.
#: Первая редакция сканера знала только `atomic_save`/`open(...,"w")` и потому не
#: видела ОСНОВНОЙ способ записи: из-за этого, например, оставалась невидимой
#: запись стоп-крана (`kill_switch_active.json`) телеграм-ботом. Низкое покрытие
#: на эталоне объяснялось не только вычисляемыми именами, как я решил сначала,
#: но и незнанием словаря записи.
_WRITE_ANY_ARG = {
    "_atomic_write", "_atomic_write_json", "_atomic_write_text", "_atomic_write_jsonl",
    "_atomic_write_rows", "atomic_write", "atomic_write_json", "atomic_write_text",
    "atomic_write_via_tmp", "_write_json", "write_json", "_save_json", "save_json",
}

#: Завершение атомарной записи, написанной вручную: `tmp` + `os.replace(tmp, dst)`.
#: Так пишут `self_heal.py`, `watchdog.py` и другие — и без этого идиома их продукт
#: не виден вовсе, хотя автор объявил его в докстринге. Имя `replace` берётся ТОЛЬКО
#: у `os`/`shutil`: голое `replace` — это `str.replace`, и оно встречается повсюду.
_RENAME_CALLS = {"replace", "rename", "move"}
_RENAME_MODULES = {"os", "shutil"}


def _is_rename_call(node: ast.Call) -> bool:
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr in _RENAME_CALLS
            and isinstance(f.value, ast.Name) and f.value.id in _RENAME_MODULES)

_SUFFIXES = (".json", ".jsonl")


def _is_artifact(name: str) -> bool:
    """У имени артефакта обязана быть ОСНОВА, а не один суффикс.

    `harness.py` пишет ``f"{self.agent_key}.json"``; разбор видит в этой строке
    константу ``".json"`` — и без этой проверки она становилась «артефактом»,
    из-за чего одиннадцать агентов семьи получали ложное «пишет мимо контракта».
    """
    stem = name.rsplit("/", 1)[-1]
    for suf in _SUFFIXES:
        if stem.endswith(suf):
            return len(stem) > len(suf)
    return False


def _name_table(node_body, seed: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """Имя переменной → имена артефактов, к которым она приводит.

    Не только константы модуля: путь почти всегда собирается через ЛОКАЛЬНУЮ
    переменную —

        ARTIFACT_REL = "agent_passports.json"      # константа модуля
        path = ddir / ARTIFACT_REL                 # локальная сборка
        atomic_save(audit(**kw), str(path))        # запись по имени `path`

    Разбор, знающий только константы модуля, увидел бы здесь вызов записи и НИ
    ОДНОГО имени файла — то есть молча вернул бы «этот модуль ничего не пишет».
    Именно так первая редакция и ответила про `agent_passports.py`.

    Таблица строится ПО ОБЛАСТЯМ ВИДИМОСТИ, а не одна на модуль. Первая редакция
    склеивала их — и немедленно соврала: в `agent_passports.py` имя `path` живёт
    в двух функциях, означая в одной артефакт агента, в другой манифест, и модуль
    получил `architecture/manifest.json: write`, хотя он манифест только читает.
    Ложный ПИСАТЕЛЬ дороже пропуска: артефакту назначат срок по расписанию чужого
    агента.

    Два прохода — чтобы присваивание, стоящее ниже по тексту, тоже разрешалось.
    """
    table: dict[str, set[str]] = {k: set(v) for k, v in (seed or {}).items()}

    def rhs(expr: ast.AST) -> set[str]:
        found: set[str] = set()
        for n in ast.walk(expr):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and _is_artifact(n.value):
                found.add(n.value)
            elif isinstance(n, ast.Name):
                found |= table.get(n.id, set())
            elif isinstance(n, ast.Attribute):
                found |= table.get(n.attr, set())
        return found

    for _ in range(2):
        for node in _own_nodes(node_body):
            if isinstance(node, ast.Assign) and node.value is not None:
                got = rhs(node.value)
                if got:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            table.setdefault(t.id, set()).update(got)
            elif isinstance(node, ast.AnnAssign) and node.value is not None \
                    and isinstance(node.target, ast.Name):
                got = rhs(node.value)
                if got:
                    table.setdefault(node.target.id, set()).update(got)
    return table


def _names_in(expr: ast.AST, table: dict[str, set[str]]) -> set[str]:
    """Имена артефактов внутри выражения-пути: литералы + разрешённые переменные.

    Берётся всё поддерево, потому что путь — это выражение
    (`str(Path(d) / SUB / NAME)`), и имя файла может лежать на любой его глубине.
    """
    found: set[str] = set()
    for n in ast.walk(expr):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _is_artifact(n.value):
            found.add(n.value)
        elif isinstance(n, ast.Name):
            found |= table.get(n.id, set())
        elif isinstance(n, ast.Attribute):
            found |= table.get(n.attr, set())
    return found


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _open_mode_is_write(node: ast.Call) -> bool:
    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        return "w" in str(node.args[1].value) or "a" in str(node.args[1].value)
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return "w" in str(kw.value.value) or "a" in str(kw.value.value)
    return False


_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _own_nodes(body):
    """Узлы ЭТОЙ области: тело без спуска во вложенные функции и классы.

    Обрезать обязано ЗДЕСЬ, а не флагом при выдаче: `ast.walk` уже спустился бы
    внутрь, и первая редакция именно так и продолжала склеивать области — имя
    `path` из двух разных функций снова оказывалось в одной таблице, и модуль
    получал ложную запись в манифест. Поэтому обход свой, с явным отказом
    класть вложенное определение в стек.
    """
    stack = [n for n in body if not isinstance(n, _NESTED)]
    while stack:
        n = stack.pop()
        yield n
        for child in ast.iter_child_nodes(n):
            if isinstance(child, _NESTED):
                continue
            stack.append(child)


def _scopes(tree: ast.Module):
    """(тело, «это модульный уровень») для модуля и каждой функции/метода."""
    yield tree.body, True
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n.body, False


def scan_source(src: str) -> dict[str, set[str]]:
    """{имя артефакта: {"write"|"read"}} для одного модуля. Синтаксис битый ⇒ пусто."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    module_table = _name_table(tree.body)
    out: dict[str, set[str]] = {}

    def mark(names: set[str], kind: str) -> None:
        for n in names:
            out.setdefault(n, set()).add(kind)

    for body, is_module in _scopes(tree):
        table = module_table if is_module else _name_table(body, seed=module_table)
        for node in _own_nodes(body):
                if not isinstance(node, ast.Call):
                    continue
                fname = _call_name(node)
                if fname is None:
                    continue
                if fname == "open":
                    kind = WRITE if _open_mode_is_write(node) else READ
                    if node.args:
                        mark(_names_in(node.args[0], table), kind)
                elif _is_rename_call(node):
                    # Назначение — второй аргумент; временный файл первым не мешает
                    # (`x.json.tmp` не проходит проверку основы имени).
                    for arg in node.args:
                        mark(_names_in(arg, table), WRITE)
                elif fname in _WRITE_ANY_ARG:
                    for arg in list(node.args) + [k.value for k in node.keywords]:
                        mark(_names_in(arg, table), WRITE)
                elif fname in _WRITERS:
                    if fname == "write_text":
                        if isinstance(node.func, ast.Attribute):
                            mark(_names_in(node.func.value, table), WRITE)
                    else:
                        idx = _WRITERS[fname]
                        if len(node.args) > idx:
                            mark(_names_in(node.args[idx], table), WRITE)
                elif fname in _READERS:
                    if fname == "read_text" and isinstance(node.func, ast.Attribute):
                        mark(_names_in(node.func.value, table), READ)
                    elif node.args:
                        mark(_names_in(node.args[0], table), READ)
    return out


def scan_file(path: str | Path) -> dict[str, set[str]]:
    p = Path(path)
    try:
        return scan_source(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def _imports(src: str) -> set[str]:
    """Модули проекта, импортируемые исходником (spa_core.* / scripts.*)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names:
                if al.name.startswith(("spa_core.", "scripts.")):
                    out.add(al.name)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            if n.module.startswith(("spa_core", "scripts")):
                out.add(n.module)
                for al in n.names:
                    out.add(f"{n.module}.{al.name}")
    return out


def closure(module: str, repo: Path, depth: int = 3) -> list[str]:
    """Модуль и то, что он тянет за собой, вглубь до `depth`.

    Нужно потому, что агент почти никогда не пишет артефакт сам: точка входа
    делегирует ниже. Сканирование ОДНОГО модуля точки входа нашло 4 писателя из
    27 объявленных в манифесте — не потому, что связи нет, а потому, что
    смотрели не туда.
    """
    seen: set[str] = set()
    frontier = [module]
    for _ in range(depth + 1):
        nxt: list[str] = []
        for m in frontier:
            if m in seen:
                continue
            seen.add(m)
            f = repo / (m.replace(".", "/") + ".py")
            if not f.is_file():
                continue
            try:
                nxt.extend(_imports(f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
        frontier = nxt
    return sorted(seen)


def writers_by_agent(entry_modules: dict[str, str], repo: Path) -> dict[str, set[str]]:
    """{артефакт: {агенты, в замыкании которых есть ЛИТЕРАЛЬНАЯ запись}}.

    Больше одного кандидата ⇒ это НЕ ответ, а двусмысленность: общий модуль,
    попавший в замыкание нескольких агентов, припишет свой артефакт им всем.
    Разрешать её угадыванием нельзя — ложный писатель получает чужое расписание,
    а значит чужой срок годности. Возвращается как есть; решает вызывающий.
    """
    out: dict[str, set[str]] = {}
    for label, mod in entry_modules.items():
        for m in closure(mod, repo):
            f = repo / (m.replace(".", "/") + ".py")
            if not f.is_file():
                continue
            for art, kinds in scan_file(f).items():
                if WRITE in kinds:
                    out.setdefault(art.split("/")[-1], set()).add(label)
    return out
