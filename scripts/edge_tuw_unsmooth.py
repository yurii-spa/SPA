#!/usr/bin/env python3
"""
scripts/edge_tuw_unsmooth.py — Ideas #143 TUW and #144 GLM (docs/DYNAMIC_LEVERAGE_GUARDIAN.md)

#143 TUW — Time-Under-Water admission
  Every de-risk rule in the registry reads DEPTH (drawdown %, μ, σ, Calmar). None reads
  DURATION. Mechanism claim: a carry book recovers its high-water mark by accrual, so its
  time under water is short and structural; an impaired book (permanent depeg loss,
  levered bleed) does not recover. Rule (causal, decided on data <= t-1):
      book i is admitted on day t  <=>  days since its own HWM (shadow equity) <= D
  Excluded weight goes to cash (TUW-cash) or is re-spread over admitted books (TUW-redist).
  CONTROL that makes it a duration claim and not a repeat of #119 CADS: DEPTH-X —
  excluded while drawdown from HWM > X. If TUW does not beat DEPTH, duration adds nothing.

#144 GLM — return-smoothing (Getmansky-Lo-Makarov 2004 / Lo 2002)
  Marks that are smoothed (stale oracles, accrual-only marks) show positive lag-1
  autocorrelation and UNDERSTATE volatility. Unsmoothed σ_u = σ·sqrt((1+ρ)/(1−ρ)),
  applied only for ρ > 0 (unsmoothing may only RAISE measured risk; negative ρ is
  mean reversion, not smoothing). Question: does σ_u measured on TRAIN rank the books'
  TEST risk better than raw σ, and does inverse-σ_u sizing beat inverse-σ sizing?

Window: 2024-03-05 .. 2026-07-04 (852 days). The panel series are flat / constant-drift
after 2026-07-05 and carry a splice on 2026-08-05 (one-day cross-panel moves of −83 %..+105 %
at the backtest→forward phase switch) — that is not market data, so it is cut (WINDOW_END).

stdlib-only, deterministic, read-only, LLM FORBIDDEN.
Advisory / paper-only (IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True): no live track, no
RiskPolicy, no execution path is touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO / "data" / "aggressive_lab"

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

WINDOW_START = "2024-03-05"
WINDOW_END = "2026-07-05"          # exclusive: flat tail + 2026-08-05 splice beyond
SPLIT_PRIMARY = "2026-01-01"       # directive: train 2024-2025 / test 2026
SPLIT_ALT = "2025-07-01"           # registry's habitual split (#112/#132); TEST holds usde_unwind_2025_10
TOLL_ROUND_TRIP = 0.0096           # registry canonical 96 bp round-trip
D_GRID = (5, 10, 20, 30, 60, 90)
X_GRID = (0.005, 0.01, 0.02, 0.05, 0.10)
SIGMA_FLOOR_ANNUAL = 0.01          # #128 SFS lesson: σ≈0 on TRAIN is "unobserved", not "riskless"


class PanelError(RuntimeError):
    """Fail-CLOSED: the panel cannot be read as one aligned axis."""


# ── data ───────────────────────────────────────────────────────────────────────

def load_panel(data_dir: Path, start: str = WINDOW_START, end: str = WINDOW_END) -> tuple[list[str], dict[str, list[float]]]:
    files = sorted(Path(data_dir).glob("*/realized_series.jsonl"))
    if not files:
        raise PanelError(f"no realized_series.jsonl under {data_dir}")
    axis = None
    eq: dict[str, list[float]] = {}
    for f in files:
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        rows = [r for r in rows if start <= r["date"] < end]
        dates = [r["date"] for r in rows]
        if axis is None:
            axis = dates
        elif dates != axis:
            raise PanelError(f"{f.parent.name}: date axis differs from the panel")
        eq[f.parent.name] = [float(r["equity_usd"]) for r in rows]
    if not axis or len(axis) < 2:
        raise PanelError("window holds fewer than 2 dates")
    return axis, eq


def returns(eq: list[float]) -> list[float]:
    return [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]


# ── metrics ────────────────────────────────────────────────────────────────────

def metrics(rets: list[float]) -> dict:
    nav, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        nav *= 1.0 + r
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
    n = len(rets)
    apy = nav ** (365.0 / n) - 1.0 if n else 0.0
    calmar = apy / mdd if mdd > 1e-12 else None   # None = no drawdown observed, not "infinite"
    return {"apy": apy, "mdd": mdd, "calmar": calmar, "days": n}


def lag1_autocorr(x: list[float]) -> float | None:
    if len(x) < 3:
        return None
    m = sum(x) / len(x)
    den = sum((v - m) ** 2 for v in x)
    if den <= 0:
        return None                               # constant series: autocorrelation unmeasured
    return sum((x[i] - m) * (x[i - 1] - m) for i in range(1, len(x))) / den


def pstdev(x: list[float]) -> float:
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / len(x))


def unsmooth_factor(rho: float | None) -> float:
    if rho is None or rho <= 0:
        return 1.0
    rho = min(rho, 0.95)
    return math.sqrt((1 + rho) / (1 - rho))


def spearman(a: list[float], b: list[float]) -> float | None:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den > 0 else None


# ── engine ─────────────────────────────────────────────────────────────────────

def days_since_hwm(eq: list[float]) -> list[int]:
    """out[t] = days since the HWM as of the close of day t (0 on a new high)."""
    out, peak, n = [], -math.inf, 0
    for e in eq:
        if e >= peak:
            peak, n = e, 0
        else:
            n += 1
        out.append(n)
    return out


def drawdown_path(eq: list[float]) -> list[float]:
    out, peak = [], -math.inf
    for e in eq:
        peak = max(peak, e)
        out.append(1.0 - e / peak)
    return out


def run_overlay(eq: dict[str, list[float]], admit: dict[str, list[bool]], redistribute: bool,
                toll: float = TOLL_ROUND_TRIP) -> list[float]:
    """Portfolio daily returns r[t-1] for t=1..T-1. Admission for day t is read at t-1 (causal)."""
    books = sorted(eq)
    n = len(books)
    T = len(eq[books[0]])
    rets = {b: returns(eq[b]) for b in books}
    prev_w = {b: 1.0 / n for b in books}
    out = []
    for t in range(1, T):
        on = [b for b in books if admit[b][t - 1]]
        if redistribute:
            w = {b: (1.0 / len(on) if b in on else 0.0) for b in books} if on else {b: 0.0 for b in books}
        else:
            w = {b: (1.0 / n if b in on else 0.0) for b in books}
        turnover = sum(abs(w[b] - prev_w[b]) for b in books)
        r = sum(w[b] * rets[b][t - 1] for b in books) - turnover * toll / 2.0
        out.append(r)
        prev_w = w
    return out


def static_weights(eq: dict[str, list[float]], w: dict[str, float]) -> list[float]:
    books = sorted(eq)
    rets = {b: returns(eq[b]) for b in books}
    T = len(eq[books[0]])
    return [sum(w[b] * rets[b][t - 1] for b in books) for t in range(1, T)]


def seg(rets: list[float], dates: list[str], lo: str, hi: str) -> list[float]:
    # rets[k] belongs to dates[k+1]
    return [r for r, d in zip(rets, dates[1:]) if lo <= d < hi]


# ── experiments ────────────────────────────────────────────────────────────────

def _row(name, rets, dates, split, extra=None):
    tr = metrics(seg(rets, dates, dates[0], split))
    te = metrics(seg(rets, dates, split, "9999"))
    row = {"name": name, "train": tr, "test": te}
    if extra:
        row.update(extra)
    return row


def experiment_tuw(dates, eq, split):
    books = sorted(eq)
    T = len(dates)
    ew = run_overlay(eq, {b: [True] * T for b in books}, redistribute=False)
    rows = [_row("EW-10 (ноль)", ew, dates, split)]
    dsh = {b: days_since_hwm(eq[b]) for b in books}
    ddp = {b: drawdown_path(eq[b]) for b in books}
    for redist in (False, True):
        tag = "redist" if redist else "cash"
        for D in D_GRID:
            admit = {b: [x <= D for x in dsh[b]] for b in books}
            rows.append(_row(f"TUW-{D}/{tag}", run_overlay(eq, admit, redist), dates, split, {"family": f"TUW/{tag}"}))
        for X in X_GRID:
            admit = {b: [x <= X for x in ddp[b]] for b in books}
            rows.append(_row(f"DEPTH-{X*100:g}%/{tag}", run_overlay(eq, admit, redist), dates, split, {"family": f"DEPTH/{tag}"}))
    # static TRAIN selection: books with positive TRAIN APY, equal weight, held through TEST
    si = dates.index(split) if split in dates else None
    if si is not None:
        pos = [b for b in books if eq[b][si - 1] > eq[b][0]]
        w = {b: (1.0 / len(pos) if b in pos else 0.0) for b in books}
        rows.append(_row(f"STATIC-TRAIN-POS ({len(pos)})", static_weights(eq, w), dates, split, {"family": "STATIC", "books": pos}))
    return rows


def pick_by_train(rows, family):
    cand = [r for r in rows if r.get("family") == family and r["train"]["calmar"] is not None]
    return max(cand, key=lambda r: r["train"]["calmar"]) if cand else None


def breakeven_toll(eq, dates, split, D, redist, target_calmar):
    """Round-trip toll at which TUW TEST Calmar falls to target (bisection); None if never above."""
    books = sorted(eq)
    dsh = {b: days_since_hwm(eq[b]) for b in books}
    admit = {b: [x <= D for x in dsh[b]] for b in books}

    def cal(toll):
        c = metrics(seg(run_overlay(eq, admit, redist, toll), dates, split, "9999"))["calmar"]
        return -math.inf if c is None else c
    if cal(0.0) <= target_calmar:
        return None
    lo, hi = 0.0, 0.5
    if cal(hi) > target_calmar:
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cal(mid) > target_calmar else (lo, mid)
    return lo


def experiment_glm(dates, eq, split):
    books = sorted(eq)
    si = dates.index(split)
    out = {}
    for b in books:
        r_tr = returns(eq[b][: si])
        r_te = returns(eq[b][si - 1:])
        rho = lag1_autocorr(r_tr)
        s = pstdev(r_tr)
        out[b] = {
            "rho_train": rho, "sigma_train": s, "sigma_u_train": s * unsmooth_factor(rho),
            "test_mdd": metrics(r_te)["mdd"], "test_sigma": pstdev(r_te),
            "moves_in_test": any(abs(x) > 1e-12 for x in r_te),
        }
    floor = SIGMA_FLOOR_ANNUAL / math.sqrt(365)    # σ≈0 on TRAIN ≠ risk 0: floored, not divided by
    corr = {}
    for label, subset in (("all", books), ("moving_in_test", [b for b in books if out[b]["moves_in_test"]])):
        for key in ("sigma_train", "sigma_u_train"):
            for tgt in ("test_mdd", "test_sigma"):
                corr[f"{label}:{key}->{tgt}"] = spearman([out[b][key] for b in subset], [out[b][tgt] for b in subset])
    ports = []
    ew = {b: 1.0 / len(books) for b in books}
    ports.append(_row("EW-10 (ноль)", static_weights(eq, ew), dates, split))
    for key, name in (("sigma_train", "INV-σ raw"), ("sigma_u_train", "INV-σ unsmoothed")):
        inv = {b: 1.0 / max(out[b][key], floor) for b in books}
        z = sum(inv.values())
        w = {b: inv[b] / z for b in books}
        ports.append(_row(name, static_weights(eq, w), dates, split, {"weights": w}))
    return {"books": out, "sigma_floor": floor, "rank_corr": corr, "portfolios": ports}


def switches(eq, D):
    books = sorted(eq)
    dsh = {b: days_since_hwm(eq[b]) for b in books}
    return sum(1 for b in books for t in range(1, len(dsh[b])) if (dsh[b][t] <= D) != (dsh[b][t - 1] <= D))


def leave_one_out(dates, eq, split):
    """Is the TUW edge one name? Re-run the TRAIN-picked comparison with each book removed."""
    out = {}
    for drop in sorted(eq):
        sub = {b: v for b, v in eq.items() if b != drop}
        rows = experiment_tuw(dates, sub, split)
        line = {"EW": rows[0]["test"]["calmar"]}
        for fam in ("TUW/cash", "DEPTH/cash"):
            p = pick_by_train(rows, fam)
            line[fam] = None if p is None else (p["name"], p["test"]["calmar"])
        st = [r for r in rows if r.get("family") == "STATIC"]
        line["STATIC"] = st[0]["test"]["calmar"] if st else None
        out[drop] = line
    return out


def run(data_dir: Path = DEFAULT_DATA) -> dict:
    dates, eq = load_panel(data_dir)
    res = {"window": [dates[0], dates[-1]], "days": len(dates), "books": sorted(eq),
           "is_advisory": IS_ADVISORY, "outside_riskpolicy": OUTSIDE_RISKPOLICY, "splits": {}}
    for split in (SPLIT_PRIMARY, SPLIT_ALT):
        rows = experiment_tuw(dates, eq, split)
        ew_te = rows[0]["test"]["calmar"]
        picks = {}
        for fam in ("TUW/cash", "TUW/redist", "DEPTH/cash", "DEPTH/redist"):
            p = pick_by_train(rows, fam)
            if p is None:
                continue
            item = {"name": p["name"], "train": p["train"], "test": p["test"]}
            if fam.startswith("TUW"):
                D = int(p["name"].split("-")[1].split("/")[0])
                item["switches_full_axis"] = switches(eq, D)
                if ew_te is not None:
                    item["breakeven_round_trip_vs_EW"] = breakeven_toll(eq, dates, split, D, fam.endswith("redist"), ew_te)
            picks[fam] = item
        res["splits"][split] = {"tuw_rows": rows, "train_picks": picks, "glm": experiment_glm(dates, eq, split),
                                "loo": leave_one_out(dates, eq, split)}
    return res


# ── report ─────────────────────────────────────────────────────────────────────

def _f(m):
    c = "—" if m["calmar"] is None else f"{m['calmar']:.3f}"
    return f"{m['apy']*100:7.2f} | {m['mdd']*100:6.2f} | {c:>7}"


def print_report(res: dict) -> None:
    print(f"[bt] window {res['window'][0]}..{res['window'][1]} ({res['days']} d), books={len(res['books'])}")
    for split, s in res["splits"].items():
        print(f"\n=== split {split} ===  строка | TRAIN APY% | maxDD% | Calmar || TEST APY% | maxDD% | Calmar")
        for r in s["tuw_rows"]:
            print(f"{r['name']:24s} | {_f(r['train'])} || {_f(r['test'])}")
        print("-- выбор по TRAIN (TEST печатается как выпал):")
        for fam, p in s["train_picks"].items():
            be = p.get("breakeven_round_trip_vs_EW", "n/a")
            be = "NEVER-ABOVE-EW" if be is None else (f"{be*1e4:.1f} bp" if isinstance(be, float) else be)
            sw = p.get("switches_full_axis", "")
            print(f"  {fam:13s} → {p['name']:20s} TEST {_f(p['test'])}  be={be} switches={sw}")
        print("-- leave-one-out (TEST Calmar; TUW/DEPTH — параметр выбран по TRAIN без этой книги):")
        cf = lambda c: "—" if c is None else f"{c:7.3f}"
        for drop, l in s["loo"].items():
            tu, de = l["TUW/cash"], l["DEPTH/cash"]
            print(f"  −{drop:18s} EW {cf(l['EW'])} | {tu[0]:12s} {cf(tu[1])} | {de[0]:15s} {cf(de[1])} | STATIC {cf(l['STATIC'])}")
        g = s["glm"]
        print(f"-- GLM: σ-floor(daily)={g['sigma_floor']:.6f}")
        for b, v in g["books"].items():
            rho = "—" if v["rho_train"] is None else f"{v['rho_train']:+.3f}"
            print(f"  {b:18s} ρ1={rho:>7} σ={v['sigma_train']*math.sqrt(365)*100:7.2f}% σu={v['sigma_u_train']*math.sqrt(365)*100:7.2f}%"
                  f"  TEST mdd={v['test_mdd']*100:6.2f}% σ={v['test_sigma']*math.sqrt(365)*100:6.2f}% moves={v['moves_in_test']}")
        for k, c in g["rank_corr"].items():
            print(f"  spearman {k:42s} {'—' if c is None else f'{c:+.3f}'}")
        for r in g["portfolios"]:
            print(f"  {r['name']:18s} | {_f(r['train'])} || {_f(r['test'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or '').strip().splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--json", type=Path, help="write the full result as JSON here")
    a = ap.parse_args(argv)
    try:
        res = run(a.data_dir)
    except PanelError as e:
        print(f"НЕ ИЗМЕРЕНО: {e}")
        return 2
    print_report(res)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
