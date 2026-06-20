"""
MP-856 ProtocolRevenueQualityScorer
=====================================
Advisory-only, read-only analytics module.
Assesses whether protocol revenue is sustainable (real fees) vs. artificial
(token emissions/incentives). Scores revenue quality and sustainability.

Output file: data/revenue_quality_log.json (ring-buffer, cap 100)
Pure Python stdlib only. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Scoring sub-components
# ---------------------------------------------------------------------------

_INF_RATIO_SENTINEL = 999.0  # stored instead of infinity when emission_cost = 0


def _fee_to_emission_ratio(fee_revenue: float, emission_cost: float) -> float:
    """
    fee_revenue / emission_cost if emission_cost > 0 else _INF_RATIO_SENTINEL.
    Returns float (sentinel 999.0 for zero-emission case).
    """
    if emission_cost <= 0:
        return _INF_RATIO_SENTINEL
    return fee_revenue / emission_cost


def _real_yield_score(
    fee_revenue: float, emission_cost: float, has_buyback: bool
) -> int:
    """
    0-40 points.  +5 if has_buyback, capped at 40.
    """
    ratio = _fee_to_emission_ratio(fee_revenue, emission_cost)

    if emission_cost <= 0:
        base = 40
    elif ratio >= 5.0:
        base = 40
    elif ratio >= 2.0:
        base = 30
    elif ratio >= 1.0:
        base = 20
    elif ratio >= 0.5:
        base = 10
    elif ratio >= 0.2:
        base = 5
    else:
        base = 0

    if has_buyback:
        base += 5

    return min(40, base)


def _diversification_score(unique_revenue_sources: int) -> int:
    """0-20 points based on number of distinct revenue streams."""
    if unique_revenue_sources >= 5:
        return 20
    if unique_revenue_sources >= 4:
        return 16
    if unique_revenue_sources >= 3:
        return 12
    if unique_revenue_sources >= 2:
        return 8
    if unique_revenue_sources == 1:
        return 4
    return 0


def _growth_score(fee_revenue_growth_30d_pct: float) -> int:
    """0-20 points based on 30-day fee revenue growth %."""
    if fee_revenue_growth_30d_pct >= 30:
        return 20
    if fee_revenue_growth_30d_pct >= 10:
        return 15
    if fee_revenue_growth_30d_pct >= 0:
        return 10
    if fee_revenue_growth_30d_pct >= -10:
        return 5
    return 0


def _efficiency_score(fee_revenue_30d: float, tvl: float) -> int:
    """0-20 points based on revenue per TVL %."""
    if tvl <= 0:
        return 0
    pct = (fee_revenue_30d / tvl) * 100.0
    if pct >= 1.0:
        return 20
    if pct >= 0.5:
        return 15
    if pct >= 0.2:
        return 10
    if pct >= 0.1:
        return 5
    return 0


def _revenue_per_tvl_pct(fee_revenue_30d: float, tvl: float) -> float:
    if tvl <= 0:
        return 0.0
    return (fee_revenue_30d / tvl) * 100.0


def _revenue_per_user_usd(fee_revenue_30d: float, mau: int) -> float:
    if mau <= 0:
        return 0.0
    return fee_revenue_30d / mau


def _revenue_quality(score: int) -> str:
    if score >= 80:
        return "EXCELLENT"
    if score >= 60:
        return "STRONG"
    if score >= 40:
        return "ADEQUATE"
    if score >= 20:
        return "WEAK"
    return "UNSUSTAINABLE"


def _sustainability_label(
    score: int, unique_revenue_sources: int, fee_to_emission_ratio: float
) -> str:
    if score >= 80:
        return "Revenue-backed — protocol earns more than it spends on incentives"
    if score >= 60:
        ratio_display = fee_to_emission_ratio if fee_to_emission_ratio < _INF_RATIO_SENTINEL else _INF_RATIO_SENTINEL
        return (
            f"Strong fundamentals — {unique_revenue_sources} revenue streams "
            f"with {ratio_display:.1f}x fee/emission ratio"
        )
    if score >= 40:
        return "Adequate — mixed revenue quality, monitor emission costs"
    if score >= 20:
        return "Weak — reliant on token incentives to attract capital"
    return "Unsustainable — emissions-driven model at risk when token price declines"


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Score revenue quality and sustainability for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list of dict with keys:
        name, protocol_fee_revenue_30d_usd, token_emission_cost_30d_usd,
        tvl_usd, monthly_active_users, unique_revenue_sources,
        has_buyback_mechanism, fee_revenue_growth_30d_pct
    config : optional dict (currently unused, reserved for future use)

    Returns
    -------
    dict with keys: protocols, most_sustainable, least_sustainable,
                    average_revenue_score, timestamp
    """
    scored = []

    for proto in protocols:
        name = str(proto.get("name", "unknown"))
        fee_revenue = float(proto.get("protocol_fee_revenue_30d_usd", 0.0))
        emission_cost = float(proto.get("token_emission_cost_30d_usd", 0.0))
        tvl = float(proto.get("tvl_usd", 0.0))
        mau = int(proto.get("monthly_active_users", 0))
        unique_sources = int(proto.get("unique_revenue_sources", 0))
        has_buyback = bool(proto.get("has_buyback_mechanism", False))
        growth_pct = float(proto.get("fee_revenue_growth_30d_pct", 0.0))

        ratio = _fee_to_emission_ratio(fee_revenue, emission_cost)
        rys = _real_yield_score(fee_revenue, emission_cost, has_buyback)
        divs = _diversification_score(unique_sources)
        gs = _growth_score(growth_pct)
        effs = _efficiency_score(fee_revenue, tvl)

        total_score = min(100, rys + divs + gs + effs)
        quality = _revenue_quality(total_score)
        rev_per_tvl = _revenue_per_tvl_pct(fee_revenue, tvl)
        rev_per_user = _revenue_per_user_usd(fee_revenue, mau)
        label = _sustainability_label(total_score, unique_sources, ratio)

        scored.append({
            "name": name,
            "revenue_score": total_score,
            "revenue_quality": quality,
            "fee_to_emission_ratio": ratio,
            "revenue_per_tvl_pct": rev_per_tvl,
            "revenue_per_user_usd": rev_per_user,
            "real_yield_score": rys,
            "diversification_score": divs,
            "growth_score": gs,
            "efficiency_score": effs,
            "sustainability_label": label,
        })

    if scored:
        best = max(scored, key=lambda x: x["revenue_score"])["name"]
        worst = min(scored, key=lambda x: x["revenue_score"])["name"]
        avg = sum(p["revenue_score"] for p in scored) / len(scored)
    else:
        best = None
        worst = None
        avg = 0.0

    return {
        "protocols": scored,
        "most_sustainable": best,
        "least_sustainable": worst,
        "average_revenue_score": avg,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "revenue_quality_log.json"
)
_RING_CAP = 100


