#!/usr/bin/env python3
"""
scripts/edge_exogenous_lead_hedge.py — ONE instrument, TWO registry ideas, both measured on
REAL series only:

  #169 XLT  — eXogenous Lead-Time census.  ИСПОЛНЕНИЕ ЗАКАЗА #168: «проверить, различает ли
              МЕДЛЕННУЮ просадку заранее (до 2025-10-08) хоть один причинный признак из уже
              снятых рядов (`data/rates_desk/`, funding-режим) — и если нет, записать это как
              предел панели».
  #170 CACH-REAL — пассивный бета-хедж (#20 CACH) на РЕАЛЬНОЙ панели и с НАБЛЮДЁННЫМ funding,
              а не на фикстуре с детерминированно отрицательной книгой.  #20 сам назвал это
              своей главной оговоркой («реальный break-even h НИЖЕ показанного»).

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

────────────────────────────────────────────────────────────────────────────────────────────
ПОЧЕМУ ОДИН ПРИБОР НА ДВЕ ЗАПИСИ.  Обе читают ОДНУ пару входов — реальную 10-книжную панель
(`data/aggressive_lab/*/realized_series.jsonl`, блок phase="backtest", загрузчик
`edge_real_panel_ensemble.plb_load`) и реальные экзогенные ряды `data/rates_desk/`
(`prices_deep.json` · `funding_deep.json` · `restaking_deep.json`).  Вторая копия загрузчика
и копия модели пошлины разошлись бы при первом же пересчёте (порядок «одно правило — одна
копия», `.claude/rules/deployment.md`), и тогда две записи реестра спорили бы друг с другом
о числах, снятых с одного файла.

────────────────────────────────────────────────────────────────────────────────────────────
#169 XLT — МЕХАНИЗМ ЗАМЕРА (всё объявлено ДО прогона).

  1. ПРЕДМЕТ — МЕДЛЕННАЯ просадка, а не день стресса.  Эпизод = связный отрезок, на котором
     трейлинг-просадка EW-портфеля ниже SLOW_DEPTH, длиной ≥ SLOW_DAYS.  Именно их #168 назвал
     невидимыми для любой меры короткого окна из ряда #119…#168.
  2. ПРИЗНАК ПРИЧИННЫЙ И ЭКЗОГЕННЫЙ.  Одиннадцать признаков считаются ТОЛЬКО из рядов
     `data/rates_desk/` по день t включительно; метка — знак доходности портфеля за дни
     t+1 … t+H.  Собственная кривая портфеля в признак не входит ни одним слагаемым: её
     бесполезность уже измерена двадцатью записями ряда #119…#168, предмет здесь — ДОБАВЛЯЕТ
     ли что-нибудь ВНЕШНИЙ ряд.
  3. ПРОПУСК РЯДА — ТРЕТИЙ ИСХОД, а не подстановка.  Ряд цен несёт 591 день на 852 днях оси
     (гистограмма зазоров: 1 д × 427, 2 д × 163).  Протяжка значения разрешена на зазор
     ≤ MAX_FILL_GAP_DAYS, дальше признак равен None и в замер не входит.  Ноль здесь был бы
     наблюдением, которого нет (инв. #17).
  4. МЕРА — AUC, и порог для неё не нужен.  AUC = доля пар (день с убытком вперёд, день без),
     упорядоченных признаком верно.  0.5 — «ничего»; НИЖЕ 0.5 — признак работает НАОБОРОТ, и
     это отдельный результат, а не отсутствие результата.
  5. ПЛАЦЕБО СЕМЕЙНОЕ, а не на один признак.  Метки перекрываются (окно H дней), поэтому
     номинальные p-значения здесь смысла не имеют.  Нуль-распределение строится циклическим
     сдвигом ряда признака (автокорреляция признака и метки сохраняются, выравнивание между
     ними разрушается), и на каждом розыгрыше ОДИН И ТОТ ЖЕ сдвиг применяется ко ВСЕМ
     признакам, а статистика — МАКСИМУМ |AUC − 0.5| по семейству.  Иначе одиннадцать попыток
     подарят «значимый» признак сами по себе.
  6. ПОТОЛОК МОЩНОСТИ НАЗЫВАЕТСЯ ЧИСЛОМ (урок #157 IOB).  Независимых наблюдений здесь не
     822 дня, а ЭПИЗОДОВ: их печатает §1.
  7. ДЕЙСТВУЮЩЕЕ ПЛЕЧО правила — гейт «признак за порогом ⇒ портфель в кэш», порог выбран ТОЛЬКО
     на TRAIN, пошлина TOLL за смену состояния, и РЯДОМ — статический двойник с той же средней
     долей кэша и нулевым таймингом (урок #120: выигрыш оверлея обычно оказывается не моментом
     выхода, а средним весом, к которому правило приходит).

#170 CACH-REAL — МЕХАНИЗМ ЗАМЕРА.

  β портфеля к ETH оценивается ТОЛЬКО на TRAIN (OLS дневных доходностей), хедж — короткий
  ETH-перп номиналом h·β от капитала:

      r_hedged(t) = r_panel(t) − h·β·r_eth(t) + h·β·f(t) − пошлина,

  где f(t) — НАБЛЮДЁННЫЙ funding того дня (`funding_deep.json`), а КОНВЕНЦИЯ ЗНАКА объявлена:
  f > 0 ⇒ длинные платят короткому, то есть короткая нога ПОЛУЧАЕТ f.  Если конвенция ряда
  обратная, слагаемое funding меняет знак — и его величина печатается отдельной строкой
  именно поэтому: вывод не должен зависеть от того, чего прибор не проверял.

  Разложение обязательно и печатается по частям: НАПРАВЛЕНИЕ (−h·β·Σr_eth) · FUNDING
  (h·β·Σf) · ПОШЛИНА.  За окно замера ETH прошёл −56.9 % — в таком окне короткая нога
  зарабатывает просто потому, что цена падала.  Это СВОЙСТВО ОКНА, не эдж, и смешивать его
  с сокращением дисперсии запрещено (инв. #8).

  БАЗИС НЕ ИЗМЕРИМ ИЗ ЭТОГО ФАЙЛА, и это названный третий исход.  Хедж ETH-беты у книги на
  LRT оставляет остаточный риск eETH/ETH.  `prices_deep.json` несёт ДНЕВНЫЕ цены без отметок
  времени, а частное двух дневных цен — по ADR-139 — в основном рассинхрон внутридневных
  принтов, а не отвязка (замер прибором: σ 3.10 %/д, разброс 0.825…1.140 — у настоящего eETH
  такого хода нет).  Поэтому вместо выдуманного базиса прибор печатает BREAK-EVEN: при какой
  σ остаточного базиса преимущество хеджа по просадке обнуляется.

ТРЕТИЙ ИСХОД (инв. #17) — ОТКАЗ кодом 2 с названной причиной, никогда ноль и никогда «эджа
нет»: файла нет · ряд цен короче MIN_PRICE_DAYS · медленных эпизодов меньше MIN_EPISODES ·
пересечение оси панели с рядом цен короче MIN_PAIRED_DAYS · дисперсия ETH на TRAIN равна нулю.

stdlib-only, детерминированно, read-only (на диск не пишется ничего), LLM FORBIDDEN.  Живой
трек не открывается; RiskPolicy v1.0, ступени kill-switch и потолок 20 %/имя не тронуты
(равный вес по 10 книгам = 10 %/имя).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_real_panel_ensemble as rpe  # noqa: E402

IS_ADVISORY: bool = True
OUTSIDE_RISKPOLICY: bool = True

ROOT = Path(__file__).resolve().parent.parent
RATES_DIR = ROOT / "data" / "rates_desk"

TOLL = rpe.PLB_ROUNDTRIP            # 96 bp round trip — конвенция #149, унаследована
SPLIT = rpe.TRAIN_END               # 2025-06-30, шов конвенции #153
WINDOWS = rpe.CRISIS_WINDOWS

# — #169 —
MAX_FILL_GAP_DAYS = 3               # протяжка значения ряда; дальше признак = None
SLOW_DAYS = 60                      # «медленная» просадка — предмет заказа #168
SLOW_DEPTH = -0.01                  # глубина, ниже которой отрезок считается просадкой
HORIZONS = (30, 60, 90)
PLACEBO_DRAWS = 2000
SEED = 169
MIN_EPISODES = 2
MIN_PRICE_DAYS = 200
MIN_PAIRED_DAYS = 300

# — #170 —
HEDGE_RATIOS = (0.0, 0.25, 0.5, 0.75, 1.0)
HEDGE_MAINT_BPS_PER_YEAR = (0.0, 50.0, 100.0)   # чувствительность к стоимости поддержания
BASIS_SIGMAS = (0.0, 0.0005, 0.001, 0.002, 0.005, 0.01)  # дневная σ остаточного базиса
BASIS_DRAWS = 200

RWA_FLOOR_DAILY = 0.034 / 365.0     # пол RWA 3.4 %/год — та же «кэш»-нога, что в #159/#168


class Unmeasured(RuntimeError):
    """Третий исход: замер не состоялся, и причина названа."""


# ── чтение рядов ────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    if not path.exists():
        raise Unmeasured(f"файла нет: {path}")
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"{path.name} не разбирается: {exc}") from exc


def load_series(rates_dir: Path = RATES_DIR) -> Dict[str, Dict[str, float]]:
    """{имя: {дата: значение}} по трём реальным наборам.  Отсутствие набора — ОТКАЗ."""
    prices = (_read_json(rates_dir / "prices_deep.json").get("series") or {})
    eth = {k: float(v) for k, v in (prices.get("eth") or {}).items() if v is not None}
    if len(eth) < MIN_PRICE_DAYS:
        raise Unmeasured(f"ряд цен ETH слишком короток: {len(eth)} < {MIN_PRICE_DAYS}")
    funding_doc = _read_json(rates_dir / "funding_deep.json")
    funding = {k: float(v) for k, v in (funding_doc.get("series") or {}).items() if v is not None}
    rest = (_read_json(rates_dir / "restaking_deep.json").get("series") or {})
    reth = {k: float(v) for k, v in (rest.get("reth") or {}).items() if v is not None}
    out = {"eth": eth, "funding": funding, "reth": reth}
    eeth = {k: float(v) for k, v in (prices.get("eeth") or {}).items() if v is not None}
    if eeth:
        out["eeth"] = eeth
    return out


def align(series: Dict[str, float], axis: Sequence[str],
          max_gap: int = MAX_FILL_GAP_DAYS) -> List[Optional[float]]:
    """Ряд на ось панели: значение протягивается не дальше `max_gap` дней, иначе None.

    None — ЧЕСТНОЕ «наблюдения нет» (инв. #17).  Ноль здесь был бы выдуманным наблюдением,
    а бесконечная протяжка выдавала бы устаревшее число за сегодняшнее (#154 FMP).
    """
    out: List[Optional[float]] = []
    last: Optional[float] = None
    last_d: Optional[datetime.date] = None
    for d in axis:
        day = datetime.date.fromisoformat(d)
        if d in series:
            last, last_d = series[d], day
        if last is None or last_d is None:
            out.append(None)
            continue
        out.append(last if (day - last_d).days <= max_gap else None)
    return out


# ── портфель и просадки ─────────────────────────────────────────────────────────────────────

def require_straddle(label: str, train: Sequence[int], test: Sequence[int]) -> None:
    """Ось обязана ЛЕЖАТЬ ПО ОБЕ СТОРОНЫ шва, иначе сравнение TRAIN/TEST не состоялось.

    Без этой двери `perf([])` вернул бы нули, и ПУСТОЕ окно стало бы неотличимо от окна,
    в котором доходность измерена и равна нулю (инв. #17).  Сцена, нашедшая дверь, —
    синтетическая ось целиком до шва: прибор печатал «TEST APY 0.00 %» про окно, которого
    у него не было.
    """
    if not train or not test:
        raise Unmeasured(
            f"{label}: ось не пересекает шов {SPLIT} — TRAIN {len(train)} д / TEST "
            f"{len(test)} д; сравнение обучающего и тестового окна не состоялось")


def ew_returns(rets: Mapping[str, Sequence[float]], books: Sequence[str]) -> List[float]:
    """Равновесный портфель с ежедневным ребалансом — та же база, что в #167/#168."""
    n = len(next(iter(rets.values())))
    return [statistics.mean(rets[b][i] for b in books) for i in range(n)]


def trailing_drawdown(returns: Sequence[float]) -> List[float]:
    eq, peak, out = 1.0, 1.0, []
    for r in returns:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        out.append(eq / peak - 1.0)
    return out


def slow_episodes(returns: Sequence[float], axis: Sequence[str], *,
                  min_days: int = SLOW_DAYS,
                  depth: float = SLOW_DEPTH) -> List[dict]:
    """Связные отрезки просадки глубже `depth`, длиной ≥ `min_days` — независимые наблюдения."""
    dd = trailing_drawdown(returns)
    spans: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, v in enumerate(dd):
        if v < depth:
            if start is None:
                start = i
        elif start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(dd) - 1))
    out: List[dict] = []
    for a, b in spans:
        if b - a + 1 < min_days:
            continue
        seg = dd[a:b + 1]
        t = a + seg.index(min(seg))
        out.append({"start": axis[a], "end": axis[b], "days": b - a + 1,
                    "trough": min(seg), "trough_date": axis[t],
                    "start_idx": a, "trough_idx": t})
    return out


# ── признаки (#169) ─────────────────────────────────────────────────────────────────────────

def build_features(series: Dict[str, Dict[str, float]], axis: Sequence[str]) -> Dict[str, List[Optional[float]]]:
    """Одиннадцать ПРИЧИННЫХ экзогенных признаков по день t включительно.

    Ни один не читает кривую портфеля — предмет замера именно в этом.
    """
    n = len(axis)
    eth = align(series["eth"], axis)
    fund = align(series.get("funding", {}), axis)
    reth = align(series.get("reth", {}), axis)

    def ratio(src: List[Optional[float]], k: int):
        def f(i: int) -> Optional[float]:
            if i - k < 0:
                return None
            a, b = src[i], src[i - k]
            if a is None or b is None or b == 0:
                return None
            return a / b - 1.0
        return f

    def window(src: List[Optional[float]], k: int, fn):
        def f(i: int) -> Optional[float]:
            if i - k < 0:
                return None
            w = src[i - k:i + 1]
            if any(v is None for v in w):
                return None
            return fn([v for v in w if v is not None])
        return f

    def realised_vol(w: Sequence[float]) -> Optional[float]:
        r = [w[j] / w[j - 1] - 1.0 for j in range(1, len(w)) if w[j - 1]]
        return statistics.stdev(r) if len(r) > 1 else None

    def mean_level(src: List[Optional[float]], k: int):
        def f(i: int) -> Optional[float]:
            if i - k + 1 < 0:
                return None
            w = src[i - k + 1:i + 1]
            if any(v is None for v in w):
                return None
            return statistics.mean([v for v in w if v is not None])
        return f

    defs = {
        "eth_mom_30": ratio(eth, 30),
        "eth_mom_90": ratio(eth, 90),
        "eth_mom_180": ratio(eth, 180),
        "eth_dd_90": window(eth, 90, lambda w: w[-1] / max(w) - 1.0),
        "eth_vol_14": window(eth, 14, realised_vol),
        "eth_vol_60": window(eth, 60, realised_vol),
        "fund_7": mean_level(fund, 7),
        "fund_30": mean_level(fund, 30),
        "rest_level": lambda i: reth[i],
        "rest_chg_30": ratio(reth, 30),
    }
    feats = {k: [fn(i) for i in range(n)] for k, fn in defs.items()}
    f7, f30 = feats["fund_7"], feats["fund_30"]
    feats["fund_slope"] = [None if (f7[i] is None or f30[i] is None) else f7[i] - f30[i]
                           for i in range(n)]
    return feats


def forward_return(returns: Sequence[float], i: int, h: int) -> Optional[float]:
    """Доходность дней t+1 … t+h.  Признак дня t её не видит — ни одним слагаемым."""
    if i + h >= len(returns):
        return None
    out = 1.0
    for j in range(i + 1, i + 1 + h):
        out *= (1.0 + returns[j])
    return out - 1.0


def forward_loss_labels(returns: Sequence[float], h: int) -> List[Optional[bool]]:
    """Метка дня t: доход дней t+1…t+h отрицателен.  Хвост оси — None («не измерено»)."""
    out: List[Optional[bool]] = []
    for i in range(len(returns)):
        fr = forward_return(returns, i, h)
        out.append(None if fr is None else fr < 0.0)
    return out


def auc(x: Sequence[Optional[float]], y: Sequence[Optional[bool]]) -> Optional[float]:
    """AUC: доля верно упорядоченных пар (метка True против метки False).  Связки — 0.5."""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    pos = sorted(a for a, b in pairs if b)
    neg = sorted(a for a, b in pairs if not b)
    if not pos or not neg:
        return None
    total = 0.0
    for p in pos:
        lo = _bisect_left(neg, p)
        hi = _bisect_right(neg, p)
        total += lo + 0.5 * (hi - lo)
    return total / (len(pos) * len(neg))


def _bisect_left(a: Sequence[float], x: float) -> int:
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(a: Sequence[float], x: float) -> int:
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def family_placebo(feats: Dict[str, List[Optional[float]]], labels: Sequence[Optional[bool]], *,
                   draws: int = PLACEBO_DRAWS,
                   seed: int = SEED) -> Tuple[Dict[str, float], List[float]]:
    """СЕМЕЙНОЕ нуль-распределение МАКСИМУМА |AUC−0.5| при циклическом сдвиге всех признаков.

    Один и тот же сдвиг применяется ко ВСЕМ признакам на розыгрыше: одиннадцать независимых
    попыток иначе подарили бы «значимый» признак сами по себе.
    """
    n = len(labels)
    names = sorted(feats)
    rnd = random.Random(seed)
    devs: List[float] = []
    for _ in range(draws):
        s = rnd.randrange(1, n) if n > 1 else 0
        best = 0.0
        for name in names:
            src = feats[name]
            shifted = [src[(i + s) % n] for i in range(n)]
            a = auc(shifted, labels)
            if a is not None:
                best = max(best, abs(a - 0.5))
        devs.append(best)
    devs.sort()
    if not devs:
        raise Unmeasured("плацебо не дало ни одного розыгрыша")
    return ({"median": statistics.median(devs),
             "p95": devs[min(len(devs) - 1, int(0.95 * len(devs)))],
             "max": devs[-1],
             "draws": float(len(devs))}, devs)


def placebo_percentile(devs: Sequence[float], value: float) -> float:
    return sum(1 for d in devs if d < value) / len(devs)


# ── гейт и его статический двойник (#169 §4) ────────────────────────────────────────────────

def gate_overlay(returns: Sequence[float], flag: Sequence[Optional[bool]], *,
                 toll: float = TOLL,
                 safe_daily: float = RWA_FLOOR_DAILY) -> Tuple[List[float], int, float]:
    """Портфель, уходящий в кэш, когда флаг дня (причинный, по t−1) взведён.

    Возвращает (доходности, число смен состояния, средняя доля риска).  Признак None =
    «не измерено» ⇒ состояние НЕ меняется (fail-CLOSED к текущему состоянию, не к риску).
    """
    out: List[float] = []
    changes = 0
    in_cash = False
    risk_days = 0
    for i, r in enumerate(returns):
        want = flag[i]
        if want is not None and bool(want) != in_cash:
            in_cash = bool(want)
            changes += 1
            out.append((safe_daily if in_cash else r) - toll)
        else:
            out.append(safe_daily if in_cash else r)
        risk_days += 0 if in_cash else 1
    return out, changes, risk_days / len(returns) if returns else 0.0


def static_twin(returns: Sequence[float], risk_share: float, *,
                safe_daily: float = RWA_FLOOR_DAILY) -> List[float]:
    """Та же СРЕДНЯЯ доля риска, ноль тайминга — контроль урока #120."""
    return [risk_share * r + (1.0 - risk_share) * safe_daily for r in returns]


def causal_flag(values: Sequence[Optional[float]], threshold: float, *,
                above: bool) -> List[Optional[bool]]:
    """Флаг дня t читает признак дня t−1: решение не видит собственного дня."""
    out: List[Optional[bool]] = [None]
    for v in values[:-1]:
        out.append(None if v is None else ((v > threshold) if above else (v < threshold)))
    return out


def choose_threshold(values: Sequence[Optional[float]], returns: Sequence[float],
                     idx: Sequence[int], *, above: bool,
                     quantiles: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5)) -> Optional[dict]:
    """Порог выбирается ТОЛЬКО на переданных днях (TRAIN) и только по Calmar."""
    obs = sorted(v for i, v in enumerate(values) if i in set(idx) and v is not None)
    if len(obs) < 30:
        return None
    best: Optional[dict] = None
    for q in quantiles:
        t = obs[min(len(obs) - 1, int((1.0 - q) * len(obs)) if above else int(q * len(obs)))]
        flag = causal_flag(values, t, above=above)
        sub = [returns[i] for i in idx]
        subflag = [flag[i] for i in idx]
        ov, changes, share = gate_overlay(sub, subflag)
        m = rpe.perf(ov)
        if best is None or m["calmar"] > best["calmar"]:
            best = {"q": q, "threshold": t, "calmar": m["calmar"], "apy": m["apy"],
                    "maxdd": m["maxdd"], "changes": changes, "risk_share": share,
                    "above": above}
    return best


