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


# ───────────────────── запись УЖЕ выполненного CI как вход вердикта ────────────
#
# Решение ARB (23.10): §49 берётся из junit-записей контрольного прогона
# `ci-control.yml` (12 шардов, полный предписанный набор), а не из pytest на
# Маке. Вердикт по-прежнему выносит ОДНА мерка — :func:`measure` по junit; всё,
# что ниже, отвечает на вопрос, который мерка задавать не обязана: «ЭТА ли
# запись, о ТОМ ли коде, ЦЕЛА ли она и СВЕЖА ли». Каждый отказ — НЕ ИЗМЕРЕНО со
# своим кодом причины (инв. #17); «нет новых падений против базы» в вердикт НЕ
# превращается никогда — сравнение с базой здесь не делается вовсе.
#
# Форма каталога записи — ровно то, что отдаёт GitHub, без перекладки:
#
#   <dir>/run.json          ответ GET /repos/{repo}/actions/runs/{id}
#   <dir>/artifacts.json    ответ GET …/runs/{id}/artifacts
#   <dir>/ci-control-report/report.json   свод `ci_control.py aggregate`
#   <dir>/ctl-manifest/manifest.json      план `ci_control.py plan`
#   <dir>/ctl-shard-<i>/{shard.json,junit*.xml,…}   запись шарда i
#
# **Две привязки SHA, и они РАЗНЫЕ (замер 23.10, прогон 39871542027).**
# `run.head_sha` — коммит, с которого GitHub взял ВОРКФЛОУ (3363bb7df), а
# проверялся вход `inputs.sha`, закреплённый джобой `manifest` (5bc06f5db).
# Проверяемый код называет `manifest.sha` (`git rev-parse HEAD` закреплённого
# checkout) и повторяет `report.sha`; `run.head_sha` записывается рядом как
# версия воркфлоу. `shard.json` SHA НЕ несёт (`{"shard": N}`): принадлежность
# шарда коммиту держится на `artifacts[].workflow_run.id` == run и на том, что
# джоба шарда берёт `needs.manifest.outputs.sha`. Если `shard.json` однажды
# понесёт `sha`, он сверяется.

CI_REPO = "yurii-spa/SPA"
CI_WORKFLOW_PATH = ".github/workflows/ci-control.yml"
CI_WORKFLOW_FILE = "ci-control.yml"
CI_REPORT_SCHEMA = "spa-ci-control-report/1"      # = scripts/ci_control.REPORT_SCHEMA
CI_MANIFEST_SCHEMA = "spa-ci-control-manifest/1"  # = scripts/ci_control.MANIFEST_SCHEMA
CI_REPORT_ARTIFACT = "ci-control-report"
CI_MANIFEST_ARTIFACT = "ctl-manifest"
CI_SHARD_PREFIX = "ctl-shard-"
CI_RUN_FILE = "run.json"
CI_ARTIFACTS_FILE = "artifacts.json"
#: Исходы свода, у которых ВСЁ измерено (`ci_control.GREEN`/`RED`).
_CI_MEASURED_VERDICTS = ("GREEN", "RED")
#: Заключения прогона, при которых он дошёл до конца. `failure` — это RED свода
#: (упавшие тесты), а не отсутствие ответа; `cancelled`/`timed_out`/… — ответа нет.
_CI_FINISHED_CONCLUSIONS = ("success", "failure")

