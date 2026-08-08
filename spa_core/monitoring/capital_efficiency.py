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
from spa_core.risk.tvl_floor import floor_is_resolved, floor_reason  # noqa: E402

_POS = _ROOT / "data" / "current_positions.json"
_APY = _ROOT / "data" / "apy_ranking.json"
_RATIONALE = _ROOT / "data" / "allocation_rationale.json"
_OUT = _ROOT / "data" / "capital_efficiency.json"

# idle above (min_cash + this) is flagged. Small band so we don't cry wolf on normal drift.
_IDLE_TOLERANCE = 0.03  # 3 percentage points over the min-cash floor

# Y2 (ADR-055): unexplained remainder ≤ this (% of capital) after a COMPLETE cash
# attribution is tolerated (EXPLAINED); above it the LAZY alarm stands.
_UNEXPLAINED_TOLERANCE_PCT = 2.0
# An attribution older than this cannot vouch for today's book (cycle is daily;
# 36h covers one missed run without letting a week-old story silence the alarm).
_RATIONALE_MAX_AGE_H = 36.0


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
            # MP-011 floor. NOT defaulted to a literal below: an unresolved floor
            # is an UNMEASURED dimension of "may this pool take money", and a
            # literal here would be a second copy of RiskPolicy's number.
            "min_tvl_usd": (float(c.min_tvl_usd)
                            if getattr(c, "min_tvl_usd", None) is not None else None),
        }
    except Exception:  # noqa: BLE001
        return {"min_cash_pct": 0.05, "t1_cap": 0.4, "t2_cap": 0.2, "min_apy": 1.0,
                "min_tvl_usd": None}


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


def _live_apys(apy_doc) -> dict[str, tuple[float, str, object]]:
    """protocol → (apy_pct, tier, tvl_raw) from apy_ranking's `by_apy` rows.

    ``tvl_raw`` is passed through VERBATIM (including ``None``): "we did not
    measure the size" and "the size is zero" are different states of the book and
    only the floor rule (:mod:`spa_core.risk.tvl_floor`) may collapse them.
    """
    if not isinstance(apy_doc, dict):
        return {}
    rows = apy_doc.get("by_apy") or apy_doc.get("by_risk_adjusted") or []
    if not rows:
        for k in apy_doc:  # fallback: first list in the doc
            if isinstance(apy_doc[k], list):
                rows = apy_doc[k]
                break
    out: dict[str, tuple[float, str, object]] = {}
    for r in rows or []:
        if isinstance(r, dict):
            n = r.get("protocol") or r.get("name")
            tier = str(r.get("tier") or "").upper()
            tvl = r.get("tvl_usd") if "tvl_usd" in r else r.get("tvl")
            try:
                out[str(n)] = (
                    float(r.get("apy_pct") if r.get("apy_pct") is not None else r.get("apy")),
                    tier, tvl)
            except Exception:  # noqa: BLE001
                pass
    return out


