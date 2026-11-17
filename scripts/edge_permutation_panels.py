#!/usr/bin/env python3
"""#162 PERM — перестановочные панели: мерил ли реестр ПРАВИЛО ОТБОРА или свой ГЕНЕРАТОР.

ИСПОЛНЕНИЕ ЗАКАЗА #157 IOB, дословно: «три кризиса фикстуры — это три авторских вектора
`window_hits`. Приёмка — прибор, который по ТЕМ ЖЕ пяти книгам строит K ≥ 10 ПЕРЕСТАНОВОЧНЫХ
панелей (перемешать `window_hits` между книгами при фиксированных дрейфах) и печатает долю
панелей, где любое правило отбора реестра (#150 QUIET-N, #153 CRP, #156 MES) угадывает пару
в ≥ 2 складках из 3. Если доля ≈ 0.01 — реестр мерил генератор; если выше — у правила есть
содержание, которое одна панель показать не могла.»

Перестановок берётся НЕ K ≥ 10, а ВСЕ **120 = 5!** — выборка здесь не нужна и была бы худшим
ответом на тот же вопрос: пространство конечно и обходится целиком за секунды, а доля по полному
обходу не зависит ни от семени, ни от порядка.

Что именно перемешивается и почему только это. `daily_drift` (headline carry книги) остаётся на
своём месте, переставляются ТОЛЬКО векторы `window_hits` — кризисные потери. Тогда «кто тише в
спокойные дни» сохраняется, а «кто теряет в каком кризисе» становится случайным: если правило
отбора несёт содержание, оно обязано угадывать ХУЖЕ на перемешанных панелях, чем на настоящей.
Если же доля попаданий на 120 панелях такая же, как на настоящей, — правило угадывает АВТОРСКУЮ
КОНСТАНТУ, а не свойство книги.

Нулевая гипотеза (арифметика #157 §1, не зависит от панели): пара из 5 книг угадывается случайно
с вероятностью 1/C(5,2) = 0.100; ≥ 2 точных попадания из 3 складок — 3·0.1²·0.9 + 0.1³ = **0.028**.

Три исхода у КАЖДОЙ складки различимы (инв. #17): ПОПАДАНИЕ · ПРОМАХ · **НЕ ИЗМЕРЕНО** (правило
не смогло назвать пару — например у всех книг TRAIN вырожден). «Не измерено» НИКОГДА не
засчитывается промахом: это завысило бы знаменатель и занизило долю, то есть подтвердило бы
вывод прибора его же слепотой.

Коды возврата: **0** — измерено · **2** — НЕ ИЗМЕРЕНО (фикстура недоступна, ни одной складки).

Только stdlib, детерминированно, никакой сети. `data/` не открывается вовсе: предмет — ФИКСТУРА.
IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS            # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures as _fx           # noqa: E402

# Правила отбора реестра, которые заказ #157 назвал поимённо.
RULES = ("QUIET-N", "CRP", "MES")
PAIR_SIZE = 2
# Доля худших дней панели, по которым считается MES (#156). Один параметр, и он назван.
MES_TAIL_FRACTION = 0.05


class Unmeasured(Exception):
    """Предпосылка замера НЕ ОБЕСПЕЧЕНА: причина называется, код возврата 2."""


# ── панель ──────────────────────────────────────────────────────────────────────────────────────
def backtest_books() -> List[str]:
    """Книги фикстуры, у которых ЕСТЬ бэктест-ряд (`thin_new` его не имеет по построению)."""
    books = sorted(k for k, spec in _fx._SPEC.items() if not spec.get("no_backtest"))
    if len(books) < PAIR_SIZE + 1:
        raise Unmeasured(f"книг с бэктестом {len(books)} — пару из них выбирать не из чего")
    return books


def crisis_keys() -> List[str]:
    keys = [str(w["key"]) for w in STRESS_WINDOWS
            if any(str(w["key"]) in (_fx._SPEC[b].get("window_hits") or {}) for b in backtest_books())]
    if len(keys) < 2:
        raise Unmeasured(f"кризисов, которые хоть одна книга переживает, {len(keys)} — "
                         "складок leave-one-crisis-out не построить")
    return keys


def crisis_bounds(key: str) -> Tuple[datetime.date, datetime.date]:
    for w in STRESS_WINDOWS:
        if str(w["key"]) == key:
            return (datetime.date.fromisoformat(str(w["date_from"])),
                    datetime.date.fromisoformat(str(w["date_to"])))
    raise Unmeasured(f"окна `{key}` нет в STRESS_WINDOWS")


def permuted_panel(books: Sequence[str], perm: Sequence[int],
                   drift_scale: float = 1.0) -> Dict[str, List[dict]]:
    """Панель, где книга `books[i]` несёт СВОЙ дрейф и ЧУЖОЙ вектор кризисных потерь `books[perm[i]]`.

    Ряд строит тот же самый генератор фикстуры (`fixtures._build_backtest_series`) — прибор не
    переписывает панель своей арифметикой, иначе мерил бы себя.

    `drift_scale` — МНОЖИТЕЛЬ дрейфа, и он существует ровно для положительного контроля самого
    замера. На фикстуре дрейф (11…15 %/год ⇒ ~0.03…0.04 % в день) на три порядка меньше кризисных
    потерь (1…28 % за окно), поэтому и правило отбора, и цель оказываются функциями ОДНОГО
    вектора `window_hits`; под перестановкой этого вектора обе стороны переставляются ОДИНАКОВО,
    и число попаданий становится ИНВАРИАНТОМ. Инвариантный ответ обязан доказать, что он
    СПОСОБЕН меняться, иначе он есть свойство прибора: `--drift-scale` — та ручка, которая
    возвращает дрейфу вес и разрывает эту симметрию. Боевое значение — 1.0.
    """
    if sorted(perm) != list(range(len(books))):
        raise Unmeasured(f"перестановка {perm} не является перестановкой {len(books)} книг")
    if not drift_scale > 0:
        raise Unmeasured(f"--drift-scale={drift_scale}: неположительный множитель дрейфа "
                         "панелью не является")
    panel: Dict[str, List[dict]] = {}
    for i, book in enumerate(books):
        spec = dict(_fx._SPEC[book])
        spec["window_hits"] = dict(_fx._SPEC[books[perm[i]]].get("window_hits") or {})
        spec["daily_drift"] = float(spec["daily_drift"]) * drift_scale
        panel[book] = _fx._build_backtest_series(spec)
    return panel


def explain_panel(books: Sequence[str], perm: Sequence[int], keys: Sequence[str],
                  drift_scale: float = 1.0) -> dict:
    """Почему правило отвечает так, как отвечает: σ, время восстановления и потери ПОИМЁННО.

    Нужна, чтобы «правило НЕ СМОГЛО назвать пару» было ЧИТАЕМЫМ состоянием, а не загадкой:
    ничья на границе отбора печатается значениями, которые её создали.
    """
    panel = permuted_panel(books, perm, drift_scale)
    out: Dict[str, Dict[str, object]] = {}
    for book, series in panel.items():
        rets = [r for _, r in daily_returns(series)]
        out[book] = {
            "sigma_all_days": statistics.pstdev(rets) if len(rets) > 2 else None,
            "recovery_days": {k: recovery_days(series, k) for k in keys},
            "window_loss": {k: window_loss(series, k) for k in keys},
            "hits_carried": dict(_fx._SPEC[books[list(perm)[list(books).index(book)]]]
                                 .get("window_hits") or {}),
        }
    return out


# ── ряды ────────────────────────────────────────────────────────────────────────────────────────
def daily_returns(series: Sequence[dict]) -> List[Tuple[datetime.date, float]]:
    out: List[Tuple[datetime.date, float]] = []
    prev: Optional[float] = None
    for point in series:
        raw_eq = point.get("equity_usd")
        raw_d = point.get("date")
        if not isinstance(raw_eq, (int, float)) or isinstance(raw_eq, bool) or not isinstance(raw_d, str):
            prev = None            # пропуск наблюдения разрывает ряд, а не обнуляет доход
            continue
        day = datetime.date.fromisoformat(raw_d)
        if prev is not None and prev > 0:
            out.append((day, float(raw_eq) / prev - 1.0))
        prev = float(raw_eq)
    return out


def _equity_at(series: Sequence[dict], lo: datetime.date, hi: datetime.date) -> List[Tuple[datetime.date, float]]:
    pts = []
    for point in series:
        raw_d, raw_eq = point.get("date"), point.get("equity_usd")
        if not isinstance(raw_d, str) or not isinstance(raw_eq, (int, float)) or isinstance(raw_eq, bool):
            continue
        day = datetime.date.fromisoformat(raw_d)
        if lo <= day <= hi:
            pts.append((day, float(raw_eq)))
    return pts


def window_loss(series: Sequence[dict], key: str) -> Optional[float]:
    """Потеря книги ВНУТРИ окна кризиса: `min(equity)/equity(начало окна) − 1`.

    ``None`` — окна в ряде нет (это НЕ нулевая потеря).
    """
    lo, hi = crisis_bounds(key)
    pts = _equity_at(series, lo, hi)
    if len(pts) < 2:
        return None
    start = pts[0][1]
    if start <= 0:
        return None
    return min(eq for _, eq in pts) / start - 1.0


def recovery_days(series: Sequence[dict], key: str) -> Optional[float]:
    """Сколько дней от минимума внутри окна до возврата к пред-кризисному пику.

    ``None`` — не измерено (нет окна или нет пред-кризисной истории). ``float('inf')`` —
    наблюдение ЦЕНЗУРИРОВАНО: до конца ряда книга не вернулась; это ЗНАЧЕНИЕ, не пропуск.
    """
    lo, hi = crisis_bounds(key)
    before = _equity_at(series, datetime.date(1970, 1, 1), lo - datetime.timedelta(days=1))
    inside = _equity_at(series, lo, hi)
    if not before or not inside:
        return None
    peak = max(eq for _, eq in before)
    trough_day, trough = min(inside, key=lambda p: p[1])
    if trough >= peak:
        return 0.0                 # книга не уходила ниже пика — измерено и равно нулю
    after = _equity_at(series, trough_day, datetime.date(9999, 12, 31))
    for day, eq in after:
        if eq >= peak:
            return float((day - trough_day).days)
    return float("inf")


# ── правила отбора реестра ──────────────────────────────────────────────────────────────────────
def _pick_lowest(scores: Dict[str, float], n: int = PAIR_SIZE) -> Optional[FrozenSet[str]]:
    """`n` книг с наименьшим счётом. ``None`` — счётов меньше `n` либо есть НИЧЬЯ на границе.

    Ничья — честное «НЕ ИЗМЕРЕНО», а не «возьмём по алфавиту»: произвольный разрыв ничьей
    сделал бы попадание свойством сортировки, и ровно это прибор обязан не делать.
    """
    usable = {k: v for k, v in scores.items() if v is not None}
    if len(usable) < n + 1:
        return None
    ordered = sorted(usable.items(), key=lambda kv: (kv[1], kv[0]))
    if ordered[n - 1][1] == ordered[n][1]:
        return None
    return frozenset(k for k, _ in ordered[:n])


def rule_quiet(panel: Dict[str, List[dict]], train_keys: Sequence[str],
               held_out: str) -> Optional[FrozenSet[str]]:
    """#150 QUIET-N: две САМЫЕ ТИХИЕ книги по σ дневных доходностей на TRAIN.

    TRAIN — все дни бэктеста, КРОМЕ окна удержанного кризиса: заглянуть в удержанное окно
    значило бы проверить правило самим собой.
    """
    lo, hi = crisis_bounds(held_out)
    scores: Dict[str, float] = {}
    for book, series in panel.items():
        rets = [r for day, r in daily_returns(series) if not (lo <= day <= hi)]
        if len(rets) < 3:
            continue
        scores[book] = statistics.pstdev(rets)
    return _pick_lowest(scores)


def rule_crp(panel: Dict[str, List[dict]], train_keys: Sequence[str],
             held_out: str) -> Optional[FrozenSet[str]]:
    """#153 CRP: две книги с НАИМЕНЬШИМ медианным временем восстановления по TRAIN-кризисам."""
    scores: Dict[str, float] = {}
    for book, series in panel.items():
        times = [t for t in (recovery_days(series, key) for key in train_keys) if t is not None]
        if not times:
            continue
        scores[book] = statistics.median(times)
    return _pick_lowest(scores)


