"""spa_core/api/routers/fundability.py — public per-sleeve HONEST verdicts (Q-OWN-05).

Owner-approved (2026-07-12): publish the forward-analytics per-sleeve verdicts on /fundability —
INCLUDING the flagship rates_desk_fixed_carry sleeve currently sitting BELOW_FLOOR. The thesis:
a public, timestamped "our own flagship doesn't clear the bar yet" is a costly-signal asset a
competitor can't fake — and the honest track record is the LP-facing product.

This endpoint serves the verdicts VERBATIM from data/forward_analytics.json (no re-derivation, no
fabrication). Every number is paper forward-track, advisory, NOT live capital. THIN_TRACK (not enough
data yet) and BELOW_FLOOR (has data, doesn't beat the floor) are kept as DISTINCT states so a viewer
never confuses "too early to tell" with "losing". Read-only, fail-closed (missing artifact → honest
empty), never a gate.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["fundability"])

_DATA = Path(__file__).resolve().parents[3] / "data"

# Human-friendly display names for the flagship + notable sleeves (opaque internal → readable).
_FLAGSHIP = "rates_desk_fixed_carry"


def _clean_name(raw: str) -> str:
    """Strip the store prefix (paper/…, strategy_lab_paper/…) for display."""
    return (raw or "").split("/")[-1]


@router.get("/api/fundability/sleeves")
def sleeves() -> dict:
    """Per-sleeve forward verdicts vs the RWA floor — served verbatim from forward_analytics.json.

    Each sleeve: name, verdict (BEATS_FLOOR | THIN_TRACK | BELOW_FLOOR), excess vs floor (pp),
    evidenced points, days-to-robust-verdict, is_flagship. Fail-closed: no artifact → empty + note."""
    try:
        d = json.loads((_DATA / "forward_analytics.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a public page must never 500
        return {"available": False, "sleeves": [], "counts": {},
                "note": "forward-analytics artifact not yet available (accrues on the paper track)."}

    floor = d.get("rwa_floor_apy_pct")
    out = []
    counts: dict = {"BEATS_FLOOR": 0, "THIN_TRACK": 0, "BELOW_FLOOR": 0}
    for t in d.get("tracks", []):
        v = t.get("verdict")
        if v in counts:
            counts[v] += 1
        raw = t.get("name", "")
        out.append({
            "name": _clean_name(raw),
            "verdict": v,
            "excess_vs_floor_pct": t.get("excess_vs_floor_pct"),
            "ann_return_pct": t.get("ann_return_pct"),
            "n_points": t.get("n_points"),
            "days_to_robust_verdict": t.get("days_to_robust_verdict"),
            "is_flagship": (_clean_name(raw) == _FLAGSHIP),
        })
    # flagship first, then BEATS, THIN, BELOW — so the honest flagship signal is prominent, not buried.
    order = {"BEATS_FLOOR": 1, "THIN_TRACK": 2, "BELOW_FLOOR": 0}
    out.sort(key=lambda s: (not s["is_flagship"], order.get(s["verdict"], 3), _clean_name(s["name"])))
    return {
        "available": True,
        "rwa_floor_apy_pct": floor,
        "min_points_for_verdict": d.get("min_points_for_ratio"),
        "generated_at": d.get("generated_at"),
        "counts": counts,
        "sleeves": out,
        "evidence_level": "paper",
        "note": ("Paper forward-track, advisory, NOT live capital. THIN_TRACK = not enough evidenced "
                 "days yet; BELOW_FLOOR = has data and does not beat the RWA floor risk-adjusted. We "
                 "publish both — including our own flagship below the floor — because the honest, "
                 "timestamped record is the product."),
    }
