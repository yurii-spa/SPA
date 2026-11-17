#!/usr/bin/env python3
"""Перепись класса «наш хук трогает объект, который ПОЗЖЕ заменяет чужая реализация
того же хука» (ADR-1037, заказ G1025 п. 3).

**Зачем.** ADR-1036 (16.11) нашёл этот класс жертвой: санитар трассы ADR-768 чистил
``call.excinfo`` в обёртке ``pytest_runtest_makereport``, а ПЛОСКИЙ встроенный хук
``_pytest/unittest.py::pytest_runtest_makereport`` ПОДМЕНЯЕТ этот объект и идёт ПОЗЖЕ
нашей обёртки. Починка не работала ни одного дня, цена — два обморока сессии (17.10
прогон 39003158532, шард 2, 4320 тестов без исхода; 16.11 прогон 43933147333, шард 7).
Население класса ADR-1036 оставил НЕ ИЗМЕРЕННЫМ и нулём это не считал.

**Три оси, и ни одна не заменяет другую.**

1. **ПОРЯДОК ЗОВА — ИЗМЕРЕН, а не выведен из чтения.** Дочерний pytest поднимается
   ровно с теми плагинами, с какими его поднимает CI-шард, и наблюдатель на
   ``pytest_collection_finish`` выписывает у КАЖДОГО хука последовательность вызова.
   Порядок берётся у живого pluggy: ``_multicall`` идёт по ``reversed(hook_impls)``,
   поэтому последовательность зова = ``reversed(get_hookimpls())``. Утверждение про
   этот порядок закреплено положительным контролем в батарее, а не принято на веру.
2. **ПРЕДИКАТ — что именно трогает НАША реализация** (AST): пути вида
   ``<аргумент хука>.<поле>``, прочитанные или записанные в теле, с засевом локальных
   имён до неподвижной точки и спуском в помощников ТОГО ЖЕ модуля. У обёртки
   различается ДО ``yield`` и ПОСЛЕ: после ``yield`` наша реализация видит уже
   окончательное состояние и в класс не попадает ПО ПОСТРОЕНИЮ.
3. **ЗАМЕНА — что ЗАПИСЫВАЕТ чужая реализация того же хука, идущая ПОЗЖЕ нашей**
   (AST): присваивания ``<аргумент>.<поле> = …``, ``setattr``, ``del``.

**Член класса** = пересечение осей 2 и 3 по ПАРЕ «имя аргумента хука + имя поля»:
наша реализация трогает ``call.excinfo``, а идущая позже чужая его ПРИСВАИВАЕТ.
Имена аргументов — часть контракта хука и общие у всех его реализаций, поэтому
пара сравнима; совпадение по одному полю без аргумента было бы подстрокой.

**Чего прибор НЕ говорит.** Что наша реализация НЕ УЧИТЫВАЕТ замену: форма класса и
дефект — разные утверждения. После починки ADR-1036 санитар перечисляет оба источника
будущего ``call.excinfo`` и остаётся в форме класса, но дефектом быть перестал. Поэтому
прибор называет ФОРМУ (кандидатов) и только ЧИТАЕТ; судит их человек, и объявление
класса (``spa_core/tests/hook_arg_mutation_class_baseline.json``) существует ровно для
того, чтобы НОВЫЙ вошедший в форму был видим, а не стоил следующих 4320 тестов.

**Три исхода различимы** (инв. #17): измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО с
названной причиной (дочерний pytest не дал записи · файл реализации не читается · имени
функции нет в AST · спуск в помощников исчерпал глубину) — и это ненулевой код возврата,
а не пустой список.

Коды возврата: **0** — измерено, состав совпал с объявленным · **1** — состав РАЗОШЁЛСЯ
с объявленным (пришло новое · объявленное исчезло) · **2** — НЕ ИЗМЕРЕНО (fail-CLOSED).

Только stdlib (инв. #4). Прибор ЧИТАЕТ: ничего не чинит и ничего не пишет в ``data/``.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: Корень дерева ПРИБОРА. Нужен на `sys.path`, потому что прибор зовут и как скрипт
#: (`python3 scripts/hook_arg_mutation_census.py` — тогда `sys.path[0]` это `scripts/`,
#: и `import spa_core` не находится), и импортом из батареи.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNMEASURED = 2

#: Плагины, которыми CI-шард поднимает набор (`.github/workflows/ci-control.yml`).
#: Перечень — часть контракта: разойдись он с воркфлоу, прибор отвечал бы о наборе,
#: которого в CI не бывает.
SHARD_PLUGINS = ("spa_core.ci.pytest_stream_record", "spa_core.ci.pytest_collect_manifest")

#: Цели сборки. Нужны РОВНО чтобы загрузились оба `conftest.py` (они грузятся при
#: обходе своего каталога), поэтому берётся по одному файлу из каждого корня.
PROBE_TARGETS = ("tests/test_doc_drift.py", "spa_core/tests/test_typed_numbers_target_as_paper.py")

#: Имя плагина-наблюдателя. Прибор ОБЯЗАН вычесть себя из предмета: иначе он мерил бы
#: своё собственное возмущение (замер ADR-898: два прогона одного прибора дали
#: несовместимые наборы кандидатов, и оба оказались его же следом).
OBSERVER_PLUGIN = "spa_hook_order_observer"

#: Глубина спуска в помощников того же модуля. Исчерпание — НЕ ИЗМЕРЕНО с причиной,
#: а не «дальше ничего нет».
HELPER_DEPTH = 3
#: Круги засева локальных имён до неподвижной точки (метод ADR-932).
SEED_ROUNDS = 5

_OBSERVER = '''\
"""Наблюдатель порядка зова (пишется прибором hook_arg_mutation_census.py)."""
import inspect, json, os, sys


def pytest_collection_finish(session):
    out = os.environ.get("SPA_HOOK_ORDER_OUT")
    if not out:
        return
    pm = session.config.pluginmanager
    hooks = {}
    for name, caller in sorted(vars(pm.hook).items()):
        rows = []
        # ПОРЯДОК ЗОВА: pluggy._callers._multicall идёт по reversed(hook_impls).
        for impl in reversed(caller.get_hookimpls()):
            fn = impl.function
            try:
                src = inspect.getsourcefile(fn)
            except Exception as exc:                       # pragma: no cover
                src = "UNREADABLE: %s: %s" % (type(exc).__name__, exc)
            rows.append({
                "plugin": str(impl.plugin_name),
                "func": getattr(fn, "__name__", "?"),
                "file": src,
                "module": getattr(fn, "__module__", "?"),
                "wrapper": bool(getattr(impl, "wrapper", False)),
                "hookwrapper": bool(getattr(impl, "hookwrapper", False)),
                "tryfirst": bool(impl.tryfirst),
                "trylast": bool(impl.trylast),
                "argnames": list(impl.argnames),
            })
        if rows:
            hooks[name] = rows
    import pluggy, pytest
    with open(out, "w") as fh:
        json.dump({"pluggy": pluggy.__version__, "pytest": pytest.__version__,
                   "hooks": hooks}, fh, indent=1, sort_keys=True)
'''


# ─────────────────────────── ось 1: порядок зова ───────────────────────────

def measure_call_order(repo_root: Path, extra_plugins=(), targets=PROBE_TARGETS,
                       plugins=SHARD_PLUGINS):
    """Снять последовательность зова у ЖИВОГО pluggy. Возвращает (payload, причина)."""
    with tempfile.TemporaryDirectory(prefix="hook_order_") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "spa_hook_order_observer.py").write_text(_OBSERVER, encoding="utf-8")
        out = tmpdir / "order.json"
        env = {**os.environ}
        env["SPA_ENV"] = env.get("SPA_ENV", "ci")
        env["PYTHONHASHSEED"] = "0"
        env["SPA_HOOK_ORDER_OUT"] = str(out)
        # PATH/интерпретатор — из своего окружения: собранный руками PATH даёт ДРУГОЙ
        # python3, pytest не запускается вовсе, а разбор пустого вывода честно отдаёт
        # пустой список (ловушка цикла #1175, заказ G1025 п. 7).
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tmpdir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        # Маркер песочницы C8(b) (ADR-580, храповик `test_sandbox_wiring_ratchet`): ребёнок
        # импортирует ДЕРЕВО, на которое мы переставили `PYTHONPATH`, и читатель без своего
        # параметра `data_dir` молча ушёл бы в ПРОД (форма INC-1). Маркер идёт ВМЕСТЕ со
        # своей песочницей: один маркер без `SPA_LIVE_ROOT`/`SPA_DATA_DIR` заставил бы
        # двери ребёнка ОТКАЗАТЬ на прод-каталоге — и перепись осталась бы НЕ ИЗМЕРЕННОЙ.
        sandbox = tmpdir / "sandbox"
        (sandbox / "data").mkdir(parents=True, exist_ok=True)
        env["SPA_SANDBOX"] = "1"
        env["SPA_LIVE_ROOT"] = str(sandbox)
        env["SPA_DATA_DIR"] = str(sandbox / "data")
        cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly",
               "-p", "spa_hook_order_observer"]
        for plugin in (*plugins, *extra_plugins):
            cmd += ["-p", plugin]
        cmd += list(targets)
        try:
            proc = subprocess.run(cmd, cwd=str(repo_root), env=env, text=True,
                                  capture_output=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"дочерний pytest не отработал: {type(exc).__name__}: {exc}"
        if not out.exists():
            tail = (proc.stderr or proc.stdout or "")[-600:]
            return None, ("наблюдатель не записал порядок зова "
                          f"(код {proc.returncode}); хвост вывода: {tail!r}")
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f"запись порядка зова не читается: {type(exc).__name__}: {exc}"
        payload["child_returncode"] = proc.returncode
        payload["child_cmd"] = cmd
        return payload, None


# ─────────────────────────── разбор исходников ───────────────────────────

class _Source:
    """Кэш разобранных модулей. Нечитаемый файл — НЕ ИЗМЕРЕНО с причиной."""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}

    def module(self, path: str):
        if path in self._cache:
            return self._cache[path]
        try:
            tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
            value: object = tree
        except (OSError, ValueError, SyntaxError) as exc:
            value = f"НЕ ИЗМЕРЕНО: {type(exc).__name__}: {exc}"
        self._cache[path] = value
        return value

    def function(self, path: str, name: str):
        tree = self.module(path)
        if isinstance(tree, str):
            return None, tree
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node, None
        return None, f"НЕ ИЗМЕРЕНО: имени `{name}` нет в AST файла {path}"

    def module_functions(self, path: str) -> dict:
        tree = self.module(path)
        if isinstance(tree, str):
            return {}
        return {n.name: n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _attr_root(node):
    """Корневое имя цепочки `a.b.c` → ('a', ['b','c']); иначе (None, [])."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id, list(reversed(parts))
    return None, []


