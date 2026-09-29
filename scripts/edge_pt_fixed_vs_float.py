#!/usr/bin/env python3
"""
IDEA #118 — PTFF: PT Fixed-vs-Float («зафиксировать ставку или остаться плавающим?»)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the fleet or the dashboard. Reads data/rates_desk/pendle_pt_history.json READ-ONLY.
stdlib-only, deterministic, LLM FORBIDDEN.

ПОЧЕМУ ЭТО НОВАЯ ГИПОТЕЗА (поиск по МЕХАНИЗМУ — урок #114)
──────────────────────────────────────────────────────────
Реестр решал «какую книгу держать» (#3, #39–#45, #85–#87, #113) и «когда снять риск»
(#1, #48, #75, #110). Ни одна запись не спрашивала того, что для yield-агрегатора решается
КАЖДЫЙ раз при входе в протокол Ethena/Lido: **брать фиксированную ставку (купить PT) или
остаться на плавающей (держать сам sUSDe/eETH)?** Поле `underlying_yield` в
`pendle_pt_history.json` (4985 ненулевых строк) — плавающая ставка РЯДОМ с фиксированной,
в одном файле, на одну дату. Этот ряд не читала ни одна из 117 записей.

МЕХАНИЗМ. PT, купленный в день t на срок tau и додержанный до погашения, отдаёт РОВНО
свою `implied_yield` (он гасится в 1 — марк по пути не важен, если не выходить). Плавающая
нога за тот же отрезок отдаёт СЛОЖЕННУЮ реализованную `underlying_yield` день за днём.
Разница считается задним числом точно и без единого параметра:
        преимущество = implied_yield(t) − реализованная плавающая[t, t+tau)
Положительное в среднем ⇒ покупатель PT получает премию за то, что берёт фиксированную
сторону (её платит покупатель YT — плечо и очки). Это не тайминг и не сигнал: это цена
одной и той же ставки на двух рынках.

РАЗВИЛКА, КОТОРУЮ ОБЯЗАН РАЗЛИЧИТЬ ЗАМЕР. Ставки sUSDe за выборку упали 17.7 % → 4.3 %.
При монотонно падающей ставке фиксированная сторона выигрывает ВСЕГДА — и премия, и
односторонний тренд дают один и тот же знак. Различает их подвыборка, где плавающая
ставка за срок ВЫРОСЛА: если премия там сохраняется, она структурна; если исчезает —
это был тренд, и повторять его нечем.

ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА (2026-09-29):
  (1) премия положительна и крупна на полной выборке (сотни–тысяча bp);
  (2) она ПЕРЕЖИВЁТ подвыборку роста, но станет в разы меньше — то есть и премия, и тренд
      реальны, и большая часть заголовочного числа — тренд;
  (3) к 2026-му премия сожмётся до десятков bp и окажется НИЖЕ стоимости переката
      (96 bp round-trip, #10/#49) при 3–4 перекатах в год ⇒ как ЭДЖ мертва, хотя как
      ИЗМЕРЕНИЕ важна: «PT-carry» — тот самый рычаг, на который опирается книга
      pendle_pt_levered, и его затухание надо назвать числом.

МЕТОД
  (1) Винтаж = (день t, живой рынок). Фиксированная = implied_yield. Плавающая =
      произведение (1+uy_d)^(1/365) по дням [t, t+tau), приведённое к году. Винтаж
      берётся только если наблюдено >= 80 % дней срока (иначе НЕ ИЗМЕРЕНО, не ноль).
  (2) Сводка: полная выборка, по годам, по НЕПЕРЕСЕКАЮЩИМСЯ винтажам (перекрывающиеся
      окна — одно наблюдение) + двусторонний знаковый тест.
  (3) Различающая подвыборка: плавающая за срок ВЫРОСЛА против УПАЛА (среднее первых
      7 дней против последних 7).
  (4) Порог: правило «покупать PT только при спреде (implied − текущая плавающая) > h»,
      h выбран на TRAIN (< 2026-01-01), оценён на TEST (2026), против «всегда PT» и
      «всегда плавающая». Порог, который не бьёт «всегда PT», — не правило.
  (5) Экономика: измеренная частота перекатов (сколько раз за год приходится менять
      рынок, если держать до погашения) и BREAK-EVEN round-trip = премия/перекаты.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Dict, List, Optional

import _pt_history as H  # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO / "data"
SPLIT = "2026-01-01"
MIN_COVERAGE = 0.8      # доля дней срока, которую надо наблюдать, иначе винтаж НЕ ИЗМЕРЕН
MIN_TAU = 10            # короче — округление годовой ставки шумит сильнее самой премии
REGIME_EDGE_DAYS = 7
H_GRID_BP = (0.0, 100.0, 250.0, 500.0, 1000.0)
RT_GRID_BP = (0.0, 10.0, 25.0, 96.0)


def vintages(u: H.Underlying) -> List[dict]:
    if not u.has_float:
        return []
    fl = u.float_rates()
    fdays = sorted(fl)
    out: List[dict] = []
    for day in u.dates:
        for market, (tau, y, _tvl) in sorted(u.obs[day].items()):
            if tau < MIN_TAU:
                continue
            end = H.shift(day, tau)
            path = [(d, fl[d]) for d in fdays if day <= d < end]
            if len(path) < tau * MIN_COVERAGE:
                continue  # НЕ ИЗМЕРЕНО: плавающий путь неполон. Не подставляем ноль.
            growth = 1.0
            for _d, r in path:
                growth *= (1.0 + r) ** (1.0 / 365.0)
            realized_float = growth ** (365.0 / len(path)) - 1.0
            head = st.mean([r for _d, r in path[:REGIME_EDGE_DAYS]])
            tail = st.mean([r for _d, r in path[-REGIME_EDGE_DAYS:]])
            out.append(
                {
                    "date": day,
                    "market": market,
                    "tau": tau,
                    "fixed": y,
                    "realized_float": realized_float,
                    "advantage": y - realized_float,
                    "spread_at_entry": y - fl.get(day, path[0][1]),
                    "float_rose": tail > head,
                    "observed_days": len(path),
                }
            )
    return out


def _summary(recs: List[dict], key: str = "advantage") -> Optional[dict]:
    if not recs:
        return None
    v = [r[key] for r in recs]
    pos = sum(1 for x in v if x > 0)
    return {
        "n": len(v),
        "mean_bp": st.mean(v) * 1e4,
        "median_bp": st.median(v) * 1e4,
        "frac_positive": pos / len(v),
        "sign_test_p": H.sign_test_p(pos, len(v)),
    }


def roll_frequency(u: H.Underlying) -> Optional[dict]:
    """Сколько перекатов в год требует «держать PT до погашения и переходить в следующий».
    Меряется по ФАКТИЧЕСКОМУ листингу: в день перехода берётся самый длинный живой рынок."""
    dates = u.dates
    if not dates:
        return None
    pos: Optional[str] = None
    rolls = 0
    for day in dates:
        live = u.obs[day]
        if pos is None or pos not in live or live[pos][0] <= 1:
            cands = [l for l in u.legs(day) if l[0] > 1]
            if not cands:
                pos = None
                continue
            if pos is not None:
                rolls += 1
            pos = max(cands)[3]
    span = H.days(dates[0], dates[-1])
    if span <= 0:
        return None
    return {"rolls": rolls, "span_days": span, "rolls_per_year": rolls * 365.0 / span}


def threshold_rule(recs: List[dict]) -> dict:
    """h выбран на TRAIN, оценён на TEST. Сравнение: всегда PT · всегда плавающая."""
    train = [r for r in recs if r["date"] < SPLIT]
    test = [r for r in recs if r["date"] >= SPLIT]

    def score(sel: List[dict], pool: List[dict]) -> Optional[float]:
        """Средняя годовая ставка правила: взял PT — фиксированная, иначе плавающая."""
        if not pool:
            return None
        taken = {id(r) for r in sel}
        return st.mean([(r["fixed"] if id(r) in taken else r["realized_float"]) for r in pool])

    grid = []
    for h in H_GRID_BP:
        sel = [r for r in train if r["spread_at_entry"] * 1e4 >= h]
        grid.append({"h_bp": h, "n_taken": len(sel), "train_rate": score(sel, train)})
    usable = [g for g in grid if g["train_rate"] is not None]
    best = max(usable, key=lambda g: g["train_rate"]) if usable else None
    out = {
        "train_grid": grid,
        "chosen_h_bp": best["h_bp"] if best else None,
        "train_n": len(train),
        "test_n": len(test),
    }
    if best and test:
        sel = [r for r in test if r["spread_at_entry"] * 1e4 >= best["h_bp"]]
        out["test_rule_rate"] = score(sel, test)
        out["test_rule_taken"] = len(sel)
        out["test_always_pt"] = st.mean([r["fixed"] for r in test])
        out["test_always_float"] = st.mean([r["realized_float"] for r in test])
    return out


def run(data_dir: Path) -> dict:
    universe = H.load(data_dir)
    out: Dict[str, dict] = {}
    for name, u in sorted(universe.items()):
        if not u.has_float:
            out[name] = {
                "unmeasured": "нет ряда underlying_yield: актив не накапливает доход по построению "
                              "(все строки 0) — это свойство актива, а не пропуск наблюдения",
                "dates": len(u.dates),
            }
            continue
        recs = vintages(u)
        if not recs:
            out[name] = {
                "unmeasured": f"ни один винтаж не покрыт плавающим путём на {MIN_COVERAGE:.0%}",
                "dates": len(u.dates),
            }
            continue
        per_year: Dict[str, List[dict]] = {}
        for r in recs:
            per_year.setdefault(r["date"][:4], []).append(r)
        rose = [r for r in recs if r["float_rose"]]
        fell = [r for r in recs if not r["float_rose"]]
        rf = roll_frequency(u)
        year_adv = {y: _summary(v) for y, v in sorted(per_year.items())}
        latest = sorted(year_adv)[-1]
        be = None
        if rf and rf["rolls_per_year"] > 0 and year_adv[latest]:
            be = year_adv[latest]["mean_bp"] / rf["rolls_per_year"]
        out[name] = {
            "dates": len(u.dates),
            "float_disagreement_dates": u.float_disagreement(),
            "advantage_all": _summary(recs),
            "advantage_per_year": year_adv,
            "advantage_per_year_non_overlapping": {
                y: _summary(H.non_overlapping(v)) for y, v in sorted(per_year.items())
            },
            "advantage_non_overlapping": _summary(H.non_overlapping(recs)),
            "advantage_train": _summary([r for r in recs if r["date"] < SPLIT]),
            "advantage_test": _summary([r for r in recs if r["date"] >= SPLIT]),
            "regime_float_rose": _summary(rose),
            "regime_float_fell": _summary(fell),
            "median_fixed_per_year": {
                y: st.median([r["fixed"] for r in v]) for y, v in sorted(per_year.items())
            },
            "median_float_per_year": {
                y: st.median([r["realized_float"] for r in v]) for y, v in sorted(per_year.items())
            },
            "rolls": rf,
            "latest_year": latest,
            "break_even_round_trip_bp": be,
            "rule": threshold_rule(recs),
        }
    return {"split": SPLIT, "rt_grid_bp": list(RT_GRID_BP), "per_underlying": out}


def _fmt(s: Optional[dict]) -> str:
    if not s:
        return "НЕ ИЗМЕРЕНО"
    p = s["sign_test_p"]
    return (f"n={s['n']:4d} mean={s['mean_bp']:+7.0f} bp  med={s['median_bp']:+6.0f} bp  "
            f"frac>0={s['frac_positive']:.2f}  sign-p={'n/a' if p is None else format(p, '.3f')}")


def report(o: dict) -> None:
    print("=" * 100)
    print("IDEA #118 PTFF — фиксированная ставка PT против реализованной плавающей  "
          "[bt] [L1 — реальный ряд] · advisory")
    print("=" * 100)
    for name, v in o["per_underlying"].items():
        print(f"\n### {name}  ({v['dates']} дат)")
        if "unmeasured" in v:
            print(f"  НЕ ИЗМЕРЕНО: {v['unmeasured']}")
            continue
        print(f"  расхождение плавающей между рынками одной даты: {v['float_disagreement_dates']} дат "
              f"(берётся медиана)")
        print("  1. преимущество фиксированной (implied − реализованная плавающая):")
        print(f"       всего            {_fmt(v['advantage_all'])}")
        for y, s in v["advantage_per_year"].items():
            mf = v["median_fixed_per_year"][y] * 100
            ml = v["median_float_per_year"][y] * 100
            nz = v["advantage_per_year_non_overlapping"][y]
            indep = "НЕ ИЗМЕРЕНО" if not nz else f"{nz['n']} независимых винтажей"
            print(f"       {y}  fixed {mf:5.2f}% / float {ml:5.2f}%   {_fmt(s)}   [{indep}]")
        print(f"       непересекающиеся {_fmt(v['advantage_non_overlapping'])}")
        print(f"       TRAIN (<{o['split']}) {_fmt(v['advantage_train'])}")
        print(f"       TEST  (>={o['split']}) {_fmt(v['advantage_test'])}")
        print("  2. различающая подвыборка (премия или односторонний тренд?):")
        print(f"       плавающая ВЫРОСЛА за срок  {_fmt(v['regime_float_rose'])}")
        print(f"       плавающая УПАЛА  за срок  {_fmt(v['regime_float_fell'])}")
        rf = v["rolls"]
        if rf:
            print(f"  3. экономика: перекатов {rf['rolls']} за {rf['span_days']} дней = "
                  f"{rf['rolls_per_year']:.1f}/год (держать до погашения, брать самый длинный живой)")
            be = v["break_even_round_trip_bp"]
            if be is None:
                print("       BREAK-EVEN round-trip: НЕ ИЗМЕРЕН")
            else:
                print(f"       BREAK-EVEN round-trip по последнему году ({v['latest_year']}): "
                      f"{be:.0f} bp  — против измеренных 96 bp (#10/#49)")
                for rt in o["rt_grid_bp"]:
                    net = v["advantage_per_year"][v["latest_year"]]["mean_bp"] - rt * rf["rolls_per_year"]
                    print(f"         rt={rt:5.0f} bp ⇒ нетто-преимущество {net:+8.0f} bp/год")
        r = v["rule"]
        print(f"  4. порог: h выбран на TRAIN = "
              f"{'НЕ ИЗМЕРЕН' if r['chosen_h_bp'] is None else format(r['chosen_h_bp'], '.0f') + ' bp'} "
              f"(TRAIN n={r['train_n']}, TEST n={r['test_n']})")
        if "test_rule_rate" in r:
            print(f"       TEST: правило {r['test_rule_rate']*100:5.2f}% (взято {r['test_rule_taken']}/{r['test_n']}) · "
                  f"всегда PT {r['test_always_pt']*100:5.2f}% · всегда плавающая "
                  f"{r['test_always_float']*100:5.2f}%")
            if r["test_rule_rate"] <= r["test_always_pt"] + 1e-12:
                print("       ⇒ порог НЕ бьёт «всегда PT»: правила нет, есть только премия")
        else:
            print("       TEST: НЕ ИЗМЕРЕН (нет винтажей в TEST)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#118 PTFF PT fixed vs realized float (advisory)")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        out = run(a.data_dir)
    except H.Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        return 3
    report(out)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
