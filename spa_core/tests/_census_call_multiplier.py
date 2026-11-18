"""Множитель цены переписи: за дорогой зов платит КЛАСС или КАЖДЫЙ тест (ADR-1056).

**Предмет.** Перепись живого дерева стои́т минуты. Порог `pytest-timeout` —
`--timeout=180` НА ТЕСТ, и он не складывается по файлу: класс, у которого дорогой
зов стои́т в теле КАЖДОГО теста, платит цену `N` раз и даёт `N` имён в красном
наборе, о которых вердикта нет НИ В ОДНУ сторону (род `wallclock_timeout`,
ADR-1055). Класс, у которого тот же зов стои́т в ``setUpClass``, платит ОДИН раз:
``unittest`` запоминает отказ классовой подготовки (``_classSetupFailed``) и
остальные тесты получают ту же причину мгновенно.

**Замер 2026-11-18 (цикл #1195, прогон `ci-control` 44325110478), на котором
правило и написано** — две крайности одного и того же устройства:

===================================================  =====  =======  ===========
файл                                                 имён   фаза     цена файла
===================================================  =====  =======  ===========
``test_subscript_silencer.py`` (зов в setUpClass)         4  setup       181.2 с
``test_known_member_probe_census.py`` (ленивый кэш)       3  call        541.4 с
===================================================  =====  =======  ===========

181.2 ≈ **1** × 180 против 541.4 ≈ **3** × 180. Цена переписи у второго НИЖЕ
(121.7 с против 57.3 с на хосте у первого) — множитель даёт не цена, а МЕСТО зова.

**Ленивый кэш множитель НЕ снимает, и это главный урок.** Форма
``if cls._census is None: cls._census = <дорогой зов>`` амортизирует всё, кроме
ровно того события, которое обязана пережить: присваивание происходит ПОСЛЕ
возврата, а по сроку зов не возвращается — значит кэш не выставлен, и следующий
тест платит полную цену снова. Поэтому «кэш есть» ответом на вопрос этого модуля
НЕ является: спрашивается МЕСТО зова, а не наличие кэша.

**Ось ФОРМЫ не равна оси СРОКА, и расхождение ИЗМЕРЕНО.** Прибор считает, у
скольких тестов дорогой зов стои́т в их собственном теле; сработает ли он по сроку
— вопрос другой. Замер 2026-11-18: у ``BatteryHoleTests`` форма даёт **3**, а
раннер дал **2** имени по сроку, и разница — ровно
``test_a_reentrant_call_refuses_the_sweep_instead_of_running_it_again``, чья
перепись ОТКАЗЫВАЕТ сама (повторный вход). То есть форма ошибается в сторону
НАХОДКИ, и это объявленное свойство, а не промах.

**Чего модуль НЕ делает.** Он не мерит цену — цена ОБЪЯВЛЕНА в :data:`EXPENSIVE`
вместе с прогоном, в котором снята, и база может только уменьшаться (инв. #16).
Он не ходит за пределы класса: достижимость считается по методам ТОГО ЖЕ класса
до неподвижной точки, а зов через модульного помощника есть ОБЪЯВЛЕННАЯ граница
оси, а не ноль.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Исходы РАЗЛИЧИМЫ (инв. #17): «не зовут» и «не разобрали» — разные ответы.
ONCE = "once_per_class"
MULTIPLIED = "multiplied"
NOT_CALLED = "not_called"
UNMEASURED = "unmeasured"
OUTCOMES = (ONCE, MULTIPLIED, NOT_CALLED, UNMEASURED)

#: Подготовка, цена которой делится на весь класс: ``unittest`` запоминает её
#: отказ и повторно не зовёт.
CLASS_SETUP = ("setUpClass", "setUpModule")

#: Подготовка, которая зовётся на КАЖДЫЙ тест и потому цену НЕ делит. Спутать её
#: с :data:`CLASS_SETUP` значило бы объявить дорогой класс дешёвым; найдено
#: положительным контролем собственной батареи до доставки (цикл #1195): прежде
#: дорогой зов в ``setUp`` был приборy не виден ВОВСЕ — ни один тест не зовёт
#: ``setUp`` по имени, поэтому засев до него не доходил, и класс выходил
#: `not_called`, то есть fail-OPEN.
PER_TEST_SETUP = ("setUp", "asyncSetUp", "tearDown", "asyncTearDown")

#: Сколько кругов засева достижимости внутри класса. Исчерпание — не «достигли
#: всего», а :data:`UNMEASURED` с названной причиной.
HOPS = 5

#: Дорогие точки входа — ОБЪЯВЛЕНИЕ с ценой и прогоном, в котором она снята.
#:
#: **Цена берётся у РАННЕРА, а не у хоста, и это замер, а не вкус.** Замер
#: 2026-11-18 на четырёх файлах, чья цена известна с обеих сторон, дал разброс
#: отношения хост/раннер **0.58×…11.2×** (`test_lint_forbidden_imports` 4.1 с
#: против 7.13 с · `test_absent_observation_probe` 16.0 против 16.48 ·
#: `test_absent_path_probe` 15.1 против 9.60 · `test_maturity_register` **222.9
#: против 19.96**). Два объяснения разброса ОПРОВЕРГНУТЫ замером: единого
#: множителя нет, размером дерева он не объясняется (12 432 файла против 10 659
#: в чекауте, `data/` 409 против 407). Поэтому числом хоста на вопрос «уложится
#: ли в 180 с на раннере» отвечать НЕЛЬЗЯ ни в одну сторону, а цена хоста
#: оставлена только как подпорка для разложения.
#:
#: ``cheap_when`` называет ДВЕРЬ САМОГО ПРИБОРА, которой зовущий отключает
#: дорогую часть: зов, передавший её явно, дорогим не считается — иначе правило
#: краснело бы на семи зовах `run_identity_key_price`, у которых перепись выключена.
#: База может только УМЕНЬШАТЬСЯ: подешевевшая перепись из неё УХОДИТ, а
#: дописывать сюда, чтобы погасить падение, запрещено (инв. #16).
EXPENSIVE: Dict[str, Dict[str, Any]] = {
    "known_member_probe_census.calibrated_measure": {
        "runner_file_s": 541.4,
        "runner_run": "44325110478",
        "host_s": 121.7,
        "measured_at": "2026-11-18",
        "cheap_when": None,
    },
    "_subscript_silencer.subscript_reads": {
        "runner_file_s": 181.2,
        "runner_run": "44325110478",
        "host_s": 57.3,
        "measured_at": "2026-11-18",
        "cheap_when": None,
    },
    "run_identity_key_price.measure": {
        "runner_file_s": 369.4,
        "runner_run": "44325110478",
        "host_s": None,
        "measured_at": "2026-11-18",
        "cheap_when": {"kwarg": "sweep_readers", "value": False},
    },
}

#: Порог `pytest-timeout` на ТЕСТ в контрольном прогоне (`ci-control.yml`).
#: Поднимать ЗАПРЕЩЕНО (инв. #16, прямая строка `CLAUDE.md`) — он здесь затем,
#: чтобы множитель можно было перевести в секунды, а не затем, чтобы его двигать.
RUNNER_TIMEOUT_S = 180


def _called_names(node: ast.AST) -> List[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _call_label(call: ast.Call) -> Optional[str]:
    """``mod.func(...)`` → ``"mod.func"``. Голое имя меткой не является.

    Литерал в строке меткой не становится ПО ПОСТРОЕНИЮ: спрашивается узел
    :class:`ast.Call`, а не подстрока (ADR-333).
    """
    fn = call.func
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        return f"{fn.value.id}.{fn.attr}"
    return None


def _is_cheap(call: ast.Call, cheap_when: Optional[Dict[str, Any]]) -> bool:
    """Зов, ЯВНО открывший дешёвую дверь прибора, дорогим не считается."""
    if not cheap_when:
        return False
    for kw in call.keywords:
        if kw.arg != cheap_when["kwarg"]:
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value == cheap_when["value"]:
            return True
    return False


def module_aliases(tree: ast.Module) -> Dict[str, str]:
    """Чьё имя стои́т слева от точки: ``import x as y`` / ``from a import b as c``.

    Без этого вопроса ось была бы ИМЕНЕМ ФУНКЦИИ, и любой чужой
    ``whatever.measure(...)`` читался бы объявленной переписью — тот самый класс
    «совпало по подстроке», против которого написан ADR-333.
    """
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[-1]] = alias.name.split(".")[-1]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out[alias.asname or alias.name] = alias.name
    return out


def _expensive_calls(func: ast.AST,
                     declared: Dict[str, Dict[str, Any]],
                     aliases: Dict[str, str]) -> List[str]:
    out: List[str] = []
    for call in _called_names(func):
        label = _call_label(call)
        if label is None:
            continue
        alias, _, attr = label.partition(".")
        module = aliases.get(alias)
        if module is None:
            continue                       # имя слева не ввезено — не наш предмет
        for key, spec in declared.items():
            want_module, _, want_func = key.rpartition(".")
            if attr != want_func or module != want_module:
                continue
            if _is_cheap(call, spec.get("cheap_when")):
                continue
            out.append(key)
    return out


def _methods(cls: ast.ClassDef) -> Dict[str, ast.AST]:
    return {n.name: n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _self_calls(func: ast.AST, known: Iterable[str]) -> List[str]:
    """Зовы методов ТОГО ЖЕ класса — именно так выглядит ленивый кэш."""
    names = set(known)
    out = []
    for call in _called_names(func):
        fn = call.func
        if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                and fn.value.id in ("self", "cls") and fn.attr in names):
            out.append(fn.attr)
    return out


def class_payers(cls: ast.ClassDef,
                 declared: Optional[Dict[str, Dict[str, Any]]] = None,
                 aliases: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Кто платит за дорогой зов в ЭТОМ классе и сколько раз.

    Возвращает ``{"outcome", "payers", "entry_points", "via_class_setup", "why"}``.
    ``payers`` — имена тестов, КАЖДЫЙ из которых зовёт дорогую перепись сам.
    """
    declared = EXPENSIVE if declared is None else declared
    aliases = {} if aliases is None else aliases
    methods = _methods(cls)

    # Засев достижимости внутри класса до неподвижной точки.
    direct = {name: set(_expensive_calls(fn, declared, aliases))
              for name, fn in methods.items()}
    reach = {name: set(hits) for name, hits in direct.items()}
    for _ in range(HOPS):
        grew = False
        for name, fn in methods.items():
            for callee in _self_calls(fn, methods):
                before = len(reach[name])
                reach[name] |= reach.get(callee, set())
                grew = grew or len(reach[name]) != before
        if not grew:
            break
    else:
        return {"outcome": UNMEASURED, "payers": [], "entry_points": [],
                "via_class_setup": False,
                "why": f"засев достижимости не сошёлся за {HOPS} кругов — "
                       "достижимость НЕ ИЗМЕРЕНА, и нулём это не считается"}

    setup_hits: set = set()
    for name in CLASS_SETUP:
        setup_hits |= reach.get(name, set())

    per_test_hits: set = set()
    for name in PER_TEST_SETUP:
        per_test_hits |= reach.get(name, set())

    tests = [name for name in methods if name.startswith("test_")]
    payers = sorted(name for name in tests if reach[name] or per_test_hits)
    points = sorted({p for name in payers for p in reach[name]}
                    | setup_hits | per_test_hits)

    if setup_hits:
        return {"outcome": ONCE, "payers": payers, "entry_points": points,
                "via_class_setup": True,
                "why": "дорогой зов стои́т в классовой подготовке — цена делится "
                       "на весь класс, и её платят ОДИН раз"}
    if not payers:
        return {"outcome": NOT_CALLED, "payers": [], "entry_points": [],
                "via_class_setup": False,
                "why": "ни один тест класса дорогую перепись не зовёт"}
    if len(payers) >= 2:
        return {"outcome": MULTIPLIED, "payers": payers, "entry_points": points,
                "via_class_setup": False,
                "why": f"{len(payers)} теста зовут дорогую перепись КАЖДЫЙ сам: "
                       f"{', '.join(points)}. Цена умножается на "
                       f"{len(payers)} (до {len(payers) * RUNNER_TIMEOUT_S} с по "
                       "сроку), и столько же имён уходит в красный набор БЕЗ "
                       "вердикта. Известный выход — ОДИН зов на класс "
                       "(setUpClass): ленивый кэш множитель НЕ снимает, "
                       "присваивание идёт ПОСЛЕ возврата, а по сроку возврата "
                       "нет. ПРИМЕНИМ ли он здесь — решает предмет тестов "
                       "(своя сцена на тест, утверждение о побочном действии), "
                       "и прибор за них этого НЕ решает"}
    return {"outcome": ONCE, "payers": payers, "entry_points": points,
            "via_class_setup": False,
            "why": "дорогую перепись зовёт РОВНО ОДИН тест — множителя нет"}


