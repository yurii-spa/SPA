"""
IDEA #86 — DDW-REAL  ·  IDEA #87 — RDW: Relative Drawdown Weighting

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the fleet or the dashboard. Reads the aggressive-lab
panel READ-ONLY. stdlib-only, deterministic, LLM FORBIDDEN.


ПОЧЕМУ ЭТОТ ПРОГОН СУЩЕСТВУЕТ
─────────────────────────────
Запись #85 (DDW: Dynamic Drawdown Weighting) закрылась ДВУМЯ явно заказанными тестами:

    «Рой не строится, заказаны два теста: (1) DDW на реальной панели (когда доступна),
     (2) DDW + наклон (#84 EXPANDING) как объединённый сигнал.»

и назвала причину, по которой не смогла сделать (1) сама: «реальная панель недоступна
в облачном checkout». Панель доступна ЗДЕСЬ — data/aggressive_lab/<book>/realized_series.jsonl,
10 книг, 852 общих дня 2024-03-06…2026-07-05, phase="backtest" блок. Заказ (1) исполняется.

ИДЕЯ #86 — DDW-REAL: выживает ли вывод #85 на реальных данных?
  Механизм НЕ переписан: `_run_ew` / `_run_ddw` / `_metrics` / `_turnover_per_year`
  ИМПОРТИРУЮТСЯ из модуля #85 (scripts/edge_dynamic_drawdown_weighting.py) и вызываются
  с временно перепривязанным списком книг. Меняются ТОЛЬКО данные. Это тот же приём,
  которым #71 проверял #70, и он существует ровно затем, чтобы любое расхождение с
  опубликованной таблицей #85 объяснялось фикстурой, а не вторым прочтением правила.

  ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА (протокол реестра): на реальной панели DDW сработает
  СИЛЬНЕЕ, чем на фикстуре, но по причине, которая является скорее приговором панели, чем
  заслугой правила: здесь есть книги в ПОСТОЯННОЙ просадке (eth_directional −51% за период,
  средняя DD 29.4%), и «вес обратно просадке» вырождается в «не держи то, что падает второй
  год». Оборот при этом вырастет против фикстурных 0.16–0.46/год, потому что реальные
  доходности варьируются каждый день, а не только в стресс-окнах.

ИДЕЯ #87 — RDW: Relative Drawdown Weighting (НОВАЯ гипотеза)
  ПРЕТЕНЗИЯ К #85, из которой растёт идея. DDW наказывает УРОВЕНЬ просадки, а уровень
  у книг несопоставим: на этой панели средняя DD пробегает от 0.000% (lp_eth_stable,
  points_farm — просадки не было ни дня) до 29.364% (eth_directional). Правило «вес ∝
  1/(1+DD×kappa)» на таком поле почти не имеет РАЗРЕШЕНИЯ внутри тихой половины: книга
  с DD 0.05% и книга с DD 0.001% получают практически один и тот же вес, хотя первая
  находится в СВОЁМ худшем состоянии за всю историю, а вторая — в обычном.

  МЕХАНИЗМ. Нормировать просадку на СОБСТВЕННУЮ историческую шкалу книги:

      S_b(t) = max(FLOOR, mean{ DD_b(u) : u < t })        ← причинно, expanding window
      w_b(t) ∝ 1 / (1 + kappa × DD_b(t) / S_b(t)),   нормировка на 1

  То есть штрафуется АНОМАЛЬНЫЙ для книги стресс, а не структурная волатильность. FLOOR
  (0.5%) не даёт знаменателю выродиться у книги, которая ещё не просаживалась; без него
  первая же микро-просадка тихой книги давала бы деление на ~0.

  FAIL-CLOSED: пока не набран WARMUP=120 дней истории, шкала НЕ ОЦЕНЕНА, и правило не
  наклоняет портфель вовсе — веса равные. «Не измерено» здесь не «ноль риска», а отказ
  ранжировать; это то же требование, что и MIN_POINTS у загрузчика панели.

  ПРЕДСКАЗАНИЕ, ЗАПИСАННОЕ ДО ПРОГОНА: на ПОЛНОЙ панели RDW ПРОИГРАЕТ DDW, и проиграет
  осознанно — самонормировка выбрасывает ровно ту информацию (уровень), которая на этой
  панели и делает всю работу: она возвращает вес eth_directional, как только его просадка
  перестаёт быть аномальной ДЛЯ НЕГО. Ожидаемое место, где RDW может выиграть, — ТИХАЯ
  подпанель, где уровневому сигналу не за что зацепиться.

  ДВА РЕШАЮЩИХ КОНТРОЛЯ (без них «RDW ≠ DDW» ничего не значит):

  (A) ОБЩАЯ ШКАЛА (`shared`). Если S одинакова для ВСЕХ книг (панельное среднее), RDW
      превращается в DDW с перемасштабированным kappa — и ничего кросс-секционного не
      добавляет. Разница `per_book` − `shared` и есть ЕДИНСТВЕННАЯ доля эффекта, которую
      можно приписать самонормировке. Без этого плеча положительный RDW неотличим от
      «мы просто взяли kappa побольше».

  (B) ТИХАЯ ПОДПАНЕЛЬ, ОТОБРАННАЯ ПРИЧИННО. Книги с maxDD < 7% на TRAIN-окне (до 2025-06-30)
      и только на нём. Отбор по полной выборке был бы заглядыванием вперёд, и тогда «RDW
      выигрывает у тихих» означало бы лишь, что мы знали заранее, кто окажется тихим.

ЧЕСТНЫЕ ПРЕДЕЛЫ, ОБЪЯВЛЕННЫЕ ЗАРАНЕЕ
  • evidence L0 — бэктест на advisory paper-панели, числа помечены [bt], никогда не реализованы;
  • книги панели сами являются бэктестами (harness.py поверх реальных глубоких фидов), то есть
    измеряется правило на реальной ФОРМЕ доходностей, а не на реализованном P&L;
  • только блок phase="backtest": forward-блок пере-якорится на ~$100k, и диффы через шов
    фабрикуют доходности −31%/−84%/+105% (починено 2026-08-02, загрузчик переиспользован);
  • kappa НЕ свипировалась на TEST; FLOOR и WARMUP зафиксированы до просмотра TEST, их
    чувствительность меряется на TRAIN;
  • сплит один и он реестрово-канонический (2025-06-30), объявлен до прогона.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _load_sibling(name: str, filename: str):
    """Import a sibling edge script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(name, str(Path(__file__).resolve().parent / filename))
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


