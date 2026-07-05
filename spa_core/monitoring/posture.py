"""spa_core/monitoring/posture.py — RTMR (ADR-053) risk-posture store (S10.1 scaffold).

The SINGLE source of truth for the current defensive posture — the one file that couples the
fast path and the slow path (§2, §7): the emergency-path WRITES posture entries
("protocol X: EXITED until T", "engine B: FROZEN", "asset Y: cap→0"), and the
rebalance-loop (`cycle_runner`) READS and HONORS them (never re-opens an EXITED scope or
exceeds a capped one until re-enable).

This module is only the STORE + query helpers (deterministic, stdlib-only, LLM-forbidden,
atomic writes). The reaction logic that DECIDES postures lands in S10.4 (`reaction.py`).
De-risk-only is enforced upstream in the reaction engine; this store just persists state.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_POSTURE_PATH = _ROOT / "data" / "monitoring" / "risk_posture.json"

# Posture states (de-risk-only vocabulary — mirrors reaction Action types §5.1)
NORMAL = "NORMAL"
FROZEN = "FROZEN"      # no new allocation; hold current
CAPPED = "CAPPED"      # exposure limited to `cap` (fraction 0..1)
EXITED = "EXITED"      # fully exited; do not re-open until `until_ts` or manual re-enable
DEFENSIVE = "DEFENSIVE"  # whole engine/portfolio in market-exit, wait
STATES = (NORMAL, FROZEN, CAPPED, EXITED, DEFENSIVE)

_EMPTY = {"version": 1, "updated_ts": 0, "entries": {}, "portfolio": NORMAL}


def _atomic_write(path: Path, obj: dict) -> None:
    """Same-dir tmp + os.replace (project invariant — never a bare open(w) on state files)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(str(path), obj)
        return
    except Exception:  # noqa: BLE001 — fall back to a same-dir atomic replace
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def load_posture() -> dict:
    """Current posture, or a fresh NORMAL posture if none/corrupt (fail-safe = read as normal;
    the fast path is what MAKES it defensive — a missing posture just means nothing active yet)."""
    try:
        with open(_POSTURE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and "entries" in d:
            return d
    except Exception:  # noqa: BLE001 — missing/corrupt → empty
        pass
    return dict(_EMPTY, entries={})


def save_posture(posture: dict, *, now_ts: int) -> None:
    posture = dict(posture)
    posture["updated_ts"] = int(now_ts)
    posture.setdefault("version", 1)
    posture.setdefault("portfolio", NORMAL)
    posture.setdefault("entries", {})
    _atomic_write(_POSTURE_PATH, posture)


def set_entry(
    posture: dict, *, scope: str, state: str, now_ts: int,
    until_ts: int | None = None, cap: float | None = None, reason: str = "",
) -> dict:
    """Return a NEW posture dict with ``scope`` set to ``state`` (does not persist)."""
    if state not in STATES:
        raise ValueError(f"unknown posture state: {state!r}")
    entries = dict(posture.get("entries", {}))
    entries[scope] = {
        "state": state,
        "since_ts": int(now_ts),
        "until_ts": (int(until_ts) if until_ts is not None else None),
        "cap": (float(cap) if cap is not None else None),
        "reason": str(reason),
    }
    return dict(posture, entries=entries)


def set_portfolio(posture: dict, *, state: str, reason: str = "") -> dict:
    if state not in STATES:
        raise ValueError(f"unknown portfolio state: {state!r}")
    return dict(posture, portfolio=state, portfolio_reason=str(reason))


# ── query helpers the rebalance-loop uses to HONOR the posture ────────────────────────

def _active(entry: dict, now_ts: int) -> bool:
    """An EXITED/CAPPED/FROZEN entry is active until its until_ts passes (None = until manual)."""
    until = entry.get("until_ts")
    return until is None or now_ts < until


def entry_state(posture: dict, scope: str, *, now_ts: int) -> str:
    e = posture.get("entries", {}).get(scope)
    if not e or not _active(e, now_ts):
        return NORMAL
    return e.get("state", NORMAL)


def is_frozen(posture: dict, scope: str, *, now_ts: int) -> bool:
    return entry_state(posture, scope, now_ts=now_ts) in (FROZEN, EXITED, DEFENSIVE)


def is_exited(posture: dict, scope: str, *, now_ts: int) -> bool:
    return entry_state(posture, scope, now_ts=now_ts) in (EXITED, DEFENSIVE)


def cap_for(posture: dict, scope: str, *, now_ts: int) -> float | None:
    """Max allowed exposure fraction for ``scope`` under the current posture, or None (no cap).

    EXITED/DEFENSIVE ⇒ 0.0; CAPPED ⇒ its cap; otherwise None. The rebalance-loop must clamp
    target weights to this — an emergency posture can only REDUCE exposure, never raise it.
    """
    st = entry_state(posture, scope, now_ts=now_ts)
    if st in (EXITED, DEFENSIVE):
        return 0.0
    e = posture.get("entries", {}).get(scope)
    if st == CAPPED and e and e.get("cap") is not None:
        return float(e["cap"])
    return None


def portfolio_defensive(posture: dict) -> bool:
    return posture.get("portfolio") == DEFENSIVE
