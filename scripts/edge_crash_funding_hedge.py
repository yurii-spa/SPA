"""
scripts/edge_crash_funding_hedge.py — #158 CFH: Crash-Funding Hedge.

ГИПОТЕЗА. ETH-крах сжимает funding бессрочных контрактов ⇒ доходность sUSDe (она и есть funding-
carry) падает ⇒ подразумеваемая ставка Pendle PT-sUSDE падает ⇒ ФИКСИРОВАННАЯ нога (PT) дорожает
ровно в тот день, когда направленные книги теряют. Если канал реален и достаточно велик, длинный
PT-sUSDE — ВЫПУКЛЫЙ ХЕДЖ ETH-краха, который сам платит carry («доход выше, риск ниже» без шорта
и без сигнала). Это НЕ #20 CACH (пассивный шорт коррелированной книги) и НЕ #118 PTFF
(фиксированная против плавающей ставки без привязки к крахам): предмет здесь — УСЛОВНОЕ поведение
марки PT в дни краха, и мерится оно на РЕАЛЬНЫХ рядах, а не на фикстуре.

ТРИ ВОПРОСА, и они РАЗНЫЕ:

  (1) КАНАЛ. В дни краха ETH funding ниже обычного? Подразумеваемая ставка PT-sUSDE падает
      сильнее обычного? Марка PT (часть дневного дохода, которая идёт от ΔY, а не от carry)
      положительна и выше обычной? Печатается по дням И по ЭПИЗОДАМ (кластерам дней краха) —
      число независимых эпизодов стоит рядом с каждым средним.

  (2) ВЕЛИЧИНА. На каждый процент падения ETH сколько даёт марка PT при 1× номинала? Это и есть
      коэффициент хеджа; обратная величина — сколько номиналов PT нужно, чтобы закрыть ПОЛОВИНУ
      краха. Хедж, которому нужно 20 номиналов, хеджем не является, каким бы верным ни был знак.

  (3) ПОРТФЕЛЬ. 50 % ETH + 50 % PT-sUSDE против ДВУХ контролей: 50 % ETH + 50 % кэш (0 %) и
      50 % ETH + 50 % плавающий sUSDe (начисление `underlying_yield`). Разность maxDD между PT и
      плавающим и есть цена выпуклости — carry у них общий. Шов TRAIN/TEST 2025-06-30 (конвенция
      #153), пошлина 96 bp на входе и на каждом перекате PT (конвенция #149).

ЧЕСТНАЯ РАМКА. [L1] Реальные ряды `data/rates_desk/` (funding_deep · prices_deep · pendle_pt_history),
но это сравнение СТАВОК и выведенной марки (P = (1+y)^(−τ)), а не реализованный P&L книги: нет
проскальзывания, газа, ёмкости и — главное — нет ХВОСТА самого sUSDe (депег USDe, срыв погашения,
риск контракта Pendle): в октябре 2025 ряд видит ПАДЕНИЕ implied yield, а не стресс принципала.
Хедж, чей собственный хвост не измерен, продавать как «тот же риск» нельзя. Pendle-ряд стоит
с 2026-07-05 (#154 п. 3), цены и funding — с 2026-06-25: окно замера конечно и названо.

Третий исход (инв. #17): файла нет · рынков sUSDE нет · эпизодов краха меньше двух · ETH-ряд
пуст — ОТКАЗ кодом 2 с названной причиной, никогда не ноль и не «хеджа нет».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_MODULE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATES_DIR = _MODULE_ROOT / "data" / "rates_desk"

CRASH_7D_PCT = -10.0        # день краха: 7-дневная доходность ETH ≤ −10 %
EPISODE_GAP_DAYS = 5        # дни краха ближе 5 дней — один эпизод
MIN_TAU_DAYS = 14           # рынок считается живым, если до погашения ≥ 14 дней
ENTRY_TOLL_BPS = 96.0       # конвенция #149 — на входе и на каждом перекате PT
TRAIN_END = datetime.date(2025, 6, 30)   # шов конвенции #153
PT_UNDERLYING = "sUSDe"
HALF_HEDGE_TARGET = 0.5     # «закрыть половину краха»
MIN_EPISODES = 2


class Unmeasured(Exception):
    """Прибор не смог ответить. Не подменяется нулём и не выдаётся за «хеджа нет»."""


Date = datetime.date


# ── чтение рядов (только чтение, прод-data/ не пишется) ───────────────────────────────────

def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Unmeasured(f"файла нет: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"{path} не разобран — {type(exc).__name__}: {exc}") from exc


def load_eth_prices(rates_dir: Path) -> Dict[Date, float]:
    doc = _read_json(rates_dir / "prices_deep.json")
    ser = (doc.get("series") or {}).get("eth") or {}
    out = {Date.fromisoformat(k): float(v) for k, v in ser.items() if v is not None}
    if len(out) < 30:
        raise Unmeasured(f"ETH-ряд слишком короток: {len(out)} точек")
    return out


def load_funding(rates_dir: Path) -> Dict[Date, float]:
    doc = _read_json(rates_dir / "funding_deep.json")
    ser = doc.get("series") or {}
    return {Date.fromisoformat(k): float(v) for k, v in ser.items() if v is not None}


def load_pt_markets(rates_dir: Path, underlying: str = PT_UNDERLYING) -> Dict[str, dict]:
    doc = _read_json(rates_dir / "pendle_pt_history.json")
    markets = doc.get("markets") or {}
    out = {k: v for k, v in markets.items()
           if str(v.get("underlying", "")).lower() == underlying.lower()}
    if not out:
        raise Unmeasured(f"рынков PT с базой {underlying} в ряде нет")
    return out


# ── марка PT: carry и Δy раздельно ────────────────────────────────────────────────────────

def pt_price(y: float, tau_years: float) -> float:
    """Цена PT к номиналу 1 при годовой ставке y и сроке τ лет: (1+y)^(−τ)."""
    return (1.0 + y) ** (-tau_years)


def decompose_day(y0: float, y1: float, tau0_days: int, tau1_days: int) -> Tuple[float, float, float]:
    """Дневной лог-доход PT = carry (ставка стоит, срок уходит) + mark (ставка двинулась)."""
    p0 = pt_price(y0, tau0_days / 365.0)
    p_carry = pt_price(y0, tau1_days / 365.0)
    p1 = pt_price(y1, tau1_days / 365.0)
    total = math.log(p1) - math.log(p0)
    carry = math.log(p_carry) - math.log(p0)
    mark = total - carry
    return total, carry, mark


def build_pt_series(markets: Dict[str, dict], *, min_tau_days: int = MIN_TAU_DAYS) -> List[dict]:
    """Вход — в САМЫЙ ДЛИННЫЙ живой рынок; держим его, пока он жив (≥ min_tau_days до погашения
    и есть наблюдение); перекат — только когда он перестаёт быть живым, без P&L в день переката.

    Строка: date · market · y · dy · total · carry · mark · rolled · float_daily (медиана
    underlying_yield по рынкам дня / 365). Дни без двух наблюдений подряд в одном рынке
    дохода не несут (None), а не ноль."""
    obs: Dict[Date, Dict[str, Tuple[float, Date, Optional[float]]]] = {}
    for name, m in markets.items():
        try:
            mat = Date.fromisoformat(m["maturity"])
        except (KeyError, ValueError) as exc:
            raise Unmeasured(f"рынок {name} без погашения — {exc}") from exc
        for row in m.get("series") or []:
            y = row.get("implied_yield")
            if y is None:
                continue
            d = Date.fromisoformat(row["date"])
            obs.setdefault(d, {})[name] = (float(y), mat, row.get("underlying_yield"))
    out: List[dict] = []
    cur: Optional[str] = None
    prev: Optional[Date] = None
    for d in sorted(obs):
        live = {k: v for k, v in obs[d].items() if (v[1] - d).days >= min_tau_days}
        floats = [v[2] for v in obs[d].values() if v[2] is not None]
        float_daily = (statistics.median(floats) / 365.0) if floats else None
        if not live:
            cur, prev = None, d
            continue
        rolled = False
        row = {"date": d, "market": None, "y": None, "dy": None, "total": None,
               "carry": None, "mark": None, "rolled": False, "float_daily": float_daily}
        if cur in live and prev is not None and cur in obs.get(prev, {}) \
                and (prev - d).days >= -3:
            y0, mat, _ = obs[prev][cur]
            y1 = live[cur][0]
            total, carry, mark = decompose_day(y0, y1, (mat - prev).days, (mat - d).days)
            row.update({"market": cur, "y": y1, "dy": y1 - y0, "total": total,
                        "carry": carry, "mark": mark})
        else:
            cur = max(live, key=lambda k: (live[k][1], k))
            rolled = prev is not None
            row.update({"market": cur, "y": live[cur][0], "rolled": rolled})
        out.append(row)
        prev = d
    if not out:
        raise Unmeasured("ни одного дня с живым рынком PT")
    return out


# ── крах ETH: дни и эпизоды ───────────────────────────────────────────────────────────────

def eth_return_7d(prices: Dict[Date, float], d: Date) -> Optional[float]:
    if d not in prices:
        return None
    for back in range(7, 11):      # пропуски в ряде: берём ближайший день 7..10 назад
        d0 = d - datetime.timedelta(days=back)
        if d0 in prices and prices[d0] > 0:
            return prices[d] / prices[d0] - 1.0
    return None


def crash_days(prices: Dict[Date, float], threshold_pct: float = CRASH_7D_PCT) -> List[Date]:
    out = []
    for d in sorted(prices):
        r = eth_return_7d(prices, d)
        if r is not None and r * 100.0 <= threshold_pct:
            out.append(d)
    return out


def cluster_episodes(days: Sequence[Date], gap_days: int = EPISODE_GAP_DAYS) -> List[List[Date]]:
    eps: List[List[Date]] = []
    for d in sorted(days):
        if eps and (d - eps[-1][-1]).days <= gap_days:
            eps[-1].append(d)
        else:
            eps.append([d])
    return eps


# ── (1) канал и (2) величина ──────────────────────────────────────────────────────────────

def _mean(xs: Sequence[Optional[float]]) -> Optional[float]:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def channel_section(pt: List[dict], funding: Dict[Date, float], prices: Dict[Date, float],
                    crash: Sequence[Date], episodes: Sequence[Sequence[Date]]) -> dict:
    crash_set = set(crash)
    by_date = {r["date"]: r for r in pt}
    all_days = sorted(set(prices) | set(by_date))
    normal = [d for d in all_days if d not in crash_set]

    def stats(days: Sequence[Date]) -> dict:
        rows = [by_date[d] for d in days if d in by_date]
        return {
            "n_days": len(days),
            "funding_mean": _mean([funding.get(d) for d in days]),
            "dy_mean": _mean([r["dy"] for r in rows]),
            "mark_mean": _mean([r["mark"] for r in rows]),
            "carry_mean": _mean([r["carry"] for r in rows]),
            "total_mean": _mean([r["total"] for r in rows]),
            "n_pt_days": sum(1 for r in rows if r["mark"] is not None),
        }

    ep_rows = []
    for ep in episodes:
        s, t = ep[0], ep[-1]
        rows = [r for r in pt if s <= r["date"] <= t]
        mark_cum = sum(r["mark"] for r in rows if r["mark"] is not None)
        dy_cum = sum(r["dy"] for r in rows if r["dy"] is not None)
        eth_ret = (prices[t] / prices[s] - 1.0) if (s in prices and t in prices and prices[s] > 0) else None
        # падение ETH за эпизод — от ПИКА семи дней перед первым днём краха до минимума внутри
        # (та же мера, что у правила «7d ETH ≤ порог»; цена накануне уже внутри падения)
        pre = [prices[d] for d in prices if s - datetime.timedelta(days=7) <= d < s]
        inside = [prices[d] for d in prices if s <= d <= t]
        eth_drop = (min(inside) / max(pre) - 1.0) if pre and inside and max(pre) > 0 else None
        y0 = next((r["y"] for r in rows if r["y"] is not None), None)
        ep_rows.append({
            "start": s.isoformat(), "end": t.isoformat(), "days": len(ep),
            "eth_ret_inside": eth_ret, "eth_drop_from_pre": eth_drop,
            "pt_mark_cum": mark_cum, "dy_cum": dy_cum, "y_at_start": y0,
            "funding_mean": _mean([funding.get(d) for d in ep]),
            "hedge_ratio": (mark_cum / abs(eth_drop)) if (eth_drop is not None and eth_drop < -0.0001) else None,
        })
    ratios = [e["hedge_ratio"] for e in ep_rows if e["hedge_ratio"] is not None and e["hedge_ratio"] > 0]
    ratios_all = [e["hedge_ratio"] for e in ep_rows if e["hedge_ratio"] is not None]
    med_ratio = statistics.median(ratios_all) if ratios_all else None
    by_year: Dict[int, dict] = {}
    for e in ep_rows:
        yr = int(e["start"][:4])
        b = by_year.setdefault(yr, {"episodes": 0, "mark_cum_sum": 0.0, "dy_cum_sum": 0.0, "y_at_start": []})
        b["episodes"] += 1
        b["mark_cum_sum"] += e["pt_mark_cum"]
        b["dy_cum_sum"] += e["dy_cum"]
        if e["y_at_start"] is not None:
            b["y_at_start"].append(e["y_at_start"])
    for b in by_year.values():
        b["y_at_start_mean"] = _mean(b.pop("y_at_start"))
    return {
        "crash_rule": f"7d ETH ≤ {CRASH_7D_PCT:.0f} %",
        "crash": stats(list(crash)),
        "normal": stats(normal),
        "n_episodes": len(episodes),
        "episodes": ep_rows,
        "n_episodes_with_positive_hedge": len(ratios),
        "n_episodes_with_ratio": len(ratios_all),
        "median_hedge_ratio": med_ratio,
        "notionals_for_half_hedge": (HALF_HEDGE_TARGET / med_ratio) if (med_ratio and med_ratio > 0) else None,
        "by_year": by_year,
    }


# ── (3) портфели ──────────────────────────────────────────────────────────────────────────

def simulate(prices: Dict[Date, float], pt: List[dict], start: Date, end: Date, *,
             leg: str, w_eth: float = 0.5, toll_bps: float = ENTRY_TOLL_BPS) -> Tuple[float, float, float]:
    """50/50 с ежедневным возвратом к весам. leg ∈ {cash, pt, float}. Возвращает (APY %, maxDD %, Calmar)."""
    by_date = {r["date"]: r for r in pt}
    dates = [d for d in sorted(prices) if start <= d <= end]
    if len(dates) < 2:
        return 0.0, 0.0, float("nan")
    eq = 100_000.0 * (1.0 - toll_bps / 10_000.0)
    peak, max_dd = eq, 0.0
    for i in range(1, len(dates)):
        d, d0 = dates[i], dates[i - 1]
        r_eth = prices[d] / prices[d0] - 1.0
        row = by_date.get(d)
        if leg == "cash" or row is None:
            r_leg = 0.0
        elif leg == "pt":
            r_leg = math.expm1(row["total"]) if row["total"] is not None else 0.0
            if row["rolled"]:
                r_leg -= toll_bps / 10_000.0
        elif leg == "float":
            r_leg = row["float_daily"] if row["float_daily"] is not None else 0.0
        else:
            raise ValueError(f"нога {leg} не объявлена")
        eq *= 1.0 + w_eth * r_eth + (1.0 - w_eth) * r_leg
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak)
    years = (dates[-1] - dates[0]).days / 365.25
    if years <= 0 or eq <= 0:
        return 0.0, max_dd * 100.0, float("nan")
    apy = ((eq / 100_000.0) ** (1.0 / years) - 1.0) * 100.0
    dd = max_dd * 100.0
    return apy, dd, (apy / dd if dd > 1e-4 else float("nan"))


def portfolio_section(prices: Dict[Date, float], pt: List[dict], *, toll_bps: float = ENTRY_TOLL_BPS) -> dict:
    first = max(min(prices), min(r["date"] for r in pt))
    last = min(max(prices), max(r["date"] for r in pt))
    periods = {
        f"TRAIN {first}..{TRAIN_END}": (first, TRAIN_END),
        f"TEST {TRAIN_END + datetime.timedelta(days=1)}..{last}": (TRAIN_END + datetime.timedelta(days=1), last),
        f"FULL {first}..{last}": (first, last),
    }
    legs = {"50% ETH + 50% кэш": "cash", "50% ETH + 50% PT-sUSDE": "pt", "50% ETH + 50% sUSDe плав.": "float"}
    out: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for pname, (a, b) in periods.items():
        out[pname] = {lname: simulate(prices, pt, a, b, leg=leg, toll_bps=toll_bps)
                      for lname, leg in legs.items()}
    return {"toll_bps": toll_bps, "window": (first.isoformat(), last.isoformat()), "results": out}


# ── отчёт ─────────────────────────────────────────────────────────────────────────────────

def build_report(rates_dir: Path) -> dict:
    prices = load_eth_prices(rates_dir)
    funding = load_funding(rates_dir)
    pt = build_pt_series(load_pt_markets(rates_dir))
    crash = crash_days(prices)
    episodes = cluster_episodes(crash)
    if len(episodes) < MIN_EPISODES:
        raise Unmeasured(f"эпизодов краха {len(episodes)} < {MIN_EPISODES} — о хедже сказать нечего")
    channel = channel_section(pt, funding, prices, crash, episodes)
    portfolio = portfolio_section(prices, pt)
    c, n = channel["crash"], channel["normal"]
    # Направление канала судят ДВА звена: funding ниже и марка выше в дни краха. Δy печатается
    # как третье звено, но в условие не входит: марка и есть −τ·Δy, и отдельное условие по Δy
    # мерке ничего не добавляло (мутационная проба #158: его снятие не меняло ни одной сцены).
    direction_ok = (c["funding_mean"] is not None and n["funding_mean"] is not None
                    and c["funding_mean"] < n["funding_mean"]
                    and c["mark_mean"] is not None and n["mark_mean"] is not None and c["mark_mean"] > n["mark_mean"])
    notionals = channel["notionals_for_half_hedge"]
    magnitude_ok = notionals is not None and notionals <= 2.0
    verdict = {
        "channel_direction_confirmed": direction_ok,
        "n_episodes": channel["n_episodes"],
        "median_hedge_ratio": channel["median_hedge_ratio"],
        "notionals_for_half_hedge": notionals,
        "hedge_is_usable": bool(direction_ok and magnitude_ok),
        "answer": None,
    }
    if direction_ok and not magnitude_ok:
        verdict["answer"] = (f"канал ЕСТЬ (funding и Δy ниже, марка выше в дни краха), но величина НЕТ: "
                             f"медианный коэффициент {channel['median_hedge_ratio']:.4f} ⇒ закрыть половину "
                             f"краха стоит {notionals:.1f} номиналов PT — хеджем это не является")
    elif direction_ok and magnitude_ok:
        verdict["answer"] = (f"канал есть и величина достаточна: {notionals:.2f} номинала PT на половину краха "
                             f"по медиане {channel['n_episodes']} эпизодов — кандидат на paper-модуль")
    else:
        verdict["answer"] = "канал НЕ подтверждён направлением: хеджа нет"
    return {
        "idea": "#158 CFH — Crash-Funding Hedge",
        "rates_dir": str(rates_dir),
        "inputs": {"eth_days": len(prices), "funding_days": len(funding), "pt_days": len(pt),
                   "eth_span": (min(prices).isoformat(), max(prices).isoformat()),
                   "pt_span": (pt[0]["date"].isoformat(), pt[-1]["date"].isoformat())},
        "channel": channel,
        "portfolio": portfolio,
        "verdict": verdict,
        "is_advisory": True,
        "outside_riskpolicy": True,
    }


def _fmt_half_hedge(x: Optional[float]) -> str:
    """Число номиналов PT на половину краха; None — «—». Вынесено из f-string: вложенные
    одинаковые кавычки внутри поля f-string разбирает только Python ≥ 3.12 (PEP 701), а CI идёт на 3.11.
    """
    return "—" if x is None else f"{x:.1f}"


def _bp(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 1e4:+.2f} bp"


def print_report(r: dict) -> None:
    i = r["inputs"]
    print("=== #158 CFH — PT-sUSDE как выпуклый хедж ETH-краха (реальные ряды, [L1]) ===")
    print(f"входы: ETH {i['eth_days']} дн {i['eth_span']} · funding {i['funding_days']} дн · PT {i['pt_days']} дн {i['pt_span']}")
    ch = r["channel"]
    c, n = ch["crash"], ch["normal"]
    print(f"§1 канал ({ch['crash_rule']}): дней краха {c['n_days']} в {ch['n_episodes']} эпизодах · обычных {n['n_days']}")
    print(f"   funding/день: крах {_bp(c['funding_mean'])} · норма {_bp(n['funding_mean'])}")
    print(f"   Δy/день:      крах {_bp(c['dy_mean'])} · норма {_bp(n['dy_mean'])}")
    print(f"   марка/день:   крах {_bp(c['mark_mean'])} · норма {_bp(n['mark_mean'])}  (carry: {_bp(c['carry_mean'])} / {_bp(n['carry_mean'])})")
    print("   эпизоды: start..end дней | ETH от пред-уровня | марка PT куммул. | Δy куммул. | y в начале | коэфф. хеджа")
    for e in ch["episodes"]:
        hr = "—" if e["hedge_ratio"] is None else f"{e['hedge_ratio']:+.4f}"
        drop = "—" if e["eth_drop_from_pre"] is None else f"{e['eth_drop_from_pre'] * 100:+.1f} %"
        y0 = "—" if e["y_at_start"] is None else f"{e['y_at_start'] * 100:.2f} %"
        print(f"     {e['start']}..{e['end']} {e['days']:2d} | {drop:>8s} | {e['pt_mark_cum'] * 100:+.3f} % | "
              f"{e['dy_cum'] * 100:+.2f} pp | {y0:>7s} | {hr}")
    print(f"§2 величина: медианный коэффициент хеджа {ch['median_hedge_ratio']} по {ch['n_episodes_with_ratio']} эпизодам "
          f"(положительных {ch['n_episodes_with_positive_hedge']}); номиналов PT на половину краха: "
          f"{_fmt_half_hedge(ch['notionals_for_half_hedge'])}")
    for yr, b in sorted(ch["by_year"].items()):
        ym = "—" if b["y_at_start_mean"] is None else f"{b['y_at_start_mean'] * 100:.1f} %"
        print(f"   {yr}: эпизодов {b['episodes']} · Σ марка {b['mark_cum_sum'] * 100:+.3f} % · Σ Δy {b['dy_cum_sum'] * 100:+.2f} pp · y в начале ≈ {ym}")
    p = r["portfolio"]
    print(f"§3 портфели (пошлина {p['toll_bps']:.0f} bp на входе и на перекате PT), [bt] на реальных ставках:")
    for pname, res in p["results"].items():
        print(f"   {pname}")
        for lname, (apy, dd, cal) in res.items():
            print(f"     {lname:28s} APY {apy:+6.2f} %  maxDD {dd:5.2f} %  Calmar {cal:+.3f}")
    print("ВЕРДИКТ:", r["verdict"]["answer"])
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута · живой трек не открыт · data/ только читается")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#158 CFH — PT-sUSDE как выпуклый хедж ETH-краха")
    ap.add_argument("--rates-dir", type=Path, default=DEFAULT_RATES_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        r = build_report(args.rates_dir)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
