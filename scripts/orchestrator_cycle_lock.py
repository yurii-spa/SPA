#!/usr/bin/env python3
"""scripts/orchestrator_cycle_lock.py — ОБЩИЙ замок цикла оркестратора (ADR-070 п.9).

Решение владельца 2026-08-07: «общий файл-замок (atomic-mkdir) на весь цикл; занят живой
сессией — вежливый выход; ручной запуск видит "подожди N минут"».

## Зачем

Карточки от одновременной работы защищены с 30.07 (`check_card_claim.py`), сам ЦИКЛ — нет.
`com.spa.orchestrator` запускается по расписанию тем же промптом, что и ручной прогон, и
30.07 две сессии независимо взяли ОДНУ карточку, проделали одну работу и правили одни файлы;
доставлена одна, вторая осталась в `/tmp`-worktree. Захват карточки ловит столкновение
ПОЗДНО — после шагов 0/0a/0b, то есть после самой дорогой части цикла, — и не ловит вовсе,
когда вторая сессия берёт СЛЕДУЮЩУЮ карточку: работа не дублируется, но два автономных
пушера идут в один `origin/main` наперегонки.

Замок отвечает на вопрос раньше всех остальных шагов: **идёт ли уже цикл?**

## Три вещи, которые он НЕ делает (и почему это важно)

1. **Не удаляет чужой замок по возрасту.** Живость держателя ИЗМЕРЯЕТСЯ (тот же
   `check_undelivered_work.session_state`, что у шагов 0a/0b: `session_pid` +
   `session_pid_start`, то есть pid И его время старта — иначе переиспользованный
   ОС pid читался бы как живая сессия). Одна семантика «жива ли сессия» на весь репозиторий;
   второй расходящийся ответ на тот же вопрос хуже отсутствия второго.
2. **Не запирает очередь навсегда.** Мёртвый держатель ⇒ замок снимается и берётся заново.
   Живость НЕ ИЗМЕРИЛАСЬ (`ps` не отработал, поля личности нет) ⇒ блокирует, но ОГРАНИЧЕННО:
   через `--unmeasured-ttl` (по умолчанию 3ч — то же окно свежести, что у шагов 0a/0b) замок
   считается брошенным. Необратимое «не измерено» над тем, что никогда не прояснится, — это
   вечный замок, а не порог (класс, разобранный в цикле #146).
3. **Не убивает цикл, если сломан сам.** Не создаётся каталог, не читается общее дерево —
   вердикт `unprotected`, код 0, цикл идёт БЕЗ защиты и говорит об этом вслух. Сторож,
   убивающий то, что охраняет, вреднее отсутствия сторожа (та же посылка, что у
   `cycle_runner._acquire_cycle_lock`).

## Где живёт замок

Рядом с ОБЩИМ журналом объявлений (`check_undelivered_work.shared_log` → главное рабочее
дерево). Это принципиально: циклы по протоколу §3.4 работают из `/tmp`-worktree, и замок в
дереве сессии не увидел бы никто — «свободно» для всех, то есть отсутствие замка с
интерфейсом замка. Не разрешилось общее дерево — это `unprotected`, а не «свободно».

## Команды

    python3 scripts/orchestrator_cycle_lock.py acquire --session cycle-123 --pid 123
    python3 scripts/orchestrator_cycle_lock.py release --session cycle-123 --pid 123
    python3 scripts/orchestrator_cycle_lock.py status [--json]

Коды возврата: **0** — можно работать (взят / уже мой / снят протухший / без защиты) ·
**3** — ЗАНЯТО живой сессией (вежливый выход, это НЕ ошибка) · **4** — release отклонён
(замок не мой — чужой не снимаем) · **2** — ошибка употребления.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIBLING = ROOT / "scripts" / "check_undelivered_work.py"

LOCK_DIRNAME = "orchestrator_cycle.lock"
HOLDER_FILE = "holder.json"

# Замок создан, holder.json ещё не дописан — окно в доли секунды. Меньше минуты считаем
# «кто-то прямо сейчас берёт», больше — брошенным огрызком.
WRITE_GRACE_SEC = 60.0

# «Живость не измерена» блокирует не дольше этого. То же окно, что у шагов 0a/0b.
DEFAULT_UNMEASURED_TTL_SEC = 3 * 3600.0

# Сколько последних сессий берём для оценки «типовой длительности цикла» и сколько
# замеров минимально требуем, чтобы вообще назвать число.
ETA_WINDOW = 12
ETA_MIN_SAMPLES = 3

ACQUIRED, ALREADY_MINE, BUSY, STALE_TAKEN, UNPROTECTED, FREE = (
    "acquired", "already_mine", "busy", "stale_taken", "unprotected", "free")
RELEASED, NOT_MINE, NOT_HELD = "released", "not_mine", "not_held"

# Внутренние состояния существующего замка (вход для `acquire`/`status`).
MINE, HELD_ALIVE, HELD_UNMEASURED, HELD_WRITING, ABANDONED_DEAD, ABANDONED_TTL, ABANDONED_JUNK = (
    "mine", "held_alive", "held_unmeasured", "held_writing",
    "abandoned_dead", "abandoned_ttl", "abandoned_junk")

_ABANDONED = {ABANDONED_DEAD, ABANDONED_TTL, ABANDONED_JUNK}

EXIT_OK, EXIT_USAGE, EXIT_BUSY, EXIT_NOT_MINE = 0, 2, 3, 4

_CYCLE_SESSION_RE = re.compile(r"^cycle-\d+$")


class LockUnavailable(RuntimeError):
    """Машинерия замка недоступна. НЕ повод останавливать цикл — повод сказать вслух."""


# ── общий код со шагами 0a/0b (единственный источник правды про активность сессии) ──

def load_sibling(path=SIBLING):
    """Модуль `check_undelivered_work` по явному пути (`scripts/` — не пакет).

    Логика «жива ли сессия» НЕ копируется намеренно: см. `check_card_claim.load_sibling`."""
    p = Path(path)
    if not p.exists():
        raise LockUnavailable(f"нет соседнего модуля шага 0a: {p}")
    spec = importlib.util.spec_from_file_location("_cycle_lock_sibling", p)
    if spec is None or spec.loader is None:
        raise LockUnavailable(f"не удалось загрузить {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("session_state", "read_entries", "shared_log", "ACTIVE", "UNKNOWN"):
        if not hasattr(mod, attr):
            raise LockUnavailable(f"{p}: нет ожидаемого символа {attr!r}")
    return mod


def lock_dir(sibling, start=ROOT):
    """(каталог замка, причина-если-он-НЕ-общий).

    Общий = рядом с общим журналом объявлений, т.е. в главном рабочем дереве. Причина не
    пустая ⇒ замок виден только этой сессии, то есть защиты нет; вызывающий обязан сказать
    это вслух, а не тихо взять локальный замок и считать себя защищённым."""
    log_path, err = sibling.shared_log(start)
    return Path(log_path).parent / LOCK_DIRNAME, err


# ── N параллельных держателей (owner-decision 26.08: «проверь и внедри, если
# безопасно» — ускорение разгрузки очереди) ──────────────────────────────────
# По умолчанию (`max_concurrent=1`) ничего не меняется: слот 0 — ТОТ ЖЕ путь, что и
# всегда (`LOCK_DIRNAME` без суффикса), а `acquire_any_slot`/`release_any_slot`/
# `status_all` при N=1 делают РОВНО один вызов существующих `acquire`/`release`/`status`
# на этот путь — байт-в-байт то же поведение, что до этой правки. Включается ОДНИМ
# флагом (`SPA_ORCHESTRATOR_MAX_CONCURRENT` / `--max-concurrent`), а не переписыванием
# формата замка: два параллельных цикла — это N НЕЗАВИСИМЫХ однослотовых замков рядом,
# каждый со своей семантикой mine/busy/abandoned/stale, ничего в которой не тронуто.
MAX_CONCURRENT_ENV = "SPA_ORCHESTRATOR_MAX_CONCURRENT"


def slot_lock_dir(sibling, slot: int, start=ROOT):
    """(каталог замка СЛОТА N, причина-если-не-общий). slot=0 — ``lock_dir`` без изменений
    (обратная совместимость с уже установленным на хосте прод-путём); slot>=1 — отдельный
    каталог рядом, тот же общий журнал определяет «общее ли дерево»."""
    base, err = lock_dir(sibling, start)
    if slot <= 0:
        return base, err
    return base.parent / f"{LOCK_DIRNAME}.{slot}", err


def acquire_any_slot(max_concurrent: int, record: dict, self_session, self_pid, sibling, *,
                     now, self_pid_start="", ps=None,
                     unmeasured_ttl_sec=DEFAULT_UNMEASURED_TTL_SEC, entries=(), start=ROOT):
    """Взять ПЕРВЫЙ свободный (или уже свой) слот из ``max_concurrent``.

    (вердикт, сообщение, номер_слота|None, путь|None). Слот пробуется по порядку — 0, 1, …
    — так что при ``max_concurrent=1`` это ровно один вызов ``acquire`` на исходный путь.
    Общий каталог не разрешился (``shared_err``) — это касается ВСЕХ слотов одинаково,
    вторую попытку не имеет смысла делать: сразу ``UNPROTECTED``."""
    last_verdict, last_msg = UNPROTECTED, "нет ни одного слота для проверки"
    for slot in range(max(1, int(max_concurrent))):
        path, shared_err = slot_lock_dir(sibling, slot, start)
        if shared_err:
            return (UNPROTECTED,
                    f"общий каталог замка не разрешён ({shared_err}) — замок был бы виден "
                    f"только этой сессии; цикл идёт БЕЗ защиты", None, path)
        verdict, msg = acquire(path, record, self_session, self_pid, sibling, now=now,
                               self_pid_start=self_pid_start, ps=ps,
                               unmeasured_ttl_sec=unmeasured_ttl_sec, entries=entries)
        if verdict != BUSY:
            return verdict, msg, slot, path
        last_verdict, last_msg = verdict, msg
    return (BUSY, f"все {max_concurrent} слот(ов) заняты. Последний: {last_msg}", None, None)


def release_any_slot(max_concurrent: int, self_session, self_pid, sibling, *,
                     self_pid_start="", start=ROOT):
    """Снять ТОТ слот (из ``max_concurrent``), который держит эта сессия.

    Проходит все слоты (дёшево — их не больше нескольких единиц) и снимает ровно тот,
    личность которого совпала; чужие/пустые слоты ``release`` уже не трогает сам по себе
    (см. докстринг ``release``). Держит не больше одного слота одновременно по построению
    ``acquire_any_slot``, но проход по всем — не догадка, а измерение."""
    released_any = False
    last_msg = "замка нет — снимать нечего"
    for slot in range(max(1, int(max_concurrent))):
        path, shared_err = slot_lock_dir(sibling, slot, start)
        if shared_err:
            continue
        verdict, msg = release(path, self_session, self_pid, self_pid_start)
        if verdict == RELEASED:
            released_any = True
            last_msg = msg
    return (RELEASED, last_msg) if released_any else (NOT_HELD, last_msg)


def status_all(max_concurrent: int, self_session, self_pid, sibling, *, now,
              self_pid_start="", ps=None, unmeasured_ttl_sec=DEFAULT_UNMEASURED_TTL_SEC,
              entries=(), start=ROOT):
    """[(слот, вердикт, сообщение, путь), …] — по каждому слоту, без единой мутации."""
    out = []
    for slot in range(max(1, int(max_concurrent))):
        path, shared_err = slot_lock_dir(sibling, slot, start)
        if shared_err:
            out.append((slot, UNPROTECTED, f"общий каталог не разрешён: {shared_err}", path))
            continue
        verdict, msg = status(path, self_session, self_pid, sibling, now=now,
                              self_pid_start=self_pid_start, ps=ps,
                              unmeasured_ttl_sec=unmeasured_ttl_sec, entries=entries)
        out.append((slot, verdict, msg, path))
    return out


# ── личность держателя ───────────────────────────────────────────────────────

def holder_record(session: str, pid, pid_start: str, now: datetime, extra=None) -> dict:
    """Запись держателя. Схема — подмножество записи журнала объявлений (`session`, `ts`,
    `session_pid`, `session_pid_start`), чтобы `session_state` читала её без переходников."""
    rec = {
        "session": str(session),
        "ts": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "cwd": os.getcwd(),
    }
    if pid is not None:
        rec["session_pid"] = int(pid)
    if pid_start:
        rec["session_pid_start"] = str(pid_start).strip()
    if extra:
        rec.update(extra)
    return rec


def same_identity(holder: dict, session: str, pid, pid_start: str = "") -> bool:
    """Держатель — это я? Совпадение по pid (сильный признак) либо по ярлыку сессии.

    pid важнее ярлыка: ярлык `cycle-<pid>` производный, но сессия может объявиться и под
    заданным `SPA_SESSION_ID`. Совпал pid — сверяем ещё и время старта, когда оно есть у
    ОБОИХ: без этого замок мёртвой сессии, чей pid ОС отдала мне, читался бы как «мой»,
    я бы работал под чужим замком и снял бы его в конце. Это ровно та проверка личности,
    ради которой шаги 0a/0b пишут `session_pid_start` рядом с pid."""
    if not isinstance(holder, dict):
        return False
    if pid is not None:
        try:
            same_pid = int(holder.get("session_pid")) == int(pid)
        except (TypeError, ValueError):
            same_pid = False
        if same_pid:
            theirs = str(holder.get("session_pid_start") or "").strip()
            mine = str(pid_start or "").strip()
            if theirs and mine and theirs != mine:
                return False             # тот же номер, ДРУГОЙ процесс
            return True
    s = str(holder.get("session") or "")
    return bool(session) and s == str(session)


# ── оценка «подожди N минут» — ЗАМЕРОМ, а не константой ─────────────────────

def typical_cycle_minutes(entries, exclude_session="", window=ETA_WINDOW,
                          min_samples=ETA_MIN_SAMPLES):
    """(медиана длительности цикла в минутах, число замеров) либо (None, число замеров).

    Замер, а не выдуманное число: длительность сессии = от её первого объявления до
    последнего (циклы объявляются на старте и по доставке). Сессии с одним объявлением
    длительности не дают — их не считаем нулём, а выбрасываем: ноль занизил бы медиану и
    ручной запуск читал бы «подожди ~0 мин» там, где ждать надо.

    Меньше `min_samples` замеров ⇒ None. Честное «оценки нет» лучше уверенного числа из двух
    точек (класс «выдуманные k», ADR-070 п.12)."""
    groups: dict[str, list[datetime]] = {}
    for e in entries or ():
        if not isinstance(e, dict):
            continue
        sess = str(e.get("session") or "")
        if not _CYCLE_SESSION_RE.match(sess) or sess == str(exclude_session):
            continue
        ts = _parse_ts(e.get("ts"))
        if ts is not None:
            groups.setdefault(sess, []).append(ts)

    spans = []
    for sess, stamps in groups.items():
        if len(stamps) < 2:
            continue
        spans.append((min(stamps), (max(stamps) - min(stamps)).total_seconds() / 60.0))
    spans.sort(key=lambda p: p[0])
    values = [v for _, v in spans[-window:] if v > 0]
    if len(values) < min_samples:
        return None, len(values)
    return statistics.median(values), len(values)


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def wait_hint(elapsed_min: float, median_min, samples: int) -> str:
    """Человеческий ответ ручному запуску на «сколько ждать»."""
    if median_min is None:
        return (f"идёт {elapsed_min:.0f} мин; оценки времени нет "
                f"(замеров длительности {samples}, нужно {ETA_MIN_SAMPLES})")
    left = median_min - elapsed_min
    if left >= 1:
        return (f"идёт {elapsed_min:.0f} мин — подожди ~{left:.0f} мин "
                f"(типовой цикл {median_min:.0f} мин по {samples} замерам)")
    return (f"идёт {elapsed_min:.0f} мин — это дольше типового цикла "
            f"({median_min:.0f} мин по {samples} замерам); освободится, как только закончит")


# ── чтение и классификация замка ─────────────────────────────────────────────

def read_holder(path: Path):
    """(запись держателя | None, причина-если-не-прочиталась)."""
    p = Path(path) / HOLDER_FILE
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "holder.json ещё не записан"
    except OSError as exc:
        return None, f"holder.json не читается: {exc}"
    try:
        obj = json.loads(raw)
    except ValueError:
        return None, "holder.json не разобран как JSON"
    if not isinstance(obj, dict):
        return None, "holder.json не является объектом"
    return obj, ""


def dir_age_seconds(path: Path, now: datetime):
    """Возраст каталога замка в секундах либо None (каталога нет / не читается)."""
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    return max(0.0, now.timestamp() - mtime)


def classify(holder, holder_err, age_sec, self_session, self_pid, sibling, *,
             self_pid_start="", ps=None, unmeasured_ttl_sec=DEFAULT_UNMEASURED_TTL_SEC):
    """(состояние, измерение словами) для СУЩЕСТВУЮЩЕГО замка. Чистая функция.

    Порядок намеренный: «это я» → «holder не прочитан» → живость держателя. Своё владение
    определяется до всех измерений — иначе повторный вызов в том же цикле (trap, ретрай)
    читал бы собственный живой замок как чужой и вежливо выходил бы посреди своей работы."""
    if holder is not None and same_identity(holder, self_session, self_pid, self_pid_start):
        return MINE, f"замок уже мой (сессия {holder.get('session')!r})"

    if holder is None:
        if age_sec is None:
            return HELD_WRITING, f"замок есть, {holder_err}; возраст не измерен — считаю занятым"
        if age_sec <= WRITE_GRACE_SEC:
            return HELD_WRITING, (f"{holder_err}; каталогу {age_sec:.0f}с — кто-то берёт замок "
                                  f"прямо сейчас")
        return ABANDONED_JUNK, (f"{holder_err}; каталогу {age_sec / 60.0:.0f} мин — держатель "
                                f"не назван, замок брошен")

    ps = ps or getattr(sibling, "_ps_lstart")
    # self_session="" намеренно: короткое замыкание «это текущая сессия» внутри session_state
    # здесь вредно — своё владение уже разобрано выше ПО ЛИЧНОСТИ, а не по ярлыку.
    state, why = sibling.session_state(holder, "", ps=ps)

    if state == sibling.ACTIVE:
        return HELD_ALIVE, why
    if state == sibling.UNKNOWN:
        if age_sec is not None and age_sec > unmeasured_ttl_sec:
            return ABANDONED_TTL, (f"{why}; замку {age_sec / 3600.0:.1f}ч — дольше окна "
                                   f"{unmeasured_ttl_sec / 3600.0:.1f}ч, считаю брошенным")
        return HELD_UNMEASURED, f"{why} — блокирую до истечения окна"
    return ABANDONED_DEAD, why


# ── действия ─────────────────────────────────────────────────────────────────

def _write_holder(path: Path, record: dict) -> None:
    """Атомарная запись holder.json внутрь уже созданного (то есть нашего) каталога."""
    target = Path(path) / HOLDER_FILE
    tmp = Path(path) / (HOLDER_FILE + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def _take_over(path: Path, record: dict):
    """Снять брошенный замок и взять заново. Возвращает True, если получилось."""
    try:
        shutil.rmtree(path)
    except OSError:
        return False
    try:
        os.mkdir(path)
    except OSError:
        return False                     # кто-то опередил — это не наш замок
    _write_holder(path, record)
    return True


def acquire(path: Path, record: dict, self_session, self_pid, sibling, *, now,
            self_pid_start="", ps=None, unmeasured_ttl_sec=DEFAULT_UNMEASURED_TTL_SEC,
            entries=()):
    """(вердикт, сообщение). Не бросает на занятом замке — занятость это исход, не авария."""
    path = Path(path)
    for attempt in (1, 2):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.mkdir(path)
        except FileExistsError:
            pass
        except OSError as exc:
            return UNPROTECTED, (f"каталог замка недоступен ({exc}) — цикл идёт БЕЗ защиты "
                                 f"от одновременного прогона")
        else:
            _write_holder(path, record)
            return ACQUIRED, "замок взят"

        holder, holder_err = read_holder(path)
        state, why = classify(holder, holder_err, dir_age_seconds(path, now),
                              self_session, self_pid, sibling,
                              self_pid_start=self_pid_start, ps=ps,
                              unmeasured_ttl_sec=unmeasured_ttl_sec)
        if state == MINE:
            return ALREADY_MINE, why
        if state in _ABANDONED:
            if attempt == 1 and _take_over(path, record):
                return STALE_TAKEN, f"снял брошенный замок и взял заново: {why}"
            continue                     # каталог увели из-под нас — перечитать
        elapsed = (dir_age_seconds(path, now) or 0.0) / 60.0
        median, samples = typical_cycle_minutes(entries, exclude_session=str(
            (holder or {}).get("session") or ""))
        who = str((holder or {}).get("session") or "неизвестная сессия")
        return BUSY, f"цикл уже идёт: {who} — {why}. {wait_hint(elapsed, median, samples)}"
    return BUSY, "замок перехватывается другим процессом — уступаю"


def release(path: Path, self_session, self_pid, self_pid_start=""):
    """(вердикт, сообщение). Чужой замок НЕ снимаем — иначе он не замок."""
    path = Path(path)
    if not path.exists():
        return NOT_HELD, "замка нет — снимать нечего"
    holder, holder_err = read_holder(path)
    if holder is not None and not same_identity(holder, self_session, self_pid, self_pid_start):
        return NOT_MINE, (f"замок держит {holder.get('session')!r}, а не "
                          f"{self_session!r} — чужой не снимаю")
    if holder is None:
        # Огрызок без держателя: снять его вправе кто угодно — он никого не представляет.
        pass
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return NOT_HELD, f"замок не снялся ({exc})"
    return RELEASED, "замок снят"


def status(path: Path, self_session, self_pid, sibling, *, now, self_pid_start="", ps=None,
           unmeasured_ttl_sec=DEFAULT_UNMEASURED_TTL_SEC, entries=()):
    """(вердикт, сообщение) без единой мутации — для ручного запуска и мониторинга."""
    path = Path(path)
    if not path.exists():
        return FREE, "замок свободен — цикл не идёт"
    holder, holder_err = read_holder(path)
    age = dir_age_seconds(path, now)
    state, why = classify(holder, holder_err, age, self_session, self_pid, sibling,
                          self_pid_start=self_pid_start, ps=ps,
                          unmeasured_ttl_sec=unmeasured_ttl_sec)
    if state == MINE:
        return ALREADY_MINE, why
    if state in _ABANDONED:
        return FREE, f"замок брошен и будет снят при следующем acquire: {why}"
    median, samples = typical_cycle_minutes(entries, exclude_session=str(
        (holder or {}).get("session") or ""))
    who = str((holder or {}).get("session") or "неизвестная сессия")
    return BUSY, f"цикл уже идёт: {who} — {why}. {wait_hint((age or 0.0) / 60.0, median, samples)}"


# ── CLI ──────────────────────────────────────────────────────────────────────

_EXIT_BY_VERDICT = {
    ACQUIRED: EXIT_OK, ALREADY_MINE: EXIT_OK, STALE_TAKEN: EXIT_OK,
    UNPROTECTED: EXIT_OK, FREE: EXIT_OK, RELEASED: EXIT_OK, NOT_HELD: EXIT_OK,
    BUSY: EXIT_BUSY, NOT_MINE: EXIT_NOT_MINE,
}


def _identity(args, sibling):
    """(сессия, pid, время старта pid). pid без подтверждённого старта личностью не считается —
    ровно то же правило, что у `log_session_change.durable_process`."""
    session = args.session or os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"
    raw = args.pid if args.pid is not None else os.environ.get("SPA_SESSION_PID")
    pid, start = None, ""
    if raw is not None and str(raw).strip().isdigit():
        candidate = int(str(raw).strip())
        if candidate > 1:
            rc, out = sibling._ps_lstart(candidate)
            if rc == 0 and str(out).strip():
                pid, start = candidate, str(out).strip()
    return session, pid, start


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("acquire", "release", "status"))
    ap.add_argument("--session", default="", help="ярлык сессии (умолчание — SPA_SESSION_ID)")
    ap.add_argument("--pid", default=None, help="долгоживущий pid (умолчание — SPA_SESSION_PID)")
    ap.add_argument("--unmeasured-ttl-hours", type=float,
                    default=DEFAULT_UNMEASURED_TTL_SEC / 3600.0)
    ap.add_argument(
        "--max-concurrent", type=int,
        default=int(os.environ.get(MAX_CONCURRENT_ENV, "1") or "1"),
        help=(f"сколько независимых слотов замка допустимо одновременно (умолчание 1 — "
              f"сегодняшнее поведение БЕЗ изменений; переопределяется {MAX_CONCURRENT_ENV})"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        sibling = load_sibling()
    except LockUnavailable as exc:
        return _emit(args, UNPROTECTED,
                     f"измерить занятость нечем ({exc}) — цикл идёт БЕЗ защиты", None)

    session, pid, start = _identity(args, sibling)
    max_concurrent = max(1, args.max_concurrent)

    entries = ()
    try:
        log_path, _ = sibling.shared_log()
        entries, _bad = sibling.read_entries(log_path, 400)
    except (OSError, ValueError):
        entries = ()                     # без оценки времени, но замок работает

    ttl = max(0.0, args.unmeasured_ttl_hours) * 3600.0

    # max_concurrent == 1 (умолчание) — путь НЕ ТРОНУТ: тот же вызов `lock_dir`/
    # `acquire`/`release`/`status` на тот же путь, что и до этой правки, буквально.
    # Ветвление на N слотов существует ТОЛЬКО когда владелец явно поднял лимит.
    if max_concurrent == 1:
        path, shared_err = lock_dir(sibling)
        if shared_err:
            return _emit(args, UNPROTECTED,
                         f"общий каталог замка не разрешён ({shared_err}) — замок был бы виден "
                         f"только этой сессии; цикл идёт БЕЗ защиты", str(path))
        if args.command == "acquire":
            verdict, msg = acquire(path, holder_record(session, pid, start, now),
                                   session, pid, sibling, now=now, self_pid_start=start,
                                   unmeasured_ttl_sec=ttl, entries=entries)
        elif args.command == "release":
            verdict, msg = release(path, session, pid, start)
        else:
            verdict, msg = status(path, session, pid, sibling, now=now, self_pid_start=start,
                                  unmeasured_ttl_sec=ttl, entries=entries)
        return _emit(args, verdict, msg, str(path))

    if args.command == "acquire":
        verdict, msg, slot, path = acquire_any_slot(
            max_concurrent, holder_record(session, pid, start, now), session, pid, sibling,
            now=now, self_pid_start=start, unmeasured_ttl_sec=ttl, entries=entries)
        extra = {"slot": slot} if args.json else None
        return _emit(args, verdict, msg, str(path) if path else None, extra=extra)
    if args.command == "release":
        verdict, msg = release_any_slot(max_concurrent, session, pid, sibling,
                                        self_pid_start=start)
        return _emit(args, verdict, msg, None)

    rows = status_all(max_concurrent, session, pid, sibling, now=now, self_pid_start=start,
                      unmeasured_ttl_sec=ttl, entries=entries)
    if args.json:
        print(json.dumps({"slots": [
            {"slot": s, "verdict": v, "message": m, "lock": str(p) if p else None}
            for s, v, m, p in rows]}, ensure_ascii=False))
        # код возврата статуса по слотам — 0, если хоть один свободен/мой; иначе занято
        return EXIT_OK if any(v != BUSY for _, v, _, _ in rows) else EXIT_BUSY
    for s, v, m, p in rows:
        mark = {BUSY: "⏸", UNPROTECTED: "⚠️"}.get(v, "✅")
        print(f"{mark} [слот {s}] [{v}] {m}")
    return EXIT_OK if any(v != BUSY for _, v, _, _ in rows) else EXIT_BUSY


def _emit(args, verdict, message, path, extra=None) -> int:
    code = _EXIT_BY_VERDICT.get(verdict, EXIT_OK)
    if args.json:
        payload = {"verdict": verdict, "message": message, "lock": path, "exit_code": code}
        if extra:
            payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False))
    else:
        mark = {BUSY: "⏸", NOT_MINE: "⛔", UNPROTECTED: "⚠️"}.get(verdict, "✅")
        slot_note = f" (слот {extra['slot']})" if extra and extra.get("slot") is not None else ""
        print(f"{mark} [{verdict}]{slot_note} {message}")
    return code


if __name__ == "__main__":
    sys.exit(main())
