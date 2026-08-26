#!/usr/bin/env python3
"""
scripts/edge_step_detection_power.py — Ideas #77 (SDP) and #78 (VSD)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. `data/aggressive_lab/` is opened READ-ONLY
and nothing under `data/` is written — every artifact of this run lands in /tmp. The panel on
disk is the shared measuring stick of thirteen registry entries; a run that rewrote it would
silently invalidate all of them (test_edge_step_detection_power.py pins the mtimes).


WHY THIS RUN EXISTS — #76 DECLARED THE HALF IT DID NOT MEASURE
--------------------------------------------------------------
#76 proved that `PriceFeed.history_ratios` — the series every depeg / liquidation kill in the
aggressive lab reads — is the right LEVEL plus an independent per-day MEASUREMENT ERROR
(lag-1 autocorrelation −0.476…−0.549 on all five ratios against −0.011 on the ETH price
control), and that all four dead books are therefore false positives. It proposed repair (A),
a CAUSAL median-of-k on the ratio, and reported that the repaired panel is better on Calmar
4/4 and on drawdown 4/4. Then it wrote its own honest limit, verbatim:

    "починка проверена только со стороны ЛОЖНЫХ СРАБАТЫВАНИЙ … 'не пропускает ли она истинный
     положительный' здесь НЕ измерено — проверено лишь на фикстуре"

A guard is not judged by its false-positive rate alone. Fewer false alarms is trivially
purchasable — by turning the alarm off. The question this run answers is the other half:

    WHAT DOES THE REPAIR STOP SEEING, AND WOULD A FREE KNOB HAVE BOUGHT THE SAME QUIET?

THE CONTROL THAT DECIDES THE VERDICT — and it is the registry's usual one.
If all the median buys is DESENSITISATION, then raising the threshold buys the same thing for
free and with zero lag, and repair (A) has no content of its own. So every detector below is
compared AT MATCHED FALSE-POSITIVE RATE against `raw` with a raised threshold. This is the
same move that killed #74 (a free "basket size" control out-ranked the proposed predictor) and
#50/#72/#75 (a frequency-matched random schedule out-ran the proposed timing rule).

A second control separates the two things a smoother does. A causal MEAN-of-5 averages; a
causal MEDIAN-of-5 also REJECTS outliers. Against a sustained step the median passes the full
step (delayed), while the mean spreads it over k days and so attenuates every daily move by
1/k — which is fatal for a trigger that reads daily moves. If median and mean score the same,
the robustness story is decoration.


THE TRIGGERS ARE READ OUT OF THE ROSTER, NOT RESTATED
-----------------------------------------------------
Three of the lab's kills read the ratio, and they are two different SHAPES, which is why one
repair cannot be judged by one number:

  • `lrt_neutral`  — LEVEL vs ENTRY: kills when the ratio sits > `depeg_kill_pct` (5.0 %)
                     below the ratio observed on the book's first tick. A state test.
  • `leverage_loop` (2×) and `levered_restaking` (3×) — SINGLE-DAY MOVE: `_mark_to_market_pct`
                     computes `levered_move = ratio_move × lev` and latches `_liquidated` when
                     `levered_move <= liq_buffer_frac` (default `−0.5/lev`). Solving:
                     `ratio_move <= −0.5/lev²` → −12.50 % at 2×, −5.56 % at 3×.

`_trigger_thresholds()` derives all three from the roster classes' own defaults at run time and
refuses to run if a default has moved, so this file cannot drift away from the code it judges.

*** A CORRECTION #77 OWES #76 ***  #76's evidence table counts ratio days over 5 % / 8.33 % /
12.5 % and labels 8.33 % "the 3× one". 8.33 % is `0.25/3`; the roster's actual 3× liquidation
line is `0.5/3² = 5.56 %`. The count under the true line is LARGER, so #76's conclusion (the
series' own noise crosses the thresholds it is supposed to measure) gets STRONGER, not weaker —
but the published number was the wrong line and is restated here beside the right one.


IDEA #77 — SDP: Step-Detection Power
  MECHANISM. The real ratio series is the noise. The event is stipulated and labelled as such:
  a multiplicative step of size S injected at a real onset date, either PERMANENT (a genuine
  depeg — a state) or TRANSIENT for D days and then fully recovered (a round trip — which is
  what the quoting artifact looks like). For every onset the SAME window is run twice, with and
  without the injection, so each detector's true-positive and false-positive rates are measured
  on identical days. Detection = the trigger fires within H days of onset.

  THE NUMBER THE WHOLE ENTRY IS ABOUT is neither rate alone but their difference:
  DISCRIMINATION = TP(permanent step) − FP(no step). A detector that fires on everything and a
  detector that fires on nothing both score zero; only a detector that tells a state from a
  round trip scores.

  WHAT THIS CANNOT ANSWER, said before the numbers. There is no confirmed real depeg in the
  panel's window, so the "true positive" here is a SHAPE the run stipulates, not an event the
  market produced. That is a real limit and it is the reason the entry does not claim a
  measured true-positive RATE in the wild; it claims a detection LAW for a step of a given size
  and duration, measured against real noise. A depeg that arrives as a slow grind rather than a
  step is outside what is measured here.

IDEA #78 — VSD: Variance-Share Dependence
  #76 closed with the finding that the "law of one book" SURVIVED the repair and flipped sign:
  dropping `eth_directional` moves the per-book overlay's edge from +2.61 to −0.32 ΔCalmar. It
  concluded this is a property of the panel's COMPOSITION — one directional beta book against
  nine quiet carry books — and made the caveat of #68/#69/#71/#72/#73 stricter.

  But drop-one is a switch, and composition is a dial. Nobody has asked WHERE the sign changes.
  #78 de-levers `eth_directional` continuously (its daily returns scaled by w ∈ [0, 1] — an
  allocation decision, not a rewrite of history), and reports the overlay's ΔCalmar against the
  loudest book's VARIANCE SHARE at each w. If the crossing is orderly, the registry's panel-
  specific caveat becomes a transferable PRECONDITION — "this overlay family pays only while
  one book carries more than X of panel variance" — and variance share is something any real
  portfolio can measure about itself. If the crossing is not orderly, the caveat stays a
  caveat, and that is the honest outcome to publish.


HONEST LIMITS DECLARED UP FRONT
  • evidence L0 — every number is [bt], never realized; IS_ADVISORY / OUTSIDE_RISKPOLICY;
  • #77's events are STIPULATED shapes on real noise, not observed depegs (see above);
  • #77 measures the TRIGGERS, not the panel P&L: it answers "does the kill fire, and when",
    which is the thing #76 changed. The panel-level consequence of repair (A) is already
    published in #76 §3 and is not re-derived here;
  • #78 scales one book's returns; it does not re-run the lab, so it cannot capture how a
    de-levered book would have interacted with its own kill switch. It is a portfolio-
    composition sweep, and it is labelled as one;
  • the `phase="backtest"` window only (2024-03-05..2026-07-05), as in #71/#75/#76.

USAGE
  python3 scripts/edge_step_detection_power.py            # both ideas, /tmp/spa_sdp_report.json
  python3 scripts/edge_step_detection_power.py --idea 77  # one of them
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import edge_rearm_rule as RARM                       # noqa: E402  (#75/#76 feeds + causal median)
import edge_pde_real_panel as PRP                    # noqa: E402  (#71/#72 panel + LOO machinery)
import edge_proportional_drawdown_exit as PDE        # noqa: E402  (#70 wedge + binary guardian)

from spa_core.strategy_lab.aggressive_lab import roster as RST    # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

#: Onset dates are sampled every `ONSET_STRIDE` days of the real series. Not tuned: a stride
#: coarse enough that neighbouring onsets do not share their whole warm-up window.
ONSET_STRIDE = 7
#: Days of real series before the onset — long enough to seat the longest smoother AND the
#: level-vs-entry anchor, so no detector is judged during its own warm-up.
WARMUP = 25
#: Detection horizon. A kill that arrives later than this is not a detection of THIS event.
HORIZON = 10
#: Step sizes swept, in percent. Spans below the depeg line (3 %), on it (5 %), between the two
#: liquidation lines (5.56 % / 12.5 %) and well past both.
STEP_PCT: Tuple[float, ...] = (3.0, 5.0, 8.0, 12.5, 20.0, 30.0)
#: Event durations in days. `None` = permanent (a state). 1 = the shape of the artifact itself.
DURATIONS: Tuple[Optional[int], ...] = (1, 2, 3, 5, None)
#: The symbols the three ratio-reading kills actually read.
DEPEG_SYMBOL = "eeth"      # LrtNeutral default lrt_symbol
LIQ_SYMBOL = "steth"       # LeverageLoop / LeveredRestaking both require lrt_ratio["steth"]


# ─────────────────────────── the triggers, derived from the roster ───────────────────────────

def _trigger_thresholds() -> Dict[str, float]:
    """The three ratio-reading kill lines, read out of the roster classes' own defaults.

    Fail-CLOSED: if a default has moved since this file was written, the run REFUSES rather
    than measuring a trigger the lab no longer has. The literals below are therefore not a
    second source of truth — they are an assertion about the first one.
    """
    lrt, loop, lev3 = RST.LrtNeutral(), RST.LeverageLoop(), RST.LeveredRestaking()
    lrt.init(PRP.INITIAL, {})
    loop.init(PRP.INITIAL, {})
    lev3.init(PRP.INITIAL, {})
    depeg = float(lrt._cfg.get("depeg_kill_pct", 5.0))
    out = {"depeg_from_entry_pct": depeg}
    for name, strat, default_lev in (("liq_2x", loop, 2.0), ("liq_3x", lev3, 3.0)):
        lev = float(strat._cfg.get("leverage", default_lev))
        buf = float(strat._cfg.get("liq_buffer_frac", -0.5 / lev))
        # levered_move = ratio_move * lev ;  kill when levered_move <= buf
        out[f"{name}_daily_move"] = buf / lev
        out[f"{name}_leverage"] = lev
    expected = {"depeg_from_entry_pct": 5.0, "liq_2x_daily_move": -0.125,
                "liq_3x_daily_move": -0.5 / 9.0, "liq_2x_leverage": 2.0, "liq_3x_leverage": 3.0}
    for k, v in expected.items():
        if abs(out[k] - v) > 1e-12:
            raise RuntimeError(
                f"roster default moved: {k} is {out[k]}, this study was written against {v}. "
                f"Refusing to measure a trigger the lab no longer has."
            )
    return out


# ─────────────────────────── detectors (repairs (A) and (B), plus controls) ───────────────────────────

def causal_mean(values: Sequence[float], k: int) -> List[float]:
    """CONTROL for the median: same causal window, averaging instead of outlier rejection."""
    out: List[float] = []
    for i in range(len(values)):
        win = values[max(0, i - k + 1): i + 1]
        out.append(statistics.fmean(win))
    return out


def causal_median_list(values: Sequence[float], k: int) -> List[float]:
    """Repair (A) of #76 on a plain list. Same rule as `RARM.causal_median`, which works on a
    date-keyed dict; the list form is used here because the injection needs positional access.
    Parity with the dict form is pinned by a test — a second implementation that silently
    disagreed with #76's would make every comparison to #76 meaningless."""
    out: List[float] = []
    for i in range(len(values)):
        win = values[max(0, i - k + 1): i + 1]
        out.append(statistics.median(win))
    return out