#: Mechanism of idea #85, imported unchanged. Nothing here re-implements it.
DDW = _load_sibling("edge_ddw_85", "edge_dynamic_drawdown_weighting.py")
#: Real-panel loader (phase-disciplined, fail-CLOSED) of ideas #16/#17/#71.
RPE = _load_sibling("edge_rpe", "edge_real_panel_ensemble.py")

#: Panel location. Overridable because the panel is NOT git-tracked: a session working from a
#: worktree has an empty data/ and must point at the prod tree's copy (read-only), otherwise it
#: silently falls back to the fixture — the trap #70 fell into and #85 declared.
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

INITIAL = DDW.INITIAL                     # 100_000.0, taken from #85 rather than restated
KAPPAS: Tuple[float, ...] = tuple(DDW.KAPPAS)      # (0, 1, 2, 5, 10, 20) — #85's ladder verbatim
COST_GRID: Tuple[int, ...] = tuple(DDW.COST_GRID)  # #80 CSS price sweep, canonical c=96
SPLIT_DATE = DDW.SPLIT_DATE               # 2025-06-30, registry-canonical

#: RDW parameters, FIXED before TEST was looked at. Sensitivity is measured on TRAIN only.
WARMUP_DAYS = 120
SCALE_FLOOR = 0.005            # 0.5% — below this a book's own DD scale is not a measurement
FLOOR_GRID: Tuple[float, ...] = (0.0025, 0.005, 0.01)

#: Causal quiet-panel criterion: maxDD on TRAIN only.
QUIET_MAXDD = 0.07

#: Per-book cap of the SECOND baseline. RiskPolicy v1.0 caps a T2 protocol at 20% of capital;
#: the cost-free EW buy-and-hold baseline drifts far past that (see `terminal_weights`), so
#: comparing a trading rule only against it measures the rule against a portfolio this project
#: is not allowed to hold. Both baselines are therefore reported side by side, always.
POLICY_CAP = 0.20
#: RiskPolicy v1.0's T1 ceiling. Reported alongside POLICY_CAP because on a panel of N books a
#: cap of 1/N or lower DEGENERATES into equal weight — on the 5-book quiet sub-panel the 20% cap
#: IS daily equal-weight rebalancing, and reading its ΔCalmar as "vs a capped buy-and-hold" would
#: credit a rule for beating a benchmark that no longer exists. The 40% line always binds here.
T1_CAP = 0.40


