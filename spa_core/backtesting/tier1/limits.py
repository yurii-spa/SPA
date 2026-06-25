"""
spa_core/backtesting/tier1/limits.py — institutional risk-LIMITS checker (Tier-1).

PARALLEL MONITORING / VALIDATION OVERLAY — NOT a gate. This does NOT block trades and does
NOT touch RiskPolicy or any canonical execution module. It independently re-checks the live
portfolio (and each Tier-1-validated strategy's allocation) against a version-pinned set of
INSTITUTIONAL exposure limits and reports breaches, so an external allocator / auditor sees
the same constraints that RiskPolicy enforces, computed by a separate, transparent code path.

Limits (deterministic constants, version-pinned — change → new ADR):
  - per-protocol max weight: 40% for T1, 20% for T2 (matches RiskPolicy caps)
  - T2 aggregate ≤ 50% of portfolio
  - T3 aggregate ≤ 10% of portfolio
  - min cash buffer ≥ 5%
  - single-pool liquidity: a position ≤ 2% of that pool's TVL at the given AUM
  - effective concentration: Herfindahl-Hirschman Index (HHI = Σ weightᵢ²) ≤ threshold

Pure stdlib (math, json), deterministic, no network, atomic writes (tmp + os.replace).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math  # noqa: F401  (stdlib-only invariant; available for any numeric extension)
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1.tail_risk import PROTOCOL_TIER
from spa_core.utils.atomic import atomic_save

LIMITS_VERSION = "v1.0"

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_OUT = _DATA / "tier1_limits.json"
_BEE = _DATA / "bee" / "defillama_apy_history.json"
_POSITIONS = _DATA / "current_positions.json"
_PAPER_STATUS = _DATA / "paper_trading_status.json"
_VERDICT = _DATA / "tier1_verdict.json"
_RESULTS = _DATA / "mass_tournament_results.json"

# ── institutional limits (version-pinned) ────────────────────────────────────────────────
PER_PROTOCOL_MAX = {"T1": 0.40, "T2": 0.20, "T3": 0.10, "_default": 0.20}
TIER_AGGREGATE_MAX = {"T2": 0.50, "T3": 0.10}
MIN_CASH = 0.05
# a single position must not exceed this share of its pool's TVL at the evaluated AUM
SINGLE_POOL_LIQUIDITY_PCT = 0.02
# effective-concentration ceiling. HHI = Σ wᵢ². 1/HHI ≈ effective number of holdings;
# 0.25 ⇒ at least ~4 effective positions (no single dominant book). cash excluded from HHI.
HHI_MAX = 0.25


def _tier(protocol: str) -> str:
    return PROTOCOL_TIER.get(protocol, "T2")


def _load_tvl() -> Dict[str, float]:
    """{protocol: tvl_usd} from the real DeFiLlama bee cache (single-pool liquidity check)."""
    try:
        c = json.loads(_BEE.read_text())
        return {k: float(v.get("tvl_usd") or 0.0)
                for k, v in (c.get("pool_results") or {}).items() if isinstance(v, dict)}
    except Exception:
        return {}


def _normalize(allocation: Dict[str, float]) -> Dict[str, float]:
    """Coerce an allocation to non-negative weights summing to 1.

    Accepts fractions (sum≈1, possibly with implicit cash) or raw USD amounts. A 'cash' key
    is honoured if present; otherwise any shortfall below 1.0 is treated as cash."""
    raw = {k: float(v) for k, v in (allocation or {}).items() if v and float(v) > 0}
    total = sum(raw.values())
    if total <= 0:
        return {"cash": 1.0}
    weights = {k: v / total for k, v in raw.items()}
    weights.setdefault("cash", 0.0)
    return weights


def _hhi(weights: Dict[str, float]) -> float:
    """Herfindahl-Hirschman Index over non-cash weights: Σ wᵢ²."""
    return round(sum(w * w for k, w in weights.items() if k != "cash"), 6)


def check_allocation(allocation: Dict[str, float], aum_usd: float = 100000.0,
                     tvl_map: Optional[Dict[str, float]] = None) -> dict:
    """Check one allocation against the institutional limits.

    `allocation` may be fractional weights or USD amounts (a 'cash' key is honoured; any
    shortfall under 1.0 becomes cash). Returns breaches, pass/fail, HHI, tier weights, and
    the max single-protocol weight. This is a REPORT — it never blocks anything."""
    if tvl_map is None:
        tvl_map = _load_tvl()
    weights = _normalize(allocation)
    cash_w = weights.get("cash", 0.0)
    protocol_w = {k: v for k, v in weights.items() if k != "cash"}

    tier_weights: Dict[str, float] = {}
    for p, w in protocol_w.items():
        tier_weights[_tier(p)] = round(tier_weights.get(_tier(p), 0.0) + w, 6)

    hhi = _hhi(weights)
    max_protocol = max(protocol_w.items(), key=lambda kv: kv[1], default=(None, 0.0))
    max_protocol_weight = round(max_protocol[1], 6)

    breaches: List[dict] = []

    # 1. per-protocol max weight (T1 40% / T2 20% / T3 10%)
    for p, w in sorted(protocol_w.items(), key=lambda kv: -kv[1]):
        cap = PER_PROTOCOL_MAX.get(_tier(p), PER_PROTOCOL_MAX["_default"])
        if w > cap + 1e-9:
            breaches.append({"limit": "per_protocol_max", "protocol": p, "tier": _tier(p),
                             "value": round(w, 6), "threshold": cap, "severity": "HIGH"})

    # 2. tier-aggregate caps (T2 ≤ 50%, T3 ≤ 10%)
    for tier, cap in TIER_AGGREGATE_MAX.items():
        agg = tier_weights.get(tier, 0.0)
        if agg > cap + 1e-9:
            breaches.append({"limit": f"{tier.lower()}_aggregate_max", "tier": tier,
                             "value": round(agg, 6), "threshold": cap, "severity": "HIGH"})

    # 3. min cash buffer
    if cash_w < MIN_CASH - 1e-9:
        breaches.append({"limit": "min_cash", "value": round(cash_w, 6),
                         "threshold": MIN_CASH, "severity": "MEDIUM"})

    # 4. effective concentration (HHI)
    if hhi > HHI_MAX + 1e-9:
        breaches.append({"limit": "hhi_max", "value": hhi, "threshold": HHI_MAX,
                         "severity": "MEDIUM"})

    # 5. single-pool liquidity (position ≤ 2% of pool TVL at this AUM); skip protocols w/o TVL
    for p, w in sorted(protocol_w.items(), key=lambda kv: -kv[1]):
        tvl = tvl_map.get(p, 0.0)
        if tvl <= 0:
            continue
        position_usd = w * aum_usd
        share = position_usd / tvl
        if share > SINGLE_POOL_LIQUIDITY_PCT + 1e-12:
            breaches.append({"limit": "single_pool_liquidity", "protocol": p,
                             "value": round(share, 6), "threshold": SINGLE_POOL_LIQUIDITY_PCT,
                             "position_usd": round(position_usd, 2), "tvl_usd": round(tvl, 0),
                             "severity": "LOW"})

    return {
        "version": LIMITS_VERSION,
        "aum_usd": round(float(aum_usd), 2),
        "passes": len(breaches) == 0,
        "breach_count": len(breaches),
        "breaches": breaches,
        "hhi": hhi,
        "effective_holdings": round(1.0 / hhi, 2) if hhi > 0 else None,
        "tier_weights": tier_weights,
        "cash_weight": round(cash_w, 6),
        "max_protocol": max_protocol[0],
        "max_protocol_weight": max_protocol_weight,
        "n_protocols": len(protocol_w),
    }


def _current_portfolio() -> Dict[str, float]:
    """Live portfolio as USD-amount allocation (positions + cash) from canonical state."""
    alloc: Dict[str, float] = {}
    try:
        pos = json.loads(_POSITIONS.read_text())
        for p, usd in (pos.get("positions") or {}).items():
            alloc[p] = float(usd or 0.0)
        cash = pos.get("cash_usd")
    except Exception:
        cash = None
    if cash is None:
        try:
            st = json.loads(_PAPER_STATUS.read_text())
            for p, usd in (st.get("current_positions") or {}).items():
                alloc.setdefault(p, float(usd or 0.0))
            cap = float(st.get("current_equity") or 0.0)
            cash = cap - sum(alloc.values()) if cap > 0 else None
        except Exception:
            cash = None
    if cash and cash > 0:
        alloc["cash"] = float(cash)
    return alloc


def _current_aum() -> float:
    for path, key in ((_POSITIONS, "capital_usd"), (_PAPER_STATUS, "current_equity")):
        try:
            v = float(json.loads(path.read_text()).get(key) or 0.0)
            if v > 0:
                return v
        except Exception:
            continue
    return 100000.0


def _validated_strategy_allocations() -> List[dict]:
    """Validated strategy ids (tier1_verdict) → their allocations (mass_tournament_results)."""
    try:
        verdict = json.loads(_VERDICT.read_text())
        validated_ids = {e.get("id") for e in verdict.get("leaderboard_tier1", [])
                         if e.get("validated")}
    except Exception:
        validated_ids = set()
    try:
        results = json.loads(_RESULTS.read_text())
        by_id = {e.get("id"): (e.get("allocation") or {})
                 for e in results.get("leaderboard", [])}
    except Exception:
        by_id = {}
    out = []
    for sid in sorted(validated_ids):
        out.append({"id": sid, "allocation": by_id.get(sid, {})})
    return out


def _atomic_write(path: Path, payload: dict) -> None:
    atomic_save(payload, str(path))


def build_report(write: bool = True) -> dict:
    """Check the CURRENT live portfolio + each validated strategy's allocation against limits.

    Writes data/tier1_limits.json atomically. Returns the full report dict."""
    tvl_map = _load_tvl()
    aum = _current_aum()
    current_alloc = _current_portfolio()
    current = check_allocation(current_alloc, aum_usd=aum, tvl_map=tvl_map)

    strategies = []
    for s in _validated_strategy_allocations():
        chk = check_allocation(s["allocation"], aum_usd=aum, tvl_map=tvl_map)
        strategies.append({"id": s["id"], "passes": chk["passes"],
                           "breach_count": chk["breach_count"], "hhi": chk["hhi"],
                           "tier_weights": chk["tier_weights"],
                           "max_protocol_weight": chk["max_protocol_weight"],
                           "breaches": chk["breaches"]})

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_limits_overlay",
        "llm_forbidden": True,
        "is_gate": False,
        "version": LIMITS_VERSION,
        "limits": {
            "per_protocol_max": PER_PROTOCOL_MAX,
            "tier_aggregate_max": TIER_AGGREGATE_MAX,
            "min_cash": MIN_CASH,
            "single_pool_liquidity_pct": SINGLE_POOL_LIQUIDITY_PCT,
            "hhi_max": HHI_MAX,
        },
        "aum_usd": aum,
        "current_portfolio": current,
        "validated_strategies": strategies,
        "summary": {
            "current_passes": current["passes"],
            "current_breaches": current["breach_count"],
            "strategies_checked": len(strategies),
            "strategies_passing": sum(1 for s in strategies if s["passes"]),
        },
        "note": ("Parallel monitoring overlay — informational only. RiskPolicy remains the "
                 "single deterministic gate that governs live exposure; this never blocks."),
    }
    if write:
        _atomic_write(_OUT, report)
    return report


if __name__ == "__main__":
    rep = build_report(write=True)
    cur = rep["current_portfolio"]
    print(f"Tier-1 Limits Overlay {LIMITS_VERSION}  (AUM ${rep['aum_usd']:,.0f})")
    print(f"  current portfolio: {'PASS' if cur['passes'] else 'BREACH'} "
          f"({cur['breach_count']} breach(es))")
    print(f"  HHI={cur['hhi']}  eff_holdings={cur['effective_holdings']}  "
          f"max_protocol={cur['max_protocol']}@{cur['max_protocol_weight']:.2%}  "
          f"cash={cur['cash_weight']:.2%}")
    print(f"  tier_weights={cur['tier_weights']}")
    for b in cur["breaches"]:
        print(f"  ! {b['severity']:<6} {b['limit']}: value={b['value']} > "
              f"threshold={b['threshold']}"
              + (f"  ({b.get('protocol')})" if b.get("protocol") else ""))
    s = rep["summary"]
    print(f"  validated strategies: {s['strategies_passing']}/{s['strategies_checked']} pass")
    print(f"  -> wrote {_OUT}")