def transform(values: Sequence[float], detector: str) -> List[float]:
    if detector == "raw":
        return list(values)
    if detector.startswith("median"):
        return causal_median_list(values, int(detector[len("median"):]))
    if detector.startswith("mean"):
        return causal_mean(values, int(detector[len("mean"):]))
    raise ValueError(f"unknown detector transform: {detector}")


def fires_level(values: Sequence[float], *, thr_pct: float, persist: int = 1,
                start_idx: int = 0) -> Optional[int]:
    """`lrt_neutral`'s kill: index of the first day the level sits > thr_pct below ENTRY.

    ENTRY is the value on day `start_idx` of the series handed in — i.e. of the DETECTOR's
    output, which is the honest reading: a lab running repair (A) would have anchored its entry
    on the repaired series too. `persist` is repair (B): the breach must hold N days running.
    """
    entry = values[start_idx]
    if entry <= 0:
        return None
    run = 0
    for i in range(start_idx, len(values)):
        drop = (entry - values[i]) / entry * 100.0
        run = run + 1 if drop > thr_pct else 0
        if run >= persist:
            return i
    return None


def fires_daily(values: Sequence[float], *, move_thr: float, persist: int = 1,
                start_idx: int = 0) -> Optional[int]:
    """The levered books' kill: index of the first day whose day-over-day move breaches.

    `move_thr` is negative (e.g. −0.125). `persist` is repair (B).
    """
    run = 0
    for i in range(max(1, start_idx), len(values)):
        prev = values[i - 1]
        move = (values[i] - prev) / prev if prev else 0.0
        run = run + 1 if move <= move_thr else 0
        if run >= persist:
            return i
    return None