def census(root: Optional[Path] = None,
           roots: Sequence[str] = ("spa_core/tests", "scripts/tests", "tests"),
           declared: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Перепись множителя по дереву. Нечитаемый файл — :data:`UNMEASURED`, не ноль."""
    root = Path(root) if root is not None else REPO_ROOT
    declared = EXPENSIVE if declared is None else declared
    rows: List[Dict[str, Any]] = []
    tally = {outcome: 0 for outcome in OUTCOMES}
    files_unread = 0

    for rel in roots:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError) as exc:
                files_unread += 1
                rows.append({"file": str(path.relative_to(root)), "class": None,
                             "outcome": UNMEASURED, "payers": [], "entry_points": [],
                             "why": f"файл не разобран: {type(exc).__name__}: {exc}"})
                tally[UNMEASURED] += 1
                continue
            aliases = module_aliases(tree)
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                verdict = class_payers(cls, declared, aliases)
                if verdict["outcome"] == NOT_CALLED:
                    continue
                rows.append({"file": str(path.relative_to(root)),
                             "class": cls.name, **verdict})
                tally[verdict["outcome"]] += 1

    return {"schema": "spa-census-call-multiplier/1",
            "root": str(root),
            "declared": sorted(declared),
            "rows": rows,
            "tally": tally,
            "files_unread": files_unread,
            "multiplied": [r for r in rows if r["outcome"] == MULTIPLIED]}


def format_report(doc: Dict[str, Any]) -> List[str]:
    out = [f"МНОЖИТЕЛЬ ЦЕНЫ ПЕРЕПИСИ · дерево {doc['root']}",
           f"  объявлено дорогих точек входа: {len(doc['declared'])}"]
    for outcome in OUTCOMES:
        out.append(f"  {outcome}: {doc['tally'][outcome]}")
    if doc["files_unread"]:
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО: файлов не прочитано {doc['files_unread']}")
    for row in doc["multiplied"]:
        out.append(f"  ❌ {row['file']}::{row['class']} — {row['why']}")
    if not doc["multiplied"]:
        out.append("  ✅ множителя нет НИ У ОДНОГО класса — это замер, а не "
                   "отсутствие замера")
    return out
