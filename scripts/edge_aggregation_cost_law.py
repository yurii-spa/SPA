#!/usr/bin/env python3
"""
scripts/edge_aggregation_cost_law.py — Ideas #73 (ACL) and #74 (ACL-EX)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads the aggressive-lab panel READ-ONLY.


WHY THIS RUN EXISTS — THE ORDER #71 LEFT, VERBATIM
--------------------------------------------------
Registry #71 (PDE-REAL) closed with one concrete next step, and it is the only transferable
part of its finding §3:

    "проверить, на каком уровне агрегации возвратность внутри полосы появляется
     (книга → пара → квартет → панель). Если порог виден, у реестра появляется правило
     «до какого размера корзины непрерывный сайзер вообще допустим», годное и за пределами PDE."

#71 measured only the two ENDS of that ladder (per-book = 8.6–71.7 bp/yr, whole panel =
513–812 bp/yr) and inferred a 7–60× multiplier from two points. Two points do not distinguish
"cost grows smoothly with basket size" from "cost is flat until the basket is big enough to
average its books into a mean-reverting series, then jumps". Those are different laws and they
imply different engineering rules, so this run fills the ladder in.

#72 already killed the obvious repair (a rebalance deadband loses to a random schedule of the
same trade count, 20/20 seeds on five rungs of six). So this is not another attempt to rescue
PDE. It is an attempt to extract the ONE rule the failure is evidence for.


IDEA #73 — ACL: is there an aggregation level at which a continuous sizer stops paying?
  The SAME wedge (#70's `_pde_exposure`, imported unchanged) is wired at four aggregation
  levels over the SAME 10 books and the SAME days. Only the level changes:

      n=1  → 10 groups of 1 book   (this is #71's per-book arm, exactly)
      n=2  →  5 groups of 2 books  (NEW)
      n=5  →  2 groups of 5 books  (NEW)
      n=10 →  1 group of 10 books  (this is #71's portfolio arm, exactly)

  Total capital is identical at every rung (disjoint groups, equal weight), so the ladder is a
  clean one-variable sweep and its two ends are anchored by numbers already in the registry —
  the parity is asserted by test, in both directions.

  Groups are drawn at RANDOM (20 seeds, median and min/max reported), because a hand-picked
  partition at n=2 or n=5 would be a choice this run must not be allowed to make. One CAUSAL
  partition — books ordered by their TRAIN correlation to the panel, then chunked — is run as
  a SEPARATE, LABELLED arm, never mixed into the random ladder.

  The mechanism is measured directly, not inferred from the outcome: for every group series,
  the fraction of days its drawdown sits INSIDE the wedge (d_start, d_full) and the number of
  times it ENTERS that interior per year. "Возвратность внутри полосы" is exactly that entry
  count, and #71 asserted it without ever counting it.

IDEA #74 — ACL-EX: can the bill be read off the raw series BEFORE anything is wired?
  Every one of the 72 registry entries learned what a continuous sizer costs by RUNNING it.
  That is a strange way to find out, because the wedge is a deterministic function of the
  drawdown path: replay the wedge over the RAW (un-overlaid) series and you get an ex-ante
  turnover estimate for free, with no overlay, no cost model and no P&L.

  The estimate is a PROXY and the gap is named up front: the live overlay watches the drawdown
  of the GUARDED equity, not the raw one. Two effects push in OPPOSITE directions and neither
  dominates a priori — cutting exposure makes the guarded drawdown shallower (less wedge
  motion, proxy reads HIGH), but it also makes the guarded equity fall more slowly, so it can
  linger inside the band for longer (more wedge motion, proxy reads LOW). Which effect wins is
  a property of the series, and this run measures it instead of assuming a sign.

  Evaluated three ways, on TEST, out of sample from a TRAIN-picked threshold:
    (1) rank agreement (Spearman) between ex-ante turnover and realized turnover;
    (2) the ratio realized/ex-ante — is it stable enough to correct for;
    (3) a DECISION rule: threshold on ex-ante cost picked on TRAIN, applied to TEST, scored
        against the truth "did the overlay actually beat raw net of cost on TEST".

  THE CONTROL THAT DECIDES IT: basket size `n` alone is a competing predictor and it is free.
  If ex-ante turnover does not beat plain `n` at ranking realized cost, then #73's law is the
  whole story and #74 adds nothing — and that is the verdict that gets written, not buried.

HONEST LIMITS DECLARED UP FRONT
  • evidence L0 — backtest on an advisory paper panel, numbers marked [bt], never realized;
  • the panel's own books are themselves backtests (harness.py over real deep-history feeds),
    so this measures a rule on a real return SHAPE, not a realized P&L;
  • the phase="backtest" block only — the forward block re-anchors at ~$100k and diffing across
    that seam fabricates returns of −31%/−84%/+105% (fixed 2026-08-02, reused loader);
  • four TRAIN/TEST splits, not one; the registry-canonical split (2025-06-30) is printed first;
  • 10 books admit exact partitions only for n ∈ {1,2,5,10}; "квартет" from #71's phrasing is
    not a divisor of 10 and is NOT silently approximated — the ladder says so out loud;
  • no parameter is tuned on TEST. The wedge grid is #70's grid verbatim; the only new knob is
    the aggregation level, and it is swept exhaustively rather than chosen.

stdlib-only, deterministic (seeded RNG), LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_pde_real_panel as PRP  # noqa: E402  #71/#72 harness: loader, splits, overlay engine
import edge_proportional_drawdown_exit as PDE  # noqa: E402  #70 mechanism, imported unchanged

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
#: The panel is NOT git-tracked. A session working from a worktree has an empty data/ and must
#: point at the prod tree's copy (read-only). #70 hit exactly this and silently fell back to a
#: fixture; #71 recorded it. Same override, same reason.
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

INITIAL = PRP.INITIAL
ROUNDTRIP = PRP.ROUNDTRIP  # 0.0096 — canonical #10/#49, inherited from #70 rather than restated

#: Aggregation levels. Only exact divisors of the panel size are admissible (see LEVELS_FOR).
LADDER: Tuple[int, ...] = (1, 2, 5, 10)
#: #70's grid verbatim. (0.02, 0.06) is the configuration #70's headline positive was published
#: on, so it leads: dropping it would mean not testing the claim actually made.
PDE_GRID: Tuple[Tuple[float, float], ...] = ((0.02, 0.06), (0.01, 0.06), (0.02, 0.08), (0.03, 0.10))
CANON_GRID = PDE_GRID[0]
SPLITS: Tuple[str, ...] = PRP.SPLITS
PART_SEEDS = 20


# ─────────────────────────── partitions ───────────────────────────

def levels_for(n_books: int, ladder: Sequence[int] = LADDER) -> List[int]:
    """The rungs that divide the panel exactly.

    Fail-CLOSED on purpose. A level that does not divide the panel would have to be realised as
    ragged groups (e.g. 4+4+2 for "квартет" on 10 books), and then the rung would be confounded
    by group-size DISPERSION on top of group SIZE — two variables under one column header. #71
    asked for "книга → пара → квартет → панель"; the quartet is not a divisor of 10 and this
    function drops it rather than approximate it silently.
    """
    return [n for n in ladder if n >= 1 and n_books % n == 0]


def random_partition(names: Sequence[str], n: int, seed: int) -> List[List[str]]:
    """Shuffle, then chunk into disjoint groups of exactly `n`.

    Returns groups sorted internally and by first member, so the same seed yields the same
    partition on any machine and the printed tables are diffable.
    """
    names = list(names)
    if n < 1 or len(names) % n != 0:
        raise ValueError(f"level {n} does not divide a panel of {len(names)} books — refusing")
    order = list(names)
    random.Random(seed).shuffle(order)
    groups = [sorted(order[i:i + n]) for i in range(0, len(order), n)]
    return sorted(groups, key=lambda g: g[0])


def causal_partition(names: Sequence[str], n: int, train_books: Dict[str, List[float]]) -> List[List[str]]:
    """Books ordered by TRAIN correlation to the equal-weight panel, then chunked.

    This is the "smart grouping" arm: if a mid-level rung ever wins, the first suspicion is that
    it won because SOME grouping is favourable, not because the level is. Ordering by beta-like
    co-movement puts the mean-reverting books together and the idiosyncratic ones together,
    which is the grouping most likely to help — so if even this does not beat the random median,
    the level really is the variable.

    Built on TRAIN ONLY. Nothing here is allowed to see the TEST window.
    """
    names = list(names)
    if n < 1 or len(names) % n != 0:
        raise ValueError(f"level {n} does not divide a panel of {len(names)} books — refusing")
    panel_ret = PRP.portfolio_returns(train_books)
    scored: List[Tuple[float, str]] = []
    for b in sorted(names):
        eq = train_books[b]
        rets = [(eq[i] / eq[i - 1] - 1.0) if eq[i - 1] > 0 else 0.0 for i in range(1, len(eq))]
        scored.append((_pearson(rets, panel_ret), b))
    scored.sort()
    order = [b for _, b in scored]
    groups = [sorted(order[i:i + n]) for i in range(0, len(order), n)]
    return sorted(groups, key=lambda g: g[0])


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation; 0.0 on a degenerate (zero-variance) leg rather than ZeroDivision.

    A flat book is not "uncorrelated with everything" as a matter of fact — it is a case where
    correlation is undefined. Returning 0.0 places it in the middle of the causal ordering,
    which is the least opinionated placement available, and the ladder never depends on it.
    """
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    va = sum((x - ma) ** 2 for x in a[:n])
    vb = sum((x - mb) ** 2 for x in b[:n])
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (va ** 0.5 * vb ** 0.5)


