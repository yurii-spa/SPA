#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.cycle_inputs_archive — append-only, hash-chained archive of the INPUTS the daily
cycle used to accrue yield (inbox «Целостность трека SPA», task 3; practice transferred from
earn-defi, 2026-09-08).

WHY
===
Measured 2026-09-08 (journal 2026-W37): the equity bar is internally consistent
(``daily_yield_usd == open_equity × apy_today / 365`` to 0.2 cents) but the per-pool ``apy_map``
the cycle actually accrued with is stored NOWHERE — ``apy_series_daily.json`` lacks pools
(``fluid_usdc``) and keeps one value per day while the cycle can run twice. So the curve could not be
re-derived from stored inputs (diffs −0.17…+0.56 USD/day). Without the inputs, "verify the equity
track yourself" is a claim, not a command.

WHAT
====
One record per cycle run, written right after ``_upsert_equity_point`` from the SAME variables
the accrual used (positions, apy_map, accrual_source, open/close of the bar). Chained with the
canonical ``compute_entry_hash`` of ``spa_core.audit.hash_chain`` (seq, ts, event_type, payload,
prev_hash). File: ``data/cycle_inputs.jsonl``. Re-runs of the same date are kept (a run is a fact);
``replay_equity`` uses the last record per date and reports runs per date.

RULES
=====
Read-only for everything else in the tree; never raises into the cycle (the caller wraps it);
stdlib only; atomic rewrite (tmp + os.replace) like ``hash_chain._atomic_write_all``; history is
never rewritten — a wrong record is followed by a correcting one, not edited.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from spa_core.audit.hash_chain import compute_entry_hash

FILENAME = "cycle_inputs.jsonl"
EVENT_TYPE = "cycle_inputs"
GENESIS = "0" * 64
SCHEMA_VERSION = "1.0"


def path_for(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / FILENAME


def read_all(data_dir: str | os.PathLike) -> list[dict]:
    p = path_for(data_dir)
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_corrupt": line[:120]})
    return out


def _atomic_write_lines(p: Path, lines: list[str]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cycle_inputs.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build_record(
    *,
    cycle_date: str,
    run_ts: str,
    open_equity: float,
    close_equity: float,
    daily_yield_usd: float,
    apy_today_pct: float,
    positions: dict[str, float],
    apy_map: dict[str, Any],
    fallback_pools: list[str],
    accrual_source: str,
    snapshot_id: Optional[str] = None,
    risk_policy_version: str = "v1.0",
) -> dict:
    """The payload — only what the accrual needs to be re-derived, plus what the bar wrote."""
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_date": cycle_date,
        "run_ts": run_ts,
        "snapshot_id": snapshot_id,
        "open_equity": round(float(open_equity), 4),
        "positions": {k: round(float(v), 4) for k, v in positions.items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)},
        # verbatim: the replay must see the same values the accrual saw (incl. None / junk that
        # _normalize_accrual_apy rejected) — no cleaning here, or the replay proves a cleaner input
        "apy_map": {k: apy_map.get(k) for k in positions},
        "fallback_pools": sorted(fallback_pools),
        "accrual_source": accrual_source,
        "apy_today_pct": round(float(apy_today_pct), 6),
        "daily_yield_usd": round(float(daily_yield_usd), 6),
        "close_equity": round(float(close_equity), 4),
        "risk_policy_version": risk_policy_version,
    }


def append_record(data_dir: str | os.PathLike, payload: dict, ts: str) -> dict:
    """Append one chained entry and return it. Whole-file atomic rewrite (the file is ~1 row/day)."""
    entries = read_all(data_dir)
    good = [e for e in entries if "entry_hash" in e]
    seq = (good[-1]["seq"] + 1) if good else 0
    prev = good[-1]["entry_hash"] if good else GENESIS
    entry = {"seq": seq, "ts": ts, "event_type": EVENT_TYPE, "payload": payload, "prev_hash": prev}
    entry["entry_hash"] = compute_entry_hash(seq, ts, EVENT_TYPE, payload, prev)
    lines = [json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
             for e in entries if "_corrupt" not in e]
    lines.append(json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    _atomic_write_lines(path_for(data_dir), lines)
    return entry


def verify(data_dir: str | os.PathLike) -> dict:
    """Recompute every hash in order. {ok, entries, broken_at, reason}."""
    entries = read_all(data_dir)
    prev = GENESIS
    for i, e in enumerate(entries):
        if "_corrupt" in e:
            return {"ok": False, "entries": len(entries), "broken_at": i, "reason": "corrupt line"}
        if e.get("prev_hash") != prev or e.get("seq") != i:
            return {"ok": False, "entries": len(entries), "broken_at": i, "reason": "chain broken (prev_hash/seq)"}
        if compute_entry_hash(e["seq"], e["ts"], e["event_type"], e["payload"], e["prev_hash"]) != e.get("entry_hash"):
            return {"ok": False, "entries": len(entries), "broken_at": i, "reason": "entry_hash mismatch (payload altered)"}
        prev = e["entry_hash"]
    return {"ok": True, "entries": len(entries), "broken_at": None, "reason": None}
