#!/usr/bin/env python3
"""
scripts/edge_sigma_floor_ctac_real.py — registry ideas #128 (SFS) and #129 (CTAC-REAL)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

Both sections execute ORDERS left verbatim by earlier registry entries; neither invents its
own question.

    #126 order 2, repeated word-for-word as #127 order 2
        "A sizer that does not confuse `quiet` with `not measured`: replace the denominator
         1/sigma with 1/max(sigma, sigma_floor) and REFUSE to fund a book whose down_days = 0
         over the estimation window. Acceptance: the weight of such a book is zero BY
         CONSTRUCTION, the 20 %/name ceiling is not violated on ANY day of the axis, and
         Calmar is either measured or REFUSED with a named cause."
        -> section 1, `sfs_report()`

    #127 order 1
        "Check CTAC on the REAL panel (data/aggressive_lab, phase=backtest), where the
         correlation `tail <-> carry` may break. Acceptance: CTAC-1 Calmar > EW Calmar, AND a
         bootstrap over 200 permutations of the crisis tails gives p < 0.05."
        -> section 2, `ctac_real_report()`

Everything measured here is advisory. No capital moves, the go-live track
(data/equity_curve_daily.json) is never opened, RiskPolicy v1.0 is untouched.

The panel loader, the metrics and the inverse-risk sizer are IMPORTED from
scripts/edge_real_panel_ensemble.py rather than reimplemented: those are the instruments
#122-#126 were measured with, and a second copy of them would make these numbers
incomparable with theirs by construction.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "edge_real_panel_ensemble.py"

#: canonical round-trip toll (#10/#49), charged on TRADED notional, not on the whole book.
ROUNDTRIP = 0.0096
#: per-name policy ceiling used across the project.
POLICY_CAP = 0.20
#: a return below this counts as a day down; above it, a day up. Symmetric by construction.
EPS = 1e-12
#: bootstrap size and seed named by #127 order 1. The seed is fixed so the p-value is a fact
#: about this panel and not about today's entropy.
BOOTSTRAP_N = 200
BOOTSTRAP_SEED = 20261009


_HARNESS_CACHE: Dict[str, object] = {}


def load_harness(path: Path = HARNESS):
    """Import scripts/edge_real_panel_ensemble.py — the panel loader everything here reuses.

    Cached per path: `drawdown_verdict` asks for it once per series, the bootstrap asks for it
    200 times, and re-executing a 950-line module that many times turns a 20-second measurement
    into a 10-minute one. The cache is keyed by path so a test can still point at a copy.
    """
    key = str(path)
    if key not in _HARNESS_CACHE:
        spec = importlib.util.spec_from_file_location("edge_real_panel_ensemble", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import the panel harness at {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _HARNESS_CACHE[key] = mod
    return _HARNESS_CACHE[key]


# ───────────────────────────── honest drawdown ─────────────────────────────
def drawdown_verdict(returns: Sequence[float], *, eps: float = EPS) -> Dict[str, object]:
    """maxDD with its STATUS — `measured`, or `unmeasured_monotone` with maxdd/calmar = None.

    Same semantics and same wording as edge_forward_phase_transfer.drawdown_verdict (#125/#126);
    duplicated here only so this script has no import cycle with that one. A series with no day
    below zero cannot draw down, so its 0.0 is arithmetic rather than observation, and handing it
    back as a float is exactly how an accrual ledger acquires an infinite Calmar (inv. #17).
    """
    if not returns:
        return {"maxdd": None, "calmar": None, "status": "unmeasured_empty", "down_days": None,
                "apy": None, "vol": None,
                "reason": "no returns at all — nothing was observed"}
    H = load_harness()
    down = sum(1 for r in returns if r < -eps)
    p = H.perf(returns)
    mdd = abs(p["maxdd"])
    if down == 0:
        return {"maxdd": None, "calmar": None, "status": "unmeasured_monotone", "down_days": 0,
                "apy": p["apy"], "vol": p["vol"],
                "reason": (f"{len(returns)} returns, not one below zero: a non-decreasing equity "
                           f"curve cannot draw down, so 0.0 here is arithmetic, not an "
                           f"observation")}
    if mdd <= 0.0:
        return {"maxdd": None, "calmar": None, "status": "unmeasured_inconsistent",
                "down_days": down, "apy": p["apy"], "vol": p["vol"],
                "reason": (f"{down} day(s) below zero yet maxDD computed as {mdd!r} — refusing "
                           f"to publish a drawdown this arithmetic cannot support")}
    return {"maxdd": mdd, "calmar": p["apy"] / mdd, "status": "measured", "down_days": down,
            "apy": p["apy"], "vol": p["vol"], "reason": None}


# ───────────────────── §1 · #128 SFS: the sigma-floor sizer ─────────────────────
def window_stats(rets: Dict[str, Sequence[float]], book: str, *, end: int,
                 lookback: int) -> Dict[str, float]:
    """Trailing sigma and down-day count for `book` over a window STRICTLY BEFORE `end`.

    Causal by construction: the window is [end-lookback, end), so day `end` — the day whose
    weight is being decided — is never inside the evidence that decides it.
    """
    lo = max(0, end - lookback)
    win = [rets[book][i] for i in range(lo, end)]
    if len(win) < 5:
        raise ValueError(f"window of {len(win)} days — refusing to call that a risk estimate")
    return {
        "sigma": statistics.pstdev(win) if len(win) > 1 else 0.0,
        "down_days": float(sum(1 for x in win if x < -EPS)),
        "n": float(len(win)),
    }


def cap_waterfill(shares: Dict[str, float], *, cap: float = POLICY_CAP) -> Dict[str, object]:
    """Impose a per-name ceiling on `shares` (which sum to 1), redistributing the excess.

    Three outcomes, and the third one is the point of this function:

      * no name over the cap               -> shares returned untouched, `cap_binds` = 0
      * some names over the cap            -> those are pinned at `cap`, the rest renormalised
                                              over the remainder, repeated to a fixed point
      * fewer than ceil(1/cap) names       -> the cap CANNOT be satisfied at full deployment.
                                              Every name goes to `cap`, the residual is CASH,
                                              and `degenerate` says so. In that state the sizer's
                                              denominator is INERT: every eligible name gets the
                                              same weight whatever 1/sigma says about it.

    The third branch is fail-CLOSED on purpose. The alternative — scaling weights up to fill the
    book — would breach the ceiling silently, which is the exact defect #126 measured (86.11 %
    in one name, 4.3x the ceiling).
    """
    if cap <= 0.0:
        raise ValueError("a non-positive per-name cap would fund nothing — refusing")
    names = [b for b, w in shares.items() if w > 0.0]
    if not names:
        return {"weights": dict(shares), "deployed": 0.0, "cash": 1.0, "cap_binds": 0,
                "degenerate": "no eligible name carries weight"}
    if len(names) * cap < 1.0 - 1e-12:
        w = {b: (cap if b in names else 0.0) for b in shares}
        deployed = cap * len(names)
        return {"weights": w, "deployed": deployed, "cash": 1.0 - deployed,
                "cap_binds": len(names),
                "degenerate": (f"{len(names)} eligible name(s) x cap {cap:.0%} = {deployed:.0%} "
                               f"< 100 %: the ceiling binds on every name, so the 1/sigma "
                               f"denominator cannot express anything — the rest is cash")}
    w = {b: float(shares.get(b, 0.0)) for b in shares}
    pinned: Dict[str, float] = {}
    for _ in range(len(names) + 1):
        over = [b for b in names if b not in pinned and w[b] > cap + 1e-15]
        if not over:
            break
        for b in over:
            pinned[b] = cap
        free = [b for b in names if b not in pinned]
        room = 1.0 - cap * len(pinned)
        tot = sum(w[b] for b in free)
        for b in names:
            if b in pinned:
                w[b] = cap
            elif tot > 0:
                w[b] = w[b] / tot * room
            else:
                w[b] = room / len(free) if free else 0.0
    return {"weights": w, "deployed": sum(w.values()), "cash": max(0.0, 1.0 - sum(w.values())),
            "cap_binds": len(pinned), "degenerate": None}


def sfs_weights(rets: Dict[str, Sequence[float]], books: Sequence[str], *, end: int,
                lookback: int = 30, sigma_floor: float = 1e-5,
                refuse_no_down_days: bool = True,
                cap: Optional[float] = POLICY_CAP) -> Dict[str, object]:
    """One day of the sigma-floor sizer. Returns weights over ALL `books` plus a diagnosis.

    `refuse_no_down_days=False` and `cap=None` and `sigma_floor=1e-5` together reproduce the
    sizer of registry line #17 exactly, which is how the three ingredients are told apart: each
    variant in `sfs_report` switches ONE of them.
    """
    stats = {b: window_stats(rets, b, end=end, lookback=lookback) for b in books}
    refused: List[str] = []
    eligible: List[str] = []
    for b in books:
        if refuse_no_down_days and stats[b]["down_days"] < 1.0:
            refused.append(b)
        else:
            eligible.append(b)
    if not eligible:
        return {"weights": {b: 0.0 for b in books}, "eligible": [], "refused": refused,
                "deployed": 0.0, "cash": 1.0, "cap_binds": 0,
                "degenerate": "no book showed a single down day in the window — all cash",
                "stats": stats}
    raw = {b: 1.0 / max(stats[b]["sigma"], sigma_floor) for b in eligible}
    tot = sum(raw.values())
    shares = {b: (raw[b] / tot if b in raw else 0.0) for b in books}
    if cap is None:
        return {"weights": shares, "eligible": eligible, "refused": refused,
                "deployed": 1.0, "cash": 0.0, "cap_binds": 0, "degenerate": None,
                "stats": stats}
    out = cap_waterfill(shares, cap=cap)
    out.update({"eligible": eligible, "refused": refused, "stats": stats})
    return out


def run_sizer(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
              lookback: int = 30, sigma_floor: float = 1e-5,
              refuse_no_down_days: bool = True, cap: Optional[float] = POLICY_CAP,
              frozen: Sequence[str] = (), roundtrip: float = ROUNDTRIP) -> Dict[str, object]:
    """Walk the sizer day by day over [lo, hi) and report its series AND its behaviour.

    The toll is charged on TRADED notional — ROUNDTRIP * sum|dw| / 2 — because a daily
    rebalancer pays for churn, not once on day one. Two series come back: `series` (net of the
    toll, the honest return) and `clean` (gross), and the drawdown question is asked of `clean`.
    That split is not a convenience: on a near-monotone panel the toll itself manufactures the
    only days below zero, and a drawdown measured on the tolled series is this script's own fee
    read back as though the market had taken it (the convention #125/#126 already used).
    """
    if lo < lookback:
        raise ValueError(f"start index {lo} is inside the first {lookback}-day window — the "
                         f"first weight would be decided on a window that does not exist")
    if hi <= lo:
        raise ValueError("empty slice — refusing to report a portfolio of nothing")
    frozen_set = set(frozen)
    prev: Dict[str, float] = {b: 0.0 for b in books}
    clean: List[float] = []
    series: List[float] = []
    max_name_weight = 0.0
    max_name_day: Optional[int] = None
    max_name: Optional[str] = None
    # None, not 0, when no ceiling was imposed. "Nobody breached a ceiling that was never
    # applied" and "the ceiling was applied and held" are different facts, and printing both as
    # 0 is exactly the substitution inv. #17 forbids: the first variant here reaches 33.1 % on a
    # single name and a column of zeroes would read as though the policy had been honoured.
    cap_violation_days: Optional[int] = None if cap is None else 0
    frozen_share: List[float] = []
    refused_weight_mass = 0.0
    deployed: List[float] = []
    turnover_total = 0.0
    degenerate_days = 0
    days_over_policy_cap = 0
    refused_counts: Dict[str, int] = {b: 0 for b in books}
    for t in range(lo, hi):
        d = sfs_weights(rets, books, end=t, lookback=lookback, sigma_floor=sigma_floor,
                        refuse_no_down_days=refuse_no_down_days, cap=cap)
        w = d["weights"]
        if d.get("degenerate"):
            degenerate_days += 1
        for b in d["refused"]:
            refused_counts[b] += 1
            refused_weight_mass += w.get(b, 0.0)
        for b in books:
            if w[b] > max_name_weight:
                max_name_weight, max_name_day, max_name = w[b], t, b
        if cap is not None and any(w[b] > cap + 1e-12 for b in books):  # noqa: SIM102
            # counted per DAY, not per name: one day on which the ceiling is breached is one
            # breach of the acceptance criterion however many names did it. An earlier version
            # `break`-ed out of the loop above on the first breach and so stopped looking for the
            # heaviest name on exactly the days where it mattered most.
            cap_violation_days = (cap_violation_days or 0) + 1
        if any(w[b] > POLICY_CAP + 1e-12 for b in books):
            # Asked of EVERY variant, capped or not: "on how many days would the 20 %/name policy
            # have been breached by these weights". For the uncapped variants that is the whole
            # finding (#126's leak), and it is a MEASUREMENT, unlike `cap_violation_days`, which
            # is only defined when a ceiling was actually imposed.
            days_over_policy_cap += 1
        frozen_share.append(sum(w[b] for b in books if b in frozen_set))
        deployed.append(float(d["deployed"]))
        turn = sum(abs(w[b] - prev[b]) for b in books) / 2.0
        turnover_total += turn
        gross = sum(w[b] * rets[b][t] for b in books)
        clean.append(gross)
        series.append(gross - roundtrip * turn)
        prev = w
    v = dict(drawdown_verdict(clean))
    tolled = drawdown_verdict(series)
    H = load_harness()
    return {
        "n_days": hi - lo,
        "apy_gross": v.get("apy"),
        "apy_net": H.perf(series)["apy"],
        "maxdd": v.get("maxdd"),
        "calmar": v.get("calmar"),
        "dd_status": v.get("status"),
        "dd_reason": v.get("reason"),
        "calmar_degenerate": calmar_degenerate(v.get("maxdd")),
        "down_days": v.get("down_days"),
        "maxdd_incl_toll": tolled.get("maxdd"),
        "dd_status_incl_toll": tolled.get("status"),
        "max_name_weight": max_name_weight,
        "max_name": max_name,
        "max_name_day": max_name_day,
        "cap_violation_days": cap_violation_days,
        "days_over_policy_cap": days_over_policy_cap,
        "mean_frozen_share": (sum(frozen_share) / len(frozen_share)) if frozen_share else None,
        "max_frozen_share": max(frozen_share) if frozen_share else None,
        "refused_weight_mass": refused_weight_mass,
        "mean_deployed": sum(deployed) / len(deployed),
        "min_deployed": min(deployed),
        "turnover_per_day": turnover_total / (hi - lo),
        "degenerate_days": degenerate_days,
        "always_refused": sorted(b for b in books if refused_counts[b] == hi - lo),
        "never_refused": sorted(b for b in books if refused_counts[b] == 0),
        "series": series,
        "clean": clean,
    }


def ew_static(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
              roundtrip: float = ROUNDTRIP) -> Dict[str, object]:
    """Equal weight over a STATIC subset, toll charged once on day one — the registry's zero."""
    if not books:
        raise ValueError("empty book list — refusing to report a portfolio of nothing")
    k = list(books)
    clean = [sum(rets[b][i] for b in k) / len(k) for i in range(lo, hi)]
    series = list(clean)
    series[0] -= roundtrip
    H = load_harness()
    v = dict(drawdown_verdict(clean))
    return {"n_days": hi - lo, "apy_gross": v.get("apy"), "apy_net": H.perf(series)["apy"],
            "maxdd": v.get("maxdd"), "calmar": v.get("calmar"), "dd_status": v.get("status"),
            "dd_reason": v.get("reason"), "down_days": v.get("down_days"),
            "max_name_weight": 1.0 / len(k), "cap_violation_days": None,
            "days_over_policy_cap": 0 if 1.0 / len(k) <= POLICY_CAP else hi - lo,
            "calmar_degenerate": calmar_degenerate(v.get("maxdd")),
            "n_books": len(k), "books": k, "series": series, "clean": clean}


def sfs_report(panel_dir: Optional[Path] = None, *, lookback: int = 30,
               sweep: Sequence[float] = (1e-5, 5e-4, 1e-3, 2e-3, 5e-3)) -> Dict[str, object]:
    """#128: the four sizer variants on the real panel, plus the two registry zeros.

    Variants switch ONE ingredient each, so the report can say which ingredient did the work:
      inv_sigma_asis  — 1/max(sigma, 1e-5), all books, no refusal, no cap   (line #17 as measured)
      floor_only      — the floor raised, no refusal, no cap
      refusal_only    — the floor raised AND down_days>=1 refusal, no cap
      sfs_full        — floor + refusal + 20 %/name cap + cash residual     (the order's proposal)
    """
    H = load_harness()
    pdir = panel_dir if panel_dir is not None else H.PANEL_DIR
    axis, rets, books = H.plb_load(pdir)
    census = H.book_census(pdir)
    era_lo, last_kill = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=era_lo)
    lo, hi = lookback, len(axis)
    headline_floor = sweep[2] if len(sweep) > 2 else sweep[-1]

    variants: Dict[str, Dict[str, object]] = {
        "inv_sigma_asis": run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback,
                                    sigma_floor=1e-5, refuse_no_down_days=False, cap=None,
                                    frozen=frozen),
        "floor_only": run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback,
                                sigma_floor=headline_floor, refuse_no_down_days=False, cap=None,
                                frozen=frozen),
        "refusal_only": run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback,
                                  sigma_floor=headline_floor, refuse_no_down_days=True, cap=None,
                                  frozen=frozen),
        "sfs_full": run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback,
                              sigma_floor=headline_floor, refuse_no_down_days=True,
                              cap=POLICY_CAP, frozen=frozen),
    }
    zeros = {
        "ew10": ew_static(rets, books, lo=lo, hi=hi),
        "ew_live": ew_static(rets, live, lo=lo, hi=hi),
    }
    # The sweep is the control on the degeneracy claim: raising the floor must move the UNCAPPED
    # variant's answer and must NOT move the capped one, because there the cap binds on every
    # name and the denominator is inert. If both move, the degeneracy claim is wrong.
    floor_sweep: Dict[str, Dict[str, object]] = {}
    for f in sweep:
        unc = run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback, sigma_floor=f,
                        refuse_no_down_days=True, cap=None, frozen=frozen)
        cap = run_sizer(rets, books, lo=lo, hi=hi, lookback=lookback, sigma_floor=f,
                        refuse_no_down_days=True, cap=POLICY_CAP, frozen=frozen)
        floor_sweep[f"{f:g}"] = {
            "uncapped_apy_net": unc["apy_net"], "uncapped_maxdd": unc["maxdd"],
            "uncapped_calmar": unc["calmar"], "uncapped_max_name": unc["max_name_weight"],
            "capped_apy_net": cap["apy_net"], "capped_maxdd": cap["maxdd"],
            "capped_calmar": cap["calmar"], "capped_max_name": cap["max_name_weight"],
        }
    acceptance = {
        "zero_weight_for_no_down_day_books": variants["sfs_full"]["refused_weight_mass"] == 0.0,
        "cap_never_violated": (variants["sfs_full"]["cap_violation_days"] == 0
                               and variants["sfs_full"]["days_over_policy_cap"] == 0),
        "calmar_measured_or_refused": variants["sfs_full"]["dd_status"] in {
            "measured", "unmeasured_monotone", "unmeasured_inconsistent", "unmeasured_empty"},
    }
    return {
        "axis": {"n": len(axis), "first": axis[0], "last": axis[-1], "judged_days": hi - lo},
        "books": books, "live": live, "frozen": frozen,
        "era": {"last_kill": last_kill, "post_kill_index": era_lo},
        "lookback": lookback, "headline_sigma_floor": headline_floor,
        "variants": {k: {kk: vv for kk, vv in v.items() if kk not in {"series", "clean"}}
                     for k, v in variants.items()},
        "zeros": {k: {kk: vv for kk, vv in v.items() if kk not in {"series", "clean"}}
                  for k, v in zeros.items()},
        "floor_sweep": floor_sweep,
        "acceptance": acceptance,
    }


