"""
spa_core/backtesting/tier1/reverse_stress.py — reverse (inverse) stress test (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. No network.

A normal stress test (spa_core/backtesting/tier1/stress.py) answers:
    "What is the loss under scenario X?"
A REVERSE stress test answers the institutional question instead:
    "What scenario causes a loss of -X% (our tolerance)?" — i.e. it solves for the
    BREAKING POINT: the smallest shock that breaches a stated loss tolerance.

This is the question regulators and allocators actually ask ("what would have to go
wrong to lose 10% of principal?"). It complements the forward stress test and the
deterministic RiskPolicy (which still governs live exposure).

Breaking points (all closed-form, deterministic, version-pinned — change → new ADR):

  • DEPEG breakpoint — a stablecoin depeg hits every deployed position pro-rata. A depeg
    of d% on deployed weight W yields a principal loss of d% * W. The breakpoint is the
    depeg that exactly hits the tolerance:
        depeg_breakpoint_pct = |tolerance| / W
    More deployed (larger W) → smaller breakpoint → MORE fragile. 100% cash → W=0 →
    breakpoint is +inf (can never be breached by a depeg).

  • EXPLOIT breakpoint — a held T2/T3 sleeve exploit wipes 50% of that sleeve's principal.
    Sort the held T2/T3 sleeves worst-first (largest weight first — the adversary picks the
    biggest first) and accumulate 50%*weight losses until the tolerance is breached. The
    count is the minimal number of simultaneous sleeve-exploits that breach; the protocol
    list names which ones. If the entire T2/T3 book cannot reach the tolerance, no finite
    answer exists (None / 0 sleeves).

  • RATE breakpoint — an APY drop reduces YIELD, not PRINCIPAL. Since the tolerance is a
    principal-loss tolerance and yield cannot itself go negative on a long stable book,
    a rate collapse alone can never breach a principal-loss tolerance. Reported as N/A
    (the honest answer) so the report does not over-state rate fragility.

  • COMBINED / most_fragile_scenario — the single SMALLEST shock across the principal
    scenarios (depeg vs exploit), expressed on a common 0..1 "shock magnitude" scale so
    the two are comparable, picking whichever breaches with the least stress. This is the
    most-likely path to the tolerance.

Public API:
    reverse_stress(allocation, loss_tolerance_pct=-10.0) -> dict
    build_report(write=True, tolerance=-10.0) -> dict   (data/tier1_reverse_stress.json)

CLI (__main__): prints the live-portfolio reverse-stress breakpoints.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1.stress import EXPLOIT_LOSS_PCT, stress_strategy
from spa_core.backtesting.tier1.tail_risk import PROTOCOL_TIER, strategy_tail_risk
from spa_core.utils.atomic import atomic_save

REVERSE_STRESS_VERSION = "v1.0"

# 50% principal loss per exploited sleeve — same convention as the forward stress test.
SLEEVE_EXPLOIT_LOSS_PCT = EXPLOIT_LOSS_PCT  # 50.0

# Sentinel for "no finite breaking point" (e.g. all-cash never depegs).
INF = float("inf")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = _REPO_ROOT / "data"
REPORT_FILENAME = "tier1_reverse_stress.json"
POSITIONS_FILENAME = "current_positions.json"


# ─── Allocation helpers ─────────────────────────────────────────────────────────


def _weights(allocation: Dict[str, float]) -> Dict[str, float]:
    """Deployed (non-cash) weights, coerced to float, zeros/None dropped."""
    return {
        str(k): float(v)
        for k, v in (allocation or {}).items()
        if k != "cash" and v
    }


def _deployed_weight(allocation: Dict[str, float]) -> float:
    """Total deployed weight (fraction of the book at risk of principal loss)."""
    return sum(_weights(allocation).values())


def _t2t3_sleeves(allocation: Dict[str, float]) -> List[tuple]:
    """Held T2/T3 sleeves, largest weight first (adversary picks the biggest)."""
    w = _weights(allocation)
    sleeves = [
        (p, wt) for p, wt in w.items()
        if PROTOCOL_TIER.get(p, "T2") in ("T2", "T3")
    ]
    # Sort worst-first: largest weight first, tie-broken by name for determinism.
    sleeves.sort(key=lambda kv: (-kv[1], kv[0]))
    return sleeves


# ─── Breaking-point solvers ─────────────────────────────────────────────────────


def depeg_breakpoint_pct(allocation: Dict[str, float],
                         loss_tolerance_pct: float) -> float:
    """Depeg % on deployed positions that exactly breaches the tolerance.

    Closed form: loss = depeg% * deployed_weight  ⇒  depeg% = |tol| / deployed_weight.
    Returns +inf when nothing is deployed (an all-cash book can never depeg-breach).
    """
    tol = abs(float(loss_tolerance_pct))
    deployed = _deployed_weight(allocation)
    if deployed <= 0.0:
        return INF
    return tol / deployed


def exploit_breakpoint(allocation: Dict[str, float],
                       loss_tolerance_pct: float) -> dict:
    """Minimal set of T2/T3 sleeve-exploits (50% each) that breaches the tolerance.

    Greedy worst-first: take the largest sleeves first until cumulative principal loss
    reaches |tolerance|. Returns the count, the named protocols, and whether the book
    can reach the tolerance at all.
    """
    tol = abs(float(loss_tolerance_pct))
    sleeves = _t2t3_sleeves(allocation)
    cumulative = 0.0
    breached_at: List[str] = []
    for protocol, weight in sleeves:
        cumulative += (SLEEVE_EXPLOIT_LOSS_PCT / 100.0) * weight * 100.0
        # loss in pct-of-book = 50% * weight; weight already a fraction → *100 to pct
        breached_at.append(protocol)
        if cumulative + 1e-12 >= tol:
            return {
                "sleeves_to_breach": len(breached_at),
                "protocols": list(breached_at),
                "cumulative_loss_pct": round(cumulative, 6),
                "breaches": True,
            }
    # Whole T2/T3 book exhausted without breaching the tolerance.
    return {
        "sleeves_to_breach": None,
        "protocols": [],
        "cumulative_loss_pct": round(cumulative, 6),
        "breaches": False,
    }


def _shock_magnitude_depeg(depeg_bp: float) -> float:
    """Normalise a depeg breakpoint (% depeg) to a 0..1 shock scale.

    A full 100% depeg = shock magnitude 1.0. Smaller depegs are smaller shocks.
    +inf breakpoint → infinite (i.e. un-reachable) shock.
    """
    if depeg_bp == INF:
        return INF
    return depeg_bp / 100.0


def _shock_magnitude_exploit(exploit: dict, allocation: Dict[str, float]) -> float:
    """Normalise an exploit breakpoint to a 0..1 shock scale.

    Shock = (deployed-T2/T3 weight that must be exploited) — the fraction of the book
    the adversary must compromise. Smaller fraction = more fragile = smaller shock.
    Un-reachable → +inf.
    """
    if not exploit.get("breaches"):
        return INF
    w = _weights(allocation)
    exploited_weight = sum(w.get(p, 0.0) for p in exploit["protocols"])
    return exploited_weight  # already a fraction of the book in 0..1


def reverse_stress(allocation: Dict[str, float],
                   loss_tolerance_pct: float = -10.0) -> dict:
    """Solve for the minimal shocks that breach `loss_tolerance_pct` (a negative %).

    Returns:
        depeg_breakpoint_pct        — depeg % on deployed positions that breaches (or inf)
        exploit_sleeves_to_breach   — # of T2/T3 sleeve-exploits to breach (or None)
        exploit_breakpoint_protocols— which protocols (worst-first) breach
        most_fragile_scenario       — the smallest shock that breaches ('depeg'/'exploit'/None)
        breaches_at                 — details of the most-fragile scenario
    """
    tol = float(loss_tolerance_pct)

    depeg_bp = depeg_breakpoint_pct(allocation, tol)
    exploit = exploit_breakpoint(allocation, tol)

    # Compare the two principal scenarios on a common shock scale; pick the smallest.
    depeg_shock = _shock_magnitude_depeg(depeg_bp)
    exploit_shock = _shock_magnitude_exploit(exploit, allocation)

    candidates = []
    if depeg_shock != INF:
        candidates.append(("depeg", depeg_shock, {
            "scenario": "depeg",
            "depeg_pct": round(depeg_bp, 6),
            "deployed_weight": round(_deployed_weight(allocation), 6),
            "description": (
                f"a {depeg_bp:.2f}% depeg across deployed positions "
                f"breaches {tol:.1f}%"
            ),
        }))
    if exploit_shock != INF:
        candidates.append(("exploit", exploit_shock, {
            "scenario": "exploit",
            "sleeves": exploit["sleeves_to_breach"],
            "protocols": exploit["protocols"],
            "description": (
                f"{exploit['sleeves_to_breach']} T2/T3 sleeve-exploit(s) "
                f"({', '.join(exploit['protocols'])}) breaches {tol:.1f}%"
            ),
        }))

    if candidates:
        candidates.sort(key=lambda c: (c[1], c[0]))  # smallest shock, name tie-break
        most_fragile = candidates[0][0]
        breaches_at = candidates[0][2]
    else:
        most_fragile = None
        breaches_at = {
            "scenario": None,
            "description": (
                f"no single principal scenario reaches {tol:.1f}% "
                "(all-cash or T2/T3 book too small)"
            ),
        }

    # Forward-stress cross-check (consistency anchor): the forward stress test at zero
    # base yield must report a worst case at least as bad as -|tol| once the most-fragile
    # shock is applied. We surface the forward worst case + tail-risk drag for context so
    # the reverse breakpoint can be read against the forward model.
    forward = stress_strategy(0.0, allocation)
    tail = strategy_tail_risk(allocation)

    return {
        "version": REVERSE_STRESS_VERSION,
        "loss_tolerance_pct": round(tol, 6),
        "deployed_weight": round(_deployed_weight(allocation), 6),
        "forward_worst_case_pct": forward["worst_case_pct"],
        "annual_tail_risk_pct": tail["tail_risk_pct"],
        "depeg_breakpoint_pct": (
            None if depeg_bp == INF else round(depeg_bp, 6)
        ),
        "exploit_sleeves_to_breach": exploit["sleeves_to_breach"],
        "exploit_breakpoint_protocols": exploit["protocols"],
        "rate_breakpoint": "N/A",  # APY drop cannot breach a PRINCIPAL-loss tolerance
        "rate_note": (
            "Rate/APY collapse reduces yield, not principal; it cannot by itself "
            "breach a principal-loss tolerance on a long stablecoin book."
        ),
        "most_fragile_scenario": most_fragile,
        "breaches_at": breaches_at,
    }


# ─── Report builder ─────────────────────────────────────────────────────────────


def _positions_to_allocation(positions: Dict[str, float]) -> Dict[str, float]:
    """Convert USD positions (+ optional cash) into normalised fractional weights."""
    total = sum(float(v) for v in positions.values() if v)
    if total <= 0:
        return {}
    return {k: float(v) / total for k, v in positions.items() if v}


def _load_live_allocation(data_dir: Path) -> Optional[Dict[str, float]]:
    """Read data/current_positions.json → normalised allocation incl. cash."""
    path = data_dir / POSITIONS_FILENAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    positions = dict(doc.get("positions") or {})
    cash = doc.get("cash_usd")
    if cash:
        positions["cash"] = float(cash)
    if not positions:
        return None
    return _positions_to_allocation(positions)


def _resolve_strategy_allocation(strategy_id: str) -> Optional[Dict[str, float]]:
    """Best-effort static allocation for a validated strategy.

    Strategy modules have heterogeneous interfaces; we only use a static allocation if
    the module exposes one of the well-known forms. Otherwise we skip (return None) —
    we never fabricate an allocation. Deterministic, no network, no LLM.
    """
    mod_name = None
    # leaderboard ids look like "s27_stablecoin_carry" → module spa_core.strategies.s27_*
    short = strategy_id.split("_")[0]  # "s27"
    try:
        import importlib

        # Try the full id first, then the short prefix match is unreliable → only full.
        mod = importlib.import_module(f"spa_core.strategies.{strategy_id}")
        mod_name = strategy_id
    except Exception:
        mod = None

    if mod is None:
        return None

    # Accept a static dict attribute or a zero-arg callable returning a dict.
    for attr in ("ALLOCATION", "STATIC_ALLOCATION", "TARGET_ALLOCATION"):
        val = getattr(mod, attr, None)
        if isinstance(val, dict) and val:
            return {k: float(v) for k, v in val.items()}
    fn = getattr(mod, "allocation", None)
    if callable(fn):
        try:
            val = fn()
            if isinstance(val, dict) and val:
                return {k: float(v) for k, v in val.items()}
        except Exception:
            return None
    return None


def _load_validated_strategy_ids(data_dir: Path) -> List[str]:
    """Validated strategy ids from data/tier1_verdict.json (best-effort)."""
    path = data_dir / "tier1_verdict.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for row in doc.get("leaderboard_tier1", []) or []:
        if row.get("validated") and row.get("id"):
            out.append(str(row["id"]))
    return out


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomic JSON write — delegates to the shared atomic-save utility."""
    atomic_save(payload, str(path))