def _resolve_log_path(data_dir: Optional[str] = None) -> str:
    if data_dir:
        return os.path.join(data_dir, "revenue_quality_log.json")
    return os.path.normpath(_DEFAULT_LOG)


def _atomic_write(path: str, obj) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def append_log(result: dict, data_dir: Optional[str] = None) -> None:
    """Append analyze() result to ring-buffer log (max 100 entries)."""
    path = _resolve_log_path(data_dir)
    log = _load_log(path)
    log.append(result)
    if len(log) > _RING_CAP:
        log = log[-_RING_CAP:]
    _atomic_write(path, log)


def run(protocols: list, config: dict = None, data_dir: Optional[str] = None) -> dict:
    """
    Run analyze() and persist result to ring-buffer log.
    Advisory only — no trades, no state mutations.
    """
    result = analyze(protocols, config)
    append_log(result, data_dir)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ProtocolRevenueQualityScorer (MP-856)")
    parser.add_argument("--check", action="store_true", help="Run analysis, print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Run analysis + persist log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    demo_protocols = [
        {
            "name": "Uniswap V3",
            "protocol_fee_revenue_30d_usd": 5_000_000,
            "token_emission_cost_30d_usd": 100_000,
            "tvl_usd": 3_000_000_000,
            "monthly_active_users": 50000,
            "unique_revenue_sources": 3,
            "has_buyback_mechanism": False,
            "fee_revenue_growth_30d_pct": 12.0,
        },
        {
            "name": "Curve Finance",
            "protocol_fee_revenue_30d_usd": 500_000,
            "token_emission_cost_30d_usd": 2_000_000,
            "tvl_usd": 4_000_000_000,
            "monthly_active_users": 10000,
            "unique_revenue_sources": 2,
            "has_buyback_mechanism": False,
            "fee_revenue_growth_30d_pct": -5.0,
        },
    ]

    if args.run:
        result = run(demo_protocols, data_dir=args.data_dir)
        print(json.dumps(result, indent=2))
    else:
        result = analyze(demo_protocols)
        print(json.dumps(result, indent=2))


