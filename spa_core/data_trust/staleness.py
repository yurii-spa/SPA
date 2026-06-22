"""
Staleness check utility — отдельный компонент проверки свежести данных.
LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from datetime import datetime
from typing import Optional, Dict


def check_staleness(
    fetched_at: Optional[str],
    max_seconds: int = 3600,
    as_of: Optional[datetime] = None,
) -> Dict:
    """
    Проверяет свежесть timestamp.

    Args:
        fetched_at: ISO timestamp строка
        max_seconds: максимальный возраст в секундах
        as_of: PIT точка (для бэктеста)

    Returns:
        {"ok": bool, "age_seconds": float, "stale": bool, "reason": str}
    """
    # LLM_FORBIDDEN
    if fetched_at is None:
        return {"ok": False, "age_seconds": None, "stale": True, "reason": "missing_timestamp"}

    try:
        ts = datetime.fromisoformat(fetched_at.rstrip("Z"))
    except ValueError:
        return {"ok": False, "age_seconds": None, "stale": True, "reason": "invalid_timestamp"}

    now = as_of or datetime.utcnow()
    age = (now - ts).total_seconds()
    stale = age > max_seconds

    return {
        "ok": not stale,
        "age_seconds": age,
        "stale": stale,
        "reason": f"stale: age {age:.0f}s > max {max_seconds}s" if stale else "fresh",
    }


def check_all_stale(
    timestamps: Dict[str, Optional[str]],
    max_seconds: int = 3600,
    as_of: Optional[datetime] = None,
) -> Dict[str, Dict]:
    """Проверяет набор timestamps."""
    # LLM_FORBIDDEN
    return {
        name: check_staleness(ts, max_seconds, as_of)
        for name, ts in timestamps.items()
    }