# ─────────────────── §2 · #129 CTAC on the real panel ───────────────────
def crisis_loss(rets: Dict[str, Sequence[float]], axis: Sequence[str], book: str,
                date_from: str, date_to: str) -> Dict[str, object]:
    """Peak-to-trough fractional loss of `book` INSIDE the named window, as a positive number.

    Returns the loss with its status. A book that never fell inside the window gets
    loss = 0.0 with status `no_down_day`: that zero is an OBSERVATION (the window was covered and
    nothing was lost), unlike the `unmeasured` status returned when the window misses the axis
    entirely. Keeping those two apart is inv. #17 — the whole point of #126.
    """
    idx = [i for i, d in enumerate(axis) if date_from <= d <= date_to]
    if not idx:
        return {"loss": None, "status": "unmeasured_window_off_axis", "n_days": 0,
                "reason": f"window {date_from}..{date_to} does not intersect the axis"}
    eq, peak, worst = 1.0, 1.0, 0.0
    for i in idx:
        eq *= 1.0 + rets[book][i]
        peak = max(peak, eq)
        worst = min(worst, eq / peak - 1.0)
    down = sum(1 for i in idx if rets[book][i] < -EPS)
    return {"loss": abs(worst), "status": "measured" if down else "no_down_day",
            "n_days": len(idx), "down_days": down, "reason": None}


