"""Перепись сторожей, которые остаются ЗЕЛЁНЫМИ на опустошённом входе-перечне.

Заказ **G44, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-419).

## Вопрос

`tests/test_no_utcnow.py` найден побочно циклом #636: его вход — перечень
каталогов `SCAN_DIRS = ("spa_core", "scripts")`, и с ПУСТЫМ перечнем он
осматривает ноль файлов и проходит. Зелёный сторож, не осмотревший ничего,
тише красного и потому опаснее: «нарушений нет» становится неотличимо от
«никуда не смотрели» — ровно инвариант #17, но про сторожей.

Заказ требует мерить это как КЛАСС, и мерить по ДРУГОЙ координате, чем
ADR-419: не по паре «сторож × исполнитель», а **по каждому стороже, чей вход
есть перечень** (каталоги, файлы, ключи).

## Что считается «входом-перечнем» — и почему не всякий перечень им является

Вход — это перечень, по которому сторож РЕШАЕТ, ГДЕ СМОТРЕТЬ. Разбор идёт по
употреблению имени, а не по его виду, и порядок разбора существен:

| употребление | роль | в население |
|---|---|---|
| имя — итератор `for`/включения | `iterated` | да |
| имя отдано аргументом в вызов (`len(X)`, `_scan(X)`) | `passed_to_call` | да |
| имя только в проверке принадлежности (`x in X`, `X.get(k)`) | `membership_only` | **нет** |
| имя не читается нигде | `not_loaded` | **нет** |

`membership_only` исключён ЗАМЕРИМО, а не из осторожности: такой перечень —
список исключений (`_ALLOWLIST`), и опустошить его значит сделать сторожа
СТРОЖЕ, а не слепее. Обратная сторона названа: сторож, отдающий перечень в
вызов, может отдавать туда тот же список исключений — поэтому роль остаётся
ПОЛЕМ строки, а не растворяется в вердикте.

## Две оси, и они отвечают на разные вопросы

1. **Вырожден ли сторож при пустом входе** — вопрос ПОВЕДЕНЧЕСКИЙ, и статикой
   он не решается: «зелёный при пустом перечне» видно только прогоном.
   Отвечает зонд (`spa_core/monitoring/vacuous_guard_probe.py`), перепись его
   журнал только ЧИТАЕТ (`PROBE_LEDGER`) — тот же порядок, что у ADR-419.
2. **Достижима ли пустота БЕЗ правки исходника** — вопрос СТАТИЧЕСКИЙ. Пустой
   перечень, записанный литералом, сам собой не возникнет; а вот ветка
   `if not base.exists(): continue` даёт ровно ту же пустоту при живом
   литерале — из дерева, где каталога нет (и такие деревья у нас штатны:
   worktree, урезанный clone, прод без `data/`). Это поле
   `empty_without_edit`, и оно НЕ вердикт: `edit_required` не означает
   «безопасно», означает «сегодня этой двери не видно статикой».

## Три исхода различимы (инв. #17)

`vacuous_pass` · `refuses_empty` · `refuses_elsewhere` — вердикты; всё
остальное `unmeasured` с НАЗВАННОЙ причиной: зонд строки не видел, журнал
относится к другому sha сторожа, сторож красен на базе, pytest ничего не
собрал. «Не измерено» вердиктом не притворяется и с учёта строку не снимает.

`refuses_elsewhere` — отдельный вердикт, а не разновидность красноты: сторож
покраснел, но НИ ОДИН упавший тест не читает опустошённое имя, то есть
краснота пришла от СОСЕДА, а сам потребитель перечня остался вырожденным.
Слить его с `refuses_empty` значило бы записать чужую красноту в защиту.

## Население считается ДО починок

Требование заказа дословно: «население считать до починок: список лечит
поводы». Перепись ничего не чинит и не вправе: найденный сторож — предмет
своей карточки, а не прицепа (инв. #16).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "vacuous_guard_census.json"
PRODUCER = "spa_core/monitoring/vacuous_guard_census.py"

#: Каталоги сторожей берутся У ПЕРЕПИСИ ADR-417 ВВОЗОМ, а не переписываются:
#: одно правило — одна копия (ADR-418, форма починки `single_copy_by_import`).
GUARD_DIRS = census.GUARD_DIRS

ROLE_ITERATED = "iterated"
ROLE_PASSED = "passed_to_call"
ROLE_MEMBERSHIP = "membership_only"
ROLE_UNREAD = "not_loaded"
#: Роли, при которых перечень есть ВХОД сторожа (население зонда).
INPUT_ROLES = (ROLE_ITERATED, ROLE_PASSED)

VERDICT_VACUOUS = "vacuous_pass"
VERDICT_REFUSES = "refuses_empty"
VERDICT_ELSEWHERE = "refuses_elsewhere"
VERDICT_UNMEASURED = "unmeasured"
VERDICTS = (VERDICT_VACUOUS, VERDICT_REFUSES, VERDICT_ELSEWHERE,
            VERDICT_UNMEASURED)
#: Вердикты, требующие строки в цикле (код возврата 1).
FINDING_VERDICTS = (VERDICT_VACUOUS, VERDICT_ELSEWHERE)

ATTRIBUTION_DIRECT = "consumer_failed"
ATTRIBUTION_HELPER = "via_helper"
ATTRIBUTION_NONE = "consumer_green"

EMPTY_REACHABLE = "reachable_absent_path"
EMPTY_EDIT = "edit_required"
#: ГДЕ стои́т найденная дверь. «В теле цикла-потребителя» — это путь ИМЕННО
#: этого перечня; «где-то в модуле» — слабее и может относиться к соседнему.
DOOR_IN_CONSUMER = "inside_consumer_loop"
DOOR_IN_MODULE = "elsewhere_in_module"
DOOR_NONE = ""

#: Журнал зонда — РЯДОМ С КОДОМ, не в `data/`: он есть замер ИСХОДНИКОВ этого
#: дерева, годный ровно для sha сторожа (та же природа, что у
#: `copy_independence_ledger.json`, ADR-419). Протухшая запись не молчит —
#: она перестаёт отвечать, и строка возвращается в `unmeasured`.
PROBE_LEDGER = "spa_core/monitoring/vacuous_guard_ledger.json"

#: Конструкторы контейнеров: запись `frozenset({...})` есть ЗНАЧЕНИЕ, а не
#: вычисление (то же правило, что у `const_value` переписи ADR-417).
_CONTAINER_CTORS = {"frozenset": frozenset, "set": set, "tuple": tuple,
                    "list": list, "dict": dict}

#: Методы, чей вызов на имени есть проверка принадлежности, а не обход.
_MEMBERSHIP_METHODS = frozenset({"get", "__contains__"})

#: Проверки существования пути. Отрицание такой проверки с телом-пропуском и
#: есть дверь к пустому входу без единой правки исходника.
_EXISTENCE_METHODS = frozenset({"exists", "is_dir", "is_file"})


class NotMeasured(RuntimeError):
    """Население не прочитано — третий исход, а не пустая перепись."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def literal_of(value_src: Optional[str]) -> Tuple[bool, object]:
    """``(разобрано ли, значение)`` для источника константы.

    Помимо литерала разбирается ВЫЗОВ КОНСТРУКТОРА контейнера
    (`frozenset({...})`, `tuple(...)`, `dict(...)`): перепись ADR-417 считает
    такую запись константной, и без этой ветки строки такого рода выпадали бы
    из населения МОЛЧА. Замер 19.09: так выпадали 19 констант (10 `frozenset`,
    8 `dict`, 1 `tuple`) — дыра в населении, а не в отчёте, и потому опаснее.

    Возврат — пара, а не значение: ``None`` есть законное значение константы, и
    сливать его с «не разобрано» значило бы завести ту же подмену исходов,
    против которой написан весь прибор.
    """
    if value_src is None:
        return False, None
    try:
        return True, ast.literal_eval(value_src)
    except Exception:  # noqa: BLE001 — не литерал; ниже разбирается конструктор
        pass
    try:
        node = ast.parse(value_src, mode="eval").body
    except SyntaxError:
        return False, None
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _CONTAINER_CTORS and not node.keywords
            and len(node.args) <= 1):
        return False, None
    ctor = _CONTAINER_CTORS[node.func.id]
    if not node.args:
        return True, ctor()
    try:
        return True, ctor(ast.literal_eval(node.args[0]))
    except Exception:  # noqa: BLE001
        return False, None