#: Закрытый перечень причин отказа: у каждой проверки свой код, склеивать их
#: значило бы снова читать разные дефекты одной прозой.
CI_RECORD_UNAVAILABLE = "record_unavailable"
CI_RECORD_BROKEN = "record_broken"
CI_WRONG_REPOSITORY = "wrong_repository"
CI_WRONG_WORKFLOW = "wrong_workflow"
CI_WRONG_RUN = "wrong_run"
CI_RUN_NOT_FINISHED = "run_not_finished"
CI_SHA_MISMATCH = "sha_mismatch"
CI_TREE_MISMATCH = "tree_mismatch"
CI_RECORD_INCONSISTENT = "record_inconsistent"
CI_RECORD_INCOMPLETE = "record_incomplete"
CI_RECORD_STALE = "record_stale"
CI_RECORD_TIME_UNREADABLE = "record_time_unreadable"
CI_CENSUS_UNMEASURED = "census_unmeasured"
CI_REFUSAL_CODES = (
    CI_RECORD_UNAVAILABLE, CI_RECORD_BROKEN, CI_WRONG_REPOSITORY, CI_WRONG_WORKFLOW,
    CI_WRONG_RUN, CI_RUN_NOT_FINISHED, CI_SHA_MISMATCH, CI_TREE_MISMATCH,
    CI_RECORD_INCONSISTENT, CI_RECORD_INCOMPLETE, CI_RECORD_STALE,
    CI_RECORD_TIME_UNREADABLE, CI_CENSUS_UNMEASURED,
)


class CIRecordRefused(RuntimeError):
    """Запись CI не принята: вердикт НЕ ИЗМЕРЕН, причина названа кодом и словами."""

    def __init__(self, code: str, reason: str) -> None:
        assert code in CI_REFUSAL_CODES, code
        super().__init__(f"[{code}] {reason}")
        self.code = code
        self.reason = reason


def ci_max_age_h() -> float:
    """Предел свежести записи — ОДНА копия, у пробы §49.

    Читается у ``card_acceptance._NO_REGRESSION_MAX_AGE_H``, а не перепечатывается:
    второй предел разошёлся бы с пробой, и запись, принятая здесь, протухала бы
    там (или наоборот).
    """
    from spa_core.monitoring import card_acceptance
    return float(card_acceptance._NO_REGRESSION_MAX_AGE_H)


def _ci_json(path: pathlib.Path, what: str) -> dict:
    import json
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                              f"{what} нет: {path} — {type(exc).__name__}: {exc}") from exc
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise CIRecordRefused(CI_RECORD_BROKEN,
                              f"{what} не разобран: {path} — {type(exc).__name__}: {exc}") from exc
    if not isinstance(doc, dict):
        raise CIRecordRefused(CI_RECORD_BROKEN, f"{what} не словарь: {path}")
    return doc


def _ci_time(value: object, what: str) -> datetime:
    try:
        made = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CIRecordRefused(CI_RECORD_TIME_UNREADABLE,
                              f"{what} не читается ({value!r}) — возраст записи НЕ ИЗМЕРЕН") from exc
    return made if made.tzinfo else made.replace(tzinfo=timezone.utc)


def _shard_ids(rows: object, what: str) -> list[int]:
    if not isinstance(rows, list):
        raise _inconsistent(f"{what}: перечня шардов нет")
    ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("shard"), int):
            raise _inconsistent(f"{what}: строка шарда без номера: {row!r}"[:300])
        ids.append(row["shard"])
    if len(set(ids)) != len(ids):
        raise _inconsistent(f"{what}: номер шарда повторён: {sorted(ids)}")
    return sorted(ids)


def _inconsistent(reason: str) -> CIRecordRefused:
    return CIRecordRefused(CI_RECORD_INCONSISTENT, reason)


def _tree_state(repo_root: str) -> tuple[str | None, list[str] | None]:
    """HEAD дерева и его изменения в корнях населения. ``None`` = не измерено."""
    head = _git_head(repo_root)
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "status", "--porcelain", "--untracked-files=all",
             "--", *TEST_ROOTS], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return head, None
    if out.returncode != 0:
        return head, None
    return head, [line for line in out.stdout.splitlines() if line.strip()]