# ─────────────────────────── real panel → returns ───────────────────────────

def load_real_panel(panel_dir: Path = PANEL_DIR
                    ) -> Tuple[List[str], List[datetime.date], Dict[str, Dict[datetime.date, float]]]:
    """(books, dates, {book: {date: daily_return}}) on the fail-CLOSED common axis.

    Delegates to the phase-disciplined loader; converts the axis to ``datetime.date`` because
    #85's engines compare dates against SPLIT_DATE and the stress-window bounds.
    """
    panel = RPE.load_panel(panel_dir)
    axis = RPE.common_axis(panel)
    if len(axis) < 120:
        raise RuntimeError(f"common axis is {len(axis)} days — refusing to publish a split on it")
    dates = [datetime.date.fromisoformat(d) for d in axis]
    rets_map = {b: {datetime.date.fromisoformat(d): panel[b][d] for d in axis} for b in sorted(panel)}
    return sorted(panel), dates, rets_map


@contextmanager
def books_bound_to(books: Sequence[str]) -> Iterator[None]:
    """Run #85's engines over a different universe without touching a line of its logic.

    #85's functions read the module-level ``BOOKS`` list. Rebinding it (and restoring it) is the
    smallest possible intervention: the arithmetic executed is byte-for-byte #85's own.
    """
    saved = DDW.BOOKS
    DDW.BOOKS = list(books)
    try:
        yield
    finally:
        DDW.BOOKS = saved


def standalone_maxdd(dates: Sequence[datetime.date], rets: Dict[datetime.date, float]) -> float:
    """Book's own max drawdown over `dates`, starting flat (no look-ahead, no portfolio context)."""
    eq = peak = INITIAL
    worst = 0.0
    for d in dates:
        eq *= (1.0 + rets[d])
        peak = max(peak, eq)
        worst = max(worst, 1.0 - eq / peak)
    return worst


def quiet_books_from_train(books: Sequence[str], dates: Sequence[datetime.date],
                           rets_map: Dict[str, Dict[datetime.date, float]],
                           threshold: float = QUIET_MAXDD) -> List[str]:
    """Books whose TRAIN-window maxDD is below `threshold`. Selection never sees TEST."""
    train_dates = [d for d in dates if d <= SPLIT_DATE]
    if len(train_dates) < WARMUP_DAYS:
        raise RuntimeError("train window shorter than warmup — refusing to select a sub-panel")
    return [b for b in books if standalone_maxdd(train_dates, rets_map[b]) < threshold]


# ─────────────────────────── idea #87 engine ───────────────────────────

def _rdw_targets(books: Sequence[str], dd: Dict[str, float], scale: Dict[str, float],
                 kappa: float) -> Dict[str, float]:
    """Normalised RDW target weights for one day. kappa=0 ⇒ equal weights, exactly."""
    n = len(books)
    if kappa == 0.0:
        return {b: 1.0 / n for b in books}
    raw = {b: 1.0 / (1.0 + kappa * dd[b] / scale[b]) for b in books}
    tot = sum(raw.values())
    return {b: raw[b] / tot for b in books}


