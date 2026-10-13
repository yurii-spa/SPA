#!/usr/bin/env python3
"""
scripts/edge_admitted_set_guardian_zero.py — registry ideas #131 (ASE) and #132 (GZ)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

Both sections execute ORDERS left verbatim by registry entry #129; neither invents its own
question.

    #129 order 1
        "Expand the ADMITTED SET, not the denominator: #128 p.5 showed that with <= 5 admitted
         names the 20 % ceiling makes any risk-inverse sizer unobservable. Check how many names
         have to be admitted before 1/max(sigma, sigma_floor) under the ceiling starts to differ
         from equal weight at all, and whether such a set EXISTS on this panel. Acceptance: the
         number of admitted names at which the capped answer stops being bitwise equal to the
         equal-weight answer is PRINTED, or there is a REFUSAL with a named cause that no such
         number exists on the panel."
        -> section 1, `ase_report()`

    #129 order 2 (= #126 order 1, the last unexecuted order of the #123...#127 series)
        "Re-measure flagship #1 with ITS OWN instrument (scripts/guardian_backtest.py, the same
         settings that produced the published table of #1) on the real panel against BOTH zeros.
         Acceptance: dCalmar against EW-10 and against EW-live printed side by side by the same
         instrument that produced table #1, each carrying a `calmar_degenerate` verdict (#129),
         so that `the overlay does not work` and `the denominator was smaller than the toll`
         stop being indistinguishable."
        -> section 2, `guardian_zero_report()`

Everything measured here is advisory. No capital moves, the go-live track
(data/equity_curve_daily.json) is never opened, RiskPolicy v1.0 is untouched, and nothing is
written to disk: both reports only print.

WHY NOTHING IS REIMPLEMENTED HERE. The panel loader, the toll convention, the drawdown verdict,
the cap water-fill and the degeneracy verdict are IMPORTED from
scripts/edge_sigma_floor_ctac_real.py (which in turn imports scripts/edge_real_panel_ensemble.py)
and the guardian overlay is IMPORTED from scripts/guardian_backtest.py. A second copy of either
would make these numbers incomparable with #122-#129 and with table #1 BY CONSTRUCTION, which is
the one way this measurement could be green and meaningless at the same time. The single loop
this file does own (`run_sizer_rule`, which #128's `run_sizer` cannot provide because its
admission rule is hard-coded) is checked against `S.run_sizer` BITWISE for the one rule they
share - test `test_rule_loop_reproduces_sfs_bitwise`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
SFS = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"
GUARDIAN = ROOT / "scripts" / "guardian_backtest.py"

#: canonical round-trip toll (#10/#49). Imported value is authoritative; this is the fallback
#: only for the degenerate case where the import itself failed, and that case raises instead.
ROUNDTRIP = 0.0096
#: per-name policy ceiling. OWNER-GATED NUMBER: it lives in RiskPolicy v1.0 and moves only by
#: ADR. This file MEASURES what it does and never changes it.
POLICY_CAP = 0.20
#: a return below this counts as a day down. Same symmetric epsilon as #128.
EPS = 1e-12
#: the published out-of-sample settings of flagship #1 (registry UPD5): pre-emptive vol guardian,
#: full exit on a hostile regime. `derisk_frac=0.0` IS the "full-exit" of that line.
IDEA1_VOL = {"lookback": 10, "vol_mult": 2.0, "derisk_frac": 0.0, "calm_mult": 1.2}
#: the reactive guardian defaults that produced the FIRST published table of #1.
IDEA1_REACTIVE = {"derisk_dd": 0.04, "derisk_frac": 0.25, "reenter_frac": 0.5}

_MOD_CACHE: Dict[str, object] = {}


def _load(path: Path, name: str):
    key = f"{name}:{path}"
    if key not in _MOD_CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import {name} at {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _MOD_CACHE[key] = mod
    return _MOD_CACHE[key]


def sfs_mod(path: Path = SFS):
    """scripts/edge_sigma_floor_ctac_real.py — the #128/#129 instrument set."""
    return _load(path, "edge_sigma_floor_ctac_real")


def guardian_mod(path: Path = GUARDIAN):
    """scripts/guardian_backtest.py — the instrument that produced table #1."""
    return _load(path, "guardian_backtest")


def panel_mod():
    return sfs_mod().load_harness()


# ═══════════════════════ §1 · #131 ASE: the admitted set ═══════════════════════
#
# Two questions hide inside the order, and telling them apart IS the content of this section.
#
#   Q_flat    "is the capped weight vector FLAT, i.e. are all admitted names equal?"
#             -> this is what #128 p.5 actually measured: when the cap binds every name, the
#                1/sigma denominator cannot express anything, whatever its value.
#   Q_bitwise "is the capped vector BITWISE EQUAL to equal weight over the admitted names?"
#             -> this is the LETTER of the order.
#
# They differ, and the difference is a trap of exactly the class #129 warned about. With k < 1/cap
# names the water-fill pins every name at `cap` and parks the rest in CASH: the vector is FLAT
# (denominator inert) but NOT bitwise equal to equal weight, because equal weight deploys 1/k > cap
# per name. So the letter of the order is satisfied at k = 1 by a degenerate branch in which the
# sizer expresses nothing at all. This file prints BOTH thresholds and answers the order by the
# flatness one, saying so out loud.


def is_flat(weights: Dict[str, float], admitted: Sequence[str], *, tol: float = 0.0) -> bool:
    """True iff every admitted name carries the same weight, to within `tol`.

    THE TOLERANCE IS THE WHOLE POINT, and `tol=0.0` is kept available only so the artifact stays
    visible. Measured here: at k = 5 under a 20 % ceiling `cap_waterfill` returns
    0.2, 0.2, 0.2, 0.2, 0.19999999999999996 — four names at the ceiling and a fifth carrying the
    float64 residue of the last renormalising division, 4e-17 of capital. Exact equality calls
    that vector NOT flat and so reports the threshold as k* = 5; the difference is a rounding
    remainder, not a decision any sizer made. With `tol = EPS` (1e-12, the same epsilon the
    registry already uses to tell a day down from arithmetic noise) the threshold is k* = 6, which
    is also the arithmetic one: ceil(1/cap) + 1. Both numbers are printed, because a measurement
    whose answer is a float remainder has to be named as such rather than quietly inherited.
    """
    if not admitted:
        return True
    first = weights.get(admitted[0], 0.0)
    if tol <= 0.0:
        return all(weights.get(b, 0.0) == first for b in admitted)
    return all(abs(weights.get(b, 0.0) - first) <= tol for b in admitted)