def empty_literal(value_src: str) -> Optional[str]:
    """Пустой литерал ТОГО ЖЕ рода — или ``None``, если род не перечень.

    Правило живёт ЗДЕСЬ в единственном экземпляре: зонд его ввозит, а не
    переписывает (ADR-418). Опустошение обязано сохранять род: подставить
    ``[]`` вместо ``frozenset()`` значило бы менять ещё и тип, и тогда
    краснота сторожа говорила бы о типе, а не о пустоте.
    """
    parsed, value = literal_of(value_src)
    if not parsed:
        return None
    if isinstance(value, tuple):
        return "()"
    if isinstance(value, list):
        return "[]"
    if isinstance(value, frozenset):
        return "frozenset()"
    if isinstance(value, set):
        return "set()"
    if isinstance(value, dict):
        return "{}"
    return None


def enumeration_value(value_src: Optional[str]) -> Optional[object]:
    """Значение перечня, если это НЕПУСТОЙ перечень строк; иначе ``None``.

    Пустой перечень в население не входит: опустошать нечего, и вердикт
    «зелёный при пустом входе» был бы о сегодняшнем состоянии сторожа, а не о
    его вырожденности.
    """
    parsed, value = literal_of(value_src)
    if not parsed:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        if not value or not all(isinstance(x, str) for x in value):
            return None
        return value
    if isinstance(value, dict):
        if not value or not all(isinstance(k, str) for k in value):
            return None
        return value
    return None


