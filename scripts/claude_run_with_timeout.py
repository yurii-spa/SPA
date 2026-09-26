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
import os
import signal
import subprocess
import sys
import time
import uuid

TIMEOUT_OWNERSHIP_CLOSED = 124
TIMEOUT_OWNERSHIP_UNRESOLVED = 125

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

#: Форма вызова `ps`, отдающая таблицу процессов ВМЕСТЕ С ОКРУЖЕНИЕМ — опция `-E`.
#: BSD `ps` (macOS) её принимает. procps-ng (Linux) отвергает ВСЮ команду целиком:
#: `error: unsupported SysV option`. Это ИЗМЕРЕНО на настоящем раннере, а не выведено из
#: чтения флагов — прогон `SPA CI` 36222500219 (джоба 108350299527, ubuntu-latest, 26.09)
#: печатает эту строку девятнадцать раз подряд.
PS_ARGS_WITH_ENV = ["-A", "-Ewww", "-o", "pid=,ppid=,state=,etime=,command="]

#: Та же таблица БЕЗ окружения. Эту форму принимают обе реализации `ps`.
PS_ARGS_TABLE_ONLY = ["-A", "-ww", "-o", "pid=,ppid=,state=,etime=,command="]

#: Окружение процесса отдельной дверью, когда `ps` его не отдаёт (Linux).
PROC_ENVIRON = "/proc/{pid}/environ"

#: Имена дверей. Существуют затем, чтобы вердикт называл, ЧЕМ он измерен: «принадлежность
#: не разрешилась» и «не разрешилась ЭТОЙ дверью» — разные утверждения (инв. #17).
DOOR_PS_WITH_ENV = "ps -E (окружение внутри таблицы)"
DOOR_PS_PLUS_PROC = "ps + /proc/<pid>/environ"

#: Отказ опции `-E` — свойство ПЛАТФОРМЫ, а не момента: `ps`, отвергший её однажды, будет
#: отвергать и через полсекунды. Кэшируется ТОЛЬКО отказ и только ради бюджета вызовов
#: (grace 120 с при такте 0.5 дал бы 240 заведомо провальных вызовов). Успех не кэшируется
#: вовсе: иначе исчезнувшая дверь читалась бы как живая.
_ENV_OPTION_REFUSED: "str | None" = None


def reset_ps_door_cache() -> None:
    """Забыть измеренный отказ опции `-E`. Нужно тестам, подменяющим двери."""
    global _ENV_OPTION_REFUSED
    _ENV_OPTION_REFUSED = None


def _ps(args: list) -> str:
    """`ps` с проверкой кода возврата. Ненулевой код — НЕ пустая таблица."""
    try:
        proc = subprocess.run(["ps"] + args, capture_output=True, text=True)
    except OSError as exc:
        raise PsUnavailable(f"ps не запустился: {exc}") from exc
    if proc.returncode != 0:
        raise PsUnavailable(
            f"ps вернул {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        )
    return proc.stdout


def _read_environ(pid: int):
    """Окружение ОДНОГО процесса через `/proc`. `None` — НЕ прочитано.

    `None` и пустая строка — РАЗНЫЕ исходы, и смешать их нельзя: пустое окружение есть
    наблюдение, а отказ чтения (чужой uid, процесс вышел, `/proc` не смонтирован) —
    отсутствие наблюдения. Вернуть `""` на отказе значило бы сказать «метки нет» там, где
    верно «не смотрели» (инв. #17).
    """
    try:
        with open(PROC_ENVIRON.format(pid=pid), "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    return " ".join(chunk.decode("utf-8", "replace")
                    for chunk in raw.split(b"\0") if chunk)


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

    def __init__(self, rows: dict, env_readable: int, env_blind: int,
                 door: str = DOOR_PS_WITH_ENV):
        # rows: pid → (ppid, state, age, command+env)
        self.rows = rows
        self.env_readable = env_readable
        self.env_blind = env_blind
        #: ЧЕМ снят этот снимок. Прибор `run_id` читает окружение, а окружение на двух
        #: платформах достаётся РАЗНЫМИ дверями; вердикт обязан называть свою.
        self.door = door

    @classmethod
    def take(cls) -> "Snapshot":
        """Снимок ОДНИМ моментом, дверью, которую эта ОС ПРИНЯЛА.

        Порядок дверей не косметика. Пока форма была одна (`ps -A -Ewww`), на Linux
        отказывал ВЕСЬ снимок, и принадлежность становилась `OWNERSHIP_UNKNOWN` ВСЕГДА:
        предохранитель, не дающий убить чужой процесс, там ничего не завершал и при этом
        выглядел исправным. Третий исход был честен (инв. #17 не нарушался), но ответа на
        вопрос «мой ли это процесс» не существовало вовсе.

        Вторая дверь — НЕ тихий обход отказа: она названа в самом снимке (`door`), и когда
        отказывают ОБЕ, наружу идёт `PsUnavailable`, назвавший оба отказа. Тихого
        `fail-OPEN` здесь нет ни в одной ветке.
        """
        global _ENV_OPTION_REFUSED
        refused = _ENV_OPTION_REFUSED
        if refused is None:
            try:
                return cls._parse(_ps(PS_ARGS_WITH_ENV), DOOR_PS_WITH_ENV)
            except PsUnavailable as exc:
                refused = str(exc)
        try:
            out = _ps(PS_ARGS_TABLE_ONLY)
        except PsUnavailable as exc:
            # ОБЕ двери отказали ⇒ третий исход, и оба отказа названы. Кэш при этом НЕ
            # трогается: «ps сейчас не ответил» — не то же самое, что «эта ОС не знает
            # опции `-E`», а запомнить первое как второе значило бы навсегда ослепить
            # прибор `run_id` на macOS из-за одной осечки.
            raise PsUnavailable(
                f"обе двери к таблице процессов отказали — с окружением: "
                f"{refused}; без окружения: {exc}"
            ) from exc
        # Отказ опции ДОКАЗАН дифференциально: тот же `ps`, другая форма — ответил.
        # Только это и есть утверждение о платформе; до него запоминать нечего.
        _ENV_OPTION_REFUSED = refused
        return cls._parse(out, DOOR_PS_PLUS_PROC)

    @classmethod
    def _parse(cls, out: str, door: str) -> "Snapshot":
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
            if door == DOOR_PS_PLUS_PROC:
                env = _read_environ(pid)
                if env is None:
                    blind += 1
                else:
                    readable += 1
                    tail = f"{tail} {env}" if tail else env
            elif "=" in tail and " PATH=" in " " + tail:
                readable += 1
            else:
                blind += 1
            rows[pid] = (ppid, state, age, tail)
        if not rows:
            raise PsUnavailable("ps вернул пустую таблицу процессов")
        return cls(rows, readable, blind, door)

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
        poll_s: float = DEFAULT_POLL_S, instruments=None) -> int:
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
    run_id = f"{label}-{os.getpid()}-{uuid.uuid4().hex}"
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
    ap.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    ns = ap.parse_args(argv)
    cmd = ns.cmd[1:] if ns.cmd and ns.cmd[0] == "--" else ns.cmd
    if not cmd:
        ap.error("после -- обязана быть команда")
    return run(cmd, timeout_s=ns.timeout_s, grace_s=ns.grace_s, log_path=ns.log,
               label=ns.label, poll_s=ns.poll_s)


if __name__ == "__main__":
    sys.exit(main())