def run_rdw(books: Sequence[str], dates: Sequence[datetime.date],
            rets_map: Dict[str, Dict[datetime.date, float]], kappa: float, cost_bps: int,
            *, scale_mode: str = "per_book", warmup: int = WARMUP_DAYS,
            floor: float = SCALE_FLOOR) -> Tuple[List[Tuple[datetime.date, float]], float]:
    """Relative Drawdown Weighting. Returns (equity curve, annualised turnover).

    scale_mode:
      "per_book" — S_b(t) = max(floor, mean of book b's own DD before t)   ← the hypothesis
      "shared"   — S(t)   = max(floor, mean of ALL books' mean DD before t) ← control (A)
      "unit"     — S ≡ 1.0, warmup ignored                                  ← null: identical to #85 DDW

    Until `warmup` observations of drawdown exist the rule HOLDS (no trade, no cost): a scale
    estimated on nothing is not a measurement, and rebalancing anyway would charge turnover for
    a decision nobody made. Day 0 holds even when ``warmup=0`` is passed: an empty history has
    no mean, and dividing by the count of nothing is arithmetic, not a measurement.

    The accounting (standalone signal equities, post-drift current weights, half-turn cost) is
    the same shape as #85's ``_run_ddw``; the "unit" mode is asserted equal to it by test, in
    both directions, so this is a generalisation rather than a second implementation.
    """
    if scale_mode not in ("per_book", "shared", "unit"):
        raise ValueError(f"unknown scale_mode {scale_mode!r}")
    cost_frac = cost_bps / 10_000.0
    n = len(books)

    standalone = {b: INITIAL for b in books}
    peaks = {b: INITIAL for b in books}
    dd_sum = {b: 0.0 for b in books}          # running sum of past DD observations (causal)
    dd_count = 0

    weights = {b: 1.0 / n for b in books}
    portfolio_eq = INITIAL
    total_turnover = 0.0
    curve: List[Tuple[datetime.date, float]] = []

    for d in dates:
        # 1. standalone equities — the signal source, never charged
        for b in books:
            standalone[b] *= (1.0 + rets_map[b][d])
            if standalone[b] > peaks[b]:
                peaks[b] = standalone[b]
        dd = {b: max(0.0, 1.0 - standalone[b] / peaks[b]) for b in books}

        # 2. portfolio return under the weights held into today
        port_ret = sum(weights[b] * rets_map[b][d] for b in books)
        portfolio_eq *= (1.0 + port_ret)

        # 3. weights after today's drift
        book_val = {b: weights[b] * (1.0 + rets_map[b][d]) / (1.0 + port_ret) for b in books}
        total_val = sum(book_val.values())
        curr_w = {b: book_val[b] / total_val for b in books}

        # 4. target weights from the RELATIVE drawdown signal
        if scale_mode == "unit":
            target_w = _rdw_targets(books, dd, {b: 1.0 for b in books}, kappa)
        elif dd_count == 0 or dd_count < warmup:
            # fail-CLOSED: the scale is not yet a measurement ⇒ do not ACT at all. Holding, not
            # rebalancing to equal: rebalancing is itself a decision, and paying turnover on a
            # measurement one does not have is the fail-OPEN reading of "не измерено".
            target_w = dict(curr_w)
        elif scale_mode == "per_book":
            scale = {b: max(floor, dd_sum[b] / dd_count) for b in books}
            target_w = _rdw_targets(books, dd, scale, kappa)
        else:  # "shared"
            shared = max(floor, sum(dd_sum.values()) / (dd_count * n))
            target_w = _rdw_targets(books, dd, {b: shared for b in books}, kappa)

        # 5. turnover (half-turn, one-sided) and its price
        turnover = 0.5 * sum(abs(target_w[b] - curr_w[b]) for b in books)
        total_turnover += turnover
        portfolio_eq -= portfolio_eq * turnover * cost_frac

        weights = target_w
        curve.append((d, portfolio_eq))

        # 6. today's DD joins the history only AFTER it was used — strictly causal
        for b in books:
            dd_sum[b] += dd[b]
        dd_count += 1

    to_year = total_turnover * 365.0 / len(dates) if dates else 0.0
    return curve, round(to_year, 4)


# ─────────────────────────── metrics / splits ───────────────────────────

def metrics(curve: Sequence[Tuple[datetime.date, float]], init: float = INITIAL) -> Dict[str, float]:
    """APY / maxDD / Calmar over `curve`, rebased to `init` (same arithmetic as #85)."""
    if not curve:
        return {"apy_pct": 0.0, "max_dd_pct": 0.0, "calmar": 0.0}
    equities = [eq for _, eq in curve]
    n_years = len(equities) / 365.0
    apy = ((equities[-1] / init) ** (1.0 / n_years) - 1.0) * 100.0 if n_years > 0 else 0.0
    peak, max_dd = init, 0.0
    for eq in equities:
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq - peak) / peak)
    max_dd_pct = max_dd * 100.0
    calmar = (apy / abs(max_dd_pct)) if max_dd_pct != 0 else 0.0
    return {"apy_pct": round(apy, 2), "max_dd_pct": round(max_dd_pct, 2), "calmar": round(calmar, 4)}


