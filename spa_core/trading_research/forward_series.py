"""Отдельная forward-серия research-модели со СВОЕЙ датой регистрации (S3 E6.6, вариант «а» решения ARB) — ПОДГОТОВКА.

Серия не запускается этим модулем сама: её запуск — первый ``tick`` в боевом каталоге, а это решение ARB/владельца
(изменение расписания агента). Здесь — всё, что нужно, чтобы запуск был одной командой и не мог переписать прошлое:

* **Своя дата.** Первая строка журнала — ``registration`` с моментом запуска; бары, открывшиеся РАНЬШЕ, в серию не
  попадают никогда (не бэкфилл, не replay прошлого).
* **Контроль не переписывается.** Контроль — существующий forward-кандидат живого движка (``control_id`` контракта);
  серия его только ЧИТАЕТ для сравнения. Свой журнал — отдельный файл в своём каталоге.
* **Неизменяемость.** На каждом такте серия детерминированно пересчитывается с регистрации; уже записанные строки
  сверяются с пересчётом. Расхождение (например, пересмотренная свеча) — ОТКАЗ ``REFUSED_HISTORY_MISMATCH``, а не
  перезапись. Журнал — только дописывание, цепочка хешей.
* **Опоздание видно.** Строка, записанная позже ``close + LATE_AFTER_MS``, помечена ``late``.
* **Аудит** — ожидаемые бары от регистрации до последнего закрытого против записанных: пропуски, опоздания, разрывы
  цепочки (третий исход — нечитаемый журнал — ``UNKNOWN``).

Только stdlib; LLM запрещён; рыночная база открывается только на чтение.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import market_data as md
from .execution import EXEC_MODELS
from .sizing_experiment import MODEL_ID, simulate_frac
from .strategies import by_id

LEDGER = "series.jsonl"
LATE_AFTER_MS = 2 * 3_600_000
SYMBOL = "BTCUSDT"


class SeriesRefused(Exception):
    pass


def _h(prev: str, row: Dict[str, Any]) -> str:
    body = json.dumps({k: v for k, v in row.items() if k != "hash"}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def read_ledger(series_dir: Path) -> List[Dict[str, Any]]:
    p = Path(series_dir) / LEDGER
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(series_dir: Path, rows: List[Dict[str, Any]]) -> None:
    p = Path(series_dir) / LEDGER
    with open(p, "a", encoding="utf-8") as fh:          # дописывание; файл никогда не переписывается целиком
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def verify_chain(rows: List[Dict[str, Any]]) -> Optional[str]:
    prev = ""
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev or r.get("hash") != _h(prev, r):
            return f"цепочка разорвана на строке {i}"
        prev = r["hash"]
    return None


def _compute(contract: Dict[str, Any], market_db: Path, registered_ms: int, now_ms: int) -> List[Dict[str, Any]]:
    cand = by_id().get(contract["control_id"])
    if cand is None or cand.def_hash != contract["control_def_hash"]:
        raise SeriesRefused("сигнал контроля не найден или его определение изменилось (def_hash) — серия не считается")
    from .read_model import open_ro
    conn = open_ro(market_db)
    try:
        bars = md.aggregate(md.load_1h(conn, SYMBOL), cand.timeframe)
    finally:
        conn.close()
    tf_ms = md.TF_MS[cand.timeframe]
    closed = [b for b in bars if b.open_time + tf_ms + md.CLOSE_GRACE_MS <= now_ms]
    first = next((i for i, b in enumerate(closed) if b.open_time >= registered_ms), None)
    if first is None or first == 0:
        return []
    targets = cand.signal(closed)
    sl_bars, sl_t = closed[first - 1:], list(targets[first - 1:])
    res = simulate_frac(sl_bars, sl_t, k=contract["k"], band=contract["band"],
                        cost_per_side=EXEC_MODELS[cand.exec_model].cost_per_side)
    out = []
    for j in range(1, len(sl_bars)):
        b = sl_bars[j]
        out.append({"kind": "bar", "bar_open_ms": b.open_time, "bar_close_ms": b.open_time + tf_ms,
                    "open": b.open, "close": b.close, "target_prev": sl_t[j - 1],
                    "equity": round(res.equity[j], 10)})
    return out


def tick(series_dir: Path, contract: Dict[str, Any], market_db: Path, *, now_ms: int) -> Dict[str, Any]:
    """Один такт серии. Первый такт в пустом каталоге — РЕГИСТРАЦИЯ (собственная дата = ``now_ms``)."""
    series_dir = Path(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
    rows = read_ledger(series_dir)
    if rows:
        broken = verify_chain(rows)
        if broken:
            raise SeriesRefused(f"журнал серии повреждён: {broken}")
    if not rows:
        reg = {"kind": "registration", "series_id": contract["series_id"], "model": MODEL_ID,
               "k": contract["k"], "band": contract["band"], "control_id": contract["control_id"],
               "registered_at_ms": now_ms, "prev_hash": ""}
        reg["hash"] = _h("", reg)
        _append(series_dir, [reg])
        return {"state": "REGISTERED", "registered_at_ms": now_ms, "new_bars": 0}
    reg = rows[0]
    if reg.get("series_id") != contract["series_id"] or reg.get("k") != contract["k"] or reg.get("band") != contract["band"]:
        raise SeriesRefused("контракт не совпадает с регистрацией серии — сменить параметры = новая серия, не правка")
    recorded = [r for r in rows if r.get("kind") == "bar"]
    fresh = _compute(contract, market_db, reg["registered_at_ms"], now_ms)
    for old, new in zip(recorded, fresh):
        if any(old.get(k) != new.get(k) for k in ("bar_open_ms", "open", "close", "target_prev", "equity")):
            raise SeriesRefused(f"REFUSED_HISTORY_MISMATCH: пересчёт бара {old['bar_open_ms']} не совпал с записанным — "
                                f"прошлое не переписывается")
    if len(fresh) < len(recorded):
        raise SeriesRefused("REFUSED_HISTORY_MISMATCH: пересчёт короче журнала — данные прошлого исчезли")
    prev = rows[-1]["hash"]
    add = []
    for r in fresh[len(recorded):]:
        r = {**r, "recorded_at_ms": now_ms, "late": now_ms > r["bar_close_ms"] + LATE_AFTER_MS, "prev_hash": prev}
        r["hash"] = _h(prev, r)
        prev = r["hash"]
        add.append(r)
    if add:
        _append(series_dir, add)
    return {"state": "OK", "registered_at_ms": reg["registered_at_ms"], "new_bars": len(add),
            "bars_total": len(recorded) + len(add)}


def audit(series_dir: Path, *, tf_ms: int = 86_400_000, now_ms: int) -> Dict[str, Any]:
    """Непрерывность серии: ожидаемые закрытые бары от регистрации против записанных; опоздания; цепочка."""
    try:
        rows = read_ledger(series_dir)
    except (OSError, ValueError) as exc:
        return {"state": "UNKNOWN", "why": f"журнал не прочитан: {type(exc).__name__}"}
    if not rows:
        return {"state": "UNKNOWN", "why": "серия не зарегистрирована"}
    broken = verify_chain(rows)
    reg = rows[0]["registered_at_ms"]
    first_open = -(-reg // tf_ms) * tf_ms                      # первый бар, открывшийся не раньше регистрации
    expected = max(0, (now_ms - md.CLOSE_GRACE_MS - first_open) // tf_ms)
    bars = [r for r in rows if r.get("kind") == "bar"]
    opens = [r["bar_open_ms"] for r in bars]
    gaps = sum(1 for a, b in zip(opens, opens[1:]) if b - a != tf_ms)
    return {"state": "BROKEN" if broken else "OK", "chain": broken or "цела", "registered_at_ms": reg,
            "expected": expected, "observed": len(bars), "gaps": gaps,
            "late": sum(1 for r in bars if r.get("late")),
            "days_since_registration": round((now_ms - reg) / 86_400_000, 2)}
