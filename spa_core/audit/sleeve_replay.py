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

        dy, _deployed = sleeve_book.accrue_book(copy.deepcopy(after), cands)
        cost = sleeve_book.book_move_cost(pl.get("book_before"), pl.get("book_after"),
                                          pl.get("chains") or {})["cost_usd"]
        mtm = sleeve_book.mark_to_market(after, pl.get("prices") or {})["pnl_usd"]

        want_open = float(pl.get("open_equity") or 0.0)
        got_close = want_open + dy - cost + mtm
        stored_close = float(bar.get("equity") if bar.get("equity") is not None
                             else pl.get("close_equity") or 0.0)
        delta = abs(got_close - stored_close)
        worst = max(worst, delta)
        if delta > tolerance_usd:
            diffs.append({"date": dt, "replayed": round(got_close, 6),
                          "stored": round(stored_close, 6), "delta_usd": round(delta, 6),
                          "legs": {"yield": round(dy, 6), "cost": round(cost, 6),
                                   "mtm": round(mtm, 6)}})

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
