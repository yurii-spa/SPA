"""
spa_core/paper_trading/sleeve_capture.py — CAPTURED-PAPER FixedCarry sleeve (WS1.3).

Promote the VALIDATED rates-desk FixedCarry edge from advisory→CAPTURED-PAPER: a BOUNDED
paper allocation that actually accrues differentiated (non-lending) carry yield, so the desk
earns a differentiated sleeve instead of only market-rate lending.

This mirrors the Engine B/C HY/LP pattern EXACTLY (spa_core/paper_trading/hy_cycle.py +
sleeve_yield.py): a SEPARATE virtual paper book ON TOP of — and BYTE-DISJOINT from — the
go-live $100k evidenced track. It is NEVER co-mingled into data/equity_curve_daily.json and it
NEVER touches spa_core/paper_trading/track_evidence.py / the go-live track. Flipping it to REAL
capital is OWNER-GATED (custody) — this module only ever moves VIRTUAL paper dollars.

WHAT IT CAPTURES (honest, real-APY, fail-CLOSED):
  - The captured book holds a BOUNDED notional (default ≤5% of a small captured-capital base,
    NOT the $100k go-live capital). The bound is enforced two ways: (1) a hard fraction cap, and
    (2) a deterministic RiskPolicy.check_new_position gate (T2 carry — respects the T2 caps).
  - It accrues daily carry at the FixedCarry sleeve's REAL live net APY, read from the validated
    forward track at data/rates_desk/paper/rates_desk_fixed_carry_state.json (the size-weighted
    LOCKED fixed PT rate the sleeve actually holds — the same rate the validated sleeve's own
    step() accrues at). NO fabricated number: if the live carry is missing / NaN / the sleeve
    holds no open book, the captured book DOES NOT accrue (fail-CLOSED) and the absence is
    observable in the state.

GUARDRAILS (un-negotiable):
  * SEPARATE BOOK — data/captured_sleeves/rates_fixed_carry_capture.json. The go-live equity
    curve stays byte-identical (red-teamed via md5).
  * RiskPolicy APPROVES the captured allocation (deterministic, LLM-FORBIDDEN). approved=False
    ⇒ no capture.
  * advisory/honest labeling preserved (is_advisory / capture_mode flags in state).
  * stdlib only, deterministic, atomic writes, fail-CLOSED.

LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from spa_core.utils import clock
from spa_core.utils.atomic import atomic_load, atomic_save

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The captured book lives in its OWN directory, NEVER under the go-live track files.
_CAPTURE_PATH = _PROJECT_ROOT / "data" / "captured_sleeves" / "rates_fixed_carry_capture.json"

# The VALIDATED forward-track state the captured book sources its REAL live carry from.
_RATES_STATE_PATH = (
    _PROJECT_ROOT / "data" / "rates_desk" / "paper" / "rates_desk_fixed_carry_state.json"
)

CAPTURE_VERSION = "sleeve_capture_v1.0"
SLEEVE_ID = "rates_desk_fixed_carry_capture"

# ── Bounded notional ────────────────────────────────────────────────────────────────────────
# Captured-capital base for the SEPARATE book — a small virtual sleeve, NOT the $100k go-live
# capital (so the go-live track is structurally untouched). The captured allocation is bounded
# to MAX_NOTIONAL_FRAC of this base.
CAPTURE_CAPITAL_BASE = 100_000.0      # virtual base for the captured sleeve's own book
MAX_NOTIONAL_FRAC = 0.05              # ≤5% notional — the bounded captured allocation

# Honest carry bounds (decimal APY). The captured book NEVER accrues above the RiskPolicy APY
# ceiling, and NEVER on a below-floor / non-positive carry (fail-CLOSED → no accrual).
APY_CAP_DECIMAL = 0.30               # mirrors RiskPolicy max_apy_for_new_position (30%)
APY_FLOOR_DECIMAL = 0.01             # mirrors RiskPolicy min_apy_for_new_position (1%)

# The FixedCarry PT carry is a T2-ish carry book → gate it under the T2 caps.
_CAPTURE_TIER = "T2"
_CAPTURE_PROTOCOL_KEY = "rates_desk_fixed_carry"
# Representative pool TVL for the gate's TVL-floor check: the validated sleeve only ever holds
# books on pools ≥ the RiskPolicy TVL floor ($5M). We read the real min held-book TVL when
# available and fall back to the floor only as a conservative default.
_DEFAULT_POOL_TVL = 9_000_000.0


def _riskpolicy_tvl_floor() -> float:
    """The deterministic RiskPolicy min TVL floor ($5M). Read from the policy config so the
    captured book stays in lockstep with the policy (never hardcoded here). fail-soft default."""
    try:
        from spa_core.risk.policy import RiskConfig
        return float(RiskConfig().min_tvl_usd)
    except Exception:  # noqa: BLE001
        return 5_000_000.0


def _eligible_books(books: dict) -> Optional[list]:
    """The validated sleeve's held books that are RiskPolicy-ELIGIBLE for the captured book:
    positive size, positive rate, and pool TVL ≥ the RiskPolicy TVL floor. The captured book
    only ever mirrors books the policy would actually approve — a sub-floor book is excluded
    (the validated sleeve may hold it under its OWN exit-capacity logic, but the captured book
    refuses to size into a pool below the $5M floor). Returns a list of (size, rate, tvl) tuples,
    or None on any malformed input (fail-CLOSED)."""
    floor = Decimal(str(_riskpolicy_tvl_floor()))
    out = []
    for bk in books.values():
        if not isinstance(bk, dict):
            return None
        try:
            size = Decimal(str(bk.get("size", "0")))
            rate = Decimal(str(bk.get("entry_rate", "0")))
            tvl = Decimal(str(((bk.get("quote") or {}).get("tvl_usd", "0"))))
        except (InvalidOperation, ValueError, TypeError):
            return None  # fail-CLOSED on any malformed field
        if size <= 0 or rate <= 0:
            continue
        if tvl < floor:
            continue  # excluded: pool below the RiskPolicy TVL floor
        out.append((size, rate, tvl))
    return out


def live_fixed_carry_apy() -> Optional[float]:
    """The captured sleeve's REAL live net carry (decimal APY), read from the VALIDATED
    FixedCarry forward-track state. This is the size-weighted LOCKED fixed PT rate across the
    sleeve's RiskPolicy-ELIGIBLE open books (pool TVL ≥ the $5M floor) — exactly the rate the
    validated sleeve's own step() accrues at, restricted to policy-fundable pools, so the
    captured book earns the SAME real carry on a bounded notional.

    fail-CLOSED — returns None (⇒ NO accrual) when:
      * the validated state file is missing / unreadable / malformed; OR
      * the sleeve holds NO RiskPolicy-eligible open book (nothing fundable to accrue against); OR
      * the computed rate is non-finite / non-positive / below the honest floor.

    NEVER fabricates a yield. Deterministic. LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    doc = atomic_load(str(_RATES_STATE_PATH), default=None)
    if not isinstance(doc, dict):
        return None
    books = ((doc.get("state") or {}).get("books")) if isinstance(doc.get("state"), dict) else None
    if not isinstance(books, dict) or not books:
        return None  # fail-CLOSED: no open carry book → nothing real to accrue

    eligible = _eligible_books(books)
    if eligible is None:
        return None  # fail-CLOSED on malformed input
    weighted = Decimal("0")
    total = Decimal("0")
    for size, rate, _tvl in eligible:
        weighted += size * rate
        total += size
    if total <= 0:
        return None  # fail-CLOSED: no eligible positive-size book
    apy = float(weighted / total)
    if not math.isfinite(apy) or apy < APY_FLOOR_DECIMAL:
        return None  # fail-CLOSED: non-finite or below the honest floor
    return min(apy, APY_CAP_DECIMAL)