def is_bitwise_ew(weights: Dict[str, float], admitted: Sequence[str]) -> bool:
    """True iff the vector equals equal weight over the admitted names, bit for bit."""
    if not admitted:
        return True
    target = 1.0 / len(admitted)
    return all(weights.get(b, 0.0) == target for b in admitted)


def arithmetic_thresholds(*, cap: float = POLICY_CAP, kmax: int = 12,
                          sigma_ladder: float = 2.0) -> Dict[str, object]:
    """MEASURE (not assert) the k at which a capped inverse-sigma vector stops being flat / EW.

    The probe feeds k names whose sigmas are maximally distinct by construction
    (sigma_i = 1e-3 * ladder**i), so if the capped answer is still flat the cause can only be the
    ceiling, never a coincidence of equal risks. This is an ARITHMETIC fact about `cap_waterfill`,
    stated as a measurement so that a future change to the water-fill cannot silently invalidate
    the sentence this section prints.
    """
    S = sfs_mod()
    rows: List[Dict[str, object]] = []
    k_flat: Optional[int] = None
    k_flat_exact: Optional[int] = None
    k_bitwise: Optional[int] = None
    for k in range(1, kmax + 1):
        names = [f"b{i}" for i in range(k)]
        sig = {names[i]: 1e-3 * (sigma_ladder ** i) for i in range(k)}
        raw = {b: 1.0 / sig[b] for b in names}
        tot = sum(raw.values())
        shares = {b: raw[b] / tot for b in names}
        out = S.cap_waterfill(shares, cap=cap)
        w = out["weights"]
        flat_exact = is_flat(w, names, tol=0.0)
        flat_eps = is_flat(w, names, tol=EPS)
        bw = is_bitwise_ew(w, names)
        spread = (max(w[b] for b in names) - min(w[b] for b in names)) if names else 0.0
        rows.append({"k": k, "flat_exact": flat_exact, "flat_eps": flat_eps, "bitwise_ew": bw,
                     "spread": spread, "deployed": out["deployed"], "cash": out["cash"],
                     "max_name": max(w.values()), "degenerate": out["degenerate"]})
        if not flat_exact and k_flat_exact is None:
            k_flat_exact = k
        if not flat_eps and k_flat is None:
            k_flat = k
        if not bw and k_bitwise is None:
            k_bitwise = k
    return {"cap": cap, "kmax": kmax, "rows": rows,
            "k_flat_threshold": k_flat, "k_flat_threshold_exact": k_flat_exact,
            "k_bitwise_threshold": k_bitwise,
            "refusal": None if k_flat is not None else
                       (f"with a {cap:.0%} ceiling the capped vector is flat for every k up to "
                        f"{kmax}: no admitted-set size makes the denominator observable")}


# ───────────────────────── admission rules (the ladder) ─────────────────────────
#
# Every rung changes EXACTLY ONE ingredient against #128's rule, so "the set got bigger" can
# never be confused with "the sizer got better". All rungs are causal by construction: the
# evidence window ends STRICTLY before the day whose weight it decides.

def _win(rets: Dict[str, Sequence[float]], book: str, end: int, lookback: int) -> List[float]:
    lo = max(0, end - lookback)
    return [rets[book][i] for i in range(lo, end)]


def rule_down_days(lookback: int) -> Callable[[Dict[str, Sequence[float]], str, int], bool]:
    """#128's rule, with the estimation window as the single free ingredient."""
    def _f(rets, book, end):
        return sum(1 for x in _win(rets, book, end, lookback) if x < -EPS) >= 1
    return _f


def rule_ever_down(rets: Dict[str, Sequence[float]], book: str, end: int) -> bool:
    """Admit a book that has EVER been observed falling, over the expanding history [0, end).

    This is the honest maximal expansion of the admitted set that still refuses the unmeasured:
    it asks "has this book ever been seen to fall?" rather than "did it fall this month?". It is
    still causal - `end` is excluded - and it is still a REFUSAL rule, not an absence of one.
    """
    return sum(1 for x in rets[book][:end] if x < -EPS) >= 1


def rule_sigma_positive(lookback: int = 30, floor: float = 1e-9):
    """Admit on MOVEMENT rather than on downside: trailing sigma strictly above a floor.

    Weaker than every rule above - a book that only ever moves up passes - and included because
    the order asks how far the admitted set can be pushed, not only how far it should be.
    """
    def _f(rets, book, end):
        win = _win(rets, book, end, lookback)
        return (statistics.pstdev(win) if len(win) > 1 else 0.0) > floor
    return _f


def rule_admit_all(rets, book, end) -> bool:
    """No refusal at all - the sizer of registry line #17. The known leak, kept as the control."""
    return True


ADMISSION_LADDER: List[Tuple[str, Callable, str]] = [
    ("base30", rule_down_days(30), "#128's rule: >=1 day down in the trailing 30 days"),
    ("base60", rule_down_days(60), "same rule, 60-day evidence window"),
    ("base90", rule_down_days(90), "same rule, 90-day evidence window"),
    ("ever_down", rule_ever_down, ">=1 day down over the whole history before today"),
    ("sigma_pos", rule_sigma_positive(30), "trailing 30d sigma > 0 (movement, not downside)"),
    ("admit_all", rule_admit_all, "no refusal at all - the #17 sizer, the known leak"),
]


