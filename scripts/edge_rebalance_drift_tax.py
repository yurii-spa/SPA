#!/usr/bin/env python3
"""Идеи реестра #49 RDT и #50 NTB — счёт, который не выставлен ни одной записи реестра.

═══════════════════════════════════════════════════════════════════════════════════════════
ЧТО ЭТОТ ЗАМЕР НЕ ДЕЛАЕТ
═══════════════════════════════════════════════════════════════════════════════════════════
* `IS_ADVISORY=True`, `OUTSIDE_RISKPOLICY=True`, evidence **L0** (бэктест на реальной истории,
  не живые деньги). Капитал не двигается, RiskPolicy v1.0 и пороги kill-switch не меняются
  ни строкой, живой трек `data/equity_curve_daily.json` не читается и не пишется.
* Здесь нет нового сигнала и нового критерия демоушена. Правила берутся готовыми из #39/#40/#45,
  меняется РОВНО ОДНО: как считается счёт за то, чтобы эти правила реально держать.

═══════════════════════════════════════════════════════════════════════════════════════════
#49 RDT — Rebalance Drift Tax: «удержание постоянного веса — это сделка, и она не оплачена»
═══════════════════════════════════════════════════════════════════════════════════════════
Каждая запись реестра начиная с #32 считает доходность портфеля как ``Σ_b w_b(t)·r_b(t)`` при
целевых весах ``w``. Это ровно то же самое, что **ежедневно возвращать веса к цели**: если бы
веса не возвращали, завтрашний вес был бы не ``w_b(t+1)``, а дрейфовавший
``w_b(t)(1+r_b(t))/G(t)``. То есть путь доходности, на котором построены все 48 вердиктов, УЖЕ
предполагает ежедневную сделку.

А счёт за неё выставлен по формуле ``48 bp × Σ_b |w_b(t) − w_b(t−1)|`` — по изменению ЦЕЛИ.
Строка с постоянной целью (`raw`, и, что важнее, решающий контроль `static-matched`) получает
в этой формуле **турновер РОВНО НОЛЬ** — при том что удержать постоянный вес на книгах с разной
доходностью без сделок невозможно.

Правильная база — не предыдущая ЦЕЛЬ, а вчерашний ДРЕЙФОВАВШИЙ вес:

    turnover_impl(t) = Σ_b | w_b(t) − w_b(t−1)(1+r_b(t−1))/G(t−1) |

Разница ``turnover_impl − turnover_target`` и есть налог на дрейф — неоплаченная часть счёта.
Вопрос идеи: (1) сколько он стоит, (2) одинаков ли он для всех правил (если нет — он меняет не
уровень, а СРАВНЕНИЕ), (3) переворачивает ли он хоть один вердикт реестра.

═══════════════════════════════════════════════════════════════════════════════════════════
#50 NTB — No-Trade Band: «а если возвращать вес не каждый день»
═══════════════════════════════════════════════════════════════════════════════════════════
Прямое следствие #49: если удержание цели стоит денег, значит есть ручка — **полоса
безразличия**. Вес возвращается к цели только когда он ушёл дальше ``band``; между сделками
веса свободно дрейфуют.

Одно исключение, и оно не косметическое: **смена ПРИГОДНОСТИ книги (0 ↔ положительный вес)
торгуется ВСЕГДА, независимо от полосы.** Демоушен — это решение о риске, а не о размере, и
экономить на нём полосой значит подменять правило риска правилом издержек (fail-CLOSED).

Обязательный контроль, без которого число ничего не значит: **случайное расписание той же
частоты.** Если полоса не бьёт случайные дни при равном числе ребалансов, то работает частота,
а не момент — и продавать это как правило тайминга запрещено.

Запуск:
    python3 scripts/edge_rebalance_drift_tax.py            # обе записи целиком
    python3 scripts/edge_rebalance_drift_tax.py --idea 49  # только налог на дрейф
    python3 scripts/edge_rebalance_drift_tax.py --idea 50  # только полоса + контроли
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                 # noqa: E402  загрузчик панели и метрики #32
import edge_capital_recycling as ecr            # noqa: E402  аллокаторы/издержки/метрики #38/#39
import edge_cross_sectional_demotion as xsd     # noqa: E402  ранговая машина состояний #40
import edge_drift_gated_overlay as dgo          # noqa: E402  панель #35/#36/#37
import edge_redundancy_demotion as erd          # noqa: E402  признаки #44/#45

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

TRAIN_END = ecr.TRAIN_END                       # "2025-06-30" — сплит реестра, здесь НЕ подбирается
COST_BP_ROUND_TRIP = ecr.COST_BP_ROUND_TRIP     # 96 bp (#10), тот же, что у всех записей
BP = cfpt.BP
EPS = 1e-12

REF_K, REF_M = 2, 20                            # опорная ячейка #40, унаследована, не перетюнена
DEFAULT_BANDS: Tuple[Optional[float], ...] = (None, 0.01, 0.03, 0.05, 0.10, 0.20)
DEFAULT_COUNTS: Tuple[int, ...] = (180, 90, 45, 20, 10, 5, 2, 0)
CONTROL_SEEDS = 20


# ═══════════════════════════════ механика дрейфа ═══════════════════════════════
def drifted_weights(weights: Dict[str, float], rets: Dict[str, float],
                    cash_annual: float = 0.0) -> Dict[str, float]:
    """Веса на начало следующего дня, если сегодня НЕ торговали.

    Незанятая часть (``1 − Σw``) — кэш, он растёт по ``cash_annual`` и остаётся кэшем: дрейф
    не переливает капитал между кэшем и книгами, он только меняет их пропорции. Сумма
    ``Σv_b + cash`` равна 1 по построению, что закреплено тестом.

    Портфель, потерявший всю стоимость (``G ≤ 0``), — не состояние, а признак сломанной панели:
    возвращать «какие-нибудь» веса тут значит выдумать состояние, поэтому отказ (fail-CLOSED).
    """
    books = list(weights)
    cash = 1.0 - sum(weights[b] for b in books)
    gross = sum(weights[b] * (1.0 + rets[b]) for b in books) + cash * (1.0 + cash_annual / 365.0)
    if gross <= EPS:
        raise ValueError("портфель обнулился — дрейф от нулевой базы не определён (fail-CLOSED)")
    return {b: weights[b] * (1.0 + rets[b]) / gross for b in books}


def target_turnover(panel: "dgo.Panel", weights: Dict[str, List[float]]) -> float:
    """Счёт, который выставляет реестр СЕГОДНЯ: изменение ЦЕЛИ, годовая величина.

    Это буквально формула `ecr.portfolio_metrics`, вынесенная отдельно, чтобы её можно было
    поставить рядом с настоящей и чтобы тест мог закрепить их равенство.
    """
    total = 0.0
    for b in panel.books:
        for i in range(1, panel.n):
            total += abs(weights[b][i] - weights[b][i - 1])
    return total * 365.0 / panel.n


def implementation_turnover(panel: "dgo.Panel", weights: Dict[str, List[float]],
                            cash_annual: float = 0.0) -> float:
    """Счёт, который выставила бы реальность: изменение от ДРЕЙФОВАВШЕГО веса, годовая величина.

    Никогда не меньше `target_turnover` (неравенство треугольника), и равен ему ровно тогда,
    когда дрейфа нет — то есть когда все книги за день дали одинаковую доходность. Оба
    утверждения закреплены тестами, второе — в обе стороны.
    """
    total = 0.0
    prev: Optional[Dict[str, float]] = None
    for i in range(panel.n):
        cur = {b: weights[b][i] for b in panel.books}
        if prev is not None:
            total += sum(abs(cur[b] - prev[b]) for b in panel.books)
        prev = drifted_weights(cur, {b: panel.rets[b][i] for b in panel.books}, cash_annual)
    return total * 365.0 / panel.n


def turnover_attribution(panel: "dgo.Panel", weights: Dict[str, List[float]],
                         cash_annual: float = 0.0) -> Dict[str, float]:
    """Доля каждой книги в НАСТОЯЩЕМ турновере. Суммы долей = 1 (закреплено тестом).

    Нужна затем, что налог на дрейф — не общий множитель: если его платит одна книга, то любое
    правило, выключающее именно её, экономит счёт, которого реестр не видит.
    """
    per = {b: 0.0 for b in panel.books}
    prev: Optional[Dict[str, float]] = None
    for i in range(panel.n):
        cur = {b: weights[b][i] for b in panel.books}
        if prev is not None:
            for b in panel.books:
                per[b] += abs(cur[b] - prev[b])
        prev = drifted_weights(cur, {b: panel.rets[b][i] for b in panel.books}, cash_annual)
    total = sum(per.values())
    if total <= EPS:
        return {b: 0.0 for b in panel.books}
    return {b: per[b] / total for b in panel.books}


# ═══════════════════════════════ прогон с полосой / расписанием ═══════════════════════════════
def rebalance_run(panel: "dgo.Panel", weights: Dict[str, List[float]],
                  band: Optional[float] = None,
                  schedule: Optional[Set[int]] = None,
                  cash_annual: float = 0.0,
                  cost_bp_round_trip: float = COST_BP_ROUND_TRIP) -> Dict[str, float]:
    """Настоящий путь портфеля при заданной политике возврата к цели.

    * ``band is None and schedule is None`` — точный ежедневный возврат. Это **конвенция всего
      реестра**, и в этом режиме доходность и просадка обязаны совпасть с `ecr.portfolio_metrics`
      до последнего знака (закреплено тестом): движок ничего не меняет в модели, он только
      выставляет ей счёт.
    * ``band`` — полоса безразличия: торгуем, когда максимальное отклонение от цели больше полосы.
    * ``schedule`` — заданное множество дней (контроль равной частоты). Полоса при этом не смотрится.
    * Смена ПРИГОДНОСТИ (вес 0 ↔ >0) торгуется всегда — риск не экономится издержками.
    """
    if band is not None and band < 0.0:
        raise ValueError("полоса не может быть отрицательной")
    books, n = panel.books, panel.n
    actual = {b: weights[b][0] for b in books}
    turnover = 0.0
    rebalance_days = 0
    rets: List[float] = []
    for i in range(n):
        target = {b: weights[b][i] for b in books}
        flip = any((target[b] <= EPS) != (actual[b] <= EPS) for b in books)
        if schedule is not None:
            trade = flip or (i in schedule)
        elif band is None:
            trade = True
        else:
            trade = flip or max(abs(actual[b] - target[b]) for b in books) > band
        if trade:
            moved = sum(abs(target[b] - actual[b]) for b in books)
            if moved > EPS:
                rebalance_days += 1
            turnover += moved
            actual = dict(target)
        deployed = sum(actual[b] for b in books)
        rets.append(sum(actual[b] * panel.rets[b][i] for b in books)
                    + (1.0 - deployed) * cash_annual / 365.0)
        actual = drifted_weights(actual, {b: panel.rets[b][i] for b in books}, cash_annual)
    perf = cfpt.perf(rets)
    turnover_yr = turnover * 365.0 / n
    cost_bp_yr = 0.5 * cost_bp_round_trip * turnover_yr
    return {
        "apy": perf["apy"],
        "maxdd": perf["maxdd"],
        "calmar": perf["calmar"],
        "turnover_yr": turnover_yr,
        "cost_bp_yr": cost_bp_yr,
        "net_apy_after_cost": perf["apy"] - cost_bp_yr / BP,
        "rebalance_days": float(rebalance_days),
    }


def random_schedules(n: int, days: int, seeds: int = CONTROL_SEEDS,
                     seed0: int = 7000) -> List[Set[int]]:
    """Контроль равной частоты: `seeds` расписаний ровно по `days` дней. Детерминирован по seed."""
    if days < 0:
        raise ValueError("число ребалансов не может быть отрицательным")
    take = min(days, n)
    return [set(random.Random(seed0 + s).sample(range(n), take)) for s in range(seeds)]


# ═══════════════════════════════ набор правил ═══════════════════════════════
def rule_weights(panel: "dgo.Panel") -> List[Tuple[str, Dict[str, List[float]]]]:
    """Правила реестра, взятые как есть. Ни одно здесь не изобретается и не перетюнивается."""
    books, n = panel.books, panel.n
    equal = 1.0 / len(books)
    xsd_flags = xsd.rank_demotion_flags(erd.panel_scores(panel, "drift"), REF_K, REF_M)
    return [
        ("raw равные веса", {b: [equal] * n for b in books}),
        ("#39 CDR абс. M=20",
         ecr.alloc_recycle(books, xsd.absolute_flags(panel, xsd.HURDLE, xsd.LOOKBACK, 20), n)),
        (f"#40 XSD k={REF_K} M={REF_M}", ecr.alloc_recycle(books, xsd_flags, n)),
        ("#45 XVD k=1 M=1",
         ecr.alloc_recycle(books, xsd.rank_demotion_flags(
             erd.panel_scores(panel, "volatility"), 1, 1), n)),
        ("КОНТРОЛЬ static-matched #40", ecr.alloc_static_matched(
            ecr.alloc_recycle(books, xsd_flags, n))),
    ]


# ═══════════════════════════════ отчёты ═══════════════════════════════
def _fmt_pct(x: float) -> str:
    return f"{x * 100:6.2f}%"


def idea49_rdt(subset: Optional[Sequence[str]] = None,
               label: str = "все 10 реальных книг") -> Dict[str, Dict[str, float]]:
    """Таблица #49: счёт реестра против настоящего счёта, по всем опорным правилам."""
    panel = dgo.Panel(subset, None, None)
    print(f"\n#49 RDT — НАЛОГ НА ДРЕЙФ ВЕСОВ ({label}, {panel.n} дней, "
          f"{panel.axis[0]}..{panel.axis[-1]})")
    print("Счёт реестра считает изменение ЦЕЛИ; настоящий — отклонение от вчерашнего ДРЕЙФА.")
    print(f"{'правило':26s} {'APY':>7s} {'maxDD':>7s} {'turn_цель':>10s} {'turn_факт':>10s} "
          f"{'счёт bp':>8s} {'факт bp':>8s} {'netAPY реестра':>15s} {'netAPY факт':>12s}")
    out: Dict[str, Dict[str, float]] = {}
    for name, w in rule_weights(panel):
        metrics = ecr.portfolio_metrics(panel, w)
        t_target = target_turnover(panel, w)
        t_impl = implementation_turnover(panel, w)
        bill_old = 0.5 * COST_BP_ROUND_TRIP * t_target
        bill_true = 0.5 * COST_BP_ROUND_TRIP * t_impl
        row = {
            "apy": metrics["apy"], "maxdd": metrics["maxdd"],
            "turnover_target": t_target, "turnover_impl": t_impl,
            "bill_bp_registry": bill_old, "bill_bp_true": bill_true,
            "net_registry": metrics["apy"] - bill_old / BP,
            "net_true": metrics["apy"] - bill_true / BP,
        }
        out[name] = row
        print(f"{name:26s} {_fmt_pct(row['apy'])} {_fmt_pct(row['maxdd'])} "
              f"{t_target:10.3f} {t_impl:10.3f} {bill_old:8.1f} {bill_true:8.1f} "
              f"{_fmt_pct(row['net_registry']):>15s} {_fmt_pct(row['net_true']):>12s}")

    print("\nКто платит настоящий счёт (доля книги в турновере raw) — и кого выключает #45 XVD:")
    equal = 1.0 / len(panel.books)
    raw_w = {b: [equal] * panel.n for b in panel.books}
    shares = turnover_attribution(panel, raw_w)
    xvd_flags = xsd.rank_demotion_flags(erd.panel_scores(panel, "volatility"), 1, 1)
    print(f"{'книга':20s} {'доля турновера':>15s} {'год. vol':>9s} {'duty XVD':>9s}")
    for b in sorted(panel.books, key=lambda x: -shares[x]):
        vol = statistics.pstdev(panel.rets[b]) * (365.0 ** 0.5)
        duty = sum(xvd_flags[b]) / panel.n
        print(f"{b:20s} {shares[b] * 100:14.1f}% {vol * 100:8.1f}% {duty * 100:8.1f}%")
    return out