# ─────────────────────────── the injection ───────────────────────────

def inject_step(values: Sequence[float], onset: int, step_pct: float,
                duration: Optional[int]) -> List[float]:
    """A multiplicative step of `step_pct` DOWN, starting at `onset`.

    `duration=None` is permanent (a depeg is a state); an integer D holds the level for D days
    and then returns to the untouched path (a round trip — the shape #76 showed the artifact
    has). Multiplicative, not additive, so the injected event is the same SIZE wherever in the
    series it lands and the real noise rides on top of it unchanged.
    """
    out = list(values)
    factor = 1.0 - step_pct / 100.0
    end = len(out) if duration is None else min(len(out), onset + duration)
    for i in range(onset, end):
        out[i] = out[i] * factor
    return out


# ─────────────────────────── the attenuation law behind the #77 numbers ───────────────────────────

def max_daily_drop(values: Sequence[float], lo: int, hi: int) -> float:
    """Largest single-day fractional DROP over [lo, hi] (a positive number, 0 if none)."""
    worst = 0.0
    for i in range(max(1, lo), min(hi + 1, len(values))):
        prev = values[i - 1]
        if prev <= 0:
            continue
        move = (values[i] - prev) / prev
        if move < 0:
            worst = max(worst, -move)
    return worst


def jump_attenuation(series: Dict[str, object], *, symbol: str = LIQ_SYMBOL,
                     stride: int = ONSET_STRIDE, horizon: int = HORIZON,
                     warmup: int = WARMUP, steps: Sequence[float] = STEP_PCT
                     ) -> Dict[str, object]:
    """WHY the TP tables look the way they do, as a number instead of an inference.

    A single-day-move trigger does not ask "did the level shift by S", it asks "was there a day
    whose move breached". So the quantity that decides it is the largest single-day DROP the
    detector's own output shows after a permanent step of size S. For `raw` that is S plus
    whatever the day's noise adds; for a causal median-of-k it is a little less than S.

    *** THE FIRST VERSION OF THIS DOCSTRING GOT THE MECHANISM WRONG, AND THE MEASUREMENT SAID
    SO. *** It predicted that the median would shrink the apparent jump by roughly two
    order-statistic gaps of the series' noise — on the order of 6 pp at k=5 and sd≈3.5 %/day.
    Measured, the shrinkage is about 0.5 pp (12.50 % → 11.98 % at S=12.5 %). The prediction was
    wrong, so it is replaced rather than quietly deleted, and the real mechanism is the more
    interesting one:

        the median takes away the noise's HELP in crossing the line.

    Read the `no event` column. `raw` shows a median largest daily drop of 3.76 % on days when
    nothing happened at all — so a real S sits on top of a ±3.76 % lottery, and at S equal to
    the line that lottery is what decides whether the guard fires (raw catches 45.90 % of
    exactly-at-the-line events; it should catch either ~100 % or ~0 %, and it catches neither).
    `median5`'s floor is 0.09 %, forty times smaller, so its output is nearly deterministic: a
    12.5 % step reads as 11.98 %, just under the 12.50 % line, and the miss stops being a
    coin flip and becomes a near-certainty (5.26 %). The law is therefore not about the size of
    the attenuation but about its VARIANCE collapsing:

        effective single-day line ≈ nominal line − ATTENUATION(k), and it now bites EVERY time

    which is the same as saying repair (A) silently DE-LEVERS every daily-move guard on the
    panel — and that on a feed repaired at the SOURCE the shift would vanish, because the
    attenuation is a property of smoothing a noisy series, not of the event. Reported as the
    median over onsets, with the no-event row printed beside it so the reader can see the noise
    floor the injection sits on.
    """
    ser = (series.get("ratio") or {}).get(symbol)
    if not ser:
        return {"refused": f"no real ratio series for {symbol}"}
    dates = sorted(ser)
    vals = [ser[d] for d in dates]
    onsets = [i for i in range(warmup, len(vals) - horizon - 1, stride)]
    out: Dict[str, object] = {"symbol": symbol, "n_onsets": len(onsets), "rows": {}}
    for label, tname, _persist in DETECTORS:
        if tname == "raw" and label != "raw":
            continue  # persistN does not change the SERIES, only the reaction
        row: Dict[str, float] = {}
        base = [max_daily_drop(transform(vals[o - warmup: o + horizon + 1], tname),
                               warmup, warmup + horizon) for o in onsets]
        row["no_event"] = statistics.median(base) * 100.0
        for step in steps:
            obs = [max_daily_drop(transform(inject_step(vals, o, step, None)[o - warmup: o + horizon + 1],
                                            tname), warmup, warmup + horizon) for o in onsets]
            row[f"S{step:g}"] = statistics.median(obs) * 100.0
        out["rows"][label] = row
    return out