def run_sizer_rule(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
                   rule: Callable, lookback: int = 30, sigma_floor: float = 1e-5,
                   cap: Optional[float] = POLICY_CAP, frozen: Sequence[str] = (),
                   roundtrip: Optional[float] = None,
                   sizer: str = "inv_sigma") -> Dict[str, object]:
    """#128's `run_sizer` loop with the ADMISSION RULE as an argument.

    Identical in every other respect - same window, same water-fill, same toll on TRADED notional
    (ROUNDTRIP * sum|dw| / 2), same gross-series drawdown convention, same verdicts. It exists
    only because `S.run_sizer` hard-codes `down_days >= 1` over its own lookback and this section's
    whole question is what happens when that rule changes. Equivalence with the original for the
    one rule they share is a TEST, not a claim.

    `sizer="ew"` is THE control the order's wording makes necessary. The order says "expand the
    admitted SET, not the denominator", so when an expanded set performs better the question
    immediately becomes which of the two did the work. Equal weight over the SAME daily admitted
    set, under the SAME ceiling and the SAME toll, answers it: whatever both share is the
    admission rule's, and only the gap between them belongs to 1/sigma.
    """
    S = sfs_mod()
    H = panel_mod()
    roundtrip = S.ROUNDTRIP if roundtrip is None else roundtrip
    if lo < lookback:
        raise ValueError(f"start index {lo} is inside the first {lookback}-day window")
    if hi <= lo:
        raise ValueError("empty slice - refusing to report a portfolio of nothing")
    frozen_set = set(frozen)
    prev: Dict[str, float] = {b: 0.0 for b in books}
    clean: List[float] = []
    series: List[float] = []
    k_per_day: List[int] = []
    flat_days = 0
    flat_exact_days = 0
    weight_sum: Dict[str, float] = {b: 0.0 for b in books}
    bitwise_days = 0
    max_name_weight = 0.0
    max_name: Optional[str] = None
    max_name_day: Optional[int] = None
    cap_violation_days: Optional[int] = None if cap is None else 0
    days_over_policy_cap = 0
    frozen_share: List[float] = []
    frozen_admitted_days = 0
    deployed: List[float] = []
    turnover_total = 0.0
    degenerate_days = 0
    refused_weight_mass = 0.0
    admit_counts: Dict[str, int] = {b: 0 for b in books}
    for t in range(lo, hi):
        admitted = [b for b in books if rule(rets, b, t)]
        refused = [b for b in books if b not in admitted]
        for b in admitted:
            admit_counts[b] += 1
        k_per_day.append(len(admitted))
        if any(b in frozen_set for b in admitted):
            frozen_admitted_days += 1
        if not admitted:
            w = {b: 0.0 for b in books}
            dep, degen = 0.0, "no admitted name"
        else:
            stats = {b: {"sigma": statistics.pstdev(_win(rets, b, t, lookback))
                         if lookback > 1 else 0.0} for b in admitted}
            if sizer == "inv_sigma":
                raw = {b: 1.0 / max(stats[b]["sigma"], sigma_floor) for b in admitted}
            elif sizer == "ew":
                raw = {b: 1.0 for b in admitted}
            else:
                raise ValueError(f"unknown sizer {sizer!r}")
            tot = sum(raw.values())
            shares = {b: (raw[b] / tot if b in raw else 0.0) for b in books}
            if cap is None:
                w, dep, degen = shares, 1.0, None
            else:
                out = S.cap_waterfill(shares, cap=cap)
                w = out["weights"]
                dep, degen = float(out["deployed"]), out["degenerate"]
        if degen:
            degenerate_days += 1
        if is_flat(w, admitted, tol=EPS):
            flat_days += 1
        if is_flat(w, admitted, tol=0.0):
            flat_exact_days += 1
        if is_bitwise_ew(w, admitted):
            bitwise_days += 1
        for b in refused:
            refused_weight_mass += w.get(b, 0.0)
        for b in books:
            if w[b] > max_name_weight:
                max_name_weight, max_name, max_name_day = w[b], b, t
        if cap is not None and any(w[b] > cap + 1e-12 for b in books):
            cap_violation_days = (cap_violation_days or 0) + 1
        if any(w[b] > POLICY_CAP + 1e-12 for b in books):
            days_over_policy_cap += 1
        for b in books:
            weight_sum[b] += w[b]
        frozen_share.append(sum(w[b] for b in books if b in frozen_set))
        deployed.append(dep)
        turn = sum(abs(w[b] - prev[b]) for b in books) / 2.0
        turnover_total += turn
        gross = sum(w[b] * rets[b][t] for b in books)
        clean.append(gross)
        series.append(gross - roundtrip * turn)
        prev = w
    v = dict(S.drawdown_verdict(clean))
    n = hi - lo
    return {
        "n_days": n,
        "apy_gross": v.get("apy"),
        "apy_net": H.perf(series)["apy"],
        "maxdd": v.get("maxdd"),
        "calmar": v.get("calmar"),
        "dd_status": v.get("status"),
        "dd_reason": v.get("reason"),
        "calmar_degenerate": S.calmar_degenerate(v.get("maxdd")),
        "down_days": v.get("down_days"),
        "k_mean": sum(k_per_day) / n,
        "k_min": min(k_per_day),
        "k_max": max(k_per_day),
        "k_hist": {str(k): k_per_day.count(k) for k in sorted(set(k_per_day))},
        "flat_days": flat_days,
        "flat_share": flat_days / n,
        "flat_exact_days": flat_exact_days,
        "flat_exact_share": flat_exact_days / n,
        "mean_weight": {b: weight_sum[b] / n for b in books},
        "sizer": sizer,
        "bitwise_ew_days": bitwise_days,
        "bitwise_ew_share": bitwise_days / n,
        "frozen_admitted_days": frozen_admitted_days,
        "max_name_weight": max_name_weight,
        "max_name": max_name,
        "max_name_day": max_name_day,
        "cap_violation_days": cap_violation_days,
        "days_over_policy_cap": days_over_policy_cap,
        "mean_frozen_share": (sum(frozen_share) / len(frozen_share)) if frozen_share else None,
        "refused_weight_mass": refused_weight_mass,
        "mean_deployed": sum(deployed) / n,
        "min_deployed": min(deployed),
        "turnover_per_day": turnover_total / n,
        "degenerate_days": degenerate_days,
        "always_admitted": sorted(b for b in books if admit_counts[b] == n),
        "never_admitted": sorted(b for b in books if admit_counts[b] == 0),
        "series": series,
        "clean": clean,
    }


def falling_census(rets: Dict[str, Sequence[float]], books: Sequence[str], *,
                   lo: int = 0, hi: Optional[int] = None) -> Dict[str, object]:
    """How many names on this panel are EVER observed falling over [lo, hi) - and which.

    This is the number the order's "does such a set exist on this panel" turns on: a name that
    never falls can be admitted by no downside rule at any window length, so it can never be the
    k-th admitted name. Three outcomes are kept apart (inv. #17): `down` (measured, >0),
    `no_down_day` (measured, exactly zero) and `unmeasured_empty` (the slice holds no days at all).
    """
    hi = len(rets[books[0]]) if hi is None else hi
    per: Dict[str, Dict[str, object]] = {}
    for b in books:
        win = [rets[b][i] for i in range(lo, hi)]
        if not win:
            per[b] = {"down_days": None, "status": "unmeasured_empty", "moves": None}
            continue
        d = sum(1 for x in win if x < -EPS)
        per[b] = {"down_days": d, "moves": sum(1 for x in win if abs(x) > EPS),
                  "status": "down" if d else "no_down_day"}
    ever = sorted(b for b in books if (per[b]["down_days"] or 0) >= 1)
    never = sorted(b for b in books if per[b]["status"] == "no_down_day")
    return {"per_book": per, "ever_falling": ever, "n_ever_falling": len(ever),
            "never_falling": never, "lo": lo, "hi": hi}