def split_metrics(curve: Sequence[Tuple[datetime.date, float]]) -> Dict[str, Dict[str, float]]:
    """TRAIN and TEST metrics, each rebased to the equity it actually started from.

    #85 compared its half-sample Calmars against a FULL-sample base and said so in its caveats;
    here each half is compared against the SAME half of the baseline (see `arm_table`), which is
    the comparison #85 listed as missing.
    """
    train = [(d, eq) for d, eq in curve if d <= SPLIT_DATE]
    test = [(d, eq) for d, eq in curve if d > SPLIT_DATE]
    train_m = metrics(train, INITIAL)
    test_m = metrics(test, train[-1][1] if train else INITIAL)
    return {"train": train_m, "test": test_m}


def ew_baseline(books: Sequence[str], dates: Sequence[datetime.date],
                rets_map: Dict[str, Dict[datetime.date, float]]) -> List[Tuple[datetime.date, float]]:
    """Equal-weight buy-and-hold — #85's baseline, its own function, zero turnover."""
    with books_bound_to(books):
        return DDW._run_ew(list(dates), rets_map, 0)


def terminal_weights(books: Sequence[str], dates: Sequence[datetime.date],
                     rets_map: Dict[str, Dict[datetime.date, float]]) -> Dict[str, float]:
    """Where equal-weight buy-and-hold actually ENDS UP. Not a metric — a disclosure."""
    n = len(books)
    eq = {b: INITIAL / n for b in books}
    for d in dates:
        for b in books:
            eq[b] *= (1.0 + rets_map[b][d])
    tot = sum(eq.values())
    return {b: eq[b] / tot for b in books}


def _cap_weights(w: Dict[str, float], cap: float) -> Dict[str, float]:
    """Trim every book to `cap`, redistributing the excess pro-rata among the uncapped ones."""
    books = list(w)
    if cap * len(books) <= 1.0:                     # cap cannot be satisfied ⇒ equal weights
        return {b: 1.0 / len(books) for b in books}
    out = dict(w)
    for _ in range(len(books)):
        over = [b for b in books if out[b] > cap + 1e-12]
        if not over:
            break
        excess = sum(out[b] - cap for b in over)
        for b in over:
            out[b] = cap
        under = [b for b in books if out[b] < cap - 1e-12]
        pool = sum(out[b] for b in under)
        if not under or pool <= 0:
            break
        for b in under:
            out[b] += excess * out[b] / pool
    tot = sum(out.values())
    return {b: out[b] / tot for b in books}


def run_capped_bh(books: Sequence[str], dates: Sequence[datetime.date],
                  rets_map: Dict[str, Dict[datetime.date, float]], cost_bps: int,
                  cap: float = POLICY_CAP) -> Tuple[List[Tuple[datetime.date, float]], float]:
    """Buy-and-hold that is allowed to drift ONLY up to a per-book cap. Turnover is charged.

    This is the INVESTABLE baseline: it trades only when a winner grows past what RiskPolicy
    v1.0 would permit, so it keeps the anti-momentum drift that makes buy-and-hold strong while
    staying inside a concentration limit the project actually lives under.
    """
    cost_frac = cost_bps / 10_000.0
    n = len(books)
    weights = {b: 1.0 / n for b in books}
    portfolio_eq = INITIAL
    total_turnover = 0.0
    curve: List[Tuple[datetime.date, float]] = []
    for d in dates:
        port_ret = sum(weights[b] * rets_map[b][d] for b in books)
        portfolio_eq *= (1.0 + port_ret)
        book_val = {b: weights[b] * (1.0 + rets_map[b][d]) / (1.0 + port_ret) for b in books}
        tot = sum(book_val.values())
        curr_w = {b: book_val[b] / tot for b in books}
        target_w = _cap_weights(curr_w, cap)
        turnover = 0.5 * sum(abs(target_w[b] - curr_w[b]) for b in books)
        total_turnover += turnover
        portfolio_eq -= portfolio_eq * turnover * cost_frac
        weights = target_w
        curve.append((d, portfolio_eq))
    return curve, round(total_turnover * 365.0 / len(dates), 4) if dates else 0.0


