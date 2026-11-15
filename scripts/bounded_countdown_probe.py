#!/usr/bin/env python3
"""ГДЕ ТЕРЯЕТСЯ ОТСЧЁТ предела у `_run_bounded` — ПРЯМОЙ замер механизма (ADR-1017).

[ADR-1015](../docs/decisions/ADR-1015-the-limit-is-blind-to-a-busy-module.md) § 7 (б)
назвал механизм слепоты ГИПОТЕЗОЙ: «`done.wait(timeout)` возвращает `True`, потому что к
моменту входа в ожидание событие УЖЕ установлено — главный поток не получает GIL у занятого
ребёнка». Числа гипотеза объясняла, прямого замера («когда именно начался отсчёт») не было, и
заказ G1005 п. 1 поставил порядок жёстко: сначала МЕХАНИЗМ, потом правка. Причина порядка
арифметическая: у отсчёта ТРИ кандидата на потерю, и чинятся они по-разному.

| где теряется | что это значит | что лечит |
|---|---|---|
| `late_in_start` | `Thread.start()` возвращает управление лишь ПОСЛЕ того, как ребёнок закончил: отсчёта не существует ВОВСЕ | отсчёт обязан начинаться ДО `start()` (дедлайн, а не длительность) |
| `late_before_wait` | `start()` вернулся вовремя, а до входа в `wait` главный поток не добрался | то же плюс: ожидание нельзя строить на «сколько осталось», не зная, сколько уже ушло |
| `on_time` | в `wait` вошли ВОВРЕМЯ, и слепота живёт ВНУТРИ ожидания | чинить сам примитив ожидания, а не моменты вокруг него |

Прибор только ЧИТАЕТ: `spa_core/analytics/signal_aggregator.py` не правится ни байтом, и этот
файл его не импортирует в money-path — он его ЗОВЁТ. Правка `_run_bounded` есть вход денежного
пути (ADR-1015 § 7а, карточка `inbox-predel-modulya-analitiki-slep-k-vychisly`) и делается
ОТДЕЛЬНО, с `pre_cutover_gate`.

Как замер остаётся замером НАСТОЯЩЕГО бегуна. Отметки снимаются не копией `_run_bounded`, а
подменой ЕДИНСТВЕННОЙ ссылки `signal_aggregator.threading` на записывающий шим: настоящая
`threading.Event`, настоящий daemon-поток, настоящий `done.wait` — меняется только то, что вокруг
их зова ставятся отметки времени. Своя копия тела означала бы класс ADR-913 (мерка, сверяющая
свои константы сама с собой).

**Шим обязан быть ПРОЗРАЧЕН, и это отдельный вопрос** (урок ADR-898: прибор, возмущающий свой
предмет, дважды дал несовместимые ответы на одном дереве). Поэтому рядом с подменённой сценой
идёт БОСАЯ — тот же `_run_bounded` без шима, — и если ответ о слепоте у них разный, вердикт есть
НЕ ИЗМЕРЕНО с названной причиной, а не число.

Код возврата: **0** — измерено (вердикт напечатан, в том числе находка: известная слепота есть
предмет замера, а не его провал — ADR-1015 § 7е о том, почему она не вправе краснить чужой
прогон) · **2** — НЕ ИЗМЕРЕНО с названной причиной. Третьего исхода «тихий ноль» у прибора нет.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading as _real_threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.analytics import signal_aggregator as _sa  # noqa: E402

# ─── Словарь ───────────────────────────────────────────────────────────────────

#: Род занятости ребёнка. Объявлен ЗНАЧЕНИЕМ (ADR-1015 § 2): «спит» и «считает» — разные
#: вопросы к пределу, и неизвестный род есть ОТКАЗ, а не молчаливая подстановка сна.
KINDS = ("busy", "sleep")

#: Место потери отсчёта у ОДНОЙ строки ряда. Порядок НЕ произволен — он есть порядок
#: дверей по времени, и каждая следующая спрашивается только если предыдущая не виновата:
#: `start()` стои́т раньше входа в ожидание, а вход в ожидание — раньше его исхода.
PLACES = ("late_in_start", "late_before_wait", "late_flag_read", "deadline_never_asked",
          "primitive_overstays", "within_limit")

#: Вердикт РЯДА. Шесть значений, и ни одно не сливается с другим: четыре места (единогласный
#: ряд) · смешанный ряд (это ИЗМЕРЕНО, а не «не измерено») · НЕ ИЗМЕРЕНО с причиной.
COUNTDOWN_VERDICTS = ("COUNTDOWN_LATE_IN_START", "COUNTDOWN_LATE_BEFORE_WAIT",
                      "COUNTDOWN_LATE_FLAG_READ", "COUNTDOWN_DEADLINE_NEVER_ASKED",
                      "COUNTDOWN_PRIMITIVE_OVERSTAYS", "COUNTDOWN_WITHIN_LIMIT",
                      "COUNTDOWN_LATE_MIXED", "COUNTDOWN_UNMEASURED")
(_V_START, _V_BEFORE_WAIT, _V_FLAG_READ, _V_NEVER_ASKED, _V_PRIMITIVE, _V_WITHIN,
 _V_MIXED, _V_UNMEASURED) = COUNTDOWN_VERDICTS
_PLACE_TO_VERDICT = dict(zip(PLACES, COUNTDOWN_VERDICTS))

#: Вердикт канарейки прозрачности шима.
CANARY_VERDICTS = ("CANARY_TRANSPARENT", "CANARY_PERTURBED", "CANARY_SUBJECT_ABSENT")
_C_OK, _C_PERTURBED, _C_ABSENT = CANARY_VERDICTS

#: Ответ ХОЗЯИНА на вопрос «кусает ли предел занятый модуль». Отдельный словарь, а не
#: переиспользование `BUSY_LIMIT_VERDICTS` переписи: там это ВЕРДИКТ СЦЕНЫ о бегуне, здесь —
#: свойство МАШИНЫ, измеренное босой дверью. Одно имя на два предмета и есть класс «одно имя —
#: один объект» (`.claude/rules/adapters.md`, цикл #274).
HOST_BUSY_VERDICTS = ("HOST_LIMIT_BLIND", "HOST_LIMIT_BITES", "HOST_LIMIT_UNMEASURED")
_H_BLIND, _H_BITES, _H_UNMEASURED = HOST_BUSY_VERDICTS

#: Сцена по умолчанию. Числа взяты у ADR-1015 § «Замер» (занят 0.05 с при пределе 0.001 с —
#: в 50× дольше предела, `ok` 18 из 20): прибор обязан смотреть на ТУ сцену, которая находку и
#: произвела, иначе он отвечает на свой вопрос.
BUSY_S = 0.05
BUSY_LIMIT_S = 0.001
BUSY_OVER_LIMIT_S = 2.00
SLEEP_S = 0.30
SLEEP_LIMIT_S = 0.01
SLEEP_OVER_LIMIT_S = 2.00
REPEATS = 10

#: Имена отметок. ПЕРВАЯ отметка побеждает: повторный зов двери момента не переписывает.
STAMPS = ("t_call", "t_start_enter", "t_start_exit", "t_wait_enter", "t_flag_read",
          "t_timed_acquire", "t_timed_acquire_done", "t_wait_exit", "t_child_enter",
          "t_child_exit", "t_set_enter", "t_set", "t_return")


class NotMeasured(RuntimeError):
    """Предпосылка замера не обеспечена. Поднимается, а не возвращается нулём."""


# ─── Запись отметок ────────────────────────────────────────────────────────────

class _Stamps:
    """Отметки одного зова `_run_bounded`, снятые ОДНОЙ дверью `time.perf_counter`.

    Два потока пишут в один словарь, и это безопасно по построению: каждое имя отметки
    принадлежит РОВНО одному потоку (`t_set`/`t_child_*` — ребёнку, остальные — главному),
    а `setdefault` у `dict` атомарен.
    """

    def __init__(self) -> None:
        self.rows: Dict[str, float] = {}
        self.wait_result: Optional[bool] = None
        #: Отметки у замка ожидания снимаются ТОЛЬКО внутри нашего `wait`: тот же
        #: `_allocate_lock` зовёт и `Thread.start()` (у него свой `Event._started`), и его
        #: замок к нашему вопросу не относится вовсе.
        self.in_wait = False
        #: БЫЛ ЛИ замок ожидания свободен в момент таймированного зова. Прямое наблюдение, а не
        #: вывод из отметок: отметка снимается на Python-строке ПЕРЕД зовом, и между нею и
        #: настоящим обращением к ОС главный поток успевает проголодать сколько угодно. Пока
        #: ответа нет, «срок не попал в ОС» и «примитив пересидел срок» неразличимы.
        self.free_at_ask: Optional[bool] = None

    def mark(self, name: str) -> None:
        if name not in STAMPS:
            raise NotMeasured(f"неизвестная отметка {name!r}: словарь отметок ЗАМКНУТ")
        self.rows.setdefault(name, time.perf_counter())


class _StampedFlag:
    """Дескриптор на `Event._flag`: отмечает ПЕРВОЕ чтение флага.

    Зачем отдельная отметка. Отметка `t_wait_enter` снимается перед зовом `Event.wait`, а
    РЕШЕНИЕ ожидание принимает позже — на строке `signaled = self._flag` внутри. Между этими
    двумя моментами главный поток исполняет Python-байткод (вход в `with self._cond`), и под
    занятым ребёнком он там и застревает. Без отметки чтения флага «вошли вовремя, а вернули
    True» объясняется ДВУМЯ разными механизмами, и правка лечила бы не ту половину:

    * флаг прочитан уже ПОСЛЕ установки ⇒ ожидание не ждало ни мгновения, и срок в него вообще
      не попал — тогда никакой `timeout` не спасает, отсчёт обязан существовать ДО `start()`;
    * флаг прочитан ДО установки ⇒ срок дошёл до примитива, и виноват сам примитив.

    Что это НЕ закрывает: имя `_flag` есть внутреннее устройство stdlib. Не прочитан ⇒ строка
    получает НЕ ИЗМЕРЕНО с названной причиной (отметки нет), а не молчаливую подстановку.
    """

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        if obj is None:
            return self
        obj._stamps.mark("t_flag_read")
        return obj._flag_value

    def __set__(self, obj: Any, value: Any) -> None:
        obj._flag_value = value


class _StampedEvent(_real_threading.Event):
    """НАСТОЯЩИЙ `threading.Event` с отметками. Ни `wait`, ни `set` не переписаны — они
    позваны у родителя, и вся машинерия ожидания остаётся стандартной.

    У установки флага ДВЕ отметки, и это не избыточность: `t_set_enter` — момент, когда ребёнок
    только собрался писать флаг, `t_set` — когда запись уже видна. Между ними флаг может быть
    прочитан, и утверждать в этом окне «уже стояло» или «ещё не стояло» было бы угадыванием;
    строка получает третий исход.
    """

    _flag = _StampedFlag()

    def __init__(self, stamps: _Stamps) -> None:
        self._stamps = stamps
        self._flag_value = False
        super().__init__()

    def set(self) -> None:
        self._stamps.mark("t_set_enter")
        super().set()
        self._stamps.mark("t_set")

    def wait(self, timeout: Optional[float] = None) -> bool:
        self._stamps.mark("t_wait_enter")
        self._stamps.in_wait = True
        try:
            got = super().wait(timeout)
        finally:
            self._stamps.in_wait = False
        self._stamps.mark("t_wait_exit")
        self._stamps.wait_result = bool(got)
        return got


class _RecordingThread:
    """Обёртка над НАСТОЯЩИМ потоком: ставит отметки вокруг `start()`.

    Предмет отметок — именно `start()`: в CPython он ЖДЁТ (`Thread._started.wait()`), пока
    ребёнок доложит о старте, а разбуженному главному потоку нужен GIL, которым владеет
    занятый ребёнок. Если `start()` возвращается уже после конца работы ребёнка, отсчёта не
    существует вовсе, и чинить `wait` было бы лечением не той половины.
    """

    def __init__(self, stamps: _Stamps, real_threading: Any, **kw: Any) -> None:
        self._stamps = stamps
        self._real = real_threading.Thread(**kw)

    def start(self) -> None:
        self._stamps.mark("t_start_enter")
        self._real.start()
        self._stamps.mark("t_start_exit")

    def join(self, timeout: Optional[float] = None) -> None:
        self._real.join(timeout)

    def is_alive(self) -> bool:
        return self._real.is_alive()


class _StampedWaiter:
    """Обёртка над замком, который `Condition.wait` создаёт себе на один зов.

    Зачем эта дверь. Строка `signaled = self._flag` — ещё не отсчёт: срок уходит в ОС только на
    ВТОРОМ зове `waiter.acquire(True, timeout)`, а между ними `Condition.wait` исполняет ещё
    четыре Python-строки (создать замок, занять его, встать в очередь ожидающих, отпустить
    замок условия). Под занятым ребёнком главный поток застревает и ТАМ, и тогда возможен исход,
    который не описывает ни одна прежняя гипотеза: очередь ожидающих занята ВОВРЕМЯ, событие
    приходит и ОТПУСКАЕТ замок, и лишь после этого главный поток доходит до `acquire` — тот
    берёт уже свободный замок МГНОВЕННО и отвечает «событие пришло», хотя срок не попадал в ОС
    ни на мгновение.

    Различить это от «примитив пересидел свой срок» можно только отметкой на самом зове, и
    различие не косметическое: в первом случае величина срока не значит ничего, во втором —
    виноват сам примитив.
    """

    def __init__(self, stamps: _Stamps, real: Any) -> None:
        self._stamps = stamps
        self._real = real
        self._acquires = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self._acquires += 1
        timed = self._acquires == 2  # второй зов и есть ТАЙМИРОВАННЫЙ (устройство Condition.wait)
        if not timed:
            return self._real.acquire(blocking, timeout)
        self._stamps.mark("t_timed_acquire")
        # НЕБЛОКИРУЮЩАЯ проба ПЕРЕД сроком. Семантику она не меняет ни на йоту: ровно то же
        # первым шагом делает сам CPython (`acquire_timed`: «first a simple non-blocking try
        # without releasing the GIL»). Зато она ОТВЕЧАЕТ на вопрос, который из отметок не
        # выводится: замок уже свободен ⇒ событие пришло ДО обращения к ОС, и срок туда не
        # попадал вовсе; замок занят ⇒ срок уходит в ОС, и дальше отвечает сама ОС.
        free = self._real.acquire(False)
        self._stamps.free_at_ask = bool(free)
        got = True if free else self._real.acquire(blocking, timeout)
        self._stamps.mark("t_timed_acquire_done")
        return got

    def release(self) -> None:
        self._real.release()

    def locked(self) -> bool:
        return self._real.locked()


class _ThreadingShim:
    """Подстановка вместо `signal_aggregator.threading` — ЕДИНСТВЕННАЯ дверь замера.

    Всё, о чём шим не знает, уходит настоящему модулю: подменять надо отметки, а не поведение.
    """

    def __init__(self, stamps: _Stamps, real: Any = _real_threading) -> None:
        self._stamps = stamps
        self._real = real

    def Event(self) -> _StampedEvent:  # noqa: N802 — имя двери принадлежит stdlib
        return _StampedEvent(self._stamps)

    def Thread(self, **kw: Any) -> _RecordingThread:  # noqa: N802 — то же
        return _RecordingThread(self._stamps, self._real, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# ─── Сцена ─────────────────────────────────────────────────────────────────────

def _work(kind: str, work_s: float, stamps: Optional[_Stamps]) -> Callable[[], Any]:
    """Тело «модуля» с ЗАДАННОЙ длительностью и ОБЪЯВЛЕННЫМ родом занятости."""
    if kind not in KINDS:
        raise NotMeasured(
            f"неизвестный род занятости {kind!r}: объявлены {KINDS}. Подстановка сна здесь "
            f"означала бы ответ на ДРУГОЙ вопрос — ADR-1015 § 4 показал, что у спящего и у "
            f"считающего модуля предел ведёт себя ПРОТИВОПОЛОЖНО")

    def fn() -> Any:
        if stamps is not None:
            stamps.mark("t_child_enter")
        if kind == "sleep":
            time.sleep(work_s)
        else:
            # Чистый Python-цикл: GIL он удерживает так же, как настоящий вычисляющий
            # модуль реестра, и именно этот род населяет реестр аналитики.
            deadline = time.perf_counter() + work_s
            spins = 0
            while time.perf_counter() < deadline:
                spins += 1
        if stamps is not None:
            stamps.mark("t_child_exit")
        return (0.0, "ok", "")

    return fn


def trace_once(*, kind: str, work_s: float, limit_s: float,
               runner: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Один зов НАСТОЯЩЕГО `_run_bounded` с отметками. Возвращает строку ряда."""
    call = runner if runner is not None else _sa._run_bounded
    stamps = _Stamps()
    shim = _ThreadingShim(stamps)
    saved_threading = _sa.threading
    # Замок ожидания создаёт САМ `Condition.wait` зовом модульной `threading._allocate_lock`,
    # и до него шим не достаёт: `Condition` живёт в настоящем модуле и смотрит на его глобаль.
    # Поэтому фабрика ставится у настоящего модуля и снимается в `finally`, а отметки она ставит
    # ТОЛЬКО внутри нашего ожидания (`stamps.in_wait`) — замок, который заводит себе
    # `Thread.start()`, к вопросу не относится.
    saved_alloc = _real_threading._allocate_lock

    def _alloc() -> Any:
        real = saved_alloc()
        return _StampedWaiter(stamps, real) if stamps.in_wait else real

    _sa.threading = shim
    _real_threading._allocate_lock = _alloc
    outcome, exc_name = "ok", None
    try:
        stamps.mark("t_call")
        try:
            call(_work(kind, work_s, stamps), limit_s, f"countdown-probe:{kind}")
        except _sa.FuturesTimeout:
            # Слово предела берётся У БЕГУНА (его же исключение), а не повторяется литералом.
            outcome = "timeout"
        except BaseException as err:  # noqa: BLE001 — исход сцены, а не предмет замера
            outcome, exc_name = "error", type(err).__name__
        stamps.mark("t_return")
    finally:
        _sa.threading = saved_threading
        _real_threading._allocate_lock = saved_alloc
    return _row(stamps, kind=kind, work_s=work_s, limit_s=limit_s,
                outcome=outcome, exc_name=exc_name)


