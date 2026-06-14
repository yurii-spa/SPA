"""
MP-1108: DeFiProtocolInsuranceFundAdequacyAnalyzer
Evaluates whether a DeFi protocol's insurance / safety reserve fund is adequate
to absorb expected loss scenarios. Computes coverage ratios, stress-test
scenarios, and a graded adequacy score. Pure stdlib, read-only/advisory,
atomic ring-buffer log.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "insurance_fund_adequacy_log.json"
)
LOG_CAP = 100

# Adequacy score thresholds (0–100; higher = better)
_ADEQUACY_THRESHOLDS: List[Tuple[float, str]] = [
    (85.0, "WELL_CAPITALIZED"),
    (65.0, "ADEQUATE"),
    (40.0, "UNDERCAPITALIZED"),
    (0.0,  "CRITICALLY_UNDERCAPITALIZED"),
]

# Stress scenario severity multipliers on base loss estimate
STRESS_MILD     = 1.0
STRESS_MODERATE = 2.5
STRESS_SEVERE   = 5.0
STRESS_EXTREME  = 10.0

# Minimum recommended coverage ratio (fund / tvl)
MIN_COVERAGE_RATIO = 0.02       # 2% of TVL
TARGET_COVERAGE_RATIO = 0.05    # 5% of TVL (fully adequate)


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _coverage_ratio(fund: float, tvl: float) -> float:
    if tvl <= 0:
        return 0.0
    return fund / tvl


def _adequacy_label(score: float) -> str:
    for threshold, label in _ADEQUACY_THRESHOLDS:
        if score >= threshold:
            return label
    return "CRITICALLY_UNDERCAPITALIZED"


def _stress_coverage(fund: float, base_loss: float, multiplier: float) -> float:
    """Return fraction of stressed loss covered by fund (0–1, can exceed 1)."""
    stressed = base_loss * multiplier
    if stressed <= 0:
        return 1.0
    return min(fund / stressed, 2.0)   # cap at 2× (over-covered)


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolInsuranceFundAdequacyAnalyzer:
    """
    Scores DeFi protocol insurance / safety reserve fund adequacy.

    Input protocol dict keys:
        name                    : str
        category                : str   ("lending", "dex", "yield_aggregator", …)
        tvl_usd                 : float (total value locked)
        insurance_fund_usd      : float (protocol-owned safety reserve)
        external_coverage_usd   : float (e.g. Nexus Mutual cover bought; optional)
        historical_bad_debt_usd : float (total documented bad debt events; optional)
        largest_single_loss_usd : float (largest past loss event; optional)
        num_audit_reports       : int   (security audits completed)
        bug_bounty_usd          : float (max bug bounty payout)
        annual_revenue_usd      : float (used to assess replenishment speed)
        total_borrow_usd        : float (optional, for lending; affects base loss)
    """

    def analyze(
        self,
        protocols: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._score_protocol(p) for p in protocols]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"protocols": results, "aggregate": agg}

    # ── per-protocol ──────────────────────────────────────────────────────────

    def _score_protocol(self, p: dict) -> dict:
        name     = p.get("name", "unknown")
        category = p.get("category", "unknown")

        tvl          = float(p.get("tvl_usd", 0.0))
        fund         = float(p.get("insurance_fund_usd", 0.0))
        ext_cover    = float(p.get("external_coverage_usd", 0.0))
        total_cover  = fund + ext_cover

        base_loss = self._base_loss_estimate(p, tvl)

        # Coverage ratios
        fund_ratio  = _coverage_ratio(fund, tvl)
        total_ratio = _coverage_ratio(total_cover, tvl)

        # Stress scenarios
        stress = {
            "mild":     _stress_coverage(total_cover, base_loss, STRESS_MILD),
            "moderate": _stress_coverage(total_cover, base_loss, STRESS_MODERATE),
            "severe":   _stress_coverage(total_cover, base_loss, STRESS_SEVERE),
            "extreme":  _stress_coverage(total_cover, base_loss, STRESS_EXTREME),
        }

        # Replenishment score (how quickly can fund be rebuilt from revenue)
        replenish_score = self._replenishment_score(
            fund, float(p.get("annual_revenue_usd", 0.0))
        )

        # Security posture bonus
        security_score = self._security_score(
            int(p.get("num_audit_reports", 0)),
            float(p.get("bug_bounty_usd", 0.0)),
        )

        # Composite adequacy score
        adequacy_score = self._compute_adequacy(
            fund_ratio, total_ratio, stress, replenish_score, security_score
        )
        label = _adequacy_label(adequacy_score)
        flags = self._flags(
            fund_ratio, total_ratio, stress, adequacy_score, p, tvl
        )

        # Months to deplete fund (at historical bad debt rate)
        months_runway = self._fund_runway_months(
            fund, float(p.get("historical_bad_debt_usd", 0.0))
        )

        return {
            "name":                   name,
            "category":               category,
            "tvl_usd":                round(tvl, 2),
            "insurance_fund_usd":     round(fund, 2),
            "total_coverage_usd":     round(total_cover, 2),
            "fund_to_tvl_ratio":      round(fund_ratio, 6),
            "total_coverage_ratio":   round(total_ratio, 6),
            "base_loss_estimate_usd": round(base_loss, 2),
            "stress_coverage": {k: round(v, 4) for k, v in stress.items()},
            "replenishment_score":    round(replenish_score, 2),
            "security_score":         round(security_score, 2),
            "adequacy_score":         round(adequacy_score, 2),
            "adequacy_label":         label,
            "fund_runway_months":     round(months_runway, 1) if months_runway is not None else None,
            "flags":                  flags,
        }

    # ── sub-computations ──────────────────────────────────────────────────────

    def _base_loss_estimate(self, p: dict, tvl: float) -> float:
        """
        Estimate 'base case' loss: 1% of TVL, raised if there's borrow exposure.
        """
        borrow = float(p.get("total_borrow_usd", 0.0))
        bad_debt = float(p.get("historical_bad_debt_usd", 0.0))

        # Use historical bad debt if available; otherwise 1% of TVL or 0.5% of borrows
        if bad_debt > 0:
            return bad_debt

        base = tvl * 0.01
        if borrow > 0:
            base = max(base, borrow * 0.005)
        return base

    def _replenishment_score(self, fund: float, annual_revenue: float) -> float:
        """
        Score 0–100: how quickly protocol can rebuild fund from annual revenue.
        Full score: rebuild ≤ 1 year.  Score 0: no revenue.
        """
        if annual_revenue <= 0:
            return 0.0
        years_to_rebuild = fund / annual_revenue
        if years_to_rebuild <= 0:
            return 100.0
        # Sigmoid-style: 1yr → ~80, 5yr → ~20
        score = 100.0 / (1.0 + years_to_rebuild)
        return _clamp(score * 2, 0.0, 100.0)

    def _security_score(self, num_audits: int, bug_bounty: float) -> float:
        """Score 0–100 reflecting security investment."""
        audit_score  = _clamp(num_audits * 20.0, 0.0, 60.0)
        bounty_score = _clamp(math.log10(bug_bounty + 1) / math.log10(1_000_000) * 40.0, 0.0, 40.0)
        return audit_score + bounty_score

    def _compute_adequacy(
        self,
        fund_ratio: float,
        total_ratio: float,
        stress: Dict[str, float],
        replenish: float,
        security: float,
    ) -> float:
        """Composite score 0–100; higher = better."""
        # Coverage ratio component (0–40 pts)
        if total_ratio >= TARGET_COVERAGE_RATIO:
            coverage_pts = 40.0
        elif total_ratio >= MIN_COVERAGE_RATIO:
            coverage_pts = 20.0 + (total_ratio - MIN_COVERAGE_RATIO) / (TARGET_COVERAGE_RATIO - MIN_COVERAGE_RATIO) * 20.0
        else:
            coverage_pts = _clamp(total_ratio / MIN_COVERAGE_RATIO * 20.0, 0.0, 20.0)

        # Stress survival component (0–30 pts): moderate scenario should be covered
        moderate_ok = stress["moderate"] >= 1.0
        severe_ok   = stress["severe"] >= 1.0
        stress_pts  = (15.0 if moderate_ok else stress["moderate"] * 15.0) + \
                      (15.0 if severe_ok   else stress["severe"]   * 15.0)

        # Replenishment (0–15 pts)
        replenish_pts = replenish * 0.15

        # Security (0–15 pts)
        security_pts = security * 0.15

        return _clamp(coverage_pts + stress_pts + replenish_pts + security_pts, 0.0, 100.0)

    def _fund_runway_months(
        self, fund: float, annual_bad_debt: float
    ) -> Optional[float]:
        """Months fund lasts at historical bad debt rate; None if no history."""
        if annual_bad_debt <= 0:
            return None
        monthly_rate = annual_bad_debt / 12.0
        return fund / monthly_rate

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self,
        fund_ratio: float,
        total_ratio: float,
        stress: Dict[str, float],
        adequacy_score: float,
        p: dict,
        tvl: float,
    ) -> List[str]:
        flags: List[str] = []

        if total_ratio < MIN_COVERAGE_RATIO:
            flags.append("BELOW_MIN_COVERAGE")

        if stress["moderate"] < 1.0:
            flags.append("CANNOT_COVER_MODERATE_STRESS")

        if stress["severe"] < 0.5:
            flags.append("SEVERE_STRESS_HALF_COVERED")

        if adequacy_score < 40.0:
            flags.append("CRITICALLY_UNDERCAPITALIZED")

        # No external cover at all
        if float(p.get("external_coverage_usd", 0.0)) == 0.0:
            flags.append("NO_EXTERNAL_COVER")

        # Large TVL + poor coverage
        if tvl >= 500_000_000 and fund_ratio < MIN_COVERAGE_RATIO:
            flags.append("LARGE_TVL_LOW_COVERAGE")

        # No audits
        if int(p.get("num_audit_reports", 0)) == 0:
            flags.append("NO_SECURITY_AUDITS")

        # Historical losses exceed current fund
        hist = float(p.get("historical_bad_debt_usd", 0.0))
        fund = float(p.get("insurance_fund_usd", 0.0))
        if hist > 0 and fund < hist:
            flags.append("FUND_BELOW_HISTORICAL_LOSSES")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        if not results:
            return {
                "best_capitalized": None,
                "worst_capitalized": None,
                "avg_adequacy_score": 0.0,
                "avg_fund_to_tvl_ratio": 0.0,
                "critically_undercapitalized_count": 0,
                "well_capitalized_count": 0,
                "total_insurance_fund_usd": 0.0,
                "total_tvl_protected_usd": 0.0,
            }

        by_score = sorted(results, key=lambda r: r["adequacy_score"], reverse=True)
        avg_score = sum(r["adequacy_score"] for r in results) / len(results)
        avg_ratio = sum(r["fund_to_tvl_ratio"] for r in results) / len(results)
        total_fund = sum(r["insurance_fund_usd"] for r in results)
        total_tvl  = sum(r["tvl_usd"] for r in results)

        return {
            "best_capitalized":    by_score[0]["name"] if by_score else None,
            "worst_capitalized":   by_score[-1]["name"] if by_score else None,
            "avg_adequacy_score":  round(avg_score, 2),
            "avg_fund_to_tvl_ratio": round(avg_ratio, 6),
            "critically_undercapitalized_count": sum(
                1 for r in results if r["adequacy_label"] == "CRITICALLY_UNDERCAPITALIZED"
            ),
            "well_capitalized_count": sum(
                1 for r in results if r["adequacy_label"] == "WELL_CAPITALIZED"
            ),
            "total_insurance_fund_usd": round(total_fund, 2),
            "total_tvl_protected_usd":  round(total_tvl, 2),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(results),
            "aggregates":     agg,
            "snapshots": [
                {
                    "name":              r["name"],
                    "adequacy_score":    r["adequacy_score"],
                    "adequacy_label":    r["adequacy_label"],
                    "fund_to_tvl_ratio": r["fund_to_tvl_ratio"],
                    "flags":             r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_protocols() -> List[dict]:
    return [
        {
            "name": "Aave V3",
            "category": "lending",
            "tvl_usd": 12_000_000_000,
            "insurance_fund_usd": 300_000_000,
            "external_coverage_usd": 50_000_000,
            "historical_bad_debt_usd": 0.0,
            "num_audit_reports": 8,
            "bug_bounty_usd": 250_000,
            "annual_revenue_usd": 150_000_000,
            "total_borrow_usd": 7_000_000_000,
        },
        {
            "name": "SmallDEX",
            "category": "dex",
            "tvl_usd": 50_000_000,
            "insurance_fund_usd": 100_000,
            "external_coverage_usd": 0.0,
            "historical_bad_debt_usd": 500_000,
            "num_audit_reports": 1,
            "bug_bounty_usd": 10_000,
            "annual_revenue_usd": 2_000_000,
            "total_borrow_usd": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="MP-1108 Insurance Fund Adequacy Analyzer")
    parser.add_argument("--run",   action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolInsuranceFundAdequacyAnalyzer()
    result = analyzer.analyze(_demo_protocols(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
