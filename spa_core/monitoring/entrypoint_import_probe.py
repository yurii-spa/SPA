"""Проба импорта точки входа агента: сможет ли она стартовать ТАК, КАК ЕЁ ЗАПУСКАЕТ launchd.

Авария 2026-08-26. Владелец ночью включил `com.spa.source_discovery`. Агент падал
КАЖДЫЙ запуск::

    exec: .../python3 .../scripts/find_defillama_sources.py --save
    ModuleNotFoundError: No module named 'spa_core'
    EXIT agent=source_discovery code=1

`deployment_acceptance` в ту же минуту отвечал **OK: 85 entrypoints executable,
6 modules import** — и был прав по букве каждой своей проверки:

* точка входа `agent_source_discovery.sh` СУЩЕСТВУЕТ и ИСПОЛНЯЕМА (проверка №1);
* все шесть модулей из `CRITICAL_IMPORTS` импортируются (проверка №2) — но ни один
  из них не есть цель этого агента;
* артефактов у недельного агента в списке нет (проверка №3).

Между «обёртка исполняема» и «агент способен стартовать» лежит ровно то, что
сломалось: launchd зовёт **скрипт по абсолютному пути**, а не модуль через `-m`.
CPython кладёт в `sys.path[0]` КАТАЛОГ СКРИПТА (`scripts/`), и рабочий каталог в
путь при этом НЕ попадает — сколько бы обёртка ни делала `cd` в корень репозитория.
Поэтому `import spa_core` из `scripts/*.py` обязан падать, и падает.

Модель прежней проверки расходилась с реальностью ровно в этом измерении:
`check_imports` зовёт `python3 -c "import X"` с `cwd=<корень репо>`, где корень
ВСЕГДА на пути. Такая проба не способна воспроизвести дефект в принципе.

**Такт агента — раз в неделю** (`StartInterval 604800`): без этой пробы падение
простояло бы семь суток, а пульс сказал бы «агент отработал» (он действительно
запускался — и умирал).

## Что делает этот модуль

Берёт ФАЙЛ точки входа и ЗАГРУЖАЕТ его во внуковом процессе, стартующем из того же
каталога, из которого его увидит launchd, — `sys.path[0]` строит настоящий
интерпретатор, а не наша арифметика над `sys.path`.

Загрузка — `runpy.run_path(..., run_name != "__main__")` для скрипта и
`importlib.import_module` для модуля: **весь верхний уровень файла исполняется В
ПОРЯДКЕ**, а блок `if __name__ == "__main__":` — нет. Порядок здесь не деталь, а
предмет: часть наших точек входа чинит себе путь (`sys.path.insert` СТРОКОЙ ВЫШЕ
импорта), часть заворачивает импорт в `try` с загрузкой по пути к файлу
(`scripts/site_freshness_monitor.py`, урок цикла #111). Обе конструкции исправны, и
проба, разбирающая импорты в отрыве от порядка, краснела бы на живом (см. ниже).

Граница риска ровно та же, что у `check_imports` и `agent_static_probe.sh`: верхний
уровень исполняется, работа агента — нет. У файла без заслона `if __name__ ==
"__main__"` верхний уровень И ЕСТЬ работа — такой файл проба ОТКАЗЫВАЕТСЯ трогать.

Read-only. Ничего не чинит и не деплоит. Fail-CLOSED: что не удалось установить —
`unchecked` с названной причиной, а не молчаливый зачёт.

LLM запрещён. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = [
    "has_main_guard",
    "resolve_wrapper_target",
    "invokes_template",
    "probe_wrapper",
    "probe_script",
    "probe_module",
    "OK",
    "FAILED",
    "UNCHECKED",
]

OK, FAILED, UNCHECKED = "ok", "failed", "unchecked"

# Коды возврата CLI. Разделены намеренно: «нашёл поломку» и «не смог проверить» —
# разные новости, и потребитель обязан уметь их различить.
RC_OK, RC_FAILED, RC_UNCHECKED = 0, 3, 4

DEFAULT_TIMEOUT = 60.0

# ПОЧЕМУ ВНУК ЗАГРУЖАЕТ ФАЙЛ, А НЕ СПИСОК ЕГО ИМПОРТОВ.
# Первая версия собирала импорты верхнего уровня разбором и пробовала их по одному.
# Модель оказалась неверной, и это НАШЛОСЬ ЗАМЕРОМ, а не рассуждением: она объявила
# мёртвым живого `com.spa.strategy_lab_paper` (exit 0, отработал в 00:11:41). Тот
# скрипт ЧИНИТ себе путь сам — `sys.path.insert(0, <корень>)` стоит строкой ВЫШЕ
# `from spa_core...`. Список импортов, вырванный из порядка исполнения, этой починки
# не видит. Так же устроены ещё шесть наших точек входа.
#
# Настоящая модель — `runpy.run_path(..., run_name != "__main__")`: исполняется весь
# верхний уровень файла В ПОРЯДКЕ (значит и починка пути, и `try/except` вокруг
# импорта), а блок `if __name__ == "__main__":` НЕ исполняется. Ровно то, что делает
# `import` с модулем: `check_imports` и `agent_static_probe.sh` живут на этом же
# допущении, новизны в риске нет.
_CHILD_SCRIPT_SRC = r"""
import json, runpy, sys, traceback
path = sys.argv[1]
try:
    runpy.run_path(path, run_name="__spa_import_probe__")