def cap_counterfactual(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
                       rule: Callable, caps: Sequence[float] = (0.20, 0.25, 0.30, 0.34, 0.40, 0.50),
                       lookback: int = 30, sigma_floor: float = 1e-5) -> List[Dict[str, object]]:
    """What ceiling would make the denominator observable on the set this panel actually admits?

    A MEASUREMENT of a counterfactual, and nothing more. The 20 %/name ceiling is a RiskPolicy
    v1.0 threshold: it moves by ADR and by owner decision, never by a research script. Printing
    the number at which the sizer would start to speak is information for that decision; choosing
    it is not this file's act.
    """
    out: List[Dict[str, object]] = []
    for c in caps:
        r = run_sizer_rule(rets, books, lo=lo, hi=hi, rule=rule, lookback=lookback,
                           sigma_floor=sigma_floor, cap=c)
        out.append({"cap": c, "flat_share": r["flat_share"], "k_mean": r["k_mean"],
                    "max_name_weight": r["max_name_weight"], "apy_net": r["apy_net"],
                    "maxdd": r["maxdd"], "calmar": r["calmar"],
                    "calmar_degenerate": r["calmar_degenerate"],
                    "days_over_policy_cap": r["days_over_policy_cap"],
                    "mean_deployed": r["mean_deployed"]})
    return out


def sigma_floor_sweep(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
                      rule: Callable, floors: Sequence[float] = (1e-5, 1e-4, 1e-3, 5e-3, 1e-2),
                      cap: Optional[float] = POLICY_CAP,
                      lookback: int = 30) -> List[Dict[str, object]]:
    """#128 p.5's control, re-run on whatever admitted set `rule` produces.

    If the admitted set is big enough for the denominator to be observable, THIS sweep has to
    move the answer; if it returns bit-identical float64 again, the expansion did not expand
    anything that matters. The control therefore works in both directions.
    """
    out: List[Dict[str, object]] = []
    for f in floors:
        r = run_sizer_rule(rets, books, lo=lo, hi=hi, rule=rule, lookback=lookback,
                           sigma_floor=f, cap=cap)
        out.append({"sigma_floor": f, "apy_net": r["apy_net"], "maxdd": r["maxdd"],
                    "calmar": r["calmar"], "max_name_weight": r["max_name_weight"],
                    "flat_share": r["flat_share"]})
    return out


def three_conditions(row: Dict[str, object], base: Dict[str, object], *,
                     toll: Optional[float] = None, cap: float = POLICY_CAP) -> Dict[str, object]:
    """#129's three-part acceptance, printed as three separate booleans plus a verdict.

    (1) the denominator is above the toll - otherwise Calmar is an artifact of division;
    (2) the per-name ceiling is not breached on any day;
    (3) the income is above the base.
    #129 made this mandatory precisely so that reporting the first without the other two becomes
    impossible.
    """
    S = sfs_mod()
    toll = S.ROUNDTRIP if toll is None else toll
    mdd = row.get("maxdd")
    c1 = (mdd is not None) and (mdd > toll)
    c2 = (row.get("days_over_policy_cap") or 0) == 0
    apy, bapy = row.get("apy_net"), base.get("apy_net")
    c3 = (apy is not None and bapy is not None and apy > bapy)
    return {"denominator_above_toll": c1, "ceiling_held": c2, "income_above_base": c3,
            "all_three": bool(c1 and c2 and c3),
            "toll": toll, "base_apy_net": bapy,
            "note": (None if (c1 and c2 and c3) else
                     "at least one of #129's three conditions fails - the letter of any "
                     "ratio-based criterion is therefore not evidence here")}


def split_index(axis: Sequence[str], split: str) -> int:
    """Index of the first day STRICTLY after `split` — the train/test seam, measured not assumed."""
    return sum(1 for d in axis if d <= split)


