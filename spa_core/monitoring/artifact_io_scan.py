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


#: ── ПОЗИЦИЯ ПУТИ У ПОМОЩНИКА ЗАПИСИ — спросить его СОБСТВЕННОЕ ТЕЛО ───────────
#:
#: `_WRITE_ANY_ARG` просматривал ВСЕ аргументы вызова, и это читалось как
#: осторожность: «позиция пути у разных авторов разная, пометим всё». Цена
#: осторожности ИЗМЕРЕНА (цикл #1053) и она не в шуме, а во ЛЖИ: помеченным
#: оказывался ПЭЙЛОАД — аргумент с данными, а не с путём.
#:
#:     report = evaluate(..., site_numbers=site_numbers, ...)   # собрано из ЧТЕНИЙ
#:     _atomic_write(_REPORT, report)                           # путь arg0, данные arg1
#:
#: `_name_table` честно наследует имена артефактов через правую часть присваивания
#: — без этого не разрешались бы настоящие пути вида `str(Path(d) / NAME)`. Но
#: вместе с путём имена наследуются и в ЗНАЧЕНИЕ, СОБРАННОЕ ИЗ ЧТЕНИЙ: `report`
#: происходит от прочитанной витрины, и `_WRITE_ANY_ARG` объявлял витрину
#: ЗАПИСАННОЙ.
#:
#: Замер репозитория (5549 файлов): **22** ложных атрибуции записи в 10 файлах, и
#: ВСЕ 22 — позиция `arg1` при видимом пути в `arg0`. Среди них
#: `spa_core/analytics/analytics_runner.py` как писатель `equity_curve_daily.json`
#: (ЖИВОЙ ТРЕК, который мандат запрещает трогать) и
#: `spa_core/data_trust/integrity.py` как писатель `data/adapter_status.json`
#: (execution-домен, `.claude/rules/adapters.md`). Одна доезжала до вердикта
#: флота: `B7:contradiction:com.spa.site_freshness` — находка WARN, которой НЕТ в
#: мире. Она же ПРЯТАЛА истинный вердикт агента: `contradiction` возвращается ДО
#: расчёта покрытия, поэтому `confirmed` по всем объявленным продуктам не
#: печатался вовсе. Ровно тот вред, о котором предупреждает докстринг
#: `_name_table`: «Ложный ПИСАТЕЛЬ дороже пропуска».
#:
#: **Чинится НЕ наследованием и НЕ именем параметра, и оба отвергнуты замером.**
#: Запрет наследовать имена через вызов убрал бы 68 НАСТОЯЩИХ записей — путь у
#: них собран помощником вроде `_default_file(...)`, то есть ошибка ушла бы в
#: СТОРОНУ ТИШИНЫ. Угадывание по имени параметра не годится тем же: 372
#: определения помощников во дереве, и позиция пути у них РАЗНАЯ
#: (`_atomic_write_rows(rows, out)` — путь ВТОРЫМ, `_atomic_write_text(text, path)`
#: — тоже).
#:
#: Чинится вопросом к самому помощнику: его тело содержит primitive-запись
#: (`open(p,"w")` · `os.replace(tmp, p)` · `p.write_text(...)` · `_WRITERS`), и
#: ПАРАМЕТР, чьё значение доходит до позиции пути этой записи, и есть путь.
#:
#: Три исхода различимы (инв. #17): позиция НАЗВАНА (помечается только она) ·
#: определения помощника в этом модуле СПОРЯТ о позиции ⇒ прежнее поведение ·
#: определения здесь НЕТ ВОВСЕ ⇒ прежнее поведение. Тишины среди исходов нет:
#: неразобранный помощник остаётся ГРОМКИМ, каким и был.
#:
#: **Чего это НЕ закрывает.** Ветка `CANONICAL_DOORS` у `write_doors` по-прежнему
#: помечает все аргументы: позиции пути у `atomic_append`/`atomic_update` живут в
#: ДРУГОМ модуле (`spa_core/utils/atomic.py`), а `write_doors` принимает только
#: текст одного исходника и файловой двери не имеет по контракту. Население этой
#: ветки названо замером в журнале цикла, а не оставлено нулём.


def _param_taint(body, params: list[str]) -> dict[str, set[str]]:
    """Локальные имена, ПРОИСХОДЯЩИЕ от каждого параметра (до неподвижной точки).

    Нужно потому, что путь внутри помощника почти всегда переобозначают
    (`p = Path(path)`, `tmp = path.with_suffix(...)`): без этого параметр-путь не
    дошёл бы до primitive-записи ни в одном реальном помощнике дерева.
    """
    taint: dict[str, set[str]] = {p: {p} for p in params}
    for _ in range(3):
        for node in ast.walk(ast.Module(body=list(body), type_ignores=[])):
            if not isinstance(node, ast.Assign) or node.value is None:
                continue
            rhs_names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            origin = {p for p, names in taint.items() if rhs_names & names}
            if not origin:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    for p in origin:
                        taint[p].add(target.id)
    return taint