# ── #170 бета-хедж ──────────────────────────────────────────────────────────────────────────

def paired_axis(axis: Sequence[str], eth: Dict[str, float]) -> List[int]:
    """Индексы оси панели, у которых есть наблюдение цены И предыдущее наблюдение цены."""
    have = [i for i, d in enumerate(axis) if d in eth]
    return have


def ols_beta(x: Sequence[float], y: Sequence[float]) -> float:
    """β = cov(x,y)/var(x).  Нулевая дисперсия x — ОТКАЗ, а не ноль."""
    if len(x) < 30:
        raise Unmeasured(f"для β слишком мало пар: {len(x)}")
    vx = statistics.variance(x)
    if vx <= 0:
        raise Unmeasured("дисперсия ETH на обучающем окне равна нулю — β не определена")
    mx, my = statistics.mean(x), statistics.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)
    return cov / vx


def hedged_returns(panel: Sequence[float], eth_r: Sequence[float], fund: Sequence[Optional[float]],
                   *, h: float, beta: float, maint_bps_year: float = 0.0,
                   entry_toll: float = TOLL) -> Tuple[List[float], Dict[str, float]]:
    """r_hedged = r_panel − h·β·r_eth + h·β·f − поддержание; пошлина входа один раз.

    КОНВЕНЦИЯ ЗНАКА объявлена: f > 0 ⇒ длинные платят, короткая нога ПОЛУЧАЕТ f.  День без
    наблюдения funding даёт нулевой ВКЛАД funding и считается в счётчик `funding_unmeasured`
    — «не измерено» остаётся различимым от «funding был равен нулю» (инв. #17).
    """
    notional = h * beta
    maint = (maint_bps_year / 10000.0) / 365.0 * notional
    out: List[float] = []
    direction = 0.0
    carry = 0.0
    unmeasured = 0
    for i, (rp, re) in enumerate(zip(panel, eth_r)):
        d = -notional * re
        f = fund[i]
        if f is None:
            unmeasured += 1
            c = 0.0
        else:
            c = notional * f
        direction += d
        carry += c
        r = rp + d + c - maint
        if i == 0 and notional > 0:
            r -= entry_toll * notional
        out.append(r)
    return out, {"notional": notional, "direction_sum": direction, "carry_sum": carry,
                 "maint_year_pct": maint * 365.0 * 100.0,
                 "funding_unmeasured_days": float(unmeasured)}