def ase_report(panel_dir: Optional[Path] = None, *, lookback: int = 30,
               cap: float = POLICY_CAP) -> Dict[str, object]:
    """#131: how many names must be admitted before the capped sizer stops being equal weight?"""
    S = sfs_mod()
    H = panel_mod()
    pd_ = Path(panel_dir) if panel_dir else H.PANEL_DIR
    axis, rets, books = H.plb_load(pd_)
    census = H.book_census(pd_)
    era_idx, last_kill = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=era_idx)
    live, frozen = sorted(live), sorted(frozen)
    lo, hi = lookback, len(axis)
    seam = split_index(axis, H.TRAIN_END)
    if not (lo < seam < hi):
        raise RuntimeError(f"train/test seam at index {seam} is outside the judged slice "
                           f"[{lo}, {hi}) — refusing to report an out-of-sample claim")

    arith = arithmetic_thresholds(cap=cap)
    k_star = arith["k_flat_threshold"]

    fall_all = falling_census(rets, books, lo=lo, hi=hi)
    fall_live = falling_census(rets, live, lo=era_idx, hi=hi)

    zeros = {
        "ew10": S.ew_static(rets, books, lo=lo, hi=hi),
        "ew_live": S.ew_static(rets, live, lo=lo, hi=hi),
    }
    zeros_test = {
        "ew10": S.ew_static(rets, books, lo=seam, hi=hi),
        "ew_live": S.ew_static(rets, live, lo=seam, hi=hi),
    }

    def _strip(d: Dict[str, object]) -> Dict[str, object]:
        return {k: v for k, v in d.items() if k not in ("series", "clean")}

    rungs: Dict[str, Dict[str, object]] = {}
    for name, rule, why in ADMISSION_LADDER:
        row: Dict[str, object] = {"why": why}
        for sizer in ("inv_sigma", "ew"):
            r = run_sizer_rule(rets, books, lo=lo, hi=hi, rule=rule, lookback=lookback, cap=cap,
                               frozen=frozen, sizer=sizer)
            r["reaches_k_star"] = (None if k_star is None else
                                   sum(c for k, c in r["k_hist"].items() if int(k) >= k_star))
            r["three_vs_ew10"] = three_conditions(r, zeros["ew10"], cap=cap)
            r["three_vs_ew_live"] = three_conditions(r, zeros["ew_live"], cap=cap)
            row[sizer] = _strip(r)
        # the gap that belongs to the DENOMINATOR rather than to the admission rule
        a, b = row["inv_sigma"], row["ew"]
        row["denominator_gap"] = {
            "d_apy_net": (None if (a["apy_net"] is None or b["apy_net"] is None)
                          else a["apy_net"] - b["apy_net"]),
            "d_maxdd": (None if (a["maxdd"] is None or b["maxdd"] is None)
                        else a["maxdd"] - b["maxdd"]),
            "d_calmar": (None if (a["calmar"] is None or b["calmar"] is None)
                         else a["calmar"] - b["calmar"]),
        }
        rungs[name] = row

    # ── out of sample: the seam is the harness's own TRAIN_END, not a number chosen here ──
    oos: Dict[str, Dict[str, object]] = {}
    for name, rule, _why in ADMISSION_LADDER:
        oos[name] = {}
        for sizer in ("inv_sigma", "ew"):
            tr = run_sizer_rule(rets, books, lo=lo, hi=seam, rule=rule, lookback=lookback,
                                cap=cap, frozen=frozen, sizer=sizer)
            te = run_sizer_rule(rets, books, lo=seam, hi=hi, rule=rule, lookback=lookback,
                                cap=cap, frozen=frozen, sizer=sizer)
            te["three_vs_ew10"] = three_conditions(te, zeros_test["ew10"], cap=cap)
            te["three_vs_ew_live"] = three_conditions(te, zeros_test["ew_live"], cap=cap)
            oos[name][sizer] = {"train": _strip(tr), "test": _strip(te)}

    sweeps = {name: sigma_floor_sweep(rets, books, lo=lo, hi=hi, rule=rule, cap=cap)
              for name, rule, _why in ADMISSION_LADDER}
    counterfactual = cap_counterfactual(rets, books, lo=lo, hi=hi, rule=rule_ever_down)

    n_ever_live = fall_live["n_ever_falling"]
    exists = (k_star is not None) and (n_ever_live >= k_star)
    refusal = None
    if not exists and k_star is not None:
        refusal = (
            "under a DOWNSIDE admission rule such a set does NOT exist on the live arm of this "
            f"panel: the ceiling needs k >= {k_star} admitted names before a capped inverse-sigma "
            "vector can differ from equal weight by more than float residue, and only "
            f"{n_ever_live} of the {len(live)} books of the live arm are EVER observed falling over "
            f"the post-kill era ({', '.join(fall_live['ever_falling'])}; never falling: "
            f"{', '.join(fall_live['never_falling']) or 'none'}). The k-th name can therefore only "
            "come from a book that is dead or never measured falling — i.e. the expansion that "
            "would make the denominator observable under a downside rule is the same expansion "
            "#122/#126/#128 measured as the leak. The set DOES exist under a LIVENESS rule "
            "(sigma > 0), and that is a different rule, not a bigger window."
        )
    return {
        "panel_dir": str(pd_), "axis_days": len(axis), "axis": [axis[0], axis[-1]],
        "lookback": lookback, "cap": cap, "judged_days": hi - lo,
        "train_end": H.TRAIN_END, "seam_index": seam,
        "train_days": seam - lo, "test_days": hi - seam,
        "books": books, "live_arm": live, "frozen": frozen,
        "post_kill_era_index": era_idx, "last_kill": last_kill,
        "arithmetic": arith, "k_star": k_star,
        "falling_census_all": fall_all, "falling_census_live": fall_live,
        "zeros": {k: _strip(v) for k, v in zeros.items()},
        "zeros_test": {k: _strip(v) for k, v in zeros_test.items()},
        "rungs": rungs, "oos": oos,
        "sigma_floor_sweeps": sweeps, "cap_counterfactual": counterfactual,
        "admitted_set_exists": exists, "refusal": refusal,
    }


# ═════════════ §2 · #132 GZ: flagship #1 by its own instrument, vs both zeros ═════════════


def equity_of(returns: Sequence[float]) -> List[float]:
    """Equity curve from a return series, starting at 1.0 - the form `apply_guardian*` expects."""
    eq = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def returns_of(equity: Sequence[float]) -> List[float]:
    """Inverse of `equity_of`, so a guarded CURVE can be judged by the #128/#129 verdicts."""
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]


def exposure_switches(equity: Sequence[float], guarded: Sequence[float], *,
                      eps: float = 1e-15) -> int:
    """How many times the overlay changed exposure, inferred from the two curves.

    Needed because the LOCAL copies of the overlay in guardian_backtest.py - the ones that
    produced the published table of #1 - charge NO transaction cost, while both registry zeros pay
    the 96 bp round-trip. Comparing a free overlay with a tolled basket would hand the overlay a
    discount nobody granted it, so the toll is charged here, per switch, and printed separately
    from the untolled figure the published table used.
    """
    if len(equity) != len(guarded) or len(equity) < 2:
        return 0
    switches = 0
    prev_ratio: Optional[float] = None
    for i in range(1, len(equity)):
        raw = equity[i] / equity[i - 1] - 1.0
        g = guarded[i] / guarded[i - 1] - 1.0
        if abs(raw) <= eps:
            continue                      # a flat day carries no information about exposure
        ratio = g / raw
        if prev_ratio is not None and abs(ratio - prev_ratio) > 1e-9:
            switches += 1
        prev_ratio = ratio
    return switches


def judge_curve(equity: Sequence[float], *, switches: int = 0,
                toll: Optional[float] = None) -> Dict[str, object]:
    """Both verdicts on one curve: table #1's own metrics AND the #128/#129 honesty verdicts.

    `GB._metrics` returns PERCENT (net_apy_from_equity) while `H.perf` returns FRACTIONS; both are
    reported, each labelled, because silently mixing the two units is how a 23 % book becomes a
    0.23 % book in a comparison table.
    """
    S, GB = sfs_mod(), guardian_mod()
    toll = S.ROUNDTRIP if toll is None else toll
    apy_pct, mdd_pct, cal = GB._metrics(list(equity))
    rets = returns_of(equity)
    v = dict(S.drawdown_verdict(rets))
    tolled = list(rets)
    if tolled and switches:
        tolled[0] -= toll * switches          # charged up front: the count is what is measured
    H = panel_mod()
    return {
        "idea1_apy_pct": apy_pct, "idea1_maxdd_pct": mdd_pct, "idea1_calmar": cal,
        "apy_frac": v.get("apy"), "maxdd_frac": v.get("maxdd"), "calmar": v.get("calmar"),
        "dd_status": v.get("status"), "dd_reason": v.get("reason"),
        "down_days": v.get("down_days"),
        "calmar_degenerate": S.calmar_degenerate(v.get("maxdd")),
        "switches": switches,
        "apy_frac_after_switch_toll": (H.perf(tolled)["apy"] if tolled else None),
    }


