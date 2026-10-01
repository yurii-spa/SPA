#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.sleeve_replay — пересчёт дня книг Balanced/Aggressive из сохранённых входов.

NO FORK, как у `replay_equity`: день пересчитывается ТЕМИ ЖЕ функциями, которыми считал цикл
(`sleeve_book.accrue_book`, `book_move_cost`, `mark_to_market`). Пересчёт отвечает на вопрос
«произвели ли сохранённые входы сохранённую строку?», а НЕ «согласны ли две формулы между собой» —
вторая формула доказывала бы только то, что автор дважды подумал одинаково.

Три исхода, без исключений наружу:

``PASS``
    каждая запись архива пересчитывается в свою строку истории с точностью до ``tolerance_usd``.
``FAIL``
    хотя бы одна расходится — называются даты и худшая дельта.
``UNCHECKED``
    архива нет, цепочка порвана или нет пересечения с историей книги. «Не измерено», а не
    «сходится»: пустой архив, выданный за успех, — самый тихий способ соврать о треке.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from spa_core.audit import sleeve_inputs_archive as archive
from spa_core.paper_trading import sleeve_book

TOLERANCE_USD = 0.01

#: Файл истории на книгу. Читается только он: у книг нет общей кривой.
STATE_FILE = {"balanced": "hy_paper_trading.json", "aggressive": "lp_paper_trading.json"}


def _history(data_dir: Path, book: str) -> dict[str, dict]:
    import json
    p = data_dir / STATE_FILE[book]
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for bar in (doc.get("daily_history") or []):
        if isinstance(bar, dict) and bar.get("date"):
            out[str(bar["date"])] = bar     # последняя запись даты выигрывает — как в кривой
    return out


def sub_book_value(sub: dict) -> "float | None":
    """Close value of a mechanic sub-book from its recorded legs/inputs (ADR-533)."""
    kind = sub.get("kind")
    if kind == "pt_carry":
        return round(sum(float(l["units"]) * float(l["mark"]) for l in sub.get("legs_after") or []), 6)
    if kind == "loop":
        st = sub.get("state_after") or {}
        if st.get("status") != "open":
            return 0.0
        vi = sub.get("valuation_inputs") or {}
        if vi.get("price") is None or vi.get("debt_per_share") is None:
            return None
        return round(float(st["collateral_units"]) * float(vi["price"])
                     - float(st["debt_shares"]) * float(vi["debt_per_share"]), 6)
    return None