def min_held_pool_tvl() -> float:
    """The minimum pool TVL across the validated sleeve's RiskPolicy-ELIGIBLE held books (for
    the gate's TVL-floor check). Since _eligible_books already excludes sub-floor pools, this is
    ≥ the RiskPolicy floor whenever an eligible book exists. Falls back to a conservative default
    if unreadable / no eligible book. fail-soft (never raises)."""
    doc = atomic_load(str(_RATES_STATE_PATH), default=None)
    if not isinstance(doc, dict):
        return _DEFAULT_POOL_TVL
    books = ((doc.get("state") or {}).get("books")) if isinstance(doc.get("state"), dict) else None
    if not isinstance(books, dict) or not books:
        return _DEFAULT_POOL_TVL
    eligible = _eligible_books(books)
    if not eligible:
        return _DEFAULT_POOL_TVL
    return float(min(tvl for _s, _r, tvl in eligible))


def riskpolicy_approves(notional_usd: float, apy_decimal: float,
                        pool_tvl_usd: Optional[float] = None) -> "RiskApproval":
    """Deterministic RiskPolicy gate for the captured allocation (LLM-FORBIDDEN). The captured
    book is sized + bounded; here we prove a fresh PortfolioState holding ONLY this captured
    position passes RiskPolicy.check_new_position under the T2 caps. approved=False ⇒ no capture.

    Returns a small RiskApproval dataclass-like dict-bearing object."""
    # LLM_FORBIDDEN
    from spa_core.risk.policy import PortfolioState, RiskPolicy

    apy_pct = apy_decimal * 100.0
    tvl = pool_tvl_usd if (pool_tvl_usd is not None) else min_held_pool_tvl()
    # Fresh state: the captured sleeve's own bounded base, no other positions (cash buffer holds).
    state = PortfolioState(total_capital_usd=CAPTURE_CAPITAL_BASE, positions=[])
    result = RiskPolicy().check_new_position(
        state=state,
        protocol_key=_CAPTURE_PROTOCOL_KEY,
        tier=_CAPTURE_TIER,
        amount_usd=notional_usd,
        current_apy=apy_pct,
        tvl_usd=tvl,
        chain="ethereum",
        check_capacity=False,
    )
    return RiskApproval(
        approved=bool(result.approved),
        violations=list(result.violations),
        tier=_CAPTURE_TIER,
        amount_usd=notional_usd,
        apy_pct=apy_pct,
        tvl_usd=tvl,
    )


