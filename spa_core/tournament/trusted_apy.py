"""Доверяемый APY для турнира: число либо ДОКАЗАНО, либо ОТКАЗ — третьего нет.

Зачем этот модуль (карточка `agent-tournament-trustworthy-real-apy.md`)
----------------------------------------------------------------------
Турнир стратегий крутится ежедневно и ранжирует стратегии по доходности. До этого
модуля его вход читался так (``tournament_engine._load_cached_apy``):

    proto = row.get("protocol_key") or row.get("protocol")
    apy   = row.get("apy_pct")
    if proto and apy:
        apy_map[proto] = float(apy)

Четыре молчаливых допущения в четырёх строках, и каждое измерено на живом файле
``data/apy_ranking.json``:

1. **Единица подразумевалась.** Докстринг утверждал «percent units», а сам файл
   единицу НЕ объявлял. `0.8` как «0.8%» и `0.8` как «80%» — одно и то же число,
   поэтому «percent» здесь было верой, а не чтением. Ровно этот класс закрывает
   `spa_core/adapters/apy_contract.py`: единицу ОБЪЯВЛЯЕТ источник, и необъявленная
   единица — ОТКАЗ, а не догадка по величине.
2. **Провенанс не проверялся.** Агрегатор с недавних пор кладёт рядом с числом
   ``apy_source`` (``live`` = напечатанное число И ЕСТЬ наблюдение, ``fallback`` =
   литерал, ``unchecked`` = не измерено). Читатель это поле игнорировал, поэтому
   литеральный fallback попадал в турнир как наблюдение — тот же класс, что mock-7%
   у S23, только оптом.
3. **Свежесть не проверялась.** У строк есть ``last_updated``; замер 2026-08-17 на
   git-версии файла: отметки от **2026-06-21**, то есть 57 суток. Двухмесячный
   литерал использовался как «живой APY».
4. **Ноль молча выпадал.** ``if proto and apy`` — правдивый нулевой APY (points-farm,
   честный ноль btc_lending) falsy, и протокол просто исчезал из карты, вместо того
   чтобы честно занести 0%.

Контракт этого модуля
---------------------
Строка снимка попадает в доверяемую карту, только если выполнено ВСЁ:

  * снимок объявил единицу (``apy_unit``) — иначе отказ ЦЕЛИКОМ, ни одной строки;
  * ``apy_source`` строки входит в :data:`spa_core.adapters.apy_aggregator.OBSERVED_APY_SOURCES`
    (то есть число — наблюдение, а не литерал); отсутствующий провенанс = отказ;
  * ``last_updated`` разбирается и не старше ``max_age_hours`` относительно
    ПЕРЕДАННОГО ``now`` (стенные часы здесь не читаются на уровне модуля);
  * значение конвертируется в десятичное через
    :func:`spa_core.adapters.apy_contract.apy_decimal_from_declared` и проходит
    его же диапазонную проверку.

Всё остальное — **ИМЕНОВАННЫЙ отказ** в :attr:`TrustedAPY.refusals`, а не тихое
выпадение. Молча подставленное число делает зелёный прогон бессмысленным; молча
ВЫПАВШЕЕ число делает бессмысленным рейтинг. Поэтому отказ обязан иметь имя,
причину и протокол.

Правила: stdlib only · детерминированно · LLM запрещён · fail-CLOSED ·
модуль read-only (в ``data/`` не пишет).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, NamedTuple, Optional

from spa_core.adapters.apy_aggregator import OBSERVED_APY_SOURCES
from spa_core.adapters.apy_contract import (
    APY_UNIT_ATTR,
    apy_decimal_from_declared,
    declared_apy_unit,
)

_log = logging.getLogger(__name__)

#: Ключ, которым СНИМОК объявляет единицу своих APY-чисел (см. `apy_contract`).
SNAPSHOT_UNIT_KEY: str = "apy_unit"

#: Предел свежести наблюдения по умолчанию. Цикл обновляет `apy_ranking.json`
#: ежедневно, поэтому 36 ч — одна пропущенная итерация, а не двухмесячный литерал.
DEFAULT_MAX_AGE_HOURS: float = 36.0

# ── Имена отказов (стабильные строки: их читают тесты и дашборд) ──────────────
REFUSAL_NO_SNAPSHOT: str = "no_snapshot"
REFUSAL_UNDECLARED_UNIT: str = "undeclared_unit"
REFUSAL_BAD_ROW_SHAPE: str = "bad_row_shape"
REFUSAL_NO_PROTOCOL: str = "no_protocol"
REFUSAL_PROVENANCE_NOT_OBSERVED: str = "provenance_not_observed"
REFUSAL_NO_TIMESTAMP: str = "no_timestamp"
REFUSAL_STALE: str = "stale"
REFUSAL_OUT_OF_BAND: str = "out_of_band"

ALL_REFUSAL_REASONS: frozenset = frozenset({
    REFUSAL_NO_SNAPSHOT,
    REFUSAL_UNDECLARED_UNIT,
    REFUSAL_BAD_ROW_SHAPE,
    REFUSAL_NO_PROTOCOL,
    REFUSAL_PROVENANCE_NOT_OBSERVED,
    REFUSAL_NO_TIMESTAMP,
    REFUSAL_STALE,
    REFUSAL_OUT_OF_BAND,
})


class TrustedAPY(NamedTuple):
    """Результат чтения снимка: что принято, что отвергнуто и ПОЧЕМУ.

    ``apy_pct`` / ``apy_decimal`` содержат ТОЛЬКО доверяемые числа (может быть
    пусто — это законный ответ). ``refusals`` называет каждую отвергнутую строку.
    ``trusted`` — итоговый вердикт: есть ли хоть одно доверяемое наблюдение.
    """

    apy_pct: Dict[str, float]
    apy_decimal: Dict[str, float]
    refusals: List[Dict[str, Any]]
    unit: Optional[str]
    reason: str

    @property
    def trusted(self) -> bool:
        return bool(self.apy_pct)


def _refusal(protocol: str, reason: str, detail: str) -> Dict[str, Any]:
    return {"protocol": protocol, "refused": True, "reason": reason, "detail": detail}


def _parse_iso(value: Any) -> Optional[datetime]:
    """Разобрать ISO-8601 отметку в tz-aware UTC. Не получилось — ``None``.

    Терпит хвостовой ``Z`` (так пишет `apy_aggregator.save_ranking`) и наивную
    отметку (трактуется как UTC — иначе сравнение с ``now`` упадёт TypeError'ом,
    а падение сторожа хуже отказа).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def snapshot_unit(snapshot: Any) -> Optional[str]:
    """Единица, ОБЪЯВЛЕННАЯ снимком, или ``None`` (необъявлена).

    Переиспользует :func:`declared_apy_unit` — второго контракта единиц в проекте
    быть не должно. Словарь заворачивается в объект с атрибутом ``APY_UNIT``,
    потому что контракт читает атрибут, а не ключ.
    """
    if not isinstance(snapshot, dict):
        return None
    return declared_apy_unit(SimpleNamespace(**{
        APY_UNIT_ATTR: snapshot.get(SNAPSHOT_UNIT_KEY),
        "PROTOCOL": str(snapshot.get("source") or "apy_snapshot"),
    }))


