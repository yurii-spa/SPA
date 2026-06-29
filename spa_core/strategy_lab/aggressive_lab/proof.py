"""
spa_core/strategy_lab/aggressive_lab/proof.py — the per-strategy proof-chain over realized points.

Each realized point in ``realized_series.jsonl`` is hash-chained: a point's ``hash`` is the sha256
of its canonical content PLUS the previous point's hash. This makes the track TAMPER-EVIDENT — you
cannot silently alter, re-order, or splice a past day without breaking every subsequent hash. (The
"don't trust us, check us" posture the rest of SPA uses; see scripts/verify_spa.py + the rates-desk
proof chain.) Lane 2 trusts this chain (it does not re-verify the crypto); our own ``verify_chain``
exists for the red-team + the standing self-check.

The chained content is ONLY the load-bearing economic fields (date, equity_usd, ret, phase, as_of)
so the hash is reproducible from the data alone — the hash fields themselves are excluded from the
preimage (otherwise the hash would depend on itself).

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Tuple

# The fields that form the hash preimage (the economic payload; hash/prev_hash excluded).
_CHAINED_FIELDS = ("date", "equity_usd", "ret", "phase", "as_of")

GENESIS = "0" * 64


def _preimage(point: dict, prev_hash: str) -> str:
    payload = {k: point.get(k) for k in _CHAINED_FIELDS if k in point}
    # canonical, stable serialization so the same economic content always hashes identically
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "|" + prev_hash


def hash_point(point: dict, prev_hash: str) -> str:
    """sha256 hex of this point's economic payload chained to ``prev_hash``."""
    return hashlib.sha256(_preimage(point, prev_hash).encode("utf-8")).hexdigest()


def chain_point(point: dict, prev_hash: Optional[str]) -> dict:
    """Return a COPY of ``point`` with prev_hash/hash stamped (chaining to ``prev_hash`` or GENESIS)."""
    prev = prev_hash if prev_hash else GENESIS
    out = dict(point)
    out["prev_hash"] = prev
    out["hash"] = hash_point(out, prev)
    return out


def last_hash(series: List[dict]) -> Optional[str]:
    """The hash of the last point in a stored series (None if empty / unhashed)."""
    if not series:
        return None
    h = series[-1].get("hash")
    return h if isinstance(h, str) and h else None


def verify_chain(series: List[dict]) -> Tuple[bool, str]:
    """Recompute the chain and confirm every link. (ok, reason). fail-CLOSED: any break → (False, …).
    An unhashed series (no hash fields at all) is reported (False, 'unhashed') — honest, not a crash."""
    if not series:
        return True, "empty"
    prev = GENESIS
    for i, pt in enumerate(series):
        stored = pt.get("hash")
        if not isinstance(stored, str) or not stored:
            return False, f"point {i} ({pt.get('date')}) is unhashed"
        stored_prev = pt.get("prev_hash")
        if stored_prev != prev:
            return False, f"point {i} ({pt.get('date')}) prev_hash break"
        recomputed = hash_point(pt, prev)
        if recomputed != stored:
            return False, f"point {i} ({pt.get('date')}) hash mismatch (tampered)"
        prev = stored
    return True, "ok"
