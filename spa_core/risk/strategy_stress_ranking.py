"""
spa_core/risk/strategy_stress_ranking.py

Rank every registered strategy by downside protection under the SPA bear-market
stress suite.

For each strategy in ``strategy_registry.REGISTRY`` this module:

  1. Extracts the strategy's target allocation at $100k of capital
     (``get_allocation`` → ``to_vportfolio_format`` → other accessors).
  2. Replays the five deterministic shock scenarios from
     :mod:`spa_core.risk.stress_tester` against that allocation, using the
     strategy's own expected APY for the yield-sensitive scenarios.
  3. Records the worst-case dollar / percent loss and the scenario that caused
     it, then derives a 0–100 ``safety_score`` ( = 100 · (1 − worst/capital) ).

Output: ``data/strategy_stress_ranking.json`` (atomic write) with three
rankings — by safety, by APY, and by a simple risk-adjusted score
(APY / (worst_case_loss_pct + 1)).

Constraints: stdlib only, atomic writes, deterministic, read-only/advisory,
LLM FORBIDDEN. Never modifies allocator / risk / execution state.

CLI:
    python3 -m spa_core.risk.strategy_stress_ranking --check
    python3 -m spa_core.risk.strategy_stress_ranking --run
    python3 -m spa_core.risk.strategy_stress_ranking --run --data-dir data
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from typing import Optional

from spa_core.risk.stress_tester import SCENARIO_NAMES, StressTester
from spa_core.strategies.strategy_registry import REGISTRY

__all__ = ["rank_strategies", "extract_allocation"]

DEFAULT_CAPITAL = 100_000.0
log = logging.getLogger(__name__)


# ─── Protocol → tier classification ──────────────────────────────────────────

def _build_tier_map() -> dict:
    """Map protocol_key → tier ("T1"/"T2"/"T3") from the adapter registry."""
    tiers: dict = {}
    try:
        from spa_core.adapters import ADAPTER_REGISTRY  # (key, tier, cls) tuples
        for entry in ADAPTER_REGISTRY:
            try:
                key, tier = entry[0], entry[1]
                tiers[str(key).lower()] = str(tier)
            except Exception:
                continue
    except Exception:
        pass
    return tiers


_TIER_MAP = _build_tier_map()

# Name-substring fallback for protocol keys not in the adapter registry
# (strategies sometimes invent their own pool labels).
_T2_HINTS = (
    "morpho", "euler", "yearn", "maple", "pendle", "curve", "convex",
    "radiant", "gmx", "glp", "velodrome", "aerodrome", "fluid", "frax",
    "spark", "silo", "dolomite", "moonwell", "susde", "usd0", "wusdm",
    "scrvusd", "stusd", "sdai", "sfrax", "lp", "ethena",
)
_T1_HINTS = ("aave", "compound", "cash", "usdc", "buffer")


def _tier_of(protocol: str) -> str:
    p = protocol.lower()
    if p in _TIER_MAP:
        return _TIER_MAP[p]
    for hint in _T2_HINTS:
        if hint in p:
            return "T2"
    for hint in _T1_HINTS:
        if hint in p:
            return "T1"
    return "T2"  # unknown ⇒ treat conservatively as T2 (riskier bucket)


def _t2_fraction(allocation: dict) -> float:
    total = sum(v for v in allocation.values() if v > 0)
    if total <= 0:
        return 0.0
    t2 = sum(v for k, v in allocation.items()
             if v > 0 and _tier_of(k) in ("T2", "T3"))
    return round(t2 / total * 100.0, 2)


# ─── Strategy instantiation + allocation extraction ──────────────────────────

def _instantiate(cls, capital: float):
    """Construct a strategy handler, tolerating heterogeneous __init__ sigs."""
    for attempt in (
        lambda: cls(),
        lambda: cls(capital),
        lambda: cls(capital_usd=capital),
        lambda: cls(capital=capital),
    ):
        try:
            return attempt()
        except Exception:
            continue
    return None


def _as_usd(weights: dict, capital: float) -> dict:
    """Normalise an allocation dict to USD.

    Strategies report either USD positions (sum ≈ capital, or > capital when
    leveraged) or fractional weights (sum ≈ 1). Disambiguate by magnitude:
    a total ≤ 3.0 is treated as fractions of capital.
    """
    clean: dict = {}
    for k, v in weights.items():
        if isinstance(v, (int, float)) and v > 0:
            clean[str(k)] = float(v)
        elif isinstance(v, dict):
            # nested descriptor, e.g. {"weight": 0.2, "amount": 20000.0}
            amt = v.get("amount")
            wt = v.get("weight")
            if isinstance(amt, (int, float)) and amt > 0:
                clean[str(k)] = float(amt)
            elif isinstance(wt, (int, float)) and wt > 0:
                clean[str(k)] = float(wt)
    if not clean:
        return {}
    total = sum(clean.values())
    if total <= 3.0:  # fractional weights → scale to capital
        return {k: v * capital for k, v in clean.items()}
    return clean


def extract_allocation(obj, capital: float) -> Optional[dict]:
    """Best-effort extraction of {protocol: usd} from a strategy handler."""
    # 1. Canonical accessor: get_allocation(capital_usd) → {protocol: usd}
    f = getattr(obj, "get_allocation", None)
    if callable(f):
        for call in (lambda: f(capital), lambda: f()):
            try:
                r = call()
                usd = _as_usd(r, capital) if isinstance(r, dict) else {}
                if usd:
                    return usd
            except Exception:
                continue
    # 2. vPortfolio export: {"positions": {usd}} or {"allocation": {weights}}
    f = getattr(obj, "to_vportfolio_format", None)
    if callable(f):
        for call in (lambda: f(capital), lambda: f()):
            try:
                d = call()
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            for key in ("positions", "allocation", "allocations", "weights"):
                sub = d.get(key)
                if isinstance(sub, dict):
                    usd = _as_usd(sub, capital)
                    if usd:
                        return usd
    # 3. Other accessors
    for name in ("get_current_allocation", "allocate", "get_target_weights",
                 "target_weights", "get_current_weights"):
        f = getattr(obj, name, None)
        if not callable(f):
            continue
        for call in (lambda: f(capital), lambda: f()):
            try:
                r = call()
                usd = _as_usd(r, capital) if isinstance(r, dict) else {}
                if usd:
                    return usd
            except Exception:
                continue
    return None


def _expected_apy_pct(obj, meta) -> float:
    """Strategy expected APY in percent; fall back to the meta midpoint."""
    f = getattr(obj, "get_expected_apy", None)
    if callable(f):
        try:
            v = f()
            if isinstance(v, (int, float)) and v is not None:
                v = float(v)
                # tolerate decimal-form returns (e.g. 0.048 → 4.8%)
                return v * 100.0 if 0 < v < 1.0 else v
        except Exception:
            pass
    return float(meta.apy_midpoint)


# ─── Per-strategy stress evaluation ──────────────────────────────────────────

def _evaluate(meta, capital: float) -> Optional[dict]:
    try:
        mod = importlib.import_module(meta.module)
        cls = getattr(mod, meta.handler_class)
    except Exception as exc:
        log.warning("load %s failed: %s", meta.id, exc)
        return None

    obj = _instantiate(cls, capital)
    if obj is None:
        log.warning("instantiate %s failed", meta.id)
        return None

    allocation = extract_allocation(obj, capital)
    if not allocation:
        log.warning("no allocation for %s", meta.id)
        return None

    apy_pct = _expected_apy_pct(obj, meta)

    tester = StressTester(positions=allocation, capital=capital,
                          blended_apy=apy_pct / 100.0)
    report = tester.analyze()

    worst_usd = report["worst_case_impact_usd"]
    worst_pct = report["worst_case_impact_pct"]
    safety = round(100.0 * (1.0 - worst_usd / capital), 2) if capital else 0.0

    return {
        "id": meta.id,
        "name": meta.name,
        "risk_tier": meta.risk_tier,
        "worst_case_loss_pct": round(worst_pct, 4),
        "worst_case_loss_usd": round(worst_usd, 2),
        "worst_scenario": report["worst_case_scenario"],
        "safety_score": safety,
        "t2_pct": _t2_fraction(allocation),
        "expected_apy": round(apy_pct, 4),
        "deployed_usd": report["deployed_usd"],
        "num_positions": report["num_positions"],
        "scenario_losses": {
            s["scenario"]: s["impact_pct"] for s in report["scenarios"]
        },
    }


def rank_strategies(capital: float = DEFAULT_CAPITAL) -> dict:
    """Stress-test every registered strategy and build the ranking document."""
    rows = []
    skipped = []
    for meta in REGISTRY.as_list(enabled_only=False):
        row = _evaluate(meta, capital)
        if row is None:
            skipped.append(meta.id)
        else:
            rows.append(row)

    by_safety = sorted(rows, key=lambda r: (r["worst_case_loss_pct"], -r["expected_apy"]))
    by_apy = sorted(rows, key=lambda r: -r["expected_apy"])
    for r in rows:
        r["risk_adjusted_score"] = round(
            r["expected_apy"] / (r["worst_case_loss_pct"] + 1.0), 4
        )
    by_risk_adj = sorted(rows, key=lambda r: -r["risk_adjusted_score"])

    def _ids(seq):
        return [r["id"] for r in seq]

    return {
        "module": "strategy_stress_ranking",
        "is_demo": False,
        "capital_usd": round(capital, 2),
        "scenarios_tested": list(SCENARIO_NAMES),
        "total_tested": len(rows),
        "total_skipped": len(skipped),
        "skipped_ids": skipped,
        "strategies": rows,
        "ranked_by_safety": _ids(by_safety),
        "ranked_by_apy": _ids(by_apy),
        "ranked_by_risk_adjusted": _ids(by_risk_adj),
    }


# ─── IO ──────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    logging.basicConfig(level=logging.WARNING)
    run_mode = "--run" in args
    data_dir = "data"
    for i, a in enumerate(args):
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    result = rank_strategies()

    print(f"[strategy_stress_ranking] tested {result['total_tested']} strategies "
          f"(skipped {result['total_skipped']})")
    print("\n  Safest 10 (lowest worst-case loss):")
    safe_by_id = {r["id"]: r for r in result["strategies"]}
    for sid in result["ranked_by_safety"][:10]:
        r = safe_by_id[sid]
        print(f"    {r['id']:<26} {r['name'][:32]:<32} "
              f"loss {r['worst_case_loss_pct']:>6.2f}%  "
              f"safety {r['safety_score']:>6.2f}  "
              f"apy {r['expected_apy']:>5.2f}%  [{r['worst_scenario']}]")

    if run_mode:
        out = os.path.join(data_dir, "strategy_stress_ranking.json")
        _atomic_write_json(out, result)
        print(f"\n[strategy_stress_ranking] saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
