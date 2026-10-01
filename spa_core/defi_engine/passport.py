"""spa_core/defi_engine/passport.py — the Position Passport: one derived record per held position.

The audit (§C #1) asked for a per-position record a reader can trust: what the position is, who pays
its yield, how it is exited, what loss it may cost, how well it is evidenced and watched. It is a
DERIVED VIEW: every field is computed from the book, the tier authority, the mechanic axis, the exit
model, the loss budget and the coverage report at build time. Nothing reads a passport back as a
source — it is rebuilt from scratch every run (``engine.publish``), so it cannot drift.

Evidence level: every book is a paper track — ``L3 · paper track`` (docs/37), never L6.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

from spa_core.defi_engine import PASSPORT_SCHEMA_VERSION
from spa_core.defi_engine import mechanics as M
from spa_core.defi_engine.exit_model import exposure_base, position_exit
from spa_core.defi_engine.tiers import authority

EVIDENCE_LEVEL = "L3 · paper track"


def build_passport(book_id: str, book: dict, position: dict, pools: dict,
                   budget: dict, coverage_row: Optional[dict]) -> dict:
    key = position["protocol"]
    base, basis = exposure_base(book)
    mech = M.mechanic_of(key)
    params = M.mechanic_params(mech) or {}
    risk = M.position_risk(key)
    pool = pools.get(key)
    return {
        "schema": PASSPORT_SCHEMA_VERSION,
        "id": f"{book_id}:{key}",
        "book": book_id,
        "engine": book.get("engine"),
        "protocol": key,
        "position": {
            "notional_usd": position["notional_usd"],
            "share_of_book": (round(position["notional_usd"] / base, 6) if base else None),
            "share_basis": basis,
        },
        "what_it_is": {
            "mechanic": mech or "unknown",
            "underlying": M.underlying_of(key),
            "price_delta_neutral": M.price_delta_neutral(key),
            "stamped_delta_neutral": position.get("stamped_delta_neutral"),
        },
        "who_pays": params.get("who_pays") or "unknown — mechanic not classified",
        "yield": {
            "spot_apy_pct": position.get("apy_pct"),
            "definition": "pool_spot_apy" if book_id == "conservative" else "book observed rate",
            "source": position.get("apy_source"),
            "live": position.get("apy_live"),
            "pool_id": (pool or {}).get("pool_id"),
        },
        "risk": {
            "protocol_tier": authority(key),
            "tier_source": "adapters.tier_map (single tier authority)",
            **risk,
            "mechanic_advisory_cap": params.get("cap"),
            "parameter_status": M.PARAMETER_STATUS,
        },
        "exit": position_exit(key, position["notional_usd"], pool),
        "loss_budget": {k: budget.get(k) for k in ("budget_pct", "status", "consumed_share_of_budget",
                                                    "bound_by_enforced_stop", "nearest_enforced_stop_pct")},
        "gate": (book.get("gate") or {}).get("gate"),
        "monitoring": ({"uncovered": coverage_row.get("uncovered"),
                        "unmeasured": coverage_row.get("unmeasured"),
                        "rate_watch": coverage_row.get("rate_watch")} if coverage_row else None),
        "data_needs": params.get("data_needs"),
        "evidence_level": EVIDENCE_LEVEL,
    }
