#!/usr/bin/env python3
"""
scripts/edge_exogenous_leading_switch.py — Idea #112 (XLS: Exogenous Leading Switch)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core/execution/. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads the panel and the deep feeds READ-ONLY.


WHY THIS RUN EXISTS — TWO ORDERS, ONE OF THEM DATA-BLOCKED SINCE 2026-07-20
--------------------------------------------------------------------------
#110 (BISS) closed with two questions. #111 (BISS-REAL) executed the first. This is the second,
verbatim:

    "(2) Существует ли NON-REACTIVE сигнал (leading indicator, не lagging) — например, по
     внешнему фиду (funding rate, basis), а не по самим доходностям — который сдвигает
     фактический барьер ближе к ORACLE?"

The same question is the closing line of #19 (EWVM), where it was explicitly declared
UNANSWERABLE for want of data:

    "Следующий шаг: RTMR exogenous signal aligned with real equity series (DATA-BLOCKED на
     synthetic fixture — нужны выровненные реальные book+signal данные)."

The data now exists and is aligned: `data/rates_desk/funding_deep.json` (755 daily ETH perp
funding observations, 2024-06-01 ... 2026-06-25) and `data/rates_desk/prices_deep.json` (six ETH/
LST price series over the same span). The panel's own axis covers 2024-03-06 ... 2026-07-05, so
the intersection is 755 days — enough to ask the question that #19 could not.


WHAT "EXOGENOUS" MEANS HERE, AND WHERE THE WORD OVERSTATES
----------------------------------------------------------
Exogenous here means: NOT derived from the books' realised equity. That is the property the
question is about — a signal computed from book returns cannot fire before the books lose money,
which is the whole barrier #110 measured.

It does NOT mean independent. ETH perp funding is the MECHANISM of the delta-neutral books
(susde_dn, pendle_yt_susde): a funding signal is structurally informed about them rather than
independent of them, and #22 (FSGC) already measured funding's own predictability on this exact
series (lag-1 autocorrelation +0.754, P(funding>0) = 84.0 %) and its economic budget as an ON/OFF
gate for the carry LEG: 1.1 bp per switch. #22's verdict was that the gate does not pay. This run
asks a different question with the same feed — not "gate the carry leg" but "switch the whole
risky sleeve" — so #22's budget does not transfer, but its warning does, and the toll is charged
here at the canonical 96 bp rather than assumed away.

ETH price is exogenous to the carry books and is the driver of the directional ones
(eth_directional, levered_restaking) — the same overstatement in the other direction. Both are
named beside their rows, never hidden.


WHAT THIS RUN MEASURES THAT #19 AND #110 COULD NOT
--------------------------------------------------
1. LEAD TIME, measured rather than modelled. #19 SET lead_days as an input and priced each day of
   it (-0.008 pp APY per extra day). Here the lead is an OUTPUT: for each declared decline window,
   the offset between the window opening and the signal's first DEFEND day. A signal that never
   fires in the band is reported as MISSED, not as lead 0 (inv. #17).
2. FEED COVERAGE as a first-class number. The ETH price series covers 78.3 % of the decision days
   on this axis. A signal cannot detect same-day what it cannot observe, so both stale-feed
   policies are run: HOLD (keep yesterday's decision) and DEFEND (fail-CLOSED while blind). #52
   (SFP) asked this question for books; it is asked here for feeds, and the two policies are
   different rows, never one averaged row.
3. The TOLL. #111 found that at 96 bp the entire binary-switch class is under water on this panel
   INCLUDING both oracles — ORACLE-DAY switches 440 times and ends at Calmar -0.749 against an
   EW zero of 3.295. So the live question for any exogenous signal is not accuracy but DUTY: a
   rule with ORACLE-WIN2's 12 switches has room, a rule with 1DAY's 33 has less, and a rule with
   ORACLE-DAY's 440 has none. Each row therefore carries its break-even round trip in bp,
   measured by bisection, beside its Calmar.

HONEST LIMITS DECLARED UP FRONT
  * evidence L1/[bt] for the signal side (real feeds), L0/[bt] for the P&L side (the panel's books
    are themselves backtests). Never realised P&L, never fills.
  * the axis shrinks to the feed overlap (755 of 852 days), so EVERY zero — EW, both oracles,
    1DAY, 5DAY — is recomputed on that axis. Comparing against #111's 852-day numbers would
    differ from the treatment by two knobs, which is the defect #109 caught in #108.
  * the window set defining ORACLE-WIN and the calm/stress split is #111's declared rule, imported
    unchanged. It is look-ahead by design; it is the ceiling, not a trading rule.
  * one funding venue, no basis risk, no venue haircut (#22 caveat (а) still stands).
  * the DEFEND destination is #110's flat 3.4 %/yr RWA convention.
  * thresholds are a small declared grid; the TRAIN-best cell's TEST number is printed as it
    falls, beside its TRAIN rank, and no cell is selected on its TEST result.
  * advisory / paper-only: nothing here sizes, funds or gates anything.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_biss_real_panel as B111  # noqa: E402  #111 harness: simulator, windows, ceilings
import edge_real_panel_ensemble as RPE  # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
FEED_DIR = Path(os.environ.get("SPA_FEED_DIR") or (ROOT / "data" / "rates_desk"))

RWA_DAILY = B111.RWA_DAILY
ROUNDTRIP = B111.ROUNDTRIP
N_RECOVER = B111.N_RECOVER
SPLIT = B111.SPLIT

#: The window depth the calm/stress split is asked against — #111's declared reference.
FP_REF_DEPTH = 0.02
LEAD_BAND = 10  # days either side of a window opening in which a signal's first fire is looked for


# ───────────────────────────── feeds ─────────────────────────────
def load_funding(feed_dir: Path = FEED_DIR) -> Dict[str, float]:
    doc = json.loads((feed_dir / "funding_deep.json").read_text())
    ser = doc.get("series")
    if not isinstance(ser, dict) or not ser:
        raise RuntimeError("funding_deep.json has no series — refusing to fabricate a feed")
    return {str(k): float(v) for k, v in ser.items()}


def load_price(asset: str, feed_dir: Path = FEED_DIR) -> Dict[str, float]:
    doc = json.loads((feed_dir / "prices_deep.json").read_text())
    ser = (doc.get("series") or {}).get(asset)
    if not isinstance(ser, dict) or not ser:
        raise RuntimeError(f"prices_deep.json has no series for {asset!r} — refusing to fabricate")
    return {str(k): float(v) for k, v in ser.items()}


# ───────────────────────────── signal primitives ─────────────────────────────
def _zscore_tail(vals: Sequence[float]) -> Optional[float]:
    """z of the LAST element against the window. None when the window cannot support a z."""
    n = len(vals)
    if n < 10:
        return None
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return None
    return (vals[-1] - mean) / sd


def funding_signal(axis: Sequence[str], fund: Dict[str, float], *, kind: str,
                   k: float = 1.0, lookback: int = 30, n_recover: int = N_RECOVER,
                   stale: str = "hold") -> Tuple[Set[str], Dict[str, int]]:
    """Causal DEFEND-day set from the funding series. Decision for day t reads t-1 and earlier.

    kind 'neg' : DEFEND while yesterday's funding < 0.
    kind 'z'   : DEFEND while yesterday's z-score over `lookback` <= -k.
    Both re-invest only after `n_recover` consecutive days on which the condition is false, so the
    rule cannot flap on a single print — the duty/toll finding of #111 makes that the live cost.

    `stale` names what happens on a day whose PREVIOUS day has no observation:
      'hold'   keep yesterday's decision (a stale feed is not an alarm);
      'defend' fail-CLOSED into DEFEND (blind means no risk).
    The choice is never silent: it is a row label.
    """
    if stale not in ("hold", "defend"):
        raise ValueError(f"unknown stale policy {stale!r}")
    hist: List[float] = []
    defend: Set[str] = set()
    state = False  # True == DEFEND
    clear = 0
    counts = {"blind_days": 0, "switches": 0}
    for i, d in enumerate(axis):
        prev = axis[i - 1] if i > 0 else None
        obs = fund.get(prev) if prev is not None else None
        if obs is None:
            counts["blind_days"] += 1
            new_state = True if stale == "defend" else state
        else:
            hist.append(obs)
            if len(hist) > lookback:
                hist.pop(0)
            if kind == "neg":
                fire: Optional[bool] = obs < 0.0
            elif kind == "z":
                z = _zscore_tail(hist)
                fire = None if z is None else z <= -k
            else:
                raise ValueError(f"unknown funding signal kind {kind!r}")
            if fire is None:
                # warm-up: the signal is NOT MEASURED yet. Treat as INVEST and count it, rather
                # than letting an unmeasured window masquerade as a calm verdict.
                counts["blind_days"] += 1
                new_state = True if stale == "defend" else state
            elif fire:
                new_state, clear = True, 0
            else:
                if state:
                    clear += 1
                    new_state = clear < n_recover
                    if not new_state:
                        clear = 0
                else:
                    new_state = False
        if new_state != state:
            counts["switches"] += 1
        state = new_state
        if state:
            defend.add(d)
    return defend, counts


def price_signal(axis: Sequence[str], px: Dict[str, float], *, kind: str, k: float,
                 short: int = 10, long: int = 60, n_recover: int = N_RECOVER,
                 stale: str = "hold") -> Tuple[Set[str], Dict[str, int]]:
    """Causal DEFEND-day set from an exogenous price series (ETH or an LST).

    kind 'dd'  : DEFEND while the price is >= k below its trailing `long`-day high.
    kind 'vol' : DEFEND while trailing `short`-day realised vol >= k x trailing `long`-day vol
                 (the pre-emptive vol trigger of #1, moved off the book's own equity and onto an
                 exogenous asset — exactly the alternative #1's caveat (а) named and did not test).

    Only observations dated strictly before the decision day are ever read.
    """
    if stale not in ("hold", "defend"):
        raise ValueError(f"unknown stale policy {stale!r}")
    obs_dates = sorted(px)
    defend: Set[str] = set()
    state = False
    clear = 0
    counts = {"blind_days": 0, "switches": 0}
    for i, d in enumerate(axis):
        past = [q for q in obs_dates if q < d]
        fire: Optional[bool]
        if len(past) < long + 2:
            fire = None
        else:
            series = [px[q] for q in past]
            if kind == "dd":
                hi = max(series[-long:])
                fire = (hi - series[-1]) / hi >= k if hi > 0 else None
            elif kind == "vol":
                rets = [series[j] / series[j - 1] - 1.0 for j in range(len(series) - long, len(series))]
                s_r, l_r = rets[-short:], rets
                def _sd(xs: Sequence[float]) -> float:
                    m = sum(xs) / len(xs)
                    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
                sd_l = _sd(l_r)
                fire = None if sd_l <= 0 else _sd(s_r) >= k * sd_l
            else:
                raise ValueError(f"unknown price signal kind {kind!r}")
        if fire is None:
            counts["blind_days"] += 1
            new_state = True if stale == "defend" else state
        elif fire:
            new_state, clear = True, 0
        else:
            if state:
                clear += 1
                new_state = clear < n_recover
                if not new_state:
                    clear = 0
            else:
                new_state = False
        if new_state != state:
            counts["switches"] += 1
        state = new_state
        if state:
            defend.add(d)
    return defend, counts


# ───────────────────────────── lead time ─────────────────────────────
def lead_times(axis: Sequence[str], windows: Sequence[Tuple[str, str]], defend: Set[str],
               band: int = LEAD_BAND) -> List[dict]:
    """Per window: how many days before the opening the signal TRANSITIONED into DEFEND.

    +n = switched n days early; 0 = on the opening day; -n = n days late.

    Three outcomes, not one number (inv. #17), because the first version of this instrument was
    WRONG and the error is instructive enough to keep written down: it looked for the first day in
    the band on which the signal WAS in DEFEND, and for #110's 1DAY rule — duty 97.7 % — that is
    the band's left edge for every window. The instrument reported "+10 days of lead" for a rule
    that is simply always defending. It was measuring DUTY and calling it LEAD.

      'fired'      an INVEST -> DEFEND transition inside [open-band, open+band]; `lead` is its offset.
      'ALREADY-IN' the signal was already in DEFEND at the band's left edge, so its state carries
                   no information about THIS window's onset. `lead` is None: a rule that never
                   leaves DEFEND cannot be early, and calling it early is the defect above.
      'MISSED'     no transition and not in DEFEND — the rule said nothing about this window.

    `saturated` marks a transition sitting exactly on the band edge, where the true lead may be
    larger than the band can see.
    """
    idx = {d: i for i, d in enumerate(axis)}
    out: List[dict] = []
    for lo, hi in windows:
        o = idx[lo]
        left = max(0, o - band)
        right = min(len(axis) - 1, o + band)
        if axis[left] in defend:
            out.append({"open": lo, "close": hi, "lead": None, "status": "ALREADY-IN",
                        "saturated": False})
            continue
        first: Optional[int] = None
        for j in range(left + 1, right + 1):
            if axis[j] in defend and axis[j - 1] not in defend:
                first = j
                break
        out.append({"open": lo, "close": hi,
                    "lead": None if first is None else o - first,
                    "status": "MISSED" if first is None else "fired",
                    "saturated": first is not None and first in (left + 1, right)})
    return out


# ───────────────────────────── the null for a lead claim ─────────────────────────────
def shift_defend(axis: Sequence[str], defend: Set[str], offset: int) -> Set[str]:
    """The same defend-day SHAPE, slid `offset` days along the axis (circularly).

    A shifted signal keeps its duty, its run lengths and its switch count and loses only its
    alignment with the windows. It is therefore the right null for "this signal is EARLY": with
    four windows, +5 days on three of them is a claim that has to beat coincidence, and prose
    cannot say whether it does.
    """
    n = len(axis)
    idx = {d: i for i, d in enumerate(axis)}
    return {axis[(idx[d] + offset) % n] for d in defend}


# ───────────────────────────── break-even toll ─────────────────────────────
def breakeven_bp(axis: Sequence[str], rets: Dict[str, List[float]], books: Sequence[str],
                 defend: Set[str], defend_frac: float, calmar_ew: float,
                 hi_bp: float = 2000.0) -> Optional[float]:
    """Round-trip bp at which this rule's Calmar falls to the EW zero's. None when it never does.

    None has two reasons and they are opposite, so the caller prints which: the rule is already
    below the zero at 0 bp (nothing to spend), or it is still above it at `hi_bp` (the search
    window is too narrow to name a number — NOT MEASURED, not "infinite").
    """
    if not defend:
        return float("nan")   # the rule never fires: there is no toll to pay (see caller)

    def cal(bp: float) -> float:
        r = B111.simulate(axis, rets, books, mode="given", defend_frac=defend_frac,
                          defend_days=defend, roundtrip=bp / 10000.0)
        return r["calmar"]

    lo_c = cal(0.0)
    if lo_c != lo_c or lo_c in (float("inf"), float("-inf")):
        return None
    if lo_c <= calmar_ew:
        return 0.0
    if cal(hi_bp) > calmar_ew:
        return None
    lo, hi = 0.0, hi_bp
    for _ in range(40):
        mid = (lo + hi) / 2.0
        c = cal(mid)
        if c != c or c in (float("inf"), float("-inf")):
            return None
        if c > calmar_ew:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ───────────────────────────── main ─────────────────────────────
def build_axis(panel_dir: Path = B111.PANEL_DIR, feed_dir: Path = FEED_DIR):
    panel = RPE.load_panel(panel_dir)
    full = RPE.common_axis(panel)
    fund = load_funding(feed_dir)
    axis = [d for d in full if d in fund]
    if len(axis) < 300:
        raise RuntimeError(f"panel/feed overlap is {len(axis)} days — refusing to judge a rule on it")
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    return axis, rets, books, fund, len(full)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=ROOT / "data" / "edge_xls_results.json")
    ap.add_argument("--asset", default="eth")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    axis, rets, books, fund, n_full = build_axis()
    B111.set_axis(axis)
    px = load_price(args.asset)
    cov = len([d for d in axis if d in px]) / len(axis)

    ew_series = [sum(rets[b][i] for b in books) / len(books) for i in range(len(axis))]
    windows = B111.decline_windows(axis, ew_series, FP_REF_DEPTH)
    win_days = B111.window_days(windows)
    oracle_day = {d for i, d in enumerate(axis) if ew_series[i] < RWA_DAILY}

    print("=== #112 XLS: does an EXOGENOUS feed move the barrier toward the ceiling? ===")
    print(f"axis {axis[0]}...{axis[-1]} ({len(axis)} of the panel's {n_full} days — the feed overlap)")
    print(f"books {len(books)}   funding obs {len(fund)}   {args.asset} price coverage on this axis "
          f"{cov:.1%} ({len([d for d in axis if d in px])}/{len(axis)})")
    m = RPE.perf(ew_series)
    print(f"EW zero RECOMPUTED on this axis: APY {m['apy'] * 100:.2f}%  maxDD {abs(m['maxdd']) * 100:.2f}%  "
          f"Calmar {m['calmar']:.2f}   (#111's 852-day EW was Calmar 3.30 — different axis, not a discrepancy)")
    print(f"ORACLE-WIN2 here: {len(windows)} windows / {len(win_days)} days "
          f"({100.0 * len(win_days) / len(axis):.1f}%)   ORACLE-DAY: {len(oracle_day)} days")
    print("[bt] signal side L1 (real feeds) / P&L side L0 (panel books are backtests). Advisory.\n")

    # rows: label -> defend-day set
    cand: List[Tuple[str, Set[str], Dict[str, int]]] = []
    for stale in ("hold", "defend"):
        s, c = funding_signal(axis, fund, kind="neg", stale=stale)
        cand.append((f"FUND-NEG/{stale}", s, c))
        for k in (1.0, 1.5):
            s, c = funding_signal(axis, fund, kind="z", k=k, stale=stale)
            cand.append((f"FUND-Z{k:g}/{stale}", s, c))
        for k in (0.08, 0.15):
            s, c = price_signal(axis, px, kind="dd", k=k, stale=stale)
            cand.append((f"ETHDD{k * 100:.0f}/{stale}", s, c))
        for k in (1.5, 2.0):
            s, c = price_signal(axis, px, kind="vol", k=k, stale=stale)
            cand.append((f"ETHVOL{k:g}/{stale}", s, c))

    results: List[dict] = []
    for df_name, df in (("HALF", 0.5), ("ZERO", 0.0)):
        ew_row = B111.simulate(axis, rets, books, mode="ew", defend_frac=df, roundtrip=ROUNDTRIP)
        ew0 = B111.simulate(axis, rets, books, mode="ew", defend_frac=df, roundtrip=0.0)
        od = B111.simulate(axis, rets, books, mode="given", defend_frac=df,
                           defend_days=oracle_day, roundtrip=ROUNDTRIP)
        ow = B111.simulate(axis, rets, books, mode="given", defend_frac=df,
                           defend_days=win_days, roundtrip=ROUNDTRIP)
        one = B111.simulate(axis, rets, books, mode="1day", defend_frac=df, roundtrip=ROUNDTRIP)
        base = [("EW", ew_row, None), ("ORACLE-DAY", od, oracle_day),
                ("ORACLE-WIN2", ow, win_days), ("1DAY(#110)", one, one["defend_days"])]

        hdr = (f"{'row':<18} {'APY%':>8} {'maxDD%':>7} {'Calmar':>8} {'duty%':>6} {'switch':>6} "
               f"{'fp|defend':>10} {'fp|calm':>8} {'recall':>7} {'blind':>6} {'be_bp':>8}")
        print(f"--- DEFEND={df_name}, round trip 96 bp (zeros recomputed on THIS axis) ---")
        print(hdr)
        print("-" * len(hdr))
        for label, row, days in base + [(l, B111.simulate(axis, rets, books, mode="given",
                                                          defend_frac=df, defend_days=s,
                                                          roundtrip=ROUNDTRIP), s)
                                        for l, s, _ in cand]:
            f = B111.fp_rates(row["defend_days"], win_days, axis)
            blind = next((c["blind_days"] for l2, s2, c in cand if l2 == label), None)
            be = (None if days is None else
                  breakeven_bp(axis, rets, books, days, df, ew0["calmar"]))
            cal = "inf" if row["calmar"] == float("inf") else f"{row['calmar']:.3f}"
            fpd = "n/a" if f["fp_of_defend"] is None else f"{f['fp_of_defend']:.1%}"
            fpc = "n/a" if f["fp_of_calm"] is None else f"{f['fp_of_calm']:.1%}"
            rec = "n/a" if f["recall_of_window"] is None else f"{f['recall_of_window']:.1%}"
            bes = ("n/a" if be is None and days is None else
                   ("NEVER-FIRES" if be is not None and be != be else
                    ("NOT MEAS" if be is None else f"{be:.1f}")))
            print(f"{label:<18} {row['apy_pct']:>8.2f} {row['maxdd_pct']:>7.2f} {cal:>8} "
                  f"{row['duty_pct']:>6.1f} {row['switches']:>6} {fpd:>10} {fpc:>8} {rec:>7} "
                  f"{('-' if blind is None else blind):>6} {bes:>8}")
            results.append({"defend": df_name, "label": label, "apy_pct": row["apy_pct"],
                            "maxdd_pct": row["maxdd_pct"], "calmar": row["calmar"],
                            "duty_pct": row["duty_pct"], "switches": row["switches"],
                            "fp_of_defend": f["fp_of_defend"], "fp_of_calm": f["fp_of_calm"],
                            "recall": f["recall_of_window"], "blind_days": blind,
                            "breakeven_bp": be})
        print()

    # ── the decisive measurement: lead time, per window, per signal ──
    print(f"--- LEAD TIME: the INVEST->DEFEND transition relative to a window opening "
          f"(+early / -late), band +-{LEAD_BAND}d ---")
    print("    ALREADY-IN = the rule was defending before the band even started, so it says "
          "nothing about this onset")
    print(f"{'signal':<18} {'duty%':>6} " + " ".join(f"{w[0][5:]:>9}" for w in windows)
          + f"  {'median':>8} {'informative':>12}")
    one_days = B111.simulate(axis, rets, books, mode="1day", defend_frac=0.0,
                             roundtrip=0.0)["defend_days"]
    lead_rows: Dict[str, List[dict]] = {"1DAY(#110)": lead_times(axis, windows, one_days)}
    duties: Dict[str, float] = {"1DAY(#110)": 100.0 * len(one_days) / len(axis)}
    for label, s_set, _ in cand:
        lead_rows[label] = lead_times(axis, windows, s_set)
        duties[label] = 100.0 * len(s_set) / len(axis)
    for label, lr in lead_rows.items():
        fired = sorted(x["lead"] for x in lr if x["status"] == "fired")
        med = "none" if not fired else f"{fired[len(fired) // 2]:+d}"
        cells = []
        for x in lr:
            if x["status"] == "ALREADY-IN":
                cells.append("ALREADY-IN".rjust(9))
            elif x["status"] == "MISSED":
                cells.append("MISSED".rjust(9))
            else:
                cells.append((f"{x['lead']:+d}" + ("*" if x["saturated"] else "")).rjust(9))
        print(f"{label:<18} {duties[label]:>6.1f} " + " ".join(cells)
              + f"  {med:>8} {len(fired):>6}/{len(lr):<5}")
    print("    (* = transition sits on the band edge; the true lead may be larger than +-"
          f"{LEAD_BAND}d)")
    print()

    print("--- NULL for the lead claim: the same signal SHAPE slid along the axis "
          "(duty/runs/switches kept, alignment destroyed) ---")
    NULL_OFFSETS = (61, 127, 181, 239, 307, 401, 509)
    print(f"{'signal':<18} {'measured':>22} | {'shifted copies (informative/median lead)':<44}")
    for label in ("FUND-Z1.5/hold", "FUND-NEG/hold", "ETHVOL1.5/hold"):
        s_set = next(x for l, x, _ in cand if l == label)
        lr = lead_rows[label]
        fired = sorted(x["lead"] for x in lr if x["status"] == "fired")
        meas = f"{len(fired)}/{len(lr)} informative, med {('none' if not fired else '%+d' % fired[len(fired) // 2])}"
        cells = []
        for off in NULL_OFFSETS:
            nl = lead_times(axis, windows, shift_defend(axis, s_set, off))
            nf = sorted(x["lead"] for x in nl if x["status"] == "fired")
            cells.append(f"{len(nf)}/{len(nl)}:{('--' if not nf else '%+d' % nf[len(nf) // 2])}")
        print(f"{label:<18} {meas:>22} | " + "  ".join(cells))
    print("    Read: if the shifted copies show the same lead, the measured lead is coincidence.")
    print()

    # ── share of the ceiling, both oracles, at 96 bp and 0 bp ──
    print("--- share of the ceiling (both oracles, both tolls) for the best exogenous rows ---")
    for rt in (0.0, ROUNDTRIP):
        for df_name, df in (("HALF", 0.5), ("ZERO", 0.0)):
            ew_c = B111.simulate(axis, rets, books, mode="ew", defend_frac=df, roundtrip=rt)["calmar"]
            for oname, odays in (("ORACLE-DAY", oracle_day), ("ORACLE-WIN2", win_days)):
                o_c = B111.simulate(axis, rets, books, mode="given", defend_frac=df,
                                    defend_days=odays, roundtrip=rt)["calmar"]
                why = B111.ceiling_refusal(ew_c, o_c)
                if why:
                    print(f"  {rt * 10000:>3.0f}bp {df_name:<5} {oname:<12} NOT MEASURED — {why}")
                    continue
                best = None
                for label, s, _ in cand:
                    c = B111.simulate(axis, rets, books, mode="given", defend_frac=df,
                                      defend_days=s, roundtrip=rt)["calmar"]
                    sh = B111.share_of_ceiling(c, ew_c, o_c)
                    if sh is not None and (best is None or sh > best[1]):
                        best = (label, sh)
                txt = "no finite share" if best is None else f"{best[0]} {best[1]:+.1%}"
                print(f"  {rt * 10000:>3.0f}bp {df_name:<5} {oname:<12} ceiling {o_c - ew_c:+.3f} "
                      f"| best exogenous: {txt}")
    print()

    # ── TRAIN/TEST: pick on TRAIN only, print TEST as it falls ──
    tr = [d for d in axis if d <= SPLIT]
    te = [d for d in axis if d > SPLIT]
    print(f"--- TRAIN/TEST at {SPLIT} ({len(tr)}/{len(te)} days), 96 bp, DEFEND=ZERO ---")
    if len(te) < 120 or len(tr) < 120:
        print(f"  NOT MEASURED — split leaves {len(tr)}/{len(te)} days")
    else:
        def sub(days: Sequence[str]):
            idx = [axis.index(d) for d in days]
            return {b: [rets[b][i] for i in idx] for b in books}
        tr_r, te_r = sub(tr), sub(te)
        ranked: List[Tuple[float, str, float]] = []
        for label, s, _ in cand:
            r = B111.simulate(tr, tr_r, books, mode="given", defend_frac=0.0,
                              defend_days={d for d in s if d in set(tr)}, roundtrip=ROUNDTRIP)
            t = B111.simulate(te, te_r, books, mode="given", defend_frac=0.0,
                              defend_days={d for d in s if d in set(te)}, roundtrip=ROUNDTRIP)
            ranked.append((r["calmar"], label, t["calmar"]))
        ranked.sort(key=lambda x: -x[0])
        ew_tr = B111.simulate(tr, tr_r, books, mode="ew", defend_frac=0.0, roundtrip=ROUNDTRIP)
        ew_te = B111.simulate(te, te_r, books, mode="ew", defend_frac=0.0, roundtrip=ROUNDTRIP)
        print(f"  EW zero            TRAIN Calmar {ew_tr['calmar']:>8.3f}   TEST Calmar {ew_te['calmar']:>8.3f}")
        for rank, (c_tr, label, c_te) in enumerate(ranked, 1):
            mark = "  <- TRAIN-best" if rank == 1 else ""
            print(f"  {label:<18} TRAIN Calmar {c_tr:>8.3f}   TEST Calmar {c_te:>8.3f}{mark}")
    print()

    out = {
        "idea": "#112 XLS",
        "axis": [axis[0], axis[-1]], "n_days": len(axis), "panel_full_days": n_full,
        "books": books, "asset": args.asset, "price_coverage": cov,
        "ew": RPE.perf(ew_series),
        "windows": [list(w) for w in windows],
        "rows": results,
        "lead": {k: v for k, v in lead_rows.items()},
    }
    if not args.no_write:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2, sort_keys=True, default=str))
        print(f"written {args.json} [bt] advisory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
