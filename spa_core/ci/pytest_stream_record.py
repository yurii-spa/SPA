#!/usr/bin/env python3
"""Потоковая запись прогона: имя теста ложится на диск ДО того, как он побежал.

**Зачем (цикл #697, 2026-09-25, карточка `inbox-ci-na-main-verdikt-vpervye-izmeren-tests`).**
ADR-474 научил шаг CI отличать «красно» от «НЕ ИЗМЕРЕНО», и первый же честный вердикт
показал, во что упирается честность: шаг `spa_core/tests/` дошёл до **80 %**, напечатал
`FFF F..F....F.F..F` — не меньше 13 упавших тестов — и был снят внешней границей
`timeout-minutes: 120`. **Имён этих тринадцати не существует нигде.** И сводка pytest, и
запись junit-XML пишутся В КОНЦЕ сессии, а конца не было; третий исход назван честно, но
он же и прячет имена.

Отсюда же вторая слепота, и она хуже. Между `20:35:41Z` и `20:42:01Z` шаг не напечатал
НИ ОДНОГО знака — шесть с лишним минут при пороге `--timeout=180`. Столько молчать может
только блокировка в C-коде, которую SIGALRM не прерывает (оговорка ADR-474, замер #59:
`_ssl__SSLSocket_read`). То есть у нас был не только безымянный провал, но и безымянный
ЗАВИС, и спросить «что исполнялось, когда упал топор» было НЕ У ЧЕГО: прогресс-строка
`-q` печатает точки, а не имена.

**Что делает этот модуль.** Одну вещь: пишет строку в тот момент, когда событие
произошло, и сбрасывает буфер. Тест НАЧАЛСЯ — строка на диске. Тест кончился — вторая
строка. Сессию убивают `os._exit`-ом, SIGKILL-ом или снятием джобы — сброшенное уже
принадлежит ядру и переживает процесс. Поэтому «начался и не кончился» становится
наблюдаемым, а до сих пор было неотличимо от «не дошли».

**Чего он НЕ делает, и это существенно.** Он не выносит вердикт и не может превратить
«НЕ ИЗМЕРЕНО» в «измерено»: его запись — перечень НАЗВАННЫХ событий, а не итог прогона.
Читатель (`scripts/ci_verdict.py`) обязан оставить код возврата 2 на оборванной сессии и
использовать эту запись ТОЛЬКО чтобы назвать имена. Иначе прибор против инварианта #17
сам бы его и нарушил: «успели 80 тысяч, и все зелёные» — это не «набор зелёный».

**Выключен по умолчанию, и это НАЗВАННЫЙ третий исход, а не ноль.** Без переменной
окружения ``SPA_PYTEST_STREAM`` плагин инертен: ни файла, ни расхода. Читатель, не нашедший
записи, обязан сказать «потоковой записи нет по пути X», а не «упавших не было».

Формат — JSON Lines, по событию на строку (поля добавляются только АДДИТИВНО):

    {"e":"session","t":<unix>,"iso":"…","pid":123,"args":[…]}
    {"e":"start","t":<unix>,"n":"<nodeid>"}
    {"e":"ok","t":<unix>,"n":"<nodeid>","d":<сек>}
    {"e":"fail","t":<unix>,"n":"<nodeid>","w":"call","d":<сек>,"msg":"<первая строка>"}
    {"e":"skip","t":<unix>,"n":"<nodeid>","w":"setup"}
    {"e":"end","t":<unix>,"status":<код выхода pytest>,"started":N,"finished":M}

``n`` повторяется в строке исхода намеренно: пара «начал/кончил» тогда сходится по имени,
а не по соседству строк, и запись остаётся читаемой, даже если события переплетутся.

Только stdlib (инв. #4).
"""
from __future__ import annotations

import json
import os
import time

# Имя переменной — часть контракта: его читают воркфлоу и тесты.
STREAM_ENV = "SPA_PYTEST_STREAM"

