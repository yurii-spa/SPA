"""Качество вывода Trading Research: forward против HOLD за то же окно, свежесть рыночных данных, поправка на отбор.

Три вопроса, на которые статус до сих пор не отвечал (инвентаризация 01.11, автономный мандат §2.3):

1. **Лучше ли кандидат, чем просто держать BTC за ТО ЖЕ forward-окно?** ``forward_net`` печатался один; HOLD
   за то же окно не считался. Здесь HOLD — цена закрытия последнего бара к цене открытия первого бара окна
   кандидата, с ОДНОЙ стороной издержек spot (вход) из ``execution.EXEC_MODELS`` — без нулевых издержек.
   Окно с пропусками баров — ``INCOMPLETE``, а не число: сравнивать дыру с непрерывным HOLD нечестно.
2. **Свежи ли рыночные данные?** Возраст последней закрытой часовой свечи на момент ``now``. Нет свечей —
   ``UNKNOWN``, а не «свежо».
3. **Отличим ли отобранный результат от удачи?** Из 138 испытанных кандидатов в forward прошли 5; лучший из
   многих почти всегда выглядит хорошо. Deflated Sharpe Ratio (Bailey & López de Prado, 2014) — вероятность, что
   истинный Sharpe > 0 с поправкой на число испытаний, разброс их Sharpe, асимметрию и эксцесс доходностей.
   Считается по ДНЕВНЫМ OOS-доходностям из бэктеста; меньше 30 наблюдений или < 2 испытаний — ``UNKNOWN``.

Только чтение; ничего не пишет и ничего не решает. LLM запрещён.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Dict, Iterable, List, Optional

from spa_core.trading_research.execution import EXEC_MODELS

MEASURED, INCOMPLETE, UNKNOWN = "MEASURED", "INCOMPLETE", "UNKNOWN"
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1D": 86_400_000}
#: свеча старше двух часовых тактов (+ такт агента 15 мин) — данные не свежи
STALE_AFTER_MS = 2 * 3_600_000 + 900_000
_EULER = 0.5772156649015329
_N = NormalDist()


def forward_vs_hold(conn, cand_id: str, tf: str) -> Dict:
    """Forward-результат кандидата против HOLD BTC за ТО ЖЕ окно его наблюдений, после издержек."""
    rows = list(conn.execute(
        "SELECT bar_open_time, bar_close_time, bar_open, bar_close, equity, gap_bars FROM observations "
        "WHERE candidate_id=? ORDER BY bar_open_time", (cand_id,)))
    if not rows:
        return {"state": UNKNOWN, "why": "forward-наблюдений нет"}
    step = TF_MS.get(tf)
    if step is None:
        return {"state": UNKNOWN, "why": f"таймфрейм {tf!r} не известен"}
    first_open, last_close = rows[0][0], rows[-1][1]
    expected = round((last_close - first_open) / step)
    gaps = sum(r[5] for r in rows)
    out = {"bars": len(rows), "expected_bars": expected, "gap_bars": gaps,
           "window": {"from_ms": first_open, "to_ms": last_close}}
    if len(rows) != expected or gaps:
        return {**out, "state": INCOMPLETE,
                "why": f"в окне {expected} баров, наблюдений {len(rows)}, пропусков {gaps} — сравнение с "
                       f"непрерывным HOLD было бы нечестным"}
    p0, p1 = rows[0][2], rows[-1][3]
    if not (p0 and p0 > 0 and p1 and p1 > 0):
        return {**out, "state": UNKNOWN, "why": "цена открытия/закрытия окна не наблюдена"}
    entry_cost = EXEC_MODELS["spot_long"].cost_per_side
    hold = (p1 / p0) * (1 - entry_cost) - 1
    fwd = rows[-1][4] - 1.0
    return {**out, "state": MEASURED, "forward_net": round(fwd, 6), "hold_net": round(hold, 6),
            "excess_vs_hold": round(fwd - hold, 6),
            "hold_costs": f"одна сторона spot: {entry_cost * 1e4:.0f} bps (комиссия + проскальзывание)"}


def market_freshness(mconn, now_ms: int, symbol: str = "BTCUSDT") -> Dict:
    """Возраст последней закрытой часовой свечи. Нет свечей — ``UNKNOWN``."""
    try:
        row = mconn.execute("SELECT MAX(open_time) FROM candles WHERE symbol=? AND tf='1h'",
                            (symbol,)).fetchone()
    except Exception as exc:          # схема не та — это «не измерено», а не «свежо»
        return {"state": UNKNOWN, "why": f"рыночная база не прочитана: {type(exc).__name__}"}
    if not row or row[0] is None:
        return {"state": UNKNOWN, "why": "в рыночной базе нет часовых свечей"}
    close_ms = row[0] + TF_MS["1h"]
    age = now_ms - close_ms
    return {"state": "FRESH" if age <= STALE_AFTER_MS else "STALE", "last_close_ms": close_ms,
            "age_minutes": round(age / 60_000, 1), "stale_after_minutes": STALE_AFTER_MS / 60_000}


def _moments(xs: List[float]):
    n = len(xs)
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / (n - 1)
    if var <= 0:
        return mu, 0.0, 0.0, 3.0
    sd = math.sqrt(var)
    skew = sum(((x - mu) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - mu) / sd) ** 4 for x in xs) / n
    return mu, sd, skew, kurt


def _sr(returns: Iterable[float]) -> Optional[tuple]:
    xs = [float(x) for x in returns if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if len(xs) < 30:
        return None
    mu, sd, skew, kurt = _moments(xs)
    if sd == 0:
        return None
    return mu / sd, len(xs), skew, kurt


def effective_trials(results: List[Dict]) -> Optional[float]:
    """Эффективное число испытаний при средней попарной корреляции дневных OOS-доходностей ρ̄:
    N_eff = ρ̄ + (1 − ρ̄)·N. Испытания одной идеи сильно коррелированы, и считать их независимыми — поправка
    строже правды; это чувствительность, а не замена основного ответа."""
    series = []
    for r in results:
        d = r.get("oos_daily_returns") or {}
        if len(d) >= 30:
            series.append(d)
    n = len(series)
    if n < 2:
        return None
    total, pairs = 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            keys = series[i].keys() & series[j].keys()
            if len(keys) < 30:
                continue
            a = [series[i][k] for k in keys]
            b = [series[j][k] for k in keys]
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            sa = math.sqrt(sum((x - ma) ** 2 for x in a))
            sb = math.sqrt(sum((x - mb) ** 2 for x in b))
            if sa == 0 or sb == 0:
                continue
            total += sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)
            pairs += 1
    if not pairs:
        return None
    rho = total / pairs
    return round(rho + (1 - rho) * n, 2)


def deflated_sharpe(results: List[Dict], ids: Iterable[str], *, n_trials: Optional[float] = None) -> Dict:
    """DSR для выбранных кандидатов против ВСЕХ испытанных (``results`` бэктеста, дневные OOS-доходности).
    ``n_trials`` — переопределить число испытаний (чувствительность к N_eff); по умолчанию — все измеренные."""
    trials = {}
    for r in results:
        s = _sr((r.get("oos_daily_returns") or {}).values())
        if s is not None:
            trials[r["id"]] = s
    n = len(trials)
    base = {"trials_tested": len(results), "trials_measured": n,
            "method": "Deflated Sharpe Ratio (Bailey & López de Prado 2014), дневные OOS-доходности"}
    if n < 2:
        return {**base, "state": UNKNOWN, "why": "меньше двух испытаний с измеримым Sharpe", "candidates": {}}
    srs = [v[0] for v in trials.values()]
    m = sum(srs) / n
    n_used = n if n_trials is None else max(float(n_trials), 2.0)
    base["trials_used"] = n_used
    var_sr = sum((x - m) ** 2 for x in srs) / (n - 1)
    sr_star = math.sqrt(var_sr) * ((1 - _EULER) * _N.inv_cdf(1 - 1 / n_used)
                                  + _EULER * _N.inv_cdf(1 - 1 / (n_used * math.e)))
    out = {}
    for cid in ids:
        t = trials.get(cid)
        if t is None:
            out[cid] = {"state": UNKNOWN, "why": "нет ≥30 дневных OOS-доходностей с ненулевым разбросом"}
            continue
        sr, T, g3, g4 = t
        denom = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
        if denom <= 0:
            out[cid] = {"state": UNKNOWN, "why": "моменты доходностей дают неопределённую дисперсию оценки"}
            continue
        z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(denom)
        p = _N.cdf(z)
        out[cid] = {"state": MEASURED, "daily_sharpe": round(sr, 5), "observations": T, "dsr": round(p, 4),
                    "distinguishable_from_luck": p >= 0.95}
    return {**base, "state": MEASURED, "sr_threshold_daily": round(sr_star, 5), "candidates": out}


_CLOSED_WINDOWS = ("in_sample", "out_of_sample", "gating")
_CLOSED_FIELDS = ("bars", "net_return", "sharpe", "max_drawdown", "trades")


def closed_window_stability(history_files: Iterable) -> Dict:
    """Не переписывает ли обновление данных ЗАКРЫТОЕ прошлое: для каждой пары версий бэктеста с ОДНОЙ версией кода
    метрики закрытых окон (IS, OOS, срез до старта forward) обязаны совпадать. Смена кода — новая версия, а не
    переписывание: прежний файл истории остаётся. Ни одной сравнимой пары — ``UNKNOWN``, а не «стабильно»."""
    import json as _json
    from pathlib import Path as _P
    prev: Dict[tuple, tuple] = {}
    compared, changed, unreadable = 0, [], []
    files = sorted(_P(f) for f in history_files)
    for f in files:
        try:
            doc = _json.loads(f.read_text(encoding="utf-8"))
            code = doc["manifest"]["code_version"]
            results = doc["results"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            unreadable.append(f"{f.name}: {type(exc).__name__}")
            continue
        for r in results:
            for w in _CLOSED_WINDOWS:
                m = r.get(w) or {}
                sig = tuple(m.get(k) for k in _CLOSED_FIELDS)
                key = (code, r.get("id"), w)
                if key in prev:
                    compared += 1
                    if prev[key][1] != sig:
                        changed.append({"candidate": r.get("id"), "window": w, "code_version": code,
                                        "before": prev[key][0], "after": f.name})
                prev[key] = (f.name, sig)
    base = {"files": len(files), "compared": compared, "changed": changed[:20], "changed_count": len(changed),
            "unreadable": unreadable}
    if compared == 0:
        return {**base, "state": UNKNOWN, "why": "нет двух версий с одной версией кода — сравнивать нечего"}
    return {**base, "state": "STABLE" if not changed else "REWRITTEN"}
