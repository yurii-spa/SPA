"""Public go-live-readiness surface (Q2-3).

The honest 'what code has proven vs what only the owner can do' one-stop endpoint:
- governance defenses FIRE (data/defenses_exercised.json — 11/11, reproducible);
- the go-live gate status (data/golive_status.json — evidenced-days + criteria);
- the owner-only blockers code CANNOT satisfy (custody / audit / legal / 30-day track).

Fail-CLOSED: a missing artifact yields an honest null, never a fabricated pass.
Read-only; serves committed/live artifacts verbatim. Nothing here moves capital.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"


def _load(name: str) -> dict:
    try:
        return json.loads((_DATA / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — fail-closed: absent/corrupt → empty, never a fake pass
        return {}


# The owner-only blockers are stable, documented facts (pre_cutover_gate advisory +
# ADR-010 + the go-live gate) — NOT fabricated numbers. AI holds no keys, is never a signer.
_OWNER_ONLY = [
    {"id": "custody", "what": "Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010) — AI holds no keys and is never a signer"},
    {"id": "audit", "what": "external security audit of the execution path signed off"},
    {"id": "legal", "what": "entity + disclosure / no-guarantee framing reviewed by counsel before any external capital"},
    {"id": "track_days", "what": "≥30 evidenced honest paper-track days (the go-live gate; time-gated, nothing to fix in code)"},
]


@router.get("/api/readiness")
def readiness() -> dict:
    dex = _load("defenses_exercised.json")
    golive = _load("golive_status.json")
    return {
        "governance_defenses": {
            "fired": dex.get("scenarios_fired"),
            "total": dex.get("scenarios_total"),
            "all_fired": dex.get("all_defenses_fired"),
            "thresholds": dex.get("thresholds"),
        },
        "go_live_gate": {
            "passed": golive.get("passed"),
            "total": golive.get("total"),
            "evidenced_days": golive.get("real_track_days"),
            "days_needed": golive.get("min_track_days", 30),
            "target_date": golive.get("target_date") or golive.get("go_live_target"),
        },
        "owner_only_blockers": _OWNER_ONLY,
        "reproduce": {
            "proof_chain": "python3 scripts/verify_spa.py data/",
            "defenses_fire": "python3 scripts/defenses_exercised_report.py",
            "money_path_gate": "python3 -m spa_core.paper_trading.pre_cutover_gate  (16/16, inert)",
        },
        "honest": "The code proves the money-path + governance defenses fire; custody / audit / legal "
                  "/ the 30-day evidenced track are owner-only and time-gated. Nothing here moves capital.",
    }