# ─────────────────────────── #77 runner ───────────────────────────

def _trigger_fn(kind: str, thresholds: Dict[str, float]):
    if kind == "depeg":
        thr = thresholds["depeg_from_entry_pct"]
        return lambda vals, persist, s0: fires_level(vals, thr_pct=thr, persist=persist,
                                                     start_idx=s0)
    if kind in ("liq_2x", "liq_3x"):
        mv = thresholds[f"{kind}_daily_move"]
        return lambda vals, persist, s0: fires_daily(vals, move_thr=mv, persist=persist,
                                                     start_idx=s0)
    raise ValueError(kind)


#: (label, transform, persist). `persist2/3` are repair (B) of #76 on the RAW series; the
#: smoothers are repair (A). They are never combined — two repairs at once cannot be attributed.
DETECTORS: Tuple[Tuple[str, str, int], ...] = (
    ("raw", "raw", 1),
    ("persist2", "raw", 2),
    ("persist3", "raw", 3),
    ("median3", "median3", 1),
    ("median5", "median5", 1),
    ("median7", "median7", 1),
    ("mean5", "mean5", 1),
)


def run_idea77(series: Dict[str, object], *, stride: int = ONSET_STRIDE,
               horizon: int = HORIZON, warmup: int = WARMUP,
               steps: Sequence[float] = STEP_PCT,
               durations: Sequence[Optional[int]] = DURATIONS) -> Dict[str, object]:
    """#77: matched TP/FP for every detector, every trigger, every (step size, duration)."""
    thresholds = _trigger_thresholds()
    ratios = series.get("ratio") or {}
    out: Dict[str, object] = {"thresholds": thresholds, "cells": {}, "meta": {}}

    plans = (("depeg", DEPEG_SYMBOL), ("liq_2x", LIQ_SYMBOL), ("liq_3x", LIQ_SYMBOL))
    for kind, sym in plans:
        ser = ratios.get(sym)
        if not ser:
            out["cells"][kind] = {"refused": f"no real ratio series for {sym}"}
            continue
        dates = sorted(ser)
        vals = [ser[d] for d in dates]
        fire = _trigger_fn(kind, thresholds)
        onsets = [i for i in range(warmup, len(vals) - horizon - 1, stride)]
        out["meta"][kind] = {"symbol": sym, "n_days": len(vals), "n_onsets": len(onsets),
                             "window": [dates[0], dates[-1]]}
        cell: Dict[str, object] = {}
        for label, tname, persist in DETECTORS:
            # ALIVE AT ONSET, and this conditioning is load-bearing. The lab's kill is
            # ABSORBING: a book already killed cannot be killed again, so an onset at which the
            # detector had ALREADY fired on pre-onset noise is not a missed detection — the book
            # was not there to detect anything. Counting those as misses would deflate exactly
            # the noisiest detector's true-positive rate while also deflating its false-positive
            # rate, i.e. it would flatter and punish `raw` at the same time and neither reader
            # nor author could tell which. They are therefore EXCLUDED from both rates and the
            # exclusion is PUBLISHED as `pre_onset_kill_rate` — for `raw` that rate IS the
            # pathology #76 diagnosed, so hiding it in a denominator would bury the finding.
            # The pre-onset segment is identical with and without injection (the step starts AT
            # the onset), so liveness is decided once, by the un-injected run, for both arms.
            alive: List[int] = []
            fp = 0
            for o in onsets:
                lo = o - warmup
                seg = transform(vals[lo: o + horizon + 1], tname)
                idx = fire(seg, persist, 0)
                if idx is not None and idx < warmup:
                    continue                      # already dead before the event — not a miss
                alive.append(o)
                if idx is not None:
                    fp += 1
            n_alive = len(alive)
            rows: Dict[str, object] = {
                "n_alive": n_alive, "n_onsets": len(onsets),
                "pre_onset_kill_rate": (len(onsets) - n_alive) / len(onsets) if onsets else 0.0,
                "fp": fp, "fp_rate": fp / n_alive if n_alive else 0.0, "tp": {}}
            for step in steps:
                for dur in durations:
                    key = f"S{step:g}_D{'perm' if dur is None else dur}"
                    hits, lats = 0, []
                    for o in alive:
                        lo = o - warmup
                        inj = inject_step(vals, o, step, dur)
                        seg = transform(inj[lo: o + horizon + 1], tname)
                        idx = fire(seg, persist, 0)
                        if idx is not None and idx >= warmup:
                            hits += 1
                            lats.append(idx - warmup)
                    rows["tp"][key] = {
                        "rate": hits / n_alive if n_alive else 0.0,
                        "median_latency": (statistics.median(lats) if lats else None),
                    }
            cell[label] = rows
        out["cells"][kind] = cell
    return out


