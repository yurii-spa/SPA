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

Прибор только ЧИТАЕТ. Капитал не двигается, живой трек не трогается.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

#: Маршруты, которые прибор НЕ ЗОВЁТ НИКОГДА — ключ ``"<модуль>:<путь>"``,
#: значение — причина. Пуст ПО ЗАМЕРУ (см. докстринг), а не по недосмотру.
HTTP_NEVER_CALL: Dict[str, str] = {}

#: Методы, при которых маршрут считается читающим. ``HEAD`` допускается рядом с
#: ``GET`` (FastAPI добавляет его сам), но сам по себе маршрутом не является.
_READ_METHODS = frozenset({"GET", "HEAD"})

DATA_DIR_ENV = "SPA_DATA_DIR"


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


def _call(endpoint):
    """Ответ обработчика, приведённый к JSON-сравнимому виду."""
    value = endpoint()
    if inspect.isawaitable(value):
        value = asyncio.new_event_loop().run_until_complete(value)
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def probe_modules(module_names, never_call: Optional[Dict[str, str]] = None) -> dict:
    """Ответы всех читающих маршрутов перечисленных модулей — на ТЕКУЩЕМ стенде."""
    out: Dict[str, dict] = {}
    for name in module_names:
        entry: Dict[str, dict] = {"routes": {}, "refused": {}, "elapsed_s": {}}
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
            entry["elapsed_s"][path] = round(time.time() - started, 3)
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
    names = json.loads(open(argv[0], encoding="utf-8").read())
    with open(argv[1], "w", encoding="utf-8") as fh:
        json.dump(probe_modules(names), fh, sort_keys=True, default=str)
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
