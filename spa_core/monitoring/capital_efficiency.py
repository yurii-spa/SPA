#!/usr/bin/env python3
"""Capital-efficiency guard (Q1-13, owner-flagged 2026-07-12) — the missing check.

The desk measures RISK world-class but had ZERO check on capital efficiency: the live book can sit
with deployable capital idle at 0% cash and nothing flags it (observed 2026-07-12: ~20% idle vs a 5%
min-cash floor, with qualifying T1 headroom unused). This guard closes that governance gap.

Read-only / advisory / deterministic / stdlib-only / **fail-CLOSED** / **no LLM**. It does NOT touch
the money-path, RiskPolicy, or the live track — it only READS the current book + the live feed and
writes a verdict. The allocator re-fill that actually deploys the cash is a separate, owner-timed
money-path change (docs/CAPITAL_EFFICIENCY_GUARD.md part A, owner chose post-go-live).

Honesty core — distinguish:
  * STRUCTURAL cash  → the tier/per-protocol caps genuinely leave no qualifying headroom → verdict OK
                       (holding cash is correct, NOT a fault).
  * LAZY cash        → idle_excess exceeds tolerance AND qualifying headroom exists (a whitelisted
                       protocol under its cap, live APY ≥ min) → verdict WARNING (we are silently
                       under-earning; the allocator left deployable capital idle).

Emits ``data/capital_efficiency.json`` (atomic). ``agent_health`` reads it and escalates a WARNING
(same pattern as Q1-10 resilience). Exit 0 ⇔ OK, 1 ⇔ WARNING, 2 ⇔ UNKNOWN (fail-closed).

    python3 -m spa_core.monitoring.capital_efficiency
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402

_POS = _ROOT / "data" / "current_positions.json"
_APY = _ROOT / "data" / "apy_ranking.json"
_OUT = _ROOT / "data" / "capital_efficiency.json"

# idle above (min_cash + this) is flagged. Small band so we don't cry wolf on normal drift.
_IDLE_TOLERANCE = 0.03  # 3 percentage points over the min-cash floor


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 — fail-closed: caller treats None as UNKNOWN
        return None


def _config():
    """RiskPolicy caps (read-only). Fail-closed to conservative literals if unavailable."""
    try:
        from spa_core.risk.policy import RiskConfig
        c = RiskConfig()
        return {
            "min_cash_pct": float(c.min_cash_pct),
            "t1_cap": float(c.max_concentration_t1),
            "t2_cap": float(c.max_concentration_t2),
            "min_apy": float(c.min_apy_for_new_position),
        }
    except Exception:  # noqa: BLE001
        return {"min_cash_pct": 0.05, "t1_cap": 0.4, "t2_cap": 0.2, "min_apy": 1.0}


def _tier_of(proto: str) -> str:
    try:
        from spa_core.adapters.tier_map import tier_of
        return str(tier_of(proto) or "").upper()
    except Exception:  # noqa: BLE001
        return ""


def _current_weights(pos: dict) -> dict[str, float]:
    """protocol → weight fraction of capital, from the positions list. Robust to key naming."""
    cap = float(pos.get("capital_usd") or pos.get("current_equity_usd") or 0) or 0.0
    out: dict[str, float] = {}
    if cap <= 0:
        return out
    items = pos.get("positions") or pos.get("positions_detail") or []
    if isinstance(items, dict):
        items = [{"protocol": k, "usd": v} for k, v in items.items()]
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = it.get("protocol") or it.get("name") or it.get("pool")
        usd = it.get("usd") or it.get("allocation_usd") or it.get("value_usd") or it.get("amount_usd")
        if name is None or usd is None:
            # maybe already a weight
            w = it.get("weight") or it.get("pct")
            if name is not None and w is not None:
                out[str(name)] = out.get(str(name), 0.0) + float(w) / (100.0 if float(w) > 1.5 else 1.0)
            continue
        try:
            out[str(name)] = out.get(str(name), 0.0) + float(usd) / cap
        except Exception:  # noqa: BLE001
            continue
    return out


def _live_apys(apy_doc) -> dict[str, tuple[float, str]]:
    """protocol → (apy_pct, tier). Reads apy_ranking's `by_apy` rows (field `apy_pct`, plus `tier`)."""
    if not isinstance(apy_doc, dict):
        return {}
    rows = apy_doc.get("by_apy") or apy_doc.get("by_risk_adjusted") or []
    if not rows:
        for k in apy_doc:  # fallback: first list in the doc
            if isinstance(apy_doc[k], list):
                rows = apy_doc[k]
                break
    out: dict[str, tuple[float, str]] = {}
    for r in rows or []:
        if isinstance(r, dict):
            n = r.get("protocol") or r.get("name")
            tier = str(r.get("tier") or "").upper()
            try:
                out[str(n)] = (float(r.get("apy_pct") if r.get("apy_pct") is not None else r.get("apy")), tier)
            except Exception:  # noqa: BLE001
                pass
    return out


