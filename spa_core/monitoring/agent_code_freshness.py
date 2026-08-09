"""ЧЕТВЁРТЫЙ вопрос: исполняет ли ЖИВОЙ процесс тот код, что лежит в дереве?

Кнопки под алертами (ADR-069) легли в дерево 7 августа, а владелец 8-го всё ещё
видел старый Телеграм. Процесс бота работал с 5 августа и исполнял память,
набранную ДО появления нового кода. `KeepAlive` держит такой процесс живым, сам
он никогда не выходит — значит новый код не попадёт в него НИКОГДА, пока
кто-нибудь не перезапустит.

Ни один сторож этого не сказал, и каждый был прав по-своему:

| вопрос | кто отвечает | что НЕ проверяет |
|---|---|---|
| это тот код, который мы приняли? | `deployment_drift_monitor` | работает ли он |
| способен ли флот стартовать? | `deployment_acceptance` | что уже запущено |
| агенты реально работают? | `agent_health_monitor` | КАКОЙ код в них загружен |
| **исполняет ли живой процесс код из дерева?** | **этот модуль** | всё остальное |

**Честная граница с ADR-077.** По следам той же аварии 08.08 появился
`telegram_health` — он задаёт ЭТОТ ЖЕ вопрос, но ровно про ОДНОГО агента
(`com.spa.telegram_bot`), и умеет его чинить (`kickstart`, предохранитель 3/час).
Здесь другой охват и другой способ: **все** долгожители и **вычисленное** множество
модулей вместо списка руками. Разница не косметическая — замер 09.08: список
`telegram_health.WATCHED_MODULES` содержит 7 файлов, а бот импортирует **47**;
правка в остальных 40 (`telegram/push_policy.py`, `owner_queue/notify.py`,
`utils/live_paths.py` …) для узкого сторожа невидима, он ответит «код свежий».
Модули НЕ заменяют друг друга и намеренно не сведены в один: `telegram_health`
чинит канал связи с владельцем и обязан оставаться быстрым (5 мин) и автономным,
этот — только называет и не трогает ничего.

Для короткоживущих агентов вопрос не нужен: они перезапускаются по расписанию и
подхватывают код сами (плюс `agent_template.sh` синкает дерево перед стартом).
Вопрос существует ровно для ДОЛГОЖИТЕЛЕЙ — `KeepAlive` + вечный цикл, — у которых
ответ «нет» может держаться неделями и выглядеть как норма.

Замер на живом проде 2026-08-09 07:1xZ, первым же прогоном:

| агент | процесс с | новейший импортируемый модуль | разрыв |
|---|---|---|---|
| `com.spa.apiserver` | 17 июля | 4 августа и позже | **> 18 суток** |
| `com.spa.familyfund` | 2 июля | 3 августа и позже | **> 36 суток** |
| `com.spa.telegram_bot` | 9 августа 02:41 | 7 августа | свежий (перезапущен) |

То есть публичный live-API отдавал дашборду числа кодом трёхнедельной давности —
и об этом не говорил никто.

**Сторож НИЧЕГО не перезапускает.** Перезапуск прод-агента — действие владельца
(`.claude/rules/deployment.md`, п. 6); автоматический перезапуск после доставки —
отдельный вопрос владельцу, а не следствие этой проверки. Здесь только слова.

Как измеряется (без догадок):

1. долгожители — `KeepAlive` в plist (любое истинное значение, в т.ч. словарь);
2. живой процесс и время его старта — `launchctl list` + `ps`; берётся python-потомок
   обёртки, если он есть (обёртка запускает python ровно один раз);
3. код, который процесс держит в памяти, — ТРАНЗИТИВНОЕ замыкание импортов от
   точки входа по файлам ЭТОГО репозитория (ast, без выполнения);
4. вердикт — сравнение старта процесса с самым новым mtime в замыкании.

Огрубления названы, а не спрятаны. Замыкание строится статически, поэтому импорт
внутри функции (ленивый) учитывается как обычный — он подгрузится с диска свежим,
и сторож в этом месте склонен ПЕРЕоценить разрыв. Обратной ошибки (промолчать о
настоящем разрыве) статическое замыкание не даёт: всё, что импортируется на старте,
в нём есть.

Порог `STALE_ALERT_HOURS` = 24 ч выбран не «чтобы было тише», а чтобы сторож не
висел жёлтым постоянно: пуши идут ежедневно, и любой ненулевой разрыв делал бы
предупреждение вечным — а вечное предупреждение перестают читать (тот же урок, что
у свежести артефактов в `deployment_acceptance`). Разрыв меньше суток остаётся
ВИДЕН в отчёте (`state=stale`), он просто не кричит.

Fail-CLOSED: всё, что измерить не удалось, — отдельное состояние `unchecked` со
своим голосом, никогда не «в порядке».

LLM запрещён. Только stdlib. Ничего не пишет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import logging
import plistlib
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("spa.monitoring.agent_code_freshness")

__all__ = [
    "STALE_ALERT_HOURS",
    "AgentCodeVerdict",
    "check_agent_code_freshness",
    "import_closure",
    "long_lived_labels",
    "resolve_target",
    "STATE_FRESH",
    "STATE_STALE",
    "STATE_FOREIGN",
    "STATE_NOT_RUNNING",
    "STATE_UNCHECKED",
    "STATE_NO_FLEET",
    "STATE_NO_LONG_LIVED",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_GLOB = "com.spa.*.plist"

OK, WARNING, CRITICAL = "OK", "WARNING", "CRITICAL"

# Разрыв, после которого сторож ПОВЫШАЕТ голос. Обоснование — в шапке модуля.
STALE_ALERT_HOURS = 24.0

# Потолок обхода импортов. Не «оптимизация»: без потолка ошибка в разрешении
# путей могла бы утащить обход в бесконечность и подвесить часового агента.
# Достижение потолка — НАХОДКА (`closure_truncated`), а не тихое усечение.
MAX_CLOSURE_FILES = 4000

STATE_FRESH = "fresh"
STATE_STALE = "stale"
STATE_FOREIGN = "foreign"            # процесс не исполняет python этого репозитория
STATE_NOT_RUNNING = "not_running"
STATE_UNCHECKED = "unchecked"
STATE_NO_FLEET = "no_fleet"
STATE_NO_LONG_LIVED = "no_long_lived"


# ── Ввод-вывод, который тесты подменяют целиком ─────────────────────────────
def _run(argv: Sequence[str]) -> str:
    """stdout команды; пустая строка при любой беде. Никогда не бросает."""
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_code_freshness: %s failed (%s)", argv[0] if argv else "?", exc)
        return ""
    return proc.stdout or ""


Runner = Callable[[Sequence[str]], str]


@dataclass
class AgentCodeVerdict:
    """Вердикт по ОДНОМУ долгоживущему агенту. ``issue`` пуст ⇒ говорить не о чем."""

    label: str
    state: str
    severity: str
    detail: str
    pid: Optional[int] = None
    started_at: Optional[str] = None
    code_newest_at: Optional[str] = None
    newest_file: Optional[str] = None
    gap_hours: Optional[float] = None
    files_checked: Optional[int] = None
    issue: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "state": self.state,
            "severity": self.severity,
            "detail": self.detail,
            "pid": self.pid,
            "started_at": self.started_at,
            "code_newest_at": self.code_newest_at,
            "newest_file": self.newest_file,
            "gap_hours": None if self.gap_hours is None else round(self.gap_hours, 2),
            "files_checked": self.files_checked,
            "notes": list(self.notes),
        }


# ── 1. Кто такие долгожители ────────────────────────────────────────────────
def long_lived_labels(agent_dir: Optional[Path] = None) -> Tuple[List[dict], Optional[str]]:
    """(долгожители, причина-почему-их-нет).

    Долгожитель — job с истинным ``KeepAlive``: launchd поднимает его обратно, сам
    он не выходит, значит нового кода не увидит. ``KeepAlive`` бывает и словарём
    (``{SuccessfulExit: false}``) — истинность проверяется, а не тип.

    Нечитаемый plist НЕ пропускается молча: он приходит помеченным ``problem`` и
    даёт `unchecked` — «не прочитали» не равно «долгожителей там нет».
    """
    d = Path(agent_dir) if agent_dir else DEFAULT_AGENT_DIR
    if not d.is_dir():
        # Каталога launchd нет вовсе — это ИЗМЕРЕНИЕ («здесь нет флота»), а не
        # неизвестность: на прод-хосте каталог есть всегда.
        return [], "каталог launchd {} отсутствует — флота здесь нет".format(d)
    try:
        plists = sorted(d.glob(AGENT_GLOB))
    except OSError as exc:
        return [], "каталог launchd {} не читается ({})".format(d, exc)
    if not plists:
        return [], "в {} нет ни одного {} — искали в правильном месте и не нашли ничего".format(
            d, AGENT_GLOB)

    out: List[dict] = []
    for p in plists:
        label = p.stem
        try:
            with open(p, "rb") as fh:
                doc = plistlib.load(fh)
        except Exception as exc:  # noqa: BLE001
            out.append({"label": label, "problem": "plist не читается: {}".format(exc)})
            continue
        if not doc.get("KeepAlive"):
            continue
        out.append({"label": label, "problem": None})
    return out, None


# ── 2. Живой процесс и время его старта ─────────────────────────────────────
def _launchctl_pid(label: str, runner: Runner) -> Optional[int]:
    """PID job'а по `launchctl list`. ``None`` — не запущен либо не измерено."""
    text = runner(["launchctl", "list"])
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == label:
            try:
                pid = int(parts[0])
            except ValueError:
                return None
            return pid if pid > 0 else None
    return None


