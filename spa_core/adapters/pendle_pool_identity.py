"""Крест ДВУХ пространств имён личности: рынок Pendle ↔ пул DeFiLlama (ADR-239).

Вопрос, ради которого написан модуль, поставлен карточкой голодающего приказа CIO
дословно: **«один ли это рынок»** у ключей ``pendle`` и ``pendle_pt_susde``. До
2026-09-06 ответить на него было НЕЧЕМ, и не потому, что никто не смотрел:

* ``pendle`` берёт число из Pendle V2 REST, где инструмент зовётся АДРЕСОМ рынка
  (``0xc5f938a8…``) — в этой вселенной UUID DeFiLlama не существует вовсе;
* ``pendle_pt_susde`` резолвится генератором ``adapter_status`` в пул DeFiLlama
  (``fc9a73bc…``) — в ЭТОЙ вселенной адреса рынка нет.

Сторож тождества (``pool_identity_collision``) сравнивает UUID, поэтому ключ без
UUID выпадает из сверки ПО ПОСТРОЕНИЮ: про ``pendle`` он не говорит «коллизии
нет», он говорит «сравнивать нечем». Цикл #498 записал этот отказ причиной в
``pendle_adapter.py`` — честно и намеренно, — и назвал сведение пространств
отдельной задачей. Это она.

Почему «положить туда адрес рынка» было бы ХУЖЕ молчания
========================================================
Строка из одного пространства имён, выданная за строку из другого, даёт сторожу
вердикт, которого никто не мерил: ``0xc5f938a8…`` и ``fc9a73bc…`` разошлись бы
как «разные пулы» ДАЖЕ НА ОДНОМ И ТОМ ЖЕ рынке. Крест обязан быть измерен, а не
объявлен.

Ключ креста — ИНСТРУМЕНТ, а не цена
===================================
Замер 2026-09-06 по живым источникам (Pendle REST + выгрузка DeFiLlama, 17 176
пулов, 90 строк ``pendle-v2``/Ethereum) показал, что привычные признаки отбора
здесь ВЫРОЖДЕНЫ:

* **TVL не разделяет.** Строки приходят ПАРАМИ на один рынок — нога PT и нога LP,
  — и TVL у них БАЙТ В БАЙТ один: APYUSD $21 447 313 у обеих. Общий отбор
  ``DeFiLlamaFeed.get_pool_id('pendle-v2', 'APYUSD')`` («побеждает больший TVL»)
  отдаёт на этом семействе ногу **LP** ``8dc83a62…`` (13.732 пп, из них 0.344 пп
  эмиссия) вместо ноги **PT** ``9fe33fd6…`` (14.018 пп целиком ``apyBase``) —
  то есть ДРУГОЙ инструмент с другим риском. Это не гипотеза: так отвечает живой
  код на живых данных, и на этом стои́т положительный контроль модуля.
* **Цена не разделяет и не опознаёт.** APY двух ног расходится по-разному от
  пары к паре (USDAT: 6.31 против 2.61 — в 2.4 раза; APYUSD: 14.02 против 13.73),
  а между сторонами дрейфует сам по себе: 05.09 наблюдения сошлись до 4-го знака,
  06.09 разошлись на 0.0036 пп. Совпадение цены — ПОДТВЕРЖДЕНИЕ с собственной
  ценой ошибки, а не удостоверение личности.
* **Срок один не разделяет.** В той же выгрузке ``PT-strUSD-26NOV2026`` и
  ``PT-sUSDe-26NOV2026`` — один день погашения, разные инструменты.
* **Актив один не разделяет.** У одного актива живут несколько выпусков.

Разделяет ПАРА (базовый актив, дата погашения) при обязательной ноге «For buying
PT-», то есть ровно то, чем инструмент и определён. Ни одно из этих полей не
меняется от того, что сдвинулась цена или переток TVL.

Fail-CLOSED и третий исход
==========================
Совпал РОВНО ОДИН пул ⇒ личность названа. Ни одного ⇒ отказ с причиной. Больше
одного ⇒ отказ с причиной (выбирать из двух одинаково подходящих — это монетка,
а монетка не наблюдение). Причина возвращается ВСЕГДА и записывается рядом с
результатом: «не измерено» обязано быть отличимо от «пул тот же».

Только stdlib; сеть модуль не трогает — популяция пулов приходит параметром.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Sequence

# Проект DeFiLlama, под которым живут рынки Pendle V2.
LLAMA_PROJECT = "pendle-v2"

# Нога PT (покупка выпуска) против ноги LP. Различает ТОЛЬКО poolMeta —
# symbol и TVL у них одинаковые (см. замер в докстроке модуля).
PT_BUY_PREFIX = "for buying pt-"

# Допуск ПОДТВЕРЖДЕНИЯ (не отбора). Наблюдённый разброс между двумя источниками
# на одном и том же инструменте: 0.0000 пп (05.09) и 0.0036 пп (06.09). Порог
# 0.5 пп — примерно в 140 раз шире измеренного шума: он ловит грубое
# расхождение («мы смотрим не туда»), а не дрожь двух опросов, сделанных врозь.
CORROBORATION_TOLERANCE_PP = 0.5

# Исходы подтверждения.
CORROBORATED = "corroborated"
DIVERGENT = "divergent"
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class PoolIdentity:
    """Ответ креста: личность пула ЛИБО названная причина её отсутствия.

    ``pool_id`` ``None`` означает «НЕ ИЗМЕРЕНО», и ``reason`` в этом случае
    говорит, почему именно, — потребитель обязан различать это и «пул тот же».
    ``corroboration`` — ОТДЕЛЬНЫЙ вопрос («сходится ли цена у опознанного
    инструмента»); он никогда не решает вопрос личности, у него своя цена ошибки.
    """

    pool_id: Optional[str]
    reason: str
    candidates: int
    apy_delta_pp: Optional[float] = None
    corroboration: str = UNMEASURED


def parse_maturity(text: str) -> Optional[date]:
    """Дата погашения из хвоста ``…-05NOV2026``, или ``None``.

    Месяц в фиде приходит капсом, а ``%b`` ждёт ``Nov``: приводится ЗНАЧЕНИЕ, не
    формат (тот же капкан разобран в ``adapter_status_generator._pt_maturity``).
    Не разобралось ⇒ ``None``: инструмент с нечитаемым сроком не опознан.
    """
    tail = str(text or "").rsplit("-", 1)[-1].strip().title()
    for fmt in ("%d%b%Y", "%d%B%Y"):
        try:
            return datetime.strptime(tail, fmt).date()
        except ValueError:
            continue
    return None


def parse_pt_leg(pool: dict) -> Optional[tuple[str, date]]:
    """``(актив в нижнем регистре, дата погашения)`` для ноги PT, иначе ``None``.

    ``None`` возвращается и для ноги LP, и для нечитаемого ``poolMeta`` — обе
    записи не есть покупаемый выпуск PT, и различать их дальше незачем.
    """
    if not isinstance(pool, dict):
        return None
    meta = str(pool.get("poolMeta") or "")
    low = meta.lower()
    if not low.startswith(PT_BUY_PREFIX):
        return None
    body = meta[len(PT_BUY_PREFIX):]        # "apyUSD-05NOV2026"
    maturity = parse_maturity(body)
    if maturity is None:
        return None
    asset = body.rsplit("-", 1)[0].strip().lower()
    if not asset:
        return None
    return asset, maturity


def _iso_date(value: object) -> Optional[date]:
    """ISO-строка (или ``date``) → ``date``; всё прочее → ``None``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def resolve_pool_identity(
    *,
    underlying_asset: object,
    maturity_date: object,
    pools: Optional[Sequence[dict]],
    implied_apy_pct: Optional[float] = None,
    chain: str = "Ethereum",
    project: str = LLAMA_PROJECT,
) -> PoolIdentity:
    """UUID пула DeFiLlama для КОНКРЕТНОГО рынка Pendle, или названный отказ.

    Вход — рынок, УЖЕ выбранный адаптером (его базовый актив и срок), и снимок
    пулов фида. Отбор здесь не повторяется и число не пересчитывается: вопрос
    ровно один — как ЭТОТ инструмент зовётся во второй вселенной имён.
    """
    asset = str(underlying_asset or "").strip().lower()
    maturity = _iso_date(maturity_date)
    if not asset or maturity is None:
        return PoolIdentity(
            None,
            "рынок Pendle не назвал базовый актив и срок — опознавать нечем",
            0,
        )
    if not pools:
        return PoolIdentity(
            None,
            "снимок пулов DeFiLlama недоступен — вторая вселенная имён не прочитана",
            0,
        )

    project_l = project.strip().lower()
    chain_l = chain.strip().lower()
    matches: list[dict] = []
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        if str(pool.get("project", "")).strip().lower() != project_l:
            continue
        if str(pool.get("chain", "")).strip().lower() != chain_l:
            continue
        leg = parse_pt_leg(pool)
        if leg is None:
            continue
        if leg != (asset, maturity):
            continue
        pool_id = pool.get("pool")
        if not isinstance(pool_id, str) or not pool_id.strip():
            continue
        matches.append(pool)

    if not matches:
        return PoolIdentity(
            None,
            f"в фиде нет ноги PT для {asset}/{maturity.isoformat()} "
            f"({project_l}/{chain_l})",
            0,
        )
    if len(matches) > 1:
        # Два пула на один инструмент — это находка, а не повод выбрать один из
        # них: любой выбор здесь монетка, а монетка не наблюдение.
        return PoolIdentity(
            None,
            f"ноге PT {asset}/{maturity.isoformat()} отвечают {len(matches)} пулов — "
            f"выбор был бы монеткой",
            len(matches),
        )

    pool = matches[0]
    pool_id = str(pool.get("pool")).strip()

    # ── Подтверждение ценой: ОТДЕЛЬНЫЙ вопрос со своей ценой ошибки ──────────
    # Расхождение здесь НЕ отменяет опознания: инструмент определён активом и
    # сроком, а два источника опрашиваются в разные моменты. Расхождение цены —
    # предмет `adapter_feed_divergence`, и оно записывается, а не проглатывается.
    delta = None
    verdict = UNMEASURED
    llama_apy = pool.get("apy")
    if (
        isinstance(implied_apy_pct, (int, float))
        and not isinstance(implied_apy_pct, bool)
        and isinstance(llama_apy, (int, float))
        and not isinstance(llama_apy, bool)
    ):
        delta = round(abs(float(llama_apy) - float(implied_apy_pct)), 6)
        verdict = CORROBORATED if delta <= CORROBORATION_TOLERANCE_PP else DIVERGENT

    return PoolIdentity(
        pool_id,
        f"нога PT {asset}/{maturity.isoformat()} совпала ровно одним пулом",
        1,
        apy_delta_pp=delta,
        corroboration=verdict,
    )