# ─────────────────────────── grouped overlay ───────────────────────────

def group_equity(books: Dict[str, List[float]], group: Sequence[str]) -> List[float]:
    """Equal-weight equity series of one group, rebased to $100k.

    A group of one is that book verbatim (asserted by test): the n=1 rung must BE #71's
    per-book arm, not merely resemble it.
    """
    missing = [b for b in group if b not in books]
    if missing:
        raise ValueError(f"group {list(group)} names {missing} absent from the panel — refusing")
    sub = {b: books[b] for b in group}
    if len(sub) != len(group):
        raise ValueError(f"group {list(group)} repeats a book — refusing")
    if len(sub) == 1:
        return list(next(iter(sub.values())))
    return PRP.equity_from_returns(PRP.portfolio_returns(sub))


def grouped_overlay(books: Dict[str, List[float]], groups: Sequence[Sequence[str]], fn
                    ) -> Tuple[List[float], float, float]:
    """Run `fn` on each group's series, then equal-weight the guarded groups.

    Returns (panel_equity, cost, turnover) with cost and turnover expressed per $100k of PANEL
    capital — i.e. each group's bill is scaled by its capital share 1/len(groups). That is
    exactly #71's `per_book_overlay` convention (`total_cost += cost / len(names)`), inherited
    rather than restated so the two ends of the ladder stay column-comparable with #71's table.

    Fail-CLOSED on a partition that is not a partition: overlapping or incomplete groups would
    silently re-weight the panel and every number below would be about a different portfolio.
    """
    groups = [list(g) for g in groups]
    flat = [b for g in groups for b in g]
    if sorted(flat) != sorted(books):
        raise ValueError(
            f"groups are not a partition of the panel: {len(flat)} slots over "
            f"{len(set(flat))} distinct books vs {len(books)} books — refusing"
        )
    sizes = {len(g) for g in groups}
    if len(sizes) != 1:
        raise ValueError(f"ragged partition {sorted(sizes)} — refusing to call that a level")
    guarded: Dict[str, List[float]] = {}
    total_cost = 0.0
    total_turn = 0.0
    for g in groups:
        res = fn(group_equity(books, g))
        eq, cost = res[0], res[1]
        turn = res[2] if len(res) > 2 else 0.0
        guarded["|".join(g)] = eq
        total_cost += cost / len(groups)
        total_turn += turn / len(groups)
    return PRP.equity_from_returns(PRP.portfolio_returns(guarded)), total_cost, total_turn