def ctac_weights(losses: Dict[str, float], *, kind: str = "ctac",
                 eps: float = 1e-4) -> Dict[str, float]:
    """Weights from observed crisis losses. `kind='ctac'` inverts them, `'anti'` follows them.

    `eps` is the only free number and it decides the weight of a book that lost nothing: with
    eps = 1e-4 a zero-loss book gets the largest raw score there is. That is CTAC's own premise
    ("what did not fall, fund"), and on this panel it is also exactly the premise #126 showed to
    be unsafe — so the number stays an argument, visible, rather than a constant.
    """
    if not losses:
        raise ValueError("no observed losses — refusing to size a portfolio on nothing")
    if kind == "ctac":
        raw = {b: 1.0 / (l + eps) for b, l in losses.items()}
    elif kind == "anti":
        raw = {b: l + eps for b, l in losses.items()}
    elif kind == "equal":
        raw = {b: 1.0 for b in losses}
    else:
        raise ValueError(f"unknown kind {kind!r}")
    tot = sum(raw.values())
    return {b: raw[b] / tot for b in raw}


def calmar_degenerate(maxdd: Optional[float], *, floor: float = ROUNDTRIP) -> Optional[str]:
    """Name the condition under which a Calmar must not be RANKED, rather than discover it later.

    Calmar is a ratio, so it grows without bound as its denominator approaches zero. #122 already
    measured that on this panel (5 of 1023 subsets draw down exactly 0), and #126 refused to print
    a four-digit Calmar for line #17 for the same reason. The threshold used here is not invented:
    it is the canonical round-trip toll. A portfolio whose deepest observed drawdown is SMALLER
    THAN THE FEE CHARGED TO ENTER IT has not been tested by the market at all, and ordering it
    against a portfolio that fell twenty times further compares a measurement with a rounding
    artefact. The number is returned as a REASON string, not as a bool, so a caller cannot print
    the verdict without printing why.
    """
    if maxdd is None:
        return "maxDD not measured at all — no ratio can be formed"
    if maxdd < floor:
        return (f"maxDD {maxdd * 100:.4f} % is below the round-trip toll {floor * 100:.2f} % — the "
                f"denominator is smaller than the entry fee, so the ratio is an artefact of "
                f"division, not a risk-adjusted return")
    return None


