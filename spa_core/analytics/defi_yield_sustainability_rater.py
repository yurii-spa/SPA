"""
MP-917: DeFi Yield Sustainability Rater
Evaluates the long-term sustainability of DeFi yield strategies by decomposing
real yield from emission-based yield and assessing protocol fundamentals.
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

import json
import os
import datetime

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_sustainability_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Sustainability labels
# --------------------------------------------------------------------------- #
LABEL_HIGHLY_SUSTAINABLE = "HIGHLY_SUSTAINABLE"
LABEL_SUSTAINABLE = "SUSTAINABLE"
LABEL_MODERATE = "MODERATE"
LABEL_DEPENDENT_ON_EMISSIONS = "DEPENDENT_ON_EMISSIONS"
LABEL_PONZI_RISK = "PONZI_RISK"

# --------------------------------------------------------------------------- #
# Flags
# --------------------------------------------------------------------------- #
FLAG_EMISSION_HEAVY = "EMISSION_HEAVY"
FLAG_DECLINING_TVL = "DECLINING_TVL"
FLAG_TOKEN_COLLAPSING = "TOKEN_COLLAPSING"
FLAG_UNAUDITED = "UNAUDITED"
FLAG_YOUNG_PROTOCOL = "YOUNG_PROTOCOL"
FLAG_REVENUE_POSITIVE = "REVENUE_POSITIVE"


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    """Safe division returning default when denominator is zero."""
    if den == 0:
        return default
    return num / den


def _real_yield_ratio(real_yield_pct: float, current_apy_pct: float) -> float:
    """
    Fraction of total APY that comes from real yield (fees/interest).
    Clamped to [0, 1].
    """
    ratio = _safe_div(real_yield_pct, current_apy_pct, 0.0)
    return round(min(max(ratio, 0.0), 1.0), 4)


def _emission_dependency(emission_apy_pct: float, current_apy_pct: float) -> float:
    """
    0-1 score: fraction of APY from token emissions.
    0 = fully real-yield, 1 = fully emission-dependent.
    """
    dep = _safe_div(emission_apy_pct, current_apy_pct, 0.0)
    return round(min(max(dep, 0.0), 1.0), 4)


def _token_drag_pct(
    token_inflation_rate_pct: float,
    token_price_change_90d_pct: float,
    emission_dependency_score: float,
) -> float:
    """
    Estimated token drag on yield from inflation and price decline.
    drag = (inflation + max(0, -price_change)) * emission_dependency
    """
    price_loss = max(0.0, -token_price_change_90d_pct)
    drag = (token_inflation_rate_pct + price_loss) * emission_dependency_score
    return round(drag, 4)


def _sustainability_score(
    real_yield_ratio: float,
    protocol_age_months: float,
    audit_count: int,
    tvl_trend: str,
    token_price_change_90d_pct: float,
    revenue_per_tvl_pct: float,
    emission_dep: float,
) -> float:
    """
    Sustainability score 0-100.

    Component weights:
      real_yield_ratio    → 35 pts  (higher is better)
      age maturity        → 15 pts  (>24m = full credit)
      audit coverage      → 15 pts  (>= 3 audits = full credit)
      TVL trend           → 15 pts  (growing=15, stable=8, declining=0)
      token price health  → 10 pts  (>0%=10, -50%..0=partial, <-50%=0)
      revenue_per_tvl     → 10 pts  (>real_yield = 10, else proportional)
    Penalty: emission_dep > 0.8 → -10 pts
    """
    # Real yield component
    ryr = min(real_yield_ratio * 35.0, 35.0)

    # Age maturity (0-15): linear up to 24 months
    age_pts = min(protocol_age_months / 24.0 * 15.0, 15.0)

    # Audit coverage (0-15): 3+ audits → full credit
    audit_pts = min(audit_count / 3.0 * 15.0, 15.0)

    # TVL trend
    trend_lc = tvl_trend.lower() if isinstance(tvl_trend, str) else "stable"
    if trend_lc == "growing":
        trend_pts = 15.0
    elif trend_lc == "stable":
        trend_pts = 8.0
    else:
        trend_pts = 0.0

    # Token price health (0-10)
    if token_price_change_90d_pct >= 0:
        price_pts = 10.0
    elif token_price_change_90d_pct >= -50:
        price_pts = (token_price_change_90d_pct + 50) / 50.0 * 10.0
    else:
        price_pts = 0.0

    # Revenue per TVL component (0-10)
    if revenue_per_tvl_pct > 0:
        rev_pts = min(revenue_per_tvl_pct / 2.0 * 10.0, 10.0)
    else:
        rev_pts = 0.0

    score = ryr + age_pts + audit_pts + trend_pts + price_pts + rev_pts

    # Emission penalty
    if emission_dep > 0.8:
        score -= 10.0

    return round(min(max(score, 0.0), 100.0), 2)


def _sustainability_label(score: float, emission_dep: float) -> str:
    """Assign sustainability label from score and emission dependency."""
    if emission_dep > 0.8 and score < 30:
        return LABEL_PONZI_RISK
    if score >= 75:
        return LABEL_HIGHLY_SUSTAINABLE
    if score >= 55:
        return LABEL_SUSTAINABLE
    # High emission dependency takes priority over the MODERATE band
    if emission_dep >= 0.6:
        return LABEL_DEPENDENT_ON_EMISSIONS
    if score >= 35:
        return LABEL_MODERATE
    return LABEL_PONZI_RISK


def _compute_flags(
    emission_apy_pct: float,
    current_apy_pct: float,
    tvl_trend: str,
    token_price_change_90d_pct: float,
    audit_count: int,
    protocol_age_months: float,
    revenue_per_tvl_pct: float,
    real_yield_pct: float,
) -> list:
    flags = []

    # EMISSION_HEAVY: emission APY > 80% of total
    if current_apy_pct > 0 and _safe_div(emission_apy_pct, current_apy_pct) > 0.8:
        flags.append(FLAG_EMISSION_HEAVY)

    # DECLINING_TVL
    trend_lc = tvl_trend.lower() if isinstance(tvl_trend, str) else ""
    if trend_lc == "declining":
        flags.append(FLAG_DECLINING_TVL)

    # TOKEN_COLLAPSING: price dropped > 50%
    if token_price_change_90d_pct < -50:
        flags.append(FLAG_TOKEN_COLLAPSING)

    # UNAUDITED
    if audit_count == 0:
        flags.append(FLAG_UNAUDITED)

    # YOUNG_PROTOCOL: < 6 months
    if protocol_age_months < 6:
        flags.append(FLAG_YOUNG_PROTOCOL)

    # REVENUE_POSITIVE: protocol revenue > real yield (self-sustaining)
    if revenue_per_tvl_pct > real_yield_pct:
        flags.append(FLAG_REVENUE_POSITIVE)

    return flags


def _rate_strategy(strategy: dict) -> dict:
    """Compute derived sustainability metrics for a single strategy dict."""
    name = strategy.get("name", "unknown")
    current_apy_pct = float(strategy.get("current_apy_pct", 0))
    real_yield_pct = float(strategy.get("real_yield_pct", 0))
    emission_apy_pct = float(strategy.get("emission_apy_pct", 0))
    protocol_age_months = float(strategy.get("protocol_age_months", 0))
    tvl_usd = float(strategy.get("tvl_usd", 0))
    tvl_trend = str(strategy.get("tvl_trend", "stable"))
    token_inflation_rate_pct = float(strategy.get("token_inflation_rate_pct", 0))
    token_price_change_90d_pct = float(strategy.get("token_price_change_90d_pct", 0))
    audit_count = int(strategy.get("audit_count", 0))
    revenue_per_tvl_pct = float(strategy.get("revenue_per_tvl_pct", 0))

    ryr = _real_yield_ratio(real_yield_pct, current_apy_pct)
    emission_dep = _emission_dependency(emission_apy_pct, current_apy_pct)
    token_drag = _token_drag_pct(
        token_inflation_rate_pct, token_price_change_90d_pct, emission_dep
    )

    score = _sustainability_score(
        ryr,
        protocol_age_months,
        audit_count,
        tvl_trend,
        token_price_change_90d_pct,
        revenue_per_tvl_pct,
        emission_dep,
    )
    label = _sustainability_label(score, emission_dep)

    flags = _compute_flags(
        emission_apy_pct,
        current_apy_pct,
        tvl_trend,
        token_price_change_90d_pct,
        audit_count,
        protocol_age_months,
        revenue_per_tvl_pct,
        real_yield_pct,
    )

    return {
        "name": name,
        "real_yield_ratio": ryr,
        "sustainability_score": score,
        "emission_dependency": emission_dep,
        "token_drag_pct": token_drag,
        "sustainability_label": label,
        "flags": flags,
        # pass-through raw fields
        "current_apy_pct": current_apy_pct,
        "real_yield_pct": real_yield_pct,
        "emission_apy_pct": emission_apy_pct,
        "protocol_age_months": protocol_age_months,
        "tvl_usd": tvl_usd,
        "tvl_trend": tvl_trend,
        "token_inflation_rate_pct": token_inflation_rate_pct,
        "token_price_change_90d_pct": token_price_change_90d_pct,
        "audit_count": audit_count,
        "revenue_per_tvl_pct": revenue_per_tvl_pct,
    }


def _build_aggregates(results: list) -> dict:
    if not results:
        return {
            "most_sustainable": None,
            "highest_ponzi_risk": None,
            "average_real_yield_ratio": 0.0,
            "average_sustainability": 0.0,
            "ponzi_risk_count": 0,
        }

    sorted_by_score = sorted(results, key=lambda r: r["sustainability_score"], reverse=True)
    most_sustainable = sorted_by_score[0]["name"]
    highest_ponzi_risk = sorted_by_score[-1]["name"]

    avg_ryr = sum(r["real_yield_ratio"] for r in results) / len(results)
    avg_sus = sum(r["sustainability_score"] for r in results) / len(results)
    ponzi_count = sum(1 for r in results if r["sustainability_label"] == LABEL_PONZI_RISK)

    return {
        "most_sustainable": most_sustainable,
        "highest_ponzi_risk": highest_ponzi_risk,
        "average_real_yield_ratio": round(avg_ryr, 4),
        "average_sustainability": round(avg_sus, 2),
        "ponzi_risk_count": ponzi_count,
    }


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append entry to ring-buffer JSON log atomically."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


class DeFiYieldSustainabilityRater:
    """
    Rates the long-term sustainability of DeFi yield strategies.

    Usage::

        rater = DeFiYieldSustainabilityRater()
        result = rater.rate(strategies, config)
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def rate(self, strategies: list, config: dict | None = None) -> dict:
        """
        Evaluate sustainability for a list of yield strategy dicts.

        Parameters
        ----------
        strategies : list[dict]
            Each dict must contain the keys described in the module docstring.
        config : dict, optional
            Reserved for future configuration (ignored currently).

        Returns
        -------
        dict with keys:
            strategies  – list of per-strategy result dicts
            aggregates  – portfolio-level aggregates
            timestamp   – ISO-8601 UTC timestamp
        """
        if config is None:
            config = {}

        results = [_rate_strategy(s) for s in strategies]
        aggregates = _build_aggregates(results)

        timestamp = datetime.datetime.utcnow().isoformat() + "Z"

        output = {
            "strategies": results,
            "aggregates": aggregates,
            "timestamp": timestamp,
        }

        # Persist to ring-buffer log
        log_entry = {
            "timestamp": timestamp,
            "strategy_count": len(results),
            "aggregates": aggregates,
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return output
