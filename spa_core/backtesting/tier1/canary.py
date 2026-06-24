"""
spa_core/backtesting/tier1/canary.py — CANARY stage of the promotion pipeline (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden, atomic writes. Adds the missing
CANARY stage to the promotion pipeline:

    RESEARCH → BACKTEST → WALK-FORWARD → PAPER → **CANARY** → FULL

The earlier stages already exist: BACKTEST/WALK-FORWARD = tier1/evaluator.py + oos.py
(net-of-cost APY, OOS hold, capacity, packages); the PAPER gate = tier1/gate.py
(`eligible_for_paper`). CANARY is the stage BETWEEN paper and full where a strategy that has
proven itself in paper gets MICRO-capital under NARROWED limits (tighter than the full
RiskPolicy caps) and must clear a HUMAN governance gate before it is promoted to FULL.

IMPORTANT — THIS IS PAPER / ADVISORY. It NEVER moves real money. It computes what a canary
WOULD be allocated (micro-capital sizing under narrowed limits) and what graduation WOULD
require — and it ALWAYS gates the canary→full promotion behind an explicit HUMAN decision
(`requires_human_gate=True`, every time, per governance). It does not touch the execution
domain, RiskPolicy, the tournament, or any canonical module — it only reads the existing
Tier-1 gate/verdict and publishes data/tier1_canary.json that those paths MAY consult.

Canary ENTRY criteria (a strategy may enter canary only if ALL hold):
  - it is in the paper gate's `eligible_for_paper` set (passed the paper gate), AND
  - in the verdict it is validated (real data + net-of-cost APY>0 + fits a package +
    yield holds out-of-sample + capacity OK), AND
  - it has accumulated >= CANARY_MIN_DAYS of paper track record (read from the verdict's
    per-strategy min_track_record_days proxy / gate metadata).

Canary GRADUATION (canary → FULL):
  - >= CANARY_GRADUATE_DAYS days running in canary with live micro-capital, AND
  - live metrics still healthy (positive realized APY, drawdown within the narrowed limit),
  - AND a HUMAN approves. `requires_human_gate` is ALWAYS True — the machine recommends,
    a human decides. No automatic promotion to full ever.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math  # noqa: F401  (stdlib-only invariant; available for any numeric extension)
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1.limits import (
    PER_PROTOCOL_MAX,
    TIER_AGGREGATE_MAX,
    MIN_CASH,
)

# ── canary CONFIG (deterministic, version-pinned — change → new ADR) ──────────────────────
CANARY_VERSION = "v1.0"

# Micro-capital sizing.
CANARY_MAX_CAPITAL_PCT = 0.01   # 1.0% of AUM may go to a SINGLE canary
CANARY_MAX_TOTAL_PCT = 0.05     # 5% of AUM across ALL canaries combined

# Time in stage.
CANARY_MIN_DAYS = 14            # paper days required to ENTER canary
CANARY_GRADUATE_DAYS = 30       # days running in canary before eligible for FULL

# Narrowed exposure limits — strictly TIGHTER than the full RiskPolicy/limits caps.
# Per-protocol caps are HALVED (T1 40%→20%, T2 20%→10%, T3 10%→5%); T2 aggregate halved;
# the cash buffer is doubled. A canary runs a deliberately conservative book.
CANARY_PER_PROTOCOL_MAX = {tier: round(cap / 2.0, 6) for tier, cap in PER_PROTOCOL_MAX.items()}
CANARY_TIER_AGGREGATE_MAX = {tier: round(cap / 2.0, 6) for tier, cap in TIER_AGGREGATE_MAX.items()}
CANARY_MIN_CASH = round(min(MIN_CASH * 2.0, 0.5), 6)   # min cash buffer doubled (cap at 50%)
# A canary's live drawdown must stay shallower than this to remain graduation-eligible.
CANARY_MAX_DRAWDOWN_PCT = 2.0

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_GATE = _DATA / "tier1_gate.json"
_VERDICT = _DATA / "tier1_verdict.json"
_OUT = _DATA / "tier1_canary.json"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _verdict_index() -> Dict[str, dict]:
    """{strategy_id: verdict-row} from data/tier1_verdict.json."""
    verdict = _load(_VERDICT, {})
    return {s.get("id"): s for s in verdict.get("leaderboard_tier1", []) if s.get("id")}


def _paper_days(row: dict) -> float:
    """Accumulated paper track-record days for a strategy (proxy from the verdict).

    The verdict exposes `min_track_record_days` (the Tier-1 estimate of how long the track
    record is / needs to be). We use it as the available paper-days signal; a dedicated live
    counter can override it later without changing this contract."""
    for key in ("paper_days", "track_days", "min_track_record_days"):
        v = row.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _entry_block_reason(sid: str, gate_eligible: set, vrow: Optional[dict]) -> Optional[str]:
    """Why a strategy may NOT enter canary (None = eligible to ENTER)."""
    if sid not in gate_eligible:
        return "not_eligible_for_paper(gate)"
    if vrow is None:
        return "missing_from_verdict"
    if not vrow.get("validated"):
        return "not_validated"
    if vrow.get("oos_holds") is False:
        return "yield_decayed_out_of_sample"
    if vrow.get("capacity_ok") is False:
        return "capacity_below_capital"
    if (vrow.get("net_apy_pct") or 0) <= 0:
        return "net_of_cost_apy<=0"
    days = _paper_days(vrow)
    if days < CANARY_MIN_DAYS:
        return f"insufficient_paper_days({days:.1f}<{CANARY_MIN_DAYS})"
    return None


def canary_candidates() -> List[str]:
    """Strategy ids eligible to ENTER the canary stage from the paper gate.

    candidates ⊆ gate `eligible_for_paper` (a canary must have passed the paper gate first)
    AND meet the extra canary-entry criteria (validated, OOS-held, capacity OK, net APY>0,
    >= CANARY_MIN_DAYS paper days). Deterministic, sorted."""
    gate = _load(_GATE, {})
    gate_eligible = set(gate.get("eligible_for_paper", []))
    vidx = _verdict_index()
    out = [sid for sid in sorted(gate_eligible)
           if _entry_block_reason(sid, gate_eligible, vidx.get(sid)) is None]
    return out


def canary_allocation(strategy_id: str, aum_usd: float) -> dict:
    """Micro-capital a canary WOULD receive (advisory — never moves real money).

    A single canary gets at most CANARY_MAX_CAPITAL_PCT of AUM. `within_limits` is True when
    that per-canary cap plus the all-canaries aggregate cap (CANARY_MAX_TOTAL_PCT, given the
    current candidate count) are both respected."""
    aum = max(float(aum_usd or 0.0), 0.0)
    per_canary_cap_usd = round(aum * CANARY_MAX_CAPITAL_PCT, 2)
    capital_usd = per_canary_cap_usd  # sized at the per-canary micro-cap

    candidates = canary_candidates()
    n = max(len(candidates), 1)
    total_cap_usd = round(aum * CANARY_MAX_TOTAL_PCT, 2)
    # Even at the per-canary cap, the whole cohort must fit under the aggregate cap.
    aggregate_would_be = round(capital_usd * len(candidates), 2) if candidates else capital_usd
    within_per_canary = capital_usd <= per_canary_cap_usd + 1e-9
    within_aggregate = aggregate_would_be <= total_cap_usd + 1e-9

    return {
        "strategy_id": strategy_id,
        "is_candidate": strategy_id in set(candidates),
        "aum_usd": round(aum, 2),
        "capital_usd": capital_usd,
        "capital_pct": CANARY_MAX_CAPITAL_PCT,
        "per_canary_cap_usd": per_canary_cap_usd,
        "total_canary_cap_usd": total_cap_usd,
        "n_candidates": len(candidates),
        "cohort_total_usd": aggregate_would_be,
        "within_limits": bool(within_per_canary and within_aggregate),
        "narrowed_limits": {
            "per_protocol_max": CANARY_PER_PROTOCOL_MAX,
            "tier_aggregate_max": CANARY_TIER_AGGREGATE_MAX,
            "min_cash": CANARY_MIN_CASH,
            "max_drawdown_pct": CANARY_MAX_DRAWDOWN_PCT,
        },
        "advisory": True,
        "note": "Advisory micro-capital sizing — paper only, never moves real money.",
    }


def graduation_check(strategy_id: str, days_in_canary: float,
                     live_metrics: Optional[dict] = None) -> dict:
    """Whether a canary is READY to be RECOMMENDED for promotion to FULL.

    ALWAYS returns requires_human_gate=True — canary→full is a HUMAN governance decision; the
    machine only recommends. `ready_for_full` requires >= CANARY_GRADUATE_DAYS in canary AND
    healthy live metrics (positive realized APY, drawdown within the narrowed limit). Even
    when ready_for_full is True, promotion still needs explicit human sign-off."""
    live_metrics = live_metrics or {}
    days = float(days_in_canary or 0.0)
    reasons: List[str] = []

    enough_days = days >= CANARY_GRADUATE_DAYS
    if not enough_days:
        reasons.append(f"days_in_canary {days:.1f} < {CANARY_GRADUATE_DAYS}")

    live_apy = live_metrics.get("realized_apy_pct")
    apy_ok = True
    if live_apy is not None:
        apy_ok = float(live_apy) > 0
        if not apy_ok:
            reasons.append(f"realized_apy {float(live_apy):.3f}% <= 0")

    dd = live_metrics.get("drawdown_pct")
    dd_ok = True
    if dd is not None:
        dd_ok = abs(float(dd)) <= CANARY_MAX_DRAWDOWN_PCT + 1e-9
        if not dd_ok:
            reasons.append(
                f"drawdown {abs(float(dd)):.3f}% > {CANARY_MAX_DRAWDOWN_PCT}% (narrowed limit)")

    ready = bool(enough_days and apy_ok and dd_ok)
    if ready and not reasons:
        reasons.append(
            f">= {CANARY_GRADUATE_DAYS}d in canary with healthy live metrics — "
            "RECOMMEND for full (pending human approval)")

    return {
        "strategy_id": strategy_id,
        "days_in_canary": round(days, 2),
        "graduate_days_required": CANARY_GRADUATE_DAYS,
        "ready_for_full": ready,
        "requires_human_gate": True,   # ALWAYS — canary→full is a human decision (governance)
        "reason": "; ".join(reasons) if reasons else "not ready",
        "advisory": True,
        "note": ("Machine RECOMMENDATION only. Promotion canary→full requires explicit human "
                 "sign-off; nothing is promoted automatically and no real money moves here."),
    }


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tier1_canary_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def build_report(write: bool = True, aum_usd: float = 100000.0) -> dict:
    """Build the canary-stage report: entry candidates, micro-allocations, narrowed config,
    and per-candidate graduation status. Writes data/tier1_canary.json atomically."""
    gate = _load(_GATE, {})
    gate_eligible = set(gate.get("eligible_for_paper", []))
    vidx = _verdict_index()
    candidates = canary_candidates()

    candidate_rows = []
    for sid in candidates:
        vrow = vidx.get(sid, {})
        alloc = canary_allocation(sid, aum_usd)
        grad = graduation_check(sid, _canary_days_in_stage(vrow),
                                live_metrics=_live_metrics_proxy(vrow))
        candidate_rows.append({
            "id": sid,
            "net_apy_pct": vrow.get("net_apy_pct"),
            "package": vrow.get("package"),
            "paper_days": round(_paper_days(vrow), 2),
            "capital_usd": alloc["capital_usd"],
            "within_limits": alloc["within_limits"],
            "graduation": grad,
        })

    # Explain who is NOT a candidate (paper-eligible but failing a canary-entry criterion).
    blocked = {}
    for sid in sorted(gate_eligible):
        reason = _entry_block_reason(sid, gate_eligible, vidx.get(sid))
        if reason is not None:
            blocked[sid] = reason

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_canary",
        "stage": "canary",
        "pipeline": "research->backtest->walk_forward->paper->CANARY->full",
        "llm_forbidden": True,
        "advisory": True,
        "is_gate": False,
        "version": CANARY_VERSION,
        "aum_usd": round(float(aum_usd or 0.0), 2),
        "config": {
            "max_capital_pct_per_canary": CANARY_MAX_CAPITAL_PCT,
            "max_total_pct_all_canaries": CANARY_MAX_TOTAL_PCT,
            "min_days_to_enter": CANARY_MIN_DAYS,
            "graduate_days_to_full": CANARY_GRADUATE_DAYS,
            "narrowed_limits": {
                "per_protocol_max": CANARY_PER_PROTOCOL_MAX,
                "tier_aggregate_max": CANARY_TIER_AGGREGATE_MAX,
                "min_cash": CANARY_MIN_CASH,
                "max_drawdown_pct": CANARY_MAX_DRAWDOWN_PCT,
            },
        },
        "candidates": [r["id"] for r in candidate_rows],
        "candidate_count": len(candidate_rows),
        "candidate_detail": candidate_rows,
        "blocked": blocked,
        "blocked_count": len(blocked),
        "summary": {
            "paper_eligible": len(gate_eligible),
            "canary_candidates": len(candidate_rows),
            "ready_for_full_pending_human": sum(
                1 for r in candidate_rows if r["graduation"]["ready_for_full"]),
        },
        "note": ("CANARY is PAPER/advisory — it sizes micro-capital under narrowed limits and "
                 "gates canary->full behind an explicit HUMAN decision. No real money moves; "
                 "promotion to full is never automatic."),
    }
    if write:
        _atomic_write(_OUT, report)
    return report


def _canary_days_in_stage(vrow: dict) -> float:
    """Days the strategy has actually been RUNNING in canary (proxy).

    No live canary counter exists yet, so we report 0 unless the verdict/state carries an
    explicit `canary_days` — graduation therefore correctly reports 'not ready' until a real
    canary runtime accumulates days. A future live counter overrides this without API change."""
    v = vrow.get("canary_days")
    return float(v) if isinstance(v, (int, float)) else 0.0


def _live_metrics_proxy(vrow: dict) -> dict:
    """Best-available live metrics for graduation (proxy from the verdict; empty if absent).
    Real canary runtime metrics would replace this; absence leaves the checks neutral."""
    m = {}
    if isinstance(vrow.get("net_apy_pct"), (int, float)):
        m["realized_apy_pct"] = vrow["net_apy_pct"]
    if isinstance(vrow.get("max_dd_pct"), (int, float)):
        m["drawdown_pct"] = vrow["max_dd_pct"]
    return m


if __name__ == "__main__":
    rep = build_report(write=True, aum_usd=100000.0)
    print(f"Tier-1 CANARY stage {CANARY_VERSION}  (AUM ${rep['aum_usd']:,.0f})")
    print(f"  pipeline: {rep['pipeline']}")
    cfg = rep["config"]
    print(f"  micro-cap: {cfg['max_capital_pct_per_canary']:.1%}/canary, "
          f"{cfg['max_total_pct_all_canaries']:.1%} total | "
          f"enter@{cfg['min_days_to_enter']}d, graduate@{cfg['graduate_days_to_full']}d")
    print(f"  paper-eligible={rep['summary']['paper_eligible']}  "
          f"canary candidates={rep['candidate_count']}")
    if rep["candidate_detail"]:
        for r in rep["candidate_detail"]:
            g = r["graduation"]
            print(f"   - {r['id']:<26} net_apy={r['net_apy_pct']} "
                  f"micro=${r['capital_usd']:,.0f} within_limits={r['within_limits']} "
                  f"ready_for_full={g['ready_for_full']} (human_gate={g['requires_human_gate']})")
    else:
        print("   (no canary candidates yet — honest: thin validated set / paper days < "
              f"{CANARY_MIN_DAYS})")
    if rep["blocked"]:
        print("  paper-eligible but blocked from canary:")
        for sid, why in rep["blocked"].items():
            print(f"   x {sid:<26} {why}")
    print(f"  -> wrote {_OUT}")
