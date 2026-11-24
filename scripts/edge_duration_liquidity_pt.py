#!/usr/bin/env python3
"""
#165 DNS — Duration-Neutral Sizing · #166 LDG — Liquidity-Depth Gate.

Две независимые гипотезы на ОДНОМ реальном ряде `data/rates_desk/pendle_pt_history.json`
(42 рынка Pendle PT, 6276 строк, 1245 дат 2023-02-07…2026-07-05, семь базовых активов).
Загрузчик переиспользован: `scripts/_pt_history.py` (идеи #117, #118, #158).

IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · stdlib-only · детерминированно · без сети.
Ряд открыт ТОЛЬКО НА ЧТЕНИЕ; ни один файл `data/` не записывается. LLM FORBIDDEN.

ПОЧЕМУ ЭТО ДВА НОВЫХ НОМЕРА
───────────────────────────
**#165 DNS.** Весь ряд сайзеров реестра (#128 SFS, #141 TUB, #149 LBS, #142 PRST, #153 CRP)
оценивает риск ПО ИСТОРИИ доходностей — и упирается в то, что история панели почти не
двигается (население измеримых книг 2–3 из 10, блок «НАСЕЛЕНИЕ ЗАМЕРА» реестра). У PT есть
риск, известный НЕ по истории, а ПО КОНТРАКТУ: марка позиции = −(τ/365)·Δlog(1+y), то есть
дюрация τ наблюдается точно СЕГОДНЯ, до всякой оценки. DNS держит дюрацию в долларах
постоянной: w = min(1, D*/τ). Это не оценка риска, это тождество.

**#166 LDG.** Колонка `tvl_usd` этого ряда в реестре не прочитана НИ РАЗУ (0 вхождений
`tvl_usd` в 15 998 строках `DYNAMIC_LEVERAGE_GUARDIAN.md`). Между тем флагманский
механизм самого документа — «плечо от ЖИВОЙ глубины выхода»; #1 мерил его на фикстуре,
#132 — на панели без глубины. Здесь впервые задан вопрос глубине на реальном ряде.

ЧЕГО ЭТИ ПРИБОРЫ НЕ ОТВЕЧАЮТ (назвать ДО чисел)
───────────────────────────────────────────────
1. Цена PT ВЫВЕДЕНА из ставки по конвенции Pendle `P=(1+y)^(−τ/365)`: `pt_price` равен
   `null` во всех 6276 строках. Это заявление о конвенции, а не замер (как и в #117/#158).
2. Дюрация — это МЕДЛЕННЫЙ риск (марка). Хвост PT (депег USDe/sUSDe, слэшинг LRT, срыв
   погашения) к τ не привязан вовсе и ни одной строкой ряда не наблюдается. DNS снижает
   марочный риск и НЕ ТРОГАЕТ gap-риск — продавать её как «безопасность» запрещено (инв. #8).
3. `tvl_usd` — НЕ глубина выхода: состав AMM-пула неизвестен, вывод за размер не наблюдается.
   TVL — верхняя оценка ёмкости, и эндогенна ставке.
4. Новорождённый рынок имеет крошечный TVL ПО ПОСТРОЕНИЮ (первая строка `PT-USDe-13AUG2026`
   несёт $0.97). «Ещё не вырос» и «осушается» — два разных состояния, и прибор их различает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pt_history as H  # noqa: E402  (общий загрузчик ряда, read-only)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

_MODULE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = _MODULE_ROOT / "data"

ROLL_COST_BP = 96.0        # та же пошлина, что у всего реестра (вход/выход)
MIN_TAU_ENTRY = 14         # рынок моложе 14 дней до погашения не открываем (как #158)
SEAM = "2025-06-30"        # шов TRAIN/TEST — тот же, что у блока «НАСЕЛЕНИЕ ЗАМЕРА»
MAX_GAP_DAYS = 10          # разрыв ряда шире — наблюдение рвётся, день не считается
DD_FLOOR_BP = 96.0         # просадка ниже пошлины входа: Calmar НЕ риск-взвешенная величина (#129)


class Unmeasured(H.Unmeasured):
    """Третий исход: не ноль, не пустота, не успех (инв. #17)."""


# ─────────────────────────────── механика одной ноги ───────────────────────────────

def leg_step(y0: float, tau0: float, y1: float, dt: int) -> Tuple[float, float]:
    """Лог-доход ноги PT за dt дней, разложенный ТОЧНО (не приближённо).

    carry — ставка стоит, срок уходит;  mark — ставка двинулась при уже ушедшем сроке.
    Сумма тождественно равна log P(y1, tau0-dt) − log P(y0, tau0): разложение полное.
    """
    tau1 = tau0 - dt
    lp = lambda y, t: -(t / 365.0) * math.log1p(y)  # noqa: E731  log P(y, t)
    carry = lp(y0, tau1) - lp(y0, tau0)
    mark = lp(y1, tau1) - lp(y0, tau1)
    return carry, mark


def dollar_duration(tau: float) -> float:
    """Дюрация в годах: сколько лог-марки даёт 1 pp сдвига ставки. Наблюдается, не оценивается."""
    return tau / 365.0


# ─────────────────────────────── симулятор ───────────────────────────────

class Sim:
    """Один прогон политики по одному базовому активу.

    select(day, legs) -> выбранная нога или None (ОТКАЗ ⇒ весь капитал в безрисковой ноге)
    weight(leg)       -> доля капитала в PT, [0,1]
    """

    def __init__(self, u: H.Underlying, *, select: Callable, weight: Callable,
                 cash_rate: Callable[[str], float], roll_cost_bp: float = ROLL_COST_BP,
                 start: Optional[str] = None, end: Optional[str] = None) -> None:
        self.u = u
        self.select = select
        self.weight = weight
        self.cash_rate = cash_rate
        self.rt = roll_cost_bp / 1e4
        self.dates = [d for d in u.dates
                      if (start is None or d >= start) and (end is None or d <= end)]

    def run(self) -> dict:
        reset = getattr(self.weight, "reset", None)
        if reset is not None:
            reset()                       # политика с памятью не переносится между окнами
        if len(self.dates) < 3:
            raise Unmeasured(f"{self.u.name}: дней {len(self.dates)} — нечего мерить, а не «ноль»")
        rets: List[Tuple[str, float]] = []
        observed = 0
        held: Optional[str] = None
        w_prev = 0.0
        rolls = refusals = breaks = 0
        turnover = 0.0
        fees = 0.0
        marks: List[float] = []
        taus: List[float] = []
        y_held: List[Tuple[float, float]] = []
        for d, d2 in zip(self.dates, self.dates[1:]):
            dt = H.days(d, d2)
            if dt <= 0 or dt > MAX_GAP_DAYS:
                breaks += 1
                held, w_prev = None, 0.0     # позиция не переносится через дыру ряда
                continue
            legs = {k: (t, y, tvl) for t, y, tvl, k in self.u.legs(d)}
            pick = self.select(d, self.u.legs(d))
            if pick is None:
                refusals += 1
                w, mkt = 0.0, None
            else:
                w, mkt = self.weight(pick), pick[3]
            tot = 0.0
            if mkt is not None and mkt in legs:
                tau0, y0, _ = legs[mkt]
                nxt = self.u.obs.get(d2, {}).get(mkt)
                if nxt is None:                       # рынок умер / не наблюдается завтра
                    mkt, w = None, 0.0
                else:
                    y1 = nxt[1]
                    carry, mark = leg_step(y0, float(tau0), y1, dt)
                    y_held.append((w, y0))
                    tot = w * (carry + mark)
                    marks.append(mark)
                    taus.append(float(tau0))
            cost = 0.0
            if mkt != held:                            # перекат: закрыть старое, открыть новое
                if held is not None:
                    cost += self.rt * w_prev
                if mkt is not None:
                    cost += self.rt * w
                    rolls += 1
            else:
                cost += self.rt * abs(w - w_prev)      # оборот сайзера — честная цена DNS
                turnover += abs(w - w_prev)
            cash = (1.0 - w) * math.log1p(self.cash_rate(d)) * dt / 365.0
            fees += cost
            observed += dt
            rets.append((d2, tot + cash - cost))
            held, w_prev = mkt, w
        if not rets:
            raise Unmeasured(f"{self.u.name}: ни одного сомкнутого дня — НЕ ИЗМЕРЕНО")
        return _metrics(rets, rolls=rolls, refusals=refusals, breaks=breaks,
                        marks=marks, taus=taus, turnover=turnover, fees=fees,
                        y_held=y_held, observed=observed)


def _metrics(rets: Sequence[Tuple[str, float]], **extra) -> dict:
    cum, peak, dd = 0.0, 0.0, 0.0
    for _, r in rets:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    span = H.days(rets[0][0], rets[-1][0]) or len(rets)
    # знаменатель — НАБЛЮДЁННЫЕ дни: календарный размах включал бы дыры ряда (у sUSDS
    # между окнами 416 ненаблюдённых дней), и ставка оказалась бы растянутой на них
    observed = extra.get("observed") or len(rets)
    apy = math.expm1(cum * 365.0 / observed)
    maxdd = -math.expm1(-dd)
    calmar = (apy / maxdd) if maxdd > DD_FLOOR_BP / 1e4 else None
    marks = extra.get("marks") or []
    out = dict(days=len(rets), span=span, observed=observed,
               first=rets[0][0], last=rets[-1][0],
               apy=apy, maxdd=maxdd, calmar=calmar,
               calmar_blocked=calmar is None,
               mark_vol=(_stdev(marks) if len(marks) > 1 else None),
               mean_tau=(sum(extra["taus"]) / len(extra["taus"]) if extra.get("taus") else None))
    yh = extra.get("y_held") or []
    wsum = sum(w for w, _y in yh)
    out["y_held_w"] = (sum(w * y for w, y in yh) / wsum) if wsum > 0 else None
    out["w_mean"] = (wsum / len(yh)) if yh else None
    out["fees_bp"] = extra.get("fees", 0.0) * 1e4
    out["turnover"] = extra.get("turnover")
    for k in ("rolls", "refusals", "breaks"):
        out[k] = extra.get(k)
    return out


def _stdev(xs: Sequence[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# ─────────────────────────────── политики ───────────────────────────────

def longest_live(min_tau: int = MIN_TAU_ENTRY) -> Callable:
    """Якорная политика всего реестра: самый ДЛИННЫЙ живой рынок (как #158)."""
    def pick(_day, legs):
        ok = [l for l in legs if l[0] >= min_tau]
        return max(ok, key=lambda l: l[0]) if ok else None
    return pick


def tvl_gated(floor_usd: float, *, require_growth: bool, history: Dict[str, Dict[str, float]],
              lookback: int = 7, invert: bool = False, min_tau: int = MIN_TAU_ENTRY) -> Callable:
    """#166: брать самый длинный рынок, ПРОШЕДШИЙ ворота глубины; иначе следующий; иначе ОТКАЗ.

    `invert=True` — анти-гейт (контроль направления): брать ровно то, что ворота отвергают.
    Новорождённый рынок (нет истории на lookback дней назад) воротами НЕ судится — он
    «ещё не вырос», а не «осушается»: третий исход, и он печатается отдельным счётчиком.
    """
    def ok(day, leg) -> Optional[bool]:
        tau, _y, tvl, mkt = leg
        if tvl is None:
            return None
        if tvl < floor_usd:
            return False
        if not require_growth:
            return True
        prev = history.get(mkt, {}).get(H.shift(day, -lookback))
        if prev is None:
            return None                      # наблюдения нет — не «упал» и не «вырос»
        return tvl >= prev

    def pick(day, legs):
        cand = sorted((l for l in legs if l[0] >= min_tau), key=lambda l: -l[0])
        for leg in cand:
            verdict = ok(day, leg)
            if verdict is None:
                continue
            if verdict != invert:
                return leg
        return None
    return pick


def dns_weight(target_days: float) -> Callable:
    """#165: доля капитала в PT = min(1, D*/τ). Дюрация в долларах постоянна по построению."""
    def w(leg):
        tau = max(float(leg[0]), 1.0)
        return min(1.0, target_days / tau)
    return w


class BandWeight:
    """DNS с анти-черном: вес пересчитывается ТОЛЬКО когда уехал от цели дальше полосы.

    `band=0` тождественно `dns_weight(target)` — это положительный контроль
    эквивалентности, а не удобство. Полоса — ЕДИНСТВЕННЫЙ способ снизить оборот
    сайзера, не меняя его правила: w* = min(1, D*/τ) остаётся целью всегда.
    """

    def __init__(self, target_days: float, band: float) -> None:
        if band < 0:
            raise ValueError("полоса не бывает отрицательной")
        self.target = float(target_days)
        self.band = float(band)
        self.w: Optional[float] = None

    def reset(self) -> None:
        self.w = None

    def __call__(self, leg) -> float:
        tgt = min(1.0, self.target / max(float(leg[0]), 1.0))
        if self.w is None or abs(tgt - self.w) > self.band:
            self.w = tgt
        return self.w


def anti_dns_weight(target_days: float) -> Callable:
    """Контроль направления: вес РАСТЁТ с дюрацией, w = min(1, τ/D*_max).

    Если выигрыш DNS происходит от дюрации (или от инверсии кривой на коротком конце),
    это правило обязано проиграть; если проигрывает и оно — мера слепа, а не находка.
    """
    def w(leg):
        return min(1.0, max(float(leg[0]), 1.0) / (target_days * 3.0))
    return w


def flat_weight(w0: float) -> Callable:
    return lambda _leg: w0


def tvl_history(u: H.Underlying) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for day, obs in u.obs.items():
        for mkt, (_tau, _y, tvl) in obs.items():
            if tvl is not None:
                out.setdefault(mkt, {})[day] = tvl
    return out


def cash_zero(_day: str) -> float:
    return 0.0


def cash_float(u: H.Underlying) -> Callable[[str], float]:
    """Безрисковая нога = ПЛАВАЮЩАЯ ставка базового актива, где она наблюдается.

    Где её нет (USDe: `underlying_yield` = 0 ПО ПОСТРОЕНИЮ) — ветка не выдумывает ставку,
    а возвращает 0 и говорит об этом через `has_float` вызывающего.
    """
    rates = u.float_rates()
    last: List[Tuple[str, float]] = sorted(rates.items())

    def rate(day: str) -> float:
        if day in rates:
            return rates[day]
        prev = [v for d, v in last if d <= day]
        return prev[-1] if prev else 0.0
    return rate


# ─────────────────────────────── §A census ───────────────────────────────

def section_census(us: Dict[str, H.Underlying]) -> dict:
    rows = []
    for name, u in sorted(us.items()):
        taus, tvls, n_null, n_born = [], [], 0, 0
        for day in u.dates:
            for mkt, (tau, _y, tvl) in u.obs[day].items():
                taus.append(tau)
                if tvl is None:
                    n_null += 1
                else:
                    tvls.append(tvl)
                    if tvl < 1000:
                        n_born += 1
        tvls.sort()
        med = tvls[len(tvls) // 2] if tvls else None
        rows.append(dict(underlying=name, obs=len(taus), markets=len(u.maturity),
                         tau_max=max(taus) if taus else None,
                         tau_med=sorted(taus)[len(taus) // 2] if taus else None,
                         tvl_null=n_null, tvl_med=med,
                         tvl_min=tvls[0] if tvls else None,
                         tvl_max=tvls[-1] if tvls else None,
                         tvl_under_1k=n_born, has_float=u.has_float,
                         float_disagreement=u.float_disagreement()))
    if not rows:
        raise Unmeasured("ряд пуст — НЕ ИЗМЕРЕНО")
    return dict(section="census", rows=rows)


# ─────────────────────────────── §B duration (#165) ───────────────────────────────

def mark_vs_tau(u: H.Underlying, *, start=None, end=None) -> dict:
    """Проверка ТОЖДЕСТВА до всякой стратегии: растёт ли |марка| с дюрацией.

    Это не статистическая гипотеза, а контроль проводки: если прибор не видит
    зависимости там, где она есть по построению, он слеп.
    """
    buckets: Dict[str, List[float]] = {"τ<60": [], "60≤τ<180": [], "τ≥180": []}
    dys: Dict[str, List[float]] = {k: [] for k in buckets}
    for d, d2 in zip(u.dates, u.dates[1:]):
        dt = H.days(d, d2)
        if dt <= 0 or dt > MAX_GAP_DAYS:
            continue
        if start and d < start or end and d2 > end:
            continue
        for mkt, (tau, y0, _tvl) in u.obs[d].items():
            nxt = u.obs.get(d2, {}).get(mkt)
            if nxt is None or tau < MIN_TAU_ENTRY:
                continue
            _c, mark = leg_step(y0, float(tau), nxt[1], dt)
            key = "τ<60" if tau < 60 else ("60≤τ<180" if tau < 180 else "τ≥180")
            buckets[key].append(mark)
            dys[key].append(math.log1p(nxt[1]) - math.log1p(y0))
    out = {}
    for k, v in buckets.items():
        out[k] = dict(n=len(v),
                      mark_vol_bp=(_stdev(v) * 1e4 if len(v) > 1 else None),
                      dy_vol_bp=(_stdev(dys[k]) * 1e4 if len(dys[k]) > 1 else None))
    return out


def section_duration(us: Dict[str, H.Underlying], *, targets=(30.0, 60.0, 120.0),
                     roll_cost_bp: float = ROLL_COST_BP) -> dict:
    rows, shape = [], {}
    for name, u in sorted(us.items()):
        shape[name] = mark_vs_tau(u)
        for window, (lo, hi) in (("TRAIN", (None, SEAM)), ("TEST", (SEAM, None)),
                                 ("FULL", (None, None))):
            sel = longest_live()
            for cash_name, cash in (("cash0", cash_zero), ("float", cash_float(u))):
                try:
                    base = Sim(u, select=sel, weight=flat_weight(1.0), cash_rate=cash,
                               roll_cost_bp=roll_cost_bp, start=lo, end=hi).run()
                except H.Unmeasured as exc:
                    rows.append(dict(underlying=name, window=window, cash=cash_name,
                                     policy="buy_and_hold", unmeasured=str(exc)))
                    continue
                rows.append(dict(underlying=name, window=window, cash=cash_name,
                                 policy="buy_and_hold", **base))
                for D in targets:
                    dns = Sim(u, select=sel, weight=dns_weight(D), cash_rate=cash,
                              roll_cost_bp=roll_cost_bp, start=lo, end=hi).run()
                    rows.append(dict(underlying=name, window=window, cash=cash_name,
                                     policy=f"DNS-{D:g}d", target=D, **dns))
                    # ПЛАЦЕБО: статический вес, равный СРЕДНЕМУ весу DNS на том же окне.
                    # Отвечает на «эффект от ЦЕЛЕНИЯ дюрации или просто от того, что меньше».
                    w_bar = min(1.0, D / dns["mean_tau"]) if dns.get("mean_tau") else None
                    if w_bar:
                        flat = Sim(u, select=sel, weight=flat_weight(w_bar), cash_rate=cash,
                                   roll_cost_bp=roll_cost_bp, start=lo, end=hi).run()
                        rows.append(dict(underlying=name, window=window, cash=cash_name,
                                         policy=f"FLAT-{D:g}d", target=D, w=w_bar, **flat))
    if not rows:
        raise Unmeasured("ни одного прогона — НЕ ИЗМЕРЕНО")
    return dict(section="duration", shape=shape, rows=rows)


def section_breakeven(us: Dict[str, H.Underlying], *,
                      target: float = 60.0,
                      bands=(0.0, 0.05, 0.10, 0.25),
                      costs=(0.0, 10.0, 25.0, 50.0, 96.0),
                      only=("sUSDe", "USDe", "eETH")) -> dict:
    """ГДЕ ИМЕННО DNS умирает от пошлины — граница, а не вердикт «дорого».

    Меряются ровно те активы, у которых есть ОБА окна (TRAIN и TEST): вывод о
    переносе невозможен там, где рынки умерли до шва, и выдавать FULL за TEST
    запрещено.
    """
    rows = []
    for name in only:
        u = us.get(name)
        if u is None:
            rows.append(dict(underlying=name, unmeasured="актива нет в ряде"))
            continue
        for window, (lo, hi) in (("TRAIN", (None, SEAM)), ("TEST", (SEAM, None))):
            for cost in costs:
                try:
                    bh = Sim(u, select=longest_live(), weight=flat_weight(1.0),
                             cash_rate=cash_zero, roll_cost_bp=cost,
                             start=lo, end=hi).run()
                except H.Unmeasured as exc:
                    rows.append(dict(underlying=name, window=window, cost_bp=cost,
                                     unmeasured=str(exc)))
                    continue
                rows.append(dict(underlying=name, window=window, cost_bp=cost,
                                 policy="buy_and_hold", **bh))
                anti = Sim(u, select=longest_live(), weight=anti_dns_weight(target),
                           cash_rate=cash_zero, roll_cost_bp=cost,
                           start=lo, end=hi).run()
                rows.append(dict(underlying=name, window=window, cost_bp=cost,
                                 policy="ANTI-DNS", **anti))
                for band in bands:
                    r = Sim(u, select=longest_live(), weight=BandWeight(target, band),
                            cash_rate=cash_zero, roll_cost_bp=cost,
                            start=lo, end=hi).run()
                    rows.append(dict(underlying=name, window=window, cost_bp=cost,
                                     policy=f"DNS-{target:g}d/band{band:g}",
                                     band=band, **r))
                w_bar = min(1.0, target / bh["mean_tau"]) if bh.get("mean_tau") else None
                if w_bar:
                    f = Sim(u, select=longest_live(), weight=flat_weight(w_bar),
                            cash_rate=cash_zero, roll_cost_bp=cost,
                            start=lo, end=hi).run()
                    rows.append(dict(underlying=name, window=window, cost_bp=cost,
                                     policy=f"FLAT-{target:g}d", w=w_bar, **f))
    if not rows:
        raise Unmeasured("ни одной ячейки — НЕ ИЗМЕРЕНО")
    return dict(section="breakeven", target=target, rows=rows)


# ─────────────────────────────── §C liquidity (#166) ───────────────────────────────

def tvl_conditional(u: H.Underlying, *, horizon: int = 7, floor_usd: float = 1e6) -> dict:
    """Несёт ли TVL информацию о БУДУЩЕЙ марке. Причинность по построению: условие из дня d,
    марка читается строго позже. Независимые винтажи считаются рядом с n (урок #117)."""
    recs: List[dict] = []
    hist = tvl_history(u)
    for d in u.dates:
        d2 = H.shift(d, horizon)
        for mkt, (tau, y0, tvl) in u.obs[d].items():
            if tvl is None or tau < MIN_TAU_ENTRY + horizon:
                continue
            nxt = u.obs.get(d2, {}).get(mkt)
            if nxt is None:
                continue
            prev = hist.get(mkt, {}).get(H.shift(d, -horizon))
            _c, mark = leg_step(y0, float(tau), nxt[1], horizon)
            recs.append(dict(date=d, tau=horizon, market=mkt, mark=mark, tvl=tvl,
                             growth=(None if prev is None else tvl - prev),
                             rich=tvl >= floor_usd))
    if not recs:
        return dict(n=0, unmeasured="ни одной пары (TVL, будущая марка) — НЕ ИЗМЕРЕНО")
    indep = H.non_overlapping(recs)
    out = dict(n=len(recs), independent=len(indep))
    for label, pool in (("all", recs), ("indep", indep)):
        rich = [r["mark"] for r in pool if r["rich"]]
        thin = [r["mark"] for r in pool if not r["rich"]]
        grow = [r["mark"] for r in pool if r["growth"] is not None and r["growth"] >= 0]
        drain = [r["mark"] for r in pool if r["growth"] is not None and r["growth"] < 0]
        out[label] = dict(
            rich_n=len(rich), rich_mean_bp=_mean_bp(rich),
            thin_n=len(thin), thin_mean_bp=_mean_bp(thin),
            grow_n=len(grow), grow_mean_bp=_mean_bp(grow),
            drain_n=len(drain), drain_mean_bp=_mean_bp(drain),
            drain_sign_p=H.sign_test_p(sum(1 for m in drain if m > 0), len(drain)),
            no_growth_obs=sum(1 for r in pool if r["growth"] is None),
        )
    return out


def _mean_bp(xs: Sequence[float]) -> Optional[float]:
    return (sum(xs) / len(xs) * 1e4) if xs else None


def section_liquidity(us: Dict[str, H.Underlying], *, floor_usd: float = 1e6) -> dict:
    cond, rows = {}, []
    for name, u in sorted(us.items()):
        cond[name] = tvl_conditional(u, floor_usd=floor_usd)
        hist = tvl_history(u)
        for window, (lo, hi) in (("TRAIN", (None, SEAM)), ("TEST", (SEAM, None)),
                                 ("FULL", (None, None))):
            policies = {
                "ungated": longest_live(),
                "LDG-floor": tvl_gated(floor_usd, require_growth=False, history=hist),
                "LDG-floor+growth": tvl_gated(floor_usd, require_growth=True, history=hist),
                "ANTI-LDG": tvl_gated(floor_usd, require_growth=True, history=hist, invert=True),
            }
            for pname, sel in policies.items():
                try:
                    r = Sim(u, select=sel, weight=flat_weight(1.0),
                            cash_rate=cash_zero, start=lo, end=hi).run()
                except H.Unmeasured as exc:
                    rows.append(dict(underlying=name, window=window, policy=pname,
                                     unmeasured=str(exc)))
                    continue
                rows.append(dict(underlying=name, window=window, policy=pname, **r))
    if not rows:
        raise Unmeasured("ни одного прогона — НЕ ИЗМЕРЕНО")
    return dict(section="liquidity", floor_usd=floor_usd, conditional=cond, rows=rows)


# ─────────────────────────────── печать ───────────────────────────────

def _fmt(v, nd=2, pct=False):
    if v is None:
        return "НЕ ИЗМЕРЕНО"
    if pct:
        return f"{v * 100:.{nd}f}%"
    return f"{v:.{nd}f}"


def print_census(res: dict) -> None:
    print("\n§A ПЕРЕПИСЬ РЯДА (до всякой гипотезы)")
    print(f"{'актив':8s} {'строк':>6s} {'рынков':>7s} {'τmax':>6s} {'τmed':>6s} "
          f"{'tvl=null':>9s} {'tvl med $':>13s} {'tvl<$1k':>8s} {'float':>6s}")
    for r in res["rows"]:
        med = "НЕ ИЗМ" if r["tvl_med"] is None else format(r["tvl_med"], ",.0f")
        print(f"{r['underlying']:8s} {r['obs']:6d} {r['markets']:7d} {str(r['tau_max']):>6s} "
              f"{str(r['tau_med']):>6s} {r['tvl_null']:9d} "
              f"{med:>13s} "
              f"{r['tvl_under_1k']:8d} {str(r['has_float']):>6s}")


def print_duration(res: dict) -> None:
    print("\n§B1 МАРКА ПРОТИВ ДЮРАЦИИ — контроль проводки (волатильность дневной марки, bp)")
    print(f"{'актив':8s} {'τ<60 n/vol':>18s} {'60≤τ<180 n/vol':>20s} {'τ≥180 n/vol':>20s}")
    for name, sh in res["shape"].items():
        cells = []
        for k in ("τ<60", "60≤τ<180", "τ≥180"):
            b = sh[k]
            cells.append(f"{b['n']}/{_fmt(b['mark_vol_bp'])}")
        print(f"{name:8s} {cells[0]:>18s} {cells[1]:>20s} {cells[2]:>20s}")
    print("\n§B2 DNS против покупки-и-держания (безрисковая нога = 0 %, пошлина 96 bp)")
    print(f"{'актив':8s} {'окно':6s} {'политика':12s} {'дней':>5s} {'APY':>9s} "
          f"{'maxDD':>8s} {'Calmar':>8s} {'перекат':>7s} {'ср.τ':>6s} {'оборот':>7s} {'пошл bp':>8s}")
    for r in res["rows"]:
        if r.get("cash") != "cash0" or r.get("unmeasured"):
            if r.get("unmeasured") and r.get("cash") == "cash0":
                print(f"{r['underlying']:8s} {r['window']:6s} {r['policy']:12s} "
                      f"НЕ ИЗМЕРЕНО: {r['unmeasured']}")
            continue
        print(f"{r['underlying']:8s} {r['window']:6s} {r['policy']:12s} {r['days']:5d} "
              f"{_fmt(r['apy'], 2, True):>9s} {_fmt(r['maxdd'], 2, True):>8s} "
              f"{_fmt(r['calmar']):>8s} {str(r['rolls']):>7s} {_fmt(r['mean_tau'], 0):>6s} "
              f"{_fmt(r['turnover'], 2):>7s} {_fmt(r['fees_bp'], 0):>8s}")


def print_breakeven(res: dict) -> None:
    print(f"\n§B3 ГРАНИЦА ПО ПОШЛИНЕ (цель D* = {res['target']:g} дн; Calmar, безрисковая нога 0 %)")
    print(f"{'актив':8s} {'окно':6s} {'политика':22s} " +
          " ".join(f"{c:>9s}" for c in ("0bp", "10bp", "25bp", "50bp", "96bp")))
    by = {}
    for r in res["rows"]:
        if r.get("unmeasured"):
            continue
        by.setdefault((r["underlying"], r["window"], r["policy"]), {})[r["cost_bp"]] = r
    for (name, window, policy), cells in by.items():
        line = []
        for c in (0.0, 10.0, 25.0, 50.0, 96.0):
            r = cells.get(c)
            line.append("—" if r is None else _fmt(r["calmar"], 2))
        print(f"{name:8s} {window:6s} {policy:22s} " + " ".join(f"{x:>9s}" for x in line))
    for r in res["rows"]:
        if r.get("unmeasured"):
            print(f"{r['underlying']:8s} {r.get('window', '-'):6s} НЕ ИЗМЕРЕНО: {r['unmeasured']}")


def print_liquidity(res: dict) -> None:
    print(f"\n§C1 НЕСЁТ ЛИ TVL ИНФОРМАЦИЮ О БУДУЩЕЙ МАРКЕ (порог ${res['floor_usd']:,.0f}, горизонт 7 дн)")
    print(f"{'актив':8s} {'n':>5s} {'незав':>6s} {'богат n/bp':>16s} {'тонк n/bp':>16s} "
          f"{'растёт n/bp':>16s} {'сохнет n/bp':>16s} {'sign-p':>7s} {'нет набл':>8s}")
    for name, c in res["conditional"].items():
        if c.get("n", 0) == 0:
            print(f"{name:8s} НЕ ИЗМЕРЕНО: {c.get('unmeasured')}")
            continue
        i = c["indep"]
        cell = lambda nk, mk: f"{i[nk]}/{_fmt(i[mk])}"  # noqa: E731
        print(f"{name:8s} {c['n']:5d} {c['independent']:6d} "
              f"{cell('rich_n', 'rich_mean_bp'):>16s} {cell('thin_n', 'thin_mean_bp'):>16s} "
              f"{cell('grow_n', 'grow_mean_bp'):>16s} {cell('drain_n', 'drain_mean_bp'):>16s} "
              f"{_fmt(i['drain_sign_p'], 3):>7s} {i['no_growth_obs']:8d}")
    print("\n§C2 ВОРОТА ГЛУБИНЫ как правило входа (вес 1.0, безрисковая нога 0 %)")
    print(f"{'актив':8s} {'окно':6s} {'политика':18s} {'дней':>5s} {'APY':>9s} "
          f"{'maxDD':>8s} {'Calmar':>8s} {'отказов':>8s}")
    for r in res["rows"]:
        if r.get("unmeasured"):
            print(f"{r['underlying']:8s} {r['window']:6s} {r['policy']:18s} "
                  f"НЕ ИЗМЕРЕНО: {r['unmeasured']}")
            continue
        print(f"{r['underlying']:8s} {r['window']:6s} {r['policy']:18s} {r['days']:5d} "
              f"{_fmt(r['apy'], 2, True):>9s} {_fmt(r['maxdd'], 2, True):>8s} "
              f"{_fmt(r['calmar']):>8s} {str(r['refusals']):>8s}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#165 DNS + #166 LDG на реальном ряде PT")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--section", choices=("census", "duration", "breakeven",
                                          "liquidity", "all"), default="all")
    ap.add_argument("--floor-usd", type=float, default=1e6)
    ap.add_argument("--roll-cost-bp", type=float, default=ROLL_COST_BP,
                    help="пошлина входа/выхода и оборота сайзера; 0 = валовое разложение")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        us = H.load(a.data_dir)
    except H.Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    out = {}
    try:
        if a.section in ("census", "all"):
            out["census"] = section_census(us)
        if a.section in ("duration", "all"):
            out["duration"] = section_duration(us, roll_cost_bp=a.roll_cost_bp)
        if a.section in ("breakeven", "all"):
            out["breakeven"] = section_breakeven(us)
        if a.section in ("liquidity", "all"):
            out["liquidity"] = section_liquidity(us, floor_usd=a.floor_usd)
    except H.Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print("#165 DNS (дюрация известна ПО КОНТРАКТУ) · #166 LDG (ворота глубины) — "
          "advisory, read-only, вне RiskPolicy")
    if "census" in out:
        print_census(out["census"])
    if "duration" in out:
        print_duration(out["duration"])
    if "breakeven" in out:
        print_breakeven(out["breakeven"])
    if "liquidity" in out:
        print_liquidity(out["liquidity"])
    print("\nХВОСТ, КОТОРЫЙ НЕ ИЗМЕРЕН НИ ОДНОЙ СТРОКОЙ ВЫШЕ: депег USDe/sUSDe, слэшинг LRT,")
    print("срыв погашения. Дюрация и TVL — про МЕДЛЕННЫЙ риск; gap-риск остаётся целиком.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