def matched_threshold_control(series: Dict[str, object], target_fp_rate: float, *,
                              stride: int = ONSET_STRIDE, horizon: int = HORIZON,
                              warmup: int = WARMUP, grid: Sequence[float] = tuple(
                                  round(5.0 + 0.5 * i, 2) for i in range(41))
                              ) -> Dict[str, object]:
    """THE FREE CONTROL, and it is only available for the depeg trigger.

    Raising `depeg_kill_pct` is a policy choice and costs nothing. Raising a LIQUIDATION line
    is not a knob at all: `liq_buffer_frac` is `−0.5/lev`, i.e. the maintenance margin implied
    by the leverage actually taken. To "raise" it you must de-lever, which changes the book's
    yield as well as its tail — so for the two levered books there IS no free alternative to
    repair (A), and that asymmetry is a finding, not an omission.

    Returns the lowest raised threshold whose false-positive rate is <= the target, plus the
    whole sweep so the reader can see the shape rather than one chosen point. Ties are resolved
    toward the LOWER threshold (fire more readily = fail-CLOSED).
    """
    ratios = series.get("ratio") or {}
    ser = ratios.get(DEPEG_SYMBOL)
    if not ser:
        return {"refused": f"no real ratio series for {DEPEG_SYMBOL}"}
    dates = sorted(ser)
    vals = [ser[d] for d in dates]
    onsets = [i for i in range(warmup, len(vals) - horizon - 1, stride)]
    sweep: List[Dict[str, object]] = []
    for thr in grid:
        alive: List[int] = []                     # same survival conditioning as run_idea77
        fp = 0
        for o in onsets:
            idx = fires_level(vals[o - warmup: o + horizon + 1], thr_pct=thr)
            if idx is not None and idx < warmup:
                continue
            alive.append(o)
            if idx is not None:
                fp += 1
        n_alive = len(alive)
        row: Dict[str, object] = {"thr_pct": thr, "fp": fp, "n_alive": n_alive,
                                  "pre_onset_kill_rate": ((len(onsets) - n_alive) / len(onsets)
                                                          if onsets else 0.0),
                                  "fp_rate": fp / n_alive if n_alive else 0.0, "tp": {}}
        for step in STEP_PCT:
            for dur in DURATIONS:
                key = f"S{step:g}_D{'perm' if dur is None else dur}"
                hits, lats = 0, []
                for o in alive:
                    inj = inject_step(vals, o, step, dur)
                    idx = fires_level(inj[o - warmup: o + horizon + 1], thr_pct=thr)
                    if idx is not None and idx >= warmup:
                        hits += 1
                        lats.append(idx - warmup)
                row["tp"][key] = {"rate": hits / n_alive if n_alive else 0.0,
                                  "median_latency": (statistics.median(lats) if lats else None)}
        sweep.append(row)
    matched = [r for r in sweep if r["fp_rate"] <= target_fp_rate + 1e-12]
    return {"target_fp_rate": target_fp_rate, "sweep": sweep,
            "matched": (matched[0] if matched else None), "n_onsets": len(onsets)}


