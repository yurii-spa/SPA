"""Что в оценке стратегии ПОДСТАВЛЕНО — назвать, а не запретить.

Класс дефекта (карточка `agent-guard-no-silent-mock-in-tournament.md`, S23)
--------------------------------------------------------------------------
Стратегия заявляет «беру живой Pendle», импортирует адаптер внутри
``try: ... except: pass``, адаптер мёртв → ошибка проглочена молча → стратегия
НАВСЕГДА сидит на mock-числе 7% → это число уезжает в турнир как реальная оценка.
Зелёный прогон при этом ничего не значит: «стратегия заработала» на выдуманном
числе неотличимо от настоящего результата.

**Почему НАЗЫВАТЬ, а не запрещать.** Моки в paper-симуляции законны: без них часть
стратегий вообще нельзя прогнать офлайн (тесты не ходят в живую сеть — правило
адаптеров). Сторож, который запрещает моки как таковые, будет отключён первым же
человеком, которому он помешал по делу. Поэтому здесь нет ни одного запрета — есть
ОБЯЗАННОСТЬ подставленного числа ехать с именем: какое поле, какой флаг живости
сказал «нет», объявляет ли стратегия mock-константу вообще.

Соглашение о флагах живости
---------------------------
Стратегия объявляет живость источника одним из трёх способов (все три встречаются
в ``spa_core/strategies/`` уже сейчас, ничего нового не вводится):

  * метод-предикат без аргументов: ``pt_is_live()`` → bool (S23);
  * булев атрибут: ``self._pt_live`` / ``self.pendle_pt_live`` (S22, S23);
  * словарь-отчёт: ``mock_provenance()`` на самой стратегии — тогда он и есть ответ.

Флаг со значением ``False`` — ЗАЯВЛЕННАЯ подстановка. Отсутствие флагов вовсе —
не «всё живое», а ``fully_live=None`` («не заявлено»): fail-CLOSED, недоказанное
не выглядит доказанным.

Правила: stdlib only · read-only/advisory · LLM запрещён · исключений не бросает
(упавший провенанс не имеет права ронять турнир — он обязан сказать «не знаю»).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

#: Префиксы имён констант-подстановок на уровне модуля стратегии.
MOCK_CONST_PREFIXES: tuple = ("MOCK_", "FALLBACK_")

#: Суффиксы имён флагов живости источника.
LIVE_FLAG_SUFFIXES: tuple = ("_live", "_is_live")

#: Метод, которым стратегия может ответить о провенансе сама (тогда он приоритетен).
SELF_REPORT_METHOD: str = "mock_provenance"


def declared_mock_constants(source: Any) -> List[str]:
    """Имена констант-подстановок, ОБЪЯВЛЕННЫХ модулем/классом стратегии.

    Только чтение атрибутов: ничего не вызывается, сеть не трогается. Пустой
    список означает «подстановочных констант не объявлено», а не «моков нет».
    """
    if source is None:
        return []
    out: List[str] = []
    for name in dir(source):
        if not name.isupper():
            continue
        if not name.startswith(MOCK_CONST_PREFIXES):
            continue
        try:
            value = getattr(source, name)
        except Exception:  # noqa: BLE001 — провенанс не падает
            continue
        if isinstance(value, (int, float, dict)) and not isinstance(value, bool):
            out.append(name)
    return sorted(out)


def _flag_base(name: str) -> str:
    """«База» имени флага: ``_pt_live`` и ``pt_is_live`` — один и тот же источник."""
    base = name.lstrip("_")
    for suffix in ("_is_live", "_live"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def live_flags(instance: Any) -> Dict[str, bool]:
    """Флаги живости источников стратегии: ``{имя_флага: жив ли}``.

    Предикаты (``*_is_live()``) ВЫЗЫВАЮТСЯ без аргументов — у стратегий это
    read-only чтение уже загруженного адаптера. Вызов, бросивший исключение,
    трактуется как ``False`` (источник не подтверждён — fail-CLOSED), а не
    пропускается: проглоченная ошибка и есть исходный дефект.

    **Предикат старше кэша (замер на S23).** У стратегии одновременно есть
    приватный ``self._pt_live`` (кэш, выставленный последним чтением) и метод
    ``pt_is_live()`` (перечитывает источник). Сразу после конструктора кэш —
    ``False``, а предикат уже вернёт ``True``: обход по ``dir()`` в алфавитном
    порядке прочитал бы сперва устаревший кэш и объявил живую стратегию
    подставленной. Поэтому, когда у одного источника есть и предикат, и кэш,
    считается ПРЕДИКАТ, а кэш из отчёта убирается.
    """
    flags: Dict[str, bool] = {}
    predicate_bases: set = set()
    if instance is None:
        return flags
    candidates = [
        n for n in dir(instance)
        if not n.startswith("__") and n.endswith(LIVE_FLAG_SUFFIXES)
    ]
    resolved: Dict[str, bool] = {}
    for name in candidates:
        try:
            attr = getattr(instance, name)
        except Exception:  # noqa: BLE001
            resolved[name] = False
            continue
        if callable(attr):
            predicate_bases.add(_flag_base(name))
            try:
                value = attr()
            except Exception as exc:  # noqa: BLE001
                _log.debug("mock_provenance: %s() raised %s → not live", name, exc)
                resolved[name] = False
                continue
        else:
            value = attr
        if isinstance(value, bool):
            resolved[name] = value
        elif value is None:
            resolved[name] = False

    for name, value in resolved.items():
        try:
            attr = getattr(instance, name)
        except Exception:  # noqa: BLE001
            attr = None
        is_predicate = callable(attr)
        if not is_predicate and _flag_base(name) in predicate_bases:
            continue  # кэш того же источника — предикат уже ответил
        flags[name] = value
    return dict(sorted(flags.items()))


def mock_provenance(instance: Any, *, module: Any = None) -> Dict[str, Any]:
    """Провенанс подстановок для одной стратегии.

    Возвращает
    ----------
    ``{strategy_id, live_flags, substituted, declared_mock_constants,
    fully_live, self_reported}``

    ``substituted`` — имена флагов живости, сказавших ``False``: именно они и есть
    «подставлено молча», если их никто не показывает. ``fully_live``:

      * ``True``  — есть флаги и все ``True``;
      * ``False`` — есть флаг со значением ``False``;
      * ``None``  — флагов нет вовсе, живость НЕ ЗАЯВЛЕНА (не путать с «живое»).
    """
    sid = str(
        getattr(instance, "STRATEGY_ID", None)
        or getattr(module, "STRATEGY_ID", None)
        or type(instance).__name__
    )

    # Стратегия может отчитаться сама — тогда её ответ и есть провенанс.
    self_report = getattr(instance, SELF_REPORT_METHOD, None)
    if callable(self_report):
        try:
            reported = self_report()
            if isinstance(reported, dict):
                out = dict(reported)
                out.setdefault("strategy_id", sid)
                out["self_reported"] = True
                return out
        except Exception as exc:  # noqa: BLE001
            _log.debug("mock_provenance: %s.%s() raised %s", sid, SELF_REPORT_METHOD, exc)

    flags = live_flags(instance)
    substituted = [name for name, alive in flags.items() if not alive]
    fully_live: Optional[bool] = None if not flags else not substituted
    return {
        "strategy_id": sid,
        "live_flags": flags,
        "substituted": substituted,
        "declared_mock_constants": sorted(set(
            declared_mock_constants(type(instance)) + declared_mock_constants(module)
        )),
        "fully_live": fully_live,
        "self_reported": False,
    }


def is_mock_fed(provenance: Any) -> bool:
    """``True``, если провенанс НАЗЫВАЕТ хотя бы одну подстановку.

    ``fully_live=None`` (живость не заявлена) — НЕ подстановка сама по себе: это
    отдельное состояние «не знаю», и путать его с «подставлено» значило бы красить
    сторожа на честных стратегиях, у которых живого источника нет по устройству.
    """
    if not isinstance(provenance, dict):
        return False
    if provenance.get("substituted"):
        return True
    return provenance.get("fully_live") is False
