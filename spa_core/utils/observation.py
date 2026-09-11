"""Чтение наблюдения из артефакта: ОТСУТСТВИЕ отличимо от нуля (инвариант #17).

Решение владельца 2026-08-23 (ADR-129): «там, где наблюдения нет, система обязана
сказать „не знаю“, а не „всё хорошо“». Шесть находок одного дня 18.08 оказались одной
болезнью, и форма у неё одна — ``or``-подстановка:

    rate = doc.get("apy_pct") or 0.0        # «ставки нет» и «ставка 0 %» — одно и то же
    book = doc.get("positions") or {}       # «поля нет» и «книга пуста» — одно и то же

Третьего исхода у такого выражения нет ПО ПОСТРОЕНИЮ, поэтому оно и пишется само:
честный отказ длиннее. Эта функция делает честную форму короче подстановки.

    from spa_core.utils.observation import observed

    book = observed(doc, "positions", kind=dict)
    if book is None:
        return {"status": "UNMEASURED", "reason": "в снимке нет positions"}

``None`` здесь значит ровно «наблюдения нет»: ключа нет, значение ``None`` или оно не
того рода. Пустой словарь, пустой список и ноль остаются ЗНАЧЕНИЯМИ — они говорят
«измерено, и вот сколько». Отличать одно от другого обязан читающий: функция не решает
за него, она лишь не даёт исходам склеиться.

Только stdlib. Храповик класса — `spa_core/tests/test_absent_observation_ratchet.py`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Any


def observed(doc: Any, key: str, *, kind: type | tuple[type, ...] | None = None) -> Any:
    """Наблюдение ``key`` из ``doc`` — или ``None``, если наблюдения НЕТ.

    ``kind`` — ожидаемый род значения (``dict``, ``list``, ``(int, float)``…).
    Значение не того рода — тоже отсутствие наблюдения: мусор в поле не есть замер.
    ``bool`` под ``kind=(int, float)`` отвергается намеренно: «да» не является числом.
    """
    if not isinstance(doc, dict) or key not in doc:
        return None
    value = doc[key]
    if value is None:
        return None
    if kind is not None:
        if isinstance(value, bool) and kind is not bool and not (
                isinstance(kind, tuple) and bool in kind):
            return None
        if not isinstance(value, kind):
            return None
    return value


def observed_number(doc: Any, key: str) -> float | None:
    """Числовое наблюдение или ``None``. Нечисло и ``bool`` — отсутствие, не ноль."""
    value = observed(doc, key, kind=(int, float))
    return None if value is None else float(value)
