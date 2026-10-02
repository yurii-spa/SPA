#!/usr/bin/env python3
"""
IDEA #116 — LYP: LST/LRT Yield Persistence («гнаться за лидером стейкинг-доходности — это эдж?»)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the fleet or the dashboard. Reads data/rates_desk/restaking_deep.json READ-ONLY.
stdlib-only, deterministic, LLM FORBIDDEN.

ПОЧЕМУ ЭТО НОВАЯ ГИПОТЕЗА
─────────────────────────
Все записи реестра, решавшие «куда класть», работали с РЕАЛИЗОВАННОЙ доходностью книг
(цена + доход вместе) и поэтому упирались в шум ratio-ряда (#76) и в хвост дня 1 (#110/#111).
Ряд `restaking_deep.json` (дневной стейкинг-APR stETH / rETH / eETH / weETH / ezETH,
2024-06…2026-06) не использовала НИ ОДНА запись. Это ряд ДОХОДА без цены: на нём можно
отдельно спросить то, что на книгах неотделимо, — УСТОЙЧИВ ЛИ ранг доходности. Если лидер
по скользящему среднему остаётся лидером завтра, ротация в лидера забирает спред без
тайминга рынка вообще.

ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА: ранг устойчив (стейкинг-APR меняются медленно), но
СПРЕД между лидером и корзиной — десятки bp в год, а не проценты; ротация «выигрывает»
у равновеса по доходу на 10–40 bp/год и не выигрывает у «купить на TRAIN лучшего и держать».
Для агрессивного тира (цель 15–25 %) это не рычаг, а шум. И главное — выигрыш по доходу
покупается уходом в LRT, чей хвост (депег/слэшинг) этот ряд не показывает вообще.

МЕТОД
  (0) Санитария ряда: пары активов с совпадающими значениями (дубликаты источника) —
      объявляются и схлопываются ДО ранжирования (иначе «лидер» считается дважды).
  (1) Устойчивость ранга: для окна L ∈ {7,14,30,60} — средняя по дням ранговая корреляция
      Спирмена между «средний APR за [t−L, t−1]» и «средний APR за [t, t+H−1]», H = 30.
  (2) Правило ROT(L, h): держать актив с наибольшим скользящим средним за L дней (строго
      до вчера); менять, только если претендент выше держателя на h bp годовых
      (гистерезис); издержка c bp на смену (своп LST→LST + газ; сетка {0, 5, 20}).
      Выбор (L, h) — на TRAIN (< 2026-01-01), оценка — на TEST (2026).
  Сравнение: EW-корзина · STATIC (лучший по среднему TRAIN, держать весь TEST) ·
  ORACLE (лучший по среднему TEST — заглядывание, потолок).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO / "data"
SPLIT = "2026-01-01"
L_GRID = (7, 14, 30, 60)
H_GRID_BP = (0.0, 10.0, 25.0, 50.0)
COST_GRID_BP = (0.0, 5.0, 20.0)
HORIZON = 30


def load(data_dir: Path) -> Tuple[List[str], Dict[str, List[float]], List[Tuple[str, str]]]:
    raw = json.loads((data_dir / "rates_desk" / "restaking_deep.json").read_text())["series"]
    # (0) duplicate sources: identical value on every shared date ⇒ one asset, not two
    names = sorted(raw)
    dups: List[Tuple[str, str]] = []
    drop = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = set(raw[a]) & set(raw[b])
            if len(common) > 30 and all(abs(raw[a][d] - raw[b][d]) < 1e-12 for d in common):
                dups.append((a, b))
                drop.add(b)
    keep = [n for n in names if n not in drop]
    axis = sorted(set.intersection(*[set(raw[n]) for n in keep]))
    if len(axis) < 200:
        raise RuntimeError(f"common axis {len(axis)} days — refusing to rank on it")
    return axis, {n: [float(raw[n][d]) for d in axis] for n in keep}, dups


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _ranks(xs: Sequence[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    for k, i in enumerate(order):
        r[i] = float(k)
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = _mean(ra), _mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def rank_persistence(axis: Sequence[str], ys: Dict[str, List[float]], L: int, lo: str, hi: str) -> dict:
    names = sorted(ys)
    vals = []
    for t in range(L, len(axis) - HORIZON):
        if not (lo <= axis[t] < hi):
            continue
        past = [_mean(ys[n][t - L:t]) for n in names]
        fut = [_mean(ys[n][t:t + HORIZON]) for n in names]
        rho = spearman(past, fut)
        if rho is not None:
            vals.append(rho)
    return {"L": L, "n": len(vals), "mean_rho": _mean(vals) if vals else None}


def rotate(axis: Sequence[str], ys: Dict[str, List[float]], L: int, h_bp: float, cost_bp: float,
           lo: str, hi: str) -> dict:
    names = sorted(ys)
    held: Optional[str] = None
    acc, n, switches = 0.0, 0, 0
    for t in range(L, len(axis)):
        if not (lo <= axis[t] < hi):
            continue
        sc = {nm: _mean(ys[nm][t - L:t]) for nm in names}
        best = max(names, key=lambda nm: (sc[nm], nm))
        if held is None:
            held = best
        elif best != held and (sc[best] - sc[held]) * 1e4 > h_bp:
            held = best
            switches += 1
            acc -= cost_bp / 1e4
        acc += ys[held][t] / 365.0
        n += 1
    ann_bp = 1e4 * acc * 365.0 / n if n else 0.0
    return {"L": L, "h_bp": h_bp, "cost_bp": cost_bp, "ann_bp": ann_bp, "switches": switches, "days": n}


def static(axis: Sequence[str], ys: Dict[str, List[float]], pick: str, lo: str, hi: str) -> float:
    xs = [ys[pick][t] for t in range(len(axis)) if lo <= axis[t] < hi]
    return 1e4 * _mean(xs)


def run(data_dir: Path, verbose: bool = True) -> dict:
    axis, ys, dups = load(data_dir)
    names = sorted(ys)
    lo_tr, hi_tr, lo_te, hi_te = axis[0], SPLIT, SPLIT, "9999"
    per_asset = {n: {"train_bp": static(axis, ys, n, lo_tr, hi_tr), "test_bp": static(axis, ys, n, lo_te, hi_te)}
                 for n in names}
    ew_tr = _mean([v["train_bp"] for v in per_asset.values()])
    ew_te = _mean([v["test_bp"] for v in per_asset.values()])
    static_pick = max(names, key=lambda n: per_asset[n]["train_bp"])
    oracle_pick = max(names, key=lambda n: per_asset[n]["test_bp"])

    persist = {"train": [rank_persistence(axis, ys, L, lo_tr, hi_tr) for L in L_GRID],
               "test": [rank_persistence(axis, ys, L, lo_te, hi_te) for L in L_GRID]}

    grid = []
    for L in L_GRID:
        for h in H_GRID_BP:
            for c in COST_GRID_BP:
                grid.append({"train": rotate(axis, ys, L, h, c, lo_tr, hi_tr),
                             "test": rotate(axis, ys, L, h, c, lo_te, hi_te)})
    # (L, h) chosen on TRAIN at the middle cost (5 bp) — declared before looking at TEST
    mid = [g for g in grid if g["train"]["cost_bp"] == 5.0]
    chosen = max(mid, key=lambda g: g["train"]["ann_bp"])
    out = {
        "span": [axis[0], axis[-1]], "days": len(axis), "assets": names, "duplicates": dups,
        "per_asset": per_asset, "ew_train_bp": ew_tr, "ew_test_bp": ew_te,
        "static_pick": static_pick, "static_test_bp": per_asset[static_pick]["test_bp"],
        "oracle_pick": oracle_pick, "oracle_test_bp": per_asset[oracle_pick]["test_bp"],
        "persistence": persist, "chosen": chosen,
        "chosen_test_all_costs": [g["test"] for g in grid
                                  if g["test"]["L"] == chosen["test"]["L"] and g["test"]["h_bp"] == chosen["test"]["h_bp"]],
        "best_test_in_grid": max((g["test"] for g in grid if g["test"]["cost_bp"] == 5.0), key=lambda r: r["ann_bp"]),
    }
    if verbose:
        _print(out)
    return out


def _print(o: dict) -> None:
    print("=== #116 LYP: LST/LRT staking-yield rank persistence [bt][L1 real feed] — advisory ===")
    print(f"axis {o['span'][0]}…{o['span'][1]} ({o['days']} days)  assets {o['assets']}")
    for a, b in o["duplicates"]:
        print(f"  DUPLICATE SOURCE: {b} == {a} on every shared date — collapsed into {a}")
    print("\n  asset     TRAIN APR   TEST APR")
    for n, v in o["per_asset"].items():
        print(f"  {n:8s} {v['train_bp']:8.0f} bp {v['test_bp']:8.0f} bp")
    print(f"  EW       {o['ew_train_bp']:8.0f} bp {o['ew_test_bp']:8.0f} bp")
    print("\n  rank persistence (Spearman past-L mean vs next-30d mean):")
    for tr, te in zip(o["persistence"]["train"], o["persistence"]["test"]):
        print(f"    L={tr['L']:>2}: TRAIN rho {tr['mean_rho']:+.3f} (n={tr['n']})   TEST rho "
              f"{'n/a' if te['mean_rho'] is None else format(te['mean_rho'], '+.3f')} (n={te['n']})")
    c = o["chosen"]
    print(f"\n  ROT chosen on TRAIN @5bp: L={c['train']['L']} h={c['train']['h_bp']:.0f}bp "
          f"→ TRAIN {c['train']['ann_bp']:.0f} bp/yr ({c['train']['switches']} switches)")
    for r in o["chosen_test_all_costs"]:
        print(f"    TEST cost {r['cost_bp']:>4.0f}bp: {r['ann_bp']:6.0f} bp/yr  switches {r['switches']}")
    print(f"  TEST EW {o['ew_test_bp']:.0f} bp · STATIC({o['static_pick']}, picked on TRAIN) {o['static_test_bp']:.0f} bp · "
          f"ORACLE({o['oracle_pick']}, look-ahead) {o['oracle_test_bp']:.0f} bp")
    b = o["best_test_in_grid"]
    print(f"  best TEST cell in grid (in-sample on TEST, a ceiling): L={b['L']} h={b['h_bp']:.0f} → {b['ann_bp']:.0f} bp")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#116 LYP LST/LRT yield persistence (advisory)")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    out = run(a.data_dir)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    if "--discount" in sys.argv[1:]:
        # #121 LDR: the same tokens' PRICE ratio to ETH — is a discount-reversion edge measurable
        # on the repository's only price history? (scripts/edge_lrt_discount.py; answer: no)
        import edge_lrt_discount
        raise SystemExit(edge_lrt_discount.main([a for a in sys.argv[1:] if a != "--discount"]))
    raise SystemExit(main())
