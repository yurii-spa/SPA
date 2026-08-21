"""spa_core/investment_os/directive.py — директива CIO для paper-цикла (ADR-103).

Мандат владельца 2026-08-21 (дословно: «Снять ограничения разрешаю все»): house-view
Chief Investment перестаёт быть write-only советом — его постура ДВИГАЕТ paper-книги.
Границы мандата, записанные в ADR-103 и не нарушаемые этим модулем:

  • RiskPolicy v1.0 остаётся ЕДИНСТВЕННЫМ hard-гейтом (инвариант #1) — директива
    стоит НИЖЕ него и ничего в нём не меняет.
  • Kill-switch (ADR-034/048) не тронут; директива переиспользует ТУ ЖЕ механику
    «no new / no increase, hold+reduce OK», что и SOFT_DERISK.
  • Fail-closed К НЕЙТРАЛИ: нет артефакта / артефакт протух / статус не ok /
    постура не осторожная — директива НЕАКТИВНА и цикл ведёт себя как раньше.
    Отсутствие advisory-артефакта НЕ останавливает деск (иначе совет стал бы
    гейтом через своё отсутствие — новая хрупкость, которой мандат не просил).
  • LLM_FORBIDDEN: house-view собран детерминированным кодом (harness), этот
    модуль — чистое чтение JSON. Никаких внешних вызовов.

Активная директива ровно одна: постура ранга 3 (RED / CRITICAL / STRESS) из
СВЕЖЕГО артефакта (≤ MAX_AGE_HOURS, SLO самого агента) ⇒ no_increase=True.
YELLOW и ниже — наблюдение, не действие (SENSE часто · ACT редко, ADR-055).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Постуры, при которых CIO запрещает наращивание (ранг 3 в _RANK chief_investment).
NO_INCREASE_POSTURES = frozenset({"RED", "CRITICAL", "STRESS"})

#: Свежесть = SLO артефакта io_chief_investment из architecture/manifest.json (26h).
MAX_AGE_HOURS = 26.0


def _neutral(reason: str) -> dict:
    return {"active": False, "no_increase": False, "posture": None,
            "reason": reason, "as_of": None}


def load_directive(data_dir: Optional[str | Path] = None, *,
                   now: Optional[datetime] = None,
                   max_age_hours: float = MAX_AGE_HOURS) -> dict:
    """Прочитать house-view CIO и вернуть директиву. НИКОГДА не бросает.

    Возвращает {"active", "no_increase", "posture", "reason", "as_of"}.
    Любая проблема → нейтраль с названной причиной (наблюдаемый fail-closed).
    """
    base = Path(data_dir) if data_dir is not None else _PROJECT_ROOT / "data"
    artifact = base / "investment_os" / "chief_investment.json"
    try:
        doc = json.loads(artifact.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _neutral("no chief_investment artifact (advisory absent ⇒ neutral)")
    except Exception as exc:  # noqa: BLE001
        return _neutral(f"chief_investment artifact unreadable ({type(exc).__name__})")

    if str(doc.get("status") or "").lower() != "ok":
        return _neutral(f"chief_investment status={doc.get('status')!r} (not ok ⇒ neutral)")

    # Свежесть: протухший совет не двигает книгу (тот же принцип, что stale-фид).
    ts = str(doc.get("generated_at") or "")
    try:
        gen = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        age_h = ((now or datetime.now(timezone.utc)) - gen).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return _neutral("chief_investment generated_at unparseable (⇒ neutral)")
    if age_h > max_age_hours or age_h < 0:
        return _neutral(f"chief_investment stale ({age_h:.1f}h > {max_age_hours}h ⇒ neutral)")

    posture = str(((doc.get("house_view") or {}).get("overall_posture")) or "").upper()
    if not posture:
        return _neutral("house_view has no overall_posture (⇒ neutral)")

    no_inc = posture in NO_INCREASE_POSTURES
    return {
        "active": no_inc,
        "no_increase": no_inc,
        "posture": posture,
        "reason": (f"cio_posture_{posture.lower()}: hold+reduce only (ADR-103)"
                   if no_inc else f"cio_posture_{posture.lower()}: no restriction"),
        "as_of": ts,
    }


def cio_allows_new_positions(data_dir: Optional[str | Path] = None, *,
                             now: Optional[datetime] = None) -> bool:
    """True, если CIO не запрещает открывать НОВЫЕ paper-позиции (рукава B/C)."""
    return not load_directive(data_dir, now=now)["no_increase"]