def basis_breakeven(panel: Sequence[float], hedged: Sequence[float], *,
                    notional: float, sigmas: Sequence[float] = BASIS_SIGMAS,
                    draws: int = BASIS_DRAWS, seed: int = SEED) -> List[dict]:
    """При какой σ остаточного базиса преимущество хеджа по просадке обнуляется.

    Базис ИЗ ФАЙЛА НЕ ИЗМЕРИМ (ADR-139: частное двух дневных цен без отметок времени —
    рассинхрон принтов, а не отвязка), поэтому прибор не выдумывает его величину, а меряет,
    какая величина убила бы вывод.  Шум iid — ОГОВОРКА, а не претензия: настоящий базис
    кластеризован, и кластеризованный хуже iid той же σ.
    """
    base = rpe.perf(panel)["maxdd"]
    rows = []
    for s in sigmas:
        worse = 0
        dds: List[float] = []
        for k in range(draws if s > 0 else 1):
            rnd = random.Random(seed + k)
            noisy = [r + notional * rnd.gauss(0.0, s) for r in hedged]
            dd = rpe.perf(noisy)["maxdd"]
            dds.append(dd)
            if dd <= base:
                worse += 1
        rows.append({"sigma": s, "median_maxdd": statistics.median(dds),
                     "share_worse_than_base": worse / len(dds), "base_maxdd": base})
    return rows