def static_weighted(rets: Dict[str, Sequence[float]], weights: Dict[str, float], *, lo: int,
                    hi: int, roundtrip: float = ROUNDTRIP) -> Dict[str, object]:
    """A STATIC weighted sleeve over [lo, hi): toll once on day one, drawdown judged gross."""
    if hi <= lo:
        raise ValueError("empty slice — refusing to report a portfolio of nothing")
    clean = [sum(weights[b] * rets[b][i] for b in weights) for i in range(lo, hi)]
    series = list(clean)
    series[0] -= roundtrip
    H = load_harness()
    v = dict(drawdown_verdict(clean))
    return {"n_days": hi - lo, "apy_gross": v.get("apy"), "apy_net": H.perf(series)["apy"],
            "maxdd": v.get("maxdd"), "calmar": v.get("calmar"), "dd_status": v.get("status"),
            "dd_reason": v.get("reason"), "down_days": v.get("down_days"),
            "max_name_weight": max(weights.values()),
            "max_name": max(weights, key=lambda b: weights[b]),
            "cap_violation": max(weights.values()) > POLICY_CAP + 1e-12,
            "calmar_degenerate": calmar_degenerate(v.get("maxdd")),
            "weights": dict(weights)}


def ctac_bootstrap(rets: Dict[str, Sequence[float]], books: Sequence[str],
                   losses: Dict[str, float], *, lo: int, hi: int, n: int = BOOTSTRAP_N,
                   seed: int = BOOTSTRAP_SEED, eps: float = 1e-4,
                   ew_calmar: Optional[float] = None) -> Dict[str, object]:
    """Permutation test asked by #127 order 1: is CTAC's Calmar a fact about the book-to-tail
    association, or about the SHAPE of the loss vector?

    Each draw PERMUTES the observed loss vector across books. The multiset of losses — and
    therefore the dispersion of the weights CTAC produces — is preserved exactly; only the link
    between a book and its own crisis tail is destroyed. So the null being tested is "any
    re-labelling of these tails would have done as well", which is the null that matters.

    A permutation whose drawdown is NOT MEASURABLE cannot be compared to a Calmar; it is counted
    in `refused` and excluded from the denominator, and the p-value is reported together with
    that count rather than silently averaged over it (inv. #17).
    """
    # Every branch below returns the SAME keys, the unmeasured ones as None. A third outcome that
    # changes the SHAPE of the answer forces each caller to re-derive "was this measured?" from
    # which keys happen to be present, and the first caller that forgets reads a missing key as a
    # zero — the substitution inv. #17 exists to prevent.
    blank = {"p_value": None, "status": None, "comparable": 0, "refused": 0, "ge": None,
             "actual_calmar": None, "actual_degenerate": None, "draw_median": None,
             "draw_max": None, "draw_min": None, "degenerate_draws": None,
             "draws_beating_ew": None, "reason": None}
    actual = static_weighted(rets, ctac_weights(losses, eps=eps), lo=lo, hi=hi)
    if actual["calmar"] is None:
        return {**blank, "status": "unmeasured_actual",
                "reason": (f"the actual CTAC series has no measurable drawdown "
                           f"({actual['dd_status']}), so no Calmar can be ranked against "
                           f"the null")}
    rng = random.Random(seed)
    names = sorted(losses)
    vals = [losses[b] for b in names]
    ge = 0
    comparable = 0
    refused = 0
    degenerate_draws = 0
    beat_ew = 0
    draws: List[float] = []
    for _ in range(n):
        shuffled = list(vals)
        rng.shuffle(shuffled)
        perm = {names[i]: shuffled[i] for i in range(len(names))}
        r = static_weighted(rets, ctac_weights(perm, eps=eps), lo=lo, hi=hi)
        if r["calmar"] is None:
            refused += 1
            continue
        comparable += 1
        draws.append(r["calmar"])
        if r["calmar"] >= actual["calmar"]:
            ge += 1
        if r["calmar_degenerate"]:
            degenerate_draws += 1
        if ew_calmar is not None and r["calmar"] > ew_calmar:
            beat_ew += 1
    if comparable == 0:
        return {**blank, "status": "unmeasured_no_comparable_draw", "refused": refused,
                "actual_calmar": actual["calmar"],
                "actual_degenerate": actual["calmar_degenerate"],
                "reason": "every permutation produced an unmeasurable drawdown"}
    return {**blank, "p_value": (ge + 1) / (comparable + 1), "status": "measured",
            "comparable": comparable, "refused": refused, "ge": ge,
            "actual_calmar": actual["calmar"],
            "actual_degenerate": actual["calmar_degenerate"],
            "draw_median": statistics.median(draws),
            "draw_max": max(draws), "draw_min": min(draws),
            "degenerate_draws": degenerate_draws,
            "draws_beating_ew": (None if ew_calmar is None else beat_ew),
            "reason": None}


