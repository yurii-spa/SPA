#!/usr/bin/env python3
"""
IDEA #117 — PTTS: Pendle PT Term Structure («что знает кривая PT о будущей ставке?»)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the fleet or the dashboard. Reads data/rates_desk/pendle_pt_history.json READ-ONLY.
stdlib-only, deterministic, LLM FORBIDDEN.

ПОЧЕМУ ЭТО НОВАЯ ГИПОТЕЗА (поиск по МЕХАНИЗМУ, а не по аббревиатуре — урок #114)
────────────────────────────────────────────────────────────────────────────────
В реестре 116 записей. Слова `implied_yield`, `maturity` не встречаются в нём ни разу;
`pendle_pt_history.json` упомянут ОДИН раз — и ровно как отсутствующий («не в cloud
checkout», #? оговорка к rates-carry). Единственное место, где PT-ставка вообще вошла в
число, — КОНТРОЛЬНАЯ строка таблицы #76 (один агрегированный ряд, 852 дня). Срочная
структура — 42 рынка с РАЗНЫМИ датами погашения, живущие одновременно, — не читалась
никогда. #24 VTST мерил срочную структуру ВОЛАТИЛЬНОСТИ, это другой ряд и другой вопрос.

МЕХАНИЗМ. В один день у одного базового актива живут несколько PT с разными сроками.
Разница их ставок — кривая. У кривой есть ровно одно проверяемое утверждение: заложенная
в неё ФОРВАРДНАЯ ставка на отрезок [t+tau_s, t+tau_l]. Её можно сверить с тем, что
реализовалось, — тот же самый длинный рынок, наблюдённый в день t+tau_s, имеет срок
ровно tau_l−tau_s. Сверка точна и причинна по построению: форвард считается из строк
дня t, реализация читается строго позже.

Смещение = реализовано − форвард. Знак говорит, какой срок выгоднее держать:
  bias > 0 ⇒ ставки упали МЕНЬШЕ, чем заложено ⇒ выгоднее короткий PT + перекат;
  bias < 0 ⇒ ставки упали БОЛЬШЕ, чем заложено ⇒ выгоднее держать длинный PT.
Это и есть «лестница против длинного» — но посчитанное без опоры на то, какие сроки
случайно оказались в листинге в нужный день.

ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА (2026-09-29):
  (1) кривая окажется ИНВЕРТИРОВАННОЙ (короткий PT платит больше длинного) — потому что
      спрос на плечо/очки живёт в коротком конце;
  (2) смещение на стейблах будет неотличимо от нуля по медиане (кривая честна);
  (3) на LST/LRT смещение будет отрицательным и большим (ставки 2024-го падали быстрее,
      чем закладывала кривая), но проверить это ВНЕ ВЫБОРКИ будет НЕ НА ЧЕМ — эти рынки
      умирают в 2024-м. Тогда верный исход — «не измерено вне выборки», а не «эдж есть».

МЕТОД
  (A) Форма кривой: наклон (y_long − y_short) на 30 дней дополнительного срока, по годам.
  (B) Несмещённость форварда: bias по всем парам, по годам, и по НЕПЕРЕСЕКАЮЩИМСЯ
      винтажам (перекрывающиеся окна — одно наблюдение, а не сто) + знаковый тест.
  (C) Положительный контроль различающей силы: та же мера с ЗАГЛЯДЫВАНИЕМ (форвард
      строится из будущей строки). Если причинная и заглядывающая колонки не расходятся,
      мера не различает гипотезы и вывод делать нельзя.
  (D) Идентифицируемость «лестницы»: сколько дней подряд цель-срок 30 и цель-срок 180
      выбирают ОДИН И ТОТ ЖЕ рынок. Совпадение ⇒ сравнение сроков на этой панели
      НЕ ИЗМЕРЕНО (названная причина), а не «разницы нет».
  (E) Прямой симулятор лестницы — ЧТОБЫ п. (D) был не доводом, а ЗАМЕРОМ. Держать PT с
      целевым сроком до погашения, перекатываться в ближайший к цели живой рынок; марк по
      ВЫВЕДЕННОЙ цене, издержка rt на перекат. Если разные цели дают ПОБИТОВО одинаковую
      кривую, вырождение показано числом, а не рассуждением о листинге. Числа реестра
      берутся отсюда, а не из черновика: иначе они невоспроизводимы.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Dict, List, Optional

import _pt_history as H  # noqa: E402  (same directory, stdlib-only)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO / "data"
SPLIT = "2026-01-01"
MIN_GAP_DAYS = 20   # ближе этого две ноги — один срок, наклон считать не на чем
MIN_SHORT_TAU = 5   # у истекающего рынка котировка тонкая; tau в знаменателе множит шум
LADDER_TARGETS = (30, 180)
SIM_TARGETS = (30, 60, 90, 120, 180)
SIM_RT_BP = (0.0, 96.0)


def _forward_rate(tau_s: float, y_s: float, tau_l: float, y_l: float) -> float:
    """Ставка, заложенная кривой на отрезок [t+tau_s, t+tau_l]."""
    p_s = H.pt_price(y_s, tau_s)
    p_l = H.pt_price(y_l, tau_l)
    return (p_s / p_l) ** (365.0 / (tau_l - tau_s)) - 1.0


def curve_shape(u: H.Underlying) -> Optional[dict]:
    slopes: List[float] = []
    per_year: Dict[str, List[float]] = {}
    for day in u.dates:
        legs = u.legs(day)
        if len(legs) < 2:
            continue
        (ts, ys, _, _), (tl, yl, _, _) = legs[0], legs[-1]
        if tl - ts < MIN_GAP_DAYS or ts < MIN_SHORT_TAU:
            continue
        slope = (yl - ys) / ((tl - ts) / 30.0)
        slopes.append(slope)
        per_year.setdefault(day[:4], []).append(slope)
    if not slopes:
        return None
    return {
        "n": len(slopes),
        "median_slope_per_30d_bp": st.median(slopes) * 1e4,
        "mean_slope_per_30d_bp": st.mean(slopes) * 1e4,
        "frac_upward": sum(1 for s in slopes if s > 0) / len(slopes),
        "per_year": {
            y: {
                "n": len(v),
                "median_bp": st.median(v) * 1e4,
                "frac_upward": sum(1 for s in v if s > 0) / len(v),
            }
            for y, v in sorted(per_year.items())
        },
    }


def forward_bias(u: H.Underlying, look_ahead: bool = False) -> List[dict]:
    """Смещение форварда. look_ahead=True — КОНТРОЛЬ: форвард строится из будущей строки
    (день реализации), то есть заведомо знает ответ. Причинная ветка будущего не видит."""
    out: List[dict] = []
    for day in u.dates:
        legs = u.legs(day)
        if len(legs) < 2:
            continue
        (ts, ys, _, ks), (tl, yl, _, kl) = legs[0], legs[-1]
        if tl - ts < MIN_GAP_DAYS or ts < MIN_SHORT_TAU:
            continue
        future = H.shift(day, ts)
        if future not in u.obs or kl not in u.obs[future]:
            continue
        realized = u.obs[future][kl][1]
        if look_ahead:
            # контроль: длинную ногу берём уже ЗНАЯ день реализации
            fwd = _forward_rate(ts, ys, tl, realized)
        else:
            fwd = _forward_rate(ts, ys, tl, yl)
        out.append(
            {
                "date": day,
                "tau": ts,
                "tau_long": tl,
                "short_market": ks,
                "long_market": kl,
                "forward": fwd,
                "realized": realized,
                "bias": realized - fwd,
            }
        )
    return out


def _summary(records: List[dict]) -> Optional[dict]:
    if not records:
        return None
    b = [r["bias"] for r in records]
    pos = sum(1 for x in b if x > 0)
    return {
        "n": len(b),
        "mean_bp": st.mean(b) * 1e4,
        "median_bp": st.median(b) * 1e4,
        "frac_positive": pos / len(b),
        "sign_test_p": H.sign_test_p(pos, len(b)),
    }


def ladder_identifiability(u: H.Underlying) -> dict:
    """Выбирают ли цель-срок 30 и цель-срок 180 один и тот же рынок?"""
    same = 0
    total = 0
    choices: Dict[int, List[str]] = {t: [] for t in LADDER_TARGETS}
    for day in u.dates:
        legs = [l for l in u.legs(day) if l[0] >= MIN_SHORT_TAU]
        if not legs:
            continue
        total += 1
        picked = {}
        for target in LADDER_TARGETS:
            picked[target] = min(legs, key=lambda l: abs(l[0] - target))[3]
            choices[target].append(picked[target])
        if len(set(picked.values())) == 1:
            same += 1
    return {
        "days": total,
        "days_same_market": same,
        "frac_same": (same / total) if total else None,
        "distinct_markets_short": len(set(choices[LADDER_TARGETS[0]])),
        "distinct_markets_long": len(set(choices[LADDER_TARGETS[-1]])),
    }


def simulate_ladder(u: H.Underlying, target_days: int, rt_bp: float) -> Optional[dict]:
    """Держать PT с целевым сроком до погашения; на погашении перейти в ближайший к цели
    живой рынок. Марк — по ВЫВЕДЕННОЙ цене (наблюдённой в ряде нет ни одной). Причинно:
    решение дня принимается по строкам этого же дня, цена входа берётся из них же."""
    dates = u.dates
    if len(dates) < 2:
        return None
    equity = 1.0
    pos: Optional[str] = None
    entry_px = 1.0
    rolls = 0
    curve: List[float] = []
    entries: List[dict] = []
    for day in dates:
        live = u.obs[day]
        if pos is not None and pos in live:
            tau, y, _ = live[pos]
            curve.append(equity * H.pt_price(y, tau) / entry_px)
        elif pos is not None:
            curve.append(equity / entry_px)          # погасился в 1
        else:
            curve.append(equity)
        if pos is not None and pos in live and live[pos][0] > 1:
            continue
        if pos is not None:                           # реализовать и заплатить за перекат
            if pos in live:
                tau, y, _ = live[pos]
                equity *= H.pt_price(y, tau) / entry_px
            else:
                equity /= entry_px
            equity *= 1.0 - rt_bp / 1e4
            rolls += 1
        cands = [l for l in u.legs(day) if l[0] >= MIN_SHORT_TAU]
        if not cands:
            pos = None
            continue
        tau, y, _tvl, market = min(cands, key=lambda l: abs(l[0] - target_days))
        pos, entry_px = market, H.pt_price(y, tau)
        # запись входа — чтобы «цена входа взята из строк ТОГО ЖЕ дня» можно было
        # проверить тестом, а не только заявить в комментарии
        entries.append({"day": day, "market": market, "tau": tau, "implied_yield": y})
    span = H.days(dates[0], dates[-1])
    if span <= 0 or curve[0] <= 0:
        return None
    final = curve[-1] / curve[0]
    peak = float("-inf")
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return {
        "target_days": target_days,
        "rt_bp": rt_bp,
        "ann_pct": (final ** (365.0 / span) - 1.0) * 100.0,
        "max_dd_pct": max_dd * 100.0,
        "rolls": rolls,
        "span_days": span,
        "entries": entries,
        # отпечаток кривой: две цели, давшие один и тот же путь, обязаны быть НАЗВАНЫ
        "curve_fingerprint": tuple(round(v, 12) for v in curve),
    }


def run(data_dir: Path) -> dict:
    universe = H.load(data_dir)
    out: Dict[str, dict] = {}
    for name, u in sorted(universe.items()):
        sims = [r for r in (simulate_ladder(u, t, rt) for rt in SIM_RT_BP for t in SIM_TARGETS)
                if r is not None]
        degenerate = []
        for rt in SIM_RT_BP:
            rows = [r for r in sims if r["rt_bp"] == rt]
            seen: Dict[tuple, int] = {}
            for r in rows:
                first = seen.setdefault(r["curve_fingerprint"], r["target_days"])
                if first != r["target_days"]:
                    degenerate.append({"rt_bp": rt, "target_days": r["target_days"],
                                       "identical_to_target_days": first})
        for r in sims:
            r.pop("curve_fingerprint", None)
            r.pop("entries", None)
        causal = forward_bias(u, look_ahead=False)
        control = forward_bias(u, look_ahead=True)
        per_year: Dict[str, dict] = {}
        for r in causal:
            per_year.setdefault(r["date"][:4], []).append(r)
        nonov = H.non_overlapping(causal)
        out[name] = {
            "dates": len(u.dates),
            "curve": curve_shape(u),
            "bias_all": _summary(causal),
            "bias_per_year": {y: _summary(v) for y, v in sorted(per_year.items())},
            "bias_per_year_non_overlapping": {
                y: _summary(H.non_overlapping(v)) for y, v in sorted(per_year.items())
            },
            "bias_non_overlapping": _summary(nonov),
            "bias_train": _summary([r for r in causal if r["date"] < SPLIT]),
            "bias_test": _summary([r for r in causal if r["date"] >= SPLIT]),
            "control_look_ahead": _summary(control),
            "ladder": ladder_identifiability(u),
            "ladder_sim": sims,
            "ladder_sim_degenerate": degenerate,
        }
    return {"split": SPLIT, "per_underlying": out}


def _fmt(s: Optional[dict]) -> str:
    if not s:
        return "НЕ ИЗМЕРЕНО (нет пар с реализацией)"
    p = s["sign_test_p"]
    return (f"n={s['n']:4d} mean={s['mean_bp']:+7.0f} bp  med={s['median_bp']:+6.0f} bp  "
            f"frac>0={s['frac_positive']:.2f}  sign-p={'n/a' if p is None else format(p, '.3f')}")


def report(o: dict) -> None:
    print("=" * 96)
    print("IDEA #117 PTTS — срочная структура Pendle PT  [bt] [L1 — реальный ряд] · advisory only")
    print("=" * 96)
    for name, v in o["per_underlying"].items():
        c = v["curve"]
        print(f"\n### {name}  ({v['dates']} дат)")
        if not c:
            print("  КРИВАЯ: НЕ ИЗМЕРЕНА — нет дней с двумя живыми сроками (>= "
                  f"{MIN_GAP_DAYS} дней разницы)")
        else:
            print(f"  A. форма кривой: n={c['n']:4d}  медианный наклон {c['median_slope_per_30d_bp']:+7.0f} bp "
                  f"на 30 дней срока · доля ВОСХОДЯЩИХ дней {c['frac_upward']:.2f}")
            for y, pv in c["per_year"].items():
                print(f"       {y}: n={pv['n']:4d} медиана {pv['median_bp']:+7.0f} bp  доля восх. {pv['frac_upward']:.2f}")
        print(f"  B. смещение форварда (реализовано − форвард), ПРИЧИННОЕ:")
        print(f"       всего            {_fmt(v['bias_all'])}")
        for y, s in v["bias_per_year"].items():
            nz = v["bias_per_year_non_overlapping"][y]
            indep = "НЕ ИЗМЕРЕНО" if not nz else f"{nz['n']} независимых винтажей"
            print(f"       {y}             {_fmt(s)}   [{indep}]")
        print(f"       непересекающиеся {_fmt(v['bias_non_overlapping'])}")
        print(f"       TRAIN (<{o['split']}) {_fmt(v['bias_train'])}")
        print(f"       TEST  (>={o['split']}) {_fmt(v['bias_test'])}")
        ctl = v["control_look_ahead"]
        base = v["bias_all"]
        if ctl and base:
            delta = abs(ctl["mean_bp"] - base["mean_bp"])
            verdict = "мера РАЗЛИЧАЕТ гипотезы" if delta > 1.0 else "⚠️ мера НЕ различает — вывод делать нельзя"
            print(f"  C. контроль с заглядыванием: mean={ctl['mean_bp']:+7.0f} bp против причинных "
                  f"{base['mean_bp']:+7.0f} bp ⇒ {verdict}")
        else:
            print("  C. контроль с заглядыванием: НЕ ИЗМЕРЕН")
        l = v["ladder"]
        if l["frac_same"] is None:
            print("  D. идентифицируемость лестницы: НЕ ИЗМЕРЕНА — нет дней с живым рынком")
        else:
            print(f"  D. идентифицируемость лестницы: цель-30 и цель-180 выбирают ОДИН рынок в "
                  f"{l['frac_same']:.0%} дней ({l['days_same_market']}/{l['days']}); "
                  f"различных рынков: короткий {l['distinct_markets_short']}, длинный {l['distinct_markets_long']}")
            if l["frac_same"] > 0.5:
                print("       ⇒ сравнение сроков на этой панели НЕ ИЗМЕРЕНО: листинг не содержит "
                      "двух сроков одновременно чаще, чем содержит. Это причина, а не результат.")
        sim = v.get("ladder_sim") or []
        if not sim:
            print("  E. прямой симулятор лестницы: НЕ ИЗМЕРЕН (нет живых рынков)")
        else:
            print("  E. прямой симулятор лестницы (держать до погашения, марк по ВЫВЕДЕННОЙ цене):")
            for r in sim:
                print(f"       цель {r['target_days']:3d}д  rt={r['rt_bp']:4.0f}bp ⇒ "
                      f"APY {r['ann_pct']:6.2f}%  maxDD {r['max_dd_pct']:5.2f}%  "
                      f"перекатов {r['rolls']:3d} за {r['span_days']}д")
            for d in v.get("ladder_sim_degenerate") or []:
                print(f"       ⚠️ rt={d['rt_bp']:.0f}bp: цель {d['target_days']}д даёт ПОБИТОВО ту же "
                      f"кривую, что цель {d['identical_to_target_days']}д — вырождение ИЗМЕРЕНО")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#117 PTTS Pendle PT term structure (advisory)")
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
