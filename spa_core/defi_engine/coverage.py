"""spa_core/defi_engine/coverage.py — which sensor watches which held position (P1-3 / P1-13).

The audit (§C #14, §F) found 30 % of the Conservative book with no liquidity sensor (maple,
morpho_blue_base), no rate-shock sensor anywhere, and the sleeve books watched by nothing that was
sized on THEIR positions. This module turns that sentence into a measurement, per held position
of every book, along the five RTMR dimensions:

=============  =================================================================================
dimension      what counts as covered
=============  =================================================================================
``peg``        the position's underlying asset is in the RTMR peg quorum
``oracle``     the underlying asset has an RTMR oracle feed
``tvl``        the protocol family is a scope of the RTMR TVL-collapse sensor
``liquidity``  the RTMR exit-liquidity sensor is SIZED on this position (it is sized on the
               Conservative book only — a sleeve position in the same protocol is not covered)
``rate``       an RTMR rate sensor — none exists; the advisory ``rate_watch`` below is daily
=============  =================================================================================

Declared coverage (the sensors' own scope tables) is cross-checked with OBSERVED coverage — a
fresh, non-stale signal for that scope in ``data/monitoring/signals/latest.json``. Declared but
not observed is reported as such: a scope table is a claim, a signal is evidence.

``rate_watch`` is an ADVISORY daily rate-shock check for every held pool of every book: today's
spot APY against the median of the pool's own live daily series (``apy_series_daily.json``,
≥ 7 points). Outside ``[0.5×, 2×]`` ⇒ finding. Too short a series ⇒ ``unmeasured``. It reacts to
nothing; an RTMR rate sensor with a reaction is a change to the de-risk ladder (ADR-532 §Owner gate).

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Optional

#: registry key → RTMR TVL-sensor scope (``sensors/build._TVL_SLUGS`` values).
_TVL_SCOPE = {
    "aave_v3": "aave_v3", "compound_v3": "compound_v3",
    "morpho_blue": "morpho_blue", "morpho_blue_base": "morpho_blue", "morpho_steakhouse": "morpho_blue",
    "fluid_fusdc": "fluid", "fluid_usdc": "fluid", "fluid_arbitrum": "fluid",
    "susde": "ethena", "ethena_susde": "ethena",
    "spark_susds": "spark", "sky_susds": "sky",
}

RATE_MIN_POINTS = 7
RATE_BAND = (0.5, 2.0)
SIGNAL_FRESH_SEC = 15 * 60


def _declared() -> dict:
    """The sensors' own scope tables — read from the sensor modules, never retyped here."""
    out: dict = {"measured": True, "peg_assets": [], "oracle_assets": [], "tvl_scopes": [],
                 "liquidity_scopes": []}
    try:
        from spa_core.monitoring.sensors import build as B
        out["peg_assets"] = list(getattr(B, "_DEFAULT_ASSETS", []))
        out["tvl_scopes"] = sorted(set(getattr(B, "_TVL_SLUGS", {}).values()))
        out["oracle_assets"] = list(getattr(B, "_DEFAULT_ASSETS", []))
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"sensors.build unreadable: {exc}"
        out["measured"] = False
    try:
        from spa_core.monitoring.sensors import liquidity_providers as LP
        out["liquidity_scopes"] = sorted(getattr(LP, "_SLUGS", {}))
    except Exception as exc:  # noqa: BLE001
        out["error_liquidity"] = f"liquidity_providers unreadable: {exc}"
        out["measured"] = False
    return out


def _observed(data_dir: Path, now_ts: float) -> dict:
    """{(source, scope)} with a fresh, non-stale signal. Unreadable ⇒ measured False."""
    path = data_dir / "monitoring" / "signals" / "latest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"signals/latest.json unreadable: {type(exc).__name__}",
                "fresh": set()}
    ts = doc.get("ts") if isinstance(doc, dict) else None
    age = (now_ts - float(ts)) if isinstance(ts, (int, float)) else None
    if age is None:
        return {"measured": False, "reason": "signals/latest.json carries no ts", "fresh": set()}
    if age > SIGNAL_FRESH_SEC:
        # The sense loop itself is not reporting: that is "we cannot see", not "nothing is covered".
        return {"measured": False, "age_sec": round(age, 1), "fresh_window_sec": SIGNAL_FRESH_SEC,
                "reason": f"signals/latest.json is {round(age)} s old (> {SIGNAL_FRESH_SEC} s)",
                "fresh": set()}
    fresh = set()
    for s in doc.get("signals", []):
        if isinstance(s, dict) and s.get("staleness_ok") is True:
            fresh.add((s.get("source"), s.get("scope")))
    return {"measured": True, "age_sec": round(age, 1), "fresh_window_sec": SIGNAL_FRESH_SEC,
            "fresh": fresh}


