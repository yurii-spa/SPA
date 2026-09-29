#!/usr/bin/env python3
"""
IDEA #115 — WKD: Weekday Loss Clustering Gate («не держать риск в дни недели, где копятся потери»)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the fleet or the dashboard. Reads the aggressive-lab
panel and data/rates_desk/*_deep.json READ-ONLY. stdlib-only, deterministic, LLM FORBIDDEN.

ПОЧЕМУ ЭТО НОВАЯ ГИПОТЕЗА
─────────────────────────
Все 114 записей реестра решают «когда снять риск» по СОСТОЯНИЮ ряда (волатильность, просадка,
funding, ранг, режим) — то есть реактивно или по экзогенному фиду. #110/#111 измерили, что
51 % потерь приходится на ДЕНЬ 1 эпизода, и любой реактивный сигнал этот день пропускает.
Единственный класс сигналов, который известен ЗАРАНЕЕ и не требует видеть ни одного бара, —
КАЛЕНДАРЬ. Популярная рыночная байка: в выходные ликвидность тоньше, каскады ликвидаций и
отрицательный funding случаются чаще. Если потери панели СОСРЕДОТОЧЕНЫ в определённых днях
недели, их можно обойти без реакции вообще — и день 1 перестаёт быть неизвлекаемым.

ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА: (1) концентрация потерь по дням недели на 852 днях
статистически неотличима от перестановки меток (p > 0.05) — 122 недели слишком мало, чтобы
различить эффект такого размера; (2) даже если отличима, одна «выходная» пересадка в неделю
при каноническом раунд-трипе 96 bp стоит ~50 %/год и съедает всё; break-even раунд-трип
окажется на единицах bp.

МЕТОД
  Ряды (все РЕАЛЬНЫЕ, L1):
    EW      — равновзвешенная панель 10 книг (loader #16 `load_panel`, phase=backtest блок).
    EW-exYT — то же без pendle_yt_susde (его 121 %/год доминирует среднее, робастность).
    ETH     — дневная доходность цены ETH, prices_deep.json (контроль «рынок»).
    FUND    — дневная ставка funding ETH perp (funding_deep.json), доля отрицательных дней.
  Метка дня = дата точки ряда (UTC); доходность даты d — движение d-1 → d.
  (1) Концентрация: по каждому дню недели — среднее, доля потерь (сумма отрицательных
      доходностей этого дня / сумма всех отрицательных), доля «хвостовых» дней (худшие 5 %).
      Статистика S = max_wd(доля хвостовых дней) − 1/7. p-value — перестановка меток дней
      недели, 20 000 перестановок, seed=115.
  (2) Устойчивость: худший день недели по TRAIN (< 2026-01-01) совпадает ли с худшим по TEST.
  (3) Правило WKD-k: в k худших по TRAIN дней недели портфель стоит в RWA-полу (3.31 %/год,
      конвенция #110); решение известно заранее (календарь) — заглядывания нет. Издержки:
      раунд-трип rt на каждый выход-и-возврат. Сетка rt ∈ {0, 10, 96} bp + break-even rt.
      Оценка на TEST (2026) с дням, выбранными на TRAIN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_DATA = REPO / "data"

SPLIT = "2026-01-01"            # train 2024-2025 / test 2026 (стандарт директивы)
RWA_DAILY = 0.0331 / 365.0      # конвенция #110/#111
RT_GRID_BP = (0.0, 10.0, 96.0)  # 96 bp — канонический раунд-трип реестра
N_PERM = 20000
SEED = 115
TAIL_Q = 0.05
WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _load_rpe():
    spec = importlib.util.spec_from_file_location("_rpe115", HERE / "edge_real_panel_ensemble.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("edge_real_panel_ensemble.py not found — refusing to load a panel another way")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rpe115"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


#: optional relabelling {date: fake weekday} — used ONLY by the within-week permutation null
_LABELS: Dict[str, int] = {}


def weekday(d: str) -> int:
    if _LABELS:
        return _LABELS[d]
    return dt.date.fromisoformat(d).weekday()


# ───────────────────────────── data ─────────────────────────────
def load_series(data_dir: Path) -> Dict[str, Tuple[List[str], List[float]]]:
    rpe = _load_rpe()
    panel = rpe.load_panel(data_dir / "aggressive_lab")
    axis = rpe.common_axis(panel)
    if len(axis) < 200:
        raise RuntimeError(f"common axis {len(axis)} days — refusing to judge a calendar on it")
    books = sorted(panel)
    out: Dict[str, Tuple[List[str], List[float]]] = {}
    out["EW"] = (axis, [sum(panel[b][d] for b in books) / len(books) for d in axis])
    ex = [b for b in books if b != "pendle_yt_susde"]
    out["EW-exYT"] = (axis, [sum(panel[b][d] for b in ex) / len(ex) for d in axis])

    px = json.loads((data_dir / "rates_desk" / "prices_deep.json").read_text())["series"]["eth"]
    pd_ = sorted(px)
    # только соседние календарные дни: пропуск в фиде не выдаётся за однодневное движение
    ed, er = [], []
    for a, b in zip(pd_, pd_[1:]):
        if (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days == 1:
            ed.append(b)
            er.append(px[b] / px[a] - 1.0)
    out["ETH"] = (ed, er)
    return out


def load_funding(data_dir: Path) -> Tuple[List[str], List[float]]:
    s = json.loads((data_dir / "rates_desk" / "funding_deep.json").read_text())["series"]
    ds = sorted(s)
    return ds, [float(s[d]) for d in ds]


# ───────────────────────────── (1) concentration ─────────────────────────────
def tail_share_by_wd(dates: Sequence[str], rets: Sequence[float], labels: Sequence[int]) -> List[float]:
    n = len(rets)
    k = max(1, int(round(TAIL_Q * n)))
    worst = sorted(range(n), key=lambda i: rets[i])[:k]
    cnt = [0] * 7
    for i in worst:
        cnt[labels[i]] += 1
    return [c / k for c in cnt]


def concentration(dates: Sequence[str], rets: Sequence[float]) -> dict:
    labels = [weekday(d) for d in dates]
    by = {w: [r for r, l in zip(rets, labels) if l == w] for w in range(7)}
    neg_total = sum(r for r in rets if r < 0) or -1e-18
    shares = tail_share_by_wd(dates, rets, labels)
    base = [len(by[w]) / len(rets) for w in range(7)]      # ожидание = доля дней, не ровно 1/7
    stat = max(s - b for s, b in zip(shares, base))
    rng = random.Random(SEED)
    lab = list(labels)
    ge = 0
    for _ in range(N_PERM):
        rng.shuffle(lab)
        sh = tail_share_by_wd(dates, rets, lab)
        if max(s - b for s, b in zip(sh, base)) >= stat - 1e-15:
            ge += 1
    rows = []
    for w in range(7):
        xs = by[w]
        rows.append({
            "wd": WD[w], "n": len(xs),
            "mean_bp": 1e4 * sum(xs) / len(xs) if xs else 0.0,
            "loss_share": sum(r for r in xs if r < 0) / neg_total,
            "tail_share": shares[w],
        })
    return {"rows": rows, "stat": stat, "p_perm": (ge + 1) / (N_PERM + 1), "n": len(rets)}


def worst_days_by_mean(dates: Sequence[str], rets: Sequence[float], k: int) -> List[int]:
    acc = [[0.0, 0] for _ in range(7)]
    for d, r in zip(dates, rets):
        w = weekday(d)
        acc[w][0] += r
        acc[w][1] += 1
    means = [(acc[w][0] / acc[w][1] if acc[w][1] else 0.0, w) for w in range(7)]
    return [w for _, w in sorted(means)[:k]]


# ───────────────────────────── (3) the rule ─────────────────────────────
def perf(rets: Sequence[float]) -> dict:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1.0 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
    n = len(rets)
    apy = eq ** (365.0 / n) - 1.0 if n else 0.0
    return {"apy": apy, "maxdd": -mdd, "calmar": apy / -mdd if mdd < 0 else float("inf")}


def gated(dates: Sequence[str], rets: Sequence[float], off: Sequence[int], rt_bp: float) -> Tuple[List[float], int]:
    """Calendar gate: on weekdays in `off` hold the RWA floor. Cost = half-roundtrip per edge."""
    out, prev_off, legs = [], False, 0
    half = rt_bp / 2e4
    offs = set(off)
    for d, r in zip(dates, rets):
        is_off = weekday(d) in offs
        x = RWA_DAILY if is_off else r
        if is_off != prev_off:
            x -= half
            legs += 1
        prev_off = is_off
        out.append(x)
    return out, legs


def evaluate(dates: Sequence[str], rets: Sequence[float]) -> dict:
    tr = [(d, r) for d, r in zip(dates, rets) if d < SPLIT]
    te = [(d, r) for d, r in zip(dates, rets) if d >= SPLIT]
    trd, trr = [d for d, _ in tr], [r for _, r in tr]
    ted, ter = [d for d, _ in te], [r for _, r in te]
    res = {"train_n": len(tr), "test_n": len(te),
           "worst_train": WD[worst_days_by_mean(trd, trr, 1)[0]],
           "worst_test": WD[worst_days_by_mean(ted, ter, 1)[0]] if te else None,
           "base_test": perf(ter), "base_train": perf(trr), "rules": []}
    for k in (1, 2):
        off = worst_days_by_mean(trd, trr, k)
        for rt in RT_GRID_BP:
            g_te, legs_te = gated(ted, ter, off, rt)
            g_tr, _ = gated(trd, trr, off, rt)
            res["rules"].append({"k": k, "off": [WD[w] for w in off], "rt_bp": rt,
                                 "test": perf(g_te), "train": perf(g_tr), "legs_test": legs_te})
        # break-even roundtrip on TEST: total-return gain / roundtrips
        g0, legs = gated(ted, ter, off, 0.0)
        tot_g = 1.0
        for x in g0:
            tot_g *= 1 + x
        tot_b = 1.0
        for x in ter:
            tot_b *= 1 + x
        rts = legs / 2.0
        res["rules"].append({"k": k, "off": [WD[w] for w in off], "breakeven_rt_bp":
                             (1e4 * (tot_g - tot_b) / rts) if rts else None})
    return res


def all_weekdays_on_test(dates: Sequence[str], rets: Sequence[float]) -> List[Tuple[str, float]]:
    """TEST total-return gain (bp, rt=0) of gating EACH weekday — so the chosen day's rank is visible."""
    ted = [d for d in dates if d >= SPLIT]
    ter = [r for d, r in zip(dates, rets) if d >= SPLIT]
    base = 1.0
    for x in ter:
        base *= 1 + x
    out = []
    for w in range(7):
        g, _ = gated(ted, ter, [w], 0.0)
        tot = 1.0
        for x in g:
            tot *= 1 + x
        out.append((WD[w], 1e4 * (tot - base)))
    return out