# ── секции ──────────────────────────────────────────────────────────────────────────────────

def section_lead(axis: Sequence[str], rets: Dict[str, List[float]], books: Sequence[str],
                 series: Dict[str, Dict[str, float]]) -> dict:
    ew = ew_returns(rets, books)
    eps = slow_episodes(ew, axis)
    if len(eps) < MIN_EPISODES:
        raise Unmeasured(f"медленных эпизодов на оси {len(eps)} < {MIN_EPISODES} — "
                         f"мощности на вопрос заказа #168 нет вовсе")
    feats = build_features(series, axis)
    tr = [i for i, d in enumerate(axis) if d <= SPLIT]
    te = [i for i, d in enumerate(axis) if d > SPLIT]
    require_straddle("#169 XLT", tr, te)

    per_h: Dict[int, dict] = {}
    for h in HORIZONS:
        labels = forward_loss_labels(ew, h)
        rows = []
        for name in sorted(feats):
            v = feats[name]
            rows.append({
                "feature": name,
                "auc_train": auc([v[i] for i in tr], [labels[i] for i in tr]),
                "auc_test": auc([v[i] for i in te], [labels[i] for i in te]),
                "auc_full": auc(v, labels),
            })
        pl, devs = family_placebo(feats, labels)
        real_max = max((abs(r["auc_full"] - 0.5) for r in rows if r["auc_full"] is not None),
                       default=0.0)
        best = max((r for r in rows if r["auc_full"] is not None),
                   key=lambda r: abs(r["auc_full"] - 0.5))
        per_h[h] = {"rows": rows, "placebo": pl,
                    "real_max_dev": real_max,
                    "real_percentile": placebo_percentile(devs, real_max),
                    "best_feature": best["feature"],
                    "best_auc_full": best["auc_full"],
                    "label_pos": sum(1 for x in labels if x),
                    "label_n": sum(1 for x in labels if x is not None)}

    # Действующее плечо: гейт по лучшему на TRAIN признаку (направление — тоже с TRAIN).
    h_gate = 60
    labels = forward_loss_labels(ew, h_gate)
    train_rows = [(name, auc([feats[name][i] for i in tr], [labels[i] for i in tr]))
                  for name in sorted(feats)]
    train_rows = [(n_, a) for n_, a in train_rows if a is not None]
    pick, pick_auc = max(train_rows, key=lambda p: abs(p[1] - 0.5))
    above = pick_auc > 0.5          # AUC>0.5 ⇒ высокие значения предвещают убыток
    chosen = choose_threshold(feats[pick], ew, tr, above=above)
    gate = None
    if chosen is not None:
        flag = causal_flag(feats[pick], chosen["threshold"], above=above)
        arms = {}
        for label, idx in (("TRAIN", tr), ("TEST", te), ("FULL", list(range(len(axis))))):
            sub = [ew[i] for i in idx]
            ov, changes, share = gate_overlay(sub, [flag[i] for i in idx])
            arms[label] = {"base": rpe.perf(sub), "gate": rpe.perf(ov),
                           "twin": rpe.perf(static_twin(sub, share)),
                           "changes": changes, "risk_share": share}
        gate = {"feature": pick, "train_auc": pick_auc, "above": above,
                "threshold": chosen["threshold"], "quantile": chosen["q"], "arms": arms}

    # Опережение: за сколько дней ДО начала каждого медленного эпизода флаг взведён.
    leads = []
    if chosen is not None:
        flag = causal_flag(feats[pick], chosen["threshold"], above=above)
        for ep in eps:
            a = ep["start_idx"]
            lead: Optional[int] = None
            for back in range(0, a + 1):
                if flag[a - back] is True:
                    lead = back
                    break
                if flag[a - back] is False:
                    continue
            leads.append({"episode": ep["start"], "lead_days": lead,
                          "flag_at_start": flag[a]})
    return {"episodes": eps, "per_h": per_h, "gate": gate, "leads": leads,
            "train_days": len(tr), "test_days": len(te),
            "feature_count": len(feats)}


