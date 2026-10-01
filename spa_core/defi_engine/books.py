"""spa_core/defi_engine/books.py — the three package books read into ONE shape (ADR-532).

The books live in three files written by three engines (ADR-530 §B):

=============  ==================  ==============================  ==================================
package        engine              state                           gate
=============  ==================  ==============================  ==================================
conservative   ``cycle_runner``    ``current_positions.json`` +    RiskPolicy v1.0 + two-tier kill
                                   ``equity_curve_daily.json``
balanced       ``hy_cycle``        ``hy_paper_trading.json``       outside RiskPolicy, own kill
aggressive     ``lp_cycle``        ``lp_paper_trading.json``       outside RiskPolicy, own kill
=============  ==================  ==============================  ==================================

This module READS them; it never writes a book. The returned shape is the same for all three so
that every derived component (APY contract, exit model, loss budget, passport) has one code path.

Series honesty (owner decision 2026-10-01, Option A): the Balanced / Aggressive series are the
``sleeve-econ-v2`` rows ONLY. Rows written by the distorted v1 model are counted (``pre_fix_rows``)
and never mixed into a figure. A missing / unreadable file is ``measured=False`` with a reason —
the third outcome, never an empty book that reads as "holds nothing" (invariant #17).

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

BOOK_IDS = ("conservative", "balanced", "aggressive")

_SLEEVE_FILES = {"balanced": "hy_paper_trading.json", "aggressive": "lp_paper_trading.json"}
_ENGINES = {"conservative": "cycle_runner", "balanced": "hy_cycle", "aggressive": "lp_cycle"}


def _load(path: Path) -> tuple[Optional[Any], Optional[str]]:
    if not path.exists():
        return None, f"{path.name} absent"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001 — unreadable is a named outcome, not a crash
        return None, f"{path.name} unreadable: {type(exc).__name__}"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def gates() -> dict:
    """Each book's enforced stop, read from the code that enforces it (no literal here)."""
    out: dict[str, dict] = {}
    try:
        from spa_core.governance import kill_switch as ks
        out["conservative"] = {
            "gate": "RiskPolicy v1.0 + two-tier kill switch (ADR-034/048)",
            "under_riskpolicy": True,
            "stops": [
                {"name": "SOFT_DERISK", "drawdown_pct": float(ks.SOFT_DERISK_THRESHOLD_PCT),
                 "effect": "halt new / no increase (hold + reduce allowed)"},
                {"name": "HARD_KILL", "drawdown_pct": float(ks.DRAWDOWN_THRESHOLD_PCT),
                 "effect": "full kill to all-cash"},
            ],
        }
    except Exception as exc:  # noqa: BLE001
        out["conservative"] = {"gate": None, "error": f"kill_switch unreadable: {exc}"}
    for book, mod, attr in (("balanced", "hy_cycle", "_KILL_DRAWDOWN_THRESHOLD"),
                            ("aggressive", "lp_cycle", "IL_KILL_THRESHOLD")):
        try:
            m = __import__(f"spa_core.paper_trading.{mod}", fromlist=["x"])
            val = _num(getattr(m, attr, None))
            out[book] = {
                "gate": f"outside RiskPolicy v1.0; own stop in {mod}.{attr}",
                "under_riskpolicy": False,
                "stops": ([{"name": "BOOK_KILL", "drawdown_pct": round(abs(val) * 100.0, 4),
                            "effect": "book kill (cycle stops trading)"}] if val is not None else []),
            }
        except Exception as exc:  # noqa: BLE001
            out[book] = {"gate": None, "error": f"{mod} unreadable: {exc}"}
    return out


def _orchestrator(ddir: Path) -> dict[str, dict]:
    doc, _ = _load(ddir / "adapter_orchestrator_status.json")
    rows = doc.get("adapters") if isinstance(doc, dict) else None
    out: dict[str, dict] = {}
    for a in rows or []:
        if isinstance(a, dict) and a.get("protocol"):
            out[str(a["protocol"])] = a
    return out


def pool_snapshot(ddir: Path) -> dict:
    """Per-pool live observation from the orchestrator snapshot (the money path's own input)."""
    doc, err = _load(ddir / "adapter_orchestrator_status.json")
    return {"measured": err is None, "reason": err,
            "as_of": (doc or {}).get("generated_at") if isinstance(doc, dict) else None,
            "pools": _orchestrator(ddir)}


