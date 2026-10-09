"""Критерий §49 `No regression` приказа «Portfolio CIO»: проходят ли существующие
risk / security / architecture-тесты.

Критерий владельца звучит дословно так:

    **No regression.** Existing risk/security/architecture tests проходят.

Вопрос простой, а подмен у него две, и обе уже случались.

**Подмена первая — цветом джобы.** «CI красный» ≠ «тесты падают», и «CI зелёный» ≠
«эти тесты прошли». Замер 28.09 (прогон ``test.yml`` 36350773679 о `351c84162`): шаг
``spa_core/tests/`` снят по ``timeout-minutes`` через 240 минут на ``[ 94%]``,
junit-записи нет, потоковая запись говорит «начато 101 206 · упало 61 · сессия дошла
до конца: НЕТ», и из 61 имени в логе напечатано 20 (``ci_verdict._NAMES_SHOWN``), а
``reports/`` артефактом не выгружается. То есть у шага, где живёт 101 206 тестов из
~121 000, вердикт о ВЕРШИНЕ ``main`` не измерен — и ответ «проходят ли risk-тесты» из
цвета джобы не извлекается ни в какую сторону.

**Подмена вторая — именем файла.** «risk-тесты» по имени дают свыше сотни файлов
``test_defi_*_risk_*.py``, и это advisory-анализаторы, к RiskPolicy отношения не
имеющие; в обратную сторону ``spa_core/tests/test_risk_policy.py`` пишет
``from risk.policy import …`` (в ``sys.path`` кладётся ``spa_core/``), поэтому
правило, знающее одно написание, теряет ГЛАВНЫЙ risk-тест системы. Поэтому
принадлежность меряется у самого теста — по тому, ЧТО ОН ИМПОРТИРУЕТ, — а оба
капкана закрыты положительными контролями в наборе.

## Что здесь население, а что вердикт

======================== ====================================================
население                тест-ФАЙЛ, импортирующий объявленную поверхность
                         (``DECLARED_SURFACES``), плюс сторож, который САМ и
                         есть проверка инварианта (импортировать ему нечего)
вердикт члена населения  из junit-ЗАПИСИ прогона, поданной аргументом
======================== ====================================================

Запись — **ВХОД**, а не окружение: прибор не запускает pytest сам. Так его можно
проверить фикстурой, а не живым прогоном, и он остаётся read-only — тот же порядок,
что у часов, pid и сети в ``.claude/rules/deployment.md``.

## Третий исход обязателен (инв. #17)

* записи нет / запись не разобрана ⇒ **НЕ ИЗМЕРЕНО** с названной причиной;
* член населения, которого в записи нет вовсе, ⇒ **НЕ ИЗМЕРЕНО С ИМЕНЕМ**, а не
  «прошёл». Именно эта склейка и позволяла месяц читать обрыв как красноту;
* тест-файл не разобран ⇒ принадлежность НЕИЗВЕСТНА, вердикт не выносится вовсе:
  «не знаю, входит ли он» нельзя записать ни в «входит», ни в «не входит»;
* население поверхности ПУСТО ⇒ отказ, а не ``satisfied``. Сторож без населения
  зелен по построению (класс ``vacuous_guard_census``), и зелень эта ничего не
  значит.

## Односторонность названа заранее

Правило принадлежности видит ПРЯМОЙ импорт. Тест, который трогает risk-логику
через промежуточный помощник, в население не попадёт — мера ошибается в сторону
ЗАНИЖЕНИЯ населения, и вердикт «регрессия» от этого не становится мягче (найденная
поломка остаётся поломкой), а вердикт «всё зелено» становится СЛАБЕЕ, чем звучит.
Это сказано здесь вслух, чтобы слабость была свойством с названием, а не сюрпризом.

## Что этот замер НЕ утверждает

* **Что набор из четырёх каталогов зелён.** Предмет здесь — объявленные три
  поверхности, а не весь набор; вердикт о наборе целиком принадлежит CI и на
  сегодня НЕ ИЗМЕРЕН (см. выше).
* **Что верны сами тесты.** Прибор читает их исход, а не их правоту.
* **Что запись сделана на том же дереве.** Дерево и хост называет тот, кто
  подаёт запись; прибор печатает путь записи, а не выдумывает её происхождение.

Прибор только ЧИТАЕТ: ни один тест не запускается, не правится и не ослабляется
(инв. #16), RiskPolicy, стоп-кран и живой трек не трогаются. LLM запрещён.
Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import os
import pathlib
import subprocess
import xml.etree.ElementTree as ET  # stdlib-only (инв. #4): запись пишет наш же pytest
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/no_regression_census.json"

NO_REGRESSION = "NO_REGRESSION"
REGRESSION = "REGRESSION"
UNMEASURED = "UNMEASURED"

#: Два РАЗНЫХ третьих исхода у члена населения, и склеивать их нельзя (инв. #17):
#: «файла нет в записи» чинится у прогона (сессию сняли, тест не собрался), «все
#: случаи пропущены» — у самого теста либо у условия среды. До заказа G107 п. 1
#: различить их можно было только по ПРОЗЕ строки `reason`, то есть подстрокой, —
#: а разбор исхода подстрокой запрещён (ADR-333). Теперь у исхода есть имя.
ABSENT_FROM_RECORD = "absent_from_the_record"
ALL_CASES_SKIPPED = "all_cases_skipped"

#: Каталоги, которые гейтит CI, — ровно предписанный `CLAUDE.md` прогон. Список
#: не сокращается «до своего набора»: именно так восемь коммитов подряд уехали на
#: красный `main` (цикл #189).
TEST_ROOTS = (
    "tests",
    "spa_core/tests",
    "scripts/tests",
    "spa_core/analytics/gross_of",
    "research/cards",
)

#: Три поверхности, названные владельцем, и чем принадлежность к каждой меряется.
#:
#: ``modules`` — префиксы импорта. Написаний у одного и того же пакета ДВА, потому
#: что тесты кладут в ``sys.path`` либо корень репозитория, либо ``spa_core/``;
#: знать одно написание значит терять половину населения, и это не гипотеза, а
#: замер (``test_risk_policy.py`` пишет ``from risk.policy import …``).
#:
#: ``self_guards`` — файлы, которые САМИ и есть проверка инварианта: у такого
#: сторожа нет модуля, который можно импортировать, — он сканирует дерево сам.
#: Список объявленный, и держится он с одной стороны: объявленного файла нет в
#: дереве ⇒ «НЕ ИЗМЕРЕНО» с именем, а не тихое выпадение из населения.
DECLARED_SURFACES: dict[str, dict[str, object]] = {
    "risk": {
        "modules": (
            "spa_core.risk", "risk",
            "spa_core.governance", "governance",
        ),
        "self_guards": (),
        "why": "risk-движок системы — `spa_core/risk/` (RiskPolicy v1.0) и "
               "`spa_core/governance/` (стоп-кран); так область очерчена в "
               "`.claude/rules/risk-engine.md`",
    },
    "security": {
        "modules": (
            "lint_llm_forbidden",        # инв. #3 — LLM запрещён в risk/exec/monitoring
            "lint_forbidden_imports",    # инв. #6 — не импортировать execution/
            "spa_core.api.auth", "api.auth",
        ),
        "self_guards": (
            # Сторож секретов (инв. #7) сам сканирует дерево: импортировать ему
            # нечего, и без явного объявления он выпал бы из населения молча.
            "tests/test_security_audit.py",
            # Сервер агента слушает петлю, а не сеть (`.claude/rules/deployment.md`
            # п. 8): сторож читает ОБЁРТКИ, модуля у него тоже нет.
            "spa_core/tests/test_agent_servers_bind_loopback.py",
        ),
        "why": "инварианты безопасности, названные `CLAUDE.md`: #3 запрет LLM в "
               "risk/execution/monitoring · #6 запрет импорта `spa_core/execution/` "
               "из read-only кода · #7 никаких секретов в файлах · авторизация API",
    },
    "architecture": {
        "modules": (
            "spa_core.monitoring.architecture_conformance",
            "monitoring.architecture_conformance",
            "spa_core.monitoring.cio_architecture_constraints",
            "monitoring.cio_architecture_constraints",
            "build_architecture_manifest",
        ),
        "self_guards": (),
        "why": "сторожа соответствия дерева объявленной архитектуре — "
               "`architecture/manifest.json` и его сверки",
    },
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head(repo_root: str) -> str | None:
    """Вершина дерева, на котором снят замер. ``None`` = наблюдения нет.

    Нужна читателю, а не вердикту: запись говорит об исходе тестов на КАКОМ-ТО
    дереве, и назвать это дерево — часть числа. Пустая строка или ноль здесь
    были бы третьим исходом, выданным за ответ (инв. #17).
    """
    try:
        out = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


# ───────────────────────── население: разбор тест-файлов ──────────────────────

def _imported_modules(tree: ast.AST) -> set[str]:
    """Все имена модулей, которые файл импортирует.

    ``from a.b import c`` даёт и ``a.b``, и ``a.b.c``: второе нужно, потому что
    поверхность бывает объявлена подмодулем, а первое — потому что бывает
    объявлена пакетом. Относительный импорт (``from . import x``) сюда не
    попадает намеренно: у него нет имени, которое можно сопоставить с
    объявленным префиксом, и выдумывать это имя значило бы гадать.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # относительный импорт — имени пакета в файле нет
                continue
            if node.module:
                out.add(node.module)
                for alias in node.names:
                    out.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Call):
            out |= _opaque_import_names(node)
    return out