# ─────────────────────────── #78 runner ───────────────────────────

def scale_book_returns(books: Dict[str, List[float]], book: str, w: float
                       ) -> Dict[str, List[float]]:
    """De-lever one book by `w`: its daily returns scaled, its equity rebuilt from them.

    This is an ALLOCATION statement (hold w× as much of that book), not a rewrite of history:
    the other nine books are untouched and every date is preserved. w=1 is the identity and is
    asserted as such by a test — a "sweep" whose w=1 point did not reproduce the published
    panel would be measuring its own arithmetic.
    """
    if book not in books:
        raise KeyError(f"{book} not in panel ({sorted(books)})")
    out = dict(books)
    eq = books[book]
    scaled = [eq[0]]
    for i in range(1, len(eq)):
        r = (eq[i] / eq[i - 1] - 1.0) if eq[i - 1] > 0 else 0.0
        scaled.append(scaled[-1] * (1.0 + r * w))
    out[book] = scaled
    return out


def variance_shares(books: Dict[str, List[float]]) -> Dict[str, float]:
    """Each book's share of the panel's TOTAL daily variance (sum of per-book variances).

    Deliberately the sum of variances, not the variance of the sum: the question is how much
    of the dispersion IN THE PANEL one book supplies, which is what #76 §4 measured book by
    book with per-book sd. Using the portfolio variance would fold in covariance and answer a
    different question.
    """
    var: Dict[str, float] = {}
    for name, eq in books.items():
        rets = [(eq[i] / eq[i - 1] - 1.0) if eq[i - 1] > 0 else 0.0 for i in range(1, len(eq))]
        var[name] = statistics.pvariance(rets) if len(rets) > 1 else 0.0
    tot = sum(var.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in sorted(var.items())}


def overlay_delta(books: Dict[str, List[float]], *, d_start: float, d_full: float
                  ) -> Dict[str, float]:
    """#71's headline comparison on whichever panel is handed in: per-book PDE wedge minus
    per-book binary guardian. `PRP` machinery is used unchanged so a difference between two
    sweep points cannot be a difference between two readings of the overlay."""
    n_days = len(next(iter(books.values()))) - 1
    pde_eq, pde_cost, pde_turn = PRP.per_book_overlay(
        books, lambda e: PRP.apply_pde_deadband(e, d_start=d_start, d_full=d_full, band=0.0))
    bin_eq, bin_cost, bin_turn = PRP.per_book_overlay(
        books, lambda e: (*PDE.apply_binary_guardian(e), PRP._binary_turnover(e)))
    p = PRP.metrics(pde_eq, pde_cost, n_days, pde_turn)
    b = PRP.metrics(bin_eq, bin_cost, n_days, bin_turn)
    return {"pde_calmar": p["calmar"], "bin_calmar": b["calmar"],
            "d_calmar": p["calmar"] - b["calmar"],
            "pde_net": p["net_apy_flat"], "bin_net": b["net_apy_flat"],
            "d_net": p["net_apy_flat"] - b["net_apy_flat"],
            "pde_dd": p["maxdd"], "bin_dd": b["maxdd"]}


WEIGHTS: Tuple[float, ...] = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.0)


def run_idea78(axis: Sequence[str], books: Dict[str, List[float]], *,
               book: str = "eth_directional", splits: Sequence[str] = PRP.SPLITS,
               weights: Sequence[float] = WEIGHTS,
               d_start: float = 0.01, d_full: float = 0.06) -> Dict[str, object]:
    """#78: ΔCalmar of the per-book overlay against the loudest book's variance share, as that
    book is de-levered continuously from 1.0 to 0."""
    out: Dict[str, object] = {"book": book, "splits": {}}
    for split in splits:
        rows: List[Dict[str, object]] = []
        for w in weights:
            scaled = scale_book_returns(books, book, w)
            for window, (s, e) in (("train", (None, split)), ("test", (split, None))):
                _, sub = PRP.slice_books(axis, scaled, s, e)
                shares = variance_shares(sub)
                d = overlay_delta(sub, d_start=d_start, d_full=d_full)
                loudest = max(shares, key=lambda k: shares[k])
                rows.append({"w": w, "window": window,
                             "var_share_book": shares.get(book, 0.0),
                             "loudest": loudest, "var_share_loudest": shares[loudest],
                             **d})
        out["splits"][split] = rows
    return out