def idea50_ntb(subset: Optional[Sequence[str]] = None,
               label: str = "все 10 реальных книг",
               bands: Sequence[Optional[float]] = DEFAULT_BANDS,
               counts: Sequence[int] = DEFAULT_COUNTS,
               seeds: int = CONTROL_SEEDS) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Таблицы #50: полоса на train/test, затем ОБЯЗАТЕЛЬНЫЙ контроль равной частоты."""
    windows = (("TRAIN ≤" + TRAIN_END, dgo.Panel(subset, None, TRAIN_END)),
               ("TEST  >" + TRAIN_END, dgo.Panel(subset, TRAIN_END, None)),
               ("FULL (in-sample, читать последним)", dgo.Panel(subset, None, None)))
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for tag, panel in windows:
        print(f"\n#50 NTB — ПОЛОСА БЕЗРАЗЛИЧИЯ · {tag} ({label}, {panel.n} дней)")
        print(f"{'правило':22s} {'полоса':>7s} {'APY':>7s} {'maxDD':>7s} {'turn':>7s} "
              f"{'netAPY':>8s} {'Calmar':>7s} {'сделок':>7s}")
        out[tag] = {}
        for name, w in rule_weights(panel):
            if name.startswith("КОНТРОЛЬ"):
                continue
            for band in bands:
                r = rebalance_run(panel, w, band=band)
                key = f"{name}|{'exact' if band is None else band}"
                out[tag][key] = r
                lbl = "точно" if band is None else f"{band * 100:.0f}%"
                print(f"{name:22s} {lbl:>7s} {_fmt_pct(r['apy'])} {_fmt_pct(r['maxdd'])} "
                      f"{r['turnover_yr']:7.3f} {_fmt_pct(r['net_apy_after_cost'])} "
                      f"{r['calmar']:7.2f} {int(r['rebalance_days']):7d}")
            print()

    test = dgo.Panel(subset, TRAIN_END, None)
    print(f"\n#50 КОНТРОЛЬ РАВНОЙ ЧАСТОТЫ (TEST, {seeds} случайных расписаний) — "
          "полоса против случайных дней при ТОМ ЖЕ числе сделок")
    print(f"{'правило':22s} {'полоса':>7s} {'netAPY':>8s} {'сделок':>7s} "
          f"{'случайн. медиана':>17s} {'бьют полосу':>12s} {'p':>6s}")
    for name, w in rule_weights(test):
        if name.startswith("КОНТРОЛЬ"):
            continue
        for band in (0.01, 0.03, 0.05):
            r = rebalance_run(test, w, band=band)
            nets = [rebalance_run(test, w, schedule=s)["net_apy_after_cost"]
                    for s in random_schedules(test.n, int(r["rebalance_days"]), seeds)]
            beat = sum(1 for x in nets if x >= r["net_apy_after_cost"])
            print(f"{name:22s} {band * 100:6.0f}% {_fmt_pct(r['net_apy_after_cost'])} "
                  f"{int(r['rebalance_days']):7d} {_fmt_pct(statistics.median(nets)):>17s} "
                  f"{beat:6d}/{seeds:<5d} {(beat + 1) / (seeds + 1):6.3f}")
        print()

    print(f"\n#50 ЧЕСТНАЯ КРИВАЯ ЧАСТОТЫ (случайные расписания, {seeds} seeds, медиана) — "
          "полоса убрана, осталась только частота")
    for tag, panel in (("TRAIN", dgo.Panel(subset, None, TRAIN_END)),
                       ("TEST", dgo.Panel(subset, TRAIN_END, None))):
        print(f"  --- {tag} ({panel.n} дней)")
        for name, w in rule_weights(panel):
            if name.startswith("КОНТРОЛЬ") or name.startswith("#39"):
                continue
            ex = rebalance_run(panel, w)
            print(f"    {name:22s} точно  APY {_fmt_pct(ex['apy'])} dd {_fmt_pct(ex['maxdd'])} "
                  f"net {_fmt_pct(ex['net_apy_after_cost'])} Calmar {ex['calmar']:6.2f}")
            for count in counts:
                rows = [rebalance_run(panel, w, schedule=s)
                        for s in random_schedules(panel.n, count, seeds)]
                apys = sorted(r["apy"] for r in rows)
                print(f"    {'':22s} R={count:<4d} APY {_fmt_pct(statistics.median(apys))} "
                      f"[{_fmt_pct(apys[0])}..{_fmt_pct(apys[-1])}] "
                      f"dd {_fmt_pct(statistics.median([r['maxdd'] for r in rows]))} "
                      f"net {_fmt_pct(statistics.median([r['net_apy_after_cost'] for r in rows]))} "
                      f"Calmar {statistics.median([r['calmar'] for r in rows]):6.2f}")
            print()
    return out


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--idea", choices=("49", "50", "both"), default="both")
    ap.add_argument("--seeds", type=int, default=CONTROL_SEEDS)
    args = ap.parse_args(argv)
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · evidence L0 (бэктест, не живые деньги).")
    print("Капитал не двигается; RiskPolicy v1.0, пороги kill-switch и живой трек не тронуты.")
    if args.idea in ("49", "both"):
        idea49_rdt()
    if args.idea in ("50", "both"):
        idea50_ntb(seeds=args.seeds)
    return 0


if __name__ == "__main__":     # pragma: no cover - CLI
    raise SystemExit(main(sys.argv[1:]))
