#!/usr/bin/env python3
"""Срок одного headless-запуска Claude И владение его потомками (ARB decision, 2026-09-18).

ЗАЧЕМ. Вызов `claude -p` в обёртках агентов не имел срока: launchd не поднимает второй
экземпляр той же метки, поэтому ОДНО зависание останавливало часовой такт навсегда и молча
(замер 18.09: девять прогонов 20.9…80.2 мин, все `exit 0` — у здоровой работы предел есть,
у зависания нет).

ПОЧЕМУ НЕ `timeout`. На машине владельца НЕТ ни `timeout`, ни `gtimeout` (coreutils не
установлен, замер 18.09). `timeout N claude …` дал бы 127 «command not found» и НЕ вызвал бы
Claude вовсе — то есть выключил бы агента, оставив в логе код, похожий на сбой Claude.

ПОЧЕМУ ГРАНИЦА ВЛАДЕНИЯ — НЕ ГРУППА И НЕ СЕССИЯ. Замер 18.09: Claude Code запускает оболочку
КАЖДОГО Bash-инструмента лидером СВОЕЙ НОВОЙ сессии (`pgid == sid == pid`), а не членом своей.
Живые улики на машине в момент решения — два полных прогона pytest с `ppid=1` и собственными
сессиями (`sid=46977`, `sid=99172`), вожаки которых мертвы. Поэтому ни `killpg(pgid claude)`,
ни «убить сессию claude», ни обход дерева по `ppid` в одиночку до них не доходят.

ГРАНИЦА — ПОЛОЖИТЕЛЬНОЕ ДОКАЗАТЕЛЬСТВО ПРИНАДЛЕЖНОСТИ, объединение ЧЕТЫРЁХ приборов:
  tree     — обход по `ppid` от нашего ребёнка (ловит всё, что ещё подчинено, включая bash);
  group    — `getpgid(pid) == pgid ребёнка` (группа наша по построению: `start_new_session`);
  session  — `getsid(pid) == sid ребёнка` (то же);
  run_id   — метка `SPA_RUN_ID` в ОКРУЖЕНИИ (наследуется через fork/exec и НЕ теряется ни при
             setsid, ни при переподчинении к init, ни при смене группы — единственный прибор,
             который видит измеренный режим отказа).

ИЗМЕРЕННАЯ СЛЕПОТА `run_id`, названная вслух, а не подразумеваемая. `ps -E` НЕ отдаёт
окружение платформенных бинарей macOS: замер 18.09 — `python3` (miniconda и системный) ДА,
`claude` (node) ДА, `/bin/bash` НЕТ, `/bin/sleep` НЕТ, `/usr/bin/git` НЕ ИЗМЕРЕНО (выходит
быстрее, чем читается). Дело не в размере окружения (проверено до 46 КБ, порога нет).
Поэтому приборов четыре: `tree`/`group`/`session` видят `bash`, пока он подчинён нам, а
`run_id` — отделившийся python/pytest, то есть ровно тот класс, который живёт часами.

OWNER POLICY (ARB decision 18.09) — две ветки, и они НАМЕРЕННО несимметричны:

* НОРМАЛЬНЫЙ выход Claude: отделившихся потомков НЕ убивать. Только снять улику и назвать
  её аномалией. Поведение здорового цикла не меняется. Замер, из которого это решение:
  цикл `cycle-80595` завершился `claude exit 0` в 10:38 и ОСТАВИЛ живой полный прогон —
  то есть переживший потомок при нормальном выходе сегодня ШТАТЕН, и убивать его молча
  значило бы менять протокол работы циклов под видом починки срока.
  Следствие асимметрии: сбой переписи на нормальной ветке НЕ меняет код возврата — иначе
  прибор срока начал бы краснить здоровые цикла, чего политика прямо не разрешает.

* TIMEOUT: сначала улика, потом завершение ТОЛЬКО тех, чья принадлежность ЭТОМУ `RUN_ID`
  доказана положительно; SIGTERM → grace → SIGKILL; неоднозначный или чужой процесс НЕ
  трогается никогда.

КОДЫ ВОЗВРАТА (различимость исходов — инв. #17):
  124 — сорвано по сроку, владение закрыто ПОЛНОСТЬЮ (никого своего не осталось);
  125 — сорвано по сроку, но владение НЕ закрыто ЛИБО доказательство состояния получить не
        удалось. «Не измерено» никогда не выдаётся за «чисто»: 124 недостижим, если хоть
        один прибор отказал;
  иной — код самого Claude, проброшенный без изменений.

STDLIB ONLY (инв. #4). LLM здесь нет и быть не может.
"""

from __future__ import annotations

import argparse
import datetime
import errno
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid

TIMEOUT_OWNERSHIP_CLOSED = 124
TIMEOUT_OWNERSHIP_UNRESOLVED = 125