except BaseException as exc:                # noqa: BLE001 — важен ЛЮБОЙ отказ загрузки
    print(json.dumps({"failed": [{"error": "{}: {}".format(type(exc).__name__, exc)[:400],
                                  "where": traceback.format_exc(limit=3)[-400:]}],
                      "sys_path0": sys.path[0]}))
else:
    print(json.dumps({"failed": [], "sys_path0": sys.path[0]}))
"""

_CHILD_MODULE_SRC = r"""
import json, importlib, sys, traceback
name = sys.argv[1]
try:
    importlib.import_module(name)
except BaseException as exc:                # noqa: BLE001
    print(json.dumps({"failed": [{"error": "{}: {}".format(type(exc).__name__, exc)[:400],
                                  "where": traceback.format_exc(limit=3)[-400:]}],
                      "sys_path0": sys.path[0]}))
else:
    print(json.dumps({"failed": [], "sys_path0": sys.path[0]}))
"""


def has_main_guard(source: str) -> bool:
    """Есть ли у файла заслон `if __name__ == "__main__":` на верхнем уровне.

    Без заслона верхний уровень файла И ЕСТЬ его работа: «загрузить, но не запускать»
    для такого файла невозможно, и проба обязана ОТКАЗАТЬСЯ, а не исполнить агента.
    Из 199 скриптов в `scripts/` заслона нет у двух — отказ будет редким и названным.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError("не разбирается как python: {}".format(exc)) from exc
    for node in tree.body:
        if isinstance(node, ast.If) and "__name__" in ast.dump(node.test):
            return True
    return False


def _run_child(src: str, arg: str, cwd: str, python: Optional[str], timeout: float,
               env: Optional[dict] = None) -> Tuple[Optional[dict], str]:
    """Гоняет пробу `src` над `arg` во ВНУКОВОМ процессе с `cwd` в `sys.path[0]`.

    `python -c` кладёт в `sys.path[0]` рабочий каталог — то же самое, что делает
    `python <script>.py` со своим каталогом. Поэтому достаточно позвать внука ИЗ
    нужного каталога, и путь строится настоящим интерпретатором, а не нашей
    арифметикой над `sys.path`.
    """
    exe = python or sys.executable
    try:
        proc = subprocess.run([exe, "-c", src, arg], cwd=cwd,
                              capture_output=True, text=True, timeout=timeout,
                              env=env if env is not None else None)
    except subprocess.TimeoutExpired:
        return None, "проба не уложилась в {:.0f}с".format(timeout)
    except Exception as exc:                     # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, exc)
    out = (proc.stdout or "").strip()
    if not out:
        return None, "внуковый процесс не ответил (rc={}): {}".format(
            proc.returncode, (proc.stderr or "").strip()[-300:])
    try:
        return json.loads(out.splitlines()[-1]), ""
    except ValueError as exc:
        return None, "ответ внука не разобран ({}): {}".format(exc, out[-200:])


