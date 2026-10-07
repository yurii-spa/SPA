"""Trading Alpha sleeve — the canonical Trading Lab seen as ONE isolated PAPER return source (ADR-640).

CAPITAL-SOURCES-01 (owner directive 2026-10-07). The question this module answers:

    "If Trading Alpha had been allocated an isolated paper capital account according to rules known at that
     time, what would its portfolio result have been?"

It is a DERIVED, read-only layer over the ADR-525 engine's own evidence store (`evidence.db`). It is not a
second Trading Lab: it registers nothing, runs no strategy, writes nothing. Everything is rebuilt from the
immutable, hash-chained rows — never from `status.json`, which is a mutable derived file.

Causality (the rule this module exists to keep — ADR-640 §temporal admission):
  * membership at time T = replay of `lifecycle_events` with an effective time ≤ T. An event's effective time
    is its own `ts_ms`, but never earlier than any event written before it (a BACKDATED row — `ts_ms` smaller
    than an earlier `seq` — takes effect only from the moment it could have been known, and is flagged);
  * an observation counts at T only when its bar has closed (`bar_close_time ≤ T`) AND it had been recorded
    (`signal_ts_ms ≤ T`);
  * clusters (duplicate members) are formed from observations ≤ the clustering instant;
  * nothing reads today's ranking, forward winners, `status.json` or a later backtest.

Weighting: equal weight across CLUSTERS of active members, equal within a cluster. Rebalanced ONLY when the
membership or the cluster partition changes (re-clustering is evaluated at each UTC day boundary with the
data available then); between rebalances each member's capital drifts with its own forward equity. Rebalance
trading costs are not modelled (named as a cost blocker, never silently zero).

Returns are FORWARD_PAPER only. BACKTEST/OOS numbers never enter this sleeve. No annualisation, volatility,
Sharpe or Sortino below 30 calendar days of sleeve evidence (ADR-590 §4) — those cells are NOT_ENOUGH_HISTORY.

# LLM_FORBIDDEN — deterministic and reproducible: the same evidence and the same `as_of_ms` give the same bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import evidence as ev
from . import lifecycle as lc
from .metrics import correlation

SCHEMA = "trading-alpha-sleeve/1"
SOURCE_ID = "trading_alpha"
SOURCE_TYPE = "TRADING_ALPHA"
CAPITAL_MODE = "PAPER"
MODE = "FORWARD_PAPER"                       # the ONLY evidence class inside this sleeve
SLEEVE_STAGES = ("FORWARD_PAPER", "ROBUST", "CHAMPION_CANDIDATE", "SHADOW")   # paper stages only
CHAMPION_STAGES = ("CHAMPION_CANDIDATE", "SHADOW")
MIN_CALENDAR_DAYS_FOR_RATE = 30              # ADR-590 §4 — no annualised figure below this
MIN_DUPLICATE_BARS = 3                       # an identical path on fewer bars is not yet evidence of identity
STALE_AFTER_H = 2.0                          # = read_model.STALE_AFTER_H (the engine ticks every 15 min)
CORR_MIN_OVERLAP_DAYS = 30                   # = Oracle POLICY correlation_min_overlap_days (ADR-554)
CORR_CLUSTER_THRESHOLD = 0.85                # = ranking.THRESHOLDS["dedupe_corr"] — the Lab's own duplicate bar
ROBUST_MIN_WEIGHT_SHARE = 0.5                # uncalibrated v1: at least half the sleeve in forward-robust members
DAY_MS = 86_400_000
WEIGHTING = ("equal weight across clusters of active members, equal within a cluster; rebalanced only on a "
             "membership or cluster-partition change; capital drifts with each member's forward equity between")

#: Execution-cost realism (epic §7). KNOWN = carried by the engine's recorded `assumptions` per observation;
#: everything else is UNKNOWN today and blocks allocation eligibility — never assumed to be zero.
COST_COMPONENTS = {
    "taker_fee": "KNOWN",           # fee_bps per side, recorded in every observation
    "slippage": "KNOWN",            # slippage_bps per side (spread folded in — see below)
    "funding": "KNOWN",             # perp models only, from the public funding history
    "maker_fee": "UNKNOWN",         # the model fills as taker only
    "spread": "UNKNOWN",            # folded into the flat slippage figure, not modelled separately
    "latency": "UNKNOWN",           # fill at the next bar's open; no latency model
    "partial_fills": "UNKNOWN",     # full fill assumed
    "min_trade_size": "UNKNOWN",    # not modelled
    "capacity": "UNKNOWN",          # no market-impact / capacity model
    "perp_mark_basis": "UNKNOWN",   # perp positions priced on SPOT candles + perp funding; mark/basis ignored
    "rebalance_costs": "UNKNOWN",   # sleeve-level rebalance trades are not charged
}


class SleeveRefused(Exception):
    """The evidence cannot support a sleeve — refuse (fail-CLOSED), never produce numbers."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ── cells (invariant #17: absence is its own value) ─────────────────────────────────────────────────────────
def _m(value, *, unit: Optional[str], n: Optional[int] = None, note: Optional[str] = None,
       evidence_class: str = MODE) -> Dict:
    return {"state": "MEASURED", "value": value, "unit": unit, "n": n, "evidence_class": evidence_class,
            "note": note}