def rate_watch(key: str, spot_apy: Optional[float], series: Optional[dict]) -> dict:
    if series is None:
        return {"status": "unmeasured", "reason": "apy_series_daily.json unreadable"}
    pts = [float(v) for _d, v in (series.get(key) or [])
           if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
    if spot_apy is None:
        return {"status": "unmeasured", "reason": "no spot APY for the pool"}
    if len(pts) < RATE_MIN_POINTS:
        return {"status": "unmeasured", "reason": f"own live series has {len(pts)} < {RATE_MIN_POINTS} points"}
    base = statistics.median(pts[-30:])
    ratio = spot_apy / base if base > 0 else None
    if ratio is None:
        return {"status": "unmeasured", "reason": "zero baseline"}
    lo, hi = RATE_BAND
    return {"status": "ok" if lo <= ratio <= hi else "shock",
            "spot_apy_pct": round(spot_apy, 4), "baseline_median_pct": round(base, 4),
            "baseline_points": min(len(pts), 30), "ratio": round(ratio, 4), "band": [lo, hi]}


def position_coverage(book_id: str, key: str, declared: dict, observed: dict,
                      conservative_held: set) -> dict:
    from spa_core.defi_engine.mechanics import underlying_of

    asset = underlying_of(key)
    tvl_scope = _TVL_SCOPE.get(key)
    dims = {
        "peg": {"declared": asset in declared["peg_assets"], "scope": asset},
        "oracle": {"declared": asset in declared["oracle_assets"], "scope": asset},
        "tvl": {"declared": tvl_scope in declared["tvl_scopes"], "scope": tvl_scope},
        "liquidity": {"declared": (key in declared["liquidity_scopes"] and book_id == "conservative"
                                   and key in conservative_held), "scope": key,
                      "note": None if book_id == "conservative" else
                      "the RTMR liquidity sensor is sized on the Conservative book only"},
        "rate": {"declared": False, "scope": None, "note": "no RTMR rate sensor exists"},
    }
    src = {"peg": "peg", "oracle": "oracle", "tvl": "tvl", "liquidity": "liquidity", "rate": "rate"}
    for name, d in dims.items():
        if not observed.get("measured"):
            d["observed"] = None
        else:
            d["observed"] = (src[name], d["scope"]) in observed["fresh"] if d["scope"] else False
    if not declared.get("measured", True):
        for d in dims.values():
            d["declared"] = None
    # Three outcomes per dimension: covered · uncovered · unmeasured (invariant #17). A dimension
    # with no declared scope is uncovered whatever the signals say; otherwise an unmeasured side
    # makes it unmeasured, never uncovered.
    uncovered, unmeasured = [], []
    for n, d in dims.items():
        if d["declared"] is False:
            uncovered.append(n)
        elif d["declared"] is None or d["observed"] is None:
            unmeasured.append(n)
        elif not d["observed"]:
            uncovered.append(n)
    return {"dimensions": dims, "uncovered": sorted(uncovered), "unmeasured": sorted(unmeasured)}


def coverage_report(books: dict, data_dir: "Path | str", now_ts: float) -> dict:
    ddir = Path(data_dir)
    declared = _declared()
    observed = _observed(ddir, now_ts)
    try:
        _doc = json.loads((ddir / "apy_series_daily.json").read_text(encoding="utf-8"))
        series = _doc.get("series") if isinstance(_doc, dict) and isinstance(_doc.get("series"), dict) else None
    except Exception:  # noqa: BLE001 — unreadable ⇒ rate_watch says so, never "0 points"
        series = None
    cons = books.get("conservative") or {}
    cons_held = {p["protocol"] for p in cons.get("positions") or []}
    per_book: dict[str, list] = {}
    totals = {"positions": 0, "fully_covered": 0, "with_unmeasured": 0, "by_dimension_uncovered": {}}
    for book_id, book in books.items():
        rows = []
        for p in (book.get("positions") or []) if book.get("measured") else []:
            cov = position_coverage(book_id, p["protocol"], declared, observed, cons_held)
            cov["rate_watch"] = rate_watch(p["protocol"], p.get("apy_pct"), series)
            rows.append({"protocol": p["protocol"], **cov})
            totals["positions"] += 1
            if not cov["uncovered"] and not cov["unmeasured"]:
                totals["fully_covered"] += 1
            if cov["unmeasured"]:
                totals["with_unmeasured"] += 1
            for d in cov["uncovered"]:
                totals["by_dimension_uncovered"][d] = totals["by_dimension_uncovered"].get(d, 0) + 1
        per_book[book_id] = rows
    obs = {k: v for k, v in observed.items() if k != "fresh"}
    obs["fresh_scopes"] = sorted(f"{a}:{b}" for a, b in observed.get("fresh", set()))
    return {"declared": declared, "observed": obs, "books": per_book, "totals": totals,
            "rate_watch_basis": f"median of the pool's own live daily series, ≥{RATE_MIN_POINTS} points, "
                                f"band {RATE_BAND[0]}×…{RATE_BAND[1]}× (advisory, reacts to nothing)"}