def verify_ci_record(record_dir: str, *, expected_sha: str, repo_root: str,
                     now: datetime | None = None, max_age_h: float | None = None,
                     expected_run_id: int | str | None = None,
                     repo: str = CI_REPO, workflow_path: str = CI_WORKFLOW_PATH) -> dict:
    """Принять запись CI или ОТКАЗАТЬ с кодом причины (:class:`CIRecordRefused`).

    Возврат — junit-пути (по шарду, в порядке номеров) и происхождение записи.
    Часы и предел — ВХОДЫ (`.claude/rules/deployment.md`): тест закрепляет обе
    стороны сравнения.
    """
    root = pathlib.Path(record_dir)
    if not root.is_dir():
        raise CIRecordRefused(CI_RECORD_UNAVAILABLE, f"каталога записи нет: {record_dir}")
    if not expected_sha or len(expected_sha) != 40:
        raise CIRecordRefused(CI_SHA_MISMATCH,
                              f"ожидаемый SHA не назван полностью ({expected_sha!r}) — "
                              f"сверять запись не с чем")
    limit = ci_max_age_h() if max_age_h is None else float(max_age_h)
    clock = now or datetime.now(timezone.utc)

    # 1. Чья это запись: репозиторий, воркфлоу, прогон.
    run = _ci_json(root / CI_RUN_FILE, "метаданные прогона (run.json)")
    full_name = (run.get("repository") or {}).get("full_name") \
        if isinstance(run.get("repository"), dict) else None
    if full_name != repo:
        raise CIRecordRefused(CI_WRONG_REPOSITORY,
                              f"прогон принадлежит {full_name!r}, ожидался {repo!r}")
    if run.get("path") != workflow_path:
        raise CIRecordRefused(CI_WRONG_WORKFLOW,
                              f"воркфлоу прогона {run.get('path')!r}, ожидался {workflow_path!r}")
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise CIRecordRefused(CI_WRONG_RUN, f"у прогона нет номера (id={run_id!r})")
    if expected_run_id is not None and str(run_id) != str(expected_run_id):
        raise CIRecordRefused(CI_WRONG_RUN,
                              f"запись о прогоне {run_id}, ожидался {expected_run_id}")
    if run.get("status") != "completed" or run.get("conclusion") not in _CI_FINISHED_CONCLUSIONS:
        raise CIRecordRefused(CI_RUN_NOT_FINISHED,
                              f"прогон {run_id}: status={run.get('status')!r}, "
                              f"conclusion={run.get('conclusion')!r} — до вердикта не дошёл")

    # 2. Артефакты прогона — список у GitHub, а не у каталога.
    listing = _ci_json(root / CI_ARTIFACTS_FILE, "перечень артефактов (artifacts.json)")
    arts = listing.get("artifacts")
    if not isinstance(arts, list) or listing.get("total_count") != len(arts):
        raise _inconsistent(
            f"перечень артефактов неполон: total_count={listing.get('total_count')!r}, "
            f"строк {len(arts) if isinstance(arts, list) else None}")
    by_name: dict[str, dict] = {}
    for a in arts:
        if not isinstance(a, dict) or not isinstance(a.get("name"), str):
            raise _inconsistent(f"строка артефакта без имени: {a!r}"[:300])
        if a["name"] in by_name:
            raise _inconsistent(f"артефакт {a['name']} назван дважды")
        by_name[a["name"]] = a
        wr = a.get("workflow_run") if isinstance(a.get("workflow_run"), dict) else {}
        if wr.get("id") != run_id:
            raise CIRecordRefused(CI_WRONG_RUN,
                                  f"артефакт {a['name']} принадлежит прогону {wr.get('id')!r}, "
                                  f"а запись — о прогоне {run_id}")
        if wr.get("head_sha") != run.get("head_sha"):
            raise _inconsistent(f"артефакт {a['name']}: head_sha {wr.get('head_sha')!r} "
                                       f"≠ прогона {run.get('head_sha')!r}")
        if a.get("expired") is not False:
            raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                                  f"артефакт {a['name']}: expired={a.get('expired')!r}")

    # 3. Свод и план — о каком коде.
    manifest = _ci_json(root / CI_MANIFEST_ARTIFACT / "manifest.json", "план шардов (manifest.json)")
    report = _ci_json(root / CI_REPORT_ARTIFACT / "report.json", "свод (report.json)")
    if manifest.get("schema") != CI_MANIFEST_SCHEMA:
        raise CIRecordRefused(CI_RECORD_BROKEN, f"план не того вида: {manifest.get('schema')!r}")
    if report.get("schema") != CI_REPORT_SCHEMA:
        raise CIRecordRefused(CI_RECORD_BROKEN, f"свод не того вида: {report.get('schema')!r}")
    if manifest.get("sha") != expected_sha:
        raise CIRecordRefused(CI_SHA_MISMATCH,
                              f"план прогона о коммите {manifest.get('sha')!r}, "
                              f"ожидался {expected_sha}")
    if report.get("sha") != manifest.get("sha"):
        raise _inconsistent(f"свод о коммите {report.get('sha')!r}, план — "
                                   f"{manifest.get('sha')!r}")
    if run.get("head_sha") == expected_sha:
        sha_binding = "run_head_sha"
    elif run.get("event") == "workflow_dispatch":
        # Вход `inputs.sha` закреплён джобой manifest; воркфлоу — из run.head_sha.
        sha_binding = "dispatch_input_pinned_by_manifest"
    else:
        raise CIRecordRefused(CI_SHA_MISMATCH,
                              f"прогон {run_id} ({run.get('event')}) шёл на "
                              f"{run.get('head_sha')!r}, а план называет {expected_sha}: "
                              f"закрепить чужой коммит может только workflow_dispatch")
    rrun = report.get("run") if isinstance(report.get("run"), dict) else {}
    if str(rrun.get("id")) != str(run_id):
        raise CIRecordRefused(CI_WRONG_RUN,
                              f"свод написан прогоном {rrun.get('id')!r}, запись — о {run_id}")
    want_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    if rrun.get("url") != want_url or run.get("html_url") != want_url:
        raise CIRecordRefused(CI_WRONG_REPOSITORY,
                              f"адрес прогона в своде {rrun.get('url')!r} / в run.json "
                              f"{run.get('html_url')!r}, ожидался {want_url}")
    for what, env in (("план", manifest.get("env")), ("свод", report.get("env"))):
        named = env.get("workflow") if isinstance(env, dict) else None
        if named != run.get("name"):
            raise CIRecordRefused(CI_WRONG_WORKFLOW, f"{what} снят воркфлоу {named!r}, "
                                                     f"прогон называется {run.get('name')!r}")
    if manifest.get("env") != report.get("env"):
        raise _inconsistent("окружение плана и свода различаются")

    # 4. Согласованность шардов: план · свод · артефакты · каталоги.
    plan_ids = _shard_ids(manifest.get("shards"), "план")
    report_ids = _shard_ids(report.get("shards"), "свод")
    art_ids = sorted(int(n[len(CI_SHARD_PREFIX):]) for n in by_name
                     if n.startswith(CI_SHARD_PREFIX) and n[len(CI_SHARD_PREFIX):].isdigit())
    dir_ids = sorted(int(p.name[len(CI_SHARD_PREFIX):]) for p in root.iterdir()
                     if p.is_dir() and p.name.startswith(CI_SHARD_PREFIX)
                     and p.name[len(CI_SHARD_PREFIX):].isdigit())
    totals = report.get("totals") if isinstance(report.get("totals"), dict) else None
    if totals is None:
        raise CIRecordRefused(CI_RECORD_INCOMPLETE, "у свода нет итогов (totals) — свод не дошёл")
    if not plan_ids:
        raise CIRecordRefused(CI_RECORD_INCOMPLETE, "в плане ноль шардов — получено ноль")
    for what, ids in (("свод", report_ids), ("артефакты прогона", art_ids),
                      ("каталоги записи", dir_ids)):
        if ids != plan_ids:
            missing = sorted(set(plan_ids) - set(ids))
            extra = sorted(set(ids) - set(plan_ids))
            code = CI_RECORD_INCOMPLETE if missing and not extra else CI_RECORD_INCONSISTENT
            raise CIRecordRefused(code, f"шарды плана {plan_ids} ≠ {what} {ids}: "
                                        f"недостаёт {missing}, лишние {extra}")
    if totals.get("shards_planned") != len(plan_ids):
        raise _inconsistent(f"свод считает {totals.get('shards_planned')!r} шардов, "
                                   f"в плане {len(plan_ids)}")
    for name in (CI_REPORT_ARTIFACT, CI_MANIFEST_ARTIFACT):
        if name not in by_name:
            raise CIRecordRefused(CI_RECORD_INCOMPLETE, f"артефакта {name} в прогоне нет")

    # 5. Полнота: свод обязан быть ИЗМЕРЕННЫМ, а не INCOMPLETE.
    if report.get("verdict") not in _CI_MEASURED_VERDICTS or report.get("incomplete"):
        raise CIRecordRefused(CI_RECORD_INCOMPLETE,
                              f"свод {report.get('verdict')!r}, причины неполноты: "
                              f"{str(report.get('incomplete'))[:300]}")
    if totals.get("not_obtained") != 0 or totals.get("shards_complete") != len(plan_ids):
        raise CIRecordRefused(CI_RECORD_INCOMPLETE,
                              f"не получено {totals.get('not_obtained')!r}, шардов завершено "
                              f"{totals.get('shards_complete')!r} из {len(plan_ids)}")
    collected = manifest.get("collected")
    if not isinstance(collected, list) or not collected:
        raise CIRecordRefused(CI_RECORD_INCOMPLETE, "население плана пусто — получено ноль")
    if totals.get("population") != len(collected) or manifest.get("population") != len(collected):
        raise _inconsistent(f"население: свод {totals.get('population')!r}, план "
                                   f"{manifest.get('population')!r}, перечень {len(collected)}")
    for row in report.get("shards") or []:
        if row.get("problems"):
            raise CIRecordRefused(CI_RECORD_INCOMPLETE,
                                  f"шард {row['shard']}: {row['problems'][0]}")

    # 6. Свежесть: время ИСХОДА — начало прогона, а не время сборки отчёта.
    started = _ci_time(run.get("run_started_at") or run.get("created_at"), "начало прогона")
    finished = _ci_time(run.get("updated_at"), "конец прогона")
    planned_at = _ci_time(manifest.get("created_at"), "время плана")
    if not (started <= planned_at <= finished):
        raise _inconsistent(f"план снят {planned_at.isoformat()} вне окна прогона "
                                   f"{started.isoformat()} … {finished.isoformat()}")
    age = (clock - started).total_seconds() / 3600.0
    if age < 0:
        raise CIRecordRefused(CI_RECORD_TIME_UNREADABLE,
                              f"прогон начат {started.isoformat()} позже часов {clock.isoformat()}")
    if age > limit:
        raise CIRecordRefused(CI_RECORD_STALE,
                              f"запись прогона {run_id} старше предела: {age:.1f}ч при "
                              f"пределе {limit:.0f}ч")

    # 7. Записи шардов: имя, SHA (если назван), junit цел, исход у КАЖДОГО теста.
    shard_plan = {sh["shard"]: sh for sh in manifest["shards"]}
    shard_fail = {}
    for f in report.get("failures") or []:
        shard_fail[f.get("shard")] = shard_fail.get(f.get("shard"), 0) + 1
    junits: list[str] = []
    per_file_cases: dict[str, int] = {}
    cache: dict[str, str | None] = {}
    tree_root = pathlib.Path(repo_root)
    for i in plan_ids:
        d = root / f"{CI_SHARD_PREFIX}{i}"
        meta = _ci_json(d / "shard.json", f"паспорт шарда {i} (shard.json)")
        if meta.get("shard") != i:
            raise _inconsistent(f"каталог шарда {i} называет себя {meta.get('shard')!r}")
        if "sha" in meta and meta["sha"] != expected_sha:
            raise CIRecordRefused(CI_SHA_MISMATCH,
                                  f"шард {i} о коммите {meta['sha']!r}, ожидался {expected_sha}")
        files = sorted(d.glob("junit*.xml"))
        if not files:
            raise CIRecordRefused(CI_RECORD_UNAVAILABLE, f"у шарда {i} нет junit-записи")
        cases = bad = 0
        for p in files:
            try:
                tree = ET.parse(p)
            except (OSError, ET.ParseError) as exc:
                raise CIRecordRefused(CI_RECORD_BROKEN,
                                      f"junit шарда {i} не разобран: {p.name} — "
                                      f"{type(exc).__name__}: {exc}") from exc
            # Шард, подложенный из ДРУГОГО прогона с тем же планом, по числам
            # неотличим (шард 3 у ab17e71 и 5bc06f5: 10979 = 10979). Отличает его
            # время: pytest пишет `timestamp` у <testsuite>, и оно обязано лежать
            # в окне ЭТОГО прогона.
            for suite in tree.getroot().iter("testsuite"):
                when = _ci_time(suite.get("timestamp"), f"время junit шарда {i} ({p.name})")
                if not (started <= when <= finished):
                    raise _inconsistent(f"junit шарда {i} ({p.name}) снят {when.isoformat()} вне "
                                        f"окна прогона {run_id} {started.isoformat()} … "
                                        f"{finished.isoformat()} — запись чужого прогона")
            for case in tree.getroot().iter("testcase"):
                cases += 1
                if any(c.tag in ("failure", "error") for c in case):
                    bad += 1
                rel = _file_of_case(case, tree_root, cache)
                if rel:
                    per_file_cases[rel] = per_file_cases.get(rel, 0) + 1
            junits.append(str(p))
        if cases != shard_plan[i].get("tests"):
            raise CIRecordRefused(CI_RECORD_INCOMPLETE,
                                  f"junit шарда {i} несёт {cases} исход(ов), план — "
                                  f"{shard_plan[i].get('tests')!r}: исход есть не у каждого теста")
        if bad != shard_fail.get(i, 0):
            raise _inconsistent(f"junit шарда {i} называет {bad} упавших, свод — "
                                       f"{shard_fail.get(i, 0)}")

    # 8. Код, о котором вердикт: дерево == ожидаемый SHA и чисто в корнях населения.
    head, dirty = _tree_state(repo_root)
    if head != expected_sha:
        raise CIRecordRefused(CI_TREE_MISMATCH,
                              f"дерево населения {repo_root} на {head!r}, запись — о {expected_sha}")
    if dirty is None:
        raise CIRecordRefused(CI_TREE_MISMATCH, f"состояние дерева {repo_root} не измерено (git status)")
    if dirty:
        raise CIRecordRefused(CI_TREE_MISMATCH,
                              f"дерево населения изменено в корнях прогона ({len(dirty)}): "
                              f"{dirty[:3]} — население не о {expected_sha[:12]}")

    tests_per_file = manifest.get("tests_per_file")
    if not isinstance(tests_per_file, dict):
        raise CIRecordRefused(CI_RECORD_BROKEN, "в плане нет числа тестов по файлам")
    return {
        "junit_paths": junits,
        "per_file_cases": per_file_cases,
        "tests_per_file": tests_per_file,
        "observed_at": started.isoformat(),
        "age_h": round(age, 3),
        "max_age_h": limit,
        "source": {
            "kind": "ci_record",
            "repo": full_name,
            "workflow": run.get("path"),
            "workflow_name": run.get("name"),
            "run_id": run_id,
            "run_attempt": run.get("run_attempt"),
            "run_url": want_url,
            "event": run.get("event"),
            "conclusion": run.get("conclusion"),
            "sha": expected_sha,
            "workflow_head_sha": run.get("head_sha"),
            "sha_binding": sha_binding,
            "run_started_at": run.get("run_started_at"),
            "run_updated_at": run.get("updated_at"),
            "ci_verdict": report.get("verdict"),
            "ci_totals": totals,
            "shards": plan_ids,
            "artifacts": [{"name": n, "id": by_name[n].get("id"),
                           "digest": by_name[n].get("digest"),
                           "size_in_bytes": by_name[n].get("size_in_bytes")}
                          for n in sorted(by_name)],
            "record_dir": str(root),
            "fetched_at": listing.get("_fetched_at"),
            "age_h_at_assembly": round(age, 3),
        },
    }


