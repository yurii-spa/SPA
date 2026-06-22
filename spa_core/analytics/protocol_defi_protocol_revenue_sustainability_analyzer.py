"""
MP-1027: ProtocolDeFiProtocolRevenueSustainabilityAnalyzer
Analyzes P&L quality and revenue sustainability of DeFi protocols.
Read-only/advisory — no modifications to allocator/risk/execution.
Atomic writes to data/protocol_revenue_sustainability_log.json (ring-buffer 100).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "protocol_revenue_sustainability_log.json"
)
LOG_CAP = 100

REVENUE_NEAR_ZERO_THRESHOLD_USD = 1_000.0   # $1K/week
EMISSION_SUBSIDY_THRESHOLD = 1.0            # emissions > revenue
LOW_DIVERSIFICATION_THRESHOLD = 70.0       # one source > 70%
MARKET_DEPENDENT_THRESHOLD = 60.0          # market_dep > 60%
REVENUE_GROWING_THRESHOLD_PCT = 5.0        # trend > 5%
RUNWAY_CRITICAL_MONTHS = 6
BURN_UNSUSTAINABLE = 2.0
RUNWAY_UNSUSTAINABLE = 12
BURN_PROFITABLE = 1.0
BURN_HIGHLY_SUSTAINABLE = 0.5


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.mean(values)


def _safe_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _revenue_volatility_pct(revenues: list[float]) -> float:
    """Coefficient of variation: std / mean * 100. 0 if mean ≤ 0."""
    mean = _safe_mean(revenues)
    if mean <= 0:
        return 0.0
    return round(_safe_stdev(revenues) / mean * 100, 4)


def _diversification_score(revenue_sources: dict[str, float]) -> float:
    """
    0-100 score: 1/HHI × 100, where HHI = sum of squared fractions.
    Higher = more diversified.
    """
    if not revenue_sources:
        return 0.0
    values = list(revenue_sources.values())
    total = sum(values)
    if total <= 0:
        return 0.0
    fracs = [v / total for v in values]
    hhi = sum(f * f for f in fracs)
    if hhi <= 0:
        return 100.0
    # 1/HHI ranges from 1 (monopoly) to n (uniform)
    score = (1.0 / hhi - 1.0) / max(1.0, len(fracs) - 1.0) * 100.0
    return round(_clamp(score), 4)


def _market_cycle_resilience(market_dependent_pct: float) -> float:
    """100 - market_dependent_pct, clamped."""
    return round(_clamp(100.0 - float(market_dependent_pct)), 4)


def _burn_multiple_score(burn_multiple: float) -> float:
    """
    Convert burn_multiple to 0-100 where lower burn = higher score.
    burn = 0   → 100; burn = 1.0 → 50; burn = 3.0 → 25; burn → ∞ → 0.
    Formula: 100 / (1 + burn_multiple)
    """
    if burn_multiple <= 0:
        return 100.0
    score = 100.0 / (1.0 + burn_multiple)
    return round(_clamp(score), 4)


def _trend_score(revenue_trend_pct: float) -> float:
    """Map revenue_trend_pct → 0-100 (50 at 0%, ±50 at ±50%)."""
    clamped = max(-50.0, min(50.0, revenue_trend_pct))
    return round(_clamp(50.0 + clamped), 4)


def _sustainability_score(burn_mult: float, diversification: float,
                          resilience: float, revenue_trend_pct: float) -> float:
    """
    0-100 composite:
      burn_mult_score   × 0.30
      diversification   × 0.25
      resilience        × 0.25
      trend_score       × 0.20
    """
    bm_score = _burn_multiple_score(burn_mult)
    ts = _trend_score(revenue_trend_pct)
    raw = (bm_score * 0.30 + diversification * 0.25 +
           resilience * 0.25 + ts * 0.20)
    return round(_clamp(raw), 4)


def _sustainability_label(protocol: dict, burn_mult: float,
                          avg_revenue: float, diversification: float,
                          resilience: float, sus_score: float) -> str:
    """Determine sustainability label for a protocol."""
    emissions_weekly = float(protocol.get("token_emissions_weekly_usd", 0.0))
    runway = float(protocol.get("treasury_runway_months", 999.0))

    # ZOMBIE: revenue near zero, pure emissions
    if avg_revenue < REVENUE_NEAR_ZERO_THRESHOLD_USD and emissions_weekly > 0:
        return "ZOMBIE"
    # UNSUSTAINABLE: burn > 2 AND runway < 12 months
    if burn_mult > BURN_UNSUSTAINABLE and runway < RUNWAY_UNSUSTAINABLE:
        return "UNSUSTAINABLE"
    # HIGHLY_SUSTAINABLE: burn < 0.5, diversified, resilient
    if (burn_mult < BURN_HIGHLY_SUSTAINABLE and
            diversification > 60.0 and resilience > 60.0):
        return "HIGHLY_SUSTAINABLE"
    # SUSTAINABLE: burn < 1 (profitable)
    if burn_mult < BURN_PROFITABLE:
        return "SUSTAINABLE"
    # BREAK_EVEN: approximately break-even (checked before SUBSIDIZED)
    if abs(burn_mult - 1.0) < 0.15:
        return "BREAK_EVEN"
    # SUBSIDIZED: burn > 1, treasury covers costs
    if burn_mult >= BURN_PROFITABLE and runway >= RUNWAY_CRITICAL_MONTHS:
        return "SUBSIDIZED"
    return "UNSUSTAINABLE"


def _compute_flags(protocol: dict, burn_mult: float, avg_revenue: float,
                   revenue_sources: dict[str, float]) -> list[str]:
    flags: list[str] = []

    if burn_mult < BURN_PROFITABLE and avg_revenue > 0:
        flags.append("PROFITABLE")

    emissions_weekly = float(protocol.get("token_emissions_weekly_usd", 0.0))
    if emissions_weekly > avg_revenue and avg_revenue > 0:
        flags.append("EMISSION_SUBSIDIZED")
    elif avg_revenue <= 0 and emissions_weekly > 0:
        flags.append("EMISSION_SUBSIDIZED")

    # Low revenue diversification: any single source > 70%
    if revenue_sources:
        total_src = sum(revenue_sources.values())
        if total_src > 0:
            max_share_pct = max(v / total_src * 100 for v in revenue_sources.values())
            if max_share_pct > LOW_DIVERSIFICATION_THRESHOLD:
                flags.append("LOW_REVENUE_DIVERSIFICATION")

    market_dep = float(protocol.get("market_dependent_revenue_pct", 0.0))
    if market_dep > MARKET_DEPENDENT_THRESHOLD:
        flags.append("MARKET_DEPENDENT")

    trend = float(protocol.get("revenue_trend_pct", 0.0))
    if trend > REVENUE_GROWING_THRESHOLD_PCT:
        flags.append("REVENUE_GROWING")

    runway = float(protocol.get("treasury_runway_months", 999.0))
    if runway < RUNWAY_CRITICAL_MONTHS:
        flags.append("RUNWAY_CRITICAL")

    return flags


def _analyze_single(protocol: dict) -> dict:
    """Analyze a single protocol; return enriched dict."""
    weekly_rev = [float(x) for x in protocol.get("weekly_revenue_usd", [])]
    weekly_cost = [float(x) for x in protocol.get("weekly_costs_usd", [])]
    revenue_sources = {k: float(v) for k, v in
                       protocol.get("revenue_sources", {}).items()}
    market_dep = float(protocol.get("market_dependent_revenue_pct", 0.0))
    trend_pct = float(protocol.get("revenue_trend_pct", 0.0))

    avg_rev = round(_safe_mean(weekly_rev), 4)
    avg_cost = round(_safe_mean(weekly_cost), 4)
    weekly_pnl = round(avg_rev - avg_cost, 4)
    burn_mult = round(avg_cost / avg_rev, 4) if avg_rev > 0 else float("inf")
    if math.isinf(burn_mult):
        burn_mult = 9999.0  # sentinel for zero-revenue
    rev_vol_pct = _revenue_volatility_pct(weekly_rev)
    div_score = _diversification_score(revenue_sources)
    resilience = _market_cycle_resilience(market_dep)
    sus_score = _sustainability_score(burn_mult, div_score, resilience, trend_pct)
    label = _sustainability_label(protocol, burn_mult, avg_rev,
                                  div_score, resilience, sus_score)
    flags = _compute_flags(protocol, burn_mult, avg_rev, revenue_sources)

    return {
        "name": protocol.get("name", ""),
        "category": protocol.get("category", ""),
        "avg_weekly_revenue_usd": avg_rev,
        "avg_weekly_costs_usd": avg_cost,
        "weekly_profit_loss_usd": weekly_pnl,
        "burn_multiple": burn_mult,
        "revenue_volatility_pct": rev_vol_pct,
        "diversification_score": div_score,
        "market_cycle_resilience": resilience,
        "sustainability_score": sus_score,
        "sustainability_label": label,
        "flags": flags,
    }


def _compute_aggregates(analyzed: list[dict]) -> dict:
    if not analyzed:
        return {
            "most_sustainable": None,
            "least_sustainable": None,
            "avg_sustainability_score": 0.0,
            "profitable_count": 0,
            "zombie_count": 0,
        }
    scores = [a["sustainability_score"] for a in analyzed]
    avg = round(statistics.mean(scores), 4)
    hi_idx = scores.index(max(scores))
    lo_idx = scores.index(min(scores))
    profitable = sum(1 for a in analyzed if "PROFITABLE" in a["flags"])
    zombies = sum(1 for a in analyzed if a["sustainability_label"] == "ZOMBIE")
    return {
        "most_sustainable": {
            "name": analyzed[hi_idx]["name"],
            "sustainability_score": analyzed[hi_idx]["sustainability_score"],
            "sustainability_label": analyzed[hi_idx]["sustainability_label"],
        },
        "least_sustainable": {
            "name": analyzed[lo_idx]["name"],
            "sustainability_score": analyzed[lo_idx]["sustainability_score"],
            "sustainability_label": analyzed[lo_idx]["sustainability_label"],
        },
        "avg_sustainability_score": avg,
        "profitable_count": profitable,
        "zombie_count": zombies,
    }


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    atomic_save(data, str(path))
def _append_log(result: dict, log_path: str) -> None:
    """Append a log entry (ring-buffer, cap LOG_CAP)."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol_count": result.get("protocol_count", 0),
        "avg_sustainability_score": result.get("aggregates", {}).get(
            "avg_sustainability_score", 0.0),
        "profitable_count": result.get("aggregates", {}).get("profitable_count", 0),
        "zombie_count": result.get("aggregates", {}).get("zombie_count", 0),
    }
    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── main class ────────────────────────────────────────────────────────────────

class ProtocolDeFiProtocolRevenueSustainabilityAnalyzer:
    """
    Analyzes revenue sustainability (P&L quality) of DeFi protocols.

    Input:
        protocols: list of protocol dicts (see module docstring)
        config: optional overrides {"log_path": str, "write_log": bool}

    Output:
        dict with keys:
            analyzed_protocols, aggregates, protocol_count, ts
    """

    def analyze(self, protocols: list[dict], config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")

        analyzed = [_analyze_single(p) for p in protocols]
        aggregates = _compute_aggregates(analyzed)

        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(analyzed),
            "analyzed_protocols": analyzed,
            "aggregates": aggregates,
        }

        if write_log and analyzed:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
