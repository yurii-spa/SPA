"""spa_core/reporting/compound_apy.py — the ONE compound-annualisation formula
(ADR-580 C2, RM-TRUTH-01 workstream W5).

RM-TRUTH-01's audit (``docs/rm_truth/A3_product.md`` §2) found the SAME "Conservative
realized APY" computed by at least five different formulas across the codebase, three
of them LINEAR over a window that includes non-evidenced days — which is how the
higher-risk packages ended up printing a LOWER annualized number than the lower-risk
one (the gas-cost-dust defect flipped the sign; the linear/short-window formula then
amplified it). The canonical public hero (``landing/src/data/track_snapshot.json`` →
``site_numbers.json`` → the site's "4.9%") already uses the honest method: COMPOUND
growth over EVIDENCED-only bars, annualised by ``365/num_days``. This module is that
ONE method, extracted so every producer calls it instead of re-deriving it (C1: one
writer per value; here, one FORMULA per value).

Deliberately pure stdlib arithmetic with NO file I/O — safe to import from the
stdlib-only daily-cycle runtime (invariant #4) as well as from the FastAPI routers,
unlike importing ``scripts/generate_track_snapshot.py`` itself (that script is only
safely run as a build-time tool — ADR-148's sys.path class — and ``spa_core`` must
never depend on ``scripts/``, the wrong import direction).

LLM forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from typing import Any, Optional


def compound_annualized_pct(
    first_equity: Optional[float],
    last_equity: Optional[float],
    num_days: Optional[int],
) -> Optional[float]:
    """``((last/first) ** (365/num_days) - 1) * 100``, or ``None`` if the inputs are
    unusable. The SAME formula ``scripts/generate_track_snapshot.py`` uses for the
    public ``paper_apy_pct`` hero and for the Balanced/Aggressive sleeve tracks.
    Two bars minimum — one bar carries no rate of change, only a value.
    """
    if (
        not isinstance(first_equity, (int, float))
        or not isinstance(last_equity, (int, float))
        or not isinstance(num_days, (int, float))
        or isinstance(num_days, bool)
        or num_days < 2
        or first_equity <= 0
        or last_equity <= 0
    ):
        return None
    return ((float(last_equity) / float(first_equity)) ** (365.0 / float(num_days)) - 1.0) * 100.0


def evidenced_bars(equity_doc: Any) -> list:
    """The bar list of ``equity_curve_daily.json``, filtered to ``evidenced is True`` —
    the SAME extraction ``scripts/generate_track_snapshot.py::build_snapshot`` uses.
    Returns ``[]`` for a missing/malformed document (fail-closed, never a guess)."""
    if not isinstance(equity_doc, dict):
        return []
    bars = equity_doc.get("bars") or equity_doc.get("curve") or equity_doc.get("daily") or []
    if not isinstance(bars, list):
        return []
    return [b for b in bars if isinstance(b, dict) and b.get("evidenced") is True]


def max_drawdown_pct(bars: list) -> Optional[float]:
    """Worst drawdown (%) over *bars* = ``min(per-bar drawdown_pct)``, falling back to
    equity peak-to-trough when no bar carries the field. The SAME method as
    ``scripts/generate_track_snapshot.py::_max_drawdown_pct``."""
    if not isinstance(bars, list):
        return None
    dds = [
        float(b.get("drawdown_pct"))
        for b in bars
        if isinstance(b, dict) and b.get("drawdown_pct") is not None
    ]
    if dds:
        return round(min(dds), 4)
    eqs = [
        float(b.get("equity"))
        for b in bars
        if isinstance(b, dict) and b.get("equity") is not None
    ]
    if len(eqs) < 2:
        return None
    peak = eqs[0]
    worst = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            worst = min(worst, (e - peak) / peak * 100.0)
    return round(worst, 4)


def floor_pct(value: Optional[float], digits: int = 1) -> Optional[float]:
    """Published-rate floor (ADR-563, owner decision 2026-10-04): round DOWN, never
    up past what was measured. Mirrors ``landing/src/lib/site_numbers.js::floorTo``'s
    ``1e-9`` epsilon guard — a binary float like ``2.9`` is stored as
    ``2.8999999999999996``, and a plain ``math.floor`` would shave a digit off a
    number that is already exactly round. Second Python copy of the SAME epsilon
    trick, pinned to the JS one by ``spa_core/tests/test_compound_apy.py``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    scale = 10 ** digits
    return math.floor(value * scale + 1e-9) / scale