def ctac_real_report(panel_dir: Optional[Path] = None, *,
                     universe: str = "all") -> Dict[str, object]:
    """#129: CTAC-1 against EW on the real panel, with the permutation test of #127 order 1."""
    H = load_harness()
    pdir = panel_dir if panel_dir is not None else H.PANEL_DIR
    axis, rets, books = H.plb_load(pdir)
    census = H.book_census(pdir)
    era_lo, _ = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=era_lo)
    pool = list(books) if universe == "all" else list(live)

    windows = list(H.CRISIS_WINDOWS)
    c1_key, c1_from, c1_to = windows[0]
    losses_by_crisis: Dict[str, Dict[str, object]] = {}
    for key, d_from, d_to in windows:
        losses_by_crisis[key] = {b: crisis_loss(rets, axis, b, d_from, d_to) for b in pool}

    c1 = losses_by_crisis[c1_key]
    off_axis = [b for b in pool if c1[b]["loss"] is None]
    if off_axis:
        return {"status": "unmeasured", "universe": universe, "pool": pool,
                "reason": (f"crisis window {c1_key} does not intersect the axis for "
                           f"{off_axis} — nothing can be sized on it")}
    c1_losses = {b: float(c1[b]["loss"]) for b in pool}
    cumulative = {b: sum(float(losses_by_crisis[k][b]["loss"] or 0.0) for k, _, _ in windows)
                  for b in pool}

    after_c1 = next((i for i, d in enumerate(axis) if d > c1_to), None)
    if after_c1 is None or len(axis) - after_c1 < 60:
        return {"status": "unmeasured", "universe": universe, "pool": pool,
                "reason": f"only {0 if after_c1 is None else len(axis) - after_c1} days follow "
                          f"crisis 1 — refusing to judge a sizer on them"}
    lo, hi = after_c1, len(axis)

    portfolios = {
        "equal_weight": static_weighted(rets, ctac_weights(c1_losses, kind="equal"),
                                        lo=lo, hi=hi),
        "ctac_1": static_weighted(rets, ctac_weights(c1_losses), lo=lo, hi=hi),
        "anti_ctac": static_weighted(rets, ctac_weights(c1_losses, kind="anti"), lo=lo, hi=hi),
        "hindsight": static_weighted(rets, ctac_weights(cumulative), lo=lo, hi=hi),
    }
    ctac_c, ew_c = portfolios["ctac_1"]["calmar"], portfolios["equal_weight"]["calmar"]
    boot = ctac_bootstrap(rets, pool, c1_losses, lo=lo, hi=hi, ew_calmar=ew_c)
    acceptance = {
        "calmar_beats_ew": (None if (ctac_c is None or ew_c is None) else ctac_c > ew_c),
        "calmar_comparable": not (ctac_c is None or ew_c is None),
        "p_below_0_05": (None if boot["p_value"] is None else boot["p_value"] < 0.05),
        "p_value": boot["p_value"],
    }
    acceptance["literal_pass"] = (bool(acceptance["calmar_beats_ew"])
                                 and bool(acceptance["p_below_0_05"]))
    # The order's criterion is literal and this panel satisfies it; these three say whether the
    # satisfaction MEANS anything. A criterion met by a degenerate denominator, by a sleeve that
    # breaches the per-name ceiling, or by a null that also beats the baseline, is met by the
    # defect the registry already knows about rather than by the hypothesis under test.
    acceptance["calmar_degenerate"] = portfolios["ctac_1"]["calmar_degenerate"]
    acceptance["cap_violated"] = portfolios["ctac_1"]["cap_violation"]
    acceptance["apy_beats_ew"] = (portfolios["ctac_1"]["apy_net"]
                                  > portfolios["equal_weight"]["apy_net"])
    acceptance["null_median_beats_ew"] = (
        None if (boot.get("draw_median") is None or ew_c is None)
        else boot["draw_median"] > ew_c)
    acceptance["null_share_beating_ew"] = (
        None if boot.get("draws_beating_ew") is None or not boot.get("comparable")
        else boot["draws_beating_ew"] / boot["comparable"])
    acceptance["passed"] = bool(
        acceptance["literal_pass"]
        and acceptance["calmar_degenerate"] is None
        and not acceptance["cap_violated"]
        and acceptance["apy_beats_ew"]
        and acceptance["null_median_beats_ew"] is False)
    # CTAC's only free number is `eps`, and on a panel where two books lost NOTHING in crisis 1
    # it is `eps` alone that decides how much of the book they get: 1/(0 + eps). A conclusion that
    # moves with it is a conclusion about the constant, not about tail persistence. The sweep is
    # printed so the reader can see which it is.
    eps_sweep: Dict[str, Dict[str, object]] = {}
    for e in (1e-5, 1e-4, 1e-3, 1e-2, 5e-2):
        r = static_weighted(rets, ctac_weights(c1_losses, eps=e), lo=lo, hi=hi)
        eps_sweep[f"{e:g}"] = {
            "apy_net": r["apy_net"], "maxdd": r["maxdd"], "calmar": r["calmar"],
            "max_name": r["max_name"], "max_name_weight": r["max_name_weight"],
            "degenerate": r["calmar_degenerate"] is not None,
        }
    return {
        "status": "measured", "universe": universe, "pool": pool, "frozen": frozen,
        "eps_sweep": eps_sweep,
        "axis": {"n": len(axis), "first": axis[0], "last": axis[-1],
                 "judged_from": axis[lo], "judged_days": hi - lo},
        "crisis_1": {"key": c1_key, "from": c1_from, "to": c1_to},
        "losses": {k: {b: {"loss": v[b]["loss"], "status": v[b]["status"]} for b in pool}
                   for k, v in losses_by_crisis.items()},
        "portfolios": portfolios, "bootstrap": boot, "acceptance": acceptance,
    }