def walk_forward(dates: Sequence[str], rets: Sequence[float], min_train: int = 180) -> dict:
    """Expanding window, quarterly re-selection of the worst weekday on ALL prior days.

    Null = the average gain of gating a weekday picked uniformly at random (mean over the 7).
    A calendar edge exists only if the chosen day beats that null out of sample, quarter by
    quarter — one train/test split with a 1-in-7 coincidence is not evidence.
    """
    def q(d: str) -> str:
        y, m = d[:4], int(d[5:7])
        return f"{y}Q{(m - 1) // 3 + 1}"
    quarters = sorted({q(d) for d in dates})
    rows = []
    for qq in quarters:
        idx = [i for i, d in enumerate(dates) if q(d) == qq]
        first = idx[0]
        if first < min_train:
            continue
        pick = worst_days_by_mean(dates[:first], rets[:first], 1)[0]
        qd = [dates[i] for i in idx]
        qr = [rets[i] for i in idx]
        base = 1.0
        for x in qr:
            base *= 1 + x
        gains = []
        for w in range(7):
            g, _ = gated(qd, qr, [w], 0.0)
            tot = 1.0
            for x in g:
                tot *= 1 + x
            gains.append(1e4 * (tot - base))
        rows.append({"q": qq, "pick": WD[pick], "gain_bp": gains[pick],
                     "null_bp": sum(gains) / 7.0,
                     "rank": 1 + sorted(gains, reverse=True).index(gains[pick])})
    beat = sum(1 for r in rows if r["gain_bp"] > r["null_bp"])
    return {"rows": rows, "beat_null": beat, "n": len(rows),
            "mean_excess_bp": (sum(r["gain_bp"] - r["null_bp"] for r in rows) / len(rows)) if rows else None}