def _a(state: str, reason: str, n: Optional[int] = None) -> Dict:
    return {"state": state, "value": None, "unit": None, "n": n, "reason": reason}


def _r(x: float, nd: int = 10) -> float:
    return round(float(x), nd)


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── evidence access ───────────────────────────────────────────────────────────────────────────────────────
def open_readonly(path: Path) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise SleeveRefused("NOT_MEASURED", f"evidence.db not found at {p}")
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)


def _events(conn) -> List[Dict]:
    rows = conn.execute("SELECT seq, candidate_id, from_stage, to_stage, evidence, ts_ms FROM lifecycle_events "
                        "ORDER BY seq").fetchall()
    out, running_max = [], None
    for seq, cid, frm, to, evidence, ts in rows:
        backdated = running_max is not None and ts < running_max
        eff = ts if running_max is None else max(ts, running_max)
        running_max = eff
        try:
            evd = json.loads(evidence) if evidence else {}
        except ValueError:
            evd = {}
        out.append({"seq": seq, "candidate_id": cid, "from": frm, "to": to, "ts_ms": ts, "effective_ms": eff,
                    "backdated": backdated, "evidence": evd if isinstance(evd, dict) else {}})
    return out


def _candidates(conn) -> Dict[str, Dict]:
    out = {}
    for cid, definition, reg, code in conn.execute(
            "SELECT candidate_id, definition, registered_at_ms, code_version FROM candidates"):
        try:
            d = json.loads(definition)
        except ValueError:
            d = {}
        out[cid] = {"definition": d if isinstance(d, dict) else {}, "registered_at_ms": reg, "code_version": code}
    return out


def _observations(conn, ids: List[str], as_of_ms: int) -> Dict[str, List[Dict]]:
    """Full per-candidate chains up to the knowable instant (bar closed AND recorded by `as_of_ms`)."""
    out: Dict[str, List[Dict]] = {cid: [] for cid in ids}
    if not ids:
        return out
    q = ("SELECT candidate_id, bar_open_time, bar_close_time, signal_ts_ms, position_held, equity, fill_cost, "
         "funding, action, closed_trade, book_state, assumptions, timeframe FROM observations "
         f"WHERE candidate_id IN ({','.join('?' * len(ids))}) AND bar_close_time <= ? AND signal_ts_ms <= ? "
         "ORDER BY candidate_id, bar_open_time")
    for r in conn.execute(q, list(ids) + [as_of_ms, as_of_ms]):
        try:
            bs = json.loads(r[10]) if r[10] else {}
            asm = json.loads(r[11]) if r[11] else {}
        except ValueError:
            bs, asm = {}, {}
        out[r[0]].append({"open": r[1], "close": r[2], "signal": r[3], "pos": r[4], "equity": r[5],
                          "cost": r[6], "funding": r[7], "action": r[8], "trade": r[9], "book": bs,
                          "assumptions": asm, "tf": r[12]})
    return out


def _evidence_digest(conn, as_of_ms: int) -> str:
    """Fingerprint of exactly the rows this build may read (chain heads ≤ as_of + every effective event)."""
    h = hashlib.sha256()
    for cid, hsh in conn.execute(
            "SELECT o.candidate_id, o.hash FROM observations o JOIN (SELECT candidate_id, MAX(bar_open_time) AS t "
            "FROM observations WHERE bar_close_time <= ? AND signal_ts_ms <= ? GROUP BY candidate_id) m "
            "ON o.candidate_id = m.candidate_id AND o.bar_open_time = m.t ORDER BY o.candidate_id",
            (as_of_ms, as_of_ms)):
        h.update(f"{cid}:{hsh}\n".encode())
    for e in _events(conn):
        if e["effective_ms"] <= as_of_ms:
            h.update(f"e{e['seq']}:{e['to']}:{e['effective_ms']}\n".encode())
    return h.hexdigest()


# ── membership & clusters ─────────────────────────────────────────────────────────────────────────────────
def _stage_at(events_by_cand: Dict[str, List[Dict]], cid: str, t: int) -> Optional[str]:
    st = None
    for e in events_by_cand.get(cid, ()):
        if e["effective_ms"] <= t:
            st = e["to"]
        else:
            break
    return st


def _episode(events_by_cand: Dict[str, List[Dict]], cid: str, t: int) -> Optional[Dict]:
    """The CURRENT admission episode at t: the latest event ≤ t that moved the candidate INTO a sleeve stage
    from outside, provided it is still inside at t. A rejection ends the episode; a re-admission opens a new
    one — its window and policy are the new episode's, never the first admission's (review P2-5)."""
    cur, start = None, None
    for e in events_by_cand.get(cid, ()):
        if e["effective_ms"] > t:
            break
        if e["to"] in SLEEVE_STAGES and cur not in SLEEVE_STAGES:
            start = e
        elif e["to"] not in SLEEVE_STAGES:
            start = None
        cur = e["to"]
    return start