# ── журнал исходов прогонов (27.10) ─────────────────────────────────────────
# Исход сессии раньше жил только в /tmp-журнале агента, а тот перезаписывался: неделю
# кодов 1 у оркестратора (14–21.10) разобрать было нечем, а 20.10 у novel_edge в том же
# журнале стояло «Failed to authenticate: OAuth session expired» — причина, которую
# пульс видел как голую цифру. Одна строка JSON на прогон, с распознанной причиной.
LEDGER_ENV = "SPA_CLAUDE_RUNS_LEDGER"
# Журнал пишется ТОЛЬКО когда назван (`--ledger` или переменная): иначе любой тест,
# зовущий main(), писал бы в data/ репозитория. Боевые обёртки называют его явно.
_AUTH_RE = re.compile(r"Failed to authenticate|OAuth session expired|Invalid API key|"
                      r"Please run /login", re.I)
CAUSE_OK, CAUSE_AUTH, CAUSE_TIMEOUT_CLOSED = "ok", "auth_expired", "timeout_closed"
CAUSE_TIMEOUT_UNRESOLVED, CAUSE_ERROR = "timeout_unresolved", "error"


def classify(rc: int, output: str) -> str:
    """Причина исхода по коду и выводу ЭТОГО прогона. Неузнанный ненулевой — `error`."""
    if rc == TIMEOUT_OWNERSHIP_CLOSED:
        return CAUSE_TIMEOUT_CLOSED
    if rc == TIMEOUT_OWNERSHIP_UNRESOLVED:
        return CAUSE_TIMEOUT_UNRESOLVED
    if rc != 0 and _AUTH_RE.search(output or ""):
        return CAUSE_AUTH
    return CAUSE_OK if rc == 0 else CAUSE_ERROR