# ─────────────────────────── #73: mechanism metrics ───────────────────────────

class WedgeStats(NamedTuple):
    """What the wedge would SEE on a series, computed without running the wedge.

    `band_frac`   fraction of days whose drawdown sits strictly inside (d_start, d_full)
    `entries_yr`  times per year the drawdown ENTERS that interior from outside — this is the
                  "возвратность внутри полосы" #71 asserted and never counted
    `turn_yr`     turnover the wedge would pay if it followed THIS series (the #74 estimate)
    """
    band_frac: float
    entries_yr: float
    turn_yr: float


def drawdown_path(eq: Sequence[float]) -> List[float]:
    """Trailing drawdown from the running peak, one value per point (0.0 at the first)."""
    out: List[float] = []
    peak = eq[0] if eq else 0.0
    for v in eq:
        peak = max(peak, v)
        out.append((peak - v) / peak if peak > 0 else 0.0)
    return out


def wedge_stats(eq: Sequence[float], *, d_start: float, d_full: float) -> WedgeStats:
    """Ex-ante wedge statistics of a RAW series — no overlay, no cost model, no P&L.

    `turn_yr` replays #70's `_pde_exposure` over the raw drawdown path and sums |Δexposure|.
    It is deliberately a PROXY, and its bias has NO FIXED SIGN: on a series that crashes once it
    matches the realized turnover almost exactly (ratio 1.00), on a series that oscillates
    through the band it UNDER-reads (ratio ~1.54, because a cut exposure lingers in the band
    longer), and on the real panel it OVER-reads (median ratio 0.28 TRAIN / 0.47 TEST). A proxy
    whose error changes direction with the shape of the input cannot be fixed with a constant,
    and that — not the rank correlation — is what decides #74. Nothing here is allowed to
    pretend the proxy is the thing.
    """
    eq = list(eq)
    if len(eq) < 2:
        return WedgeStats(0.0, 0.0, 0.0)
    dd = drawdown_path(eq)
    years = max((len(eq) - 1) / 365.0, 1e-9)
    inside = [d_start < d < d_full for d in dd]
    entries = sum(1 for i in range(1, len(dd)) if inside[i] and not inside[i - 1])
    turn = 0.0
    prev = PDE._pde_exposure(dd[0], d_start, d_full)
    for i in range(1, len(dd)):
        cur = PDE._pde_exposure(dd[i], d_start, d_full)
        turn += abs(cur - prev)
        prev = cur
    return WedgeStats(sum(inside) / len(dd), entries / years, turn / years)


def panel_wedge_stats(books: Dict[str, List[float]], groups: Sequence[Sequence[str]],
                      *, d_start: float, d_full: float) -> WedgeStats:
    """Capital-weighted mean of the group-level ex-ante stats (same 1/len(groups) convention)."""
    groups = [list(g) for g in groups]
    stats = [wedge_stats(group_equity(books, g), d_start=d_start, d_full=d_full) for g in groups]
    k = len(stats)
    return WedgeStats(
        sum(s.band_frac for s in stats) / k,
        sum(s.entries_yr for s in stats) / k,
        sum(s.turn_yr for s in stats) / k,
    )


# ─────────────────────────── ladder runner ───────────────────────────

class Rung(NamedTuple):
    level: int
    label: str
    apy: float
    maxdd: float
    calmar: float
    net_apy: float
    cost_bp_yr: float
    turn_yr: float
    band_frac: float
    entries_yr: float
    ex_turn_yr: float


def _pde_fn(d_start: float, d_full: float, roundtrip: float):
    def fn(raw: Sequence[float]):
        return PRP.apply_pde_deadband(raw, d_start=d_start, d_full=d_full, band=0.0,
                                      roundtrip=roundtrip)
    return fn


def run_rung(books: Dict[str, List[float]], groups: Sequence[Sequence[str]], *,
             d_start: float, d_full: float, roundtrip: float = ROUNDTRIP,
             label: str = "") -> Rung:
    """One (partition, wedge) pair: outcome metrics AND the ex-ante mechanism metrics."""
    eq, cost, turn = grouped_overlay(books, groups, _pde_fn(d_start, d_full, roundtrip))
    n_days = len(eq) - 1
    m = PRP.metrics(eq, cost, n_days, turn)
    ws = panel_wedge_stats(books, groups, d_start=d_start, d_full=d_full)
    return Rung(len(groups[0]), label, m["apy"], m["maxdd"], m["calmar"], m["net_apy_flat"],
                m["cost_bp_yr"], m["turn_yr"], ws.band_frac, ws.entries_yr, ws.turn_yr)


def baseline_rows(books: Dict[str, List[float]], *, roundtrip: float = ROUNDTRIP
                  ) -> Dict[str, Dict[str, float]]:
    """raw equal-weight panel and #70's binary guardian per book — the two rules already known.

    The binary guardian is not decoration: it is the rule ALREADY DEPLOYED in the swarm, so
    "the wedge beats raw" is not the bar. The bar is "the wedge beats what is running".
    """
    names = sorted(books)
    raw_eq = PRP.equity_from_returns(PRP.portfolio_returns(books))
    n_days = len(raw_eq) - 1
    out = {"raw равновес": PRP.metrics(raw_eq, 0.0, n_days, 0.0)}
    bin_eq, bin_cost, _ = PRP.per_book_overlay(
        books, lambda raw: PDE.apply_binary_guardian(list(raw), roundtrip=roundtrip))
    bin_turn = sum(PRP._binary_turnover(books[b]) for b in names) / len(names)
    out["binary per-book"] = PRP.metrics(bin_eq, bin_cost, len(bin_eq) - 1, bin_turn)
    return out