# =============================================================================
# MP-973  ProtocolRevenueQualityScorer
# =============================================================================
# Scores quality and sustainability of DeFi protocol revenue.
#
# Protocol fields:
#   name, total_revenue_30d_usd, trading_fee_revenue_pct,
#   liquidation_fee_revenue_pct, protocol_fee_revenue_pct,
#   incentive_revenue_pct, revenue_growth_mom_pct,
#   revenue_concentration_top3_users_pct, unique_revenue_sources_count,
#   has_recurring_revenue (bool), cyclical_dependency (bull_market/neutral/bear),
#   revenue_30d_vs_90d_avg_ratio
#
# Computed:
#   organic_revenue_pct     = 100 - incentive_revenue_pct
#   quality_score (0-100)   = organic×0.4 + diversity×0.3 + recurring×0.2 + growth×0.1
#   revenue_stability_score = avg(non-concentration, cyclical-resilience, 90d-consistency)
#   sustainability_multiple = quality/100 × revenue_30d × 12
#
# Labels: PREMIUM | HIGH | MEDIUM | LOW | INCENTIVE_DEPENDENT
# Flags:  INCENTIVE_DEPENDENT | WHALE_REVENUE | DECLINING |
#         HIGH_QUALITY_GROWTH | CYCLICAL_RISK
# =============================================================================

# MP-973 Label constants
MP973_LABEL_PREMIUM             = "PREMIUM"              # organic>80% AND quality>75
MP973_LABEL_HIGH                = "HIGH"                 # quality > 60
MP973_LABEL_MEDIUM              = "MEDIUM"               # quality > 40
MP973_LABEL_LOW                 = "LOW"                  # quality > 20
MP973_LABEL_INCENTIVE_DEPENDENT = "INCENTIVE_DEPENDENT"  # incentive > 50% or very low

# MP-973 Flag constants
MP973_FLAG_INCENTIVE_DEPENDENT = "INCENTIVE_DEPENDENT"
MP973_FLAG_WHALE_REVENUE       = "WHALE_REVENUE"         # top3 > 70%
MP973_FLAG_DECLINING           = "DECLINING"             # growth < -20%
MP973_FLAG_HIGH_QUALITY_GROWTH = "HIGH_QUALITY_GROWTH"   # quality>70 AND growth>20%
MP973_FLAG_CYCLICAL_RISK       = "CYCLICAL_RISK"         # bull_market dependent


# ── MP-973 sub-scorers ────────────────────────────────────────────────────────

def _mp973_organic_revenue_pct(incentive_pct: float) -> float:
    """100 − incentive_revenue_pct, clamped 0-100."""
    return max(0.0, min(100.0, 100.0 - incentive_pct))


def _mp973_diversity_score(unique_sources: int) -> float:
    """0-100 score: each revenue source = 20 pts, cap 100."""
    return min(100.0, float(unique_sources) * 20.0)


def _mp973_recurring_score(has_recurring: bool) -> float:
    """100 if has_recurring_revenue else 0."""
    return 100.0 if has_recurring else 0.0


def _mp973_growth_score(growth_mom_pct: float) -> float:
    """0-100 score from month-over-month revenue growth %."""
    if growth_mom_pct >= 30.0:
        return 100.0
    if growth_mom_pct >= 10.0:
        return 75.0
    if growth_mom_pct >= 0.0:
        return 50.0
    if growth_mom_pct >= -20.0:
        return 25.0
    return 0.0