def _process_table(runner: Runner) -> List[dict]:
    """[{pid, ppid, command}] по всем процессам. Пусто ⇒ измерить нечем."""
    text = runner(["ps", "-eo", "pid=,ppid=,command="])
    rows: List[dict] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "command": parts[2]})
        except ValueError:
            continue
    return rows


def _start_epoch(pid: int, runner: Runner) -> Optional[float]:
    """Момент старта процесса (epoch). ``None`` — не измерено."""
    raw = runner(["ps", "-o", "lstart=", "-p", str(pid)]).strip()
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    # ``lstart`` — ЛОКАЛЬНОЕ время без зоны; переводим через локальный календарь,
    # а не подставляем UTC: подстановка дала бы сдвиг на часовой пояс и разрыв
    # «в несколько часов» на ровном месте.
    try:
        return time.mktime(dt.timetuple())
    except (OverflowError, ValueError):
        return None


def _python_descendant(pid: int, table: List[dict]) -> Optional[int]:
    """python-потомок обёртки, если он есть.

    Обёртка `agent_template.sh` запускает python РОВНО ОДИН раз, поэтому потомок
    не старше родителя и не «моложе перезапуска». Меряем именно его: код держит
    в памяти он, а не bash.
    """
    by_parent: Dict[int, List[dict]] = {}
    for row in table:
        by_parent.setdefault(row["ppid"], []).append(row)
    seen: Set[int] = set()
    frontier = [pid]
    depth = 0
    while frontier and depth < 6:
        nxt: List[int] = []
        for p in frontier:
            for child in by_parent.get(p, []):
                cp = child["pid"]
                if cp in seen:
                    continue
                seen.add(cp)
                if "python" in child["command"].split()[0].rsplit("/", 1)[-1].lower():
                    return cp
                nxt.append(cp)
        frontier = nxt
        depth += 1
    return None


