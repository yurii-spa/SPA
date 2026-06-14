"""
MP-778: ProtocolTVLFilter
=========================
Filters protocols by TVL quality criteria for safe deployment.

Advisory / read-only — never modifies allocator, risk, or execution.
Atomic writes only (tmp + os.replace). Pure stdlib. Exit 0 always.

Data file: data/protocol_tvl_filter_log.json  (ring-buffer, max 100 entries)

CLI:
    python3 -m spa_core.analytics.protocol_tvl_filter --check   # compute + print, no write
    python3 -m spa_core.analytics.protocol_tvl_filter --run     # + atomic write
    python3 -m spa_core.analytics.protocol_tvl_filter --run --data-dir <dir>
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_MIN_TVL_USD: float = 10_000_000.0        # $10M
DEFAULT_MAX_TVL_DROP_7D_PCT: float = -20.0        # -20%
DEFAULT_MAX_TVL_DROP_30D_PCT: float = -40.0       # -40%

LOG_FILENAME = "protocol_tvl_filter_log.json"
LOG_MAX_ENTRIES = 100

# TVL score size component: log10 scale from $1M (score=0) to $10B (score=50)
_TVL_LOG_MIN = 6.0   # log10($1M)
_TVL_LOG_MAX = 10.0  # log10($10B)


# ---------------------------------------------------------------------------
# TVL Quality Score
# ---------------------------------------------------------------------------

def _compute_tvl_quality_score(
    tvl_usd: float,
    tvl_7d_change_pct: float,
    tvl_30d_change_pct: float,
) -> float:
    """Return 0–100 quality score for a protocol based on TVL size + stability.

    Size component (0–50):
        Logarithmic scale from $1M → 0 pts to $10B → 50 pts.

    Stability component (0–50):
        7-day sub-score (0–25): full marks when ≥ 0%, scales to 0 at -20%.
        30-day sub-score (0–25): full marks when ≥ 0%, scales to 0 at -40%.
    """
    # Size score
    if tvl_usd <= 0:
        size_score = 0.0
    else:
        log_tvl = math.log10(tvl_usd)
        size_score = 50.0 * max(0.0, min(1.0, (log_tvl - _TVL_LOG_MIN) / (_TVL_LOG_MAX - _TVL_LOG_MIN)))

    # 7-day stability (0–25)
    if tvl_7d_change_pct >= 0:
        score_7d = 25.0
    else:
        # Linear from 0% → 25 pts to DEFAULT_MAX_TVL_DROP_7D_PCT → 0 pts
        score_7d = max(0.0, 25.0 * (1.0 + tvl_7d_change_pct / abs(DEFAULT_MAX_TVL_DROP_7D_PCT)))

    # 30-day stability (0–25)
    if tvl_30d_change_pct >= 0:
        score_30d = 25.0
    else:
        score_30d = max(0.0, 25.0 * (1.0 + tvl_30d_change_pct / abs(DEFAULT_MAX_TVL_DROP_30D_PCT)))

    total = size_score + score_7d + score_30d
    return round(min(100.0, max(0.0, total)), 2)


# ---------------------------------------------------------------------------
# Default criteria dict
# ---------------------------------------------------------------------------

def _default_criteria() -> Dict[str, float]:
    return {
        "min_tvl_usd": DEFAULT_MIN_TVL_USD,
        "max_tvl_drop_7d_pct": DEFAULT_MAX_TVL_DROP_7D_PCT,
        "max_tvl_drop_30d_pct": DEFAULT_MAX_TVL_DROP_30D_PCT,
    }


# ---------------------------------------------------------------------------
# Core filter function (stateless)
# ---------------------------------------------------------------------------

def filter_protocols(
    protocols: List[Dict[str, Any]],
    criteria: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Filter a list of protocol dicts by TVL quality criteria.

    Parameters
    ----------
    protocols : list of dicts, each with keys:
        protocol            (str)
        tvl_usd             (float)
        tvl_7d_change_pct   (float, e.g. -5.0 means -5%)
        tvl_30d_change_pct  (float)
        chain               (str, optional)
        category            (str, optional)

    criteria : dict (optional), override any default:
        min_tvl_usd             – absolute TVL floor in USD
        max_tvl_drop_7d_pct     – most-negative allowed 7-day change (e.g. -20)
        max_tvl_drop_30d_pct    – most-negative allowed 30-day change (e.g. -40)

    Returns
    -------
    dict with:
        passed_protocols    : list of enriched protocol dicts (+ tvl_quality_score)
        rejected_protocols  : list of enriched protocol dicts (+ rejection_reason)
        pass_rate_pct       : float
        avg_tvl_of_passed   : float (0.0 if none passed)
        criteria_used       : dict
        timestamp_utc       : float (epoch)
        total_evaluated     : int
    """
    c = {**_default_criteria(), **(criteria or {})}
    min_tvl = c["min_tvl_usd"]
    max_drop_7d = c["max_tvl_drop_7d_pct"]
    max_drop_30d = c["max_tvl_drop_30d_pct"]

    passed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for raw in protocols:
        p = dict(raw)
        tvl = float(p.get("tvl_usd", 0.0))
        chg7 = float(p.get("tvl_7d_change_pct", 0.0))
        chg30 = float(p.get("tvl_30d_change_pct", 0.0))

        p["tvl_quality_score"] = _compute_tvl_quality_score(tvl, chg7, chg30)

        reasons: List[str] = []
        if tvl < min_tvl:
            reasons.append(
                f"tvl_usd {tvl:,.0f} < min {min_tvl:,.0f}"
            )
        if chg7 < max_drop_7d:
            reasons.append(
                f"tvl_7d_change_pct {chg7:.1f}% < max_drop {max_drop_7d:.1f}%"
            )
        if chg30 < max_drop_30d:
            reasons.append(
                f"tvl_30d_change_pct {chg30:.1f}% < max_drop {max_drop_30d:.1f}%"
            )

        if reasons:
            p["rejection_reason"] = "; ".join(reasons)
            rejected.append(p)
        else:
            passed.append(p)

    total = len(protocols)
    pass_rate = round(100.0 * len(passed) / total, 2) if total > 0 else 0.0
    avg_tvl = (
        sum(float(p["tvl_usd"]) for p in passed) / len(passed)
        if passed
        else 0.0
    )

    return {
        "passed_protocols": passed,
        "rejected_protocols": rejected,
        "pass_rate_pct": pass_rate,
        "avg_tvl_of_passed": round(avg_tvl, 2),
        "criteria_used": c,
        "timestamp_utc": time.time(),
        "total_evaluated": total,
    }


