#!/usr/bin/env python3
"""
scripts/edge_causal_window_robustness.py — RE-VALIDATION (not a new idea): is the Idea #9
causal drawdown-overlay edge ROBUST ACROSS all three crisis windows, or CONCENTRATED in one?

Overfitting is the #1 failure mode of a backtested edge: an aggregate Calmar advantage can be
driven entirely by ONE lucky crisis while the controller is neutral-or-harmful in the others. A
generalization audit is the OPPOSITE of overfitting — it stress-tests a claimed edge rather than
manufacturing another one. This script introduces NO new signal and re-tunes NOTHING: it replays
the EXACT #9 causal controller (the best-by-aggregate-Calmar sweep row) and the #3 static baseline
from ``edge_causal_drawdown_overlay.run_analysis()``, then ATTRIBUTES the edge per STRESS_WINDOW —
within each crisis, did the causal book preserve more capital (higher within-window return) than
the static blend?

HONEST SCOPE. The aggressive_lab fixture is SYNTHETIC and only the sUSDe leg carries real crisis
vol (rates/RWA are smooth synthetic), so this measures generalization across the three synthetic
crisis SHAPES, not out-of-sample on real market data. A real-data version needs a REAL book-return
series aligned to real exogenous signals: data/peg_history.json + data/perp_funding_rate_history.json
exist, but aligning a real signal to a real book P&L on one shared date axis (so lead-lag is genuine,
not circular) is a separate, careful task — flagged here, never faked. Using a real peg series against
this synthetic book's hardcoded drawdown timing would be circular and is deliberately NOT done.

VERDICT
  ROBUST        — causal preserves more capital than static in >= 2 of the 3 windows
  CONCENTRATED  — advantage in exactly 1 window (the aggregate edge IS that window; generalization unproven)
  NONE          — advantage in 0 windows (the aggregate edge came from between-crisis carry, not defense)

EXIT 0 always (advisory R&D). stdlib-only, deterministic, read-only — mutates nothing, no network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

_NINE = Path(__file__).resolve().parent / "edge_causal_drawdown_overlay.py"


def _load_nine():
    """Load the Idea #9 module by path (mirrors how its test suite loads it)."""
    spec = importlib.util.spec_from_file_location("edge_causal_drawdown_overlay", _NINE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _window_segment(dates: List[str], eq: List[float], d_from: str, d_to: str) -> Optional[List[float]]:
    """
    Equity segment spanning a crisis window. eq[0] is the pre-series initial; dates[i] maps to
    eq[i+1]. eq[first] is therefore the value ENTERING the window (close of the day before the
    first window day); eq[last+1] is the value at the window's close. Returns None if the window
    is outside the fixture's date range.
    """
    lo = datetime.date.fromisoformat(d_from)
    hi = datetime.date.fromisoformat(d_to)
    idx = [i for i, d in enumerate(dates) if lo <= datetime.date.fromisoformat(d) <= hi]
    if not idx:
        return None
    first, last = idx[0], idx[-1]
    return eq[first:last + 2]


def _ret_and_maxdd(seg: List[float]):
    ret = seg[-1] / seg[0] - 1.0
    peak = seg[0]
    mdd = 0.0
    for e in seg:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < mdd:
            mdd = dd
    return ret, abs(mdd)


def run_analysis() -> Dict[str, object]:
    """Deterministic; returns a structured verdict dict (no printing)."""
    nine = _load_nine()
    base = nine.run_analysis()
    windows = nine.STRESS_WINDOWS

    dates: List[str] = base["dates"]              # type: ignore[assignment]
    eq_static: List[float] = base["static"]["equity"]      # type: ignore[index]
    eq_causal: List[float] = base["best"]["equity"]        # type: ignore[index]

    rows = []
    advantage = 0
    for w in windows:
        ss = _window_segment(dates, eq_static, str(w["date_from"]), str(w["date_to"]))
        cs = _window_segment(dates, eq_causal, str(w["date_from"]), str(w["date_to"]))
        if ss is None or cs is None:
            rows.append({"key": w["key"], "covered": False})
            continue
        s_ret, s_dd = _ret_and_maxdd(ss)
        c_ret, c_dd = _ret_and_maxdd(cs)
        causal_better = c_ret > s_ret + 1e-9  # preserved more capital THROUGH the crisis
        if causal_better:
            advantage += 1
        rows.append({
            "key": w["key"], "label": w["label"], "covered": True,
            "static_ret": s_ret, "static_maxdd": s_dd,
            "causal_ret": c_ret, "causal_maxdd": c_dd,
            "ret_edge": c_ret - s_ret, "dd_edge": s_dd - c_dd,
            "causal_better": causal_better,
        })

    covered = [r for r in rows if r.get("covered")]
    verdict = "ROBUST" if advantage >= 2 else "CONCENTRATED" if advantage == 1 else "NONE"
    return {
        "n_windows_covered": len(covered),
        "n_causal_advantage": advantage,
        "verdict": verdict,
        "aggregate_static_calmar": base["static"]["calmar"],   # type: ignore[index]
        "aggregate_causal_calmar": base["best"]["calmar"],     # type: ignore[index]
        "rows": rows,
    }


def main() -> None:
    r = run_analysis()
    print("Idea #9 causal drawdown-overlay — per-crisis ROBUSTNESS re-validation (synthetic fixture)")
    sc = r["aggregate_static_calmar"]
    cc = r["aggregate_causal_calmar"]
    print(f"  aggregate Calmar: static={sc:.2f}  causal={cc:.2f}")
    print(f"  windows covered: {r['n_windows_covered']}/3   causal-advantage windows: {r['n_causal_advantage']}")
    for row in r["rows"]:                                    # type: ignore[union-attr]
        if not row.get("covered"):
            print(f"  - {row['key']:24s} not covered by fixture date range")
            continue
        mark = "causal preserved more" if row["causal_better"] else "no within-crisis edge"
        print(f"  - {row['key']:24s} static_ret={row['static_ret'] * 100:+6.2f}%  "
              f"causal_ret={row['causal_ret'] * 100:+6.2f}%  edge={row['ret_edge'] * 100:+5.2f}pp  [{mark}]")
    tail = {
        "ROBUST": "edge GENERALIZES across crises",
        "CONCENTRATED": "edge CONCENTRATED in one crisis — generalization UNPROVEN (overfit risk)",
        "NONE": "no within-crisis defense edge — aggregate advantage came from between-crisis carry",
    }[r["verdict"]]
    print(f"  VERDICT: {r['verdict']} — {tail}")


if __name__ == "__main__":
    main()
