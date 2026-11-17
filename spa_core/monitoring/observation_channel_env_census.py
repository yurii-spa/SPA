#!/usr/bin/env python3
"""spa_core/monitoring/observation_channel_env_census.py — «есть ли ЧЕТВЁРТАЯ
переменная рода „канал наблюдения, который родитель объявляет себе, а наследует
ребёнок"?»

**Зачем.** ADR-1039 (цикл #1178) закрыл три переменные — ``SPA_PYTEST_STREAM``,
``SPA_PYTEST_MANIFEST``, ``SPA_PYTEST_RESUME_ONLY``: шард объявляет их в окружении
джобы, грузит оба плагина флагом ``-p``, а дочерний pytest любой площадки наследует
окружение через ``env = {**os.environ}``. Перечень собранного открывался на ``"w"``
⇒ перечень шарда ИСЧЕЗАЛ целиком, и **вердикта о НАБОРЕ не было ДВА контрольных
прогона подряд** (`43985062958`, `43996349768`) — а ``conclusion failure`` этого не
говорит (ADR-474).

Раздел «чего это НЕ закрывает» того же решения сказал вслух: **существуют ли
ЧЕТВЁРТЫЕ такие переменные — НЕ ИЗМЕРЕНО, и нулём это не считается.** Заказ G1028
п. 1 назвал и способ замера, дословно: «переменные, которые воркфлоу объявляет шагу
pytest, × те, что читает ``pytest_configure`` любого нашего плагина; затем
дифференциал (ребёнок с унаследованным окружением против ребёнка с чистым)». Этот
модуль задаёт первый вопрос; второй — :func:`inheritance_probe`.

**ДВЕ СТУПЕНИ, и склеивать их нельзя.**

====================  ======================================================
ступень               на какой вопрос отвечает
====================  ======================================================
``census`` (статика)  ПОВЕРХНОСТЬ: какие переменные вообще могут оказаться
                      каналом — пересечение «объявлено шагу pytest» и
                      «читается в ``pytest_configure`` нашего плагина».
                      Это ВЕРХНЯЯ граница, а не население.
``inheritance_probe`` ЧЛЕНСТВО: видит ли ребёнок значение родителя (дверь
(дифференциал)        открыта) и ПИШЕТ ли читающий плагин в это значение.
                      Членом класса переменная становится, только когда ОБА
                      ответа «да».
====================  ======================================================

**Почему статики недостаточно и почему «дверь закрыта» — ПРЕТЕНЗИЯ, а не ответ.**
``os.environ.pop`` рядом с абзацем про снятие канала есть ровно та «записка вместо
инъекции», которую цикл #477 нашёл у претензии ``injected-clock``: претензию обязан
мерить ПРИБОР, а не читатель. Поэтому статический ярлык ``removed`` здесь называется
``claim_removed`` и его ПРОВЕРЯЕТ дифференциал на живой двухуровневой сцене
(pytest → тест → дочерний pytest).

**Почему «наследуется» само по себе дефектом НЕ является.** ``SPA_ENV=ci`` и
``PYTHONHASHSEED=0`` объявлены тому же шагу и наследуются НАМЕРЕННО — предписанная
команда (``CLAUDE.md``) без них отвечает на свой вопрос, а не на нужный (цикл #421).
Вред класса требует ВТОРОГО условия: читающий плагин ОТКРЫВАЕТ значение на запись,
то есть переменная называет АРТЕФАКТ родителя, а не режим прогона. Слить два условия
в одно значило бы объявить членом класса каждую переменную окружения CI.

**Три исхода различимы у каждой двери** (инв. #17): измерено · измерено и равно нулю
· НЕ ИЗМЕРЕНО с названной причиной. В частности:

* разборщик YAML не ввезён ⇒ ``status="unmeasured"`` с причиной, а не «воркфлоу не
  объявляют переменных» (дословный урок ``pyflakes``,
  `.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»: отсутствие инструмента есть
  самостоятельный третий исход, а не число и не скип);
* каталог воркфлоу не прочитан ⇒ то же;
* имя переменной, собранное выражением, которое прибор не разрешил, ⇒ строка
  ``unresolved`` с причиной, а не молчаливый пропуск. **Цена названа вслух:**
  разрешение имени идёт ГЛУБИНОЙ 1 по присваиваниям модуля, поэтому найденное есть
  НИЖНЯЯ граница (урок G1028 п. 4: литеральный ``argv`` не увидел саму виновницу
  ADR-1039, потому что её команда собрана в переменную).

**Перечень плагинов НЕ взят из памяти — он ИЗМЕРЕН:** модули, которые воркфлоу
грузит флагом ``-p`` шагу pytest, плюс ``conftest.py`` корней, названных в той же
команде. Плагин, которого воркфлоу не называет, в поверхность не входит, и это
ЦЕНА, а не пробел: загруженным в CI он не бывает.

**Прибор только ЧИТАЕТ** — ни одного байта никуда не пишет и ничего не исполняет;
дочерние процессы поднимает ТОЛЬКО :func:`inheritance_probe`, и только в каталоге,
который ей передали.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Каталог воркфлоу — ОБЪЯВЛЕНИЕ. Другой каталог есть решение, а не умолчание.
DECLARED_WORKFLOW_DIR = ".github/workflows"

#: Корни ВТОРОГО места объявления (код, кладущий переменную ребёнку-pytest).
#: Каталог, которого здесь нет, в поверхность не входит, и это сказано вслух.
DECLARED_ROOTS = ("spa_core", "scripts", "tests")

#: Вложенные деревья того же клона несут КОПИИ тех же файлов; считать их значило бы
#: умножить население на число worktree'ов, живущих внутри репозитория.
SKIP_PARTS = (".claude", "node_modules", ".git", "site-packages", "__pycache__")

#: Как узнаётся «шаг зовёт pytest». Форма ЗАМКНУТА и печатается в отчёте: шаг,
#: зовущий pytest иначе, в поверхность не входит. `pip install pytest==…` под это
#: правило НЕ подходит намеренно — установка инструмента каналом не распоряжается.
_PYTEST_INVOCATION = re.compile(
    r"(?:^|[\s;&|(])(?:python[0-9.]*\s+-m\s+pytest|pytest)(?=[\s\\]|$)")

#: Чтения окружения, которые прибор узнаёт. Вызов под другим именем даёт строку
#: `unresolved`, а не тишину.
_READ_KINDS = {
    ("environ", "pop"): "pop",
    ("environ", "get"): "get",
    ("environ", "setdefault"): "setdefault",
}

#: Объявленные исходы каждой ступени. Исход вне перечня краснит сторожа, а не
#: проезжает молча (инв. #17).
DECLARED_STATUSES = ("measured", "unmeasured")
DECLARED_VERDICTS = (
    "member",            # ребёнок видит значение И плагин пишет в него
    "door_closed",       # ребёнок значения НЕ видит — канал снят родителем
    "inherited_benign",  # ребёнок видит, но плагин в значение не пишет (режим, не канал)
    "unmeasured",        # предпосылка не обеспечена, причина названа
)


# --------------------------------------------------------------------------- #
# ось 1 — что воркфлоу ОБЪЯВЛЯЕТ шагу pytest
# --------------------------------------------------------------------------- #

def _load_yaml(text: str, *, filename: str) -> tuple[Optional[dict], Optional[str]]:
    """YAML → документ. Отсутствие разборщика — ТРЕТИЙ ИСХОД, а не пустой документ."""
    try:
        import yaml  # noqa: PLC0415 — ленивый ввоз: инв. #4 (только stdlib в рантайме)
    except Exception as exc:                                 # pragma: no cover
        return None, f"разборщик YAML не ввезён: {type(exc).__name__}: {exc}"
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:
        return None, f"{filename}: YAML не разобран: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, f"{filename}: корень YAML не отображение ({type(doc).__name__})"
    return doc, None


def _env_of(node: Any) -> dict[str, str]:
    """``env:`` узла. Не отображение ⇒ пусто (и это видно по отсутствию строк)."""
    env = node.get("env") if isinstance(node, dict) else None
    if not isinstance(env, dict):
        return {}
    return {str(k): ("" if v is None else str(v)) for k, v in env.items()}


def invokes_pytest(run: object) -> bool:
    """Зовёт ли ``run`` шага pytest как КОМАНДУ (а не ставит его как пакет)."""
    if not isinstance(run, str):
        return False
    for line in run.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "pip install" in stripped or stripped.startswith("pip "):
            continue
        if _PYTEST_INVOCATION.search(stripped):
            return True
    return False


def plugins_in(run: str) -> list[str]:
    """Модули, загруженные шагу флагом ``-p`` (без встроенных ``no:…``)."""
    out: list[str] = []
    for match in re.finditer(r"-p\s+([A-Za-z_][\w.]*)", run):
        name = match.group(1)
        if name.startswith("no:") or "." not in name:
            continue
        if name not in out:
            out.append(name)
    return out


def roots_in(run: str) -> list[str]:
    """Каталоги, названные команде pytest — по ним ищутся ``conftest.py``."""
    out: list[str] = []
    for match in re.finditer(r"(?<![\w./-])([\w][\w./-]*/)(?=[\s\\]|$)", run):
        root = match.group(1).rstrip("/")
        if root and root not in out:
            out.append(root)
    return out


def pytest_steps(workflow_dir: Path) -> dict[str, Any]:
    """Шаги всех воркфлоу, которые зовут pytest, с ВИДИМЫМ им окружением.

    Видимое окружение — объединение ``env`` воркфлоу, джобы и самого шага: именно
    его ребёнок и наследует. Нечитаемый файл даёт строку в ``unreadable``, а не
    молчаливый пропуск.
    """
    steps: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    files: list[str] = []
    if not workflow_dir.is_dir():
        return {"steps": [], "unreadable": [], "files": [],
                "why": f"каталог воркфлоу не прочитан: {workflow_dir}"}
    for path in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        rel = path.name
        files.append(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            unreadable.append({"file": rel, "why": f"не прочитан: {exc}"})
            continue
        doc, why = _load_yaml(text, filename=rel)
        if doc is None:
            unreadable.append({"file": rel, "why": why or "причина не названа"})
            continue
        top_env = _env_of(doc)
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_env = _env_of(job)
            raw_steps = job.get("steps")
            if not isinstance(raw_steps, list):
                continue
            for index, step in enumerate(raw_steps):
                if not isinstance(step, dict):
                    continue
                run = step.get("run")
                if not invokes_pytest(run):
                    continue
                run_text = run if isinstance(run, str) else ""
                visible = {**top_env, **job_env, **_env_of(step)}
                steps.append({
                    "file": rel,
                    "job": str(job_name),
                    "step": str(step.get("name") or f"#{index}"),
                    "env": visible,
                    "plugins": plugins_in(run_text),
                    "roots": roots_in(run_text),
                })
    return {"steps": steps, "unreadable": unreadable, "files": files, "why": None}


# --------------------------------------------------------------------------- #
# ось 2 — что ЧИТАЕТ `pytest_configure` нашего плагина
# --------------------------------------------------------------------------- #

def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Строковые константы модуля — материал разрешения имени ГЛУБИНОЙ 1."""
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value.value
    return out