def run_ladder(books: Dict[str, List[float]], train_books: Dict[str, List[float]], *,
               d_start: float = CANON_GRID[0], d_full: float = CANON_GRID[1],
               seeds: int = PART_SEEDS, roundtrip: float = ROUNDTRIP,
               ) -> Dict[int, Dict[str, object]]:
    """The #73 ladder: every admissible level, `seeds` random partitions plus the causal one.

    n=1 and n=10 have exactly ONE partition each, so seeding them would print twenty identical
    rows and dress a constant up as a distribution. They are run once and labelled `unique`.
    """
    names = sorted(books)
    out: Dict[int, Dict[str, object]] = {}
    for n in levels_for(len(names)):
        unique = (n == 1 or n == len(names))
        seed_list = [0] if unique else list(range(seeds))
        rungs = [run_rung(books, random_partition(names, n, s), d_start=d_start, d_full=d_full,
                          roundtrip=roundtrip, label=f"seed{s}")
                 for s in seed_list]
        causal = run_rung(books, causal_partition(names, n, train_books), d_start=d_start,
                          d_full=d_full, roundtrip=roundtrip, label="causal")
        out[n] = {"unique": unique, "rungs": rungs, "causal": causal}
    return out


# ─────────────────────────── #74: ex-ante predictor ───────────────────────────