def trace_bare(*, kind: str, work_s: float, limit_s: float,
               runner: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Тот же зов БЕЗ шима — канарейка прозрачности. Отметок нет, есть только исход."""
    call = runner if runner is not None else _sa._run_bounded
    outcome, exc_name = "ok", None
    t0 = time.perf_counter()
    try:
        call(_work(kind, work_s, None), limit_s, f"countdown-bare:{kind}")
    except _sa.FuturesTimeout:
        outcome = "timeout"
    except BaseException as err:  # noqa: BLE001
        outcome, exc_name = "error", type(err).__name__
    return {"kind": kind, "work_s": work_s, "limit_s": limit_s, "outcome": outcome,
            "exc": exc_name, "wall_s": round(time.perf_counter() - t0, 4), "shim": False}


def _row(stamps: _Stamps, *, kind: str, work_s: float, limit_s: float,
         outcome: str, exc_name: Optional[str]) -> Dict[str, Any]:
    r = stamps.rows
    base = r.get("t_call")

    def rel(name: str) -> Optional[float]:
        v, b = r.get(name), base
        if v is None or b is None:
            return None
        return round(v - b, 6)

    def gap(a: str, b: str) -> Optional[float]:
        x, y = r.get(a), r.get(b)
        if x is None or y is None:
            return None
        return round(y - x, 6)

    row: Dict[str, Any] = {
        "kind": kind, "work_s": work_s, "limit_s": limit_s, "outcome": outcome,
        "exc": exc_name, "shim": True, "wait_result": stamps.wait_result,
        # ПРЯМОЕ наблюдение, а не вывод из отметок (см. `_StampedWaiter`).
        "free_at_ask": stamps.free_at_ask,
        "at": {name: rel(name) for name in STAMPS},
        "start_cost_s": gap("t_start_enter", "t_start_exit"),
        "gap_to_wait_s": gap("t_start_exit", "t_wait_enter"),
        "child_work_s": gap("t_child_enter", "t_child_exit"),
        # СКОЛЬКО ПРОСТОЯЛО САМО ОЖИДАНИЕ. Это и есть число, которого не было у гипотезы
        # ADR-1015 § 7б: пока оно не названо, «вернуло True» объясняется и «флаг уже стоял при
        # входе», и «ожидание пересидело свой же срок» — а чинятся эти две половины по-разному.
        "wait_s": gap("t_wait_enter", "t_wait_exit"),
        # Сколько простоял САМ таймированный зов: отдельное число, потому что «ожидание
        # простояло» и «срок в ОС простоял» — разные утверждения, и первое включает в себя
        # голодание главного потока ДО зова.
        "timed_acquire_s": gap("t_timed_acquire", "t_timed_acquire_done"),
        "wall_s": gap("t_call", "t_return"),
    }
    row["place"], row["place_reason"] = classify_row(row, stamps.rows)
    return row


def classify_row(row: Dict[str, Any], raw: Dict[str, float]) -> Any:
    """ГДЕ потерян отсчёт у ОДНОЙ строки. Чистая функция — у неё нет ни часов, ни потоков.

    Пять дверей спрашиваются В ПОРЯДКЕ ВРЕМЕНИ, и это не стиль, а условие полезности ответа:
    каждая следующая спрашивается только если предыдущая не виновата, потому что ЧИНЯТСЯ они
    по-разному.

    * `late_in_start` — управление вернулось из `Thread.start()` уже после конца работы
      ребёнка. Отсчёта не существует ВОВСЕ, и правка ожидания тут бесполезна;
    * `late_before_wait` — `start()` вернулся вовремя, а зов ожидания случился после установки
      события. Это РОВНО гипотеза ADR-1015 § 7 (б) в её буквальном виде;
    * `late_flag_read` — ожидание ПОЗВАНО вовремя, но решение оно принимает на чтении флага, и
      флаг прочитан уже после установки. Срок в примитив не попал ни на мгновение ⇒ менять
      величину срока бессмысленно;
    * `wait_overstays` — флаг прочитан ДО установки, то есть срок до примитива дошёл, и всё
      равно вернулось «событие пришло» позже срока. Тогда виноват сам примитив;
    * `within_limit` — ребёнок успел в отведённый срок, и `ok` ЗАКОНЕН. Ряд, целиком такой,
      предметом не является, и прибор обязан сказать это, а не выдать «потерю».

    Границы берутся КОНСЕРВАТИВНО: «уже установлено» судится по `t_set` (запись видна), «ещё не
    установлено» — по `t_set_enter` (запись не начата). Окно между ними ответом не является.
    """
    t_set, t_set_enter = raw.get("t_set"), raw.get("t_set_enter")
    t_start_exit, t_wait_enter = raw.get("t_start_exit"), raw.get("t_wait_enter")
    t_flag = raw.get("t_flag_read")
    limit = row.get("limit_s")
    missing = [n for n, v in (("t_set", t_set), ("t_set_enter", t_set_enter),
                              ("t_start_exit", t_start_exit), ("t_wait_enter", t_wait_enter),
                              ("limit_s", limit)) if v is None]
    if missing:
        return None, (
            f"НЕ ИЗМЕРЕНО: нет отметок {missing}. Отсутствие отметок установки ЗАКОННО у строки, "
            f"где предел прозвучал: ребёнок к моменту вердикта ещё работает, и сочинить ему "
            f"конец значило бы ответить за него")
    if t_start_exit >= t_set:
        return PLACES[0], (
            f"`Thread.start()` держал главный поток {round(t_start_exit - raw['t_start_enter'], 6)} с "
            f"и вернул управление ПОСЛЕ конца работы ребёнка "
            f"({round(t_set - raw['t_start_enter'], 6)} с от зова `start`) — отсчёта не существует вовсе")
    if t_wait_enter >= t_set:
        return PLACES[1], (
            f"`start()` вернулся вовремя, но зов ожидания случился через "
            f"{round(t_wait_enter - t_start_exit, 6)} с после него, когда событие уже установлено "
            f"(гипотеза ADR-1015 § 7б в буквальном виде)")
    if t_flag is None:
        return None, (
            "НЕ ИЗМЕРЕНО: чтение флага события не отмечено — `Event.wait` принял решение не на "
            "`_flag`, то есть устройство примитива в этом интерпретаторе иное, чем предполагает "
            "прибор; молчаливая подстановка здесь назвала бы механизм, которого не видели")
    if t_flag >= t_set:
        return PLACES[2], (
            f"ожидание позвано за {round(t_set - t_wait_enter, 6)} с до конца работы ребёнка, но "
            f"флаг события прочитан лишь через {round(t_flag - t_wait_enter, 6)} с — уже после "
            f"установки: срок {limit} с не попал в примитив ни на мгновение, ожидание простояло "
            f"{row.get('wait_s')} с и вернуло {row.get('wait_result')!r}")
    if t_flag > t_set_enter:
        return None, (
            f"НЕ ИЗМЕРЕНО: флаг прочитан ВНУТРИ окна записи "
            f"({round(t_flag - t_set_enter, 6)} с после её начала и до её видимости) — утверждать "
            f"«уже стояло» или «ещё не стояло» здесь значило бы угадывать")
    if t_set_enter <= t_wait_enter + limit:
        return PLACES[5], (
            f"ребёнок закончил через {round(t_set_enter - t_wait_enter, 6)} с после зова ожидания, "
            f"то есть В ПРЕДЕЛАХ срока {limit} с — исход `ok` здесь законен")
    t_acq = raw.get("t_timed_acquire")
    free = row.get("free_at_ask")
    if t_acq is None or free is None:
        return None, (
            "НЕ ИЗМЕРЕНО: таймированный зов замка ожидания не наблюдён — `Condition.wait` ушёл в "
            "ОС не через второй `acquire`, то есть устройство примитива в этом интерпретаторе "
            "иное, чем предполагает прибор")
    if free:
        return PLACES[3], (
            f"срок {limit} с НЕ ПОПАЛ В ОС ВОВСЕ: флаг прочитан вовремя (за "
            f"{round(t_set_enter - t_flag, 6)} с до установки), а когда главный поток через "
            f"{round(t_acq - t_flag, 6)} с добрался до таймированного зова, замок ожидания был "
            f"УЖЕ СВОБОДЕН — событие успело прийти и отпустить его, и зов ответил «событие "
            f"пришло» мгновенно")
    return PLACES[4], (
        f"срок {limit} с ПОПАЛ в ОС (замок в момент зова был ЗАНЯТ) за "
        f"{round(t_set_enter - t_acq, 6)} с до события, истекал за "
        f"{round(t_set_enter - t_acq - limit, 6)} с до него, а зов простоял "
        f"{row.get('timed_acquire_s')} с и вернул {row.get('wait_result')!r} ⇒ свой срок "
        f"пересидел САМ примитив")


def primitive_control(*, kind: str, work_s: float, limit_s: float,
                      repeats: int) -> List[Dict[str, Any]]:
    """НЕЗАВИСИМЫЙ замер САМОГО примитива: ни бегуна, ни шима, ни наблюдателя в сцене нет.

    Вердикт `primitive_overstays` есть утверждение о stdlib, и подтверждать его тем же прибором,
    который его произвёл, значило бы сверять мерку с собой (класс ADR-913). Поэтому сцена здесь
    голая: занятый замок, рядом поток, который либо СЧИТАЕТ, либо СПИТ `work_s`, а затем замок
    отпускает; главный поток зовёт `lock.acquire(True, limit_s)` и смотрит на ответ и на часы.

    Ответ ряда двузначен по построению, и оба значения названы:
    * `honoured` — вернулось «не взял»: срок соблюдён;
    * `overstay` — вернулось «взял» ПОЗЖЕ срока: примитив ответил об успехе после своего срока;
    * `instant` — вернулось «взял» В ПРЕДЕЛАХ срока: сцена не поймала окно (замок освободился
      раньше, чем главный поток дошёл до зова), и это не ответ о сроке, а промах сцены.
    """
    if kind not in KINDS:
        raise NotMeasured(f"неизвестный род занятости {kind!r}: объявлены {KINDS}")
    rows: List[Dict[str, Any]] = []
    for _ in range(max(0, repeats)):
        lock = _real_threading.Lock()
        lock.acquire()
        started = _real_threading.Event()

        def holder() -> None:
            started.set()
            if kind == "sleep":
                time.sleep(work_s)
            else:
                deadline = time.perf_counter() + work_s
                while time.perf_counter() < deadline:
                    pass
            lock.release()

        th = _real_threading.Thread(target=holder, daemon=True, name="countdown-primitive")
        th.start()
        started.wait(5.0)
        t0 = time.perf_counter()
        got = lock.acquire(True, limit_s)
        seconds = time.perf_counter() - t0
        if got:
            lock.release()
        th.join(5.0)
        rows.append({"kind": kind, "work_s": work_s, "limit_s": limit_s, "got": bool(got),
                     "seconds": round(seconds, 6),
                     "place": _primitive_place(bool(got), seconds, limit_s),
                     "over_x": round(seconds / limit_s, 1) if limit_s > 0 else None})
    return rows


def _primitive_place(got: bool, seconds: float, limit_s: float) -> str:
    """Исход ОДНОГО зова голой сцены. Вынесено в чистую функцию ради сцены: три её ветки
    различаются входами, а не удачей с GIL, и мутация любой из них краснит свою проверку."""
    if not got:
        return "honoured"
    return "overstay" if seconds > limit_s else "instant"


# ─── Вердикты ──────────────────────────────────────────────────────────────────

def canary(shim_rows: List[Dict[str, Any]], bare_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Возмущает ли шим свой предмет — ОТДЕЛЬНЫЙ вопрос, и он задаётся ДО вердикта.

    Предмет механизма существует только там, где предел СЛЕП, то есть где занятый модуль
    получил `ok` вопреки превышению. Босой ряд без единого `ok` означает, что на этом хосте
    предмета в сцене нет (а не что механизм найден), и ответ обязан быть третьим исходом.
    """
    bare_ok = sum(1 for r in bare_rows if r["outcome"] == "ok")
    shim_ok = sum(1 for r in shim_rows if r["outcome"] == "ok")
    doc = {"bare_ok_n": bare_ok, "bare_n": len(bare_rows),
           "shim_ok_n": shim_ok, "shim_n": len(shim_rows), "reason": None}
    if not bare_rows or not shim_rows:
        return {**doc, "verdict": _C_ABSENT,
                "reason": "ряд пуст: сравнивать нечего, и ноль повторов ответом не является"}
    if bare_ok == 0:
        return {**doc, "verdict": _C_ABSENT, "reason": (
            f"босой ряд не дал ни одного `ok` ({len(bare_rows)} повторов): на этом хосте предел "
            f"кусает занятый модуль, предмета механизма в сцене НЕТ")}
    if shim_ok == 0:
        return {**doc, "verdict": _C_PERTURBED, "reason": (
            f"босой ряд слеп {bare_ok} из {len(bare_rows)}, а под шимом слепых 0 — прибор "
            f"ПЕРЕВЕРНУЛ свой предмет, и отметки описывают его самого")}
    return {**doc, "verdict": _C_OK}


def host_busy_limit(*, work_s: float = BUSY_S, limit_s: float = BUSY_LIMIT_S,
                    repeats: int = REPEATS,
                    runner: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Кусает ли предел ЗАНЯТЫЙ модуль НА ЭТОМ ХОЗЯИНЕ — ОТДЕЛЬНЫЙ вопрос, задаваемый ДО сцены.

    Дверь написана по карточке `inbox-proverka-slepoty-predela-zakrepila-otvet`: утверждение
    «предел слеп» ЕСТЬ свойство хозяина, а не кода. Замер ADR-1015/1017: на macOS (CPython 3.13)
    предел слеп к вычисляющему модулю, на `ubuntu-latest` (CPython 3.11) тот же настоящий бегун
    предел КУСАЕТ. Проверка, закрепившая ответ одной машины, краснеет от смены ХОЗЯИНА — и
    красный по известной причине перестаёт быть сигналом (`.claude/rules/deployment.md`).

    Дверь ОДНА и БОСАЯ (`trace_bare`): шима здесь нет намеренно — вопрос о хозяине не должен
    зависеть от прибора, возмущающего свой предмет (урок ADR-898). Своей копии зова у двери нет:
    она звёт `trace_bare`, то есть НАСТОЯЩИЙ `_run_bounded`.

    Три исхода различимы (инв. #17) и ни один не сливается с другим:

    * ``HOST_LIMIT_BLIND`` — хотя бы один `ok` при превышении: предмет слепоты НА ЭТОМ ХОЗЯИНЕ
      ЕСТЬ. Исход гонки не детерминирован, поэтому ответом является ДОЛЯ, а не одно наблюдение;
    * ``HOST_LIMIT_BITES`` — ПОЛНЫЙ ряд без единого `ok`: на этом хозяине предел кусает, и
      предмета слепоты в сцене НЕТ. Это НЕ находка о коде и НЕ провал — это третий исход
      (та же форма, что `CANARY_SUBJECT_ABSENT`);
    * ``HOST_LIMIT_UNMEASURED`` — ряд пуст, неполон или в нём есть строка `error`. **Пустой ряд
      НЕ есть `BITES`:** ноль наблюдений и ноль слепых строк — разные вещи, и выдать первое за
      второе значило бы объявить предел кусающим, ничего не измерив.
    """
    if repeats < 1:
        return {"verdict": _H_UNMEASURED, "ok_n": None, "timeout_n": None, "n": 0,
                "asked_n": repeats, "over_x": None, "rows": [],
                "reason": (f"повторов запрошено {repeats}: ряда нет, а ноль наблюдений "
                           f"ответом о хозяине не является")}
    over_x = round(work_s / limit_s, 1) if limit_s > 0 else None
    rows: List[Dict[str, Any]] = []
    try:
        for _ in range(repeats):
            rows.append(trace_bare(kind="busy", work_s=work_s, limit_s=limit_s, runner=runner))
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return {"verdict": _H_UNMEASURED, "ok_n": None, "timeout_n": None, "n": len(rows),
                "asked_n": repeats, "over_x": over_x, "rows": rows,
                "reason": f"ряд не собран: {type(exc).__name__}: {exc}"}
    errors = [r for r in rows if r["outcome"] == "error"]
    doc = {"ok_n": sum(1 for r in rows if r["outcome"] == "ok"),
           "timeout_n": sum(1 for r in rows if r["outcome"] == "timeout"),
           "n": len(rows), "asked_n": repeats, "over_x": over_x, "rows": rows}
    if errors or len(rows) != repeats:
        return {**doc, "verdict": _H_UNMEASURED, "ok_n": None, "timeout_n": None,
                "reason": (f"ряд НЕПОЛОН или испорчен: собрано {len(rows)} из {repeats}, "
                           f"строк `error` {len(errors)}"
                           + (f" ({errors[0].get('exc')})" if errors else "")
                           + " — доля по обрезку есть ответ о другом ряде")}
    if doc["ok_n"] > 0:
        return {**doc, "verdict": _H_BLIND, "reason": (
            f"предел СЛЕП на этом хозяине: `ok` {doc['ok_n']} из {len(rows)} при превышении "
            f"{over_x}× (занят {work_s} с при пределе {limit_s} с)")}
    return {**doc, "verdict": _H_BITES, "reason": (
        f"предел КУСАЕТ на этом хозяине: ни одного `ok` в {len(rows)} повторах при превышении "
        f"{over_x}× — предмета слепоты в сцене НЕТ, и это третий исход, а не падение")}


def verdict_of_series(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Вердикт РЯДА по строкам, где предел оказался слеп.

    Предмет существует только у слепых строк: там, где предел прозвучал, отсчёт не терялся и
    спрашивать «где он потерян» нечего. Единогласие обязательно НАЗЫВАТЬСЯ — исход гонки за GIL
    не детерминирован (ADR-1015 § 4), и «в большинстве вот тут» ответом не является.
    """
    blind = [r for r in rows if r["outcome"] == "ok"]
    places = {p: sum(1 for r in blind if r["place"] == p) for p in PLACES}
    unknown = [r["place_reason"] for r in blind if r["place"] is None]
    doc = {"blind_n": len(blind), "total_n": len(rows), "places": places,
           "unmeasured_rows": len(unknown), "reason": None}
    if not rows:
        return {**doc, "verdict": _V_UNMEASURED,
                "reason": "ряд пуст: ноль наблюдений ответом не является"}
    if not blind:
        return {**doc, "verdict": _V_UNMEASURED, "reason": (
            f"ни одной слепой строки из {len(rows)}: вопрос «где потерян отсчёт» задан ряду, в "
            f"котором отсчёт не терялся")}
    if unknown:
        return {**doc, "verdict": _V_UNMEASURED,
                "reason": f"строк без отметок {len(unknown)} из {len(blind)}: {unknown[0]}"}
    hit = [p for p in PLACES if places[p]]
    if len(hit) > 1:
        return {**doc, "verdict": _V_MIXED, "reason": (
            "ряд НЕ единогласен: " + " · ".join(f"{p}={places[p]}" for p in hit) +
            " — место потери зависит от того, как в этот раз разошёлся GIL, и одна правка "
            "закроет не весь класс")}
    return {**doc, "verdict": _PLACE_TO_VERDICT[hit[0]]}


def measure(*, busy_s: float = BUSY_S, busy_limit_s: float = BUSY_LIMIT_S,
            busy_over_limit_s: float = BUSY_OVER_LIMIT_S, sleep_s: float = SLEEP_S,
            sleep_limit_s: float = SLEEP_LIMIT_S,
            sleep_over_limit_s: float = SLEEP_OVER_LIMIT_S, repeats: int = REPEATS,
            trace_door: Optional[Callable[..., Dict[str, Any]]] = None,
            bare_door: Optional[Callable[..., Dict[str, Any]]] = None,
            primitive_door: Optional[Callable[..., List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Пять сторон, и у КАЖДОГО печатаемого ответа есть свой положительный контроль.

    | сторона | на какой вопрос отвечает |
    |---|---|
    | `busy_under_limit` | ПРЕДМЕТ: где теряется отсчёт у занятого вычислением ребёнка |
    | `busy_over_limit` | зависит ли потеря от ВЕЛИЧИНЫ предела (контроль независимости) |
    | `sleep_under_limit` | умеет ли прибор увидеть ЧЕСТНО сработавший предел |
    | `sleep_over_limit` | умеет ли прибор увидеть ЗАКОННЫЙ `ok` (`within_limit`) |
    | `bare_busy_under_limit` | канарейка: не перевернул ли шим свой предмет |
    """
    if repeats < 1:
        empty_series = {"verdict": _V_UNMEASURED, "blind_n": 0, "total_n": 0,
                        "places": {p: 0 for p in PLACES}, "unmeasured_rows": 0,
                        "reason": f"повторов {repeats}"}
        return {"verdict": _V_UNMEASURED,
                "canary": {"verdict": _C_ABSENT, "reason": f"повторов {repeats}"},
                "sides": {}, "series": empty_series,
                "controls": {"limit_honoured": {"ok": False, "reason": f"повторов {repeats}"},
                             "legal_ok": {"ok": False, "reason": f"повторов {repeats}"},
                             "primitive_quiet": {"ok": False, "reason": f"повторов {repeats}"}},
                "primitive": {"total_n": 0, "places": {}, "overstay_n": 0, "worst_s": None,
                              "worst_over_x": None, "rows": [], "quiet_rows": []},
                "scene": {"busy_s": busy_s, "busy_limit_s": busy_limit_s,
                          "busy_over_limit_s": busy_over_limit_s, "sleep_s": sleep_s,
                          "sleep_limit_s": sleep_limit_s, "sleep_over_limit_s": sleep_over_limit_s,
                          "repeats": repeats, "over_x": None,
                          "switch_interval_s": sys.getswitchinterval()},
                "unmeasured_reason": (
                    f"повторов {repeats}: ряд из нуля наблюдений ответом не является")}
    tr = trace_door or trace_once
    ba = bare_door or trace_bare
    sides: Dict[str, List[Dict[str, Any]]] = {
        "busy_under_limit": [tr(kind="busy", work_s=busy_s, limit_s=busy_limit_s)
                             for _ in range(repeats)],
        "busy_over_limit": [tr(kind="busy", work_s=busy_s, limit_s=busy_over_limit_s)
                            for _ in range(repeats)],
        "sleep_under_limit": [tr(kind="sleep", work_s=sleep_s, limit_s=sleep_limit_s)
                              for _ in range(repeats)],
        "sleep_over_limit": [tr(kind="sleep", work_s=sleep_s, limit_s=sleep_over_limit_s)
                             for _ in range(repeats)],
        "bare_busy_under_limit": [ba(kind="busy", work_s=busy_s, limit_s=busy_limit_s)
                                  for _ in range(repeats)],
    }
    # Дверь НЕЗАВИСИМОЙ сцены инъектируется ровно для того, чтобы у перекрёстной сверки ниже
    # была РАЗЛИЧАЮЩАЯ сцена: ветка, которой нечем показать спор, не убивается никакой
    # мутацией (урок ADR-1015, мутант M12).
    pc = primitive_door or primitive_control
    prim = {"busy": pc(kind="busy", work_s=busy_s, limit_s=busy_limit_s, repeats=repeats),
            "sleep": pc(kind="sleep", work_s=sleep_s, limit_s=sleep_limit_s, repeats=repeats)}
    can = canary(sides["busy_under_limit"], sides["bare_busy_under_limit"])
    series = verdict_of_series(sides["busy_under_limit"])
    controls = {"limit_honoured": _control_limit_honoured(sides["sleep_under_limit"]),
                "legal_ok": _control_legal_ok(sides["sleep_over_limit"]),
                "primitive_quiet": _control_primitive_quiet(prim["sleep"])}
    doc: Dict[str, Any] = {"sides": sides, "canary": can, "series": series,
                           "controls": controls, "primitive": _primitive_verdict(prim),
                           "scene": {"busy_s": busy_s, "busy_limit_s": busy_limit_s,
                                     "busy_over_limit_s": busy_over_limit_s,
                                     "sleep_s": sleep_s, "sleep_limit_s": sleep_limit_s,
                                     "sleep_over_limit_s": sleep_over_limit_s,
                                     "repeats": repeats,
                                     "over_x": round(busy_s / busy_limit_s, 1) if busy_limit_s else None,
                                     "switch_interval_s": sys.getswitchinterval()},
                           "unmeasured_reason": None}
    if can["verdict"] != _C_OK:
        return {**doc, "verdict": _V_UNMEASURED,
                "unmeasured_reason": f"канарейка прозрачности: {can['reason']}"}
    broken = [name for name, c in controls.items() if not c["ok"]]
    if broken:
        return {**doc, "verdict": _V_UNMEASURED, "unmeasured_reason": (
            "положительный контроль не держится (" + ", ".join(broken) + "): "
            + " · ".join(controls[name]["reason"] for name in broken))}
    # ПЕРЕКРЁСТНАЯ СВЕРКА: утверждение о примитиве обязано держаться и у НЕЗАВИСИМОЙ сцены.
    # Разошлись — ответа нет ни у одной: «мой прибор говорит, а голая сцена нет» есть ровно та
    # мерка, что сверяет себя с собой.
    pv = doc["primitive"]
    if series["verdict"] == _V_PRIMITIVE and pv["overstay_n"] == 0:
        return {**doc, "verdict": _V_UNMEASURED, "unmeasured_reason": (
            f"два наблюдения СПОРЯТ: ряд под прибором дал `{_V_PRIMITIVE}` "
            f"{series['places']['primitive_overstays']}/{series['blind_n']}, а НЕЗАВИСИМАЯ голая "
            f"сцена не дала ни одного пересиживания из {pv['total_n']} "
            f"({pv['places']}) — пока они не согласны, утверждение о примитиве не доказано")}
    return {**doc, "verdict": series["verdict"],
            "unmeasured_reason": series.get("reason") if series["verdict"] == _V_UNMEASURED else None}


def _primitive_verdict(prim: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Сводка НЕЗАВИСИМОЙ сцены по занятому соседу."""
    rows = prim.get("busy") or []
    places = {"honoured": 0, "overstay": 0, "instant": 0}
    for r in rows:
        places[r["place"]] = places.get(r["place"], 0) + 1
    overs = [r["seconds"] for r in rows if r["place"] == "overstay"]
    return {"total_n": len(rows), "places": places, "overstay_n": places["overstay"],
            "worst_s": round(max(overs), 6) if overs else None,
            "worst_over_x": max((r["over_x"] for r in rows if r["place"] == "overstay"),
                                default=None),
            "rows": rows, "quiet_rows": prim.get("sleep") or []}


def _control_primitive_quiet(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Положительный контроль НЕЗАВИСИМОЙ сцены: у СПЯЩЕГО соседа срок обязан соблюдаться.

    Без него «примитив пересиживает» было бы утверждением прибора, который не видел ни одного
    соблюдённого срока, то есть не умеет различить два ответа.
    """
    if not rows:
        return {"ok": False, "honoured_n": 0, "total_n": 0,
                "reason": "ряд контроля пуст: ноль наблюдений контролем не является"}
    hon = sum(1 for r in rows if r["place"] == "honoured")
    ok = hon == len(rows)
    return {"ok": ok, "honoured_n": hon, "total_n": len(rows),
            "reason": None if ok else (
                f"у СПЯЩЕГО соседа срок соблюдён {hon} из {len(rows)} — голая сцена не умеет "
                f"показать соблюдённый срок, и её «пересиживание» ничего не доказывает")}


def _control_limit_honoured(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Умеет ли прибор увидеть ЧЕСТНО сработавший предел — на СПЯЩЕМ ребёнке.

    Спящий ребёнок GIL не держит, поэтому срок обязан прозвучать: исход — слово предела у
    бегуна, а ожидание обязано вернуть «события не было». Прибор, умеющий только один ответ,
    есть украшение (`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).
    """
    if not rows:
        return {"ok": False, "timeout_n": 0, "false_n": 0, "total_n": 0,
                "reason": "ряд контроля пуст: ноль наблюдений контролем не является"}
    to = sum(1 for r in rows if r["outcome"] == "timeout")
    fa = sum(1 for r in rows if r["wait_result"] is False)
    ok = to == len(rows) and fa == len(rows)
    return {"ok": ok, "timeout_n": to, "false_n": fa, "total_n": len(rows),
            "reason": None if ok else (
                f"у СПЯЩЕГО ребёнка предел прозвучал {to} из {len(rows)}, ожидание вернуло "
                f"«события не было» {fa} из {len(rows)} — прибор не показал честный отсчёт, и "
                f"его «потеря» ничего не доказывает")}


def _control_legal_ok(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Умеет ли прибор увидеть ЗАКОННЫЙ `ok` — спящий ребёнок при пределе ВЫШЕ сна.

    Без этой стороны `within_limit` был бы значением, которого прибор не напечатал ни разу, —
    то есть словом, а не исходом.
    """
    if not rows:
        return {"ok": False, "within_n": 0, "ok_n": 0, "total_n": 0,
                "reason": "ряд контроля пуст: ноль наблюдений контролем не является"}
    within = sum(1 for r in rows if r["place"] == PLACES[5])
    oks = sum(1 for r in rows if r["outcome"] == "ok")
    good = within == len(rows) and oks == len(rows)
    return {"ok": good, "within_n": within, "ok_n": oks, "total_n": len(rows),
            "reason": None if good else (
                f"при пределе ВЫШЕ сна законных `ok` {oks} из {len(rows)}, строк "
                f"`{PLACES[5]}` {within} из {len(rows)} — значение `{PLACES[5]}` прибор "
                f"напечатать не умеет")}


# ─── Печать ────────────────────────────────────────────────────────────────────

def _span(rows: List[Dict[str, Any]], key: str) -> str:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return "НЕ ИЗМЕРЕНО"
    return f"{min(vals):.6f} … {max(vals):.6f} с"


def render(doc: Dict[str, Any]) -> str:
    """Печать вырезает свой предмет по ЗАГОЛОВКУ строки (урок ADR-1015 § 7): утверждение,
    ищущее подстроку по всей печати, отдаёт подтверждение даром."""
    sc = doc["scene"]
    out = [f"ГДЕ ТЕРЯЕТСЯ ОТСЧЁТ: {doc['verdict']}",
           f"СЦЕНА: занят {sc['busy_s']} с при пределе {sc['busy_limit_s']} с "
           f"(в {sc['over_x']}× дольше), повторов {sc['repeats']}, "
           f"интервал переключения {sc['switch_interval_s']} с"]
    can = doc["canary"]
    out.append(f"КАНАРЕЙКА: {can['verdict']} — слепых босых {can.get('bare_ok_n')}/"
               f"{can.get('bare_n')}, под шимом {can.get('shim_ok_n')}/{can.get('shim_n')}"
               + (f" · {can['reason']}" if can.get("reason") else ""))
    for name, title in (("limit_honoured", "КОНТРОЛЬ ЧЕСТНОГО ПРЕДЕЛА"),
                        ("legal_ok", "КОНТРОЛЬ ЗАКОННОГО OK"),
                        ("primitive_quiet", "КОНТРОЛЬ ТИХОГО ПРИМИТИВА")):
        c = (doc.get("controls") or {}).get(name) or {}
        out.append(f"{title}: {'держится' if c.get('ok') else 'НЕ ДЕРЖИТСЯ'}"
                   + (f" · {c['reason']}" if c.get("reason") else ""))
    pv = doc.get("primitive") or {}
    out.append(f"НЕЗАВИСИМЫЙ ПРИМИТИВ: пересиживаний {pv.get('overstay_n')}/{pv.get('total_n')} "
               f"· {pv.get('places')} · худшее {pv.get('worst_s')} с "
               f"(в {pv.get('worst_over_x')}× срока)")
    ser = doc["series"]
    out.append(f"РЯД: слепых {ser['blind_n']}/{ser['total_n']} · "
               + " · ".join(f"{p}={ser['places'][p]}" for p in PLACES)
               + (f" · {ser['reason']}" if ser.get("reason") else ""))
    for name, rows in doc["sides"].items():
        if not rows:
            out.append(f"СТОРОНА {name}: НЕ ИЗМЕРЕНО (ряд пуст)")
            continue
        outcomes: Dict[str, int] = {}
        for r in rows:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        line = f"СТОРОНА {name}: " + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items()))
        if rows[0].get("shim"):
            line += (f" · предел {rows[0]['limit_s']} с"
                     f" · start() {_span(rows, 'start_cost_s')}"
                     f" · старт→wait {_span(rows, 'gap_to_wait_s')}"
                     f" · ОЖИДАНИЕ ПРОСТОЯЛО {_span(rows, 'wait_s')}"
                     f" · срок в ОС простоял {_span(rows, 'timed_acquire_s')}"
                     f" · замок свободен в момент зова "
                     f"{sum(1 for r in rows if r.get('free_at_ask') is True)}/"
                     f"{sum(1 for r in rows if r.get('free_at_ask') is not None)}"
                     f" · работа ребёнка {_span(rows, 'child_work_s')}")
        else:
            line += f" · стена {_span(rows, 'wall_s')}"
        out.append(line)
    blind = [r for r in doc["sides"].get("busy_under_limit", []) if r["outcome"] == "ok"]
    if blind:
        out.append(f"ПРИЧИНА (первая слепая строка): {blind[0]['place_reason']}")
    if doc.get("unmeasured_reason"):
        out.append(f"НЕ ИЗМЕРЕНО: {doc['unmeasured_reason']}")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--busy-s", type=float, default=BUSY_S)
    ap.add_argument("--limit-s", type=float, default=BUSY_LIMIT_S)
    ap.add_argument("--sleep-s", type=float, default=SLEEP_S)
    ap.add_argument("--sleep-limit-s", type=float, default=SLEEP_LIMIT_S)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        doc = measure(busy_s=args.busy_s, busy_limit_s=args.limit_s, sleep_s=args.sleep_s,
                      sleep_limit_s=args.sleep_limit_s, repeats=args.repeats)
    except NotMeasured as exc:
        doc = {"verdict": _V_UNMEASURED, "unmeasured_reason": str(exc), "sides": {},
               "canary": {"verdict": _C_ABSENT, "reason": str(exc)},
               "series": {"verdict": _V_UNMEASURED, "blind_n": 0, "total_n": 0,
                          "places": {p: 0 for p in PLACES}, "reason": str(exc)},
               "controls": {"limit_honoured": {"ok": False, "reason": str(exc)},
                            "legal_ok": {"ok": False, "reason": str(exc)},
                            "primitive_quiet": {"ok": False, "reason": str(exc)}},
               "primitive": {"total_n": 0, "places": {}, "overstay_n": 0, "worst_s": None,
                             "worst_over_x": None, "rows": [], "quiet_rows": []},
               "scene": {"busy_s": args.busy_s, "busy_limit_s": args.limit_s,
                         "busy_over_limit_s": BUSY_OVER_LIMIT_S, "sleep_s": args.sleep_s,
                         "sleep_limit_s": args.sleep_limit_s,
                         "sleep_over_limit_s": SLEEP_OVER_LIMIT_S, "repeats": args.repeats,
                         "over_x": None, "switch_interval_s": sys.getswitchinterval()}}
    print(json.dumps(doc, ensure_ascii=False, indent=2) if args.json else render(doc))
    return 2 if doc["verdict"] == _V_UNMEASURED else 0


if __name__ == "__main__":
    raise SystemExit(main())
