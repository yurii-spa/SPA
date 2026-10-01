"""spa_core/paper_trading/pendle_market.py — Pendle PT markets observed for the Balanced PAPER model.

Input of the fixed-rate (PT hold-to-maturity) mechanic (ADR-533). Two Pendle endpoints, read-only:

* ``/core/v1/1/markets/active`` — the market list: expiry, ``details.impliedApy``, ``details.liquidity``;
* ``/core/v1/1/markets/{address}`` — the PT's own observed USD price (``pt.price.usd``, with
  ``priceUpdatedAt``) — the mark the model uses.

**Consistency check, NOT a second witness** (review 2026-10-01): both numbers come from the Pendle
backend, so agreement proves they are consistent, not that they are fresh — hence the separate
``priceUpdatedAt`` age gate (``MAX_PRICE_AGE_H``).

**Cross-check, not trust.** The PT's price is ALSO derived from the implied APY,
``(1 + implied)^(−τ/365)`` in units of the accounting asset. A mark is accepted only when the two
agree within ``PRICE_AGREEMENT_TOL`` (the accounting asset is a USD stable, so its USD price ≈ 1;
a larger gap means one of the two is stale or the underlying moved — the model must not pick).
Disagreement or absence ⇒ ``mark_ok = False`` with a reason; the model then holds and does not
re-mark (invariant #17), it never invents a price.

A market that has LEFT ``/active`` before its expiry is ``listed = False`` — a named outcome.
Stdlib only, LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

API = "https://api-v2.pendle.finance/core/v1/1"
PRICE_AGREEMENT_TOL = 0.005      # 0.5 % between the observed and the implied-derived price
MAX_PRICE_AGE_H = 6.0            # an older Pendle price is not a mark

#: Underlyings the Balanced mandate may hold, with how their USD peg is evidenced (ADR-533).
#: sUSDS → USDS: 1:1 convertible to DAI through the Sky converter, and DAI is in the RTMR peg
#: quorum. sUSDe → USDe has NO measured peg today (peg_history marks it UNMEASURED) ⇒ excluded.
ELIGIBLE_UNDERLYINGS = {"sUSDS": "USDS (1:1 DAI via Sky converter; DAI in the RTMR peg quorum)"}


def _get(url: str) -> object:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "spa-paper/1.0"}),
                                timeout=20) as r:  # noqa: S310 — public https API
        return json.loads(r.read())


def _parse_ts(s: object) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def implied_price(implied_apy: float, days_to_expiry: float) -> float:
    return (1.0 + implied_apy) ** (-max(0.0, days_to_expiry) / 365.0)


def observe(*, get: Optional[Callable] = None, now: Optional[datetime] = None,
            names: Optional[set] = None) -> dict:
    """``{"markets": [...], "ok": bool, "reason": ...}`` for the eligible-underlying markets."""
    get = get or _get
    now = now or datetime.now(timezone.utc)
    names = names if names is not None else set(ELIGIBLE_UNDERLYINGS)
    out: dict = {"observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": API, "markets": []}
    try:
        act = get(f"{API}/markets/active")
    except Exception as exc:  # noqa: BLE001
        return {**out, "ok": False, "reason": f"Pendle /markets/active unreachable: {type(exc).__name__}"}
    rows = (act.get("markets") if isinstance(act, dict) else act) or []
    for m in rows:
        if not isinstance(m, dict) or m.get("name") not in names:
            continue
        exp = _parse_ts(m.get("expiry"))
        det = m.get("details") or {}
        iy, liq, fee = det.get("impliedApy"), det.get("liquidity"), det.get("feeRate")
        row: dict = {"underlying": m.get("name"), "market": m.get("address"), "expiry": m.get("expiry"),
                     "pt": str(m.get("pt") or "").split("-")[-1], "listed": True,
                     "implied_apy_pct": (float(iy) * 100.0 if isinstance(iy, (int, float)) else None),
                     "liquidity_usd": (float(liq) if isinstance(liq, (int, float)) else None),
                     "fee_rate": (float(fee) if isinstance(fee, (int, float)) else None),
                     "peg_evidence": ELIGIBLE_UNDERLYINGS.get(m.get("name"))}
        days = ((exp - now).total_seconds() / 86400.0) if exp else None
        row["days_to_expiry"] = round(days, 4) if days is not None else None
        try:
            det2 = get(f"{API}/markets/{m.get('address') or ''}")
            pt = (det2 or {}).get("pt") or {}
            price = (pt.get("price") or {}).get("usd")
            row["pt_price_usd"] = float(price) if isinstance(price, (int, float)) else None
            row["pt_price_updated_at"] = pt.get("priceUpdatedAt")
        except Exception as exc:  # noqa: BLE001
            row["pt_price_usd"] = None
            row["pt_price_reason"] = f"market detail unreachable: {type(exc).__name__}"
        upd = _parse_ts(row.get("pt_price_updated_at"))
        age_h = ((now - upd).total_seconds() / 3600.0) if upd else None
        row["pt_price_age_h"] = round(age_h, 3) if age_h is not None else None
        if age_h is None or age_h > MAX_PRICE_AGE_H:
            row["mark_ok"] = False
            row["mark_reason"] = f"PT price age {age_h} h > {MAX_PRICE_AGE_H} h (or no timestamp)"
        elif row["pt_price_usd"] is not None and row["implied_apy_pct"] is not None and days is not None:
            derived = implied_price(row["implied_apy_pct"] / 100.0, days)
            row["derived_price"] = round(derived, 8)
            gap = abs(row["pt_price_usd"] - derived) / derived
            row["price_gap"] = round(gap, 6)
            row["mark_ok"] = gap <= PRICE_AGREEMENT_TOL
            if not row["mark_ok"]:
                row["mark_reason"] = f"observed vs implied-derived price differ by {gap:.2%}"
        else:
            row["mark_ok"] = False
            row["mark_reason"] = row.get("pt_price_reason") or "price, implied APY or expiry missing"
        out["markets"].append(row)
    out["ok"] = True
    out["reason"] = None
    return out