def _path_param_index(fn) -> int | None:
    """Индекс параметра-ПУТИ у помощника записи. `None` = по телу НЕ РАЗОБРАНО.

    Голосуют ТОЛЬКО позиции пути у primitive-записей внутри тела. Вложенный
    помощник из `_WRITE_ANY_ARG` голоса не подаёт: его собственная позиция ещё
    не выяснена, и считать её известной значило бы вывести ответ из догадки.
    Ноль голосов и спор голосов — ОДИН исход («не разобрано»), и он ведёт к
    прежнему громкому поведению, а не к тишине.
    """
    params = [a.arg for a in fn.args.args]
    if not params:
        return None
    offset = 1 if params[0] == "self" else 0
    effective = params[offset:]
    if not effective:
        return None
    taint = _param_taint(fn.body, effective)
    votes: set[int] = set()

    def vote(expr) -> None:
        seen = ({n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}
                | {n.attr for n in ast.walk(expr) if isinstance(n, ast.Attribute)})
        for i, name in enumerate(effective):
            if taint[name] & seen:
                votes.add(i)

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        called = _call_name(node)
        if called == "open":
            if node.args and _open_mode_is_write(node):
                vote(node.args[0])
        elif _is_rename_call(node):
            if len(node.args) > 1:
                vote(node.args[1])          # НАЗНАЧЕНИЕ, не временный файл
        elif called in ("write_text", "write_bytes") and isinstance(node.func, ast.Attribute):
            vote(node.func.value)
        elif called in _WRITERS:
            idx = _WRITERS[called]
            if len(node.args) > idx:
                vote(node.args[idx])
    return next(iter(votes)) + offset if len(votes) == 1 else None


