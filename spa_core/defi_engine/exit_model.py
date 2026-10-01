"""spa_core/defi_engine/exit_model.py — how fast, and how deep, each position can be exited (P1-3).

Two separate questions, never folded into one number:

* **Exit latency** — how long the protocol makes you wait (withdraw queue, cooldown, epoch). The ONE
  source is the adapter class constant ``EXIT_LATENCY_HOURS`` (maple 336 h, sUSDe 168 h, …), read
  from the class object in ``ADAPTER_REGISTRY`` without instantiating it. The legacy
  ``paper_trading/exit_liquidity.py`` keeps a hand-written MIRROR of these constants that has
  drifted (it lacks ``fluid_fusdc``, 20 % of the Conservative book, which it therefore counts as
  illiquid); this module does not read the mirror.
* **Exit depth** — how large the position is against the pool it must leave: ``position / live
  pool TVL`` from the orchestrator snapshot, only when that TVL is ``tvl_source == "live"``
  (ADR-053: a constant is not evidence). No live TVL ⇒ ``None``.

Thresholds and the book-level policy (≤ 25 % of the book in positions slower than 72 h) are
REUSED from ``spa_core.adapters.exit_latency_policy`` — not duplicated. Unknown latency counts as
illiquid, as that policy already rules: an undeclared exit can never pass silently.

Advisory: nothing here gates allocation (that would be a RiskPolicy axis — ``check_axes`` — and an
ADR). LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

from spa_core.adapters.exit_latency_policy import (
    ILLIQUID_THRESHOLD_HOURS,
    MAX_ILLIQUID_SHARE,
    classify_exit_latency,
)

WINDOW_24H = 24.0

#: Exit kind by mechanic — what the wait IS, for the passport reader.
_KIND = {
    "rwa_credit": "redemption queue (epoch-based)",
    "staked_synthetic": "unstake cooldown",
    "pt_fixed": "secondary market before maturity / par at maturity",
    "rwa_tbill": "issuer redemption",
    "vault_aggregator": "vault withdrawal",
}


#: ADR-533 sub-book positions: not adapters, so their exit is declared here with its reason.
#: PT: sold on the Pendle AMM before expiry (or held to par) — 24 h as the Pendle adapters declare;
#: loop: an unwind is a chain of swaps (sUSDe→USDe→PYUSD) and a repay — 24 h, the 7-day sUSDe
#: cooldown route is NOT assumed; the swap slippage is in loop_book's cost model.
SUB_BOOK_LATENCY_HOURS = {"pendle_pt_susds": 24.0, "morpho_susde_pyusd_loop": 24.0}


def latency_hours(key: object) -> Optional[float]:
    """Declared exit latency of a registry key, from its adapter class. ``None`` = undeclared."""
    from spa_core.adapters import ADAPTER_REGISTRY
    k = str(key or "").strip().lower()
    if k in SUB_BOOK_LATENCY_HOURS:
        return SUB_BOOK_LATENCY_HOURS[k]
    for entry in ADAPTER_REGISTRY:
        if entry[0] == k:
            v = getattr(entry[2], "EXIT_LATENCY_HOURS", None)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return None


def exposure_base(book: dict) -> tuple[float, str]:
    """Denominator for shares of a book: NAV when its cash is measured (cash counts), else the
    deployed notional — a sleeve has no cash field and its legs may exceed NAV (ADR-531)."""
    cash = book.get("cash_usd")
    nav = book.get("nav_usd")
    if isinstance(cash, (int, float)) and isinstance(nav, (int, float)) and nav > 0:
        return float(nav), "NAV (measured cash included)"
    deployed = sum(float(p.get("notional_usd") or 0.0) for p in book.get("positions") or [])
    return deployed, "deployed notional (book state carries no cash)"


def position_exit(key: str, notional_usd: float, pool: Optional[dict]) -> dict:
    from spa_core.defi_engine.mechanics import mechanic_of

    lat = latency_hours(key)
    bucket = classify_exit_latency(lat)
    mech = mechanic_of(key)
    kind = "instant withdrawal" if lat == 0.0 else _KIND.get(mech or "", "withdrawal")
    tvl = None
    if isinstance(pool, dict) and pool.get("tvl_source") == "live":
        t = pool.get("tvl_usd")
        tvl = float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None
    share = (notional_usd / tvl) if tvl else None
    return {
        "exit_latency_hours": lat,
        "latency_source": "adapter class EXIT_LATENCY_HOURS" if lat is not None else None,
        "bucket": bucket,                       # instant / liquid / illiquid / unknown
        "exit_kind": kind if lat is not None else "unknown — adapter declares no exit profile",
        "within_24h": (lat is not None and lat <= WINDOW_24H),
        "pool_tvl_usd": tvl,
        "share_of_pool_tvl": (round(share, 8) if share is not None else None),
        "depth_reason": None if tvl else "no LIVE pool TVL in the snapshot (ADR-053)",
    }


def book_exit(book: dict, pools: dict) -> dict:
    """Book-level exit profile: share exitable within 24 h, share slower than 72 h, policy verdict."""
    if not book.get("measured"):
        return {"measured": False, "reason": book.get("reason")}
    nav = book.get("nav_usd")
    if not isinstance(nav, (int, float)) or nav <= 0:
        return {"measured": False, "reason": "book NAV not measured"}
    cash = book.get("cash_usd")
    base, basis = exposure_base(book)
    rows = []
    for p in book.get("positions") or []:
        e = position_exit(p["protocol"], p["notional_usd"], pools.get(p["protocol"]))
        rows.append({"protocol": p["protocol"], "notional_usd": p["notional_usd"], **e})
    illiquid = sum(r["notional_usd"] for r in rows if r["bucket"] in ("illiquid", "unknown"))
    fast_legs = sum(r["notional_usd"] for r in rows if r["within_24h"])
    lat_known = [r for r in rows if r["exit_latency_hours"] is not None]
    w_mean = (sum(r["notional_usd"] * r["exit_latency_hours"] for r in lat_known) / base
              if lat_known and base else None)
    share_illiquid = illiquid / base if base else 0.0
    return {
        "measured": True,
        "share_basis": basis,
        # Cash is instantly exitable — but only a MEASURED cash counts; unknown cash ⇒ unmeasured.
        "share_exitable_24h": (round((float(cash) + fast_legs) / base, 6)
                               if isinstance(cash, (int, float)) and base else None),
        "share_exitable_24h_reason": None if isinstance(cash, (int, float)) else book.get("cash_reason"),
        "share_illiquid": round(share_illiquid, 6),
        "illiquid_threshold_hours": ILLIQUID_THRESHOLD_HOURS,
        "max_illiquid_share": MAX_ILLIQUID_SHARE,
        "policy_ok": share_illiquid <= MAX_ILLIQUID_SHARE + 1e-12,
        "illiquid_positions": sorted(r["protocol"] for r in rows if r["bucket"] in ("illiquid", "unknown")),
        "nav_weighted_exit_latency_hours": (round(w_mean, 2) if w_mean is not None else None),
        "max_share_of_pool_tvl": max((r["share_of_pool_tvl"] for r in rows
                                      if r["share_of_pool_tvl"] is not None), default=None),
        "positions": rows,
        "enforced": False,
        "note": "advisory — the ≤25 % illiquid policy is computed, not enforced (ADR-532)",
    }