class RiskApproval:
    """Thin, JSON-safe carrier for the RiskPolicy verdict on the captured allocation."""

    __slots__ = ("approved", "violations", "tier", "amount_usd", "apy_pct", "tvl_usd")

    def __init__(self, approved, violations, tier, amount_usd, apy_pct, tvl_usd):
        self.approved = approved
        self.violations = violations
        self.tier = tier
        self.amount_usd = amount_usd
        self.apy_pct = apy_pct
        self.tvl_usd = tvl_usd

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "violations": self.violations,
            "tier": self.tier,
            "amount_usd": round(self.amount_usd, 2),
            "apy_pct": round(self.apy_pct, 4),
            "tvl_usd": round(self.tvl_usd, 2),
        }


def bounded_notional(capital_base: float = CAPTURE_CAPITAL_BASE,
                     frac: float = MAX_NOTIONAL_FRAC) -> float:
    """The hard-capped captured notional (≤ frac of the captured-capital base). Deterministic."""
    if not (math.isfinite(capital_base) and capital_base > 0):
        return 0.0
    f = frac if (math.isfinite(frac) and 0.0 < frac <= MAX_NOTIONAL_FRAC) else MAX_NOTIONAL_FRAC
    return round(capital_base * f, 2)


def daily_carry(notional_usd: float, apy_decimal: float) -> float:
    """One day of carry on the captured notional at the live decimal APY. Never negative."""
    if notional_usd <= 0 or apy_decimal <= 0:
        return 0.0
    return notional_usd * apy_decimal / 365.0


def _default_capture_state() -> dict:
    """Minimal safe SEPARATE-book state (never run / corrupt). LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    return {
        "sleeve_id": SLEEVE_ID,
        "name": "Rates Desk — Fixed Carry (CAPTURED-PAPER)",
        "version": CAPTURE_VERSION,
        "is_advisory": True,
        "capture_mode": "PAPER",
        "owner_gated_real_capital": True,
        "separate_book": True,
        "co_mingled_with_golive": False,
        "capital_base": CAPTURE_CAPITAL_BASE,
        "notional_usd": 0.0,
        "equity_usd": 0.0,
        "accrued_usd": 0.0,
        "live_apy_decimal": None,
        "risk_approved": None,
        "daily_history": [],
        "cycles_completed": 0,
        "last_cycle_at": None,
        "note": "Captured FixedCarry sleeve — awaiting first cycle (auto-bounds on run).",
        "LLM_FORBIDDEN": True,
    }


def load_capture_state() -> dict:
    """Load the SEPARATE captured-book state. fail-CLOSED → safe default. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    doc = atomic_load(str(_CAPTURE_PATH), default=None)
    if not isinstance(doc, dict):
        return _default_capture_state()
    return doc