def is_empty_literal(value_src: Optional[str]) -> bool:
    """Пуст ли литерал перечня. Вопрос отдельный от «это перечень строк».

    Нужен зонду, чтобы проверить, что опустошение ПРИМЕНИЛОСЬ. Слить его с
    :func:`enumeration_value` нельзя: та возвращает ``None`` и на непустом
    перечне чисел, и на пустом перечне строк, и «не применилось» стало бы
    неотличимо от «применилось».
    """
    parsed, value = literal_of(value_src)
    return parsed and isinstance(value, (list, tuple, set, frozenset, dict)) \
        and not value


def enumeration_role(tree: ast.Module, name: str) -> str:
    """Роль имени по УПОТРЕБЛЕНИЮ. Порядок разбора — порядок объявления ролей.

    Обход идёт ОДИН раз по всему дереву, потому что имя может употребляться
    и так и этак: `for d in SCAN_DIRS` рядом с `if x in SCAN_DIRS` — это вход,
    а не фильтр, и старшинство `iterated` отвечает именно на это.
    """
    iterated = passed = membership = False
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                and node.iter.id == name:
            iterated = True
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                               ast.DictComp)):
            for gen in node.generators:
                if isinstance(gen.iter, ast.Name) and gen.iter.id == name:
                    iterated = True
        elif isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            for cmp_node in node.comparators:
                if isinstance(cmp_node, ast.Name) and cmp_node.id == name:
                    membership = True
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == name:
                if func.attr in _MEMBERSHIP_METHODS:
                    membership = True
                else:
                    passed = True
                continue
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Name) and arg.id == name:
                    passed = True
                elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name) \
                        and arg.value.id == name:
                    passed = True
    if iterated:
        return ROLE_ITERATED
    if passed:
        return ROLE_PASSED
    if membership:
        return ROLE_MEMBERSHIP
    if census.constant_is_loaded(tree, name):
        # Читается, но ни обходом, ни вызовом, ни принадлежностью: подписка,
        # f-строка, сравнение целиком. Входом сторожа это не является, и
        # выдавать такую строку за население значило бы мерить не тот класс.
        return ROLE_MEMBERSHIP
    return ROLE_UNREAD