def probe_script(script: str, *, python: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, env: Optional[dict] = None) -> dict:
    """`python3 /abs/path/script.py` — `sys.path[0]` = КАТАЛОГ СКРИПТА.

    Внук стартует ИЗ каталога скрипта, поэтому путь строит настоящий интерпретатор,
    а не наша арифметика над `sys.path`.
    """
    path = Path(script)
    res = {"target": str(path), "kind": "script", "status": UNCHECKED,
           "failures": [], "reason": ""}
    if not path.is_file():
        res["reason"] = "файла точки входа нет: {}".format(path)
        return res
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        res["reason"] = "файл не читается: {}".format(exc)
        return res
    try:
        guarded = has_main_guard(source)
    except ValueError as exc:
        res["status"] = FAILED
        res["failures"] = [{"error": str(exc)}]
        return res
    if not guarded:
        res["reason"] = ("у файла нет заслона `if __name__ == \"__main__\"` — его верхний "
                         "уровень И ЕСТЬ работа агента; загрузить, не запустив, невозможно, "
                         "поэтому проба ОТКАЗЫВАЕТСЯ (запускать агента она не имеет права)")
        return res
    doc, err = _run_child(_CHILD_SCRIPT_SRC, str(path), str(path.parent.resolve()),
                          python, timeout, env)
    if doc is None:
        res["reason"] = err
        return res
    res["sys_path0"] = doc.get("sys_path0")
    res["failures"] = doc.get("failed") or []
    res["status"] = FAILED if res["failures"] else OK
    return res


def probe_module(module: str, *, cwd: Optional[str] = None, python: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, env: Optional[dict] = None) -> dict:
    """`python3 -m pkg.mod` — `sys.path[0]` = РАБОЧИЙ КАТАЛОГ (шаблон делает `cd` в корень).

    `import pkg.mod` исполняет верхний уровень модуля и НЕ исполняет его
    `if __name__ == "__main__"` — та же граница, что у скриптовой пробы.
    """
    root = cwd or os.getcwd()
    res = {"target": module, "kind": "module", "status": UNCHECKED,
           "failures": [], "reason": ""}
    doc, err = _run_child(_CHILD_MODULE_SRC, module, root, python, timeout, env)
    if doc is None:
        res["reason"] = err
        return res
    res["sys_path0"] = doc.get("sys_path0")
    res["failures"] = doc.get("failed") or []
    res["status"] = FAILED if res["failures"] else OK
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Проба импорта точки входа агента так, как её запускает launchd. "
                    "Ничего не исполняет и не чинит.")
    ap.add_argument("--agent", default="", help="метка агента (для отчёта)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--script", help="абсолютный путь к .py, который запускает launchd")
    g.add_argument("--module", help="имя модуля, который запускается через -m")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)

    if args.script:
        res = probe_script(args.script, timeout=args.timeout)
    else:
        res = probe_module(args.module, timeout=args.timeout)
    res["agent"] = args.agent
    print(json.dumps(res, ensure_ascii=False))
    return {OK: RC_OK, FAILED: RC_FAILED}.get(res["status"], RC_UNCHECKED)


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Разбор обёртки агента: ЧТО именно запускает launchd
# ---------------------------------------------------------------------------
#
# ПОЧЕМУ СТАТИЧЕСКИ, А НЕ ЗАПУСКОМ ОБЁРТКИ С ФЛАГОМ «только проверь».
# Такой режим был написан и снят В ТОТ ЖЕ ЗАХОД, потому что замер показал цену.
# Обёртка агента `exec`ает `agent_template.sh` ПО АБСОЛЮТНОМУ ПУТИ — то есть шаблон
# БОЕВОГО дерева, а не того, из которого мы проверяем. Пока флаг не доехал до прода,
# он просто игнорируется, и обёртка запускает НАСТОЯЩЕГО АГЕНТА. Измерено 2026-08-27
# дословно: шесть обёрток, позванных с флагом против дерева без поддержки,
# отработали как обычные запуски — 86.6 с, `aggressive_lab` прогнал полный
# paper-цикл вне расписания.
#
# Поэтому цель достаётся РАЗБОРОМ ТЕКСТА обёртки: не исполняется ничего, ни разу.

