"""spa_core/investment_os/directive.py — директива CIO для paper-цикла (ADR-103 + ADR-104).

Мандат владельца 2026-08-21: house-view Chief Investment перестал быть write-only
советом (ADR-103) — и «CIO должен следить за КАЖДЫМ движением актива и принимать
решения, не раз в день» (ADR-104). Оба закрыты здесь.

Как достигается «постоянное слежение» БЕЗ тяжёлого повтора суточного синтеза:
директива читает не только суточный house-view, но и ДВА непрерывных сигнала,
которые уже собираются каждые ~5 минут / в реальном времени:

  • data/intraday_equity.json — внутридневная просадка + tier (intraday_equity, 300с);
  • data/monitoring/risk_posture.json — оборонительная постура RTMR (rtmr_sense, daemon).

Любой из них, показавший движение вниз (intraday tier ≥ SOFT_DERISK, или portfolio
posture ≠ NORMAL), включает no_increase НЕМЕДЛЕННО — не дожидаясь суточного цикла.
Это и есть «решение на каждое движение»: движение ловят непрерывные сенсоры, CIO
реагирует тем же тактом. DERISK всегда быстро (ADR-055).

Границы мандата (не нарушаются этим модулем):
  • RiskPolicy v1.0 — ЕДИНСТВЕННЫЙ hard-гейт (инвариант #1); директива стоит НИЖЕ.
  • Kill-switch (ADR-034/048) не тронут; директива переиспользует ТУ ЖЕ механику
    «no new / no increase, hold+reduce OK», что и SOFT_DERISK.
  • Fail-closed. Для house-view — к НЕЙТРАЛИ (нет/протух артефакт ⇒ поведение
    прежнее: совет не становится гейтом через отсутствие). Для intraday/posture —
    к ОСТОРОЖНОСТИ на обнаруженном движении, но нечитаемый сигнал ≠ движение
    (нечитаемый intraday/posture молчит, не выдумывает просадку).
  • LLM_FORBIDDEN: всё — детерминированное чтение JSON. Никаких внешних вызовов.

Активная директива: (house-view ранга 3 RED/CRITICAL/STRESS из СВЕЖЕГО артефакта)
ИЛИ (intraday tier ≥ SOFT_DERISK) ИЛИ (risk_posture.portfolio ≠ NORMAL).
YELLOW и ниже без движения — наблюдение, не действие (SENSE часто · ACT редко).
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


def _intraday_movement(base: Path) -> Optional[str]:
    """Внутридневное движение вниз из data/intraday_equity.json (сенсор 300с).

    tier ≥ SOFT_DERISK ⇒ вернуть причину (движение обнаружено). Нет файла /
    нечитаем / tier NONE ⇒ None (нечитаемый сигнал НЕ выдумывает просадку).
    """
    try:
        doc = json.loads((base / "intraday_equity.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    tier = str(doc.get("tier") or "").upper()
    if tier in ("SOFT_DERISK", "HARD_KILL"):
        dd = doc.get("drawdown_pct")
        return f"intraday_{tier.lower()}: drawdown {dd}% — движение вниз, немедленно"
    return None


def _posture_movement(base: Path) -> Optional[str]:
    """Оборонительная постура RTMR из data/monitoring/risk_posture.json (daemon).

    portfolio ≠ NORMAL ⇒ вернуть причину. Нет файла / нечитаем / NORMAL ⇒ None.
    """
    try:
        doc = json.loads((base / "monitoring" / "risk_posture.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    portfolio = str(doc.get("portfolio") or "NORMAL").upper()
    if portfolio and portfolio != "NORMAL":
        return f"rtmr_posture_{portfolio.lower()}: оборонительная постройка — немедленно"
    return None


def load_directive(data_dir: Optional[str | Path] = None, *,
                   now: Optional[datetime] = None,
                   max_age_hours: float = MAX_AGE_HOURS) -> dict:
    """Прочитать house-view CIO и вернуть директиву. НИКОГДА не бросает.

    Возвращает {"active", "no_increase", "posture", "reason", "as_of"}.
    Любая проблема → нейтраль с названной причиной (наблюдаемый fail-closed).
    """
    base = Path(data_dir) if data_dir is not None else _PROJECT_ROOT / "data"

    # ── непрерывное слежение (ADR-104): движение вниз из intraday/RTMR-сенсоров
    # включает no_increase НЕМЕДЛЕННО, независимо от суточного house-view. Это и
    # есть «решение на каждое движение» — DERISK всегда быстро (ADR-055).
    for mover in (_intraday_movement(base), _posture_movement(base)):
        if mover:
            return {"active": True, "no_increase": True, "posture": "MOVEMENT_DERISK",
                    "reason": f"cio_intraday_derisk: {mover} (ADR-104)", "as_of": None}

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