#: Формы непрозрачного импорта, у которых имя модуля объявлено ЛИТЕРАЛОМ.
#: Перечень ЗАКРЫТ намеренно (урок ADR-468/469: открытый перечень
#: конструкторов молча пропускает незнакомую форму). Не-литерал сюда не
#: попадает: имя, которое надо вычислять, здесь не гадается.
#:
#: Форма не выдумана: `spa_core/tests/test_architecture_manifest.py` грузит
#: генератор манифеста именно так, и без этой ветки ЖИВОЙ красный
#: architecture-тест выпадал из населения молча — то есть «критерий выполнен»
#: получался из слепоты правила.
_OPAQUE_IMPORTERS: dict[str, int] = {
    "spec_from_file_location": 0,   # importlib.util.spec_from_file_location(name, path)
    "import_module": 0,             # importlib.import_module(name)
    "__import__": 0,
    "find_spec": 0,                 # importlib.util.find_spec(name)
}


def _opaque_import_names(call: ast.Call) -> set[str]:
    """Имена модулей, объявленные ЛИТЕРАЛОМ в непрозрачном импорте."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)
    if name not in _OPAQUE_IMPORTERS:
        return set()
    position = _OPAQUE_IMPORTERS[name]
    args = list(call.args)
    candidates: list[ast.expr] = []
    if len(args) > position:
        candidates.append(args[position])
    for kw in call.keywords:
        if kw.arg == "name":
            candidates.append(kw.value)
    out: set[str] = set()
    for node in candidates:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def _matches(modules: set[str], prefixes: tuple[str, ...]) -> list[str]:
    """Объявленные префиксы, которые файл действительно импортирует.

    Сравнение по ГРАНИЦЕ имени, а не подстрокой: ``risk`` не должен ловить
    ``riskwire``, иначе advisory-слой попал бы в население risk-политики — ровно
    та подмена именем, против которой прибор и написан.
    """
    hit: list[str] = []
    for prefix in prefixes:
        for name in modules:
            if name == prefix or name.startswith(prefix + "."):
                hit.append(prefix)
                break
    return sorted(set(hit))


def population(repo_root: str = REPO_ROOT) -> dict:
    """Кто входит в каждую поверхность — разбором дерева.

    Возврат несёт и находки, и НЕ ИЗМЕРЕНО: файл, который не разобрался, не
    объявляется ни входящим, ни не входящим.
    """
    root = pathlib.Path(repo_root)
    surfaces: dict[str, dict[str, list]] = {
        name: {"files": [], "by_import": [], "by_declaration": []}
        for name in DECLARED_SURFACES
    }
    unparsed: list[dict[str, str]] = []
    missing_guards: list[dict[str, str]] = []
    scanned = 0
    roots_absent: list[str] = []

    for rel_root in TEST_ROOTS:
        base = root / rel_root
        if not base.is_dir():
            roots_absent.append(rel_root)
            continue
        for path in sorted(base.rglob("test_*.py")):
            scanned += 1
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                unparsed.append({"file": rel, "reason": f"{type(exc).__name__}: {exc}"})
                continue
            imported = _imported_modules(tree)
            for name, surface in DECLARED_SURFACES.items():
                hit = _matches(imported, surface["modules"])  # type: ignore[arg-type]
                if hit:
                    surfaces[name]["files"].append(rel)
                    surfaces[name]["by_import"].append({"file": rel, "via": hit})

    for name, surface in DECLARED_SURFACES.items():
        for rel in surface["self_guards"]:  # type: ignore[union-attr]
            if not (root / rel).is_file():
                missing_guards.append({"surface": name, "file": rel})
                continue
            if rel not in surfaces[name]["files"]:
                surfaces[name]["files"].append(rel)
            surfaces[name]["by_declaration"].append(rel)
        surfaces[name]["files"] = sorted(set(surfaces[name]["files"]))

    return {
        "surfaces": surfaces,
        "unparsed": unparsed,
        "missing_self_guards": missing_guards,
        "roots_absent": roots_absent,
        "files_scanned": scanned,
    }


# ─────────────────────────── исход: чтение junit-записи ───────────────────────

def _file_of_case(case: ET.Element, root: pathlib.Path,
                  cache: dict[str, str | None]) -> str | None:
    """Файл, к которому относится случай записи. ``None`` = установить не удалось.

    Атрибут ``file`` пишет только семейство ``xunit1``; по умолчанию pytest
    пишет ``xunit2``, где его НЕТ вовсе — и наш CI пишет именно умолчание.
    Поэтому путь берётся из ``classname`` и **проверяется существованием
    файла**: из точечного имени
    ``spa_core.tests.test_x.SomeClass`` разбирается самый длинный префикс,
    которому в дереве соответствует ``.py``.

    Это ЗАМЕР, а не догадка: префикс, которому файла нет, не принимается, и
    случай честно остаётся без файла (третий исход). Требовать от записи
    атрибута ``file`` значило бы объявить наш собственный CI непрочитанным.
    """
    raw = case.get("file")
    if raw:
        return pathlib.PurePosixPath(raw).as_posix()
    classname = case.get("classname") or ""
    if not classname:
        return None
    if classname in cache:
        return cache[classname]
    parts = classname.split(".")
    resolved: str | None = None
    for cut in range(len(parts), 0, -1):
        candidate = pathlib.PurePosixPath(*parts[:cut]).with_suffix(".py").as_posix()
        if (root / candidate).is_file():
            resolved = candidate
            break
    cache[classname] = resolved
    return resolved


def read_record(paths: list[str], repo_root: str = REPO_ROOT) -> dict:
    """Исход каждого тест-ФАЙЛА из junit-записей pytest.

    Единица здесь — ФАЙЛ, потому что единица населения тоже файл. Отсутствие
    файла в записи и отсутствие самой записи — разные факты, и оба названы.
    """
    root = pathlib.Path(repo_root)
    files: dict[str, dict] = {}
    read: list[str] = []
    unread: list[dict[str, str]] = []
    orphan_cases = 0
    cache: dict[str, str | None] = {}
    meta: list[dict[str, str | None]] = []

    for raw in paths:
        p = pathlib.Path(raw)
        if not p.is_absolute():
            p = root / raw
        try:
            tree = ET.parse(p)
        except (OSError, ET.ParseError) as exc:
            unread.append({"record": raw, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        read.append(raw)
        # Происхождение записи — НАБЛЮДЕНИЕ, а не прозаическая подпись: pytest
        # сам пишет `hostname` и `timestamp` у <testsuite>, и они отвечают на
        # «где и когда снят исход». Атрибута нет ⇒ None, а не выдуманная строка.
        for suite in tree.getroot().iter("testsuite"):
            meta.append({"record": raw,
                         "hostname": suite.get("hostname"),
                         "timestamp": suite.get("timestamp"),
                         "tests": suite.get("tests")})
        for case in tree.getroot().iter("testcase"):
            rel = _file_of_case(case, root, cache)
            if not rel:
                orphan_cases += 1
                continue
            row = files.setdefault(
                rel, {"passed": 0, "skipped": 0, "bad": [], "records": []})
            if raw not in row["records"]:
                row["records"].append(raw)
            name = f"{case.get('classname') or ''}::{case.get('name') or ''}".strip(":")
            kind: str | None = None
            message = ""
            for child in case:
                if child.tag in ("failure", "error", "skipped"):
                    kind = child.tag
                    message = child.get("message") or ""
                    break
            if kind in ("failure", "error"):
                row["bad"].append({"case": name, "kind": kind,
                                   "message": message[:300]})
            elif kind == "skipped":
                row["skipped"] += 1
            else:
                row["passed"] += 1

    return {"files": files, "records_read": read, "records_unread": unread,
            "records_meta": meta, "cases_without_file": orphan_cases}


# ───────────────────────────────── вердикт ────────────────────────────────────

def judge(population_by_surface: dict[str, list[str]], record: dict) -> dict:
    """Вердикт по ЛЮБОМУ населению при ОДНОЙ записи прогона.

    Вынесено из :func:`measure` ОДНОЙ копией, а не скопировано: заказ G107 п. 1
    требует спросить, **меняет ли расширение населения сам вердикт**, — то есть
    приложить ту же мерку к ДРУГОМУ населению. Вторая копия правила разошлась бы
    с этой при первой же правке и дала бы два разных вердикта у одного критерия
    (ровно дефект, который ловит ADR-522), а население самого критерия расширять
    замером ЗАПРЕЩЕНО: это отдельное решение, потому что сдвигает вердикт
    критерия владельца.

    Население подаётся ВХОДОМ (``{поверхность: [файлы]}``) и здесь не считается:
    кто его посчитал — вопрос вызывающего, а не мерки.

    Три исхода у члена населения (инв. #17) и ни одной склейки между ними:
    файла нет в записи ⇒ НЕ ИЗМЕРЕНО С ИМЕНЕМ · все случаи ПРОПУЩЕНЫ ⇒ НЕ
    ИЗМЕРЕНО С ИМЕНЕМ · есть хоть одна поломка ⇒ поломка. ``verdict_by_surface``
    отдаётся отдельным полем, а не внутри ``surfaces``: форма ``surfaces``
    принадлежит :func:`measure` и её читателям, и дописывать в неё ключ значило
    бы менять чужой документ заодно со своим.
    """
    surfaces: dict[str, dict] = {}
    verdict_by_surface: dict[str, str] = {}
    total_failed: list[dict] = []
    total_unmeasured: list[dict] = []
    for name, files in population_by_surface.items():
        passed, failed, unmeasured, cases = [], [], [], 0
        for rel in files:
            row = record["files"].get(rel)
            if row is None:
                unmeasured.append({"file": rel, "kind": ABSENT_FROM_RECORD,
                                   "reason": "в записи прогона файла нет — тест не "
                                             "дошёл до вердикта (сессия снята, тест "
                                             "не собран или не запускался)"})
                continue
            cases += row["passed"] + row["skipped"] + len(row["bad"])
            if row["bad"]:
                failed.append({"file": rel, "cases": row["bad"]})
            elif row["passed"] == 0:
                # Пропущенный тест НЕ «проходит»: файл, все случаи которого
                # скипнуты, исхода не дал. Сложить его к зелёным значило бы
                # сделать «не измерено» неотличимым от успеха ровно там, где
                # скип и ставится — на условии среды (инв. #17).
                unmeasured.append({"file": rel, "kind": ALL_CASES_SKIPPED,
                                   "reason": f"все {row['skipped']} случа(й/ев) файла "
                                             f"ПРОПУЩЕНЫ — исход не наблюдён"})
            else:
                passed.append(rel)
        surfaces[name] = {
            "cases_seen": cases,
            # Список, а не счётчик: читателю пробы нужно знать, ПРО КАКОЙ файл
            # запись говорит «зелен». Со счётчиком пришлось бы выводить это из
            # разности множеств, то есть заводить вторую копию мерки.
            "files_passed": passed,
            "files_failed": failed,
            "files_unmeasured": unmeasured,
        }
        verdict_by_surface[name] = REGRESSION if failed else (
            NO_REGRESSION if not unmeasured else UNMEASURED)
        total_failed += [{"surface": name, **f} for f in failed]
        total_unmeasured += [{"surface": name, **u} for u in unmeasured]

    complete = not total_unmeasured
    return {
        "surfaces": surfaces,
        "verdict_by_surface": verdict_by_surface,
        "failed": total_failed,
        "unmeasured_members": total_unmeasured,
        "complete": complete,
        "verdict": REGRESSION if total_failed else (
            NO_REGRESSION if complete else UNMEASURED),
    }


def measure(repo_root: str = REPO_ROOT, junit_paths: list[str] | None = None) -> dict:
    """Вердикт критерия §49 ``No regression``.

    ``satisfied`` выдаётся РОВНО ТОГДА, когда у каждого члена каждой поверхности
    есть вердикт и все вердикты зелёные. Любая дыра — не «почти да», а третий
    исход с именем.
    """
    stamp = _stamp()
    pop = population(repo_root)
    base = {
        "generated_at": stamp,
        "criterion": "§49 No regression — Existing risk/security/architecture tests проходят",
        "repo_root": repo_root,
        "repo_head": _git_head(repo_root),
        "declared_surfaces": {k: v["why"] for k, v in DECLARED_SURFACES.items()},
        "files_scanned": pop["files_scanned"],
        "unparsed": pop["unparsed"],
        "missing_self_guards": pop["missing_self_guards"],
        "roots_absent": pop["roots_absent"],
    }

    if pop["roots_absent"]:
        return {**base, "measured": False, "status": UNMEASURED, "verdict": UNMEASURED,
                "reason": "каталог(и) предписанного прогона не найдены: "
                          + ", ".join(pop["roots_absent"])
                          + " — население неполно по построению"}
    if pop["unparsed"]:
        return {**base, "measured": False, "status": UNMEASURED, "verdict": UNMEASURED,
                "reason": f"{len(pop['unparsed'])} тест-файл(ов) не разобран(ы): "
                          + ", ".join(u["file"] for u in pop["unparsed"][:5])
                          + " — принадлежность НЕИЗВЕСТНА, вердикт не выносится"}
    if pop["missing_self_guards"]:
        return {**base, "measured": False, "status": UNMEASURED, "verdict": UNMEASURED,
                "reason": "объявленного сторожа-инварианта нет в дереве: "
                          + ", ".join(f"{m['surface']}:{m['file']}"
                                      for m in pop["missing_self_guards"])
                          + " — объявление разошлось с деревом"}

    empty = [name for name, s in pop["surfaces"].items() if not s["files"]]
    if empty:
        return {**base, "measured": False, "status": UNMEASURED, "verdict": UNMEASURED,
                "reason": "население поверхност(и/ей) ПУСТО: " + ", ".join(empty)
                          + " — сторож без населения зелен по построению, и эта "
                            "зелень ничего не значит"}

    record = read_record(list(junit_paths or []), repo_root=repo_root)
    base["records_read"] = record["records_read"]
    base["records_unread"] = record["records_unread"]
    base["records_meta"] = record["records_meta"]
    base["cases_without_file"] = record["cases_without_file"]

    if not record["records_read"]:
        reason = "записи прогона нет вовсе — исход тестов не наблюдён"
        if record["records_unread"]:
            reason = ("ни одна запись прогона не прочитана: "
                      + "; ".join(f"{u['record']} — {u['reason']}"
                                  for u in record["records_unread"]))
        return {**base, "measured": False, "status": UNMEASURED, "verdict": UNMEASURED,
                "reason": reason,
                "population_total": sum(len(s["files"]) for s in pop["surfaces"].values())}

    judged = judge({name: list(s["files"]) for name, s in pop["surfaces"].items()},
                   record)
    surfaces = {
        name: {
            "why": DECLARED_SURFACES[name]["why"],
            "population": len(s["files"]),
            "by_import": len(s["by_import"]),
            "by_declaration": list(s["by_declaration"]),
            **judged["surfaces"][name],
        }
        for name, s in pop["surfaces"].items()
    }
    total_failed = judged["failed"]
    total_unmeasured = judged["unmeasured_members"]
    complete = judged["complete"]
    verdict = judged["verdict"]

    return {
        **base,
        "measured": True,
        "status": verdict,
        "verdict": verdict,
        "complete": complete,
        "population_total": sum(s["population"] for s in surfaces.values()),
        "surfaces": surfaces,
        "failed_total": len(total_failed),
        "unmeasured_total": len(total_unmeasured),
        "failed": total_failed,
        "unmeasured_members": total_unmeasured,
        "numbers_unit": {"population": "тест-ФАЙЛОВ", "cases_seen": "случаев в записи"},
    }


# ─────────────────────────────────── печать ───────────────────────────────────

def _lines(report: dict) -> list[str]:
    if not report.get("measured"):
        return [f"критерий §49 `No regression`: НЕ ИЗМЕРЕНО — {report.get('reason')}"]
    out = [
        f"критерий §49 `No regression`: {report['verdict']} · население "
        f"{report['population_total']} тест-файл(ов) · упало "
        f"{report['failed_total']} · НЕ ИЗМЕРЕНО {report['unmeasured_total']}",
        f"[ЗАПИСИ] прочитано {len(report['records_read'])}: "
        + (", ".join(report["records_read"]) or "—")
        + (f" · не прочитано {len(report['records_unread'])}"
           if report["records_unread"] else ""),
    ]
    for name, s in report["surfaces"].items():
        out.append(
            f"[{name.upper()}] население {s['population']} "
            f"(импортом {s['by_import']}, объявлением {len(s['by_declaration'])}) · "
            f"зелёных файлов {len(s['files_passed'])} · упало {len(s['files_failed'])} · "
            f"НЕ ИЗМЕРЕНО {len(s['files_unmeasured'])} · случаев в записи {s['cases_seen']}")
    for f in report["failed"][:12]:
        first = f["cases"][0]
        out.append(f"[УПАЛ · {f['surface']}] {f['file']} — {first['kind']} "
                   f"{first['case']}: {first['message'].splitlines()[0][:160]}"
                   + (f" (+{len(f['cases']) - 1} ещё в файле)"
                      if len(f["cases"]) > 1 else ""))
    if len(report["failed"]) > 12:
        out.append(f"… ещё {len(report['failed']) - 12} упавших файл(ов) — "
                   f"полный перечень в артефакте")
    for u in report["unmeasured_members"][:12]:
        out.append(f"[НЕ ИЗМЕРЕНО · {u['surface']}] {u['file']} — {u['reason']}")
    if len(report["unmeasured_members"]) > 12:
        out.append(f"… ещё {len(report['unmeasured_members']) - 12} неизмеренных "
                   f"член(ов) населения — полный перечень в артефакте")
    if report["verdict"] == REGRESSION:
        out.append("[НАХОДКА] критерий §49 `No regression` НЕ ВЫПОЛНЕН: названные выше "
                   "тесты объявленных поверхностей не проходят. Имена — ответ замером, "
                   "а не мнением; гасить их правкой теста запрещено (инв. #16)")
    elif report["verdict"] == UNMEASURED:
        out.append("[НЕ ИЗМЕРЕНО] упавших нет, но вердикт получили НЕ ВСЕ члены "
                   "населения — «остальные, наверное, прошли» есть ровно та подмена, "
                   "против которой написан инв. #17")
    out.append("ADVISORY: ни один тест не запускается, не правится и не ослабляется; "
               "RiskPolicy v1.0, стоп-кран, живой трек и landing/ не трогаются — "
               "прибор только ЧИТАЕТ")
    return out


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=REPO_ROOT)
    ap.add_argument("--junit", action="append", default=[],
                    help="путь к junit-XML прогона (можно несколько раз); "
                         "без него вердикт — НЕ ИЗМЕРЕНО, и это ответ, а не ошибка")
    ap.add_argument("--population-only", action="store_true",
                    help="напечатать только население поверхностей")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    if args.population_only:
        pop = population(args.repo_root)
        for name, s in pop["surfaces"].items():
            print(f"[{name.upper()}] {len(s['files'])} файл(ов)")
            for rel in s["files"]:
                print(f"   {rel}")
        if pop["unparsed"]:
            print(f"[НЕ ИЗМЕРЕНО] не разобрано {len(pop['unparsed'])}")
            return 2
        return 0

    report = measure(args.repo_root, junit_paths=args.junit)
    for line in _lines(report):
        print(line)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, os.path.join(args.repo_root, REPORT_REL))
    if not report.get("measured") or report["verdict"] == UNMEASURED:
        return 2
    return 1 if report["verdict"] == REGRESSION else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