def _mp973_quality_score(
    organic_pct: float,
    unique_sources: int,
    has_recurring: bool,
    growth_mom_pct: float,
) -> float:
    """
    quality_score (0-100):
        organic_pct × 0.4  (organic already 0-100)
      + diversity   × 0.3
      + recurring   × 0.2
      + growth      × 0.1
    """
    org = organic_pct
    div = _mp973_diversity_score(unique_sources)
    rec = _mp973_recurring_score(has_recurring)
    gro = _mp973_growth_score(growth_mom_pct)
    raw = org * 0.4 + div * 0.3 + rec * 0.2 + gro * 0.1
    return min(100.0, max(0.0, raw))


def _mp973_cyclicality_resilience(cyclical_dependency: str) -> float:
    """
    bear   = 100  (revenue holds in bear market → stable)
    neutral = 67
    bull_market = 33 (collapses in bear → fragile)
    """
    mapping = {"bear": 100.0, "neutral": 67.0, "bull_market": 33.0}
    return mapping.get(cyclical_dependency, 67.0)


def _mp973_revenue_stability_score(
    concentration_top3_pct: float,
    cyclical_dependency: str,
    rev_30d_vs_90d_ratio: float,
) -> float:
    """
    Stability score (0-100): average of three components:
      1. Non-concentration:   100 - concentration_top3_pct
      2. Cyclical resilience: 100 (bear) / 67 (neutral) / 33 (bull)
      3. 90d consistency:     based on |ratio - 1.0|
    """
    conc_score = max(0.0, 100.0 - concentration_top3_pct)
    cycl_score = _mp973_cyclicality_resilience(cyclical_dependency)
    delta = abs(rev_30d_vs_90d_ratio - 1.0)
    if delta < 0.1:
        ratio_score = 100.0
    elif delta < 0.2:
        ratio_score = 80.0
    elif delta < 0.3:
        ratio_score = 60.0
    elif delta < 0.5:
        ratio_score = 40.0
    else:
        ratio_score = 0.0
    return (conc_score + cycl_score + ratio_score) / 3.0


def _mp973_sustainability_multiple(quality_score: float, revenue_30d_usd: float) -> float:
    """quality / 100 × (revenue_30d_usd × 12)."""
    annualized = revenue_30d_usd * 12.0
    return (quality_score / 100.0) * annualized


def _mp973_quality_label(
    organic_pct: float,
    quality: float,
    incentive_pct: float,
) -> str:
    """Assign a quality label. INCENTIVE_DEPENDENT wins when incentive > 50%."""
    if incentive_pct > 50.0:
        return MP973_LABEL_INCENTIVE_DEPENDENT
    if organic_pct > 80.0 and quality > 75.0:
        return MP973_LABEL_PREMIUM
    if quality > 60.0:
        return MP973_LABEL_HIGH
    if quality > 40.0:
        return MP973_LABEL_MEDIUM
    if quality > 20.0:
        return MP973_LABEL_LOW
    return MP973_LABEL_INCENTIVE_DEPENDENT


def _mp973_flags(
    incentive_pct: float,
    concentration_top3_pct: float,
    growth_mom_pct: float,
    quality: float,
    cyclical_dependency: str,
) -> list:
    """Return list of flag strings for a protocol."""
    flags = []
    if incentive_pct > 50.0:
        flags.append(MP973_FLAG_INCENTIVE_DEPENDENT)
    if concentration_top3_pct > 70.0:
        flags.append(MP973_FLAG_WHALE_REVENUE)
    if growth_mom_pct < -20.0:
        flags.append(MP973_FLAG_DECLINING)
    if quality > 70.0 and growth_mom_pct > 20.0:
        flags.append(MP973_FLAG_HIGH_QUALITY_GROWTH)
    if cyclical_dependency == "bull_market":
        flags.append(MP973_FLAG_CYCLICAL_RISK)
    return flags