def save_capture_state(state: dict) -> None:
    """Atomic write of the SEPARATE captured-book state. NEVER writes any go-live track file.
    LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    atomic_save(state, str(_CAPTURE_PATH))


def run_capture_cycle(dry_run: bool = True,
                      capital_base: float = CAPTURE_CAPITAL_BASE,
                      frac: float = MAX_NOTIONAL_FRAC,
                      capture_path: Optional[Path] = None,
                      rates_state_path: Optional[Path] = None) -> dict:
    """One captured-paper cycle for the FixedCarry sleeve.

    Steps (deterministic, fail-CLOSED):
      1. Read the REAL live carry from the validated FixedCarry forward track. Missing/NaN/no-book
         ⇒ NO accrual (fail-CLOSED), recorded honestly in the result + state.
      2. Compute the BOUNDED notional (≤frac of the captured-capital base).
      3. Gate the allocation through deterministic RiskPolicy (T2). approved=False ⇒ NO accrual.
      4. Accrue ONE day of REAL carry on the bounded notional, compound into the SEPARATE book's
         equity, append a daily bar (dedup by UTC date).
      5. dry_run=False ⇒ atomic write to the SEPARATE captured-book file ONLY. The go-live track
         is NEVER read or written here.

    `capture_path` / `rates_state_path` overrides keep the sandbox smoke + tests hermetic.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN — allow hermetic path overrides for sandbox/tests without touching live data.
    global _CAPTURE_PATH, _RATES_STATE_PATH
    saved_cap, saved_rates = _CAPTURE_PATH, _RATES_STATE_PATH
    if capture_path is not None:
        _CAPTURE_PATH = Path(capture_path)
    if rates_state_path is not None:
        _RATES_STATE_PATH = Path(rates_state_path)
    try:
        return _run_capture_cycle_inner(dry_run, capital_base, frac)
    finally:
        _CAPTURE_PATH, _RATES_STATE_PATH = saved_cap, saved_rates


