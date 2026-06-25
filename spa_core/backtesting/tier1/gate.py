"""
spa_core/backtesting/tier1/gate.py — enforced backtest→paper→live gate (Tier-1 P3).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. Closes the validation loop:

  backtest (real data) → Tier-1 verdict (net-of-cost APY + OOS hold + capacity) →
  GATE: a strategy may enter paper ONLY if `validated` → live → divergence monitor demotes
  if live paper yield stops matching the backtest expectation.

Produces data/tier1_gate.json — the authoritative eligibility list. The tournament /
promotion path SHOULD consult `is_eligible(strategy_id)` before adding a strategy to the
paper-shadow set (advisory: this module never touches the execution domain and never edits
tournament state — it only publishes the gate the tournament reads).

Live-vs-backtest divergence: compares the live paper APY (data/paper_trading_status.json)
to the Tier-1-expected net APY of validated strategies. A material shortfall flags that the
live book has stopped delivering backtest yield → demotion/review signal.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_VERDICT = _DATA / "tier1_verdict.json"
_PAPER = _DATA / "paper_trading_status.json"
_OUT = _DATA / "tier1_gate.json"

DIVERGENCE_FLOOR = 0.5   # live APY below 50% of expected → DIVERGENT (auto-demote signal)


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _block_reason(s: dict) -> Optional[str]:
    """Why a non-validated strategy is blocked from paper (None = eligible)."""
    if s.get("validated"):
        return None
    if (s.get("net_apy_pct") or 0) <= 0:
        return "net_of_cost_apy<=0"
    if s.get("package") is None:
        return "outside_all_package_risk_bands"
    if s.get("oos_holds") is False:
        return "yield_decayed_out_of_sample"
    if s.get("capacity_ok") is False:
        return f"capacity_below_capital(binding={s.get('binding_protocol')})"
    if s.get("tier1_grade") == "UNPROVEN":
        return "data_not_trustworthy"
    return "not_validated"


def _live_divergence(verdict: dict) -> dict:
    """Portfolio-level live-vs-backtest: live paper APY vs expected net APY of validated set."""
    paper = _load(_PAPER, {})
    live_apy = paper.get("apy_today_pct")
    if live_apy is None:
        live_apy = paper.get("regime_t1_avg_apy")
    board = verdict.get("leaderboard_tier1", [])
    validated_nets = [s["net_apy_pct"] for s in board if s.get("validated") and s.get("net_apy_pct")]
    if not validated_nets or live_apy is None:
        return {"status": "insufficient_data", "live_apy_pct": live_apy,
                "expected_apy_pct": None}
    validated_nets.sort()
    expected = validated_nets[len(validated_nets) // 2]  # median validated net APY
    try:
        live = float(live_apy)
    except (TypeError, ValueError):
        return {"status": "insufficient_data", "live_apy_pct": live_apy, "expected_apy_pct": expected}
    divergent = expected > 0 and live < expected * DIVERGENCE_FLOOR
    return {
        "status": "DIVERGENT" if divergent else "ok",
        "live_apy_pct": round(live, 3),
        "expected_apy_pct": round(expected, 3),
        "shortfall_pct": round(expected - live, 3),
        "note": ("Live paper yield is far below the Tier-1-expected net APY of validated "
                 "strategies → review/demote (backtest no longer predicts live).")
        if divergent else "live paper yield tracks backtest expectation",
    }


def build_gate(write: bool = True) -> dict:
    verdict = _load(_VERDICT, {})
    board = verdict.get("leaderboard_tier1", [])
    eligible, blocked = [], {}
    for s in board:
        reason = _block_reason(s)
        if reason is None:
            eligible.append(s["id"])
        else:
            blocked[s["id"]] = reason

    gate = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gate": "tier1_backtest_to_paper",
        "llm_forbidden": True,
        "regime": verdict.get("regime"),
        "criteria": ("validated = real data + net-of-cost APY>0 + fits a risk package + "
                     "yield holds out-of-sample + capacity >= capital"),
        "eligible_for_paper": eligible,
        "eligible_count": len(eligible),
        "blocked": blocked,
        "blocked_count": len(blocked),
        "live_vs_backtest": _live_divergence(verdict),
    }
    if write:
        atomic_save(gate, str(_OUT))
    return gate


def is_eligible(strategy_id: str) -> bool:
    """Advisory check for the tournament/promotion path: may this strategy enter paper?
    Fail-OPEN to True if the gate file is missing (don't block ops on a missing Tier-1 run)."""
    gate = _load(_OUT, None)
    if not gate:
        return True
    return strategy_id in set(gate.get("eligible_for_paper", []))


if __name__ == "__main__":
    g = build_gate()
    print(json.dumps({
        "regime": g["regime"], "eligible_count": g["eligible_count"],
        "blocked_count": g["blocked_count"],
        "eligible": g["eligible_for_paper"][:10],
        "block_reasons_sample": dict(list(g["blocked"].items())[:5]),
        "live_vs_backtest": g["live_vs_backtest"],
    }, indent=2, ensure_ascii=False))