# ───────────────────────────── printing ─────────────────────────────
def _f(x: Optional[float], *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def print_sfs(rep: Dict[str, object]) -> None:
    ax = rep["axis"]
    print("=" * 100)
    print("§1 · ИДЕЯ #128 SFS — sigma-floor sizer (заказ #126 п.2 = #127 п.2)")
    print("=" * 100)
    print(f"ось: {ax['n']} возвратов {ax['first']}..{ax['last']} · судимых дней {ax['judged_days']}"
          f" · lookback {rep['lookback']} · sigma_floor {rep['headline_sigma_floor']:g}")
    print(f"книги ({len(rep['books'])}): {', '.join(rep['books'])}")
    print(f"живой рукав (#122, после {rep['era']['last_kill']}): {', '.join(rep['live'])}")
    print(f"замороженные: {', '.join(rep['frozen'])}")
    print()
    head = (f"{'вариант':<16}{'APY net':>10}{'maxDD':>13}{'Calmar':>10}{'макс/имя':>10}"
            f"{'дней >20%':>11}{'потолок':>14}{'в мёртвых':>11}{'deployed':>10}{'оборот/д':>10}")
    print(head)
    print("-" * len(head))
    rows = list(rep["variants"].items()) + list(rep["zeros"].items())
    for name, v in rows:
        cvd = v.get("cap_violation_days")
        print(f"{name:<16}{_f(v['apy_net'], pct=True):>10}{_f(v['maxdd'], pct=True):>13}"
              f"{_f(v['calmar']):>10}{_f(v['max_name_weight'], pct=True, nd=1):>10}"
              f"{v['days_over_policy_cap']:>11}"
              f"{('НЕ НАЛОЖЕН' if cvd is None else f'{cvd} наруш.'):>14}"
              f"{_f(v.get('mean_frozen_share'), pct=True, nd=1, dash='—'):>11}"
              f"{_f(v.get('mean_deployed'), pct=True, nd=1, dash='100.0 %'):>10}"
              f"{_f(v.get('turnover_per_day'), pct=True, nd=2, dash='—'):>10}")
    print()
    for name, v in rep["variants"].items():
        print(f"  {name}: dd_status={v['dd_status']} · down_days={v['down_days']} "
              f"· always_refused={v['always_refused']} · degenerate_days={v['degenerate_days']}")
        if v["dd_reason"]:
            print(f"      причина отказа: {v['dd_reason']}")
    print()
    print("КОНТРОЛЬ НА ВЫРОЖДЕННОСТЬ — свип sigma_floor (должен двигать БЕЗ потолка и НЕ двигать с ним):")
    sw = (f"{'floor':>8}{'unc APY':>11}{'unc Calmar':>12}{'unc макс/имя':>14}"
          f"{'cap APY':>11}{'cap Calmar':>12}{'cap макс/имя':>14}")
    print(sw)
    print("-" * len(sw))
    for f, v in rep["floor_sweep"].items():
        print(f"{f:>8}{_f(v['uncapped_apy_net'], pct=True):>11}{_f(v['uncapped_calmar']):>12}"
              f"{_f(v['uncapped_max_name'], pct=True, nd=1):>14}"
              f"{_f(v['capped_apy_net'], pct=True):>11}{_f(v['capped_calmar']):>12}"
              f"{_f(v['capped_max_name'], pct=True, nd=1):>14}")
    print()
    print("ПРИЁМКА ЗАКАЗА:")
    for k, ok in rep["acceptance"].items():
        print(f"  [{'✅' if ok else '❌'}] {k}")


def print_ctac(rep: Dict[str, object]) -> None:
    print()
    print("=" * 100)
    print(f"§2 · ИДЕЯ #129 CTAC-REAL (заказ #127 п.1) — вселенная '{rep['universe']}'")
    print("=" * 100)
    if rep["status"] != "measured":
        print(f"НЕ ИЗМЕРЕНО: {rep['reason']}")
        return
    ax = rep["axis"]
    print(f"ось {ax['n']} возвратов {ax['first']}..{ax['last']} · судится с {ax['judged_from']} "
          f"({ax['judged_days']} дней) · кризис 1 = {rep['crisis_1']['key']} "
          f"{rep['crisis_1']['from']}..{rep['crisis_1']['to']}")
    print(f"вселенная ({len(rep['pool'])}): {', '.join(rep['pool'])}")
    print()
    keys = list(rep["losses"].keys())
    head = f"{'книга':<20}" + "".join(f"{k[:18]:>20}" for k in keys)
    print(head)
    print("-" * len(head))
    for b in rep["pool"]:
        row = f"{b:<20}"
        for k in keys:
            e = rep["losses"][k][b]
            row += f"{(_f(e['loss'], pct=True) + ('*' if e['status'] == 'no_down_day' else '')):>20}"
        print(row)
    print("  (* = окно покрыто, но ни одного дня вниз — ноль ИЗМЕРЕН, а не подставлен)")
    print()
    head = (f"{'портфель':<16}{'APY net':>10}{'maxDD':>13}{'Calmar':>10}{'макс/имя':>11}"
            f"{'потолок 20%':>13}")
    print(head)
    print("-" * len(head))
    for name, v in rep["portfolios"].items():
        print(f"{name:<16}{_f(v['apy_net'], pct=True):>10}{_f(v['maxdd'], pct=True):>13}"
              f"{_f(v['calmar']):>10}{_f(v['max_name_weight'], pct=True, nd=1):>11}"
              f"{('НАРУШЕН' if v['cap_violation'] else 'ok'):>13}")
    for name, v in rep["portfolios"].items():
        if v["dd_reason"]:
            print(f"  {name}: {v['dd_status']} — {v['dd_reason']}")
        if v["calmar_degenerate"]:
            print(f"  ⚠️  {name}: Calmar НЕ РАНЖИРУЕМ — {v['calmar_degenerate']}")
        print(f"      веса: " + ", ".join(f"{b} {w * 100:.1f} %" for b, w in
                                          sorted(v["weights"].items(), key=lambda kv: -kv[1])
                                          if w > 0.005))
    print()
    b = rep["bootstrap"]
    print(f"BOOTSTRAP ({BOOTSTRAP_N} перестановок вектора потерь, seed {BOOTSTRAP_SEED}): "
          f"status={b['status']}")
    if b["status"] == "measured":
        print(f"  actual Calmar {b['actual_calmar']:.3f} · медиана нуля {b['draw_median']:.3f} "
              f"· диапазон [{b['draw_min']:.3f}, {b['draw_max']:.3f}]")
        print(f"  перестановок >= actual: {b['ge']}/{b['comparable']} (отказано {b['refused']}) "
              f"⇒ p = {b['p_value']:.4f}")
        print(f"  ⚠️  вырожденных перестановок (maxDD < пошлины): "
              f"{b['degenerate_draws']}/{b['comparable']}"
              f" · перестановок, бьющих EW по Calmar: {b['draws_beating_ew']}/{b['comparable']}")
    else:
        print(f"  {b['reason']}")
    print()
    print("КОНТРОЛЬ НА ПАРАМЕТР — свип eps (единственное свободное число CTAC):")
    hd = f"{'eps':>8}{'APY net':>11}{'maxDD':>12}{'Calmar':>12}{'тяжелейшее имя':>22}{'вес':>9}{'вырожд.':>9}"
    print(hd)
    print("-" * len(hd))
    for e, v in rep["eps_sweep"].items():
        print(f"{e:>8}{_f(v['apy_net'], pct=True):>11}{_f(v['maxdd'], pct=True, nd=4):>12}"
              f"{_f(v['calmar']):>12}{v['max_name']:>22}"
              f"{_f(v['max_name_weight'], pct=True, nd=1):>9}"
              f"{('да' if v['degenerate'] else 'нет'):>9}")
    print()
    print("ПРИЁМКА ЗАКАЗА #127 п.1:")
    for k in ("calmar_comparable", "calmar_beats_ew", "p_below_0_05", "literal_pass"):
        v = rep["acceptance"][k]
        mark = "⚠️ НЕ ИЗМЕРЕНО" if v is None else ("✅" if v else "❌")
        print(f"  [{mark}] {k} = {v}")
    print("ЗНАЧИТ ЛИ ЭТО ЧТО-НИБУДЬ (проверки поверх буквы заказа):")
    for k in ("calmar_degenerate", "cap_violated", "apy_beats_ew", "null_median_beats_ew",
              "null_share_beating_ew", "passed"):
        v = rep["acceptance"][k]
        if k == "calmar_degenerate":
            mark = "✅" if v is None else "❌"
        elif k == "cap_violated":
            mark = "✅" if v is False else "❌"
        elif k == "null_median_beats_ew":
            mark = "✅" if v is False else "❌"
        elif k == "null_share_beating_ew":
            mark = "ℹ️"
        else:
            mark = "⚠️ НЕ ИЗМЕРЕНО" if v is None else ("✅" if v else "❌")
        print(f"  [{mark}] {k} = {v}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="registry #128 (SFS) and #129 (CTAC-REAL)")
    ap.add_argument("--panel-dir", type=Path, default=None,
                    help="panel root; default = the harness's own data/aggressive_lab")
    ap.add_argument("--section", choices=("sfs", "ctac", "both"), default="both")
    ap.add_argument("--json", action="store_true", help="dump the raw report as JSON")
    a = ap.parse_args(argv)
    out: Dict[str, object] = {}
    if a.section in ("sfs", "both"):
        out["sfs"] = sfs_report(a.panel_dir)
        print_sfs(out["sfs"])
    if a.section in ("ctac", "both"):
        for uni in ("all", "live"):
            rep = ctac_real_report(a.panel_dir, universe=uni)
            out[f"ctac_{uni}"] = rep
            print_ctac(rep)
    if a.json:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