def rule_mes(panel: Dict[str, List[dict]], train_keys: Sequence[str],
             held_out: str) -> Optional[FrozenSet[str]]:
    """#156 MES: две книги с НАИМЕНЬШИМ условным убытком в худшие p% дней равновесной панели.

    Счёт книги — её средняя доходность в те дни, когда ПАНЕЛЬ была в худших p%; меньший убыток
    (то есть больший средний доход) считается лучшим, поэтому счёт берётся со знаком минус.
    """
    lo, hi = crisis_bounds(held_out)
    per_book: Dict[str, Dict[datetime.date, float]] = {
        book: {day: r for day, r in daily_returns(series) if not (lo <= day <= hi)}
        for book, series in panel.items()
    }
    days = sorted(set.intersection(*(set(d) for d in per_book.values())) if per_book else [])
    if len(days) < 20:
        return None
    panel_ret = [(day, statistics.fmean(per_book[b][day] for b in per_book)) for day in days]
    panel_ret.sort(key=lambda p: p[1])
    tail_n = max(1, int(len(panel_ret) * MES_TAIL_FRACTION))
    tail_days = {day for day, _ in panel_ret[:tail_n]}
    scores: Dict[str, float] = {}
    for book, by_day in per_book.items():
        vals = [by_day[day] for day in tail_days]
        if not vals:
            continue
        scores[book] = -statistics.fmean(vals)
    return _pick_lowest(scores)