def _read_from(path, offset: int, limit: int = 200_000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def record_outcome(*, label: str, run_id, rc: int, cause: str, started_at: str,
                   ended_at: str, ledger=None) -> bool:
    """Дописать строку исхода. Ошибка записи возвращает False и НЕ меняет код прогона."""
    path = ledger or os.environ.get(LEDGER_ENV)
    if not path:
        return False
    line = json.dumps({"label": label, "run_id": run_id, "rc": rc, "cause": cause,
                       "started_at": started_at, "ended_at": ended_at},
                      ensure_ascii=False, sort_keys=True)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except OSError:
        return False

#: Запас на дрожание замера при фильтре «процесс не старше самого запуска».
START_SLACK_S = 10.0

#: Такт опроса и grace — ОДНО определение на функцию и на CLI. Два умолчания в двух
#: местах означали бы два разных прибора под одним именем: правка одного молча оставила
#: бы другой прежним, и вердикт зависел бы от того, каким входом его позвали.
DEFAULT_POLL_S = 2.0     #: 2 с, а не 0.5 (ARB 18.09): перепись стоит 27–29 мс, но при
                         #: grace 120 с такт 0.5 давал бы 240 вызовов `ps` при нулевой
                         #: пользе — вердикт меняется секундами, не миллисекундами.
DEFAULT_GRACE_S = 120.0

#: Имя метки владения. Читается ИЗ ОКРУЖЕНИЯ потомков, поэтому переименование —
#: изменение контракта, а не косметика.
RUN_ID_VAR = "SPA_RUN_ID"


class PsUnavailable(RuntimeError):
    """Прибор состояния процессов не ответил. Это ТРЕТИЙ ИСХОД, а не пустой ответ."""


# ── двери к ОС: ровно две, и обе инъектируемы ────────────────────────────────
# Тест подменяет их, чтобы проверить (а) отказ прибора → 125, (б) «убить не удалось» → 125.
# Инъекция именно здесь, а не в вызывающем: замер собственного класса (#453) показал, что
# «половина инъекции» — та же бомба, поэтому у пути к ОС не должно остаться обходных дверей.

def _ps(args: list) -> str:
    """Таблица процессов в форме `ps`. Ненулевой код / нечитаемый источник — НЕ пустая таблица.

    ОДНА дверь на две платформы (G03, CI run #6, 17.10). Флаг `-E` (окружение) есть только
    у BSD-`ps` macOS; procps на Linux отвечает «unsupported SysV option», и прибор на
    раннере ВСЕГДА отдавал третий исход (125 / OWNERSHIP_UNKNOWN) — честно, но слепо.
    Поэтому на Linux те же три вопроса задаются `/proc` и ответ РЕНДЕРИТСЯ в ту же форму
    строк, что у `ps`: разбор (`Snapshot.take`, `argv_rows`, `_alive`) остаётся одним на
    обе платформы, а тесты, подменяющие `_ps` текстом, по-прежнему подменяют ВСЮ дверь к
    ОС, а не её половину (#453). На macOS поведение не меняется ни на байт.
    """
    if _use_proc():
        form = _proc_form(args)
        if form is not None:
            return _proc_ps(form, args)
    try:
        proc = subprocess.run(["ps"] + args, capture_output=True, text=True)
    except OSError as exc:
        raise PsUnavailable(f"ps не запустился: {exc}") from exc
    if proc.returncode != 0:
        raise PsUnavailable(
            f"ps вернул {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        )
    return proc.stdout


# ── Linux: те же вопросы к `/proc` ───────────────────────────────────────────
#: Корень procfs и такт часов ядра — ВХОДЫ (тест кладёт поддельное дерево в tmp и говорит
#: «это Linux»), а не окружение: иначе поведение Linux нечем доказать на Маке.
PROC_ROOT = "/proc"
CLK_TCK = None           #: None ⇒ `os.sysconf("SC_CLK_TCK")` в момент замера

#: Формы вопроса, которые этот модуль и `safe_terminate` задают `ps`. Иная форма на Linux
#: уходит в настоящий `ps` (procps) — с той же проверкой кода возврата.
FORM_SNAPSHOT = ("-A", "-Ewww", "-o", "pid=,ppid=,state=,etime=,command=")
FORM_ARGV = ("-A", "-wwwo", "pid=,command=")


def _use_proc() -> bool:
    """Переключатель платформы. Linux ⇒ `/proc`; всё прочее (darwin) ⇒ `ps`."""
    return sys.platform.startswith("linux")


def _proc_form(args: list):
    a = tuple(args)
    if a == FORM_SNAPSHOT:
        return "snapshot"
    if a == FORM_ARGV:
        return "argv"
    if len(a) == 4 and a[0] == "-o" and a[1] == "stat=" and a[2] == "-p" and a[3].isdigit():
        return "stat"
    return None


def _printable(text: str) -> str:
    """Управляющие символы → `?`, как делает `ps`: перевод строки в аргументе иначе
    разорвал бы таблицу, и разбор принял бы хвост аргумента за новую строку процесса."""
    return "".join("?" if ord(ch) < 32 or ord(ch) == 127 else ch for ch in text)


def _proc_read(root: str, pid: int, name: str):
    """Байты `/proc/<pid>/<name>`. Процесса нет ⇒ None (измерено: ушёл).
    Нет права ⇒ `PsUnavailable` (не измерено) — слепое пятно в таблице НЕ выдаётся за
    отсутствие процесса: перепись владения тогда объявила бы «своих не осталось»."""
    path = os.path.join(root, str(pid), name)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except PermissionError as exc:
        raise PsUnavailable(f"{path} не читается: {exc}") from exc
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return None
        raise PsUnavailable(f"{path} не читается: {exc}") from exc


def _proc_stat(raw: bytes):
    """`/proc/<pid>/stat` → (comm, state, ppid, starttime_ticks). Форма не та ⇒ `PsUnavailable`."""
    text = raw.decode("utf-8", errors="replace")
    lp, rp = text.find("("), text.rfind(")")
    if lp < 0 or rp < lp:
        raise PsUnavailable(f"stat не разобрать: {text[:120]!r}")
    comm = text[lp + 1:rp]
    rest = text[rp + 1:].split()
    try:
        return comm, rest[0], int(rest[1]), int(rest[19])
    except (IndexError, ValueError):
        raise PsUnavailable(f"stat не разобрать: {text[:120]!r}")


def _fmt_etime(seconds: float) -> str:
    """Секунды → `[[DD-]HH:]MM:SS` — та форма, которую разбирает `_parse_etime`."""
    s = max(0, int(seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}-{h:02d}:{m:02d}:{s:02d}"
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _proc_cmd(raw_cmdline: bytes, comm: str) -> str:
    """Командная строка как у `ps`: аргументы через пробел; пустая (поток ядра, зомби) ⇒ `[comm]`."""
    parts = [p.decode("utf-8", errors="replace") for p in raw_cmdline.split(b"\0") if p]
    return _printable(" ".join(parts)) if parts else f"[{_printable(comm)}]"


def _proc_ps(form: str, args: list, root=None) -> str:
    root = PROC_ROOT if root is None else root
    if form == "stat":
        raw = _proc_read(root, int(args[3]), "stat")
        if raw is None:
            return ""                    # процесса нет — измерено
        return _proc_stat(raw)[1] + "\n"
    try:
        names = os.listdir(root)
    except OSError as exc:
        raise PsUnavailable(f"{root} не читается: {exc}") from exc
    uptime = None
    if form == "snapshot":
        try:
            with open(os.path.join(root, "uptime"), "rb") as fh:
                uptime = float(fh.read().split()[0])
        except (OSError, ValueError, IndexError) as exc:
            raise PsUnavailable(f"{root}/uptime не прочитан — возраст не измерить: {exc}")
        tck = CLK_TCK if CLK_TCK is not None else os.sysconf("SC_CLK_TCK")
    lines = []
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        st = _proc_read(root, pid, "stat")
        if st is None:
            continue                     # ушёл между листингом и чтением
        comm, state, ppid, start = _proc_stat(st)
        cl = _proc_read(root, pid, "cmdline")
        if cl is None:
            continue
        cmd = _proc_cmd(cl, comm)
        if form == "argv":
            lines.append(f"{pid} {cmd}")
            continue
        # Окружение ЧУЖОГО процесса закрыто правами — это слепота строки (как у `ps -E`
        # на платформенных бинарях macOS), а не отказ всей таблицы: приборы tree/group/
        # session строку по-прежнему видят, а мерка `PATH=` считает её «слепой».
        try:
            env_raw = _proc_read(root, pid, "environ")
        except PsUnavailable:
            env_raw = b""
        if env_raw is None:
            continue
        env = [p.decode("utf-8", errors="replace") for p in env_raw.split(b"\0") if p]
        tail = cmd + (" " + _printable(" ".join(env)) if env else "")
        age = uptime - start / float(tck)
        lines.append(f"{pid} {ppid} {state} {_fmt_etime(age)} {tail}")
    return "\n".join(lines) + ("\n" if lines else "")


def _signal_pid(pid: int, sig: int) -> None:
    """Послать сигнал ОДНОМУ процессу. Отсутствие процесса — не ошибка."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        raise PsUnavailable(f"нет права сигналить pid {pid}")


# ── разбор таблицы процессов ─────────────────────────────────────────────────

def _parse_etime(text: str) -> float:
    """`[[DD-]HH:]MM:SS` → секунды. Форма локале-независима (в отличие от `lstart`).

    Русская локаль этой машины печатает `lstart` как «пятница, 18 сентября 2026 г.», и
    `strptime` на нём ломается — поэтому возраст меряется `etime`, а не датой старта.
    """
    days = 0
    rest = text.strip()
    if "-" in rest:
        d, rest = rest.split("-", 1)
        days = int(d)
    parts = [int(p) for p in rest.split(":")]
    if len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    elif len(parts) == 3:
        h, m, s = parts
    else:
        raise ValueError(f"необъяснимая форма etime: {text!r}")
    return days * 86400 + h * 3600 + m * 60 + s


class Snapshot:
    """Один снимок системы: pid → (ppid, возраст, командная строка + окружение).

    ОДНИМ вызовом `ps`, а не тремя: три вызова дали бы три разных момента времени, и
    «процесс, которого нет в одной таблице и есть в другой» стал бы неотличим от ошибки
    разбора.
    """

    def __init__(self, rows: dict, env_readable: int, env_blind: int):
        # rows: pid → (ppid, state, age, command+env)
        self.rows = rows
        self.env_readable = env_readable
        self.env_blind = env_blind

    @classmethod
    def take(cls) -> "Snapshot":
        out = _ps(["-A", "-Ewww", "-o", "pid=,ppid=,state=,etime=,command="])
        rows = {}
        readable = blind = 0
        for line in out.splitlines():
            fields = line.split(None, 4)
            if len(fields) < 4:
                continue
            try:
                pid = int(fields[0])
                ppid = int(fields[1])
                state = fields[2]
                age = _parse_etime(fields[3])
            except ValueError:
                # Строку не разобрали — молчать нельзя: это и есть «не измерено».
                raise PsUnavailable(f"строку ps не разобрать: {line[:120]!r}")
            tail = fields[4] if len(fields) > 4 else ""
            rows[pid] = (ppid, state, age, tail)
            if "=" in tail and " PATH=" in " " + tail:
                readable += 1
            else:
                blind += 1
        if not rows:
            raise PsUnavailable("ps вернул пустую таблицу процессов")
        return cls(rows, readable, blind)

    def children_of(self, pid: int) -> list:
        return [p for p, (ppid, _, _, _) in self.rows.items() if ppid == pid]


# ── приборы владения ─────────────────────────────────────────────────────────

def _inst_tree(snap: Snapshot, child_pid: int, run_id: str) -> set:
    """Потомки по `ppid`, до неподвижной точки."""
    found, frontier = set(), [child_pid]
    while frontier:
        cur = frontier.pop()
        for kid in snap.children_of(cur):
            if kid not in found:
                found.add(kid)
                frontier.append(kid)
    return found


def _inst_group(snap: Snapshot, child_pid: int, run_id: str) -> set:
    return {p for p in snap.rows if _safe_pgid(p) == child_pid}


def _inst_session(snap: Snapshot, child_pid: int, run_id: str) -> set:
    return {p for p in snap.rows if _safe_sid(p) == child_pid}


def _inst_run_id(snap: Snapshot, child_pid: int, run_id: str) -> set:
    needle = f"{RUN_ID_VAR}={run_id}"
    return {p for p, (_, _, _, tail) in snap.rows.items() if needle in tail}


#: ОТКУДА в строке `ps` взялось совпадение метки. `-Ewww` печатает командную строку и
#: окружение ОДНИМ полем, поэтому прибор выше не различает «метка унаследована работником»
#: (окружение) и «метка передана аргументом» (обёртка `--run-id …`, да и сам замер
#: `grep <метка>`). Замер 14.10 на рабочем Маке: из ЧЕТЫРЁХ живых носителей метки идущего
#: цикла ДВА оказались самим прибором замера — python, задавший вопрос, и `ps`, которого он
#: для этого позвал; оба несут метку в ОКРУЖЕНИИ по наследству. Вердикт это не меняет
#: (носитель метки найден — работа идёт), но ЧИСЛО в прозе вердикта — не население
#: работников, и пока происхождение не названо, этого по прозе не видно.
MATCH_ENV, MATCH_CMDLINE, MATCH_UNMEASURED = "env", "cmdline", "unmeasured"


def _ps_argv() -> str:
    """Та же таблица БЕЗ `-E`: только командная строка. Отдельная дверь к ОС (инъектируема)."""
    return _ps(["-A", "-wwwo", "pid=,command="])


def argv_rows(probe=None) -> dict:
    """pid → командная строка БЕЗ окружения. Поднимает `PsUnavailable` как и снимок."""
    out = (probe or _ps_argv)()
    rows = {}
    for line in out.splitlines():
        fields = line.split(None, 1)
        if len(fields) < 2:
            continue
        try:
            rows[int(fields[0])] = fields[1]
        except ValueError:
            raise PsUnavailable(f"строку ps (без -E) не разобрать: {line[:120]!r}")
    if not rows:
        raise PsUnavailable("ps (без -E) вернул пустую таблицу процессов")
    return rows


def match_origin(snap: "Snapshot", run_id: str, argv=None, probe=None) -> dict:
    """pid-носитель метки → (`env` | `cmdline` | `unmeasured`, причина).

    Как мерится. В выводе `-Ewww` окружение ДОПИСАНО за командной строкой, поэтому строка
    без `-E` есть ПРЕФИКС строки с `-E` (замер 14.10: свойство держится у 649 строк из 649).
    Смещение совпадения меньше длины префикса ⇒ метка в КОМАНДНОЙ строке, иначе ⇒ в
    ОКРУЖЕНИИ. Префикс не совпал или pid в одной таблице есть, а в другой нет (замер: 1 pid
    из 650 — таблицы снимаются не в один миг) ⇒ **третий исход** `unmeasured` с причиной:
    выдать его за `env` значило бы объявить обёртку работником (инв. #17).

    `argv` (готовая таблица) и `probe` (дверь к ОС, которой её добыть) — ВХОДЫ ровно по
    тем же причинам, по которым инъектируемы обе дверцы `census`: сторож, спрашивающий у
    живой ОС, меняет вердикт от того, кто сегодня занял номер. Сцена «вторую таблицу снять
    не удалось» достижима ТОЛЬКО через `probe`, поэтому без него третий исход остался бы
    необъявленным по существу.
    """
    needle = f"{RUN_ID_VAR}={run_id}"
    try:
        rows = argv if argv is not None else argv_rows(probe=probe)
    except PsUnavailable as exc:
        rows = None
        why_all = f"командная строка без окружения не снята ({exc})"
    out = {}
    for pid, (_, _, _, tail) in snap.rows.items():
        at = tail.find(needle)
        if at < 0:
            continue
        if rows is None:
            out[pid] = (MATCH_UNMEASURED, why_all)
            continue
        argv_line = rows.get(pid)
        if argv_line is None:
            out[pid] = (MATCH_UNMEASURED,
                        "процесса нет во второй таблице — снимки не в один миг")
        elif not tail.startswith(argv_line):
            out[pid] = (MATCH_UNMEASURED,
                        "строка без окружения не является префиксом строки с окружением — "
                        "границу командной строки не определить")
        # Граница СТРОГАЯ, и равенство здесь недостижимо по построению: `ps -E`
        # отделяет окружение от командной строки ПРОБЕЛОМ, а игла начинается с `S`,
        # поэтому смещение `len(argv_line)` пришлось бы на сам разделитель. Мутант
        # `<=` этим и ВЫЖИЛ в прогоне #866 — равносильность названа, а не замолчана;
        # граница закреплена с ДОСТИЖИМЫХ сторон (`test_run_id_match_origin`:
        # игла, упирающаяся в конец argv ⇒ `cmdline`; игла с первого символа
        # окружения ⇒ `env`).
        elif at < len(argv_line):
            out[pid] = (MATCH_CMDLINE, "метка стоит в КОМАНДНОЙ строке (обёртка, замер, "
                                       "ручной запуск) — работником это не доказано")
        else:
            out[pid] = (MATCH_ENV, "метка в ОКРУЖЕНИИ — унаследована от запуска")
    return out


def origin_census(snap: "Snapshot", run_id: str, *, argv=None, probe=None,
                  self_pid=None) -> dict:
    """Население носителей метки по происхождению + сколько из них — сам прибор замера.

    `self_pid` считается ОТДЕЛЬНО, а не вычитается: вычитание изменило бы ВЕРДИКТ, а в
    единственной сцене, где прибор видит собственную метку, он спрашивает о СВОЕЙ работе
    (`already_mine` у замка, `self_identities` у захвата) — там вердикт и так короткий.
    Вычесть «на всякий случай» значило бы отдать карточку живого работника, потому что
    работник оказался предком замерщика (так он и устроен: python зовут из его дерева).
    """
    org = match_origin(snap, run_id, argv=argv, probe=probe)
    me = os.getpid() if self_pid is None else self_pid
    kin = {me} | set(snap.children_of(me))
    counts = {MATCH_ENV: 0, MATCH_CMDLINE: 0, MATCH_UNMEASURED: 0}
    for pid, (kind, _why) in org.items():
        counts[kind] += 1
    return {"origin": org, "counts": counts,
            "self": sorted(p for p in org if p in kin), "total": len(org)}


#: Порядок не важен, важна полнота. Тест выключает приборы ПОШТУЧНО и обязан краснеть
#: на выключении `run_id` — иначе «объединение приборов» недоказуемо.
INSTRUMENTS = {
    "tree": _inst_tree,
    "group": _inst_group,
    "session": _inst_session,
    "run_id": _inst_run_id,
}


def _safe_pgid(pid: int):
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None
    except OSError as exc:
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return None
        raise


def _safe_sid(pid: int):
    try:
        return os.getsid(pid)
    except (ProcessLookupError, PermissionError):
        return None
    except OSError as exc:
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return None
        raise


class Owned:
    __slots__ = ("pid", "ppid", "age", "pgid", "sid", "cmd", "by")

    def __init__(self, pid, ppid, age, pgid, sid, cmd, by):
        self.pid, self.ppid, self.age = pid, ppid, age
        self.pgid, self.sid, self.cmd, self.by = pgid, sid, cmd, by

    def line(self) -> str:
        return (
            f"pid={self.pid} ppid={self.ppid} pgid={self.pgid} sid={self.sid} "
            f"age={self.age:.0f}s приборы={'+'.join(sorted(self.by))} :: {self.cmd[:110]}"
        )


def census(child_pid: int, run_id: str, run_age_s: float, *, self_pid: int,
           self_sid, instruments=None) -> list:
    """Кто ПОЛОЖИТЕЛЬНО принадлежит этому запуску. Может поднять `PsUnavailable`.

    Три защиты от «выстрела в чужого», и каждая закрывает свой класс:
      * pid 1, сам прибор и его собственная сессия исключаются всегда;
      * возраст цели не больше возраста запуска — иначе через несколько часов сигнал ушёл бы
        в ПЕРЕИСПОЛЬЗОВАННЫЙ номер (тот же класс, что литеральный pid в тестах);
      * принадлежность обязана быть НАЙДЕНА прибором, а не предположена по отсутствию улик.
    """
    snap = Snapshot.take()
    instruments = INSTRUMENTS if instruments is None else instruments
    hits = {}
    for name, fn in instruments.items():
        for pid in fn(snap, child_pid, run_id):
            hits.setdefault(pid, set()).add(name)

    out = []
    for pid, by in hits.items():
        if pid <= 1 or pid == self_pid:
            continue
        sid = _safe_sid(pid)
        if sid is not None and self_sid is not None and sid == self_sid:
            # Наша собственная сессия — это обёртка агента и launchd-задание. Никогда.
            continue
        row = snap.rows.get(pid)
        if row is None:
            continue
        ppid, state, age, cmd = row
        if state.startswith("Z"):
            # Зомби — это запись в таблице процессов, а не процесс: он не исполняется,
            # ничего не пишет и ничем не владеет, а `kill -0` по нему ПРОХОДИТ (замер
            # 18.09: `57648 57647 Z 00:01 <defunct>`). Считать его выжившим значило бы
            # выдавать ЛОЖНЫЙ 125 всякий раз, когда родитель не успел его дожать за те
            # секунды, что идёт финальная перепись.
            continue
        if age > run_age_s + START_SLACK_S:
            # Старше самого запуска ⇒ нашим потомком быть не может.
            continue
        out.append(Owned(pid, ppid, age, _safe_pgid(pid), sid, cmd, by))
    out.sort(key=lambda o: o.pid)
    return out


# ── журнал ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


class Log:
    """Дописывание в тот же файл, куда пишет Claude.

    `O_APPEND` и flush на каждую строку: у ребёнка СВОЙ дескриптор того же файла, и без
    режима добавления строки прибора и строки сессии перезаписывали бы друг друга.
    """

    def __init__(self, path):
        self.path = path

    def __call__(self, text: str) -> None:
        line = f"[{_ts()}] {text}\n"
        if self.path is None:
            sys.stderr.write(line)
            sys.stderr.flush()
            return
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()


# ── основной ход ─────────────────────────────────────────────────────────────

def _terminate(owned: list, sig: int, log: Log, run_id: str, child_pid: int,
               run_age_s: float, self_pid: int, self_sid, instruments) -> None:
    """Сигнал списку. Принадлежность перепроверяется НЕПОСРЕДСТВЕННО перед выстрелом."""
    still = {o.pid for o in census(child_pid, run_id, run_age_s, self_pid=self_pid,
                                   self_sid=self_sid, instruments=instruments)}
    name = "SIGTERM" if sig == signal.SIGTERM else "SIGKILL"
    for o in owned:
        if o.pid not in still:
            continue
        log(f"⏱ TIMEOUT: {name} → pid={o.pid} ({'+'.join(sorted(o.by))})")
        _signal_pid(o.pid, sig)


def run(cmd: list, *, timeout_s: float, grace_s: float, log_path, label: str,
        poll_s: float = DEFAULT_POLL_S, instruments=None, run_id=None) -> int:
    """`instruments` ограничивает набор приборов ДЛЯ ВЫСТРЕЛА, но НЕ для вердикта.

    Разделение найдено собственным тестом (канарейка 18.09) и оно не косметическое.
    Сначала обе переписи — и «кого убивать», и «закрыто ли владение» — шли одним набором.
    При выключенном приборе метки отделившийся потомок ВЫЖИВАЛ, а прибор возвращал **124
    «владение закрыто полностью»**: он не видел того, кого не смог убить, и докладывал об
    этом как о чистоте. Это ровно тот класс, против которого написан инв. #17 — зелёный
    ответ прибора на СВОЙ вопрос выдавался за ответ на нужный. Теперь вердикт всегда
    меряется ПОЛНЫМ набором: «124» означает «никого своего не нашлось ничем из того, чем
    мы умеем искать», а не «никого не нашлось тем, чем мы стреляли».
    """
    log = Log(log_path)
    kill_instruments = INSTRUMENTS if instruments is None else instruments
    # `run_id` может прийти СНАРУЖИ: замок цикла записывает его в holder.json ДО запуска,
    # чтобы живость РАБОТНИКА измерялась той же меткой, которой здесь меряется владение
    # (см. ADR-720). Не передали — генерируем, как и раньше: поведение не меняется.
    run_id = str(run_id or "").strip() or f"{label}-{os.getpid()}-{uuid.uuid4().hex}"
    self_pid = os.getpid()
    self_sid = _safe_sid(self_pid)

    env = dict(os.environ)
    env[RUN_ID_VAR] = run_id

    stdout = None
    if log_path is not None:
        stdout = open(log_path, "a", encoding="utf-8")
    started = time.monotonic()
    log(f"⏱ RUN {run_id}: срок {timeout_s:.0f}s, grace {grace_s:.0f}s, команда: {cmd[0]}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=stdout if stdout is not None else None,
            stderr=subprocess.STDOUT if stdout is not None else None,
            # Своя сессия: (1) группа и сессия запуска становятся НАШИМИ по построению,
            # (2) прибор физически не может выстрелить в собственную группу.
            start_new_session=True,
            env=env,
        )
    finally:
        if stdout is not None:
            stdout.close()

    timed_out = False
    try:
        rc = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        rc = None

    run_age = time.monotonic() - started

    # ── ветка НОРМАЛЬНОГО выхода: улика да, убийство нет (owner policy 1) ────
    if not timed_out:
        assert rc is not None   # ветка входит только когда wait() вернул код

        try:
            survivors = census(proc.pid, run_id, run_age, self_pid=self_pid,
                               self_sid=self_sid, instruments=INSTRUMENTS)
        except PsUnavailable as exc:
            # Код НЕ меняем: политика прямо оставляет нормальный цикл как есть.
            log(f"⚠️ ANOMALY НЕ ИЗМЕРЕНА: {exc} — переживших назвать нечем (код не меняется)")
            return rc
        if survivors:
            log(f"⚠️ ANOMALY: claude вышел с {rc}, но {len(survivors)} процесс(ов) этого "
                f"запуска ЖИВЫ. Политика ARB: НЕ убивать, только зафиксировать:")
            for o in survivors:
                log(f"    ANOMALY-EVIDENCE {o.line()}")
        return rc

    # ── ветка TIMEOUT ────────────────────────────────────────────────────────
    log(f"⏱ TIMEOUT: {run_id} не завершился за {timeout_s:.0f}s")
    try:
        owned = census(proc.pid, run_id, run_age, self_pid=self_pid,
                       self_sid=self_sid, instruments=kill_instruments)
    except PsUnavailable as exc:
        # Ровно тот исход, ради которого 125 существует: срок сорван, а СОСТОЯНИЕ
        # неизвестно. Убивать по недоказанной принадлежности запрещено политикой,
        # поэтому единственное, что здесь законно — выстрел в СВОЕГО ребёнка, чей pid
        # мы держим сами, и громкий 125.
        log(f"⏱ TIMEOUT: ВЛАДЕНИЕ НЕ ИЗМЕРЕНО ({exc}); сигналю только своему ребёнку "
            f"pid={proc.pid}, чужих не трогаю; исход 125")
        try:
            _signal_pid(proc.pid, signal.SIGTERM)
            time.sleep(min(grace_s, 5.0))
            _signal_pid(proc.pid, signal.SIGKILL)
        except PsUnavailable as exc2:
            log(f"⏱ TIMEOUT: и сигнал не удался: {exc2}")
        return TIMEOUT_OWNERSHIP_UNRESOLVED

    # УЛИКА ДО РАЗРУШЕНИЯ — иначе о том, что именно было убито, не останется ничего.
    log(f"⏱ TIMEOUT-EVIDENCE: процессов этого запуска — {len(owned)}; "
        f"каждый назван с прибором, который его нашёл")
    for o in owned:
        log(f"    TIMEOUT-EVIDENCE {o.line()}")

    try:
        _terminate(owned, signal.SIGTERM, log, run_id, proc.pid, run_age,
                   self_pid, self_sid, kill_instruments)
    except PsUnavailable as exc:
        log(f"⏱ TIMEOUT: SIGTERM не разослан: {exc}")
        return TIMEOUT_OWNERSHIP_UNRESOLVED

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        try:
            if not census(proc.pid, run_id, time.monotonic() - started,
                          self_pid=self_pid, self_sid=self_sid,
                          instruments=INSTRUMENTS):
                break
        except PsUnavailable as exc:
            log(f"⏱ TIMEOUT: состояние во время grace не измерено: {exc}; исход 125")
            return TIMEOUT_OWNERSHIP_UNRESOLVED

    try:
        left = census(proc.pid, run_id, time.monotonic() - started, self_pid=self_pid,
                      self_sid=self_sid, instruments=kill_instruments)
    except PsUnavailable as exc:
        log(f"⏱ TIMEOUT: состояние после grace не измерено: {exc}; исход 125")
        return TIMEOUT_OWNERSHIP_UNRESOLVED

    if left:
        try:
            _terminate(left, signal.SIGKILL, log, run_id, proc.pid,
                       time.monotonic() - started, self_pid, self_sid, kill_instruments)
        except PsUnavailable as exc:
            log(f"⏱ TIMEOUT: SIGKILL не разослан: {exc}; исход 125")
            return TIMEOUT_OWNERSHIP_UNRESOLVED
        time.sleep(min(poll_s * 4, 2.0))

    try:
        final = census(proc.pid, run_id, time.monotonic() - started, self_pid=self_pid,
                       self_sid=self_sid, instruments=INSTRUMENTS)
    except PsUnavailable as exc:
        log(f"⏱ TIMEOUT: финальное состояние не измерено: {exc}; исход 125")
        return TIMEOUT_OWNERSHIP_UNRESOLVED

    # Своего ребёнка дожинаем всегда: без wait() он остался бы зомби у прибора.
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass

    if final:
        log(f"⏱ TIMEOUT: ВЛАДЕНИЕ НЕ ЗАКРЫТО — {len(final)} процесс(ов) выжили:")
        for o in final:
            log(f"    SURVIVOR {o.line()}")
        return TIMEOUT_OWNERSHIP_UNRESOLVED

    log("⏱ TIMEOUT: владение закрыто полностью (своих процессов не осталось); исход 124")
    return TIMEOUT_OWNERSHIP_CLOSED


def build_parser() -> argparse.ArgumentParser:
    """Разбор аргументов вынесен, чтобы умолчания CLI были ИЗМЕРИМЫ тестом.

    Иначе «такт 2 с» проверялся бы по тексту `--help`, а argparse умолчаний там не
    печатает: проверка читала бы не то, что прибор делает.
    """
    ap = argparse.ArgumentParser(
        description="Срок headless-запуска Claude и владение его потомками.")
    ap.add_argument("--timeout-s", type=float, required=True)
    ap.add_argument("--grace-s", type=float, default=DEFAULT_GRACE_S)
    ap.add_argument("--log", default=None)
    ap.add_argument("--label", required=True)
    ap.add_argument("--run-id", default=None,
                    help="готовая метка владения (умолчание — сгенерировать). Нужна, когда\nметку уже записал замок цикла, чтобы обе стороны мерили ОДНУ личность")
    ap.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S)
    ap.add_argument("--ledger", default=None,
                    help="журнал исходов (JSONL); не назван — исход не записывается")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    ns = ap.parse_args(argv)
    cmd = ns.cmd[1:] if ns.cmd and ns.cmd[0] == "--" else ns.cmd
    if not cmd:
        ap.error("после -- обязана быть команда")
    run_id = str(ns.run_id or "").strip() or f"{ns.label}-{os.getpid()}-{uuid.uuid4().hex}"
    offset = 0
    if ns.log:
        try:
            offset = os.path.getsize(ns.log)
        except OSError:
            offset = 0
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rc = run(cmd, timeout_s=ns.timeout_s, grace_s=ns.grace_s, log_path=ns.log,
             label=ns.label, poll_s=ns.poll_s, run_id=run_id)
    cause = classify(rc, _read_from(ns.log, offset) if ns.log else "")
    named = bool(ns.ledger or os.environ.get(LEDGER_ENV))
    ok = record_outcome(label=ns.label, run_id=run_id, rc=rc, cause=cause, ledger=ns.ledger,
                        started_at=started_at,
                        ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    log = Log(ns.log)
    log(f"⏱ OUTCOME {run_id}: rc={rc} cause={cause}"
        + ("" if ok or not named else " (журнал исходов НЕ записан)"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