def write_helper_paths(tree: ast.Module) -> dict[str, tuple[int, str] | None]:
    """{имя помощника: (индекс пути, имя параметра)} по определениям ЭТОГО модуля.

    `None` у имени — НАЗВАННЫЙ отказ: определения в одном модуле спорят о позиции.
    Отсутствие ключа — помощника здесь не определяли вовсе. Оба исхода ведут к
    прежнему поведению, но различимы для читателя (инв. #17).
    """
    out: dict[str, tuple[int, str] | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _WRITE_ANY_ARG:
            continue
        idx = _path_param_index(node)
        if idx is None:
            out[node.name] = None
            continue
        spot = (idx, [a.arg for a in node.args.args][idx])
        if node.name not in out:
            out[node.name] = spot
        elif out[node.name] is None or out[node.name][0] != idx:
            out[node.name] = None           # спор определений НАЗВАН, не замолчан
    return out


def path_bearing_args(node: ast.Call, fname: str,
                      helper_paths: dict[str, tuple[int, str] | None]) -> list:
    """Выражения вызова помощника, способные нести ПУТЬ — ОДНА дверь на обоих
    читателей (`scan_source` и `write_doors`).

    Своя копия этого выбора у второго читателя была бы вторым определением одного
    имени — тем самым дефектом «одно имя — один объект»: разойдясь, копии дали бы
    разную запись об одном файле.
    """
    spot = helper_paths.get(fname)
    if isinstance(spot, tuple):
        idx, pname = spot
        if len(node.args) > idx:
            return [node.args[idx]]
        return [k.value for k in node.keywords if k.arg == pname]
    # НЕ РАЗОБРАНО (определения нет либо они спорят) — прежнее громкое поведение.
    return list(node.args) + [k.value for k in node.keywords]


def scan_source(src: str) -> dict[str, set[str]]:
    """{имя артефакта: {"write"|"read"}} для одного модуля. Синтаксис битый ⇒ пусто."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    # Позиция пути у помощников записи ЭТОГО модуля — ответ их собственных тел.
    helper_paths = write_helper_paths(tree)
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
                    # Только позиция ПУТИ: пометить аргумент с данными значило бы
                    # объявить писателем того, кто артефакт ПРОЧИТАЛ (см. блок
                    # «ПОЗИЦИЯ ПУТИ У ПОМОЩНИКА ЗАПИСИ» выше).
                    for arg in path_bearing_args(node, fname, helper_paths):
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


#: Канонические двери записи — те, что живут в ОДНОМ месте
#: (:mod:`spa_core.utils.atomic`). Правка внутри любой из них достаётся всем её
#: вызывающим даром, и именно это свойство меряет :func:`write_doors`.
#: ``atomic_append``/``atomic_append_ring``/``atomic_update`` перечислены не для
#: полноты: каждая из них САМА зовёт ``atomic_save``, поэтому её вызывающий стои́т
#: за общей дверью ровно так же, как если бы звал её напрямую.
CANONICAL_DOORS = frozenset({
    "atomic_save", "atomic_save_text", "atomic_append", "atomic_append_ring",
    "atomic_update", "atomic_write_via_tmp",
})

#: Позиция ПУТИ у канонических дверей. Объявлено ЗДЕСЬ по одной причине:
#: :func:`write_doors` принимает ТЕКСТ одного исходника и файловой двери не имеет по
#: контракту, а определения этих шести живут в ДРУГОМ модуле
#: (`spa_core/utils/atomic.py`) — спросить их тело прямо отсюда нечем.
#:
#: **Объявление НЕ доверенное.** Его паритет с настоящими подписями мерит
#: `test_canonical_door_path_positions_match_the_real_module` ТЕМ ЖЕ резолвером
#: (:func:`_path_param_index`), которым разбираются локальные помощники: переименуй
#: кто-нибудь параметр или поменяй порядок — краснеет тест, а не молчит таблица.
#: Объявление, которое само себе мерка, и есть дефект, против которого это написано.
#:
#: Зачем вообще: до цикла #1053 ветка канонических дверей помечала ВСЕ аргументы, и
#: `spa_core/monitoring/intraday_equity.py` числился писателем
#: `data/equity_curve_daily.json` — ЖИВОГО ТРЕКА, который он только читает. Верхняя
#: граница класса измерена тем же циклом: из 1041 вызова канонических дверей больше
#: одного имени артефакта среди аргументов несут **15**.
CANONICAL_PATH_ARG = {
    "atomic_save": 1,
    "atomic_save_text": 1,
    "atomic_append": 1,
    "atomic_append_ring": 1,
    "atomic_update": 0,
    "atomic_write_via_tmp": 0,
}

#: Дверь ОБЩАЯ · дверь СВОЯ · дверь НЕ РАЗОБРАНА. Третий исход отделён
#: намеренно (инв. #17): помощник, определённый в ДРУГОМ модуле, не есть ни
#: доказательство общей двери, ни доказательство своей.
DOOR_SHARED = "shared"
DOOR_OWN = "own"
DOOR_UNRESOLVED = "unresolved"

#: Модули, чей ``dump`` действительно пишет в файловый объект. Голое ``dump``
#: встречается у чего угодно (своего класса, numpy, joblib), и считать его
#: дверью записи значило бы повторить ошибку с ``replace`` ниже.
_DUMP_OWNERS = frozenset({"json", "pickle", "yaml", "msgpack"})


def _own_door_call(node: ast.Call) -> bool:
    """Пишет ли ЭТОТ вызов на диск САМ, минуя общую дверь.

    **Имя берётся вместе с ВЛАДЕЛЬЦЕМ, и это не придирка.** Первая редакция
    замера (цикл #945) спрашивала у вызова только имя — и получила ``replace``
    12 раз, ``_parse_ts`` 13 и ``_headline`` 7 в перечне «пишет своей дверью»:
    ``str.replace`` и ``datetime.replace`` неотличимы от ``os.replace`` по
    имени, а помощник, внутри которого они стоят, транзитивно получал вердикт
    «своя дверь». Ответ при этом вышел неверным в ОПАСНУЮ сторону — цена штампа
    завышалась (12 артефактов «за общей дверью» против 159 при верном разборе).
    Ровно об этом предупреждает докстринг :data:`_RENAME_CALLS` выше, и
    поэтому ``replace``/``rename``/``move`` здесь спрашиваются у
    :func:`_is_rename_call`, а не у имени.
    """
    name = _call_name(node)
    if name is None:
        return False
    if name == "open":
        return _open_mode_is_write(node)
    if name in _RENAME_CALLS:
        return _is_rename_call(node)
    if name in ("write_text", "write_bytes"):
        return isinstance(node.func, ast.Attribute)
    if name == "mkstemp":
        return (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "tempfile")
    if name == "dump":
        return (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in _DUMP_OWNERS)
    return False


def helper_doors(tree: ast.Module) -> dict[str, str]:
    """{имя функции модуля: дверь, за которой она пишет} — до неподвижной точки.

    **Зачем транзитивность.** В дереве 304 определения локальных помощников вида
    ``_atomic_write``/``_atomic_write_json`` (замер 26.10), и две трети из них
    САМИ зовут ``atomic_save``: то есть пишут через общую дверь, лишь называясь
    по-своему. Остановиться на первом шаге значило бы объявить их своей дверью и
    завысить цену общей правки — замер этой ошибки: 142 артефакта «за общей
    дверью» при одном шаге против 159 при неподвижной точке.

    ``own`` сильнее ``shared`` НАМЕРЕННО: помощник, который в одной ветке зовёт
    общую дверь, а в другой пишет сам, правкой общей двери не покрывается, и
    назвать его покрытым было бы ответом в опасную сторону.
    """
    bodies: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bodies[node.name] = node
    calls: dict[str, set[str]] = {}
    verdict: dict[str, str] = {}
    for name, fn in bodies.items():
        seen: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            called = _call_name(node)
            if called:
                seen.add(called)
            if called in CANONICAL_DOORS:
                verdict.setdefault(name, DOOR_SHARED)
            elif _own_door_call(node):
                verdict[name] = DOOR_OWN
        calls[name] = seen
    changed = True
    while changed:
        changed = False
        for name, seen in calls.items():
            if verdict.get(name) == DOOR_OWN:
                continue
            reached = {verdict[c] for c in seen if c in verdict}
            new = DOOR_OWN if DOOR_OWN in reached else (
                DOOR_SHARED if DOOR_SHARED in reached else None)
            if new and verdict.get(name) != new:
                if verdict.get(name) == DOOR_SHARED and new == DOOR_SHARED:
                    continue
                verdict[name] = new
                changed = True
    return verdict


def write_doors(src: str) -> dict[str, set[str]]:
    """{имя артефакта: {двери, которыми его пишут}} для одного модуля.

    **Вопрос у этой функции свой, и он не тот, на который отвечает**
    :func:`scan_source`. Та говорит, ЧТО модуль пишет; эта — ЧЕМ он пишет, то
    есть достанется ли ему правка, сделанная ОДИН раз внутри общей двери. Для
    заказа G820 п. 1 (ADR-821) это вопрос ЦЕНЫ: штамп атрибуции, положенный в
    ``atomic_save``, приходит её вызывающим даром и не приходит никому другому.

    Разрешатель путей здесь НЕ СВОЙ — берутся те же :func:`_name_table`,
    :func:`_names_in`, :func:`_scopes`, :func:`_own_nodes`, что у соседа. Своя
    копия разрешателя была бы вторым определением одного имени, то есть ровно
    тем дефектом, который `.claude/rules/adapters.md` описывает как «одно имя —
    один объект»: разойдясь, две копии дали бы разную запись об одном файле.

    Синтаксис битый ⇒ пусто (как у соседа): модуль, который не разобрался, не
    утверждает ни «общая дверь», ни «своя».
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    helpers = helper_doors(tree)
    helper_paths = write_helper_paths(tree)
    module_table = _name_table(tree.body)
    out: dict[str, set[str]] = {}

    def mark(names: set[str], door: str) -> None:
        for n in names:
            out.setdefault(n, set()).add(door)

    for body, is_module in _scopes(tree):
        table = module_table if is_module else _name_table(body, seed=module_table)
        for node in _own_nodes(body):
            if not isinstance(node, ast.Call):
                continue
            fname = _call_name(node)
            if fname is None:
                continue
            if fname in CANONICAL_DOORS:
                # Только позиция ПУТИ (`CANONICAL_PATH_ARG`): аргумент с данными
                # объявил бы писателем того, кто артефакт ПРОЧИТАЛ. Имени нет в
                # объявлении ⇒ третий исход, прежнее громкое поведение.
                idx = CANONICAL_PATH_ARG.get(fname)
                if idx is None:
                    spots = list(node.args) + [k.value for k in node.keywords]
                elif len(node.args) > idx:
                    spots = [node.args[idx]]
                else:
                    spots = [k.value for k in node.keywords if k.arg == "path"]
                names: set[str] = set()
                for arg in spots:
                    names |= _names_in(arg, table)
                mark(names, DOOR_SHARED)
            elif _own_door_call(node):
                if fname in ("write_text", "write_bytes"):
                    mark(_names_in(node.func.value, table), DOOR_OWN)
                elif fname == "dump" and len(node.args) > 1:
                    mark(_names_in(node.args[1], table), DOOR_OWN)
                else:
                    names = set()
                    for arg in node.args:
                        names |= _names_in(arg, table)
                    mark(names, DOOR_OWN)
            elif fname in _WRITE_ANY_ARG or fname in helpers:
                names = set()
                for arg in path_bearing_args(node, fname, helper_paths):
                    names |= _names_in(arg, table)
                mark(names, helpers.get(fname) or DOOR_UNRESOLVED)
    return out