_RULE_FNS = {"QUIET-N": rule_quiet, "CRP": rule_crp, "MES": rule_mes}


def target_pair(panel: Dict[str, List[dict]], held_out: str) -> Optional[FrozenSet[str]]:
    """Пара книг с НАИМЕНЬШЕЙ потерей в удержанном кризисе — то, что правило должно было угадать."""
    losses: Dict[str, float] = {}
    for book, series in panel.items():
        loss = window_loss(series, held_out)
        if loss is None:
            continue
        losses[book] = -loss       # меньшая потеря = меньший счёт
    return _pick_lowest(losses)


# ── замер ───────────────────────────────────────────────────────────────────────────────────────
def score_panel(panel: Dict[str, List[dict]], keys: Sequence[str]) -> Dict[str, Dict[str, int]]:
    """По каждому правилу: сколько складок ПОПАДАНИЕ · ПРОМАХ · НЕ ИЗМЕРЕНО."""
    out = {rule: {"hit": 0, "miss": 0, "unmeasured": 0} for rule in RULES}
    for held_out in keys:
        train = [k for k in keys if k != held_out]
        truth = target_pair(panel, held_out)
        for rule in RULES:
            pick = _RULE_FNS[rule](panel, train, held_out)
            if truth is None or pick is None:
                out[rule]["unmeasured"] += 1
            elif pick == truth:
                out[rule]["hit"] += 1
            else:
                out[rule]["miss"] += 1
    return out