def _command_of(pid: int, table: List[dict]) -> Optional[str]:
    for row in table:
        if row["pid"] == pid:
            return row["command"]
    return None


# ── 3. Какой код этот процесс держит ────────────────────────────────────────
def resolve_target(command: str, repo_root: Path) -> Tuple[str, Optional[str]]:
    """Что именно исполняет процесс: ``("module"|"script"|"foreign", значение)``.

    Разбирается ровно то, что видно в командной строке живого процесса, — не
    plist и не обёртка: между ними и процессом могло пройти что угодно.
    """
    parts = command.split()
    if not parts:
        return "foreign", "пустая командная строка"

    # `python -m <модуль> [...]`
    if "-m" in parts:
        i = parts.index("-m")
        if i + 1 < len(parts):
            mod = parts[i + 1]
            # uvicorn исполняет ЧУЖОЙ модуль, переданный ему как `pkg.mod:attr`
            if mod == "uvicorn":
                for a in parts[i + 2:]:
                    if a.startswith("-"):
                        continue
                    target = a.split(":", 1)[0]
                    return "module", target
                return "foreign", "uvicorn без цели в командной строке"
            return "module", mod

    # `python /abs/script.py`
    for a in parts[1:]:
        if a.endswith(".py"):
            return "script", a

    return "foreign", "не python-модуль этого репозитория"


def _module_file(dotted: str, repo_root: Path) -> Optional[Path]:
    """Файл модуля ВНУТРИ репозитория. ``None`` ⇒ модуль не наш (stdlib/пакет)."""
    if not dotted:
        return None
    parts = dotted.split(".")
    base = repo_root.joinpath(*parts)
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        try:
            if cand.is_file():
                return cand
        except OSError:
            return None
    return None


