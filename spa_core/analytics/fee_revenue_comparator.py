"""
MP-800 FeeRevenueComparator
Compares fee revenue efficiency across DeFi protocols:
  - Revenue per dollar of TVL
  - Fee yield to LPs
  - Protocol sustainability via revenue-to-expense ratio

Pure stdlib, read-only advisory, atomic writes, ring-buffer 100.
"""

import json
import math
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "fee_revenue_comparison_log.json"
)
_LOG_MAX = 100

_DEFAULT_MIN_ANNUALIZED_REVENUE = 1_000_000.0  # USD

# Efficiency grade thresholds (revenue_to_tvl_pct)
_GRADE_A = 5.0
_GRADE_B = 2.0
_GRADE_C = 1.0
_GRADE_D = 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Compare fee revenue efficiency across protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each item: {
            "name": str,
            "tvl_usd": float,
            "daily_fee_revenue_usd": float,
            "lp_fee_share_pct": float,        # 0-100
            "protocol_fee_share_pct": float,   # 0-100
            "monthly_expenses_usd": float
        }
    config : dict, optional
        {
            "min_annualized_revenue_usd": float  # default 1_000_000
        }

    Returns
    -------
    dict  (see module docstring for full schema)
    """
    cfg = config or {}
    # config param exists but per spec we include all protocols — no hard filter
    _min_rev = float(cfg.get("min_annualized_revenue_usd", _DEFAULT_MIN_ANNUALIZED_REVENUE))

    rows = []
    total_daily = 0.0
    total_annual = 0.0

    for p in protocols:
        name = str(p.get("name", ""))
        tvl = max(0.0, float(p.get("tvl_usd", 0.0)))
        daily_fee = max(0.0, float(p.get("daily_fee_revenue_usd", 0.0)))
        lp_share = max(0.0, min(100.0, float(p.get("lp_fee_share_pct", 0.0))))
        proto_share = max(0.0, min(100.0, float(p.get("protocol_fee_share_pct", 0.0))))
        monthly_exp = max(0.0, float(p.get("monthly_expenses_usd", 0.0)))

        annualized = daily_fee * 365.0

        # Revenue-to-TVL
        rev_to_tvl = (annualized / tvl * 100.0) if tvl > 0 else 0.0

        # LP yield
        lp_yield = (annualized * lp_share / 100.0 / tvl * 100.0) if tvl > 0 else 0.0

        # Protocol revenue annual
        proto_rev_annual = annualized * proto_share / 100.0

        # Sustainability ratio
        annual_expenses = monthly_exp * 12.0
        if annual_expenses > 0:
            sustainability_ratio = proto_rev_annual / annual_expenses
        else:
            # zero expenses → infinite sustainability
            sustainability_ratio = math.inf

        is_sustainable = sustainability_ratio >= 1.0

        # Efficiency grade
        grade = _efficiency_grade(rev_to_tvl)

        total_daily += daily_fee
        total_annual += annualized

        rows.append({
            "name": name,
            "annualized_revenue_usd": round(annualized, 4),
            "revenue_to_tvl_pct": round(rev_to_tvl, 6),
            "lp_yield_pct": round(lp_yield, 6),
            "protocol_revenue_annual_usd": round(proto_rev_annual, 4),
            "sustainability_ratio": sustainability_ratio,  # may be inf
            "efficiency_grade": grade,
            "is_sustainable": is_sustainable,
        })

    # ---- ranking ----------------------------------------------------------------
    ranking = [r["name"] for r in sorted(rows, key=lambda x: x["revenue_to_tvl_pct"], reverse=True)]

    most_efficient = ranking[0] if ranking else ""
    best_lp_yield = (
        max(rows, key=lambda x: x["lp_yield_pct"])["name"] if rows else ""
    )
    # For sustainability: inf > finite, compare with a key that treats inf as very large
    def _sust_key(r):
        s = r["sustainability_ratio"]
        return s if not math.isinf(s) else float("1e300")

    most_sustainable = (
        max(rows, key=_sust_key)["name"] if rows else ""
    )

    sustainable_count = sum(1 for r in rows if r["is_sustainable"])

    avg_rev_to_tvl = (
        sum(r["revenue_to_tvl_pct"] for r in rows) / len(rows) if rows else 0.0
    )

    return {
        "protocols": rows,
        "ranking": ranking,
        "most_efficient": most_efficient,
        "best_lp_yield": best_lp_yield,
        "most_sustainable": most_sustainable,
        "market_summary": {
            "total_daily_revenue_usd": round(total_daily, 4),
            "total_annualized_revenue_usd": round(total_annual, 4),
            "avg_revenue_to_tvl_pct": round(avg_rev_to_tvl, 6),
            "sustainable_protocol_count": sustainable_count,
        },
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_snapshot(result: dict, log_path: str = None) -> None:
    """Append *result* to the ring-buffer JSON log (max 100 entries, atomic)."""
    path = os.path.abspath(log_path or _DEFAULT_LOG)
    _ensure_dir(path)

    existing = _read_log(path)
    # serialise inf before saving
    snapshot = _sanitise_for_json(result)
    existing.append(snapshot)
    if len(existing) > _LOG_MAX:
        existing = existing[-_LOG_MAX:]
    _atomic_write(path, existing)


def load_log(log_path: str = None) -> list:
    """Return the full ring-buffer log list."""
    path = os.path.abspath(log_path or _DEFAULT_LOG)
    return _read_log(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _efficiency_grade(rev_to_tvl_pct: float) -> str:
    if rev_to_tvl_pct >= _GRADE_A:
        return "A"
    if rev_to_tvl_pct >= _GRADE_B:
        return "B"
    if rev_to_tvl_pct >= _GRADE_C:
        return "C"
    if rev_to_tvl_pct >= _GRADE_D:
        return "D"
    return "F"


def _sanitise_for_json(obj):
    """Recursively replace float('inf') / float('-inf') / nan with string sentinel."""
    if isinstance(obj, dict):
        return {k: _sanitise_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        if math.isnan(obj):
            return "NaN"
    return obj


def _read_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data) -> None:
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample = [
        {
            "name": "Uniswap V3",
            "tvl_usd": 5_000_000_000,
            "daily_fee_revenue_usd": 1_500_000,
            "lp_fee_share_pct": 100.0,
            "protocol_fee_share_pct": 0.0,
            "monthly_expenses_usd": 500_000,
        },
        {
            "name": "Aave",
            "tvl_usd": 10_000_000_000,
            "daily_fee_revenue_usd": 800_000,
            "lp_fee_share_pct": 90.0,
            "protocol_fee_share_pct": 10.0,
            "monthly_expenses_usd": 2_000_000,
        },
        {
            "name": "Curve",
            "tvl_usd": 2_000_000_000,
            "daily_fee_revenue_usd": 200_000,
            "lp_fee_share_pct": 50.0,
            "protocol_fee_share_pct": 50.0,
            "monthly_expenses_usd": 300_000,
        },
    ]

    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    result = analyze(sample)

    if mode == "--run":
        save_snapshot(result)
        print("Snapshot saved.")
    else:
        import json as _json
        print(_json.dumps(_sanitise_for_json(result), indent=2))