def section_hedge(axis: Sequence[str], rets: Dict[str, List[float]], books: Sequence[str],
                  series: Dict[str, Dict[str, float]]) -> dict:
    eth = series["eth"]
    have = paired_axis(axis, eth)
    if len(have) < MIN_PAIRED_DAYS:
        raise Unmeasured(f"пересечение оси панели с рядом цен {len(have)} < {MIN_PAIRED_DAYS}")
    # Сравниваемые ряды живут на ОДНОЙ оси пар: база пересчитывается на ней же.
    dates = [axis[i] for i in have]
    eth_r = [eth[dates[k]] / eth[dates[k - 1]] - 1.0 for k in range(1, len(dates))]
    idxs = [have[k] for k in range(1, len(dates))]
    ds = dates[1:]
    ew_all = ew_returns(rets, books)
    panel_r = [ew_all[i] for i in idxs]
    fund_all = align(series.get("funding", {}), axis)
    fund = [fund_all[i] for i in idxs]

    tr = [k for k, d in enumerate(ds) if d <= SPLIT]
    te = [k for k, d in enumerate(ds) if d > SPLIT]
    require_straddle("#170 CACH-REAL", tr, te)
    beta = ols_beta([eth_r[k] for k in tr], [panel_r[k] for k in tr])
    beta_full = ols_beta(eth_r, panel_r)

    per_book = {}
    for b in books:
        br = [rets[b][i] for i in idxs]
        try:
            per_book[b] = ols_beta([eth_r[k] for k in tr], [br[k] for k in tr])
        except Unmeasured:
            per_book[b] = float("nan")

    arms = []
    for h in HEDGE_RATIOS:
        for maint in HEDGE_MAINT_BPS_PER_YEAR:
            hr, parts = hedged_returns(panel_r, eth_r, fund, h=h, beta=beta,
                                       maint_bps_year=maint)
            row = {"h": h, "maint_bps": maint, "parts": parts,
                   "FULL": rpe.perf(hr),
                   "TRAIN": rpe.perf([hr[k] for k in tr]),
                   "TEST": rpe.perf([hr[k] for k in te])}
            # просадка внутри кризисных окон
            row["windows"] = {}
            for name, a, b in WINDOWS:
                sel = [hr[k] for k, d in enumerate(ds) if a <= d <= b]
                row["windows"][name] = rpe.perf(sel)["maxdd"] if len(sel) > 2 else None
            arms.append(row)

    # Сравнение с ИЗЪЯТИЕМ (#145 EDX): хедж ≈ изъятие + сохранённый carry + полученный funding
    beta_book = max(per_book, key=lambda b: per_book[b] if per_book[b] == per_book[b] else -9)
    rest = [b for b in books if b != beta_book]
    exc = [statistics.mean(rets[b][i] for b in rest) for i in idxs]
    excision = {"book": beta_book, "FULL": rpe.perf(exc),
                "TRAIN": rpe.perf([exc[k] for k in tr]), "TEST": rpe.perf([exc[k] for k in te])}

    # Полный хедж считается ЗДЕСЬ, до §6: его разложение читает §6, и брать `parts` из
    # последней итерации сетки армов значило бы ссылаться на ячейку, которую выбрал цикл,
    # а не ту, о которой говорит §6.
    full_hedge, parts = hedged_returns(panel_r, eth_r, fund, h=1.0, beta=beta)
    breakeven = basis_breakeven(panel_r, full_hedge, notional=parts["notional"])

    # §6 ПОЧЕМУ хедж может проиграть ИЗЪЯТИЮ даже когда он работает: остаточный carry
    # хеджируемой книги против АЛЬТЕРНАТИВНОГО применения той же доли капитала.
    beta_book_own = per_book.get(beta_book, float("nan"))
    residual: Dict[str, dict] = {}
    if beta_book_own == beta_book_own:
        br = [rets[beta_book][i] for i in idxs]
        res = [br[k] - beta_book_own * eth_r[k] for k in range(len(br))]
        for label, sel in (("TRAIN", tr), ("TEST", te), ("FULL", list(range(len(br))))):
            residual[label] = {"book": rpe.perf([br[k] for k in sel]),
                               "residual": rpe.perf([res[k] for k in sel])}
    weight = 1.0 / len(books)
    funding_year = (parts["carry_sum"] / len(eth_r)) * 365.0
    opportunity = {label: {
        "next_best_apy": excision[label]["apy"],
        "residual_apy": residual.get(label, {}).get("residual", {}).get("apy"),
        "funding_apy_on_slice": funding_year / weight,
        "weight": weight,
    } for label in ("TRAIN", "TEST", "FULL")}

    # базис из файла: НЕ ИЗМЕРИМ — величина артефакта печатается как улика (ADR-139)
    basis_artifact = None
    if "eeth" in series:
        common = sorted(set(series["eeth"]) & set(eth))
        if len(common) > 60:
            ratios = [series["eeth"][d] / eth[d] for d in common]
            chg = [ratios[i] / ratios[i - 1] - 1.0 for i in range(1, len(ratios))]
            basis_artifact = {"days": len(common), "sigma_daily": statistics.stdev(chg),
                              "min_ratio": min(ratios), "max_ratio": max(ratios)}

    return {"beta_train": beta, "beta_full": beta_full, "per_book": per_book,
            "paired_days": len(eth_r), "axis": (ds[0], ds[-1]),
            "train_days": len(tr), "test_days": len(te),
            "arms": arms, "excision": excision, "breakeven": breakeven,
            "residual": residual, "opportunity": opportunity, "beta_book": beta_book,
            "basis_artifact": basis_artifact,
            "funding_mean_daily": statistics.mean([f for f in fund if f is not None])
            if any(f is not None for f in fund) else None}