# ─────────────────────────── reporting ───────────────────────────

def _fmt_row(label: str, m: Dict[str, float], dcal: float, dcal2: float, dcal3: float,
             to: float) -> str:
    return (f"{label:>26} {m['apy_pct']:>9.2f} {m['max_dd_pct']:>9.2f} "
            f"{m['calmar']:>9.4f} {dcal:>9.4f} {dcal2:>9.4f} {dcal3:>9.4f} {to:>8.2f}")


def arm_table(title: str, books: Sequence[str], dates: Sequence[datetime.date],
              rets_map: Dict[str, Dict[datetime.date, float]], cost_bps: int) -> Dict:
    """Full ladder: EW base · #85 DDW · #87 RDW per_book · #87 RDW shared, at one price."""
    base_curve = ew_baseline(books, dates, rets_map)
    base = metrics(base_curve)
    base_split = split_metrics(base_curve)
    cap_curve, cap_to = run_capped_bh(books, dates, rets_map, cost_bps)
    cap_base = metrics(cap_curve)
    t1_curve, t1_to = run_capped_bh(books, dates, rets_map, cost_bps, cap=T1_CAP)
    t1_base = metrics(t1_curve)
    degenerate = POLICY_CAP * len(books) <= 1.0 + 1e-12

    print(f"\n{title}  [bt, реальная панель, L0, c={cost_bps} bps]")
    print(f"  книг: {len(books)} ({', '.join(books)})")
    print(f"  БАЗА 1 EW buy-and-hold: APY {base['apy_pct']:.2f}% / maxDD {base['max_dd_pct']:.2f}% "
          f"/ Calmar {base['calmar']:.4f} / оборот 0  ← НЕ инвестируема, см. терминальные веса")
    print(f"  БАЗА 2 capped BH ({POLICY_CAP:.0%}/книга): APY {cap_base['apy_pct']:.2f}% / "
          f"maxDD {cap_base['max_dd_pct']:.2f}% / Calmar {cap_base['calmar']:.4f} / оборот {cap_to:.2f}"
          + (f"   ← ВЫРОЖДЕНА: {POLICY_CAP:.0%} на {len(books)} книг — это РОВНО равновесная "
             f"ребалансировка" if degenerate else ""))
    print(f"  БАЗА 3 capped BH ({T1_CAP:.0%}/книга, потолок T1): APY {t1_base['apy_pct']:.2f}% / "
          f"maxDD {t1_base['max_dd_pct']:.2f}% / Calmar {t1_base['calmar']:.4f} / оборот {t1_to:.2f}"
          + ("   ← НЕвырожденная база для этого арма" if degenerate else ""))
    print(f"{'арм':>26} {'APY%':>9} {'maxDD%':>9} {'Calmar':>9} {'ΔCal1':>9} {'ΔCal2':>9} "
          f"{'ΔCal3':>9} {'TO/год':>8}")
    print("-" * 96)

    out: Dict = {"base": base, "base_split": base_split, "cap_base": cap_base,
                 "cap_turnover": cap_to, "cap_split": split_metrics(cap_curve),
                 "t1_base": t1_base, "t1_turnover": t1_to, "cap_degenerate": degenerate,
                 "ddw": {}, "rdw": {}, "rdw_shared": {}}

    with books_bound_to(books):
        for kappa in KAPPAS:
            curve = DDW._run_ddw(list(dates), rets_map, kappa, cost_bps)
            to = DDW._turnover_per_year(list(dates), rets_map, kappa)
            m = metrics(curve)
            out["ddw"][kappa] = {**m, "dcalmar": round(m["calmar"] - base["calmar"], 4),
                                "dcalmar_cap": round(m["calmar"] - cap_base["calmar"], 4),
                                "dcalmar_t1": round(m["calmar"] - t1_base["calmar"], 4),
                                "turnover": to, **split_metrics(curve)}
            print(_fmt_row(f"#85 DDW k={kappa:g}", m, m["calmar"] - base["calmar"],
                           m["calmar"] - cap_base["calmar"], m["calmar"] - t1_base["calmar"], to))

    for mode, key in (("per_book", "rdw"), ("shared", "rdw_shared")):
        for kappa in KAPPAS:
            if kappa == 0.0:
                continue          # kappa=0 is equal-weight rebalancing for every mode alike
            curve, to = run_rdw(books, dates, rets_map, kappa, cost_bps, scale_mode=mode)
            m = metrics(curve)
            out[key][kappa] = {**m, "dcalmar": round(m["calmar"] - base["calmar"], 4),
                               "dcalmar_cap": round(m["calmar"] - cap_base["calmar"], 4),
                               "dcalmar_t1": round(m["calmar"] - t1_base["calmar"], 4),
                               "turnover": to, **split_metrics(curve)}
            print(_fmt_row(f"#87 RDW/{mode} k={kappa:g}", m, m["calmar"] - base["calmar"],
                           m["calmar"] - cap_base["calmar"], m["calmar"] - t1_base["calmar"], to))
    return out


