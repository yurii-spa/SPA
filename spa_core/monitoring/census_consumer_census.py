"""Сколько ПОТРЕБИТЕЛЕЙ у переписей ступени — и согласны ли они, что значит `root`.

Заказ #564 (стоячая карточка CIO) поставлен дословно так:

> Контракт `run(root=…)` измерен у ОДНОГО потребителя (ступень `findings_bridge`).
> Вопрос: **сколько ЕЩЁ потребителей зовут эти же переписи, и согласны ли они о
> том, что значит `root`.** Первым результатом — НАСЕЛЕНИЕ потребителей, ноль
> сверх моста ⇒ третий исход «потребитель единственный». Ловушка названа заранее:
> «модуль зовут по имени» и «модуль зовут через реестр, строку или `importlib`» —
> РАЗНЫЕ множества, и грепом по `.run(` второе не находится; мерить надо оба, а
> несведённое звать «не измерено», а не «нет».

## Почему вопрос не праздный

Цикл #564 (ADR-326) нашёл, что одно слово `root` значило у двух переписей из
двенадцати РАЗНОЕ: у одиннадцати — корень дерева, у двух — сам каталог данных.
Расхождение не ловилось ничем, потому что мерили его у ЕДИНСТВЕННОГО известного
потребителя. Если потребителей больше одного, починка «у моста» закрывает класс
ровно настолько, насколько мост — единственный зовущий; а это утверждение до
сих пор никто не мерил.

## Ловушка заказа обойдена так же, как в #564: замер не читает `data/` вовсе

Вопрос — о КОДЕ (кто кого зовёт и что при этом значит `root`). Ответ не имеет
права зависеть от того, что сегодня лежит на диске: перепись, которую сегодня
некому было запустить, потребителем быть не перестаёт.

## Четыре класса потребителей, и они РАЗНОРОДНЫ

=========================  ====================================================
класс                      чем отличается вопрос о `root`
=========================  ====================================================
``by_name``                зовёт ``X.run(root=…)`` дословно; видно, ЧТО передано
``cli``                    свой ``__main__``; `root` берётся из флага или умолчания
``dynamic``                модуль добыт строкой/``importlib``; имя статике не даётся
``fleet``                  обёртка launchd зовёт модуль как ``-m``; `root` не передаёт
=========================  ====================================================

Сводить их в одно число нельзя: у ``by_name`` значение `root` написано в вызове,
у ``cli`` — в умолчании, у ``fleet`` — не написано нигде и берётся умолчанием
модуля. «Потребителей N» без разбиения по классам было бы верным ответом не на
тот вопрос.

## Третий исход назван и НЕ растворён

``import_module(<переменная>)`` статике не даётся ПО ПОСТРОЕНИЮ. Такие места
считаются отдельно (`dynamic_unresolved`) и никогда не складываются с нулём:
«мы не смогли посмотреть» и «там никого нет» — разные утверждения, и второе,
выданное за первое, и есть ровно тот fail-OPEN, против которого написан ADR-326.

ADVISORY. Прибор ничего не чинит и капитал не двигает: он читает исходники и
НАЗЫВАЕТ население. `POLLED_ADAPTERS`, пины, писатель журнала решений, пороги
RiskPolicy v1.0, стоп-кран и живой трек не трогаются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

OUTPUT_FILENAME = "census_consumer_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Каталоги, по которым ищутся и переписи, и их потребители. Тесты ищутся тоже:
#: тест — такой же потребитель контракта, и расхождение у него так же реально.
_CODE_DIRS = ("spa_core", "scripts", "tests", "research")

#: Обёртки флота и манифесты — четвёртый класс потребителя.
_FLEET_DIRS = ("scripts", "launchd", "architecture")

#: Зов ступени моста дословно — БЕЗ оглядки на импорт и на имя приёмника.
#: Импорт-соседство теряет население тремя способами разом (замер #565): приёмник
#: без ведущего подчёркивания, зов вовсе без присваивания (`house_view_gap`,
#: `loop_health`) и зов через тринадцать строк после импорта (`loop_retro`).
_STAGE_CALL = re.compile(r"\b(\w+)\.run\(root=args\.root\)")


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def find_callees(root: Path) -> Dict[str, str]:
    """Перепись = модуль с ВЕРХНЕУРОВНЕВЫМ ``run()``, принимающим ``root``.

    Определение намеренно не «модуль из списка моста»: список моста — это
    ответ ОДНОГО потребителя, а вопрос заказа шире. Перепись, которую мост
    ещё не зовёт, контракт `root` всё равно объявляет.
    """
    out: Dict[str, str] = {}
    for sub in _CODE_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            tree = _parse(path)
            if tree is None:
                continue
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name != "run":
                    continue
                args = ([a.arg for a in node.args.args]
                        + [a.arg for a in node.args.kwonlyargs])
                if "root" in args:
                    out[path.stem] = str(path.relative_to(root))
    return out


def _root_default(fn: ast.FunctionDef) -> Optional[str]:
    """Что стоит умолчанием у параметра ``root``; ``None`` = параметр обязателен."""
    positional = [a.arg for a in fn.args.args]
    if "root" in positional:
        defaults = list(fn.args.defaults)
        index = positional.index("root")
        offset = len(positional) - len(defaults)
        if index >= offset:
            return ast.unparse(defaults[index - offset])
        return None
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    if "root" in kwonly:
        value = fn.args.kw_defaults[kwonly.index("root")]
        return ast.unparse(value) if value is not None else None
    return None


def find_by_name_consumers(root: Path, callees: Dict[str, str]) -> List[dict]:
    """Места вида ``X.run(...)``, где ``X`` — имя переписи, видимое статике."""
    sites: List[dict] = []
    for sub in _CODE_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "run":
                    continue
                value = func.value
                if not isinstance(value, ast.Name) or value.id not in callees:
                    continue
                passed = None
                for kw in node.keywords:
                    if kw.arg == "root":
                        passed = ast.unparse(kw.value)
                sites.append({
                    "file": str(path.relative_to(root)),
                    "line": node.lineno,
                    "callee": value.id,
                    "root_argument": passed,
                    "positional_args": len(node.args),
                })
    return sites


def find_cli_consumers(root: Path, callees: Dict[str, str]) -> List[dict]:
    """Собственный ``__main__`` каждой переписи — самостоятельный потребитель."""
    out: List[dict] = []
    for name, rel in sorted(callees.items()):
        path = root / rel
        source = path.read_text(encoding="utf-8")
        tree = _parse(path)
        default = None
        if tree is not None:
            for node in tree.body:
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "run"):
                    default = _root_default(node)
        out.append({
            "callee": name,
            "file": rel,
            "has_main": "__main__" in source,
            "exposes_root_flag": '"--root"' in source or "'--root'" in source,
            "exposes_data_dir_flag": ('"--data-dir"' in source
                                      or "'--data-dir'" in source),
            "run_root_default": default,
        })
    return out


def find_dynamic_consumers(root: Path, callees: Dict[str, str]) -> dict:
    """Зов через строку/``importlib`` — и отдельно то, что статике не даётся.

    Разделение здесь и есть предмет ловушки заказа. ``import_module("a.b.c")``
    разрешимо; ``import_module(name)`` — нет, и назвать его отсутствием было бы
    изготовлением чистого ответа.
    """
    resolved: List[dict] = []
    unresolved: List[dict] = []
    literal = re.compile(r"import_module\(\s*[\"']([\w.]+)[\"']\s*\)")
    variable = re.compile(r"import_module\(\s*(?![\"'])([^)]+?)\s*\)")
    for sub in _CODE_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "import_module" not in source:
                continue
            rel = str(path.relative_to(root))
            for match in literal.finditer(source):
                stem = match.group(1).rsplit(".", 1)[-1]
                if stem in callees:
                    resolved.append({
                        "file": rel,
                        "line": source[:match.start()].count("\n") + 1,
                        "callee": stem,
                    })
            for match in variable.finditer(source):
                unresolved.append({
                    "file": rel,
                    "line": source[:match.start()].count("\n") + 1,
                    "expression": match.group(1)[:80],
                })
    return {"resolved": resolved, "unresolved": unresolved}


def find_unprobeable(root: Path, callees: Dict[str, str]) -> List[str]:
    """Перепись, у которой нет параметра ``write``, — её нельзя ПРОВЕРИТЬ, не записав.

    Замер #565 наткнулся на это собственным зондом: проба контракта, позванная
    без аргументов, молча положила артефакт в дерево пробующего. Свойство важно
    не косметически — сторож, который обязан ЗАПИСАТЬ, чтобы измерить, платит
    за каждый замер настоящим файлом, и отличить его запись от рабочей нельзя.
    Разбор статический: параметр либо есть в сигнатуре, либо нет.
    """
    out: List[str] = []
    for name, rel in sorted(callees.items()):
        tree = _parse(root / rel)
        if tree is None:
            continue
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "run"):
                args = ([a.arg for a in node.args.args]
                        + [a.arg for a in node.args.kwonlyargs])
                has_kwargs = node.args.kwarg is not None
                if "write" not in args and not has_kwargs:
                    out.append(name)
    return out


def find_fleet_consumers(root: Path, callees: Dict[str, str]) -> List[dict]:
    """Обёртки launchd и манифесты, называющие перепись как цель запуска."""
    out: List[dict] = []
    dotted = re.compile(r"spa_core\.monitoring\.(\w+)")
    for sub in _FLEET_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in (".sh", ".plist"):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            named = sorted({m.group(1) for m in dotted.finditer(source)
                            if m.group(1) in callees})
            if named:
                out.append({
                    "file": str(path.relative_to(root)),
                    "callees": named,
                    "passes_root": "--root" in source,
                })
    return out


#: Файл храповика контракта `run(root=…)` (цикл #564, поправлен #565).
_RATCHET = ("spa_core", "tests", "test_census_stage_root_contract.py")

#: Имя функции, чей возврат И ЕСТЬ население, которое храповик потом проверяет.
_RATCHET_POPULATION_FN = "stage_censuses"


def stage_population_under_ratchet(root: Path) -> Optional[List[str]]:
    """Что видит храповик — формой зова, которую он ДЕЙСТВИТЕЛЬНО применяет.

    Спрашивать надо не «какие регулярки лежат в файле», а «какая из них питает
    население». Регулярка, объявленная и не использованная, охраняет ноль, и
    сложить её с работающей значило бы изготовить покрытие. Поэтому имя формы
    берётся из тела ``stage_censuses`` разбором AST, а не текстовым поиском.

    Возврат ``None`` — третий исход «не измерено» (файла нет, разбор не дался,
    форма связана не с литералом). Пустой список означал бы «храповик не видит
    ничего», а это совсем другое утверждение.
    """
    path = root.joinpath(*_RATCHET)
    bridge = root / "spa_core" / "monitoring" / "findings_bridge.py"
    if not path.is_file() or not bridge.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    tree = _parse(path)
    if tree is None:
        return None

    # 1. какое ИМЯ формы возвращает функция населения
    used: Optional[str] = None
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != _RATCHET_POPULATION_FN:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Attribute) and inner.attr == "findall"
                    and isinstance(inner.value, ast.Name)):
                used = inner.value.id
    if used is None:
        return None

    # 2. с каким литералом это имя связано на верхнем уровне
    pattern_src: Optional[str] = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if used not in targets:
            continue
        call = node.value
        if (isinstance(call, ast.Call) and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            pattern_src = call.args[0].value
    if pattern_src is None:
        return None

    try:
        pattern = re.compile(pattern_src)
    except re.error:
        return None
    found = pattern.findall(bridge.read_text(encoding="utf-8"))
    # Форма с группой отдаёт строки; с несколькими — кортежи. Берём первую группу.
    names = [f if isinstance(f, str) else f[0] for f in found]
    del text
    return sorted(set(names))


def stage_population_by_call_form(root: Path) -> List[str]:
    """Что ступень зовёт на самом деле — тем же зовом, без оглядки на имя переменной."""
    bridge = root / "spa_core" / "monitoring" / "findings_bridge.py"
    if not bridge.is_file():
        return []
    return sorted(set(_STAGE_CALL.findall(bridge.read_text(encoding="utf-8"))))


def measure(root: Path, *, now=None) -> dict:
    """Замер. `root` — КОРЕНЬ ДЕРЕВА (контракт ADR-326), `data/` не читается."""
    root = Path(root)
    if not (root / "spa_core" / "monitoring").is_dir():
        return {
            "status": STATUS_UNMEASURED,
            "overall": STATUS_UNMEASURED,
            "findings": [
                "[НЕ ИЗМЕРЕНО] в дереве нет `spa_core/monitoring` — читать "
                f"нечего (корень: {root}). Это НЕ «потребителей нет»"],
            "counts": {"critical": 0, "warn": 0, "info": 0, "unchecked": 1},
        }

    callees = find_callees(root)
    by_name = find_by_name_consumers(root, callees)
    cli = find_cli_consumers(root, callees)
    dynamic = find_dynamic_consumers(root, callees)
    fleet = find_fleet_consumers(root, callees)

    bridge_rel = "spa_core/monitoring/findings_bridge.py"
    by_name_files = sorted({s["file"] for s in by_name})
    beyond_bridge = [f for f in by_name_files if f != bridge_rel]

    under_ratchet = stage_population_under_ratchet(root)
    by_call_form = stage_population_by_call_form(root)
    ratchet_unmeasured = under_ratchet is None
    unguarded = ([] if ratchet_unmeasured
                 else sorted(set(by_call_form) - set(under_ratchet)))

    findings: List[str] = []

    findings.append(
        f"[ОТВЕТ] переписей (модуль с верхнеуровневым `run()`, принимающим "
        f"`root`): {len(callees)}. Потребителей по классам — "
        f"по имени: файлов {len(by_name_files)} / вызовов {len(by_name)} · "
        f"свой CLI: {len(cli)} · через строку/`importlib`: "
        f"{len(dynamic['resolved'])} · обёртки флота: {len(fleet)}")

    if beyond_bridge:
        findings.append(
            f"[ОТВЕТ] третий исход «потребитель единственный» НЕ наступил: "
            f"кроме моста перепись зовут по имени ещё {len(beyond_bridge)} "
            f"файл(ов) — {', '.join(beyond_bridge)}")
    else:
        findings.append(
            "[ОТВЕТ] по имени перепись зовёт ТОЛЬКО мост — в этом классе "
            "потребитель единственный. На другие классы это не переносится")

    # Согласие о значении `root`: у `by_name` оно написано в вызове.
    disagreeing = sorted({s["callee"] for s in by_name
                          if s["root_argument"] is not None
                          and s["root_argument"] not in ("args.root", "root",
                                                         "str(tree)", "str(root)")})
    passed_forms = sorted({s["root_argument"] for s in by_name
                           if s["root_argument"] is not None})
    findings.append(
        f"[ОТВЕТ] что передают под именем `root` (класс «по имени»): "
        f"{', '.join(passed_forms) if passed_forms else '— ничего явно'}")

    defaults = {}
    for entry in cli:
        defaults.setdefault(str(entry["run_root_default"]), []).append(entry["callee"])
    findings.append(
        "[ОТВЕТ] умолчание `root` у самих переписей (класс «свой CLI»): "
        + " · ".join(f"{k}: {len(v)}" for k, v in sorted(
            defaults.items(), key=lambda kv: -len(kv[1]))))

    required = sorted(e["callee"] for e in cli if e["run_root_default"] is None)
    if required:
        findings.append(
            f"[ИНФО] у {len(required)} переписи(ей) `root` обязателен — умолчания "
            f"нет вовсе, и класс «обёртка не передаёт `root`» её не касается: "
            f"{', '.join(required)}")

    no_flag = sorted(e["callee"] for e in cli
                     if e["has_main"] and not e["exposes_root_flag"])
    if no_flag:
        findings.append(
            f"[ИНФО] {len(no_flag)} переписи(ей) имеют свой `__main__`, но НЕ "
            "показывают флаг `--root`: их корень решает умолчание `run()`, а не "
            "зовущий. Это не дефект — это другой договор, и он должен быть назван")

    if dynamic["unresolved"]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {len(dynamic['unresolved'])} мест(а) зовут "
            "`import_module(<переменная>)`: имя модуля статике не даётся ПО "
            "ПОСТРОЕНИЮ. Достают ли они перепись — не измерено, и нулём это "
            "не считается")

    unprobeable = find_unprobeable(root, callees)
    if unprobeable:
        findings.append(
            f"[ИНФО] {len(unprobeable)} перепись(ей) нельзя позвать, НЕ записав "
            "артефакт: параметра `write` у них нет вовсе. Проба контракта платит "
            "за каждый замер настоящим файлом в дереве пробующего, и отличить "
            "запись пробы от рабочей нельзя: "
            + ", ".join(unprobeable))

    fleet_without_root = [f for f in fleet if not f["passes_root"]]
    if fleet_without_root:
        findings.append(
            f"[ИНФО] обёрток флота, зовущих перепись без `--root`: "
            f"{len(fleet_without_root)} — "
            + ", ".join(f["file"] for f in fleet_without_root))

    status = STATUS_OK
    if ratchet_unmeasured:
        status = STATUS_UNMEASURED
        findings.append(
            "[НЕ ИЗМЕРЕНО] население храповика контракта не выведено: файла нет "
            "либо форма зова связана не с литералом. Это НЕ «храповик покрывает "
            "всё» — покрытие не измерено вовсе")
    elif unguarded:
        status = STATUS_CRITICAL
        findings.append(
            f"[CRITICAL] храповик контракта видит {len(under_ratchet)} "
            f"переписи ступени из {len(by_call_form)}, зовущихся ДОСЛОВНО той же "
            f"формой: вне его {len(unguarded)}. Форма зова в нём требует "
            "ВЕДУЩЕГО ПОДЧЁРКИВАНИЯ в имени переменной-приёмника — это свойство "
            "того, как назвал переменные автор четырёх последних переписей, а не "
            "свойство зова. Заявление «перепись, добавленная завтра, попадает под "
            "проверку сама» верно ровно настолько, насколько завтрашний автор "
            "угадает соглашение об имени")

    if not callees:
        status = STATUS_UNMEASURED
        findings.append(
            "[НЕ ИЗМЕРЕНО] переписей не найдено ни одной — форма поиска "
            "отвечает не на тот вопрос")

    doc = {
        "status": status,
        "overall": status,
        "generated_at": (now.isoformat() if now is not None else None),
        "counts": {
            "callees": len(callees),
            "consumers_by_name_files": len(by_name_files),
            "consumers_by_name_calls": len(by_name),
            "consumers_cli": len(cli),
            "consumers_dynamic_resolved": len(dynamic["resolved"]),
            "consumers_fleet": len(fleet),
            "dynamic_unresolved": len(dynamic["unresolved"]),
            "unprobeable_without_writing": len(unprobeable),
            "stage_under_ratchet": (None if ratchet_unmeasured
                                    else len(under_ratchet)),
            "stage_by_call_form": len(by_call_form),
            "stage_unguarded": len(unguarded),
            "critical": sum(1 for f in findings if f.startswith("[CRITICAL]")),
            "warn": 0,
            "info": sum(1 for f in findings if f.startswith("[ОТВЕТ]")
                        or f.startswith("[ИНФО]")),
            "unchecked": sum(1 for f in findings if f.startswith("[НЕ ИЗМЕРЕНО]")),
        },
        "callees": callees,
        "consumers": {
            "by_name": by_name,
            "cli": cli,
            "dynamic": dynamic,
            "fleet": fleet,
        },
        "stage_ratchet": {
            "under_ratchet": under_ratchet,
            "under_ratchet_unmeasured": ratchet_unmeasured,
            "by_call_form": by_call_form,
            "unguarded": unguarded,
        },
        "disagreeing_root_arguments": disagreeing,
        "unprobeable_without_writing": unprobeable,
        "findings": findings,
        "advisory": (
            "ADVISORY: прибор читает исходники и НАЗЫВАЕТ население потребителей. "
            "POLLED_ADAPTERS, пины, писатель журнала решений, пороги RiskPolicy "
            "v1.0, потолки концентрации, стоп-кран и живой трек НЕ трогаются"),
    }
    return doc


def format_report(doc: dict) -> List[str]:
    lines = [f"census_consumer_census: {doc.get('overall')}"]
    lines.extend(doc.get("findings") or [])
    return lines


def run(root: Optional[str] = None, *, now=None, write: bool = True,
        data_dir: Optional[str] = None) -> dict:
    """Форма ступени переписей: `root` — КОРЕНЬ ДЕРЕВА (ADR-326).

    Явный каталог данных передаётся СВОИМ именем `data_dir=` — одно имя на два
    смысла и было дефектом, который чинил ADR-326.
    """
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    out_dir = Path(data_dir) if data_dir else Path(root) / "data"
    doc = measure(Path(root), now=now)
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(out_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="население потребителей переписей и согласие о `root` (заказ #564)")
    ap.add_argument("--root", default=None, help="КОРЕНЬ ДЕРЕВА")
    ap.add_argument("--data-dir", default=None, help="каталог данных, если не <root>/data")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    root = args.root or str(Path(__file__).resolve().parents[2])
    data_dir = args.data_dir or os.environ.get("SPA_DATA_DIR")
    doc = run(root=root, write=not args.no_write, data_dir=data_dir)
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