# ── печать ──────────────────────────────────────────────────────────────────────────────────

def _p(x: Optional[float], digits: int = 2, pct: bool = True) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "НЕ ИЗМЕРЕНО"
    return f"{x * 100:.{digits}f} %" if pct else f"{x:.{digits}f}"


def print_lead(r: dict) -> None:
    print("=" * 96)
    print("#169 XLT — eXogenous Lead-Time census (ИСПОЛНЕНИЕ ЗАКАЗА #168)")
    print("=" * 96)
    print(f"\n§1 НЕЗАВИСИМЫЕ НАБЛЮДЕНИЯ: медленных эпизодов (≥{SLOW_DAYS} д, глубже "
          f"{SLOW_DEPTH * 100:.0f} %) — {len(r['episodes'])}")
    for e in r["episodes"]:
        print(f"    {e['start']} … {e['end']}  {e['days']:>3} д  дно {_p(e['trough'])}"
              f"  ({e['trough_date']})")
    print(f"    TRAIN дней {r['train_days']} · TEST дней {r['test_days']} · признаков "
          f"{r['feature_count']}")
    for h, blk in r["per_h"].items():
        print(f"\n§2 H={h} д · метка «доход вперёд < 0»: {blk['label_pos']} из {blk['label_n']} дней")
        print(f"    {'признак':<14} {'AUC TRAIN':>10} {'AUC TEST':>10} {'AUC FULL':>10}")
        for row in blk["rows"]:
            print(f"    {row['feature']:<14} {_p(row['auc_train'], 3, False):>10} "
                  f"{_p(row['auc_test'], 3, False):>10} {_p(row['auc_full'], 3, False):>10}")
        pl = blk["placebo"]
        print(f"    СЕМЕЙНОЕ ПЛАЦЕБО (циклический сдвиг, {int(pl['draws'])} розыгрышей, "
              f"максимум |AUC−0.5| по всем признакам):")
        print(f"      медиана {pl['median']:.3f} · p95 {pl['p95']:.3f} · максимум {pl['max']:.3f}")
        print(f"      настоящий максимум {blk['real_max_dev']:.3f} ({blk['best_feature']}, "
              f"AUC {blk['best_auc_full']:.3f}) ⇒ перцентиль {blk['real_percentile']:.1%}")
    g = r["gate"]
    print("\n§3 ДЕЙСТВУЮЩЕЕ ПЛЕЧО (гейт «в кэш», порог и направление выбраны ТОЛЬКО на TRAIN)")
    if g is None:
        print("    НЕ ИЗМЕРЕНО: на TRAIN не набралось наблюдений для выбора порога")
    else:
        print(f"    признак {g['feature']} · TRAIN AUC {g['train_auc']:.3f} · "
              f"срабатывает при значении {'ВЫШЕ' if g['above'] else 'НИЖЕ'} "
              f"{g['threshold']:.6g} (квантиль {g['quantile']})")
        print(f"    {'окно':<6} {'APY база':>10} {'APY гейт':>10} {'APY двойник':>12} "
              f"{'maxDD база':>11} {'maxDD гейт':>11} {'Calmar база':>12} {'Calmar гейт':>12} "
              f"{'Calmar двойник':>15} {'смен':>5}")
        for label, a in g["arms"].items():
            print(f"    {label:<6} {_p(a['base']['apy']):>10} {_p(a['gate']['apy']):>10} "
                  f"{_p(a['twin']['apy']):>12} {_p(a['base']['maxdd']):>11} "
                  f"{_p(a['gate']['maxdd']):>11} {a['base']['calmar']:>12.2f} "
                  f"{a['gate']['calmar']:>12.2f} {a['twin']['calmar']:>15.2f} "
                  f"{a['changes']:>5}")
    print("\n§4 ОПЕРЕЖЕНИЕ: за сколько дней ДО начала эпизода флаг был взведён")
    for l in r["leads"]:
        lead = "НЕ ВЗВОДИЛСЯ ни разу до начала" if l["lead_days"] is None else f"{l['lead_days']} д"
        print(f"    эпизод {l['episode']}: {lead} · флаг в день начала = {l['flag_at_start']}")


