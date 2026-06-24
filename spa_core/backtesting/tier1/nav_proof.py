"""
spa_core/backtesting/tier1/nav_proof.py — Verifiable NAV / proof-of-reserves snapshot.

PARALLEL MODEL — reads the live paper state read-only and produces a SELF-VERIFYING NAV
snapshot. Does not touch RiskPolicy, the cycle, or any canonical module.

Institutional trust requirement: anyone can recompute the published NAV from its components.
  1. NAV = sum(position_usd) + cash_usd — the published equity is rebuilt from its parts.
  2. RECONCILE the computed NAV against the REPORTED current_equity → delta + tolerance flag.
     This proves the headline equity number equals the sum of the parts (no hidden value).
  3. FINGERPRINT the inputs: components_hash = sha256 of canonical JSON of the sorted
     positions + cash; nav_hash = sha256 over (computed_nav, components_hash, ts). Publishing
     these hashes lets a third party detect any tamper with the components or the NAV.

verify_proof() recomputes the hashes AND the NAV from the proof's own components and confirms
internal consistency — the "anyone can verify" function.

Deterministic, stdlib only, LLM-forbidden. Atomic writes (tmp + os.replace).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_POSITIONS = _DATA / "current_positions.json"
_STATUS = _DATA / "paper_trading_status.json"
_EQUITY = _DATA / "equity_curve_daily.json"
_OUT = _DATA / "tier1_nav_proof.json"

# Reconciliation tolerance: ok if |delta| < $1 OR < 0.01% of reported equity.
TOL_ABS_USD = 1.0
TOL_REL_PCT = 0.01


def _canonical(obj) -> str:
    """Canonical JSON: sort_keys=True, compact separators — deterministic byte string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _coerce_usd(v) -> Optional[float]:
    """A position value may be a bare USD number or a dict with a usd/value/amount field."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("usd", "usd_value", "value_usd", "value", "amount_usd", "amount"):
            x = v.get(k)
            if isinstance(x, (int, float)):
                return float(x)
    return None


def _load_positions() -> dict:
    """{protocol: usd} from current_positions.json, falling back to paper_trading_status or
    the latest equity-curve bar. Handles {protocol: usd} maps and dict-valued positions."""
    pos = _read_json(_POSITIONS)
    raw = pos.get("positions")
    if not isinstance(raw, dict) or not raw:
        raw = _read_json(_STATUS).get("current_positions")
    if not isinstance(raw, dict) or not raw:
        daily = _read_json(_EQUITY).get("daily") or []
        if daily and isinstance(daily[-1], dict):
            raw = daily[-1].get("positions")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        usd = _coerce_usd(v)
        if usd is not None:
            out[str(k)] = round(usd, 8)
    return out


def _load_cash() -> float:
    """cash_usd from current_positions.json, else paper_trading_status.json (cash/cash_usd)."""
    pos = _read_json(_POSITIONS)
    for k in ("cash_usd", "cash"):
        v = pos.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    st = _read_json(_STATUS)
    for k in ("cash_usd", "cash"):
        v = st.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _load_reported_equity() -> Optional[float]:
    """Reported headline equity: paper_trading_status.current_equity, else latest equity bar."""
    st = _read_json(_STATUS)
    for k in ("current_equity", "equity", "end_equity"):
        v = st.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    daily = _read_json(_EQUITY).get("daily") or []
    if daily and isinstance(daily[-1], dict):
        for k in ("close_equity", "equity", "nav"):
            v = daily[-1].get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _components_hash(positions: dict, cash_usd: float) -> str:
    """sha256 of canonical JSON of the SORTED positions + cash (inputs fingerprint)."""
    comp = {
        "positions": [{"protocol": p, "usd": positions[p]} for p in sorted(positions)],
        "cash_usd": round(float(cash_usd), 8),
    }
    return _sha256(_canonical(comp))


def _nav_hash(computed_nav: float, components_hash: str, ts: str) -> str:
    """sha256 over (computed_nav, components_hash, ts) — binds NAV to its inputs + time."""
    return _sha256(_canonical({
        "computed_nav_usd": round(float(computed_nav), 8),
        "components_hash": components_hash,
        "ts": ts,
    }))


def _reconcile(computed_nav: float, reported_equity: Optional[float]) -> dict:
    """Delta between computed NAV and reported equity + a tolerance flag."""
    if reported_equity is None:
        return {"reconciliation_delta_usd": None, "reconciliation_ok": False,
                "reconciliation_note": "no reported equity available to reconcile against"}
    delta = round(computed_nav - reported_equity, 8)
    rel_pct = abs(delta) / reported_equity * 100.0 if reported_equity else float("inf")
    ok = abs(delta) < TOL_ABS_USD or rel_pct < TOL_REL_PCT
    return {
        "reconciliation_delta_usd": delta,
        "reconciliation_delta_pct": round(rel_pct, 6),
        "reconciliation_ok": bool(ok),
        "reconciliation_note": (
            "computed NAV matches reported equity within tolerance"
            if ok else
            f"MISMATCH: |delta| ${abs(delta):.2f} ({rel_pct:.4f}%) exceeds "
            f"${TOL_ABS_USD:.2f} / {TOL_REL_PCT}% tolerance"
        ),
    }


def compute_nav() -> dict:
    """NAV = sum(position_usd) + cash, reconciled against reported current_equity.

    Returns the components and the reconciliation, but NOT the hashes (build_proof adds
    those with a single pinned timestamp)."""
    positions = _load_positions()
    cash_usd = round(_load_cash(), 8)
    deployed = round(sum(positions.values()), 8)
    computed_nav = round(deployed + cash_usd, 8)
    reported = _load_reported_equity()
    rec = _reconcile(computed_nav, reported)
    return {
        "positions": [{"protocol": p, "usd": positions[p]} for p in sorted(positions)],
        "cash_usd": cash_usd,
        "deployed_usd": deployed,
        "computed_nav_usd": computed_nav,
        "reported_equity_usd": reported,
        **rec,
    }


def build_proof(write: bool = True) -> dict:
    """Build a verifiable NAV proof snapshot and (optionally) atomically write it."""
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    nav = compute_nav()
    positions_map = {row["protocol"]: row["usd"] for row in nav["positions"]}
    comp_hash = _components_hash(positions_map, nav["cash_usd"])
    nav_hash = _nav_hash(nav["computed_nav_usd"], comp_hash, ts)
    proof = {
        "ts": ts,
        "model": "tier1_nav_proof",
        "llm_forbidden": True,
        "canonical_json": "sort_keys=True,separators=(',',':')",
        "tolerance": {"abs_usd": TOL_ABS_USD, "rel_pct": TOL_REL_PCT},
        "positions": nav["positions"],
        "cash_usd": nav["cash_usd"],
        "deployed_usd": nav["deployed_usd"],
        "computed_nav_usd": nav["computed_nav_usd"],
        "reported_equity_usd": nav["reported_equity_usd"],
        "reconciliation_delta_usd": nav["reconciliation_delta_usd"],
        "reconciliation_delta_pct": nav.get("reconciliation_delta_pct"),
        "reconciliation_ok": nav["reconciliation_ok"],
        "reconciliation_note": nav["reconciliation_note"],
        "components_hash": comp_hash,
        "nav_hash": nav_hash,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_DATA), prefix=".tier1_nav_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(proof, f, indent=2)
            os.replace(tmp, _OUT)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
    return proof


def verify_proof(proof: dict) -> bool:
    """Recompute hashes AND NAV from the proof's OWN components and confirm consistency.

    This is the 'anyone can verify' function — it needs nothing but the published proof:
      * components_hash recomputed from the proof's positions + cash must match,
      * computed_nav_usd must equal sum(positions) + cash,
      * nav_hash recomputed from (computed_nav, components_hash, ts) must match.
    Returns False (never raises) on any malformed input or mismatch.
    """
    try:
        rows = proof.get("positions") or []
        positions_map = {}
        recomputed_sum = 0.0
        for row in rows:
            p = str(row["protocol"])
            usd = float(row["usd"])
            positions_map[p] = round(usd, 8)
            recomputed_sum += usd
        cash_usd = float(proof.get("cash_usd", 0.0))

        # 1) inputs fingerprint
        if _components_hash(positions_map, cash_usd) != proof.get("components_hash"):
            return False

        # 2) NAV equals sum of parts (this catches a tampered computed_nav_usd)
        recomputed_nav = round(recomputed_sum + cash_usd, 8)
        claimed_nav = round(float(proof.get("computed_nav_usd")), 8)
        if abs(recomputed_nav - claimed_nav) > 1e-6:
            return False

        # 3) nav_hash binds NAV + components + ts
        expected_nav_hash = _nav_hash(claimed_nav, proof.get("components_hash"), proof.get("ts"))
        if expected_nav_hash != proof.get("nav_hash"):
            return False
        return True
    except Exception:
        return False


if __name__ == "__main__":
    p = build_proof(write=True)
    print(json.dumps({
        "ts": p["ts"],
        "deployed_usd": p["deployed_usd"],
        "cash_usd": p["cash_usd"],
        "computed_nav_usd": p["computed_nav_usd"],
        "reported_equity_usd": p["reported_equity_usd"],
        "reconciliation_delta_usd": p["reconciliation_delta_usd"],
        "reconciliation_ok": p["reconciliation_ok"],
        "reconciliation_note": p["reconciliation_note"],
        "components_hash": p["components_hash"][:16] + "...",
        "nav_hash": p["nav_hash"][:16] + "...",
        "verify_proof": verify_proof(p),
    }, indent=2))