def _getattr_call(node):
    """`getattr(x, "y")` → (узел x, 'y'); иначе (None, None)."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
        return node.args[0], node.args[1].value
    return None, None


def _yield_lineno(fn):
    """Строка первого `yield` в теле — граница «до/после» у обёртки."""
    for node in ast.walk(fn):
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return getattr(node, "lineno", None)
    return None


def _seed_locals(fn, rootmap: dict) -> dict:
    """Локальные имена, ЗНАЧЕНИЕ которых происходит от аргументов хука.

    Возвращает карту «локальное имя → имя АРГУМЕНТА ХУКА, от которого оно
    происходит». Контейнер привязкой НЕ является (урок `_injected_clock`):
    учитываются только прямые формы `x = <корень>`, `x = <корень>.поле`,
    `x = getattr(<корень>, "поле")` — «RHS содержит якорь» происхождением не
    считается, иначе оправдали бы ровно ту форму, ради которой правило написано.
    """
    tracked = dict(rootmap)
    for _ in range(SEED_ROUNDS):
        before = len(tracked)
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            base, _attr = _getattr_call(value)
            if base is not None:
                value = base
            if not isinstance(value, (ast.Attribute, ast.Name)):
                continue
            root, _parts = _attr_root(value)
            if root is None or root not in tracked:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    tracked.setdefault(target.id, tracked[root])
        if len(tracked) == before:
            return tracked
    return tracked          # исчерпание кругов сообщается вызывающим как граница оси


def touched_paths(src: _Source, path: str, func: str, argnames, is_wrapper: bool):
    """Пары (аргумент хука, поле), которые НАША реализация трогает ДО `yield`.

    Возвращает (множество пар, список причин «НЕ ИЗМЕРЕНО», список границ оси).
    """
    fn, why = src.function(path, func)
    if fn is None:
        return set(), [why], []
    boundaries: list[str] = []
    found: set = set()
    cut = _yield_lineno(fn) if is_wrapper else None
    helpers = src.module_functions(path)
    visited: set = set()

    def visit(fn_node, rootmap: dict, depth: int, cut_line, label: str) -> None:
        if depth > HELPER_DEPTH:
            boundaries.append(f"{label}: спуск в помощников исчерпал глубину {HELPER_DEPTH}")
            return
        key = (fn_node.name, tuple(sorted(rootmap.items())))
        if key in visited:
            return
        visited.add(key)
        tracked = _seed_locals(fn_node, rootmap)
        for node in ast.walk(fn_node):
            line = getattr(node, "lineno", None)
            if cut_line is not None and line is not None and line > cut_line:
                continue        # после `yield` обёртка видит ОКОНЧАТЕЛЬНОЕ состояние
            base, attr = _getattr_call(node)
            if base is not None:
                if isinstance(base, (ast.Attribute, ast.Name)):
                    root, parts = _attr_root(base)
                    if root in tracked and not parts:
                        found.add((tracked[root], attr))
                continue
            if isinstance(node, ast.Attribute):
                root, parts = _attr_root(node)
                if root in tracked and parts:
                    found.add((tracked[root], parts[0]))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                helper = helpers.get(node.func.id)
                if helper is None or helper is fn_node:
                    continue
                formals = [a.arg for a in helper.args.args]
                mapping: dict = {}
                for idx, arg in enumerate(node.args):
                    if not isinstance(arg, (ast.Attribute, ast.Name)):
                        continue
                    root, parts = _attr_root(arg)
                    if root in tracked and not parts and idx < len(formals):
                        mapping[formals[idx]] = tracked[root]
                if mapping:
                    visit(helper, mapping, depth + 1, None, f"{label}→{helper.name}")

    visit(fn, {a: a for a in argnames}, 0, cut, f"{path}::{func}")
    return {pair for pair in found if pair[0] in set(argnames)}, [], boundaries


def assigned_paths(src: _Source, path: str, func: str, argnames, is_wrapper: bool):
    """Пары (аргумент, поле), которые ЧУЖАЯ реализация ПРИСВАИВАЕТ (до `yield`)."""
    fn, why = src.function(path, func)
    if fn is None:
        return set(), [why]
    cut = _yield_lineno(fn) if is_wrapper else None
    out: set[tuple[str, str]] = set()
    roots = set(argnames)
    tracked = _seed_locals(fn, {a: a for a in argnames})
    for node in ast.walk(fn):
        line = getattr(node, "lineno", None)
        if cut is not None and line is not None and line > cut:
            continue
        targets: list = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        for target in targets:
            if isinstance(target, ast.Attribute):
                root, parts = _attr_root(target)
                if root in tracked and parts:
                    out.add((root, parts[0]))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            root, parts = (_attr_root(node.args[0])
                           if isinstance(node.args[0], (ast.Attribute, ast.Name)) else (None, []))
            if root in tracked and not parts:
                out.add((root, node.args[1].value))
    return {pair for pair in out if pair[0] in roots}, []


# ─────────────────────────── ось 3: соединение ───────────────────────────

def census(repo_root: Path, extra_plugins=(), targets=PROBE_TARGETS,
           plugins=SHARD_PLUGINS) -> dict:
    root = str(repo_root.resolve())
    payload, why = measure_call_order(repo_root, extra_plugins, targets, plugins)
    if payload is None:
        return {"verdict": "unmeasured", "reasons": [why], "members": [], "rows": []}

    src = _Source()
    unmeasured: list[str] = []
    boundaries: list[str] = []
    rows = []
    members = []
    ours_total = 0

    observer_seen = 0
    for hook, all_impls in sorted(payload["hooks"].items()):
        # Прибор вычитает СЕБЯ: наблюдатель — не предмет, а инструмент наблюдения.
        impls = [i for i in all_impls if i.get("plugin") != OBSERVER_PLUGIN]
        observer_seen += len(all_impls) - len(impls)
        for position, impl in enumerate(impls):
            file = impl.get("file") or ""
            if not file.startswith(root + os.sep) and file != root:
                continue
            ours_total += 1
            is_wrapper = impl["wrapper"] or impl["hookwrapper"]
            touched, why_ours, bound = touched_paths(
                src, file, impl["func"], impl["argnames"], is_wrapper)
            unmeasured.extend(why_ours)
            boundaries.extend(bound)
            later = []
            for other in impls[position + 1:]:
                other_file = other.get("file") or ""
                if other_file.startswith(root + os.sep):
                    continue                        # чужая = НЕ наша
                if other_file.startswith("UNREADABLE"):
                    unmeasured.append(f"{hook}: исходник реализации `{other['plugin']}` "
                                      f"не определён: {other_file}")
                    continue
                wrote, why_other = assigned_paths(
                    src, other_file, other["func"], other["argnames"],
                    other["wrapper"] or other["hookwrapper"])
                unmeasured.extend(why_other)
                overlap = sorted(touched & wrote)
                later.append({"plugin": other["plugin"], "file": other_file,
                              "builtin": "/_pytest/" in other_file,
                              "flat": not (other["wrapper"] or other["hookwrapper"]),
                              "assigns": sorted(f"{a}.{b}" for a, b in wrote),
                              "overlap": [f"{a}.{b}" for a, b in overlap]})
            row = {"hook": hook, "position": position, "ours": file[len(root) + 1:],
                   "func": impl["func"], "plugin": impl["plugin"],
                   "wrapper": is_wrapper, "tryfirst": impl["tryfirst"],
                   "trylast": impl["trylast"],
                   "touches": sorted(f"{a}.{b}" for a, b in touched),
                   "later_not_ours": later}
            rows.append(row)
            hit = sorted({p for entry in later for p in entry["overlap"]})
            if hit:
                members.append({"key": f"{row['ours']}::{impl['func']}#{hook}",
                                "paths": hit,
                                "replaced_by": sorted({entry["plugin"] for entry in later
                                                       if entry["overlap"]})})

    verdict = "unmeasured" if unmeasured else "measured"
    return {"verdict": verdict, "reasons": sorted(set(unmeasured)),
            "boundaries": sorted(set(boundaries)), "rows": rows,
            "members": sorted(members, key=lambda m: m["key"]),
            "ours_total": ours_total, "observer_impls_subtracted": observer_seen,
            "pluggy": payload.get("pluggy"), "pytest": payload.get("pytest"),
            "hooks_seen": len(payload["hooks"])}


def _load_baseline(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"объявление класса НЕ ПРОЧИТАНО ({path}): {type(exc).__name__}: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("members"), list):
        return None, f"объявление класса не в объявленной форме ({path})"
    return data, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=None,
                    help="дерево, у которого спрашивают (умолчание — дерево прибора, ПЕЧАТАЕТСЯ)")
    ap.add_argument("--baseline", default=None,
                    help="объявление класса (умолчание — spa_core/tests/hook_arg_mutation_class_baseline.json)")
    ap.add_argument("--extra-plugin", action="append", default=[],
                    help="дополнительный плагин для дочернего pytest (контроль-бомба)")
    ap.add_argument("--plugin", action="append", default=[],
                    help="заменить перечень плагинов шарда (для одноразовой сцены контроля)")
    ap.add_argument("--target", action="append", default=[],
                    help="цель сборки дочернего pytest (умолчание — по одному файлу на корень)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--no-baseline", action="store_true",
                    help="не сверять с объявлением (только назвать состав)")
    args = ap.parse_args(argv)

    default_root = PROJECT_ROOT
    # Умолчание РАЗРЕШАЕТСЯ ДО двери: судить `None` нельзя (инв. #17).
    root = Path(args.repo_root).expanduser().resolve() if args.repo_root else default_root
    # ADR-1000 транш 1 (добавлено циклом #1177, ADR-1038): точка входа с умолчанием
    # каталога, ДОСТИЖИМЫМ у руки, обязана спросить дверь песочницы ДО первой работы —
    # и ДО отказа «дерево не репозиторий»: тот тоже выходит кодом 2, и без имени двери
    # код 2 ничего бы не доказывал. Ввоз здесь, а не в шапке: так же, как у соседей транша.
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks
    refuse_if_sandbox_leaks(root, who="hook_arg_mutation_census")
    if args.repo_root:
        if not (root / "scripts").is_dir():
            print(f"❌ НЕ ИЗМЕРЕНО: названное дерево не читается как репозиторий: {root}",
                  file=sys.stderr)
            return EXIT_UNMEASURED
        print(f"дерево: {root} (НАЗВАНО входом --repo-root)")
    else:
        print(f"дерево: {root} (УМОЛЧАНИЕ — дерево прибора; назвать входом --repo-root)")

    targets = tuple(args.target) if args.target else PROBE_TARGETS
    plugins = tuple(args.plugin) if args.plugin else SHARD_PLUGINS
    result = census(root, tuple(args.extra_plugin), targets, plugins)

    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False, sort_keys=True))
    else:
        print(f"порядок зова снят у живого pluggy {result.get('pluggy')} / "
              f"pytest {result.get('pytest')}; хуков с реализациями: {result.get('hooks_seen')}")
        print(f"НАШИХ реализаций в живом наборе: {result.get('ours_total')} "
              f"(реализаций наблюдателя вычтено: {result.get('observer_impls_subtracted')})")
        for row in result["rows"]:
            tag = "обёртка" if row["wrapper"] else "плоский"
            print(f"  {row['hook']} · {row['ours']}::{row['func']} "
                  f"(поз. {row['position']}, {tag}"
                  f"{', tryfirst' if row['tryfirst'] else ''}"
                  f"{', trylast' if row['trylast'] else ''})")
            print(f"      трогает: {', '.join(row['touches']) or '—'}")
            for entry in row["later_not_ours"]:
                mark = "⚠️ ПЕРЕСЕЧЕНИЕ " + ", ".join(entry["overlap"]) if entry["overlap"] else ""
                print(f"      позже: {entry['plugin']} "
                      f"({'встроенный' if entry['builtin'] else 'сторонний'}, "
                      f"{'плоский' if entry['flat'] else 'обёртка'}) "
                      f"присваивает: {', '.join(entry['assigns']) or '—'} {mark}")
        for line in result.get("boundaries", []):
            print(f"  ГРАНИЦА ОСИ: {line}")

    if result["verdict"] == "unmeasured":
        for reason in result["reasons"]:
            print(f"❌ НЕ ИЗМЕРЕНО: {reason}", file=sys.stderr)
        return EXIT_UNMEASURED

    observed = sorted(m["key"] for m in result["members"])
    if not observed:
        print("✅ ИЗМЕРЕНО И РАВНО НУЛЮ: ни одна наша реализация не трогает поле, "
              "которое присваивает идущая позже чужая реализация того же хука")
    else:
        print(f"состав класса (ИЗМЕРЕН): {len(observed)}")
        for member in result["members"]:
            print(f"  • {member['key']} — {', '.join(member['paths'])} "
                  f"← заменяет {', '.join(member['replaced_by'])}")

    if args.no_baseline:
        return EXIT_OK

    baseline_path = Path(args.baseline) if args.baseline else (
        root / "spa_core" / "tests" / "hook_arg_mutation_class_baseline.json")
    baseline, why = _load_baseline(baseline_path)
    if baseline is None:
        print(f"❌ НЕ ИЗМЕРЕНО: {why}", file=sys.stderr)
        return EXIT_UNMEASURED
    declared = sorted(str(m) for m in baseline["members"])
    came = [k for k in observed if k not in declared]
    gone = [k for k in declared if k not in observed]
    if came or gone:
        if came:
            print(f"❌ ПРИШЛО НОВОЕ ({len(came)}): " + ", ".join(came), file=sys.stderr)
        if gone:
            print(f"❌ ОБЪЯВЛЕННОЕ ИСЧЕЗЛО ({len(gone)}): " + ", ".join(gone), file=sys.stderr)
        print(f"   объявление: {baseline_path}", file=sys.stderr)
        return EXIT_FINDINGS
    print(f"✅ состав РОВНО совпал с объявленным ({len(declared)}): {baseline_path.name}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
