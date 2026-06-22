"""
YieldSustainabilityIndex (SPA-V596 / MP-719) — advisory / read-only.

Computes a composite sustainability score (0–100) for DeFi yield opportunities
by combining real yield quality, protocol maturity, security history, and
TVL stability.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/sustainability_index_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

CLI
---
  python3 -m spa_core.analytics.yield_sustainability_index --check
  python3 -m spa_core.analytics.yield_sustainability_index --run
  python3 -m spa_core.analytics.yield_sustainability_index --run --data-dir PATH
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "sustainability_index_log.json"
_RING_BUFFER_MAX = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SustainabilityFactors:
    # Real yield (0–25 points)
    real_yield_ratio: float         # 0.0–1.0 (from RealYieldExtractor)

    # Protocol maturity (0–25 points)
    protocol_age_months: int        # months since launch
    audit_count: int                # number of security audits
    bug_bounty_usd: float           # size of bug bounty program (0 if none)

    # Security (0–25 points)
    hack_history: bool              # True if protocol was ever exploited
    hack_loss_pct: float            # % of TVL lost in worst hack (0 if no history)
    admin_key_risk: bool            # True if protocol has unrestricted admin key

    # TVL stability (0–25 points)
    tvl_30d_change_pct: float       # % TVL change over 30 days
    tvl_90d_change_pct: float       # % TVL change over 90 days
    tvl_usd: float                  # current TVL


@dataclass
class SustainabilityReport:
    protocol: str
    pool: str
    factors: SustainabilityFactors

    # Sub-scores (0–25 each)
    real_yield_score: float
    maturity_score: float
    security_score: float
    tvl_stability_score: float

    # Total (0–100)
    sustainability_index: float

    # Grade
    grade: str       # "A" (>=80) | "B" (60-79) | "C" (40-59) | "D" (<40)
    label: str       # "HIGHLY_SUSTAINABLE" | "SUSTAINABLE" | "MODERATE_RISK" | "HIGH_RISK"

    key_strengths: List[str]     # top 2 sub-scores described
    key_risks: List[str]         # lowest 2 sub-scores described

    invest_confidence: str   # "HIGH" | "MEDIUM" | "LOW" | "AVOID"
    warnings: List[str]
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_real_yield(real_yield_ratio: float) -> float:
    """
    Score real yield quality (0–25 points).
    ratio >= 0.8 → 25; >= 0.6 → 20; >= 0.4 → 14; >= 0.2 → 8; else 2
    """
    if real_yield_ratio >= 0.8:
        return 25.0
    elif real_yield_ratio >= 0.6:
        return 20.0
    elif real_yield_ratio >= 0.4:
        return 14.0
    elif real_yield_ratio >= 0.2:
        return 8.0
    else:
        return 2.0


def score_maturity(
    age_months: int,
    audit_count: int,
    bug_bounty_usd: float,
) -> float:
    """
    Score protocol maturity (0–25 points).
    age:        >= 24 → 10; >= 12 → 7; >= 6 → 4; else 1
    audits:     >= 3 → 10; >= 2 → 7; >= 1 → 4; else 0
    bug_bounty: >= 1_000_000 → 5; >= 100_000 → 3; > 0 → 1; else 0
    return min(25, sum)
    """
    if age_months >= 24:
        age_score = 10
    elif age_months >= 12:
        age_score = 7
    elif age_months >= 6:
        age_score = 4
    else:
        age_score = 1

    if audit_count >= 3:
        audit_score = 10
    elif audit_count >= 2:
        audit_score = 7
    elif audit_count >= 1:
        audit_score = 4
    else:
        audit_score = 0

    if bug_bounty_usd >= 1_000_000:
        bounty_score = 5
    elif bug_bounty_usd >= 100_000:
        bounty_score = 3
    elif bug_bounty_usd > 0:
        bounty_score = 1
    else:
        bounty_score = 0

    return min(25.0, float(age_score + audit_score + bounty_score))


def score_security(
    hack_history: bool,
    hack_loss_pct: float,
    admin_key_risk: bool,
) -> float:
    """
    Score security record (0–25 points).
    base = 25
    if hack_history: base -= min(20, hack_loss_pct * 2)
    if admin_key_risk: base -= 5
    return max(0, base)
    """
    base = 25.0
    if hack_history:
        base -= min(20.0, hack_loss_pct * 2.0)
    if admin_key_risk:
        base -= 5.0
    return max(0.0, base)


def score_tvl_stability(
    tvl_30d_change_pct: float,
    tvl_90d_change_pct: float,
    tvl_usd: float,
) -> float:
    """
    Score TVL stability (0–25 points).
    tvl_size:    >= 1B → 8; >= 100M → 6; >= 10M → 4; else 1
    stability_30d: |30d| < 5 → 10; < 15 → 7; < 30 → 4; else 1
    stability_90d: |90d| < 10 → 7; < 25 → 5; < 50 → 2; else 0
    return min(25, sum)
    """
    if tvl_usd >= 1_000_000_000:
        tvl_size = 8
    elif tvl_usd >= 100_000_000:
        tvl_size = 6
    elif tvl_usd >= 10_000_000:
        tvl_size = 4
    else:
        tvl_size = 1

    abs_30d = abs(tvl_30d_change_pct)
    if abs_30d < 5.0:
        stability_30d = 10
    elif abs_30d < 15.0:
        stability_30d = 7
    elif abs_30d < 30.0:
        stability_30d = 4
    else:
        stability_30d = 1

    abs_90d = abs(tvl_90d_change_pct)
    if abs_90d < 10.0:
        stability_90d = 7
    elif abs_90d < 25.0:
        stability_90d = 5
    elif abs_90d < 50.0:
        stability_90d = 2
    else:
        stability_90d = 0

    return min(25.0, float(tvl_size + stability_30d + stability_90d))


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

_SCORE_NAMES = ["real_yield_score", "maturity_score", "security_score", "tvl_stability_score"]
_SCORE_DESCRIPTIONS = {
    "real_yield_score": "real yield quality",
    "maturity_score": "protocol maturity",
    "security_score": "security record",
    "tvl_stability_score": "TVL stability",
}


def compute(
    protocol: str,
    pool: str,
    factors: SustainabilityFactors,
) -> SustainabilityReport:
    """
    Compute a full SustainabilityReport for a protocol/pool combination.
    """
    ry_score = score_real_yield(factors.real_yield_ratio)
    mat_score = score_maturity(
        factors.protocol_age_months, factors.audit_count, factors.bug_bounty_usd
    )
    sec_score = score_security(
        factors.hack_history, factors.hack_loss_pct, factors.admin_key_risk
    )
    tvl_score = score_tvl_stability(
        factors.tvl_30d_change_pct, factors.tvl_90d_change_pct, factors.tvl_usd
    )

    sustainability_index = ry_score + mat_score + sec_score + tvl_score

    # Grade & label
    if sustainability_index >= 80.0:
        grade = "A"
        label = "HIGHLY_SUSTAINABLE"
        invest_confidence = "HIGH"
    elif sustainability_index >= 60.0:
        grade = "B"
        label = "SUSTAINABLE"
        invest_confidence = "MEDIUM"
    elif sustainability_index >= 40.0:
        grade = "C"
        label = "MODERATE_RISK"
        invest_confidence = "LOW"
    else:
        grade = "D"
        label = "HIGH_RISK"
        invest_confidence = "AVOID"

    # Key strengths / risks (by sub-score value)
    subscores: List[Tuple[float, str]] = [
        (ry_score, "real_yield_score"),
        (mat_score, "maturity_score"),
        (sec_score, "security_score"),
        (tvl_score, "tvl_stability_score"),
    ]
    sorted_scores = sorted(subscores, key=lambda x: x[0], reverse=True)

    key_strengths = [
        f"strong {_SCORE_DESCRIPTIONS[name]} ({score:.0f}/25)"
        for score, name in sorted_scores[:2]
    ]
    key_risks = [
        f"weak {_SCORE_DESCRIPTIONS[name]} ({score:.0f}/25)"
        for score, name in sorted_scores[-2:]
    ]

    # Warnings
    warnings: List[str] = []
    if factors.hack_history:
        warnings.append("protocol was exploited")
    if factors.admin_key_risk:
        warnings.append("admin key risk")
    if factors.real_yield_ratio < 0.2:
        warnings.append("low real yield")

    return SustainabilityReport(
        protocol=protocol,
        pool=pool,
        factors=factors,
        real_yield_score=ry_score,
        maturity_score=mat_score,
        security_score=sec_score,
        tvl_stability_score=tvl_score,
        sustainability_index=sustainability_index,
        grade=grade,
        label=label,
        key_strengths=key_strengths,
        key_risks=key_risks,
        invest_confidence=invest_confidence,
        warnings=warnings,
    )


def rank_protocols(reports: List[SustainabilityReport]) -> List[SustainabilityReport]:
    """Return reports sorted by sustainability_index descending."""
    return sorted(reports, key=lambda r: r.sustainability_index, reverse=True)


# ---------------------------------------------------------------------------
# Persistence (ring-buffer, atomic write)
# ---------------------------------------------------------------------------

def _log_path(data_dir: Optional[Path] = None) -> Path:
    base = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
    return Path(base) / _LOG_FILENAME


def _report_to_dict(report: SustainabilityReport) -> dict:
    """Convert SustainabilityReport to a JSON-serialisable dict."""
    d = asdict(report)
    return d


def save_results(
    report: SustainabilityReport,
    data_dir: Optional[Path] = None,
) -> str:
    """
    Append report to the ring-buffer log (max 100 entries).
    Returns the path written to.
    """
    path = _log_path(data_dir)

    # Load existing
    existing: list = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    # Append new entry
    entry = _report_to_dict(report)
    entry["_saved_at"] = datetime.now(timezone.utc).isoformat()
    existing.append(entry)

    # Trim to ring-buffer cap
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    # Atomic write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(existing, str(path))
    report.saved_to = str(path)
    return str(path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load all persisted sustainability records."""
    path = _log_path(data_dir)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report: SustainabilityReport) -> None:
    print("\n=== YieldSustainabilityIndex ===")
    print(f"  Protocol  : {report.protocol} / {report.pool}")
    print(f"  Index     : {report.sustainability_index:.1f}/100  [{report.grade}] — {report.label}")
    print(f"  Confidence: {report.invest_confidence}")
    print("  Sub-scores:")
    print(f"    Real yield   : {report.real_yield_score:.0f}/25")
    print(f"    Maturity     : {report.maturity_score:.0f}/25")
    print(f"    Security     : {report.security_score:.0f}/25")
    print(f"    TVL stability: {report.tvl_stability_score:.0f}/25")
    print(f"  Strengths : {'; '.join(report.key_strengths)}")
    print(f"  Risks     : {'; '.join(report.key_risks)}")
    if report.warnings:
        print(f"  ⚠  Warnings: {'; '.join(report.warnings)}")
    print()


def _demo_factors() -> SustainabilityFactors:
    return SustainabilityFactors(
        real_yield_ratio=0.75,
        protocol_age_months=30,
        audit_count=3,
        bug_bounty_usd=1_500_000.0,
        hack_history=False,
        hack_loss_pct=0.0,
        admin_key_risk=False,
        tvl_30d_change_pct=3.0,
        tvl_90d_change_pct=8.0,
        tvl_usd=500_000_000.0,
    )


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="YieldSustainabilityIndex (MP-719)")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute, print, and save")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else None

    history = load_history(data_dir)
    if history:
        print(f"Loaded {len(history)} historical sustainability records.")
    else:
        print("No history found — generating demo report.")
        factors = _demo_factors()
        report = compute("Aave V3", "USDC", factors)
        _print_report(report)
        if args.run:
            path = save_results(report, data_dir)
            print(f"Saved to: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