def _conservative(ddir: Path) -> dict:
    cp, err = _load(ddir / "current_positions.json")
    curve, err2 = _load(ddir / "equity_curve_daily.json")
    if err or not isinstance(cp, dict):
        return {"measured": False, "reason": err or "current_positions.json not an object"}
    raw_pos = cp.get("positions")
    pos: dict = raw_pos if isinstance(raw_pos, dict) else {}
    pools = _orchestrator(ddir)
    positions = []
    for proto, usd in sorted(pos.items()):
        usd_f = _num(usd)
        if usd_f is None or usd_f <= 0:
            continue
        snap = pools.get(proto, {})
        positions.append({"protocol": proto, "notional_usd": round(usd_f, 2),
                          "apy_pct": _num(snap.get("apy_pct")),
                          "apy_source": "orchestrator snapshot" if snap else None,
                          "apy_live": bool(snap.get("live_data")) if snap else None})
    daily = (curve or {}).get("daily") if isinstance(curve, dict) else None
    series = [{"date": r.get("date"), "equity": _num(r.get("equity")),
               # None = the bar carries no cost field (bars before costs were charged, ADR-298) —
               # kept as None, never read as a measured zero (invariant #17).
               "cost_usd": _num(r.get("cost_usd")),
               "yield_usd": _num(r.get("daily_yield_usd"))}
              for r in (daily or []) if isinstance(r, dict) and r.get("evidenced") is True]
    return {
        "measured": True,
        "engine": _ENGINES["conservative"],
        "nav_usd": _num(cp.get("current_equity_usd")),
        "capital_usd": _num(cp.get("capital_usd")),
        "cash_usd": _num(cp.get("cash_usd")),
        "cash_reason": None if _num(cp.get("cash_usd")) is not None else "current_positions.json has no cash_usd",
        "notional_minus_nav_usd": None,
        "positions": positions,
        "series": series,
        "series_basis": "evidenced daily bars (equity_curve_daily.json, evidenced=True)",
        "series_reason": err2,
        "pre_fix_rows": 0,
        "peak_equity": max((r["equity"] for r in series if r["equity"]), default=None),
    }


def _sleeve(ddir: Path, book: str) -> dict:
    from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL

    st, err = _load(ddir / _SLEEVE_FILES[book])
    if err or not isinstance(st, dict):
        return {"measured": False, "reason": err or f"{_SLEEVE_FILES[book]} not an object"}
    positions = []
    for p in st.get("positions") or []:
        if not isinstance(p, dict) or not p.get("protocol"):
            continue
        usd = _num(p.get("notional_usd"))
        if usd is None or usd <= 0:
            continue
        positions.append({"protocol": str(p["protocol"]), "notional_usd": round(usd, 2),
                          "apy_pct": _num(p.get("apy_pct")),
                          "apy_source": "book's observed rate (sleeve state)",
                          "apy_live": (not bool(p.get("stale"))) if "stale" in p else None,
                          "stamped_delta_neutral": p.get("is_delta_neutral")})
    # ADR-533: the mechanic sub-books are positions of the book too
    legs = (st.get("fixed_carry") or {}).get("legs") or []
    if legs:
        positions.append({"protocol": "pendle_pt_susds",
                          "notional_usd": round(sum(float(l["units"]) * float(l["mark"]) for l in legs), 2),
                          "apy_pct": None, "apy_source": "fixed rate locked at purchase (PT price)",
                          "apy_live": all(bool(l.get("mark_ok")) for l in legs),
                          "kind": "pt_fixed", "legs": len(legs)})
    loop = st.get("loop") or {}
    if loop.get("status") == "open":
        lv = loop.get("last_valuation") or {}
        positions.append({"protocol": "morpho_susde_pyusd_loop",
                          "notional_usd": round(float(lv.get("equity") or 0.0), 2),
                          "apy_pct": None, "apy_source": "simulated loop: collateral share price − debt growth",
                          # live only if the LATEST run measured the loop (not the stale fallback)
                          "apy_live": int(loop.get("unmeasured_runs") or 0) == 0 and lv.get("at") is not None,
                          "kind": "loop",
                          "debt_usd": lv.get("debt_value"), "hf": lv.get("hf")})
    hist = [h for h in (st.get("daily_history") or []) if isinstance(h, dict)]
    v2 = [h for h in hist if h.get("economics_model") == ECONOMICS_MODEL]
    series = [{"date": h.get("date"), "equity": _num(h.get("equity")),
               "cost_usd": _num(h.get("cost_usd")), "yield_usd": _num(h.get("daily_yield_usd"))}
              for h in v2]
    deployed = sum(p["notional_usd"] for p in positions)
    nav = _num(st.get("equity"))
    return {
        "measured": True,
        "engine": _ENGINES[book],
        "nav_usd": nav,
        "capital_usd": _num(st.get("seed_equity")),
        # A sleeve state carries NO cash field: its legs are sized on equity and may exceed it by
        # one day's charged cost until the next re-size (ADR-531). A residual NAV − Σnotional
        # would publish a negative "cash"; the mismatch is named on its own instead.
        "cash_usd": None,
        "cash_reason": "sleeve state carries no cash field",
        "notional_minus_nav_usd": (round(deployed - nav, 2) if nav is not None else None),
        "positions": positions,
        "series": series,
        "series_basis": f"`{ECONOMICS_MODEL}` rows only (owner Option A, 2026-10-01)",
        "series_reason": None if series else "no rows written by the corrected cost model yet",
        "pre_fix_rows": len(hist) - len(v2),
        "peak_equity": max((r["equity"] for r in series if r["equity"]), default=None),
    }


def load_books(data_dir: "Path | str") -> dict[str, dict]:
    ddir = Path(data_dir)
    out = {"conservative": _conservative(ddir)}
    for book in ("balanced", "aggressive"):
        try:
            out[book] = _sleeve(ddir, book)
        except Exception as exc:  # noqa: BLE001 — a broken book is a named outcome
            out[book] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
    for book, g in gates().items():
        out.setdefault(book, {"measured": False, "reason": "not loaded"})["gate"] = g
    return out