def _read_kind(call: ast.Call) -> Optional[str]:
    """Вид чтения окружения у вызова — либо ``None``, если это не оно."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        key = (func.value.attr, func.attr)
        if key in _READ_KINDS and isinstance(func.value.value, ast.Name) \
                and func.value.value.id == "os":
            return _READ_KINDS[key]
    if isinstance(func, ast.Attribute) and func.attr == "getenv" \
            and isinstance(func.value, ast.Name) and func.value.id == "os":
        return "getenv"
    return None


def _first_arg_name(call: ast.Call, constants: dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    """Имя переменной окружения у вызова: (имя, причина-если-не-разрешено)."""
    if not call.args:
        return None, "вызов без аргументов"
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value, None
    if isinstance(arg, ast.Name):
        resolved = constants.get(arg.id)
        if resolved is not None:
            return resolved, None
        return None, (f"имя `{arg.id}` не разрешено константой модуля "
                      f"(разрешение глубиной 1 — НИЖНЯЯ граница)")
    return None, f"аргумент — выражение {type(arg).__name__}, прибор его не разрешает"


def _subscript_names(node: ast.AST, constants: dict[str, str]) -> list[tuple[str, Optional[str]]]:
    """``os.environ[X]`` — чтение индексом, отдельная форма от ``get``/``pop``."""
    out: list[tuple[str, Optional[str]]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Subscript):
            continue
        value = sub.value
        if not (isinstance(value, ast.Attribute) and value.attr == "environ"
                and isinstance(value.value, ast.Name) and value.value.id == "os"):
            continue
        key = sub.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            out.append((key.value, None))
        elif isinstance(key, ast.Name) and key.id in constants:
            out.append((constants[key.id], None))
        else:
            out.append(("", f"индекс — выражение {type(key).__name__}, не разрешён"))
    return out


def _writes_paths(tree: ast.Module) -> bool:
    """Открывает ли МОДУЛЬ что-нибудь на запись (``open(..., "w"/"a"/"x")``).

    Это вторая половина вреда: переменная, в значение которой никто не пишет,
    называет РЕЖИМ прогона, а не АРТЕФАКТ родителя, и наследуется безвредно.
    Вопрос задаётся МОДУЛЮ, а не выражению: прослеживать значение до дескриптора
    значило бы чинить дефект догадкой (`StreamRecorder(path)` открывает файл
    СОБСТВЕННЫМ кодом, и дверь по `open(path)` его бы не увидела).
    """
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if name not in ("open", "atomic_save", "write_text", "write_bytes"):
            continue
        if name != "open":
            return True
        modes = [a.value for a in call.args[1:]
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        modes += [kw.value.value for kw in call.keywords
                  if kw.arg == "mode" and isinstance(kw.value, ast.Constant)
                  and isinstance(kw.value.value, str)]
        if any(m and m[0] in "wax" for m in modes):
            return True
    return False


def module_env_reads(path: Path) -> dict[str, Any]:
    """Чтения окружения в ``pytest_configure`` и на уровне модуля плагина."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"rows": [], "unresolved": [], "writes": None,
                "why": f"не прочитан: {exc}"}
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return {"rows": [], "unresolved": [], "writes": None,
                "why": f"не разобран: {exc}"}
    constants = _module_constants(tree)
    rows: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []

    def collect(node: ast.AST, scope: str) -> None:
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            kind = _read_kind(call)
            if kind is None:
                continue
            name, why = _first_arg_name(call, constants)
            if name is None:
                unresolved.append({"scope": scope, "line": str(call.lineno),
                                   "kind": kind, "why": why or "причина не названа"})
                continue
            rows.append({"name": name, "kind": kind, "scope": scope,
                         "line": str(call.lineno)})
        for name, why in _subscript_names(node, constants):
            if name:
                rows.append({"name": name, "kind": "index", "scope": scope, "line": "?"})
            else:
                unresolved.append({"scope": scope, "line": "?", "kind": "index",
                                   "why": why or "причина не названа"})

    configure = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "pytest_configure"]
    for node in configure:
        collect(node, "pytest_configure")
    # Уровень модуля: `conftest.py` читает `SPA_ENV` на импорте, то есть ДО
    # `pytest_configure`, и ребёнок наследует его так же. Пропустить этот охват
    # значило бы ответить о форме кода, а не о классе.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        collect(node, "module")
    return {"rows": rows, "unresolved": unresolved,
            "writes": _writes_paths(tree), "why": None}


