"""
MP-925 ProtocolFeeRevenueSustainabilityAnalyzer
------------------------------------------------
Analyzes the sustainability of a DeFi protocol's fee revenue by examining
revenue growth, operating cost coverage, token incentive dependence, and
unit economics.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "fee_revenue_sustainability_log.json"
)
_LOG_CAP = 100

# Thresholds for flags
_GROWING_REVENUE_THRESHOLD_PCT = 20.0
_INCENTIVE_DEPENDENT_PCT = 50.0       # incentives > 50% of revenue
_HIGH_PROFIT_MARGIN_PCT = 60.0

# Sustainability label thresholds (profit_margin_pct)
_PROFITABLE_MARGIN = 0.0
_BREAK_EVEN_MARGIN = -5.0
_SUBSIDIZED_MARGIN = -30.0
_LOSS_MAKING_MARGIN = -60.0

# Revenue quality / unit economics thresholds
_HIGH_REVENUE_QUALITY = 60.0
_GOOD_UNIT_ECON = 60.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _revenue_growth_rate_pct(
    monthly_fee_revenue_usd: float,
    monthly_revenue_3m_ago_usd: float,
) -> float:
    """Growth rate vs 3 months ago (%)."""
    if monthly_revenue_3m_ago_usd <= 0:
        return 0.0
    return (monthly_fee_revenue_usd - monthly_revenue_3m_ago_usd) / monthly_revenue_3m_ago_usd * 100.0


def _revenue_per_tvl_pct(
    monthly_fee_revenue_usd: float,
    tvl_usd: float,
) -> float:
    """Monthly fee revenue as % of TVL (annualised would be *12, but kept monthly)."""
    if tvl_usd <= 0:
        return 0.0
    return monthly_fee_revenue_usd / tvl_usd * 100.0


def _profit_margin_pct(
    monthly_fee_revenue_usd: float,
    monthly_operating_costs_usd: float,
    token_incentives_monthly_usd: float,
) -> float:
    """
    Profit margin after costs and token incentives.
    = (revenue - costs - incentives) / revenue * 100
    Returns 0 if revenue is 0.
    """
    if monthly_fee_revenue_usd <= 0:
        return -100.0 if (monthly_operating_costs_usd + token_incentives_monthly_usd) > 0 else 0.0
    profit = monthly_fee_revenue_usd - monthly_operating_costs_usd - token_incentives_monthly_usd
    return profit / monthly_fee_revenue_usd * 100.0


def _revenue_quality_score(
    monthly_fee_revenue_usd: float,
    token_incentives_monthly_usd: float,
    revenue_growth_rate: float,
    revenue_per_tvl: float,
) -> float:
    """
    0-100 score measuring fee revenue quality, ignoring token subsidies.
    Higher = better organic revenue.
    Components:
      - organic ratio (40 pts): fee revenue with no incentives
      - growth component (30 pts): positive growth rate
      - efficiency (30 pts): revenue per TVL
    """
    # Organic ratio: penalise if incentives are a large share of revenue
    if monthly_fee_revenue_usd <= 0:
        organic_ratio = 0.0
    else:
        incentive_ratio = min(1.0, max(0.0, token_incentives_monthly_usd / monthly_fee_revenue_usd))
        organic_ratio = 1.0 - incentive_ratio
    organic_pts = organic_ratio * 40.0

    # Growth component: clamp growth rate to -100..+200%
    growth_clamped = max(-100.0, min(200.0, revenue_growth_rate))
    growth_pts = (growth_clamped + 100.0) / 300.0 * 30.0

    # Efficiency: revenue_per_tvl in range 0..2%, map to 0-30
    eff_clamped = max(0.0, min(2.0, revenue_per_tvl))
    eff_pts = eff_clamped / 2.0 * 30.0

    return round(min(100.0, organic_pts + growth_pts + eff_pts), 2)


def _unit_economics_score(
    fee_revenue_per_user_usd: float,
    team_size: float,
    monthly_fee_revenue_usd: float,
    active_users_monthly: float,
) -> float:
    """
    0-100 unit economics score.
    Components:
      - Revenue per user relative to $100 benchmark (40 pts)
      - Revenue per team member (30 pts)
      - User monetization efficiency (30 pts)
    """
    # Revenue per user: $0→0pts, $100→40pts, capped
    rev_per_user_pts = min(40.0, (fee_revenue_per_user_usd / 100.0) * 40.0)

    # Revenue per team member per month: $0→0, $10k→30pts
    if team_size > 0:
        rev_per_team = monthly_fee_revenue_usd / team_size
        team_pts = min(30.0, (rev_per_team / 10_000.0) * 30.0)
    else:
        team_pts = 30.0  # no team = fully automated, perfect score on this dimension

    # User monetization: active users with any revenue
    if active_users_monthly > 0 and monthly_fee_revenue_usd > 0:
        monetization_ratio = min(1.0, fee_revenue_per_user_usd / max(fee_revenue_per_user_usd, 1.0))
        monetization_pts = 30.0 * monetization_ratio
    else:
        monetization_pts = 0.0

    return round(min(100.0, rev_per_user_pts + team_pts + monetization_pts), 2)


def _sustainability_label(profit_margin: float) -> str:
    """Map profit_margin_pct → sustainability label."""
    if profit_margin >= _PROFITABLE_MARGIN:
        return "PROFITABLE"
    if profit_margin >= _BREAK_EVEN_MARGIN:
        return "BREAK_EVEN"
    if profit_margin >= _SUBSIDIZED_MARGIN:
        return "SUBSIDIZED"
    if profit_margin >= _LOSS_MAKING_MARGIN:
        return "LOSS_MAKING"
    return "CRITICAL"


def _compute_flags(
    revenue_growth_rate: float,
    token_incentives: float,
    monthly_fee_revenue: float,
    market_share_pct: float,
    monthly_revenue_3m_ago: float,
    profit_margin: float,
) -> list[str]:
    """Return advisory flag strings for this protocol."""
    flags: list[str] = []
    if revenue_growth_rate > _GROWING_REVENUE_THRESHOLD_PCT:
        flags.append("GROWING_REVENUE")
    if monthly_fee_revenue > 0 and token_incentives / monthly_fee_revenue > _INCENTIVE_DEPENDENT_PCT / 100.0:
        flags.append("INCENTIVE_DEPENDENT")
    # Market share decline: if 3m ago had higher share and revenue declined
    if monthly_revenue_3m_ago > monthly_fee_revenue and market_share_pct < 5.0:
        flags.append("DECLINING_MARKET_SHARE")
    if profit_margin > _HIGH_PROFIT_MARGIN_PCT:
        flags.append("HIGH_PROFIT_MARGIN")
    if profit_margin < 0:
        flags.append("NEGATIVE_MARGIN")
    return flags


def _analyze_protocol(protocol: dict) -> dict:
    """Analyze a single protocol and return its metrics dict."""
    name = protocol.get("name", "UNKNOWN")
    revenue = float(protocol.get("monthly_fee_revenue_usd", 0.0))
    revenue_3m = float(protocol.get("monthly_revenue_3m_ago_usd", 0.0))
    revenue_6m = float(protocol.get("monthly_revenue_6m_ago_usd", 0.0))
    costs = float(protocol.get("monthly_operating_costs_usd", 0.0))
    team = float(protocol.get("team_size", 1.0))
    incentives = float(protocol.get("token_incentives_monthly_usd", 0.0))
    tvl = float(protocol.get("tvl_usd", 0.0))
    users = float(protocol.get("active_users_monthly", 0.0))
    rev_per_user = float(protocol.get("fee_revenue_per_user_usd", 0.0))
    mkt_share = float(protocol.get("market_share_pct", 0.0))

    growth = _revenue_growth_rate_pct(revenue, revenue_3m)
    rev_per_tvl = _revenue_per_tvl_pct(revenue, tvl)
    margin = _profit_margin_pct(revenue, costs, incentives)
    quality = _revenue_quality_score(revenue, incentives, growth, rev_per_tvl)
    unit_econ = _unit_economics_score(rev_per_user, team, revenue, users)
    label = _sustainability_label(margin)
    flags = _compute_flags(growth, incentives, revenue, mkt_share, revenue_3m, margin)

    return {
        "name": name,
        "revenue_growth_rate_pct": round(growth, 4),
        "revenue_per_tvl_pct": round(rev_per_tvl, 6),
        "profit_margin_pct": round(margin, 4),
        "revenue_quality_score": quality,
        "unit_economics_score": unit_econ,
        "sustainability_label": label,
        "flags": flags,
        # Pass-through for aggregation convenience
        "_monthly_fee_revenue_usd": revenue,
        "_revenue_6m_ago": revenue_6m,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolFeeRevenueSustainabilityAnalyzer:
    """
    Analyzes fee revenue sustainability for a list of DeFi protocols.

    Usage
    -----
    analyzer = ProtocolFeeRevenueSustainabilityAnalyzer()
    result = analyzer.analyze(protocols, config)
    """

    def analyze(self, protocols: list[dict], config: dict | None = None) -> dict:
        """
        Analyze fee revenue sustainability for each protocol.

        Parameters
        ----------
        protocols : list[dict]
            Each dict must contain:
            - name: str
            - monthly_fee_revenue_usd: float
            - monthly_revenue_3m_ago_usd: float
            - monthly_revenue_6m_ago_usd: float
            - monthly_operating_costs_usd: float
            - team_size: float
            - token_incentives_monthly_usd: float
            - tvl_usd: float
            - active_users_monthly: float
            - fee_revenue_per_user_usd: float
            - market_share_pct: float
        config : dict, optional
            - log_path: str

        Returns
        -------
        dict
            Per-protocol analysis + aggregate metrics.
        """
        cfg = config or {}
        log_path = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        if not protocols:
            return {
                "protocols": [],
                "most_profitable": None,
                "most_critical": None,
                "total_ecosystem_revenue": 0.0,
                "average_profit_margin": 0.0,
                "profitable_count": 0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        analyzed = [_analyze_protocol(p) for p in protocols]

        # Aggregate
        total_revenue = sum(a["_monthly_fee_revenue_usd"] for a in analyzed)
        margins = [a["profit_margin_pct"] for a in analyzed]
        average_margin = sum(margins) / len(margins)
        profitable_count = sum(1 for a in analyzed if a["sustainability_label"] == "PROFITABLE")

        most_profitable = max(analyzed, key=lambda x: x["profit_margin_pct"])
        most_critical = min(analyzed, key=lambda x: x["profit_margin_pct"])

        # Strip internal keys before returning
        clean_analyzed = []
        for a in analyzed:
            entry = {k: v for k, v in a.items() if not k.startswith("_")}
            clean_analyzed.append(entry)

        result: dict[str, Any] = {
            "protocols": clean_analyzed,
            "most_profitable": most_profitable["name"],
            "most_critical": most_critical["name"],
            "total_ecosystem_revenue": round(total_revenue, 2),
            "average_profit_margin": round(average_margin, 4),
            "profitable_count": profitable_count,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if write_log:
            log_entry = {
                "timestamp": result["timestamp"],
                "protocol_count": len(protocols),
                "most_profitable": result["most_profitable"],
                "most_critical": result["most_critical"],
                "total_ecosystem_revenue": result["total_ecosystem_revenue"],
                "average_profit_margin": result["average_profit_margin"],
                "profitable_count": profitable_count,
            }
            _atomic_log(log_path, log_entry)

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(protocols: list[dict], config: dict | None = None) -> dict:
    """Module-level convenience wrapper around ProtocolFeeRevenueSustainabilityAnalyzer.analyze."""
    return ProtocolFeeRevenueSustainabilityAnalyzer().analyze(protocols, config)