def build_report(write: bool = True,
                 tolerance: float = -10.0,
                 data_dir: Optional[Path] = None) -> dict:
    """Reverse-stress report for the live portfolio + each validated strategy.

    Writes data/tier1_reverse_stress.json atomically when write=True.
    """
    data_dir = Path(data_dir) if data_dir is not None else _DATA_DIR

    strategies: Dict[str, dict] = {}

    # Live portfolio (real allocation from current_positions.json).
    live_alloc = _load_live_allocation(data_dir)
    if live_alloc is not None:
        strategies["live_portfolio"] = {
            "source": POSITIONS_FILENAME,
            "allocation": {k: round(v, 6) for k, v in live_alloc.items()},
            "reverse_stress": reverse_stress(live_alloc, tolerance),
        }

    # Validated strategies — only those whose static allocation we can resolve honestly.
    for sid in _load_validated_strategy_ids(data_dir):
        alloc = _resolve_strategy_allocation(sid)
        if alloc is None:
            strategies[sid] = {
                "source": "strategy_module",
                "allocation": None,
                "reverse_stress": None,
                "note": "no static allocation exposed by module — skipped (not fabricated)",
            }
            continue
        strategies[sid] = {
            "source": "strategy_module",
            "allocation": {k: round(float(v), 6) for k, v in alloc.items()},
            "reverse_stress": reverse_stress(alloc, tolerance),
        }

    report = {
        "version": REVERSE_STRESS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "tier1_reverse_stress",
        "llm_forbidden": True,
        "advisory_only": True,
        "loss_tolerance_pct": round(float(tolerance), 6),
        "method": (
            "Inverse stress: solve for the minimal shock that breaches the loss "
            "tolerance. Depeg breakpoint = |tol|/deployed_weight; exploit breakpoint = "
            "greedy worst-first 50%-per-sleeve T2/T3 accumulation; rate collapse is N/A "
            "for a principal-loss tolerance."
        ),
        "strategies": strategies,
    }

    if write:
        _atomic_write(data_dir / REPORT_FILENAME, report)

    return report


if __name__ == "__main__":
    _live = _load_live_allocation(_DATA_DIR)
    print("=" * 70)
    print("SPA Reverse Stress Test — live portfolio breaking points (tol -10%)")
    print("=" * 70)
    if _live is None:
        print("No live portfolio found (data/current_positions.json missing/invalid).")
    else:
        rs = reverse_stress(_live, loss_tolerance_pct=-10.0)
        print(json.dumps(rs, indent=2))
        print("-" * 70)
        bp = rs["depeg_breakpoint_pct"]
        print(f"DEPEG breakpoint : a {bp:.2f}% depeg on deployed positions breaches -10%"
              if bp is not None else "DEPEG breakpoint : never (all-cash)")
        n = rs["exploit_sleeves_to_breach"]
        if n:
            print(f"EXPLOIT breakpoint: {n} sleeve-exploit(s) "
                  f"({', '.join(rs['exploit_breakpoint_protocols'])}) breach -10%")
        else:
            print("EXPLOIT breakpoint: T2/T3 book cannot reach -10% alone")
        print(f"MOST FRAGILE     : {rs['most_fragile_scenario']} — "
              f"{rs['breaches_at'].get('description')}")
