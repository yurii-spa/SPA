"""Зов ПИТОНЬИХ читателей журнала решений — отдельным процессом, с плечом пина.

Заказ **G31 приказа владельца «Portfolio CIO»**, пункт 1. ADR-405 нашёл у соседа
класс, которого перепись до сих пор не умела назвать: параметр ``now=`` доходит
до точки входа читателя, а ВНУТРИ читателя часы берутся у двери, чьё имя
связано на импорте (``from datetime import datetime`` в модуле-потомке). Такую
дверь инъекция параметром не закрывает НИКОГДА — и молча: ответ читателя плывёт,
координата снимается как нестабильная, вердикт получается «нечувствителен к
стенду». Отличить «не зависит от стенда» от «зависимость легла в снятую
координату» по одному плечу нельзя.

## Почему два плеча и отдельный процесс

Мера — дифференциальная и по ИСХОДУ, а не по тексту модуля:

* **плечо A** — читатель зовётся так, как его зовёт перепись сегодня:
  ``now=`` проводится в подпись, класс ``datetime.datetime`` настоящий;
* **плечо B** — то же самое, но класс ``datetime.datetime`` подменён до первого
  импорта ``spa_core`` (``pin_clock`` соседа ``_http_reader_probe``).

Координата, нестабильная в плече A и стабильная в плече B, и есть **дверь,
связанная на импорте**: параметром её не закрыть, подменой класса — можно.
Разность считается поимённо, а не по счётчику: счётчик одного размера может
получиться из разных множеств.

Пин класса действует на модули, импортированные ПОСЛЕ него, поэтому плечо B
обязано быть отдельным процессом, а пин — первым делом в нём. Внутри процесса
переписи (где 108 читателей уже импортированы) он не сделал бы ничего и дал бы
ложный ноль — fail-OPEN, который тише красной строки.

``time.time()`` не закрепляется намеренно — на нём TTL кешей и сроки ожидания
(та же оговорка, что в ADR-404). Дверь на ``time.time()`` эта мера поэтому НЕ
ДОКЛАДЫВАЕТ: её ответ односторонний — «закрывается пином класса» либо «этим
пином не закрывается», а не «дверей больше нет».

Прибор только ЧИТАЕТ: капитал не двигается, живой трек и ``data/`` не трогаются,
зов идёт против КОПИИ-стенда, ``write=False`` передаётся везде, где параметр
есть (правило ``module_driver``).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import sys

# Запуск ПО ПУТИ кладёт каталог скрипта первым в `sys.path`, и сосед
# `spa_core/monitoring/signal.py` затеняет стандартный `signal`. Снимать ДО
# остальных импортов, а не в `__main__`: там уже поздно. Сравниваются
# РАЗРЕШЁННЫЕ пути — дерево под `/tmp` на macOS есть ссылка на `/private/tmp`,
# и сравнение `abspath` роняло импорт всех модулей (замер 17.09, ADR-405).
if __name__ == "__main__" and sys.path and (
        os.path.realpath(sys.path[0])
        == os.path.dirname(os.path.realpath(__file__))):
    del sys.path[0]

import importlib
import importlib.util
import json
import pathlib
import time
from typing import Dict, List, Optional

#: Каталог стенда (его подкаталог ``data/`` получает читатель).
STAND_ENV = "SPA_READER_STAND"

#: Момент прогона — он же значение ``now=`` и он же момент пина (ISO-8601 с поясом).
CLOCK_ENV = "SPA_CENSUS_PINNED_NOW"

#: ``1`` ⇒ подменить класс ``datetime.datetime`` ДО первого импорта ``spa_core``.
PIN_CLASS_ENV = "SPA_CENSUS_PIN_CLASS"

#: Сколько раз спросить часы, прежде чем назвать их закреплёнными. Настоящие
#: часы сдвигаются за единицы зовов; запас взят с избытком, потому что цена
#: ошибки несимметрична: ложный «закреплён» превратил бы замер в выдумку.
CLOCK_TICK_ATTEMPTS = 10_000


def _load_pin_clock():
    """``pin_clock`` соседа — ПО ПУТИ, чтобы не импортировать пакет.

    Обычный ``import spa_core.monitoring._http_reader_probe`` втянул бы пакет
    ``spa_core`` целиком — то есть связал бы ``datetime`` в десятках модулей
    РАНЬШЕ подмены, и плечо B стало бы копией плеча A. Тише красной строки и
    потому опаснее: разность вышла бы нулевой, а ноль читался бы как ответ.
    """
    path = pathlib.Path(__file__).resolve().with_name("_http_reader_probe.py")
    spec = importlib.util.spec_from_file_location("_spa_http_reader_probe", path)
    if spec is None or spec.loader is None:            # pragma: no cover
        raise ImportError(f"сосед не загружен: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pin_clock


def clock_is_pinned() -> bool:
    """Закреплён ли класс — ЗАМЕР у двери, а не вера в переданный флаг.

    Настоящие часы РАНО ИЛИ ПОЗДНО сдвигаются, подменённые — никогда. Поэтому
    спрашивается не «различны ли два соседних зова» (два подряд могут лечь в одну
    микросекунду, и тогда настоящие часы прочлись бы как закреплённые — ложный
    пин, то есть замер, выданный за наблюдение), а «сдвинулись ли часы хоть раз
    за N зовов». Вопрос «пин сработал?» задаётся отдельно от вопроса «пин
    просили?»: модуль, связавший настоящий класс раньше подмены, выдаёт себя
    только здесь.
    """
    import datetime as _dt

    first = _dt.datetime.now(_dt.timezone.utc)
    for _ in range(CLOCK_TICK_ATTEMPTS):
        if _dt.datetime.now(_dt.timezone.utc) != first:
            return False
    return True


def probe_modules(names: List[str], stand: pathlib.Path,
                  now, delay_s: float) -> Dict[str, dict]:
    """Каждому читателю — ДВА ответа на ОДНОМ стенде, между ними пауза.

    Пауза нужна: координата, бегущая на каждом зове, без зазора могла бы совпасть
    и прочиталась бы как стабильная — то есть плечо A недосчитало бы дверей, и
    ошибка пошла бы в сторону ЗАНИЖЕНИЯ находки.
    """
    from spa_core.monitoring.run_identity_key_price import (  # локально: после пина
        clock_kwarg, leaf_values, module_driver, no_entry_cause,
        stable_leaf_digests, unstable_coords,
    )

    out: Dict[str, dict] = {}
    for name in names:
        row: Dict[str, object] = {}
        try:
            mod = importlib.import_module(name)
        except BaseException as exc:                          # noqa: BLE001
            out[name] = {"cause": "import_failed",
                         "reason": f"импорт не удался: {type(exc).__name__}"}
            continue
        entry, call = module_driver(mod, now=now)
        if call is None:
            cause, reason = no_entry_cause(mod)
            out[name] = {"cause": cause, "reason": reason}
            continue
        row["entry"] = entry
        row["clock_injected"] = bool(
            clock_kwarg(getattr(mod, str(entry), None), now))
        try:
            first = call(stand)
            time.sleep(delay_s)
            second = call(stand)
        except BaseException as exc:                          # noqa: BLE001
            out[name] = {"cause": "entry_raised",
                         "reason": f"{entry}() упал: {type(exc).__name__}"}
            continue
        # Правило «что считать нестабильным» НЕ копируется: берётся то же
        # `unstable_coords`, которым судит сама перепись. Вторая копия правила
        # была бы ровно тем классом, который перепись ловит у читателей.
        row["unstable"] = sorted(unstable_coords(first, second))
        # Значения того, что НЕ плывёт внутри плеча. Разность имён отвечает
        # «где дрожит», а цена закрытия двери — вопрос про ОТВЕТ: сравнив эти
        # значения между плечами, оркестратор видит, изменил ли пин вердикт
        # читателя, а не только его дрожь (заказ G32, п. 1).
        row["stable"] = stable_leaf_digests(first, set(row["unstable"]))
        # ЗНАЧЕНИЯ плывущих координат — на обеих пробах. Нужны затем, чтобы
        # оркестратор судил о роде координаты ЗАМЕРОМ, а не по её имени (заказ
        # G33, п. 4): «свой временный стенд, свежий на каждый зов» — это пара
        # РАЗНЫХ путей под временным каталогом, и такое утверждение проверяемо.
        # Правило записи не копируется: значения берутся тем же обходом, что и
        # имена, иначе координата не нашлась бы по своему же адресу.
        row["unstable_values"] = {
            "first": leaf_values(first, set(row["unstable"])),
            "second": leaf_values(second, set(row["unstable"])),
        }
        out[name] = row
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """``_python_reader_clock_probe <modules.json> <out.json>``.

    Стенд и часы — из окружения, ДО первого импорта ``spa_core``. Нет стенда или
    нет часов ⇒ ОТКАЗ кодом 2: зов пошёл бы против живого каталога или со
    стенными часами, и оба плеча стали бы неразличимы — «не измерено», выданное
    за ответ.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2:
        sys.stderr.write(
            "usage: _python_reader_clock_probe <modules.json> <out.json>\n")
        return 2
    stand_raw = str(os.environ.get(STAND_ENV) or "").strip()
    if not stand_raw:
        sys.stderr.write(f"ОТКАЗ: {STAND_ENV} не задана — зов пошёл бы против "
                         "ЖИВОГО каталога\n")
        return 2
    pinned_iso = str(os.environ.get(CLOCK_ENV) or "").strip()
    if not pinned_iso:
        sys.stderr.write(f"ОТКАЗ: {CLOCK_ENV} не задана — плечи отличались бы "
                         "не пином, а стенными часами\n")
        return 2
    want_pin = str(os.environ.get(PIN_CLASS_ENV) or "").strip() == "1"
    if want_pin:
        try:
            _load_pin_clock()(pinned_iso)
        except (ImportError, ValueError) as exc:
            sys.stderr.write(f"ОТКАЗ: класс часов не закреплён — {exc}\n")
            return 2

    import datetime as _dt
    now = _dt.datetime.fromisoformat(pinned_iso)
    if now.tzinfo is None:
        sys.stderr.write(f"ОТКАЗ: {CLOCK_ENV} без пояса: {pinned_iso!r}\n")
        return 2

    from spa_core.monitoring.run_identity_key_price import _STABILITY_PROBE_DELAY_S

    names = json.loads(pathlib.Path(argv[0]).read_text(encoding="utf-8"))
    answer: Dict[str, object] = {
        "__modules__": probe_modules(list(names), pathlib.Path(stand_raw),
                                     now, _STABILITY_PROBE_DELAY_S),
        # Спрашивается ПОСЛЕ зова: до зова класс мог быть ещё не связан никем.
        "__clock__": {"pin_requested": want_pin,
                      "pin_observed": clock_is_pinned(),
                      "moment": pinned_iso},
    }
    pathlib.Path(argv[1]).write_text(
        json.dumps(answer, sort_keys=True, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
