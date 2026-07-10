"""6mo-M2 #16 — tournament DATA-TRUST monitor (deterministic, advisory, fail-CLOSED).

The tournament ranking is stamped `trustworthy=False` today (its backtest runs on mock/degenerate data —
see Part A of the 6-month backlog). Two future transitions are therefore SIGNIFICANT and must NOT slip
by unnoticed:

  1. `trustworthy` flips True on either tournament artifact — the data-quality claim changed; a human must
     confirm the feeds were actually fixed (#13) before any ranking is believed.
  2. `total_promotions` goes non-zero — the engine promoted a strategy toward 'live'. On untrusted data a
     promotion is a THEATER hazard; every promotion needs human review before it means anything.

This monitor watches both and raises an advisory ALERT on either. It is fail-CLOSED: a missing/corrupt
artifact is reported as an explicit unknown, never silently OK. It compares against the previously-written
status to stamp WHEN a transition first appeared (auditable), but the verdict is ABSOLUTE — trustworthy
True or promotions>0 is an ALERT regardless of history, because on untrusted data neither should happen.

Deterministic, stdlib-only, LLM-forbidden. Writes data/data_trust_status.json atomically. Advisory —
never gates, never promotes, never moves capital.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_MASS = _DATA / "mass_tournament_results.json"
_TOURN = _DATA / "strategy_tournament.json"
_ENGINE = _DATA / "tournament_engine_state.json"
_OUT = _DATA / "data_trust_status.json"

OK = "OK"
ALERT = "ALERT"


def _load(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _now_iso(now: Optional[str] = None) -> str:
    return now if now is not None else datetime.now(timezone.utc).isoformat()


def build_report(*, now_iso: Optional[str] = None, write: bool = True) -> dict:
    mass = _load(_MASS)
    tourn = _load(_TOURN)
    engine = _load(_ENGINE)
    prior = _load(_OUT) or {}

    # trustworthy across both ranking artifacts (None = artifact missing → unknown, NOT trusted)
    mass_trust = mass.get("trustworthy") if mass else None
    tourn_trust = tourn.get("trustworthy") if tourn else None
    any_trust_true = (mass_trust is True) or (tourn_trust is True)

    total_promotions = (engine or {}).get("total_promotions")
    promotions_fired = isinstance(total_promotions, int) and total_promotions > 0

    reasons = []
    if any_trust_true:
        reasons.append(
            f"tournament trustworthy flipped True (mass={mass_trust}, strategy={tourn_trust}) — "
            "confirm the feeds were actually fixed (#13) before believing any ranking")
    if promotions_fired:
        reasons.append(
            f"total_promotions={total_promotions} (>0) — a strategy was promoted toward 'live' on "
            "untrusted data; human review required before it counts")

    missing = [p.name for p, d in ((_MASS, mass), (_TOURN, tourn), (_ENGINE, engine)) if d is None]
    status = ALERT if reasons else OK

    now = _now_iso(now_iso)
    # first-seen stamping (auditable transition time), carried from the prior status when unchanged
    first_alert_at = prior.get("first_alert_at")
    if status == ALERT and not first_alert_at:
        first_alert_at = now
    elif status == OK:
        first_alert_at = None

    report = {
        "model": "data_trust_monitor",
        "generated_at": now,
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "status": status,
        "mass_trustworthy": mass_trust,
        "strategy_trustworthy": tourn_trust,
        "total_promotions": total_promotions,
        "reasons": reasons,
        "missing_artifacts": missing,
        "first_alert_at": first_alert_at,
        "note": (
            "Watches the tournament data-trust flags + promotion counter. On untrusted data (the current "
            "expected state: trustworthy=False, total_promotions=0 → OK) any flip to trustworthy=True or "
            "any promotion firing is an advisory ALERT needing human review — NOT an automatic trust. "
            "fail-CLOSED: a missing artifact is reported (missing_artifacts), never treated as trusted. "
            "Advisory — never gates, never promotes, never moves capital."
        ),
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


def main() -> int:
    rep = build_report(write=True)
    print(f"data-trust: {rep['status']}  "
          f"(mass_trust={rep['mass_trustworthy']}, strategy_trust={rep['strategy_trustworthy']}, "
          f"promotions={rep['total_promotions']})")
    for r in rep["reasons"]:
        print(f"  ALERT: {r}")
    if rep["missing_artifacts"]:
        print(f"  missing: {rep['missing_artifacts']}")
    print(f"  → wrote {_OUT}")
    return 1 if rep["status"] == ALERT else 0


if __name__ == "__main__":
    raise SystemExit(main())