def measure_from_ci_record(record_dir: str, *, expected_sha: str, repo_root: str,
                           now: datetime | None = None, max_age_h: float | None = None,
                           expected_run_id: int | str | None = None) -> dict:
    """§49 по записи УЖЕ выполненного CI: проверки → :func:`measure` → происхождение.

    Вердикт выносит :func:`measure` по junit-записям шардов — ни строчки сравнения
    с базой. Отказ — :class:`CIRecordRefused`; запись отчёта — дело вызывающего
    (и только при успехе).

    ``generated_at`` отчёта — время НАБЛЮДЕНИЯ исхода (начало прогона CI), а не
    время сборки: проба §49 судит по нему о возрасте записи, и время сборки
    сделало бы недельную запись свежей ещё на неделю. Время сборки — ``assembled_at``.
    """
    got = verify_ci_record(record_dir, expected_sha=expected_sha, repo_root=repo_root,
                           now=now, max_age_h=max_age_h, expected_run_id=expected_run_id)
    report = measure(repo_root, junit_paths=got["junit_paths"])
    if not report.get("measured"):
        raise CIRecordRefused(CI_CENSUS_UNMEASURED, f"перепись не измерила: {report.get('reason')}")
    if report.get("records_unread") or len(report.get("records_read") or []) != len(got["junit_paths"]):
        raise CIRecordRefused(CI_RECORD_BROKEN,
                              f"перепись прочитала {len(report.get('records_read') or [])} из "
                              f"{len(got['junit_paths'])} записей: {report.get('records_unread')}")
    # Исход у КАЖДОГО теста члена населения: число случаев файла в junit == план.
    short = []
    for name, s in report["surfaces"].items():
        members = list(s["files_passed"]) + [f["file"] for f in s["files_failed"]]
        for rel in members:
            planned = got["tests_per_file"].get(rel)
            seen = got["per_file_cases"].get(rel)
            if planned is not None and seen != planned:
                short.append(f"{name}:{rel} ({seen}/{planned})")
    if short:
        raise CIRecordRefused(CI_RECORD_INCOMPLETE,
                              f"у членов населения исход есть не у каждого теста: {short[:5]}")
    report["assembled_at"] = report["generated_at"]
    report["generated_at"] = got["observed_at"]
    report["source"] = got["source"]
    report["ci_record_age_h"] = got["age_h"]
    report["ci_record_max_age_h"] = got["max_age_h"]
    return report