def loaders_of(tree: ast.Module, name: str) -> Tuple[Set[str], Set[str], bool]:
    """Кто читает имя: ``(тесты, помощники, читается ли на уровне модуля)``.

    Нужно для ПРИПИСЫВАНИЯ красноты. Сторож — файл, но вырожден бывает один
    тест из нескольких: если упал сосед, а потребитель перечня остался
    зелёным, краснота защитой не является.
    """
    tests: Set[str] = set()
    helpers: Set[str] = set()
    covered: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            loaded = any(
                isinstance(sub, ast.Name) and sub.id == name
                and isinstance(sub.ctx, ast.Load)
                for sub in ast.walk(node))
            if loaded:
                (tests if node.name.startswith("test") else helpers).add(node.name)
            for sub in ast.walk(node):
                covered.add(id(sub))
    module_level = any(
        isinstance(node, ast.Name) and node.id == name
        and isinstance(node.ctx, ast.Load) and id(node) not in covered
        for node in ast.walk(tree))
    return tests, helpers, module_level


def silently_skips_absent(tree: ast.Module,
                          *, within: Optional[ast.AST] = None) -> Optional[str]:
    """Есть ли ветка, дающая пустой вход БЕЗ правки исходника.

    Ищется отрицание проверки существования (или пустоты) с телом-пропуском:
    ``if not base.exists(): continue``. Найдено ⇒ вырожденность достижима из
    дерева, где каталога просто нет, — и тогда она не гипотетическая.

    ``within`` сужает поиск до тела ОДНОГО узла (цикла-потребителя). Это и
    есть разница между «дверь есть где-то в модуле» и «дверь стои́т на пути
    ИМЕННО этого перечня»; смешивать их нельзя — модульная дверь может
    относиться к соседнему перечню и приписала бы строке чужую достижимость.

    Обратная сторона названа вслух: отсутствие такой ветки НЕ доказывает, что
    пустой вход недостижим. Перечень может собираться вызовом, каталог может
    оказаться пустым, а не отсутствующим. Мера односторонняя.
    """
    for node in ast.walk(within if within is not None else tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
            continue
        operand = test.operand
        marker: Optional[str] = None
        if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Attribute) \
                and operand.func.attr in _EXISTENCE_METHODS:
            marker = f"{operand.func.attr}()"
        elif isinstance(operand, ast.Name):
            marker = operand.id
        if marker is None:
            continue
        body = node.body
        if len(body) == 1 and isinstance(body[0], (ast.Continue, ast.Pass)):
            return f"строка {node.lineno}: `if not …{marker}:` → пропуск"
        if len(body) == 1 and isinstance(body[0], ast.Return):
            return f"строка {node.lineno}: `if not …{marker}:` → выход"
    return None


def consumer_loops(tree: ast.Module, name: str) -> List[ast.AST]:
    """Циклы, чей итератор есть само имя. Тело такого цикла — путь перечня."""
    out: List[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.iter, ast.Name) \
                and node.iter.id == name:
            out.append(node)
    return out


def row_key(guard_rel: str, name: str) -> str:
    """Координата строки в журнале зонда."""
    return f"{guard_rel}|{name}"