def print_hedge(r: dict) -> None:
    print("\n" + "=" * 96)
    print("#170 CACH-REAL — пассивный бета-хедж на РЕАЛЬНОЙ панели с НАБЛЮДЁННЫМ funding")
    print("=" * 96)
    print(f"\n§1 ОСЬ ПАР: {r['paired_days']} дней {r['axis'][0]} … {r['axis'][1]} "
          f"(TRAIN {r['train_days']} / TEST {r['test_days']})")
    print(f"    β портфеля к ETH: TRAIN {r['beta_train']:.4f} · FULL {r['beta_full']:.4f}")
    fm = r["funding_mean_daily"]
    print(f"    средний наблюдённый funding: "
          f"{'НЕ ИЗМЕРЕНО' if fm is None else f'{fm * 10000:.3f} bp/д = {fm * 365 * 100:.2f} %/год'}")
    print("    β по книгам (TRAIN):")
    for b, v in sorted(r["per_book"].items(), key=lambda p: -(p[1] if p[1] == p[1] else -9)):
        print(f"      {b:<20} {'НЕ ИЗМЕРЕНО' if v != v else f'{v:+.4f}'}")
    print("\n§2 АРМЫ ХЕДЖА (maint = стоимость поддержания, bp/год на номинал хеджа)")
    print(f"    {'h':>5} {'maint':>6} {'APY TRAIN':>10} {'DD TRAIN':>9} {'APY TEST':>10} "
          f"{'DD TEST':>9} {'Calmar TEST':>12} {'Σнаправл.':>10} {'Σfunding':>9}")
    for a in r["arms"]:
        print(f"    {a['h']:>5.2f} {a['maint_bps']:>6.0f} {_p(a['TRAIN']['apy']):>10} "
              f"{_p(a['TRAIN']['maxdd']):>9} {_p(a['TEST']['apy']):>10} "
              f"{_p(a['TEST']['maxdd']):>9} {a['TEST']['calmar']:>12.2f} "
              f"{_p(a['parts']['direction_sum']):>10} {_p(a['parts']['carry_sum'], 3):>9}")
    print("\n§3 КРИЗИСНЫЕ ОКНА (просадка внутри окна; h=1.0, maint=0)")
    full = [a for a in r["arms"] if a["h"] == 1.0 and a["maint_bps"] == 0][0]
    base = [a for a in r["arms"] if a["h"] == 0.0 and a["maint_bps"] == 0][0]
    for name in full["windows"]:
        print(f"    {name:<24} база {_p(base['windows'][name])} → хедж {_p(full['windows'][name])}")
    print("\n§4 СРАВНЕНИЕ С ИЗЪЯТИЕМ (#145 EDX): изъята книга "
          f"{r['excision']['book']}")
    for label in ("TRAIN", "TEST", "FULL"):
        e = r["excision"][label]
        print(f"    {label:<6} APY {_p(e['apy'])} · maxDD {_p(e['maxdd'])} · "
              f"Calmar {e['calmar']:.2f}")
    print("\n§5 BREAK-EVEN ОСТАТОЧНОГО БАЗИСА (базис из файла НЕ ИЗМЕРИМ — ADR-139)")
    if r["basis_artifact"]:
        b = r["basis_artifact"]
        print(f"    улика артефакта: частное дневных цен eETH/ETH на {b['days']} днях даёт "
              f"σ {b['sigma_daily'] * 100:.2f} %/д, разброс {b['min_ratio']:.3f}…{b['max_ratio']:.3f}"
              f" — у настоящего eETH такого хода нет ⇒ это рассинхрон принтов, а не отвязка")
    print(f"    {'σ базиса/д':>12} {'медиана maxDD хеджа':>22} {'доля розыгрышей хуже базы':>27}")
    for row in r["breakeven"]:
        print(f"    {row['sigma'] * 100:>11.2f}% {_p(row['median_maxdd']):>22} "
              f"{row['share_worse_than_base'] * 100:>26.1f}%")
    print(f"    база (без хеджа) maxDD {_p(r['breakeven'][0]['base_maxdd'])}")
    print("\n§6 ПОЧЕМУ ХЕДЖ МОЖЕТ ПРОИГРАТЬ ИЗЪЯТИЮ: остаточный carry против альтернативы")
    print(f"    хеджируется книга {r['beta_book']} (её β к ETH {r['per_book'][r['beta_book']]:+.4f}), "
          f"доля {r['opportunity']['FULL']['weight'] * 100:.0f} % капитала")
    print(f"    {'окно':<6} {'книга APY':>11} {'книга maxDD':>12} {'ОСТАТОК APY':>12} "
          f"{'ОСТАТОК maxDD':>14} {'альтернатива APY':>17} {'порог окупаемости':>18}")
    for label in ("TRAIN", "TEST", "FULL"):
        o = r["opportunity"][label]
        res = r["residual"].get(label)
        if res is None:
            print(f"    {label:<6} НЕ ИЗМЕРЕНО: β хеджируемой книги не определена")
            continue
        need = o["next_best_apy"] - o["funding_apy_on_slice"]
        print(f"    {label:<6} {_p(res['book']['apy']):>11} {_p(res['book']['maxdd']):>12} "
              f"{_p(res['residual']['apy']):>12} {_p(res['residual']['maxdd']):>14} "
              f"{_p(o['next_best_apy']):>17} {_p(need):>18}")
    print("    порог окупаемости = доходность альтернативного применения доли минус полученный")
    print("    funding на номинал хеджа: остаток НИЖЕ порога ⇒ изъятие строго лучше хеджа.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("--section", choices=("lead", "hedge", "all"), default="all")
    ap.add_argument("--panel-dir", default=None,
                    help="каталог панели (по умолчанию data/aggressive_lab прод-дерева)")
    ap.add_argument("--rates-dir", default=None,
                    help="каталог экзогенных рядов (по умолчанию data/rates_desk)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    panel_dir = Path(args.panel_dir) if args.panel_dir else rpe.PANEL_DIR
    rates_dir = Path(args.rates_dir) if args.rates_dir else RATES_DIR
    print(f"[прибор] панель: {panel_dir}", file=sys.stderr)
    print(f"[прибор] экзогенные ряды: {rates_dir}", file=sys.stderr)

    try:
        axis, rets, books = rpe.plb_load(panel_dir)
        series = load_series(rates_dir)
        out: Dict[str, dict] = {}
        if args.section in ("lead", "all"):
            out["lead"] = section_lead(axis, rets, books, series)
        if args.section in ("hedge", "all"):
            out["hedge"] = section_hedge(axis, rets, books, series)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0
    print(f"\nПанель: {len(books)} книг, ось {axis[0]} … {axis[-1]} ({len(axis)} дней); "
          f"шов TRAIN/TEST {SPLIT}; пошлина {TOLL * 10000:.0f} bp")
    if "lead" in out:
        print_lead(out["lead"])
    if "hedge" in out:
        print_hedge(out["hedge"])
    print("\nIS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · на диск не записано ничего · "
          "RiskPolicy v1.0 и живой трек не тронуты")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
