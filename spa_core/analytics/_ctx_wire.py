"""
_ctx_wire.py — общий помощник контекст-веток Tier-B (audit 2026-08-05, A2).

Единственная задача: свести результат СОБСТВЕННОГО движка модуля (dict со
score-ключом «выше = лучше» или «выше = опаснее») к протокол-сигналу
агрегатора {"risk_score": 0-100, выше = опаснее}. Полярность задаётся явно
вызывающей веткой — класс ошибки «инвертировали не туда» известен по фазе 2.

Никакой фабрикации: нет валидного числа / INSUFFICIENT_DATA → None
(громкий dormant в агрегаторе). stdlib-only, LLM FORBIDDEN.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

CTX_WIRE_SOURCE = "protocol_facts+apy_series"


def engine_risk(res: Any, protocol: str,
                higher_is_better: bool = True,
                score_key: str = "score",
                insufficient_label: str = "INSUFFICIENT_DATA",
                extra: Optional[Dict[str, Any]] = None,
                ) -> Optional[Dict[str, Any]]:
    """Результат движка → {"risk_score": ...} | None (не измерено).

    higher_is_better=True → risk = 100 - score (движки семейства vault-*
    отдают «выше = честнее/безопаснее»); False → risk = score как есть.
    """
    if not isinstance(res, dict):
        return None
    if res.get("classification") == insufficient_label:
        return None
    v = res.get(score_key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    fv = float(v)
    if not math.isfinite(fv):
        return None
    score = max(0.0, min(100.0, fv))
    risk = 100.0 - score if higher_is_better else score
    out: Dict[str, Any] = {
        "protocol": protocol,
        "risk_score": round(risk, 2),
        "engine_score": round(fv, 2),
        "classification": res.get("classification"),
        "source": CTX_WIRE_SOURCE,
    }
    if extra:
        out.update(extra)
    return out
