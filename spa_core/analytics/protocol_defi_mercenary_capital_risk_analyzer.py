"""
MP-1075  ProtocolDeFiMercenaryCapitalRiskAnalyzer
--------------------------------------------------
Estimate how much of a protocol's TVL is "mercenary" incentive-chasing capital
likely to exit when emissions fall, and the resulting yield / liquidity
sustainability risk.

Mercenary capital parks in a protocol purely to harvest incentives and rotates
out the moment a richer opportunity appears or emissions taper. A protocol
whose TVL is dominated by such capital has fragile liquidity: cutting emissions
(or merely seeing them decay) can trigger a TVL exodus, widening spreads and
collapsing the very yields that attracted depositors. This module quantifies:

  (a) the incentive APR premium over organic yield,
  (b) the share of TVL judged mercenary vs. sticky,
  (c) TVL churn and whether incentive spend is covered by revenue, and
  (d) the estimated TVL retained if incentives were removed.

Genuine gap: existing incentive modules score incentive efficiency and farming
lifecycles, but none estimate mercenary-capital share or incentive stickiness.

The module returns:
- incentive_apr_premium_pct       – incentive APR minus base organic APR
- mercenary_tvl_pct               – share of TVL judged mercenary
- sticky_tvl_pct                  – 100 - mercenary
- tvl_churn_rate_pct              – 30d outflow / TVL
- incentive_cost_coverage_ratio   – protocol revenue / emissions spend
- projected_tvl_retention_pct     – TVL retained if incentives removed
- mercenary_risk_score            – 0-100, higher = riskier
- classification                  – STICKY .. MERCENARY_DOMINATED
- grade                           – A-F letter grade
- flags / recommendations         – advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
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
    "mercenary_capital_risk_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel coverage ratio used when there is no incentive spend (fully covered).
_NO_EMISSIONS_COVERAGE = 999.0

# Classification bands
CLASS_STICKY = "STICKY"
CLASS_MOSTLY_ORGANIC = "MOSTLY_ORGANIC"
CLASS_MIXED = "MIXED"
CLASS_INCENTIVE_DEPENDENT = "INCENTIVE_DEPENDENT"
CLASS_MERCENARY_DOMINATED = "MERCENARY_DOMINATED"

ALL_CLASSIFICATIONS = (
    CLASS_STICKY,
    CLASS_MOSTLY_ORGANIC,
    CLASS_MIXED,
    CLASS_INCENTIVE_DEPENDENT,
    CLASS_MERCENARY_DOMINATED,
)

# Flags
FLAG_HIGH_MERCENARY_SHARE = "HIGH_MERCENARY_SHARE"
FLAG_EMISSIONS_EXCEED_REVENUE = "EMISSIONS_EXCEED_REVENUE"
FLAG_HIGH_CHURN = "HIGH_CHURN"
FLAG_YOUNG_DEPOSIT_BASE = "YOUNG_DEPOSIT_BASE"
FLAG_LARGE_INCENTIVE_PREMIUM = "LARGE_INCENTIVE_PREMIUM"
FLAG_LOW_RETENTION_RISK = "LOW_RETENTION_RISK"
FLAG_STICKY_BASE = "STICKY_BASE"
FLAG_ORGANIC_YIELD_STRONG = "ORGANIC_YIELD_STRONG"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_MERCENARY_SHARE,
    FLAG_EMISSIONS_EXCEED_REVENUE,
    FLAG_HIGH_CHURN,
    FLAG_YOUNG_DEPOSIT_BASE,
    FLAG_LARGE_INCENTIVE_PREMIUM,
    FLAG_LOW_RETENTION_RISK,
    FLAG_STICKY_BASE,
    FLAG_ORGANIC_YIELD_STRONG,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds
_HIGH_MERCENARY_PCT = 60.0          # >= 60% mercenary TVL is high
_HIGH_CHURN_PCT = 30.0             # 30d outflow >= 30% of TVL is high churn
_YOUNG_DEPOSIT_DAYS = 30.0         # avg deposit age < 30 days is young
_LARGE_PREMIUM_PCT = 5.0          # incentive premium >= 5% is large
_LOW_RETENTION_PCT = 40.0          # < 40% retention if incentives removed
_STRONG_ORGANIC_APR_PCT = 4.0      # organic APR >= 4% is "strong" standalone
_STICKY_BASE_PCT = 60.0            # sticky TVL >= 60% is a sticky base


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
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
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, abs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _incentive_apr_premium_pct(
    incentive_apr_pct: float,
    base_organic_apr_pct: float,
) -> float:
    """
    Incentive APR premium over organic yield, in pct (clamped to >= 0).

    A larger premium attracts more incentive-chasing capital.
    """
    return max(0.0, incentive_apr_pct - base_organic_apr_pct)


def _incentivized_share_pct(
    incentivized_tvl_usd: float,
    total_tvl_usd: float,
) -> float:
    """
    Share of TVL sitting in incentivized pools, in pct.

    Returns 0.0 when total TVL <= 0 (avoids div-by-zero).
    """
    if total_tvl_usd <= 0:
        return 0.0
    return _clamp(incentivized_tvl_usd / total_tvl_usd * 100.0)


def _tvl_churn_rate_pct(
    tvl_outflow_30d_usd: float,
    total_tvl_usd: float,
) -> float:
    """
    30-day outflow as a share of TVL, in pct.

    Returns 0.0 when total TVL <= 0 (avoids div-by-zero). Not clamped above
    100 because outflow can exceed current TVL in a fast-bleeding pool, but
    floored at 0.
    """
    if total_tvl_usd <= 0:
        return 0.0
    return max(0.0, tvl_outflow_30d_usd / total_tvl_usd * 100.0)


def _incentive_cost_coverage_ratio(
    protocol_revenue_usd_per_day: float,
    reward_token_emissions_usd_per_day: float,
) -> tuple[float, bool]:
    """
    Protocol revenue relative to daily incentive spend.

    Returns ``(ratio, no_emissions)``.

    When there is no incentive spend the protocol is trivially "covered"; we
    return a large capped sentinel (999.0) and ``no_emissions=True`` to avoid
    division-by-zero and ``float('inf')``.
    """
    if reward_token_emissions_usd_per_day <= 0:
        return _NO_EMISSIONS_COVERAGE, True
    return max(0.0, protocol_revenue_usd_per_day) / reward_token_emissions_usd_per_day, False


def _mercenary_tvl_pct(
    incentivized_share_pct: float,
    incentive_apr_premium_pct: float,
    avg_deposit_age_days: float,
    tvl_churn_rate_pct: float,
) -> float:
    """
    Heuristic share of TVL judged "mercenary", 0-100.

    Mercenary capital is more likely when:
    - a large share of TVL sits in incentivized pools,
    - the incentive premium over organic yield is large,
    - the average deposit age is young, and
    - observed churn is high.

    Each driver contributes a bounded component; the blend is clamped to 0-100.
    Only the incentivized share can be mercenary, so the result is capped at
    the incentivized share.
    """
    # Premium driver: saturates at a large premium.
    premium_frac = _clamp(
        incentive_apr_premium_pct / (_LARGE_PREMIUM_PCT * 2.0), 0.0, 1.0
    )

    # Youth driver: 0 days → 1.0, >= 180 days → 0.0.
    youth_frac = _clamp(1.0 - max(0.0, avg_deposit_age_days) / 180.0, 0.0, 1.0)

    # Churn driver: saturates at twice the high-churn threshold.
    churn_frac = _clamp(
        tvl_churn_rate_pct / (_HIGH_CHURN_PCT * 2.0), 0.0, 1.0
    )

    # Blend the behavioural drivers (premium, youth, churn) into a propensity.
    propensity = 0.45 * premium_frac + 0.30 * youth_frac + 0.25 * churn_frac

    # Mercenary capital can only come from the incentivized share.
    mercenary = _clamp(incentivized_share_pct) * propensity
    return _clamp(mercenary)


def _projected_tvl_retention_pct(
    mercenary_tvl_pct: float,
    base_organic_apr_pct: float,
    incentive_apr_premium_pct: float,
) -> float:
    """
    Estimated share of TVL retained if incentives were removed, 0-100.

    Starts from the sticky share (100 - mercenary) and nudges it up when the
    organic yield is strong enough to retain some otherwise-fickle capital, and
    down when the incentive premium is so large that even nominally sticky
    capital may chase yield elsewhere.
    """
    sticky = _clamp(100.0 - _clamp(mercenary_tvl_pct))

    # Strong organic yield retains a little extra (up to +10).
    organic_bonus = _clamp(
        base_organic_apr_pct / _STRONG_ORGANIC_APR_PCT, 0.0, 1.0
    ) * 10.0

    # A very large premium erodes retention a little (up to -10).
    premium_drag = _clamp(
        incentive_apr_premium_pct / (_LARGE_PREMIUM_PCT * 2.0), 0.0, 1.0
    ) * 10.0

    return _clamp(sticky + organic_bonus - premium_drag)


def _mercenary_risk_score(
    mercenary_tvl_pct: float,
    tvl_churn_rate_pct: float,
    coverage_ratio: float,
    no_emissions: bool,
    projected_tvl_retention_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = riskier.

    Blends:
    - mercenary share (0-45): the dominant driver,
    - churn (0-20): saturating at twice the high-churn threshold,
    - poor coverage (0-20): emissions outrunning revenue is risky,
    - low retention (0-15): little TVL survives an incentive cut.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    mercenary_component = _clamp(mercenary_tvl_pct / 100.0, 0.0, 1.0) * 45.0

    churn_component = _clamp(
        tvl_churn_rate_pct / (_HIGH_CHURN_PCT * 2.0), 0.0, 1.0
    ) * 20.0

    # Coverage component: ratio >= 1 → 0 risk; ratio 0 → full 20.
    if no_emissions or coverage_ratio >= 1.0:
        coverage_component = 0.0
    else:
        coverage_component = (1.0 - _clamp(coverage_ratio, 0.0, 1.0)) * 20.0

    retention_component = (
        1.0 - _clamp(projected_tvl_retention_pct / 100.0, 0.0, 1.0)
    ) * 15.0

    return _clamp(
        mercenary_component
        + churn_component
        + coverage_component
        + retention_component
    )


def _classify(
    mercenary_tvl_pct: float,
    mercenary_risk_score: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band, driven by the mercenary share.

    Bands (on mercenary_tvl_pct):
      < 20   → STICKY
      < 40   → MOSTLY_ORGANIC
      < 60   → MIXED
      < 80   → INCENTIVE_DEPENDENT
      >= 80  → MERCENARY_DOMINATED
    A high overall risk score downgrades a borderline band by one notch.

    No data falls back to STICKY (no mercenary capital can be demonstrated).
    """
    if not has_data:
        return CLASS_STICKY

    if mercenary_tvl_pct < 20.0:
        base = CLASS_STICKY
    elif mercenary_tvl_pct < 40.0:
        base = CLASS_MOSTLY_ORGANIC
    elif mercenary_tvl_pct < 60.0:
        base = CLASS_MIXED
    elif mercenary_tvl_pct < 80.0:
        base = CLASS_INCENTIVE_DEPENDENT
    else:
        base = CLASS_MERCENARY_DOMINATED

    order = list(ALL_CLASSIFICATIONS)
    idx = order.index(base)
    if mercenary_risk_score >= 75.0 and idx < len(order) - 1:
        idx += 1
    return order[idx]