def run_idea78_placebo(axis: Sequence[str], books: Dict[str, List[float]], *,
                       split: str = PRP.SPLITS[0], w_low: float = 0.1,
                       d_start: float = 0.01, d_full: float = 0.06) -> Dict[str, object]:
    """THE PLACEBO. De-lever each OTHER book by the same w and see whether the edge moves too.

    Without this the sweep proves nothing: "ΔCalmar falls when I shrink a book" is consistent
    with "ΔCalmar falls when I shrink ANY book", which would make the result a statement about
    the arithmetic of an equal-weight average rather than about `eth_directional`. Each row is
    the same measurement performed on a book that the law of one book says should not matter.
    """
    out: Dict[str, object] = {"split": split, "w_low": w_low, "rows": {}}
    _, base_sub = PRP.slice_books(axis, books, split, None)
    out["baseline"] = overlay_delta(base_sub, d_start=d_start, d_full=d_full)["d_calmar"]
    for book in sorted(books):
        scaled = scale_book_returns(books, book, w_low)
        _, sub = PRP.slice_books(axis, scaled, split, None)
        shares = variance_shares(sub)
        d = overlay_delta(sub, d_start=d_start, d_full=d_full)
        out["rows"][book] = {"d_calmar": d["d_calmar"],
                             "delta_vs_baseline": d["d_calmar"] - out["baseline"],
                             "var_share_after": shares.get(book, 0.0)}
    return out


# ─────────────────────────── reporting ───────────────────────────

def _pc(v: float, nd: int = 2) -> str:
    return f"{v * 100.0:.{nd}f}%"


def _print_idea77(res: Dict[str, object]) -> None:
    thr = res["thresholds"]
    print("\n  0. THE THREE KILL LINES, derived from the roster's own defaults [bt]:")
    print("  | trigger | shape | line |")
    print("  |---|---|---|")
    print(f"  | lrt_neutral depeg | level vs ENTRY | drop > {thr['depeg_from_entry_pct']:.2f}% |")
    print(f"  | leverage_loop (2x) | single-day move | move <= {thr['liq_2x_daily_move']*100:.2f}% |")
    print(f"  | levered_restaking (3x) | single-day move | move <= {thr['liq_3x_daily_move']*100:.2f}% |")
    print("  (#76 printed 8.33% as 'the 3x one'; the roster's line is 0.5/3^2 = 5.56% — the")
    print("   correction makes #76's own conclusion stronger, and is stated in the entry.)")

    for kind in ("depeg", "liq_2x", "liq_3x"):
        cell = res["cells"].get(kind) or {}
        if "refused" in cell:
            print(f"\n  trigger {kind}: REFUSED — {cell['refused']}")
            continue
        meta = res["meta"][kind]
        print(f"\n  TRIGGER `{kind}` on {meta['symbol']} — {meta['n_onsets']} onsets, "
              f"{meta['n_days']} real days, horizon {HORIZON}d [bt]")
        print("  | detector | killed BEFORE the event | alive | FP rate (no event) | TP perm 5% "
              "| TP perm 8% | TP perm 12.5% | TP perm 20% | TP 1-day 20% "
              "| DISCRIM (perm20 − FP) | lat perm 20% |")
        print("  |---|---|---|---|---|---|---|---|---|---|---|")
        for label, _, _ in DETECTORS:
            r = cell[label]
            g = lambda k: r["tp"][k]["rate"]  # noqa: E731
            lat = r["tp"]["S20_Dperm"]["median_latency"]
            print(f"  | {label} | {_pc(r['pre_onset_kill_rate'])} | {r['n_alive']} "
                  f"| {_pc(r['fp_rate'])} | {_pc(g('S5_Dperm'))} "
                  f"| {_pc(g('S8_Dperm'))} | {_pc(g('S12.5_Dperm'))} | {_pc(g('S20_Dperm'))} "
                  f"| {_pc(g('S20_D1'))} | {_pc(g('S20_Dperm') - r['fp_rate'])} "
                  f"| {'—' if lat is None else f'{lat:.0f}d'} |")


def _print_attenuation(att: Dict[str, object]) -> None:
    if "refused" in att:
        print(f"\n  attenuation: REFUSED — {att['refused']}")
        return
    steps = [f"S{s:g}" for s in STEP_PCT]
    print(f"\n  THE LAW BEHIND THOSE TP RATES — median largest single-day DROP the detector's own")
    print(f"  output shows after a PERMANENT step of size S ({att['n_onsets']} onsets, "
          f"{att['symbol']}) [bt]:")
    print("  | detector | no event | " + " | ".join(f"step {s[1:]}%" for s in steps) + " |")
    print("  |---|---|" + "---|" * len(steps))
    for label, row in att["rows"].items():
        cells = " | ".join(f"{row[s]:.2f}%" for s in steps)
        print(f"  | {label} | {row['no_event']:.2f}% | {cells} |")
    print("  The 2x line is 12.50% and the 3x line is 5.56%: read across a row to see which")
    print("  step sizes that detector can still push past each of them.")


def _print_idea78(res: Dict[str, object], split: str) -> None:
    rows = [r for r in res["splits"][split] if r["window"] == "test"]
    print(f"\n  split {split} — TEST window, `{res['book']}` de-levered by w [bt]")
    print("  | w | var share of that book | loudest book | its share | PDE Calmar "
          "| binary Calmar | ΔCalmar | Δnet APY |")
    print("  |---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"  | {r['w']:.2f} | {_pc(r['var_share_book'])} | {r['loudest']} "
              f"| {_pc(r['var_share_loudest'])} | {r['pde_calmar']:.2f} | {r['bin_calmar']:.2f} "
              f"| {r['d_calmar']:+.2f} | {_pc(r['d_net'])} |")


