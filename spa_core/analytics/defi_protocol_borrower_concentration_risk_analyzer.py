"""
MP-1107: DeFiProtocolBorrowerConcentrationRiskAnalyzer
Analyzes the concentration of borrowing activity across DeFi lending protocols.
High borrower concentration → cascade liquidation risk when top borrowers exit.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "borrower_concentration_log.json"
)
LOG_CAP = 100

# HHI thresholds (mirroring DOJ/FTC standard, scaled to 0–10000)
HHI_COMPETITIVE    = 1500.0
HHI_MODERATE       = 2500.0
# above 2500 → concentrated

# Cascade severity scores based on top-1 concentration
TOP1_CRITICAL = 0.40   # top borrower holds >40% of total borrow → CRITICAL
TOP1_HIGH     = 0.25   # >25% → HIGH
TOP1_MODERATE = 0.15   # >15% → MODERATE

# Score thresholds for overall risk label (0=best, 100=worst)
_RISK_THRESHOLDS: List[Tuple[float, str]] = [
    (80.0, "CRITICAL"),
    (60.0, "HIGH"),
    (40.0, "MODERATE"),
    (0.0,  "LOW"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _hhi(shares: List[float]) -> float:
    """Herfindahl-Hirschman Index from fractional shares (0–1). Result 0–10000."""
    return sum((s * 100.0) ** 2 for s in shares)


def _gini(values: List[float]) -> float:
    """Gini coefficient for a list of non-negative values. Returns 0–1."""
    n = len(values)
    if n == 0:
        return 0.0
    total = sum(values)
    if total == 0:
        return 0.0
    sorted_vals = sorted(values)
    numerator = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_vals))
    return numerator / (n * total)


def _top_n_share(amounts: List[float], n: int) -> float:
    """Fraction of total held by top-n borrowers (0–1)."""
    if not amounts or sum(amounts) == 0:
        return 0.0
    top_n = sorted(amounts, reverse=True)[:n]
    return sum(top_n) / sum(amounts)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _risk_label(score: float) -> str:
    for threshold, label in _RISK_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolBorrowerConcentrationRiskAnalyzer:
    """
    Assesses concentration risk in DeFi lending protocols by examining the
    distribution of borrowing positions.

    Input protocol dict keys:
        name                        : str
        total_borrow_usd            : float    (total outstanding borrows)
        top_borrower_amounts_usd    : List[float] (individual borrow amounts,
                                                   sorted descending preferred)
        protocol_reserve_usd        : float    (safety reserve / insurance fund)
        liquidation_threshold_pct   : float    (LT, e.g. 80 = 80%)
        avg_collateral_ratio        : float    (average CR across borrowers, e.g. 1.5)
        category                    : str      (e.g. "lending", "cdp")

    top_borrower_amounts_usd can be partial (e.g. top-20 borrowers).
    If the sum < total_borrow_usd, the remainder is treated as the long tail.
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
        category = p.get("category", "lending")

        total_borrow = float(p.get("total_borrow_usd", 0.0))
        top_amounts  = [max(0.0, a) for a in p.get("top_borrower_amounts_usd", [])]

        # Construct full distribution (add tail bucket if needed)
        tail = total_borrow - sum(top_amounts)
        if tail > 0:
            distribution = top_amounts + [tail]
        else:
            distribution = top_amounts if top_amounts else [total_borrow]

        shares = (
            [a / total_borrow for a in distribution]
            if total_borrow > 0 else []
        )

        # Concentration metrics
        hhi_val  = _hhi(shares) if shares else 0.0
        gini_val = _gini(top_amounts) if top_amounts else 0.0

        # top-N shares use total_borrow as denominator (not just top-N sum)
        if total_borrow > 0 and top_amounts:
            sorted_top = sorted(top_amounts, reverse=True)
            top1_share = sorted_top[0] / total_borrow
            top3_share = sum(sorted_top[:3]) / total_borrow
            top5_share = sum(sorted_top[:5]) / total_borrow
        else:
            top1_share = top3_share = top5_share = 0.0

        # Cascade risk score (0=none, 100=extreme)
        cascade_score = self._cascade_score(top1_share, top3_share, hhi_val)

        # Reserve coverage
        reserve      = p.get("protocol_reserve_usd", 0.0)
        reserve_ratio = reserve / total_borrow if total_borrow > 0 else 0.0

        # Overall risk score (0–100, higher = worse)
        risk_score = self._risk_score(
            cascade_score, hhi_val, reserve_ratio,
            p.get("avg_collateral_ratio", 1.5),
        )
        label = _risk_label(risk_score)
        flags = self._flags(top1_share, top3_share, hhi_val, reserve_ratio,
                             risk_score, total_borrow, p)

        return {
            "name":                name,
            "category":            category,
            "total_borrow_usd":    round(total_borrow, 2),
            "hhi":                 round(hhi_val, 1),
            "gini":                round(gini_val, 4),
            "top1_share_pct":      round(top1_share * 100, 2),
            "top3_share_pct":      round(top3_share * 100, 2),
            "top5_share_pct":      round(top5_share * 100, 2),
            "cascade_risk_score":  round(cascade_score, 2),
            "reserve_coverage_ratio": round(reserve_ratio, 4),
            "overall_risk_score":  round(risk_score, 2),
            "risk_label":          label,
            "flags":               flags,
        }

    # ── scoring helpers ───────────────────────────────────────────────────────

    def _cascade_score(
        self, top1: float, top3: float, hhi: float
    ) -> float:
        """Cascade risk 0–100 from top-borrower metrics."""
        # Top-1 component
        if top1 >= TOP1_CRITICAL:
            c1 = 100.0
        elif top1 >= TOP1_HIGH:
            c1 = 70.0 + (top1 - TOP1_HIGH) / (TOP1_CRITICAL - TOP1_HIGH) * 30.0
        elif top1 >= TOP1_MODERATE:
            c1 = 40.0 + (top1 - TOP1_MODERATE) / (TOP1_HIGH - TOP1_MODERATE) * 30.0
        else:
            c1 = top1 / TOP1_MODERATE * 40.0

        # Top-3 component
        c3 = _clamp(top3 * 100.0 * 1.2, 0.0, 100.0)

        # HHI component
        c_hhi = _clamp((hhi - HHI_COMPETITIVE) / (10000.0 - HHI_COMPETITIVE) * 100.0, 0.0, 100.0)

        return _clamp(0.5 * c1 + 0.3 * c3 + 0.2 * c_hhi, 0.0, 100.0)

    def _risk_score(
        self,
        cascade: float,
        hhi: float,
        reserve_ratio: float,
        avg_cr: float,
    ) -> float:
        """Composite risk score 0–100 (higher = more risk)."""
        # HHI sub-score
        if hhi >= HHI_MODERATE:
            hhi_score = _clamp((hhi - HHI_MODERATE) / (10000 - HHI_MODERATE) * 100, 0, 100)
        else:
            hhi_score = _clamp(hhi / HHI_MODERATE * 60, 0, 100)

        # Reserve penalty: low reserve → higher risk
        # Full coverage ratio ≥0.10 (10%) → 0 penalty; 0% → 30 pts penalty
        reserve_penalty = _clamp((0.10 - reserve_ratio) / 0.10 * 30.0, 0.0, 30.0)

        # Collateral ratio bonus: avg_cr ≥ 2.0 → no add; 1.0 → +20 pts
        cr_penalty = _clamp((2.0 - avg_cr) / 1.0 * 20.0, 0.0, 20.0)

        raw = 0.55 * cascade + 0.20 * hhi_score + reserve_penalty + cr_penalty
        return _clamp(raw, 0.0, 100.0)

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self,
        top1: float,
        top3: float,
        hhi: float,
        reserve_ratio: float,
        risk_score: float,
        total_borrow: float,
        p: dict,
    ) -> List[str]:
        flags: List[str] = []

        if top1 >= TOP1_CRITICAL:
            flags.append("TOP1_BORROWER_CRITICAL")
        elif top1 >= TOP1_HIGH:
            flags.append("TOP1_BORROWER_HIGH")

        if top3 >= 0.60:
            flags.append("TOP3_EXCEED_60PCT")

        if hhi >= HHI_MODERATE:
            flags.append("HHI_CONCENTRATED")
        elif hhi >= HHI_COMPETITIVE:
            flags.append("HHI_MODERATE")

        if reserve_ratio < 0.02:
            flags.append("LOW_RESERVE_COVERAGE")

        if risk_score >= 80.0:
            flags.append("CRITICAL_CASCADE_RISK")

        # Large borrow + concentrated
        if total_borrow >= 100_000_000 and risk_score >= 60.0:
            flags.append("LARGE_MARKET_HIGH_RISK")

        avg_cr = p.get("avg_collateral_ratio", 1.5)
        if avg_cr < 1.2:
            flags.append("LOW_COLLATERAL_RATIO")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        if not results:
            return {
                "riskiest_protocol": None,
                "safest_protocol": None,
                "avg_hhi": 0.0,
                "avg_risk_score": 0.0,
                "critical_count": 0,
                "total_at_risk_borrow_usd": 0.0,
            }

        by_risk = sorted(results, key=lambda r: r["overall_risk_score"], reverse=True)
        avg_hhi  = sum(r["hhi"] for r in results) / len(results)
        avg_risk = sum(r["overall_risk_score"] for r in results) / len(results)
        total_at_risk = sum(
            r["total_borrow_usd"]
            for r in results
            if r["risk_label"] in ("CRITICAL", "HIGH")
        )

        return {
            "riskiest_protocol":       by_risk[0]["name"] if by_risk else None,
            "safest_protocol":         by_risk[-1]["name"] if by_risk else None,
            "avg_hhi":                 round(avg_hhi, 1),
            "avg_risk_score":          round(avg_risk, 2),
            "critical_count":          sum(1 for r in results if r["risk_label"] == "CRITICAL"),
            "total_at_risk_borrow_usd": float(round(total_at_risk, 2)),
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
                    "name":        r["name"],
                    "hhi":         r["hhi"],
                    "top1_share_pct": r["top1_share_pct"],
                    "risk_label":  r["risk_label"],
                    "risk_score":  r["overall_risk_score"],
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
            "total_borrow_usd": 8_000_000_000,
            "top_borrower_amounts_usd": [
                400_000_000, 200_000_000, 150_000_000,
                100_000_000, 80_000_000,
            ],
            "protocol_reserve_usd": 200_000_000,
            "liquidation_threshold_pct": 80.0,
            "avg_collateral_ratio": 1.8,
        },
        {
            "name": "SmallLender",
            "category": "lending",
            "total_borrow_usd": 50_000_000,
            "top_borrower_amounts_usd": [
                25_000_000, 15_000_000, 5_000_000,
            ],
            "protocol_reserve_usd": 500_000,
            "liquidation_threshold_pct": 75.0,
            "avg_collateral_ratio": 1.3,
        },
    ]


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="MP-1107 Borrower Concentration Risk Analyzer")
    parser.add_argument("--run",   action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolBorrowerConcentrationRiskAnalyzer()
    result = analyzer.analyze(_demo_protocols(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