def null_probability(n_books: int, folds: int, min_hits: int) -> float:
    """P(≥ `min_hits` точных попаданий из `folds`) при случайном угадывании пары из `n_books`."""
    import math
    p = 1.0 / math.comb(n_books, PAIR_SIZE)
    total = 0.0
    for k in range(min_hits, folds + 1):
        total += math.comb(folds, k) * (p ** k) * ((1 - p) ** (folds - k))
    return total


def run(limit: Optional[int] = None, min_hits: int = 2, drift_scale: float = 1.0) -> dict:
    books = backtest_books()
    keys = crisis_keys()
    perms = list(itertools.permutations(range(len(books))))
    identity = tuple(range(len(books)))
    if limit is not None:
        if limit < 1:
            raise Unmeasured(f"--limit={limit}: панелей меньше одной не бывает")
        perms = perms[:limit]
        if identity not in perms:
            perms = [identity] + perms[:-1]
    rows: List[dict] = []
    for perm in perms:
        panel = permuted_panel(books, perm, drift_scale)
        rows.append({"perm": perm, "identity": perm == identity, "scores": score_panel(panel, keys)})
    if not rows:
        raise Unmeasured("ни одной панели не построено")

    per_rule: Dict[str, dict] = {}
    for rule in RULES:
        measured = [r for r in rows if r["scores"][rule]["unmeasured"] == 0]
        winners = [r for r in measured if r["scores"][rule]["hit"] >= min_hits]
        hits_hist: Dict[int, int] = {}
        for r in measured:
            hits_hist[r["scores"][rule]["hit"]] = hits_hist.get(r["scores"][rule]["hit"], 0) + 1
        ident = next((r for r in rows if r["identity"]), None)
        folds_hit = sum(r["scores"][rule]["hit"] for r in rows)
        folds_miss = sum(r["scores"][rule]["miss"] for r in rows)
        folds_unmeasured = sum(r["scores"][rule]["unmeasured"] for r in rows)
        per_rule[rule] = {
            "folds_hit": folds_hit,
            "folds_miss": folds_miss,
            "folds_unmeasured": folds_unmeasured,
            # Доля ПО СКЛАДКАМ считается от ИЗМЕРЕННЫХ складок: «не измерено» в знаменателе
            # занизило бы её, то есть подтвердило бы вывод слепотой прибора.
            "fold_hit_rate": ((folds_hit / (folds_hit + folds_miss))
                              if (folds_hit + folds_miss) else None),
            "panels_total": len(rows),
            "panels_measured": len(measured),
            "panels_unmeasured": len(rows) - len(measured),
            "panels_with_min_hits": len(winners),
            "share": (len(winners) / len(measured)) if measured else None,
            "hits_histogram": dict(sorted(hits_hist.items())),
            "identity_panel": (ident["scores"][rule] if ident else None),
        }
    distinct_hit_counts = {rule: len({r["scores"][rule]["hit"] for r in rows
                                      if r["scores"][rule]["unmeasured"] == 0})
                           for rule in RULES}
    return {
        "books": books,
        "drift_scale": drift_scale,
        "distinct_hit_counts": distinct_hit_counts,
        "crises": keys,
        "folds": len(keys),
        "min_hits": min_hits,
        "panels": len(rows),
        "null_share": null_probability(len(books), len(keys), min_hits),
        "null_fold_rate": null_probability(len(books), 1, 1),
        "per_rule": per_rule,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#162 PERM — перестановочные панели (заказ #157)")
    ap.add_argument("--limit", type=int, default=None,
                    help="взять только первые N перестановок (по умолчанию — ВСЕ 5! = 120)")
    ap.add_argument("--min-hits", type=int, default=2,
                    help="сколько точных попаданий считается успехом панели (заказ #157: 2 из 3)")
    ap.add_argument("--drift-scale", type=float, default=1.0,
                    help="множитель дрейфа; ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ замера, боевое значение 1.0")
    ap.add_argument("--explain", action="store_true",
                    help="печатать σ, время восстановления и потери настоящей панели ПОИМЁННО")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        res = run(limit=args.limit, min_hits=args.min_hits, drift_scale=args.drift_scale)
        if args.explain:
            books, keys = backtest_books(), crisis_keys()
            res["explain_identity_panel"] = explain_panel(
                books, tuple(range(len(books))), keys, args.drift_scale)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0

    print("#162 PERM — перестановочные панели (ИСПОЛНЕНИЕ ЗАКАЗА #157)")
    print("=" * 96)
    print(f"книг с бэктестом: {len(res['books'])} — {', '.join(res['books'])}")
    print(f"кризисов (складок leave-one-crisis-out): {res['folds']} — {', '.join(res['crises'])}")
    print(f"панелей: {res['panels']} (перемешан ТОЛЬКО вектор window_hits, дрейфы на месте)")
    print(f"множитель дрейфа: ×{res['drift_scale']}"
          f"{'  (боевое значение)' if res['drift_scale'] == 1.0 else '  ⚠️ КОНТРОЛЬНЫЙ, не боевой'}")
    print(f"успех панели: ≥ {res['min_hits']} точных попаданий из {res['folds']}")
    print(f"случайное ожидание доли ПАНЕЛЕЙ: {res['null_share']:.4f} · "
          f"одной СКЛАДКИ: {res['null_fold_rate']:.4f}")
    print()
    print(f"{'правило':<10} {'измер.':>7} {'НЕ ИЗМ.':>8} {'успешных':>9} {'доля':>8} "
          f"{'настоящая панель (hit/miss/НЕ ИЗМ)':>34}")
    for rule, info in res["per_rule"].items():
        ident = info["identity_panel"]
        ident_s = ("НЕ ИЗМЕРЕНО" if ident is None
                   else f"{ident['hit']}/{ident['miss']}/{ident['unmeasured']}")
        share = "НЕ ИЗМЕРЕНО" if info["share"] is None else f"{info['share']:.4f}"
        print(f"{rule:<10} {info['panels_measured']:>7} {info['panels_unmeasured']:>8} "
              f"{info['panels_with_min_hits']:>9} {share:>8} {ident_s:>34}")
        rate = ("НЕ ИЗМЕРЕНО" if info["fold_hit_rate"] is None
                else f"{info['fold_hit_rate']:.4f}")
        print(f"{'':<10} по СКЛАДКАМ: попаданий {info['folds_hit']} · промахов "
              f"{info['folds_miss']} · НЕ ИЗМЕРЕНО {info['folds_unmeasured']} · доля {rate}")
        print(f"{'':<10} распределение попаданий по панелям: {info['hits_histogram']} · "
              f"различных значений: {res['distinct_hit_counts'][rule]}"
              f"{'  ⚠️ ИНВАРИАНТ — ответ не меняется ни на одной перестановке' if res['distinct_hit_counts'][rule] == 1 else ''}")
    print()
    print("Читать так: доля ≈ случайного ожидания ⇒ правило угадывает АВТОРСКУЮ КОНСТАНТУ")
    print("генератора, а не свойство книги. Доля СУЩЕСТВЕННО выше ⇒ у правила есть содержание,")
    print("которое одна панель показать не могла. Настоящая панель — одна из 120 и сама по себе")
    print("вердиктом не является (ровно урок #157: одно наблюдение даёт p = 0.10).")
    if "explain_identity_panel" in res:
        print()
        print("ПОИМЁННО по настоящей панели (почему правило отвечает так):")
        for book, info in res["explain_identity_panel"].items():
            sigma = info["sigma_all_days"]
            print(f"  {book:<16} σ={'НЕ ИЗМЕРЕНО' if sigma is None else format(sigma, '.6f')}")
            print(f"    восстановление, дн: {info['recovery_days']}")
            print(f"    потеря в окне:      "
                  f"{ {k: (None if v is None else round(v, 4)) for k, v in info['window_loss'].items()} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