def price_sweep(books: Sequence[str], dates: Sequence[datetime.date],
                rets_map: Dict[str, Dict[datetime.date, float]], mode: str) -> Dict[int, Dict[float, float]]:
    """ΔCalmar vs the (cost-free) EW buy-and-hold base across the #80 price ladder."""
    base = metrics(ew_baseline(books, dates, rets_map))
    sweep: Dict[int, Dict[float, float]] = {}
    for c in COST_GRID:
        row: Dict[float, float] = {}
        for kappa in KAPPAS:
            if mode == "ddw":
                with books_bound_to(books):
                    curve = DDW._run_ddw(list(dates), rets_map, kappa, c)
            else:
                if kappa == 0.0:
                    continue
                curve, _ = run_rdw(books, dates, rets_map, kappa, c, scale_mode=mode)
            row[kappa] = round(metrics(curve)["calmar"] - base["calmar"], 4)
        sweep[c] = row
    return sweep


def _print_sweep(title: str, sweep: Dict[int, Dict[float, float]]) -> None:
    kappas = sorted(next(iter(sweep.values())))
    print(f"\n{title} (ΔCalmar; строки=cost_bps, столбцы=kappa)")
    corner = "c\\k"
    print(f"{corner:>6}" + "".join(f"{k:>10.1f}" for k in kappas))
    print("-" * (6 + 10 * len(kappas)))
    for c in COST_GRID:
        print(f"{c:>6}" + "".join(f"{sweep[c][k]:>10.4f}" for k in kappas))


def floor_sensitivity(books: Sequence[str], dates: Sequence[datetime.date],
                      rets_map: Dict[str, Dict[datetime.date, float]],
                      cost_bps: int = 96) -> Dict[float, Dict[float, float]]:
    """TRAIN-only sensitivity of RDW/per_book to the scale FLOOR (a fixed parameter, not a knob)."""
    train_dates = [d for d in dates if d <= SPLIT_DATE]
    base = metrics(ew_baseline(books, train_dates, rets_map))
    out: Dict[float, Dict[float, float]] = {}
    for floor in FLOOR_GRID:
        row: Dict[float, float] = {}
        for kappa in KAPPAS:
            if kappa == 0.0:
                continue
            curve, _ = run_rdw(books, train_dates, rets_map, kappa, cost_bps,
                               scale_mode="per_book", floor=floor)
            row[kappa] = round(metrics(curve)["calmar"] - base["calmar"], 4)
        out[floor] = row
    return out


def split_table(title: str, arm: Dict) -> None:
    """TRAIN/TEST ΔCalmar against the SAME-HALF baseline (the comparison #85 declared missing)."""
    b = arm["base_split"]
    print(f"\n{title} — TRAIN/TEST, база = ТА ЖЕ половина EW "
          f"(train Calmar {b['train']['calmar']:.4f} · test Calmar {b['test']['calmar']:.4f})")
    print(f"{'арм':>26} {'trΔCal':>10} {'tsΔCal':>10} {'trAPY%':>9} {'tsAPY%':>9}")
    print("-" * 68)
    for key, label in (("ddw", "#85 DDW"), ("rdw", "#87 RDW/per_book"), ("rdw_shared", "#87 RDW/shared")):
        for kappa, cell in sorted(arm[key].items()):
            if kappa == 0.0 and key != "ddw":
                continue
            print(f"{label + f' k={kappa:g}':>26} "
                  f"{cell['train']['calmar'] - b['train']['calmar']:>10.4f} "
                  f"{cell['test']['calmar'] - b['test']['calmar']:>10.4f} "
                  f"{cell['train']['apy_pct']:>9.2f} {cell['test']['apy_pct']:>9.2f}")