def _run_capture_cycle_inner(dry_run: bool, capital_base: float, frac: float) -> dict:
    # LLM_FORBIDDEN
    now = clock.utcnow()
    today = now.strftime("%Y-%m-%d")

    state = load_capture_state()
    # Self-bound: set the bounded notional + base on a genuinely fresh book only.
    if float(state.get("notional_usd", 0) or 0) <= 0 and not state.get("daily_history"):
        state["capital_base"] = capital_base
        state["equity_usd"] = 0.0
        state["accrued_usd"] = 0.0
    notional = bounded_notional(capital_base, frac)
    state["notional_usd"] = notional
    state["is_advisory"] = True
    state["capture_mode"] = "PAPER"
    state["owner_gated_real_capital"] = True
    state["separate_book"] = True
    state["co_mingled_with_golive"] = False
    state["LLM_FORBIDDEN"] = True

    # 1. REAL live carry (fail-CLOSED).
    apy = live_fixed_carry_apy()
    state["live_apy_decimal"] = apy

    base_result = {
        "sleeve_id": SLEEVE_ID,
        "notional_usd": notional,
        "live_apy_decimal": apy,
        "ran_at": now.isoformat() + "Z",
        "dry_run": dry_run,
        "is_advisory": True,
        "capture_mode": "PAPER",
        "LLM_FORBIDDEN": True,
    }

    if apy is None:
        # fail-CLOSED: no real carry available → NO accrual, NO fabricated yield.
        state["risk_approved"] = None
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["cycles_completed"] = int(state.get("cycles_completed", 0)) + 1
        state["note"] = "fail-CLOSED: no live carry from validated track — no accrual this cycle."
        if not dry_run:
            save_capture_state(state)
        base_result.update({"accrued": False, "reason": "no_live_carry_fail_closed",
                            "equity_usd": round(float(state.get("equity_usd", 0.0)), 2)})
        return base_result

    # 3. RiskPolicy gate (T2). approved=False ⇒ NO accrual.
    approval = riskpolicy_approves(notional, apy)
    state["risk_approved"] = approval.to_dict()
    if not approval.approved:
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["cycles_completed"] = int(state.get("cycles_completed", 0)) + 1
        state["note"] = f"RiskPolicy REJECTED capture: {approval.violations}"
        if not dry_run:
            save_capture_state(state)
        base_result.update({"accrued": False, "reason": "risk_policy_rejected",
                            "risk_violations": approval.violations,
                            "equity_usd": round(float(state.get("equity_usd", 0.0)), 2)})
        return base_result

    # 4. Accrue ONE day of REAL carry on the BOUNDED notional (dedup by UTC date).
    equity = float(state.get("equity_usd", 0.0) or 0.0)
    accrued_total = float(state.get("accrued_usd", 0.0) or 0.0)
    existing_dates = {b.get("date") for b in state.get("daily_history", [])}
    accrued_today = 0.0
    if today not in existing_dates:
        accrued_today = daily_carry(notional, apy)
        equity += accrued_today
        accrued_total += accrued_today
        state["equity_usd"] = round(equity, 6)
        state["accrued_usd"] = round(accrued_total, 6)
        state.setdefault("daily_history", []).append({
            "date": today,
            "notional_usd": notional,
            "apy_decimal": round(apy, 8),
            "daily_carry_usd": round(accrued_today, 6),
            "equity_usd": round(equity, 6),
            "risk_approved": True,
        })

    state["last_cycle_at"] = now.isoformat() + "Z"
    state["cycles_completed"] = int(state.get("cycles_completed", 0)) + 1
    state["note"] = (f"Captured FixedCarry accruing at {apy * 100:.4f}% on "
                     f"${notional:,.0f} bounded notional (PAPER, owner-gated for real capital).")
    if not dry_run:
        save_capture_state(state)

    base_result.update({
        "accrued": True,
        "reason": "ok",
        "daily_carry_usd": round(accrued_today, 6),
        "equity_usd": round(equity, 6),
        "accrued_usd": round(accrued_total, 6),
        "risk_approved": True,
    })
    return base_result


def get_capture_summary(capture_path: Optional[Path] = None) -> dict:
    """Compact status of the captured sleeve for dashboard / health. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    global _CAPTURE_PATH
    saved = _CAPTURE_PATH
    if capture_path is not None:
        _CAPTURE_PATH = Path(capture_path)
    try:
        state = load_capture_state()
    finally:
        _CAPTURE_PATH = saved
    return {
        "sleeve_id": SLEEVE_ID,
        "is_advisory": bool(state.get("is_advisory", True)),
        "capture_mode": state.get("capture_mode", "PAPER"),
        "separate_book": True,
        "co_mingled_with_golive": False,
        "owner_gated_real_capital": True,
        "notional_usd": float(state.get("notional_usd", 0.0) or 0.0),
        "equity_usd": float(state.get("equity_usd", 0.0) or 0.0),
        "accrued_usd": float(state.get("accrued_usd", 0.0) or 0.0),
        "live_apy_decimal": state.get("live_apy_decimal"),
        "days_tracked": len(state.get("daily_history", [])),
        "cycles_completed": int(state.get("cycles_completed", 0) or 0),
        "LLM_FORBIDDEN": True,
    }


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys

    dry = "--run" not in sys.argv
    res = run_capture_cycle(dry_run=dry)
    print(f"[sleeve_capture {CAPTURE_VERSION}] accrued={res.get('accrued')} "
          f"reason={res.get('reason')} notional=${res.get('notional_usd'):,.0f} "
          f"apy={res.get('live_apy_decimal')} dry_run={dry}")
    if "--verbose" in sys.argv or "-v" in sys.argv:
        print(json.dumps(res, indent=2, default=str))
        print(json.dumps(get_capture_summary(), indent=2, default=str))