class ProtocolRevenueQualityScorer:
    """
    MP-973: Scores the quality and sustainability of DeFi protocol revenue.

    Advisory-only — never mutates allocator / risk / execution state.
    Output: data/revenue_quality_log.json (ring-buffer cap 100, atomic write).
    """

    def score(self, protocols: list, config: dict = None) -> dict:
        """
        Score revenue quality for a list of DeFi protocols.

        Parameters
        ----------
        protocols : list of dict
            Required keys:
                name, total_revenue_30d_usd, trading_fee_revenue_pct,
                liquidation_fee_revenue_pct, protocol_fee_revenue_pct,
                incentive_revenue_pct, revenue_growth_mom_pct,
                revenue_concentration_top3_users_pct,
                unique_revenue_sources_count, has_recurring_revenue (bool),
                cyclical_dependency (bull_market|neutral|bear),
                revenue_30d_vs_90d_avg_ratio
        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict
            Keys: protocols, highest_quality, lowest_quality,
                  average_quality_score, premium_count,
                  incentive_dependent_count, timestamp
        """
        if config is None:
            config = {}

        scored = []
        for proto in protocols:
            name           = str(proto.get("name", "unknown"))
            rev_30d        = float(proto.get("total_revenue_30d_usd", 0.0))
            trading_fee    = float(proto.get("trading_fee_revenue_pct", 0.0))
            liq_fee        = float(proto.get("liquidation_fee_revenue_pct", 0.0))
            proto_fee      = float(proto.get("protocol_fee_revenue_pct", 0.0))
            incentive_pct  = float(proto.get("incentive_revenue_pct", 0.0))
            growth_mom     = float(proto.get("revenue_growth_mom_pct", 0.0))
            conc_top3      = float(proto.get("revenue_concentration_top3_users_pct", 0.0))
            unique_sources = int(proto.get("unique_revenue_sources_count", 0))
            has_recurring  = bool(proto.get("has_recurring_revenue", False))
            cyclical       = str(proto.get("cyclical_dependency", "neutral"))
            ratio_30_90    = float(proto.get("revenue_30d_vs_90d_avg_ratio", 1.0))

            organic_pct   = _mp973_organic_revenue_pct(incentive_pct)
            quality       = _mp973_quality_score(organic_pct, unique_sources, has_recurring, growth_mom)
            stability     = _mp973_revenue_stability_score(conc_top3, cyclical, ratio_30_90)
            sust_multiple = _mp973_sustainability_multiple(quality, rev_30d)
            label         = _mp973_quality_label(organic_pct, quality, incentive_pct)
            flags         = _mp973_flags(incentive_pct, conc_top3, growth_mom, quality, cyclical)

            scored.append({
                "name":                                name,
                "quality_score":                       round(quality, 4),
                "organic_revenue_pct":                 round(organic_pct, 4),
                "revenue_stability_score":             round(stability, 4),
                "sustainability_multiple":             round(sust_multiple, 4),
                "label":                               label,
                "flags":                               flags,
                "trading_fee_revenue_pct":             trading_fee,
                "liquidation_fee_revenue_pct":         liq_fee,
                "protocol_fee_revenue_pct":            proto_fee,
                "incentive_revenue_pct":               incentive_pct,
                "revenue_growth_mom_pct":              growth_mom,
                "has_recurring_revenue":               has_recurring,
                "cyclical_dependency":                 cyclical,
                "revenue_30d_vs_90d_avg_ratio":        ratio_30_90,
                "unique_revenue_sources_count":        unique_sources,
                "revenue_concentration_top3_users_pct": conc_top3,
            })

        # ── Aggregates ────────────────────────────────────────────────────────
        if scored:
            highest  = max(scored, key=lambda x: x["quality_score"])["name"]
            lowest   = min(scored, key=lambda x: x["quality_score"])["name"]
            avg_q    = sum(p["quality_score"] for p in scored) / len(scored)
            prem_cnt = sum(1 for p in scored if p["label"] == MP973_LABEL_PREMIUM)
            inc_cnt  = sum(
                1 for p in scored if p["label"] == MP973_LABEL_INCENTIVE_DEPENDENT
            )
        else:
            highest  = None
            lowest   = None
            avg_q    = 0.0
            prem_cnt = 0
            inc_cnt  = 0

        return {
            "protocols":                  scored,
            "highest_quality":            highest,
            "lowest_quality":             lowest,
            "average_quality_score":      round(avg_q, 4),
            "premium_count":              prem_cnt,
            "incentive_dependent_count":  inc_cnt,
            "timestamp":                  time.time(),
        }

    def run(
        self,
        protocols: list,
        config: dict = None,
        data_dir: Optional[str] = None,
    ) -> dict:
        """Score and persist result to ring-buffer log (cap 100, atomic write)."""
        result = self.score(protocols, config)
        path = _resolve_log_path(data_dir)
        log  = _load_log(path)
        log.append(result)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]
        _atomic_write(path, log)
        return result
