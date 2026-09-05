"""ADR-233 — общий помощник: личность пула, разрешённого адаптером в этом вызове.

Отдельный модуль, а не копия в каждом адаптере: семь опрашиваемых адаптеров задают
фиду один и тот же вопрос, и разъехавшиеся копии этого вопроса — ровно тот класс,
который проект уже ловил на трёх реестрах с одним именем (`.claude/rules/adapters.md`).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

from spa_core.utils.errors import safe_call


def resolved_pool_id(feed, *args, **kwargs) -> Optional[str]:
    """UUID пула, который отбор выбрал в ЭТОМ вызове, или ``None`` (ADR-233).

    ``getattr`` здесь не украшение. Обращение ``feed.get_pool_id`` вычисляется
    ДО того, как ``safe_call`` получит управление, поэтому фид без этого метода
    (тестовый двойник, альтернативная реализация) поднял бы ``AttributeError``
    прямо из ``fetch()`` — а ``fetch()`` по контракту НЕ БРОСАЕТ никогда и обязан
    возвращать честный отказ. Замер 05.09: так падали 23 существующие проверки.

    Фид, не умеющий назвать пул, даёт ``None`` — «личность НЕ ИЗМЕРЕНА». Это
    третий исход, а не «пул тот же»: потребитель обязан их различать.
    """
    getter = getattr(feed, "get_pool_id", None)
    if getter is None:
        return None
    resolved = safe_call(getter, *args, default=None, log_error=False, **kwargs)
    if not isinstance(resolved, str) or not resolved.strip():
        return None
    return resolved.strip()