def trusted_apy_map(
    snapshot: Any,
    *,
    now: datetime,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    rows_key: str = "by_apy",
    observed_sources: frozenset = OBSERVED_APY_SOURCES,
) -> TrustedAPY:
    """Прочитать снимок APY и вернуть ТОЛЬКО доверяемые числа + список отказов.

    Параметры
    ---------
    snapshot:
        Разобранный JSON снимка (``data/apy_ranking.json``-подобный). Любая другая
        форма — отказ целиком, без исключения.
    now:
        Момент отсчёта свежести. **Обязательный именованный аргумент**: стенные
        часы здесь не читаются, иначе тест на свежесть становится бомбой с
        часовым механизмом (`.claude/rules/deployment.md`).
    max_age_hours:
        Предел свежести наблюдения.
    observed_sources:
        Значения ``apy_source``, считающиеся НАБЛЮДЕНИЕМ. По умолчанию — реестр
        агрегатора (``{"live"}``); литерал/непроверенное наблюдением не является.

    Никогда не бросает исключений и никогда не подставляет значение: невозможность
    доверять числу выражается отказом с именем.
    """
    if not isinstance(snapshot, dict):
        return TrustedAPY({}, {}, [
            _refusal("*", REFUSAL_NO_SNAPSHOT,
                     f"snapshot is {type(snapshot).__name__}, not a dict"),
        ], None, "no snapshot (fail-closed)")

    unit = snapshot_unit(snapshot)
    if unit is None:
        # Отказ ЦЕЛИКОМ: без объявленной единицы ни одно число снимка не читается.
        return TrustedAPY({}, {}, [
            _refusal("*", REFUSAL_UNDECLARED_UNIT,
                     f"snapshot declares no {SNAPSHOT_UNIT_KEY!r}; the unit is never "
                     f"guessed from the magnitude of the number"),
        ], None, f"snapshot has no declared {SNAPSHOT_UNIT_KEY} (fail-closed)")

    rows = snapshot.get(rows_key)
    if not isinstance(rows, list):
        return TrustedAPY({}, {}, [
            _refusal("*", REFUSAL_BAD_ROW_SHAPE,
                     f"{rows_key!r} is {type(rows).__name__}, not a list"),
        ], unit, f"snapshot {rows_key!r} is not a list (fail-closed)")

    horizon = timedelta(hours=max(0.0, float(max_age_hours)))
    apy_pct: Dict[str, float] = {}
    apy_dec: Dict[str, float] = {}
    refusals: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            refusals.append(_refusal(f"row[{idx}]", REFUSAL_BAD_ROW_SHAPE,
                                     f"row is {type(row).__name__}, not a dict"))
            continue
        proto = row.get("protocol_key") or row.get("protocol")
        if not proto or not isinstance(proto, str):
            refusals.append(_refusal(f"row[{idx}]", REFUSAL_NO_PROTOCOL,
                                     f"protocol key missing/non-string: {proto!r}"))
            continue

        src = row.get("apy_source")
        if src not in observed_sources:
            refusals.append(_refusal(
                proto, REFUSAL_PROVENANCE_NOT_OBSERVED,
                f"apy_source={src!r} is not an observation "
                f"(observed: {sorted(observed_sources)}) — a literal must not "
                f"enter the tournament as a live reading",
            ))
            continue

        observed_at = _parse_iso(row.get("last_updated"))
        if observed_at is None:
            refusals.append(_refusal(proto, REFUSAL_NO_TIMESTAMP,
                                     f"last_updated unparseable: {row.get('last_updated')!r}"))
            continue
        age = now - observed_at
        if age > horizon:
            refusals.append(_refusal(
                proto, REFUSAL_STALE,
                f"observed {observed_at.isoformat()} — {age.total_seconds() / 3600.0:.1f}h "
                f"old, limit {max_age_hours:.1f}h",
            ))
            continue

        # 0.0 — ЗАКОННОЕ значение (честный нулевой APY), поэтому проверяется
        # наличие ключа, а не истинность числа: `if apy` теряло правдивый ноль.
        raw = row.get("apy_pct", row.get("current_apy"))
        dec = apy_decimal_from_declared(raw, unit, protocol=proto)
        if dec is None:
            refusals.append(_refusal(
                proto, REFUSAL_OUT_OF_BAND,
                f"apy {raw!r} ({unit}) rejected by the APY contract",
            ))
            continue

        # Первое доверяемое наблюдение по протоколу выигрывает: снимок отсортирован
        # по APY, и перезапись дала бы худшую (более позднюю) строку того же ключа.
        if proto in apy_dec:
            continue
        apy_dec[proto] = dec
        apy_pct[proto] = dec * 100.0

    reason = (
        f"{len(apy_pct)} trusted observation(s), {len(refusals)} refused "
        f"(unit={unit}, max_age={max_age_hours:.1f}h)"
    )
    if not apy_pct:
        reason = f"no trusted observation — {len(refusals)} refused (fail-closed)"
    return TrustedAPY(apy_pct, apy_dec, refusals, unit, reason)


def refusal_summary(refusals: Any) -> Dict[str, int]:
    """Свести отказы в ``{reason: count}`` — компактная форма для статуса/лога."""
    out: Dict[str, int] = {}
    if not isinstance(refusals, list):
        return out
    for r in refusals:
        if isinstance(r, dict):
            key = str(r.get("reason") or "unknown")
            out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