def _launches_pytest(tree: ast.Module) -> bool:
    """Поднимает ли МОДУЛЬ дочерний pytest (``-m pytest`` либо бинарь ``pytest``)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == "pytest" or node.value.endswith("-m pytest"):
                return True
    return False


#: Предел кругов засева. Исчерпание — ТРЕТИЙ ИСХОД, а не молчаливая остановка.
_SEED_ROUNDS = 6


def _is_env_seed(node: ast.AST, seeds: set[str]) -> bool:
    """``os.environ`` либо уже засеянное имя — сам по себе, без обёрток.

    **Выбор между двумя отображениями засевает ОБА.** ``os.environ if env is None
    else env`` и ``env or os.environ`` — это окружение в любой из ветвей, и ровно в
    такой форме стои́т ``base_env`` у ``scripts/ci_control.py``, то есть у модуля,
    объявляющего ИЗВЕСТНОГО члена класса. Редакция без этой ветви потеряла
    ``SPA_PYTEST_RESUME_ONLY`` третий раз подряд — и в третий раз по новой причине.
    """
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return True
    if isinstance(node, ast.Name):
        return node.id in seeds
    if isinstance(node, ast.IfExp):
        return _is_env_seed(node.body, seeds) or _is_env_seed(node.orelse, seeds)
    if isinstance(node, ast.BoolOp):
        return any(_is_env_seed(v, seeds) for v in node.values)
    return False


def _derives_from(node: ast.AST, seeds: set[str]) -> bool:
    """Является ли ВЫРАЖЕНИЕ отображением окружения.

    Форма ЗАМКНУТА намеренно: ``e`` · ``dict(e)`` · ``e.copy()`` · ``{**e}`` ·
    ``{**e, "K": v}``. «RHS где-то УПОМИНАЕТ засеянное имя» формой НЕ является — это
    ровно та ошибка, что у контейнера в сторожe `injected-clock` (#477): при таком
    правиле ``code = subprocess.run(cmd, env=e)`` засеял бы ``code``, засев пошёл бы
    каскадом по всему модулю и не сходился за шесть кругов (замер: 4 модуля, среди
    них ``scripts/ci_control.py`` — тот самый, что объявляет известного члена).
    """
    if _is_env_seed(node, seeds):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "dict":
            return any(_is_env_seed(a, seeds) for a in node.args) or any(
                _is_env_seed(kw.value, seeds) for kw in node.keywords if kw.arg is None)
        if isinstance(func, ast.Attribute) and func.attr == "copy":
            return _is_env_seed(func.value, seeds)
        return False
    if isinstance(node, ast.Dict):
        return any(key is None and _is_env_seed(value, seeds)
                   for key, value in zip(node.keys, node.values))
    return False


def _env_mapping_names(tree: ast.Module) -> tuple[set[str], bool]:
    """Имена, которые в этом модуле ЕСТЬ отображение окружения. → (имена, исчерпано?)

    Без этой двери ось объявления считает ключами окружения ЛЮБУЮ запись индексом —
    первая редакция так дала 276 «переменных», из которых окружением были единицы
    (``aave_v3``, ``cmd``, ``path`` — ключи обычных словарей).

    **Засев идёт ДО НЕПОДВИЖНОЙ ТОЧКИ, а не глубиной 1** (приём ADR-932). Глубины 1
    не хватило на ИЗВЕСТНОГО члена класса: в ``scripts/ci_control.py`` путь
    доигрывания кладётся в ``e``, где ``e = dict(base_env)``, а
    ``base_env = dict(os.environ…)`` — два хопа, и редакция глубины 1 потеряла
    ``SPA_PYTEST_RESUME_ONLY`` ровно так же, как редакция без второго места
    объявления. Исчерпание кругов — третий исход, а не тихая остановка.
    """
    seeds = {"environ"}
    for _ in range(_SEED_ROUNDS):
        grown = set(seeds)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _derives_from(value, seeds):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    grown.add(target.id)
        if grown == seeds:
            return seeds, False
        seeds = grown
    return seeds, True


def _env_key_stores(tree: ast.Module, constants: dict[str, str]) -> tuple[list[dict[str, str]], bool]:
    """Ключи, которые модуль КЛАДЁТ в ОТОБРАЖЕНИЕ ОКРУЖЕНИЯ (индексом либо ``update``)."""
    rows: list[dict[str, str]] = []
    env_names, exhausted = _env_mapping_names(tree)

    def base_is_env(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in env_names
        if isinstance(node, ast.Attribute):
            return node.attr == "environ"
        return False

    def key_name(key: ast.AST) -> Optional[str]:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
        if isinstance(key, ast.Name):
            return constants.get(key.id)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Subscript) or not base_is_env(target.value):
                    continue
                name = key_name(target.slice)
                if name:
                    rows.append({"name": name, "line": str(node.lineno), "kind": "store"})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "update" and base_is_env(node.func.value):
            for arg in node.args:
                if not isinstance(arg, ast.Dict):
                    continue
                for key in arg.keys:
                    name = key_name(key) if key is not None else None
                    if name:
                        rows.append({"name": name, "line": str(node.lineno),
                                     "kind": "update"})
    return rows, exhausted


def declared_by_code(repo_root: Path, roots: Iterable[str]) -> dict[str, Any]:
    """ВТОРОЕ место объявления: переменная, которую КОД кладёт ребёнку-pytest.

    Первая редакция этой переписи спрашивала только ``env:`` воркфлоу — ровно так,
    как назвал способ заказ G1028 п. 1, — и **не нашла известного члена класса**:
    ``SPA_PYTEST_RESUME_ONLY`` ни в одном воркфлоу не объявлен, его кладёт
    ``scripts/ci_control.py`` в окружение дочернего pytest при доигрывании
    (``e[RESUME_ENV] = keep``). Замер, не нашедший известного члена, мерой класса не
    является (дословный урок того же заказа, п. 4) — поэтому мест объявления ДВА.

    Граница названа: модуль считается объявляющим, если он (а) поднимает дочерний
    pytest и (б) кладёт ключ в отображение записью индексом или ``update``. Это
    НИЖНЯЯ граница: отображение не прослеживается до ``env=`` вызова, то есть в ось
    попадут и ключи, уехавшие в другое место. Ось — ПОВЕРХНОСТЬ, а не население;
    сужать её догадкой значило бы вернуть первую редакцию.
    """
    rows: dict[str, list[dict[str, str]]] = {}
    unreadable: list[dict[str, str]] = []
    modules = 0
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            unreadable.append({"file": root, "why": "каталог не прочитан"})
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                unreadable.append({"file": str(path.relative_to(repo_root)),
                                   "why": f"{type(exc).__name__}: {exc}"})
                continue
            if not _launches_pytest(tree):
                continue
            modules += 1
            constants = _module_constants(tree)
            stores, exhausted = _env_key_stores(tree, constants)
            if exhausted:
                unreadable.append({
                    "file": str(path.relative_to(repo_root)),
                    "why": f"засев окружения НЕ СОШЁЛСЯ за {_SEED_ROUNDS} кругов — "
                           "ключи этого модуля НЕ ИЗМЕРЕНЫ"})
                continue
            for row in stores:
                rows.setdefault(row["name"], []).append({
                    **row, "file": str(path.relative_to(repo_root))})
    return {"rows": rows, "unreadable": unreadable, "modules": modules}


def plugin_paths(repo_root: Path, steps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Файлы плагинов, ИЗМЕРЕННЫЕ по воркфлоу: ``-p`` модули + ``conftest.py`` корней."""
    found: dict[str, str] = {}
    missing: list[dict[str, str]] = []
    for step in steps:
        for dotted in step.get("plugins", ()):
            rel = dotted.replace(".", "/") + ".py"
            path = repo_root / rel
            if path.is_file():
                found[dotted] = rel
            else:
                missing.append({"module": dotted, "why": f"файл не найден: {rel}"})
        for root in step.get("roots", ()):
            candidate = repo_root / root / "conftest.py"
            if candidate.is_file():
                found[f"{root}/conftest"] = f"{root}/conftest.py"
    return {"found": found, "missing": missing}


# --------------------------------------------------------------------------- #
# ступень 1 — поверхность
# --------------------------------------------------------------------------- #

def channel_shape(values: Iterable[str]) -> str:
    """Называет ли значение ПУТЬ (канал) или РЕЖИМ прогона — либо НЕ ИЗМЕРЕНО.

    Разделитель здесь несущий: ``ctl/collected.jsonl`` — артефакт родителя, ``ci`` —
    режим. Переменная-режим наследуется НАМЕРЕННО (предписанная команда ``CLAUDE.md``
    без ``SPA_ENV``/``PYTHONHASHSEED`` отвечает на свой вопрос, а не на нужный —
    цикл #421), поэтому объявить её членом класса значило бы назвать членом каждую
    переменную окружения CI. Значение, объявленное КОДОМ, литералом не является ⇒
    третий исход, и он НЕ приравнивается к «режим»: ошибка обязана идти в сторону
    находки.
    """
    literal = [v for v in values if v]
    if not literal:
        return "unmeasured"
    if any("/" in v or "\\" in v or re.search(r"\.[A-Za-z0-9]{2,6}$", v) for v in literal):
        return "path"
    return "mode"


def census(repo_root: Path | str = REPO_ROOT, *,
           workflow_dir: Path | str | None = None,
           roots: Iterable[str] = DECLARED_ROOTS) -> dict[str, Any]:
    """Поверхность класса: «объявлено шагу pytest» × «читается плагином»."""
    root = Path(repo_root)
    wf_dir = Path(workflow_dir) if workflow_dir is not None else root / DECLARED_WORKFLOW_DIR
    surface = pytest_steps(wf_dir)
    if surface["why"]:
        return {"schema": "spa-observation-channel-env-census/1",
                "status": "unmeasured", "why": surface["why"],
                "steps": [], "declared": {}, "read": {}, "candidates": {},
                "plugins": {"found": {}, "missing": []}, "unresolved": [],
                "unreadable": surface["unreadable"]}
    if surface["unreadable"] and not surface["steps"]:
        return {"schema": "spa-observation-channel-env-census/1",
                "status": "unmeasured",
                "why": ("ни один воркфлоу не разобран: "
                        + "; ".join(f"{u['file']} — {u['why']}" for u in surface["unreadable"])),
                "steps": [], "declared": {}, "read": {}, "candidates": {},
                "plugins": {"found": {}, "missing": []}, "unresolved": [],
                "unreadable": surface["unreadable"]}

    declared: dict[str, list[dict[str, str]]] = {}
    for step in surface["steps"]:
        for name, value in step["env"].items():
            declared.setdefault(name, []).append({
                "file": step["file"], "job": step["job"],
                "step": step["step"], "value": value, "place": "workflow"})
    code = declared_by_code(root, roots)
    for name, rows in code["rows"].items():
        for row in rows:
            declared.setdefault(name, []).append({
                "file": row["file"], "job": "—", "step": f"{row['kind']}:{row['line']}",
                "value": "", "place": "code"})

    plugins = plugin_paths(root, surface["steps"])
    read: dict[str, list[dict[str, str]]] = {}
    writes: dict[str, bool] = {}
    unresolved: list[dict[str, str]] = []
    unreadable = list(surface["unreadable"])
    for dotted, rel in sorted(plugins["found"].items()):
        info = module_env_reads(root / rel)
        if info["why"]:
            unreadable.append({"file": rel, "why": info["why"]})
            continue
        writes[dotted] = bool(info["writes"])
        for row in info["rows"]:
            read.setdefault(row["name"], []).append({**row, "module": dotted, "file": rel})
        for row in info["unresolved"]:
            unresolved.append({**row, "module": dotted, "file": rel})

    candidates: dict[str, dict[str, Any]] = {}
    for name in sorted(set(declared) & set(read)):
        reads = read[name]
        # `setdefault` — ЗАПИСЬ в своё окружение, а не чтение канала: она не делает
        # переменную каналом и в претензию «снято» тоже не входит.
        channel_reads = [r for r in reads if r["kind"] != "setdefault"]
        if not channel_reads:
            continue
        claim_removed = any(r["kind"] == "pop" for r in channel_reads)
        plugin_writes = any(writes.get(r["module"], False) for r in channel_reads)
        values = sorted({d["value"] for d in declared[name]})
        candidates[name] = {
            "declared_at": declared[name],
            "declared_places": sorted({d["place"] for d in declared[name]}),
            "read_at": channel_reads,
            "claim_removed": claim_removed,
            "plugin_writes_a_file": plugin_writes,
            "channel_shape": channel_shape(values),
            "values": values,
        }
    unreadable.extend(code["unreadable"])
    return {"schema": "spa-observation-channel-env-census/1",
            "status": "measured", "why": None,
            "steps": surface["steps"], "declared": declared, "read": read,
            "candidates": candidates, "plugins": plugins,
            "unresolved": unresolved, "unreadable": unreadable,
            "files": surface["files"],
            "code_declaring_modules": code["modules"],
            # ДВА разных разрешения, и равнять их нельзя: отображение окружения
            # засевается ДО НЕПОДВИЖНОЙ ТОЧКИ (иначе теряется известный член —
            # `e = dict(base_env)`, `base_env = dict(os.environ if … else env)`), а
            # ИМЯ КЛЮЧА разрешается глубиной 1 по константам модуля, и это НИЖНЯЯ
            # граница: ключ, собранный выражением, даёт строку `unresolved`.
            "env_mapping_resolution": "fixed-point",
            "key_name_resolution_depth": 1}


# --------------------------------------------------------------------------- #
# ступень 2 — дифференциал: ребёнок с унаследованным окружением против чистого
# --------------------------------------------------------------------------- #

_PARENT_SCENE = '''\
import json, os, subprocess, sys

_WATCHED = json.loads(os.environ["SPA_PROBE_WATCHED"])


def test_the_child_reports_what_it_inherited():
    """Ребёнок ДОКЛАДЫВАЕТ, какие из наблюдаемых переменных до него дошли."""
    report = os.environ["SPA_PROBE_REPORT"]
    code = (
        "import json, os, sys\\n"
        "watched = json.loads(os.environ['SPA_PROBE_WATCHED'])\\n"
        "seen = {k: os.environ.get(k) for k in watched}\\n"
        "open(os.environ['SPA_PROBE_REPORT'], 'w', encoding='utf-8')"
        ".write(json.dumps(seen, ensure_ascii=False, sort_keys=True))\\n"
    )
    env = {**os.environ} if os.environ.get("SPA_PROBE_INHERIT") == "1" else {
        "PATH": os.environ.get("PATH", ""),
        "SPA_PROBE_WATCHED": os.environ["SPA_PROBE_WATCHED"],
        "SPA_PROBE_REPORT": report,
    }
    done = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
'''


#: Имя файла сцены и nodeid её единственного теста. Объявлены ЗДЕСЬ, потому что
#: вызывающему они нужны: ``SPA_PYTEST_RESUME_ONLY`` есть СПИСОК того, что доигрывать,
#: и пустой список гасит сцену целиком («1 deselected», код 5). Первая попытка
#: дифференциала так и ответила — честным третьим исходом, и этот исход ЕСТЬ авария
#: 17.10, воспроизведённая прибором на самом себе.
PROBE_SCENE_FILE = "test_inherited_channel_probe.py"
PROBE_SCENE_NODEID = f"{PROBE_SCENE_FILE}::test_the_child_reports_what_it_inherited"


def inheritance_probe(watched: list[str], scene_dir: Path, *,
                      plugins: Iterable[str] = (),
                      env_values: Optional[dict[str, str]] = None,
                      timeout_s: float = 600.0) -> dict[str, Any]:
    """Дифференциал: что из ``watched`` доходит до ребёнка ОДНОГО родителя-pytest.

    Сцена настоящая и двухуровневая — pytest (с теми же плагинами, что в CI) → тест
    → дочерний процесс, собравший окружение так же, как 35 площадок набора
    (``{**os.environ}``). Ребёнок не судит ни о чём: он ДОКЛАДЫВАЕТ, что увидел.

    Три исхода различимы: ``measured`` · ``measured`` с пустым ``seen`` (ребёнок
    не увидел ничего — дверь закрыта у всех) · ``unmeasured`` с причиной (родитель
    не отработал, доклада нет, доклад не разобран). «Доклада нет» НИКОГДА не
    выдаётся за «ничего не унаследовано»: это разные ответы.
    """
    scene_dir = Path(scene_dir)
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene = scene_dir / PROBE_SCENE_FILE
    scene.write_text(_PARENT_SCENE, encoding="utf-8")
    report = scene_dir / "child_report.json"

    env = {**os.environ}
    env.update(env_values or {})
    env["SPA_PROBE_WATCHED"] = json.dumps(list(watched))
    env["SPA_PROBE_REPORT"] = str(report)
    env["SPA_PROBE_INHERIT"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p)
    # ДВЕРЬ ПЕСОЧНИЦЫ (C8(b), ADR-580). Харнесс, поднимающий дочерний процесс против
    # переставленного `PYTHONPATH`, обязан объявить себя песочницей И назвать ей
    # СВОЙ каталог: иначе ребёнок при записи уйдёт в прод (класс INC-1). Прибор,
    # приехавший без этой двери, краснит сторожа в ДЕНЬ доставки — так и случилось
    # с ADR-1038, и этот зов есть исполнение того урока, а не украшение.
    from spa_core.utils import live_paths as _lp       # noqa: PLC0415 — тест-домен

    env[_lp.SANDBOX_ENV] = "1"
    env[_lp.DATA_DIR_ENV] = str(scene_dir / "data")
    env[_lp.LIVE_ROOT_ENV] = str(scene_dir)
    (scene_dir / "data").mkdir(parents=True, exist_ok=True)

    # ЯКОРЬ rootdir обязателен. Без него pytest считает rootdir общим предком cwd и
    # аргумента и обходит scandir'ом весь системный временный каталог (замер #382:
    # 9 780 560 записей, >300 с) — сторож `test_child_pytest_rootdir` считает такой
    # зов членом своего предмета, и приехать в уже красный храповик НОВЫМ членом
    # значило бы молча его ослабить (инв. #16).
    argv = [sys.executable, "-m", "pytest", str(scene), "-q",
            f"--rootdir={scene_dir}", f"--confcutdir={scene_dir}",
            "-p", "no:randomly", "-p", "no:cacheprovider"]
    for dotted in plugins:
        argv += ["-p", dotted]
    try:
        done = subprocess.run(argv, cwd=str(scene_dir), env=env,
                              capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unmeasured", "seen": {},
                "why": f"родитель не поднялся: {type(exc).__name__}: {exc}"}
    if done.returncode != 0:
        return {"status": "unmeasured", "seen": {},
                "why": f"родитель вышел кодом {done.returncode}: "
                       + (done.stdout + done.stderr)[-2000:]}
    if not report.is_file():
        return {"status": "unmeasured", "seen": {},
                "why": "доклада ребёнка нет — это НЕ «ничего не унаследовано»"}
    try:
        seen = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "unmeasured", "seen": {},
                "why": f"доклад ребёнка не разобран: {type(exc).__name__}: {exc}"}
    if not isinstance(seen, dict):
        return {"status": "unmeasured", "seen": {},
                "why": f"доклад ребёнка не отображение: {type(seen).__name__}"}
    return {"status": "measured", "seen": seen, "why": None}


