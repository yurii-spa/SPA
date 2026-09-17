"""Зов обработчиков HTTP-маршрутов ПРОТИВ СТЕНДА — отдельным процессом.

Заказ G27 приказа владельца «Portfolio CIO», часть 2. Перепись читателей журнала
решений (``run_identity_key_price``) не выносила вердикта **20 модулям из 61 не
измеренного**, и все двадцать — обработчики HTTP-маршрутов, то есть ровно те
читатели, чей ответ владелец видит на дашборде. Причина стояла такая:

    «каталог стенда ему не передать — он читает через модульный корень, а не
    через аргумент»

**Замер 16.09 эту причину опроверг.** Ворота у маршрутов есть, и они объявлены в
их же докстринге: ``spa_core/api/_shared.py::data_dir()`` резолвит каталог **В
МОМЕНТ ВЫЗОВА** через ``spa_core.api.server._DATA_DIR``, а сам ``_DATA_DIR``
инициализируется из переменной ``SPA_DATA_DIR``. То есть каталог передать МОЖНО —
не аргументом, а окружением, до импорта.

## Почему отдельным процессом, а не подменой атрибута

Подменить ``server._DATA_DIR`` после импорта — ровно то, что делает набор тестов
API, и для самих обработчиков этого достаточно. Но модуль, посчитавший свой путь
НА ИМПОРТЕ (``_PROJECT_ROOT / "data"``), такой подменой не сдвинется и молча
прочитает ЖИВОЙ каталог — тот же класс, что «patching module ROOT after import
leaves stale constants». Отдельный процесс с ``SPA_DATA_DIR``, выставленной ДО
первого импорта, закрывает обе дороги разом, а заодно не тащит FastAPI и два
десятка роутеров в процесс переписи, где рядом меряются ещё 88 читателей.

## Что зовётся, а что нет — fail-CLOSED

Зовётся маршрут, у которого ВСЕ три условия:

1. метод ровно ``GET`` (``HEAD`` допускается рядом) — ``POST``/``DELETE`` не
   зовутся никогда;
2. обработчик объявлен В ЭТОМ модуле (``__module__``) — иначе роутеры,
   подключённые в ``server.app``, посчитались бы дважды, у чужого хозяина;
3. у обработчика НЕТ ни одного обязательного параметра — подставлять аргумент
   значило бы выдумывать вход.

Плюс именной список отказов ``HTTP_NEVER_CALL``: маршрут, чей зов совершил бы
действие. Сегодня он ПУСТ, и это ЗАМЕР, а не умолчание: прогон всех 111
подходящих маршрутов против копии стенда не изменил в ней ни одного байта
(1325 файлов, sha до и после). Механизм оставлен именно потому, что «пусто
сегодня» и «пусто всегда» — разные утверждения.

## Часы процесса-зонда закреплены (заказ G29, ADR-404)

Замер 17.09: у **18 маршрутов** из класса ``verdict_rests_on_unstable_coords``
между двумя пробами ОДНОГО стенда расходилась ровно одна координата — отметка
верхнего уровня (``generated_at`` / ``timestamp`` / ``served_at`` /
``server_timestamp``), выставляемая стенными часами в момент зова. Вердикта не
было не потому, что стенд до маршрута не доходил, а потому, что зов шёл без
часов — та же «половина инъекции», что ADR-401 закрыл у питоньих читателей.

Параметр ``now=`` обработчику не передать: зов идёт отдельным процессом, а у
обработчика часов в подписи нет. Поэтому часы доносятся ТЕМ ЖЕ путём, что и
каталог стенда, — переменной ``SPA_CENSUS_PINNED_NOW`` ДО первого импорта:
класс ``datetime.datetime`` подменяется наследником, чьи ``now``/``utcnow``
отдают закреплённый момент. Отсюда и запуск ПО ПУТИ к файлу, а не ``-m``:
``-m`` импортирует пакет ``spa_core.monitoring`` (а с ним десятки модулей)
раньше, чем ``main`` успеет что-либо закрепить.

Закреплено ли — МЕРЯЕТСЯ у двери, а не предполагается: ответ несёт
``__clock__`` с тем, что вернул ``spa_core.api._shared.now()``. ``time.time()``
НЕ закрепляется намеренно: на нём стоят TTL кешей и сроки ожидания, и
замёрзшие часы там превращают ожидание в вечный цикл. Производные от
``time.time()`` по-прежнему ловит накрывающее окно проб (ADR-399).

## Ответ-объект читается по ТЕЛУ (там же, ADR-404)

Замер 17.09: **20 маршрутов** (``live``, ``btc_engine``, ``cockpit``,
``tournament``) возвращают ``JSONResponse``, а зов приводил ответ через
``json.dumps(default=str)`` — то есть сравнивал строку
``<starlette.responses.JSONResponse object at 0x…>``: АДРЕС в памяти, а не
тело. Все двадцать стояли в ``answer_not_reproducible``, и перепись ни разу не
видела, что они отвечают. Теперь сравнивается тело (и код статуса); ответ, чьё
тело прочитать нельзя (потоковый), помечается ``__unread_response__`` и
вердикта не получает — «одинаковый объект» не есть «одинаковый ответ».

## Окно зова — чтобы момент выдачи узнавался ЗАМЕРОМ (заказ G30)

У 18 маршрутов после закрепления часов осталась одна плывущая координата ТЕЛА
(``_fetched_at`` ×12, ``ts`` ×6). Замер 17.09 трассировкой ``time.time``: у них
**16 дверей в трёх модулях и ни одной общей** — каждое значение рождено прямым
``time.time()`` в самом обработчике, так что «закрепить одну дверь», как
``_shared.now``, нельзя. Поэтому зонд пишет окно каждого зова
``window[path] = [начало, конец]`` по тем же стенным часам процесса, и перепись
сама узнаёт координату, чьё значение на КАЖДОЙ пробе лежит внутри окна своего
зова (``run_identity_key_price.call_moment_coords``).

Прибор только ЧИТАЕТ. Капитал не двигается, живой трек не трогается.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import sys

# Запуск ПО ПУТИ кладёт каталог скрипта первым в sys.path, и сосед
# `spa_core/monitoring/signal.py` затеняет стандартный `signal` — `asyncio`
# ниже и `anyio` внутри FastAPI падали ImportError на ВСЕХ 20 модулях (замер
# 17.09). Снимать ДО остальных импортов, а не в `__main__`: там уже поздно.
# Сравнивать РАЗРЕШЁННЫЕ пути (заказ G30): интерпретатор кладёт в `sys.path[0]`
# путь без ссылок, а `__file__` несёт путь, как его назвали. Дерево под `/tmp`
# на macOS (ссылка на `/private/tmp`) при сравнении `abspath` не совпадало, и
# все 20 модулей снова падали ImportError — замер 17.09.
if __name__ == "__main__" and sys.path and (
        os.path.realpath(sys.path[0])
        == os.path.dirname(os.path.realpath(__file__))):
    del sys.path[0]

import asyncio
import importlib
import inspect
import json
import time
from typing import Dict, List, Optional, Tuple

#: Маршруты, которые прибор НЕ ЗОВЁТ НИКОГДА — ключ ``"<модуль>:<путь>"``,
#: значение — причина. Пуст ПО ЗАМЕРУ (см. докстринг), а не по недосмотру.
HTTP_NEVER_CALL: Dict[str, str] = {}

#: Методы, при которых маршрут считается читающим. ``HEAD`` допускается рядом с
#: ``GET`` (FastAPI добавляет его сам), но сам по себе маршрутом не является.
_READ_METHODS = frozenset({"GET", "HEAD"})

DATA_DIR_ENV = "SPA_DATA_DIR"

#: Момент, к которому закрепляются часы процесса-зонда (ISO-8601 с поясом).
CLOCK_ENV = "SPA_CENSUS_PINNED_NOW"

#: Ключ ответа, которым помечено тело, прочитать которое нельзя.
UNREAD_RESPONSE = "__unread_response__"


def pin_clock(iso: str):
    """Подменить ``datetime.datetime`` наследником с закреплёнными часами.

    Возвращает закреплённый момент. Действует на модули, импортированные ПОСЛЕ
    вызова (``from datetime import datetime`` связывает имя на импорте), —
    поэтому зовётся до первого импорта ``spa_core``. Момент без пояса —
    ОТКАЗ: наивное время здесь было бы догадкой о поясе (fail-CLOSED).
    """
    import datetime as _dt

    base = _dt.datetime
    while getattr(base, "_spa_census_pinned", False):
        base = base.__mro__[1]
    moment = base.fromisoformat(str(iso))
    if moment.tzinfo is None:
        raise ValueError(f"{CLOCK_ENV} без пояса: {iso!r}")
    stamp = moment.timestamp()

    class _PinnedDatetime(base):
        _spa_census_pinned = True

        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(stamp, tz)

        @classmethod
        def utcnow(cls):
            return cls.fromtimestamp(stamp, _dt.timezone.utc).replace(tzinfo=None)

    _dt.datetime = _PinnedDatetime
    return moment


def unpin_clock() -> None:
    """Вернуть настоящий ``datetime.datetime`` (для тестов в одном процессе)."""
    import datetime as _dt

    while getattr(_dt.datetime, "_spa_census_pinned", False):
        _dt.datetime = _dt.datetime.__mro__[1]


def clock_at_the_door() -> Dict[str, object]:
    """Что отвечает дверь серверных отметок — ``_shared.now()``. Замер, не вера."""
    try:
        from spa_core.api import _shared
        return {"shared_now": _shared.now()}
    except BaseException as exc:                              # noqa: BLE001
        return {"shared_now": None, "reason": type(exc).__name__}


def _routers(mod):
    """Пары ``(имя атрибута, объект)`` — HTTP-поверхности модуля.

    Спрашиваем у ТИПА объекта, а не у имени модуля: имя было бы догадкой и
    ошибалось бы в обе стороны (роутер живёт и вне каталога ``routers/``).
    """
    return [(attr, obj) for attr, obj in vars(mod).items()
            if type(obj).__name__ in ("APIRouter", "FastAPI")]


def callable_routes(mod, never_call: Optional[Dict[str, str]] = None
                    ) -> Tuple[List[Tuple[str, object]], Dict[str, str]]:
    """``(зовём, отказы)`` для одного модуля. Каждый отказ несёт ПРИЧИНУ."""
    never_call = HTTP_NEVER_CALL if never_call is None else never_call
    name = getattr(mod, "__name__", "")
    called: List[Tuple[str, object]] = []
    refused: Dict[str, str] = {}
    seen: set = set()
    for _attr, router in _routers(mod):
        for route in getattr(router, "routes", ()):
            endpoint = getattr(route, "endpoint", None)
            path = str(getattr(route, "path", "?"))
            if endpoint is None:
                continue
            if getattr(endpoint, "__module__", None) != name:
                continue          # хозяин маршрута — сосед; там он и посчитается
            if path in seen:
                continue
            seen.add(path)
            methods = set(getattr(route, "methods", set()) or set())
            if not methods <= _READ_METHODS or "GET" not in methods:
                refused[path] = (f"метод {sorted(methods) or ['—']} — зовётся только "
                                 f"GET, остальное совершило бы действие")
                continue
            key = f"{name}:{path}"
            if key in never_call:
                refused[path] = f"именной отказ: {never_call[key]}"
                continue
            try:
                sig = inspect.signature(endpoint)
            except (TypeError, ValueError) as exc:           # pragma: no cover
                refused[path] = f"подпись не разобрана: {type(exc).__name__}"
                continue
            required = [p.name for p in sig.parameters.values()
                        if p.default is inspect.Parameter.empty
                        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            if required:
                refused[path] = ("обязательные аргументы " + ", ".join(required) +
                                 " — подставить их значило бы выдумать вход")
                continue
            called.append((path, endpoint))
    return called, refused


def _response_view(value):
    """Ответ-объект (Starlette ``Response``) → его ТЕЛО и код статуса.

    Узнаётся по поведению (``status_code`` + ``headers``), а не по имени
    класса. Тела нет (потоковый ответ) — ``UNREAD_RESPONSE``, а не ``repr``:
    ``repr`` несёт адрес в памяти и сравнивал бы объекты, а не ответы.
    """
    if not (hasattr(value, "status_code") and hasattr(value, "headers")):
        return value
    body = getattr(value, "body", None)
    if not isinstance(body, (bytes, bytearray)):
        return {UNREAD_RESPONSE: type(value).__name__,
                "__status__": getattr(value, "status_code", None)}
    text = bytes(body).decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = text
    return {"__status__": value.status_code, "__body__": parsed}


def _call(endpoint):
    """Ответ обработчика, приведённый к JSON-сравнимому виду."""
    value = endpoint()
    if inspect.isawaitable(value):
        value = asyncio.new_event_loop().run_until_complete(value)
    value = _response_view(value)
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def probe_modules(module_names, never_call: Optional[Dict[str, str]] = None) -> dict:
    """Ответы всех читающих маршрутов перечисленных модулей — на ТЕКУЩЕМ стенде."""
    out: Dict[str, dict] = {}
    for name in module_names:
        entry: Dict[str, dict] = {"routes": {}, "refused": {}, "elapsed_s": {},
                                  "window": {}}
        try:
            mod = importlib.import_module(name)
        except BaseException as exc:                          # noqa: BLE001
            entry["import_failed"] = type(exc).__name__
            out[name] = entry
            continue
        called, refused = callable_routes(mod, never_call)
        entry["refused"] = refused
        for path, endpoint in called:
            started = time.time()
            try:
                entry["routes"][path] = _call(endpoint)
            except BaseException as exc:                      # noqa: BLE001
                # Падение — тоже ответ, и он сравним между стендами: маршрут,
                # падающий одинаково везде, нечувствителен к стенду, а маршрут,
                # падающий только на одном, о стенде как раз свидетельствует.
                entry["routes"][path] = {"__raised__": type(exc).__name__,
                                         "__message__": str(exc)[:200]}
            finished = time.time()
            entry["elapsed_s"][path] = round(finished - started, 3)
            # Окно зова НЕ округляется: по нему судят, лежит ли отметка тела
            # внутри зова (заказ G30), а округление сдвинуло бы границу.
            entry["window"][path] = [started, finished]
        out[name] = entry
    return out


def main(argv=None) -> int:
    """``_http_reader_probe <modules.json> <out.json>``. Каталог — из окружения.

    Отказ при незаданной ``SPA_DATA_DIR`` — НЕ придирка. Без неё обработчики
    прочитали бы ЖИВОЙ каталог, а перепись доложила бы «нечувствителен к стенду»
    — то есть выдала бы за наблюдение то, что стенда вообще не касалось. Это
    fail-OPEN, и он тише красной строки, поэтому закрыт здесь.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2:
        sys.stderr.write("usage: _http_reader_probe <modules.json> <out.json>\n")
        return 2
    if not str(os.environ.get(DATA_DIR_ENV) or "").strip():
        sys.stderr.write(f"ОТКАЗ: {DATA_DIR_ENV} не задана — зов пошёл бы против "
                         "ЖИВОГО каталога, а ответ выдался бы за замер стенда\n")
        return 2
    pinned_iso = str(os.environ.get(CLOCK_ENV) or "").strip()
    pinned = None
    if pinned_iso:
        try:
            pinned = pin_clock(pinned_iso)
        except ValueError as exc:
            sys.stderr.write(f"ОТКАЗ: часы не закреплены — {exc}\n")
            return 2
    names = json.loads(open(argv[0], encoding="utf-8").read())
    answer = probe_modules(names)
    # Закреплено ли — спрашиваем у двери ПОСЛЕ зова: модуль, связавший
    # настоящий класс раньше подмены, выдал бы себя именно здесь.
    answer["__clock__"] = dict(clock_at_the_door(),
                               pinned=pinned.isoformat() if pinned else None)
    with open(argv[1], "w", encoding="utf-8") as fh:
        json.dump(answer, fh, sort_keys=True, default=str)
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
