#!/usr/bin/env python3
"""Одно определение «пул проходит порог TVL» — на всех читателей (карточка 07.08).

Замер, из-за которого файл появился (цикл #143, повторно подтверждён 08.08 на
артефактах 12:33Z): атрибуция кэша (``attribute_cash``, ADR-055) и гейт RiskPolicy
пользовались РАЗНЫМИ определениями одного и того же. Атрибуция смотрела только на
ПРОИСХОЖДЕНИЕ TVL (``proto in tvl_live``) и не знала про порог $5M вовсе, поэтому
``moonwell_base`` (TVL $1.41M) стоял в списке «fundable headroom» — комнаты, которую
аллокатору финансировать ЗАПРЕЩЕНО, — и вменялся аллокатору как лень.

Обе половины дефекта работают в одну сторону: ЗАВЫШАЮТ пригодную комнату, то есть
завышают ``unexplained_deployable`` — число, по которому ``agent_health`` обвиняет
аллокатор. Ложное обвинение обесценивает настоящее.

**Порог здесь не живёт.** Значение приходит входом (``RiskConfig.min_tvl_usd``);
ни одного литерала в этом модуле нет — иначе получилась бы третья копия правила.
Модуль отвечает ровно на один вопрос: ПРИ ДАННОМ пороге проходит ли данный TVL.

Fail-CLOSED, ровно как у аллокатора (``allocator._filter_by_tvl``, MP-011/ADR-053):

* TVL отсутствует (``None``) ⇒ НЕ проходит (аллокатор коэрсит ``None`` в 0.0 и
  отклоняет; «не измерено» никогда не значит «пригоден по умолчанию»);
* TVL не финитный (``NaN`` / ``inf`` из битого фида) ⇒ НЕ проходит: ``inf >= floor``
  прошёл бы numerically, а дальше MP-209 делит на этот TVL и в money-path уезжает
  ``NaN``-вес (property-тест PROP-TVL-NONFINITE);
* нечисловое значение ⇒ НЕ проходит;
* порог не разрешён (``None``) ⇒ вопрос НЕ измерен — вызывающий обязан сообщить это
  как UNCHECKED, а не подставить свой литерал (см. :func:`floor_is_resolved`).

Точное сравнение — ``>=``: пул РОВНО на пороге проходит (так у аллокатора и у
``policy.py:386``). Изменение этого знака — изменение RiskPolicy, а не рефакторинг.

Read-only · детерминированно · только stdlib · LLM запрещён · ничего не пишет.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

__all__ = ["coerce_tvl", "passes_tvl_floor", "floor_is_resolved", "floor_reason"]


def coerce_tvl(raw: object) -> float:
    """Приведение сырого TVL к числу ПО ПРАВИЛУ АЛЛОКАТОРА (``_filter_by_tvl``).

    ``None`` → 0.0 (аллокатор именно так: отсутствующий TVL отклоняется порогом),
    нечисловое → ``NaN`` (не финитно ⇒ отклоняется). Никогда не бросает.
    """
    if raw is None:
        return 0.0
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def floor_is_resolved(min_tvl_usd: Optional[float]) -> bool:
    """Разрешён ли порог. ``None`` ⇒ вопрос не измерен (fail-CLOSED у вызывающего)."""
    if min_tvl_usd is None:
        return False
    try:
        return math.isfinite(float(min_tvl_usd))
    except (TypeError, ValueError):
        return False


def passes_tvl_floor(raw_tvl: object, min_tvl_usd: Optional[float]) -> bool:
    """Проходит ли пул порог TVL. Единственное место, где это решается.

    Порог не разрешён ⇒ ``False``: не «пропустить на всякий случай», а «не пригоден,
    пока не измерено» (и вызывающий обязан пометить это UNCHECKED, чтобы отказ не
    выглядел как обоснованное объяснение простоя).
    """
    if not floor_is_resolved(min_tvl_usd):
        return False
    tvl = coerce_tvl(raw_tvl)
    return math.isfinite(tvl) and tvl >= float(min_tvl_usd)  # type: ignore[arg-type]


def floor_reason(raw_tvl: object, min_tvl_usd: Optional[float]) -> Tuple[bool, str]:
    """``(проходит, причина)`` — причина называет ИМЕННО то, что помешало.

    «не измерен» и «измерен и мал» — разные состояния книги: первое чинится фидом,
    второе — это честный отказ по политике. Слипшись в одну строку, они дали бы тот
    же класс, что и «UNEXPLAINED, потому что причина не названа».
    """
    if not floor_is_resolved(min_tvl_usd):
        return False, "tvl_floor_unresolved"
    if raw_tvl is None:
        return False, "tvl_unmeasured"
    tvl = coerce_tvl(raw_tvl)
    if not math.isfinite(tvl):
        return False, "tvl_non_finite"
    if tvl <= 0.0:
        return False, "tvl_unmeasured"
    floor = float(min_tvl_usd)  # type: ignore[arg-type]
    if tvl < floor:
        return False, "tvl_below_floor:${:,.0f}<${:,.0f}".format(tvl, floor)
    return True, ""