# ── сеть: скачать запись прогона (вход, а не окружение) ──────────────────────

class GitHubReader:
    """Чтение API GitHub. Токен — из окружения или Keychain, никогда не печатается.

    ``get_json(path)`` и ``get_bytes(url)`` — ВСЯ поверхность; тест подаёт свою
    пару, и «сеть отрезана» проверяется без сети.
    """

    API = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT_SPA")
        if not self._token:
            try:
                proc = subprocess.run(["security", "find-generic-password", "-s",
                                       "GITHUB_PAT_SPA", "-w"],
                                      capture_output=True, text=True, timeout=30)
                self._token = proc.stdout.strip() if proc.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                self._token = None

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "User-Agent": "spa-no-regression-census"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def get_json(self, path: str) -> dict:
        import json
        import urllib.request
        req = urllib.request.Request(self.API + path, headers=self._headers())
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)

    def get_bytes(self, url: str) -> bytes:
        import urllib.error
        import urllib.request

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):  # noqa: ANN001 — сигнатура stdlib
                return None

        if not self._token:
            raise PermissionError("токена нет: архив артефакта без авторизации не отдаётся")
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(urllib.request.Request(url, headers=self._headers()),
                             timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if not location:
                raise
        # Подписанный адрес хранилища: заголовок авторизации туда НЕ уходит.
        with urllib.request.urlopen(location, timeout=600) as resp:
            return resp.read()


def find_ci_run(http, *, head_sha: str, repo: str = CI_REPO,
                workflow_file: str = CI_WORKFLOW_FILE) -> int:
    """Номер последнего ЗАВЕРШЁННОГО прогона воркфлоу, чей план мог быть о ``head_sha``.

    Ищется по ``head_sha`` прогона: для расписанного прогона он и есть
    проверяемый коммит. Прогон, закрепивший чужой коммит через
    ``workflow_dispatch``, этим поиском не находится — его номер называют явно.
    """
    try:
        doc = http.get_json(f"/repos/{repo}/actions/workflows/{workflow_file}/runs"
                            f"?head_sha={head_sha}&status=completed&per_page=20")
    except Exception as exc:  # noqa: BLE001 — недоступность названа, а не проглочена
        raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                              f"перечень прогонов не получен: {type(exc).__name__}: {exc}") from exc
    runs = [r for r in (doc.get("workflow_runs") or []) if isinstance(r, dict)
            and r.get("head_sha") == head_sha
            and r.get("conclusion") in _CI_FINISHED_CONCLUSIONS]
    if not runs:
        raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                              f"у коммита {head_sha[:12]} нет завершённого прогона {workflow_file}")
    # Расписанный прогон гоняет ИМЕННО head_sha; ручной (dispatch) мог закрепить
    # другой коммит входом — тогда сверка плана откажет. Поэтому расписанный — первым.
    scheduled = [r for r in runs if r.get("event") == "schedule"]
    return max(scheduled or runs, key=lambda r: str(r.get("created_at")))["id"]