def replay(data_dir: str | os.PathLike, book: str,
           tolerance_usd: float = TOLERANCE_USD) -> dict[str, Any]:
    d = Path(data_dir)
    if book not in archive.BOOKS:
        return {"status": "UNCHECKED", "book": book, "days": 0,
                "reason": f"unknown book {book!r}"}
    entries = archive.read_all(d, book)
    if not entries:
        return {"status": "UNCHECKED", "book": book, "days": 0, "reruns": {},
                "reason": "архива входов ещё нет (он начинается с первого цикла после доставки)",
                "chain": {"ok": None}}
    chain = archive.verify(d, book)
    if not chain.get("ok"):
        return {"status": "UNCHECKED", "book": book, "days": 0, "reruns": {},
                "reason": f"цепочка архива порвана: {chain.get('reason')} (seq {chain.get('broken_at')})",
                "chain": chain}

    hist = _history(d, book)
    by_date: dict[str, dict] = {}
    reruns: dict[str, int] = {}
    for e in entries:
        pl = e.get("payload") or {}
        dt = str(pl.get("cycle_date") or "")
        if not dt:
            continue
        reruns[dt] = reruns.get(dt, 0) + 1
        by_date[dt] = pl                    # последний прогон даты — тот, что оставил строку

    dates = sorted(set(by_date) & set(hist))
    if not dates:
        return {"status": "UNCHECKED", "book": book, "days": 0, "reruns": reruns,
                "reason": "нет ни одной даты, которая есть и в архиве, и в истории книги",
                "chain": chain}

    diffs: list[dict] = []
    worst = 0.0
    for dt in dates:
        pl = by_date[dt]
        bar = hist[dt]
        cands = [dict(c) for c in (pl.get("candidates") or [])]

        # книга ПОСЛЕ ребаланса, но ДО начисления/переоценки: копия, чтобы пересчёт не
        # трогал сохранённое (accrue_book пишет `stale`, mark_to_market — `mark_price`)
        after = copy.deepcopy(pl.get("book_after") or [])
        for leg in after:
            mp = (pl.get("marks_before") or {}).get(leg.get("protocol"))
            if mp is None:
                leg.pop("mark_price", None)
            else:
                leg["mark_price"] = mp

        # ADR-531: день пересчитывается ТОЙ моделью, что его писала. Нет поля ⇒ v1
        # (записи до 2026-10-01) — без полосы пыли, как они и были посчитаны.
        model = pl.get("economics_model") or sleeve_book.ECONOMICS_MODEL_V1
        if model == sleeve_book.ECONOMICS_MODEL_V1:
            dust = 0.0
        elif model == sleeve_book.ECONOMICS_MODEL and pl.get("cost_dust_usd") is not None:
            dust = float(pl["cost_dust_usd"])
        else:
            diffs.append({"date": dt, "reason": f"модель {model!r} без полосы пыли или незнакома — "
                                                "день не пересчитать"})
            continue
        cost = sleeve_book.book_move_cost(pl.get("book_before"), pl.get("book_after"),
                                          pl.get("chains") or {}, dust_usd=dust)["cost_usd"]
        if model == sleeve_book.ECONOMICS_MODEL:
            # v2: процент сначала растёт ВНУТРИ позиции, затем переоценка — тот же порядок, что
            # у цикла (иначе движение цены считалось бы без сегодняшнего процента).
            dy, _deployed = sleeve_book.accrue_book(after, cands, compound_in_place=True)
        else:
            dy, _deployed = sleeve_book.accrue_book(copy.deepcopy(after), cands)
        mtm = sleeve_book.mark_to_market(after, pl.get("prices") or {})["pnl_usd"]

        want_open = float(pl.get("open_equity") or 0.0)
        got_close = want_open + dy - cost + mtm
        # ADR-533: a day with a mechanic sub-book closes at floating part + sub-book. The sub-book's
        # close value is RE-DERIVED from its recorded legs / inputs, not copied from the record.
        sub = pl.get("sub_book")
        if isinstance(sub, dict):
            sub_val = sub_book_value(sub)
            if sub_val is None or abs(sub_val - float(sub.get("value_close") or 0.0)) > tolerance_usd:
                diffs.append({"date": dt, "reason": "sub-book close value does not re-derive",
                              "recorded": sub.get("value_close"), "rederived": sub_val})
                continue
            got_close += sub_val
        stored_close = float(bar.get("equity") if bar.get("equity") is not None
                             else pl.get("close_equity") or 0.0)
        delta = abs(got_close - stored_close)
        worst = max(worst, delta)
        if delta > tolerance_usd:
            diffs.append({"date": dt, "replayed": round(got_close, 6),
                          "stored": round(stored_close, 6), "delta_usd": round(delta, 6),
                          "legs": {"yield": round(dy, 6), "cost": round(cost, 6),
                                   "mtm": round(mtm, 6)}})

    # ADR-533: day-to-day CONTINUITY of the floating part. A day's opening floating equity must be the
    # previous day's closing floating equity moved only by the cash the mechanic sub-book took or gave
    # (PT bought / redeemed / sold; loop cash in / out, intraday unwind cash). Without this the replay
    # starts each day from the recorded opening and cannot see a flow applied twice or not at all.
    for prev_dt, cur_dt in zip(sorted(by_date), sorted(by_date)[1:]):
        prev, cur = by_date[prev_dt], by_date[cur_dt]
        sub = cur.get("sub_book")
        if not isinstance(sub, dict):
            continue
        if sub.get("kind") == "pt_carry":
            flow = (-float(sub.get("bought_usd") or 0.0) + float(sub.get("redeemed_usd") or 0.0)
                    + float(sub.get("sold_usd") or 0.0))
        elif sub.get("kind") == "loop":
            flow = (-float(sub.get("cash_in_usd") or 0.0) + float(sub.get("cash_out_usd") or 0.0)
                    + float(sub.get("intraday_cash_in_usd") or 0.0))
        else:
            continue
        prev_float = float(prev.get("close_equity") or 0.0)
        # the previous day closed WITH a sub-book: its total is floating + sub value; its archived
        # close_equity is the floating part (ADR-533) — a legacy day (no sub-book) closed floating = total
        want = prev_float + flow
        got = float(cur.get("open_equity") or 0.0)
        if abs(want - got) > tolerance_usd:
            diffs.append({"date": cur_dt, "reason": "floating part does not continue from the previous day",
                          "expected_open": round(want, 6), "recorded_open": round(got, 6),
                          "flow_usd": round(flow, 6)})

    return {
        "status": "FAIL" if diffs else "PASS",
        "book": book,
        "days": len(dates),
        "first": dates[0],
        "last": dates[-1],
        "tolerance_usd": tolerance_usd,
        "max_abs_diff_usd": round(worst, 6),
        "diffs": diffs,
        "reruns": {k: v for k, v in reruns.items() if v > 1},
        "chain": chain,
        "reason": None,
    }


def replay_all(data_dir: str | os.PathLike,
               tolerance_usd: float = TOLERANCE_USD) -> dict[str, Any]:
    """Обе книги. Общий статус — худший из двух; UNCHECKED не считается успехом."""
    per = {b: replay(data_dir, b, tolerance_usd) for b in archive.BOOKS}
    order = {"FAIL": 2, "UNCHECKED": 1, "PASS": 0}
    worst = max(per.values(), key=lambda r: order.get(r["status"], 1))
    return {"status": worst["status"], "books": per}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="пересчитать дни книг Balanced/Aggressive из архива входов")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--book", choices=(*archive.BOOKS, "all"), default="all")
    a = ap.parse_args(argv)
    rep = replay_all(a.data_dir) if a.book == "all" else replay(a.data_dir, a.book)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