def _episodes_count(events_by_cand: Dict[str, List[Dict]], cid: str, t: int) -> int:
    n, cur = 0, None
    for e in events_by_cand.get(cid, ()):
        if e["effective_ms"] > t:
            break
        if e["to"] in SLEEVE_STAGES and cur not in SLEEVE_STAGES:
            n += 1
        cur = e["to"]
    return n


def _admission_policy(e: Dict, cand: Dict) -> str:
    v = e.get("evidence", {}).get("admission_policy_version")
    if isinstance(v, str) and v:
        return v
    return f"reconstructed:{cand.get('code_version')} (admission policy unversioned at the time)"


def _window_rows(obs: Dict[str, List[Dict]], m: str, start: int, t: int) -> List[Dict]:
    return [o for o in obs.get(m, ()) if o["open"] >= start and o["close"] <= t and o["signal"] <= t]


def _daily_net(obs: Dict[str, List[Dict]], m: str, start: int, t: int) -> Dict[int, float]:
    """{UTC day index: net return of that day} for member m inside its episode, from observations closed AND
    recorded by t. Day-end equity = last observation closed by the day's end."""
    chain = [o for o in obs.get(m, ()) if o["close"] <= t and o["signal"] <= t]
    before = [o for o in chain if o["close"] <= start]
    prev = before[-1]["equity"] if before else 1.0
    rows = [o for o in chain if o["open"] >= start]
    ends: Dict[int, float] = {}
    for o in rows:
        ends[(o["close"] - 1) // DAY_MS] = o["equity"]
    out: Dict[int, float] = {}
    for d in sorted(ends):
        if prev > 0:
            out[d] = ends[d] / prev - 1.0
        prev = ends[d]
    return out


def _corr_state(members: List[str], obs: Dict[str, List[Dict]], since: Dict[str, int], t: int) -> Dict:
    """Pairwise forward correlation of daily net returns, only on ≥CORR_MIN_OVERLAP_DAYS shared days."""
    series = {m: _daily_net(obs, m, since[m], t) for m in members}
    pairs, measured, undefined = {}, 0, 0
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            shared = len(set(series[a]) & set(series[b]))
            c = correlation(series[a], series[b]) if shared >= CORR_MIN_OVERLAP_DAYS else None
            if shared < CORR_MIN_OVERLAP_DAYS:
                state = "NOT_ENOUGH_HISTORY"
            elif c is None:
                state = "UNDEFINED"            # enough days but a constant series: independence cannot be judged
                undefined += 1
            else:
                state = "MEASURED"
                measured += 1
            pairs[f"{a}|{b}"] = {"overlap_days": shared, "state": state,
                                 "correlation": None if c is None else round(c, 6)}
    return {"pairs": pairs, "pairs_total": len(pairs), "pairs_measured": measured, "pairs_undefined": undefined}


def _clusters(members: List[str], obs: Dict[str, List[Dict]], since: Dict[str, int], t: int) -> List[List[str]]:
    """Clusters from observations closed and recorded ≤ t, inside each member's current episode.
    1. EXACT duplicates (any length): same timeframe and the identical (bar, position, equity) path, with at least
       MIN_DUPLICATE_BARS bars IN A POSITION (a common flat stretch is not identity).
    2. NEAR duplicates: daily net returns correlated ≥ CORR_CLUSTER_THRESHOLD over ≥ CORR_MIN_OVERLAP_DAYS shared
       days. Before that much overlap exists the pair is NOT judged (and the sleeve says so — see
       correlation_state and the eligibility blocker), never assumed independent."""
    parent = {m: m for m in members}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    sig: Dict[str, Tuple] = {}
    for m in members:
        rows = _window_rows(obs, m, since[m], t)
        # identity needs INFORMATIVE bars: two members that were merely flat together share no position,
        # and calling them one cluster would merge (then split) them on noise (found on the real ledger 07.10)
        if sum(1 for o in rows if o["pos"] != 0) >= MIN_DUPLICATE_BARS:
            sig[m] = (rows[0]["tf"],) + tuple((o["open"], o["pos"], round(o["equity"], 10)) for o in rows)
    by_sig: Dict[Any, List[str]] = defaultdict(list)
    for m in sorted(sig):
        by_sig[sig[m]].append(m)
    for g in by_sig.values():
        for m in g[1:]:
            union(g[0], m)
    cs = _corr_state(sorted(members), obs, since, t)
    for key, v in cs["pairs"].items():
        if v["correlation"] is not None and v["correlation"] >= CORR_CLUSTER_THRESHOLD:
            a, b = key.split("|")
            union(a, b)
    groups: Dict[str, List[str]] = defaultdict(list)
    for m in sorted(members):
        groups[find(m)].append(m)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


# ── the sleeve ────────────────────────────────────────────────────────────────────────────────────────────
def build(conn, *, as_of_ms: int, now_ms: Optional[int] = None, previous: Optional[Dict] = None,
          evidence_path: Optional[str] = None) -> Dict:
    """The sleeve as knowable at `as_of_ms`. `previous` = an earlier output of this function (any as_of):
    a moved forward clock or fewer rows than it saw is a reset/reseed and is REFUSED.
    Raises SleeveRefused on corrupt evidence, a live stage, or a detected reset."""
    now_ms = as_of_ms if now_ms is None else now_ms
    integrity = ev.verify(conn)
    if not integrity["ok"]:
        raise SleeveRefused("CORRUPT_LEDGER", f"hash chain breaks: {integrity['breaks'][:5]}")

    cands = _candidates(conn)
    events = _events(conn)
    live = [e for e in events if e["to"] in lc.FORBIDDEN_TARGETS]
    if live:
        raise SleeveRefused("LIVE_STAGE_PRESENT",
                            f"{live[0]['candidate_id']} → {live[0]['to']}: real-capital stage in a PAPER sleeve")
    forward_start = min((c["registered_at_ms"] for c in cands.values()), default=None)
    counts = {
        "candidates": sum(1 for c in cands.values() if c["registered_at_ms"] <= as_of_ms),
        "events_effective": sum(1 for e in events if e["effective_ms"] <= as_of_ms),
        "observations": conn.execute("SELECT COUNT(*) FROM observations WHERE bar_close_time <= ? AND "
                                     "signal_ts_ms <= ?", (as_of_ms, as_of_ms)).fetchone()[0],
    }
    if previous:
        pv = previous.get("provenance") or {}
        if pv.get("forward_start_ms") is not None and pv.get("forward_start_ms") != forward_start:
            raise SleeveRefused("RESET_DETECTED", f"forward clock moved {pv.get('forward_start_ms')} → {forward_start}")
        if (pv.get("as_of_ms") or 0) <= as_of_ms:
            for k, v in (pv.get("counts") or {}).items():
                if isinstance(v, int) and counts.get(k, 0) < v:
                    raise SleeveRefused("RESET_DETECTED", f"{k} decreased {v} → {counts.get(k)} (history rewritten?)")

    anomalies: List[Dict] = []
    by_cand: Dict[str, List[Dict]] = defaultdict(list)
    for e in events:
        by_cand[e["candidate_id"]].append(e)
        if e["backdated"]:
            anomalies.append({"kind": "BACKDATED_EVENT", "candidate_id": e["candidate_id"], "seq": e["seq"],
                              "ts": _iso(e["ts_ms"]), "effective": _iso(e["effective_ms"]),
                              "note": "applied from the moment it could have been known, never retroactively"})
        if e["candidate_id"] not in cands:
            anomalies.append({"kind": "EVENT_FOR_UNREGISTERED_CANDIDATE", "candidate_id": e["candidate_id"],
                              "seq": e["seq"]})
        elif e["to"] in SLEEVE_STAGES and e["effective_ms"] < cands[e["candidate_id"]]["registered_at_ms"]:
            anomalies.append({"kind": "ADMISSION_BEFORE_REGISTRATION", "candidate_id": e["candidate_id"],
                              "seq": e["seq"]})

    # membership change instants (≤ as_of)
    change_ts = sorted({e["effective_ms"] for e in events if e["effective_ms"] <= as_of_ms
                        and (e["to"] in SLEEVE_STAGES or e["from"] in SLEEVE_STAGES)})
    ever_members = sorted({e["candidate_id"] for e in events if e["to"] in SLEEVE_STAGES
                           and e["effective_ms"] <= as_of_ms and e["candidate_id"] in cands})
    obs = _observations(conn, ever_members, as_of_ms)

    def members_at(t: int) -> List[str]:
        return sorted(m for m in ever_members if _stage_at(by_cand, m, t) in SLEEVE_STAGES)

    def since_at(t: int, ms: List[str]) -> Dict[str, int]:
        """Each member's CURRENT episode start at t (review P2-5: never the first admission)."""
        return {m: _episode(by_cand, m, t)["effective_ms"] for m in ms}

    base = _base_doc(as_of_ms, now_ms, forward_start, counts, evidence_path, conn, cands, by_cand, anomalies)
    if not change_ts or not ever_members:
        base["nav"] = _a("NOT_MEASURED", "no candidate has ever been admitted to a sleeve stage by this instant")
        return _finish(base, None)

    inception = change_ts[0]
    # timeline: membership changes, UTC day boundaries (re-cluster), and every member observation
    timeline: List[Tuple[int, int, Any]] = []
    for t in change_ts:
        timeline.append((t, 0, "membership"))
    d = (inception // DAY_MS + 1) * DAY_MS
    while d <= as_of_ms:
        timeline.append((d, 1, "recluster"))
        d += DAY_MS
    prev_eq: Dict[str, float] = {}
    for m in ever_members:
        last = 1.0                                   # every forward chain starts at unit equity, flat
        for o in obs[m]:
            timeline.append((max(o["close"], o["signal"]), 2, (m, o, last)))
            last = o["equity"]
    timeline.sort(key=lambda x: (x[0], x[1], x[2][0] if isinstance(x[2], tuple) else "",
                                 x[2][1]["open"] if isinstance(x[2], tuple) else 0))

    cap: Dict[str, float] = {}
    cash = 1.0
    nav_path: List[Tuple[int, float]] = [(inception, 1.0)]
    active: List[str] = []
    partition: List[List[str]] = []
    turnover_trading = turnover_rebalance = fees = slippage = funding = gross_pnl = 0.0
    trades_closed = skipped_straddle = credited = 0
    rebalances: List[Dict] = []

    def nav() -> float:
        return cash + sum(cap.values())

    def rebalance(t: int, why: str) -> None:
        nonlocal cash, turnover_rebalance, active, partition
        total = nav()
        new_active = members_at(t)
        new_part = _clusters(new_active, obs, since_at(t, new_active), t) if new_active else []
        old_w = {m: cap.get(m, 0.0) / total for m in set(cap) | set(new_active)} if total > 0 else {}
        new_cap: Dict[str, float] = {}
        if new_part and total > 0:
            per_cluster = total / len(new_part)
            for g in new_part:
                for m in g:
                    new_cap[m] = per_cluster / len(g)
        if total > 0 and cap:          # deploying cash into an empty sleeve is not a rebalance trade
            turnover_rebalance += sum(abs(new_cap.get(m, 0.0) / total - old_w.get(m, 0.0))
                                      for m in set(old_w) | set(new_cap)) / 2
        cap.clear()
        cap.update(new_cap)
        cash = total - sum(new_cap.values())
        active, partition = new_active, new_part
        rebalances.append({"at": _iso(t), "why": why, "members": len(new_active), "clusters": len(new_part)})

    for t, kind, payload in timeline:
        if t > as_of_ms:
            continue
        if kind == 0:
            if members_at(t) != active:
                rebalance(t, "membership change")
        elif kind == 1:
            if active and _clusters(active, obs, since_at(t, active), t) != partition:
                rebalance(t, "cluster partition change")
        else:
            m, o, eq_prev = payload
            if m not in cap or eq_prev <= 0:
                continue
            ep = _episode(by_cand, m, t)
            if ep is None or o["open"] < ep["effective_ms"]:
                skipped_straddle += 1        # review P2-3: a bar that opened before admission is not credited
                continue
            c0 = cap[m]
            r_net = o["equity"] / eq_prev - 1.0
            cost_frac = (o["cost"] or 0.0) / eq_prev
            fund_frac = (o["funding"] or 0.0) / eq_prev
            fee_bps = float(o["assumptions"].get("fee_bps") or 0.0)
            slip_bps = float(o["assumptions"].get("slippage_bps") or 0.0)
            share_fee = fee_bps / (fee_bps + slip_bps) if (fee_bps + slip_bps) > 0 else 0.0
            fees += c0 * cost_frac * share_fee
            slippage += c0 * cost_frac * (1 - share_fee)
            funding += c0 * fund_frac
            gross_pnl += c0 * (r_net + cost_frac + fund_frac)
            if o["action"] in ("BUY", "SELL", "SHORT", "COVER"):
                turnover_trading += c0
            elif o["action"] == "FLIP":
                turnover_trading += 2 * c0
            if o["trade"]:
                trades_closed += 1
            cap[m] = c0 * (1.0 + r_net)
            credited += 1
            nav_path.append((t, nav()))

    return _finish(base, {
        "inception_ms": inception, "nav_path": nav_path, "cap": cap, "cash": cash, "active": active,
        "partition": partition, "obs": obs, "since": since_at(as_of_ms, active), "cands": cands,
        "turnover_trading": turnover_trading, "turnover_rebalance": turnover_rebalance,
        "skipped_straddle": skipped_straddle, "credited": credited, "conn": conn,
        "fees": fees, "slippage": slippage, "funding": funding, "gross_pnl": gross_pnl,
        "trades_closed": trades_closed, "rebalances": rebalances, "by_cand": by_cand,
    })


def _base_doc(as_of_ms, now_ms, forward_start, counts, evidence_path, conn, cands, by_cand, anomalies) -> Dict:
    last_tick = conn.execute("SELECT MAX(finished_ms) FROM ticks WHERE finished_ms <= ?", (as_of_ms,)).fetchone()[0]
    stages: Dict[str, int] = defaultdict(int)
    known = [cid for cid, c in cands.items() if c["registered_at_ms"] <= as_of_ms]
    for cid in known:
        stages[_stage_at(by_cand, cid, as_of_ms) or "UNSTAGED"] += 1
    fresh_age_h = None if last_tick is None else (now_ms - last_tick) / 3_600_000
    return {
        "schema": SCHEMA, "source_id": SOURCE_ID, "source_type": SOURCE_TYPE, "capital_mode": CAPITAL_MODE,
        "evidence_class": MODE, "real_capital_usd": 0, "executes": False,
        "as_of": _iso(as_of_ms), "as_of_ms": as_of_ms,
        "research": {"strategies_registered": len(known), "stages": dict(sorted(stages.items()))},
        "freshness": (_a("NOT_MEASURED", "no engine tick recorded by this instant") if last_tick is None else
                      _m({"state": "STALE" if fresh_age_h > STALE_AFTER_H else "FRESH",
                          "last_tick": _iso(last_tick), "age_hours": _r(fresh_age_h, 3)},
                         unit=None, note=f"stale after {STALE_AFTER_H} h (engine ticks every 15 min)")),
        "anomalies": anomalies,
        "provenance": {"evidence_db": evidence_path, "forward_start_ms": forward_start,
                       "forward_start": _iso(forward_start), "as_of_ms": as_of_ms, "counts": counts,
                       "evidence_digest": _evidence_digest(conn, as_of_ms),
                       "derived_from": "spa_core/trading_research evidence.db (ADR-525) — immutable, hash-chained",
                       "never_from": "status.json (mutable derived file), backtest refreshes, forward rankings"},
        "weighting": WEIGHTING,
        "cost_components": dict(COST_COMPONENTS),
    }


def _daily(nav_path: List[Tuple[int, float]], inception: int, as_of_ms: int) -> List[float]:
    """End-of-UTC-day NAV for each COMPLETE day since inception (the inception day's start = 1.0)."""
    out, i = [], 0
    day_end = (inception // DAY_MS + 1) * DAY_MS
    last = 1.0
    while day_end <= as_of_ms:
        while i < len(nav_path) and nav_path[i][0] <= day_end:
            last = nav_path[i][1]
            i += 1
        out.append(last)
        day_end += DAY_MS
    return out


def _finish(doc: Dict, s: Optional[Dict]) -> Dict:
    eligibility_blockers = [f"cost component {k} is UNKNOWN" for k, v in COST_COMPONENTS.items() if v != "KNOWN"]
    if doc["freshness"].get("state") == "MEASURED" and doc["freshness"]["value"]["state"] == "STALE":
        eligibility_blockers.append("trading data is STALE")
    if doc["anomalies"]:
        eligibility_blockers.append(f"{len(doc['anomalies'])} evidence anomaly(ies) — see anomalies")
    if s is None:
        doc.update({k: _a("NOT_MEASURED", "no sleeve: nothing admitted") for k in (
            "net_return", "gross_return", "annualized_return", "max_drawdown", "volatility", "sharpe", "sortino",
            "turnover", "estimated_costs", "realized_costs", "exposure", "pnl")})
        doc["members"], doc["clusters"] = [], []
        doc["eligibility"] = {"state": "NOT_ELIGIBLE", "blockers": eligibility_blockers + ["no admitted members"]}
        return doc

    as_of_ms = doc["as_of_ms"]
    path = s["nav_path"]
    nav_now = path[-1][1]
    days = (as_of_ms - s["inception_ms"]) / DAY_MS
    n_obs = s["credited"]
    peak, mdd = path[0][1], 0.0
    for _, v in path:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0 if peak > 0 else 0.0)
    cost_total = s["fees"] + s["slippage"] + s["funding"]
    daily = _daily(path, s["inception_ms"], as_of_ms)
    rets = [daily[0] - 1.0] + [daily[i] / daily[i - 1] - 1.0 for i in range(1, len(daily))] if daily else []
    mature = days >= MIN_CALENDAR_DAYS_FOR_RATE
    short = f"{days:.1f} calendar days < {MIN_CALENDAR_DAYS_FOR_RATE} (ADR-590 §4: no annualised figure)"
    doc["evidence"] = {"inception": _iso(s["inception_ms"]), "calendar_days": _r(days, 3),
                       "observations_in_sleeve": n_obs,
                       "note": "calendar time and observation count are separate dimensions — "
                               "hourly bars are not days"}
    doc["nav"] = _m(_r(nav_now), unit="paper_nav_units (1.0 at inception)", n=len(path))
    doc["net_return"] = _m(_r(nav_now - 1.0), unit="fraction, cumulative since inception", n=n_obs,
                           note="net of the engine's modelled taker fees, slippage and funding")
    doc["gross_return"] = _m(_r(nav_now - 1.0 + cost_total), unit="fraction, cumulative since inception", n=n_obs,
                             note="net + modelled costs (additive approximation)")
    doc["max_drawdown"] = _m(_r(mdd), unit="fraction", n=len(path))
    if mature and len(rets) >= 2 and statistics.pstdev(rets) > 0:
        mu, sd = statistics.mean(rets), statistics.pstdev(rets)
        dn = [min(0.0, r) for r in rets]
        dsd = math.sqrt(sum(x * x for x in dn) / len(dn))
        doc["annualized_return"] = _m(_r(nav_now ** (365.0 / days) - 1.0), unit="fraction per year, compound",
                                      n=len(rets))
        doc["volatility"] = _m(_r(sd * math.sqrt(365)), unit="fraction per year", n=len(rets))
        doc["sharpe"] = _m(_r(mu / sd * math.sqrt(365), 4), unit="ratio, rf=0", n=len(rets))
        doc["sortino"] = (_m(_r(mu / dsd * math.sqrt(365), 4), unit="ratio, rf=0", n=len(rets)) if dsd > 0 else
                          _a("UNDEFINED", "no down day in the window", n=len(rets)))
    else:
        for k in ("annualized_return", "volatility", "sharpe", "sortino"):
            doc[k] = _a("NOT_ENOUGH_HISTORY", short, n=len(rets))
    doc["turnover"] = _m({"trading": _r(s["turnover_trading"]), "rebalance": _r(s["turnover_rebalance"])},
                         unit="multiples of inception NAV, cumulative", n=n_obs)
    doc["estimated_costs"] = _m({"fees": _r(s["fees"]), "slippage": _r(s["slippage"]), "funding": _r(s["funding"]),
                                 "total": _r(cost_total)}, unit="NAV units, cumulative (modelled)", n=n_obs,
                                note="maker fee, spread, latency, partial fills, capacity, perp mark/basis and "
                                     "rebalance costs are NOT modelled (see cost_components)")
    doc["realized_costs"] = _a("NOT_MEASURED", "paper only: no fill has ever been executed")
    # exposure and P&L split at as_of
    long_ = short_ = unreal = 0.0
    for m, c in s["cap"].items():
        o = [x for x in s["obs"][m] if x["close"] <= as_of_ms][-1:] or [None]
        o = o[0]
        if o is None:
            continue
        lev = float(o["assumptions"].get("leverage") or 1.0)
        if o["pos"] > 0:
            long_ += c * lev
        elif o["pos"] < 0:
            short_ += c * lev
        ent = o["book"].get("entry_eq")
        if o["pos"] != 0 and isinstance(ent, (int, float)) and o["equity"] > 0:
            unreal += c * (1.0 - ent / o["equity"])
    nv = nav_now if nav_now > 0 else 1.0
    doc["exposure"] = _m({"long": _r(long_ / nv), "short": _r(short_ / nv), "gross": _r((long_ + short_) / nv),
                          "net": _r((long_ - short_) / nv), "cash": _r(s["cash"] / nv)},
                         unit="fraction of sleeve NAV", n=len(s["cap"]))
    doc["pnl"] = _m({"realized": _r(nav_now - 1.0 - unreal), "unrealized": _r(unreal),
                     "closed_trades": s["trades_closed"]}, unit="NAV units since inception", n=n_obs)
    families: Dict[str, int] = defaultdict(int)
    members = []
    cl_index = {m: i for i, g in enumerate(s["partition"]) for m in g}
    for m in sorted(s["active"]):
        dfn = s["cands"][m]["definition"]
        families[dfn.get("family") or m.split("@")[0]] += 1
        ep = _episode(s["by_cand"], m, as_of_ms)
        members.append({"candidate_id": m, "stage": _stage_at(s["by_cand"], m, as_of_ms),
                        "admitted_at": _iso(ep["effective_ms"]) if ep else None,
                        "admission_episode": _episodes_count(s["by_cand"], m, as_of_ms),
                        "admission_policy": _admission_policy(ep, s["cands"][m]) if ep else None,
                        "observations": len(_window_rows(s["obs"], m, s["since"][m], as_of_ms)),
                        "cluster": cl_index.get(m), "weight": _r(s["cap"].get(m, 0.0) / nv),
                        "last_observation": _iso(s["obs"][m][-1]["close"]) if s["obs"][m] else None})
    doc["members"] = members
    doc["champions"] = sum(1 for x in members if x["stage"] in CHAMPION_STAGES)
    doc["clusters"] = [{"cluster": i, "members": g, "weight": _r(sum(s["cap"].get(m, 0.0) for m in g) / nv)}
                       for i, g in enumerate(s["partition"])]
    doc["concentration"] = _m({"max_cluster_weight": _r(max((c["weight"] for c in doc["clusters"]), default=0.0)),
                               "families": dict(sorted(families.items())), "assets": ["BTC"]},
                              unit=None, n=len(members))
    # diversification (review P1-1): exact duplicates are known on any length; near-duplicates only once every
    # pair of active members shares ≥ CORR_MIN_OVERLAP_DAYS days. Until then the cluster count is an UPPER
    # bound and the sleeve is not allocation-eligible — never «N independent sources» on faith.
    cst = _corr_state(sorted(s["active"]), s["obs"], s["since"], as_of_ms)
    n_cl = len(s["partition"])
    verified = len(s["active"]) <= 1 or cst["pairs_measured"] == cst["pairs_total"]
    doc["correlation_state"] = {
        "exact_duplicates": [g for g in s["partition"] if len(g) > 1],
        "independent_clusters": {"upper_bound": n_cl, "verified": verified,
                                 "display": f"{n_cl}" if verified else
                                 f"≤{n_cl}, unverified" + (f" ({cst['pairs_undefined']} pair(s) UNDEFINED)"
                                                           if cst["pairs_undefined"] else "")},
        "forward_cluster_correlation": (
            _m({"pairs": cst["pairs"], "threshold": CORR_CLUSTER_THRESHOLD}, unit="pearson on daily net returns",
               n=cst["pairs_measured"]) if verified and cst["pairs_total"] else
            _a("UNDEFINED" if cst["pairs_undefined"] and cst["pairs_measured"] + cst["pairs_undefined"]
               == cst["pairs_total"] else "NOT_ENOUGH_HISTORY",
               f"{cst['pairs_measured']} of {cst['pairs_total']} member pairs measured over "
               f"≥{CORR_MIN_OVERLAP_DAYS} shared days; {cst['pairs_undefined']} UNDEFINED (constant series)",
               n=cst["pairs_measured"])
            if not verified else _a("UNDEFINED", "a single active member has no pair")),
        "note": "exact duplicates (≥3 identical bars in a position) on any length; near-duplicates by daily "
                f"net-return correlation ≥{CORR_CLUSTER_THRESHOLD} over ≥{CORR_MIN_OVERLAP_DAYS} shared days",
    }
    doc["rebalances"] = s["rebalances"]
    # forward robustness by WEIGHT (review P2-8), not «any member»
    robust_w = sum(x["weight"] for x in members if x["stage"] in ("ROBUST",) + CHAMPION_STAGES)
    invested = sum(x["weight"] for x in members)
    share = robust_w / invested if invested > 0 else 0.0
    doc["robust_weight_share"] = _m(_r(share), unit="fraction of invested sleeve weight in ROBUST+ members",
                                    n=len(members), note=f"eligibility needs ≥{ROBUST_MIN_WEIGHT_SHARE} "
                                                         "(uncalibrated v1 parameter)")
    # overfitting control (review P2-D): the admitted set against ALL forward-observed candidates
    doc["selection_check"] = _selection_check(s["conn"], as_of_ms, [x["candidate_id"] for x in members],
                                              nav_now - 1.0)
    doc["notes"] = [
        "first UTC day is partial: inception was mid-day",
        "max drawdown mixes cadences: 4h/1h members mark every bar, 1D members only at the daily close",
        "recorded time = the engine tick's START (signal_ts_ms); the row was written up to one tick later",
        "net return excludes rebalance and membership entry/exit costs; a leaving member is marked at its last "
        "observation before the event (the bar straddling an exit is not credited — approximation)",
        f"{s['skipped_straddle']} bar(s) that opened before an admission were not credited",
    ]
    doc["net_return"]["note"] = ("net of the engine's modelled taker fees, slippage and funding; EXCLUDES rebalance "
                                 "and membership entry/exit costs (see notes)")
    if not mature:
        eligibility_blockers.append(short)
    if not verified:
        eligibility_blockers.append(f"diversification not measured: {doc['correlation_state']['forward_cluster_correlation'].get('reason')}")
    if share < ROBUST_MIN_WEIGHT_SHARE:
        eligibility_blockers.append(f"only {share:.0%} of sleeve weight sits in forward-robust (ROBUST+) members "
                                    f"(< {ROBUST_MIN_WEIGHT_SHARE:.0%})")
    doc["eligibility"] = {"state": "NOT_ELIGIBLE" if eligibility_blockers else "ELIGIBLE",
                          "blockers": eligibility_blockers,
                          "rule": "unknown costs, immaturity, unmeasured diversification, too little robust weight, "
                                  "staleness or evidence anomalies ⇒ not allocation-eligible (CAPITAL-SOURCES-01 §7)"}
    return doc


def _selection_check(conn, as_of_ms: int, admitted: List[str], sleeve_net: float) -> Dict:
    """Forward net of EVERY registered candidate (the rejected ones are observed too) vs the admitted set and the
    sleeve. A sleeve that only beats nothing but its own selection is not evidence of skill."""
    rows = conn.execute(
        "SELECT o.candidate_id, o.equity FROM observations o JOIN (SELECT candidate_id, MAX(bar_open_time) AS t "
        "FROM observations WHERE bar_close_time <= ? AND signal_ts_ms <= ? GROUP BY candidate_id) m "
        "ON o.candidate_id = m.candidate_id AND o.bar_open_time = m.t", (as_of_ms, as_of_ms)).fetchall()
    net = {cid: eq - 1.0 for cid, eq in rows}
    if not net:
        return _a("NOT_MEASURED", "no forward observation of any candidate by this instant")
    adm = [net[c] for c in admitted if c in net]
    return _m({"all_candidates_median_forward_net": _r(statistics.median(net.values())),
               "all_candidates_n": len(net),
               "share_of_all_positive": _r(sum(1 for v in net.values() if v > 0) / len(net)),
               "admitted_median_forward_net": _r(statistics.median(adm)) if adm else None,
               "sleeve_net": _r(sleeve_net)},
              unit="fraction, cumulative forward since each candidate's registration", n=len(net),
              note="diagnostic only (overfitting control) — never an admission input")


def build_from_path(path: Path, *, as_of_ms: int, now_ms: Optional[int] = None,
                    previous: Optional[Dict] = None) -> Dict:
    conn = open_readonly(path)
    try:
        return build(conn, as_of_ms=as_of_ms, now_ms=now_ms, previous=previous, evidence_path=str(path))
    finally:
        conn.close()


def dumps(doc: Dict) -> str:
    """Canonical serialisation (byte-stable): sorted keys, no NaN."""
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def main(argv=None) -> int:
    import argparse
    import time
    ap = argparse.ArgumentParser(description="Trading Alpha sleeve (read-only, derived from evidence.db)")
    ap.add_argument("--evidence", default=None, help="path to evidence.db (default: data/trading_research)")
    ap.add_argument("--as-of-ms", type=int, default=None)
    a = ap.parse_args(argv)
    path = Path(a.evidence) if a.evidence else Path(__file__).resolve().parents[2] / "data" / "trading_research" / "evidence.db"
    as_of = a.as_of_ms if a.as_of_ms is not None else int(time.time() * 1000)
    try:
        doc = build_from_path(path, as_of_ms=as_of)
    except SleeveRefused as e:
        print(json.dumps({"refused": e.code, "detail": e.detail}, ensure_ascii=False))
        return 2
    print(json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