def _print_placebo(pl: Dict[str, object]) -> None:
    print(f"\n  THE PLACEBO — split {pl['split']}, TEST: de-lever EACH book to w={pl['w_low']} "
          f"in turn. Baseline ΔCalmar {pl['baseline']:+.2f} [bt]")
    print("  | book de-levered | its var share after | ΔCalmar | move vs baseline |")
    print("  |---|---|---|---|")
    for book, r in sorted(pl["rows"].items(), key=lambda kv: kv[1]["delta_vs_baseline"]):
        print(f"  | {book} | {_pc(r['var_share_after'])} | {r['d_calmar']:+.2f} "
              f"| {r['delta_vs_baseline']:+.2f} |")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ideas #77 SDP / #78 VSD (advisory)")
    ap.add_argument("--idea", choices=("77", "78", "both"), default="both")
    ap.add_argument("--refresh-feeds", action="store_true")
    ap.add_argument("--stride", type=int, default=ONSET_STRIDE)
    ap.add_argument("--json-out", default="/tmp/spa_sdp_report.json")
    args = ap.parse_args(argv)

    print("=" * 100)
    print("IDEAS #77 SDP / #78 VSD — advisory backtest, OUTSIDE_RISKPOLICY, [bt] L0")
    print("data/aggressive_lab is READ-ONLY; nothing under data/ is written")
    print("=" * 100)

    report: Dict[str, object] = {"is_advisory": True, "outside_riskpolicy": True,
                                 "evidence": "L0", "marker": "[bt]"}

    if args.idea in ("77", "both"):
        print("\n" + "-" * 100)
        print("IDEA #77 — SDP: what does repair (A) stop seeing, and would a free knob have")
        print("           bought the same quiet?")
        print("-" * 100)
        series = RARM.load_feed_series(refresh=args.refresh_feeds)
        res77 = run_idea77(series, stride=args.stride)
        report["idea77"] = res77
        _print_idea77(res77)
        att = jump_attenuation(series, stride=args.stride)
        report["idea77_attenuation"] = att
        _print_attenuation(att)

        depeg = res77["cells"].get("depeg") or {}
        if "refused" not in depeg:
            target = depeg["median5"]["fp_rate"]
            ctrl = matched_threshold_control(series, target, stride=args.stride)
            report["idea77_threshold_control"] = ctrl
            print("\n  THE FREE CONTROL — raise the depeg threshold on the RAW series until its")
            print(f"  false-positive rate matches median5's ({_pc(target)}), then compare what")
            print("  each one still detects. (No such knob exists for the levered books: their")
            print("  line is the maintenance margin implied by the leverage actually taken.)")
            m = ctrl.get("matched")
            if not m:
                print("  | no raised threshold in the sweep reaches that FP rate |")
            else:
                print("  | arm | thr | FP rate | TP perm 5% | TP perm 8% | TP perm 12.5% "
                      "| TP 1-day 20% | lat perm 8% |")
                print("  |---|---|---|---|---|---|---|---|")
                r5 = depeg["median5"]
                lat5 = r5["tp"]["S8_Dperm"]["median_latency"]
                latm = m["tp"]["S8_Dperm"]["median_latency"]
                print(f"  | median5 (repair A) | 5.00% | {_pc(r5['fp_rate'])} "
                      f"| {_pc(r5['tp']['S5_Dperm']['rate'])} | {_pc(r5['tp']['S8_Dperm']['rate'])} "
                      f"| {_pc(r5['tp']['S12.5_Dperm']['rate'])} "
                      f"| {_pc(r5['tp']['S20_D1']['rate'])} "
                      f"| {'—' if lat5 is None else f'{lat5:.0f}d'} |")
                print(f"  | raw @ raised thr (FREE) | {m['thr_pct']:.2f}% | {_pc(m['fp_rate'])} "
                      f"| {_pc(m['tp']['S5_Dperm']['rate'])} | {_pc(m['tp']['S8_Dperm']['rate'])} "
                      f"| {_pc(m['tp']['S12.5_Dperm']['rate'])} "
                      f"| {_pc(m['tp']['S20_D1']['rate'])} "
                      f"| {'—' if latm is None else f'{latm:.0f}d'} |")

    if args.idea in ("78", "both"):
        print("\n" + "-" * 100)
        print("IDEA #78 — VSD: where does the law of one book actually cross zero?")
        print("-" * 100)
        axis, books = PRP.load_books()
        print(f"\n  panel: {len(books)} books, {len(axis)} days "
              f"({axis[0]} .. {axis[-1]}), read-only from {PRP.PANEL_DIR}")
        res78 = run_idea78(axis, books)
        report["idea78"] = res78
        for split in PRP.SPLITS:
            _print_idea78(res78, split)
        placebo = run_idea78_placebo(axis, books)
        report["idea78_placebo"] = placebo
        _print_placebo(placebo)

    Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
    print(f"\nJSON → {args.json_out}")
    print("\nIS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · evidence L0 [bt] · no capital moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
