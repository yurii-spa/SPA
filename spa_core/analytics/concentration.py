"""Portfolio concentration metrics (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations


def calculate_concentration(allocation: dict) -> dict:
    """Concentration of a ``{protocol_id: weight}`` allocation.

    Non-positive / non-numeric weights are ignored; the remaining weights
    are normalized to sum to 1, so absolute USD amounts work as well as
    fractional weights. Herfindahl index: 1/n (equal weights) … 1.0
    (single position).
    """
    weights = sorted(
        (
            float(w)
            for w in (allocation or {}).values()
            if isinstance(w, (int, float)) and float(w) > 0
        ),
        reverse=True,
    )
    total = sum(weights)
    if not weights or total <= 0:
        return {
            "herfindahl_index": 0.0,
            "top1_weight": 0.0,
            "top3_weight": 0.0,
            "n_active": 0,
        }
    norm = [w / total for w in weights]
    return {
        "herfindahl_index": round(sum(w * w for w in norm), 6),
        "top1_weight": round(norm[0], 6),
        "top3_weight": round(sum(norm[:3]), 6),
        "n_active": len(norm),
    }
