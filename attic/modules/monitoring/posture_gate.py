"""spa_core/monitoring/posture_gate.py — RTMR (ADR-053) S10.5a posture-enforcement gate.

The rebalance-loop must HONOR the emergency-path's posture (§2, §7): never re-open an EXITED scope,
never exceed a CAPPED one, and go all-cash when the portfolio is DEFENSIVE. This is that clamp,
as a PURE function so it can be unit-tested and reviewed in isolation.

**de-risk-only (§1.4):** it can only LOWER a target weight (or zero it); it never raises exposure and
never moves weight between protocols — freed weight goes to cash. Deterministic, LLM-forbidden.

S10.5a = this pure gate (additive, no behaviour change on its own). S10.5b = the one-line wire that
calls it in `cycle_runner`'s allocation step — **owner-gated** (touches the money path).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring import posture as P


def apply_posture(target_weights: dict, posture: dict, *, now_ts: int) -> tuple[dict, list]:
    """Clamp ``{scope: weight}`` to the active posture. Returns (clamped_weights, notes).

    - portfolio DEFENSIVE ⇒ everything to 0 (all-cash), one note.
    - per-scope EXITED/DEFENSIVE ⇒ weight 0; CAPPED ⇒ min(weight, cap); FROZEN ⇒ min(weight, held?)
      is enforced upstream (no-new); here FROZEN does not raise but also cannot exceed its current —
      as a pure weight clamp we treat FROZEN as "no increase" = min(weight, weight) (caller passes the
      already-held weight when it wants strict no-new). NORMAL ⇒ unchanged.
    Freed weight is NOT redistributed to other protocols (that would be an increase) — it implicitly
    becomes cash.
    """
    notes: list = []
    if P.portfolio_defensive(posture):
        notes.append("portfolio DEFENSIVE → all-cash")
        return ({k: 0.0 for k in target_weights}, notes)

    out: dict = {}
    for scope, w in target_weights.items():
        w = float(w)
        cap = P.cap_for(posture, scope, now_ts=now_ts)  # 0.0 for EXITED, the cap for CAPPED, else None
        if cap is not None and w > cap:
            out[scope] = cap
            notes.append(f"{scope}: {w:.3f}→{cap:.3f} ({P.entry_state(posture, scope, now_ts=now_ts)})")
        else:
            out[scope] = w
    return out, notes


def would_change(target_weights: dict, posture: dict, *, now_ts: int) -> bool:
    """True if the active posture would alter the given target (for a cheap 'is any posture live?' check)."""
    clamped, _ = apply_posture(target_weights, posture, now_ts=now_ts)
    return any(abs(clamped[k] - float(target_weights[k])) > 1e-9 for k in target_weights)