def _package_of(path: Path, repo_root: Path) -> List[str]:
    """Пакет, в котором лежит файл, — для разрешения относительных импортов."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return []
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        return parts[:-1]
    return parts[:-1]


def _imports_of(path: Path, repo_root: Path) -> List[str]:
    """Точечные имена модулей, которые импортирует файл. Разбор, без выполнения."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return []
    pkg = _package_of(path, repo_root)
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join(anchor + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if not base:
                continue
            names.append(base)
            # `from pkg import sub` — `sub` вполне может быть модулем, а не именем
            names.extend("{}.{}".format(base, a.name) for a in node.names if a.name != "*")
    return names


def import_closure(
    entry: Path,
    repo_root: Path,
    max_files: int = MAX_CLOSURE_FILES,
) -> Tuple[Set[Path], bool]:
    """(файлы репозитория, достижимые импортом от точки входа; упёрлись ли в потолок)."""
    entry = Path(entry)
    seen: Set[Path] = set()
    if not entry.is_file():
        return seen, False
    stack = [entry]
    truncated = False
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        if len(seen) >= max_files:
            truncated = True
            break
        seen.add(cur)
        for dotted in _imports_of(cur, repo_root):
            f = _module_file(dotted, repo_root)
            if f is not None and f not in seen:
                stack.append(f)
    return seen, truncated


def _newest(files: Set[Path]) -> Tuple[Optional[float], Optional[Path]]:
    newest_t: Optional[float] = None
    newest_f: Optional[Path] = None
    for f in files:
        try:
            t = f.stat().st_mtime
        except OSError:
            continue
        if newest_t is None or t > newest_t:
            newest_t, newest_f = t, f
    return newest_t, newest_f


# ── 4. Вердикт ──────────────────────────────────────────────────────────────
def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _words(epoch: Optional[float]) -> str:
    """«от 5 августа» — как это сказал бы человек."""
    if epoch is None:
        return "неизвестно когда"
    m = ("января февраля марта апреля мая июня июля августа сентября октября "
         "ноября декабря").split()
    dt = datetime.fromtimestamp(epoch)
    return "от {} {}".format(dt.day, m[dt.month - 1])


def _check_one(
    label: str,
    problem: Optional[str],
    *,
    repo_root: Path,
    runner: Runner,
    table: List[dict],
    now: float,
    alert_hours: float,
    max_files: int,
) -> AgentCodeVerdict:
    if problem:
        return AgentCodeVerdict(
            label=label, state=STATE_UNCHECKED, severity=WARNING,
            detail=problem,
            issue="{}: {} — долгоживучесть НЕ ИЗМЕРЕНА".format(label, problem),
        )

    pid = _launchctl_pid(label, runner)
    if pid is None:
        # Не запущен — это забота `agent_health` (PID==0 у always-on агента там
        # уже CRITICAL). Дублировать чужую тревогу не нужно, а молчать нельзя:
        # состояние названо, голос не повышен.
        return AgentCodeVerdict(
            label=label, state=STATE_NOT_RUNNING, severity=OK,
            detail="долгожитель не запущен — какой код в нём загружен, вопроса нет",
        )

    target_pid = _python_descendant(pid, table) or pid
    command = _command_of(target_pid, table)
    if command is None:
        return AgentCodeVerdict(
            label=label, state=STATE_UNCHECKED, severity=WARNING, pid=target_pid,
            detail="процесс pid={} не найден в таблице процессов — НЕ ИЗМЕРЕНО".format(target_pid),
            issue="{}: процесс pid={} не виден в ps — какой код он исполняет, "
                  "измерить нечем".format(label, target_pid),
        )

    kind, value = resolve_target(command, repo_root)
    if kind == "foreign":
        return AgentCodeVerdict(
            label=label, state=STATE_FOREIGN, severity=OK, pid=target_pid,
            detail="исполняет не python этого репозитория ({}) — свежесть нашего "
                   "кода к нему не относится".format(value),
        )

    entry = Path(value) if kind == "script" else _module_file(value or "", repo_root)
    if entry is None or not entry.is_file():
        if kind == "module":
            # Модуль есть, но не наш (stdlib вроде `http.server`) — это ИЗМЕРЕНИЕ.
            return AgentCodeVerdict(
                label=label, state=STATE_FOREIGN, severity=OK, pid=target_pid,
                detail="исполняет модуль `{}` вне этого репозитория — свежесть "
                       "нашего кода к нему не относится".format(value),
            )
        return AgentCodeVerdict(
            label=label, state=STATE_UNCHECKED, severity=WARNING, pid=target_pid,
            detail="точка входа `{}` не найдена в дереве — НЕ ИЗМЕРЕНО".format(value),
            issue="{}: точка входа `{}` не найдена в дереве — какой код исполняется, "
                  "измерить нечем".format(label, value),
        )

    started = _start_epoch(target_pid, runner)
    if started is None:
        return AgentCodeVerdict(
            label=label, state=STATE_UNCHECKED, severity=WARNING, pid=target_pid,
            detail="время старта pid={} измерить не удалось — НЕ ИЗМЕРЕНО".format(target_pid),
            issue="{}: время старта процесса pid={} измерить не удалось — это не "
                  "«код свежий»".format(label, target_pid),
        )

    files, truncated = import_closure(entry, repo_root, max_files)
    newest_t, newest_f = _newest(files)
    notes: List[str] = []
    if truncated:
        notes.append("обход импортов упёрся в потолок {} файлов — часть дерева "
                     "НЕ ПРОСМОТРЕНА".format(max_files))
    if newest_t is None:
        return AgentCodeVerdict(
            label=label, state=STATE_UNCHECKED, severity=WARNING, pid=target_pid,
            started_at=_iso(started), files_checked=len(files), notes=notes,
            detail="ни один файл замыкания импортов не читается — НЕ ИЗМЕРЕНО",
            issue="{}: возраст кода измерить нечем (замыкание импортов пусто или "
                  "нечитаемо)".format(label),
        )

    rel = str(newest_f.relative_to(repo_root)) if newest_f and newest_f.is_relative_to(repo_root) \
        else (str(newest_f) if newest_f else None)
    gap_h = (newest_t - started) / 3600.0

    if gap_h <= 0:
        return AgentCodeVerdict(
            label=label, state=STATE_FRESH, severity=OK, pid=target_pid,
            started_at=_iso(started), code_newest_at=_iso(newest_t), newest_file=rel,
            gap_hours=gap_h, files_checked=len(files), notes=notes,
            detail="процесс стартовал позже последней правки кода ({} файлов "
                   "проверено) — исполняется то, что лежит в дереве".format(len(files)),
        )

    words = ("{} работает с кодом {}, а в дереве код {} — разрыв {:.1f} суток "
             "(самый новый: {})").format(
        label, _words(started), _words(newest_t), gap_h / 24.0, rel)

    if gap_h < alert_hours:
        # Видно в отчёте, но не кричит: обоснование порога — в шапке модуля.
        return AgentCodeVerdict(
            label=label, state=STATE_STALE, severity=OK, pid=target_pid,
            started_at=_iso(started), code_newest_at=_iso(newest_t), newest_file=rel,
            gap_hours=gap_h, files_checked=len(files), notes=notes,
            detail="{} (меньше суток — в пределах обычного окна доставки, "
                   "голос не повышаю)".format(words),
        )

    return AgentCodeVerdict(
        label=label, state=STATE_STALE, severity=WARNING, pid=target_pid,
        started_at=_iso(started), code_newest_at=_iso(newest_t), newest_file=rel,
        gap_hours=gap_h, files_checked=len(files), notes=notes,
        detail=words,
        issue=("доставлено, но НЕ исполняется: {}. Процесс долгоживущий "
               "(KeepAlive) — сам новый код не подхватит никогда; перезапуск — "
               "решение владельца (правило доставки, п. 6)").format(words),
    )


def check_agent_code_freshness(
    *,
    agent_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    runner: Optional[Runner] = None,
    now: Optional[float] = None,
    alert_hours: float = STALE_ALERT_HOURS,
    max_files: int = MAX_CLOSURE_FILES,
) -> dict:
    """Пройти по долгожителям и сказать, кто исполняет несвежий код. Ничего не пишет."""
    root = Path(repo_root) if repo_root else _REPO_ROOT
    run = runner or _run
    now = now if now is not None else time.time()

    labels, why_none = long_lived_labels(agent_dir)
    if why_none:
        # Каталога нет вовсе — «флота здесь нет», это измерение. Каталог есть, а
        # job'ов в нём нет — искали в правильном месте и не нашли ничего: находка.
        missing_dir = "отсутствует" in why_none
        return {
            "monitor": "agent_code_freshness",
            "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "status": OK if missing_dir else WARNING,
            "state": STATE_NO_FLEET if missing_dir else STATE_UNCHECKED,
            "agents": [],
            "long_lived_total": 0,
            "stale_count": 0,
            "unchecked_count": 0,
            "issues": [] if missing_dir else [
                "agent_code_freshness UNCHECKED: {}".format(why_none)],
            "reasons": [why_none],
        }

    if not labels:
        return {
            "monitor": "agent_code_freshness",
            "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "status": OK, "state": STATE_NO_LONG_LIVED, "agents": [],
            "long_lived_total": 0, "stale_count": 0, "unchecked_count": 0,
            "issues": [],
            "reasons": ["долгоживущих (KeepAlive) агентов нет — вопрос не возникает"],
        }

    table = _process_table(run)
    verdicts: List[AgentCodeVerdict] = []
    for entry in labels:
        try:
            verdicts.append(_check_one(
                entry["label"], entry.get("problem"), repo_root=root, runner=run,
                table=table, now=now, alert_hours=alert_hours, max_files=max_files))
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED, не тихий пропуск
            verdicts.append(AgentCodeVerdict(
                label=entry.get("label", "?"), state=STATE_UNCHECKED, severity=WARNING,
                detail="проверка упала: {}: {}".format(type(exc).__name__, exc),
                issue="{}: проверка свежести кода упала ({}) — «не измерено», а не "
                      "«в порядке»".format(entry.get("label", "?"), type(exc).__name__)))

    issues = [v.issue for v in verdicts if v.issue]
    status = OK
    for v in verdicts:
        if v.severity == CRITICAL:
            status = CRITICAL
            break
        if v.severity == WARNING:
            status = WARNING

    stale = [v for v in verdicts if v.state == STATE_STALE]
    unchecked = [v for v in verdicts if v.state == STATE_UNCHECKED]
    reasons = ["{} долгоживущих проверено, {} исполняют несвежий код".format(
        len(verdicts), len(stale))]
    if unchecked:
        reasons.append("{} НЕ ИЗМЕРЕНО — счёт несвежих неполон".format(len(unchecked)))

    # Одно слово итогового вердикта не имеет права быть `fresh`, когда мерить
    # не удалось: `stale_count: 0` рядом с `state: fresh` читается как «все
    # проверены, несвежих нет» — ровно та подмена «не измерено» → «в порядке»,
    # от которой этот модуль и написан. Порядок: нашли несвежих → stale;
    # не нашли, но что-то не измерено → unchecked; измерили всё → fresh.
    if stale:
        overall_state = STATE_STALE
    elif unchecked:
        overall_state = STATE_UNCHECKED
    else:
        overall_state = STATE_FRESH

    return {
        "monitor": "agent_code_freshness",
        "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "status": status,
        "state": overall_state,
        "agents": [v.as_dict() for v in verdicts],
        "long_lived_total": len(verdicts),
        "stale_count": len(stale),
        "unchecked_count": len(unchecked),
        "issues": issues,
        "reasons": reasons,
        "note": ("Отвечает ТОЛЬКО на вопрос «исполняет ли живой процесс код из "
                 "дерева». Не проверяет ни версию (deployment_drift), ни "
                 "способность стартовать (deployment_acceptance), ни то, что "
                 "агент вообще работает (agent_health). Ничего не перезапускает."),
    }


def format_report_text(doc: dict) -> str:
    icon = {OK: "✅", WARNING: "⚠️", CRITICAL: "🚨"}.get(doc.get("status"), "❓")
    lines = ["{} agent_code_freshness: {}".format(icon, doc.get("status")),
             "  долгожителей: {} · исполняют несвежий код: {} · НЕ ИЗМЕРЕНО: {}".format(
                 doc.get("long_lived_total"), doc.get("stale_count"),
                 doc.get("unchecked_count"))]
    for a in doc.get("agents", []):
        mark = {STATE_STALE: "✗", STATE_UNCHECKED: "?", STATE_FRESH: "✓"}.get(a.get("state"), "·")
        lines.append("    {} {}: {}".format(mark, a.get("label"), a.get("detail")))
    for r in doc.get("reasons", []):
        lines.append("  • {}".format(r))
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="Исполняет ли живой долгоживущий агент тот код, что лежит в дереве?")
    ap.add_argument("--agent-dir", default=None)
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()
    doc = check_agent_code_freshness(
        agent_dir=Path(args.agent_dir) if args.agent_dir else None,
        repo_root=Path(args.repo_root) if args.repo_root else None)
    print(format_report_text(doc))
    return {OK: 0, WARNING: 1, CRITICAL: 2}.get(doc.get("status"), 2)


if __name__ == "__main__":
    raise SystemExit(main())