# ---------------------------------------------------------------------------
# ProtocolTVLFilter class
# ---------------------------------------------------------------------------

class ProtocolTVLFilter:
    """Stateful wrapper around filter_protocols with ring-buffer log persistence.

    Usage
    -----
    f = ProtocolTVLFilter(data_dir="data")
    result = f.filter_protocols(protocols, criteria={"min_tvl_usd": 20_000_000})
    qualified = f.get_qualified_protocols()
    summary = f.get_rejection_summary()
    f.save()   # atomic write to ring-buffer log
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = data_dir
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_protocols(
        self,
        protocols: List[Dict[str, Any]],
        criteria: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Run filter and cache result internally. Returns full result dict."""
        self._last_result = filter_protocols(protocols, criteria)
        return self._last_result

    def get_qualified_protocols(self) -> List[Dict[str, Any]]:
        """Return passed protocols from last filter_protocols() call."""
        if self._last_result is None:
            return []
        return self._last_result.get("passed_protocols", [])

    def get_rejection_summary(self) -> Dict[str, Any]:
        """Return rejection summary from last filter_protocols() call.

        Returns dict with:
            rejected_count      : int
            rejection_reasons   : list of {protocol, rejection_reason}
            pass_rate_pct       : float
        """
        if self._last_result is None:
            return {"rejected_count": 0, "rejection_reasons": [], "pass_rate_pct": 0.0}

        rejected = self._last_result.get("rejected_protocols", [])
        return {
            "rejected_count": len(rejected),
            "rejection_reasons": [
                {
                    "protocol": p.get("protocol", "unknown"),
                    "rejection_reason": p.get("rejection_reason", ""),
                }
                for p in rejected
            ],
            "pass_rate_pct": self._last_result.get("pass_rate_pct", 0.0),
        }

    def save(self) -> str:
        """Atomically append last result to ring-buffer log. Returns log path."""
        if self._last_result is None:
            raise RuntimeError("No filter result to save; call filter_protocols() first.")

        log_path = os.path.join(self._data_dir, LOG_FILENAME)
        log = _load_log(log_path)
        log.append(self._last_result)
        # Trim to ring-buffer cap
        if len(log) > LOG_MAX_ENTRIES:
            log = log[-LOG_MAX_ENTRIES:]
        _atomic_write(log_path, log)
        return log_path

    # ------------------------------------------------------------------
    # Convenience: run + save in one call
    # ------------------------------------------------------------------

    def run_and_save(
        self,
        protocols: List[Dict[str, Any]],
        criteria: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """filter_protocols() + save() combined."""
        result = self.filter_protocols(protocols, criteria)
        self.save()
        return result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_log(path: str) -> List[Any]:
    """Load existing log list from JSON file, or return empty list."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_protocols() -> List[Dict[str, Any]]:
    """Return demo protocols for CLI self-test."""
    return [
        {
            "protocol": "Aave V3",
            "tvl_usd": 8_500_000_000,
            "tvl_7d_change_pct": -1.2,
            "tvl_30d_change_pct": 3.5,
            "chain": "ethereum",
            "category": "lending",
        },
        {
            "protocol": "Compound V3",
            "tvl_usd": 2_100_000_000,
            "tvl_7d_change_pct": 0.8,
            "tvl_30d_change_pct": -5.0,
            "chain": "ethereum",
            "category": "lending",
        },
        {
            "protocol": "TinyPool",
            "tvl_usd": 500_000,
            "tvl_7d_change_pct": -25.0,
            "tvl_30d_change_pct": -50.0,
            "chain": "ethereum",
            "category": "amm",
        },
        {
            "protocol": "SmallDeFi",
            "tvl_usd": 8_000_000,
            "tvl_7d_change_pct": -5.0,
            "tvl_30d_change_pct": -10.0,
            "chain": "polygon",
            "category": "yield",
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: --check (default) or --run [--data-dir DIR]."""
    import argparse

    parser = argparse.ArgumentParser(description="MP-778 ProtocolTVLFilter")
    parser.add_argument("--check", action="store_true", default=False,
                        help="Compute and print result without writing (default)")
    parser.add_argument("--run", action="store_true", default=False,
                        help="Compute + atomically write to ring-buffer log")
    parser.add_argument("--data-dir", default="data",
                        help="Directory for log file (default: data)")
    args = parser.parse_args(argv)

    protocols = _sample_protocols()
    tvl_filter = ProtocolTVLFilter(data_dir=args.data_dir)

    result = tvl_filter.filter_protocols(protocols)

    print(f"[ProtocolTVLFilter] Evaluated {result['total_evaluated']} protocols")
    print(f"  Passed : {len(result['passed_protocols'])} ({result['pass_rate_pct']:.1f}%)")
    print(f"  Rejected: {len(result['rejected_protocols'])}")
    print(f"  Avg TVL of passed: ${result['avg_tvl_of_passed']:,.0f}")
    print()
    for p in result["passed_protocols"]:
        print(f"  ✓ {p['protocol']:30s}  TVL=${p['tvl_usd']:>15,.0f}  score={p['tvl_quality_score']:5.1f}")
    for p in result["rejected_protocols"]:
        print(f"  ✗ {p['protocol']:30s}  reason: {p.get('rejection_reason', '')}")

    if args.run:
        log_path = tvl_filter.save()
        print(f"\n[ProtocolTVLFilter] Log written → {log_path}")
    else:
        print("\n[ProtocolTVLFilter] (--check mode, no write)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
