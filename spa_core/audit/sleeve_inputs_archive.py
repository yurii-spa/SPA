#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.sleeve_inputs_archive — архив ВХОДОВ книг Balanced и Aggressive (ADR-292, п. 4).

Зачем. Приёмка ADR-292 требует у советательных книг ту же доказательную обвязку, что у
консервативной: «пересчёт кривой из сохранённого». Строка истории книги сама по себе для этого не
годится — в ней лежат результаты (`daily_yield_usd`, `cost_usd`, `mtm_pnl_usd`), а не входы, из
которых они получились. По результатам нельзя проверить результаты.

Что пишем. Один хеш-связанный слепок на прогон: книга ДО ребаланса, книга ПОСЛЕ, набор кандидатов
с их наблюдёнными ставками, карта сетей, наблюдённые цены и отметки, с которыми книга пришла в
день. Этого ровно достаточно, чтобы `spa_core.audit.sleeve_replay` пересчитал день ТЕМИ ЖЕ
функциями, которыми считал цикл, — без второй формулы (правило NO FORK из `replay_equity`).

Механизм цепочки не свой: `append_record`/`verify`/`read_all` берутся у
`cycle_inputs_archive` с другим именем файла и типом события. Вторая копия хеш-цепочки рядом с
первой — это две реализации одного инварианта, которые однажды разойдутся.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from spa_core.audit import cycle_inputs_archive as _base

SCHEMA_VERSION = "1.0"
BOOKS = ("balanced", "aggressive")


def filename_for(book: str) -> str:
    if book not in BOOKS:
        raise ValueError(f"unknown book {book!r} (expected one of {BOOKS})")
    return f"sleeve_inputs_{book}.jsonl"


def event_type_for(book: str) -> str:
    return f"sleeve_inputs_{book}"


def path_for(data_dir: str | os.PathLike, book: str):
    return _base.path_for(data_dir, filename_for(book))


def read_all(data_dir: str | os.PathLike, book: str) -> list[dict]:
    return _base.read_all(data_dir, filename_for(book))


def verify(data_dir: str | os.PathLike, book: str) -> dict:
    return _base.verify(data_dir, filename_for(book))


def _legs(book_legs: Optional[list]) -> list[dict]:
    """Ноги в том виде, в каком их видели считающие функции — дословно, без чистки.

    Чистить здесь нельзя по той же причине, что и в `cycle_inputs_archive.build_record`:
    пересчёт должен увидеть ТЕ ЖЕ значения, что видел цикл, включая мусор, который функции
    отвергли. Иначе пересчёт докажет исправность на исправленном входе.
    """
    out = []
    for leg in book_legs or []:
        if not isinstance(leg, dict):
            continue
        out.append({k: leg.get(k) for k in
                    ("protocol", "notional_usd", "apy_pct", "opened", "is_delta_neutral",
                     "stale", "mark_price")})
    return out


def build_record(
    *,
    book: str,
    cycle_date: str,
    run_ts: str,
    open_equity: float,
    close_equity: float,
    book_before: Optional[list],
    book_after: Optional[list],
    candidates: Optional[list],
    chains: Optional[dict],
    prices: Optional[dict],
    marks_before: Optional[dict],
    daily_yield_usd: float,
    cost_usd: float,
    mtm_pnl_usd: float,
    accrual_basis: str,
    allow_new: Optional[bool] = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "book": book,
        "cycle_date": cycle_date,
        "run_ts": run_ts,
        "open_equity": round(float(open_equity), 6),
        "book_before": _legs(book_before),
        "book_after": _legs(book_after),
        "candidates": [{"protocol": c.get("protocol"), "apy_pct": c.get("apy_pct")}
                       for c in (candidates or []) if isinstance(c, dict)],
        "chains": dict(chains or {}),
        "prices": dict(prices or {}),
        "marks_before": dict(marks_before or {}),
        "daily_yield_usd": round(float(daily_yield_usd), 6),
        "cost_usd": round(float(cost_usd), 6),
        "mtm_pnl_usd": round(float(mtm_pnl_usd), 6),
        "close_equity": round(float(close_equity), 6),
        "accrual_basis": accrual_basis,
        "allow_new": allow_new,
    }


def append_record(data_dir: str | os.PathLike, book: str, payload: dict, ts: str) -> dict:
    return _base.append_record(data_dir, payload, ts,
                               filename=filename_for(book), event_type=event_type_for(book))
