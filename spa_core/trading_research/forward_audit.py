"""Сохранность forward-истории за последние N завершённых суток UTC + хвост (S3 E6.6). Только чтение снимков.

По каждому кандидату и дню: сколько закрытых баров ожидалось (по таймфрейму), сколько наблюдений записано, сколько
помечено ``late``, сколько пришло с ``gap_bars>0`` и сколько записано позже срока (``signal_ts_ms`` дальше
``bar_close_time`` более чем на ``late_after_ms`` — запись задним числом, а не в свой тик). Календарные дни и
наблюдённые дни считаются раздельно; свечи рынка за тот же день сверяются отдельно (пропуск свечи ≠ пропуск
наблюдения). Ничего не исправляет и не дописывает."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional

from .market_data import TF_MS

DAY = 86_400_000


def _ro(p: Path) -> sqlite3.Connection:
    from .read_model import open_ro   # одна дверь read-only (migrate_callsites)
    return open_ro(p)


def audit(evidence_db: Path, market_db: Path, *, as_of_ms: int, days: int = 7,
          late_after_ms: int = 2 * 3_600_000) -> Dict[str, Any]:
    end = as_of_ms - as_of_ms % DAY                # начало текущих (незавершённых) суток
    lo = end - days * DAY
    e, m = _ro(evidence_db), _ro(market_db)
    try:
        cands = e.execute("SELECT candidate_id, registered_at_ms FROM candidates").fetchall()
        rows = e.execute("SELECT candidate_id, timeframe, bar_open_time, bar_close_time, signal_ts_ms, late, gap_bars "
                         "FROM observations WHERE bar_close_time > ? AND bar_close_time <= ?", (lo, as_of_ms)).fetchall()
        first_last = {c: (a, z, n) for c, a, z, n in e.execute(
            "SELECT candidate_id, MIN(bar_open_time), MAX(bar_close_time), COUNT(*) FROM observations GROUP BY candidate_id")}
        hours = {r[0] for r in m.execute("SELECT open_time FROM candles WHERE symbol='BTCUSDT' AND tf='1h' "
                                         "AND open_time >= ? AND open_time < ?", (lo, as_of_ms))}
    finally:
        e.close()
        m.close()
    tf_of = {}
    per: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for cid, tf, bo, bc, sig, late, gap in rows:
        tf_of[cid] = tf
        d = per[cid][(bc - 1) // DAY * DAY]
        d["observed"] += 1
        d["late"] += int(bool(late))
        d["gap_flagged"] += int(gap > 0)
        d["recorded_after_deadline"] += int(sig - bc > max(late_after_ms, TF_MS[tf]))   # то же правило, что ``late`` движка
    day_list = [lo + i * DAY for i in range(days)] + [end]          # 7 завершённых + хвост
    market = {}
    for d in day_list:
        exp = sum(1 for h in range(d, d + DAY, 3_600_000) if h + 3_600_000 + 60_000 <= as_of_ms)   # только закрытые часы
        market[d] = {"hours_expected": exp, "hours_present": sum(1 for h in hours if d <= h < d + DAY)}
    out_c = {}
    for cid, reg in cands:
        tf = tf_of.get(cid) or cid.split(":")[2]
        per_day = {}
        for d in day_list:
            closes_upto = min(d + DAY, as_of_ms)
            expected = sum(1 for t in range(d, d + DAY, TF_MS[tf]) if t >= reg and t + TF_MS[tf] <= closes_upto)
            x = per[cid].get(d, {})
            per_day[d] = {"expected": expected, "observed": x.get("observed", 0), "late": x.get("late", 0),
                          "gap_flagged": x.get("gap_flagged", 0),
                          "recorded_after_deadline": x.get("recorded_after_deadline", 0)}
        a, z, n = first_last.get(cid, (None, None, 0))
        out_c[cid] = {"timeframe": tf, "registered_at_ms": reg, "per_day": per_day,
                      "history": {"observations": n, "first_bar_open": a, "last_bar_close": z,
                                  "calendar_days": ((z - reg) / DAY) if z else None,
                                  "observed_days": observed_days(evidence_db, cid)}}
    return {"as_of_ms": as_of_ms, "window": [lo, end], "tail": [end, as_of_ms], "market": market, "candidates": out_c}


def summarize(rep: Dict[str, Any]) -> Dict[str, Any]:
    tot = defaultdict(int)
    short = []
    for cid, c in rep["candidates"].items():
        for d, x in c["per_day"].items():
            tail = d == rep["tail"][0]
            for k in ("expected", "observed", "late", "gap_flagged", "recorded_after_deadline"):
                tot[("tail_" if tail else "") + k] += x[k]
            if x["observed"] < x["expected"]:
                short.append((cid, d, x["expected"], x["observed"]))
    return {"totals": dict(tot), "days_with_missing_observations": short,
            "market_missing_hours": {d: v for d, v in rep["market"].items() if v["hours_present"] < v["hours_expected"]}}


def observed_days(evidence_db: Path, candidate_id: str) -> Optional[int]:
    """Число РАЗНЫХ суток UTC, в которых у кандидата есть хотя бы одно наблюдение (≠ календарные дни)."""
    e = _ro(evidence_db)
    try:
        r = e.execute("SELECT COUNT(DISTINCT (bar_close_time - 1) / 86400000) FROM observations WHERE candidate_id=?",
                      (candidate_id,)).fetchone()
    finally:
        e.close()
    return r[0] if r else None
