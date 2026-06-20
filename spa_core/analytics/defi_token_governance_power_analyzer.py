"""
DeFi Token Governance Power Analyzer (MP-885)
==============================================

Analyzes token governance distribution, voting power concentration, and
decentralization quality across DeFi protocols.

Design constraints:
* Pure stdlib only — no numpy/scipy/requests/pandas.
* Atomic writes: tmp + os.replace (POSIX-safe).
* Advisory / read-only analytics — never modifies allocator/risk/execution.
* Deterministic: identical input → identical output.
* Ring-buffer JSON: MAX_ENTRIES = 100.

CLI:
    python3 -m spa_core.analytics.defi_token_governance_power_analyzer --check  (default)
    python3 -m spa_core.analytics.defi_token_governance_power_analyzer --run    (+ atomic save)
    python3 -m spa_core.analytics.defi_token_governance_power_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = _PROJECT_ROOT / "data" / "governance_power_log.json"
MAX_ENTRIES = 100  # ring-buffer size

# Token model bonuses
_TOKEN_MODEL_BONUS: Dict[str, int] = {
    "VOTE_ESCROWED": 15,
    "DELEGATED": 10,
    "DUAL_UTILITY": 5,
    "GOVERNANCE_ONLY": 0,
}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
def _compute_hhi_score(top10_holder_pct: float) -> int:
    """
    Herfindahl approximation for top-10 holders assuming equal shares.
    hhi_score = min(100, int((top10_holder_pct / 10) ** 2 * 10))
    Range: 0 (perfect distribution) to 100 (monopoly).
    """
    raw = (top10_holder_pct / 10.0) ** 2 * 10.0
    return min(100, int(raw))


def _compute_decentralization_score(hhi_score: int, team_treasury_pct: float) -> int:
    """
    100 - hhi_score - team_concentration_penalty
    team_concentration_penalty = min(40, int(team_treasury_pct * 0.8))
    decentralization_score = max(0, 100 - hhi_score - team_concentration_penalty)
    """
    penalty = min(40, int(team_treasury_pct * 0.8))
    return max(0, 100 - hhi_score - penalty)


def _compute_participation_score(avg_voter_turnout_pct: float) -> int:
    """
    0-100: min(100, int(avg_voter_turnout_pct * 5))
    20% turnout → 100 score.
    """
    return min(100, int(avg_voter_turnout_pct * 5))


def _compute_activity_score(proposals_last_90d: int) -> int:
    """0-100: min(100, proposals_last_90d * 10)"""
    return min(100, proposals_last_90d * 10)


def _compute_governance_quality(
    decentralization_score: int, participation_score: int
) -> str:
    """
    "EXCELLENT" if dec>=70 and part>=50
    "GOOD"      if dec>=50 and part>=30
    "MODERATE"  if dec>=30
    "WEAK"      if dec>=15
    "PLUTOCRATIC" otherwise (<15)
    """
    if decentralization_score >= 70 and participation_score >= 50:
        return "EXCELLENT"
    if decentralization_score >= 50 and participation_score >= 30:
        return "GOOD"
    if decentralization_score >= 30:
        return "MODERATE"
    if decentralization_score >= 15:
        return "WEAK"
    return "PLUTOCRATIC"


def _compute_token_model_bonus(token_type: str) -> int:
    """Look up bonus by token_type; unknown types get 0."""
    return _TOKEN_MODEL_BONUS.get(token_type, 0)


def _compute_composite_score(
    decentralization_score: int,
    participation_score: int,
    activity_score: int,
    token_model_bonus: int,
) -> int:
    """
    int(decentralization*0.4 + participation*0.3 + activity*0.2 + token_model_bonus*0.1)
    Clamped to 0-100.
    """
    raw = (
        decentralization_score * 0.4
        + participation_score * 0.3
        + activity_score * 0.2
        + token_model_bonus * 0.1
    )
    return max(0, min(100, int(raw)))


def _compute_flags(
    top10_holder_pct: float,
    team_treasury_pct: float,
    avg_voter_turnout_pct: float,
    proposals_last_90d: int,
) -> List[str]:
    """
    "WHALE_DOMINATED": top10_holder_pct > 50
    "TEAM_HEAVY":      team_treasury_pct > 30
    "LOW_PARTICIPATION": avg_voter_turnout_pct < 5
    "INACTIVE":        proposals_last_90d < 3
    """
    flags: List[str] = []
    if top10_holder_pct > 50:
        flags.append("WHALE_DOMINATED")
    if team_treasury_pct > 30:
        flags.append("TEAM_HEAVY")
    if avg_voter_turnout_pct < 5:
        flags.append("LOW_PARTICIPATION")
    if proposals_last_90d < 3:
        flags.append("INACTIVE")
    return flags


def _build_recommendation(
    governance_quality: str,
    active_voters_30d: int,
    avg_voter_turnout_pct: float,
    proposals_last_90d: int,
    top10_holder_pct: float,
    flags: List[str],
) -> str:
    """Build recommendation string based on governance quality tier."""
    if governance_quality == "EXCELLENT":
        return (
            f"Strong governance. {active_voters_30d} active voters, "
            f"{avg_voter_turnout_pct:.1f}% turnout."
        )
    if governance_quality == "GOOD":
        return f"Solid participation. {proposals_last_90d} proposals in 90 days."
    if governance_quality == "MODERATE":
        concern_str = (
            ", ".join(flags[:2]) if flags else "low engagement"
        )
        return (
            f"Governance functional but {len(flags)} concern(s): {concern_str}."
        )
    # WEAK or PLUTOCRATIC
    return (
        f"Governance at risk. Top 10 holders control {top10_holder_pct:.0f}%."
    )


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze governance power distribution across DeFi protocols.

    protocols: list of {
        "name": str,
        "top10_holder_pct": float,
        "team_treasury_pct": float,
        "circulating_supply_pct": float,
        "active_voters_30d": int,
        "total_token_holders": int,
        "proposals_last_90d": int,
        "avg_voter_turnout_pct": float,
        "token_type": str
    }
    config: dict = None  (reserved for future use)

    Returns: {
        "protocols": list of per-protocol results,
        "most_decentralized": str | None,
        "average_composite_score": float,
        "timestamp": float
    }
    """
    # config is accepted but not used (all defaults are baked in)
    _ = config

    if not protocols:
        return {
            "protocols": [],
            "most_decentralized": None,
            "average_composite_score": 0.0,
            "timestamp": time.time(),
        }

    results = []
    for proto in protocols:
        name = proto.get("name", "")
        top10_holder_pct = float(proto.get("top10_holder_pct", 0.0))
        team_treasury_pct = float(proto.get("team_treasury_pct", 0.0))
        active_voters_30d = int(proto.get("active_voters_30d", 0))
        proposals_last_90d = int(proto.get("proposals_last_90d", 0))
        avg_voter_turnout_pct = float(proto.get("avg_voter_turnout_pct", 0.0))
        token_type = str(proto.get("token_type", "GOVERNANCE_ONLY"))

        hhi_score = _compute_hhi_score(top10_holder_pct)
        decentralization_score = _compute_decentralization_score(
            hhi_score, team_treasury_pct
        )
        participation_score = _compute_participation_score(avg_voter_turnout_pct)
        activity_score = _compute_activity_score(proposals_last_90d)
        governance_quality = _compute_governance_quality(
            decentralization_score, participation_score
        )
        token_model_bonus = _compute_token_model_bonus(token_type)
        composite_score = _compute_composite_score(
            decentralization_score,
            participation_score,
            activity_score,
            token_model_bonus,
        )
        flags = _compute_flags(
            top10_holder_pct,
            team_treasury_pct,
            avg_voter_turnout_pct,
            proposals_last_90d,
        )
        recommendation = _build_recommendation(
            governance_quality,
            active_voters_30d,
            avg_voter_turnout_pct,
            proposals_last_90d,
            top10_holder_pct,
            flags,
        )

        results.append(
            {
                "name": name,
                "hhi_score": hhi_score,
                "decentralization_score": decentralization_score,
                "participation_score": participation_score,
                "activity_score": activity_score,
                "governance_quality": governance_quality,
                "token_model_bonus": token_model_bonus,
                "composite_score": composite_score,
                "flags": flags,
                "recommendation": recommendation,
            }
        )

    # most_decentralized: highest decentralization_score
    most_decentralized: Optional[str] = None
    if results:
        best = max(results, key=lambda r: r["decentralization_score"])
        most_decentralized = best["name"]

    # average_composite_score
    average_composite_score = (
        sum(r["composite_score"] for r in results) / len(results)
        if results
        else 0.0
    )

    return {
        "protocols": results,
        "most_decentralized": most_decentralized,
        "average_composite_score": average_composite_score,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_log(path: Path) -> list:
    """Load existing ring-buffer log or return empty list."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_result(result: dict, path: Path = DATA_FILE) -> None:
    """Append result to ring-buffer log (max MAX_ENTRIES) and atomic-write."""
    log = _load_log(path)
    log.append(result)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_protocols() -> list:
    """Return sample protocol data for CLI demo."""
    return [
        {
            "name": "Aave",
            "top10_holder_pct": 35.0,
            "team_treasury_pct": 15.0,
            "circulating_supply_pct": 85.0,
            "active_voters_30d": 1200,
            "total_token_holders": 150000,
            "proposals_last_90d": 8,
            "avg_voter_turnout_pct": 12.0,
            "token_type": "GOVERNANCE_ONLY",
        },
        {
            "name": "Curve",
            "top10_holder_pct": 55.0,
            "team_treasury_pct": 20.0,
            "circulating_supply_pct": 70.0,
            "active_voters_30d": 800,
            "total_token_holders": 90000,
            "proposals_last_90d": 15,
            "avg_voter_turnout_pct": 25.0,
            "token_type": "VOTE_ESCROWED",
        },
        {
            "name": "Compound",
            "top10_holder_pct": 65.0,
            "team_treasury_pct": 35.0,
            "circulating_supply_pct": 60.0,
            "active_voters_30d": 150,
            "total_token_holders": 40000,
            "proposals_last_90d": 2,
            "avg_voter_turnout_pct": 3.0,
            "token_type": "GOVERNANCE_ONLY",
        },
    ]


def main(argv: list = None) -> None:
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv
    data_dir: Optional[Path] = None

    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir = Path(argv[idx + 1])

    out_path = (data_dir / "governance_power_log.json") if data_dir else DATA_FILE

    protocols = _sample_protocols()
    result = analyze(protocols)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if run_mode:
        save_result(result, out_path)
        print(f"\n✅ Saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