def _safe_extract(blob: bytes, dest: pathlib.Path, name: str) -> None:
    import io
    import zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        bad = zf.testzip()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise CIRecordRefused(CI_RECORD_BROKEN,
                              f"архив {name} не разобран: {type(exc).__name__}: {exc}") from exc
    if bad is not None:
        raise CIRecordRefused(CI_RECORD_BROKEN, f"архив {name}: битый член {bad}")
    target = dest.resolve()
    for member in zf.namelist():
        out = (dest / member).resolve()
        if target != out and target not in out.parents:
            raise CIRecordRefused(CI_RECORD_BROKEN, f"архив {name}: путь вне каталога: {member!r}")
    zf.extractall(dest)


def fetch_ci_record(dest: str, *, run_id: int | str, http=None, repo: str = CI_REPO,
                    now: datetime | None = None) -> pathlib.Path:
    """Скачать запись прогона в ``dest`` в той форме, которую читает :func:`verify_ci_record`.

    Скачивается только СВОЁ: свод, план и шарды. Дайджест архива, если GitHub
    его назвал, сверяется с байтами (`sha256:`), расхождение — отказ.
    """
    import hashlib
    reader = http or GitHubReader()
    root = pathlib.Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    try:
        run = reader.get_json(f"/repos/{repo}/actions/runs/{run_id}")
        listing = reader.get_json(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
    except Exception as exc:  # noqa: BLE001
        raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                              f"прогон {run_id} не получен: {type(exc).__name__}: {exc}") from exc
    if not isinstance(run, dict) or not isinstance(listing, dict):
        raise CIRecordRefused(CI_RECORD_BROKEN, f"ответ API о прогоне {run_id} не словарь")
    listing["_fetched_at"] = (now or datetime.now(timezone.utc)).isoformat()
    from spa_core.utils.atomic import atomic_save
    atomic_save(run, str(root / CI_RUN_FILE))
    atomic_save(listing, str(root / CI_ARTIFACTS_FILE))
    for a in listing.get("artifacts") or []:
        name = a.get("name") if isinstance(a, dict) else None
        if not (name in (CI_REPORT_ARTIFACT, CI_MANIFEST_ARTIFACT)
                or (isinstance(name, str) and name.startswith(CI_SHARD_PREFIX))):
            continue
        try:
            blob = reader.get_bytes(a["archive_download_url"])
        except Exception as exc:  # noqa: BLE001
            raise CIRecordRefused(CI_RECORD_UNAVAILABLE,
                                  f"архив {name} не получен: {type(exc).__name__}: {exc}") from exc
        digest = a.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            got = "sha256:" + hashlib.sha256(blob).hexdigest()
            if got != digest:
                raise CIRecordRefused(CI_RECORD_BROKEN,
                                      f"архив {name}: дайджест {got} ≠ объявленного {digest}")
        _safe_extract(blob, root / name, name)
    return root


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
