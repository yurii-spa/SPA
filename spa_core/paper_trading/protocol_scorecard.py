#!/usr/bin/env python3
"""Protocol Onboarding Scorecard (SPA-V436 / MP-129) — read-only / advisory.

Evaluates whether a new protocol candidate is ready to onboard into the SPA
portfolio. Produces a structured scorecard with a weighted composite score and
a pass/fail/conditional verdict.

Criteria (configurable via data/onboarding_criteria.json, defaults if absent):
- TVL: minimum $50M, 5× min = full score
- Audit: required by default; top-tier firms score 1.0, unknown firms 0.5
- Age: ≥180 days since launch
- APY premium: ≥50 bps over current T1 average
- Diversification: new protocols score 1.0; existing at cap score 0

Verdict thresholds:
- APPROVED:     composite ≥ 0.70 AND no blocking flags
- CONDITIONAL:  composite ≥ 0.50
- REJECTED:     composite < 0.50 OR blocking flags present when composite < 0.70

Output / persistence
====================
:func:`compute_scorecard` returns a stable-schema dict and NEVER raises.
:func:`save_scorecard` atomically writes
``data/scorecard_{protocol_id}_{date}.json`` (tmp + ``os.replace``).

CLI::

    python3 -m spa_core.paper_trading.protocol_scorecard --check \\
        --protocol aave_v4 --tvl 200000000 --has-audit \\
        --audit-firms "Trail of Bits,OpenZeppelin" \\
        --launch-date 2023-01-01 --protocol-apy 5.5 --t1-avg-apy 4.9

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/ast) — no external
dependencies. Never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.protocol_scorecard")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_CRITERIA_FILE = _DEFAULT_DATA_DIR / "onboarding_criteria.json"

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_scorecard"
DISCLAIMER = "NOT investment advice — read-only advisory module"

# Verdict thresholds
THRESHOLD_APPROVED = 0.70
THRESHOLD_CONDITIONAL = 0.50

# Top-tier audit firms (case-insensitive match)
_TOP_AUDIT_FIRMS = {
    "trail of bits",
    "openzeppelin",
    "consensys",
    "spearbit",
    "certora",
    "mixbytes",
}

_DEFAULT_CRITERIA: Dict[str, Any] = {
    "tvl_min_usd": 50_000_000,
    "audit_required": True,
    "min_age_days": 180,
    "max_protocol_concentration": 0.30,
    "min_apy_premium_bps": 50,
    "weights": {
        "tvl": 0.25,
        "audit": 0.20,
        "age": 0.20,
        "apy_premium": 0.20,
        "diversification": 0.15,
    },
}


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def load_criteria(criteria_file: str = "data/onboarding_criteria.json") -> dict:
    """Load scoring criteria weights and thresholds.

    If the file is missing or unreadable, returns the built-in defaults:
    {
        "tvl_min_usd": 50_000_000,
        "audit_required": True,
        "min_age_days": 180,
        "max_protocol_concentration": 0.30,
        "min_apy_premium_bps": 50,
        "weights": {
            "tvl": 0.25, "audit": 0.20, "age": 0.20,
            "apy_premium": 0.20, "diversification": 0.15
        }
    }
    """
    import copy

    path = Path(criteria_file)
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return copy.deepcopy(_DEFAULT_CRITERIA)

    # Merge: keep defaults for any missing keys
    result = copy.deepcopy(_DEFAULT_CRITERIA)
    for key, val in raw.items():
        if key == "weights" and isinstance(val, dict):
            result["weights"].update(val)
        else:
            result[key] = val
    return result


# ─── Individual scorers ───────────────────────────────────────────────────────


def score_tvl(tvl_usd: float, min_usd: float) -> dict:
    """Score TVL dimension.

    score = min(tvl_usd / (min_usd * 5), 1.0)
    Below min/2 → 0; below min → proportional (0..0.2).

    Returns: {score: float 0..1, details: str}
    """
    if not isinstance(tvl_usd, (int, float)) or not math.isfinite(float(tvl_usd)):
        return {"score": 0.0, "details": "TVL value invalid"}
    if not isinstance(min_usd, (int, float)) or min_usd <= 0 or not math.isfinite(float(min_usd)):
        return {"score": 0.0, "details": "min_usd invalid"}

    tvl_usd = float(tvl_usd)
    min_usd = float(min_usd)

    half_min = min_usd / 2.0
    if tvl_usd < half_min:
        score = 0.0
        details = (
            f"TVL ${tvl_usd:,.0f} is below half of minimum "
            f"(${half_min:,.0f}) — score 0"
        )
    else:
        score = min(tvl_usd / (min_usd * 5.0), 1.0)
        details = (
            f"TVL ${tvl_usd:,.0f} vs min ${min_usd:,.0f} "
            f"(5× target ${min_usd * 5:,.0f}) → score {score:.4f}"
        )
    return {"score": round(score, 6), "details": details}


def score_audit(has_audit: bool, audit_firms: list) -> dict:
    """Score audit dimension.

    No audit → 0.0
    Audit by top firm (Trail of Bits, OpenZeppelin, Consensys, Spearbit,
      Certora, MixBytes) → 1.0
    Audit by unknown firm → 0.5

    Returns: {score: float 0..1, details: str}
    """
    if not has_audit or not audit_firms:
        return {
            "score": 0.0,
            "details": "No security audit — score 0",
        }

    firms_lower = [f.strip().lower() for f in audit_firms if isinstance(f, str)]
    top_matches = [f for f in firms_lower if f in _TOP_AUDIT_FIRMS]

    if top_matches:
        matched = [f for f in audit_firms if isinstance(f, str) and f.strip().lower() in _TOP_AUDIT_FIRMS]
        return {
            "score": 1.0,
            "details": f"Audited by top-tier firm(s): {', '.join(matched)} → score 1.0",
        }
    else:
        return {
            "score": 0.5,
            "details": (
                f"Audited by non-top-tier firm(s): {', '.join(str(f) for f in audit_firms)} "
                f"→ score 0.5"
            ),
        }


def score_age(launch_date: str, min_days: int) -> dict:
    """Score protocol age dimension.

    launch_date: ISO date string YYYY-MM-DD
    score = min(days_since_launch / min_days, 1.0)

    Returns: {score: float 0..1, details: str}
    """
    today = date.today()

    if not isinstance(launch_date, str) or len(launch_date) < 10:
        return {"score": 0.0, "details": f"Invalid launch_date: {launch_date!r}"}

    try:
        ld = date.fromisoformat(launch_date[:10])
    except ValueError:
        return {"score": 0.0, "details": f"Cannot parse launch_date: {launch_date!r}"}

    if not isinstance(min_days, int) or min_days <= 0:
        return {"score": 0.0, "details": f"min_days must be a positive int, got {min_days!r}"}

    days_live = (today - ld).days
    if days_live < 0:
        return {
            "score": 0.0,
            "details": f"launch_date {launch_date} is in the future — score 0",
        }

    score = min(days_live / min_days, 1.0)
    return {
        "score": round(score, 6),
        "details": (
            f"Protocol live {days_live} days vs min {min_days} days "
            f"→ score {score:.4f}"
        ),
    }


def score_apy_premium(
    protocol_apy: float, t1_avg_apy: float, min_premium_bps: int
) -> dict:
    """Score APY premium over T1 benchmark.

    premium_bps = (protocol_apy - t1_avg_apy) * 10000
    score = min(premium_bps / (min_premium_bps * 5), 1.0)
    If premium <= 0 → score = 0

    Returns: {score: float 0..1, details: str}
    """
    if not isinstance(protocol_apy, (int, float)) or not math.isfinite(float(protocol_apy)):
        return {"score": 0.0, "details": "protocol_apy invalid"}
    if not isinstance(t1_avg_apy, (int, float)) or not math.isfinite(float(t1_avg_apy)):
        return {"score": 0.0, "details": "t1_avg_apy invalid"}
    if not isinstance(min_premium_bps, int) or min_premium_bps <= 0:
        return {"score": 0.0, "details": f"min_premium_bps must be positive int, got {min_premium_bps!r}"}

    premium_bps = (float(protocol_apy) - float(t1_avg_apy)) * 10000.0

    if premium_bps <= 0:
        return {
            "score": 0.0,
            "details": (
                f"APY premium {premium_bps:.1f} bps ≤ 0 "
                f"(protocol {protocol_apy:.4f}% vs T1 avg {t1_avg_apy:.4f}%) → score 0"
            ),
        }

    score = min(premium_bps / (min_premium_bps * 5.0), 1.0)
    return {
        "score": round(score, 6),
        "details": (
            f"APY premium {premium_bps:.1f} bps "
            f"(protocol {protocol_apy:.4f}% vs T1 avg {t1_avg_apy:.4f}%) "
            f"vs 5× target {min_premium_bps * 5} bps → score {score:.4f}"
        ),
    }


def score_diversification(protocol_id: str, current_portfolio: dict) -> dict:
    """Score portfolio diversification impact.

    current_portfolio: {protocol_id: allocation_fraction}
    New protocol not in portfolio → score 1.0 (adds diversification).
    Existing protocol at or above 30% concentration cap → score 0.
    Existing protocol below cap → proportional score based on remaining headroom.

    Returns: {score: float 0..1, details: str}
    """
    _CAP = 0.30  # Default concentration cap used in scoring logic

    if not isinstance(current_portfolio, dict):
        return {"score": 1.0, "details": "No portfolio data — assuming new protocol, score 1.0"}

    current_alloc = current_portfolio.get(protocol_id)

    if current_alloc is None:
        return {
            "score": 1.0,
            "details": f"Protocol {protocol_id!r} not in current portfolio — adds diversification, score 1.0",
        }

    # Protocol already in portfolio
    try:
        alloc = float(current_alloc)
    except (TypeError, ValueError):
        return {"score": 0.0, "details": f"Invalid allocation for {protocol_id!r}: {current_alloc!r}"}

    if alloc >= _CAP:
        return {
            "score": 0.0,
            "details": (
                f"Protocol {protocol_id!r} already at {alloc:.1%} "
                f"(≥ {_CAP:.0%} cap) — no room, score 0"
            ),
        }

    # Below cap: score proportional to remaining headroom
    headroom = (_CAP - alloc) / _CAP
    return {
        "score": round(headroom, 6),
        "details": (
            f"Protocol {protocol_id!r} at {alloc:.1%} in portfolio; "
            f"headroom to {_CAP:.0%} cap = {headroom:.1%} → score {headroom:.4f}"
        ),
    }


# ─── Composite scorecard ─────────────────────────────────────────────────────


def compute_scorecard(
    protocol_id: str,
    tvl_usd: float,
    has_audit: bool,
    audit_firms: list,
    launch_date: str,
    protocol_apy: float,
    t1_avg_apy: float,
    current_portfolio: dict,
    criteria: Optional[dict] = None,
) -> dict:
    """Run all scorers, apply weights, return full scorecard.

    Returns:
    {
        protocol_id: str,
        timestamp: str,
        composite_score: float,        # 0..1 weighted sum
        verdict: str,                  # "APPROVED" | "CONDITIONAL" | "REJECTED"
        threshold: {approved: 0.7, conditional: 0.5},
        breakdown: {
            tvl: {score, weight, weighted, details},
            audit: {score, weight, weighted, details},
            age: {score, weight, weighted, details},
            apy_premium: {score, weight, weighted, details},
            diversification: {score, weight, weighted, details}
        },
        blocking_flags: [str],
        recommendation: str
    }
    """
    if criteria is None:
        criteria = load_criteria()

    weights = criteria.get("weights", _DEFAULT_CRITERIA["weights"])
    tvl_min = criteria.get("tvl_min_usd", _DEFAULT_CRITERIA["tvl_min_usd"])
    audit_required = criteria.get("audit_required", _DEFAULT_CRITERIA["audit_required"])
    min_age = criteria.get("min_age_days", _DEFAULT_CRITERIA["min_age_days"])
    min_premium_bps = criteria.get("min_apy_premium_bps", _DEFAULT_CRITERIA["min_apy_premium_bps"])

    # Run each scorer
    r_tvl = score_tvl(tvl_usd, tvl_min)
    r_audit = score_audit(has_audit, audit_firms)
    r_age = score_age(launch_date, min_age)
    r_apy = score_apy_premium(protocol_apy, t1_avg_apy, min_premium_bps)
    r_div = score_diversification(protocol_id, current_portfolio)

    w_tvl = float(weights.get("tvl", 0.25))
    w_audit = float(weights.get("audit", 0.20))
    w_age = float(weights.get("age", 0.20))
    w_apy = float(weights.get("apy_premium", 0.20))
    w_div = float(weights.get("diversification", 0.15))

    breakdown = {
        "tvl": {
            "score": r_tvl["score"],
            "weight": w_tvl,
            "weighted": round(r_tvl["score"] * w_tvl, 6),
            "details": r_tvl["details"],
        },
        "audit": {
            "score": r_audit["score"],
            "weight": w_audit,
            "weighted": round(r_audit["score"] * w_audit, 6),
            "details": r_audit["details"],
        },
        "age": {
            "score": r_age["score"],
            "weight": w_age,
            "weighted": round(r_age["score"] * w_age, 6),
            "details": r_age["details"],
        },
        "apy_premium": {
            "score": r_apy["score"],
            "weight": w_apy,
            "weighted": round(r_apy["score"] * w_apy, 6),
            "details": r_apy["details"],
        },
        "diversification": {
            "score": r_div["score"],
            "weight": w_div,
            "weighted": round(r_div["score"] * w_div, 6),
            "details": r_div["details"],
        },
    }

    composite = sum(v["weighted"] for v in breakdown.values())
    composite = round(composite, 6)

    # Blocking flags
    blocking_flags: List[str] = []
    if audit_required and not has_audit:
        blocking_flags.append("NO_AUDIT")

    # Verdict
    if composite >= THRESHOLD_APPROVED and not blocking_flags:
        verdict = "APPROVED"
        recommendation = (
            f"Protocol {protocol_id!r} meets all quantitative criteria "
            f"(composite score {composite:.3f} ≥ {THRESHOLD_APPROVED}) "
            f"with no blocking flags. Recommend adding to candidate pool "
            f"for manual Owner review per ADR-002 before any allocation."
        )
    elif composite >= THRESHOLD_CONDITIONAL and not blocking_flags:
        verdict = "CONDITIONAL"
        recommendation = (
            f"Protocol {protocol_id!r} meets the conditional threshold "
            f"(composite score {composite:.3f} ≥ {THRESHOLD_CONDITIONAL}) "
            f"but falls short of full approval (< {THRESHOLD_APPROVED}). "
            f"Consider re-evaluating after improving weak criteria "
            f"(see breakdown above). No blocking flags."
        )
    elif composite >= THRESHOLD_CONDITIONAL and blocking_flags:
        # Composite ok but blocked
        verdict = "REJECTED"
        flags_str = ", ".join(blocking_flags)
        recommendation = (
            f"Protocol {protocol_id!r} has composite score {composite:.3f} "
            f"but is REJECTED due to blocking flag(s): [{flags_str}]. "
            f"Resolve all blocking flags before re-evaluating."
        )
    else:
        verdict = "REJECTED"
        flags_str = ", ".join(blocking_flags) if blocking_flags else "none"
        recommendation = (
            f"Protocol {protocol_id!r} is REJECTED — composite score "
            f"{composite:.3f} is below the conditional threshold "
            f"({THRESHOLD_CONDITIONAL}). Blocking flags: [{flags_str}]. "
            f"Significant improvement required before re-evaluation."
        )

    return {
        "protocol_id": protocol_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "composite_score": composite,
        "verdict": verdict,
        "threshold": {
            "approved": THRESHOLD_APPROVED,
            "conditional": THRESHOLD_CONDITIONAL,
        },
        "breakdown": breakdown,
        "blocking_flags": blocking_flags,
        "recommendation": recommendation,
    }


# ─── Persist ──────────────────────────────────────────────────────────────────


def save_scorecard(scorecard: dict, data_dir: str = "data") -> str:
    """Atomic write to data/scorecard_{protocol_id}_{date}.json.

    Returns absolute output path.
    """
    ddir = Path(data_dir)
    protocol_id = str(scorecard.get("protocol_id", "unknown"))
    # Sanitize protocol_id for filesystem
    safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in protocol_id)
    today_str = date.today().isoformat()
    filename = f"scorecard_{safe_id}_{today_str}.json"
    out_path = ddir / filename
    _atomic_write_json(out_path, scorecard)
    log.info("scorecard written: %s", out_path)
    return str(out_path.resolve())


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.protocol_scorecard",
        description=(
            "Protocol Onboarding Scorecard (SPA-V436 / MP-129): "
            "read-only / advisory scorecard for evaluating protocol candidates. Offline."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="compute and print JSON scorecard WITHOUT writing (default)")
    group.add_argument("--run", action="store_true",
                       help="compute and atomically write scorecard to data/")
    p.add_argument("--data-dir", default=None, help="override data directory")
    p.add_argument("--protocol", required=False, default="test_protocol",
                   help="protocol ID to evaluate")
    p.add_argument("--tvl", type=float, default=100_000_000, help="TVL in USD")
    p.add_argument("--has-audit", action="store_true", help="protocol has an audit")
    p.add_argument("--audit-firms", default="",
                   help="comma-separated audit firm names")
    p.add_argument("--launch-date", default="2023-01-01",
                   help="protocol launch date YYYY-MM-DD")
    p.add_argument("--protocol-apy", type=float, default=5.0,
                   help="protocol current APY (%%)")
    p.add_argument("--t1-avg-apy", type=float, default=4.5,
                   help="T1 average APY benchmark (%%)")
    p.add_argument("--criteria-file", default=None,
                   help="path to criteria JSON (default: data/onboarding_criteria.json)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR] --protocol ID",
                file=sys.stderr,
            )
        return 0

    try:
        ddir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
        criteria_file = args.criteria_file if args.criteria_file else str(ddir / "onboarding_criteria.json")
        criteria = load_criteria(criteria_file)

        audit_firms = [f.strip() for f in args.audit_firms.split(",") if f.strip()] if args.audit_firms else []

        scorecard = compute_scorecard(
            protocol_id=args.protocol,
            tvl_usd=args.tvl,
            has_audit=args.has_audit,
            audit_firms=audit_firms,
            launch_date=args.launch_date,
            protocol_apy=args.protocol_apy,
            t1_avg_apy=args.t1_avg_apy,
            current_portfolio={},
            criteria=criteria,
        )

        if args.run:
            out_path = save_scorecard(scorecard, data_dir=str(ddir))
            print(
                f"protocol_scorecard: {scorecard['protocol_id']} "
                f"verdict={scorecard['verdict']} "
                f"composite={scorecard['composite_score']:.4f} "
                f"written → {out_path}"
            )
        else:
            print(json.dumps(scorecard, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            f"protocol_scorecard: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