# Первая строка сообщения об ошибке, обрезанная до этого предела. Сообщение здесь —
# подсказка, а не улика: полный текст живёт в junit-записи, когда она есть.
_MSG_LIMIT = 200


class StreamRecorder:
    """Пишет по строке на событие и сбрасывает буфер после каждой.

    Сброс после КАЖДОЙ строки — не перестраховка, а весь смысл модуля: буфер,
    не дошедший до ядра, умирает вместе с процессом, а процесс здесь убивают
    по построению. ``fsync`` при этом НЕ зовётся: от гибели процесса защищает
    уже сброс, а ``fsync`` защищал бы от гибели МАШИНЫ и стоил бы на каждой из
    ~200 000 строк.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.started = 0
        self.finished = 0
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Дозапись, а не перезапись: два шага одного прогона могут делить путь,
        # и потерять запись первого из-за второго значило бы вернуть ту самую
        # безымянность, против которой модуль написан.
        self._fh = open(path, "a", encoding="utf-8")

    def emit(self, event: dict) -> None:
        event.setdefault("t", round(time.time(), 3))
        self._fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:                                    # pragma: no cover
            pass


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _first_line(text: object) -> str:
    line = str(text).strip().splitlines()[0] if str(text).strip() else ""
    return line[:_MSG_LIMIT]


# --- хуки pytest -----------------------------------------------------------
# Плагин грузится флагом `-p spa_core.ci.pytest_stream_record`. Писатель живёт в
# модуле, а не только в `config`: из четырёх хуков ниже три вызываются БЕЗ `config`
# и до него не дотянулись бы. Пока писателя нет, каждый хук выходит первой строкой,
# поэтому загрузка плагина без переменной окружения не стоит ничего.
_RECORDER: "StreamRecorder | None" = None


def pytest_configure(config) -> None:                        # noqa: ANN001
    global _RECORDER
    path = os.environ.get(STREAM_ENV)
    if not path:
        _RECORDER = None
        return
    _RECORDER = StreamRecorder(path)
    now = time.time()
    params = getattr(config, "invocation_params", None)
    _RECORDER.emit({
        "e": "session", "t": round(now, 3), "iso": _iso(now), "pid": os.getpid(),
        "args": list(params.args) if params is not None else [],
    })


def pytest_runtest_logstart(nodeid, location) -> None:       # noqa: ANN001, ARG001
    if _RECORDER is None:
        return
    _RECORDER.started += 1
    _RECORDER.emit({"e": "start", "n": nodeid})


def pytest_runtest_logreport(report) -> None:                # noqa: ANN001
    if _RECORDER is None:
        return
    if report.failed:
        _RECORDER.emit({
            "e": "fail", "n": report.nodeid, "w": report.when,
            "d": round(float(report.duration or 0.0), 3),
            "msg": _first_line(getattr(report, "longrepr", "") or ""),
        })
        # `teardown` не считается завершением теста: тот же тест уже посчитан на
        # `call` или `setup`, и второй счёт разошёлся бы со счётом стартов.
        if report.when in ("call", "setup"):
            _RECORDER.finished += 1
        return
    if report.skipped and report.when in ("setup", "call"):
        _RECORDER.emit({"e": "skip", "n": report.nodeid, "w": report.when})
        _RECORDER.finished += 1
        return
    if report.when == "call" and report.passed:
        _RECORDER.emit({
            "e": "ok", "n": report.nodeid,
            "d": round(float(report.duration or 0.0), 3),
        })
        _RECORDER.finished += 1


def pytest_sessionfinish(session, exitstatus) -> None:       # noqa: ANN001, ARG001
    global _RECORDER
    if _RECORDER is None:
        return
    _RECORDER.emit({
        "e": "end", "status": int(exitstatus),
        "started": _RECORDER.started, "finished": _RECORDER.finished,
    })
    _RECORDER.close()
    _RECORDER = None