def verdicts(doc: dict[str, Any], probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Членство каждого кандидата — ПО ИСХОДУ дифференциала, не по претензии.

    ``member`` требует ДВУХ условий: ребёнок видит значение родителя И читающий
    плагин открывает файлы на запись. Одно без другого членством не является, и
    расхождение претензии ``claim_removed`` с исходом НАЗЫВАЕТСЯ отдельным полем —
    молчаливое согласие прибора с запиской в коде и есть класс цикла #477.
    """
    out: dict[str, dict[str, Any]] = {}
    unmeasured_why = probe.get("why") if probe.get("status") != "measured" else None
    seen = probe.get("seen") or {}
    for name, info in (doc.get("candidates") or {}).items():
        if unmeasured_why:
            out[name] = {"verdict": "unmeasured", "why": unmeasured_why,
                         "claim_removed": info["claim_removed"],
                         "claim_holds": None}
            continue
        if name not in seen:
            out[name] = {"verdict": "unmeasured",
                         "why": f"переменная {name} не входила в наблюдаемый перечень",
                         "claim_removed": info["claim_removed"], "claim_holds": None}
            continue
        inherited = seen[name] is not None
        claim_holds = (info["claim_removed"] is not inherited)
        # Член класса требует ТРЁХ условий, и каждое чинится своим: ребёнок видит
        # значение · читающий плагин открывает файлы на запись · значение называет
        # ПУТЬ, а не режим прогона. Третий исход формы («значение объявлено кодом,
        # литерала нет») членство НЕ снимает — ошибка обязана идти в сторону находки.
        shape = info.get("channel_shape", "unmeasured")
        if not inherited:
            verdict = "door_closed"
        elif info["plugin_writes_a_file"] and shape != "mode":
            verdict = "member"
        else:
            verdict = "inherited_benign"
        out[name] = {"verdict": verdict, "why": None,
                     "inherited": inherited,
                     "claim_removed": info["claim_removed"],
                     "claim_holds": claim_holds,
                     "channel_shape": shape,
                     "plugin_writes_a_file": info["plugin_writes_a_file"]}
    return out


# --------------------------------------------------------------------------- #
# печать
# --------------------------------------------------------------------------- #

def format_census(doc: dict[str, Any], verdict_rows: Optional[dict[str, Any]] = None) -> str:
    """Отчёт человеку. Третий исход печатается ПЕРВЫМ, а не прячется в хвосте."""
    if doc.get("status") != "measured":
        return ("НЕ ИЗМЕРЕНО: перепись канала наблюдения — "
                + str(doc.get("why") or "причина не названа"))
    lines = [
        f"поверхность: воркфлоу {len(doc['files'])} · шагов pytest {len(doc['steps'])} "
        f"· плагинов измерено {len(doc['plugins']['found'])}",
        f"  ось 1 (объявлено шагу pytest): {len(doc['declared'])} — "
        + ", ".join(sorted(doc["declared"])),
        f"  ось 2 (читается плагином): {len(doc['read'])} — "
        + ", ".join(sorted(doc["read"])),
        f"  ПЕРЕСЕЧЕНИЕ (кандидаты): {len(doc['candidates'])} — "
        + (", ".join(sorted(doc["candidates"])) or "ПУСТО"),
        f"  отображение окружения: засев {doc['env_mapping_resolution']} · имя ключа: "
        f"глубина {doc['key_name_resolution_depth']} ⇒ найденное есть НИЖНЯЯ граница",
        f"  мест объявления ДВА: воркфлоу + код ({doc['code_declaring_modules']} модул(ь/я/ей), "
        "поднимающих дочерний pytest)",
    ]
    if doc["unresolved"]:
        lines.append(f"  НЕ РАЗРЕШЕНО имён: {len(doc['unresolved'])} — "
                     + "; ".join(f"{r['file']}:{r['line']} {r['why']}"
                                 for r in doc["unresolved"][:5]))
    if doc["unreadable"]:
        lines.append(f"  НЕ ПРОЧИТАНО файлов: {len(doc['unreadable'])} — "
                     + "; ".join(f"{r['file']} ({r['why']})" for r in doc["unreadable"][:5]))
    if verdict_rows is None:
        lines.append("  членство НЕ ИЗМЕРЕНО: дифференциал не запускался "
                     "(перечень кандидатов — ВЕРХНЯЯ граница, не население)")
        return "\n".join(lines)
    members = [n for n, r in verdict_rows.items() if r["verdict"] == "member"]
    closed = [n for n, r in verdict_rows.items() if r["verdict"] == "door_closed"]
    benign = [n for n, r in verdict_rows.items() if r["verdict"] == "inherited_benign"]
    unmeasured = [n for n, r in verdict_rows.items() if r["verdict"] == "unmeasured"]
    lines += [
        f"  ЧЛЕНОВ класса: {len(members)} — " + (", ".join(sorted(members)) or "НОЛЬ"),
        f"  дверь закрыта: {len(closed)} — " + (", ".join(sorted(closed)) or "—"),
        f"  наследуется безвредно (режим, не канал): {len(benign)} — "
        + (", ".join(sorted(benign)) or "—"),
        f"  НЕ ИЗМЕРЕНО: {len(unmeasured)} — " + (", ".join(sorted(unmeasured)) or "—"),
    ]
    broken = sorted(n for n, r in verdict_rows.items() if r.get("claim_holds") is False)
    if broken:
        lines.append(f"  ⚠️ ПРЕТЕНЗИЯ РАСХОДИТСЯ С ИСХОДОМ у {len(broken)}: "
                     + ", ".join(broken))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ; дочерний процесс поднимает "
                 "только дифференциал, и только в переданном ему каталоге")
    return "\n".join(lines)