def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation. Ties get average ranks; a degenerate leg returns 0.0, not a crash."""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0

    def ranks(v: Sequence[float]) -> List[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(xs[:n]), ranks(ys[:n])
    ma, mb = sum(ra) / n, sum(rb) / n
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((x - mb) ** 2 for x in rb)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((ra[i] - ma) * (rb[i] - mb) for i in range(n)) / (va ** 0.5 * vb ** 0.5)


class Observation(NamedTuple):
    """One (split, level, partition) cell: what could be known ex ante, what actually happened."""
    split: str
    level: int
    ex_turn_yr: float      # #74 predictor: wedge turnover replayed on the RAW series
    entries_yr: float      # #73 mechanism: band entries per year on the RAW series
    turn_yr: float         # realized turnover of the overlay
    cost_bp_yr: float      # realized bill
    net_apy: float         # overlay, net of cost
    raw_net_apy: float     # doing nothing
    beats_raw: bool        # the truth a pre-flight check would want to predict


def collect_observations(axis: Sequence[str], books: Dict[str, List[float]], *,
                         d_start: float = CANON_GRID[0], d_full: float = CANON_GRID[1],
                         seeds: int = PART_SEEDS, window: str = "test",
                         roundtrip: float = ROUNDTRIP) -> List[Observation]:
    """Every ladder cell across all four splits, on TRAIN or on TEST.

    `window` selects which side of each split is measured. #74's threshold is picked on
    window="train" and scored on window="test"; the two calls share this one code path so the
    two sides cannot drift into answering different questions.
    """
    if window not in ("train", "test"):
        raise ValueError(f"window must be 'train' or 'test', got {window!r}")
    obs: List[Observation] = []
    for split in SPLITS:
        if window == "train":
            _, win = PRP.slice_books(axis, books, None, split)
        else:
            _, win = PRP.slice_books(axis, books, split, None)
        names = sorted(win)
        raw_eq = PRP.equity_from_returns(PRP.portfolio_returns(win))
        raw_net = PRP.metrics(raw_eq, 0.0, len(raw_eq) - 1, 0.0)["net_apy_flat"]
        for n in levels_for(len(names)):
            unique = (n == 1 or n == len(names))
            for s in ([0] if unique else range(seeds)):
                groups = random_partition(names, n, s)
                r = run_rung(win, groups, d_start=d_start, d_full=d_full, roundtrip=roundtrip)
                obs.append(Observation(split, n, r.ex_turn_yr, r.entries_yr, r.turn_yr,
                                       r.cost_bp_yr, r.net_apy, raw_net, r.net_apy > raw_net))
    return obs


def pick_threshold(train: Sequence[Observation]) -> float:
    """Ex-ante turnover threshold that best separates "wedge beat raw" on TRAIN.

    Chosen by maximising balanced accuracy over the observed values as candidate cuts. Ties go
    to the LOWER cut, i.e. to refusing more often: this is a pre-flight check whose false
    negative ("wire it, then lose 12% a year" — #71's worst cell) costs more than its false
    positive ("skip a rule that would have worked"). Fail-CLOSED, and the tie-break is stated
    rather than left to sort order.
    """
    if not train:
        return 0.0
    cands = sorted({o.ex_turn_yr for o in train})
    best, best_score = cands[0], -1.0
    for c in cands:
        tp = sum(1 for o in train if o.ex_turn_yr <= c and o.beats_raw)
        fn_ = sum(1 for o in train if o.ex_turn_yr > c and o.beats_raw)
        tn = sum(1 for o in train if o.ex_turn_yr > c and not o.beats_raw)
        fp = sum(1 for o in train if o.ex_turn_yr <= c and not o.beats_raw)
        sens = tp / (tp + fn_) if (tp + fn_) else 0.0
        spec = tn / (tn + fp) if (tn + fp) else 0.0
        score = (sens + spec) / 2.0
        if score > best_score + 1e-12:
            best, best_score = c, score
    return best


def score_threshold(test: Sequence[Observation], thr: float) -> Dict[str, float]:
    """Confusion matrix of "predict admissible iff ex-ante turnover <= thr", on TEST."""
    tp = sum(1 for o in test if o.ex_turn_yr <= thr and o.beats_raw)
    fp = sum(1 for o in test if o.ex_turn_yr <= thr and not o.beats_raw)
    fn_ = sum(1 for o in test if o.ex_turn_yr > thr and o.beats_raw)
    tn = sum(1 for o in test if o.ex_turn_yr > thr and not o.beats_raw)
    n = max(tp + fp + fn_ + tn, 1)
    sens = tp / (tp + fn_) if (tp + fn_) else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn_, "tn": tn, "acc": (tp + tn) / n,
            "sens": sens, "spec": spec, "bal_acc": (sens + spec) / 2.0}


def predictor_contest(obs: Sequence[Observation]) -> Dict[str, float]:
    """#74's decisive control: does the ex-ante statistic beat plain basket size?

    Both are ranked against the SAME truth (realized cost). If `n` alone ranks as well, the
    honest verdict is that #73's law is the whole content and #74's statistic is redundant.
    """
    cost = [o.cost_bp_yr for o in obs]
    return {
        "rho_exante_cost": spearman([o.ex_turn_yr for o in obs], cost),
        "rho_entries_cost": spearman([o.entries_yr for o in obs], cost),
        "rho_level_cost": spearman([float(o.level) for o in obs], cost),
        "rho_exante_turn": spearman([o.ex_turn_yr for o in obs], [o.turn_yr for o in obs]),
    }


def ratio_stats(obs: Sequence[Observation]) -> Dict[str, float]:
    """realized / ex-ante turnover — the proxy's calibration, reported not assumed."""
    rs = [o.turn_yr / o.ex_turn_yr for o in obs if o.ex_turn_yr > 1e-9]
    if not rs:
        return {"n": 0, "median": 0.0, "lo": 0.0, "hi": 0.0}
    rs.sort()
    return {"n": len(rs), "median": rs[len(rs) // 2], "lo": rs[0], "hi": rs[-1]}


# ─────────────────────────── reporting ───────────────────────────

def _med(vals: Sequence[float]) -> float:
    v = sorted(vals)
    return v[len(v) // 2] if v else 0.0


def _print_ladder(title: str, ladder: Dict[int, Dict[str, object]],
                  baselines: Dict[str, Dict[str, float]]) -> None:
    print(f"\n{title}")
    print(f"{'уровень':<22}{'APY':>9}{'maxDD':>9}{'Calmar':>9}{'netAPY':>10}"
          f"{'бп/год':>10}{'turn':>8}{'в полосе':>10}{'входов/г':>10}")
    for name, m in baselines.items():
        print(f"{name:<22}{m['apy']*100:>8.2f}%{m['maxdd']*100:>8.2f}%{m['calmar']:>9.2f}"
              f"{m['net_apy_flat']*100:>9.2f}%{m['cost_bp_yr']:>10.1f}{m['turn_yr']:>8.2f}"
              f"{'—':>10}{'—':>10}")
    for n in sorted(ladder):
        cell = ladder[n]
        rungs: List[Rung] = cell["rungs"]  # type: ignore[assignment]
        label = f"n={n} ({'уникальна' if cell['unique'] else f'медиана {len(rungs)} сидов'})"
        print(f"{label:<22}{_med([r.apy for r in rungs])*100:>8.2f}%"
              f"{_med([r.maxdd for r in rungs])*100:>8.2f}%"
              f"{_med([r.calmar for r in rungs]):>9.2f}"
              f"{_med([r.net_apy for r in rungs])*100:>9.2f}%"
              f"{_med([r.cost_bp_yr for r in rungs]):>10.1f}"
              f"{_med([r.turn_yr for r in rungs]):>8.2f}"
              f"{_med([r.band_frac for r in rungs])*100:>9.1f}%"
              f"{_med([r.entries_yr for r in rungs]):>10.1f}")
        if not cell["unique"]:
            print(f"{'  разброс netAPY':<22}"
                  f"{min(r.net_apy for r in rungs)*100:>8.2f}% … "
                  f"{max(r.net_apy for r in rungs)*100:.2f}%   "
                  f"бп/год {min(r.cost_bp_yr for r in rungs):.0f} … "
                  f"{max(r.cost_bp_yr for r in rungs):.0f}")
            c: Rung = cell["causal"]  # type: ignore[assignment]
            print(f"{'  causal (TRAIN-corr)':<22}{c.apy*100:>8.2f}%{c.maxdd*100:>8.2f}%"
                  f"{c.calmar:>9.2f}{c.net_apy*100:>9.2f}%{c.cost_bp_yr:>10.1f}{c.turn_yr:>8.2f}"
                  f"{c.band_frac*100:>9.1f}%{c.entries_yr:>10.1f}")


# ─────────────────────────── #73 control: is the LAW about one book? ───────────────────────────

def subsets(names: Sequence[str], k: int) -> List[List[str]]:
    """All k-subsets, deterministic order. Exhaustive beats sampled here: there are few of them."""
    names = sorted(names)
    out: List[List[str]] = []

    def rec(start: int, acc: List[str]) -> None:
        if len(acc) == k:
            out.append(list(acc))
            return
        for i in range(start, len(names)):
            acc.append(names[i])
            rec(i + 1, acc)
            acc.pop()

    rec(0, [])
    return out


def one_book_control(books: Dict[str, List[float]], *, culprit: str = "eth_directional",
                     d_start: float = CANON_GRID[0], d_full: float = CANON_GRID[1],
                     seeds: int = 5, roundtrip: float = ROUNDTRIP,
                     ) -> Dict[str, Dict[int, Dict[str, float]]]:
    """The ladder rebuilt on EIGHT-book sub-panels, with and without one named book.

    TWO jobs in one pass, and neither is decoration:

    (1) THE QUARTET. #71 asked for "книга → пара → квартет → панель"; 4 does not divide 10, so
        the main ladder had to drop it. It divides 8. Running the sub-panel ladder at
        {1, 2, 4, 8} delivers the rung the order actually named.

    (2) THE ONE-BOOK CONTROL. #68 (list composition), #69 (knob k) and #71 (overlay shape) each
        ended the same way: the advantage was a statement about `eth_directional`, not about the
        rule. A LAW about aggregation levels must not have that shape. Arm A is every 8-subset
        that CONTAINS the book (C(9,2)=36); arm B is every 8-subset that EXCLUDES it (C(9,8)=9).
        Exhaustive, so no subset was chosen. If arm B's ladder is flat while arm A's has a knee,
        the law is the one-book law wearing a new hat and it does NOT go in the registry as a law.
    """
    names = sorted(books)
    if culprit not in names:
        raise ValueError(f"{culprit!r} is not on the panel — refusing a control against nothing")
    others = [b for b in names if b != culprit]
    arms = {
        "с eth_directional": [sorted(s + [culprit]) for s in subsets(others, 7)],
        "без eth_directional": subsets(others, 8),
    }
    out: Dict[str, Dict[int, Dict[str, float]]] = {}
    for arm, subs in arms.items():
        per_level: Dict[int, Dict[str, List[float]]] = {}
        for sub in subs:
            sub_books = {b: books[b] for b in sub}
            for n in levels_for(len(sub), (1, 2, 4, 8)):
                unique = (n == 1 or n == len(sub))
                for sd in ([0] if unique else range(seeds)):
                    r = run_rung(sub_books, random_partition(sub, n, sd), d_start=d_start,
                                 d_full=d_full, roundtrip=roundtrip)
                    slot = per_level.setdefault(n, {"band": [], "net": [], "cost": [], "ent": []})
                    slot["band"].append(r.band_frac)
                    slot["net"].append(r.net_apy)
                    slot["cost"].append(r.cost_bp_yr)
                    slot["ent"].append(r.entries_yr)
        out[arm] = {n: {k: _med(v) for k, v in slot.items()} | {"cells": float(len(slot["net"]))}
                    for n, slot in sorted(per_level.items())}
    return out


def substitutability_scan(books: Dict[str, List[float]], *, d_start: float = CANON_GRID[0],
                          d_full: float = CANON_GRID[1], roundtrip: float = ROUNDTRIP,
                          ) -> List[Tuple[str, float, float, float, float]]:
    """For EVERY book b: what does the aggregate wedge look like on 8-subsets that exclude b?

    The question #68/#69/#71 never asked. Each of them removed `eth_directional`, watched the
    edge vanish and concluded "one book". But "the edge needs THAT book" and "the edge needs A
    book of that kind" are different claims with different engineering consequences: the first
    says the finding is an accident of this panel, the second says it is a property of the book
    CLASS and would reappear on any panel carrying one. The scan removes each book in turn, so
    the answer is read off ten arms instead of asserted from one.

    Returns (book, own daily sd %, median band residency, median cost bp/yr, median netAPY)
    for the n=8 rung of the subsets that EXCLUDE that book. Sorted by band residency.
    """
    names = sorted(books)
    rows: List[Tuple[str, float, float, float, float]] = []
    for b in names:
        others = [x for x in names if x != b]
        band: List[float] = []
        cost: List[float] = []
        net: List[float] = []
        for sub in subsets(others, 8):
            sub_books = {x: books[x] for x in sub}
            r = run_rung(sub_books, [sorted(sub)], d_start=d_start, d_full=d_full,
                         roundtrip=roundtrip)
            band.append(r.band_frac)
            cost.append(r.cost_bp_yr)
            net.append(r.net_apy)
        eq = books[b]
        rets = [(eq[i] / eq[i - 1] - 1.0) if eq[i - 1] > 0 else 0.0 for i in range(1, len(eq))]
        mu = sum(rets) / len(rets) if rets else 0.0
        sd = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5 if rets else 0.0
        rows.append((b, sd * 100.0, _med(band), _med(cost), _med(net)))
    return sorted(rows, key=lambda t: -t[2])


# ─────────────────── panel liveness: what the one-book law actually IS ───────────────────

class Liveness(NamedTuple):
    book: str
    sd_pct: float          # own daily sd over the window, in percent
    moving_days: int       # days whose return is not exactly zero
    days: int
    killed_days: int       # days the LAB's own kill-switch had this book flat
    first_kill: str
    # ── added 2026-08-23 (cycle #353) ────────────────────────────────────────────────────
    # "мертва" and "мертва ПОЧЕМУ" are different measurements, and only the second one can
    # say whether a proposed repair reaches the book. Both fields below are counted over the
    # window AFTER the first kill, because that is the only stretch the repair has to fix.
    feedless_days_after_kill: int   # post-kill days whose row carries mtm_source=None
    fed_days_after_kill: int        # post-kill days whose row DOES carry a marked-to-market source
    rearms: int                     # killed → not-killed transitions anywhere in the window
    kill_mtm_pct: Optional[float]   # the move on the day of the first kill (None if unrecorded)


def panel_liveness(panel_dir: Path = PANEL_DIR, *, start: Optional[str] = None) -> List[Liveness]:
    """Which books on the panel are ALIVE, read from the same rows the loader reads.

    THIS FUNCTION EXISTS BECAUSE OF WHAT THE #73 CONTROL TURNED UP, and it is the most
    consequential thing in this file. `substitutability_scan` showed that removing
    `eth_directional` does not make the aggregate wedge cheaper — it makes it INERT (band
    residency 0.0%, cost 0.0 bp/yr). A ten-book average that cannot reach a 2% drawdown once a
    single book is removed is not a ten-book average. So: count them.

    The answer is that four books (`leverage_loop`, `levered_restaking`, `lp_eth_stable`,
    `lrt_neutral`) were KILLED by the lab's own kill-switch between 2024-03-06 and 2024-08-23
    and have been carried as FROZEN equity ever since — 682–851 killed days out of 852. They are
    not quiet books. They are dead books held at a flat line, and in an equal-weight panel they
    are 40% of the capital contributing exactly zero variance.

    That is the mechanical cause of the "закон одной книги" that #68 (list composition), #69
    (knob k) and #71 (overlay shape) each recorded as a property of RULES. It is not a property
    of rules. It is a property of THIS PANEL, and it is measurable in one pass.

    Read-only. Never writes to the panel.
    """
    rows_by_book: List[Liveness] = []
    for d in sorted(p for p in panel_dir.iterdir() if p.is_dir()):
        f = d / "realized_series.jsonl"
        if not f.exists():
            continue
        rows = RPE_backtest_rows(f)
        if start is not None:
            rows = [r for r in rows if str(r.get("date", "")) >= start]
        if len(rows) < 2:
            continue
        eq = [float(r["equity_usd"]) for r in rows]
        rets = [(eq[i] / eq[i - 1] - 1.0) if eq[i - 1] > 0 else 0.0 for i in range(1, len(eq))]
        mu = sum(rets) / len(rets)
        sd = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5
        kills = [str(r.get("date", "")) for r in rows if r.get("killed")]

        # Why the book is dead, not just that it is. A repair aimed at feeds only reaches the
        # book whose post-kill rows carry no mark-to-market source; a book whose feed kept
        # arriving the whole time is frozen by something else, and fixing feeds moves nothing.
        first_kill_idx = next((i for i, r in enumerate(rows) if r.get("killed")), None)
        if first_kill_idx is None:
            feedless = fed = 0
            kill_mtm = None
        else:
            tail = rows[first_kill_idx:]
            feedless = sum(1 for r in tail if r.get("mtm_source") is None)
            fed = len(tail) - feedless
            raw_mtm = rows[first_kill_idx].get("mtm_today_pct")
            kill_mtm = float(raw_mtm) if raw_mtm is not None else None
        rearms = sum(
            1 for i in range(1, len(rows))
            if rows[i - 1].get("killed") and not rows[i].get("killed")
        )

        rows_by_book.append(Liveness(
            d.name, sd * 100.0, sum(1 for r in rets if abs(r) > 1e-12), len(rets),
            len(kills), kills[0] if kills else "—",
            feedless, fed, rearms, kill_mtm))
    return sorted(rows_by_book, key=lambda l: -l.sd_pct)


def RPE_backtest_rows(path: Path) -> List[dict]:
    """The loader's own row reader + phase filter, reused so liveness cannot disagree with it.

    Using a second reader here would be the classic cross-guard blind spot: an audit that
    compares a COPY of the data to the data is green through any drift between them.
    """
    return PRP.RPE.backtest_block(PRP.RPE._read_rows(path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    seeds = PART_SEEDS
    if "--seeds" in argv:
        seeds = int(argv[argv.index("--seeds") + 1])

    print("=" * 100)
    print("ИДЕИ #73 (ACL) + #74 (ACL-EX) — ЗАКОН СТОИМОСТИ НЕПРЕРЫВНОГО САЙЗЕРА ПО УРОВНЮ АГРЕГАЦИИ")
    print("advisory / paper-only / OUTSIDE_RISKPOLICY · evidence L0 · все числа [bt]")
    print("=" * 100)

    axis, books = PRP.load_books(PANEL_DIR)
    print(f"\nпанель: {len(books)} книг, {len(axis)} общих дней {axis[0]}..{axis[-1]}")
    print(f"допустимые уровни (делители {len(books)}): {levels_for(len(books))}"
          f"  ·  «квартет» из заказа #71 не делит 10 и НЕ приближается молча")
    print(f"клин: d_start={CANON_GRID[0]:.0%}, d_full={CANON_GRID[1]:.0%} (публикация #70), "
          f"roundtrip={ROUNDTRIP*10000:.0f} бп")

    # ── #73: the ladder, per split ────────────────────────────────────────────
    for split in SPLITS:
        _, train = PRP.slice_books(axis, books, None, split)
        _, test = PRP.slice_books(axis, books, split, None)
        ladder = run_ladder(test, train, seeds=seeds)
        _print_ladder(f"#73 ЛЕСТНИЦА АГРЕГАЦИИ — TEST после {split} ({len(test['susde_dn'])-1} дней) [bt]",
                      ladder, baseline_rows(test))

    # ── #73: grid robustness on the canonical split ───────────────────────────
    _, train = PRP.slice_books(axis, books, None, SPLITS[0])
    _, test = PRP.slice_books(axis, books, SPLITS[0], None)
    print(f"\n#73 УСТОЙЧИВОСТЬ ПО СЕТКЕ КЛИНА — TEST после {SPLITS[0]}, медиана {seeds} сидов [bt]")
    print(f"{'клин':<14}" + "".join(f"{'n='+str(n):>26}" for n in levels_for(len(books))))
    for ds, df in PDE_GRID:
        row = f"{ds:.0%}-{df:.0%}".ljust(14)
        lad = run_ladder(test, train, d_start=ds, d_full=df, seeds=seeds)
        for n in levels_for(len(books)):
            rr: List[Rung] = lad[n]["rungs"]  # type: ignore[assignment]
            row += f"{_med([r.net_apy for r in rr])*100:>12.2f}% / {_med([r.cost_bp_yr for r in rr]):>7.0f}бп"
        print(row)

    # ── #73 control: eight-book sub-panels, with and without eth_directional ──
    ctrl = one_book_control(test, seeds=5)
    print(f"\n#73 КОНТРОЛЬ «ЗАКОН ОДНОЙ КНИГИ» — под-панели по 8 книг, TEST после {SPLITS[0]}, "
          f"уровни 1/2/4/8 (КВАРТЕТ из заказа #71 делит 8) [bt]")
    print(f"{'арм':<24}{'уровень':>9}{'ячеек':>8}{'netAPY':>10}{'бп/год':>10}{'в полосе':>10}{'входов/г':>10}")
    for arm, lad in ctrl.items():
        for n, m in lad.items():
            print(f"{arm:<24}{('n='+str(n)):>9}{m['cells']:>8.0f}{m['net']*100:>9.2f}%"
                  f"{m['cost']:>10.1f}{m['band']*100:>9.1f}%{m['ent']:>10.1f}")

    print(f"\n#73 ЧЬЯ ЭТО КНИГА — или любой такой хватит? под-панели по 8 книг БЕЗ каждой книги "
          f"по очереди, рунг n=8, TEST после {SPLITS[0]} [bt]")
    print(f"{'выброшена':<22}{'её sd/день':>12}{'в полосе':>11}{'бп/год':>10}{'netAPY':>10}")
    for b, sd, band, cost, net in substitutability_scan(test):
        print(f"{b:<22}{sd:>11.3f}%{band*100:>10.1f}%{cost:>10.1f}{net*100:>9.2f}%")

    print(f"\n#73 ЖИВОСТЬ ПАНЕЛИ — что «закон одной книги» ЕСТЬ на самом деле "
          f"(блок phase=backtest целиком) [bt]")
    print(f"{'книга':<22}{'sd/день':>10}{'двигалась':>11}{'дней':>7}{'убита дней':>12}{'первый kill':>14}")
    live = panel_liveness()
    for l in live:
        print(f"{l.book:<22}{l.sd_pct:>9.3f}%{l.moving_days:>11}{l.days:>7}"
              f"{l.killed_days:>12}{l.first_kill:>14}")
    dead = [l for l in live if l.killed_days > l.days * 0.5]
    print(f"⇒ книг, убитых собственным kill-switch лаборатории и с тех пор замороженных: "
          f"{len(dead)} из {len(live)} — это {len(dead)/max(len(live),1)*100:.0f}% капитала "
          f"равновесной панели, дающих РОВНО НОЛЬ дисперсии")

    # ── ПОЧЕМУ мертва, и достаёт ли до неё принятая починка (добавлено циклом #353) ──────
    # Решение владельца по own-54 (19.08, вариант 1) — «починить фиды». Оно достаёт ровно до
    # той книги, у которой после kill'а фида НЕТ. У книги, которой фид приходил все дни,
    # причина заморозки другая, и починка фидов не сдвинет её ни на день. Считаем, а не
    # предполагаем.
    print(f"\n#73 ПОЧЕМУ КНИГА МЕРТВА — фид или настоящая просадка (дни ПОСЛЕ первого kill'а) [bt]")
    print(f"{'книга':<22}{'ход в день kill':>17}{'без фида':>10}{'с фидом':>9}"
          f"{'возвратов':>11}  причина")
    for l in dead:
        cause = ("фид пропал" if l.fed_days_after_kill == 0
                 else "настоящая просадка, фид ЖИВ" if l.feedless_days_after_kill == 0
                 else "смешанная — обе стороны есть")
        mtm = "не записан" if l.kill_mtm_pct is None else f"{l.kill_mtm_pct:.2f}%"
        print(f"{l.book:<22}{mtm:>17}{l.feedless_days_after_kill:>10}"
              f"{l.fed_days_after_kill:>9}{l.rearms:>11}  {cause}")
    feed_reachable = [l for l in dead if l.fed_days_after_kill == 0]
    never_rearmed = [l for l in dead if l.rearms == 0]
    print(f"⇒ починка фидов (решение владельца own-54, вариант 1) достаёт до "
          f"{len(feed_reachable)} из {len(dead)} мёртвых книг: "
          f"{', '.join(l.book for l in feed_reachable) or '—'}")
    print(f"⇒ вернулись в строй после kill'а: {len(dead) - len(never_rearmed)} из {len(dead)} — "
          f"у лабораторного kill-switch НЕТ политики возврата, поэтому даже книга с "
          f"починенным фидом останется замороженной")

    # ── #74: ex-ante predictor, TRAIN → TEST ──────────────────────────────────
    print("\n" + "=" * 100)
    print("#74 ACL-EX — МОЖНО ЛИ УЗНАТЬ СЧЁТ ДО ТОГО, КАК ЧТО-ТО ПОДКЛЮЧЕНО")
    print("=" * 100)
    tr_obs = collect_observations(axis, books, seeds=seeds, window="train")
    te_obs = collect_observations(axis, books, seeds=seeds, window="test")
    print(f"наблюдений: TRAIN {len(tr_obs)} · TEST {len(te_obs)} (4 сплита × уровни × партиции)")

    con_tr = predictor_contest(tr_obs)
    con_te = predictor_contest(te_obs)
    print(f"\n{'ранговая связь (Spearman)':<42}{'TRAIN':>10}{'TEST':>10}")
    for key, name in (("rho_exante_cost", "ex-ante оборот  →  реальный счёт"),
                      ("rho_entries_cost", "входов в полосу →  реальный счёт"),
                      ("rho_level_cost", "КОНТРОЛЬ: размер корзины n → счёт"),
                      ("rho_exante_turn", "ex-ante оборот  →  реальный оборот")):
        print(f"{name:<42}{con_tr[key]:>10.3f}{con_te[key]:>10.3f}")

    rt, re_ = ratio_stats(tr_obs), ratio_stats(te_obs)
    print(f"\nкалибровка прокси (реальный / ex-ante оборот):")
    print(f"  TRAIN медиана {rt['median']:.3f}  вилка {rt['lo']:.3f}…{rt['hi']:.3f}  (n={rt['n']})")
    print(f"  TEST  медиана {re_['median']:.3f}  вилка {re_['lo']:.3f}…{re_['hi']:.3f}  (n={re_['n']})")

    thr = pick_threshold(tr_obs)
    sc_tr = score_threshold(tr_obs, thr)
    sc_te = score_threshold(te_obs, thr)
    print(f"\nправило предполётной проверки, ПОРОГ ВЫБРАН НА TRAIN: подключать клин, только если "
          f"ex-ante оборот ≤ {thr:.2f}/год")
    print(f"{'':<10}{'TP':>6}{'FP':>6}{'FN':>6}{'TN':>6}{'точность':>11}{'sens':>8}{'spec':>8}{'bal':>8}")
    for name, sc in (("TRAIN", sc_tr), ("TEST", sc_te)):
        print(f"{name:<10}{sc['tp']:>6.0f}{sc['fp']:>6.0f}{sc['fn']:>6.0f}{sc['tn']:>6.0f}"
              f"{sc['acc']*100:>10.1f}%{sc['sens']:>8.2f}{sc['spec']:>8.2f}{sc['bal_acc']:>8.2f}")
    base_rate = sum(1 for o in te_obs if o.beats_raw) / max(len(te_obs), 1)
    print(f"КОНТРОЛЬ: доля «клин реально обыграл равновес» на TEST = {base_rate*100:.1f}% — "
          f"правило обязано бить ЭТУ константу, а не 50%")

    print("\nвсё выше — advisory backtest [bt], L0. Капитал не двигался, RiskPolicy v1.0, "
          "kill-switch, живой трек и флот НЕ тронуты.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
