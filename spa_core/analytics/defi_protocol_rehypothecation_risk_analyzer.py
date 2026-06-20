"""
MP-1015: DeFiProtocolRehypothecationRiskAnalyzer
=================================================
Advisory-only analytics module.

Quantifies *rehypothecation / recursive-leverage risk* of a looped DeFi yield
position — where deposited collateral is repeatedly re-borrowed against and
re-deposited (collateral looping / folding). This builds hidden leverage and
contagion the headline APY hides. Gap confirmed: leverage modules to date score
single-protocol leverage or liquidation price, not the *re-use depth* of the same
underlying collateral and the carry/health trade-off it creates.

For each position it computes the geometric leverage built by finite loops:
    total_exposure = principal * (1 - r^(loops+1)) / (1 - r)   where r = loop_ltv
    leverage_multiple = total_exposure / principal
and from that:
  net_leveraged_apy_pct   levered yield minus levered borrow cost
  position_ltv_pct        blended LTV of the whole looped stack
  health_buffer_pct       liquidation_ltv − position_ltv
  liquidation_drop_pct    collateral price drop that triggers liquidation
  contagion_score         0-100 (leverage × thin buffer)
  rehypothecation_risk_score 0-100 (HIGHER = riskier)
  grade A-F
  classification          MINIMAL_REHYPOTHECATION / CONSERVATIVE / MODERATE /
                          AGGRESSIVE / EXTREME_REHYPOTHECATION

Flags: NO_LEVERAGE, THIN_HEALTH_BUFFER, EXCESSIVE_LOOPING, NEGATIVE_CARRY,
HIGH_LIQUIDATION_RISK, DEEP_REHYPOTHECATION, CONTAGION_RISK, SUSTAINABLE_CARRY,
INSUFFICIENT_DATA

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/rehypothecation_risk_log.json
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "rehypothecation_risk_log.json",
)
LOG_MAX_ENTRIES = 100

# Classification thresholds on rehypothecation_risk_score (higher = riskier)
EXTREME_REHYPOTHECATION = 80.0
AGGRESSIVE = 60.0
MODERATE = 40.0
CONSERVATIVE = 20.0

# Flag thresholds
THIN_BUFFER_PCT = 8.0          # health buffer (liq_ltv - position_ltv) considered thin
DEEP_LOOPS = 5                 # loops at/above this = deep rehypothecation
EXCESSIVE_LOOPS = 8
HIGH_LEVERAGE_MULTIPLE = 4.0
LIQUIDATION_DROP_DANGER = 12.0  # < this % drop-to-liquidation = high risk


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_position(p: dict, idx: int) -> None:
    """Validate required fields in a position dict."""
    required = {
        "name",
        "principal_usd",
        "loop_ltv_pct",
        "loops",
        "base_apy_pct",
        "borrow_apy_pct",
        "liquidation_ltv_pct",
    }
    missing = required - set(p.keys())
    if missing:
        raise ValueError(
            f"Position {idx} ('{p.get('name', '?')}') missing fields: {missing}"
        )
    if p["principal_usd"] <= 0:
        raise ValueError(f"Position {idx}: principal_usd must be > 0")
    loop_ltv = p["loop_ltv_pct"]
    if loop_ltv < 0 or loop_ltv >= 100:
        raise ValueError(f"Position {idx}: loop_ltv_pct must be in [0, 100)")
    if not isinstance(p["loops"], int) or p["loops"] < 0:
        raise ValueError(f"Position {idx}: loops must be a non-negative int")
    liq = p["liquidation_ltv_pct"]
    if liq <= 0 or liq > 100:
        raise ValueError(f"Position {idx}: liquidation_ltv_pct must be in (0, 100]")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _total_exposure(principal: float, loop_ltv_pct: float, loops: int) -> float:
    """
    Geometric sum of a finite collateral loop.

    Each loop re-deposits r = loop_ltv of the previous deposit:
        exposure = principal * (1 + r + r^2 + ... + r^loops)
                 = principal * (1 - r^(loops+1)) / (1 - r)
    """
    r = loop_ltv_pct / 100.0
    if loops <= 0 or r <= 0.0:
        return principal
    # 1 - r is strictly positive because loop_ltv_pct < 100 (validated).
    return principal * (1.0 - r ** (loops + 1)) / (1.0 - r)


def _leverage_multiple(principal: float, total_exposure: float) -> float:
    if principal <= 0:
        return 1.0
    return round(total_exposure / principal, 4)


def _total_borrowed(total_exposure: float, principal: float) -> float:
    """Debt = everything beyond the original principal."""
    return max(0.0, total_exposure - principal)


def _position_ltv_pct(total_borrowed: float, total_exposure: float) -> float:
    """Blended LTV of the whole looped stack = debt / collateral."""
    if total_exposure <= 0:
        return 0.0
    return round(total_borrowed / total_exposure * 100.0, 4)


def _net_leveraged_apy(base_apy_pct: float, borrow_apy_pct: float,
                       leverage_multiple: float) -> float:
    """
    Levered carry: earn base yield on the full exposure, pay borrow cost on debt.
        net = base * L - borrow * (L - 1)
    """
    levered_yield = base_apy_pct * leverage_multiple
    levered_cost = borrow_apy_pct * max(0.0, leverage_multiple - 1.0)
    return round(levered_yield - levered_cost, 4)


def _health_buffer_pct(liquidation_ltv_pct: float, position_ltv_pct: float) -> float:
    """Headroom between current blended LTV and the liquidation LTV."""
    return round(liquidation_ltv_pct - position_ltv_pct, 4)


def _liquidation_drop_pct(position_ltv_pct: float, liquidation_ltv_pct: float) -> float:
    """
    Collateral price drop (%) that pushes position_ltv up to liquidation_ltv.

    LTV scales as 1/price, so a drop d satisfies:
        position_ltv / (1 - d) = liquidation_ltv
        d = 1 - position_ltv / liquidation_ltv
    """
    if liquidation_ltv_pct <= 0 or position_ltv_pct <= 0:
        return 100.0
    drop = 1.0 - (position_ltv_pct / liquidation_ltv_pct)
    return round(max(0.0, min(drop, 1.0)) * 100.0, 4)


def _contagion_score(leverage_multiple: float, health_buffer_pct: float,
                     loops: int) -> float:
    """
    0-100: how strongly a shock to this collateral would cascade. Driven by
    leverage size, thin health buffer, and loop depth.
    """
    # Leverage component (0-50): L=1 → 0, L>=6 → 50.
    lev_component = min(max(leverage_multiple - 1.0, 0.0) / 5.0, 1.0) * 50.0
    # Thin-buffer component (0-35): buffer 0 → 35, buffer >=25 → 0.
    buffer_component = max(0.0, 1.0 - max(health_buffer_pct, 0.0) / 25.0) * 35.0
    # Depth component (0-15): loops>=10 → 15.
    depth_component = min(loops / 10.0, 1.0) * 15.0
    return round(min(lev_component + buffer_component + depth_component, 100.0), 2)


def _rehypothecation_risk_score(leverage_multiple: float, health_buffer_pct: float,
                                liquidation_drop_pct: float,
                                net_apy_pct: float, loops: int) -> float:
    """
    Composite rehypothecation risk 0-100 (HIGHER = riskier).
    """
    # Leverage (0-35).
    lev = min(max(leverage_multiple - 1.0, 0.0) / 5.0, 1.0) * 35.0
    # Liquidation proximity (0-35): smaller drop-to-liq = riskier; 0% → 35, >=40% → 0.
    liq = max(0.0, 1.0 - min(liquidation_drop_pct, 40.0) / 40.0) * 35.0
    # Depth (0-15).
    depth = min(loops / 10.0, 1.0) * 15.0
    # Carry penalty (0-15): negative net carry means leverage is destroying value.
    carry = 15.0 if net_apy_pct < 0 else max(0.0, 1.0 - min(net_apy_pct, 10.0) / 10.0) * 7.5
    score = lev + liq + depth + carry
    return round(max(0.0, min(score, 100.0)), 2)


def _classify(risk: float) -> str:
    if risk >= EXTREME_REHYPOTHECATION:
        return "EXTREME_REHYPOTHECATION"
    if risk >= AGGRESSIVE:
        return "AGGRESSIVE"
    if risk >= MODERATE:
        return "MODERATE"
    if risk >= CONSERVATIVE:
        return "CONSERVATIVE"
    return "MINIMAL_REHYPOTHECATION"


def _grade(risk: float) -> str:
    if risk < 20.0:
        return "A"
    if risk < 40.0:
        return "B"
    if risk < 60.0:
        return "C"
    if risk < 80.0:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def _compute_flags(loops: int, leverage_multiple: float, health_buffer_pct: float,
                   liquidation_drop_pct: float, net_apy_pct: float,
                   contagion: float) -> list:
    flags = []
    if loops <= 0 or leverage_multiple <= 1.0001:
        flags.append("NO_LEVERAGE")
    if 0.0 <= health_buffer_pct < THIN_BUFFER_PCT:
        flags.append("THIN_HEALTH_BUFFER")
    if health_buffer_pct < 0.0:
        flags.append("THIN_HEALTH_BUFFER")
    if loops >= EXCESSIVE_LOOPS:
        flags.append("EXCESSIVE_LOOPING")
    if net_apy_pct < 0.0:
        flags.append("NEGATIVE_CARRY")
    if liquidation_drop_pct < LIQUIDATION_DROP_DANGER:
        flags.append("HIGH_LIQUIDATION_RISK")
    if loops >= DEEP_LOOPS or leverage_multiple >= HIGH_LEVERAGE_MULTIPLE:
        flags.append("DEEP_REHYPOTHECATION")
    if contagion >= 60.0:
        flags.append("CONTAGION_RISK")
    if net_apy_pct > 0.0 and health_buffer_pct >= THIN_BUFFER_PCT:
        flags.append("SUSTAINABLE_CARRY")
    # Deduplicate while preserving order.
    seen = set()
    out = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# Per-position analysis
# ---------------------------------------------------------------------------

def _analyze_one(p: dict) -> dict:
    principal = float(p["principal_usd"])
    loop_ltv = float(p["loop_ltv_pct"])
    loops = int(p["loops"])
    base_apy = float(p["base_apy_pct"])
    borrow_apy = float(p["borrow_apy_pct"])
    liq_ltv = float(p["liquidation_ltv_pct"])

    total_exposure = _total_exposure(principal, loop_ltv, loops)
    leverage = _leverage_multiple(principal, total_exposure)
    total_borrowed = _total_borrowed(total_exposure, principal)
    position_ltv = _position_ltv_pct(total_borrowed, total_exposure)
    net_apy = _net_leveraged_apy(base_apy, borrow_apy, leverage)
    health_buffer = _health_buffer_pct(liq_ltv, position_ltv)
    liq_drop = _liquidation_drop_pct(position_ltv, liq_ltv)
    contagion = _contagion_score(leverage, health_buffer, loops)
    risk = _rehypothecation_risk_score(
        leverage, health_buffer, liq_drop, net_apy, loops
    )
    classification = _classify(risk)
    grade = _grade(risk)
    flags = _compute_flags(
        loops, leverage, health_buffer, liq_drop, net_apy, contagion
    )

    return {
        "name": p["name"],
        "principal_usd": round(principal, 2),
        "loops": loops,
        "loop_ltv_pct": round(loop_ltv, 2),
        "total_exposure_usd": round(total_exposure, 2),
        "total_borrowed_usd": round(total_borrowed, 2),
        "leverage_multiple": leverage,
        "position_ltv_pct": position_ltv,
        "net_leveraged_apy_pct": net_apy,
        "health_buffer_pct": health_buffer,
        "liquidation_drop_pct": liq_drop,
        "contagion_score": contagion,
        "rehypothecation_risk_score": risk,
        "grade": grade,
        "classification": classification,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolRehypothecationRiskAnalyzer:
    """
    Analyzes rehypothecation / recursive-leverage risk across looped DeFi positions.
    Advisory / read-only. No execution side-effects.
    """

    def analyze(self, positions: list, config: Optional[dict] = None) -> dict:
        """
        Parameters
        ----------
        positions : list[dict]
            Each dict must contain:
                name                 str
                principal_usd        float  (> 0)
                loop_ltv_pct         float  ([0, 100) — LTV re-borrowed each loop)
                loops                int    (>= 0 — number of recursive loops)
                base_apy_pct         float  (yield earned on collateral)
                borrow_apy_pct       float  (cost of borrow)
                liquidation_ltv_pct  float  ((0, 100] — liquidation threshold)
        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys:
            positions                  list[dict]
            safest_position            str | None
            riskiest_position          str | None
            avg_rehypothecation_risk   float
            extreme_count              int
            avg_leverage_multiple      float
            analyzed_at                str  ISO timestamp
        """
        if config is None:
            config = {}
        if not isinstance(positions, list) or len(positions) == 0:
            raise ValueError("positions must be a non-empty list")

        for idx, p in enumerate(positions):
            _validate_position(p, idx)

        results = [_analyze_one(p) for p in positions]

        avg_risk = round(
            sum(r["rehypothecation_risk_score"] for r in results) / len(results), 2
        )
        avg_leverage = round(
            sum(r["leverage_multiple"] for r in results) / len(results), 4
        )
        extreme_count = sum(
            1 for r in results if r["classification"] == "EXTREME_REHYPOTHECATION"
        )

        sorted_safe = sorted(results, key=lambda r: r["rehypothecation_risk_score"])
        safest = sorted_safe[0]["name"] if sorted_safe else None
        riskiest = sorted_safe[-1]["name"] if sorted_safe else None

        output = {
            "positions": results,
            "safest_position": safest,
            "riskiest_position": riskiest,
            "avg_rehypothecation_risk": avg_risk,
            "extreme_count": extreme_count,
            "avg_leverage_multiple": avg_leverage,
            "analyzed_at": _iso_now(),
        }

        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result snapshot to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "position_count": len(result.get("positions", [])),
        "avg_rehypothecation_risk": result.get("avg_rehypothecation_risk"),
        "avg_leverage_multiple": result.get("avg_leverage_multiple"),
        "extreme_count": result.get("extreme_count"),
        "safest_position": result.get("safest_position"),
        "riskiest_position": result.get("riskiest_position"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(positions: list, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to DeFiProtocolRehypothecationRiskAnalyzer."""
    return DeFiProtocolRehypothecationRiskAnalyzer().analyze(positions, config)