# Имя модуля python — иначе случайный токен обёртки уезжает в пробу как «модуль»
# (замерено: `agent_static_probe.sh` отдавал целью строку `PY_SEEN=1;`).
_RE_MODULE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$')

_RE_TEMPLATE_CALL = re.compile(
    r'agent_template\.sh["\']?\s*(?:\\\s*\n\s*)?([^\s\\]+)\s*(?:\\\s*\n\s*)?([^\s\\]+)')
# ВЫЗОВ шаблона, а не упоминание. `agent_static_probe.sh` — инструмент, а не обёртка
# агента: он лишь СОПОСТАВЛЯЕТ имя шаблона в `case`-ветке. Проверка «есть подстрока»
# записывала его в обёртки и требовала у него цель запуска, которой нет.
_RE_TEMPLATE_INVOCATION = re.compile(
    r'^\s*(?:exec\s+)?(?:/bin/)?bash\s+\S*agent_template\.sh\b', re.M)

_RE_ASSIGN = re.compile(
    r'^\s*(?:export\s+)?([A-Z_]+)=(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\s#\n]*))', re.M)


def invokes_template(src: str) -> bool:
    """Правда ли, что этот файл ЗАПУСКАЕТ agent_template.sh (а не упоминает его)."""
    return bool(_RE_TEMPLATE_INVOCATION.search(strip_comments(src)))