def population(root: Path) -> Tuple[List[dict], Dict[str, int], List[dict]]:
    """Население переписи: ``(строки-входы, счётчик ролей, нечитаемые файлы)``."""
    rows: List[dict] = []
    roles: Dict[str, int] = {ROLE_ITERATED: 0, ROLE_PASSED: 0,
                             ROLE_MEMBERSHIP: 0, ROLE_UNREAD: 0}
    unreadable: List[dict] = []
    for path in census._guard_files(root):
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
            # filename= обязателен: без него предупреждение разбора (например
            # SyntaxWarning про недопустимую escape-последовательность) печатает
            # `<unknown>:74` и НЕ называет файл — по такой строке действовать
            # нельзя, а перепись как раз и написана против «сказано, но не
            # названо». SyntaxError путь уже несёт (ниже, в `unreadable`).
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError) as exc:
            unreadable.append({"guard": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        constants = census.toplevel_constants(tree)
        module_door = silently_skips_absent(tree)
        for name, value_src in sorted(constants.items()):
            value = enumeration_value(value_src)
            if value is None:
                continue
            role = enumeration_role(tree, name)
            roles[role] += 1
            if role not in INPUT_ROLES:
                continue
            tests, helpers, module_level = loaders_of(tree, name)
            door, scope = module_door, (DOOR_IN_MODULE if module_door else DOOR_NONE)
            for loop in consumer_loops(tree, name):
                inner = silently_skips_absent(tree, within=loop)
                if inner:
                    door, scope = inner, DOOR_IN_CONSUMER
                    break
            rows.append({
                "key": row_key(rel, name),
                "guard": rel,
                "name": name,
                "value": value_src,
                "size": len(value),
                "role": role,
                "empty_literal": empty_literal(value_src),
                "guard_sha": _sha256(path),
                "consumer_tests": sorted(tests),
                "consumer_helpers": sorted(helpers),
                "loaded_at_module_level": module_level,
                "empty_without_edit": EMPTY_REACHABLE if door else EMPTY_EDIT,
                "empty_without_edit_evidence": door or "",
                "door_scope": scope,
            })
    return rows, roles, unreadable


def _attribute(row: dict, entry: dict) -> Tuple[str, str]:
    """Кто принёс красноту: потребитель перечня или сосед.

    Возврат — ``(вердикт, приписывание)``. Список упавших тестов зонд берёт из
    короткой сводки pytest; если его нет, приписывание не выдумывается.
    """
    failed = entry.get("failed_tests")
    consumers = set(row.get("consumer_tests") or [])
    if not isinstance(failed, list) or not failed:
        return VERDICT_REFUSES, ATTRIBUTION_HELPER
    failed_names = {str(f).rsplit("::", 1)[-1].split("[", 1)[0] for f in failed}
    if consumers & failed_names:
        return VERDICT_REFUSES, ATTRIBUTION_DIRECT
    if not consumers:
        # Имя читается помощником или на уровне модуля — какой именно тест
        # есть потребитель, статикой не решается. Это НЕ «сосед покраснел».
        return VERDICT_REFUSES, ATTRIBUTION_HELPER
    return VERDICT_ELSEWHERE, ATTRIBUTION_NONE


def _verdict(row: dict, ledger: Dict[str, dict],
             ledger_reason: Optional[str]) -> dict:
    """Вердикт строки по журналу зонда — или ``unmeasured`` с причиной."""
    out = {"verdict": VERDICT_UNMEASURED, "attribution": "", "evidence": ""}
    entry = ledger.get(row["key"])
    if entry is None:
        out["evidence"] = ledger_reason or "зонд этой строки не видел"
        return out
    if entry.get("guard_sha") != row["guard_sha"]:
        out["evidence"] = ("запись зонда относится к ДРУГОМУ sha сторожа — "
                           "после правки строка возвращается на учёт")
        return out
    if entry.get("value") != row["value"]:
        out["evidence"] = "запись зонда относится к другому значению перечня"
        return out
    verdict = entry.get("verdict")
    if verdict == VERDICT_VACUOUS:
        out["verdict"] = VERDICT_VACUOUS
        out["attribution"] = ATTRIBUTION_NONE
        out["evidence"] = str(entry.get("evidence") or
                              "сторож ЗЕЛЁН с опустошённым перечнем")
        return out
    if verdict == VERDICT_REFUSES:
        resolved, attribution = _attribute(row, entry)
        out["verdict"] = resolved
        out["attribution"] = attribution
        if resolved == VERDICT_ELSEWHERE:
            out["evidence"] = (
                f"сторож покраснел, но упали {sorted(entry.get('failed_tests') or [])} "
                f"— ни один не читает `{row['name']}`; потребители "
                f"{row.get('consumer_tests')} остались зелёными")
        else:
            out["evidence"] = str(entry.get("evidence") or
                                  "сторож краснеет на опустошённом перечне")
        return out
    out["evidence"] = str(entry.get("evidence") or "зонд не поставил опыт")
    return out


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotMeasured(f"корень дерева не прочитан: {root}")
    try:
        rows, roles, unreadable = population(root)
    except census.NotMeasured as exc:
        # Отказ ввезённого читателя населения — тоже «не измерено», и он обязан
        # быть исходом ЭТОГО прибора, а не трассировкой чужого класса.
        raise NotMeasured(str(exc)) from exc
    ledger, ledger_reason = census.load_probe_ledger(root / PROBE_LEDGER)
    counts = {v: 0 for v in VERDICTS}
    reachable = 0
    for row in rows:
        row.update(_verdict(row, ledger, ledger_reason))
        counts[row["verdict"]] += 1
        if row["empty_without_edit"] == EMPTY_REACHABLE:
            reachable += 1
    in_consumer = len([r for r in rows if r.get("door_scope") == DOOR_IN_CONSUMER])
    vacuous_reachable = len([
        r for r in rows
        if r["verdict"] == VERDICT_VACUOUS
        and r["empty_without_edit"] == EMPTY_REACHABLE])
    guards = sorted({r["guard"] for r in rows})
    status = "MEASURED"
    if counts[VERDICT_VACUOUS] or counts[VERDICT_ELSEWHERE]:
        status = "CRITICAL"
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": status,
        "question": "сколько сторожей остаются зелёными с ОПУСТОШЁННЫМ входом-перечнем",
        "guard_dirs": list(GUARD_DIRS),
        "rows": rows,
        "guards": len(guards),
        "inputs": len(rows),
        "roles": roles,
        "counts": counts,
        "empty_reachable_without_edit": reachable,
        "door_inside_consumer_loop": in_consumer,
        "vacuous_and_reachable": vacuous_reachable,
        "unreadable": unreadable,
        "probe_ledger": PROBE_LEDGER,
        "probe_ledger_reason": ledger_reason or "",
        "what_it_does_not_prove": [
            "что `refuses_empty` означает исправного сторожа — он означает лишь, что ПУСТОЙ вход не проходит молча",
            "что `refuses_elsewhere` есть защита: покраснел сосед, а потребитель перечня остался вырожденным",
            "что `edit_required` означает недостижимую пустоту — статикой видна одна дверь (отсутствующий путь), а перечень может опустеть и иначе",
            "что `membership_only` безвреден — он лишь не есть ВХОД: опустошение списка исключений делает сторожа строже, а не слепее",
            "что строка без записи зонда исправна — `unmeasured` есть третий исход и на учёт строку ВОЗВРАЩАЕТ",
            "что население полно: перечень, собранный вызовом (а не литералом), в него не входит по построению",
            "что дверь `elsewhere_in_module` стои́т на пути ИМЕННО этого перечня — по модулю она измерена, по телу цикла-потребителя названа отдельно (`door_scope`)",
        ],
    }


def report(doc: dict, *, max_rows: int = 25) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    roles = observed(doc, "roles", kind=dict) or {}
    out = [
        f"перепись вырожденных сторожей (заказ G44 п. 1): {status} · сторожей "
        f"{doc.get('guards')} · входов-перечней {doc.get('inputs')} · ВЫРОЖДЕН "
        f"{counts.get(VERDICT_VACUOUS)} · краснеет {counts.get(VERDICT_REFUSES)} · "
        f"краснеет НЕ ТЕМ ТЕСТОМ {counts.get(VERDICT_ELSEWHERE)} · НЕ ИЗМЕРЕНО "
        f"{counts.get(VERDICT_UNMEASURED)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[РОЛИ] обход {roles.get(ROLE_ITERATED)} · отдан в вызов "
        f"{roles.get(ROLE_PASSED)} · только принадлежность "
        f"{roles.get(ROLE_MEMBERSHIP)} (не вход: опустошение делает СТРОЖЕ) · "
        f"не читается {roles.get(ROLE_UNREAD)}",
        f"[ДВЕРЬ БЕЗ ПРАВКИ] пустота достижима из дерева без каталога у "
        f"{doc.get('empty_reachable_without_edit')} входов (дверь стои́т в теле "
        f"самого цикла-потребителя у {doc.get('door_inside_consumer_loop')}); из "
        f"них уже вырождены {doc.get('vacuous_and_reachable')}",
    ]
    if doc.get("probe_ledger_reason"):
        out.append(f"[ЗОНД] журнал не прочитан: {doc.get('probe_ledger_reason')} — "
                   f"строки остаются НЕ ИЗМЕРЕНЫ, а не исправны")
    if doc.get("unreadable"):
        out.append(f"[НЕ ИЗМЕРЕНО] файлов сторожей не разобрано: "
                   f"{len(doc.get('unreadable') or [])}")
    shown = [r for r in (doc.get("rows") or [])
             if r.get("verdict") in FINDING_VERDICTS]
    for row in shown[:max_rows]:
        out.append(f"[{row.get('verdict')}] {row.get('guard')} · "
                   f"{row.get('name')} ({row.get('size')} эл., {row.get('role')}, "
                   f"{row.get('empty_without_edit')}): {row.get('evidence')}")
    if len(shown) > max_rows:
        out.append(f"… ещё {len(shown) - max_rows} находок(и) — полный перечень в артефакте")
    out.append("НЕ ДОКЛАДЫВАЕТ: верность самого правила сторожа; перечни, "
               "собираемые вызовом; достижимость пустоты иными дверями, кроме "
               "отсутствующего пути")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Короткая форма для шага 0-офис."""
    return report(doc, max_rows=max_rows)


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def fill_ledger(root: Path, *, sample: Optional[int] = None,
                write: bool = True) -> dict:
    """Позвать зонд и обновить журнал, на который перепись опирается.

    Ввоз ЛЕНИВЫЙ и односторонний: зонд ввозит перепись на верхнем уровне
    (ему нужны правила населения), обратный ввоз на верхнем уровне замкнул бы
    круг. Перепись зовёт зонд только когда её об этом просят явно: прогон
    зонда стои́т сотен прогонов pytest, и ставить его в шестичасового агента
    было бы платой временем за ответ, который меняется от правки сторожа, а
    не от календаря.
    """
    from spa_core.monitoring import vacuous_guard_probe
    return vacuous_guard_probe.run(
        root, write=write,
        **({} if sample is None else {"sample": sample}))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись сторожей, зеленеющих на опустошённом входе (G44 п. 1)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--max-rows", type=int, default=25)
    ap.add_argument("--probe", nargs="?", type=int, const=-1, default=None,
                    metavar="N",
                    help="сперва позвать зонд (долго: прогоны pytest), затем "
                         "перемерить; N — размер случайной выборки сверх "
                         "подкласса с достижимой пустотой")
    args = ap.parse_args(argv)

    if args.probe is not None:
        probe_outcome = fill_ledger(Path(args.root),
                                    sample=None if args.probe < 0 else args.probe,
                                    write=not args.no_write)
        print(f"[ЗОНД] {probe_outcome['doc'].get('status')} · зондировано "
              f"{probe_outcome['doc'].get('probed')}")

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc, max_rows=args.max_rows):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    counts = doc.get("counts") or {}
    return 1 if any(counts.get(v) for v in FINDING_VERDICTS) \
        or counts.get(VERDICT_UNMEASURED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