def _grade(mercenary_risk_score: float) -> str:
    """Map mercenary_risk_score (higher = riskier) to an A-F letter grade."""
    s = mercenary_risk_score
    if s < 10.0:
        return "A"
    if s < 30.0:
        return "B"
    if s < 50.0:
        return "C"
    if s < 70.0:
        return "D"
    return "F"


def _flags(
    mercenary_tvl_pct: float,
    sticky_tvl_pct: float,
    coverage_ratio: float,
    no_emissions: bool,
    tvl_churn_rate_pct: float,
    avg_deposit_age_days: float,
    incentive_apr_premium_pct: float,
    projected_tvl_retention_pct: float,
    base_organic_apr_pct: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if mercenary_tvl_pct >= _HIGH_MERCENARY_PCT:
        flags.append(FLAG_HIGH_MERCENARY_SHARE)

    if not no_emissions and coverage_ratio < 1.0:
        flags.append(FLAG_EMISSIONS_EXCEED_REVENUE)

    if tvl_churn_rate_pct >= _HIGH_CHURN_PCT:
        flags.append(FLAG_HIGH_CHURN)

    if 0.0 < avg_deposit_age_days < _YOUNG_DEPOSIT_DAYS:
        flags.append(FLAG_YOUNG_DEPOSIT_BASE)

    if incentive_apr_premium_pct >= _LARGE_PREMIUM_PCT:
        flags.append(FLAG_LARGE_INCENTIVE_PREMIUM)

    if projected_tvl_retention_pct < _LOW_RETENTION_PCT:
        flags.append(FLAG_LOW_RETENTION_RISK)

    if sticky_tvl_pct >= _STICKY_BASE_PCT:
        flags.append(FLAG_STICKY_BASE)

    if base_organic_apr_pct >= _STRONG_ORGANIC_APR_PCT:
        flags.append(FLAG_ORGANIC_YIELD_STRONG)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    mercenary_tvl_pct: float,
    sticky_tvl_pct: float,
    projected_tvl_retention_pct: float,
    coverage_ratio: float,
    tvl_churn_rate_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: total_tvl_usd <= 0. Cannot assess "
            "mercenary-capital risk for this protocol."
        )
        return recs

    if classification == CLASS_MERCENARY_DOMINATED:
        recs.append(
            f"Mercenary-dominated: ~{mercenary_tvl_pct:.0f}% of TVL is "
            "incentive-chasing and likely to exit if emissions fall. Treat "
            "liquidity depth and current yields as unstable."
        )
    elif classification == CLASS_INCENTIVE_DEPENDENT:
        recs.append(
            f"Incentive-dependent: ~{mercenary_tvl_pct:.0f}% of TVL is "
            "mercenary. The protocol leans on emissions to retain liquidity; "
            "size positions for a possible drawdown."
        )
    elif classification == CLASS_MIXED:
        recs.append(
            f"Mixed base: ~{mercenary_tvl_pct:.0f}% mercenary vs. "
            f"{sticky_tvl_pct:.0f}% sticky. A material slice of TVL is "
            "incentive-sensitive; monitor emissions changes."
        )
    elif classification == CLASS_MOSTLY_ORGANIC:
        recs.append(
            f"Mostly organic: only ~{mercenary_tvl_pct:.0f}% of TVL looks "
            "mercenary. Liquidity is reasonably resilient to emission changes."
        )
    else:  # STICKY
        recs.append(
            f"Sticky base: ~{sticky_tvl_pct:.0f}% of TVL is non-mercenary. "
            "Liquidity is unlikely to flee on an emission cut."
        )

    if FLAG_EMISSIONS_EXCEED_REVENUE in flags:
        recs.append(
            f"Emissions exceed protocol revenue (coverage ratio "
            f"{coverage_ratio:.2f} < 1.0): incentive spend is unsustainable "
            "and will eventually be cut, pressuring mercenary TVL."
        )

    if FLAG_HIGH_CHURN in flags:
        recs.append(
            f"High TVL churn ({tvl_churn_rate_pct:.0f}% 30d outflow): capital "
            "is already rotating quickly, consistent with a mercenary base."
        )

    if FLAG_YOUNG_DEPOSIT_BASE in flags:
        recs.append(
            "Young deposit base: the average deposit is recent, so little of "
            "the TVL has demonstrated stickiness through a yield cycle."
        )

    if FLAG_LARGE_INCENTIVE_PREMIUM in flags:
        recs.append(
            "Large incentive premium over organic yield: most of the headline "
            "APR is subsidised and will not persist once emissions taper."
        )

    if FLAG_LOW_RETENTION_RISK in flags:
        recs.append(
            f"Low projected retention (~{projected_tvl_retention_pct:.0f}% of "
            "TVL would remain if incentives were removed). Expect a sharp TVL "
            "drop on an incentive cut."
        )

    if FLAG_STICKY_BASE in flags and FLAG_HIGH_MERCENARY_SHARE not in flags:
        recs.append(
            f"Sticky base intact (~{sticky_tvl_pct:.0f}% non-mercenary): the "
            "core liquidity should survive an emission reduction."
        )

    if FLAG_ORGANIC_YIELD_STRONG in flags:
        recs.append(
            "Organic yield is strong on its own, which improves the odds that "
            "depositors stay even without incentives."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    protocol: dict | None = None,
    config: dict | None = None,
    *,
    total_tvl_usd: float | None = None,
    incentivized_tvl_usd: float | None = None,
    incentive_apr_pct: float | None = None,
    base_organic_apr_pct: float | None = None,
    avg_deposit_age_days: float | None = None,
    tvl_inflow_30d_usd: float | None = None,
    tvl_outflow_30d_usd: float | None = None,
    reward_token_emissions_usd_per_day: float | None = None,
    protocol_revenue_usd_per_day: float | None = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the mercenary-capital risk of a single protocol / pool.

    Inputs may be supplied as a ``protocol`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                               : str
    - total_tvl_usd                      : float (>= 0)
    - incentivized_tvl_usd               : float (>= 0)
    - incentive_apr_pct                  : float (>= 0)
    - base_organic_apr_pct               : float (>= 0)
    - avg_deposit_age_days               : float (>= 0)
    - tvl_inflow_30d_usd                 : float (>= 0)
    - tvl_outflow_30d_usd                : float (>= 0)
    - reward_token_emissions_usd_per_day : float (>= 0)
    - protocol_revenue_usd_per_day       : float (>= 0)

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    p = protocol if isinstance(protocol, dict) else {}

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(p.get(key, default), default)

    name_val = name if name is not None else str(p.get("name", "UNKNOWN"))

    total_tvl = max(0.0, _pick(total_tvl_usd, "total_tvl_usd", 0.0))
    incentivized_tvl = max(0.0, _pick(
        incentivized_tvl_usd, "incentivized_tvl_usd", 0.0))
    incentive_apr = max(0.0, _pick(incentive_apr_pct, "incentive_apr_pct", 0.0))
    base_organic_apr = max(0.0, _pick(
        base_organic_apr_pct, "base_organic_apr_pct", 0.0))
    deposit_age = max(0.0, _pick(avg_deposit_age_days, "avg_deposit_age_days", 0.0))
    inflow = max(0.0, _pick(tvl_inflow_30d_usd, "tvl_inflow_30d_usd", 0.0))
    outflow = max(0.0, _pick(tvl_outflow_30d_usd, "tvl_outflow_30d_usd", 0.0))
    emissions = max(0.0, _pick(
        reward_token_emissions_usd_per_day, "reward_token_emissions_usd_per_day", 0.0))
    revenue = max(0.0, _pick(
        protocol_revenue_usd_per_day, "protocol_revenue_usd_per_day", 0.0))

    # Clamp incentivized TVL to total TVL (cannot exceed the whole).
    if total_tvl > 0:
        incentivized_tvl = min(incentivized_tvl, total_tvl)

    # Data sufficiency: need a positive total TVL.
    has_data = total_tvl > 0

    premium = _incentive_apr_premium_pct(incentive_apr, base_organic_apr)
    incentivized_share = _incentivized_share_pct(incentivized_tvl, total_tvl)
    churn = _tvl_churn_rate_pct(outflow, total_tvl)
    coverage_ratio, no_emissions = _incentive_cost_coverage_ratio(
        revenue, emissions
    )
    mercenary = _mercenary_tvl_pct(
        incentivized_share, premium, deposit_age, churn
    )
    sticky = _clamp(100.0 - mercenary)
    retention = _projected_tvl_retention_pct(
        mercenary, base_organic_apr, premium
    )
    risk = _mercenary_risk_score(
        mercenary, churn, coverage_ratio, no_emissions, retention, has_data
    )
    classification = _classify(mercenary, risk, has_data)
    grade = _grade(risk)
    flags = _flags(
        mercenary,
        sticky,
        coverage_ratio,
        no_emissions,
        churn,
        deposit_age,
        premium,
        retention,
        base_organic_apr,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        mercenary,
        sticky,
        retention,
        coverage_ratio,
        churn,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "total_tvl_usd": total_tvl,
        "incentivized_tvl_usd": incentivized_tvl,
        "incentive_apr_pct": incentive_apr,
        "base_organic_apr_pct": base_organic_apr,
        "avg_deposit_age_days": deposit_age,
        "tvl_inflow_30d_usd": inflow,
        "tvl_outflow_30d_usd": outflow,
        "reward_token_emissions_usd_per_day": emissions,
        "protocol_revenue_usd_per_day": revenue,
        "incentive_apr_premium_pct": premium,
        "incentivized_share_pct": incentivized_share,
        "mercenary_tvl_pct": mercenary,
        "sticky_tvl_pct": sticky,
        "tvl_churn_rate_pct": churn,
        "incentive_cost_coverage_ratio": coverage_ratio,
        "no_emissions": no_emissions,
        "projected_tvl_retention_pct": retention,
        "mercenary_risk_score": risk,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(protocols: list, config: dict | None = None) -> dict:
    """
    Analyse mercenary-capital risk across a batch of protocols and summarise.

    Returns
    -------
    dict
        - total_protocols              : int
        - results                      : list[dict]  (per-protocol analysis)
        - most_mercenary_protocol      : str | None  (highest mercenary risk)
        - least_mercenary_protocol     : str | None  (lowest mercenary risk)
        - avg_mercenary_risk_score     : float
        - mercenary_dominated_count    : int
        - timestamp                    : float
    """
    if not isinstance(protocols, list):
        protocols = []

    results = [
        analyze(p if isinstance(p, dict) else {}, config=config)
        for p in protocols
    ]
    total = len(results)

    if total == 0:
        return {
            "total_protocols": 0,
            "results": [],
            "most_mercenary_protocol": None,
            "least_mercenary_protocol": None,
            "avg_mercenary_risk_score": 0.0,
            "mercenary_dominated_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["mercenary_risk_score"])
    least = min(results, key=lambda r: r["mercenary_risk_score"])
    avg = sum(r["mercenary_risk_score"] for r in results) / total
    dominated = sum(
        1 for r in results if r["classification"] == CLASS_MERCENARY_DOMINATED
    )

    return {
        "total_protocols": total,
        "results": results,
        "most_mercenary_protocol": most["name"],
        "least_mercenary_protocol": least["name"],
        "avg_mercenary_risk_score": avg,
        "mercenary_dominated_count": dominated,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiMercenaryCapitalRiskAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = ProtocolDeFiMercenaryCapitalRiskAnalyzer()
    >>> r = a.analyze({"name": "FarmX", "total_tvl_usd": 50_000_000, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, protocol: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(protocol, config=self._config, **kwargs)

    def analyze_portfolio(self, protocols: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(protocols, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_protocols = [
        {
            "name": "FarmX (mercenary)",
            "total_tvl_usd": 50_000_000.0,
            "incentivized_tvl_usd": 48_000_000.0,
            "incentive_apr_pct": 40.0,
            "base_organic_apr_pct": 2.0,
            "avg_deposit_age_days": 9.0,
            "tvl_inflow_30d_usd": 30_000_000.0,
            "tvl_outflow_30d_usd": 25_000_000.0,
            "reward_token_emissions_usd_per_day": 100_000.0,
            "protocol_revenue_usd_per_day": 20_000.0,
        },
        {
            "name": "BlueChip (sticky)",
            "total_tvl_usd": 800_000_000.0,
            "incentivized_tvl_usd": 50_000_000.0,
            "incentive_apr_pct": 5.0,
            "base_organic_apr_pct": 4.5,
            "avg_deposit_age_days": 200.0,
            "tvl_inflow_30d_usd": 20_000_000.0,
            "tvl_outflow_30d_usd": 10_000_000.0,
            "reward_token_emissions_usd_per_day": 5_000.0,
            "protocol_revenue_usd_per_day": 50_000.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_protocols[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_protocols)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