def wf_permutation(dates: Sequence[str], rets: Sequence[float], n_perm: int = 400) -> dict:
    """Null for the walk-forward: shuffle the 7 weekday labels INSIDE each calendar week.

    Keeps every return on its own date (so crises, kills and regimes stay where they were) and
    destroys only the claim «the same weekday is bad every week». If the observed walk-forward
    excess is not in the right tail of this null, the calendar carries nothing that selection on
    noise with an expanding window would not also produce.
    """
    global _LABELS
    obs = walk_forward(dates, rets)["mean_excess_bp"]
    weeks: Dict[Tuple[int, int], List[str]] = {}
    for d in dates:
        iso = dt.date.fromisoformat(d).isocalendar()
        weeks.setdefault((iso[0], iso[1]), []).append(d)
    rng = random.Random(SEED + 1)
    ge, vals = 0, []
    try:
        for _ in range(n_perm):
            lab: Dict[str, int] = {}
            for ds in weeks.values():
                real = [dt.date.fromisoformat(d).weekday() for d in ds]
                rng.shuffle(real)
                lab.update(zip(ds, real))
            _LABELS = lab
            v = walk_forward(dates, rets)["mean_excess_bp"]
            vals.append(v)
            if v is not None and obs is not None and v >= obs - 1e-12:
                ge += 1
    finally:
        _LABELS = {}
    vals.sort()
    return {"observed_bp": obs, "p": (ge + 1) / (n_perm + 1), "n_perm": n_perm,
            "null_median_bp": vals[len(vals) // 2], "null_p95_bp": vals[int(0.95 * len(vals))]}


#: the one day that selects «Friday» in TRAIN for the carry books: a ratio-noise kill (#76) that
#: hit leverage_loop −29.7 % and lrt_neutral −14.8 % at once — named, not searched for.
KILL_ARTIFACT_DAY = "2024-08-09"


def decomposition(data_dir: Path, n_perm: int = 200) -> List[dict]:
    """Is the panel's walk-forward excess ONE effect, or a selection by one component rewarded by another?"""
    rpe = _load_rpe()
    panel = rpe.load_panel(data_dir / "aggressive_lab")
    axis = rpe.common_axis(panel)
    books = sorted(panel)

    def ew(bs: Sequence[str]) -> List[float]:
        return [sum(panel[b][d] for b in bs) / len(bs) for d in axis]

    carry = [b for b in books if b != "eth_directional"]
    cr = ew(carry)
    cases = [("eth_directional only", list(axis), ew(["eth_directional"])),
             ("EW ex eth_directional", list(axis), cr)]
    if KILL_ARTIFACT_DAY in axis:
        i = axis.index(KILL_ARTIFACT_DAY)
        cases.append((f"EW ex eth_directional, {KILL_ARTIFACT_DAY} dropped", axis[:i] + axis[i + 1:], cr[:i] + cr[i + 1:]))
    out = []
    for name, d, x in cases:
        wf = walk_forward(d, x)
        nl = wf_permutation(d, x, n_perm)
        out.append({"case": name, "picks": [q["pick"] for q in wf["rows"]], "beat": wf["beat_null"],
                    "n": wf["n"], "excess_bp": wf["mean_excess_bp"], "null_p95_bp": nl["null_p95_bp"], "p": nl["p"]})
    return out


def run(data_dir: Path, verbose: bool = True) -> dict:
    series = load_series(data_dir)
    fd, fv = load_funding(data_dir)
    out = {"series": {}, "funding": {}}
    for name, (d, r) in series.items():
        out["series"][name] = {"concentration": concentration(d, r), "rule": evaluate(d, r),
                               "span": [d[0], d[-1]], "test_by_day": all_weekdays_on_test(d, r),
                               "walk_forward": walk_forward(d, r),
                               "wf_null": wf_permutation(d, r)}
    # funding: share of negative days by weekday (+ permutation on the max excess)
    labels = [weekday(d) for d in fd]
    neg = [1 if v < 0 else 0 for v in fv]
    tot_neg = sum(neg)
    base = [labels.count(w) / len(labels) for w in range(7)]
    share = [sum(n for n, l in zip(neg, labels) if l == w) / tot_neg if tot_neg else 0.0 for w in range(7)]
    stat = max(s - b for s, b in zip(share, base))
    rng, lab, ge = random.Random(SEED), list(labels), 0
    for _ in range(N_PERM):
        rng.shuffle(lab)
        sh = [sum(n for n, l in zip(neg, lab) if l == w) / tot_neg for w in range(7)] if tot_neg else [0] * 7
        if max(s - b for s, b in zip(sh, base)) >= stat - 1e-15:
            ge += 1
    out["funding"] = {"n": len(fv), "neg_days": tot_neg,
                      "neg_share_by_wd": dict(zip(WD, share)), "stat": stat,
                      "p_perm": (ge + 1) / (N_PERM + 1), "span": [fd[0], fd[-1]]}
    out["decomposition"] = decomposition(data_dir)
    if verbose:
        _print(out)
    return out


def _print(out: dict) -> None:
    print("=== #115 WKD: weekday loss clustering [bt][L1 real feeds] — advisory, not P&L ===")
    for name, s in out["series"].items():
        c, r = s["concentration"], s["rule"]
        print(f"\n--- {name}  {s['span'][0]}…{s['span'][1]}  n={c['n']} ---")
        print("  wd   n   mean bp  loss share  tail(5%) share")
        for row in c["rows"]:
            print(f"  {row['wd']}  {row['n']:3d}  {row['mean_bp']:+7.2f}   {row['loss_share'] * 100:5.1f}%"
                  f"     {row['tail_share'] * 100:5.1f}%")
        print(f"  max tail-share excess over base {c['stat'] * 100:.1f} pp   permutation p = {c['p_perm']:.3f}")
        print(f"  worst weekday TRAIN={r['worst_train']}  TEST={r['worst_test']}")
        bt = r["base_test"]
        print(f"  TEST base: APY {bt['apy'] * 100:.2f}%  maxDD {bt['maxdd'] * 100:.2f}%  Calmar {bt['calmar']:.2f}")
        for x in r["rules"]:
            if "breakeven_rt_bp" in x:
                be = x["breakeven_rt_bp"]
                print(f"    k={x['k']} off={x['off']}: break-even roundtrip on TEST = "
                      f"{'n/a' if be is None else f'{be:.1f} bp'}")
                continue
            t = x["test"]
            print(f"    k={x['k']} off={x['off']} rt={x['rt_bp']:>4.0f}bp: TEST APY {t['apy'] * 100:6.2f}%  "
                  f"maxDD {t['maxdd'] * 100:5.2f}%  Calmar {t['calmar']:6.2f}   (legs {x['legs_test']})")
        print("  TEST gain of gating each weekday (rt=0, bp total): "
              + "  ".join(f"{w} {g:+.0f}" for w, g in s["test_by_day"]))
        wf = s["walk_forward"]
        print(f"  walk-forward (expanding, quarterly re-pick): chosen day beats random-day null in "
              f"{wf['beat_null']}/{wf['n']} quarters, mean excess "
              f"{'n/a' if wf['mean_excess_bp'] is None else format(wf['mean_excess_bp'], '+.0f')} bp/quarter")
        nl = s["wf_null"]
        print(f"  within-week label-shuffle null ({nl['n_perm']} perms): observed {nl['observed_bp']:+.0f} bp/q, "
              f"null median {nl['null_median_bp']:+.0f}, null p95 {nl['null_p95_bp']:+.0f}, p = {nl['p']:.3f}")
        for q in wf["rows"]:
            print(f"    {q['q']} pick {q['pick']}  gain {q['gain_bp']:+7.0f} bp  null {q['null_bp']:+7.0f}  rank {q['rank']}/7")
    f = out["funding"]
    print(f"\n--- FUNDING ETH perp {f['span'][0]}…{f['span'][1]}: {f['neg_days']} negative days of {f['n']} ---")
    print("  " + "  ".join(f"{w} {v * 100:4.1f}%" for w, v in f["neg_share_by_wd"].items()))
    print(f"  max excess {f['stat'] * 100:.1f} pp   permutation p = {f['p_perm']:.3f}")
    print("\n--- DECOMPOSITION: one effect, or selection by one component rewarded by another? ---")
    for c in out["decomposition"]:
        print(f"  {c['case']:48s} picks {','.join(c['picks'])}  beat {c['beat']}/{c['n']}  "
              f"excess {c['excess_bp']:+.1f} bp/q  null p95 {c['null_p95_bp']:+.1f}  p={c['p']:.3f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#115 WKD weekday loss clustering gate (advisory)")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    out = run(a.data_dir)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