def _cash_attribution() -> dict | None:
    """Fresh, complete Y2 cash attribution from allocation_rationale.json, or None.

    None ⇒ the caller falls back to the legacy headroom heuristic (fail-closed:
    a missing / stale / incomplete attribution never vouches for the book).
    """
    doc = _load(_RATIONALE)
    if not isinstance(doc, dict):
        return None
    cash = doc.get("cash")
    if not isinstance(cash, dict) or "components" not in cash:
        return None  # pre-Y2 artifact shape — cannot vouch
    try:
        from datetime import datetime, timezone
        gen = datetime.fromisoformat(str(doc.get("generated_at")).replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001 — undatable artifact cannot vouch
        return None
    if age_h > _RATIONALE_MAX_AGE_H:
        return None
    return cash


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
    # MP-011 (карточка 07.08, замер 08.08): «пригодная комната» обязана значить то
    # же, что у аллокатора. Раньше здесь спрашивали только про APY и тир, поэтому
    # в headroom стояли aerodrome_usdc_lp (TVL 0.0, доходность — статический
    # литерал 8.5 %) и moonwell_base (TVL $1.41M против порога $5M) — комната,
    # которую финансировать НЕЛЬЗЯ, вменялась аллокатору как лень.
    excluded: list[str] = []
    unmeasured_rooms: list[str] = []
    floor = cfg.get("min_tvl_usd")
    for proto, (apy, feed_tier, tvl_raw) in apys.items():
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
        if room <= 1e-6:
            continue
        floor_ok, floor_why = floor_reason(tvl_raw, floor)
        if not floor_ok:
            if len(excluded) < 8:
                excluded.append(f"{proto}(+{room*100:.0f}% @ {apy:.1f}%): {floor_why}")
            # "измерили и мал" ≠ "не измеряли". Первое — структурная причина
            # (кэш держать правильно), второе — дыра в наблюдении, и выдать её
            # за структурность значит погасить тревогу потерей входа.
            if not floor_why.startswith("tvl_below_floor"):
                unmeasured_rooms.append(proto)
            continue
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
    # Same fail-CLOSED shape for the floor: without RiskPolicy's threshold we
    # cannot tell "no qualifying headroom" from "did not check", and the second
    # must never be printed as the first (that is how an alarm goes quiet by
    # losing an input rather than by the book improving).
    floor_ok = floor_is_resolved(floor)
    # …и то же самое, когда порог есть, но мерить было нечего: комнаты остались
    # только у пулов с ненаблюдённым размером. Молчаливое "headroom=0 ⇒ OK"
    # объявило бы дыру в наблюдении структурной причиной.
    size_blind = headroom <= 1e-6 and bool(unmeasured_rooms)
    if idle_excess > _IDLE_TOLERANCE and (not (feed_ok and floor_ok) or size_blind):
        verdict = "UNKNOWN"
    else:
        verdict = "WARNING" if lazy else "OK"
    forgone_bps = round(deployable_now * best_apy * 100) if lazy else 0  # deployable × APY, in bps
    reason = (
        "LAZY: {:.0f}% deployable capital idle at 0% while qualifying T1/T2 headroom exists"
        .format(deployable_now * 100)
        if lazy else
        ("structural: idle within tolerance or no qualifying headroom (caps exhausted) — holding cash is correct"
         if verdict == "OK" else
         ("unknown: TVL floor unresolved — eligibility not measured (fail-closed)"
          if not floor_ok else
          ("unknown: headroom exists only in pools whose SIZE was never observed "
           "({}) — not measured is not the same as structural (fail-closed)".format(
               ", ".join(sorted(unmeasured_rooms)[:5]))
           if size_blind else "unknown")))
    )

    # ── Y2 (ADR-055): the cycle's own cash attribution outranks the heuristic ──
    # The rationale writer decomposes the SAME cash into named binders with USD +
    # forgone bps, fail-closed (missing input ⇒ UNCHECKED, not zero). When a fresh,
    # COMPLETE attribution exists it is the better-informed witness:
    #   * status "explained"            → EXPLAINED, not LAZY (cash is a logged decision);
    #   * unexplained ≤ 2% of capital   → EXPLAINED (small remainder, named split shown);
    #   * unexplained > 2% of capital   → LAZY stands, now with the honest number;
    #   * incomplete / stale / missing  → this heuristic stays in force (fail-closed).
    attribution = _cash_attribution()
    attribution_status = None
    unexplained_pct = None
    if isinstance(attribution, dict):
        attribution_status = str(attribution.get("status") or "")
        if attribution_status in ("explained", "UNEXPLAINED_CASH"):
            raw_unexpl = attribution.get("unexplained_pct")
            unexplained_pct = float(raw_unexpl) if isinstance(raw_unexpl, (int, float)) else None
        if attribution_status == "explained":
            verdict = "EXPLAINED"
            reason = "cash fully attributed by the cycle (see cash_attribution) — a logged decision, not LAZY"
            forgone_bps = 0
        elif attribution_status == "UNEXPLAINED_CASH" and unexplained_pct is not None:
            comp = next((c for c in attribution.get("components", [])
                         if isinstance(c, dict) and c.get("kind") == "unexplained_deployable"), {})
            fb = comp.get("forgone_bps_yr")
            if unexplained_pct > _UNEXPLAINED_TOLERANCE_PCT:
                verdict = "WARNING"
                forgone_bps = round(float(fb)) if isinstance(fb, (int, float)) else forgone_bps
                reason = (
                    "LAZY: {:.1f}% of capital idle UNEXPLAINED after attribution "
                    "(fundable headroom under every cap left unused)".format(unexplained_pct)
                )
                # ADR-055: the alarm keeps its number, but stops being anonymous
                # when the cycle recorded WHY the budget was freed. The alarm is
                # NOT downgraded — the dollars are still placeable elsewhere.
                _causes = comp.get("caused_by") or attribution.get("policy_refusals") or []
                _named = ["{}:{} (${:,.0f} removed from target)".format(
                    c.get("protocol"), c.get("reason"),
                    float(c.get("usd_removed_from_target") or 0.0))
                    for c in _causes if isinstance(c, dict) and c.get("protocol")]
                if _named:
                    reason += " — caused by: " + "; ".join(_named) + \
                              "; freed budget was not re-filled"
            else:
                verdict = "EXPLAINED"
                reason = (
                    "cash attributed; unexplained remainder {:.1f}% ≤ {:.1f}% tolerance"
                    .format(unexplained_pct, _UNEXPLAINED_TOLERANCE_PCT)
                )
                forgone_bps = 0
        # attribution_incomplete / error → legacy verdict stands (fail-closed).

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
        # Rooms that exist but may NOT take money, with the reason named. An
        # excluded pool is a fact about the book, not a silent deletion.
        "headroom_excluded": excluded,
        "headroom_size_unmeasured": sorted(unmeasured_rooms),
        "min_tvl_usd": floor,
        "verdict": verdict,
        "reason": reason,
        "tolerance_pct": _IDLE_TOLERANCE,
        # Y2 (ADR-055) — the attribution this verdict leaned on (None ⇒ legacy heuristic).
        "attribution_status": attribution_status,
        "cash_unexplained_pct": unexplained_pct,
        "cash_attribution": (attribution.get("components") if isinstance(attribution, dict) else None),
        # ADR-053 refusals the cycle recorded (provenance of the freed budget).
        "cash_policy_refusals": (attribution.get("policy_refusals")
                                 if isinstance(attribution, dict) else None),
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
    if res.get("cash_attribution"):
        for c in res["cash_attribution"]:
            print("    cash · {}: ${:,.0f} ({}%){}".format(
                c.get("kind"), c.get("usd", 0), c.get("pct"),
                " [UNCHECKED]" if c.get("status") == "UNCHECKED" else ""))
    # EXPLAINED = attributed idle cash is a logged decision (ADR-055), same green as OK.
    return {"OK": 0, "EXPLAINED": 0, "WARNING": 1}.get(v, 2)


if __name__ == "__main__":
    raise SystemExit(main())