def guardian_on(returns: Sequence[float], *, kind: str) -> Dict[str, object]:
    """Apply flagship #1's overlay to a return series, with #1's PUBLISHED settings."""
    GB = guardian_mod()
    eq = equity_of(returns)
    if kind == "vol":
        g = GB.apply_guardian_vol(eq, **IDEA1_VOL)
    elif kind == "reactive":
        g = GB.apply_guardian(eq, **IDEA1_REACTIVE)
    elif kind == "raw":
        g = list(eq)
    else:
        raise ValueError(f"unknown overlay kind {kind!r}")
    sw = 0 if kind == "raw" else exposure_switches(eq, g)
    out = judge_curve(g, switches=sw)
    out["kind"] = kind
    out["settings"] = dict(IDEA1_VOL if kind == "vol" else
                           IDEA1_REACTIVE if kind == "reactive" else {})
    return out


def delta_calmar(guarded: Dict[str, object], base: Dict[str, object]) -> Dict[str, object]:
    """dCalmar with BOTH degeneracy verdicts attached - the exact acceptance of #129 order 2.

    If either side is degenerate the delta is REFUSED rather than printed: subtracting an
    artifact of division from a measurement produces a number with no referent, and #129's whole
    point is that "the overlay does not help" and "the denominator was below the toll" must stop
    being the same cell in a table.
    """
    gc, bc = guarded.get("calmar"), base.get("calmar")
    gd, bd = guarded.get("calmar_degenerate"), base.get("calmar_degenerate")
    if gc is None or bc is None or gd or bd:
        return {"delta_calmar": None, "status": "refused",
                "reason": (f"guarded: {gd or ('calmar=' + repr(gc))}; "
                           f"base: {bd or ('calmar=' + repr(bc))}"),
                "guarded_calmar": gc, "base_calmar": bc,
                "guarded_degenerate": gd, "base_degenerate": bd}
    return {"delta_calmar": gc - bc, "status": "measured", "reason": None,
            "guarded_calmar": gc, "base_calmar": bc,
            "guarded_degenerate": None, "base_degenerate": None}


def guardian_zero_report(panel_dir: Optional[Path] = None) -> Dict[str, object]:
    """#132: flagship #1's overlay on the REAL panel, against EW-10 and EW-live."""
    H = panel_mod()
    pd_ = Path(panel_dir) if panel_dir else H.PANEL_DIR
    axis, rets, books = H.plb_load(pd_)
    census = H.book_census(pd_)
    era_idx, last_kill = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=era_idx)
    live = sorted(live)

    zeros: Dict[str, Dict[str, object]] = {}
    for zname, universe in (("ew10", books), ("ew_live", live)):
        basket = [sum(rets[b][i] for b in universe) / len(universe) for i in range(len(axis))]
        raw = guardian_on(basket, kind="raw")
        vol = guardian_on(basket, kind="vol")
        rea = guardian_on(basket, kind="reactive")
        zeros[zname] = {
            "universe": list(universe), "n_books": len(universe),
            "raw": raw, "vol": vol, "reactive": rea,
            "delta_vol": delta_calmar(vol, raw),
            "delta_reactive": delta_calmar(rea, raw),
        }

    per_book: Dict[str, Dict[str, object]] = {}
    for b in books:
        per_book[b] = {
            "raw": guardian_on(rets[b], kind="raw"),
            "vol": guardian_on(rets[b], kind="vol"),
            "reactive": guardian_on(rets[b], kind="reactive"),
        }
        per_book[b]["delta_vol"] = delta_calmar(per_book[b]["vol"], per_book[b]["raw"])
        per_book[b]["delta_reactive"] = delta_calmar(per_book[b]["reactive"],
                                                     per_book[b]["raw"])

    judged = sum(1 for b in books if per_book[b]["delta_vol"]["status"] == "measured")
    return {
        "panel_dir": str(pd_), "axis_days": len(axis), "axis": [axis[0], axis[-1]],
        "books": books, "live_arm": live, "frozen": sorted(frozen),
        "post_kill_era_index": era_idx, "last_kill": last_kill,
        "settings_vol": dict(IDEA1_VOL), "settings_reactive": dict(IDEA1_REACTIVE),
        "zeros": zeros, "per_book": per_book,
        "books_with_measurable_delta": judged, "books_total": len(books),
    }


