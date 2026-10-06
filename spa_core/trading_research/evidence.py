"""Forward-paper EVIDENCE store — append-only, hash-chained, versioned by candidate identity.

Rules enforced by the database itself, not by convention:
  * no UPDATE and no DELETE on any evidence table (SQLite triggers abort the statement);
  * one observation per (candidate, bar) — a re-run of the same tick inserts nothing;
  * every row carries prev_hash/hash; `verify()` recomputes every chain;
  * a candidate is registered once with its full definition and def_hash — a changed strategy has a
    different id, so it starts a NEW history and never rewrites the old one.

Observation = what the paper book knew and did at one CLOSED bar:
  the fill of the order decided at the previous bar (at this bar's open, with cost), the bar's
  mark-to-market (+ funding for the perpetual model), the new target decided on this bar's close,
  the market-data reference it was computed from, and the code identity that computed it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

GENESIS = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY, def_hash TEXT NOT NULL, definition TEXT NOT NULL,
  registered_at_ms INTEGER NOT NULL, code_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL, asset TEXT NOT NULL, timeframe TEXT NOT NULL,
  bar_open_time INTEGER NOT NULL, bar_close_time INTEGER NOT NULL,
  signal_ts_ms INTEGER NOT NULL, late INTEGER NOT NULL, gap_bars INTEGER NOT NULL,
  bar_open REAL NOT NULL, bar_close REAL NOT NULL,
  position_before INTEGER NOT NULL, fill_price REAL, fill_cost REAL NOT NULL, funding REAL NOT NULL,
  position_held INTEGER NOT NULL, equity REAL NOT NULL, target INTEGER NOT NULL, action TEXT NOT NULL,
  closed_trade TEXT, book_state TEXT NOT NULL, assumptions TEXT NOT NULL, data_ref TEXT NOT NULL,
  code_version TEXT NOT NULL,
  release TEXT, prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  UNIQUE (candidate_id, bar_open_time)
);
CREATE TABLE IF NOT EXISTS lifecycle_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT NOT NULL, from_stage TEXT, to_stage TEXT NOT NULL,
  reason TEXT NOT NULL, evidence TEXT NOT NULL, actor TEXT NOT NULL, ts_ms INTEGER NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticks (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, started_ms INTEGER NOT NULL, finished_ms INTEGER NOT NULL,
  new_bars INTEGER NOT NULL, new_observations INTEGER NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL,
  code_version TEXT NOT NULL
);
"""
_IMMUTABLE = ("candidates", "observations", "lifecycle_events", "ticks")


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.executescript(SCHEMA)
    for t in _IMMUTABLE:
        conn.executescript(
            f"CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t} "
            f"BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;"
            f"CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t} "
            f"BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;")
    return conn