def assess() -> dict:
    pos = _load(_POS)
    cfg = _config()
    if not isinstance(pos, dict):
        return {"verdict": "UNKNOWN", "reason": "positions unreadable (fail-closed)", **cfg}

    cap = float(pos.get("capital_usd") or pos.get("current_equity_usd") or 0) or 0.0
    cash = float(pos.get("cash_usd") or 0)
    deployed = float(pos.get("deployed_usd") or (cap - cash if cap else 0))
    if cap <= 0:
        return {"verdict": "UNKNOWN", "reason": "no capital base (fail-closed)", **cfg}

    cash_pct = round(cash / cap, 6)
    deployed_pct = round(deployed / cap, 6)
    idle_excess = round(max(0.0, cash_pct - cfg["min_cash_pct"]), 6)

    weights = _current_weights(pos)
    apys = _live_apys(_load(_APY))

    # Qualifying deployable headroom: whitelisted T1/T2 protocols with a live APY ≥ min, under their
    # per-protocol cap. Structural (caps exhausted) ⇒ no headroom ⇒ OK; headroom present ⇒ LAZY.
    headroom = 0.0
    best_apy = 0.0
    contributors: list[str] = []
    for proto, (apy, feed_tier) in apys.items():
        if apy < cfg["min_apy"]:
            continue
        tier = feed_tier or _tier_of(proto)
        if tier == "T1":
            cap_p = cfg["t1_cap"]
        elif tier == "T2":
            cap_p = cfg["t2_cap"]
        else:
            continue  # T3/unknown: don't count as "safe deployable headroom"
        room = max(0.0, cap_p - weights.get(proto, 0.0))
        if room > 1e-6:
            headroom += room
            if apy > best_apy:
                best_apy = apy
            if len(contributors) < 6:
                contributors.append(f"{proto}(+{room*100:.0f}% @ {apy:.1f}%)")

    deployable_now = min(headroom, idle_excess)  # how much of the idle cash could actually be placed
    lazy = idle_excess > _IDLE_TOLERANCE and deployable_now > _IDLE_TOLERANCE
    # Fail-CLOSED: an idle book we CANNOT prove is structural (empty/unreadable APY feed → headroom
    # undetermined) must NOT be declared OK. Idle over tolerance + no usable feed ⇒ UNKNOWN, not OK.
    feed_ok = len(apys) > 0
    if idle_excess > _IDLE_TOLERANCE and not feed_ok:
        verdict = "UNKNOWN"
    else:
        verdict = "WARNING" if lazy else "OK"
    forgone_bps = round(deployable_now * best_apy * 100) if lazy else 0  # deployable × APY, in bps

    return {
        "check": "capital_efficiency",
        "deterministic": True,
        "llm_forbidden": True,
        "advisory": True,
        "capital_usd": cap,
        "deployed_pct": deployed_pct,
        "cash_pct": cash_pct,
        "min_cash_pct": cfg["min_cash_pct"],
        "idle_excess_pct": idle_excess,
        "deployable_headroom_pct": round(headroom, 6),
        "deployable_now_pct": round(deployable_now, 6),
        "best_qualifying_apy_pct": round(best_apy, 4),
        "forgone_yield_bps_est": forgone_bps,
        "headroom_contributors": contributors,
        "verdict": verdict,
        "reason": (
            "LAZY: {:.0f}% deployable capital idle at 0% while qualifying T1/T2 headroom exists"
            .format(deployable_now * 100)
            if lazy else
            ("structural: idle within tolerance or no qualifying headroom (caps exhausted) — holding cash is correct"
             if verdict == "OK" else "unknown")
        ),
        "tolerance_pct": _IDLE_TOLERANCE,
    }


def main() -> int:
    res = assess()
    try:
        atomic_save(res, str(_OUT))
    except Exception as e:  # noqa: BLE001
        print(f"[capital_efficiency] write failed: {e}", file=sys.stderr)
    v = res.get("verdict")
    print(f"[capital_efficiency] {v}: {res.get('reason')}")
    if v == "WARNING":
        print(f"  cash {res['cash_pct']*100:.0f}% (min {res['min_cash_pct']*100:.0f}%) · "
              f"deployable {res['deployable_now_pct']*100:.0f}% @ up to {res['best_qualifying_apy_pct']:.1f}% "
              f"→ ~{res['forgone_yield_bps_est']}bps/yr forgone")
        for c in res.get("headroom_contributors", []):
            print(f"    · {c}")
    return {"OK": 0, "WARNING": 1}.get(v, 2)


if __name__ == "__main__":
    raise SystemExit(main())
