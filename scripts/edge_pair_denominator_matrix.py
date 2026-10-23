#!/usr/bin/env python3
"""scripts/edge_pair_denominator_matrix.py — registry ideas #140 (PDM) and #141 (TUB).

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

TWO IDEAS, ONE FILE, BECAUSE THEY ARE THE SAME DEFECT SEEN FROM TWO SIDES
=========================================================================
Seven registry entries in a row (#122, #124, #126, #128, #129, #131, #137) died on one thing:
on the real panel a book that carries has no observed tail, a book with a tail has no carry, and
every ratio formed between them has a denominator that is not there. #137 closed its entry with
a one-line order:

    "Проверить, существует ли на этой оси ХОТЬ ОДНА пара книг, у которой обе ноги дают
     измеренный знаменатель на обеих половинах шва, — и если да, мерить состав только на ней.
     Критерий приёмки: напечатана матрица 10x10 'пара -> измеримость знаменателя на TRAIN и на
     TEST', либо ОТКАЗ с названной причиной, что таких пар нет."

#138 and #139 were written after that order and did not execute it: both measured the SYNTHETIC
stress fixture, and both said so. This file executes it (#140) and then asks the opposite
question (#141): instead of hunting for the places where the denominator survives, can a sizer
be built whose denominator CANNOT vanish, because ignorance is PRICED rather than read as zero?

  §1  THE LEGS.   Per-book measurability of maxDD on TRAIN and on TEST, three outcomes kept
      apart, and a SECOND gate the order's wording does not mention but #129/#132 already
      made binding: a maxDD below the round-trip toll is a rounding artefact, not a risk.
  §2  THE MATRIX. The 10x10 table the order's acceptance criterion names, cell by cell.
  §3  THE COMPOSITION. Only on the surviving pairs, as the order instructs: an 11-point blend
      sweep per pair, both halves, toll charged, plus the rank transfer of the frontier.
  §4  TUB (#141). A NEW hypothesis. The risk denominator of a book is not its observed maxDD
      but an exact one-sided Clopper-Pearson UPPER BOUND on its daily-loss probability times
      the loss magnitude -- so a book with no observed down day is charged for the days it was
      NOT observed falling, instead of being handed a zero. Prediction P1, registered before
      the run: this moves weight AWAY from never-fallen books relative to 1/sigma (#131).

WHY #141 IS NOT A RESTATEMENT OF #30 (SKD)
------------------------------------------
#30 replaced sigma^2 in Kelly with downside semi-variance. That is still an OBSERVED quantity and
it vanishes on exactly the same books, for exactly the same reason -- a series with no day below
zero has semi-variance 0.0 as surely as it has maxDD 0.0. TUB's denominator is not an observation
at all: it is a bound whose size is driven by HOW LITTLE WAS SEEN (p_hi -> 1/N), which is why it
cannot vanish while N is finite. The registry has no confidence-bound entry: `Wilson`,
`Clopper-Pearson`, `rule of three`, `UCB` and `Bayes` appear nowhere in its 13 679 lines.

HONEST LIMIT OF #141, STATED BEFORE ITS NUMBERS
-----------------------------------------------
A bound needs a probability AND a magnitude. For a book that never fell, the probability is
boundable from N alone, but the magnitude is NOT OBSERVABLE from its own return series -- nothing
in the data says how far it would have fallen. This file uses the panel's median observed
down-day magnitude as that stand-in and labels every such number `modelled_magnitude`
(kind="modelled", ADR-580 C2), never `measured`. That substitution is the weakest joint of the
idea and §4 measures its consequence rather than asserting it is small.

Advisory only. Nothing is written to disk, the panel is opened read-only, the go-live track is
never touched, RiskPolicy v1.0 is not read and not changed, no module is built, no agent deployed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
SFS_PATH = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"

#: the 11-point blend grid of §3. Coarse on purpose: a finer grid would let §3 report an
#: interior optimum that is an artefact of resolution rather than of the data.
BLEND_GRID: Tuple[float, ...] = tuple(k / 10.0 for k in range(11))

#: confidence levels swept in §4. Spans ten orders of magnitude so "the penalty is too weak"
#: is a statement about the mechanism and not about the one alpha a convention happens to use.
ALPHA_SWEEP: Tuple[float, ...] = (0.32, 0.10, 0.05, 0.01, 1e-4, 1e-8)

#: trailing windows swept in §4.
LOOKBACK_SWEEP: Tuple[int, ...] = (30, 90, 180, 365)

#: default trailing window of the TUB sizer.
TUB_LOOKBACK = 90

#: default confidence level of the TUB bound (one-sided 95 %).
TUB_ALPHA = 0.05

_MOD_CACHE: Dict[str, object] = {}


def _load(path: Path, name: str):
    key = str(path)
    if key not in _MOD_CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import {name} at {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MOD_CACHE[key] = mod
    return _MOD_CACHE[key]


def sfs_mod(path: Path = SFS_PATH):
    """#128's module: `drawdown_verdict`, `calmar_degenerate`, `cap_waterfill`, the toll, the cap.

    IMPORTED, never retyped. Every threshold this file judges by (ROUNDTRIP 0.96 %, POLICY_CAP
    20 %, EPS) is read off that module at call time, so a change there cannot leave this file
    quietly judging by a stale copy of it.
    """
    return _load(path, "edge_sigma_floor_ctac_real")


def panel_mod():
    """The panel loader everything in the series reuses (`plb_load`, `perf`, `rank_spearman`)."""
    return sfs_mod().load_harness()


# ═════════════════════════════ the panel and its seam ═════════════════════════════
def load_axis(panel_dir: Optional[Path] = None) -> Dict[str, object]:
    """Panel, common axis and the harness's OWN out-of-sample seam.

    The seam is `TRAIN_END` of the harness, read from it rather than restated: a seam retyped
    here could drift from the one every earlier entry of the series was measured against, and
    the whole point of §2 is comparability with #137.
    """
    H = panel_mod()
    pdir = Path(panel_dir) if panel_dir is not None else H.PANEL_DIR
    if not pdir.is_dir():
        raise RuntimeError(
            f"panel directory {pdir} does not exist -- NOT MEASURED. The real panel is runtime "
            f"state and lives only in the production tree; pass --panel-dir pointing at it. "
            f"Refusing to judge anything on a panel that is not there."
        )
    axis, rets, books = H.plb_load(pdir)
    seam = H.TRAIN_END
    before = [i for i, d in enumerate(axis) if d <= seam]
    if not before or len(before) == len(axis):
        raise RuntimeError(f"seam {seam} does not split this axis ({axis[0]}..{axis[-1]})")
    split = before[-1] + 1
    return {"axis": axis, "rets": rets, "books": books, "split": split, "seam": seam,
            "halves": {"TRAIN": (0, split), "TEST": (split, len(axis))},
            "panel_dir": str(pdir)}


# ═══════════════════════ §1 · PDM: which legs can be judged at all ═══════════════════════
def leg_measurability(rets: Dict[str, Sequence[float]], book: str,
                      halves: Dict[str, Tuple[int, int]]) -> Dict[str, object]:
    """maxDD status of one book in each half, under BOTH gates, with the reason kept.

    Gate 1 is #128's `drawdown_verdict`: a series with no day below zero has NOT drawn down 0.0,
    it has not been observed drawing down at all (inv. #17).

    Gate 2 is #129's/#132's toll floor, and it is the gate the order's wording omits. A book
    whose deepest observed fall is shallower than the 0.96 % charged to enter it has a
    denominator made of rounding, and ordering it against a book that fell twenty times further
    is the degeneracy that produced four of the seven dead entries. Both gates are reported
    separately so a reader can see WHICH one refused -- "no fall was seen" and "the fall seen is
    smaller than the fee" are different facts and the series has already confused them once.
    """
    S = sfs_mod()
    per: Dict[str, object] = {}
    survives = True
    for half, (lo, hi) in halves.items():
        v = S.drawdown_verdict(rets[book][lo:hi])
        degen = S.calmar_degenerate(v["maxdd"])
        ok = v["status"] == "measured" and degen is None
        survives = survives and ok
        per[half] = {"status": v["status"], "maxdd": v["maxdd"], "down_days": v["down_days"],
                     "apy": v["apy"], "degenerate": degen, "survives": ok,
                     "reason": v["reason"]}
    return {"book": book, "halves": per, "survives_both": survives}


def legs_report(rets: Dict[str, Sequence[float]], books: Sequence[str],
                halves: Dict[str, Tuple[int, int]]) -> Dict[str, object]:
    rows = {b: leg_measurability(rets, b, halves) for b in books}
    survivors = sorted(b for b in books if rows[b]["survives_both"])
    return {"rows": rows, "survivors": survivors, "n_books": len(books),
            "n_survivors": len(survivors)}


# ═══════════════════════ §2 · PDM: the matrix the order asks for ═══════════════════════
#: the only three cell verdicts §2 may print. A pair is refused by its LEGS (one of them cannot
#: be judged in some half) or by ITSELF (both legs judgeable, but the 50/50 portfolio's own
#: drawdown is not), and those are different findings: the first is about the panel, the second
#: about what mixing does to a denominator.
CELL_LEGS = "legs_refused"
CELL_PAIR = "pair_refused"
CELL_OK = "measurable"


def pair_cell(rets: Dict[str, Sequence[float]], a: str, b: str,
              halves: Dict[str, Tuple[int, int]], legs: Dict[str, object]) -> Dict[str, object]:
    """One cell: can the PAIR be judged on both halves, and if not, which gate refused?"""
    S = sfs_mod()
    if not (legs["rows"][a]["survives_both"] and legs["rows"][b]["survives_both"]):
        bad = [n for n in (a, b) if not legs["rows"][n]["survives_both"]]
        return {"verdict": CELL_LEGS, "blocked_by": bad,
                "reason": f"leg(s) {', '.join(bad)} cannot be judged in both halves"}
    per: Dict[str, object] = {}
    ok = True
    for half, (lo, hi) in halves.items():
        r = S.static_weighted(rets, {a: 0.5, b: 0.5}, lo=lo, hi=hi)
        good = r["dd_status"] == "measured" and r["calmar_degenerate"] is None
        ok = ok and good
        per[half] = {"status": r["dd_status"], "maxdd": r["maxdd"], "calmar": r["calmar"],
                     "degenerate": r["calmar_degenerate"], "survives": good}
    return {"verdict": CELL_OK if ok else CELL_PAIR, "halves": per,
            "reason": None if ok else "both legs judgeable, the 50/50 portfolio is not"}


def pair_matrix(rets: Dict[str, Sequence[float]], books: Sequence[str],
                halves: Dict[str, Tuple[int, int]],
                legs: Dict[str, object]) -> Dict[str, object]:
    """The full N x N table. Unordered pairs are listed once; the printed matrix stays square."""
    cells: Dict[str, Dict[str, object]] = {}
    pairs: List[Tuple[str, str]] = []
    for a in books:
        for b in books:
            if a == b:
                continue
            cells.setdefault(a, {})[b] = cell = pair_cell(rets, a, b, halves, legs)
            if a < b and cell["verdict"] == CELL_OK:
                pairs.append((a, b))
    total = len(books) * (len(books) - 1) // 2
    return {"cells": cells, "surviving_pairs": pairs, "n_pairs_total": total,
            "n_pairs_surviving": len(pairs),
            "refusal_reason": (None if pairs else
                               "no pair on this axis has both legs judgeable in both halves")}


# ═══════════════════════ §3 · PDM: composition, on the survivors only ═══════════════════════
def blend_sweep(rets: Dict[str, Sequence[float]], a: str, b: str,
                halves: Dict[str, Tuple[int, int]],
                grid: Sequence[float] = BLEND_GRID) -> Dict[str, object]:
    """An 11-point static blend of one surviving pair, judged in each half.

    Static by construction: #137's order is about COMPOSITION, and a timed rule would answer a
    different question with the same table. The toll is charged once on entry (`static_weighted`),
    which is the convention the rest of the series used for static sleeves.

    The 20 %/name ceiling is VIOLATED by every interior cell of a two-book blend by construction,
    and that is reported rather than hidden: §3 answers "is there anything to find in composition
    here", not "is this deployable". Nothing deployable comes out of a two-name sleeve anyway.
    """
    S = sfs_mod()
    H = panel_mod()
    rows: Dict[str, List[Dict[str, object]]] = {}
    for half, (lo, hi) in halves.items():
        out = []
        for w in grid:
            r = S.static_weighted(rets, {a: w, b: 1.0 - w}, lo=lo, hi=hi)
            out.append({"w_a": w, "apy_net": r["apy_net"], "apy_gross": r["apy_gross"],
                        "maxdd": r["maxdd"], "calmar": r["calmar"],
                        "degenerate": r["calmar_degenerate"], "status": r["dd_status"],
                        "cap_violation": r["cap_violation"]})
        rows[half] = out

    def judged(half: str) -> Optional[List[float]]:
        vals = [c["calmar"] if c["degenerate"] is None else None for c in rows[half]]
        return None if any(v is None for v in vals) else [float(v) for v in vals]

    tr, te = judged("TRAIN"), judged("TEST")
    transfer: Dict[str, object]
    if tr is None or te is None:
        missing = [h for h, v in (("TRAIN", tr), ("TEST", te)) if v is None]
        transfer = {"status": "unmeasured", "spearman": None,
                    "reason": f"at least one blend cell is refused in {', '.join(missing)} -- "
                              f"a rank correlation over a column with a hole is not a number"}
    else:
        i_tr = max(range(len(tr)), key=lambda i: tr[i])
        i_te = max(range(len(te)), key=lambda i: te[i])
        order = sorted(range(len(te)), key=lambda i: -te[i])
        interior = [i for i in range(1, len(grid) - 1)
                    if te[i] > max(te[0], te[-1]) + 1e-12]
        transfer = {
            "status": "measured",
            "spearman": H.rank_spearman(tr, te),
            "argmax_train_w": grid[i_tr], "argmax_train_calmar": tr[i_tr],
            "argmax_train_on_test_calmar": te[i_tr],
            "argmax_train_rank_on_test": order.index(i_tr) + 1,
            "n_cells": len(grid),
            "argmax_test_w": grid[i_te], "argmax_test_calmar": te[i_te],
            "train_interior_optimum": 0 < i_tr < len(grid) - 1,
            "test_interior_optimum": 0 < i_te < len(grid) - 1,
            "test_blend_beats_both_legs": bool(interior),
            "test_best_interior_gain": (te[max(interior, key=lambda i: te[i])]
                                        - max(te[0], te[-1])) if interior else None,
        }
    return {"pair": [a, b], "rows": rows, "transfer": transfer}


# ═══════════════════════════ §4 · TUB: pricing what was not seen ═══════════════════════════
def binom_tail_le(n: int, d: int, p: float) -> float:
    """P(X <= d) for X ~ Bin(n, p), summed in log space.

    Log space is not decoration: `math.comb(482, 175)` is a 140-digit integer and multiplying it
    by p**175 in float arithmetic overflows one way and underflows the other. lgamma keeps every
    term finite for the window sizes this file sweeps.
    """
    if n < 0 or d < 0 or d > n:
        raise ValueError(f"invalid binomial tail request n={n} d={d}")
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if d >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    total = 0.0
    for k in range(d + 1):
        lc = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        total += math.exp(lc + k * lp + (n - k) * lq)
    return min(1.0, total)


def cp_upper(n: int, d: int, alpha: float = TUB_ALPHA, *, iters: int = 80) -> Optional[float]:
    """Exact one-sided Clopper-Pearson upper bound on p: smallest p with P(X <= d) <= alpha.

    Stdlib only, by bisection on a tail that is monotone decreasing in p. The d == 0 case has
    the closed form 1 - alpha**(1/n) -- the "rule of three" when alpha = 0.05 -- and is returned
    directly rather than bisected, so the one case the whole idea turns on is exact and not
    approximate.

    Returns None for n <= 0: a bound over no observations is not 1.0 and not 0.0, it is NOT
    MEASURED, and handing back a float here is how a sizer would come to weight a book it has
    never seen (inv. #17).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if n <= 0:
        return None
    if d >= n:
        return 1.0
    if d == 0:
        return 1.0 - alpha ** (1.0 / n)
    lo, hi = d / n, 1.0
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if binom_tail_le(n, d, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def tub_bounds(rets: Dict[str, Sequence[float]], books: Sequence[str], *, end: int,
               lookback: int, alpha: float = TUB_ALPHA,
               eps: Optional[float] = None) -> Dict[str, object]:
    """Per-book upper bound on expected daily loss over the window STRICTLY BEFORE `end`.

    bound = p_hi * m, where p_hi is the Clopper-Pearson upper bound on the probability of a day
    below zero and m is the magnitude of such a day:

      * m OBSERVED  (`measured_magnitude`)  -- the window has down days; m is their mean |r|.
      * m MODELLED  (`modelled_magnitude`)  -- the window has none; m is the PANEL's median
        observed down-day magnitude in the same window. This is the idea's weakest joint, named
        in the file header, and it is labelled on every row that uses it.
      * m ABSENT    (`unmeasured_no_panel_magnitude`) -- not one book fell anywhere in the
        window. Then there is no magnitude to borrow and the bound is None: the day is refused,
        not filled in.

    Causality: the window is `rets[b][end-lookback : end]`, open at `end`. The day being sized is
    never inside the window that sizes it.
    """
    S = sfs_mod()
    eps = S.EPS if eps is None else eps
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    lo = max(0, end - lookback)
    win = {b: list(rets[b][lo:end]) for b in books}
    mags: Dict[str, float] = {}
    for b in books:
        down = [abs(x) for x in win[b] if x < -eps]
        if down:
            mags[b] = statistics.fmean(down)
    panel_m = statistics.median(mags.values()) if mags else None
    out: Dict[str, Dict[str, object]] = {}
    for b in books:
        n = len(win[b])
        d = sum(1 for x in win[b] if x < -eps)
        p_hi = cp_upper(n, d, alpha)
        if p_hi is None:
            out[b] = {"bound": None, "kind": "unmeasured_empty_window", "p_hi": None,
                      "m": None, "n": n, "down": d}
        elif d > 0:
            out[b] = {"bound": p_hi * mags[b], "kind": "measured_magnitude", "p_hi": p_hi,
                      "m": mags[b], "n": n, "down": d}
        elif panel_m is not None:
            out[b] = {"bound": p_hi * panel_m, "kind": "modelled_magnitude", "p_hi": p_hi,
                      "m": panel_m, "n": n, "down": d}
        else:
            out[b] = {"bound": None, "kind": "unmeasured_no_panel_magnitude", "p_hi": p_hi,
                      "m": None, "n": n, "down": d}
    return {"books": out, "panel_magnitude": panel_m, "lookback": lookback, "alpha": alpha}


def rule_live(rets: Dict[str, Sequence[float]], book: str, end: int, lookback: int) -> bool:
    """#131's liveness admission: the book MOVED in the trailing window (sigma > 0).

    Reused verbatim in spirit because #131 measured that it is the only admission rule on this
    panel under which the denominator is observable at all. Here it is a CONTROL, not the idea:
    §4 runs TUB with and without it precisely so the dead-book leak and the bound can be told
    apart.
    """
    lo = max(0, end - lookback)
    w = rets[book][lo:end]
    return len(w) > 1 and statistics.pstdev(w) > 1e-9


def run_tub(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int, hi: int,
            kind: str = "tub", lookback: int = TUB_LOOKBACK, alpha: float = TUB_ALPHA,
            cap: Optional[float] = None, roundtrip: Optional[float] = None,
            live_filter: bool = False) -> Dict[str, object]:
    """One causal sizer run over [lo, hi). `kind` selects the denominator.

    Four denominators share this loop so that the only difference between the rows of §4's table
    is the denominator itself -- same window, same water-fill, same ceiling, same toll on TRADED
    notional (roundtrip * sum|dw| / 2), same gross-series drawdown convention as
    `edge_admitted_set_guardian_zero.run_sizer_rule`. Equivalence with that function on the two
    rules they share (`ew`, `inv_sigma`) is asserted by a TEST, not claimed here.

      tub        1 / (p_hi * m)   -- #141, the idea
      inv_sigma  1 / sigma        -- #131's sizer, the rule TUB claims to improve on
      ew         1                -- the parameter-free zero (#123)
    """
    S = sfs_mod()
    H = panel_mod()
    cap = S.POLICY_CAP if cap is None else cap
    roundtrip = S.ROUNDTRIP if roundtrip is None else roundtrip
    if lo < lookback:
        raise ValueError(f"start index {lo} is inside the first {lookback}-day window")
    if hi <= lo:
        raise ValueError("empty slice -- refusing to report a portfolio of nothing")
    prev = {b: 0.0 for b in books}
    clean: List[float] = []
    series: List[float] = []
    wsum = {b: 0.0 for b in books}
    kind_days: Dict[str, int] = {}
    refused_days = 0
    deployed: List[float] = []
    turnover = 0.0
    max_w, max_name = 0.0, None
    cap_violation_days = 0
    for t in range(lo, hi):
        pool = [b for b in books if (not live_filter) or rule_live(rets, b, t, lookback)]
        if kind == "tub":
            bounds = tub_bounds(rets, pool, end=t, lookback=lookback, alpha=alpha)["books"]
            admitted = [b for b in pool
                        if bounds[b]["bound"] is not None and bounds[b]["bound"] > 0.0]
            for b in admitted:
                k = str(bounds[b]["kind"])
                kind_days[k] = kind_days.get(k, 0) + 1
            raw = {b: 1.0 / float(bounds[b]["bound"]) for b in admitted}
        elif kind == "inv_sigma":
            admitted = [b for b in pool if rule_live(rets, b, t, lookback)]
            raw = {b: 1.0 / max(statistics.pstdev(rets[b][max(0, t - lookback):t]), 1e-5)
                   for b in admitted}
        elif kind == "ew":
            admitted = list(pool)
            raw = {b: 1.0 for b in admitted}
        else:
            raise ValueError(f"unknown denominator {kind!r}")
        if not admitted:
            refused_days += 1
            w = {b: 0.0 for b in books}
            dep = 0.0
        else:
            tot = sum(raw.values())
            shares = {b: (raw.get(b, 0.0) / tot) for b in books}
            out = S.cap_waterfill(shares, cap=cap)
            w = out["weights"]
            dep = float(out["deployed"])
        for b in books:
            wsum[b] += w[b]
            if w[b] > max_w:
                max_w, max_name = w[b], b
        if any(w[b] > S.POLICY_CAP + 1e-12 for b in books):
            cap_violation_days += 1
        deployed.append(dep)
        turn = sum(abs(w[b] - prev[b]) for b in books) / 2.0
        turnover += turn
        gross = sum(w[b] * rets[b][t] for b in books)
        clean.append(gross)
        series.append(gross - roundtrip * turn)
        prev = w
    v = S.drawdown_verdict(clean)
    n = hi - lo
    return {"kind": kind, "live_filter": live_filter, "lookback": lookback, "alpha": alpha,
            "n_days": n, "apy_gross": v["apy"], "apy_net": H.perf(series)["apy"],
            "maxdd": v["maxdd"], "calmar": v["calmar"], "dd_status": v["status"],
            "dd_reason": v["reason"], "down_days": v["down_days"],
            "calmar_degenerate": S.calmar_degenerate(v["maxdd"]),
            "mean_weight": {b: wsum[b] / n for b in books},
            "max_name": max_name, "max_name_weight": max_w,
            "cap_violation_days": cap_violation_days,
            "turnover_per_day": turnover / n, "mean_deployed": sum(deployed) / n,
            "refused_days": refused_days, "magnitude_kind_days": kind_days}


def never_fallen(rets: Dict[str, Sequence[float]], books: Sequence[str], *, lo: int = 0,
                 hi: Optional[int] = None) -> List[str]:
    """Books with no day below zero over [lo, hi) -- the names P1 is about."""
    S = sfs_mod()
    hi = len(next(iter(rets.values()))) if hi is None else hi
    return sorted(b for b in books if not any(r < -S.EPS for r in rets[b][lo:hi]))


def breakeven_alpha(rets: Dict[str, Sequence[float]], books: Sequence[str], *,
                    n_obs: Optional[int] = None) -> Dict[str, object]:
    """At what confidence would a never-fallen book be ranked RISKIER than each measured book?

    This is the honest size of the mechanism, and it is a number rather than an opinion. A
    never-fallen book over n observations has p_hi = 1 - alpha**(1/n), so to reach the bound of a
    measured book it needs p_hi >= target/m_panel, i.e. alpha <= (1 - target/m_panel)**n. Where
    that requires p_hi > 1 the answer is `unreachable`: no confidence level, however extreme,
    ranks the never-fallen book riskier -- the bound is capped at the magnitude itself.
    """
    S = sfs_mod()
    n_obs = len(next(iter(rets.values()))) if n_obs is None else n_obs
    mags: Dict[str, float] = {}
    for b in books:
        down = [abs(r) for r in rets[b][:n_obs] if r < -S.EPS]
        if down:
            mags[b] = statistics.fmean(down)
    if not mags:
        return {"status": "unmeasured", "panel_magnitude": None, "rows": {},
                "reason": "not one book on this panel fell -- no magnitude to compare against"}
    panel_m = statistics.median(mags.values())
    rows: Dict[str, Dict[str, object]] = {}
    for b, m in mags.items():
        d = sum(1 for r in rets[b][:n_obs] if r < -S.EPS)
        p_hi = cp_upper(n_obs, d, TUB_ALPHA)
        target = (p_hi or 0.0) * m
        need = target / panel_m
        rows[b] = {"bound": target, "needed_p_hi": need, "down_days": d,
                   "alpha": ((1.0 - need) ** n_obs) if 0.0 < need < 1.0 else None,
                   "status": "measured" if 0.0 < need < 1.0 else "unreachable"}
    return {"status": "measured", "panel_magnitude": panel_m, "n_obs": n_obs, "rows": rows}


# ═══════════════════════════════════ the report ═══════════════════════════════════
def pdm_report(panel_dir: Optional[Path] = None, *, lookback: int = TUB_LOOKBACK,
               alpha: float = TUB_ALPHA) -> Dict[str, object]:
    """§1-§4 in one pass. Pure: reads the panel, writes nothing."""
    L = load_axis(panel_dir)
    rets, books, halves = L["rets"], L["books"], L["halves"]
    legs = legs_report(rets, books, halves)
    matrix = pair_matrix(rets, books, halves, legs)
    comps = [blend_sweep(rets, a, b, halves) for a, b in matrix["surviving_pairs"]]

    split = int(L["split"])
    tub_halves = {"TRAIN": (lookback, split), "TEST": (split, len(L["axis"]))}
    table: List[Dict[str, object]] = []
    for half, (lo, hi) in tub_halves.items():
        for kind, lf in (("tub", False), ("tub", True), ("inv_sigma", False),
                         ("ew", False), ("ew", True)):
            r = run_tub(rets, books, lo=lo, hi=hi, kind=kind, lookback=lookback,
                        alpha=alpha, live_filter=lf)
            r["half"] = half
            r["label"] = kind + ("_live" if lf else "")
            table.append(r)

    nf_full = never_fallen(rets, books)
    p1: Dict[str, object] = {"never_fallen": nf_full, "halves": {}}
    for half, (lo, hi) in tub_halves.items():
        t = run_tub(rets, books, lo=lo, hi=hi, kind="tub", lookback=lookback, alpha=alpha)
        s = run_tub(rets, books, lo=lo, hi=hi, kind="inv_sigma", lookback=lookback)
        mt = sum(t["mean_weight"][b] for b in nf_full)
        ms = sum(s["mean_weight"][b] for b in nf_full)
        p1["halves"][half] = {"tub_mass": mt, "inv_sigma_mass": ms, "delta": mt - ms,
                              "p1_holds": mt < ms,
                              "per_book": {b: {"tub": t["mean_weight"][b],
                                               "inv_sigma": s["mean_weight"][b]} for b in books}}
    sweeps = {
        "alpha": [dict(run_tub(rets, books, lo=split, hi=len(L["axis"]), kind="tub",
                               lookback=lookback, alpha=a),
                       never_fallen_mass=None) for a in ALPHA_SWEEP],
        "lookback": [run_tub(rets, books, lo=max(lb, split), hi=len(L["axis"]), kind="tub",
                             lookback=lb, alpha=alpha) for lb in LOOKBACK_SWEEP],
    }
    for row in sweeps["alpha"]:
        row["never_fallen_mass"] = sum(row["mean_weight"][b] for b in nf_full)
    for row in sweeps["lookback"]:
        row["never_fallen_mass"] = sum(row["mean_weight"][b] for b in nf_full)

    return {"panel": {k: L[k] for k in ("axis", "books", "split", "seam", "panel_dir")},
            "legs": legs, "matrix": matrix, "composition": comps,
            "tub": {"table": table, "p1": p1, "sweeps": sweeps,
                    "breakeven": breakeven_alpha(rets, books)}}


def _f(x: Optional[float], *, pct: bool = False, nd: int = 2,
       dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f}" if pct else f"{x:.{nd}f}"


def _calmar(c: Optional[float], degen: Optional[str]) -> str:
    return "ОТКАЗАН" if (c is None or degen) else f"{c:.3f}"


def print_report(rep: Dict[str, object]) -> None:
    P, legs, matrix = rep["panel"], rep["legs"], rep["matrix"]
    axis = P["axis"]
    print("=" * 100)
    print("#140 PDM — ИСПОЛНЕНИЕ ЗАКАЗА #137 · #141 TUB — знаменатель, наказывающий незнание")
    print("=" * 100)
    print(f"панель: {P['panel_dir']}")
    print(f"ось: {len(axis)} дней {axis[0]} … {axis[-1]} | шов {P['seam']} | "
          f"TRAIN {P['split']} / TEST {len(axis) - P['split']} | книг {legs['n_books']}")
    print(f"пошлина {sfs_mod().ROUNDTRIP * 100:.2f} % · потолок {sfs_mod().POLICY_CAP * 100:.0f} %/имя")

    print("\n" + "─" * 100)
    print("§1 НОГИ — измерим ли знаменатель книги в ОБЕИХ половинах шва (два гейта)")
    print("─" * 100)
    print(f"{'книга':20} {'TRAIN статус':>22} {'maxDD%':>8} {'TEST статус':>22} {'maxDD%':>8} {'ОБЕ':>5}")
    for b in legs["rows"]:
        r = legs["rows"][b]["halves"]
        print(f"{b:20} {r['TRAIN']['status']:>22} {_f(r['TRAIN']['maxdd'], pct=True):>8} "
              f"{r['TEST']['status']:>22} {_f(r['TEST']['maxdd'], pct=True):>8} "
              f"{('ДА' if legs['rows'][b]['survives_both'] else 'нет'):>5}")
    print(f"\nвыжило ног: {legs['n_survivors']} из {legs['n_books']} → {legs['survivors']}")
    for b in legs["rows"]:
        for h in ("TRAIN", "TEST"):
            d = legs["rows"][b]["halves"][h]["degenerate"]
            if d and legs["rows"][b]["halves"][h]["status"] == "measured":
                print(f"  ВТОРОЙ ГЕЙТ отказал {b} на {h}: {d}")

    print("\n" + "─" * 100)
    print("§2 МАТРИЦА 10×10 — критерий приёмки заказа #137")
    print("─" * 100)
    books = P["books"]
    short = {b: b[:9] for b in books}
    print(f"{'':20}" + "".join(f"{short[b]:>11}" for b in books))
    tag = {CELL_OK: "ДА", CELL_PAIR: "пара", CELL_LEGS: "ноги"}
    for a in books:
        cells = []
        for b in books:
            cells.append("·" if a == b else tag[str(matrix["cells"][a][b]["verdict"])])
        print(f"{a:20}" + "".join(f"{c:>11}" for c in cells))
    print(f"\nвыживших ПАР: {matrix['n_pairs_surviving']} из {matrix['n_pairs_total']}")
    for a, b in matrix["surviving_pairs"]:
        print(f"  · {a} / {b}")
    if matrix["refusal_reason"]:
        print(f"ОТКАЗ: {matrix['refusal_reason']}")

    print("\n" + "─" * 100)
    print("§3 СОСТАВ — только на выживших парах (статический бленд, пошлина взята)")
    print("─" * 100)
    for comp in rep["composition"]:
        a, b = comp["pair"]
        print(f"\nПАРА {a} / {b}   (w_a — доля первой ноги)")
        print(f"{'w_a':>5} | {'TRAIN apy%':>11} {'maxDD%':>8} {'Calmar':>9} | "
              f"{'TEST apy%':>11} {'maxDD%':>8} {'Calmar':>9}")
        for i, w in enumerate(BLEND_GRID):
            tr, te = comp["rows"]["TRAIN"][i], comp["rows"]["TEST"][i]
            print(f"{w:5.1f} | {_f(tr['apy_net'], pct=True):>11} {_f(tr['maxdd'], pct=True):>8} "
                  f"{_calmar(tr['calmar'], tr['degenerate']):>9} | "
                  f"{_f(te['apy_net'], pct=True):>11} {_f(te['maxdd'], pct=True):>8} "
                  f"{_calmar(te['calmar'], te['degenerate']):>9}")
        t = comp["transfer"]
        if t["status"] != "measured":
            print(f"  ПЕРЕНОС НЕ ИЗМЕРЕН: {t['reason']}")
            continue
        print(f"  spearman(TRAIN,TEST) по {t['n_cells']} клеткам = {t['spearman']:+.3f}")
        print(f"  argmax TRAIN w_a={t['argmax_train_w']:.1f} (Calmar {t['argmax_train_calmar']:.3f}) "
              f"→ на TEST Calmar {t['argmax_train_on_test_calmar']:.3f}, "
              f"место {t['argmax_train_rank_on_test']}/{t['n_cells']}")
        print(f"  argmax TEST  w_a={t['argmax_test_w']:.1f} (Calmar {t['argmax_test_calmar']:.3f})")
        print(f"  внутренний оптимум: TRAIN={'ДА' if t['train_interior_optimum'] else 'НЕТ (угол)'} · "
              f"TEST={'ДА' if t['test_interior_optimum'] else 'НЕТ (угол)'}")
        g = t["test_best_interior_gain"]
        print(f"  бьёт ли бленд ОБЕ ноги на TEST: "
              f"{('ДА, +%.3f Calmar' % g) if t['test_blend_beats_both_legs'] else 'НЕТ'}")

    print("\n" + "─" * 100)
    print("§4 TUB (#141) — знаменатель 1/(p_hi·m): граница вероятности падения × размер падения")
    print("─" * 100)
    T = rep["tub"]
    print(f"{'половина':8} {'правило':12} {'apyNet%':>9} {'maxDD%':>8} {'Calmar':>9} "
          f"{'макс.имя':>19} {'maxW':>6} {'оборот/д':>9}")
    for r in T["table"]:
        print(f"{r['half']:8} {r['label']:12} {_f(r['apy_net'], pct=True):>9} "
              f"{_f(r['maxdd'], pct=True):>8} {_calmar(r['calmar'], r['calmar_degenerate']):>9} "
              f"{str(r['max_name'])[:19]:>19} {r['max_name_weight']:6.3f} "
              f"{r['turnover_per_day']:9.4f}")

    p1 = T["p1"]
    print(f"\nПРЕДИКЦИЯ P1 («TUB уводит вес ОТ книг, которые ни разу не падали») — "
          f"никогда не падали: {p1['never_fallen']}")
    for half, d in p1["halves"].items():
        print(f"  {half}: масса в них TUB {d['tub_mass']:.3f} против 1/σ {d['inv_sigma_mass']:.3f} "
              f"⇒ Δ {d['delta']:+.3f} · P1 {'ПОДТВЕРЖДЕНА' if d['p1_holds'] else 'ОПРОВЕРГНУТА'}")
    print(f"\n  {'книга':20} {'TUB':>8} {'1/σ':>8} {'Δ':>8}   (TEST)")
    for b, d in p1["halves"]["TEST"]["per_book"].items():
        print(f"  {b:20} {d['tub']:8.3f} {d['inv_sigma']:8.3f} {d['tub'] - d['inv_sigma']:+8.3f}")

    print(f"\nСВЁРТКА ПО α (TEST) — меняет ли сила наказания исход")
    print(f"{'alpha':>10} {'apyNet%':>9} {'maxDD%':>8} {'Calmar':>9} {'масса в непадавших':>20}")
    for r in T["sweeps"]["alpha"]:
        print(f"{r['alpha']:10.0e} {_f(r['apy_net'], pct=True):>9} {_f(r['maxdd'], pct=True):>8} "
              f"{_calmar(r['calmar'], r['calmar_degenerate']):>9} {r['never_fallen_mass']:20.3f}")
    print(f"\nСВЁРТКА ПО ОКНУ (TEST)")
    print(f"{'lookback':>10} {'apyNet%':>9} {'maxDD%':>8} {'Calmar':>9} {'масса в непадавших':>20}")
    for r in T["sweeps"]["lookback"]:
        print(f"{r['lookback']:10d} {_f(r['apy_net'], pct=True):>9} {_f(r['maxdd'], pct=True):>8} "
              f"{_calmar(r['calmar'], r['calmar_degenerate']):>9} {r['never_fallen_mass']:20.3f}")

    be = T["breakeven"]
    print(f"\nГРАНИЦА БЕЗРАЗЛИЧИЯ — при каком α непадавшая книга (n={be.get('n_obs')}) становится "
          f"РИСКОВАННЕЕ измеренной")
    if be["status"] != "measured":
        print(f"  НЕ ИЗМЕРЕНО: {be['reason']}")
    else:
        print(f"  медиана размера падения по панели m = {be['panel_magnitude'] * 1e4:.1f} бп")
        print(f"  {'книга':20} {'её граница, бп/д':>17} {'нужен p_hi':>11} {'нужна α':>12}")
        for b, r in sorted(be["rows"].items(), key=lambda kv: kv[1]["bound"]):
            a = f"{r['alpha']:.3e}" if r["status"] == "measured" else "НЕДОСТИЖИМА"
            print(f"  {b:20} {r['bound'] * 1e4:17.2f} {r['needed_p_hi'] * 100:10.4f}% {a:>12}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#140 PDM + #141 TUB — advisory, read-only")
    ap.add_argument("--panel-dir", default=None,
                    help="panel root; the real panel is runtime state and lives only in the "
                         "production tree, so from a worktree this must be given explicitly")
    ap.add_argument("--lookback", type=int, default=TUB_LOOKBACK)
    ap.add_argument("--alpha", type=float, default=TUB_ALPHA)
    ap.add_argument("--json", action="store_true", help="dump the report as JSON to stdout")
    args = ap.parse_args(argv)
    try:
        rep = pdm_report(Path(args.panel_dir) if args.panel_dir else None,
                         lookback=args.lookback, alpha=args.alpha)
    except RuntimeError as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        slim = dict(rep)
        slim["panel"] = {k: v for k, v in rep["panel"].items() if k != "axis"}
        print(json.dumps(slim, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