def _hash(prev: str, payload: Dict) -> str:
    return hashlib.sha256((prev + json.dumps(payload, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


OBS_FIELDS = ("candidate_id", "asset", "timeframe", "bar_open_time", "bar_close_time", "signal_ts_ms", "late",
              "gap_bars", "bar_open", "bar_close", "position_before", "fill_price", "fill_cost", "funding",
              "position_held", "equity", "target", "action", "closed_trade", "book_state", "assumptions", "data_ref",
              "code_version", "release")


def register(conn, cand_id: str, def_hash: str, definition: Dict, *, now_ms: int, code_version: str) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?)",
                       (cand_id, def_hash, json.dumps(definition, sort_keys=True), now_ms, code_version))
    return cur.rowcount == 1


def registered(conn) -> Dict[str, Dict]:
    return {r[0]: {"def_hash": r[1], "definition": json.loads(r[2]), "registered_at_ms": r[3], "code_version": r[4]}
            for r in conn.execute("SELECT * FROM candidates")}


def observation_count(conn, cand_id: str) -> int:
    """True forward-observation count — COUNT(*) of real rows, never `len(eq)` of a metrics series
    that prepends a synthetic seed point (RM-TRUTH-01 C1 D1: the seed makes every `forward_bars`
    value published by forward.forward_metrics() off by +1). This is the one place both the
    producer (forward.write_status) and any reader are meant to get the count from."""
    row = conn.execute("SELECT COUNT(*) FROM observations WHERE candidate_id=?", (cand_id,)).fetchone()
    return row[0] if row else 0


def last_observation(conn, cand_id: str) -> Optional[Dict]:
    cols = ["seq"] + list(OBS_FIELDS) + ["prev_hash", "hash"]
    r = conn.execute(f"SELECT {','.join(cols)} FROM observations WHERE candidate_id=? ORDER BY bar_open_time DESC LIMIT 1",
                     (cand_id,)).fetchone()
    return dict(zip(cols, r)) if r else None


def append_observation(conn, obs: Dict) -> bool:
    """Insert one observation, chained to the candidate's previous one. False if it already exists."""
    last = last_observation(conn, obs["candidate_id"])
    if last and obs["bar_open_time"] <= last["bar_open_time"]:
        return False                                     # never write into the past
    payload = {k: obs.get(k) for k in OBS_FIELDS}
    prev = last["hash"] if last else GENESIS
    h = _hash(prev, payload)
    cur = conn.execute(f"INSERT OR IGNORE INTO observations ({','.join(OBS_FIELDS)},prev_hash,hash) "
                       f"VALUES ({','.join('?' * (len(OBS_FIELDS) + 2))})",
                       [payload[k] for k in OBS_FIELDS] + [prev, h])
    return cur.rowcount == 1


def append_event(conn, cand_id: str, from_stage: Optional[str], to_stage: str, reason: str,
                 evidence: Dict, *, actor: str, now_ms: int) -> None:
    last = conn.execute("SELECT hash FROM lifecycle_events WHERE candidate_id=? ORDER BY seq DESC LIMIT 1",
                        (cand_id,)).fetchone()
    prev = last[0] if last else GENESIS
    payload = {"candidate_id": cand_id, "from_stage": from_stage, "to_stage": to_stage, "reason": reason,
               "evidence": evidence, "actor": actor, "ts_ms": now_ms}
    conn.execute("INSERT INTO lifecycle_events (candidate_id,from_stage,to_stage,reason,evidence,actor,ts_ms,"
                 "prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?)",
                 (cand_id, from_stage, to_stage, reason, json.dumps(evidence, sort_keys=True), actor, now_ms,
                  prev, _hash(prev, payload)))


def current_stages(conn) -> Dict[str, str]:
    out = {}
    for cid, stage in conn.execute("SELECT candidate_id, to_stage FROM lifecycle_events ORDER BY seq"):
        out[cid] = stage
    return out


def record_tick(conn, *, started_ms: int, finished_ms: int, new_bars: int, new_obs: int, ok: bool,
                detail: Dict, code_version: str) -> None:
    conn.execute("INSERT INTO ticks (started_ms,finished_ms,new_bars,new_observations,ok,detail,code_version) "
                 "VALUES (?,?,?,?,?,?,?)", (started_ms, finished_ms, new_bars, new_obs, int(ok),
                                             json.dumps(detail, sort_keys=True), code_version))


def verify(conn) -> Dict:
    """Recompute every hash chain. Any break is named; nothing is repaired."""
    breaks: List[str] = []
    n = 0
    cols = list(OBS_FIELDS) + ["prev_hash", "hash"]
    prev_by: Dict[str, tuple] = {}
    for row in conn.execute(f"SELECT {','.join(cols)} FROM observations ORDER BY candidate_id, bar_open_time"):
        d = dict(zip(cols, row))
        n += 1
        cid = d["candidate_id"]
        want_prev, last_t = prev_by.get(cid, (GENESIS, None))
        if d["prev_hash"] != want_prev or _hash(d["prev_hash"], {k: d[k] for k in OBS_FIELDS}) != d["hash"]:
            breaks.append(f"observation {cid}@{d['bar_open_time']}")
        prev_by[cid] = (d["hash"], d["bar_open_time"])
    ev_prev: Dict[str, str] = {}
    for row in conn.execute("SELECT candidate_id,from_stage,to_stage,reason,evidence,actor,ts_ms,prev_hash,hash "
                            "FROM lifecycle_events ORDER BY seq"):
        cid = row[0]
        payload = {"candidate_id": cid, "from_stage": row[1], "to_stage": row[2], "reason": row[3],
                   "evidence": json.loads(row[4]), "actor": row[5], "ts_ms": row[6]}
        if row[7] != ev_prev.get(cid, GENESIS) or _hash(row[7], payload) != row[8]:
            breaks.append(f"lifecycle {cid}@{row[6]}")
        ev_prev[cid] = row[8]
    return {"observations": n, "chains": len(prev_by), "breaks": breaks, "ok": not breaks}
