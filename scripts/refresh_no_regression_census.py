#!/usr/bin/env python3
"""Производитель ЗАПИСИ для критерия §49 `No regression` приказа «Portfolio CIO».

Заказ **G673 п. 1** (цикл #810): критерий §49 `No regression` измеряется ТОЛЬКО
junit-записью прогона, а записи прогона на хосте **не держит никто**. Перепись
(:mod:`spa_core.monitoring.no_regression_census`) записи не производит НАМЕРЕННО —
она прибор, запись ей подают входом. Производителя не было ни одного, и замер
17.10 показал цену этого: артефакт `data/no_regression_census.json` написан 28.09,
возраст **448.9 ч** при пределе пробы **192 ч** ⇒ критерий владельца стоял
`unmeasured`. Он не краснел и не зеленел — он молча перестал отвечать.

## Что делает этот скрипт и чего он НЕ делает

| делает | НЕ делает |
|---|---|
| считает население трёх объявленных поверхностей (перепись, разбором дерева) | не расширяет и не сужает население — это предмет №2 границы ADR-285 |
| гоняет pytest РОВНО по этим файлам с `--junitxml` | не гоняет предписанный прогон четырёх каталогов и не выдаёт себя за него |
| ХРАНИТ запись в дереве, которое ПЕРЕЖИВЁТ прогон (`--records-root`, умолчание — боевое дерево) | ничего не удаляет без явного `--keep N` |
| отдаёт запись переписи и пишет её отчёт | не считает вердикт сам — мерка одна, и она у переписи |

**Вердикт этого прогона отвечает на вопрос владельца и только на него:**
«проходят ли существующие risk/security/architecture-тесты». Он НЕ утверждает,
что зелен весь предписанный набор (`CLAUDE.md`, «Все тесты») — у того вердикта
свой читатель и на сегодня он измеряется в CI.

## Третий исход — у каждого отказа (инв. #17)

«Не измерено» никогда не выдаётся ни за зелень, ни за находку:

* дерево — ПРОД (`spa_core.utils.live_paths.DEFAULT_LIVE_ROOT`) ⇒ отказ ДО запуска.
  Тесты населения пишут в `data/` своего дерева; прогнать их в боевом дереве значило
  бы ровно то, что запрещает `.claude/rules/deployment.md` п. 4. Осознанный обход —
  `--allow-prod-tree`, и он печатается в отчёте;
* `pytest` не запускается (нет модуля, упал на сборке) ⇒ НЕ ИЗМЕРЕНО с кодом возврата
  и хвостом вывода. Отдельный вопрос отдельной пробой: «инструмент есть?» не
  отвечается кодом рабочего прогона (`.claude/rules/deployment.md`, урок `pyflakes`);
* записи после прогона нет или в ней ноль случаев ⇒ НЕ ИЗМЕРЕНО. Это НЕ редкость:
  `--timeout-method=thread` зовёт `os._exit(1)` и снимает сессию, тогда junit-файла
  не остаётся вовсе (ADR-474). Пустая запись не записывается как «всё прошло»;
* перепись не измерила (население не разобрано, поверхность пуста) ⇒ её собственная
  причина, дословно.

Код возврата говорит о СОСТОЯНИИ КРИТЕРИЯ, а не об успехе скрипта:
**0** — измерено, регрессии нет · **1** — измерено, поломки НАЗВАНЫ (находка;
гасить правкой теста запрещено, инв. #16) · **2** — НЕ ИЗМЕРЕНО с названной причиной.

## Такт решает ФАЙЛ, а не расписание

`--if-due` сверяет возраст действующего артефакта с `--max-age-h` (по умолчанию
120 ч — ниже предела пробы 192 ч, чтобы критерий не успевал протухнуть между
прогонами). Не срок ⇒ скрипт НИЧЕГО не перезапускает и печатает вердикт ПРЕЖНЕГО
замера вместе с его возрастом, чтобы «0» нельзя было прочитать как «я только что
померил».

Только stdlib (инв. #4). Прибор не правит ни одного теста (инв. #16), не трогает
RiskPolicy, стоп-кран и живой трек. LLM запрещён.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET  # stdlib-only (инв. #4), как у переписи: запись
# производит наш же pytest в этом же процессе-потомке, внешнего XML здесь нет вовсе.
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Куда складываются записи прогона (относительно каталога хранения).
#: `data/records/` в .gitignore — запись живёт на ХОСТЕ и на origin не уезжает.
RECORDS_REL = Path("data") / "records" / "no_regression"

#: Где хранить записи ПО УМОЛЧАНИЮ — и это НЕ дерево прогона, хотя произведена
#: запись именно там. Прогон обязан идти в ОДНОРАЗОВОМ дереве (см.
#: `_refuse_if_prod_tree`), а одноразовое дерево на то и одноразовое: вместе с ним
#: исчезла бы и запись, то есть ровно то, чего требует заказ G673 п. 1 («записи
#: прогона на хосте не держит никто»), осталось бы невыполненным. Поэтому «где
#: гнать» и «где хранить» — два разных входа: по умолчанию хранилище — боевое
#: дерево (оно переживает любой worktree), и ПИШЕТСЯ туда только XML-запись, а не
#: результат тестов.
DEFAULT_RECORDS_ROOT = Path.home() / "Documents" / "SPA_Claude"

#: Предел возраста действующего артефакта для `--if-due`. Ниже предела пробы
#: (`card_acceptance._NO_REGRESSION_MAX_AGE_H` = 192 ч) НАМЕРЕННО: равные пороги
#: означали бы, что критерий протухает ровно в тот момент, когда наступает срок.
DEFAULT_MAX_AGE_H = 120.0

#: Окружение предписанного прогона. Переменные — часть команды, а не фон:
#: `PYTHONHASHSEED` фиксирует порядок обхода множеств, `SPA_ENV=ci` включает
#: ci-ветки (`CLAUDE.md`, цикл #421). Без них прогон отвечает на СВОЙ вопрос.
RUN_ENV = {"SPA_ENV": "ci", "PYTHONHASHSEED": "0"}

NOT_MEASURED = "unmeasured"

#: Снимок кода (клон коммита) НЕ изолирует прогон от боевых путей: `live_paths` без
#: `SPA_DATA_DIR`/`SPA_LIVE_ROOT` разрешает живое состояние в `~/Documents/SPA_Claude`, а
#: код с `Path.home()`/абсолютным путём пишет туда независимо от дерева прогона (замер 22.10).
#:
#: ЧТО ЕСТЬ ГРАНИЦА, А ЧТО НАБЛЮДАТЕЛЬ (поправка 22.10 по воспроизведению ARB):
#:   * ГРАНИЦА записи — профиль Seatbelt (`sandbox-exec`, `deny file-write*` на охраняемые
#:     корни), наследуемый ВСЕМ деревом потомков: ядро отказывает и sqlite, и shell-потомку,
#:     и `os.open(..., dir_fd=)`. Перед КАЖДЫМ прогоном граница проверяется на временной
#:     сцене (`verify_write_boundary`); нет `sandbox-exec` или хоть один зонд прошёл ⇒ отказ
#:     ДО тестов.
#:   * Окружение (`SPA_DATA_DIR`/`SPA_LIVE_ROOT`, снят `SPA_ALLOW_LIVE_WRITE`) — уводит живое
#:     состояние, но ничего не ЗАПРЕЩАЕТ.
#:   * Python audit-хук (`GUARD_SITECUSTOMIZE`) — НАБЛЮДАТЕЛЬ, не граница: sqlite3 (C-код),
#:     shell-потомок и `dir_fd` проходят мимо него (воспроизведено ARB 22.10). Его отчёт
#:     называет то, что видно Python, и не более.
#:   * Хеш канонического трека — сверка ОДНОГО файла после прогона, не запрет.
#: Чего граница НЕ закрывает: записи, которые по IPC делает за процесс системный демон
#: (launchd, cfprefsd и т. п.), и сеть. Поэтому полная изоляция НЕ доказана, и рабочий запуск
#: против боевого дерева ЗАБЛОКИРОВАН (`PRODUCTION_RUN_BLOCKED`).
GUARD_REPORT_ENV = "SPA_NOREG_GUARD_REPORT_DIR"
GUARD_ROOTS_ENV = "SPA_NOREG_GUARD_ROOTS"
ISOLATION_ENV_DROP = ("SPA_ALLOW_LIVE_WRITE",)

#: Самодостаточный текст: репозиторий прогона не импортируется — сломанный код в снимке
#: не может отключить сторожа. После установки зовётся исходный `sitecustomize` (у conda
#: он добавляет каталоги пакетов), иначе подмена меняла бы окружение прогона.
GUARD_SITECUSTOMIZE = r'''
import atexit, json, os, sys
_DIR = os.environ.get("SPA_NOREG_GUARD_REPORT_DIR")
_ROOTS = [os.path.realpath(r) for r in os.environ.get("SPA_NOREG_GUARD_ROOTS", "").split(os.pathsep) if r]
_refused, _reads, _children, _secrets = [], [0], [], [0]
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

def _real(path):
    if isinstance(path, int) or path is None:
        return None
    try:
        path = os.fsdecode(path)
    except TypeError:
        return None
    path = os.path.abspath(path)
    head, tail = path, []
    while head and not os.path.exists(head):
        head, t = os.path.split(head)
        if not t:
            break
        tail.append(t)
    return os.path.join(os.path.realpath(head), *reversed(tail))

def _guarded(path):
    real = _real(path)
    return real if real and any(real == r or real.startswith(r + os.sep) for r in _ROOTS) else None

def _refuse(event, real):
    _refused.append({"event": event, "path": real})
    raise PermissionError(f"no_regression isolation: запись в охраняемый корень запрещена ({event}: {real})")

_PATH_EVENTS = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 1, "os.chmod": 1, "os.chown": 1,
                "os.truncate": 1, "os.utime": 1, "shutil.rmtree": 1, "os.symlink": 2, "os.link": 2}

def _hook(event, args):
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        real = _guarded(path)
        if real is None:
            return
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                  (isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing:
            _refuse(event, real)
        _reads[0] += 1
    elif event == "os.rename":
        for p in args[:2]:
            real = _guarded(p)
            if real:
                _refuse(event, real)
    elif event in _PATH_EVENTS:
        real = _guarded(args[_PATH_EVENTS[event] - 1])
        if real:
            _refuse(event, real)
    elif event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"):
        exe, argv = (list(args) + [None, None])[:2]
        name = os.path.basename(os.fsdecode(exe)) if isinstance(exe, (str, bytes)) else str(exe)[:80]
        if name == "security":
            # Связка ключей хоста — не вход прогона: тест, которому нужен секрет, обязан
            # подать его сам. Запуск запрещается ДО чтения, попытка считается.
            _secrets[0] += 1
            raise PermissionError("no_regression isolation: связка ключей хоста закрыта для прогона")
        try:
            head = [os.fsdecode(a)[:40] for a in list(argv or [])[1:3]]
        except TypeError:
            head = []
        _children.append(" ".join([name] + head))

if _ROOTS and _DIR:
    sys.addaudithook(_hook)

def _dump():
    if not _DIR:
        return
    tmp = os.path.join(_DIR, f".{os.getpid()}.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "installed": bool(_ROOTS and _DIR), "roots": _ROOTS,
                   "argv0": os.path.basename(sys.argv[0]) if sys.argv else "",
                   "pytest": any("pytest" in a for a in sys.argv[:1]) or "pytest" in sys.modules,
                   "refused": _refused, "live_reads": _reads[0], "keychain_refused": _secrets[0],
                   "children": sorted(set(_children))}, fh)
    os.replace(tmp, os.path.join(_DIR, f"{os.getpid()}.json"))

atexit.register(_dump)

_here = os.path.dirname(os.path.abspath(__file__))
for _p in sys.path:
    if _p and os.path.abspath(_p) != _here and os.path.exists(os.path.join(_p, "sitecustomize.py")):
        exec(compile(open(os.path.join(_p, "sitecustomize.py"), encoding="utf-8").read(),
                     os.path.join(_p, "sitecustomize.py"), "exec"))
        break
'''


def default_protected_roots(repo_root: Path) -> list[Path]:
    """Боевой корень — охраняемый, если прогон идёт НЕ в нём (в нём прогон отказан раньше)."""
    from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
    live = Path(DEFAULT_LIVE_ROOT).resolve()
    run = Path(repo_root).resolve()
    if run == live or live in run.parents:
        return []
    return [live]


def isolated_env(base: dict, repo_root: Path, roots: list[Path], scratch: Path) -> dict:
    """Окружение потомка: живое состояние — в дереве прогона, сторож записи — в каждом Python."""
    site = scratch / "guard_site"
    reports = scratch / "guard_reports"
    site.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    (site / "sitecustomize.py").write_text(GUARD_SITECUSTOMIZE, encoding="utf-8")
    env = {k: v for k, v in base.items() if k not in ISOLATION_ENV_DROP}
    prior = env.get("PYTHONPATH")
    env.update(RUN_ENV)
    env.update({"PYTHONPATH": os.pathsep.join([str(site)] + ([prior] if prior else [])),
                "SPA_DATA_DIR": str(Path(repo_root) / "data"),
                "SPA_LIVE_ROOT": str(repo_root),
                GUARD_REPORT_ENV: str(reports),
                GUARD_ROOTS_ENV: os.pathsep.join(str(r) for r in roots)})
    return env


def judge_isolation(scratch: Path, roots: list[Path]) -> dict:
    """Отчёты НАБЛЮДАТЕЛЯ Python → его вердикт. Отказ записи или нет отчёта pytest ⇒ NotMeasured.

    Это не доказательство изоляции: наблюдатель не видит sqlite, не-Python потомков и `dir_fd`,
    и наличие отчёта КАЖДОГО Python-потомка не проверяется (требуется только процесс pytest).
    Запрет записи держит граница Seatbelt (`verify_write_boundary`)."""
    reports = []
    for f in sorted((scratch / "guard_reports").glob("*.json")):
        try:
            reports.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise NotMeasured(f"отчёт сторожа записи {f.name} не прочитан: "
                              f"{type(exc).__name__}: {exc} — наблюдение записи не состоялось") from exc
    want = sorted(str(Path(r).resolve()) for r in roots)
    main = [r for r in reports if r.get("pytest") and r.get("installed")
            and sorted(r.get("roots") or []) == want]
    if not main:
        raise NotMeasured(f"сторож записи не отчитался из процесса pytest ({len(reports)} "
                          f"отчёт(ов) всего) — наблюдение записи под {want} не состоялось, вердикт не выносится")
    refused = [dict(x, pid=r["pid"]) for r in reports for x in r.get("refused") or []]
    out = {"protected_roots": want, "guard_processes": len(reports),
           "refused_writes": len(refused),
           "live_reads": sum(int(r.get("live_reads") or 0) for r in reports),
           "keychain_refused": sum(int(r.get("keychain_refused") or 0) for r in reports),
           "unaudited_children": sorted({c for r in reports for c in r.get("children") or []})}
    if refused:
        raise NotMeasured(f"попытка записи в охраняемый корень: {len(refused)} попыт(ка/ок) "
                          f"отказано, первые: {refused[:3]} — прогон не есть "
                          f"проверка кандидата, живой отчёт не трогается")
    return out


#: Рабочий запуск (живой корень = боевое дерево) заблокирован: граница Seatbelt закрывает
#: прямую запись дерева процессов, но не запись, делегированную системному демону по IPC.
#: Условие снятия — решение ARB/владельца о достаточности границы (или прогон под отдельным
#: пользователем ОС без права записи в боевое дерево) и ADR; снимается правкой кода, а не флагом.
PRODUCTION_RUN_BLOCKED = (
    "рабочий запуск против боевого дерева ЗАБЛОКИРОВАН: граница записи — Seatbelt "
    "(прямая запись дерева процессов), запись через системные демоны по IPC не закрыта, "
    "полная изоляция не доказана; условие — решение ARB/владельца + ADR")

_BOUNDARY_PROBE = r'''
import os, sqlite3, subprocess, sys
P = sys.argv[1]
def t(fn):
    try:
        fn(); return "written"
    except Exception:
        return "refused"
def a():
    c = sqlite3.connect(os.path.join(P, "probe.sqlite")); c.execute("CREATE TABLE t(x)"); c.commit()
def b():
    subprocess.run(["/bin/sh", "-c", 'printf changed > "$1"', "probe", os.path.join(P, "sentinel")], check=True)
def c():
    fd = os.open(P, os.O_RDONLY)
    f = os.open("sentinel", os.O_WRONLY | os.O_TRUNC, dir_fd=fd); os.write(f, b"changed")
def d():
    open(os.path.join(P, "py.txt"), "w").write("x")
def outside():
    open(sys.argv[2], "w").write("x")
print("|".join([t(a), t(b), t(c), t(d), t(outside)]))
'''


def boundary_profile(roots: list[Path]) -> str:
    """Профиль Seatbelt: всё разрешено, кроме записи под охраняемыми корнями (realpath)."""
    rules = []
    for r in roots:
        real = os.path.realpath(str(r))
        if any(ch in real for ch in '"\\\n'):
            raise NotMeasured(f"путь охраняемого корня непригоден для профиля: {real!r}")
        rules.append(f'(deny file-write* (subpath "{real}"))')
    return "(version 1)(allow default)" + "".join(rules)


def verify_write_boundary(*, sandbox_exec: str = "/usr/bin/sandbox-exec") -> dict:
    """Самопроверка ГРАНИЦЫ на временной сцене ДО прогона — теми же классами, что прошли
    мимо Python-наблюдателя (sqlite, shell-потомок, dir_fd) + обычная запись Python, и
    положительный контроль: запись ВНЕ корня обязана пройти (иначе профиль запрещает всё и
    прогон ничего не мерит). Любое отклонение ⇒ NotMeasured, тесты не запускаются."""
    import shutil
    import tempfile
    if not os.path.exists(sandbox_exec):
        raise NotMeasured(f"граница записи не обеспечена: нет {sandbox_exec} — прогон не начат")
    scene = Path(tempfile.mkdtemp(prefix="noreg_boundary_"))
    try:
        prot = scene / "protected"
        prot.mkdir()
        (prot / "sentinel").write_text("orig", encoding="utf-8")
        outside = scene / "outside.txt"
        probe = scene / "probe.py"
        probe.write_text(_BOUNDARY_PROBE, encoding="utf-8")
        try:
            # Popen, а не run/check_output: зов прогона населения и зов самопроверки — разные
            # двери, и подмена одной (тестом) не должна молча подменять другую.
            with subprocess.Popen(
                    [sandbox_exec, "-p", boundary_profile([prot]), sys.executable, str(probe),
                     os.path.realpath(prot), str(outside)], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True) as proc:
                out, err = proc.communicate(timeout=60)
            if proc.returncode != 0:
                # Например `sandbox_apply: Operation not permitted` (код 71) — среда не даёт
                # применить профиль (вложенная песочница). Граница не обеспечена ⇒ отказ.
                raise NotMeasured(f"граница записи не обеспечена: зонд границы вышел с кодом "
                                  f"{proc.returncode} ({(err or '').strip()[:200]}) — прогон не начат")
        except (OSError, subprocess.SubprocessError) as exc:
            raise NotMeasured(f"самопроверка границы записи не выполнена: "
                              f"{type(exc).__name__}: {exc} — прогон не начат") from exc
        got = dict(zip(("sqlite", "shell_child", "dir_fd", "python_open", "outside"),
                       out.strip().split("|")))
        intact = (prot / "sentinel").read_text(encoding="utf-8") == "orig" and \
            not (prot / "probe.sqlite").exists() and not (prot / "py.txt").exists()
        ok = intact and got.get("outside") == "written" and all(
            got.get(k) == "refused" for k in ("sqlite", "shell_child", "dir_fd", "python_open"))
        if not ok:
            raise NotMeasured(f"граница записи не держит на сцене: {got}, корень цел={intact} "
                              f"— прогон не начат")
        return {"mechanism": "seatbelt deny file-write*", "probes": got,
                "not_covered": ["запись через системные демоны по IPC", "сеть"]}
    finally:
        shutil.rmtree(scene, ignore_errors=True)


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


class SeatbeltBoundary:
    """НАСТОЯЩАЯ граница записи: самопроверка на сцене + обёртка команды профилем Seatbelt.
    Нет sandbox-exec (Linux) или среда не даёт применить профиль ⇒ `verify` отказывает."""

    def __init__(self, sandbox_exec: str = "/usr/bin/sandbox-exec") -> None:
        self.sandbox_exec = sandbox_exec

    def verify(self) -> dict:
        return dict(verify_write_boundary(sandbox_exec=self.sandbox_exec), proves_isolation=False)

    def wrap(self, cmd: list, roots: list) -> list:
        return [self.sandbox_exec, "-p", boundary_profile(roots), *cmd]


def default_boundary():
    """Граница прогона по умолчанию — настоящая. Тест протокола вправе подать свою, но её
    отметка `mechanism` попадает в отчёт, и подмена никогда не выдаётся за изоляцию."""
    return SeatbeltBoundary()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def artifact_age_hours(repo_root: Path, *, now: datetime | None = None) -> tuple[float | None, str]:
    """Возраст действующего отчёта переписи в часах и ПОЧЕМУ он таков.

    ``None`` — возраст НЕ ИЗМЕРЕН (файла нет, не разобран, нет отметки времени).
    Это не «ноль часов» и не «старый»: третий исход у возраста тоже свой.
    """
    from spa_core.monitoring import no_regression_census as census

    path = repo_root / census.REPORT_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"отчёта переписи нет: {type(exc).__name__}: {exc}"
    except ValueError as exc:
        return None, f"отчёт переписи не разобран: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, "отчёт переписи не словарь"
    stamp = doc.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, f"у отчёта нет читаемой отметки времени (generated_at={stamp!r})"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    return age, (f"возраст действующего отчёта {age:.1f}ч, вердикт "
                 f"{doc.get('verdict')!r}, измерено={doc.get('measured')!r}")


def population_files(repo_root: Path) -> list[str]:
    """Файлы населения трёх объявленных поверхностей — одной копией у переписи.

    Считает НЕ этот скрипт: своя копия правила принадлежности разошлась бы с
    переписью при первой же правке и дала бы два разных населения у одного
    критерия (класс ADR-522).
    """
    from spa_core.monitoring import no_regression_census as census

    pop = census.population(str(repo_root))
    if pop["roots_absent"]:
        raise NotMeasured("каталог(и) предписанного прогона не найдены: "
                          + ", ".join(pop["roots_absent"]))
    if pop["unparsed"]:
        raise NotMeasured(f"{len(pop['unparsed'])} тест-файл(ов) не разобран(ы): "
                          + ", ".join(u["file"] for u in pop["unparsed"][:5])
                          + " — принадлежность НЕИЗВЕСТНА")
    empty = [name for name, s in pop["surfaces"].items() if not s["files"]]
    if empty:
        raise NotMeasured("население поверхност(и/ей) ПУСТО: " + ", ".join(empty))
    files: list[str] = []
    for surface in pop["surfaces"].values():
        for rel in surface["files"]:
            if rel not in files:
                files.append(rel)
    return files


def _refuse_if_prod_tree(repo_root: Path, *, allow: bool) -> None:
    """Прогон тестов в БОЕВОМ дереве запрещён, и отказ громкий.

    Тесты населения пишут в `data/` того дерева, из которого запущены, а в боевом
    дереве `data/` — это состояние, а не мусор (`.claude/rules/deployment.md` п. 4,
    авария 2026-08-24: 116 файлов откатились на три недели). Поэтому вопрос
    задаётся ДО запуска и ответ на него — отказ, а не предупреждение.
    """
    if allow:
        return
    try:
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
    except Exception as exc:  # noqa: BLE001 — нечем спросить ≠ «можно»
        raise NotMeasured(f"не удалось узнать путь боевого дерева: "
                          f"{type(exc).__name__}: {exc} — прогон НЕ начат") from exc
    try:
        same = repo_root.resolve() == Path(DEFAULT_LIVE_ROOT).resolve()
    except OSError as exc:
        raise NotMeasured(f"путь дерева не разрешился: {type(exc).__name__}: {exc}") from exc
    if same:
        raise NotMeasured(
            f"дерево {repo_root} — БОЕВОЕ ({DEFAULT_LIVE_ROOT}). Тесты населения пишут "
            f"в `data/` своего дерева, а в боевом `data/` — живое состояние "
            f"(.claude/rules/deployment.md п. 4). Гонять население надо из одноразового "
            f"worktree; осознанный обход — --allow-prod-tree")


def run_population(repo_root: Path, files: list[str], record: Path,
                   *, timeout_s: float | None = None,
                   protected_roots: list[Path] | None = None,
                   write_boundary=None) -> dict:
    """Прогнать РОВНО население и оставить junit-запись на хосте.

    Возвращает словарь наблюдений о прогоне (код возврата, число случаев в
    записи, хвост вывода, вердикт изоляции). Запись-пустышка и отсутствие записи —
    третий исход: :class:`NotMeasured`, а не «ноль поломок». Так же — нарушенная или
    недоказанная изоляция от охраняемого корня (`judge_isolation`).

    junit пишет ПОТОМОК в каталог прогона (охраняемый корень ему закрыт), в хранилище
    запись переносит этот процесс — уже после вердикта изоляции.
    """
    import shutil
    import tempfile
    roots = (default_protected_roots(repo_root) if protected_roots is None
             else [Path(r) for r in protected_roots])
    scratch = Path(tempfile.mkdtemp(prefix=".noreg_isolation_", dir=str(repo_root)))
    staged = scratch / record.name
    cmd = [sys.executable, "-m", "pytest", *files,
           "-q", "--tb=no", "-p", "no:randomly", f"--junitxml={staged}"]
    env = isolated_env(dict(os.environ), repo_root, roots, scratch) if roots else \
        {**os.environ, **RUN_ENV}
    try:
        boundary = None
        if roots:
            # Граница ДО тестов: не держит на сцене ⇒ тесты не запускаются вовсе.
            gate = write_boundary if write_boundary is not None else default_boundary()
            boundary = gate.verify()
            cmd = gate.wrap(cmd, roots)
        try:
            proc = subprocess.run(cmd, cwd=str(repo_root), env=env, timeout=timeout_s,
                                  capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise NotMeasured(f"pytest не запущен: {type(exc).__name__}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise NotMeasured(f"прогон населения снят по сроку {timeout_s}с — вердикта нет "
                              f"ни у одного члена: {exc}") from exc
        tail = "\n".join((proc.stdout or "").strip().splitlines()[-6:])
        if not staged.exists():
            raise NotMeasured(
                f"pytest вышел с кодом {proc.returncode}, а junit-записи нет: {staged}. "
                f"Так выглядит снятая сессия (ADR-474: --timeout-method=thread зовёт "
                f"os._exit(1)), и это НЕ «все прошли». Хвост вывода: {tail!r}")
        try:
            cases = len(list(ET.parse(staged).getroot().iter("testcase")))
        except (OSError, ET.ParseError) as exc:
            raise NotMeasured(f"junit-запись не разобрана: {type(exc).__name__}: {exc}") from exc
        if cases == 0:
            raise NotMeasured(f"в junit-записи {staged} ноль случаев — прогон не дал исхода "
                              f"ни одному члену населения (код pytest {proc.returncode})")
        isolation = (dict(judge_isolation(scratch, roots), boundary=boundary,
                          full_isolation_proven=False) if roots else
                     {"protected_roots": [], "reason": "прогон в самом охраняемом корне "
                      "(осознанный обход --allow-prod-tree) — изоляции нет и она не заявляется"})
        record.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, record)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"returncode": proc.returncode, "cases_in_record": cases,
            "record": str(record), "tail": tail, "files_requested": len(files),
            "isolation": isolation}


def refresh(repo_root: Path, *, if_due: bool = False, max_age_h: float = DEFAULT_MAX_AGE_H,
            junit: list[str] | None = None, allow_prod_tree: bool = False,
            write: bool = True, timeout_s: float | None = None,
            records_root: Path | None = None,
            now: datetime | None = None,
            protected_roots: list[Path] | None = None) -> dict:
    """Обновить отчёт переписи, произведя запись прогона, и вернуть наблюдения."""
    from spa_core.monitoring import no_regression_census as census

    age, why_age = artifact_age_hours(repo_root, now=now)
    out: dict = {"repo_root": str(repo_root), "artifact_age_h": age, "age_reason": why_age,
                 "max_age_h": max_age_h, "ran": False,
                 # Обход отказа «дерево боевое» обязан быть ВИДЕН читателю отчёта: молчаливый
                 # обход превращает отказ в украшение.
                 "allow_prod_tree": bool(allow_prod_tree)}

    head = _tree_head(repo_root)
    prior_sha = None
    if age is not None:
        try:
            prior_sha = report_sha(json.loads((repo_root / census.REPORT_REL).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            prior_sha = None
    out["tree_head"], out["prior_sha"] = head, prior_sha
    # «Не срок» — только когда прежний отчёт о ТЕКУЩЕМ коммите этого дерева; неизвестный коммит
    # (дерево без git, отчёт без отметки) — это срок, а не свежесть.
    if if_due and age is not None and age <= max_age_h and head is not None and prior_sha == head:
        # Не срок. Вердикт берётся у ДЕЙСТВУЮЩЕГО отчёта, и его возраст называется
        # вслух: иначе «0» читалось бы как «я только что померил».
        try:
            doc = json.loads((repo_root / census.REPORT_REL).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # отчёт исчез между замером и чтением
            raise NotMeasured(f"возраст отчёта измерен, а сам отчёт не прочитан: "
                              f"{type(exc).__name__}: {exc}") from exc
        out.update({"due": False, "report": doc, "source": "прежний отчёт"})
        return out
    out["due"] = True

    if junit:
        out["source"] = "запись подана входом"
        paths = list(junit)
    else:
        _refuse_if_prod_tree(repo_root, allow=allow_prod_tree)
        files = population_files(repo_root)
        keep_in = Path(records_root) if records_root is not None else DEFAULT_RECORDS_ROOT
        record = keep_in / RECORDS_REL / f"{_stamp()}.xml"
        out["records_root"] = str(keep_in)
        out["run"] = run_population(repo_root, files, record, timeout_s=timeout_s,
                                    protected_roots=protected_roots)
        out["ran"] = True
        out["source"] = f"прогон населения ({len(files)} файл(ов)) на этом хосте"
        paths = [str(record)]

    report = census.measure(str(repo_root), junit_paths=paths)
    out["report"] = report
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(repo_root / census.REPORT_REL))
        out["written"] = str(repo_root / census.REPORT_REL)
    return out


#: Метка, которой отчёт помечает запуск ПО РАСПИСАНИЮ (а не рукой). Агент launchd
#: `com.spa.no_regression_census` ПОДГОТОВЛЕН (`launchd/…plist`, `scripts/agent_no_regression_census.sh`),
#: но НЕ установлен: установщик ставит агентов явными строками, строки для этого нет, а
#: в конституции у артефакта по-прежнему `producer: null` — включение есть отдельное
#: действие через гейт деплоя (`.claude/rules/deployment.md`).
SCHEDULED_PRODUCER = "com.spa.no_regression_census"

#: Статус производителя — ПОДГОТОВЛЕН, не работает в production. Различие видно в самом отчёте:
#: production-запуск несёт `invoked_by.env.via == "launchd:com.spa.no_regression_census"`
#: (ставит только обёртка агента); любой другой — "manual".
#:
#: Подключение (отдельное действие через гейт деплоя, НЕ в этой ветке):
#:   1. доставить код на origin и дождаться синхронизации прод-дерева;
#:   2. `scripts/check_agent_before_deploy.sh no_regression_census` (агент НЕ долгожитель —
#:      пробный прогон допустим), затем `launchctl bootstrap` plist из `launchd/`;
#:   3. строка в `scripts/install_all_agents.sh` и `producer: com.spa.no_regression_census`
#:      у `data/no_regression_census.json` в `architecture/manifest.json`.
#: Приёмка: первый запуск агента дал отчёт с `invoked_by.env.via` = launchd и `sha` = текущий
#:   origin/main; `deployment_acceptance` до и после — 0; проба `no_regression_tests_pass`
#:   отвечает по ЭТОМУ отчёту; в `data/records/no_regression/` лежит junit-запись прогона.
#: Откат: `launchctl bootout gui/$UID/com.spa.no_regression_census`, вернуть `producer: null`;
#:   отчёт и записи НЕ удалять — они история измерений.


def _git(live_root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(live_root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise NotMeasured(f"git {' '.join(args)} в {live_root}: код {proc.returncode} — "
                          f"{(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout.strip()


def snapshot_commit(live_root: Path, sha: str, dest: Path) -> int:
    """Снимок ТОЧНОГО коммита в `dest` — клоном, у которого есть `.git`. Возвращает число файлов.

    Прежде снимок делался `git archive`: в нём нет `.git`, и тесты, спрашивающие git о
    своём дереве (`git ls-files`), падали «not a git repository» — ложная поломка, которой
    в CI нет (там checkout с `.git`; замер 22.10, `test_halt_state_survives_tree_restore`).
    Не worktree и не checkout в боевом дереве: те пишут в его `.git`. `clone --shared`
    читает объекты источника через alternates и пишет ТОЛЬКО в `dest`.
    """
    def git(*args, cwd=None):
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise NotMeasured(f"git {' '.join(args[:3])}: код {proc.returncode} — "
                              f"{(proc.stderr or '').strip()[:300]}")
        return proc.stdout
    git("clone", "--quiet", "--shared", "--no-checkout", str(live_root), str(dest))
    git("-C", str(dest), "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", sha)
    head = git("-C", str(dest), "rev-parse", "HEAD").strip()
    if head != sha:
        raise NotMeasured(f"снимок указывает на {head[:12]}, а заказан {sha[:12]}")
    n = len([f for f in git("-C", str(dest), "ls-files", "-z").split("\0") if f])
    if n == 0:
        raise NotMeasured(f"снимок {sha} пуст — прогонять нечего")
    return n


#: Кто зовёт производителя. Только обёртка агента ставит это значение; ручной запуск
#: `--scheduled` записывается как ручной — «подготовлен» и «работает в production» различимы
#: по самому отчёту, а не по тому, что про него написано.
VIA_ENV = "SPA_NO_REGRESSION_VIA"


def run_environment() -> dict:
    """Окружение, в котором получен вердикт: без него «тот же код» ничего не доказывает."""
    import platform
    try:
        from importlib.metadata import version
        pytest_version = version("pytest")
    except Exception:  # noqa: BLE001 — неизвестная версия названа, а не выдумана
        pytest_version = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": platform.platform(), "pytest": pytest_version, "run_env": dict(RUN_ENV),
            "via": os.environ.get(VIA_ENV) or "manual"}


def report_sha(doc: dict) -> str | None:
    """Какой коммит проверял отчёт: `invoked_by.sha` (снимок) либо `repo_head` переписи."""
    inv = doc.get("invoked_by") if isinstance(doc.get("invoked_by"), dict) else {}
    sha = inv.get("sha") or doc.get("repo_head")
    return str(sha) if sha else None


def _tree_head(repo_root: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


#: Канонический трек — тот же файл, чей хеш сверяет пред-деплойный гейт.
TRACK_REL = Path("data") / "equity_curve_daily.json"


def track_fingerprint(live_root: Path) -> str:
    """sha256 канонического трека; файла нет — так и названо (а не пустая строка)."""
    import hashlib
    try:
        return hashlib.sha256((Path(live_root) / TRACK_REL).read_bytes()).hexdigest()
    except FileNotFoundError:
        return "absent"


def _record_refusal(records_root: Path, payload: dict) -> Path:
    """След отказа рядом с записями прогона: причина не исчезает вместе с процессом."""
    from spa_core.utils.atomic import atomic_save
    target = Path(records_root) / RECORDS_REL / f"{_stamp()}.refusal.json"
    atomic_save(payload, str(target))
    return target


def scheduled(live_root: Path, *, ref: str = "origin/main", max_age_h: float = DEFAULT_MAX_AGE_H,
              timeout_s: float | None = None, now: datetime | None = None,
              refresh_fn=None, workdir: Path | None = None) -> dict:
    """Запуск ПО РАСПИСАНИЮ: прогон в снимке коммита, отчёт — в живой `data/`.

    Порядок: (1) возраст живого отчёта — не срок ⇒ ничего не делать; (2) `ref` →
    точный SHA; (3) снимок этого SHA во временный каталог вне боевого дерева;
    (4) `refresh` в снимке (`write=False`, запись прогона хранится в `live_root`);
    (5) отчёт атомарно — в `live_root/data/`, с пометкой ``invoked_by`` (кто, какой SHA);
    (6) временный каталог снимка — удалить (он создан здесь и больше никому не нужен).
    Любой отказ — :class:`NotMeasured`, и живой отчёт при этом НЕ трогается.
    """
    import shutil
    import tempfile
    from spa_core.monitoring import no_regression_census as census
    from spa_core.utils.atomic import atomic_save

    live_root = Path(live_root)
    sha = _git(live_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    age, why_age = artifact_age_hours(live_root, now=now)
    out: dict = {"mode": "scheduled", "live_root": str(live_root), "artifact_age_h": age,
                 "age_reason": why_age, "max_age_h": max_age_h, "ran": False, "sha": sha}
    prior = None
    if age is not None:
        prior = json.loads((live_root / census.REPORT_REL).read_text(encoding="utf-8"))
    prior_sha = report_sha(prior) if isinstance(prior, dict) else None
    out["prior_sha"] = prior_sha
    # «Не срок» — только про ТОТ ЖЕ коммит: свежий отчёт о другом коде не проверка этого кода.
    if age is not None and age <= max_age_h and prior_sha == sha:
        out.update({"due": False, "source": f"прежний отчёт о том же коммите {sha[:12]}",
                    "report": prior})
        return out
    out["due"] = True
    out["due_reason"] = ("отчёта нет или он не читается" if age is None else
                         f"отчёт старше {max_age_h:.0f}ч" if age > max_age_h else
                         f"отчёт о другом коммите ({(prior_sha or 'неизвестно')[:12]} ≠ {sha[:12]})")
    from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
    if live_root.resolve() == Path(DEFAULT_LIVE_ROOT).resolve():
        raise NotMeasured(PRODUCTION_RUN_BLOCKED)
    env = run_environment()
    tmp = Path(tempfile.mkdtemp(prefix="spa_no_regression_", dir=str(workdir) if workdir else None))
    try:
        try:
            out["snapshot_files"] = snapshot_commit(live_root, sha, tmp)
            track_before = track_fingerprint(live_root)
            # Охраняется и боевой корень по умолчанию, и тот, куда ляжет отчёт: снимку
            # писать нельзя ни туда, ни туда — отчёт и запись кладёт этот процесс.
            roots = default_protected_roots(tmp)
            if live_root.resolve() not in roots:
                roots.append(live_root.resolve())
            res = (refresh_fn or refresh)(tmp, if_due=False, write=False, timeout_s=timeout_s,
                                          records_root=live_root, now=now,
                                          protected_roots=roots)
            track_after = track_fingerprint(live_root)
            if track_before != track_after:
                # Сверка ОДНОГО файла (как у check_agent_before_deploy.sh): сдвиг трека за
                # время прогона — отказ. Это не запрет и не охват прочих файлов.
                raise NotMeasured(f"канонический трек {TRACK_REL} изменился за время прогона "
                                  f"({track_before} → {track_after}) — замер не принят")
        except NotMeasured as exc:
            out["refusal_record"] = str(_record_refusal(live_root, {
                "stamp": _stamp(), "ref": ref, "sha": sha, "env": env, "reason": str(exc),
                "live_report_untouched": True}))
            raise
        report = dict(res["report"])
        report["invoked_by"] = {"entry": "scheduled", "producer": SCHEDULED_PRODUCER,
                                "ref": ref, "sha": sha, "tree": "git clone --shared snapshot",
                                "env": env,
                                "isolation": (res.get("run") or {}).get("isolation")}
        target = live_root / census.REPORT_REL
        atomic_save(report, str(target))
        out.update({"ran": res.get("ran", False), "run": res.get("run"), "report": report,
                    "source": f"снимок {sha[:12]} ({ref})", "written": str(target), "sha": sha})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


#: Вход «из CI» (решение ARB 23.10): вердикт §49 берётся у junit-записей УЖЕ
#: выполненного контрольного прогона `ci-control.yml`, pytest на этом хосте НЕ
#: запускается вовсе. Поэтому `PRODUCTION_RUN_BLOCKED` к этому входу не относится:
#: он запрещает гнать тесты против боевого дерева, а здесь тестов нет. Что вход
#: делает с хостом: (1) `git clone --shared` точного коммита во временный каталог
#: (читает объекты источника, пишет только во временный каталог) — дерево нужно
#: переписи, чтобы посчитать население и разрешить `classname` записи в файлы;
#: (2) скачивает артефакты прогона во временный каталог; (3) пишет отчёт АТОМАРНО
#: в `--out-root`/data ТОЛЬКО при успехе, а отказ — отдельным файлом рядом с
#: записями (`*.refusal.json`), и прежний отчёт при отказе цел.
#:
#: «Подготовлен» и «работает в production» различимы по самому отчёту:
#: `invoked_by.entry == "ci_record"` и `invoked_by.env.via` — "manual" у ручного
#: запуска и метка агента у запуска обёрткой (`SPA_NO_REGRESSION_VIA`). На
#: 23.10 вызывающего в production НЕТ: агент `com.spa.no_regression_census` не
#: установлен, и его обёртка зовёт `--scheduled`, а не `--from-ci`.
CI_ENTRY = "ci_record"


class RevisionUnpinned(NotMeasured):
    """Ревизия S у сервера НЕ закреплена — НЕ ИЗМЕРЕНО; подстановки кэша или предка нет."""

    code = "revision_unpinned"


def pin_revision(live_root: Path, ref: str, work: Path) -> tuple[dict, Path]:
    """Закрепить S = вершину ``ref`` У СЕРВЕРА, не записав НИЧЕГО в ``live_root``.

    Решение ARB 23.10 (этап 8, п. 4). ``server_ref.pin_server_ref`` при нехватке
    объекта делает ``git fetch`` в ПЕРЕДАННЫЙ репозиторий — то есть пишет в его
    ``.git`` (объекты, ``FETCH_HEAD``, remote-tracking ссылку). Боевое дерево и
    зеркало под видом «только чтения» так трогать нельзя. Поэтому механизм
    закрепления зовётся у ВРЕМЕННОГО bare-клона ``work/pin.git``:
    ``git clone --bare --shared`` читает объекты источника через alternates и
    пишет только в ``work``; адрес удалённого берётся у источника
    (``remote get-url`` — чтение), недостающий объект добирается fetch'ем во
    временный клон. Из ``live_root`` читаются только конфиг и объекты.

    Возврат — (описание ревизии, путь клона, из которого снимается снимок S).
    Отказ — :class:`RevisionUnpinned` с причиной (сеть, нет удалённого, ref не
    remote-tracking, объект не добирается).
    """
    from spa_core.utils import server_ref

    split = server_ref.split_remote_ref(str(live_root), ref)
    if isinstance(split, tuple) and split[0] is None:
        raise RevisionUnpinned(f"ref {ref!r} не классифицирован: {split[1]}")
    if split is None:
        raise RevisionUnpinned(f"ref {ref!r} — не ветка удалённого: S выбирает СЕРВЕР; "
                               f"локальная ссылка или sha — только явным --sha")
    remote, branch = split
    try:
        url = _git(live_root, "remote", "get-url", remote)
    except NotMeasured as exc:
        raise RevisionUnpinned(f"адрес удалённого {remote!r} не прочитан: {exc}") from exc
    pin = Path(work) / "pin.git"
    for args in (["clone", "--quiet", "--bare", "--shared", str(live_root), str(pin)],
                 ["-C", str(pin), "remote", "remove", "origin"],
                 ["-C", str(pin), "remote", "add", remote, url]):
        proc = subprocess.run(["git", *args], capture_output=True, text=True)
        if proc.returncode != 0 and not (args[3:4] == ["remove"]):
            raise RevisionUnpinned(f"временный клон закрепления: git {' '.join(args[:3])}: "
                                   f"код {proc.returncode} — {(proc.stderr or '').strip()[:300]}")
    pinned = server_ref.pin_server_ref(str(pin), f"{remote}/{branch}")
    if not pinned.sha or pinned.source != "server":
        raise RevisionUnpinned(f"вершина {remote}/{branch} у сервера не закреплена: "
                               f"{pinned.reason}")
    return ({"source": "server", "ref": ref, "remote": remote, "branch": branch,
             "url": url, "sha": pinned.sha, "observed_at": pinned.observed_at,
             "pinned_in": "временный bare-клон (--shared); источник только читается"}, pin)


def instrument_revision() -> dict:
    """Версия ПРИБОРА — дерево, из которого собран отчёт (не код под проверкой)."""
    from spa_core.monitoring import no_regression_census as census
    rev = census.tree_revision(str(ROOT))
    return {"path": str(ROOT), "sha": rev.get("sha"), "clean": rev.get("clean"),
            "reason": rev.get("reason") or ""}


def _reusable_prior(prior: dict | None, *, run_id, expected: str, now: datetime | None,
                    max_age_h: float | None) -> tuple[bool, str]:
    """Можно ли ответить прежним отчётом (``--if-due``) — и почему.

    Повторное использование НЕ обходит ни проверку ревизии, ни свежесть: отчёт
    засчитывается, только если он о ТОМ ЖЕ прогоне, ТОЙ ЖЕ ревизии S (источник,
    ``invoked_by``, ревизия дерева населения) и его запись ещё не старше предела
    — по времени наблюдения (``generated_at`` = начало прогона CI), а не по
    времени файла. Отчёт не переписывается, его отметка не трогается.
    """
    from spa_core.monitoring import no_regression_census as census
    if not prior:
        return False, "прежнего измеренного отчёта нет"
    src = prior.get("source") if isinstance(prior.get("source"), dict) else {}
    inv = prior.get("invoked_by") if isinstance(prior.get("invoked_by"), dict) else {}
    said = census.report_revision(prior)
    if str(src.get("run_id")) != str(run_id):
        return False, f"прежний отчёт о прогоне {src.get('run_id')}, выбран {run_id}"
    if not (src.get("sha") == expected == inv.get("sha") == said.get("sha")):
        return False, f"прежний отчёт не о ревизии {expected[:12]}"
    if said.get("clean") is not True:
        return False, f"прежний отчёт не подтверждает чистое дерево: {said.get('reason')}"
    limit = census.ci_max_age_h() if max_age_h is None else float(max_age_h)
    try:
        made = datetime.fromisoformat(str(prior.get("generated_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False, "у прежнего отчёта нет читаемой отметки наблюдения"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age > limit:
        return False, f"запись прежнего отчёта старше предела ({age:.1f}ч > {limit:.0f}ч)"
    return True, (f"прежний отчёт о прогоне {run_id} и ревизии {expected[:12]}, "
                  f"возраст записи {age:.1f}ч")


def _ci_env() -> dict:
    """Окружение СБОРКИ отчёта (не прогона тестов — тесты шли в CI)."""
    import platform
    return {"python": platform.python_version(), "platform": platform.platform(),
            "via": os.environ.get(VIA_ENV) or "manual"}


def from_ci(live_root: Path, *, out_root: Path, ref: str = "origin/main",
            sha: str | None = None, run_id: int | str | None = None,
            record_dir: Path | None = None, if_due: bool = False,
            now: datetime | None = None, http=None, workdir: Path | None = None,
            max_age_h: float | None = None, decide: bool = False) -> dict:
    """§49 по записи CI → отчёт в ``out_root/data`` (только при успехе).

    ``live_root`` — git-дерево, ИЗ которого снимается коммит (только чтение);
    ``out_root`` — куда ляжет отчёт и след отказа. Они разведены намеренно:
    сборка во временный каталог не обязана трогать боевое дерево вовсе.
    Любой отказ — :class:`NotMeasured` с кодом причины; отчёт ``out_root`` цел.

    ``decide`` (вариант А §49, решение ARB 23.10): после записи отчёта решение
    выносится настоящим ``card_acceptance.run_probe`` о ТОМ ЖЕ чистом снимке S, на
    котором считалось население, с отчётом из ``out_root/data`` (вход
    ``report_dir``). Это утверждение о S — не о ``live_root``, не о
    ``out_root`` и не о текущем main, если их ревизия иная; ``out["decision"]``
    называет все четыре факта раздельно. Файла решение не пишет.
    """
    import shutil
    import tempfile
    from spa_core.monitoring import no_regression_census as census
    from spa_core.utils.atomic import atomic_save

    live_root, out_root = Path(live_root), Path(out_root)
    target = out_root / census.REPORT_REL
    out: dict = {"mode": "from_ci", "live_root": str(live_root), "out_root": str(out_root),
                 "ran": False, "ref": ref}
    env = _ci_env()
    tmp = Path(tempfile.mkdtemp(prefix="spa_s49_ci_", dir=str(workdir) if workdir else None))
    try:
        try:
            snapshot_source = live_root
            if sha:
                out["revision"] = {"source": "explicit", "sha": sha, "ref": None}
                expected = sha
            else:
                # S — вершина у СЕРВЕРА, закреплённая во временном клоне (п. 4 ARB):
                # ни rev-parse кэша, ни fetch в боевое дерево/зеркало.
                out["revision"], snapshot_source = pin_revision(live_root, ref, tmp)
                expected = out["revision"]["sha"]
            out["sha"] = expected
            if record_dir is None:
                if run_id is None:
                    run_id = census.find_ci_run(http or census.GitHubReader(), head_sha=expected,
                                                scheduled_only=True)
                out["run_id"] = run_id
                if if_due:
                    ok, why = _reusable_prior(_prior_ci_report(target), run_id=run_id,
                                              expected=expected, now=now, max_age_h=max_age_h)
                    out["reuse"] = why
                    if ok:
                        out.update({"due": False, "report": _prior_ci_report(target),
                                    "age_reason": why,
                                    "max_age_h": (census.ci_max_age_h() if max_age_h is None
                                                  else float(max_age_h)),
                                    "source": f"прежний отчёт о том же прогоне {run_id}"})
                        return out
                record = census.fetch_ci_record(str(tmp / "record"), run_id=run_id,
                                                http=http, now=now)
            else:
                record = Path(record_dir)
            out["due"] = True
            tree = tmp / "tree"
            out["snapshot_files"] = snapshot_commit(snapshot_source, expected, tree)
            report = census.measure_from_ci_record(str(record), expected_sha=expected,
                                                   repo_root=str(tree), now=now,
                                                   max_age_h=max_age_h,
                                                   expected_run_id=run_id)
        except (census.CIRecordRefused, NotMeasured) as exc:
            code = getattr(exc, "code", "not_measured")
            out["refusal_record"] = str(_record_refusal(out_root, {
                "stamp": _stamp(), "entry": CI_ENTRY, "ref": ref, "sha": out.get("sha"),
                "run_id": out.get("run_id", run_id), "code": code, "reason": str(exc),
                "env": env, "live_report_untouched": True}))
            raise NotMeasured(str(exc)) from exc
        report["invoked_by"] = {"entry": CI_ENTRY, "producer": SCHEDULED_PRODUCER,
                                "ref": ref, "sha": expected,
                                "revision": out["revision"],
                                "instrument": instrument_revision(),
                                "tree": "git clone --shared snapshot (только население)",
                                "tests_ran_on": "github-actions (ci-control.yml)",
                                "source": report["source"], "env": env}
        atomic_save(report, str(target))
        out.update({"report": report, "written": str(target),
                    "source": f"CI-прогон {report['source']['run_id']} о {expected[:12]}"})
        if decide:
            out["decision"] = decide_in_snapshot(tree, target.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def decide_in_snapshot(tree: Path, report_dir: Path) -> dict:
    """Решение §49 о чистом снимке S — через НАСТОЯЩИЙ ``run_probe``, а не прямой вызов."""
    from spa_core.monitoring import card_acceptance as ca
    from spa_core.monitoring import no_regression_census as census
    verdict, detail = ca.run_probe("no_regression_tests_pass", repo_root=str(tree),
                                   report_dir=str(report_dir))
    return {"verdict": verdict, "detail": detail,
            "decision_tree": {"kind": "clone --shared snapshot of S (удаляется после)",
                              "path": str(tree), **census.tree_revision(str(tree))},
            "report_dir": str(report_dir),
            "reached": [k for k in ca.probe_tree_inputs("no_regression_tests_pass")
                        if k in ("repo_root", "report_dir")],
            "scope": "утверждение о ревизии снимка; о боевом дереве, другом checkout и "
                     "текущем main не говорит ничего, если их ревизия иная"}


def _prior_ci_report(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("measured") else None


def prune_records(records_root: Path, keep: int) -> list[str]:
    """Снять все записи, кроме ``keep`` самых свежих. ``keep<=0`` — не снимать ничего.

    Удаление необратимо, поэтому оно НЕ по умолчанию и трогает только файлы
    собственного каталога записей с собственным расширением.
    """
    if keep <= 0:
        return []
    base = Path(records_root) / RECORDS_REL
    if not base.is_dir():
        return []
    found = sorted((p for p in base.glob("*.xml") if p.is_file()),
                   key=lambda p: p.name, reverse=True)
    dropped = []
    for p in found[keep:]:
        p.unlink()
        dropped.append(str(p))
    return dropped


def _lines(out: dict) -> list[str]:
    from spa_core.monitoring import no_regression_census as census

    lines = []
    if out.get("due") is False:
        lines.append(f"не срок: {out['age_reason']} при пределе {out['max_age_h']:.0f}ч — "
                     f"ничего не перезапускалось")
    run = out.get("run")
    if run:
        lines.append(f"[ПРОГОН] населения {run['files_requested']} файл(ов) → "
                     f"{run['cases_in_record']} случа(й/ев) в записи, код pytest "
                     f"{run['returncode']}; запись оставлена на хосте: {run['record']}")
    report = out.get("report") or {}
    lines += census._lines(report) if report else ["отчёта нет"]
    lines.append(f"[ИСТОЧНИК ВЕРДИКТА] {out.get('source')}")
    if out.get("allow_prod_tree"):
        lines.append("[ОБХОД] --allow-prod-tree: отказ «дерево боевое» снят ОСОЗНАННО — "
                     "тесты населения писали в `data/` этого дерева")
    if out.get("written"):
        lines.append(f"[ЗАПИСАНО] {out['written']}")
    dec = out.get("decision")
    if dec:
        tree = dec["decision_tree"]
        lines.append(f"[РЕШЕНИЕ §49 О СНИМКЕ] {dec['verdict']} — дерево {tree['path']} "
                     f"({(tree.get('sha') or '?')[:12]}, чистое={tree.get('clean')}), отчёт "
                     f"{dec['report_dir']}: {dec['detail']}")
        lines.append(f"  {dec['scope']}")
    return lines


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--if-due", action="store_true",
                    help=f"прогонять только если отчёт старше --max-age-h "
                         f"(по умолчанию {DEFAULT_MAX_AGE_H:.0f}ч)")
    ap.add_argument("--max-age-h", type=float, default=DEFAULT_MAX_AGE_H)
    ap.add_argument("--junit", action="append", default=[],
                    help="взять ГОТОВУЮ запись (например выгрузку CI) вместо прогона")
    ap.add_argument("--allow-prod-tree", action="store_true",
                    help="осознанный обход отказа «дерево боевое»")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--records-root", default=None,
                    help=f"каталог ХРАНЕНИЯ записей (умолчание {DEFAULT_RECORDS_ROOT}) — "
                         f"он переживает одноразовое дерево прогона")
    ap.add_argument("--keep", type=int, default=0,
                    help="оставить N самых свежих записей, остальные снять (0 — не снимать)")
    ap.add_argument("--timeout-s", type=float, default=None,
                    help="предел на весь прогон населения; снятие по сроку = НЕ ИЗМЕРЕНО")
    ap.add_argument("--scheduled", action="store_true",
                    help="режим расписания: прогон в снимке `--ref` (git clone --shared), отчёт — в "
                         "`--live-root`/data; такт решает возраст живого отчёта")
    ap.add_argument("--live-root", default=str(DEFAULT_RECORDS_ROOT),
                    help="боевое дерево: откуда снимок и куда отчёт (только с --scheduled)")
    ap.add_argument("--ref", default="origin/main", help="что снимать (--scheduled / --from-ci)")
    ap.add_argument("--from-ci", action="store_true",
                    help="вердикт из junit-записей УЖЕ выполненного ci-control.yml; pytest здесь "
                         "не запускается. Снимок коммита берётся из --live-root, отчёт — в --out-root")
    ap.add_argument("--out-root", default=None,
                    help="куда писать отчёт и след отказа (с --from-ci ОБЯЗАТЕЛЕН: умолчания "
                         "на боевое дерево нет намеренно)")
    ap.add_argument("--sha", default=None, help="проверяемый коммит (умолчание — --ref)")
    ap.add_argument("--ci-run", default=None, help="номер прогона ci-control.yml (умолчание — "
                                                    "последний завершённый о --sha)")
    ap.add_argument("--decide", action="store_true",
                    help="(--from-ci) вынести решение §49 о чистом снимке S той же пробой, "
                         "что и сводка (run_probe, вход report_dir); файла не пишет")
    ap.add_argument("--ci-record-dir", default=None,
                    help="уже скачанная запись прогона (run.json, artifacts.json, артефакты)")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        if args.from_ci:
            if not args.out_root:
                print("критерий §49 `No regression`: НЕ ИЗМЕРЕНО — --from-ci без --out-root: "
                      "куда писать, называет вызывающий")
                return 2
            out = from_ci(Path(args.live_root), out_root=Path(args.out_root), ref=args.ref,
                          sha=args.sha, run_id=args.ci_run, if_due=args.if_due,
                          record_dir=Path(args.ci_record_dir) if args.ci_record_dir else None,
                          decide=args.decide)
        elif args.scheduled:
            out = scheduled(Path(args.live_root), ref=args.ref, max_age_h=args.max_age_h,
                            timeout_s=args.timeout_s)
        else:
            out = refresh(repo_root, if_due=args.if_due, max_age_h=args.max_age_h,
                          junit=args.junit, allow_prod_tree=args.allow_prod_tree,
                          write=not args.no_write, timeout_s=args.timeout_s,
                          records_root=Path(args.records_root) if args.records_root else None)
    except NotMeasured as exc:
        print(f"критерий §49 `No regression`: НЕ ИЗМЕРЕНО — {exc}")
        return 2

    for line in _lines(out):
        print(line)
    for path in prune_records(Path(args.records_root) if args.records_root
                              else DEFAULT_RECORDS_ROOT, args.keep):
        print(f"[СНЯТА ЗАПИСЬ] {path}")

    from spa_core.monitoring import no_regression_census as census
    report = out.get("report") or {}
    if not report.get("measured") or report.get("verdict") == census.UNMEASURED:
        return 2
    return 1 if report.get("verdict") == census.REGRESSION else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
