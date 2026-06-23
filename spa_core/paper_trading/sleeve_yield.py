"""
spa_core/paper_trading/sleeve_yield.py — honest yield source for Engine B/C sleeves.

The HY (carry) and LP sleeves paper-trade dedicated virtual capital. To make that a
MEANINGFUL paper test (not a flat book) they accrue daily yield at the REAL on-chain
APY of their target protocols, read from data/apy_ranking.json (written by cycle_runner
every cycle). No yield is invented — if no live APY is available we fall back to a
conservative floor and the absence is observable in the state.

v1 simplifications (documented, to be refined):
  - HY "funding rate" proxy = representative APY of the high-yield protocol band
    (real lending/Pendle APY ≥ HY_BAND_MIN%). True perp-funding feed is not yet wired.
  - LP yield = representative APY of LP-pool protocols; impermanent loss is NOT yet
    modelled (needs a price feed) — tracked separately via il_drawdown, 0 until then.

LLM_FORBIDDEN. stdlib only. fail-closed: no data → conservative floor.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APY_RANKING = _PROJECT_ROOT / "data" / "apy_ranking.json"

# Bands / caps (percent). Cap mirrors RiskPolicy APY ceiling (30%).
HY_BAND_MIN = 6.0      # high-yield band floor
APY_CAP = 30.0         # never accrue above policy APY ceiling
HY_FLOOR = 6.0         # conservative HY fallback if no live data
LP_FLOOR = 8.0         # conservative LP fallback if no live data
_LP_NAME_HINTS = ("lp", "aerodrome", "velodrome", "curve", "uniswap", "pool")


def _load_ranking() -> List[dict]:
    try:
        d = json.loads(_APY_RANKING.read_text(encoding="utf-8"))
        rows = d.get("by_apy") or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def _median_capped(vals: List[float], floor: float) -> float:
    vals = [v for v in vals if isinstance(v, (int, float)) and 0 < v <= APY_CAP]
    if not vals:
        return floor
    return min(APY_CAP, float(statistics.median(vals)))


def hy_target_apy_pct() -> float:
    """Representative APY (%) of the high-yield band — used as carry proxy + accrual."""
    rows = _load_ranking()
    band = [float(r.get("apy_pct", 0) or 0) for r in rows
            if float(r.get("apy_pct", 0) or 0) >= HY_BAND_MIN]
    return _median_capped(band, HY_FLOOR)


def lp_target_apy_pct() -> float:
    """Representative APY (%) of LP-pool protocols — used for LP fee accrual."""
    rows = _load_ranking()
    lp = [float(r.get("apy_pct", 0) or 0) for r in rows
          if any(h in str(r.get("protocol", "")).lower() for h in _LP_NAME_HINTS)]
    return _median_capped(lp, LP_FLOOR)


def daily_yield(equity: float, apy_pct: float) -> float:
    """Daily compounding yield for `equity` at annual `apy_pct` (%). Never negative."""
    if equity <= 0 or apy_pct <= 0:
        return 0.0
    return equity * (apy_pct / 100.0) / 365.0