# ───────────────────────────────── printing ─────────────────────────────────
def _f(x, *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def print_ase(rep: Dict[str, object]) -> None:
    print("=" * 108)
    print("#131 ASE — РАСШИРЕНИЕ ДОПУЩЕННОГО МНОЖЕСТВА (исполнение заказа #129 п.1)")
    print("=" * 108)
    print(f"панель: {rep['panel_dir']}  ось {rep['axis'][0]}…{rep['axis'][1]} "
          f"({rep['axis_days']} дней, судимых {rep['judged_days']})")
    print(f"книг {len(rep['books'])}; живой рукав ({len(rep['live_arm'])}): "
          f"{', '.join(rep['live_arm'])}")
    print(f"заморожены ({len(rep['frozen'])}): {', '.join(rep['frozen'])} "
          f"· последний kill {rep['last_kill']} (индекс {rep['post_kill_era_index']})")
    print(f"шов train/test = {rep['train_end']} (индекс {rep['seam_index']}): "
          f"TRAIN {rep['train_days']} дней · TEST {rep['test_days']} дней")

    a = rep["arithmetic"]
    print(f"\n§1 ПОРОГ k* — АРИФМЕТИКА (потолок {a['cap']:.0%}, сигмы различны ПО ПОСТРОЕНИЮ)")
    print(f"{'k':>3} {'плоский(0)':>11} {'плоский(1e-12)':>15} {'=EW побитово':>13} "
          f"{'разброс веса':>14} {'deployed':>9} {'кэш':>7}")
    for r in a["rows"]:
        print(f"{r['k']:>3} {str(r['flat_exact']):>11} {str(r['flat_eps']):>15} "
              f"{str(r['bitwise_ew']):>13} {r['spread']:>14.3e} "
              f"{r['deployed'] * 100:>8.1f}% {r['cash'] * 100:>6.1f}%")
    print(f"  k* по ПЛОСКОСТИ с допуском 1e-12 = {a['k_flat_threshold']}   ← ОТВЕТ")
    print(f"  k  по ПЛОСКОСТИ побитово (допуск 0) = {a['k_flat_threshold_exact']}   "
          "← АРТЕФАКТ: при k=5 вектор это 0.2×4 + 0.19999999999999996,")
    print("     то есть остаток float64 от последнего деления водослива (4e-17 капитала), "
          "а не решение сайзера.")
    print(f"  k  по ПОБИТОВОМУ равенству EW = {a['k_bitwise_threshold']}   "
          "← буква заказа выполняется уже при k=1:")
    print("     при k < 1/cap вектор ПЛОСКИЙ (знаменатель инертен), но не равен EW, потому что EW")
    print("     разворачивает 1/k > cap на имя, а потолок кладёт остаток в КЭШ. Отвечаю по ПЛОСКОСТИ.")

    fl = rep["falling_census_live"]
    print("\n§2 СУЩЕСТВУЕТ ЛИ ТАКОЕ МНОЖЕСТВО НА ПАНЕЛИ (живой рукав, эра после последнего kill)")
    print(f"{'книга':24} {'дней вниз':>10} {'дней движения':>14} {'статус':>14}")
    for b, d in sorted(fl["per_book"].items()):
        print(f"{b:24} {str(d['down_days']):>10} {str(d['moves']):>14} {str(d['status']):>14}")
    print(f"  имён, КОГДА-ЛИБО падавших, на живом рукаве: {fl['n_ever_falling']} "
          f"({', '.join(fl['ever_falling'])})")
    print(f"  НИ РАЗУ не падавших: {', '.join(fl['never_falling']) or '—'}")

    def _row(label: str, r: Dict[str, object], base_key: str = "three_vs_ew_live") -> str:
        cal = ("ОТКАЗАН" if r["calmar_degenerate"] else _f(r["calmar"]))
        return (f"{label:20} {r['k_mean']:>6.2f} {r['k_max']:>5} "
                f"{r['flat_share'] * 100:>7.1f}% {_f(r['apy_net'], pct=True):>9} "
                f"{_f(r['maxdd'], pct=True):>9} {cal:>8} {r['max_name_weight'] * 100:>8.1f}% "
                f"{r['days_over_policy_cap']:>5} {_f(r['mean_frozen_share'], pct=True):>8} "
                f"{str(r[base_key]['all_three']):>7}")

    print("\n§3 ЛЕСТНИЦА ДОПУСКА × ДВА САЙЗЕРА (каждая ступень меняет РОВНО ОДИН ингредиент)")
    print("   сайзер 'ew' — КОНТРОЛЬ: равный вес по ТОМУ ЖЕ дневному допущенному множеству, "
          "тот же потолок, та же пошлина.")
    print(f"{'правило/сайзер':20} {'k сред':>6} {'kmax':>5} {'плоских':>8} {'APY net':>9} "
          f"{'maxDD':>9} {'Calmar':>8} {'макс/имя':>9} {'>20%':>5} {'в мёртв':>8} {'3 усл.':>7}")
    for name, _rule, _why in ADMISSION_LADDER:
        row = rep["rungs"][name]
        print(_row(f"{name} · 1/σ", row["inv_sigma"]))
        print(_row(f"{name} · ew", row["ew"]))
        g = row["denominator_gap"]
        print(f"{'   ← доля ЗНАМЕНАТЕЛЯ':20} ΔAPY {_f(g['d_apy_net'], pct=True)} · "
              f"ΔmaxDD {_f(g['d_maxdd'], pct=True)} · ΔCalmar {_f(g['d_calmar'])}")
    for zname, z in rep["zeros"].items():
        cal = ("ОТКАЗАН" if z["calmar_degenerate"] else _f(z["calmar"]))
        print(f"{zname + ' (ноль)':20} {'—':>6} {z['n_books']:>5} {'—':>8} "
              f"{_f(z['apy_net'], pct=True):>9} {_f(z['maxdd'], pct=True):>9} {cal:>8} "
              f"{z['max_name_weight'] * 100:>8.1f}% {z['days_over_policy_cap']:>5} {'—':>8} {'—':>7}")

    print(f"\n§4 OUT-OF-SAMPLE (шов {rep['train_end']}, параметров не подбирали — правило, не fit)")
    print(f"{'правило/сайзер':20} {'TRAIN APY':>10} {'TRAIN Cal':>10} {'TEST APY':>10} "
          f"{'TEST maxDD':>11} {'TEST Cal':>9} {'TEST 3 усл.':>12}")
    for name, _rule, _why in ADMISSION_LADDER:
        for sizer in ("inv_sigma", "ew"):
            d = rep["oos"][name][sizer]
            tr, te = d["train"], d["test"]
            trc = ("ОТКАЗАН" if tr["calmar_degenerate"] else _f(tr["calmar"]))
            tec = ("ОТКАЗАН" if te["calmar_degenerate"] else _f(te["calmar"]))
            lbl = f"{name} · {'1/σ' if sizer == 'inv_sigma' else 'ew'}"
            print(f"{lbl:20} {_f(tr['apy_net'], pct=True):>10} {trc:>10} "
                  f"{_f(te['apy_net'], pct=True):>10} {_f(te['maxdd'], pct=True):>11} {tec:>9} "
                  f"{str(te['three_vs_ew_live']['all_three']):>12}")
    for zname, z in rep["zeros_test"].items():
        cal = ("ОТКАЗАН" if z["calmar_degenerate"] else _f(z["calmar"]))
        print(f"{zname + ' (ноль, TEST)':20} {'—':>10} {'—':>10} "
              f"{_f(z['apy_net'], pct=True):>10} {_f(z['maxdd'], pct=True):>11} {cal:>9} {'—':>12}")

    print("\n§5 КОНТРОЛЬ #128 п.5 — свип σ_floor (обязан ДВИГАТЬ, если множество расширилось)")
    for rule_name, rows in rep["sigma_floor_sweeps"].items():
        vals = {(r["apy_net"], r["maxdd"], r["calmar"], r["max_name_weight"]) for r in rows}
        verdict = ("знаменатель НАБЛЮДАЕМ" if len(vals) > 1
                   else "знаменатель НЕ НАБЛЮДАЕМ (инертен)")
        rng = (f"APY {_f(min(r['apy_net'] for r in rows), pct=True)}…"
               f"{_f(max(r['apy_net'] for r in rows), pct=True)}")
        print(f"  {rule_name:11} различных ответов {len(vals)}/{len(rows)} · {rng} ⇒ {verdict}")

    print("\n§6 СЧЁТНЫЙ КОНТРФАКТ ПО ПОТОЛКУ (правило ever_down) — ИЗМЕРЕНИЕ, НЕ РЕШЕНИЕ")
    print("    потолок 20 %/имя живёт в RiskPolicy v1.0 и двигается ADR'ом, не скриптом.")
    print(f"{'cap':>6} {'плоских':>9} {'макс/имя':>9} {'APY net':>9} {'maxDD':>9} {'Calmar':>9} "
          f"{'дней >20%':>10} {'deployed':>9}")
    for r in rep["cap_counterfactual"]:
        cal = ("ОТКАЗАН" if r["calmar_degenerate"] else _f(r["calmar"]))
        print(f"{r['cap']:>6.0%} {r['flat_share'] * 100:>8.1f}% {r['max_name_weight'] * 100:>8.1f}% "
              f"{_f(r['apy_net'], pct=True):>9} {_f(r['maxdd'], pct=True):>9} {cal:>9} "
              f"{r['days_over_policy_cap']:>10} {r['mean_deployed'] * 100:>8.1f}%")

    print("\n§7 ОТВЕТ НА ЗАКАЗ")
    print(f"  k* = {rep['k_star']} (измерено §1, допуск 1e-12)")
    print("  множество размера k* на живом рукаве при ДОВОДНОМ правиле СУЩЕСТВУЕТ: "
          f"{rep['admitted_set_exists']}")
    if rep["refusal"]:
        print("  ОТКАЗ С НАЗВАННОЙ ПРИЧИНОЙ:")
        for chunk in rep["refusal"].split(". "):
            print(f"    {chunk.strip()}.")
    best = rep["rungs"]["sigma_pos"]["inv_sigma"]
    print("  средний вес по именам у правила sigma_pos · 1/σ:")
    for b, w in sorted(best["mean_weight"].items(), key=lambda kv: -kv[1]):
        if w > 1e-6:
            print(f"    {b:22} {w * 100:>6.2f} %")


def print_gz(rep: Dict[str, object]) -> None:
    print("=" * 100)
    print("#132 GZ — ФЛАГМАН #1 ЕГО СОБСТВЕННЫМ ПРИБОРОМ НА РЕАЛЬНОЙ ПАНЕЛИ "
          "(исполнение заказа #129 п.2 = #126 п.1)")
    print("=" * 100)
    print("прибор: scripts/guardian_backtest.py (apply_guardian_vol / apply_guardian / _metrics)")
    print(f"настройки #1 (UPD5, OOS): {rep['settings_vol']} · реактивный: {rep['settings_reactive']}")
    print(f"панель {rep['panel_dir']} · ось {rep['axis'][0]}…{rep['axis'][1]} "
          f"({rep['axis_days']} дней)")

    print("\n§1 ПРОТИВ ОБОИХ НУЛЕЙ — ровно то, что требует заказ")
    for zname, z in rep["zeros"].items():
        print(f"\n  {zname} ({z['n_books']} книг: {', '.join(z['universe'])})")
        print(f"    {'вариант':11} {'APY% (#1)':>11} {'maxDD% (#1)':>12} {'Calmar (#1)':>12} "
              f"{'maxDD чест.':>12} {'Calmar чест.':>13} {'перекл.':>8} {'APY по пошлине':>15}")
        for kind in ("raw", "vol", "reactive"):
            m = z[kind]
            honest = ("ОТКАЗАН" if m["calmar_degenerate"] else _f(m["calmar"], nd=3))
            print(f"    {kind:11} {_f(m['idea1_apy_pct'], nd=2):>11} "
                  f"{_f(m['idea1_maxdd_pct'], nd=3):>12} {_f(m['idea1_calmar'], nd=3):>12} "
                  f"{_f(m['maxdd_frac'], pct=True, nd=3):>12} {honest:>13} "
                  f"{m['switches']:>8} {_f(m['apy_frac_after_switch_toll'], pct=True):>15}")
        for key, label in (("delta_vol", "ΔCalmar (упреждающий − raw)"),
                           ("delta_reactive", "ΔCalmar (реактивный − raw)")):
            d = z[key]
            if d["status"] == "measured":
                print(f"    {label}: {d['delta_calmar']:+.3f} "
                      f"({d['guarded_calmar']:.3f} против {d['base_calmar']:.3f})")
            else:
                print(f"    {label}: ОТКАЗАН — {d['reason']}")

    print("\n§2 ПО КНИГАМ — форма таблицы #1, но данные РЕАЛЬНОЙ панели")
    print(f"{'книга':20} {'raw APY%':>9} {'raw DD%':>8} {'raw Cal':>8} "
          f"{'упр APY%':>9} {'упр DD%':>8} {'упр Cal':>8} {'ΔCalmar':>10} {'вердикт':>10}")
    for b, d in rep["per_book"].items():
        r, v = d["raw"], d["vol"]
        dv = d["delta_vol"]
        delta = (f"{dv['delta_calmar']:+.3f}" if dv["status"] == "measured" else "ОТКАЗАН")
        verdict = ("измерен" if dv["status"] == "measured" else "вырожден")
        print(f"{b:20} {_f(r['idea1_apy_pct']):>9} {_f(r['idea1_maxdd_pct'], nd=3):>8} "
              f"{_f(r['idea1_calmar'], nd=2):>8} {_f(v['idea1_apy_pct']):>9} "
              f"{_f(v['idea1_maxdd_pct'], nd=3):>8} {_f(v['idea1_calmar'], nd=2):>8} "
              f"{delta:>10} {verdict:>10}")
    print(f"\n  книг с ИЗМЕРИМОЙ ΔCalmar: {rep['books_with_measurable_delta']} "
          f"из {rep['books_total']} — у остальных знаменатель ниже пошлины входа, и ΔCalmar "
          "ОТКАЗАН, а не напечатан нулём")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="registry #131 ASE + #132 GZ (advisory, read-only)")
    ap.add_argument("--panel", default=None,
                    help="panel dir (default: the repo's own data/aggressive_lab; from a "
                         "worktree pass the prod tree's dir — the panel is untracked)")
    ap.add_argument("--section", choices=("ase", "gz", "both"), default="both")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    panel = Path(a.panel) if a.panel else None
    out: Dict[str, object] = {}
    if a.section in ("ase", "both"):
        rep = ase_report(panel)
        out["ase"] = rep
        if not a.json:
            print_ase(rep)
    if a.section in ("gz", "both"):
        rep = guardian_zero_report(panel)
        out["gz"] = rep
        if not a.json:
            print()
            print_gz(rep)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