def main() -> None:
    print("=" * 78)
    print("IDEA #86 DDW-REAL  ·  IDEA #87 RDW: Relative Drawdown Weighting")
    print("  advisory / paper / OUTSIDE_RISKPOLICY — капитал не двигается, RiskPolicy не трогается")
    print("=" * 78)

    books, dates, rets_map = load_real_panel()
    print(f"\nПАНЕЛЬ: {len(books)} книг × {len(dates)} общих дней "
          f"{dates[0].isoformat()}…{dates[-1].isoformat()} (только phase=backtest)")
    print("\nсобственная шкала просадки каждой книги (полная выборка, справочно):")
    for b in books:
        dd_sum, eq, peak = 0.0, INITIAL, INITIAL
        worst = 0.0
        for d in dates:
            eq *= (1.0 + rets_map[b][d])
            peak = max(peak, eq)
            cur = max(0.0, 1.0 - eq / peak)
            dd_sum += cur
            worst = max(worst, cur)
        print(f"  {b:22s} maxDD {worst * 100:6.2f}%   meanDD {dd_sum / len(dates) * 100:7.3f}%")

    tw = terminal_weights(books, dates, rets_map)
    top = sorted(tw.items(), key=lambda kv: -kv[1])
    print(f"\nГДЕ ЗАКАНЧИВАЕТ EW buy-and-hold (терминальные веса — это ОГОВОРКА, не метрика):")
    for b, w in top:
        flag = "  ← выше потолка RiskPolicy v1.0 для T2 (20%)" if w > POLICY_CAP else ""
        print(f"  {b:22s} {w * 100:6.2f}%{flag}")
    print(f"  top-2 = {top[0][1] * 100 + top[1][1] * 100:.2f}% капитала")

    quiet = quiet_books_from_train(books, dates, rets_map)
    print(f"\nТИХАЯ ПОДПАНЕЛЬ (отбор ПРИЧИННЫЙ: maxDD < {QUIET_MAXDD:.0%} на TRAIN до "
          f"{SPLIT_DATE.isoformat()}): {len(quiet)} книг — {', '.join(quiet)}")

    full = arm_table("АРМ 1 — ПОЛНАЯ ПАНЕЛЬ", books, dates, rets_map, 96)
    split_table("АРМ 1 — ПОЛНАЯ ПАНЕЛЬ", full)

    _print_sweep("АРМ 1 · #85 DDW — развёртка по цене", price_sweep(books, dates, rets_map, "ddw"))
    _print_sweep("АРМ 1 · #87 RDW/per_book — развёртка по цене",
                 price_sweep(books, dates, rets_map, "per_book"))
    _print_sweep("АРМ 1 · #87 RDW/shared (контроль A) — развёртка по цене",
                 price_sweep(books, dates, rets_map, "shared"))

    if len(quiet) >= 3:
        q = arm_table("АРМ 2 — ТИХАЯ ПОДПАНЕЛЬ (контроль B)", quiet, dates, rets_map, 96)
        split_table("АРМ 2 — ТИХАЯ ПОДПАНЕЛЬ", q)
        _print_sweep("АРМ 2 · #85 DDW — развёртка по цене", price_sweep(quiet, dates, rets_map, "ddw"))
        _print_sweep("АРМ 2 · #87 RDW/per_book — развёртка по цене",
                     price_sweep(quiet, dates, rets_map, "per_book"))
    else:
        print("\nАРМ 2 ПРОПУЩЕН: меньше 3 тихих книг на TRAIN — подпанель не ранжируема (fail-CLOSED)")

    print("\n\nЧУВСТВИТЕЛЬНОСТЬ К FLOOR (ТОЛЬКО TRAIN, параметр зафиксирован до просмотра TEST):")
    fs = floor_sensitivity(books, dates, rets_map)
    ks = sorted(next(iter(fs.values())))
    print(f"{'floor':>8}" + "".join(f"{k:>10.1f}" for k in ks))
    for floor, row in fs.items():
        print(f"{floor:>8.4f}" + "".join(f"{row[k]:>10.4f}" for k in ks))


if __name__ == "__main__":
    main()