def strip_comments(src: str) -> str:
    """Убирает строки-комментарии. Разбор ОБЯЗАН смотреть только на код.

    В шапках наших обёрток живут примеры (`RUN_SCRIPT="/abs/path/script.py"`,
    «позови agent_template.sh …»). Разбор по всему тексту принимал их за настоящий
    вызов: `agent_aggressive_lab.sh` так «запускал» цель с именем `bash-wrapper`
    из фразы в комментарии.
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def _assignments(src: str) -> dict:
    """Присваивания верхнего уровня вида VAR="value" — без исполнения shell."""
    out = {}
    for m in _RE_ASSIGN.finditer(src):
        val = next((g for g in m.groups()[1:] if g is not None), "")
        out.setdefault(m.group(1), val)
    return out


def _abs(path: str, repo_root: str) -> str:
    """Относительный путь в обёртке разрешается от КОРНЯ РЕПО: шаблон делает туда `cd`."""
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


def _expand(value: str, repo_root: str) -> str:
    for token in ("${REPO_ROOT}", "$REPO_ROOT", "${REPO}", "$REPO"):
        value = value.replace(token, repo_root)
    return value


def resolve_wrapper_target(wrapper: str, *, default_repo_root: str = "") -> dict:
    """Что запустит эта обёртка: `{"kind","target","pythonpath","template","reason"}`.

    `kind` = `script` | `module` | `""` (не разобрано — тогда заполнен `reason`).
    Ничего не исполняет.
    """
    res = {"kind": "", "target": "", "pythonpath": "", "template": "", "reason": "",
           "structural": False}
    wp = Path(wrapper)
    try:
        src = wp.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        res["reason"] = "обёртка не читается: {}".format(exc)
        return res

    src = strip_comments(src)
    assigns = _assignments(src)
    repo_root = _expand(assigns.get("REPO_ROOT", ""), "") or default_repo_root or str(wp.parent.parent)
    # `REPO_ROOT="${SPA_AGENT_REPO_ROOT:-/abs/path}"` — берём значение по умолчанию
    m = re.search(r'REPO_ROOT="\$\{SPA_AGENT_REPO_ROOT:-([^}"]+)\}"', src)
    if m:
        repo_root = m.group(1)

    # PYTHONPATH, который обёртка экспортирует ДО передачи управления шаблону
    m = re.search(r'^\s*export\s+PYTHONPATH="?([^"\n]+)"?', src, re.M)
    if m:
        pp = m.group(1)
        pp = re.sub(r'\$\{PYTHONPATH:\+:\$PYTHONPATH\}', '', pp)
        res["pythonpath"] = _expand(pp.strip(), repo_root)

    m = re.search(r'(\S*agent_template\.sh)', src)
    if m:
        res["template"] = _expand(m.group(1), repo_root)

    if not invokes_template(src):
        # СТРУКТУРНАЯ слепота, а не поломка: такая обёртка — не «агент с одной целью»,
        # а собственный сценарий из нескольких шагов (дневной цикл, автопуш, бэкап).
        # Цели у неё нет, выдумывать её нельзя, а запускать обёртку — тем более.
        # Помечается отдельно от «не смогли разобрать» и вердикт НЕ красит: сторож,
        # который не может стать зелёным ни при каком значении, перестают читать.
        res["structural"] = True
        res["reason"] = ("обёртка не делегирует agent_template.sh — это собственный сценарий, "
                         "а не агент с одной целью запуска; цель не выводится разбором, "
                         "а запускать обёртку нельзя (она исполнит сценарий)")
        return res

    # Режим A: заголовочные переменные в самой обёртке
    run_script = _expand(assigns.get("RUN_SCRIPT", ""), repo_root)
    module = _expand(assigns.get("MODULE", ""), repo_root)
    # `MODULE="${MODULE:-}"` в шаблоне — пустышка; в обёртке значение непустое
    if run_script and run_script.endswith(".py"):
        res["kind"], res["target"] = "script", _abs(run_script, repo_root)
        return res
    if module and _RE_MODULE_NAME.match(module):
        res["kind"], res["target"] = "module", module
        return res

    # Режим B: цель — второй позиционный аргумент вызова шаблона
    m = _RE_TEMPLATE_CALL.search(src)
    if m:
        target = _expand(m.group(2).strip('"\''), repo_root)
        if target.endswith(".py"):
            res["kind"], res["target"] = "script", _abs(target, repo_root)
        elif _RE_MODULE_NAME.match(target):
            res["kind"], res["target"] = "module", target
        if res["kind"]:
            return res

    res["reason"] = "цель запуска не найдена в обёртке (ни RUN_SCRIPT/MODULE, ни аргумент шаблона)"
    return res


def probe_wrapper(wrapper: str, *, default_repo_root: str = "", python: Optional[str] = None,
                  timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Вердикт по ОДНОЙ обёртке агента. Не исполняет ни обёртку, ни цель."""
    info = resolve_wrapper_target(wrapper, default_repo_root=default_repo_root)
    out = {"wrapper": str(wrapper), "kind": info["kind"], "target": info["target"],
           "status": UNCHECKED, "failures": [], "reason": info["reason"],
           "structural": info["structural"]}
    if not info["kind"]:
        return out

    env = dict(os.environ)
    if info["pythonpath"]:
        env["PYTHONPATH"] = info["pythonpath"] + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    else:
        # Не наследуем PYTHONPATH своего процесса: он может ЧИНИТЬ то, что в
        # проде не починено, и проба тихо позеленеет на сломанном агенте.
        env.pop("PYTHONPATH", None)

    if info["kind"] == "script":
        res = probe_script(info["target"], python=python, timeout=timeout, env=env)
    else:
        root = info["target"] and (default_repo_root or str(Path(wrapper).resolve().parent.parent))
        res = probe_module(info["target"], cwd=root, python=python, timeout=timeout, env=env)
    out.update({"status": res["status"], "failures": res["failures"],
                "reason": res["reason"], "sys_path0": res.get("sys_path0")})
    return out
